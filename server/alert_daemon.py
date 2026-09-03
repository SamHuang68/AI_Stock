#!/usr/bin/env python3
# ============================================================
# Stock Terminal v3.8 — Alert Daemon (後端常駐警報)
# ------------------------------------------------------------
# 不依賴瀏覽器開著。server.py 啟動時開一條背景 thread，
# 每 N 秒輪詢 alert_rules.json 的價位，跨越時推播：
#   • Telegram Bot  (推薦，免費跨平台)
#   • Email (SMTP)
# 設定存 alert_config.json (含 token，已加 .gitignore)
# 觸發紀錄存 logs/alerts/alerts_YYYY-MM.log
# ============================================================
import os, json, time, threading, urllib.request, urllib.parse, smtplib, ssl
from email.mime.text import MIMEText
from datetime import datetime

try:
    from .atomic_store import StoreCorruptError, atomic_write_json, load_json
    from .secret_store import load_secret_json, save_secret_json
except ImportError:
    from atomic_store import StoreCorruptError, atomic_write_json, load_json
    from secret_store import load_secret_json, save_secret_json

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(_BASE, 'data', 'alert_config.json')
RULES_FILE = os.path.join(_BASE, 'data', 'alert_rules.json')
SECRETS_FILE = os.path.join(_BASE, 'data', 'alert_secrets.bin')
LOG_DIR = os.path.join(_BASE, 'logs', 'alerts')
# 本機埠所有權：ST 18432、WaveDeck 18433、Private Web 18434／18435。
# 通知守護程序只以 18436 作為跨進程單例鎖，不得占用服務埠。
ALERT_DAEMON_LOCK_PORT = 18436

_DEFAULT_CONFIG = {
    'enabled': False,
    'poll_seconds': 60,
    # Canonical market-signal transitions are recorded in-app regardless of
    # this switch.  External delivery remains an explicit owner opt-in while
    # the precursor model is in prospective shadow validation.
    'market_signal_enabled': False,
    'watch_enabled': False,        # v3.8: WATCH 後端 24h 自動偵測
    'watch_poll_seconds': 300,
    'telegram': {'enabled': False, 'bot_token': '', 'chat_id': ''},
    'email': {'enabled': False, 'smtp_host': 'smtp.gmail.com', 'smtp_port': 587,
              'user': '', 'app_password': '', 'to': ''},
    'webhook': {'enabled': False, 'url': ''},   # v3.9 P5: 通用 Webhook (Discord/自架/Line替代)
}

# rule: {id, sym, market, type, price, note, enabled, _last_side}
#   type: 'cross_up' 過壓力 | 'cross_down' 破支撐
_state = {'thread': None, 'stop': False, 'last_quotes': {}, 'fired': []}
_lock = threading.Lock()


# ---- config / rules I/O -----------------------------------
def load_config():
    default = json.loads(json.dumps(_DEFAULT_CONFIG))
    try:
        c = load_json(CONFIG_FILE, default={}, expected_type=dict)
        merged = default
        merged.update(c)
        for k in ('telegram', 'email', 'webhook'):
            if isinstance(c.get(k), dict):
                merged[k] = {**_DEFAULT_CONFIG[k], **c[k]}
        # One-time migration: move legacy plaintext credentials out of JSON.
        legacy_secret = bool(
            merged.get('telegram', {}).get('bot_token') or
            merged.get('email', {}).get('app_password')
        )
        if legacy_secret:
            save_config(merged)
            merged['telegram']['bot_token'] = ''
            merged['email']['app_password'] = ''
        secrets = load_secret_json(SECRETS_FILE)
        merged['telegram']['bot_token'] = str(secrets.get('telegram_bot_token') or '')
        merged['email']['app_password'] = str(secrets.get('email_app_password') or '')
        return merged
    except (StoreCorruptError, ValueError, OSError) as exc:
        print('[alert-store] config unavailable:', type(exc).__name__)
        return default


def save_config(c):
    clean = json.loads(json.dumps(c if isinstance(c, dict) else {}))
    try:
        secrets = load_secret_json(SECRETS_FILE)
    except Exception:
        secrets = {}
    for section, field, secret_key in (
        ('telegram', 'bot_token', 'telegram_bot_token'),
        ('email', 'app_password', 'email_app_password'),
    ):
        part = clean.setdefault(section, {})
        value = part.get(field)
        if value == '***set***':
            pass
        elif value:
            secrets[secret_key] = str(value)
        else:
            secrets.pop(secret_key, None)
        part[field] = ''
    save_secret_json(SECRETS_FILE, secrets)
    # The config and its recovery copy are deliberately secret-free.
    atomic_write_json(CONFIG_FILE, clean, backup=False, private=True)
    atomic_write_json(CONFIG_FILE + '.bak', clean, backup=False, private=True)


def load_rules():
    try:
        return load_json(RULES_FILE, default=[], expected_type=list)
    except StoreCorruptError as exc:
        print('[alert-store] rules unavailable:', type(exc).__name__)
        return []


def save_rules(rules):
    atomic_write_json(RULES_FILE, rules, backup=True, private=True)


# ---- Yahoo 報價 (自足) -------------------------------------
def _yf_symbol(sym, market):
    sym = str(sym).strip()
    if market == 'US' or '.' in sym:
        return sym
    return sym + '.TW'  # 台股預設；上櫃由前端送 .TWO 亦可


def fetch_price(sym, market):
    """回傳當前有效價。美股盤後/盤前時改用延伸交易價，讓盤後突破/跌破也能觸發。"""
    yf = _yf_symbol(sym, market)
    for host in ('query1', 'query2'):
        try:
            url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yf)}?range=1d&interval=1m&includePrePost=true'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
            meta = d['chart']['result'][0]['meta']
            st = meta.get('marketState')
            if st in ('POST', 'POSTPOST') and meta.get('postMarketPrice') is not None:
                return meta.get('postMarketPrice')
            if st == 'PRE' and meta.get('preMarketPrice') is not None:
                return meta.get('preMarketPrice')
            return meta.get('regularMarketPrice')
        except Exception:
            continue
    return None


# ---- 推播 --------------------------------------------------
def push_telegram(cfg, text):
    tg = cfg.get('telegram', {})
    if not tg.get('enabled') or not tg.get('bot_token') or not tg.get('chat_id'):
        return False, 'telegram disabled/unconfigured'
    try:
        url = f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage"
        data = urllib.parse.urlencode({'chat_id': tg['chat_id'], 'text': text}).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return True, 'ok'
    except Exception as e:
        return False, str(e)


def push_email(cfg, subject, text, html=None):
    em = cfg.get('email', {})
    if not em.get('enabled') or not em.get('user') or not em.get('app_password') or not em.get('to'):
        return False, 'email disabled/unconfigured'
    try:
        if html:
            msg = MIMEText(html, 'html', 'utf-8')
        else:
            msg = MIMEText(text, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = em['user']
        msg['To'] = em['to']
        ctx = ssl.create_default_context()
        with smtplib.SMTP(em['smtp_host'], int(em['smtp_port']), timeout=15) as s:
            s.starttls(context=ctx)
            s.login(em['user'], em['app_password'])
            s.sendmail(em['user'], [em['to']], msg.as_string())
        return True, 'ok'
    except Exception as e:
        return False, str(e)


def push_webhook(cfg, text, subject='Stock Terminal 警報'):
    wh = cfg.get('webhook', {})
    if not wh.get('enabled') or not wh.get('url'):
        return False, 'webhook disabled/unconfigured'
    try:
        # 同時送 text 與 content(Discord 用 content 欄位)，相容多數接收端
        payload = json.dumps({'text': text, 'content': text, 'subject': subject}).encode('utf-8')
        req = urllib.request.Request(wh['url'], data=payload,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return True, 'ok'
    except Exception as e:
        return False, str(e)


def notify(cfg, text, subject='Stock Terminal 警報'):
    results = {}
    ok1, m1 = push_telegram(cfg, text); results['telegram'] = m1
    ok2, m2 = push_email(cfg, subject, text); results['email'] = m2
    ok3, m3 = push_webhook(cfg, text, subject); results['webhook'] = m3
    _log(text)
    return (ok1 or ok2 or ok3), results


def deliver_signal_events(events):
    """Transport canonical transition events without recomputing their score."""
    rows = [row for row in (events or []) if isinstance(row, dict)]
    if not rows:
        return {'ok': True, 'delivered': 0, 'reason': 'no_transition'}
    cfg = load_config()
    if not cfg.get('enabled') or not cfg.get('market_signal_enabled'):
        return {'ok': True, 'delivered': 0, 'reason': 'shadow_transport_disabled'}
    delivered = 0
    results = []
    for event in rows:
        state = str(event.get('toState') or '')
        if state not in ('ARMED', 'CONFIRMED', 'ACTIVE', 'CONFLICT', 'RECOVERY', 'INVALIDATED'):
            continue
        strength = event.get('strength')
        strength_text = f'{float(strength):.0f}' if strength is not None else '—'
        reasons = '；'.join((event.get('reasons') or [])[:3]) or '等待更多同向證據'
        counter = '；'.join((event.get('strongestCounterEvidence') or [])[:1]) or '無明顯反證'
        text = (
            f"【ST 前兆雷達 · {event.get('label') or event.get('signalId')}】\n"
            f"狀態 {state}｜訊號強度 {strength_text}｜獨立來源 {event.get('independentDomains') or 0}\n"
            f"支持：{reasons}\n反證：{counter}\n"
            f"失效：{event.get('invalidation') or '—'}\n"
            "Shadow observation only，不是下單或槓桿指令。"
        )
        ok, detail = notify(cfg, text, subject='Stock Terminal 市場前兆雷達')
        results.append({'eventId': event.get('eventId'), 'ok': ok, 'detail': detail})
        delivered += int(bool(ok))
    return {'ok': True, 'delivered': delivered, 'results': results}


def _log(text):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fn = os.path.join(LOG_DIR, 'alerts_' + datetime.now().strftime('%Y-%m') + '.log')
        with open(fn, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass


# ---- 複合警示：抓日線 + 指標 + 多條件 (v3.9 P5) -------------
def _fetch_daily_candles(sym, market):
    suffixes = [''] if market == 'US' else ['.TW', '.TWO']
    for suf in suffixes:
        yf = sym if market == 'US' else sym + suf
        for host in ('query1', 'query2'):
            try:
                url = (f'https://{host}.finance.yahoo.com/v8/finance/chart/'
                       f'{urllib.parse.quote(yf)}?range=1y&interval=1d')
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as r:
                    d = json.loads(r.read())
                res = d['chart']['result'][0]
                q = res['indicators']['quote'][0]
                ts = res['timestamp']
                candles = []
                for i in range(len(ts)):
                    cl = q['close'][i]
                    if cl is None:
                        continue
                    candles.append({
                        'high': q['high'][i] if q['high'][i] is not None else cl,
                        'low': q['low'][i] if q['low'][i] is not None else cl,
                        'close': cl, 'volume': q['volume'][i] or 0,
                    })
                if len(candles) >= 20:
                    return candles
            except Exception:
                continue
        if market == 'US':
            break
    return None


def _calc_ind(candles):
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    vols = [c['volume'] for c in candles]
    n = len(closes)
    def sma(p):
        return sum(closes[-p:]) / p if n >= p else None
    sma20, sma60 = sma(20), sma(60)
    g = l = 0.0
    for i in range(max(1, n - 14), n):
        dd = closes[i] - closes[i - 1]
        if dd > 0: g += dd
        else: l -= dd
    rsi = 100.0 if l == 0 else 100 - 100 / (1 + (g / 14) / (l / 14))
    bbL = bbU = None
    if sma20 is not None and n >= 20:
        var = sum((x - sma20) ** 2 for x in closes[-20:]) / 20
        sd = var ** 0.5
        bbL, bbU = sma20 - 2 * sd, sma20 + 2 * sd
    v5 = sum(vols[-5:]) / 5 if n >= 5 else 0
    v20 = sum(vols[-20:]) / 20 if n >= 20 else 0
    return {
        'close': closes[-1], 'sma20': sma20, 'sma60': sma60, 'rsi14': rsi,
        'bbL': bbL, 'bbU': bbU, 'volRatio': (v5 / v20 if v20 > 0 else 0),
        'high20': max(highs[-21:-1]) if n >= 21 else None,
    }


def _eval_composite(rule, ind):
    """評估 rule['conditions'] (AND/OR)。回 (satisfied, detail)。
       條件 {left, op, right}：left=指標名；right=數值或指標名；op=gt/lt/gte/lte。"""
    conds = rule.get('conditions') or []
    if not conds:
        return False, ''
    combine = (rule.get('combine') or 'AND').upper()
    def val(x):
        if x in ind:
            return ind[x]
        try:
            return float(x)
        except Exception:
            return None
    results, details = [], []
    LBL = {'close': '收盤', 'sma20': 'SMA20', 'sma60': 'SMA60', 'rsi14': 'RSI', 'bbL': '布林下軌', 'bbU': '布林上軌', 'volRatio': '量比', 'high20': '20日高'}
    for c in conds:
        a = val(c.get('left')); b = val(c.get('right'))
        if a is None or b is None:
            results.append(False); continue
        op = c.get('op', 'gt')
        ok = (a > b if op == 'gt' else a < b if op == 'lt'
              else a >= b if op == 'gte' else a <= b if op == 'lte' else False)
        results.append(ok)
        opsym = {'gt': '>', 'lt': '<', 'gte': '≥', 'lte': '≤'}.get(op, op)
        rname = LBL.get(c.get('right'), c.get('right'))
        details.append(f"{LBL.get(c.get('left'), c.get('left'))}({a:.2f}){opsym}{rname}")
    satisfied = all(results) if combine == 'AND' else any(results)
    return satisfied, ('；'.join(details))


def _check_composite(r, cfg):
    """評估單一複合規則，回傳是否需存檔(_last_fired 變動)。"""
    candles = _fetch_daily_candles(r.get('sym'), r.get('market', 'TW'))
    if not candles:
        return False
    ind = _calc_ind(candles)
    satisfied, detail = _eval_composite(r, ind)
    prev = r.get('_last_fired')
    r['_last_fired'] = satisfied
    if satisfied and not prev:
        now = time.time()
        # 5 分鐘 (300 秒) 冷卻防範震盪重複推播
        if now - r.get('_last_fired_time', 0) < 300:
            return True
        r['_last_fired_time'] = now
        combine = (r.get('combine') or 'AND').upper()
        text = f"🎯 {r.get('sym')} 複合警示成立（{combine}）：{detail}　{r.get('note', '')}".strip()
        notify(cfg, text)
        _state['fired'].append({'t': now, 'text': text})
        _state['fired'] = _state['fired'][-100:]
    return True


# ---- 核心檢查 ----------------------------------------------
def _check_once():
    cfg = load_config()
    if not cfg.get('enabled'):
        return
    rules = load_rules()
    changed = False
    for r in rules:
        if not r.get('enabled', True):
            continue
        if r.get('type') == 'composite':
            try:
                if _check_composite(r, cfg):
                    changed = True
            except Exception as e:
                _log('composite check error: ' + str(e))
            continue
        price = fetch_price(r.get('sym'), r.get('market', 'TW'))
        if price is None:
            continue
        with _lock:
            _state['last_quotes'][r.get('sym')] = price
        target = float(r.get('price', 0))
        typ = r.get('type', 'cross_up')
        prev = r.get('_last_side')
        if prev is None:
            # 第一次初始化，不觸發
            side = 'above' if price >= target else 'below'
            r['_last_side'] = side
            changed = True
            continue
            
        # 遲滯門檻 (Hysteresis Band = 1.0%)：過濾臨界點微幅抖動。
        # 只有在價格顯著向相反方向回退 1% 時，才允許重置狀態供下一次觸發。
        hysteresis = 0.01
        if prev == 'above':
            if typ == 'cross_up':
                # 只有當價格跌回低於壓力位 1% (即限額線) 時，才允許重置為 below 供下次觸發突破
                side = 'below' if price < target * (1.0 - hysteresis) else 'above'
            else:
                side = 'below' if price < target else 'above'
        else: # prev == 'below'
            if typ == 'cross_down':
                # 只有當價格漲回高於支撐位 1% 時，才允許重置為 above 供下次觸發跌破
                side = 'above' if price > target * (1.0 + hysteresis) else 'below'
            else:
                side = 'above' if price >= target else 'below'

        if side != prev:
            r['_last_side'] = side
            changed = True
            
        crossed = (typ == 'cross_up' and prev == 'below' and side == 'above') or \
                  (typ == 'cross_down' and prev == 'above' and side == 'below')
        if crossed:
            now = time.time()
            # 5 分鐘 (300 秒) 冷卻防範在價格突破線來回震盪時的警報轟炸
            if now - r.get('_last_fired_time', 0) < 300:
                continue
            r['_last_fired_time'] = now
            arrow = '突破↑ 過壓力' if typ == 'cross_up' else '跌破↓ 破支撐'
            text = f"⚠️ {r.get('sym')} {arrow} {target} (現價 {price})  {r.get('note', '')}".strip()
            notify(cfg, text)
            _state['fired'].append({'t': now, 'text': text})
            _state['fired'] = _state['fired'][-100:]
    if changed:
        save_rules(rules)


def _loop():
    while not _state['stop']:
        try:
            _check_once()
        except Exception as e:
            _log('daemon error: ' + str(e))
        cfg = load_config()
        time.sleep(max(15, int(cfg.get('poll_seconds', 60))))


_lock_socket = None

def start():
    global _lock_socket
    if _state['thread'] and _state['thread'].is_alive():
        return
    # 使用專屬埠作為進程單例鎖，防止背景殘存重複實例發信。
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', ALERT_DAEMON_LOCK_PORT))
        s.listen(1)
        _lock_socket = s
    except OSError:
        _log(f"[alert] 告警背景服務已在連接埠 {ALERT_DAEMON_LOCK_PORT} 執行，略過重複啟動。")
        return

    _state['stop'] = False
    t = threading.Thread(target=_loop, daemon=True, name='alert-daemon')
    t.start()
    _state['thread'] = t


def status():
    cfg = load_config()
    return {
        'enabled': cfg.get('enabled', False),
        'poll_seconds': cfg.get('poll_seconds', 60),
        'telegram_on': cfg.get('telegram', {}).get('enabled', False),
        'email_on': cfg.get('email', {}).get('enabled', False),
        'rules_count': len(load_rules()),
        'recent_fired': _state['fired'][-20:],
        'last_quotes': _state['last_quotes'],
        'running': bool(_state['thread'] and _state['thread'].is_alive()),
    }


if __name__ == '__main__':
    print('alert_daemon standalone test — one check pass')
    _check_once()
    print(json.dumps(status(), ensure_ascii=False, indent=2))

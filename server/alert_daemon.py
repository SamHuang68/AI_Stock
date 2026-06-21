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

_BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_BASE, 'alert_config.json')
RULES_FILE = os.path.join(_BASE, 'alert_rules.json')
LOG_DIR = os.path.join(_BASE, 'logs', 'alerts')

_DEFAULT_CONFIG = {
    'enabled': False,
    'poll_seconds': 60,
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
    try:
        with open(CONFIG_FILE, encoding='utf-8') as f:
            c = json.load(f)
        merged = json.loads(json.dumps(_DEFAULT_CONFIG))
        merged.update(c)
        for k in ('telegram', 'email', 'webhook'):
            if isinstance(c.get(k), dict):
                merged[k] = {**_DEFAULT_CONFIG[k], **c[k]}
        return merged
    except Exception:
        return json.loads(json.dumps(_DEFAULT_CONFIG))


def save_config(c):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


def load_rules():
    try:
        with open(RULES_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_rules(rules):
    with open(RULES_FILE, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)


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
        combine = (r.get('combine') or 'AND').upper()
        text = f"🎯 {r.get('sym')} 複合警示成立（{combine}）：{detail}　{r.get('note', '')}".strip()
        notify(cfg, text)
        _state['fired'].append({'t': time.time(), 'text': text})
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
        side = 'above' if price >= target else 'below'
        prev = r.get('_last_side')
        r['_last_side'] = side
        changed = True
        if prev is None:
            continue  # 第一次只記錄基準，不觸發
        crossed = (typ == 'cross_up' and prev == 'below' and side == 'above') or \
                  (typ == 'cross_down' and prev == 'above' and side == 'below')
        if crossed:
            arrow = '突破↑ 過壓力' if typ == 'cross_up' else '跌破↓ 破支撐'
            text = f"⚠️ {r.get('sym')} {arrow} {target} (現價 {price})  {r.get('note', '')}".strip()
            notify(cfg, text)
            _state['fired'].append({'t': time.time(), 'text': text})
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


def start():
    if _state['thread'] and _state['thread'].is_alive():
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

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
import copy
import hashlib
import uuid
from email.mime.text import MIMEText
from datetime import datetime

try:
    from .atomic_store import StoreCorruptError, atomic_write_json, load_json
    from .secret_store import load_secret_json, save_secret_json
    from .indicators import dated_candle_snapshot
except ImportError:
    from atomic_store import StoreCorruptError, atomic_write_json, load_json
    from secret_store import load_secret_json, save_secret_json
    from indicators import dated_candle_snapshot

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(_BASE, 'data', 'alert_config.json')
RULES_FILE = os.path.join(_BASE, 'data', 'alert_rules.json')
SECRETS_FILE = os.path.join(_BASE, 'data', 'alert_secrets.bin')
LOG_DIR = os.path.join(_BASE, 'logs', 'alerts')
# 送達待送匣：全部已設定通道都失敗的推播在此保留並重試（審查 AL-01）。
OUTBOX_FILE = os.path.join(_BASE, 'data', 'alert_outbox.json')
OUTBOX_MAX_ATTEMPTS = 5
OUTBOX_MAX_AGE_SECONDS = 3600
OUTBOX_RETRY_GAP_SECONDS = 60
OUTBOX_MAX_ITEMS = 50
_UNCONFIGURED = 'disabled/unconfigured'
_outbox_lock = threading.Lock()
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
_state = {'thread': None, 'stop': False, 'last_quotes': {}, 'fired': [], 'deliveries': []}
_lock = threading.Lock()
_config_lock = threading.RLock()
_rules_lock = threading.RLock()


class RulesConflictError(ValueError):
    """使用者規則已變更，拒絕用舊快照覆寫。"""


# ---- config / rules I/O -----------------------------------
def load_config(*, strict=False):
    with _config_lock:
        return _load_config_locked(strict=strict)


def _load_config_locked(*, strict=False):
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
        if strict:
            raise
        return default


def save_config(c):
    with _config_lock:
        _save_config_locked(c)


def _save_config_locked(c):
    if not isinstance(c, dict):
        raise ValueError('警報設定必須是物件。')
    clean = copy.deepcopy(c)
    # 讀取失敗必須中止；無法解密不等於沒有金鑰。
    secret_changes = any(
        isinstance(clean.get(section), dict)
        and field in clean[section] and clean[section][field] != '***set***'
        for section, field in (('telegram', 'bot_token'), ('email', 'app_password'))
    )
    secrets = None
    if secret_changes:
        secrets = load_secret_json(SECRETS_FILE)
    original_secrets = copy.deepcopy(secrets)
    for section, field, secret_key in (
        ('telegram', 'bot_token', 'telegram_bot_token'),
        ('email', 'app_password', 'email_app_password'),
    ):
        part = clean.setdefault(section, {})
        if not isinstance(part, dict):
            raise ValueError('警報通道設定必須是物件。')
        value = part.get(field)
        # 缺少欄位及遮罩保留原值；只有明確空字串才清除。
        if field in part and value != '***set***':
            if value is None:
                raise ValueError('清除金鑰請明確提供空字串。')
            if value:
                secrets[secret_key] = str(value)
            else:
                secrets.pop(secret_key, None)
        part[field] = ''
    if secrets != original_secrets:
        save_secret_json(SECRETS_FILE, secrets)
    # The config and its recovery copy are deliberately secret-free.
    atomic_write_json(CONFIG_FILE, clean, backup=False, private=True)
    atomic_write_json(CONFIG_FILE + '.bak', clean, backup=False, private=True)


def update_config(incoming):
    """在同一交易內合併局部設定，不讓讀取失敗變成清除。"""
    if not isinstance(incoming, dict):
        raise ValueError('警報設定必須是物件。')
    with _config_lock:
        current = load_config(strict=True)
        for key, value in incoming.items():
            if key in ('telegram', 'email', 'webhook'):
                if not isinstance(value, dict):
                    raise ValueError('警報通道設定必須是物件。')
                current[key].update({k: v for k, v in value.items() if v != '***set***'})
            else:
                current[key] = value
        # 沒有修改金鑰的操作不重寫金鑰檔，也不翻動其復原副本。
        persisted = copy.deepcopy(current)
        for section, field in (('telegram', 'bot_token'), ('email', 'app_password')):
            supplied = incoming.get(section, {})
            if field not in supplied or supplied[field] == '***set***':
                persisted[section][field] = '***set***'
        _save_config_locked(persisted)
        return current


def load_rules(*, strict=False):
    try:
        with _rules_lock:
            rules = load_json(RULES_FILE, default=[], expected_type=list)
            if any(not isinstance(rule, dict) for rule in rules):
                raise StoreCorruptError('警報規則含非物件項目；保留原檔並拒絕覆寫。')
            return rules
    except StoreCorruptError as exc:
        print('[alert-store] rules unavailable:', type(exc).__name__)
        if strict:
            raise
        return []


def _rule_settings(rule):
    return {key: value for key, value in rule.items() if not key.startswith('_last_')}


def rules_revision(rules):
    settings = [_rule_settings(rule) for rule in rules]
    raw = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return '"' + hashlib.sha256(raw.encode('utf-8')).hexdigest() + '"'


def rules_snapshot():
    with _rules_lock:
        rules = load_rules(strict=True)
        return rules, rules_revision(rules)


def save_rules(rules, *, expected_revision=None):
    if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
        raise ValueError('警報規則必須是物件陣列。')
    with _rules_lock:
        current = load_rules(strict=True)
        if expected_revision is not None and expected_revision != rules_revision(current):
            raise RulesConflictError('警報規則已被更新，請重新讀取後再保存。')
        # 相同規則保留最新評估狀態，避免前端的舊狀態回捲冷卻時間。
        latest = {json.dumps(_rule_settings(r), sort_keys=True, ensure_ascii=False): r for r in current}
        merged = copy.deepcopy(rules)
        for rule in merged:
            old = latest.get(json.dumps(_rule_settings(rule), sort_keys=True, ensure_ascii=False))
            if old is not None:
                for key in tuple(rule):
                    if key.startswith('_last_'):
                        rule.pop(key)
                rule.update({key: value for key, value in old.items() if key.startswith('_last_')})
        atomic_write_json(RULES_FILE, merged, backup=True, private=True)
        return rules_revision(merged)


def _merge_rule_state(before, evaluated):
    """網路評估結束後，只合併仍存在且內容未變的規則狀態。"""
    with _rules_lock:
        current = load_rules(strict=True)
        changed = False
        for old, result in zip(before, evaluated):
            if old == result:
                continue
            for rule in current:
                if rule == old:
                    rule.update({key: value for key, value in result.items() if key.startswith('_last_')})
                    changed = True
                    break
        if changed:
            atomic_write_json(RULES_FILE, current, backup=True, private=True)


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


def _redact(cfg, value):
    """失敗原因寫入日誌前移除權杖、密碼與 webhook 網址。"""
    text = str(value)
    for secret in ((cfg.get('telegram') or {}).get('bot_token'),
                   (cfg.get('email') or {}).get('app_password'),
                   (cfg.get('webhook') or {}).get('url')):
        if secret:
            text = text.replace(str(secret), '***')
    return text[:300]


def _failures(cfg, results):
    """已設定且失敗的通道；未設定的通道不算送達失敗。"""
    return {name: _redact(cfg, detail) for name, detail in (results or {}).items()
            if detail != 'ok' and _UNCONFIGURED not in str(detail)}


def _note_delivery(entry):
    with _lock:
        _state['deliveries'].append(entry)
        _state['deliveries'] = _state['deliveries'][-50:]


def _outbox_load():
    items = load_json(OUTBOX_FILE, default=[], expected_type=list)
    return [item for item in items if isinstance(item, dict) and item.get('id') and item.get('text')]


def deliver(cfg, text, subject='Stock Terminal 警報', *, source='alert', now=None):
    """送出推播並回傳送達狀態：sent／queued／no_channel。

    舊版各路徑直接呼叫 notify 並忽略結果，全部通道失敗時警報仍記為已觸發、不重送（審查 AL-01）。
    """
    now = time.time() if now is None else now
    ok, results = notify(cfg, text, subject)
    failed = _failures(cfg, results)
    delivery_id = uuid.uuid4().hex
    if failed:
        _log(f'送出失敗（{source}，第 1 次）：' + '；'.join(f'{k}={v}' for k, v in failed.items()))
    if ok:
        status = 'sent'
    elif not failed:
        status = 'no_channel'
    else:
        status = 'queued'
        with _outbox_lock:
            items = _outbox_load()
            items.append({'id': delivery_id, 'source': source, 'subject': subject, 'text': text,
                          'createdAt': now, 'attempts': 1, 'nextAt': now + OUTBOX_RETRY_GAP_SECONDS,
                          'lastError': failed})
            for item in items[:-OUTBOX_MAX_ITEMS]:
                _log(f"待送匣已滿，放棄最舊一筆（{item.get('source')}）：{item.get('text')}")
            atomic_write_json(OUTBOX_FILE, items[-OUTBOX_MAX_ITEMS:], private=True)
    _note_delivery({'t': now, 'id': delivery_id, 'source': source, 'status': status, 'attempts': 1,
                    'failed': failed})
    return {'status': status, 'id': delivery_id}


def retry_outbox(cfg=None, now=None):
    """重送待送匣；本輪只要有一筆仍全部失敗就停止，避免網路中斷時逐筆等候逾時。"""
    now = time.time() if now is None else now
    out = {'sent': 0, 'pending': 0, 'dropped': 0}
    with _outbox_lock:
        items = _outbox_load()
        if not items:
            return out
        cfg = cfg if cfg is not None else load_config()
        keep, stalled = [], False
        for item in items:
            if now - float(item.get('createdAt') or 0) > OUTBOX_MAX_AGE_SECONDS:
                _log(f"放棄送出（{item.get('source')}，逾 {OUTBOX_MAX_AGE_SECONDS // 60} 分鐘未送達）：{item['text']}")
                _note_delivery({'t': now, 'id': item['id'], 'source': item.get('source'), 'status': 'failed',
                                'attempts': item.get('attempts'), 'failed': item.get('lastError') or {}})
                out['dropped'] += 1
                continue
            if stalled or now < float(item.get('nextAt') or 0):
                keep.append(item)
                continue
            ok, results = notify(cfg, item['text'], item.get('subject') or 'Stock Terminal 警報')
            item['attempts'] = int(item.get('attempts') or 0) + 1
            failed = _failures(cfg, results)
            if ok or not failed:
                _note_delivery({'t': now, 'id': item['id'], 'source': item.get('source'),
                                'status': 'sent' if ok else 'no_channel', 'attempts': item['attempts'],
                                'failed': failed})
                out['sent'] += int(ok)
                continue
            _log(f"送出失敗（{item.get('source')}，第 {item['attempts']} 次）："
                 + '；'.join(f'{k}={v}' for k, v in failed.items()))
            if item['attempts'] >= OUTBOX_MAX_ATTEMPTS:
                _log(f"放棄送出（{item.get('source')}，已試 {item['attempts']} 次）：{item['text']}")
                _note_delivery({'t': now, 'id': item['id'], 'source': item.get('source'), 'status': 'failed',
                                'attempts': item['attempts'], 'failed': failed})
                out['dropped'] += 1
                continue
            item.update(nextAt=now + OUTBOX_RETRY_GAP_SECONDS, lastError=failed)
            keep.append(item)
            stalled = True
        atomic_write_json(OUTBOX_FILE, keep, private=True)
        out['pending'] = len(keep)
    return out


def outbox_pending():
    with _outbox_lock:
        return len(_outbox_load())


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
def _fetch_daily_candles(code, market):
    from stock_signals_routes import load_alert_bars
    loaded = load_alert_bars(code, market, _fetch_daily_candles_remote)
    _state.setdefault('daily_sources', {})[f'{market}:{code}'] = {
        key: value for key, value in loaded.items() if key != 'bars'}
    if loaded.get('error'):
        from log_once import log_once
        log_once(f'警報日線-{market}-{code}', loaded['error'])
    return loaded['bars'] or None


def _fetch_daily_candles_remote(sym, market):
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
                    candles.append({'time': ts[i], **{
                        key: (q.get(key) or [])[i] if i < len(q.get(key) or []) else None
                        for key in ('open', 'high', 'low', 'close', 'volume')}})
                if len(candles) >= 20:
                    return candles
            except Exception:
                continue
        if market == 'US':
            break
    return None


def _calc_ind(candles, market='TW', symbol=''):
    """複合警示指標：一律走 indicators.dated_candle_snapshot（Wilder RSI、母體σ布林），
    與畫面 pro_v2 同口徑；不得在 daemon 內自寫近似版 RSI。"""
    snap = dated_candle_snapshot(candles, market, symbol)
    return {k: snap.get(k) for k in
            ('close', 'sma20', 'sma60', 'rsi14', 'bbL', 'bbU', 'volRatio', 'high20')}


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
            results.append(None); continue
        op = c.get('op', 'gt')
        ok = (a > b if op == 'gt' else a < b if op == 'lt'
              else a >= b if op == 'gte' else a <= b if op == 'lte' else False)
        results.append(ok)
        opsym = {'gt': '>', 'lt': '<', 'gte': '≥', 'lte': '≤'}.get(op, op)
        rname = LBL.get(c.get('right'), c.get('right'))
        details.append(f"{LBL.get(c.get('left'), c.get('left'))}({a:.2f}){opsym}{rname}")
    if combine == 'AND':
        satisfied = False if False in results else (None if None in results else True)
    else:
        satisfied = True if True in results else (None if None in results else False)
    return satisfied, ('；'.join(details))


def _check_composite(r, cfg):
    """評估單一複合規則，回傳是否需存檔(_last_fired 變動)。"""
    candles = _fetch_daily_candles(r.get('sym'), r.get('market', 'TW'))
    if not candles:
        return False
    ind = _calc_ind(candles, r.get('market', 'TW'), r.get('sym', ''))
    satisfied, detail = _eval_composite(r, ind)
    # 三值邏輯：已知假可解除 AND，只有整體未知才保留舊狀態。
    if satisfied is None:
        return False
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
        sent = deliver(cfg, text, source='composite', now=now)
        _state['fired'].append({'t': now, 'text': text, 'delivery': sent['status'], 'deliveryId': sent['id']})
        _state['fired'] = _state['fired'][-100:]
    return True


# ---- 核心檢查 ----------------------------------------------
def _check_once():
    cfg = load_config()
    if not cfg.get('enabled'):
        return
    rules = load_rules(strict=True)
    original_rules = copy.deepcopy(rules)
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
            sent = deliver(cfg, text, source='price', now=now)
            _state['fired'].append({'t': now, 'text': text, 'delivery': sent['status'], 'deliveryId': sent['id']})
            _state['fired'] = _state['fired'][-100:]
    if changed:
        _merge_rule_state(original_rules, rules)


def _loop():
    while not _state['stop']:
        try:
            retry_outbox()
        except Exception as e:
            _log('outbox retry error: ' + str(e))
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
        'recent_deliveries': _state['deliveries'][-20:],
        'pending_deliveries': outbox_pending(),
        'last_quotes': _state['last_quotes'],
        'running': bool(_state['thread'] and _state['thread'].is_alive()),
        'daily_sources': _state.get('daily_sources', {}),
    }


if __name__ == '__main__':
    print('alert_daemon standalone test — one check pass')
    _check_once()
    print(json.dumps(status(), ensure_ascii=False, indent=2))

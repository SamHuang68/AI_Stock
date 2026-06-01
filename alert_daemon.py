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
    'telegram': {'enabled': False, 'bot_token': '', 'chat_id': ''},
    'email': {'enabled': False, 'smtp_host': 'smtp.gmail.com', 'smtp_port': 587,
              'user': '', 'app_password': '', 'to': ''},
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
        for k in ('telegram', 'email'):
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
    yf = _yf_symbol(sym, market)
    for host in ('query1', 'query2'):
        try:
            url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yf)}?range=1d&interval=1m'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
            meta = d['chart']['result'][0]['meta']
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


def push_email(cfg, subject, text):
    em = cfg.get('email', {})
    if not em.get('enabled') or not em.get('user') or not em.get('app_password') or not em.get('to'):
        return False, 'email disabled/unconfigured'
    try:
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


def notify(cfg, text, subject='Stock Terminal 警報'):
    results = {}
    ok1, m1 = push_telegram(cfg, text); results['telegram'] = m1
    ok2, m2 = push_email(cfg, subject, text); results['email'] = m2
    _log(text)
    return (ok1 or ok2), results


def _log(text):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fn = os.path.join(LOG_DIR, 'alerts_' + datetime.now().strftime('%Y-%m') + '.log')
        with open(fn, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass


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

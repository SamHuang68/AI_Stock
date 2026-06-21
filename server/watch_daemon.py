#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# Stock Terminal v3.8 — WATCH 後端 24h 自動偵測
# ------------------------------------------------------------
# 把前端 WATCH 的 8 個策略移植到 Python，背景常駐：
#   每 N 秒抓各觀察股日線 → 算指標 → 評估訊號 →
#   新觸發(trigger/broken)用 alert_daemon 已設定的 Telegram/Email 推播。
# 瀏覽器關著也會偵測。
#   watch_rules.json  : 前端同步的觀察清單 {code:{mkt,signals:[{id,strategy,params}]}}
#   watch_state.json  : 去重狀態 {code:sigId: status}
#   設定沿用 alert_config.json：watch_enabled / watch_poll_seconds
# ============================================================
import os, json, time, threading, urllib.request, urllib.parse
from datetime import datetime

try:
    import alert_daemon
except Exception as e:
    alert_daemon = None
    print('[watch] alert_daemon import failed:', e)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_FILE = os.path.join(_BASE, 'data', 'watch_rules.json')
STATE_FILE = os.path.join(_BASE, 'data', 'watch_state.json')
LOG_DIR = os.path.join(_BASE, 'logs', 'watch')
_state = {'thread': None, 'stop': False, 'last_run': None, 'fired': []}


# ---- I/O ---------------------------------------------------
def load_rules():
    try:
        with open(RULES_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_rules(d):
    with open(RULES_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def _load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_state(s):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False)
    except Exception:
        pass

def _log(text):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fn = os.path.join(LOG_DIR, 'watch_' + datetime.now().strftime('%Y-%m') + '.log')
        with open(fn, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass


# ---- 抓日線 ------------------------------------------------
def _fetch_daily(code, mkt):
    suffixes = ([''] if mkt == 'US' else ['.TW', '.TWO'])
    for suf in suffixes:
        yf = code + suf if suf or mkt != 'US' else code
        if mkt == 'US':
            yf = code
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
                        'close': cl,
                        'volume': q['volume'][i] or 0,
                    })
                if len(candles) >= 20:
                    return candles
            except Exception:
                continue
        if mkt == 'US':
            break
    return None


# ---- 指標 --------------------------------------------------
def _ind(candles):
    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    vols = [c['volume'] for c in candles]
    n = len(closes)

    def sma(p):
        return sum(closes[-p:]) / p if n >= p else None

    sma20 = sma(20); sma60 = sma(60)
    # RSI 14
    g = l = 0.0
    for i in range(n - 14, n):
        if i < 1:
            continue
        dd = closes[i] - closes[i - 1]
        if dd > 0: g += dd
        else: l -= dd
    rsi = 100.0 if l == 0 else 100 - 100 / (1 + (g / 14) / (l / 14))
    # BB lower = sma20 - 2*std20
    bbL = None
    if sma20 is not None and n >= 20:
        m = sma20
        var = sum((x - m) ** 2 for x in closes[-20:]) / 20
        bbL = m - 2 * (var ** 0.5)
    v5 = sum(vols[-5:]) / 5 if n >= 5 else 0
    v20 = sum(vols[-20:]) / 20 if n >= 20 else 0
    volRatio = v5 / v20 if v20 > 0 else 0
    return {'close': closes[-1], 'sma20': sma20, 'sma60': sma60, 'rsi14': rsi,
            'bbL': bbL, 'volRatio': volRatio, 'highs': highs}


# ---- 策略評估（對齊 watch_v2 STRATEGIES.check）-------------
def _eval(strategy, ind, params):
    p = params or {}
    c = ind['close']
    if strategy == 'sma60_pullback':
        s = ind['sma60']
        if s is None: return ('none', '')
        tol = (p.get('tolerance', 1.5)) / 100
        lo, hi = s * (1 - tol), s * (1 + tol)
        if lo <= c <= hi: return ('trigger', f'進入容差區 {lo:.2f}~{hi:.2f}')
        if c < lo: return ('broken', f'跌破容差下緣 {lo:.2f}')
        return ('wait', '')
    if strategy == 'sma20_pullback':
        s = ind['sma20']
        if s is None: return ('none', '')
        tol = (p.get('tolerance', 1.0)) / 100
        lo, hi = s * (1 - tol), s * (1 + tol)
        if lo <= c <= hi: return ('trigger', f'進入容差區 {lo:.2f}~{hi:.2f}')
        if c < lo: return ('broken', f'跌破容差下緣 {lo:.2f}')
        return ('wait', '')
    if strategy == 'breakout_n_high':
        days = int(p.get('days', 20)); vm = p.get('volMult', 1.5)
        highs = ind['highs']
        if len(highs) < days + 1: return ('none', '')
        mx = max(highs[-(days + 1):-1])
        if c > mx and ind['volRatio'] >= vm:
            return ('trigger', f'突破 {days} 日新高 {mx:.2f} + 量 {ind["volRatio"]:.1f}x')
        return ('wait', '')
    if strategy == 'rsi_oversold_bounce':
        r = ind['rsi14']
        if 30 <= r <= 38: return ('trigger', f'RSI {r:.1f} 反彈區')
        return ('wait', '')
    if strategy == 'bb_lower_touch':
        b = ind['bbL']
        if b is None: return ('none', '')
        if c <= b: return ('trigger', f'觸布林下軌 {b:.2f}')
        return ('wait', '')
    if strategy == 'rsi_overheat':
        thr = p.get('threshold', 75)
        if ind['rsi14'] >= thr: return ('trigger', f'RSI {ind["rsi14"]:.1f} ≥ {thr} 過熱')
        return ('wait', '')
    if strategy == 'custom_buy':
        t = p.get('target')
        if t and c <= float(t): return ('trigger', f'已達買進價 {float(t):.2f}')
        return ('wait', '')
    if strategy == 'custom_sell':
        t = p.get('target')
        if t and c >= float(t): return ('trigger', f'已達賣出價 {float(t):.2f}')
        return ('wait', '')
    return ('none', '')


_STRAT_LBL = {
    'sma60_pullback': '回測60日均線', 'sma20_pullback': '回測20日均線',
    'breakout_n_high': '突破N日新高', 'rsi_oversold_bounce': 'RSI超賣反彈',
    'bb_lower_touch': '布林下軌承接', 'rsi_overheat': 'RSI過熱', 'custom_buy': '自訂買進', 'custom_sell': '自訂賣出',
}


def check_once():
    cfg = alert_daemon.load_config() if alert_daemon else {}
    if not cfg.get('watch_enabled'):
        return
    rules = load_rules()
    if not rules:
        return
    state = _load_state()
    fired = 0
    for code, w in rules.items():
        mkt = (w or {}).get('mkt', 'TW')
        sigs = (w or {}).get('signals', []) or []
        if not sigs:
            continue
        candles = _fetch_daily(code, mkt)
        if not candles:
            continue
        ind = _ind(candles)
        for sig in sigs:
            status, detail = _eval(sig.get('strategy'), ind, sig.get('params'))
            key = f"{code}:{sig.get('id')}"
            prev = state.get(key)
            if status in ('trigger', 'broken') and prev != status:
                icon = '🎯' if status == 'trigger' else '⚠️'
                lbl = _STRAT_LBL.get(sig.get('strategy'), sig.get('strategy'))
                text = f"{icon} {code} — {lbl}：{detail}（現價 {ind['close']:.2f}）"
                if alert_daemon:
                    alert_daemon.notify(cfg, text, subject=f'WATCH 訊號 {code}')
                _log(text)
                _state['fired'].append({'t': time.time(), 'text': text})
                _state['fired'] = _state['fired'][-100:]
                state[key] = status
                fired += 1
            elif status not in ('trigger', 'broken') and prev:
                del state[key]
    _save_state(state)
    _state['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if fired:
        _log(f'check_once fired {fired}')


def _loop():
    while not _state['stop']:
        try:
            check_once()
        except Exception as e:
            _log('daemon error: ' + str(e))
        cfg = alert_daemon.load_config() if alert_daemon else {}
        time.sleep(max(60, int(cfg.get('watch_poll_seconds', 300))))


def start():
    if _state['thread'] and _state['thread'].is_alive():
        return
    _state['stop'] = False
    t = threading.Thread(target=_loop, daemon=True, name='watch-daemon')
    t.start()
    _state['thread'] = t


def status():
    cfg = alert_daemon.load_config() if alert_daemon else {}
    return {
        'enabled': cfg.get('watch_enabled', False),
        'poll_seconds': cfg.get('watch_poll_seconds', 300),
        'rules_count': len(load_rules()),
        'last_run': _state['last_run'],
        'recent_fired': _state['fired'][-20:],
        'running': bool(_state['thread'] and _state['thread'].is_alive()),
    }


if __name__ == '__main__':
    print('watch_daemon one-shot check')
    check_once()
    print(json.dumps(status(), ensure_ascii=False, indent=2))

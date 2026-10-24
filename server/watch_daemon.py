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

from daemon_lock import acquire_daemon_lock
try:
    from .atomic_store import StoreCorruptError, atomic_write_json, load_json
    from .indicators import dated_candle_snapshot
except ImportError:
    from atomic_store import StoreCorruptError, atomic_write_json, load_json
    from indicators import dated_candle_snapshot

try:
    import alert_daemon
except Exception as e:
    alert_daemon = None
    print('[watch] alert_daemon import failed:', e)

import data_paths
from runtime_storage import assert_write_allowed

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_FILE = str(data_paths.data_path('watch_rules.json', code_root=_BASE))
STATE_FILE = str(data_paths.data_path('watch_state.json', code_root=_BASE))
LOG_DIR = str(data_paths.log_path('watch', code_root=_BASE))
_state = {'thread': None, 'stop': False, 'last_run': None, 'fired': []}


# ---- I/O ---------------------------------------------------
def load_rules():
    try:
        return load_json(RULES_FILE, default={}, expected_type=dict)
    except StoreCorruptError as exc:
        print('[watch-store] rules unavailable:', type(exc).__name__)
        return {}

def save_rules(d):
    atomic_write_json(RULES_FILE, d, backup=True, private=True)

def _load_state():
    try:
        return load_json(STATE_FILE, default={}, expected_type=dict)
    except StoreCorruptError as exc:
        print('[watch-store] state unavailable:', type(exc).__name__)
        return {}

def _save_state(s):
    try:
        atomic_write_json(STATE_FILE, s, backup=True, private=True, indent=None)
    except Exception as exc:
        print('[watch-store] state save failed:', type(exc).__name__)

def _log(text):
    try:
        assert_write_allowed(LOG_DIR)
        os.makedirs(LOG_DIR, exist_ok=True)
        fn = os.path.join(LOG_DIR, 'watch_' + datetime.now().strftime('%Y-%m') + '.log')
        with open(fn, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass


# ---- 抓日線 ------------------------------------------------
def _fetch_daily(code, market):
    from stock_signals_routes import load_alert_bars
    loaded = load_alert_bars(code, market, _fetch_daily_remote)
    _state.setdefault('daily_sources', {})[f'{market}:{code}'] = {
        key: value for key, value in loaded.items() if key != 'bars'}
    if loaded.get('error'):
        from log_once import log_once
        log_once(f'警報日線-{market}-{code}', loaded['error'])
    return loaded['bars'] or None


def _fetch_daily_remote(code, mkt):
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
                    candles.append({'time': ts[i], **{
                        key: (q.get(key) or [])[i] if i < len(q.get(key) or []) else None
                        for key in ('open', 'high', 'low', 'close', 'volume')}})
                if len(candles) >= 20:
                    return candles
            except Exception:
                continue
        if mkt == 'US':
            break
    return None


# ---- 指標 --------------------------------------------------
def _ind(candles, mkt='TW', symbol=''):
    """與複合警報共用日期及分欄品質契約。"""
    return dated_candle_snapshot(candles, mkt, symbol)


# ---- 策略評估（對齊 watch_v2 STRATEGIES.check）-------------
def _rsi_bounce_state(rsi, prev_min):
    """RSI 超賣反彈（事件，非水位）：近 5 根曾 < 30，今日回升站上 30 且仍在 38 以內才觸發。

    與前端 watch_v2 rsi_oversold_bounce 共用同一規則；單看「RSI 在 30~38」會把
    從 60 一路跌到 35 的走勢誤判成反彈。
    """
    if rsi is None:
        return ('none', '')
    recent_oversold = prev_min is not None and prev_min < 30
    if rsi < 30:
        return ('wait', f'RSI {rsi:.1f} 仍在超賣區，等回升站上 30')
    if rsi <= 38:
        if recent_oversold:
            return ('trigger', f'RSI 由 {prev_min:.1f} 回升至 {rsi:.1f}（近 5 日曾跌破 30）')
        return ('wait', f'RSI {rsi:.1f} 在 30~38，但近 5 日未曾跌破 30，非超賣反彈')
    if rsi < 50 and recent_oversold:
        return ('expired', f'RSI {rsi:.1f} 已離開反彈區')
    return ('wait', '')


def _eval(strategy, ind, params):
    p = params or {}
    c = ind.get('close')
    if c is None:
        return ('none', '')
    if strategy == 'sma60_pullback':
        s = ind.get('sma60')
        if s is None: return ('none', '')
        tol = (p.get('tolerance', 1.5)) / 100
        lo, hi = s * (1 - tol), s * (1 + tol)
        if lo <= c <= hi: return ('trigger', f'進入容差區 {lo:.2f}~{hi:.2f}')
        if c < lo: return ('broken', f'跌破容差下緣 {lo:.2f}')
        return ('wait', '')
    if strategy == 'sma20_pullback':
        s = ind.get('sma20')
        if s is None: return ('none', '')
        tol = (p.get('tolerance', 1.0)) / 100
        lo, hi = s * (1 - tol), s * (1 + tol)
        if lo <= c <= hi: return ('trigger', f'進入容差區 {lo:.2f}~{hi:.2f}')
        if c < lo: return ('broken', f'跌破容差下緣 {lo:.2f}')
        return ('wait', '')
    if strategy == 'breakout_n_high':
        days = int(p.get('days', 20)); vm = p.get('volMult', 1.5)
        highs = ind.get('highs') or []
        if len(highs) < days + 1: return ('none', '')
        prior = highs[-(days + 1):-1]
        if any(value is None for value in prior): return ('none', '')
        mx = max(prior)
        vr = ind.get('volVs20d')  # 當日量／前 20 日均量，與個股訊號「帶量突破」同口徑
        if c > mx:
            if vr is None:
                return ('none', '')
            if vr is not None and vr >= vm:
                return ('trigger', f'突破 {days} 日新高 {mx:.2f} + 量 {vr:.1f}x')
            return ('partial', f'價突破 {mx:.2f} 但量不足')
        return ('wait', '')
    if strategy == 'rsi_oversold_bounce':
        return _rsi_bounce_state(ind.get('rsi14'), ind.get('rsiPrevMin5'))
    if strategy == 'bb_lower_touch':
        b = ind.get('bbL')
        if b is None: return ('none', '')
        if c <= b: return ('trigger', f'觸布林下軌 {b:.2f}')
        return ('wait', '')
    if strategy == 'rsi_overheat':
        thr = p.get('threshold', 75)
        r = ind.get('rsi14')
        if r is None: return ('none', '')
        if r >= thr: return ('trigger', f'RSI {r:.1f} ≥ {thr} 過熱')
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
        ind = _ind(candles, mkt, code)
        for sig in sigs:
            status, detail = _eval(sig.get('strategy'), ind, sig.get('params'))
            if status == 'none':
                # 未知不是條件解除；保留冷卻與去重狀態。
                continue
            key = f"{code}:{sig.get('id')}"
            
            # 讀取與標準化舊狀態
            raw_prev = state.get(key)
            if isinstance(raw_prev, dict):
                prev_status = raw_prev.get('status')
                last_fired = raw_prev.get('last_fired_time', 0)
                fired_px = raw_prev.get('fired_price')
            else:
                prev_status = raw_prev
                last_fired = 0
                fired_px = None
                
            now = time.time()
            cur_px = ind['close']
            
            # --- 1. 觸發狀態升級 ---
            if status in ('trigger', 'broken') and prev_status != status:
                # 5 分鐘 (300 秒) 冷卻防線
                if now - last_fired < 300:
                    # 依然更新狀態防止重複判定，但本次跳過發送
                    state[key] = {
                        'status': status,
                        'last_fired_time': last_fired,  # 保留上一次的觸發時間
                        'fired_price': fired_px or cur_px
                    }
                    continue
                
                # 發送警報
                icon = '🎯' if status == 'trigger' else '⚠️'
                lbl = _STRAT_LBL.get(sig.get('strategy'), sig.get('strategy'))
                text = f"{icon} {code} — {lbl}：{detail}（現價 {cur_px:.2f}）"
                delivery = (alert_daemon.deliver(cfg, text, subject=f'WATCH 訊號 {code}', source='watch', now=now)
                            if alert_daemon else {'status': 'no_channel', 'id': None})
                _log(text)
                _state['fired'].append({'t': now, 'text': text, 'delivery': delivery['status'],
                                        'deliveryId': delivery['id']})
                _state['fired'] = _state['fired'][-100:]
                
                state[key] = {
                    'status': status,
                    'last_fired_time': now,
                    'fired_price': cur_px
                }
                fired += 1
                
            # --- 2. 重置狀態過濾 (Hysteresis) ---
            elif status not in ('trigger', 'broken') and prev_status:
                # 遲滯過濾：只有當最新價格與觸發時價格相比，變動大於 1.0% 時，才允許重置
                if fired_px is not None:
                    pct_change = abs(cur_px - fired_px) / fired_px
                    if pct_change < 0.01:
                        # 變動不夠大，拒絕重置狀態！強行保持原狀態
                        continue
                
                # 變動夠大或無紀錄，重置為待機狀態
                state[key] = {
                    'status': None,
                    'last_fired_time': last_fired,  # 保留歷史觸發時間供冷卻參考
                    'fired_price': None
                }
    _save_state(state)
    _state['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if fired:
        _log(f'check_once fired {fired}')


def _loop():
    while not _state['stop']:
        if alert_daemon:
            try:
                alert_daemon.retry_outbox()
            except Exception as e:
                _log('outbox retry error: ' + str(e))
        try:
            check_once()
        except Exception as e:
            _log('daemon error: ' + str(e))
        cfg = alert_daemon.load_config() if alert_daemon else {}
        time.sleep(max(60, int(cfg.get('watch_poll_seconds', 300))))


_lock_handle = None

def start():
    global _lock_handle
    if _state['thread'] and _state['thread'].is_alive():
        return
    # OS file lock prevents duplicate notification workers without consuming a TCP port.
    try:
        if _lock_handle is None:
            _lock_handle = acquire_daemon_lock('watch_daemon')
        if _lock_handle is None:
            _log("[watch] watch_daemon already running; skip start.")
            return
    except OSError as exc:
        _log("[watch] daemon lock failed: " + str(exc))
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
        'daily_sources': _state.get('daily_sources', {}),
    }


if __name__ == '__main__':
    if data_paths.binding_for().mode != 'legacy':
        raise SystemExit('外置資料模式不允許獨立 WATCH 檢查；請使用受管後端工作。')
    print('watch_daemon one-shot check')
    check_once()
    print(json.dumps(status(), ensure_ascii=False, indent=2))

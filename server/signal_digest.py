# -*- coding: utf-8 -*-
"""個股訊號推播：收盤摘要（新手）與即時事件（老手）。

* 模式存在 alert_config.json 的 ``stock_signal_push``：off / digest / realtime（預設 off）。
* 推播管道沿用 alert_daemon.notify（Telegram／Email／Webhook），不另建通道。
* 只在「狀態轉換」時推播：同一 (代號, 訊號, 日期) 只推一次；收盤摘要每市場每天一次。
* 標的 = 前端同步的自選股（/stock-signals/watchlist）∪ WATCH 觀察清單。
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    from . import stock_signals as ss
    from . import stock_signals_routes as routes
    from .atomic_store import StoreCorruptError, atomic_write_json, load_json
    from .daemon_lock import acquire_daemon_lock
except ImportError:
    import stock_signals as ss
    import stock_signals_routes as routes
    from atomic_store import StoreCorruptError, atomic_write_json, load_json
    from daemon_lock import acquire_daemon_lock

try:
    import alert_daemon
except Exception:  # pragma: no cover
    alert_daemon = None

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(_BASE, 'data', 'stock_signal_push_state.json')
CONFIG_KEY = 'stock_signal_push'
POLL_KEY = 'stock_signal_poll_seconds'
# 收盤後多久送摘要（當地時間），給資料源時間定稿
DIGEST_AFTER = {'TW': (14, 30), 'US': (16, 45)}

_state: Dict[str, Any] = {'thread': None, 'stop': False, 'last_run': None, 'sent': []}
_lock_handle = None
ICON = {'bull': '▲', 'bear': '▼', 'risk': '!', 'caution': '!', 'neutral': '•', 'unknown': '·'}


def _load_state() -> Dict[str, Any]:
    try:
        return load_json(STATE_FILE, default={}, expected_type=dict)
    except StoreCorruptError:
        return {}


def _save_state(st: Dict[str, Any]) -> None:
    sent = st.get('sent') or {}
    if len(sent) > 2000:  # 只保留最近的去重鍵
        st['sent'] = dict(sorted(sent.items(), key=lambda kv: kv[1])[-1500:])
    atomic_write_json(STATE_FILE, st, backup=True, private=True, indent=None)


def get_mode(cfg: Optional[Dict[str, Any]] = None) -> str:
    cfg = cfg if cfg is not None else (alert_daemon.load_config() if alert_daemon else {})
    mode = str(cfg.get(CONFIG_KEY) or 'off')
    return mode if mode in routes.PUSH_MODES else 'off'


def set_mode(mode: str) -> None:
    if not alert_daemon:
        raise RuntimeError('alert daemon unavailable')
    cur = alert_daemon.load_config()
    cur[CONFIG_KEY] = mode
    alert_daemon.save_config(cur)
    if mode != 'off':
        start()


def symbols() -> List[Dict[str, str]]:
    items = list(routes.load_watchlist())
    seen = {(i['sym'], i['market']) for i in items}
    try:
        import watch_daemon
        for code, w in (watch_daemon.load_rules() or {}).items():
            c = routes.clean_symbol(code)
            if not c:
                continue
            m = routes.infer_market(c, (w or {}).get('mkt'))
            if (c, m) not in seen:
                seen.add((c, m))
                items.append({'sym': c, 'market': m})
    except Exception:
        pass
    return items


def _lights_line(result: Dict[str, Any]) -> str:
    parts = []
    for l in result['health']['lights']:
        if l['state'] == 'unknown':
            continue
        parts.append(f"{l['label']}{ICON.get(l['state'], '')}{l['tag']}")
    return ' · '.join(parts)


def _event_line(e: Dict[str, Any]) -> str:
    tag = '（盤中暫定）' if e.get('provisional') else ''
    lvl = e['invalidation'].get('level')
    inval = e['invalidation']['text'] + (f' {lvl:,.2f}' if lvl is not None else '')
    stats = ''
    for row in ((e.get('stats') or {}).get('horizons') or []):
        if row['horizon'] == 5 and row.get('gate') == 'ok':
            stats = (f"；本檔過去 {row['n']} 次後 5 日上漲 {row['upRatio'] * 100:.0f}%"
                     f"（全期間 {row['baseUpRatio'] * 100:.0f}%）")
    if not stats:
        pooled = e.get('pooledStats') or {}
        for row in pooled.get('horizons') or []:
            if row['horizon'] == 5 and row.get('gate') == 'ok':
                stats = (f"；同市場 {pooled.get('symbols')} 檔合計 {row['n']} 次後 5 日上漲 "
                         f"{row['upRatio'] * 100:.0f}%（基準 {row['baseUpRatio'] * 100:.0f}%）")
    return (f"  {ICON.get(e['direction'], '•')} {e['label']}（{e['directionLabel']}）{tag}："
            f"{e['detail']}；失效：{inval}{stats}")


def format_symbol_block(result: Dict[str, Any], today_only: bool = True) -> Optional[str]:
    if not result.get('ok'):
        return None
    chg = result['indicators'].get('chgPct')
    chg_txt = f'（{chg:+.2f}%）' if chg is not None else ''
    head = f"{result['symbol']}  收 {result['indicators']['close']:,.2f}{chg_txt}  {_lights_line(result)}"
    lines = [head, '  ' + result['health']['summary']['sentence']]
    events = [e for e in result.get('events') or []
              if e['status'] != 'invalidated' and (not today_only or e['barsAgo'] == 0)]
    lines += [_event_line(e) for e in events]
    return '\n'.join(lines)


def build_digest(market: str, *, allow_network: bool = True,
                 items: Optional[List[Dict[str, str]]] = None) -> str:
    items = [i for i in (items if items is not None else symbols()) if i['market'] == market]
    title = f"📋 自選股收盤體檢（{'台股' if market == 'TW' else '美股'}）"
    if not items:
        return title + '\n尚未同步自選股：請在圖表頁「體檢」分頁開啟推播，或把股票加入自選。'
    blocks, as_of = [], None
    for it in items:
        try:
            r = routes.analyze_symbol(it['sym'], market, allow_network=allow_network)
        except Exception:
            continue
        if r.get('ok'):
            as_of = max(as_of or '', r['asOf'])
        block = format_symbol_block(r)
        if block:
            blocks.append(block)
    body = '\n\n'.join(blocks) if blocks else '（本機尚無可用日線）'
    return f"{title} {as_of or ''}\n\n{body}\n\n— {ss.DISCLAIMER}"


def _digest_due(market: str, st: Dict[str, Any], now: Optional[datetime]) -> Optional[str]:
    local = routes._now_local(market, now)
    if local.weekday() >= 5:
        return None
    hh, mm = DIGEST_AFTER[market]
    if local < local.replace(hour=hh, minute=mm, second=0, microsecond=0):
        return None
    today = local.date().isoformat()
    if (st.get('digestSent') or {}).get(market) == today:
        return None
    return today


def check_once(now: Optional[datetime] = None, notify=None) -> Dict[str, int]:
    cfg = alert_daemon.load_config() if alert_daemon else {}
    mode = get_mode(cfg)
    counts = {'events': 0, 'digests': 0}
    if mode == 'off':
        return counts
    send = notify or (lambda text, subject: alert_daemon.notify(cfg, text, subject=subject)
                      if alert_daemon else None)
    st = _load_state()
    st.setdefault('sent', {})
    st.setdefault('digestSent', {})
    items = symbols()
    if mode == 'realtime':
        for it in items:
            try:
                r = routes.analyze_symbol(it['sym'], it['market'])
            except Exception:
                continue
            if not r.get('ok'):
                continue
            fresh = []
            for e in r.get('events') or []:
                if e['barsAgo'] != 0 or e['status'] == 'invalidated':
                    continue
                key = f"{it['market']}:{it['sym']}:{e['signalId']}:{e['date']}"
                if key in st['sent']:
                    continue
                st['sent'][key] = int(time.time())
                fresh.append(e)
            if fresh:
                text = '\n'.join([f"🔔 {r['symbol']} 新訊號（{r['asOf']}）"] +
                                 [_event_line(e) for e in fresh] +
                                 ['  ' + r['health']['summary']['sentence']])
                send(text, f"個股訊號 {r['symbol']}")
                counts['events'] += len(fresh)
    for market in ('TW', 'US'):
        if mode not in ('digest', 'realtime'):
            break
        day = _digest_due(market, st, now)
        if not day or not any(i['market'] == market for i in items):
            continue
        text = build_digest(market, items=items)
        send(text, f"自選股收盤體檢 {day}")
        st['digestSent'][market] = day
        counts['digests'] += 1
    _save_state(st)
    _maybe_refresh_pooled(items)
    _state['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if counts['events'] or counts['digests']:
        _state['sent'].append({'t': time.time(), **counts})
        _state['sent'] = _state['sent'][-50:]
    return counts


POOLED_MAX_AGE_DAYS = 7


def _maybe_refresh_pooled(items: List[Dict[str, str]]) -> None:
    """推播開啟時，每週在背景重算一次同市場合併統計（使用者已明確啟用，不在 GET 偷跑）。"""
    try:
        import job_queue
        import signal_stats_pool as pool
    except Exception:
        return
    for market in sorted({i['market'] for i in items}):
        cached = pool.load_cached(market)
        stamp = (cached or {}).get('generatedAt')
        try:
            age = (datetime.now(ss._TZ['TW']) - datetime.fromisoformat(stamp)).days if stamp else None
        except ValueError:
            age = None
        if age is not None and age < POOLED_MAX_AGE_DAYS:
            continue
        job_queue.submit(pool.JOB_PREFIX + market,
                         (lambda m=market: (pool.refresh(m), routes.clear_cache())),
                         meta={'market': market, 'reason': 'weekly'})


def _loop():
    while not _state['stop']:
        try:
            check_once()
        except Exception as exc:
            print('[stock-signal] daemon error:', type(exc).__name__, exc)
        cfg = alert_daemon.load_config() if alert_daemon else {}
        if get_mode(cfg) == 'off':
            _state['thread'] = None
            return
        time.sleep(max(120, int(cfg.get(POLL_KEY, 600) or 600)))


def start():
    global _lock_handle
    if _state['thread'] and _state['thread'].is_alive():
        return
    try:
        if _lock_handle is None:
            _lock_handle = acquire_daemon_lock('stock_signal_daemon')
        if _lock_handle is None:
            print('[stock-signal] daemon already running; skip start.')
            return
    except OSError as exc:
        print('[stock-signal] daemon lock failed:', exc)
        return
    _state['stop'] = False
    t = threading.Thread(target=_loop, daemon=True, name='stock-signal-daemon')
    t.start()
    _state['thread'] = t


def status() -> Dict[str, Any]:
    cfg = alert_daemon.load_config() if alert_daemon else {}
    st = _load_state()
    channels = [k for k in ('telegram', 'email', 'webhook') if (cfg.get(k) or {}).get('enabled')]
    return {
        'mode': get_mode(cfg), 'modes': list(routes.PUSH_MODES),
        'pollSeconds': int(cfg.get(POLL_KEY, 600) or 600),
        'channels': channels,
        'symbols': len(symbols()),
        'digestSent': st.get('digestSent') or {},
        'lastRun': _state['last_run'],
        'running': bool(_state['thread'] and _state['thread'].is_alive()),
    }

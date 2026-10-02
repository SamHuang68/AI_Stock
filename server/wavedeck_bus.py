# -*- coding: utf-8 -*-
"""Stock Terminal ↔ WaveDeck reverse bus + shared cost meter + SSE fan-out.

WD → ST: POST /bridge/wavedeck（部位／FSM／成本回報；狀態變更推播）
ST → Browser: GET /bridge/wavedeck/stream（SSE；FULL_SYNC／POSITION_STATE_CHANGE）
ST 計價：本機 LLM 呼叫次數、雲端估算 USD；合併 WD costs 供頂列／Pulse 顯示。

Chip payload 極度輕量：不含 K 線／推論全文，僅 UI 必要欄位。
"""
from __future__ import annotations

import json
import queue
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

TZ8 = timezone(timedelta(hours=8))
DATA = Path(__file__).resolve().parents[1] / 'data'
STORE = DATA / 'wavedeck_bus.json'

# WaveDeck 預設／fallback 埠（與 bridge JS、run.py 對齊）。
# 18434／18435 保留給 Private Web，不可作為 WaveDeck fallback。
WD_PORTS = (18433, 18765, 28765, 38433, 8765)

_lock = threading.RLock()
_subscribers: list[queue.Queue] = []
_state: dict[str, Any] = {
    'report': None,  # last WD → ST payload
    'report_at': None,
    'report_epoch_ms': None,
    'costs': {
        'st_local_calls': 0,
        'st_cloud_calls': 0,
        'st_cloud_usd_est': 0.0,
        'wd_session_usd': 0.0,
        'wd_day_usd': 0.0,
        'wd_month_usd': 0.0,
        'wd_local_calls': 0,
        'wd_cloud_calls': 0,
        'wd_provider': None,
        'updated_at': None,
    },
}


def _now_iso() -> str:
    return datetime.now(TZ8).strftime('%Y-%m-%d %H:%M:%S')


def _load() -> None:
    global _state
    if not STORE.is_file():
        return
    try:
        raw = json.loads(STORE.read_text(encoding='utf-8'))
        if isinstance(raw, dict):
            with _lock:
                if isinstance(raw.get('costs'), dict):
                    _state['costs'].update(raw['costs'])
                if raw.get('report') is not None:
                    _state['report'] = raw['report']
                    _state['report_at'] = raw.get('report_at')
                    _state['report_epoch_ms'] = raw.get('report_epoch_ms')
                    if _state['report_epoch_ms'] is None and isinstance(raw.get('report'), dict):
                        _state['report_epoch_ms'] = raw['report'].get('received_epoch_ms')
    except Exception:
        pass


def _save() -> None:
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        with _lock:
            payload = {
                'report': _state.get('report'),
                'report_at': _state.get('report_at'),
                'report_epoch_ms': _state.get('report_epoch_ms'),
                'costs': _state.get('costs'),
            }
        tmp = STORE.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(STORE)
    except Exception:
        pass


_load()


def is_wavedeck_origin(origin_or_referer: str) -> bool:
    """Allow browser POSTs from WaveDeck loopback consoles."""
    o = (origin_or_referer or '').strip()
    if not o:
        return False
    try:
        u = urlparse(o if '://' in o else ('http://' + o))
        host = (u.hostname or '').lower()
        if host not in ('127.0.0.1', 'localhost'):
            return False
        port = u.port
        if port is None:
            port = 80 if (u.scheme or 'http') == 'http' else 443
        return int(port) in WD_PORTS
    except Exception:
        return False


def accept_report(body: dict[str, Any]) -> dict[str, Any]:
    """Ingest WaveDeck runtime snapshot (reverse bus)."""
    body = body if isinstance(body, dict) else {}
    ai = body.get('ai') if isinstance(body.get('ai'), dict) else {}
    costs = body.get('costs') if isinstance(body.get('costs'), dict) else {}
    pos = body.get('positions') if isinstance(body.get('positions'), dict) else {}
    ov = body.get('st_overlay') if isinstance(body.get('st_overlay'), dict) else {}

    report = {
        'fsm': body.get('fsm'),
        'mode': body.get('mode'),
        'style': body.get('style'),
        'symbol': body.get('symbol') or 'TXF',
        'kill_switch': bool(body.get('kill_switch')),
        'ai': {
            'action': ai.get('action'),
            'action_label': ai.get('action_label'),
            'confidence': ai.get('confidence'),
            'provider': ai.get('provider'),
            'invalidation': ai.get('invalidation') if isinstance(ai.get('invalidation'), dict) else {},
        },
        'positions': {
            'account': pos.get('account'),
            'txt_target': pos.get('txt_target'),
            'strategy': pos.get('strategy'),
            'ai_suggested': pos.get('ai_suggested'),
        },
        'st_overlay': {
            'aggressiveness': ov.get('aggressiveness'),
            'delever': ov.get('delever'),
            'rotation': ov.get('rotation'),
            'spillover_prob': ov.get('spillover_prob'),
            'hot_stage': ov.get('hot_stage'),
            'leaders': (ov.get('leaders') or [])[:6] if isinstance(ov.get('leaders'), list) else [],
            'chain_breadth': ov.get('chain_breadth'),
            'chain_contig': ov.get('chain_contig'),
            'note': (str(ov.get('note') or ''))[:200],
            'fail_safe': bool(ov.get('fail_safe')),
            'fail_safe_reason': (str(ov.get('fail_safe_reason') or ''))[:120],
        },
        'costs': {
            'session_usd': costs.get('session_usd'),
            'day_usd': costs.get('day_usd'),
            'month_usd': costs.get('month_usd'),
            'local_calls': costs.get('local_calls'),
            'cloud_calls': costs.get('cloud_calls'),
            'provider': costs.get('provider'),
        },
        'account': body.get('account') if isinstance(body.get('account'), dict) else {},
        'st_link': body.get('st_link') if isinstance(body.get('st_link'), dict) else {},
        'push_reason': str(body.get('push_reason') or '')[:64],
        'source': str(body.get('source') or 'wavedeck')[:64],
        'received_at': _now_iso(),
        'received_epoch_ms': int(time.time() * 1000),
    }
    # Lightweight chip (also accept pre-built chip from WD if present)
    chip_in = body.get('chip') if isinstance(body.get('chip'), dict) else None
    report['chip'] = chip_in or chip_from_report(report)

    with _lock:
        _state['report'] = report
        _state['report_at'] = report['received_at']
        _state['report_epoch_ms'] = report['received_epoch_ms']
        c = _state['costs']
        if costs.get('session_usd') is not None:
            try:
                c['wd_session_usd'] = float(costs['session_usd'])
            except Exception:
                pass
        if costs.get('day_usd') is not None:
            try:
                c['wd_day_usd'] = float(costs['day_usd'])
            except Exception:
                pass
        if costs.get('month_usd') is not None:
            try:
                c['wd_month_usd'] = float(costs['month_usd'])
            except Exception:
                pass
        if costs.get('provider'):
            c['wd_provider'] = str(costs['provider'])[:40]
        if costs.get('local_calls') is not None:
            try:
                c['wd_local_calls'] = int(costs['local_calls'])
            except Exception:
                pass
        if costs.get('cloud_calls') is not None:
            try:
                c['wd_cloud_calls'] = int(costs['cloud_calls'])
            except Exception:
                pass
        c['updated_at'] = report['received_at']
    _save()
    # Fan-out to SSE browsers (non-blocking)
    try:
        broadcast(make_event('POSITION_STATE_CHANGE', report['chip'], report=report))
    except Exception:
        pass
    return snapshot()


def record_st_local(n: int = 1) -> None:
    with _lock:
        _state['costs']['st_local_calls'] = int(_state['costs'].get('st_local_calls') or 0) + max(0, int(n))
        _state['costs']['updated_at'] = _now_iso()
    _save()


def record_st_cloud(usd: float = 0.02, calls: int = 1) -> None:
    with _lock:
        _state['costs']['st_cloud_calls'] = int(_state['costs'].get('st_cloud_calls') or 0) + max(0, int(calls))
        try:
            _state['costs']['st_cloud_usd_est'] = round(
                float(_state['costs'].get('st_cloud_usd_est') or 0) + float(usd), 4
            )
        except Exception:
            pass
        _state['costs']['updated_at'] = _now_iso()
    _save()


def snapshot() -> dict[str, Any]:
    with _lock:
        costs = deepcopy(_state['costs'])
        report = deepcopy(_state['report'])
        report_at = _state.get('report_at')
        report_epoch = _state.get('report_epoch_ms')
        if report_epoch is None and isinstance(report, dict):
            report_epoch = report.get('received_epoch_ms')
    now_ms = int(time.time() * 1000)
    age_sec = None
    if report_epoch is not None:
        try:
            age_sec = max(0.0, round((now_ms - int(report_epoch)) / 1000.0, 1))
        except Exception:
            age_sec = None
    # Fresh = report within last 30s (WD polls ~2s, reports ~12s)
    fresh = bool(age_sec is not None and age_sec <= 30.0)
    wd_day = float(costs.get('wd_day_usd') or 0)
    st_cloud = float(costs.get('st_cloud_usd_est') or 0)
    ov = (report or {}).get('st_overlay') if isinstance(report, dict) else {}
    return {
        'ok': True,
        'service': 'StockTerminal',
        'bridge': 'wavedeck',
        'report': report,
        'report_at': report_at,
        'age_sec': age_sec,
        'fresh': fresh,
        'costs': {
            'st_local_calls': int(costs.get('st_local_calls') or 0),
            'st_cloud_calls': int(costs.get('st_cloud_calls') or 0),
            'st_cloud_usd_est': st_cloud,
            'wd_session_usd': float(costs.get('wd_session_usd') or 0),
            'wd_day_usd': wd_day,
            'wd_month_usd': float(costs.get('wd_month_usd') or 0),
            'wd_local_calls': int(costs.get('wd_local_calls') or 0),
            'wd_cloud_calls': int(costs.get('wd_cloud_calls') or 0),
            'wd_provider': costs.get('wd_provider'),
            'combined_usd_est': round(st_cloud + wd_day, 4),
            'updated_at': costs.get('updated_at'),
        },
        'wavedeck': {
            'report_at': report_at,
            'age_sec': age_sec,
            'fresh': fresh,
            'fsm': (report or {}).get('fsm') if isinstance(report, dict) else None,
            'mode': (report or {}).get('mode') if isinstance(report, dict) else None,
            'style': (report or {}).get('style') if isinstance(report, dict) else None,
            'spillover_prob': ov.get('spillover_prob') if isinstance(ov, dict) else None,
            'hot_stage': ov.get('hot_stage') if isinstance(ov, dict) else None,
            'combined_usd_est': round(st_cloud + wd_day, 4),
            'wd_provider': costs.get('wd_provider'),
        },
        'chip': (report or {}).get('chip') if isinstance(report, dict) else None,
        'chips': (
            [(report or {}).get('chip')]
            if isinstance(report, dict) and (report or {}).get('chip')
            else []
        ),
        'ts': _now_iso(),
        'epoch_ms': now_ms,
    }


def last_report() -> Optional[dict[str, Any]]:
    with _lock:
        return deepcopy(_state['report'])


def _norm_sym(sym: Any) -> str:
    s = str(sym or 'TXF').upper().replace('.TW', '').replace('.TWO', '').strip()
    return s or 'TXF'


def _market_of(sym: str) -> str:
    if sym in {'TXF', 'TX', 'TWII', '^TWII', 'MXF'} or (sym.isdigit() and len(sym) <= 6):
        return 'TW'
    return 'US'


def chip_from_report(report: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Build lightweight POSITION_STATE chip for ST UI (no bars / no LLM text)."""
    if not isinstance(report, dict):
        return None
    pos = report.get('positions') if isinstance(report.get('positions'), dict) else {}
    ai = report.get('ai') if isinstance(report.get('ai'), dict) else {}
    inv = ai.get('invalidation') if isinstance(ai.get('invalidation'), dict) else {}
    ov = report.get('st_overlay') if isinstance(report.get('st_overlay'), dict) else {}
    qty_raw = pos.get('account')
    if qty_raw is None:
        qty_raw = pos.get('txt_target')
    try:
        qty_i = int(qty_raw) if qty_raw is not None else 0
    except Exception:
        qty_i = 0
    if qty_i > 0:
        direction = 'LONG'
    elif qty_i < 0:
        direction = 'SHORT'
    else:
        direction = 'EMPTY'
    sym = _norm_sym(report.get('symbol'))
    mode = str(report.get('mode') or 'paper').lower()
    try:
        inv_px = float(inv['price']) if inv.get('price') is not None else None
    except Exception:
        inv_px = None
    try:
        conf = float(ai['confidence']) if ai.get('confidence') is not None else None
    except Exception:
        conf = None
    return {
        'symbol': sym,
        'market': _market_of(sym),
        'direction': direction,
        'position_size': abs(qty_i),
        'invalidation_price': inv_px,
        'invalidation_side': str(inv.get('side') or 'below')[:12],
        'wd_mode': 'REAL' if mode == 'live' else 'PAPER',
        'ai_confidence': conf,
        'action': ai.get('action'),
        'action_label': ai.get('action_label'),
        'fsm': report.get('fsm'),
        'style': report.get('style'),
        'fail_safe': bool(ov.get('fail_safe')),
        'spillover_prob': ov.get('spillover_prob'),
        'macro_style': ov.get('aggressiveness'),
        'rotation': ov.get('rotation'),
        'hot_stage': ov.get('hot_stage'),
        'link_status': (report.get('st_link') or {}).get('status') if isinstance(report.get('st_link'), dict) else None,
    }


def make_event(
    event_type: str,
    data: Any,
    *,
    report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """SSE / bus event envelope."""
    snap_costs = None
    try:
        with _lock:
            c = deepcopy(_state.get('costs') or {})
        wd_day = float(c.get('wd_day_usd') or 0)
        st_cloud = float(c.get('st_cloud_usd_est') or 0)
        snap_costs = {
            'combined_usd_est': round(st_cloud + wd_day, 4),
            'wd_day_usd': wd_day,
            'wd_provider': c.get('wd_provider'),
            'st_local_calls': int(c.get('st_local_calls') or 0),
        }
    except Exception:
        snap_costs = None
    return {
        'event_type': str(event_type or 'POSITION_STATE_CHANGE'),
        'timestamp': int(time.time()),
        'data': data,
        'costs': snap_costs,
        'push_reason': (report or {}).get('push_reason') if isinstance(report, dict) else None,
        'st_link': (report or {}).get('st_link') if isinstance(report, dict) else None,
    }


def full_sync_event() -> dict[str, Any]:
    """On SSE connect: push all known chips so ST UI matches WD."""
    with _lock:
        report = deepcopy(_state.get('report'))
    chip = None
    if isinstance(report, dict):
        chip = report.get('chip') or chip_from_report(report)
    positions = [chip] if chip else []
    return make_event('FULL_SYNC', {'positions': positions}, report=report if isinstance(report, dict) else None)


def subscribe(maxsize: int = 32) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=max(4, int(maxsize)))
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def broadcast(event: dict[str, Any]) -> int:
    """Deliver event to all SSE subscribers; drop oldest if a queue is full."""
    if not isinstance(event, dict):
        return 0
    with _lock:
        subs = list(_subscribers)
    n = 0
    for q in subs:
        try:
            q.put_nowait(event)
            n += 1
        except queue.Full:
            try:
                q.get_nowait()
            except Exception:
                pass
            try:
                q.put_nowait(event)
                n += 1
            except Exception:
                pass
    return n


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)

# -*- coding: utf-8 -*-
"""Deterministic, shadow-only market precursor signal engine.

The engine consumes the already frozen Pulse/DecisionContext contracts.  It
never fetches data, mutates the authoritative regime/action envelope, or emits
buy/sell instructions.  Persistence exists so UI and transports can react to
state *transitions* instead of repeatedly announcing the same observation.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any


if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(_BASE, 'data', 'market_signals.db')
CONTRACT_VERSION = 3
ENGINE_VERSION = 'st-market-precursor/v2'
POLICY_VERSION = 'shadow-lifecycle/2026-09-v2'
OUTCOME_MODEL_VERSION = 'st-signal-prospective-ledger/v1'
OUTCOME_HORIZONS = (1, 3, 5)
OUTCOME_MIN_SAMPLE = 20
MATERIAL_MOVE_PCT = 2.0
_TRACKED_STATES = ('WATCH', 'ARMED', 'CONFIRMED', 'ACTIVE')
_HEADLINE_SIGNAL_IDS = ('TW_DOWNSIDE_PRECURSOR', 'TW_ATTACK_BUILDUP')

_WEIGHTS = {
    'globalTech': 0.24,
    'anchor': 0.26,
    'memoryCycle': 0.18,
    'breadthLiquidity': 0.18,
    'flowDerivatives': 0.14,
}
_REGIME_VALUE = {
    'OVERNIGHT_CONFIRMED': 0.85,
    'CASH_SESSION_ACCUMULATION': 0.60,
    'GAP_FADE_DISTRIBUTION': -0.70,
    'BROAD_CORRECTION': -0.90,
    'MIXED_LOW_CONFIDENCE': 0.0,
    'INSUFFICIENT_DATA': 0.0,
}
_STATE_RANK = {
    'OBSERVATION': 0, 'WATCH': 1, 'ARMED': 2, 'CONFIRMED': 3, 'ACTIVE': 4,
    'CONFLICT': 1, 'RECOVERY': 1, 'INVALIDATED': 0, 'EXPIRED': 0,
}


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value and value not in (float('inf'), float('-inf')) else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _iso_now(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def _twse_expiry_contract(at: datetime, is_session_date=None) -> dict[str, Any]:
    """將訊號到期時間對齊 TWSE 現貨盤邊界；未知假日採提前失效。"""
    if at.tzinfo is None:
        raise ValueError('expiry time must be timezone-aware')
    taipei_zone = timezone(timedelta(hours=8))
    local = at.astimezone(taipei_zone)
    resolver = is_session_date or (lambda day: day.weekday() < 5)
    quality = 'injected_calendar' if is_session_date else 'weekday_fallback'

    def next_session_day(day):
        candidate = day
        for _ in range(370):
            if resolver(candidate):
                return candidate
            candidate += timedelta(days=1)
        raise RuntimeError('TWSE session boundary could not be resolved')

    if resolver(local.date()) and local.time() < datetime.min.time().replace(hour=9):
        session_day = local.date()
        boundary_name = 'regular_open'
        boundary_local = datetime.combine(
            session_day, datetime.min.time().replace(hour=9), taipei_zone)
    elif resolver(local.date()) and local.time() < datetime.min.time().replace(hour=13, minute=30):
        session_day = local.date()
        boundary_name = 'regular_close'
        boundary_local = datetime.combine(
            session_day, datetime.min.time().replace(hour=13, minute=30), taipei_zone)
    else:
        session_day = next_session_day(local.date() + timedelta(days=1))
        boundary_name = 'next_regular_open'
        boundary_local = datetime.combine(
            session_day, datetime.min.time().replace(hour=9), taipei_zone)
    return {
        'expiresAt': boundary_local.astimezone(timezone.utc).isoformat(),
        'expiry': {
            'market': 'TWSE', 'session': 'regular', 'boundary': boundary_name,
            'boundaryAt': boundary_local.isoformat(), 'sessionDate': session_day.isoformat(),
            'timeZone': 'Asia/Taipei', 'calendarQuality': quality,
            'calendarSource': quality, 'calendarVersion': None,
            'policy': 'twse_regular_boundary/v1',
        },
    }


def _stable_expiry_contract(candidate: dict[str, Any], previous: dict | None,
                            *, same_observation: bool) -> dict[str, Any]:
    """同一來源觀測沿用首次到期邊界，不因伺服器重算而滑動延長。"""
    if not same_observation or not previous:
        return candidate
    try:
        payload = json.loads(str(previous.get('event_json') or '{}'))
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    expires_at = payload.get('expiresAt')
    if not expires_at:
        return candidate
    expiry = payload.get('expiry')
    if not isinstance(expiry, dict):
        observed = _aware_datetime(expires_at)
        local = observed.astimezone(timezone(timedelta(hours=8))) if observed else None
        expiry = {
            'market': 'TWSE', 'session': 'regular', 'boundary': 'legacy_preserved',
            'boundaryAt': local.isoformat() if local else str(expires_at),
            'sessionDate': local.date().isoformat() if local else None,
            'timeZone': 'Asia/Taipei', 'calendarQuality': 'legacy',
            'calendarSource': 'legacy_event', 'calendarVersion': None,
            'policy': 'legacy_preserved/v1',
        }
    return {'expiresAt': str(expires_at), 'expiry': expiry}


def _aware_datetime(value: Any) -> datetime | None:
    """Parse a source timestamp without treating server time as market time."""
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            return None
    # Legacy Pulse timestamps were emitted in Taiwan local time without an
    # offset.  Preserve compatibility while making the assumption explicit.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    return parsed.astimezone(timezone.utc)


def _effective_signal_view(signal: dict[str, Any], at: datetime | str | None = None) -> dict[str, Any]:
    """保留原始生命週期狀態，並依牆上時間派生實際有效狀態。"""
    checked_at = _aware_datetime(at) or datetime.now(timezone.utc)
    expires_at = _aware_datetime(signal.get('expiresAt'))
    expired = bool(expires_at and checked_at >= expires_at)
    view = dict(signal)
    view['expired'] = expired
    view['effectiveState'] = 'EXPIRED' if expired else str(signal.get('state') or 'OBSERVATION')
    return view


def _is_active_signal(signal: dict[str, Any]) -> bool:
    return str(signal.get('effectiveState') or signal.get('state') or 'OBSERVATION') not in (
        'OBSERVATION', 'RECOVERY', 'INVALIDATED', 'EXPIRED')


def _latest_timestamp(values: list[Any]) -> str | None:
    parsed = [(stamp, value) for value in values if (stamp := _aware_datetime(value)) is not None]
    if not parsed:
        return None
    return str(max(parsed, key=lambda row: row[0])[1])


def _quote_temporal(pulse: dict, symbol: str, *, fallback_market: str,
                    fallback_session: str) -> dict[str, Any]:
    quote = _market_quote(pulse, symbol)
    market = quote.get('market') or {}
    source_as_of = market.get('asOf') or quote.get('asOf')
    return {
        'market': market.get('market') or quote.get('marketCode') or fallback_market,
        'session': market.get('session') or quote.get('session') or fallback_session,
        'tradingDate': _date_key(
            market.get('sessionDate') or quote.get('tradeDate') or quote.get('date') or source_as_of),
        'sourceAsOf': source_as_of, 'asOf': source_as_of,
        'source': market.get('source') or quote.get('source') or 'canonical-pulse',
        'referenceType': market.get('referenceType') or quote.get('referenceType') or 'previous_close',
        'changePct': _quote_change(quote),
    }


def _temporal_status(metadata: dict[str, Any], computed_at: datetime,
                     *, evaluation_mode: str, reference: bool = False) -> dict[str, Any]:
    source_time = _aware_datetime(metadata.get('sourceAsOf'))
    age = max(0.0, (computed_at - source_time).total_seconds()) if source_time else None
    session = str(metadata.get('session') or 'unknown').lower()
    explicit = str(metadata.get('status') or '').lower()
    if reference:
        status = 'reference'
        finalized = True
    elif explicit in ('live', 'delayed', 'finalized', 'reference', 'stale', 'mixed'):
        status = explicit
        finalized = explicit in ('finalized', 'reference')
    elif session == 'regular' and evaluation_mode in (
            'cash_close_review', 'overnight_monitor', 'finalized_review'):
        status = 'finalized'
        finalized = True
    elif age is None:
        status = 'unknown'
        finalized = False
    elif age <= 120:
        status = 'live'
        finalized = False
    elif age <= 900:
        status = 'delayed'
        finalized = False
    else:
        status = 'stale'
        finalized = False
    return {
        **metadata,
        'status': status,
        'freshnessStatus': status,
        'finalized': finalized,
        'ageSeconds': round(age, 1) if age is not None else None,
    }


def _quote_rows(pulse: dict) -> dict[str, dict]:
    rows = list(pulse.get('global') or []) + list(pulse.get('signalQuotes') or [])
    return {str(row.get('symbol')): row for row in rows if isinstance(row, dict) and row.get('symbol')}


def _market_quote(pulse: dict, symbol: str) -> dict:
    quotes = ((pulse.get('marketSnapshot') or {}).get('quotes') or {})
    return quotes.get(symbol) or {}


def _quote_change(row: dict) -> float | None:
    market = row.get('market') or {}
    value = _number(market.get('displayChangePct'))
    return value if value is not None else _number(row.get('changePct'))


def _feature_value(context: dict, key: str) -> float | None:
    return _number((((context.get('scenario') or {}).get(key) or {}).get('value')))


def _evidence_source_as_of(context: dict, evidence_ids: tuple[str, ...]) -> str | None:
    wanted = set(evidence_ids)
    return _latest_timestamp([
        row.get('asOf') for row in (context.get('evidence') or [])
        if isinstance(row, dict) and row.get('id') in wanted
    ])


def _family(identifier: str, value: float | None, quality: float, reasons: list[str],
            evidence_ids: list[str], observed: dict | None = None,
            temporal: dict | None = None) -> dict[str, Any]:
    available = value is not None and quality > 0
    return {
        'id': identifier,
        'value': round(_clamp(value), 4) if available else None,
        'quality': round(_clamp(quality, 0.0, 1.0), 3) if available else 0.0,
        'available': available,
        'reasons': reasons,
        'evidenceIds': evidence_ids,
        'observed': observed or {},
        'temporal': temporal or {},
    }


def _global_family(pulse: dict) -> dict[str, Any]:
    rows = _quote_rows(pulse)
    parts: list[tuple[float, float, str]] = []
    specs = (('^SOX', 2.5, 0.45, '費半'), ('^IXIC', 2.0, 0.25, 'NASDAQ'),
             ('NVDA', 3.0, 0.15, 'NVIDIA'), ('AVGO', 3.0, 0.15, 'Broadcom'))
    observed = {}
    for symbol, scale, weight, label in specs:
        change = _quote_change(rows.get(symbol) or {})
        if change is None:
            continue
        observed[symbol] = round(change, 3)
        parts.append((_clamp(change / scale), weight, label))
    if not parts:
        return _family('globalTech', None, 0, [], [], observed)
    total = sum(weight for _, weight, _ in parts)
    value = sum(value * weight for value, weight, _ in parts) / total
    direction = '偏強' if value >= 0.20 else ('偏弱' if value <= -0.20 else '分歧')
    source_as_of = _latest_timestamp([
        ((rows.get(symbol) or {}).get('market') or {}).get('asOf') or (rows.get(symbol) or {}).get('asOf')
        for symbol, *_ in specs
    ])
    return _family('globalTech', value, min(1.0, total),
                   [f'國際科技鏈{direction}（{len(parts)}/4）'], ['global.tech'], observed,
                   {'market': 'US', 'session': 'latest_finalized', 'sourceAsOf': source_as_of,
                    'referenceType': 'previous_close', 'status': 'finalized'})


def _anchor_family(context: dict, pulse: dict) -> dict[str, Any]:
    rows = _quote_rows(pulse)
    tsm_tw = _quote_change(rows.get('2330.TW') or rows.get('2330') or {})
    tai50 = _quote_change(rows.get('0050.TW') or rows.get('0050') or {})
    tsm_adr = _quote_change(rows.get('TSM') or {})
    txf = _quote_change(_market_quote(pulse, '__TXF__'))
    benchmarks = ((context.get('exposureLab') or {}).get('benchmarks') or {})
    benchmark = benchmarks.get('FTSE_TAIWAN_50') or {}
    weight_pct = _number(benchmark.get('tsmcWeightPct'))
    weight = weight_pct / 100.0 if weight_pct is not None else None
    residual = None
    guard = 'residual_unavailable'
    if tsm_tw is not None and tai50 is not None and weight is not None and 0.05 < weight < 0.90:
        residual = (tai50 - weight * tsm_tw) / (1.0 - weight)
        guard = '0050_ex_2330_residual'
    parts: list[tuple[float, float]] = []
    if tsm_tw is not None:
        parts.append((_clamp(tsm_tw / 2.5), 0.60))
    if residual is not None:
        parts.append((_clamp(residual / 2.0), 0.25))
    elif tai50 is not None and tsm_tw is None:
        parts.append((_clamp(tai50 / 2.0), 0.45))
    if tsm_adr is not None:
        # ADR is context only: without a point-in-time FX/parity contract it
        # cannot independently confirm the Taiwan cash-session anchor.
        parts.append((_clamp(tsm_adr / 3.0), 0.10))
    if txf is not None:
        parts.append((_clamp(txf / 2.0), 0.05))
    observed = {
        '2330ChangePct': tsm_tw, '0050ChangePct': tai50,
        '0050Ex2330ChangePct': round(residual, 4) if residual is not None else None,
        'tsmcWeightPct': weight_pct, 'tsmAdrChangePct': tsm_adr,
        'txfChangePct': txf, 'doubleCountGuard': guard,
    }
    if not parts:
        return _family('anchor', None, 0, [], [], observed)
    total = sum(weight for _, weight in parts)
    value = sum(value * weight for value, weight in parts) / total
    quality = min(1.0, total) * (1.0 if residual is not None else 0.72)
    direction = '同向轉強' if value >= 0.20 else ('同向轉弱' if value <= -0.20 else '尚未同向')
    reason = f'台積電／0050 去重錨點{direction}'
    if residual is None and tsm_tw is not None and tai50 is not None:
        reason += '；缺可用權重，0050 不重複計票'
    anchor_rows = [rows.get(symbol) or {} for symbol in ('2330.TW', '2330', '0050.TW', '0050', 'TSM')]
    txf_quote = _market_quote(pulse, '__TXF__')
    source_as_of = _latest_timestamp([
        *((row.get('market') or {}).get('asOf') or row.get('asOf') for row in anchor_rows),
        (txf_quote.get('market') or {}).get('asOf') or txf_quote.get('asOf'),
    ])
    return _family('anchor', value, quality, [reason], ['anchor.2330_0050'], observed,
                   {'market': 'TW_US_CROSS_MARKET', 'session': 'mixed',
                    'sourceAsOf': source_as_of, 'referenceType': 'mixed', 'status': 'mixed'})


def _memory_family(memory_snapshot: dict | None) -> dict[str, Any]:
    snapshot = memory_snapshot or {}
    markets = {str(row.get('market')): row for row in (snapshot.get('markets') or []) if isinstance(row, dict)}
    parts: list[tuple[float, float, str]] = []
    observed: dict[str, Any] = {}
    for market, weight in (('TW', 0.55), ('US', 0.45)):
        row = markets.get(market) or {}
        summary = row.get('summary') or {}
        regime = ((summary.get('regime') or {}).get('id'))
        quality = (row.get('quality') or {}).get('status')
        if regime not in _REGIME_VALUE or quality == 'insufficient':
            continue
        value = _REGIME_VALUE[regime]
        parts.append((value, weight, market))
        observed[market] = {
            'regime': regime,
            'overnight20Pct': summary.get('overnightRepricing20Pct'),
            'intraday20Pct': summary.get('cashSessionAcceptance20Pct'),
            'breadthPct': summary.get('basketBreadthPct'),
            'asOf': summary.get('asOf'),
        }
    if not parts:
        return _family('memoryCycle', None, 0, [], [], observed)
    total = sum(weight for _, weight, _ in parts)
    value = sum(value * weight for value, weight, _ in parts) / total
    direction = '產業共振轉強' if value >= 0.25 else ('產業共振轉弱' if value <= -0.25 else '跨市場分歧')
    source_as_of = _latest_timestamp([
        ((markets.get(market) or {}).get('summary') or {}).get('asOf') for market in ('TW', 'US')
    ])
    return _family('memoryCycle', value, min(1.0, total), [direction],
                   [f'shadow.overnight_intraday.{market.lower()}' for _, _, market in parts], observed,
                   {'market': 'TW_US_MEMORY_BASKETS', 'session': 'research',
                    'sourceAsOf': source_as_of, 'referenceType': '20_session_research',
                    'status': 'reference'})


def _breadth_family(context: dict) -> dict[str, Any]:
    breadth = _feature_value(context, 'breadth')
    sector = _feature_value(context, 'sector')
    parts = [(breadth, 0.70)] if breadth is not None else []
    if sector is not None:
        parts.append((sector, 0.30))
    if not parts:
        return _family('breadthLiquidity', None, 0, [], [], {})
    total = sum(weight for _, weight in parts)
    value = sum(value * weight for value, weight in parts) / total
    raw = (((context.get('scenario') or {}).get('breadth') or {}).get('raw') or {})
    adv = _number(raw.get('advRatio'))
    direction = '多數股票參與' if value >= 0.20 else ('廣度收縮' if value <= -0.20 else '廣度中性')
    result = _family('breadthLiquidity', value, min(1.0, total), [direction],
                   ['breadth.stock_scope', 'breadth.velocity', 'sector.participation'],
                   {'advRatio': adv, 'velocity3': raw.get('velocity3'), 'velocity5': raw.get('velocity5')},
                   {'market': 'TWSE', 'session': 'regular',
                    'sourceAsOf': _evidence_source_as_of(
                        context, ('breadth.stock_scope', 'breadth.velocity', 'sector.participation')),
                    'referenceType': 'same_session_breadth'})
    return result


def _flow_family(context: dict, pulse: dict) -> dict[str, Any]:
    flow = _feature_value(context, 'flow')
    txf = _quote_change(_market_quote(pulse, '__TXF__'))
    parts = [(flow, 0.75)] if flow is not None else []
    if txf is not None:
        parts.append((_clamp(txf / 2.0), 0.25))
    if not parts:
        return _family('flowDerivatives', None, 0, [], [], {})
    total = sum(weight for _, weight in parts)
    value = sum(value * weight for value, weight in parts) / total
    raw = (((context.get('scenario') or {}).get('flow') or {}).get('raw') or {})
    direction = '資金／期貨支持' if value >= 0.20 else ('資金／期貨轉弱' if value <= -0.20 else '資金訊號分歧')
    txf_quote = _market_quote(pulse, '__TXF__')
    source_as_of = _latest_timestamp([
        _evidence_source_as_of(context, ('flow.institutional', 'flow.tx_oi')),
        (txf_quote.get('market') or {}).get('asOf') or txf_quote.get('asOf')])
    return _family('flowDerivatives', value, min(1.0, total), [direction],
                   ['flow.institutional', 'flow.tx_oi', 'txf.live'],
                   {'institutionalNetYi': raw.get('institutionalNetYi'),
                    'txOiChangePct': raw.get('txOiChangePct'), 'txfChangePct': txf},
                   {'market': 'TW_CASH_DERIVATIVES', 'session': 'mixed',
                    'sourceAsOf': source_as_of, 'referenceType': 'mixed', 'status': 'mixed'})


def _direction_strength(families: list[dict], direction: str) -> tuple[float, int, list[str], list[str]]:
    sign = 1.0 if direction == 'upside' else -1.0
    support = opposition = available_weight = 0.0
    domains = 0
    reasons: list[tuple[float, str]] = []
    counters: list[tuple[float, str]] = []
    for family in families:
        if not family.get('available'):
            continue
        weight = _WEIGHTS[family['id']] * float(family.get('quality') or 0)
        value = float(family['value']) * sign
        available_weight += weight
        if value >= 0:
            support += weight * value
            if value >= 0.25:
                domains += 1
            for reason in family.get('reasons') or []:
                reasons.append((value * weight, reason))
        else:
            opposition += weight * abs(value)
            for reason in family.get('reasons') or []:
                counters.append((abs(value) * weight, reason))
    if available_weight <= 0:
        return 0.0, 0, [], []
    strength = max(0.0, (support - 0.35 * opposition) / available_weight) * 100.0
    return (round(min(100.0, strength), 1), domains,
            [row[1] for row in sorted(reasons, reverse=True)[:3]],
            [row[1] for row in sorted(counters, reverse=True)[:2]])


def _build_temporal_context(context: dict, pulse: dict, computed_at: datetime) -> dict[str, Any]:
    baseline_raw = _quote_temporal(pulse, '^TWII', fallback_market='TWSE', fallback_session='regular')
    overlay_raw = _quote_temporal(pulse, '__TXF__', fallback_market='TAIFEX', fallback_session='unknown')
    overlay_session = str(overlay_raw.get('session') or '').lower()
    # TWSE and TAIFEX use Taiwan time year-round.  A quote labelled ``night``
    # can remain in the snapshot during the cash session, so its label alone
    # must not switch the whole engine into overnight mode.
    taipei = computed_at.astimezone(timezone(timedelta(hours=8)))
    minute = taipei.hour * 60 + taipei.minute
    weekday = taipei.weekday()
    cash_window = weekday < 5 and 9 * 60 <= minute < 13 * 60 + 30
    cash_close_window = weekday < 5 and 13 * 60 + 30 <= minute < 15 * 60
    night_window = (
        overlay_session == 'night' and (
            weekday < 5 and minute >= 15 * 60
            or 1 <= weekday <= 5 and minute <= 5 * 60
        )
    )
    if cash_window:
        mode = 'cash_session_monitor'
    elif cash_close_window:
        mode = 'cash_close_review'
    elif night_window:
        mode = 'overnight_monitor'
    else:
        mode = 'finalized_review'
    baseline = _temporal_status(baseline_raw, computed_at, evaluation_mode=mode)
    overlay = _temporal_status(overlay_raw, computed_at, evaluation_mode=mode)
    breadth_raw = (((context.get('scenario') or {}).get('breadth') or {}).get('raw') or {})
    breadth_as_of = _evidence_source_as_of(context, ('breadth.stock_scope', 'breadth.velocity'))
    breadth_date = _date_key(breadth_as_of)
    local_date = taipei.date().isoformat()
    breadth = _temporal_status({
        'market': 'TWSE', 'session': 'regular', 'tradingDate': breadth_date,
        'sourceAsOf': breadth_as_of, 'asOf': breadth_as_of,
        'source': 'canonical-decision-context', 'referenceType': 'same_session_breadth',
        'status': ('live' if mode == 'cash_session_monitor' and breadth_date == local_date else
                   'finalized' if mode in ('cash_close_review', 'overnight_monitor', 'finalized_review')
                   and breadth_date else None),
        'advRatio': _number(breadth_raw.get('advRatio')),
    }, computed_at, evaluation_mode=mode)
    source_times = [
        stamp for stamp in (
            _aware_datetime(baseline.get('sourceAsOf')),
            _aware_datetime(overlay.get('sourceAsOf')),
            _aware_datetime(breadth.get('sourceAsOf')),
        ) if stamp is not None
    ]
    statuses = {str(row.get('freshnessStatus') or 'unknown') for row in (baseline, overlay, breadth)}
    freshness_status = next(iter(statuses)) if len(statuses) == 1 else 'mixed'
    return {
        'computedAt': computed_at.astimezone(timezone.utc).isoformat(),
        'evaluationMode': mode,
        'baseline': baseline,
        'liveOverlay': overlay,
        'breadth': breadth,
        'target': {
            'market': 'TWSE', 'session': 'regular',
            'fromTradingSession': 1, 'toTradingSession': 5,
            'label': '下一個至第五個台股交易日',
        },
        'freshness': {
            'status': freshness_status,
            'oldestSourceAsOf': min(source_times).isoformat() if source_times else None,
            'newestSourceAsOf': max(source_times).isoformat() if source_times else None,
            'allInputsLive': bool(statuses) and statuses == {'live'},
        },
    }


def _normalize_family_temporal(families: list[dict], computed_at: datetime,
                               evaluation_mode: str) -> None:
    for family in families:
        metadata = dict(family.get('temporal') or {})
        family['temporal'] = _temporal_status(
            metadata, computed_at, evaluation_mode=evaluation_mode,
            reference=str(metadata.get('status') or '').lower() == 'reference')


def _observation_key(families: list[dict], temporal_context: dict[str, Any]) -> str:
    """Key lifecycle progression to source observations, not recomputation time."""
    compact_families = []
    for family in families:
        temporal = family.get('temporal') or {}
        compact_families.append({
            'id': family.get('id'), 'value': family.get('value'), 'quality': family.get('quality'),
            'available': family.get('available'), 'observed': family.get('observed') or {},
            # Research and finalized external sessions can advance without a
            # numeric change; server-generated DecisionContext timestamps may not.
            'sourceAsOf': temporal.get('sourceAsOf') if temporal.get('session') in (
                'night', 'latest_finalized', 'research') else None,
        })
    baseline = temporal_context.get('baseline') or {}
    overlay = temporal_context.get('liveOverlay') or {}
    raw = json.dumps({
        'families': compact_families,
        'baseline': {key: baseline.get(key) for key in ('tradingDate', 'sourceAsOf', 'changePct')},
        'liveOverlay': {key: overlay.get(key) for key in ('session', 'tradingDate', 'sourceAsOf', 'changePct')},
    }, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def _signal(signal_id: str, label: str, direction: str, strength: float, domains: int,
            quality: float, reasons: list[str], counters: list[str], evidence_ids: list[str],
            context: dict, pulse: dict, temporal_context: dict) -> dict[str, Any]:
    twii = _quote_change(_market_quote(pulse, '^TWII'))
    txf = _quote_change(_market_quote(pulse, '__TXF__'))
    breadth = _number(((((context.get('scenario') or {}).get('breadth') or {}).get('raw') or {}).get('advRatio')))
    cash_confirmed = bool(
        direction == 'upside' and twii is not None and twii > 0 and breadth is not None and breadth >= 0.55
        or direction == 'downside' and twii is not None and twii < 0 and breadth is not None and breadth <= 0.45)
    mode = temporal_context.get('evaluationMode')
    baseline = temporal_context.get('baseline') or {}
    breadth_time = temporal_context.get('breadth') or {}
    computed_stamp = _aware_datetime(temporal_context.get('computedAt'))
    evaluated_local_date = (
        computed_stamp.astimezone(timezone(timedelta(hours=8))).date().isoformat()
        if computed_stamp else None)
    baseline_date = baseline.get('tradingDate')
    breadth_date = breadth_time.get('tradingDate')
    trusted_statuses = {'live', 'delayed', 'finalized'}
    cash_confirmation_eligible = bool(
        cash_confirmed and mode in ('cash_session_monitor', 'cash_close_review')
        and baseline_date and breadth_date
        and baseline_date == breadth_date == evaluated_local_date
        and str(baseline.get('session') or '').lower() == 'regular'
        and str(breadth_time.get('session') or '').lower() == 'regular'
        and baseline.get('status') in trusted_statuses
        and breadth_time.get('status') in trusted_statuses)
    overnight = mode == 'overnight_monitor'
    if cash_confirmation_eligible:
        confirmation = '台股現貨方向與上市廣度同向確認'
    elif cash_confirmed and overnight:
        confirmation = '當日現貨與廣度同向；夜盤新事件仍須下一現貨盤確認'
    else:
        confirmation = '等待台股現貨與廣度同向確認'
    return {
        'signalId': signal_id, 'label': label, 'direction': direction,
        'strength': round(strength, 1), 'independentDomains': int(domains),
        'evidenceQuality': round(quality, 3), 'reasons': reasons,
        'strongestCounterEvidence': counters,
        'evidenceIds': sorted(set(evidence_ids)),
        'cashConfirmation': cash_confirmed,
        'cashConfirmationEligible': cash_confirmation_eligible,
        'confirmationSessionDate': baseline_date if cash_confirmation_eligible else None,
        'candidateSessionDate': baseline_date,
        'confirmationSession': baseline.get('session'),
        'observed': {'twiiChangePct': twii, 'txfChangePct': txf, 'advRatio': breadth},
        'confirmation': confirmation,
        'invalidation': '訊號強度連續三次低於 45，或核心方向反轉',
        'horizon': 'next_session_to_5_sessions',
        'target': temporal_context.get('target') or {},
    }


def evaluate_context(context: dict, pulse: dict, *, memory_snapshot: dict | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    """Pure evaluation.  Returned strengths are evidence strength, not probability."""
    computed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    families = [
        _global_family(pulse), _anchor_family(context, pulse), _memory_family(memory_snapshot),
        _breadth_family(context), _flow_family(context, pulse),
    ]
    temporal_context = _build_temporal_context(context, pulse, computed_at)
    _normalize_family_temporal(families, computed_at, temporal_context['evaluationMode'])
    observation_key = _observation_key(families, temporal_context)
    completeness = _number((context.get('dataQuality') or {}).get('completeness')) or 0.0
    freshness = _number((context.get('dataQuality') or {}).get('freshness')) or 0.0
    available_weight = sum(_WEIGHTS[row['id']] * float(row.get('quality') or 0)
                           for row in families if row.get('available'))
    evidence_quality = _clamp(available_weight * completeness * (0.55 + 0.45 * freshness), 0.0, 1.0)
    up_strength, up_domains, up_reasons, up_counters = _direction_strength(families, 'upside')
    down_strength, down_domains, down_reasons, down_counters = _direction_strength(families, 'downside')
    evidence_ids = [eid for row in families for eid in row.get('evidenceIds') or []]
    signals = [
        _signal('TW_DOWNSIDE_PRECURSOR', '下行前兆證據', 'downside', down_strength, down_domains,
                evidence_quality, down_reasons, down_counters, evidence_ids, context, pulse, temporal_context),
        _signal('TW_ATTACK_BUILDUP', '上行前兆證據', 'upside', up_strength, up_domains,
                evidence_quality, up_reasons, up_counters, evidence_ids, context, pulse, temporal_context),
    ]
    family_map = {row['id']: row for row in families}
    for signal_id, label, family_ids in (
        ('AI_WAFER_DOUBLE_ARROW', 'AI 雙箭頭晶圓連動', ('globalTech', 'anchor', 'breadthLiquidity')),
        ('MEMORY_CYCLE_RESONANCE', '記憶體週期共振', ('memoryCycle', 'anchor', 'breadthLiquidity')),
    ):
        selected = [family_map[key] for key in family_ids]
        pos, pos_n, pos_reasons, pos_counters = _direction_strength(selected, 'upside')
        neg, neg_n, neg_reasons, neg_counters = _direction_strength(selected, 'downside')
        core_values = [selected[index].get('value') for index in (0, 1)
                       if selected[index].get('available')]
        core_conflict = (len(core_values) == 2 and abs(float(core_values[0])) >= 0.20
                         and abs(float(core_values[1])) >= 0.20
                         and float(core_values[0]) * float(core_values[1]) < 0)
        direction = ('mixed' if core_conflict else
                     ('upside' if pos > neg + 5 else ('downside' if neg > pos + 5 else 'mixed')))
        strength = max(pos, neg) if direction != 'mixed' else min(54.0, max(pos, neg))
        reasons = pos_reasons if direction == 'upside' else neg_reasons if direction == 'downside' else ['核心來源尚未同向']
        counters = pos_counters if direction == 'upside' else neg_counters if direction == 'downside' else []
        domains = pos_n if direction == 'upside' else neg_n if direction == 'downside' else 0
        selected_ids = [eid for row in selected for eid in row.get('evidenceIds') or []]
        signals.append(_signal(signal_id, label, direction, strength, domains, evidence_quality,
                               reasons, counters, selected_ids, context, pulse, temporal_context))
    conflict = up_strength >= 55 and down_strength >= 55
    return {
        'ok': bool(context.get('ok')),
        'contractVersion': CONTRACT_VERSION, 'model': ENGINE_VERSION,
        'policyVersion': POLICY_VERSION, 'shadowOnly': True,
        'actionAuthority': 'none', 'asOf': context.get('asOf') or pulse.get('updatedAt'),
        'temporalContext': temporal_context,
        'observationKey': observation_key,
        'thresholds': {
            'watchStrength': 55, 'watchIndependentDomains': 2,
            'armedStrength': 70, 'armedIndependentDomains': 3,
            'confirmedStrength': 80, 'confirmedIndependentDomains': 3,
        },
        'status': 'CONFLICT' if conflict else 'READY',
        'evidenceQuality': round(evidence_quality, 3),
        'familyScores': families, 'signals': signals,
        'upside': {'strength': up_strength, 'independentDomains': up_domains},
        'downside': {'strength': down_strength, 'independentDomains': down_domains},
        'dataQuality': {
            'availableDomains': sum(1 for row in families if row.get('available')),
            'requiredDomainsForHighAlert': 3,
            'missingDomains': [row['id'] for row in families if not row.get('available')],
            'strengthIsProbability': False,
        },
    }


def _date_key(value: Any) -> str | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    if len(raw) >= 10 and raw[4:5] == '-' and raw[7:8] == '-':
        return raw[:10]
    digits = ''.join(ch for ch in raw[:10] if ch.isdigit())
    if len(digits) >= 8:
        return f'{digits[:4]}-{digits[4:6]}-{digits[6:8]}'
    return None


def _market_reference(pulse: dict, as_of: str) -> dict[str, Any]:
    quote = _market_quote(pulse, '^TWII')
    market = quote.get('market') or {}
    price = _number(quote.get('price', market.get('price')))
    session_date = _date_key(
        market.get('sessionDate') or quote.get('tradeDate') or quote.get('date') or
        pulse.get('date') or market.get('asOf') or quote.get('asOf') or as_of)
    return {
        'symbol': '^TWII', 'price': price, 'sessionDate': session_date,
        'asOf': market.get('asOf') or quote.get('asOf') or as_of,
        'source': market.get('source') or quote.get('source') or 'canonical-pulse',
        'session': market.get('session') or quote.get('session') or 'regular',
    }


def _sync_market_sessions(conn: sqlite3.Connection, rows: Any, observed_at: str) -> int:
    normalized: dict[str, tuple[float, str, str]] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        day = _date_key(raw.get('date') or raw.get('asOf') or raw.get('ts'))
        close = _number(raw.get('close', raw.get('indexClose')))
        if day and close is not None and close > 0:
            normalized[day] = (
                close, str(raw.get('source') or 'pulse-history:index'),
                str(raw.get('asOf') or raw.get('date') or day),
            )
    for day, (close, source, as_of) in normalized.items():
        conn.execute(
            'INSERT INTO signal_market_sessions(session_date,close,source,as_of,observed_at) '
            'VALUES(?,?,?,?,?) ON CONFLICT(session_date) DO UPDATE SET '
            'close=excluded.close,source=excluded.source,as_of=excluded.as_of,observed_at=excluded.observed_at',
            (day, close, source, as_of, observed_at),
        )
    return len(normalized)


def _enroll_trials(conn: sqlite3.Connection, signals: list[dict], market_ref: dict,
                   created_at: str) -> int:
    enrolled = 0
    entry_price = _number(market_ref.get('price'))
    origin_session = _date_key(market_ref.get('sessionDate') or market_ref.get('asOf'))
    if entry_price is None or entry_price <= 0 or not origin_session:
        return 0
    for signal in signals or []:
        direction = str(signal.get('direction') or '')
        state = str(signal.get('state') or '')
        if direction not in ('upside', 'downside') or state not in _TRACKED_STATES:
            continue
        first_seen = str(signal.get('firstSeenAt') or created_at)
        identity = f"{signal.get('signalId')}:{direction}:{first_seen}"
        trial_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
        payload = {
            'trialId': trial_id, 'signalId': signal.get('signalId'), 'label': signal.get('label'),
            'direction': direction, 'triggerState': state, 'originAsOf': market_ref.get('asOf'),
            'originSession': origin_session, 'entryPrice': round(entry_price, 4),
            'strength': signal.get('strength'), 'evidenceQuality': signal.get('evidenceQuality'),
            'independentDomains': signal.get('independentDomains'),
            'policyVersion': signal.get('policyVersion') or POLICY_VERSION,
            'engineVersion': signal.get('engineVersion') or ENGINE_VERSION,
            'shadowOnly': True, 'actionAuthority': 'none',
            'enrollment': 'first_observed_tracked_episode',
        }
        before = conn.total_changes
        conn.execute(
            'INSERT OR IGNORE INTO signal_trials('
            'trial_id,signal_id,label,direction,trigger_state,origin_as_of,origin_session,entry_price,'
            'strength,evidence_quality,domains,policy_version,engine_version,created_at,trial_json) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (trial_id, signal.get('signalId'), signal.get('label'), direction, state,
             market_ref.get('asOf'), origin_session, entry_price, signal.get('strength'),
             signal.get('evidenceQuality'), signal.get('independentDomains'),
             signal.get('policyVersion') or POLICY_VERSION,
             signal.get('engineVersion') or ENGINE_VERSION, created_at,
             json.dumps(payload, ensure_ascii=False, separators=(',', ':'), default=str)),
        )
        enrolled += int(conn.total_changes > before)
    return enrolled


def _median(values: list[float]) -> float | None:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return None
    middle = len(clean) // 2
    return clean[middle] if len(clean) % 2 else (clean[middle - 1] + clean[middle]) / 2.0


def _resolve_trials(conn: sqlite3.Connection, resolved_at: str) -> int:
    rows = conn.execute(
        'SELECT trial_id,signal_id,direction,origin_session,entry_price FROM signal_trials '
        'WHERE (SELECT COUNT(*) FROM signal_outcomes o WHERE o.trial_id=signal_trials.trial_id)<?',
        (len(OUTCOME_HORIZONS),),
    ).fetchall()
    inserted = 0
    for trial_id, signal_id, direction, origin_session, entry_price in rows:
        if direction not in ('upside', 'downside') or not entry_price:
            continue
        future = conn.execute(
            'SELECT session_date,close,source,as_of FROM signal_market_sessions '
            'WHERE session_date>? ORDER BY session_date ASC LIMIT ?',
            (origin_session, max(OUTCOME_HORIZONS)),
        ).fetchall()
        if not future:
            continue
        signed_returns: list[float] = []
        raw_returns: list[float] = []
        sign = 1.0 if direction == 'upside' else -1.0
        for _day, close, _source, _as_of in future:
            raw_return = (float(close) / float(entry_price) - 1.0) * 100.0
            raw_returns.append(raw_return)
            signed_returns.append(raw_return * sign)
        for horizon in OUTCOME_HORIZONS:
            if len(future) < horizon:
                continue
            exists = conn.execute(
                'SELECT 1 FROM signal_outcomes WHERE trial_id=? AND horizon_sessions=?',
                (trial_id, horizon),
            ).fetchone()
            if exists:
                continue
            signed_path = signed_returns[:horizon]
            raw_path = raw_returns[:horizon]
            directional_return = signed_path[-1]
            max_favorable = max([0.0] + signed_path)
            max_adverse = max([0.0] + [-value for value in signed_path])
            lead = next((index + 1 for index, value in enumerate(signed_path)
                         if value >= MATERIAL_MOVE_PCT), None)
            target = future[horizon - 1]
            payload = {
                'trialId': trial_id, 'signalId': signal_id, 'direction': direction,
                'horizonSessions': horizon, 'originSession': origin_session,
                'targetSession': target[0], 'entryPrice': round(float(entry_price), 4),
                'exitPrice': round(float(target[1]), 4),
                'rawReturnPct': round(raw_path[-1], 4),
                'directionalReturnPct': round(directional_return, 4),
                'directionCorrect': directional_return > 0,
                'materialMoveThresholdPct': MATERIAL_MOVE_PCT,
                'materialMoveHit': max_favorable >= MATERIAL_MOVE_PCT,
                'maxFavorableExcursionPct': round(max_favorable, 4),
                'maxAdverseExcursionPct': round(max_adverse, 4),
                'materialMoveLeadSessions': lead,
                'source': target[2], 'sourceAsOf': target[3],
                'historicalEmpirical': True, 'predictiveProbability': False,
                'shadowOnly': True, 'actionAuthority': 'none',
            }
            conn.execute(
                'INSERT INTO signal_outcomes('
                'trial_id,horizon_sessions,target_session,exit_price,raw_return_pct,directional_return_pct,'
                'max_favorable_pct,max_adverse_pct,direction_hit,material_hit,lead_sessions,resolved_at,outcome_json) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (trial_id, horizon, target[0], target[1], raw_path[-1], directional_return,
                 max_favorable, max_adverse, int(directional_return > 0),
                 int(max_favorable >= MATERIAL_MOVE_PCT), lead, resolved_at,
                 json.dumps(payload, ensure_ascii=False, separators=(',', ':'), default=str)),
            )
            inserted += 1
    return inserted


def _prospective_summary_conn(conn: sqlite3.Connection, signal_id: str | None = None) -> dict[str, Any]:
    if signal_id:
        where = ' WHERE signal_id=?'
        params: tuple[Any, ...] = (signal_id,)
    else:
        where = ' WHERE signal_id IN (?,?)'
        params = _HEADLINE_SIGNAL_IDS
    total = int(conn.execute('SELECT COUNT(*) FROM signal_trials' + where, params).fetchone()[0])
    started = conn.execute('SELECT MIN(origin_session) FROM signal_trials' + where, params).fetchone()[0]
    horizons = []
    resolved_total = 0
    for horizon in OUTCOME_HORIZONS:
        query = (
            'SELECT o.directional_return_pct,o.max_favorable_pct,o.max_adverse_pct,'
            'o.direction_hit,o.material_hit,o.lead_sessions FROM signal_outcomes o '
            'JOIN signal_trials t ON t.trial_id=o.trial_id WHERE o.horizon_sessions=?'
        )
        args: tuple[Any, ...] = (horizon,)
        if signal_id:
            query += ' AND t.signal_id=?'
            args = (horizon, signal_id)
        else:
            query += ' AND t.signal_id IN (?,?)'
            args = (horizon, *_HEADLINE_SIGNAL_IDS)
        rows = conn.execute(query, args).fetchall()
        resolved = len(rows)
        resolved_total += resolved
        qualified = resolved >= OUTCOME_MIN_SAMPLE
        direction_hits = sum(int(row[3] or 0) for row in rows)
        material_hits = sum(int(row[4] or 0) for row in rows)
        leads = [float(row[5]) for row in rows if row[5] is not None]
        horizons.append({
            'sessions': horizon, 'resolvedCount': resolved,
            'pendingCount': max(0, total - resolved),
            'minimumSample': OUTCOME_MIN_SAMPLE, 'ratesAvailable': qualified,
            'directionHitRatePct': round(direction_hits / resolved * 100.0, 1) if qualified else None,
            'materialMoveHitRatePct': round(material_hits / resolved * 100.0, 1) if qualified else None,
            'falseAlertRatePct': round((resolved - material_hits) / resolved * 100.0, 1) if qualified else None,
            'averageDirectionalReturnPct': round(sum(float(row[0]) for row in rows) / resolved, 3) if qualified else None,
            'averageMaxFavorablePct': round(sum(float(row[1]) for row in rows) / resolved, 3) if qualified else None,
            'averageMaxAdversePct': round(sum(float(row[2]) for row in rows) / resolved, 3) if qualified else None,
            'medianMaterialMoveLeadSessions': round(_median(leads), 1) if qualified and leads else None,
        })
    capacity = total * len(OUTCOME_HORIZONS)
    status = 'empty' if total == 0 else (
        'ready' if all(row['ratesAvailable'] for row in horizons) else 'building')
    return {
        'ok': True, 'contractVersion': 1, 'model': OUTCOME_MODEL_VERSION,
        'status': status, 'shadowOnly': True, 'actionAuthority': 'none',
        'totalTrials': total, 'resolvedOutcomes': resolved_total,
        'coveragePct': round(resolved_total / capacity * 100.0, 1) if capacity else 0.0,
        'minimumSampleForRates': OUTCOME_MIN_SAMPLE,
        'materialMoveThresholdPct': MATERIAL_MOVE_PCT,
        'startedAt': started, 'signalId': signal_id,
        'scope': signal_id or 'headline_precursors', 'horizons': horizons,
        'methodology': {
            'entry': 'first canonical TWII observation in each tracked signal episode',
            'exit': 'finalized TWII daily closes from existing Pulse index history',
            'horizons': list(OUTCOME_HORIZONS),
            'directionHit': 'signed terminal return above zero',
            'materialMoveHit': f'max favorable excursion reaches {MATERIAL_MOVE_PCT:.1f}%',
            'ratesWithheldBelowSample': OUTCOME_MIN_SAMPLE,
            'retrospectiveBackfill': False, 'strengthIsProbability': False,
        },
    }


def _empty_prospective(status: str = 'empty', error: str | None = None) -> dict[str, Any]:
    out = {
        'ok': status != 'unavailable', 'contractVersion': 1,
        'model': OUTCOME_MODEL_VERSION, 'status': status,
        'shadowOnly': True, 'actionAuthority': 'none',
        'totalTrials': 0, 'resolvedOutcomes': 0, 'coveragePct': 0.0,
        'minimumSampleForRates': OUTCOME_MIN_SAMPLE,
        'materialMoveThresholdPct': MATERIAL_MOVE_PCT,
        'horizons': [
            {
                'sessions': horizon, 'resolvedCount': 0, 'pendingCount': 0,
                'minimumSample': OUTCOME_MIN_SAMPLE, 'ratesAvailable': False,
            }
            for horizon in OUTCOME_HORIZONS
        ],
    }
    if error:
        out['error'] = error
    return out


def _init_db(path: str = DB_PATH) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS signal_state('
                         'signal_id TEXT PRIMARY KEY,direction TEXT,state TEXT,first_seen_at TEXT,'
                         'changed_at TEXT,last_seen_at TEXT,strength REAL,evidence_quality REAL,'
                         'consecutive_hits INTEGER,miss_count INTEGER,dedupe_key TEXT,event_json TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS signal_observations('
                         'id INTEGER PRIMARY KEY AUTOINCREMENT,signal_id TEXT,direction TEXT,as_of TEXT,'
                         'observation_key TEXT,strength REAL,domains INTEGER,qualified INTEGER,snapshot_json TEXT,'
                         'UNIQUE(signal_id,direction,as_of))')
            observation_columns = {
                str(row[1]) for row in conn.execute('PRAGMA table_info(signal_observations)').fetchall()
            }
            if 'observation_key' not in observation_columns:
                conn.execute('ALTER TABLE signal_observations ADD COLUMN observation_key TEXT')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_observation_key '
                         'ON signal_observations(signal_id,direction,observation_key) '
                         'WHERE observation_key IS NOT NULL')
            conn.execute('CREATE TABLE IF NOT EXISTS signal_events('
                         'id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE,signal_id TEXT,direction TEXT,'
                         'from_state TEXT,to_state TEXT,tier TEXT,as_of TEXT,created_at TEXT,dedupe_key TEXT,event_json TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS signal_market_sessions('
                         'session_date TEXT PRIMARY KEY,close REAL NOT NULL,source TEXT,as_of TEXT,observed_at TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS signal_trials('
                         'trial_id TEXT PRIMARY KEY,signal_id TEXT,label TEXT,direction TEXT,'
                         'trigger_state TEXT,origin_as_of TEXT,origin_session TEXT,entry_price REAL,strength REAL,'
                         'evidence_quality REAL,domains INTEGER,policy_version TEXT,engine_version TEXT,'
                         'created_at TEXT,trial_json TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS signal_outcomes('
                         'trial_id TEXT NOT NULL,horizon_sessions INTEGER NOT NULL,target_session TEXT,'
                         'exit_price REAL,raw_return_pct REAL,directional_return_pct REAL,max_favorable_pct REAL,'
                         'max_adverse_pct REAL,direction_hit INTEGER,material_hit INTEGER,lead_sessions INTEGER,'
                         'resolved_at TEXT,outcome_json TEXT,PRIMARY KEY(trial_id,horizon_sessions))')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_signal_trials_signal '
                         'ON signal_trials(signal_id,direction,origin_session)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_signal_outcomes_horizon '
                         'ON signal_outcomes(horizon_sessions,resolved_at)')


def _target_state(signal: dict, previous: dict | None, same_observation: bool) -> tuple[str, int, int]:
    if same_observation and previous:
        return str(previous['state']), int(previous['consecutive_hits']), int(previous['miss_count'])
    direction = signal.get('direction')
    strength = float(signal.get('strength') or 0)
    domains = int(signal.get('independentDomains') or 0)
    prior_state = str((previous or {}).get('state') or 'OBSERVATION')
    prior_direction = (previous or {}).get('direction')
    hits = int((previous or {}).get('consecutive_hits') or 0)
    misses = int((previous or {}).get('miss_count') or 0)
    if direction == 'mixed':
        return 'CONFLICT', 0, 0
    if previous and prior_direction not in (None, direction) and _STATE_RANK.get(prior_state, 0) >= 1:
        return 'INVALIDATED', 0, 0
    qualified = strength >= 55 and domains >= 2
    hits = hits + 1 if qualified else 0
    misses = misses + 1 if strength < 45 else 0
    tracked = prior_state in ('WATCH', 'ARMED', 'CONFIRMED', 'ACTIVE')
    if tracked and strength < 45:
        if misses >= 3:
            return 'RECOVERY', 0, misses
        return prior_state, hits, misses
    if prior_state == 'ACTIVE':
        return 'ACTIVE', hits, 0
    confirmation_eligible = signal.get('cashConfirmationEligible')
    if confirmation_eligible is None:
        confirmation_eligible = signal.get('cashConfirmation')
    if (strength >= 80 and domains >= 3 and confirmation_eligible
            and (prior_state == 'ARMED' or hits >= 3)):
        if prior_state in ('CONFIRMED', 'ACTIVE'):
            return 'ACTIVE', hits, 0
        return 'CONFIRMED', hits, 0
    if prior_state == 'CONFIRMED':
        return 'CONFIRMED', hits, 0
    if strength >= 70 and domains >= 3 and hits >= 2:
        return 'ARMED', hits, 0
    if prior_state == 'ARMED':
        return 'ARMED', hits, 0
    if qualified:
        return 'WATCH', hits, 0
    if prior_state == 'WATCH' and strength >= 45:
        return 'WATCH', hits, 0
    return 'OBSERVATION', hits, misses


def _state_row(row: tuple | None) -> dict | None:
    if not row:
        return None
    keys = ('signal_id', 'direction', 'state', 'first_seen_at', 'changed_at', 'last_seen_at',
            'strength', 'evidence_quality', 'consecutive_hits', 'miss_count', 'dedupe_key', 'event_json')
    return dict(zip(keys, row))


def _tier(state: str) -> str:
    return {'WATCH': 'info', 'ARMED': 'watch', 'CONFIRMED': 'warning', 'ACTIVE': 'critical',
            'CONFLICT': 'watch', 'RECOVERY': 'info', 'INVALIDATED': 'info'}.get(state, 'observation')


def process_context(context: dict, pulse: dict, *, memory_snapshot: dict | None = None,
                    market_history: Any = None, db_path: str = DB_PATH,
                    now: datetime | None = None) -> dict[str, Any]:
    evaluated = evaluate_context(context, pulse, memory_snapshot=memory_snapshot, now=now)
    as_of = str(evaluated.get('asOf') or _iso_now(now))
    observation_key = str(evaluated.get('observationKey') or as_of)
    run_at = now or datetime.now(timezone.utc)
    created_at = _iso_now(run_at)
    candidate_expiry = _twse_expiry_contract(run_at)
    market_ref = _market_reference(pulse, as_of)
    _init_db(db_path)
    new_events: list[dict] = []
    persisted: list[dict] = []
    with closing(sqlite3.connect(db_path, timeout=10)) as conn:
        with conn:
            for signal in evaluated.get('signals') or []:
                signal_id = str(signal['signalId'])
                direction = str(signal.get('direction') or 'mixed')
                previous = _state_row(conn.execute(
                    'SELECT signal_id,direction,state,first_seen_at,changed_at,last_seen_at,strength,'
                    'evidence_quality,consecutive_hits,miss_count,dedupe_key,event_json '
                    'FROM signal_state WHERE signal_id=?', (signal_id,)).fetchone())
                exists = conn.execute(
                    'SELECT 1 FROM signal_observations WHERE signal_id=? AND direction=? '
                    'AND (observation_key=? OR (observation_key IS NULL AND as_of=?))',
                    (signal_id, direction, observation_key, as_of)).fetchone() is not None
                state, hits, misses = _target_state(signal, previous, exists)
                first_seen = (previous or {}).get('first_seen_at') or created_at
                if (previous and str(previous.get('state') or '') in
                        ('RECOVERY', 'INVALIDATED', 'EXPIRED', 'OBSERVATION') and
                        state in _TRACKED_STATES and not exists):
                    first_seen = created_at
                changed_at = ((previous or {}).get('changed_at') or created_at)
                from_state = (previous or {}).get('state') or 'OBSERVATION'
                changed = state != from_state
                if changed:
                    changed_at = created_at
                dedupe = f'{signal_id}:{direction}:{state}:{observation_key}'
                expiry_contract = _stable_expiry_contract(
                    candidate_expiry, previous, same_observation=exists)
                enriched = {
                    **signal, 'state': state, 'tier': _tier(state),
                    'firstSeenAt': first_seen, 'changedAt': changed_at, 'lastSeenAt': created_at,
                    'expiresAt': expiry_contract['expiresAt'],
                    'expiry': expiry_contract['expiry'],
                    'consecutiveHits': hits, 'missCount': misses, 'dedupeKey': dedupe,
                    'policyVersion': POLICY_VERSION, 'engineVersion': ENGINE_VERSION,
                    'temporalContext': evaluated.get('temporalContext') or {},
                    'observationKey': observation_key,
                    'shadowOnly': True, 'actionAuthority': 'none',
                }
                raw = json.dumps(enriched, ensure_ascii=False, separators=(',', ':'), default=str)
                conn.execute('INSERT OR IGNORE INTO signal_observations('
                             'signal_id,direction,as_of,observation_key,strength,domains,qualified,snapshot_json) '
                             'VALUES(?,?,?,?,?,?,?,?)',
                             (signal_id, direction, as_of, observation_key,
                              signal.get('strength'), signal.get('independentDomains'),
                              int((signal.get('strength') or 0) >= 55 and (signal.get('independentDomains') or 0) >= 2), raw))
                conn.execute('INSERT INTO signal_state(signal_id,direction,state,first_seen_at,changed_at,last_seen_at,'
                             'strength,evidence_quality,consecutive_hits,miss_count,dedupe_key,event_json) '
                             'VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(signal_id) DO UPDATE SET '
                             'direction=excluded.direction,state=excluded.state,first_seen_at=excluded.first_seen_at,'
                             'changed_at=excluded.changed_at,last_seen_at=excluded.last_seen_at,strength=excluded.strength,'
                             'evidence_quality=excluded.evidence_quality,consecutive_hits=excluded.consecutive_hits,'
                             'miss_count=excluded.miss_count,dedupe_key=excluded.dedupe_key,event_json=excluded.event_json',
                             (signal_id, direction, state, first_seen, changed_at, created_at,
                              signal.get('strength'), signal.get('evidenceQuality'), hits, misses, dedupe, raw))
                if changed and not exists:
                    event_id = hashlib.sha256(f'{dedupe}:{from_state}'.encode()).hexdigest()[:24]
                    event = {
                        'eventId': event_id, 'signalId': signal_id, 'label': signal.get('label'),
                        'direction': direction, 'fromState': from_state, 'toState': state,
                        'tier': _tier(state), 'asOf': as_of, 'createdAt': created_at,
                        'observationKey': observation_key,
                        'expiresAt': enriched['expiresAt'], 'expiry': enriched['expiry'],
                        'strength': signal.get('strength'),
                        'evidenceQuality': signal.get('evidenceQuality'),
                        'independentDomains': signal.get('independentDomains'),
                        'reasons': signal.get('reasons') or [],
                        'strongestCounterEvidence': signal.get('strongestCounterEvidence') or [],
                        'confirmation': signal.get('confirmation'), 'invalidation': signal.get('invalidation'),
                        'cashConfirmation': signal.get('cashConfirmation'),
                        'cashConfirmationEligible': signal.get('cashConfirmationEligible'),
                        'confirmationSessionDate': signal.get('confirmationSessionDate'),
                        'horizon': signal.get('horizon'),
                        'temporalContext': evaluated.get('temporalContext') or {},
                        'evidenceIds': signal.get('evidenceIds') or [], 'dedupeKey': dedupe,
                        'policyVersion': POLICY_VERSION, 'engineVersion': ENGINE_VERSION,
                        'shadowOnly': True, 'actionAuthority': 'none',
                    }
                    event_raw = json.dumps(event, ensure_ascii=False, separators=(',', ':'), default=str)
                    conn.execute('INSERT OR IGNORE INTO signal_events(event_id,signal_id,direction,from_state,to_state,'
                                 'tier,as_of,created_at,dedupe_key,event_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                 (event_id, signal_id, direction, from_state, state, event['tier'], as_of,
                                  created_at, dedupe, event_raw))
                    if state in ('WATCH', 'ARMED', 'CONFIRMED', 'ACTIVE', 'CONFLICT', 'RECOVERY', 'INVALIDATED'):
                        new_events.append(event)
                persisted.append(enriched)
            try:
                _sync_market_sessions(conn, market_history, created_at)
                _enroll_trials(conn, persisted, market_ref, created_at)
                _resolve_trials(conn, created_at)
                prospective = _prospective_summary_conn(conn)
            except Exception as exc:
                # Validation is observational.  A ledger migration or write
                # failure must never suppress the canonical signal state.
                prospective = _empty_prospective('unavailable', type(exc).__name__)
            conn.execute('DELETE FROM signal_observations WHERE id NOT IN '
                         '(SELECT id FROM signal_observations ORDER BY id DESC LIMIT 2000)')
            conn.execute('DELETE FROM signal_events WHERE id NOT IN '
                         '(SELECT id FROM signal_events ORDER BY id DESC LIMIT 500)')
    visible_signals = [_effective_signal_view(row, run_at) for row in persisted]
    evaluated['signals'] = visible_signals
    evaluated['newEvents'] = new_events
    evaluated['activeEvents'] = [row for row in visible_signals if _is_active_signal(row)]
    evaluated['prospectiveValidation'] = prospective
    return evaluated


def active(path: str = DB_PATH, *, now: datetime | str | None = None) -> dict[str, Any]:
    try:
        _init_db(path)
        with closing(sqlite3.connect(path, timeout=10)) as conn:
            rows = conn.execute('SELECT event_json FROM signal_state ORDER BY changed_at DESC').fetchall()
        signals = [
            _effective_signal_view(json.loads(row[0]), now)
            for row in rows if row and row[0]
        ]
        return {'ok': True, 'contractVersion': CONTRACT_VERSION, 'model': ENGINE_VERSION,
                'shadowOnly': True, 'signals': signals,
                'activeEvents': [row for row in signals if _is_active_signal(row)]}
    except Exception as exc:
        return {'ok': False, 'error': str(exc), 'signals': [], 'activeEvents': []}


def history(n: int = 80, path: str = DB_PATH) -> dict[str, Any]:
    n = max(1, min(int(n or 80), 500))
    try:
        _init_db(path)
        with closing(sqlite3.connect(path, timeout=10)) as conn:
            rows = conn.execute('SELECT event_json FROM signal_events ORDER BY id DESC LIMIT ?', (n,)).fetchall()
        return {'ok': True, 'contractVersion': CONTRACT_VERSION, 'model': ENGINE_VERSION,
                'shadowOnly': True, 'events': [json.loads(row[0]) for row in rows if row and row[0]]}
    except Exception as exc:
        return {'ok': False, 'error': str(exc), 'events': []}


def performance(n: int = 80, path: str = DB_PATH,
                signal_id: str | None = None) -> dict[str, Any]:
    """Read-only prospective evidence; empirical rates stay hidden below n=20."""
    n = max(1, min(int(n or 80), 500))
    clean_signal = str(signal_id or '').strip() or None
    try:
        _init_db(path)
        with closing(sqlite3.connect(path, timeout=10)) as conn:
            summary = _prospective_summary_conn(conn, clean_signal)
            query = (
                'SELECT trial_id,trial_json FROM signal_trials'
                + (' WHERE signal_id=?' if clean_signal else ' WHERE signal_id IN (?,?)')
                + ' ORDER BY origin_session DESC,created_at DESC LIMIT ?'
            )
            params: tuple[Any, ...] = ((clean_signal, n) if clean_signal else (*_HEADLINE_SIGNAL_IDS, n))
            trial_rows = conn.execute(query, params).fetchall()
            trials = []
            for trial_id, trial_raw in trial_rows:
                trial = json.loads(trial_raw) if trial_raw else {'trialId': trial_id}
                outcomes = conn.execute(
                    'SELECT outcome_json FROM signal_outcomes WHERE trial_id=? '
                    'ORDER BY horizon_sessions ASC', (trial_id,),
                ).fetchall()
                trial['outcomes'] = [json.loads(row[0]) for row in outcomes if row and row[0]]
                trials.append(trial)
        return {**summary, 'trials': trials, 'returnedTrials': len(trials)}
    except Exception as exc:
        return {**_empty_prospective('unavailable', type(exc).__name__), 'trials': []}


def empty(reason: str = 'NOT_EVALUATED') -> dict[str, Any]:
    return {
        'ok': False, 'contractVersion': CONTRACT_VERSION, 'model': ENGINE_VERSION,
        'policyVersion': POLICY_VERSION, 'shadowOnly': True, 'actionAuthority': 'none',
        'status': 'INSUFFICIENT_DATA', 'signals': [], 'newEvents': [], 'activeEvents': [],
        'temporalContext': {},
        'thresholds': {
            'watchStrength': 55, 'watchIndependentDomains': 2,
            'armedStrength': 70, 'armedIndependentDomains': 3,
            'confirmedStrength': 80, 'confirmedIndependentDomains': 3,
        },
        'familyScores': [], 'dataQuality': {'reason': reason, 'strengthIsProbability': False},
        'prospectiveValidation': _empty_prospective(),
    }

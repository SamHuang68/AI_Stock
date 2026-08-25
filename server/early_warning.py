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
CONTRACT_VERSION = 1
ENGINE_VERSION = 'st-market-precursor/v1'
POLICY_VERSION = 'shadow-lifecycle/2026-08-v1'

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


def _family(identifier: str, value: float | None, quality: float, reasons: list[str],
            evidence_ids: list[str], observed: dict | None = None) -> dict[str, Any]:
    available = value is not None and quality > 0
    return {
        'id': identifier,
        'value': round(_clamp(value), 4) if available else None,
        'quality': round(_clamp(quality, 0.0, 1.0), 3) if available else 0.0,
        'available': available,
        'reasons': reasons,
        'evidenceIds': evidence_ids,
        'observed': observed or {},
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
    return _family('globalTech', value, min(1.0, total),
                   [f'國際科技鏈{direction}（{len(parts)}/4）'], ['global.tech'], observed)


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
    return _family('anchor', value, quality, [reason], ['anchor.2330_0050'], observed)


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
    return _family('memoryCycle', value, min(1.0, total), [direction],
                   [f'shadow.overnight_intraday.{market.lower()}' for _, _, market in parts], observed)


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
    return _family('breadthLiquidity', value, min(1.0, total), [direction],
                   ['breadth.stock_scope', 'breadth.velocity', 'sector.participation'],
                   {'advRatio': adv, 'velocity3': raw.get('velocity3'), 'velocity5': raw.get('velocity5')})


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
    return _family('flowDerivatives', value, min(1.0, total), [direction],
                   ['flow.institutional', 'flow.tx_oi', 'txf.live'],
                   {'institutionalNetYi': raw.get('institutionalNetYi'),
                    'txOiChangePct': raw.get('txOiChangePct'), 'txfChangePct': txf})


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


def _signal(signal_id: str, label: str, direction: str, strength: float, domains: int,
            quality: float, reasons: list[str], counters: list[str], evidence_ids: list[str],
            context: dict, pulse: dict) -> dict[str, Any]:
    twii = _quote_change(_market_quote(pulse, '^TWII'))
    breadth = _number(((((context.get('scenario') or {}).get('breadth') or {}).get('raw') or {}).get('advRatio')))
    cash_confirmed = bool(
        direction == 'upside' and twii is not None and twii > 0 and breadth is not None and breadth >= 0.55
        or direction == 'downside' and twii is not None and twii < 0 and breadth is not None and breadth <= 0.45)
    return {
        'signalId': signal_id, 'label': label, 'direction': direction,
        'strength': round(strength, 1), 'independentDomains': int(domains),
        'evidenceQuality': round(quality, 3), 'reasons': reasons,
        'strongestCounterEvidence': counters,
        'evidenceIds': sorted(set(evidence_ids)),
        'cashConfirmation': cash_confirmed,
        'observed': {'twiiChangePct': twii, 'advRatio': breadth},
        'confirmation': ('台股現貨方向與上市廣度同向確認' if cash_confirmed else '等待台股現貨與廣度同向確認'),
        'invalidation': '訊號強度連續三次低於 45，或核心方向反轉',
        'horizon': 'next_session_to_5_sessions',
    }


def evaluate_context(context: dict, pulse: dict, *, memory_snapshot: dict | None = None) -> dict[str, Any]:
    """Pure evaluation.  Returned strengths are evidence strength, not probability."""
    families = [
        _global_family(pulse), _anchor_family(context, pulse), _memory_family(memory_snapshot),
        _breadth_family(context), _flow_family(context, pulse),
    ]
    completeness = _number((context.get('dataQuality') or {}).get('completeness')) or 0.0
    freshness = _number((context.get('dataQuality') or {}).get('freshness')) or 0.0
    available_weight = sum(_WEIGHTS[row['id']] * float(row.get('quality') or 0)
                           for row in families if row.get('available'))
    evidence_quality = _clamp(available_weight * completeness * (0.55 + 0.45 * freshness), 0.0, 1.0)
    up_strength, up_domains, up_reasons, up_counters = _direction_strength(families, 'upside')
    down_strength, down_domains, down_reasons, down_counters = _direction_strength(families, 'downside')
    evidence_ids = [eid for row in families for eid in row.get('evidenceIds') or []]
    signals = [
        _signal('TW_DOWNSIDE_PRECURSOR', '台股下跌前兆', 'downside', down_strength, down_domains,
                evidence_quality, down_reasons, down_counters, evidence_ids, context, pulse),
        _signal('TW_ATTACK_BUILDUP', '台股強攻蓄勢', 'upside', up_strength, up_domains,
                evidence_quality, up_reasons, up_counters, evidence_ids, context, pulse),
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
                               reasons, counters, selected_ids, context, pulse))
    conflict = up_strength >= 55 and down_strength >= 55
    return {
        'ok': bool(context.get('ok')),
        'contractVersion': CONTRACT_VERSION, 'model': ENGINE_VERSION,
        'policyVersion': POLICY_VERSION, 'shadowOnly': True,
        'actionAuthority': 'none', 'asOf': context.get('asOf') or pulse.get('updatedAt'),
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
                         'strength REAL,domains INTEGER,qualified INTEGER,snapshot_json TEXT,'
                         'UNIQUE(signal_id,direction,as_of))')
            conn.execute('CREATE TABLE IF NOT EXISTS signal_events('
                         'id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE,signal_id TEXT,direction TEXT,'
                         'from_state TEXT,to_state TEXT,tier TEXT,as_of TEXT,created_at TEXT,dedupe_key TEXT,event_json TEXT)')


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
    if (strength >= 80 and domains >= 3 and signal.get('cashConfirmation')
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
                    db_path: str = DB_PATH, now: datetime | None = None) -> dict[str, Any]:
    evaluated = evaluate_context(context, pulse, memory_snapshot=memory_snapshot)
    as_of = str(evaluated.get('asOf') or _iso_now(now))
    created_at = _iso_now(now)
    expires_at = (now or datetime.now(timezone.utc)) + timedelta(hours=24)
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
                    'SELECT 1 FROM signal_observations WHERE signal_id=? AND direction=? AND as_of=?',
                    (signal_id, direction, as_of)).fetchone() is not None
                state, hits, misses = _target_state(signal, previous, exists)
                first_seen = (previous or {}).get('first_seen_at') or created_at
                changed_at = ((previous or {}).get('changed_at') or created_at)
                from_state = (previous or {}).get('state') or 'OBSERVATION'
                changed = state != from_state
                if changed:
                    changed_at = created_at
                dedupe = f'{signal_id}:{direction}:{state}:{as_of[:10]}'
                enriched = {
                    **signal, 'state': state, 'tier': _tier(state),
                    'firstSeenAt': first_seen, 'changedAt': changed_at, 'lastSeenAt': created_at,
                    'expiresAt': expires_at.astimezone(timezone.utc).isoformat(),
                    'consecutiveHits': hits, 'missCount': misses, 'dedupeKey': dedupe,
                    'policyVersion': POLICY_VERSION, 'engineVersion': ENGINE_VERSION,
                    'shadowOnly': True, 'actionAuthority': 'none',
                }
                raw = json.dumps(enriched, ensure_ascii=False, separators=(',', ':'), default=str)
                conn.execute('INSERT OR IGNORE INTO signal_observations('
                             'signal_id,direction,as_of,strength,domains,qualified,snapshot_json) VALUES(?,?,?,?,?,?,?)',
                             (signal_id, direction, as_of, signal.get('strength'), signal.get('independentDomains'),
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
                        'expiresAt': enriched['expiresAt'], 'strength': signal.get('strength'),
                        'evidenceQuality': signal.get('evidenceQuality'),
                        'independentDomains': signal.get('independentDomains'),
                        'reasons': signal.get('reasons') or [],
                        'strongestCounterEvidence': signal.get('strongestCounterEvidence') or [],
                        'confirmation': signal.get('confirmation'), 'invalidation': signal.get('invalidation'),
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
            conn.execute('DELETE FROM signal_observations WHERE id NOT IN '
                         '(SELECT id FROM signal_observations ORDER BY id DESC LIMIT 2000)')
            conn.execute('DELETE FROM signal_events WHERE id NOT IN '
                         '(SELECT id FROM signal_events ORDER BY id DESC LIMIT 500)')
    evaluated['signals'] = persisted
    evaluated['newEvents'] = new_events
    evaluated['activeEvents'] = [row for row in persisted if row.get('state') not in
                                 ('OBSERVATION', 'RECOVERY', 'INVALIDATED', 'EXPIRED')]
    return evaluated


def active(path: str = DB_PATH) -> dict[str, Any]:
    try:
        _init_db(path)
        with closing(sqlite3.connect(path, timeout=10)) as conn:
            rows = conn.execute('SELECT event_json FROM signal_state ORDER BY changed_at DESC').fetchall()
        signals = [json.loads(row[0]) for row in rows if row and row[0]]
        return {'ok': True, 'contractVersion': CONTRACT_VERSION, 'model': ENGINE_VERSION,
                'shadowOnly': True, 'signals': signals,
                'activeEvents': [row for row in signals if row.get('state') not in
                                 ('OBSERVATION', 'RECOVERY', 'INVALIDATED', 'EXPIRED')]}
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


def empty(reason: str = 'NOT_EVALUATED') -> dict[str, Any]:
    return {
        'ok': False, 'contractVersion': CONTRACT_VERSION, 'model': ENGINE_VERSION,
        'policyVersion': POLICY_VERSION, 'shadowOnly': True, 'actionAuthority': 'none',
        'status': 'INSUFFICIENT_DATA', 'signals': [], 'newEvents': [], 'activeEvents': [],
        'familyScores': [], 'dataQuality': {'reason': reason, 'strengthIsProbability': False},
    }

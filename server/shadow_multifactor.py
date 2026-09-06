#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 shadow-only multifactor cross-sectional ranking research surface.

Default OFF via ``shadowMultifactor``. Never writes Decision / exposure envelopes.
Isolated from ``llm_gate`` — no LLM scores, no local-deep stampede.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Callable

from conditional_expectation import (
    BIN_MODEL_ID,
    _bars_upto_date,
    _deviation_z,
    _relative_strength_percentile,
    _session_date_from_ts,
    aggregate_horizon_stats,
    bin_state,
    evaluate_asof_gate,
    load_chip_inst_history,
    regime_at_date,
)
from feature_settings import is_enabled
from postmarket_report import tech_summary_from_bars
from promotion_gate import FEATURE_COUNT_CAP, default_fail_payload, evaluate as evaluate_promotion_gate

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:  # pragma: no cover
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))

CONTRACT_VERSION = 1
MODEL_VERSION = 'st-shadow-multifactor/v1'
EPISTEMIC_RANKING = 'CONDITIONAL'
EPISTEMIC_ML_STUB = 'HYPOTHESIS'
LONG_HORIZONS = (60, 120)
SHORT_HORIZONS = (1, 5, 20)
DEFAULT_SCAN_SYMBOLS = (
    '2330', '2317', '2454', '2303', '2382', '3711', '3008', '2891', '2881', '2882',
    '2412', '1301', '1303', '1216', '2002', '2886', '2884', '2308', '2357', '3034',
)
MAX_SCAN = 40
MIN_BARS = 140

FACTOR_WEIGHTS = {
    'deviationZ': 0.30,
    'relativeStrengthPct': 0.35,
    'momentum60d': 0.20,
    'volRatio': -0.15,
}

ML_STUB_WEIGHTS = {
    'deviationZ': 0.25,
    'relativeStrengthPct': 0.30,
    'momentum60d': 0.25,
    'volRatio': -0.10,
    'rsi14Centered': 0.10,
}


def disabled_payload(reason: str = 'SHADOW_DISABLED') -> dict[str, Any]:
    return {
        'ok': False,
        'enabled': False,
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'predictiveProbability': False,
        'epistemic': EPISTEMIC_RANKING,
        'contractVersion': CONTRACT_VERSION,
        'model': MODEL_VERSION,
        'status': 'DISABLED',
        'reason': reason,
        'ranking': None,
        'longHorizonCards': [],
        'mlExperiment': None,
        'promotionGate': default_fail_payload(),
        'nonGoals': _non_goals(),
    }


def _non_goals() -> list[str]:
    return [
        'No production Decision wiring',
        'No guaranteed-alpha marketing copy',
        'No LLM Decision scores',
        'No llm_gate acquisition',
        'No exposure envelope mutation',
    ]


def _momentum_return(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    base = closes[-1 - period]
    if base <= 0:
        return None
    return (closes[-1] / base - 1.0) * 100.0


def _factor_vector(
    symbol: str,
    *,
    bars: list,
    as_of: date,
    chip_inst_by_date: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    pit = _bars_upto_date(bars, as_of)
    if len(pit) < MIN_BARS:
        return None
    closes = [float(row[4]) for row in pit if row and row[4] is not None]
    if len(closes) < MIN_BARS:
        return None
    tech = tech_summary_from_bars(pit) or {}
    devz = _deviation_z(closes)
    rs_pct = _relative_strength_percentile(closes)
    mom60 = _momentum_return(closes, 60)
    vol_ratio = tech.get('volRatio')
    rsi14 = tech.get('rsi14')
    state = bin_state(
        symbol,
        as_of,
        bars=bars,
        chip_inst_by_date=chip_inst_by_date,
        regime_id=regime_at_date(as_of),
    )
    factors = {
        'deviationZ': round(devz, 4) if devz is not None else None,
        'relativeStrengthPct': round(rs_pct, 2) if rs_pct is not None else None,
        'momentum60d': round(mom60, 4) if mom60 is not None else None,
        'volRatio': round(float(vol_ratio), 4) if vol_ratio is not None else None,
        'rsi14': round(float(rsi14), 2) if rsi14 is not None else None,
    }
    usable = [key for key, value in factors.items() if value is not None and math.isfinite(float(value))]
    if len(usable) < 3:
        return None
    return {
        'symbol': str(symbol).strip().upper(),
        'asOfDate': as_of.isoformat(),
        'binId': state.get('binId'),
        'binModelId': BIN_MODEL_ID,
        'factors': factors,
        'featureCount': len(usable),
        'evidenceAsOf': state.get('evidenceAsOf') or {},
    }


def _normalize_factor(key: str, value: float | None) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    if key == 'deviationZ':
        return max(-2.0, min(2.0, float(value))) / 2.0
    if key == 'relativeStrengthPct':
        return (float(value) - 50.0) / 50.0
    if key == 'momentum60d':
        return max(-30.0, min(30.0, float(value))) / 30.0
    if key == 'volRatio':
        return max(-1.0, min(1.0, (float(value) - 1.0)))
    return 0.0


def research_score(factors: dict[str, float | None]) -> float:
    """Bounded composite research score in [-1, 1]; CONDITIONAL, not alpha."""
    total = 0.0
    weight_sum = 0.0
    for key, weight in FACTOR_WEIGHTS.items():
        norm = _normalize_factor(key, factors.get(key))
        total += norm * weight
        weight_sum += abs(weight)
    if weight_sum <= 0:
        return 0.0
    raw = total / weight_sum
    return round(max(-1.0, min(1.0, raw)), 4)


def ml_experiment_stub(factors: dict[str, float | None]) -> dict[str, Any]:
    """Lightweight fixed-weight linear stub — HYPOTHESIS tier, not production ML."""
    rsi = factors.get('rsi14')
    rsi_centered = None
    if rsi is not None and math.isfinite(float(rsi)):
        rsi_centered = (float(rsi) - 50.0) / 50.0
    extended = dict(factors)
    extended['rsi14Centered'] = rsi_centered
    total = 0.0
    weight_sum = 0.0
    for key, weight in ML_STUB_WEIGHTS.items():
        value = extended.get(key)
        if value is None or not math.isfinite(float(value)):
            continue
        if key == 'rsi14Centered':
            norm = max(-1.0, min(1.0, float(value)))
        else:
            norm = _normalize_factor(key, float(value))
        total += norm * weight
        weight_sum += abs(weight)
    score = round(total / weight_sum, 4) if weight_sum > 0 else 0.0
    return {
        'status': 'EXPERIMENT_STUB',
        'epistemic': EPISTEMIC_ML_STUB,
        'model': 'st-ml-linear-stub/v0',
        'score': score,
        'weights': ML_STUB_WEIGHTS,
        'disclaimer': 'Fixed-weight research stub only; not walk-forward validated.',
    }


def _forward_outcome(rows: list, origin_idx: int, horizon: int) -> dict[str, float] | None:
    if origin_idx < 0 or origin_idx + horizon >= len(rows):
        return None
    entry = float(rows[origin_idx][4])
    if entry <= 0:
        return None
    exit_close = float(rows[origin_idx + horizon][4])
    path = [float(rows[j][4]) for j in range(origin_idx + 1, origin_idx + horizon + 1)]
    worst = 0.0
    for price in path:
        drawdown = (float(price) / float(entry) - 1.0) * 100.0
        if drawdown < worst:
            worst = drawdown
    return {'returnPct': (exit_close / entry - 1.0) * 100.0, 'maxDrawdownPct': worst}


def _collect_long_horizon_observations(
    symbol: str,
    bars: list,
    *,
    chip_inst_by_date: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    rows = [r for r in (bars or []) if r and r[4] is not None]
    max_h = max(LONG_HORIZONS)
    if len(rows) < MIN_BARS + max_h:
        return []
    chip_map = chip_inst_by_date or {}
    observations: list[dict[str, Any]] = []
    for idx in range(MIN_BARS - 1, len(rows) - max_h):
        session = _session_date_from_ts(rows[idx][0])
        state = bin_state(
            symbol,
            session,
            bars=rows,
            chip_inst_by_date=chip_map,
            regime_id=regime_at_date(session),
        )
        outcomes: dict[str, dict[str, float]] = {}
        for horizon in LONG_HORIZONS:
            outcome = _forward_outcome(rows, idx, horizon)
            if outcome is not None:
                outcomes[str(horizon)] = outcome
        if not outcomes:
            continue
        observations.append({
            'sessionDate': session.isoformat(),
            'binId': state['binId'],
            'binModelId': state['binModelId'],
            'outcomes': outcomes,
        })
    return observations


def _long_horizon_card(
    symbol: str,
    *,
    bars: list,
    chip_inst_by_date: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    observations = _collect_long_horizon_observations(
        symbol,
        bars,
        chip_inst_by_date=chip_inst_by_date,
    )
    if not observations:
        return None
    current = observations[-1]
    horizons: dict[str, Any] = {}
    for horizon in LONG_HORIZONS:
        key = str(horizon)
        returns = [
            float(row['outcomes'][key]['returnPct'])
            for row in observations
            if key in row.get('outcomes', {})
        ]
        drawdowns = [
            float(row['outcomes'][key]['maxDrawdownPct'])
            for row in observations
            if key in row.get('outcomes', {})
        ]
        horizons[key] = aggregate_horizon_stats(returns, drawdowns)
    return {
        'symbol': symbol,
        'epistemic': EPISTEMIC_RANKING,
        'horizons': horizons,
        'binId': current.get('binId'),
        'binModelId': current.get('binModelId'),
        'label': f'Long-horizon conditional stats H∈{{{",".join(str(h) for h in LONG_HORIZONS)}}}',
    }


def _load_bars(symbol: str) -> list:
    try:
        import datastore
        return datastore.get_bars(symbol, market='TW') or []
    except Exception:
        return []


def rank_cross_section(
    symbols: list[str],
    *,
    as_of: date | None = None,
    now: datetime | None = None,
    quote_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    chips_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    limit: int = 20,
    include_ml: bool = False,
    base_dir: str | None = None,
) -> dict[str, Any]:
    from conditional_expectation import _last_tw_close_day

    now = now or datetime.now(TZ_TPE)
    as_of = as_of or _last_tw_close_day(now)

    rows: list[dict[str, Any]] = []
    stale_count = 0
    scan = [str(s).strip().upper() for s in symbols if str(s).strip()][:MAX_SCAN]
    for code in scan:
        bars = _load_bars(code)
        chips = chips_lookup(code) if chips_lookup else None
        chip_map = load_chip_inst_history(code, current_chip=chips)
        vector = _factor_vector(code, bars=bars, as_of=as_of, chip_inst_by_date=chip_map)
        if vector is None:
            continue
        quote = quote_lookup(code) if quote_lookup else {'asOf': vector['evidenceAsOf'].get('quote')}
        gate = evaluate_asof_gate(quote=quote, chips=chips, now=now)
        score = research_score(vector['factors'])
        degraded = not gate.get('usable')
        if degraded:
            stale_count += 1
        item = {
            'symbol': code,
            'rankScore': score if not degraded else round(score * 0.5, 4),
            'epistemic': EPISTEMIC_RANKING,
            'factors': vector['factors'],
            'binId': vector.get('binId'),
            'featureCount': vector.get('featureCount'),
            'asOfGate': gate,
            'degraded': degraded,
            'label': 'CONDITIONAL research rank — not Decision alpha',
        }
        if include_ml and is_enabled('shadowMlExperiment', base_dir):
            item['mlExperiment'] = ml_experiment_stub(vector['factors'])
        rows.append(item)

    rows.sort(key=lambda row: row['rankScore'], reverse=True)
    capped = rows[: max(1, min(int(limit), MAX_SCAN))]
    feature_names = list(FACTOR_WEIGHTS.keys())
    gate_bundle = {
        'features': feature_names,
        'featureCount': len(feature_names),
    }
    return {
        'epistemic': EPISTEMIC_RANKING,
        'asOfDate': as_of.isoformat(),
        'model': MODEL_VERSION,
        'binModelId': BIN_MODEL_ID,
        'universeSize': len(scan),
        'qualified': len(rows),
        'staleDegraded': stale_count,
        'basket': capped,
        'horizons': {
            'short': list(SHORT_HORIZONS),
            'long': list(LONG_HORIZONS),
        },
        'promotionGate': evaluate_promotion_gate(gate_bundle),
        'nonGoals': _non_goals(),
    }


def build_research_snapshot(
    *,
    symbols: list[str] | None = None,
    limit: int = 15,
    long_horizon_symbols: list[str] | None = None,
    now: datetime | None = None,
    base_dir: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(TZ_TPE)
    from conditional_expectation import _last_tw_close_day
    as_of = _last_tw_close_day(now)
    scan = list(symbols or DEFAULT_SCAN_SYMBOLS)
    include_ml = is_enabled('shadowMlExperiment', base_dir)
    ranking = rank_cross_section(
        scan,
        as_of=as_of,
        now=now,
        limit=limit,
        include_ml=include_ml,
        base_dir=base_dir,
    )
    lh_symbols = long_horizon_symbols or [row['symbol'] for row in ranking['basket'][:3]]
    long_cards: list[dict[str, Any]] = []
    for code in lh_symbols[:5]:
        bars = _load_bars(code)
        chip_map = load_chip_inst_history(code)
        card = _long_horizon_card(code, bars=bars, chip_inst_by_date=chip_map)
        if card:
            long_cards.append(card)
    ml_block = None
    if include_ml:
        ml_block = {
            'enabled': True,
            'epistemic': EPISTEMIC_ML_STUB,
            'status': 'EXPERIMENT_STUB',
            'featureCountCap': FEATURE_COUNT_CAP,
            'note': 'Per-symbol mlExperiment attached when shadowMlExperiment flag is ON.',
        }
    return {
        'ok': True,
        'enabled': True,
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'predictiveProbability': False,
        'contractVersion': CONTRACT_VERSION,
        'model': MODEL_VERSION,
        'status': 'READY',
        'ranking': ranking,
        'longHorizonCards': long_cards,
        'mlExperiment': ml_block,
        'flags': {
            'shadowMultifactor': True,
            'shadowMlExperiment': include_ml,
        },
        'promotionGate': ranking.get('promotionGate') or default_fail_payload(),
        'nonGoals': _non_goals(),
    }

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shadow-only Conditional Expectation card (rule bins, not LLM scores).

P0 Slice 1: point-in-time rule-bin conditional statistics behind
``shadowConditionalExpectation`` (default OFF).  See
docs/FINDINGS_CONDITIONAL_EXPECTATION_P0.md for methodology and leakage notes.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Callable

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:  # pragma: no cover
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))

from postmarket_report import staleness as _quote_staleness
from postmarket_report import tech_summary_from_bars

CONTRACT_VERSION = 1
BIN_MODEL_ID = 'rsi14×devz×rs×inst3d×regime/v2'
MODEL_VERSION = 'st-conditional-expectation/pit-v2'
RETURN_CONVENTION = 'close_to_close_same_symbol'
EPISTEMIC = 'CONDITIONAL'
HORIZONS = (1, 5, 20)
MIN_SAMPLE = 20
MIN_OBSERVATION_BARS = 20
CHIP_MAX_LAG_SESSIONS = 2

if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DECISION_DB_PATH = os.path.join(_BASE, 'data', 'decision_history.db')
CHIP_HISTORY_PATH = os.path.join(_BASE, 'data', 'chip_history')


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ_TPE)
        return parsed.astimezone(TZ_TPE)
    except (TypeError, ValueError):
        return None


def _chip_session_date(chip_as_of: Any) -> date | None:
    raw = str(chip_as_of or '').strip()
    if not raw:
        return None
    if len(raw) == 8 and raw.isdigit():
        raw = f'{raw[:4]}-{raw[4:6]}-{raw[6:]}'
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _last_tw_close_day(now: datetime) -> date:
    local = now.astimezone(TZ_TPE)
    day = local.date()
    if local.time() < dtime(13, 30):
        day = day.fromordinal(day.toordinal() - 1)
    while day.weekday() >= 5:
        day = day.fromordinal(day.toordinal() - 1)
    return day


def _session_date_from_ts(ts: float | int) -> date:
    return datetime.fromtimestamp(float(ts), TZ_TPE).date()


def _bars_upto_date(bars: list, as_of: date) -> list:
    out = []
    for row in bars or []:
        if not row or row[4] is None:
            continue
        if _session_date_from_ts(row[0]) <= as_of:
            out.append(row)
    return out


def evaluate_asof_gate(
    *,
    quote: dict[str, Any] | None,
    chips: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return whether quote/chips are fresh enough for conditional prediction use."""
    now = now or datetime.now(TZ_TPE)
    reasons: list[str] = []
    quote_reasons = _quote_staleness(quote, now) if quote else ['quote 無 asOf（資料不足）']
    if quote_reasons:
        reasons.extend(quote_reasons)

    chip_as_of = (chips or {}).get('asOf')
    chip_day = _chip_session_date(chip_as_of)
    if chips and chip_day is None:
        reasons.append('chips asOf 無法解析（籌碼日期不可用）')
    elif chip_day is not None:
        last_close = _last_tw_close_day(now)
        lag_sessions = 0
        cursor = last_close
        while cursor > chip_day and lag_sessions <= CHIP_MAX_LAG_SESSIONS + 3:
            lag_sessions += 1
            cursor = cursor.fromordinal(cursor.toordinal() - 1)
            while cursor.weekday() >= 5:
                cursor = cursor.fromordinal(cursor.toordinal() - 1)
        if lag_sessions > CHIP_MAX_LAG_SESSIONS:
            reasons.append(
                f'chips asOf {chip_as_of} 落後最近收盤日 {last_close.isoformat()} '
                f'逾 {CHIP_MAX_LAG_SESSIONS} 個交易日門檻'
            )

    usable = not reasons
    return {
        'usable': usable,
        'status': 'fresh' if usable else 'expired',
        'reasons': reasons,
        'checkedAt': now.isoformat(),
        'policy': 'quote_staleness_postmarket_v1+chip_lag_sessions',
    }


def disabled_payload(reason: str = 'SHADOW_DISABLED') -> dict[str, Any]:
    return {
        'ok': False,
        'enabled': False,
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'predictiveProbability': False,
        'epistemic': EPISTEMIC,
        'contractVersion': CONTRACT_VERSION,
        'model': MODEL_VERSION,
        'binModelId': BIN_MODEL_ID,
        'status': 'DISABLED',
        'reason': reason,
        'horizons': list(HORIZONS),
        'minimumSample': MIN_SAMPLE,
        'card': None,
    }


def _rsi_band(rsi: float | None) -> tuple[str, str]:
    if rsi is None:
        return 'unknown', 'RSI 未知'
    low = int(rsi // 10) * 10
    high = low + 10
    low = max(0, min(low, 90))
    high = min(high, 100)
    return f'rsi{low}', f'RSI {low}-{high}'


def _deviation_z(closes: list[float], period: int = 20) -> float | None:
    """Price deviation z-score: (close − SMA) / stdev(closes), PIT on provided series."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    sma = sum(window) / period
    if sma <= 0:
        return None
    variance = sum((value - sma) ** 2 for value in window) / max(1, period - 1)
    std = math.sqrt(variance)
    if std <= 0:
        return None
    return (closes[-1] - sma) / std


def _devz_band(z: float | None) -> tuple[str, str]:
    if z is None or not math.isfinite(z):
        return 'unknown', '偏離Z 未知'
    if z <= -1.0:
        return 'devz_low', f'偏離Z ≤-1 ({z:.2f})'
    if z <= 0.0:
        return 'devz_midneg', f'偏離Z (-1,0] ({z:.2f})'
    if z <= 1.0:
        return 'devz_midpos', f'偏離Z (0,1] ({z:.2f})'
    return 'devz_high', f'偏離Z >1 ({z:.2f})'


def _relative_strength_percentile(
    closes: list[float],
    *,
    ret_period: int = 20,
    min_history: int = 60,
) -> float | None:
    """Percentile rank of current ret_period return vs trailing same-length returns (price only)."""
    if len(closes) < ret_period + min_history:
        return None
    current = closes[-1] / closes[-1 - ret_period] - 1.0
    history: list[float] = []
    for idx in range(ret_period, len(closes)):
        base = closes[idx - ret_period]
        if base <= 0:
            continue
        history.append(closes[idx] / base - 1.0)
    if len(history) < min_history:
        return None
    history = history[:-1]
    if not history:
        return None
    below = sum(1 for value in history if value <= current)
    return (below / len(history)) * 100.0


def _rs_band(percentile: float | None) -> tuple[str, str]:
    if percentile is None or not math.isfinite(percentile):
        return 'rs_unknown', '相對強度 未知'
    if percentile <= 33.0:
        return 'rs_weak', f'相對強度弱 ({percentile:.0f}%)'
    if percentile <= 66.0:
        return 'rs_mid', f'相對強度中 ({percentile:.0f}%)'
    return 'rs_strong', f'相對強度強 ({percentile:.0f}%)'


def _inst3d_sign(chip_inst_by_date: dict[str, float], as_of: date) -> tuple[str, str]:
    eligible = sorted(
        (day, total)
        for day, total in (chip_inst_by_date or {}).items()
        if _chip_session_date(day) is not None and _chip_session_date(day) <= as_of
    )
    if not eligible:
        return 'unknown', '法人3日 未知'
    recent = [total for _, total in sorted(eligible, reverse=True)[:3]]
    net = sum(recent)
    if net > 0:
        return 'buy', '法人3日淨買'
    if net < 0:
        return 'sell', '法人3日淨賣'
    return 'flat', '法人3日持平'


def _normalize_regime(regime_id: str | None) -> str:
    raw = str(regime_id or '').strip().upper()
    return raw or 'UNKNOWN'


def _make_bin_id(
    rsi_key: str,
    devz_key: str,
    rs_key: str,
    inst_key: str,
    regime_key: str,
) -> str:
    return f'{rsi_key}_{devz_key}_{rs_key}_inst{inst_key}_reg{regime_key}'


def _make_bin_label(
    rsi_label: str,
    devz_label: str,
    rs_label: str,
    inst_label: str,
    regime_key: str,
) -> str:
    return f'{rsi_label} · {devz_label} · {rs_label} · {inst_label} · {regime_key}'


def load_chip_inst_history(
    symbol: str,
    *,
    chip_history_path: str = CHIP_HISTORY_PATH,
    current_chip: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Map YYYY-MM-DD → inst.total for symbol (chip_history snapshots + live chip)."""
    code = str(symbol or '').strip().upper()
    out: dict[str, float] = {}
    if os.path.isdir(chip_history_path):
        for fn in sorted(glob.glob(os.path.join(chip_history_path, '*.json'))):
            base = os.path.basename(fn)
            raw_day = base.replace('.json', '')
            if len(raw_day) == 8 and raw_day.isdigit():
                day = f'{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:]}'
            else:
                day = raw_day[:10]
            try:
                with open(fn, encoding='utf-8') as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            rec = (payload or {}).get(code)
            if not isinstance(rec, dict):
                continue
            total = rec.get('total')
            if total is not None:
                out[day] = float(total)
    if isinstance(current_chip, dict):
        inst = current_chip.get('inst') or {}
        total = inst.get('total')
        chip_day = _chip_session_date(current_chip.get('date') or current_chip.get('asOf'))
        if total is not None and chip_day is not None:
            out[chip_day.isoformat()] = float(total)
    return out


def regime_at_date(
    as_of: date,
    *,
    decision_db_path: str = DECISION_DB_PATH,
) -> str:
    """Point-in-time regime tag from decision_history (no future leakage)."""
    if not os.path.isfile(decision_db_path):
        return 'UNKNOWN'
    target = as_of.isoformat()
    try:
        with closing(sqlite3.connect(decision_db_path, timeout=5)) as conn:
            row = conn.execute(
                'SELECT regime FROM decision_history '
                'WHERE substr(as_of, 1, 10) <= ? ORDER BY as_of DESC LIMIT 1',
                (target,),
            ).fetchone()
        return _normalize_regime(row[0] if row else None)
    except sqlite3.Error:
        return 'UNKNOWN'


def bin_state(
    symbol: str,
    as_of_date: date,
    *,
    bars: list,
    chip_inst_by_date: dict[str, float] | None = None,
    regime_id: str | None = None,
) -> dict[str, Any]:
    """Compute rule-bin state using features available only on or before ``as_of_date``."""
    code = str(symbol or '').strip().upper()
    pit_bars = _bars_upto_date(bars, as_of_date)
    tech = tech_summary_from_bars(pit_bars)
    closes = [float(row[4]) for row in pit_bars if row and row[4] is not None]
    devz = _deviation_z(closes)
    rs_pct = _relative_strength_percentile(closes)
    devz_key, devz_label = _devz_band(devz)
    rs_key, rs_label = _rs_band(rs_pct)
    rsi_key, rsi_label = _rsi_band((tech or {}).get('rsi14'))
    inst_key, inst_label = _inst3d_sign(chip_inst_by_date or {}, as_of_date)
    regime_key = _normalize_regime(regime_id or regime_at_date(as_of_date))
    bin_id = _make_bin_id(rsi_key, devz_key, rs_key, inst_key, regime_key)
    return {
        'symbol': code,
        'asOfDate': as_of_date.isoformat(),
        'binModelId': BIN_MODEL_ID,
        'binId': bin_id,
        'binLabel': _make_bin_label(rsi_label, devz_label, rs_label, inst_label, regime_key),
        'features': {
            'rsi14': (tech or {}).get('rsi14'),
            'rsiBand': rsi_key,
            'deviationZ': round(devz, 4) if devz is not None else None,
            'devzBand': devz_key,
            'relativeStrengthPct': round(rs_pct, 2) if rs_pct is not None else None,
            'rsBand': rs_key,
            'volRatio': (tech or {}).get('volRatio'),
            'inst3d': inst_key,
            'regime': regime_key,
            'bars': (tech or {}).get('bars'),
            'close': (tech or {}).get('close'),
        },
        'evidenceAsOf': {
            'quote': (tech or {}).get('asOf'),
            'chips': max(
                (day for day in (chip_inst_by_date or {}) if _chip_session_date(day) and _chip_session_date(day) <= as_of_date),
                default=None,
            ),
            'regime': regime_key,
        },
    }


def _max_drawdown_pct(path_closes: list[float], entry: float) -> float:
    worst = 0.0
    for price in path_closes:
        drawdown = (float(price) / float(entry) - 1.0) * 100.0
        if drawdown < worst:
            worst = drawdown
    return worst


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def _forward_outcome(rows: list, origin_idx: int, horizon: int) -> dict[str, float] | None:
    if origin_idx < 0 or origin_idx + horizon >= len(rows):
        return None
    entry = float(rows[origin_idx][4])
    if entry <= 0:
        return None
    exit_close = float(rows[origin_idx + horizon][4])
    path = [float(rows[j][4]) for j in range(origin_idx + 1, origin_idx + horizon + 1)]
    return {
        'returnPct': (exit_close / entry - 1.0) * 100.0,
        'maxDrawdownPct': _max_drawdown_pct(path, entry),
    }


def collect_pit_observations(
    symbol: str,
    bars: list,
    *,
    chip_inst_by_date: dict[str, float] | None = None,
    regime_lookup: Callable[[date], str] | None = None,
) -> list[dict[str, Any]]:
    """Walk daily bars and emit PIT bin assignments with forward outcomes."""
    rows = [r for r in (bars or []) if r and r[4] is not None]
    if len(rows) < MIN_OBSERVATION_BARS + max(HORIZONS):
        return []
    lookup = regime_lookup or regime_at_date
    chip_map = chip_inst_by_date or {}
    observations: list[dict[str, Any]] = []
    max_h = max(HORIZONS)
    for idx in range(MIN_OBSERVATION_BARS - 1, len(rows) - max_h):
        session = _session_date_from_ts(rows[idx][0])
        state = bin_state(
            symbol,
            session,
            bars=rows,
            chip_inst_by_date=chip_map,
            regime_id=lookup(session),
        )
        outcomes: dict[str, dict[str, float]] = {}
        for horizon in HORIZONS:
            outcome = _forward_outcome(rows, idx, horizon)
            if outcome is not None:
                outcomes[str(horizon)] = outcome
        if not outcomes:
            continue
        observations.append({
            'sessionDate': session.isoformat(),
            'binId': state['binId'],
            'binModelId': state['binModelId'],
            'features': state['features'],
            'outcomes': outcomes,
        })
    return observations


def aggregate_horizon_stats(
    returns: list[float],
    drawdowns: list[float],
) -> dict[str, Any]:
    n = len(returns)
    qualified = n >= MIN_SAMPLE
    return {
        'medianReturnPct': round(_median(returns), 4) if qualified else None,
        'winRate': round(sum(1 for value in returns if value > 0) / n, 4) if qualified else None,
        'n': n,
        'maxDrawdownQ90Pct': round(_quantile(drawdowns, 0.90), 4) if qualified else None,
        'ratesAvailable': qualified,
    }


def aggregate_bin_stats(
    observations: list[dict[str, Any]],
    bin_id: str,
) -> dict[str, dict[str, Any]]:
    """Aggregate conditional stats for one bin across all horizons."""
    matched = [row for row in observations if row.get('binId') == bin_id]
    horizons: dict[str, dict[str, Any]] = {}
    for horizon in HORIZONS:
        key = str(horizon)
        returns = [
            float(row['outcomes'][key]['returnPct'])
            for row in matched
            if key in row.get('outcomes', {})
        ]
        drawdowns = [
            float(row['outcomes'][key]['maxDrawdownPct'])
            for row in matched
            if key in row.get('outcomes', {})
        ]
        horizons[key] = aggregate_horizon_stats(returns, drawdowns)
    return horizons


def _empty_horizons() -> dict[str, Any]:
    return {
        str(h): {
            'medianReturnPct': None,
            'winRate': None,
            'n': 0,
            'maxDrawdownQ90Pct': None,
            'ratesAvailable': False,
        }
        for h in HORIZONS
    }


def compute_card_stats(
    symbol: str,
    *,
    bars: list,
    chip_inst_by_date: dict[str, float] | None = None,
    as_of_date: date | None = None,
    regime_lookup: Callable[[date], str] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return (bin_state, horizons) for the symbol at ``as_of_date``."""
    rows = [r for r in (bars or []) if r and r[4] is not None]
    if not rows:
        empty = {
            'symbol': str(symbol or '').strip().upper(),
            'asOfDate': None,
            'binModelId': BIN_MODEL_ID,
            'binId': None,
            'binLabel': None,
            'features': {},
            'evidenceAsOf': {},
        }
        return empty, _empty_horizons()
    if as_of_date is None:
        as_of_date = _session_date_from_ts(rows[-1][0])
    lookup = regime_lookup or regime_at_date
    state = bin_state(
        symbol,
        as_of_date,
        bars=rows,
        chip_inst_by_date=chip_inst_by_date,
        regime_id=lookup(as_of_date),
    )
    observations = collect_pit_observations(
        symbol,
        rows,
        chip_inst_by_date=chip_inst_by_date,
        regime_lookup=lookup,
    )
    horizons = aggregate_bin_stats(observations, state['binId'])
    return state, horizons


def _invalid_if(gate: dict[str, Any], horizons: dict[str, dict[str, Any]], *, has_bin: bool) -> list[str]:
    invalid: list[str] = []
    if not gate.get('usable'):
        invalid.append('asof_gate_expired')
    if not has_bin:
        invalid.append('insufficient_bar_history')
    if any((horizons.get(str(h)) or {}).get('n', 0) < MIN_SAMPLE for h in HORIZONS):
        invalid.append('n_below_minimum')
    return invalid


def build_card(
    symbol: str,
    *,
    quote: dict[str, Any] | None = None,
    chips: dict[str, Any] | None = None,
    bars: list | None = None,
    chip_inst_by_date: dict[str, float] | None = None,
    now: datetime | None = None,
    regime_lookup: Callable[[date], str] | None = None,
) -> dict[str, Any]:
    """Build the Conditional Expectation card with PIT rule-bin statistics."""
    code = str(symbol or '').strip().upper()
    now = now or datetime.now(TZ_TPE)
    gate = evaluate_asof_gate(quote=quote, chips=chips, now=now)
    as_of_date = _last_tw_close_day(now)
    chip_map = chip_inst_by_date
    if chip_map is None and chips is not None:
        chip_map = load_chip_inst_history(code, current_chip=chips)
    state, horizons = compute_card_stats(
        code,
        bars=bars or [],
        chip_inst_by_date=chip_map,
        as_of_date=as_of_date,
        regime_lookup=regime_lookup,
    )
    has_bin = bool(state.get('binId'))
    invalid_if = _invalid_if(gate, horizons, has_bin=has_bin)
    usable_stats = gate.get('usable') and has_bin
    status = 'READY' if usable_stats else ('EXPIRED' if not gate.get('usable') else 'INSUFFICIENT_DATA')

    return {
        'ok': True,
        'enabled': True,
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'predictiveProbability': False,
        'epistemic': EPISTEMIC,
        'contractVersion': CONTRACT_VERSION,
        'model': MODEL_VERSION,
        'binModelId': BIN_MODEL_ID,
        'returnConvention': RETURN_CONVENTION,
        'status': status,
        'symbol': code,
        'binId': state.get('binId'),
        'binLabel': state.get('binLabel'),
        'features': state.get('features') or {},
        'horizons': horizons,
        'minimumSample': MIN_SAMPLE,
        'invalidIf': invalid_if,
        'asOfGate': gate,
        'evidenceAsOf': {
            'quote': (quote or {}).get('asOf') or (state.get('evidenceAsOf') or {}).get('quote'),
            'chips': (chips or {}).get('asOf') or (state.get('evidenceAsOf') or {}).get('chips'),
            'regime': (state.get('evidenceAsOf') or {}).get('regime'),
        },
        'pitAssumptions': [
            'Features computed from daily bars with ts <= asOf session only.',
            f'Forward returns use {RETURN_CONVENTION} over horizons {list(HORIZONS)} sessions.',
            'Chip bins use published chip_history dates <= asOf (T+2 publication lag respected).',
            'Regime tag from decision_history row with as_of <= session (never latest_context for history).',
        ],
        'notes': [
            '規則分箱歷史條件期望（shadow research）；不可覆寫 DecisionContext 曝險或信心分數。',
            'ratesAvailable=false 表示樣本數未達 minimumSample，統計 withheld。',
        ],
    }

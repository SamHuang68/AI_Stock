#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic key levels and realized-volatility metrics.

The module is deliberately data-source agnostic.  Callers provide completed
daily bars in either tuple form ``(ts, o, h, l, c, volume)`` or dictionaries.
No live quote is mixed into the reference session.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable


TW_TZ = timezone(timedelta(hours=8))


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), TW_TZ).date().isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == '-' and text[7] == '-':
        return text[:10]
    if len(text) == 8 and text.isdigit():
        return f'{text[:4]}-{text[4:6]}-{text[6:]}'
    return None


def _normalize(rows: Iterable[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            rec = {
                'date': _date_text(row.get('date', row.get('d', row.get('ts')))),
                'open': _number(row.get('open')),
                'high': _number(row.get('high')),
                'low': _number(row.get('low')),
                'close': _number(row.get('close')),
                'volume': _number(row.get('volume')),
            }
        else:
            values = list(row or [])
            if len(values) < 5:
                continue
            rec = {
                'date': _date_text(values[0]),
                'open': _number(values[1]),
                'high': _number(values[2]),
                'low': _number(values[3]),
                'close': _number(values[4]),
                'volume': _number(values[5]) if len(values) > 5 else None,
            }
        if all(rec.get(k) is not None for k in ('open', 'high', 'low', 'close')):
            if rec['high'] >= rec['low'] and rec['close'] > 0:
                out.append(rec)
    out.sort(key=lambda x: x.get('date') or '')
    return out


def _atr(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(rows) < period + 1:
        return None
    true_ranges: list[float] = []
    for i in range(1, len(rows)):
        high, low, prev = rows[i]['high'], rows[i]['low'], rows[i - 1]['close']
        true_ranges.append(max(high - low, abs(high - prev), abs(low - prev)))
    vals = true_ranges[-period:]
    return sum(vals) / period if len(vals) == period else None


def _realized_vol(rows: list[dict[str, Any]], period: int = 20) -> float | None:
    closes = [r['close'] for r in rows]
    if len(closes) < period + 1:
        return None
    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1]]
    vals = returns[-period:]
    if len(vals) < period:
        return None
    mean = sum(vals) / len(vals)
    variance = sum((x - mean) ** 2 for x in vals) / max(1, len(vals) - 1)
    return math.sqrt(variance) * math.sqrt(252.0) * 100.0


def _downside_vol(rows: list[dict[str, Any]], period: int = 20) -> float | None:
    """Annualized downside semideviation used only as a fast risk brake."""
    closes = [r['close'] for r in rows]
    if len(closes) < period + 1:
        return None
    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1]]
    vals = returns[-period:]
    if len(vals) < period:
        return None
    downside = [min(0.0, x) for x in vals]
    variance = sum(x * x for x in downside) / max(1, len(downside) - 1)
    return math.sqrt(variance) * math.sqrt(252.0) * 100.0


def _horizon_vol_forecast(rv60: float | None, rv20: float | None, long_run: float = 20.0) -> float | None:
    """Slow 12-month research denominator; never a near-term trade forecast."""
    observed = rv60 if rv60 is not None else rv20
    if observed is None:
        return None
    return math.sqrt(0.55 * observed * observed + 0.45 * long_run * long_run)


def _percentile(values: list[float], percentile: float) -> float | None:
    vals = sorted(x for x in values if math.isfinite(x))
    if not vals:
        return None
    rank = (len(vals) - 1) * max(0.0, min(1.0, percentile))
    lo, hi = int(math.floor(rank)), int(math.ceil(rank))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (rank - lo)


def _return_distribution(rows: list[dict[str, Any]], period: int = 60) -> dict[str, Any]:
    sample = rows[-(period + 1):]
    returns = [
        (sample[i]['close'] / sample[i - 1]['close'] - 1.0) * 100.0
        for i in range(1, len(sample)) if sample[i - 1]['close']
    ]
    abs_returns = [abs(x) for x in returns]
    return {
        'samples': len(returns),
        'absP95Pct': round(_percentile(abs_returns, 0.95), 3) if abs_returns else None,
        'worstDownPct': round(min(returns), 3) if returns else None,
        'worstUpPct': round(max(returns), 3) if returns else None,
    }


def _gap_distribution(rows: list[dict[str, Any]], period: int = 60) -> dict[str, Any]:
    sample = rows[-(period + 1):]
    gaps = [
        (sample[i]['open'] / sample[i - 1]['close'] - 1.0) * 100.0
        for i in range(1, len(sample)) if sample[i - 1]['close']
    ]
    abs_gaps = [abs(x) for x in gaps]
    return {
        'samples': len(gaps),
        'meanAbsPct': round(sum(abs_gaps) / len(abs_gaps), 3) if abs_gaps else None,
        'absP90Pct': round(_percentile(abs_gaps, 0.90), 3) if abs_gaps else None,
        'worstAbsPct': round(max(abs_gaps), 3) if abs_gaps else None,
    }


def _confirmed_swings(rows: list[dict[str, Any]], wing: int = 2) -> tuple[dict | None, dict | None]:
    """Return the latest confirmed fractal high/low, never the live edge bar."""
    high_hit = low_hit = None
    for i in range(wing, len(rows) - wing):
        h = rows[i]['high']
        l = rows[i]['low']
        around = rows[i - wing:i] + rows[i + 1:i + wing + 1]
        if all(h > r['high'] for r in around):
            high_hit = {'price': h, 'date': rows[i].get('date'), 'window': wing}
        if all(l < r['low'] for r in around):
            low_hit = {'price': l, 'date': rows[i].get('date'), 'window': wing}
    return high_hit, low_hit


def calculate_key_levels(
    bars: Iterable[Any] | None,
    *,
    symbol: str = '^TWII',
    session: str = 'regular',
    source: str = 'local-daily-series',
    as_of: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Calculate Classic Pivot, ATR bands, confirmed swings and realized vol."""
    rows = _normalize(bars)
    now = datetime.now(TW_TZ)
    as_of = as_of or now.isoformat()
    today = today or now.date()
    empty = {
        'symbol': symbol, 'session': session, 'asOf': as_of, 'source': source,
        'referenceDate': None, 'method': 'classic_pivot_v1', 'timeframe': '1d',
        'levels': {'r2': None, 'r1': None, 'pivot': None, 's1': None, 's2': None},
        'atr': {'period': 14, 'value': None, 'pct': None, 'upper': None, 'lower': None},
        'swing': {'high': None, 'low': None, 'method': 'confirmed_fractal_2x2'},
        'volatility': {
            'realized20AnnualPct': None, 'realized60AnnualPct': None,
            'stateDownside20AnnualPct': None, 'horizonForecastAnnualPct': None,
            'stateToForecastRatio': None,
            'normal68OneDayPct': None, 'normal95OneDayPct': None,
            'normal68Range': None, 'normal95Range': None,
            'atrExpectedOneDayPct': None, 'expectedOneDayPct': None, 'gap60': _gap_distribution([], 60),
            'tail60': _return_distribution([], 60), 'proxy': 'realized',
            'stateVolRole': 'risk_brake_only',
            'horizonForecastMethod': '55% realized60 variance + 45% long-run 20% variance anchor',
            'modelLimitations': 'historical realized volatility; normal ranges are not guarantees or implied volatility',
        },
        'quality': {'complete': False, 'stale': True, 'bars': len(rows), 'reason': 'insufficient_bars'},
    }
    if not rows:
        return empty

    ref = rows[-1]
    high, low, close = ref['high'], ref['low'], ref['close']
    pivot = (high + low + close) / 3.0
    levels = {
        'r2': pivot + (high - low),
        'r1': 2.0 * pivot - low,
        'pivot': pivot,
        's1': 2.0 * pivot - high,
        's2': pivot - (high - low),
    }
    atr = _atr(rows, 14)
    rv20 = _realized_vol(rows, 20)
    rv60 = _realized_vol(rows, 60)
    downside20 = _downside_vol(rows, 20)
    horizon_vol = _horizon_vol_forecast(rv60, rv20)
    state_ratio = downside20 / horizon_vol if downside20 is not None and horizon_vol else None
    sigma1 = rv20 / math.sqrt(252.0) if rv20 is not None else None
    swing_high, swing_low = _confirmed_swings(rows[-40:], 2)
    ref_date = ref.get('date')
    stale = True
    if ref_date:
        try:
            stale = (today - date.fromisoformat(ref_date)).days > 7
        except ValueError:
            stale = True

    out = dict(empty)
    out['referenceDate'] = ref_date
    out['levels'] = {k: round(v, 2) for k, v in levels.items()}
    out['atr'] = {
        'period': 14,
        'value': round(atr, 2) if atr is not None else None,
        'pct': round(atr / close * 100.0, 3) if atr is not None and close else None,
        'upper': round(close + atr, 2) if atr is not None else None,
        'lower': round(close - atr, 2) if atr is not None else None,
    }
    out['swing'] = {
        'high': swing_high,
        'low': swing_low,
        'method': 'confirmed_fractal_2x2',
    }
    out['volatility'] = {
        'realized20AnnualPct': round(rv20, 2) if rv20 is not None else None,
        'realized60AnnualPct': round(rv60, 2) if rv60 is not None else None,
        'stateDownside20AnnualPct': round(downside20, 2) if downside20 is not None else None,
        'horizonForecastAnnualPct': round(horizon_vol, 2) if horizon_vol is not None else None,
        'stateToForecastRatio': round(state_ratio, 3) if state_ratio is not None else None,
        'normal68OneDayPct': round(sigma1, 3) if sigma1 is not None else None,
        'normal95OneDayPct': round(sigma1 * 1.96, 3) if sigma1 is not None else None,
        'normal68Range': ([round(close * (1.0 - sigma1 / 100.0), 2), round(close * (1.0 + sigma1 / 100.0), 2)]
                          if sigma1 is not None else None),
        'normal95Range': ([round(close * (1.0 - 1.96 * sigma1 / 100.0), 2), round(close * (1.0 + 1.96 * sigma1 / 100.0), 2)]
                          if sigma1 is not None else None),
        'atrExpectedOneDayPct': round(atr / close * 100.0, 3) if atr is not None and close else None,
        'expectedOneDayPct': round(atr / close * 100.0, 3) if atr is not None and close else None,
        'gap60': _gap_distribution(rows, 60),
        'tail60': _return_distribution(rows, 60),
        'proxy': 'realized',
        'stateVolRole': 'risk_brake_only',
        'horizonForecastMethod': '55% realized60 variance + 45% long-run 20% variance anchor',
        'modelLimitations': 'historical realized volatility; normal ranges are not guarantees or implied volatility',
    }
    out['quality'] = {
        'complete': True,
        'stale': stale,
        'bars': len(rows),
        'reason': 'reference_older_than_7_calendar_days' if stale else None,
    }
    return out

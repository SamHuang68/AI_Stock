#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Realized-volatility percentile regime switch (P1 shadow research).

Detects percentile cross up/down and emits a **position width hint** only.
Does not overwrite Decision envelope; hints are epistemic CONDITIONAL.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

import key_levels as kl

from conditional_expectation import _bars_upto_date, _session_date_from_ts

MODEL_VERSION = 'st-vol-regime-switch/v1'
LOOKBACK_SESSIONS = 252
VOL_PERIOD = 20
LOW_PERCENTILE = 20.0
HIGH_PERCENTILE = 80.0
WIDTH_NEUTRAL = 1.0
WIDTH_HIGH_VOL = 0.70
WIDTH_LOW_VOL = 1.05


def _percentile_rank(value: float, history: list[float]) -> float | None:
    if not history or value is None or not math.isfinite(value):
        return None
    ordered = sorted(history)
    below = sum(1 for item in ordered if item <= value)
    return (below / len(ordered)) * 100.0


def _realized_vol_series(bars: list, *, as_of: date, lookback: int = LOOKBACK_SESSIONS) -> list[float]:
    pit = _bars_upto_date(bars, as_of)
    rows = kl._normalize(pit)
    series: list[float] = []
    for idx in range(VOL_PERIOD + 1, len(rows) + 1):
        window = rows[:idx]
        rv = kl._realized_vol(window, VOL_PERIOD)
        if rv is not None and math.isfinite(rv):
            series.append(float(rv))
    if lookback > 0 and len(series) > lookback:
        series = series[-lookback:]
    return series


def _regime_bucket(percentile: float | None) -> str:
    if percentile is None:
        return 'unknown'
    if percentile >= HIGH_PERCENTILE:
        return 'high'
    if percentile <= LOW_PERCENTILE:
        return 'low'
    return 'mid'


def _width_hint(
    bucket: str,
    *,
    prev_bucket: str,
    crossed: str | None,
) -> dict[str, Any]:
    multiplier = WIDTH_NEUTRAL
    action = 'hold_width'
    label = '維持基準部位寬度'
    if bucket == 'high':
        multiplier = WIDTH_HIGH_VOL
        action = 'reduce_width'
        label = '高波動分位 · 建議縮小部位寬度（僅研究提示）'
    elif bucket == 'low':
        multiplier = WIDTH_LOW_VOL
        action = 'allow_full_width'
        label = '低波動分位 · 可恢復基準部位寬度（僅研究提示）'
    if crossed == 'up_high':
        action = 'reduce_width'
        label = 'RV 分位上穿高波動門檻 · 建議縮小部位寬度'
    elif crossed == 'down_low':
        action = 'allow_full_width'
        label = 'RV 分位下穿低波動門檻 · 可恢復基準部位寬度'
    return {
        'multiplier': round(multiplier, 3),
        'action': action,
        'label': label,
        'prevBucket': prev_bucket,
        'crossed': crossed,
        'baselineWidth': WIDTH_NEUTRAL,
    }


def evaluate_vol_regime_switch(
    symbol: str,
    *,
    bars: list,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    code = str(symbol or '').strip().upper()
    rows = [r for r in (bars or []) if r and r[4] is not None]
    if as_of_date is None and rows:
        as_of_date = _session_date_from_ts(rows[-1][0])
    if not rows or as_of_date is None:
        return {
            'model': MODEL_VERSION,
            'epistemic': 'CONDITIONAL',
            'shadowOnly': True,
            'actionAuthority': 'none',
            'decisionUse': 'research_only',
            'symbol': code,
            'status': 'INSUFFICIENT_DATA',
            'positionWidthHint': None,
        }

    series = _realized_vol_series(rows, as_of=as_of_date)
    if len(series) < VOL_PERIOD + 5:
        return {
            'model': MODEL_VERSION,
            'epistemic': 'CONDITIONAL',
            'shadowOnly': True,
            'actionAuthority': 'none',
            'decisionUse': 'research_only',
            'symbol': code,
            'asOfDate': as_of_date.isoformat(),
            'status': 'INSUFFICIENT_DATA',
            'positionWidthHint': None,
            'reason': 'realized_vol_history_too_short',
        }

    current_rv = series[-1]
    history = series[:-1] if len(series) > 1 else series
    pct = _percentile_rank(current_rv, history)
    prev_rv = series[-2] if len(series) >= 2 else current_rv
    prev_pct = _percentile_rank(prev_rv, history[:-1] if len(history) > 1 else history)

    bucket = _regime_bucket(pct)
    prev_bucket = _regime_bucket(prev_pct)
    crossed = None
    if prev_pct is not None and pct is not None:
        if prev_pct < HIGH_PERCENTILE <= pct:
            crossed = 'up_high'
        elif prev_pct > LOW_PERCENTILE >= pct:
            crossed = 'down_low'

    hint = _width_hint(bucket, prev_bucket=prev_bucket, crossed=crossed)
    return {
        'model': MODEL_VERSION,
        'epistemic': 'CONDITIONAL',
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'predictiveProbability': False,
        'symbol': code,
        'asOfDate': as_of_date.isoformat(),
        'status': 'READY',
        'realizedVol20AnnualPct': round(current_rv, 4),
        'percentile': round(pct, 2) if pct is not None else None,
        'prevPercentile': round(prev_pct, 2) if prev_pct is not None else None,
        'regimeBucket': bucket,
        'thresholds': {
            'lowPercentile': LOW_PERCENTILE,
            'highPercentile': HIGH_PERCENTILE,
            'lookbackSessions': LOOKBACK_SESSIONS,
            'volPeriod': VOL_PERIOD,
        },
        'positionWidthHint': hint,
        'notes': [
            '僅輸出部位寬度提示；不覆寫 DecisionContext actionEnvelope。',
            '分位以 PIT 歷史 realized vol 序列計算（不含未來 bar）。',
        ],
    }

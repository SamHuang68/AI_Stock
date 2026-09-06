#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H-day post-event return distributions (P1 shadow research).

Uses rule-based revenue publish calendar (monthly 10th) when no dedicated
historical ex-div store exists.  Ex-dividend backtest is stubbed with an
explicit DEFERRED note — no invented events.
"""
from __future__ import annotations

import calendar
import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Callable

from conditional_expectation import (
    HORIZONS,
    MIN_SAMPLE,
    _bars_upto_date,
    _forward_outcome,
    _median,
    _quantile,
    _session_date_from_ts,
    aggregate_horizon_stats,
)

MODEL_VERSION = 'st-event-window-returns/v1'
RETURN_CONVENTION = 'close_to_close_same_symbol'
REVENUE_PUBLISH_DAY = 10
EVENT_HORIZONS = HORIZONS

if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REPORT_PATH = os.path.join(_BASE, 'docs', 'research', 'event_window_deferred.json')


def _month_publish_date(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    day = min(REVENUE_PUBLISH_DAY, last_day)
    return date(year, month, day)


def _shift_to_prev_tradable(day: date) -> date:
    cursor = day
    while cursor.weekday() >= 5:
        cursor = cursor.fromordinal(cursor.toordinal() - 1)
    return cursor


def revenue_publish_dates(start: date, end: date) -> list[date]:
    """Rule calendar: TW monthly revenue publish by 10th (shift to prior weekday)."""
    out: list[date] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        pub = _shift_to_prev_tradable(_month_publish_date(cursor.year, cursor.month))
        if start <= pub <= end:
            out.append(pub)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return out


def _bar_index_by_date(bars: list, as_of: date) -> dict[date, int]:
    mapping: dict[date, int] = {}
    for idx, row in enumerate(_bars_upto_date(bars, as_of)):
        mapping[_session_date_from_ts(row[0])] = idx
    return mapping


def _nearest_bar_index(mapping: dict[date, int], event_day: date, *, max_lag: int = 5) -> int | None:
    cursor = event_day
    for _ in range(max_lag + 1):
        if cursor in mapping:
            return mapping[cursor]
        cursor = cursor.fromordinal(cursor.toordinal() - 1)
        while cursor.weekday() >= 5:
            cursor = cursor.fromordinal(cursor.toordinal() - 1)
    return None


def collect_event_outcomes(
    bars: list,
    event_dates: list[date],
    *,
    as_of: date,
    event_type: str,
) -> list[dict[str, Any]]:
    """PIT: only events on or before ``as_of``; forward returns from event session."""
    rows = [r for r in (bars or []) if r and r[4] is not None]
    mapping = _bar_index_by_date(rows, as_of)
    observations: list[dict[str, Any]] = []
    max_h = max(EVENT_HORIZONS)
    for event_day in sorted(event_dates):
        if event_day > as_of:
            continue
        origin_idx = _nearest_bar_index(mapping, event_day)
        if origin_idx is None or origin_idx + max_h >= len(rows):
            continue
        outcomes: dict[str, dict[str, float]] = {}
        for horizon in EVENT_HORIZONS:
            outcome = _forward_outcome(rows, origin_idx, horizon)
            if outcome is not None:
                outcomes[str(horizon)] = outcome
        if outcomes:
            observations.append({
                'eventType': event_type,
                'eventDate': event_day.isoformat(),
                'outcomes': outcomes,
            })
    return observations


def aggregate_event_horizons(observations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    horizons: dict[str, dict[str, Any]] = {}
    for horizon in EVENT_HORIZONS:
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
    return horizons


def deferred_ex_dividend_note() -> dict[str, Any]:
    return {
        'eventType': 'ex_dividend',
        'status': 'DEFERRED_OPTIONAL',
        'reason': 'event calendar',
        'detail': (
            'Live /events exDividend feed has no versioned historical store in-repo. '
            'Post-event ex-div distributions require a PIT event ledger — not invented here.'
        ),
        'horizons': {str(h): {'n': 0, 'ratesAvailable': False} for h in EVENT_HORIZONS},
        'artifact': 'docs/FINDINGS_CONDITIONAL_EXPECTATION_P0.md#p1-event-window',
    }


def evaluate_event_windows(
    symbol: str,
    *,
    bars: list,
    as_of_date: date | None = None,
    history_years: int = 5,
) -> dict[str, Any]:
    code = str(symbol or '').strip().upper()
    rows = [r for r in (bars or []) if r and r[4] is not None]
    if not rows:
        return {
            'model': MODEL_VERSION,
            'epistemic': 'CONDITIONAL',
            'shadowOnly': True,
            'actionAuthority': 'none',
            'decisionUse': 'research_only',
            'symbol': code,
            'status': 'INSUFFICIENT_DATA',
            'events': [],
        }
    if as_of_date is None:
        as_of_date = _session_date_from_ts(rows[-1][0])
    start = date(as_of_date.year - history_years, as_of_date.month, 1)
    revenue_dates = revenue_publish_dates(start, as_of_date)
    revenue_obs = collect_event_outcomes(rows, revenue_dates, as_of=as_of_date, event_type='revenue_publish')
    revenue_stats = aggregate_event_horizons(revenue_obs)

    return {
        'model': MODEL_VERSION,
        'epistemic': 'CONDITIONAL',
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'predictiveProbability': False,
        'symbol': code,
        'asOfDate': as_of_date.isoformat(),
        'status': 'READY' if revenue_obs else 'INSUFFICIENT_DATA',
        'returnConvention': RETURN_CONVENTION,
        'minimumSample': MIN_SAMPLE,
        'events': [
            {
                'eventType': 'revenue_publish',
                'calendar': f'monthly_by_day_{REVENUE_PUBLISH_DAY}',
                'observationCount': len(revenue_obs),
                'horizons': revenue_stats,
                'pitAssumptions': [
                    'Events on or before asOfDate only.',
                    f'Forward returns: {RETURN_CONVENTION}.',
                    'Event session matched to nearest prior tradable bar within 5 sessions.',
                ],
            },
            deferred_ex_dividend_note(),
        ],
        'notes': [
            '事件窗口為歷史條件分布；非未來保證。',
            'ex_dividend 需 PIT 事件帳本 — 見 DEFERRED_OPTIONAL stub。',
        ],
    }


def write_deferred_artifact() -> str:
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    payload = {
        'generatedAt': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
        'deferred': [deferred_ex_dividend_note()],
    }
    with open(REPORT_PATH, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return REPORT_PATH

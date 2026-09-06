#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rule-based chip path dependency state machine (P1 shadow research).

Consecutive institutional buy/sell streak × price reaction → discrete states
such as accumulate / chase / distribute / unwind.  Descriptive only — not buy/sell
advice and never merged into Decision actionEnvelope.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Callable

from conditional_expectation import (
    CHIP_MAX_LAG_SESSIONS,
    _bars_upto_date,
    _chip_session_date,
    _last_tw_close_day,
    _session_date_from_ts,
    load_chip_inst_history,
)

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:  # pragma: no cover
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))
MODEL_VERSION = 'st-chip-path-state/v1'
MIN_STREAK_DAYS = 3
CHASE_RETURN_PCT = 3.0
DISTRIBUTE_RETURN_PCT = -3.0

STATE_LABELS = {
    'accumulate': '法人連買 · 價格尚未大幅反映（潛在累積）',
    'chase': '法人連買 · 價格已明顯上漲（路徑依賴追逐）',
    'distribute': '法人連賣 · 價格同步走弱（派發）',
    'unwind': '法人連賣 · 價格仍偏強（背離出貨）',
    'neutral': '籌碼路徑中性或樣本不足',
}


def _inst_streak(inst_by_date: dict[str, float], as_of: date) -> tuple[int, float]:
    """Return (signed streak days, net total over streak window) using PIT chip dates."""
    eligible = sorted(
        (day, total)
        for day, total in (inst_by_date or {}).items()
        if _chip_session_date(day) is not None and _chip_session_date(day) <= as_of
    )
    if not eligible:
        return 0, 0.0
    eligible.sort(key=lambda item: item[0], reverse=True)
    sign = 0
    streak = 0
    net = 0.0
    for day, total in eligible:
        if total == 0:
            break
        day_sign = 1 if total > 0 else -1
        if sign == 0:
            sign = day_sign
        if day_sign != sign:
            break
        streak += 1
        net += float(total)
    return streak * sign, net


def _price_reaction_pct(bars: list, as_of: date, streak_days: int) -> float | None:
    """Close-to-close return over the most recent ``streak_days`` sessions <= as_of."""
    pit = _bars_upto_date(bars, as_of)
    if len(pit) < streak_days + 1 or streak_days <= 0:
        return None
    start_close = float(pit[-(streak_days + 1)][4])
    end_close = float(pit[-1][4])
    if start_close <= 0:
        return None
    return (end_close / start_close - 1.0) * 100.0


def classify_path_state(
    *,
    streak_signed: int,
    price_reaction_pct: float | None,
) -> str:
    days = abs(streak_signed)
    if days < MIN_STREAK_DAYS or price_reaction_pct is None:
        return 'neutral'
    reaction = float(price_reaction_pct)
    if streak_signed > 0:
        return 'chase' if reaction >= CHASE_RETURN_PCT else 'accumulate'
    if streak_signed < 0:
        return 'distribute' if reaction <= DISTRIBUTE_RETURN_PCT else 'unwind'
    return 'neutral'


def path_state_score(state_id: str) -> float:
    """Bounded feature contribution for integration score (−1…+1)."""
    return {
        'accumulate': 0.55,
        'chase': -0.35,
        'distribute': -0.55,
        'unwind': 0.15,
        'neutral': 0.0,
    }.get(state_id, 0.0)


def _chips_asof_solid(
    chips: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> tuple[bool, list[str]]:
    """Return whether chips asOf is fresh enough for path-state classification."""
    now = now or datetime.now(TZ_TPE)
    reasons: list[str] = []
    chip_as_of = (chips or {}).get('asOf')
    chip_day = _chip_session_date(chip_as_of)
    if not chips or chip_day is None:
        return False, ['chips asOf 缺失或無法解析']
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
    return (not reasons, reasons)


def evaluate_chip_path_state(
    symbol: str,
    *,
    bars: list,
    chip_inst_by_date: dict[str, float] | None = None,
    chips: dict[str, Any] | None = None,
    as_of_date: date | None = None,
    now: datetime | None = None,
    streak_fn: Callable[[dict[str, float], date], tuple[int, float]] | None = None,
) -> dict[str, Any]:
    """Build chip path state payload (FACT rule label, shadow-safe)."""
    code = str(symbol or '').strip().upper()
    now = now or datetime.now(TZ_TPE)
    solid, chip_reasons = _chips_asof_solid(chips, now=now)
    if not solid:
        return {
            'model': MODEL_VERSION,
            'epistemic': 'FACT',
            'shadowOnly': True,
            'actionAuthority': 'none',
            'decisionUse': 'research_only',
            'symbol': code,
            'state': 'neutral',
            'stateLabel': STATE_LABELS['neutral'],
            'streakDays': 0,
            'priceReactionPct': None,
            'status': 'CHIPS_ASOF_EXPIRED',
            'chipsAsOfGate': {'usable': False, 'reasons': chip_reasons},
            'reason': 'chips_asof_not_solid',
        }
    rows = [r for r in (bars or []) if r and r[4] is not None]
    if not rows:
        return {
            'model': MODEL_VERSION,
            'epistemic': 'FACT',
            'shadowOnly': True,
            'actionAuthority': 'none',
            'decisionUse': 'research_only',
            'symbol': code,
            'state': 'neutral',
            'stateLabel': STATE_LABELS['neutral'],
            'streakDays': 0,
            'priceReactionPct': None,
            'status': 'INSUFFICIENT_DATA',
            'reason': 'insufficient_bar_history',
        }
    if as_of_date is None:
        as_of_date = _session_date_from_ts(rows[-1][0])
    chip_map = chip_inst_by_date or {}
    streak_lookup = streak_fn or _inst_streak
    streak_signed, streak_net = streak_lookup(chip_map, as_of_date)
    streak_days = abs(streak_signed)
    reaction = _price_reaction_pct(rows, as_of_date, streak_days) if streak_days else None
    state_id = classify_path_state(streak_signed=streak_signed, price_reaction_pct=reaction)
    return {
        'model': MODEL_VERSION,
        'epistemic': 'FACT',
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'symbol': code,
        'asOfDate': as_of_date.isoformat(),
        'state': state_id,
        'stateLabel': STATE_LABELS.get(state_id, STATE_LABELS['neutral']),
        'streakDays': streak_signed,
        'streakNetShares': round(streak_net, 2),
        'priceReactionPct': round(reaction, 4) if reaction is not None else None,
        'status': 'READY',
        'chipsAsOfGate': {'usable': True, 'reasons': []},
        'thresholds': {
            'minStreakDays': MIN_STREAK_DAYS,
            'chaseReturnPct': CHASE_RETURN_PCT,
            'distributeReturnPct': DISTRIBUTE_RETURN_PCT,
        },
        'notes': [
            '規則狀態機；非買賣建議。',
            'priceReactionPct 為 streak 窗口 close-to-close 報酬（%）。',
        ],
    }


def evaluate_from_symbol(
    symbol: str,
    *,
    bars: list | None = None,
    current_chip: dict[str, Any] | None = None,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    chip_map = load_chip_inst_history(symbol, current_chip=current_chip)
    if bars is None:
        try:
            import datastore
            bars = datastore.get_bars(symbol, market='TW') or []
        except Exception:
            bars = []
    return evaluate_chip_path_state(
        symbol,
        bars=bars,
        chip_inst_by_date=chip_map,
        chips={'asOf': (current_chip or {}).get('date') or (current_chip or {}).get('asOf')} if current_chip else None,
        as_of_date=as_of_date,
    )

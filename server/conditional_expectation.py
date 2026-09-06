#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shadow-only Conditional Expectation card (rule bins, not LLM scores).

P0 contract scaffold: epistemic tier CONDITIONAL, default disabled via
``shadowConditionalExpectation``.  Bin statistics and point-in-time tables are
not implemented in this module yet — see docs/FINDINGS_CONDITIONAL_EXPECTATION_P0.md.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime
from typing import Any

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:  # pragma: no cover
    from datetime import timezone, timedelta
    TZ_TPE = timezone(timedelta(hours=8))

from postmarket_report import staleness as _quote_staleness

CONTRACT_VERSION = 1
MODEL_VERSION = 'st-conditional-expectation/scaffold-v0'
EPISTEMIC = 'CONDITIONAL'
HORIZONS = (1, 5, 20)
MIN_SAMPLE = 30
CHIP_MAX_LAG_SESSIONS = 2


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
        'status': 'DISABLED',
        'reason': reason,
        'horizons': list(HORIZONS),
        'minimumSample': MIN_SAMPLE,
        'card': None,
    }


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


def build_card(
    symbol: str,
    *,
    quote: dict[str, Any] | None = None,
    chips: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the Conditional Expectation card payload (scaffold — no bin stats yet)."""
    code = str(symbol or '').strip().upper()
    now = now or datetime.now(TZ_TPE)
    gate = evaluate_asof_gate(quote=quote, chips=chips, now=now)
    invalid_if: list[str] = []
    if not gate['usable']:
        invalid_if.append('asof_gate_expired')
    invalid_if.append('bin_engine_not_implemented')

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
        'status': 'SCAFFOLD',
        'symbol': code,
        'binId': None,
        'binLabel': None,
        'horizons': _empty_horizons(),
        'minimumSample': MIN_SAMPLE,
        'invalidIf': invalid_if,
        'asOfGate': gate,
        'evidenceAsOf': {
            'quote': (quote or {}).get('asOf'),
            'chips': (chips or {}).get('asOf'),
        },
        'notes': [
            '規則分箱歷史條件期望尚未實作；此為契約 scaffold。',
            '不可覆寫 DecisionContext 曝險或信心分數。',
        ],
    }

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 orchestrator for Conditional Expectation shadow research modules."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from feature_settings import is_enabled

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:  # pragma: no cover
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))

P1_CONTRACT_VERSION = 1


def disabled_p1_payload(reason: str = 'P1_SHADOW_DISABLED') -> dict[str, Any]:
    return {
        'ok': False,
        'enabled': False,
        'contractVersion': P1_CONTRACT_VERSION,
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'status': 'DISABLED',
        'reason': reason,
        'chipPathState': None,
        'volRegimeSwitch': None,
        'integrationScore': None,
        'eventWindows': None,
    }


def build_p1_research(
    symbol: str,
    *,
    quote: dict[str, Any] | None = None,
    chips: dict[str, Any] | None = None,
    bars: list | None = None,
    chip_inst_by_date: dict[str, float] | None = None,
    now: datetime | None = None,
    base_dir: str | None = None,
    write_walk_forward: bool = False,
) -> dict[str, Any]:
    """Assemble P1 modules behind per-feature flags (all default OFF)."""
    import chip_path_state
    import conditional_integration_score as cis
    import event_window_returns as ewr
    import vol_regime_switch

    import conditional_expectation as ce

    code = str(symbol or '').strip().upper()
    now = now or datetime.now(TZ_TPE)
    as_of = ce._last_tw_close_day(now)
    chip_map = chip_inst_by_date
    if chip_map is None and chips is not None:
        chip_map = ce.load_chip_inst_history(code, current_chip=chips)

    out: dict[str, Any] = {
        'ok': True,
        'enabled': True,
        'contractVersion': P1_CONTRACT_VERSION,
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'symbol': code,
        'asOfDate': as_of.isoformat(),
        'chipPathState': None,
        'volRegimeSwitch': None,
        'integrationScore': None,
        'eventWindows': None,
        'flags': {},
    }

    if is_enabled('shadowChipPathState', base_dir):
        out['chipPathState'] = chip_path_state.evaluate_chip_path_state(
            code,
            bars=bars or [],
            chip_inst_by_date=chip_map,
            as_of_date=as_of,
        )
    out['flags']['shadowChipPathState'] = is_enabled('shadowChipPathState', base_dir)

    if is_enabled('shadowVolRegimeSwitch', base_dir):
        out['volRegimeSwitch'] = vol_regime_switch.evaluate_vol_regime_switch(
            code,
            bars=bars or [],
            as_of_date=as_of,
        )
    out['flags']['shadowVolRegimeSwitch'] = is_enabled('shadowVolRegimeSwitch', base_dir)

    if is_enabled('shadowEventWindowReturns', base_dir):
        out['eventWindows'] = ewr.evaluate_event_windows(
            code,
            bars=bars or [],
            as_of_date=as_of,
        )
    out['flags']['shadowEventWindowReturns'] = is_enabled('shadowEventWindowReturns', base_dir)

    if is_enabled('shadowConditionalIntegrationScore', base_dir):
        out['integrationScore'] = cis.evaluate_integration_score(
            code,
            bars=bars or [],
            chip_inst_by_date=chip_map,
            as_of_date=as_of,
            write_report=write_walk_forward,
        )
    out['flags']['shadowConditionalIntegrationScore'] = is_enabled(
        'shadowConditionalIntegrationScore', base_dir,
    )

    return out

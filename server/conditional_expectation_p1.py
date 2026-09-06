#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 orchestrator for Conditional Expectation shadow research modules.

Host Gate ship order (must-ship):
  1. Deviation-z / relative-strength bins → conditional_expectation.py (P0 card)
  2. Chip path state machine (when chips asOf solid)
  3. Vol-regime switch → position width/caution only

Deferred in this PR:
  4. Event windows — no versioned event calendar
  5. Bounded composite score — until 1–3 are promoted with walk-forward
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from feature_settings import is_enabled

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:  # pragma: no cover
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))

P1_CONTRACT_VERSION = 2

DEFERRED_EVENT_WINDOWS = {
    'status': 'DEFERRED_OPTIONAL',
    'reason': 'event calendar',
    'detail': 'No versioned PIT event ledger in-repo; live /events is forward-looking only.',
    'artifact': 'docs/research/event_window_deferred.json',
}

DEFERRED_INTEGRATION_SCORE = {
    'status': 'DEFERRED',
    'reason': 'awaiting_must_ship_modules_and_walk_forward',
    'detail': 'Bounded composite score (−2…+2) deferred until deviation-z bins, chip path, and vol width are stable with walk-forward sketch.',
    'artifact': 'docs/research/integration_score_deferred.json',
}


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
        'deferred': {
            'eventWindows': DEFERRED_EVENT_WINDOWS,
            'integrationScore': DEFERRED_INTEGRATION_SCORE,
        },
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
) -> dict[str, Any]:
    """Assemble must-ship P1 modules (2–3) behind per-feature flags (default OFF)."""
    import chip_path_state
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
        'binModelId': ce.BIN_MODEL_ID,
        'chipPathState': None,
        'volRegimeSwitch': None,
        'deferred': {
            'eventWindows': DEFERRED_EVENT_WINDOWS,
            'integrationScore': DEFERRED_INTEGRATION_SCORE,
        },
        'flags': {},
        'notes': [
            'Must-ship: deviation-z/rs bins on main card; chip path + vol width here.',
            'Event windows and composite score intentionally deferred per Host Gate.',
        ],
    }

    if is_enabled('shadowChipPathState', base_dir):
        out['chipPathState'] = chip_path_state.evaluate_chip_path_state(
            code,
            bars=bars or [],
            chip_inst_by_date=chip_map,
            chips=chips,
            as_of_date=as_of,
            now=now,
        )
    out['flags']['shadowChipPathState'] = is_enabled('shadowChipPathState', base_dir)

    if is_enabled('shadowVolRegimeSwitch', base_dir):
        out['volRegimeSwitch'] = vol_regime_switch.evaluate_vol_regime_switch(
            code,
            bars=bars or [],
            as_of_date=as_of,
        )
    out['flags']['shadowVolRegimeSwitch'] = is_enabled('shadowVolRegimeSwitch', base_dir)

    return out

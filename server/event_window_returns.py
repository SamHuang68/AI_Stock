#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Event window returns — DEFERRED (P1 Host Gate).

No versioned PIT event calendar in-repo.  Do not invent event dates.
Revenue rule-calendar and ex-div backtests deferred until a proper ledger exists.
"""
from __future__ import annotations

from typing import Any

MODEL_VERSION = 'st-event-window-returns/deferred'


def deferred_event_windows_note() -> dict[str, Any]:
    return {
        'eventType': 'all',
        'status': 'DEFERRED_OPTIONAL',
        'reason': 'event calendar',
        'detail': (
            'Live /events feed is forward-looking; no versioned historical event ledger. '
            'H-day post-event return distributions require PIT calendar data — not invented here.'
        ),
        'artifact': 'docs/research/event_window_deferred.json',
    }


def deferred_ex_dividend_note() -> dict[str, Any]:
    note = deferred_event_windows_note()
    note['eventType'] = 'ex_dividend'
    return note

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded composite integration score — DEFERRED (P1 Host Gate).

Must-ship modules (deviation-z bins, chip path, vol width) take priority.
Composite −2…+2 score ships only with walk-forward sketch after Host review.
"""
from __future__ import annotations

from typing import Any

MODEL_VERSION = 'st-conditional-integration/deferred'
SCORE_MIN = -2.0
SCORE_MAX = 2.0


def deferred_integration_score_note() -> dict[str, Any]:
    return {
        'status': 'DEFERRED',
        'reason': 'awaiting_must_ship_modules_and_walk_forward',
        'detail': (
            'Orthogonal composite score deferred until must-ship P1 modules are stable '
            'and a walk-forward report is reviewed under Host Gate.'
        ),
        'scoreRange': [SCORE_MIN, SCORE_MAX],
        'artifact': 'docs/research/integration_score_deferred.json',
    }

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Feature flags for shadow / experimental research surfaces.

Defaults keep the main Pulse + DecisionContext path lean. Enable via:
  - Environment variables (see ``ENV_KEYS``)
  - ``data/feature_flags.local.json`` (gitignored local override)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


FEATURE_KEYS = (
    'shadowOvernightIntraday',
    'shadowEarlyWarning',
    'shadowConsensusAttention',
)

ENV_KEYS = {
    'shadowOvernightIntraday': 'ST_SHADOW_OVERNIGHT_INTRADAY',
    'shadowEarlyWarning': 'ST_SHADOW_EARLY_WARNING',
    'shadowConsensusAttention': 'ST_SHADOW_CONSENSUS_ATTENTION',
}

# Convenience master switch for local research sessions.
MASTER_ENV = 'ST_ENABLE_SHADOW_RESEARCH'


def _truthy(value: str | None) -> bool:
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _local_override_path(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return root / 'data' / 'feature_flags.local.json'


def _read_local_overrides(base_dir: str | Path | None = None) -> dict[str, bool]:
    path = _local_override_path(base_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, bool] = {}
    for key in FEATURE_KEYS:
        if key in payload:
            out[key] = bool(payload.get(key))
    return out


def feature_flags(base_dir: str | Path | None = None) -> dict[str, bool]:
    """Return the effective feature-flag map for this process."""
    master = _truthy(os.environ.get(MASTER_ENV))
    local = _read_local_overrides(base_dir)
    out: dict[str, bool] = {}
    for key in FEATURE_KEYS:
        env_name = ENV_KEYS[key]
        if key in local:
            out[key] = bool(local[key])
        elif _truthy(os.environ.get(env_name)):
            out[key] = True
        elif master:
            out[key] = True
        else:
            out[key] = False
    return out


def is_enabled(name: str, base_dir: str | Path | None = None) -> bool:
    return bool(feature_flags(base_dir).get(name))


def public_payload(base_dir: str | Path | None = None) -> dict[str, Any]:
    flags = feature_flags(base_dir)
    return {
        'ok': True,
        'contractVersion': 1,
        'defaults': {key: False for key in FEATURE_KEYS},
        'flags': flags,
        'enable': {
            'env': {key: ENV_KEYS[key] for key in FEATURE_KEYS},
            'masterEnv': MASTER_ENV,
            'localFile': 'data/feature_flags.local.json',
            'example': {
                'shadowOvernightIntraday': True,
                'shadowEarlyWarning': True,
                'shadowConsensusAttention': True,
            },
        },
    }

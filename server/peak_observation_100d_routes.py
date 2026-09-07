#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP boundary for st-peak-100d-v0 observation-only research (CONDITIONAL)."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from feature_settings import is_enabled


def _disabled_payload() -> dict:
    import peak_observation_100d as po100
    payload = po100.disabled_payload('SHADOW_DISABLED')
    payload['error'] = (
        'Peak observation 100d (st-peak-100d-v0) is disabled. '
        'Set ST_SHADOW_PEAK_100D=1 or ST_ENABLE_SHADOW_RESEARCH=1, '
        'or create data/feature_flags.local.json to enable.'
    )
    return payload


def _load_symbol_bars(symbol: str) -> list:
    try:
        import datastore
        return datastore.get_bars(symbol, market='TW') or []
    except Exception:
        return []


class PeakObservation100dRoutesMixin:
    def _peak_observation_100d_symbol(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        return str((query.get('symbol') or [''])[0] or '').strip().upper()

    def _handle_peak_observation_100d(self):
        base_dir = getattr(self, '_BASE', None)
        if not is_enabled('shadowPeak100d', base_dir):
            self._ok(json.dumps(_disabled_payload(), ensure_ascii=False).encode())
            return

        import peak_observation_100d as po100

        symbol = self._peak_observation_100d_symbol()
        if not symbol:
            self._err('symbol query parameter is required', 400)
            return

        bars = _load_symbol_bars(symbol)
        observation = po100.build_for_evidence_pack(symbol, bars=bars, base_dir=base_dir)
        payload = {
            'ok': True,
            'enabled': True,
            'epistemic': po100.EPISTEMIC,
            'observation': observation,
        }
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

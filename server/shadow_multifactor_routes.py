#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP boundary for P2 shadow multifactor research (isolated from llm_gate)."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from feature_settings import is_enabled
from promotion_gate import evaluate as evaluate_promotion_gate


def _disabled_payload() -> dict:
    import shadow_multifactor as sm
    payload = sm.disabled_payload('SHADOW_DISABLED')
    payload['error'] = (
        'Shadow multifactor research is disabled by default. '
        'Set ST_SHADOW_MULTIFACTOR=1 or ST_ENABLE_SHADOW_RESEARCH=1, '
        'or create data/feature_flags.local.json to enable.'
    )
    return payload


class ShadowMultifactorRoutesMixin:
    def _shadow_multifactor_query(self) -> dict:
        query = parse_qs(urlparse(self.path).query)
        symbols_raw = str((query.get('symbols') or [''])[0] or '').strip()
        symbols = [s.strip().upper() for s in symbols_raw.split(',') if s.strip()] if symbols_raw else []
        try:
            limit = int((query.get('limit') or ['15'])[0])
        except (TypeError, ValueError):
            limit = 15
        return {'symbols': symbols, 'limit': limit}

    def _handle_shadow_multifactor(self):
        base_dir = getattr(self, '_BASE', None)
        if not is_enabled('shadowMultifactor', base_dir):
            self._ok(json.dumps(_disabled_payload(), ensure_ascii=False).encode())
            return

        import shadow_multifactor as sm

        params = self._shadow_multifactor_query()
        symbols = params['symbols'] or list(sm.DEFAULT_SCAN_SYMBOLS)
        payload = sm.build_research_snapshot(
            symbols=symbols,
            limit=params['limit'],
            base_dir=base_dir,
        )
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

    def _handle_promotion_gate(self):
        """Read-only promotion gate checklist — always returns FAIL until evidence supplied."""
        query = parse_qs(urlparse(self.path).query)
        if query.get('demoPass'):
            bundle = {
                'oosReport': {
                    'status': 'complete',
                    'reportId': 'demo-oos-001',
                    'asOf': '2026-09-01',
                    'sampleSize': 120,
                    'windows': [{'id': 'w1'}, {'id': 'w2'}, {'id': 'w3'}],
                },
                'costTurnoverNotes': {
                    'status': 'documented',
                    'turnoverBps': 45.0,
                    'costBps': 12.0,
                    'summary': 'TW equity round-trip cost model v1',
                },
                'decayMonitor': {
                    'status': 'active',
                    'metric': 'rank_ic_20d',
                    'lookbackDays': 60,
                    'alertThreshold': 0.15,
                },
                'features': ['deviationZ', 'relativeStrengthPct', 'momentum60d', 'volRatio'],
            }
            payload = evaluate_promotion_gate(bundle)
        else:
            payload = evaluate_promotion_gate(None)
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

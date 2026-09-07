#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP boundary for st-touxin-5d-v0 observation-only research (CONDITIONAL)."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from feature_settings import is_enabled


def _disabled_payload() -> dict:
    import touxin_5d as t5
    payload = t5.disabled_payload('SHADOW_DISABLED')
    payload['error'] = (
        'Touxin 5d net-buy observation (st-touxin-5d-v0) is disabled. '
        'Set ST_SHADOW_TOUXIN_5D=1 or ST_ENABLE_SHADOW_RESEARCH=1, '
        'or create data/feature_flags.local.json to enable.'
    )
    return payload


class Touxin5dRoutesMixin:
    def _touxin_5d_symbol(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        return str((query.get('symbol') or [''])[0] or '').strip().upper()

    def _handle_touxin_5d_netbuy(self):
        base_dir = getattr(self, '_BASE', None)
        if not is_enabled('shadowTouxin5d', base_dir):
            self._ok(json.dumps(_disabled_payload(), ensure_ascii=False).encode())
            return

        import touxin_5d as t5

        symbol = self._touxin_5d_symbol()
        if not symbol:
            self._err('symbol query parameter is required', 400)
            return

        observation = t5.build_for_evidence_pack(symbol, base_dir=base_dir)
        payload = {
            'ok': True,
            'enabled': True,
            'epistemic': t5.EPISTEMIC,
            'observation': observation,
        }
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

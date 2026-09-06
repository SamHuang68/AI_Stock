#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP boundary for shadow Conditional Expectation research."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from feature_settings import is_enabled
from http_boundary import BodyReadError


def _disabled_payload() -> dict:
    import conditional_expectation as ce
    payload = ce.disabled_payload('SHADOW_DISABLED')
    payload['error'] = (
        'Conditional Expectation shadow research is disabled by default. '
        'Set ST_SHADOW_CONDITIONAL_EXPECTATION=1 or ST_ENABLE_SHADOW_RESEARCH=1, '
        'or create data/feature_flags.local.json to enable.'
    )
    return payload


class ConditionalExpectationRoutesMixin:
    def _conditional_expectation_symbol(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        return str((query.get('symbol') or [''])[0] or '').strip().upper()

    def _handle_conditional_expectation(self):
        base_dir = getattr(self, '_BASE', None)
        if not is_enabled('shadowConditionalExpectation', base_dir):
            self._ok(json.dumps(_disabled_payload(), ensure_ascii=False).encode())
            return

        import conditional_expectation as ce
        import postmarket_report as pr

        symbol = self._conditional_expectation_symbol()
        if not symbol:
            self._err('symbol query parameter is required', 400)
            return

        quote = None
        chips = None
        try:
            bars = pr._default_bars(symbol)
            quote = pr.quote_from_bars(bars)
            chips = pr._chip_evidence(pr._default_chip(symbol))
        except Exception:
            pass

        payload = {
            'ok': True,
            'enabled': True,
            'card': ce.build_card(symbol, quote=quote, chips=chips),
        }
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

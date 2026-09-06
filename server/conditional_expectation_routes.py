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


def _load_symbol_context(symbol: str) -> dict:
    import conditional_expectation as ce
    import postmarket_report as pr

    quote = None
    chips = None
    bars = []
    chip_raw = None
    try:
        import datastore
        bars = datastore.get_bars(symbol, market='TW') or []
        quote = pr.quote_from_bars(bars)
        chip_raw = pr._default_chip(symbol)
        chips = pr._chip_evidence(chip_raw)
    except Exception:
        pass
    chip_history = ce.load_chip_inst_history(symbol, current_chip=chip_raw)
    return {
        'quote': quote,
        'chips': chips,
        'bars': bars,
        'chip_raw': chip_raw,
        'chip_history': chip_history,
    }


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

        symbol = self._conditional_expectation_symbol()
        if not symbol:
            self._err('symbol query parameter is required', 400)
            return

        ctx = _load_symbol_context(symbol)
        payload = {
            'ok': True,
            'enabled': True,
            'card': ce.build_card(
                symbol,
                quote=ctx['quote'],
                chips=ctx['chips'],
                bars=ctx['bars'],
                chip_inst_by_date=ctx['chip_history'],
            ),
        }
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

    def _handle_conditional_expectation_p1(self):
        base_dir = getattr(self, '_BASE', None)
        if not is_enabled('shadowConditionalExpectation', base_dir):
            import conditional_expectation_p1 as p1
            payload = p1.disabled_p1_payload('SHADOW_DISABLED')
            payload['error'] = _disabled_payload()['error']
            self._ok(json.dumps(payload, ensure_ascii=False).encode())
            return

        import conditional_expectation as ce
        import conditional_expectation_p1 as p1

        symbol = self._conditional_expectation_symbol()
        if not symbol:
            self._err('symbol query parameter is required', 400)
            return

        query = parse_qs(urlparse(self.path).query)
        write_report = str((query.get('writeWalkForward') or ['0'])[0]).lower() in (
            '1', 'true', 'yes', 'on',
        )

        ctx = _load_symbol_context(symbol)
        card = ce.build_card(
            symbol,
            quote=ctx['quote'],
            chips=ctx['chips'],
            bars=ctx['bars'],
            chip_inst_by_date=ctx['chip_history'],
        )
        p1_payload = p1.build_p1_research(
            symbol,
            quote=ctx['quote'],
            chips=ctx['chips'],
            bars=ctx['bars'],
            chip_inst_by_date=ctx['chip_history'],
            base_dir=base_dir,
            write_walk_forward=write_report,
        )
        payload = {
            'ok': True,
            'enabled': True,
            'card': card,
            'p1': p1_payload,
        }
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

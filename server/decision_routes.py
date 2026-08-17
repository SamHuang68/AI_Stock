#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP handlers for the DecisionContext API, split out of server.py."""
from __future__ import annotations

import json
import math
import re
from urllib.parse import parse_qs, urlparse

from http_boundary import BodyReadError, read_json_body


_HOLDING_SYMBOL = re.compile(r'^[A-Za-z0-9^._=-]{1,20}$')
_NUMERIC_RISK_FIELDS = (
    'baseGrossExposure', 'maxGrossExposure', 'maxLeverage', 'maxSingleNameWeight',
    'maxSectorWeight', 'maxPortfolioBeta', 'maxDailyVaR',
)


class DecisionRoutesMixin:
    def _decision_body(self, limit: int = 65536) -> tuple[dict | None, BodyReadError | None]:
        try:
            return read_json_body(self, max_bytes=limit), None
        except BodyReadError as exc:
            return None, exc

    def _decision_payload(self, body: dict) -> tuple[dict | None, str | None]:
        risk_profile = body.get('riskProfile')
        if risk_profile is not None and not isinstance(risk_profile, dict):
            return None, 'riskProfile must be an object or null'
        if isinstance(risk_profile, dict):
            for key in _NUMERIC_RISK_FIELDS:
                value = risk_profile.get(key)
                if value in (None, ''):
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    return None, f'riskProfile.{key} must be numeric'
                if not math.isfinite(number) or number < 0 or number > 1000:
                    return None, f'riskProfile.{key} is outside accepted bounds'
            horizon = risk_profile.get('investmentHorizon')
            if horizon is not None and (not isinstance(horizon, str) or not 1 <= len(horizon.strip()) <= 32):
                return None, 'riskProfile.investmentHorizon must be 1-32 characters'

        holdings = body.get('holdings')
        if holdings is not None and not isinstance(holdings, list):
            return None, 'holdings must be an array or null'
        if isinstance(holdings, list) and len(holdings) > 80:
            return None, 'holdings supports at most 80 rows'
        clean_holdings = []
        for idx, row in enumerate(holdings or []):
            if not isinstance(row, dict):
                return None, f'holdings[{idx}] must be an object'
            symbol = str(row.get('sym') or '').strip()
            if not _HOLDING_SYMBOL.fullmatch(symbol):
                return None, f'holdings[{idx}].sym is invalid'
            try:
                weight = float(row.get('weight', 1))
            except (TypeError, ValueError):
                return None, f'holdings[{idx}].weight must be numeric'
            if not math.isfinite(weight) or weight <= 0 or weight > 1e12:
                return None, f'holdings[{idx}].weight must be positive'
            clean_holdings.append({'sym': symbol, 'weight': weight})

        portfolio_kind = str(body.get('portfolioKind') or 'actual')
        if portfolio_kind not in ('actual', 'observation_pool'):
            return None, 'portfolioKind must be actual or observation_pool'
        return {
            'riskProfile': risk_profile,
            'holdings': clean_holdings,
            'portfolioKind': portfolio_kind,
        }, None

    def _handle_decision_context(self):
        import decision_context as dc
        out = dc.latest_context() or dc.empty_context('pulse_not_ready')
        self._ok(json.dumps(out, ensure_ascii=False).encode())

    def _handle_decision_context_post(self):
        import decision_context as dc
        body, error = self._decision_body()
        if error:
            self._err(str(error), error.status)
            return
        payload, error = self._decision_payload(body or {})
        if error:
            self._err(error, 400)
            return
        risk_profile = payload['riskProfile']
        holdings = payload['holdings']
        portfolio_kind = payload['portfolioKind']
        overlay = None
        if holdings:
            try:
                import portfolio
                sector_map = None
                hook = getattr(self, '_decision_sector_map', None)
                if callable(hook):
                    sector_map = hook()
                overlay = portfolio.compute(holdings, sectors_map=sector_map)
            except Exception as exc:
                overlay = {'error': str(exc)}
        out = dc.rebuild_latest(risk_profile=risk_profile, portfolio_overlay=overlay, portfolio_kind=portfolio_kind)
        self._ok(json.dumps(out, ensure_ascii=False).encode())

    def _handle_decision_history(self):
        import decision_context as dc
        qs = parse_qs(urlparse(self.path).query)
        try:
            n = int((qs.get('n') or qs.get('limit') or ['40'])[0])
        except (TypeError, ValueError):
            n = 40
        self._ok(json.dumps(dc.history(n), ensure_ascii=False).encode())

    def _handle_key_levels(self):
        import datastore
        import key_levels
        qs = parse_qs(urlparse(self.path).query)
        symbol = str((qs.get('symbol') or ['^TWII'])[0] or '^TWII')
        if symbol not in ('^TWII', '^TWOII', '__TXF__'):
            self._err('unsupported symbol', 400)
            return
        rows = datastore.get_bars(symbol, limit=80)
        out = key_levels.calculate_key_levels(rows, symbol=symbol)
        self._ok(json.dumps(out, ensure_ascii=False).encode())

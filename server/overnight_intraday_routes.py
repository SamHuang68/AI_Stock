#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP boundary for shadow overnight/intraday research."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from http_boundary import BodyReadError, read_json_body


class OvernightIntradayRoutesMixin:
    def _overnight_intraday_market(self):
        query = parse_qs(urlparse(self.path).query)
        return str((query.get("market") or ["all"])[0] or "all")

    def _handle_overnight_intraday(self):
        import overnight_intraday
        try:
            payload = overnight_intraday.latest_cached(market=self._overnight_intraday_market())
        except ValueError as exc:
            self._err(str(exc), 400)
            return
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

    def _handle_overnight_intraday_refresh(self):
        import overnight_intraday
        try:
            body = read_json_body(self, max_bytes=2048)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        allowed = {"market", "force"}
        unknown = set((body or {}).keys()) - allowed
        if unknown:
            self._err("unsupported refresh fields", 400)
            return
        if "market" in (body or {}) and not isinstance(body["market"], str):
            self._err("market must be a string", 400)
            return
        if "force" in (body or {}) and not isinstance(body["force"], bool):
            self._err("force must be a boolean", 400)
            return
        market = str((body or {}).get("market") or self._overnight_intraday_market())
        try:
            payload = overnight_intraday.get_snapshot(market=market, force=bool((body or {}).get("force", False)))
        except ValueError as exc:
            self._err(str(exc), 400)
            return
        except Exception as exc:
            self._err(f"overnight/intraday refresh unavailable: {str(exc)[:160]}", 502)
            return
        self._ok(json.dumps(payload, ensure_ascii=False).encode())

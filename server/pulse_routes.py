#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP handlers for /pulse and pulse history sync."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from http_boundary import BodyReadError, read_json_body
from pulse_orchestration import build_pulse_payload


class PulseRoutesMixin:
    def _handle_pulse(self):
        """GET /pulse — market pulse intelligence (orchestrated in pulse_orchestration)."""
        body = build_pulse_payload(self, self.path)
        self._ok(body)

    def _handle_pulse_history(self):
        """GET /pulse/history?kind=breadth|institutional|index|pulse&n=40"""
        qs = parse_qs(urlparse(self.path).query)
        kind = (qs.get('kind', ['breadth'])[0] or 'breadth').lower()
        n = qs.get('n', ['40'])[0]
        try:
            n = int(n)
        except Exception:
            n = 40
        try:
            import pulse_history as ph
            self._ok(json.dumps(ph.history(kind=kind, n=n), ensure_ascii=False).encode())
        except Exception as e:
            self._err('pulse history failed: ' + str(e), 500)

    def _handle_sync(self):
        """POST /sync — background merge. A read must never start work."""
        try:
            body = read_json_body(self, max_bytes=4096)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        qs = parse_qs(urlparse(self.path).query)
        days = body.get('days', (qs.get('days') or ['40'])[0])
        try:
            days = max(5, min(120, int(days)))
        except Exception:
            days = 40
        force_value = body.get('full', (qs.get('full') or ['0'])[0])
        force = force_value is True or str(force_value or '').lower() in ('1', 'true', 'yes')
        try:
            import pulse_history as ph
            started = ph.start_background_sync(days=days, force_full=force)
            self._ok(json.dumps({
                'ok': True, 'started': bool(started),
                'message': '同步已啟動（背景 merge）' if started else '同步進行中',
                'status': ph.status(),
            }, ensure_ascii=False).encode())
        except Exception as e:
            self._err('sync failed: ' + str(e), 500)

    def _handle_sync_status(self):
        try:
            import pulse_history as ph
            self._ok(json.dumps(ph.status(), ensure_ascii=False).encode())
        except Exception as e:
            self._err('sync status failed: ' + str(e), 500)

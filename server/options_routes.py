#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP boundary for the TXO Options Structure Lab."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from http_boundary import BodyReadError, read_json_body


_EXPIRY = re.compile(r'^(?:\d{8}|\d{4}-\d{2}-\d{2})$')


class OptionsRoutesMixin:
    def _handle_options_structure(self):
        """GET returns cache only; it never hides a network refresh in a read."""
        import options_exposure
        out = options_exposure.latest_cached()
        if not out:
            out = {
                'ok': False, 'contractVersion': 2, 'model': 'st-options-structure/v2',
                'status': 'insufficient', 'shadowMode': True, 'decisionUse': 'research_only',
                'observed': {}, 'derived': {},
                'modeled': {'eligible': False, 'scenarios': []},
                'quality': {'warnings': ['NOT_REFRESHED']},
            }
        self._ok(json.dumps(out, ensure_ascii=False).encode('utf-8'))

    def _handle_options_history(self):
        """GET returns bounded compact snapshots; it never triggers a refresh."""
        import options_exposure
        qs = parse_qs(urlparse(self.path).query)
        try:
            limit = int((qs.get('limit') or ['30'])[0])
        except (TypeError, ValueError):
            self._err('limit must be an integer', 400)
            return
        if limit < 1 or limit > 180:
            self._err('limit must be between 1 and 180', 400)
            return
        expiry = (qs.get('expiry') or [None])[0]
        if expiry is not None and not _EXPIRY.fullmatch(str(expiry).strip()):
            self._err('expiry must be YYYYMMDD or YYYY-MM-DD', 400)
            return
        try:
            out = options_exposure.history(limit=limit, expiry=str(expiry).strip() if expiry else None)
        except options_exposure.OptionsHistoryCorruptError:
            self._err('options history is temporarily unavailable', 500)
            return
        except ValueError as exc:
            self._err(str(exc), 400)
            return
        self._ok(json.dumps(out, ensure_ascii=False).encode('utf-8'))

    def _handle_options_refresh(self):
        import decision_context as dc
        import job_queue
        from 更新路由 import coordinator

        if str(self.headers.get('X-ST-Gateway-Role', '')).lower() not in ('', 'owner'):
            self._err('唯讀模式不能更新選擇權資料', 403)
            return

        try:
            body = read_json_body(self, max_bytes=4096)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        qs = parse_qs(urlparse(self.path).query)
        if set(body) - {'expiry', 'force'}:
            self._err('選擇權更新含有未支援欄位', 400)
            return
        expiry = body.get('expiry') or (qs.get('expiry') or [None])[0]
        if expiry is not None and not _EXPIRY.fullmatch(str(expiry).strip()):
            self._err('expiry must be YYYYMMDD or YYYY-MM-DD', 400)
            return
        reference = dc.latest_market_reference()
        if not reference:
            self._err('DecisionContext 尚未形成；請先更新市場資料。', 409)
            return
        try:
            params = {'force': body.get('force', True)}
            if expiry is not None:
                params['expiry'] = str(expiry).strip()
            out = coordinator().submit('options', params)
            self._ok(json.dumps(out, ensure_ascii=False).encode('utf-8'), status=202)
        except ValueError as exc:
            self._err(str(exc), 400)
        except job_queue.QueueFull as exc:
            self._err(str(exc), 429)
        except Exception:
            self._err('選擇權工作尚未接受，請稍後重試', 503)

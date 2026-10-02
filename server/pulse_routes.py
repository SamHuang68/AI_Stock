#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP handlers for /pulse and pulse history sync."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from http_boundary import BodyReadError, read_json_body
from pulse_orchestration import build_pulse_payload


class PulseRoutesMixin:
    def _handle_pulse(self):
        """僅讀已持久提交的快照；refresh 查詢也不啟動來源。"""
        import decision_context as dc
        try:
            payload = dc.latest_pulse() or {'ok': False, 'error': '尚未有已提交快照',
                'decisionSummary': dc.compact_context(dc.empty_context('pulse_not_ready'))}
            payload['updateState'] = self._pulse_service().status()
            self._ok(json.dumps(payload, ensure_ascii=False).encode())
        except Exception:
            self._err('已提交市場快照無法讀取', 503)

    def _handle_pulse_update_status(self):
        qs = parse_qs(urlparse(self.path).query)
        job_id = (qs.get('jobId') or [None])[0]
        if job_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', job_id):
            self._err('更新工作識別碼格式不正確', 400)
            return
        try:
            result = self._pulse_service().status(job_id)
            if job_id is not None and result.get('job') is None:
                self._err('找不到指定市場更新工作', 404)
                return
            self._ok(json.dumps(result, ensure_ascii=False).encode())
        except Exception:
            self._err('市場更新狀態無法讀取', 503)

    def _handle_pulse_refresh(self):
        if str(self.headers.get('X-ST-Gateway-Role', '')).lower() not in ('', 'owner'):
            self._err('唯讀模式不能更新市場資料', 403)
            return
        try:
            body = read_json_body(self, max_bytes=1024)
            if body:
                self._err('Pulse 更新只接受空物件', 400)
                return
            result = self._pulse_service().submit(reason='manual')
            self._ok(json.dumps({'ok': True, **result}, ensure_ascii=False).encode(), status=202)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
        except Exception:
            self._err('更新工作尚未接受，請稍後重試', 503)

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

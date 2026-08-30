# -*- coding: utf-8 -*-
"""ETF HTTP handlers mixin（H2 續拆 server.py）"""
from __future__ import annotations

import json
import os
import shutil
import threading
from urllib.parse import parse_qs, urlparse

import etf_api
from atomic_store import atomic_write_json
from http_boundary import BodyReadError, read_json_body


class EtfRoutesMixin:
    def _handle_etf_catalog_get(self):
        if not os.path.isfile(etf_api.ETF_CATALOG_FILE):
            self._err('etf_catalog.json not found', 404); return
        try:
            with open(etf_api.ETF_CATALOG_FILE, 'rb') as f:
                data = f.read()
            self._ok(data)
        except Exception as e:
            self._err('read catalog failed: ' + str(e), 500)

    def _handle_etf_catalog_post(self):
        try:
            obj = read_json_body(self, max_bytes=512 * 1024)
            if 'categories' not in obj:
                self._err('invalid catalog: missing categories', 400); return
            if not isinstance(obj.get('categories'), list):
                self._err('invalid catalog: categories must be an array', 422); return
            atomic_write_json(etf_api.ETF_CATALOG_FILE, obj, backup=True)
            n = sum(
                1 for c in obj.get('categories', [])
                for e in c.get('etfs', []) if e.get('enabled')
            )
            self._ok(json.dumps({'ok': True, 'enabledCount': n}).encode())
        except BodyReadError as e:
            self._err(str(e), e.status)
        except Exception as e:
            self._err('save catalog failed: ' + str(e), 500)

    def _handle_tracker_run(self):
        with etf_api._tracker_lock:
            if etf_api._tracker_state['running']:
                self._err('tracker already running', 409); return
            etf_api._tracker_state.update({
                'running': True, 'startedAt': __import__('time').time(),
                'finishedAt': None, 'lastReturnCode': None, 'lastOutput': '',
            })
        t = threading.Thread(target=etf_api._run_tracker_async, daemon=True)
        t.start()
        self._ok(json.dumps({'ok': True, 'started': True}).encode())

    def _handle_tracker_status(self):
        with etf_api._tracker_lock:
            state = dict(etf_api._tracker_state)
        self._ok(json.dumps(state, ensure_ascii=False).encode())

    def _handle_etf_delta(self):
        files = etf_api.list_etf_files()
        d = etf_api.find_etf_dir() or 'not found'
        health = etf_api.etf_history_status()
        if self.path.startswith('/etf-delta/list'):
            dates = [
                os.path.basename(f).replace('top10_active_etf_holdings_', '').replace('.json', '')
                for f in files
            ]
            self._ok(json.dumps({'dates': dates, 'dir': d, 'health': health}).encode())
            return
        if len(files) < 2:
            msg = (
                f'need ≥2 history files; found {len(files)} in dir={d}. '
                f'執行 etf_delta_tracker.py 累積每日快照'
            )
            self._err(msg)
            return
        qs = parse_qs(urlparse(self.path).query)
        date = qs.get('date', [None])[0]
        try:
            result = etf_api.compute_etf_delta(files, date)
        except Exception as e:
            self._err(str(e), 500); return
        if result is None:
            self._err('delta compute failed'); return
        result['meta'] = {'history': health}
        self._ok(json.dumps(result, ensure_ascii=False).encode())

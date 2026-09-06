#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Conditional Expectation scaffold and asOf gate."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

import conditional_expectation as ce  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))


class ConditionalExpectationGateTests(unittest.TestCase):
    def test_fresh_quote_and_recent_chips_are_usable(self):
        now = datetime(2026, 9, 6, 15, 0, tzinfo=TZ_TPE)
        quote = {
            'asOf': '2026-09-06T13:30:00+08:00',
            'session': 'closed',
        }
        chips = {'asOf': '2026-09-05'}
        gate = ce.evaluate_asof_gate(quote=quote, chips=chips, now=now)
        self.assertTrue(gate['usable'])
        self.assertEqual(gate['status'], 'fresh')
        self.assertEqual(gate['reasons'], [])

    def test_stale_quote_marks_gate_expired(self):
        now = datetime(2026, 9, 7, 10, 0, tzinfo=TZ_TPE)
        quote = {
            'asOf': '2026-09-05T13:30:00+08:00',
            'session': 'closed',
        }
        gate = ce.evaluate_asof_gate(quote=quote, chips={'asOf': '2026-09-05'}, now=now)
        self.assertFalse(gate['usable'])
        self.assertEqual(gate['status'], 'expired')
        self.assertTrue(gate['reasons'])

    def test_build_card_is_scaffold_and_conditional(self):
        card = ce.build_card(
            '2330',
            quote={'asOf': '2026-09-06T13:30:00+08:00', 'session': 'closed'},
            chips={'asOf': '2026-09-05'},
            now=datetime(2026, 9, 6, 15, 0, tzinfo=TZ_TPE),
        )
        self.assertEqual(card['epistemic'], 'CONDITIONAL')
        self.assertEqual(card['status'], 'SCAFFOLD')
        self.assertTrue(card['shadowOnly'])
        self.assertFalse(card['predictiveProbability'])
        self.assertIn('bin_engine_not_implemented', card['invalidIf'])
        self.assertEqual(card['horizons']['1']['n'], 0)
        self.assertFalse(card['horizons']['1']['ratesAvailable'])


def _load_server():
    import importlib.util
    spec = importlib.util.spec_from_file_location('st_cond_exp_http', SERVER_DIR / 'server.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('unable to load server')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConditionalExpectationRouteTests(unittest.TestCase):
    _ENV_KEYS = (
        'ST_ENABLE_SHADOW_RESEARCH',
        'ST_SHADOW_CONDITIONAL_EXPECTATION',
    )

    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in self._ENV_KEYS}
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_disabled_route_returns_cheap_payload(self):
        st_server = _load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            with urllib.request.urlopen(
                base + '/research/conditional-expectation?symbol=2330', timeout=3,
            ) as resp:
                body = json.load(resp)
            self.assertEqual(resp.status, 200)
            self.assertFalse(body['enabled'])
            self.assertFalse(body['ok'])
            self.assertEqual(body['epistemic'], 'CONDITIONAL')
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()

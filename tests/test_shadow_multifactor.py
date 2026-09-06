#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for P2 shadow multifactor research (default OFF, no Decision writes)."""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import unittest
import urllib.request
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

import shadow_multifactor as sm  # noqa: E402
import promotion_gate as pg  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))


def _bar_day(base: date, close: float, offset: int = 0) -> tuple:
    day = base + timedelta(days=offset)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    ts = datetime.combine(day, datetime.min.time().replace(hour=13, minute=30), TZ_TPE).timestamp()
    return (ts, close, close, close, close, 1_000_000)


def _synthetic_bars(n: int = 200, start_close: float = 100.0, drift: float = 0.2) -> list:
    base = date(2024, 1, 2)
    rows = []
    close = start_close
    for i in range(n):
        close = max(1.0, close + drift + (0.05 if i % 7 == 0 else -0.02))
        rows.append(_bar_day(base, close, i))
    return rows


class ShadowMultifactorUnitTests(unittest.TestCase):
    def test_disabled_payload_is_shadow_only(self):
        payload = sm.disabled_payload()
        self.assertFalse(payload['enabled'])
        self.assertTrue(payload['shadowOnly'])
        self.assertEqual(payload['decisionUse'], 'research_only')
        self.assertEqual(payload['promotionGate']['verdict'], 'FAIL')

    def test_research_score_bounded(self):
        factors = {
            'deviationZ': 2.5,
            'relativeStrengthPct': 95.0,
            'momentum60d': 25.0,
            'volRatio': 1.8,
        }
        score = sm.research_score(factors)
        self.assertTrue(-1.0 <= score <= 1.0)

    def test_ml_stub_is_hypothesis_tier(self):
        stub = sm.ml_experiment_stub({
            'deviationZ': 0.5,
            'relativeStrengthPct': 60.0,
            'momentum60d': 5.0,
            'volRatio': 1.1,
            'rsi14': 55.0,
        })
        self.assertEqual(stub['epistemic'], 'HYPOTHESIS')
        self.assertEqual(stub['status'], 'EXPERIMENT_STUB')

    def test_factor_vector_requires_min_bars(self):
        short = _synthetic_bars(50)
        self.assertIsNone(sm._factor_vector('2330', bars=short, as_of=date(2024, 3, 1)))

    def test_rank_cross_section_with_synthetic_bars(self):
        bars = _synthetic_bars(220, drift=0.3)
        with patch.object(sm, '_load_bars', return_value=bars):
            ranking = sm.rank_cross_section(['AAA', 'BBB'], as_of=date(2024, 8, 1), limit=5)
        self.assertEqual(ranking['epistemic'], 'CONDITIONAL')
        self.assertGreaterEqual(len(ranking['basket']), 1)
        self.assertEqual(ranking['promotionGate']['verdict'], 'FAIL')
        for row in ranking['basket']:
            self.assertIn('CONDITIONAL', row['label'])
            self.assertIn('rankScore', row)

    def test_stale_asof_degrades_rank_score(self):
        bars = _synthetic_bars(220)
        stale_quote = {'asOf': '2020-01-01T09:00:00'}
        with patch.object(sm, '_load_bars', return_value=bars):
            ranking = sm.rank_cross_section(
                ['AAA'],
                as_of=date(2024, 8, 1),
                quote_lookup=lambda _s: stale_quote,
                limit=1,
            )
        row = ranking['basket'][0]
        self.assertTrue(row['degraded'])
        self.assertFalse(row['asOfGate']['usable'])

    def test_long_horizon_card_includes_60_120(self):
        bars = _synthetic_bars(300, drift=0.1)
        card = sm._long_horizon_card('2330', bars=bars)
        if card is not None:
            self.assertIn('60', card['horizons'])
            self.assertIn('120', card['horizons'])


class ShadowMultifactorRouteTests(unittest.TestCase):
    _ENV_KEYS = (
        'ST_ENABLE_SHADOW_RESEARCH',
        'ST_SHADOW_MULTIFACTOR',
        'ST_SHADOW_ML_EXPERIMENT',
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

    def _load_server(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('st_p2_http', SERVER_DIR / 'server.py')
        if spec is None or spec.loader is None:
            raise RuntimeError('unable to load server')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_route_disabled_by_default(self):
        st_server = self._load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            with urllib.request.urlopen(base + '/research/shadow-multifactor', timeout=5) as resp:
                body = json.load(resp)
            self.assertEqual(resp.status, 200)
            self.assertFalse(body['enabled'])
            self.assertIn('SHADOW_DISABLED', body.get('reason', ''))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_promotion_gate_defaults_fail(self):
        st_server = self._load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            with urllib.request.urlopen(base + '/research/promotion-gate', timeout=5) as resp:
                body = json.load(resp)
            self.assertEqual(body['verdict'], 'FAIL')
            self.assertFalse(body['autoPromote'])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_route_returns_ranking_when_flag_on(self):
        os.environ['ST_SHADOW_MULTIFACTOR'] = '1'
        bars = _synthetic_bars(220, drift=0.25)
        st_server = self._load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            with patch.object(sm, '_load_bars', return_value=bars):
                with urllib.request.urlopen(
                    base + '/research/shadow-multifactor?symbols=AAA,BBB&limit=2', timeout=10,
                ) as resp:
                    body = json.load(resp)
            self.assertTrue(body['enabled'])
            self.assertTrue(body['shadowOnly'])
            self.assertEqual(body['decisionUse'], 'research_only')
            self.assertIn('basket', body['ranking'])
            self.assertEqual(body['promotionGate']['verdict'], 'FAIL')
            self.assertIn('No production Decision wiring', body['nonGoals'][0])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_no_llm_gate_on_shadow_route(self):
        """Shadow multifactor must not acquire llm_gate."""
        os.environ['ST_SHADOW_MULTIFACTOR'] = '1'
        import llm_gate
        st_server = self._load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        held_before = llm_gate.status()['held']
        try:
            with patch.object(sm, '_load_bars', return_value=_synthetic_bars(220)):
                with urllib.request.urlopen(base + '/research/shadow-multifactor?symbols=AAA', timeout=10):
                    pass
            self.assertEqual(llm_gate.status()['held'], held_before)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()

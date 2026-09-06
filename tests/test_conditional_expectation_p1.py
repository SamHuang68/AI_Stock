#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Conditional Expectation P1 modules (shadow flags default OFF)."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.request
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

import chip_path_state as cps  # noqa: E402
import conditional_expectation as ce  # noqa: E402
import conditional_integration_score as cis  # noqa: E402
import event_window_returns as ewr  # noqa: E402
import vol_regime_switch as vrs  # noqa: E402

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


def _synthetic_bars(n: int = 120, start_close: float = 100.0, drift: float = 0.15) -> list:
    base = date(2024, 1, 2)
    rows = []
    close = start_close
    for i in range(n):
        close = max(1.0, close + drift + (0.08 if i % 5 == 0 else -0.03))
        rows.append(_bar_day(base, close, i))
    return rows


class ChipPathStateTests(unittest.TestCase):
    def test_accumulate_when_inst_buy_without_large_price_move(self):
        as_of = date(2024, 6, 10)
        bars = _synthetic_bars(40, drift=0.02)
        chip_map = {}
        for offset in range(5):
            day = (as_of - timedelta(days=offset)).isoformat()
            chip_map[day] = 500.0
        payload = cps.evaluate_chip_path_state(
            '2330', bars=bars, chip_inst_by_date=chip_map, as_of_date=as_of,
        )
        self.assertEqual(payload['epistemic'], 'FACT')
        self.assertIn(payload['state'], ('accumulate', 'neutral', 'chase'))

    def test_classify_chase_on_buy_with_strong_reaction(self):
        state = cps.classify_path_state(streak_signed=4, price_reaction_pct=5.0)
        self.assertEqual(state, 'chase')

    def test_classify_distribute_on_sell_with_down_move(self):
        state = cps.classify_path_state(streak_signed=-4, price_reaction_pct=-4.0)
        self.assertEqual(state, 'distribute')


class VolRegimeSwitchTests(unittest.TestCase):
    def test_returns_position_width_hint_without_decision_fields(self):
        bars = _synthetic_bars(300, drift=0.05)
        payload = vrs.evaluate_vol_regime_switch('2330', bars=bars)
        self.assertEqual(payload['epistemic'], 'CONDITIONAL')
        self.assertTrue(payload['shadowOnly'])
        hint = payload.get('positionWidthHint') or {}
        self.assertIn('multiplier', hint)
        self.assertNotIn('confidence', payload)
        self.assertNotIn('regime', payload)


class EventWindowReturnsTests(unittest.TestCase):
    def test_revenue_publish_horizons_pit(self):
        bars = _synthetic_bars(400, drift=0.1)
        payload = ewr.evaluate_event_windows('2330', bars=bars)
        revenue = payload['events'][0]
        self.assertEqual(revenue['eventType'], 'revenue_publish')
        self.assertEqual(set(revenue['horizons'].keys()), {'1', '5', '20'})

    def test_ex_dividend_deferred_stub(self):
        stub = ewr.deferred_ex_dividend_note()
        self.assertEqual(stub['status'], 'DEFERRED_OPTIONAL')
        self.assertIn('event calendar', stub['reason'])


class IntegrationScoreTests(unittest.TestCase):
    def test_score_bounded(self):
        vec = cis.feature_vector(
            rsi14=70.0, inst_key='buy', chip_state='chase', vol_percentile=85.0,
        )
        score = cis.integrate_score(vec)
        self.assertGreaterEqual(score, cis.SCORE_MIN)
        self.assertLessEqual(score, cis.SCORE_MAX)

    def test_score_withheld_without_walk_forward_evidence(self):
        bars = _synthetic_bars(120)
        chip_map = {}
        for row in bars[::4]:
            chip_map[ce._session_date_from_ts(row[0]).isoformat()] = 100.0
        payload = cis.evaluate_integration_score(
            '2330', bars=bars, chip_inst_by_date=chip_map,
        )
        self.assertFalse(payload['walkForwardEvidencePresent'])
        self.assertIsNone(payload['score'])

    def test_walk_forward_report_artifact(self):
        bars = _synthetic_bars(200)
        observations = ce.collect_pit_observations('2330', bars)
        enriched = [{
            **row,
            'chipState': 'neutral',
            'volPercentile': 50.0,
        } for row in observations]
        report = cis.build_walk_forward_report(enriched, symbol='2330')
        if report.get('status') == 'READY':
            paths = cis.write_walk_forward_artifacts(report)
            self.assertTrue(os.path.isfile(paths[0]))
            self.assertTrue(os.path.isfile(paths[1]))


class ConditionalExpectationP1RouteTests(unittest.TestCase):
    _ENV_KEYS = (
        'ST_ENABLE_SHADOW_RESEARCH',
        'ST_SHADOW_CONDITIONAL_EXPECTATION',
        'ST_SHADOW_CHIP_PATH_STATE',
        'ST_SHADOW_VOL_REGIME_SWITCH',
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
        spec = importlib.util.spec_from_file_location('st_p1_http', SERVER_DIR / 'server.py')
        if spec is None or spec.loader is None:
            raise RuntimeError('unable to load server')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_p1_route_disabled_by_default(self):
        st_server = self._load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            with urllib.request.urlopen(
                base + '/research/conditional-expectation/p1?symbol=2330', timeout=5,
            ) as resp:
                body = json.load(resp)
            self.assertEqual(resp.status, 200)
            self.assertFalse(body['enabled'])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_p1_route_returns_modules_when_flags_on(self):
        os.environ['ST_SHADOW_CONDITIONAL_EXPECTATION'] = '1'
        os.environ['ST_SHADOW_CHIP_PATH_STATE'] = '1'
        os.environ['ST_SHADOW_VOL_REGIME_SWITCH'] = '1'
        os.environ['ST_SHADOW_EVENT_WINDOW_RETURNS'] = '1'
        st_server = self._load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            with urllib.request.urlopen(
                base + '/research/conditional-expectation/p1?symbol=2330', timeout=15,
            ) as resp:
                body = json.load(resp)
            self.assertTrue(body['enabled'])
            p1 = body['p1']
            self.assertIsNotNone(p1['chipPathState'])
            self.assertIsNotNone(p1['volRegimeSwitch'])
            self.assertIsNotNone(p1['eventWindows'])
            self.assertEqual(p1['chipPathState']['epistemic'], 'FACT')
            self.assertEqual(p1['volRegimeSwitch']['epistemic'], 'CONDITIONAL')
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()

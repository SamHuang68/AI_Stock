#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Conditional Expectation P1 must-ship modules (shadow flags default OFF)."""
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
import conditional_expectation_p1 as p1  # noqa: E402
import event_window_returns as ewr  # noqa: E402
import conditional_integration_score as cis  # noqa: E402
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


class DeviationZBinTests(unittest.TestCase):
    def test_bin_state_includes_devz_and_rs_bands(self):
        bars = _synthetic_bars(100)
        as_of = ce._session_date_from_ts(bars[60][0])
        state = ce.bin_state(
            '2330', as_of, bars=bars, chip_inst_by_date={'2024-03-01': 100.0}, regime_id='TEST',
        )
        self.assertEqual(state['binModelId'], ce.BIN_MODEL_ID)
        self.assertIn('devz', state['binId'])
        self.assertIn('rs_', state['binId'])
        self.assertIn('deviationZ', state['features'])
        self.assertIn('relativeStrengthPct', state['features'])

    def test_deviation_z_is_pit_on_truncated_series(self):
        bars = _synthetic_bars(80, drift=0.0)
        as_of = ce._session_date_from_ts(bars[40][0])
        pit_closes = [float(row[4]) for row in ce._bars_upto_date(bars, as_of)]
        future = _synthetic_bars(30, start_close=500.0, drift=5.0)
        # Shift future bars to sessions strictly after as_of
        shift = (as_of - ce._session_date_from_ts(future[0][0])).days + 1
        shifted_future = []
        for row in future:
            day = ce._session_date_from_ts(row[0]) + timedelta(days=shift)
            while day.weekday() >= 5:
                day += timedelta(days=1)
            ts = datetime.combine(day, datetime.min.time().replace(hour=13, minute=30), TZ_TPE).timestamp()
            shifted_future.append((ts, row[1], row[2], row[3], row[4], row[5]))
        extended = list(bars) + shifted_future
        pit_after = [float(row[4]) for row in ce._bars_upto_date(extended, as_of)]
        self.assertEqual(pit_closes, pit_after)
        self.assertEqual(ce._deviation_z(pit_closes), ce._deviation_z(pit_after))


class ChipPathStateTests(unittest.TestCase):
    def test_neutral_when_chips_asof_missing(self):
        bars = _synthetic_bars(40)
        payload = cps.evaluate_chip_path_state('2330', bars=bars, chips=None)
        self.assertEqual(payload['state'], 'neutral')
        self.assertEqual(payload['status'], 'CHIPS_ASOF_EXPIRED')

    def test_classify_chase_on_buy_with_strong_reaction(self):
        self.assertEqual(cps.classify_path_state(streak_signed=4, price_reaction_pct=5.0), 'chase')

    def test_accumulate_on_buy_without_large_move(self):
        now = datetime(2024, 6, 12, 15, 0, tzinfo=TZ_TPE)
        as_of = date(2024, 6, 10)
        bars = _synthetic_bars(40, drift=0.02)
        chip_map = { (as_of - timedelta(days=i)).isoformat(): 500.0 for i in range(5) }
        payload = cps.evaluate_chip_path_state(
            '2330',
            bars=bars,
            chip_inst_by_date=chip_map,
            chips={'asOf': as_of.isoformat()},
            as_of_date=as_of,
            now=now,
        )
        self.assertEqual(payload['status'], 'READY')
        self.assertIn(payload['state'], ('accumulate', 'neutral'))


class VolRegimeSwitchTests(unittest.TestCase):
    def test_width_and_caution_only_no_buy_sell_score(self):
        bars = _synthetic_bars(300, drift=0.05)
        payload = vrs.evaluate_vol_regime_switch('2330', bars=bars)
        hint = payload.get('positionWidthHint') or {}
        self.assertIn('multiplier', hint)
        self.assertIn('caution', hint)
        self.assertNotIn('score', payload)
        self.assertNotIn('confidence', payload)


class DeferredModuleTests(unittest.TestCase):
    def test_event_windows_deferred(self):
        note = ewr.deferred_event_windows_note()
        self.assertEqual(note['status'], 'DEFERRED_OPTIONAL')
        self.assertIn('event calendar', note['reason'])

    def test_integration_score_deferred(self):
        note = cis.deferred_integration_score_note()
        self.assertEqual(note['status'], 'DEFERRED')

    def test_p1_orchestrator_lists_deferred(self):
        payload = p1.build_p1_research('2330', bars=_synthetic_bars(80))
        self.assertEqual(payload['deferred']['eventWindows']['status'], 'DEFERRED_OPTIONAL')
        self.assertEqual(payload['deferred']['integrationScore']['status'], 'DEFERRED')


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

    def test_p1_route_returns_must_ship_modules_when_flags_on(self):
        os.environ['ST_SHADOW_CONDITIONAL_EXPECTATION'] = '1'
        os.environ['ST_SHADOW_CHIP_PATH_STATE'] = '1'
        os.environ['ST_SHADOW_VOL_REGIME_SWITCH'] = '1'
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
            p1_payload = body['p1']
            self.assertEqual(p1_payload.get('binModelId'), ce.BIN_MODEL_ID)
            self.assertIsNotNone(p1_payload['volRegimeSwitch'])
            self.assertEqual(p1_payload['deferred']['integrationScore']['status'], 'DEFERRED')
            self.assertNotIn('eventWindows', p1_payload)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()

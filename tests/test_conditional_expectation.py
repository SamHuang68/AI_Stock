#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Conditional Expectation PIT bin engine, asOf gate, and route."""
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

import conditional_expectation as ce  # noqa: E402
import indicators as ind  # noqa: E402

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


def _synthetic_bars(n: int = 80, start_close: float = 100.0, drift: float = 0.2) -> list:
    base = date(2025, 1, 2)
    rows = []
    close = start_close
    for i in range(n):
        close = max(1.0, close + drift + (0.1 if i % 7 == 0 else -0.05))
        rows.append(_bar_day(base, close, i))
    return rows


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


class ConditionalExpectationBinTests(unittest.TestCase):
    def test_bin_state_uses_only_bars_upto_as_of(self):
        bars = _synthetic_bars(60)
        as_of = ce._session_date_from_ts(bars[30][0])
        state = ce.bin_state(
            '2330',
            as_of,
            bars=bars,
            chip_inst_by_date={'2025-01-10': 100.0, '2025-01-11': 50.0},
            regime_id='BROAD_RISK_ON',
        )
        self.assertEqual(state['binModelId'], ce.BIN_MODEL_ID)
        self.assertTrue(state['binId'].startswith('rsi'))
        self.assertIn('devz', state['binId'])
        self.assertIn('rs_', state['binId'])
        self.assertIn('inst', state['binId'])
        self.assertIn('regBROAD_RISK_ON', state['binId'])
        self.assertLessEqual(
            ce._chip_session_date(state['evidenceAsOf']['chips']),
            as_of,
        )

    def test_aggregate_requires_minimum_sample(self):
        obs = []
        for i in range(15):
            obs.append({
                'binId': 'rsi40_instbuy_regTEST',
                'outcomes': {
                    '1': {'returnPct': 1.0, 'maxDrawdownPct': -0.5},
                    '5': {'returnPct': 2.0, 'maxDrawdownPct': -1.0},
                    '20': {'returnPct': 3.0, 'maxDrawdownPct': -2.0},
                },
            })
        stats = ce.aggregate_bin_stats(obs, 'rsi40_instbuy_regTEST')
        self.assertEqual(stats['1']['n'], 15)
        self.assertFalse(stats['1']['ratesAvailable'])
        self.assertIsNone(stats['1']['medianReturnPct'])

        for i in range(10):
            obs.append({
                'binId': 'rsi40_instbuy_regTEST',
                'outcomes': {
                    '1': {'returnPct': 1.0, 'maxDrawdownPct': -0.5},
                    '5': {'returnPct': 2.0, 'maxDrawdownPct': -1.0},
                    '20': {'returnPct': 3.0, 'maxDrawdownPct': -2.0},
                },
            })
        stats = ce.aggregate_bin_stats(obs, 'rsi40_instbuy_regTEST')
        self.assertEqual(stats['1']['n'], 25)
        self.assertTrue(stats['1']['ratesAvailable'])
        self.assertIsNotNone(stats['1']['medianReturnPct'])
        self.assertIsNotNone(stats['1']['winRate'])
        self.assertIsNotNone(stats['1']['maxDrawdownQ90Pct'])

    def test_build_card_returns_real_horizons_when_flag_data_present(self):
        bars = _synthetic_bars(100)
        chip_map = {}
        for row in bars[::3]:
            day = ce._session_date_from_ts(row[0]).isoformat()
            chip_map[day] = 10.0
        quote = {
            'asOf': datetime.fromtimestamp(bars[-1][0], TZ_TPE).isoformat(),
            'session': 'closed',
        }
        now = datetime.fromtimestamp(bars[-1][0], TZ_TPE) + timedelta(hours=2)
        card = ce.build_card(
            '2330',
            quote=quote,
            chips={'asOf': ce._session_date_from_ts(bars[-1][0]).isoformat()},
            bars=bars,
            chip_inst_by_date=chip_map,
            now=now,
            regime_lookup=lambda _d: 'BROAD_RISK_ON',
        )
        self.assertEqual(card['epistemic'], 'CONDITIONAL')
        self.assertIn(card['status'], ('READY', 'INSUFFICIENT_DATA'))
        self.assertTrue(card['shadowOnly'])
        self.assertFalse(card['predictiveProbability'])
        self.assertIsNotNone(card['binId'])
        self.assertEqual(set(card['horizons'].keys()), {'1', '5', '20'})
        for key in ('medianReturnPct', 'winRate', 'n', 'maxDrawdownQ90Pct', 'ratesAvailable'):
            self.assertIn(key, card['horizons']['1'])
        self.assertNotIn('bin_engine_not_implemented', card['invalidIf'])


class ConditionalExpectationLeakageSmokeTests(unittest.TestCase):
    def test_future_bar_does_not_change_pit_features(self):
        bars = _synthetic_bars(50, start_close=50.0, drift=0.0)
        as_of = ce._session_date_from_ts(bars[25][0])
        before = ce.bin_state('2330', as_of, bars=bars[:26], regime_id='TEST')
        after = ce.bin_state('2330', as_of, bars=bars, regime_id='TEST')
        self.assertEqual(before['features']['rsi14'], after['features']['rsi14'])
        self.assertEqual(before['features']['close'], after['features']['close'])

    def test_rsi_matches_truncated_indicator_series(self):
        bars = _synthetic_bars(40)
        as_of = ce._session_date_from_ts(bars[30][0])
        pit_bars = ce._bars_upto_date(bars, as_of)
        closes = [float(row[4]) for row in pit_bars]
        expected = ind.rsi_wilders(closes, 14)
        state = ce.bin_state('2330', as_of, bars=bars, regime_id='TEST')
        self.assertAlmostEqual(state['features']['rsi14'], expected, places=6)

    def test_forward_outcome_uses_only_future_sessions_after_origin(self):
        bars = _synthetic_bars(30, start_close=100.0, drift=1.0)
        outcome = ce._forward_outcome(bars, 10, 5)
        self.assertIsNotNone(outcome)
        entry = float(bars[10][4])
        exit_close = float(bars[15][4])
        self.assertAlmostEqual(outcome['returnPct'], (exit_close / entry - 1.0) * 100.0, places=6)


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

    def test_enabled_route_returns_card_with_horizons(self):
        os.environ['ST_SHADOW_CONDITIONAL_EXPECTATION'] = '1'
        st_server = _load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            with urllib.request.urlopen(
                base + '/research/conditional-expectation?symbol=2330', timeout=10,
            ) as resp:
                body = json.load(resp)
            self.assertEqual(resp.status, 200)
            self.assertTrue(body['enabled'])
            card = body['card']
            self.assertEqual(card['epistemic'], 'CONDITIONAL')
            self.assertIn('horizons', card)
            self.assertEqual(set(card['horizons'].keys()), {'1', '5', '20'})
            self.assertIn('pitAssumptions', card)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()

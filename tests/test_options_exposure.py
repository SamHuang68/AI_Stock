#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import os
import sys
import json
import tempfile
import unittest
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'server')
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import options_exposure as ox


class BlackScholesTests(unittest.TestCase):
    def test_standard_fixture_and_parity(self):
        args = dict(spot=100.0, strike=100.0, years=0.5, risk_free_rate=0.02,
                    dividend_yield=0.01, sigma=0.20)
        call = ox.black_scholes(call_put='C', **args)
        put = ox.black_scholes(call_put='P', **args)
        self.assertAlmostEqual(call['d1'], 0.1060660172, places=9)
        self.assertAlmostEqual(call['price'], 5.846717441, places=8)
        self.assertAlmostEqual(put['price'], 5.350452896, places=8)
        self.assertAlmostEqual(call['delta'], 0.539530605, places=8)
        self.assertAlmostEqual(put['delta'], -0.455481874, places=8)
        self.assertAlmostEqual(call['gamma'], 0.02791134013, places=10)
        self.assertAlmostEqual(call['vega'], 27.91134013, places=8)
        parity = 100 * math.exp(-0.01 * 0.5) - 100 * math.exp(-0.02 * 0.5)
        self.assertAlmostEqual(call['price'] - put['price'], parity, places=10)
        self.assertAlmostEqual(put['delta'], call['delta'] - math.exp(-0.01 * 0.5), places=10)

    def test_exposure_units(self):
        greeks = ox.black_scholes(100, 100, 0.5, 0.02, 0.01, 0.20, 'C')
        self.assertAlmostEqual(ox.oi_gamma_1pct_ntd(greeks['gamma'], 1000, 100), 139556.70065, places=4)
        self.assertAlmostEqual(ox.oi_vega_1vol_ntd(greeks['vega'], 1000), 13955.67006, places=4)
        self.assertAlmostEqual(ox.oi_vega_1vol_point_ntd(greeks['vega'], 1000), 13955.67006, places=4)

    def test_scenario_vex_uses_same_coefficients_as_gex(self):
        contracts = [
            {'strike': 100.0, 'callPut': 'C', 'iv': 0.20, 'openInterest': 1000},
            {'strike': 100.0, 'callPut': 'P', 'iv': 0.20, 'openInterest': 1000},
        ]
        balanced = ox._scenario_profile(
            contracts, ox.SCENARIOS[0], 100, 0.5, 0.02, 0.01, 80, 120, 1)
        stress = ox._scenario_profile(
            contracts, ox.SCENARIOS[3], 100, 0.5, 0.02, 0.01, 80, 120, 1)
        single = ox.oi_vega_1vol_point_ntd(
            ox.black_scholes(100, 100, 0.5, 0.02, 0.01, 0.20, 'C')['vega'], 1000)
        self.assertAlmostEqual(balanced['scenarioVex1VolPointNtd'], 0.0, places=6)
        self.assertAlmostEqual(stress['scenarioVex1VolPointNtd'], -2 * single, places=2)
        self.assertEqual(balanced['coefficientVersion'], ox.SCENARIO_COEFFICIENT_VERSION)

    def test_realistic_scale(self):
        greeks = ox.black_scholes(45727, 46000, 4 / 365, 0.015, 0.020, 0.25, 'C')
        self.assertAlmostEqual(greeks['price'], 353.571966, places=5)
        self.assertAlmostEqual(greeks['gamma'], 0.000325570454, places=11)
        self.assertAlmostEqual(ox.oi_gamma_1pct_ntd(greeks['gamma'], 5000, 45727),
                               1701885793.49, delta=2.0)

    def test_iv_round_trip_and_bounds(self):
        for sigma in (0.01, 0.05, 0.20, 1.0, 3.0):
            price = ox.black_scholes(100, 100, 0.4, 0.01, 0.02, sigma, 'C')['price']
            solved, error = ox.solve_implied_volatility(price, 100, 100, 0.4, 0.01, 0.02, 'C')
            self.assertIsNone(error)
            self.assertAlmostEqual(solved, sigma, places=5)
        solved, error = ox.solve_implied_volatility(500, 100, 100, 0.5, 0.01, 0.0, 'C')
        self.assertIsNone(solved)
        self.assertEqual(error, 'OUTSIDE_ARBITRAGE_BOUNDS')

    def test_flip_root_fixture(self):
        spot, years, rate, dividend, sigma = 100.0, 0.5, 0.02, 0.01, 0.20

        def signed(test_spot):
            put = ox.black_scholes(test_spot, 90, years, rate, dividend, sigma, 'P')
            call = ox.black_scholes(test_spot, 110, years, rate, dividend, sigma, 'C')
            return ox.oi_gamma_1pct_ntd(put['gamma'], 1, test_spot) - ox.oi_gamma_1pct_ntd(
                call['gamma'], 1, test_spot)

        roots = ox.find_roots(signed, 80, 120, 1)
        expected = math.sqrt(90 * 110) * math.exp(-(rate - dividend + 0.5 * sigma * sigma) * years)
        self.assertEqual(len(roots), 1)
        self.assertAlmostEqual(roots[0], expected, places=6)


def _report_row(month_week, strike, cp, settlement, oi, volume=10, session='一般', day='20260814'):
    return {
        'Date': day, 'Contract': 'TXO', 'ContractMonth(Week)': month_week,
        'StrikePrice': str(strike), 'CallPut': '買權' if cp == 'C' else '賣權',
        'SettlementPrice': str(settlement), 'Close': str(settlement),
        'OpenInterest': str(oi), 'Volume': str(volume), 'TradingSession': session,
        'BestBid': '-', 'BestAsk': '-',
    }


def _delta_row(month_week, strike, cp, delta, settlement_day):
    return {
        'Contract': 'TXO', 'ContractMonth(Week)': month_week, 'StrikePrice': str(strike),
        'CallPut': '買權' if cp == 'C' else '賣權', 'Delta': str(delta),
        'ContractSettlementDay': settlement_day,
    }


class StructureContractTests(unittest.TestCase):
    def _fixture(self):
        spot, expiry = 100.0, '20260819'
        trade = '20260814'
        years = ox._time_to_expiry('2026-08-14', '2026-08-19')
        report, delta = [], []
        for strike in (90, 95, 100, 105, 110):
            for cp in ('C', 'P'):
                price = ox.black_scholes(spot, strike, years, 0.015, 0.020, 0.25, cp)['price']
                oi = 100 + abs(strike - 100) * 10 + (200 if cp == 'C' and strike == 110 else 0)
                report.append(_report_row('202608W3', strike, cp, price, oi, day=trade))
                model_delta = ox.black_scholes(spot, strike, years, 0.015, 0.020, 0.25, cp)['delta']
                delta.append(_delta_row('202608W3', strike, cp, model_delta, expiry))
        # A duplicate night row and an expired chain must never enter the selected structure.
        report.append(_report_row('202608W3', 100, 'C', 999, 99999, session='盤後', day=trade))
        report.append(_report_row('202608F2', 100, 'C', 0, 99999, day=trade))
        return report, delta

    def test_layers_expiry_and_deduplication(self):
        report, delta = self._fixture()
        out = ox.build_options_structure(
            report, delta, spot=100, spot_as_of='2026-08-14',
            now=datetime(2026, 8, 16, tzinfo=timezone.utc))
        self.assertEqual(out['status'], 'ready')
        self.assertEqual(out['observed']['expiry'], '2026-08-19')
        self.assertEqual(out['observed']['rowCount'], 10)
        self.assertEqual(out['observed']['callWall']['strike'], 110)
        self.assertGreaterEqual(out['derived']['ivOiCoveragePct'], 99.0)
        self.assertTrue(out['modeled']['eligible'])
        self.assertGreater(out['derived']['totalOiVega1VolPointNtd'], 0)
        self.assertEqual(len(out['derived']['topVegaStrikes']), 5)
        self.assertTrue(all(row['scenarioVex1VolPointNtd'] is not None
                            for row in out['modeled']['scenarios']))
        self.assertIn('publicOiLimit', out['assumptions'])
        self.assertNotIn('dealer', out['observed'])

    def test_hybrid_timestamp_disables_model(self):
        report, delta = self._fixture()
        out = ox.build_options_structure(
            report, delta, spot=100, spot_as_of='2026-08-15',
            now=datetime(2026, 8, 16, tzinfo=timezone.utc))
        self.assertEqual(out['status'], 'stale')
        self.assertTrue(out['quality']['isHybridTimestamp'])
        self.assertFalse(out['modeled']['eligible'])
        self.assertTrue(all(row['scenarioVex1VolPointNtd'] is None
                            for row in out['modeled']['scenarios']))

    def test_zero_price_is_missing_not_zero_vol(self):
        report, delta = self._fixture()
        report[0]['SettlementPrice'] = '0'
        report[0]['Close'] = '0'
        out = ox.build_options_structure(
            report, delta, spot=100, spot_as_of='2026-08-14',
            now=datetime(2026, 8, 16, tzinfo=timezone.utc))
        self.assertIn('MISSING_PRICE', out['quality']['ivErrors'])

    def test_fetch_failure_returns_insufficient_without_fabrication(self):
        old_path = ox.CACHE_PATH
        try:
            ox.CACHE_PATH = os.path.join(ROOT, 'tests', '__missing_options_cache__.json')
            ox.clear_memory_cache()

            def fail(*_args, **_kwargs):
                raise TimeoutError('fixture timeout')

            out = ox.refresh(spot=100, spot_as_of='2026-08-14', force=True, fetcher=fail)
            self.assertEqual(out['status'], 'insufficient')
            self.assertFalse(out['modeled']['eligible'])
            self.assertEqual(out['quality']['warnings'], ['SOURCE_REFRESH_FAILED'])
        finally:
            ox.CACHE_PATH = old_path
            ox.clear_memory_cache()


class OptionsHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_history = ox.HISTORY_PATH
        ox.HISTORY_PATH = os.path.join(self.tmp.name, 'options-history.json')

    def tearDown(self):
        ox.HISTORY_PATH = self.old_history
        self.tmp.cleanup()

    @staticmethod
    def _value(trade_date, expiry='2026-08-19', *, gamma=1.0, vega=10.0,
               status='ready', hybrid=False, model=ox.MODEL_VERSION):
        return {
            'ok': status == 'ready', 'status': status, 'contractVersion': ox.CONTRACT_VERSION,
            'model': model,
            'observed': {
                'tradeDate': trade_date, 'expiry': expiry, 'session': 'day_eod',
                'spot': 100.0, 'dte': 3, 'callOpenInterest': 1000,
                'putOpenInterest': 1200, 'oiPutCallRatio': 1.2,
                'callWall': {'strike': 105}, 'putWall': {'strike': 95},
                'wallScope': {'low': 90, 'high': 110},
            },
            'derived': {
                'atmIvPct': 20.0, 'ivSkew25dPctPoint': 2.0,
                'totalOiGammaYi': gamma, 'totalOiVegaWan': vega,
                'ivOiCoveragePct': 100.0,
            },
            'modeled': {
                'eligible': True, 'directionConsensus': 'DIRECTION_AMBIGUOUS',
                'coefficientVersion': ox.SCENARIO_COEFFICIENT_VERSION,
                'flipBand': {'low': 98, 'high': 102},
            },
            'quality': {
                'fetchedAt': trade_date + 'T10:00:00+00:00',
                'isHybridTimestamp': hybrid, 'deltaCoveragePct': 100.0,
            },
        }

    def test_history_dedupes_and_compares_strict_prior_same_expiry(self):
        first = ox._record_history(self._value('2026-08-14'))
        self.assertEqual(first['status'], 'building')
        ox._record_history(self._value('2026-08-14', gamma=9.0))
        self.assertEqual(ox.history(limit=20)['total'], 1)
        second = ox._record_history(self._value('2026-08-15', gamma=2.0, vega=12.0))
        self.assertEqual(second['status'], 'ready')
        self.assertEqual(second['baselineTradeDate'], '2026-08-14')
        self.assertAlmostEqual(second['changes']['totalOiVegaPct'], 20.0)
        self.assertEqual(ox.history(limit=20, expiry='20260819')['total'], 2)

    def test_new_expiry_and_non_ready_rows_never_cross_compare_or_persist(self):
        ox._record_history(self._value('2026-08-14'))
        rollover = ox._record_history(self._value('2026-08-15', expiry='2026-08-22'))
        self.assertEqual(rollover['status'], 'new_expiry')
        self.assertFalse(rollover['sameExpiry'])
        stale = ox._record_history(self._value('2026-08-16', status='stale'))
        self.assertEqual(stale['status'], 'unavailable')
        self.assertEqual(ox.history(limit=20)['total'], 2)

    def test_corrupt_history_is_not_silently_overwritten(self):
        with open(ox.HISTORY_PATH, 'w', encoding='utf-8') as fh:
            fh.write('{broken')
        result = ox._record_history(self._value('2026-08-14'))
        self.assertEqual(result['persistence'], 'corrupt_source')
        self.assertFalse(result['historyPersisted'])
        with open(ox.HISTORY_PATH, 'r', encoding='utf-8') as fh:
            self.assertEqual(fh.read(), '{broken')
        with self.assertRaises(ox.OptionsHistoryCorruptError):
            ox.history(limit=10)


if __name__ == '__main__':
    unittest.main()

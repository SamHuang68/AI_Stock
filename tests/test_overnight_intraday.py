# -*- coding: utf-8 -*-
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import overnight_intraday as oi  # noqa: E402


def yahoo_payload(symbol='MU', count=180, factor_change=False, missing_open=None,
                  market_state='CLOSED', end=None, timezone_name='America/New_York'):
    end = end or datetime.now(timezone.utc) - timedelta(days=1)
    dates = [end - timedelta(days=count - 1 - index) for index in range(count)]
    timestamps, opens, closes, adjcloses, volumes = [], [], [], [], []
    adjusted_previous = 100.0
    for index, day in enumerate(dates):
        gap = 0.003 if index % 3 == 0 else -0.001
        intraday = 0.002 if index % 4 else -0.0015
        adjusted_open = adjusted_previous * math.exp(gap)
        adjusted_close = adjusted_open * math.exp(intraday)
        factor = 0.5 if factor_change and index < count // 2 else 1.0
        timestamps.append(int(day.timestamp()))
        opens.append(None if index == missing_open else adjusted_open / factor)
        closes.append(adjusted_close / factor)
        adjcloses.append(adjusted_close)
        volumes.append(1000 + index)
        adjusted_previous = adjusted_close
    return {
        'chart': {'error': None, 'result': [{
            'meta': {'symbol': symbol, 'exchangeTimezoneName': timezone_name, 'marketState': market_state},
            'timestamp': timestamps,
            'indicators': {
                'quote': [{'open': opens, 'close': closes, 'volume': volumes}],
                'adjclose': [{'adjclose': adjcloses}],
            },
        }]},
    }


class OvernightIntradayTest(unittest.TestCase):
    def setUp(self):
        with oi._CACHE_LOCK:
            oi._CACHE.clear()

    def test_close_to_close_equals_overnight_plus_intraday(self):
        normalized = oi.normalize_yahoo_chart(yahoo_payload(), 'MU')
        rows = oi.derive_session_returns(normalized['rows'])
        self.assertGreaterEqual(len(rows), oi.MIN_RETURNS)
        self.assertLessEqual(max(row['identityError'] for row in rows), oi.IDENTITY_TOLERANCE)
        for row in rows:
            self.assertAlmostEqual(row['closeToClose'], row['overnight'] + row['intraday'], places=12)

    def test_split_adjustment_does_not_create_fake_gap(self):
        normalized = oi.normalize_yahoo_chart(yahoo_payload(factor_change=True), 'MU')
        rows = oi.derive_session_returns(normalized['rows'])
        self.assertTrue(normalized['corporateActionAdjusted'])
        self.assertLess(max(abs(row['overnight']) for row in rows), 0.02)

    def test_missing_open_is_rejected_not_imputed(self):
        normalized = oi.normalize_yahoo_chart(yahoo_payload(missing_open=90), 'MU')
        self.assertTrue(any(row['reason'] == 'missing_or_nonpositive_adjusted_ohlc' for row in normalized['rejected']))
        self.assertEqual(len(normalized['rows']), 179)

    def test_mismatched_arrays_fail_closed(self):
        payload = yahoo_payload()
        payload['chart']['result'][0]['indicators']['quote'][0]['open'].pop()
        with self.assertRaisesRegex(ValueError, 'mismatched'):
            oi.normalize_yahoo_chart(payload, 'MU')

    def test_partial_latest_exchange_session_is_excluded(self):
        payload = yahoo_payload(market_state='REGULAR', end=datetime.now(timezone.utc))
        normalized = oi.normalize_yahoo_chart(payload, 'MU')
        self.assertEqual(len(normalized['rows']), 179)
        self.assertEqual(normalized['rejected'][-1]['reason'], 'unfinished_regular_session')

    def test_benchmark_alignment_is_inner_join_without_forward_fill(self):
        member = oi.derive_session_returns(oi.normalize_yahoo_chart(yahoo_payload(), 'MU')['rows'])
        benchmark = oi.derive_session_returns(oi.normalize_yahoo_chart(yahoo_payload(symbol='^SOX'), '^SOX')['rows'])
        removed_date = benchmark[50]['date']
        benchmark = [row for row in benchmark if row['date'] != removed_date]
        residual = oi.residualize(member, benchmark)
        self.assertNotIn(removed_date, {row['date'] for row in residual})
        self.assertEqual(len(residual), len(member) - 1)

    def test_gap_retention_ignores_near_zero_gaps(self):
        rows = [{'date': str(index), 'overnight': 0.0001, 'intraday': 0.001,
                 'closeToClose': 0.0011, 'identityError': 0.0} for index in range(100)]
        result = oi.analyze_returns(rows)
        self.assertIsNone(result['gapRetention']['value'])
        self.assertEqual(result['gapRetention']['sample'], 0)

    def test_build_snapshot_requires_three_of_four_members(self):
        failures = {'STX'}

        def fetcher(symbol):
            if symbol in failures:
                return {'chart': {'error': {'code': 'missing'}, 'result': None}}
            return yahoo_payload(symbol=symbol)

        ready = oi.build_snapshot(('US',), fetcher=fetcher)
        market = ready['markets'][0]
        self.assertTrue(ready['ok'])
        self.assertEqual(market['quality']['quorum'], {'required': 3, 'eligible': 3, 'total': 4})
        failures.add('WDC')
        insufficient = oi.build_snapshot(('US',), fetcher=fetcher)
        self.assertFalse(insufficient['ok'])
        self.assertEqual(insufficient['markets'][0]['status'], 'insufficient')

    def test_tw_basket_requires_four_of_five_members(self):
        failures = {'8299.TWO'}

        def fetcher(symbol):
            if symbol in failures:
                return {'chart': {'error': {'code': 'missing'}, 'result': None}}
            return yahoo_payload(symbol=symbol, timezone_name='Asia/Taipei')

        ready = oi.build_snapshot(('TW',), fetcher=fetcher)
        self.assertTrue(ready['ok'])
        self.assertEqual(
            ready['markets'][0]['quality']['quorum'],
            {'required': 4, 'eligible': 4, 'total': 5},
        )
        failures.add('3006.TW')
        insufficient = oi.build_snapshot(('TW',), fetcher=fetcher)
        self.assertFalse(insufficient['ok'])
        self.assertEqual(insufficient['markets'][0]['status'], 'insufficient')

    def test_contract_is_shadow_only_and_finite(self):
        snapshot = oi.build_snapshot(('US',), fetcher=lambda symbol: yahoo_payload(symbol=symbol))
        self.assertTrue(snapshot['shadowOnly'])
        self.assertEqual(snapshot['authority']['mutates'], [])
        self.assertIn('actionEnvelope', snapshot['authority']['prohibited'])
        self.assertNotIn('confidence', snapshot['markets'][0]['summary']['regime'])
        self.assertNotIn('NaN', str(snapshot))
        self.assertNotIn('Infinity', str(snapshot))
        self.assertEqual(snapshot['markets'][0]['universe']['members'], ['MU', 'SNDK', 'WDC', 'STX'])
        self.assertEqual(oi.UNIVERSES['TW']['members'][-1]['symbol'], '8299.TWO')
        self.assertNotIn('3260.TWO', [row['symbol'] for row in oi.UNIVERSES['TW']['members']])

    def test_get_is_cache_only_and_refresh_uses_fixed_universe(self):
        self.assertEqual(oi.latest_cached('US')['quality']['warnings'], ['NOT_REFRESHED'])
        called = []

        def fetcher(symbol):
            called.append(symbol)
            return yahoo_payload(symbol=symbol)

        refreshed = oi.get_snapshot('US', force=True, fetcher=fetcher)
        self.assertTrue(refreshed['ok'])
        self.assertEqual(set(called), {'^SOX', 'MU', 'SNDK', 'WDC', 'STX'})

    def test_failed_refresh_preserves_last_valid_cache_as_stale(self):
        valid = oi.build_snapshot(('US',), fetcher=lambda symbol: yahoo_payload(symbol=symbol))
        with oi._CACHE_LOCK:
            oi._CACHE['US'] = (0.0, valid)
        original_fetch = oi._fetch_yahoo_payload
        try:
            oi._fetch_yahoo_payload = lambda symbol: {
                'chart': {'error': {'code': 'provider_down'}, 'result': None}
            }
            stale = oi.get_snapshot('US', force=True)
        finally:
            oi._fetch_yahoo_payload = original_fetch
        self.assertTrue(stale['ok'])
        self.assertEqual(stale['quality']['status'], 'stale')
        self.assertEqual(stale['quality']['warnings'], ['REFRESH_FAILED_LAST_VALID_PRESERVED'])
        self.assertTrue(stale['cache']['stale'])
        with oi._CACHE_LOCK:
            self.assertIs(oi._CACHE['US'][1], valid)


if __name__ == '__main__':
    unittest.main()

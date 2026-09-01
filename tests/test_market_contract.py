# -*- coding: utf-8 -*-
"""Regression tests for the additive market quote contract."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
from market_contract import attach_quote_contract, cumulative_volume_contract  # noqa: E402
from market_routes import market_snapshot, twse_mis_observation  # noqa: E402


class TestMarketContract(unittest.TestCase):
    def test_twse_mis_observation_preserves_exchange_time(self):
        observed = twse_mis_observation({
            'd': '20260826', 't': '13:30:00', 'tlong': '1787722200000',
        })
        self.assertEqual(observed['asOf'], '2026-08-26T13:30:00+08:00')
        self.assertEqual(observed['tradeDate'], '2026-08-26')

        fallback = twse_mis_observation({'d': '20260826', 't': '09:05:07'})
        self.assertEqual(fallback['asOf'], '2026-08-26T09:05:07+08:00')
        self.assertEqual(fallback['tradeDate'], '2026-08-26')

    def test_twse_mis_observation_does_not_fabricate_fetch_time(self):
        self.assertEqual(twse_mis_observation({}), {})
        self.assertEqual(twse_mis_observation({'d': 'bad', 't': 'bad'}), {})

    def test_twse_lots_normalize_to_canonical_shares(self):
        volume = cumulative_volume_contract(
            '151,164', source_unit='lot', source='twse-mis',
            timestamp_ms='1786932654000')
        self.assertEqual(volume['volume'], 151164)
        self.assertEqual(volume['volumeShares'], 151164000)
        self.assertEqual(volume['volumeUnit'], 'lot')
        self.assertEqual(volume['volumeKind'], 'session_cumulative')
        self.assertTrue(volume['volumeRealtime'])

    def test_yahoo_shares_keep_odd_lots_without_1000x_error(self):
        volume = cumulative_volume_contract(
            147122573, source_unit='share', source='yahoo-v8-chart')
        self.assertEqual(volume['volume'], 147122.573)
        self.assertEqual(volume['volumeShares'], 147122573)
        self.assertEqual(volume['volume'] * volume['volumeLotSize'],
                         volume['volumeShares'])
        self.assertFalse(volume['volumeRealtime'])

    def test_invalid_volume_stays_missing_but_zero_is_observed(self):
        for value in (None, '', '-', 'NaN', 'inf', -1, 'bad'):
            with self.subTest(value=value):
                volume = cumulative_volume_contract(
                    value, source_unit='share', source='yahoo-v8-chart')
                self.assertIsNone(volume['volume'])
                self.assertIsNone(volume['volumeShares'])
        zero = cumulative_volume_contract(0, source_unit='lot', source='twse-mis')
        self.assertEqual(zero['volume'], 0)
        self.assertEqual(zero['volumeShares'], 0)

    def test_unknown_provider_unit_fails_closed(self):
        with self.assertRaises(ValueError):
            cumulative_volume_contract(100, source_unit='mystery', source='unknown')

    def test_live_change_is_not_recomputed_from_stale_series(self):
        q = attach_quote_contract(
            {'price': 44719, 'prevClose': 44990, 'changePct': -0.6024, 'source': 'taifex-mis'},
            symbol='__TXF__', market='TW', session='night')
        self.assertAlmostEqual(q['market']['displayChangePct'], -0.6024, places=4)
        self.assertEqual(q['market']['referenceType'], 'previous_close')
        self.assertEqual(q['market']['session'], 'night')
        self.assertEqual(q['displayChangePct'], q['market']['displayChangePct'])

    def test_snapshot_preserves_source_session_and_reference(self):
        snap = market_snapshot(
            {'t00': {'price': 22000, 'prevClose': 21900, 'changePct': 0.4566, 'source': 'twse-mis'}},
            {'price': 21950, 'prevClose': 22100, 'changePct': -0.6787, 'session': 'night', 'source': 'taifex-mis'})
        self.assertTrue(snap['ok'])
        self.assertEqual(snap['contractVersion'], 2)
        self.assertEqual(snap['quotes']['^TWII']['market']['source'], 'twse-mis')
        self.assertEqual(snap['quotes']['__TXF__']['market']['session'], 'night')
        self.assertAlmostEqual(snap['quotes']['__TXF__']['market']['displayChangePct'], -0.6787, places=4)

    def test_snapshot_separates_generation_and_market_time(self):
        generated = datetime(2026, 8, 16, 3, 0, tzinfo=timezone.utc)
        snap = market_snapshot(
            {'t00': {'price': 22000, 'prevClose': 21900,
                     'asOf': '2026-08-15T05:30:00+00:00', 'source': 'twse-mis'}},
            {'price': 22050, 'prevClose': 21950,
             'asOf': '2026-08-15T06:00:00+00:00', 'session': 'night',
             'source': 'taifex-mis'}, generated_at=generated)
        self.assertEqual(snap['generatedAt'], '2026-08-16T03:00:00Z')
        self.assertEqual(snap['marketAsOf'], '2026-08-15T06:00:00Z')
        self.assertEqual(snap['updatedAt'], snap['marketAsOf'])
        self.assertEqual(snap['sessionDate'], '2026-08-15')
        self.assertEqual(snap['session'], 'mixed')
        self.assertEqual(snap['sourceStatus']['taifex-mis']['freshness'], 'stale')

    def test_missing_market_time_is_not_fabricated(self):
        q = attach_quote_contract(
            {'price': 22000, 'prevClose': 21900},
            symbol='^TWII', market='TW')
        self.assertIsNone(q['asOf'])
        self.assertIsNone(q['market']['asOf'])
        snap = market_snapshot({'t00': q}, None)
        self.assertIsNone(snap['marketAsOf'])
        self.assertIsNone(snap['updatedAt'])
        self.assertEqual(snap['sourceStatus']['twse-mis']['freshness'], 'unknown')


if __name__ == '__main__':
    unittest.main()

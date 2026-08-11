# -*- coding: utf-8 -*-
"""Regression tests for the additive market quote contract."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
from market_contract import attach_quote_contract  # noqa: E402
from market_routes import market_snapshot  # noqa: E402


class TestMarketContract(unittest.TestCase):
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
        self.assertEqual(snap['contractVersion'], 1)
        self.assertEqual(snap['quotes']['^TWII']['market']['source'], 'twse-mis')
        self.assertEqual(snap['quotes']['__TXF__']['market']['session'], 'night')
        self.assertAlmostEqual(snap['quotes']['__TXF__']['market']['displayChangePct'], -0.6787, places=4)


if __name__ == '__main__':
    unittest.main()

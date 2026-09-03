#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""融資維持率公式與欄位對齊測試（無需網路的單元部分 + 可選 TWSE 整合）。"""
import os
import sys
import unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

import margin_ratio as mr  # noqa: E402


class TestMarginRatioUnit(unittest.TestCase):
    def test_etf_filter(self):
        self.assertTrue(mr._is_etf_code('0050'))
        self.assertTrue(mr._is_etf_code('006208'))
        self.assertFalse(mr._is_etf_code('2330'))
        self.assertFalse(mr._is_etf_code('2317'))
        self.assertFalse(mr._is_stock_code('0050'))
        self.assertTrue(mr._is_stock_code('2330'))

    def test_date_ts_roundtrip(self):
        from datetime import date
        d = date(2024, 6, 3)
        ts = mr._date_to_ts(d)
        self.assertEqual(mr._ts_to_date(ts), d)

    def test_fnum(self):
        self.assertEqual(mr._fnum('1,234.5'), 1234.5)
        self.assertIsNone(mr._fnum('--'))
        self.assertIsNone(mr._fnum(None))

    def test_risk_zones_ordered(self):
        levels = [z['level'] for z in mr.RISK_ZONES]
        self.assertEqual(levels, sorted(levels))
        self.assertIn(166.0, levels)

    def test_seed_csv_roundtrip(self):
        import tempfile
        from datetime import date
        rows = [
            (mr._date_to_ts(date(2024, 1, 2)), 180.123456),
            (mr._date_to_ts(date(2024, 1, 3)), 181.5),
        ]
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'm.csv')
            n = mr.save_seed_csv(rows, path)
            self.assertEqual(n, 2)
            loaded = mr.load_seed_csv(path)
            self.assertEqual(len(loaded), 2)
            self.assertAlmostEqual(loaded[0][1], 180.123456, places=5)

    def test_live_exchange_date_requires_matching_authoritative_dates(self):
        closes = [{'Date': '1150828', 'Code': '2330'}]
        self.assertEqual(
            mr._coherent_live_exchange_date(closes, {'date': '20260828'}),
            date(2026, 8, 28),
        )
        self.assertIsNone(mr._coherent_live_exchange_date(closes, {'date': '20260827'}))
        self.assertIsNone(mr._coherent_live_exchange_date(closes, {}))

    def test_refresh_today_uses_exchange_date_not_local_calendar_date(self):
        exchange_date = date(2026, 8, 28)
        fake_ds = mock.Mock()
        with mock.patch.object(mr, 'fetch_latest_ratio_live', return_value=(exchange_date, 186.236448)), \
                mock.patch.object(mr, '_import_datastore', return_value=fake_ds), \
                mock.patch.object(mr, '_store_points') as store, \
                mock.patch.object(mr, 'load_seed_csv', return_value=[]), \
                mock.patch.object(mr, 'save_seed_csv') as save:
            mr._last_today_refresh = 0
            self.assertAlmostEqual(mr.refresh_today(force=True), 186.236448)
        expected = mr._date_to_ts(exchange_date)
        store.assert_called_once_with(fake_ds, [(expected, 186.236448)])
        save.assert_called_once_with([(expected, 186.236448)], mr.SEED_CSV)


@unittest.skipUnless(os.environ.get('MARGIN_LIVE_TEST') == '1', 'set MARGIN_LIVE_TEST=1')
class TestMarginRatioLive(unittest.TestCase):
    def test_compute_known_day(self):
        from datetime import date
        r = mr.compute_ratio_for_date(date(2024, 6, 3))
        self.assertIsNotNone(r)
        # MacroMicro-aligned ex-ETF；允許合理區間
        self.assertGreater(r, 150)
        self.assertLess(r, 190)


if __name__ == '__main__':
    unittest.main()

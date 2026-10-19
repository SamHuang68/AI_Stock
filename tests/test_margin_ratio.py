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

    def _seed_env(self, td, content):
        path = os.path.join(td, 'seed.csv')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        fake_ds = mock.Mock()
        return path, fake_ds

    def test_rejected_seed_is_not_recrawled_or_overwritten(self):
        # 一列未來日期 → 整檔拒收。過去：ensure_seed_loaded 視為「0 筆」→ 每次呼叫都重爬 TWSE
        # 約 100 次，最後 save 因拒絕覆寫而拋錯，_seed_ensured 永遠不會設定。
        import tempfile
        bad = 'date,margin_ratio_pct\n2024-01-02,180.0\n2999-01-01,181.0\n'
        with tempfile.TemporaryDirectory() as td:
            path, fake_ds = self._seed_env(td, bad)
            with mock.patch.object(mr, 'SEED_CSV', path), \
                    mock.patch.object(mr, '_seed_ensured', False), \
                    mock.patch.object(mr, '_seed_ensured_n', 0), \
                    mock.patch.object(mr, '_rejected_seed_sig', None), \
                    mock.patch.object(mr, '_trading_days_from_yahoo') as cal, \
                    mock.patch.object(mr, 'compute_ratio_for_date') as crawl, \
                    mock.patch.object(mr, '_store_points') as store, \
                    mock.patch('builtins.print') as log:
                self.assertEqual(mr.ensure_seed_loaded(fake_ds), 0)
                self.assertEqual(mr.ensure_seed_loaded(fake_ds), 0)
            cal.assert_not_called()
            crawl.assert_not_called()
            store.assert_not_called()
            with open(path, encoding='utf-8') as f:
                self.assertEqual(f.read(), bad, 'rejected seed must stay untouched')
            warned = [c for c in log.call_args_list if '被拒收' in ' '.join(map(str, c.args))]
            self.assertEqual(len(warned), 1, 'warn once per file version, not per call')

    def test_header_only_seed_is_rebuilt_not_treated_as_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path, fake_ds = self._seed_env(td, 'date,margin_ratio_pct\n')
            days = [date(2024, 1, 2), date(2024, 1, 3)]
            with mock.patch.object(mr, 'SEED_CSV', path), \
                    mock.patch.object(mr, '_seed_ensured', False), \
                    mock.patch.object(mr, '_seed_ensured_n', 0), \
                    mock.patch.object(mr, '_trading_days_from_yahoo', return_value=days), \
                    mock.patch.object(mr, 'compute_ratio_for_date', return_value=180.0), \
                    mock.patch.object(mr, '_store_points', side_effect=lambda ds, pts: len(list(pts))):
                self.assertEqual(mr.ensure_seed_loaded(fake_ds), 2)
            self.assertEqual(len(mr.load_seed_csv(path)), 2)

    def test_save_still_refuses_to_replace_a_rejected_seed(self):
        import tempfile
        bad = 'date,margin_ratio_pct\n2024-01-03,181.0\n2024-01-02,180.0\n'   # 日期非遞增
        with tempfile.TemporaryDirectory() as td:
            path, _ = self._seed_env(td, bad)
            with self.assertRaises(ValueError):
                mr.save_seed_csv([(mr._date_to_ts(date(2024, 1, 4)), 182.0)], path)
            with open(path, encoding='utf-8') as f:
                self.assertEqual(f.read(), bad)

    def test_live_exchange_date_requires_matching_authoritative_dates(self):
        closes = [{'Date': '1150828', 'Code': '2330'}]
        self.assertEqual(
            mr._coherent_live_exchange_date(closes, {'date': '20260828'}),
            date(2026, 8, 28),
        )
        self.assertIsNone(mr._coherent_live_exchange_date(closes, {'date': '20260827'}))
        self.assertIsNone(mr._coherent_live_exchange_date(closes, {}))

    def _live(self, closing_codes):
        lots = {'2330': 900.0, '2317': 80.0, '1101': 20.0}
        margin = [{'股票代號': code, '融資今日餘額': str(lot)} for code, lot in lots.items()]
        closes = [{'Date': '1150828', 'Code': code, 'ClosingPrice': '100'} for code in closing_codes]
        summary = {'date': '20260828'}
        replies = {'MI_MARGN': margin, 'STOCK_DAY_ALL': closes, 'selectType=MS': summary}
        def http(url):
            return next(v for k, v in replies.items() if k in url and (k != 'MI_MARGN' or 'openapi' in url))
        with mock.patch.object(mr, '_http_json', side_effect=http),                 mock.patch.object(mr, '_parse_loan_from_tables', return_value=60_000_000.0),                 mock.patch('builtins.print'):
            return mr.fetch_latest_ratio_live()

    def test_live_ratio_rejects_incomplete_closing_prices(self):
        # 審查 CM-01：收盤價回應缺一大段時，分母仍是全市場融資，比率會被低估且無標示。
        exchange_date, ratio = self._live(['2330', '2317', '1101'])
        self.assertEqual(exchange_date, date(2026, 8, 28))
        self.assertAlmostEqual(ratio, 1000 * 1000 * 100 / 60_000_000 * 100)
        self.assertIsNotNone(self._live(['2330', '2317']))   # 缺 2% 張數：照常輸出
        self.assertIsNone(self._live(['2330']))              # 缺 10% 張數：拒絕

    def test_lot_coverage_counts_margin_lots_not_stock_count(self):
        collateral, used, coverage = mr._collateral_with_coverage({'A': 90.0, 'B': 10.0, 'C': 0.0}, {'A': 10.0})
        self.assertEqual((collateral, used), (900_000.0, 1))
        self.assertAlmostEqual(coverage, 0.9)

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

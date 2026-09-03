# -*- coding: utf-8 -*-
"""指數／期貨價格趨勢量化：vs前日／vs5／動能分／連漲跌。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import trend_quant as tq  # noqa: E402


class TestPriceSeriesQuant(unittest.TestCase):
    def test_uptrend_vs_ma5(self):
        closes = [100, 101, 102, 103, 108]
        q = tq.price_series_quant(closes)
        self.assertEqual(q['close'], 108.0)
        self.assertGreater(q['vsMa5Pct'], 0)
        self.assertGreaterEqual(q['momScore'], 50)
        self.assertTrue(q['streak'] > 0)
        self.assertIn(q['level'], ('偏強', '強勢', '中性'))
        self.assertTrue(len(q['spark']) >= 2)

    def test_downtrend(self):
        closes = [110, 108, 106, 104, 98]
        q = tq.price_series_quant(closes)
        self.assertLess(q['vsMa5Pct'], 0)
        self.assertLessEqual(q['momScore'], 50)
        self.assertTrue(q['streak'] < 0)
        self.assertTrue(
            ('下行' in (q['trend'] or '')) or ('趨降' in (q['trend'] or '')) or
            (q['level'] in ('偏弱', '弱勢'))
        )

    def test_latest_overlay(self):
        closes = [100, 101, 102]
        q = tq.price_series_quant(closes, latest=110)
        self.assertEqual(q['close'], 110.0)
        self.assertGreater(q['n'], 3)

    def test_quote_change_overrides_stale_daily_series(self):
        # 期貨夜盤／換月時，日線最後一筆可能與官方昨收基準不同；
        # 頂列漲跌必須與同卡即時報價一致，而不是拿日線快取反推方向。
        q = tq.price_series_quant(
            [43000, 43800, 44280], latest=44719, quote_change_pct=-0.6024)
        self.assertEqual(q['close'], 44719.0)
        self.assertAlmostEqual(q['chgPct'], -0.60, places=2)
        self.assertGreater(q['vsMa5Pct'], 0)  # 日線水位仍可獨立呈現

    def test_empty(self):
        q = tq.price_series_quant([])
        self.assertIsNone(q['close'])
        self.assertEqual(q['n'], 0)
        self.assertEqual(q['spark'], [])


class TestMomentumScore(unittest.TestCase):
    def test_neutral(self):
        self.assertAlmostEqual(tq.momentum_score(0.0, 0.0, 0.0), 50.0, delta=1.0)

    def test_hot_cold(self):
        self.assertGreater(tq.momentum_score(3.0, 1.5, 1.0), tq.momentum_score(0, 0, 0))
        self.assertLess(tq.momentum_score(-3.0, -1.5, -1.0), 50.0)


if __name__ == '__main__':
    unittest.main()

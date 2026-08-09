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

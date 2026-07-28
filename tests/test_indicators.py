# -*- coding: utf-8 -*-
"""鐵律：SMA / Wilder RSI 精算回歸（固定 fixture，禁止概略）。"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import indicators as ind  # noqa: E402


class TestSMA(unittest.TestCase):
    def test_sma_simple(self):
        vals = [1, 2, 3, 4, 5]
        self.assertEqual(ind.sma(vals, 3, 4), 4.0)  # (3+4+5)/3
        self.assertEqual(ind.sma(vals, 5, 4), 3.0)
        self.assertIsNone(ind.sma(vals, 3, 1))

    def test_sma_with_none(self):
        vals = [1.0, None, 3.0]
        self.assertIsNone(ind.sma(vals, 3, 2))


class TestRSIWilders(unittest.TestCase):
    def test_too_short(self):
        self.assertIsNone(ind.rsi_wilders(list(range(10)), 14))

    def test_monotonic_up_is_100(self):
        # 嚴格遞增 → 全 gains → RSI 100
        prices = [float(i) for i in range(1, 30)]
        self.assertEqual(ind.rsi_wilders(prices, 14), 100.0)

    def test_known_fixture(self):
        # 手工可驗：15 根收盤，前 14 變動建 seed，再 1 根更新
        # closes: 44.. 經典 TradingView 風格小樣本
        prices = [
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
            45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
            46.03, 46.41, 46.22, 45.64,
        ]
        rsi = ind.rsi_wilders(prices, 14)
        self.assertIsNotNone(rsi)
        # Wilder RSI 應落在合理區間；精確值鎖定防回歸
        self.assertAlmostEqual(rsi, 57.91502067008556, places=10)

    def test_series_last_matches_scalar(self):
        prices = [float(x) for x in range(50, 80)]
        series = ind.rsi_wilders_series(prices, 14)
        self.assertAlmostEqual(series[-1], ind.rsi_wilders(prices, 14), places=12)


if __name__ == '__main__':
    unittest.main()

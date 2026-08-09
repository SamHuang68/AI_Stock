# -*- coding: utf-8 -*-
"""成交金額量化：vs前日／vs5日均／量能分／趨勢標籤。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import turnover_quant as tq  # noqa: E402


class TestTurnoverQuant(unittest.TestCase):
    def test_shrink_vs_ma5(self):
        turns = [{'amount': x * 1e8} for x in (10000, 11000, 12000, 11500, 8500)]
        q = tq.turnover_quant(turns)
        self.assertEqual(q['yi'], 8500.0)
        self.assertLess(q['vsMa5Pct'], 0)
        self.assertIsNotNone(q['volumeScore'])
        self.assertIn('縮量', q['trend'])

    def test_expand_and_score(self):
        turns = [{'amount': x * 1e8} for x in (6000, 6500, 7000, 7500, 10000)]
        q = tq.turnover_quant(turns)
        self.assertGreater(q['vsMa5Pct'], 0)
        self.assertGreaterEqual(q['volumeScore'], 50)
        self.assertTrue(q['streak'] > 0)

    def test_latest_yi_override(self):
        turns = [{'amount': x * 1e8} for x in (8000, 8100, 8200)]
        q = tq.turnover_quant(turns, latest_yi=9000)
        self.assertEqual(q['yi'], 9000.0)
        self.assertGreater(q['n'], 3)

    def test_empty(self):
        q = tq.turnover_quant([])
        self.assertIsNone(q['yi'])
        self.assertEqual(q['n'], 0)


class TestVolumeScoreYi(unittest.TestCase):
    def test_neutral_hot(self):
        self.assertAlmostEqual(tq.volume_score_yi(8000), 50.0, delta=0.5)
        self.assertGreater(tq.volume_score_yi(12000), tq.volume_score_yi(8000))
        self.assertLess(tq.volume_score_yi(4000), 50.0)


if __name__ == '__main__':
    unittest.main()

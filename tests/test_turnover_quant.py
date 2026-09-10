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

    def test_intraday_cumulative_same_date_replaces(self):
        # 盤中累積 300 億 vs 昨收 4000 億遠超 3%，舊啟發式會幽靈 append。
        turns = [
            {'date': '2026-09-09', 'amount': 4000 * 1e8},
            {'date': '2026-09-10', 'amount': 200 * 1e8},
        ]
        q = tq.turnover_quant(turns, latest_yi=300, latest_date='2026-09-10')
        self.assertEqual(q['yi'], 300.0)
        self.assertEqual(q['n'], 2)

    def test_new_session_appends_once(self):
        turns = [
            {'date': '115/09/09', 'amount': 4000 * 1e8},
        ]
        q = tq.turnover_quant(turns, latest_yi=300, latest_date='2026-09-10')
        self.assertEqual(q['n'], 2)
        q2 = tq.turnover_quant(turns + [
            {'date': '2026-09-10', 'amount': 300 * 1e8},
        ], latest_yi=800, latest_date='2026-09-10')
        self.assertEqual(q2['n'], 2)
        self.assertEqual(q2['yi'], 800.0)

    def test_latest_without_date_does_not_invent_a_day(self):
        turns = [{'amount': x * 1e8} for x in (8000, 8100, 8200)]
        q = tq.turnover_quant(turns, latest_yi=9000)
        self.assertEqual(q['yi'], 9000.0)
        self.assertEqual(q['n'], 3)

    def test_empty(self):
        q = tq.turnover_quant([])
        self.assertIsNone(q['yi'])
        self.assertEqual(q['n'], 0)


class TestVolumeScoreYi(unittest.TestCase):
    def test_neutral_hot(self):
        self.assertAlmostEqual(tq.volume_score_yi(8000), 50.0, delta=0.5)
        self.assertGreater(tq.volume_score_yi(12000), tq.volume_score_yi(8000))
        self.assertLess(tq.volume_score_yi(4000), 50.0)

    def test_relative_label_from_z20(self):
        self.assertEqual(tq.volume_relative_label(1.4), '相對偏熱')
        self.assertEqual(tq.volume_relative_label(-1.2), '相對偏冷')
        self.assertEqual(tq.volume_relative_label(0.2), '相對中性')
        self.assertGreater(tq.volume_relative_score(2.0), 50)


if __name__ == '__main__':
    unittest.main()

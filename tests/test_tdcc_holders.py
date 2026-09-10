# -*- coding: utf-8 -*-
"""TDCC holders: HHI / entropy from published 1–16 buckets, not total row 17."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import tdcc_holders as th  # noqa: E402


_CSV = (
    '資料日期,證券代號,證券名稱,持股分級,人數,股數,占集保庫存數比例\n'
    '20260905,2330,台積電,1,100,1000,10\n'
    '20260905,2330,台積電,2,50,2000,20\n'
    '20260905,2330,台積電,12,10,3000,30\n'
    '20260905,2330,台積電,15,2,4000,40\n'
    '20260905,2330,台積電,17,162,10000,100\n'
)


class TestTdccHhi(unittest.TestCase):
    def test_hhi_excludes_total_level_and_does_not_enter_score(self):
        rows = th._parse_csv_bytes(_CSV.encode('utf-8'))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['date'], '2026-09-05')
        self.assertEqual(row['code'], '2330')
        self.assertEqual(row['holders'], 162)
        self.assertAlmostEqual(row['major_pct'], 70.0, places=2)
        self.assertAlmostEqual(row['mega_pct'], 40.0, places=2)
        # 0.1^2+0.2^2+0.3^2+0.4^2 = 0.30 → HHI 3000
        self.assertAlmostEqual(row['hhi'], 3000.0, places=1)
        self.assertGreater(row['entropy'], 1.0)
        scored = th.score_concentration([row])
        self.assertIsNotNone(scored['score'])
        self.assertEqual(scored['detail']['hhi'], 3000.0)
        labels = [r['k'] for r in scored['marketRows']]
        self.assertIn('HHI', labels)
        self.assertIn('籌碼熵', labels)
        hhi_row = next(r for r in scored['marketRows'] if r['k'] == 'HHI')
        self.assertIsNone(hhi_row['score'])
        mutated = dict(row)
        mutated['hhi'] = 9000
        self.assertEqual(th.score_concentration([row])['score'],
                         th.score_concentration([mutated])['score'])

    def test_uniform_buckets_have_lower_hhi_than_concentrated(self):
        concentrated = {1: 90.0, 2: 10.0}
        spread = {i: 100.0 / 15.0 for i in range(1, 16)}
        hhi_c, ent_c = th._hhi_entropy(concentrated)
        hhi_s, ent_s = th._hhi_entropy(spread)
        self.assertGreater(hhi_c, hhi_s)
        self.assertLess(ent_c, ent_s)
        self.assertIsNone(th._hhi_entropy({17: 100.0})[0])
        only_valid = th._hhi_entropy({1: 50.0, 18: 50.0})
        self.assertAlmostEqual(only_valid[0], 10000.0, places=1)


if __name__ == '__main__':
    unittest.main()

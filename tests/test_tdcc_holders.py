# -*- coding: utf-8 -*-
"""TDCC holders: HHI / entropy from published 1–16 buckets, not total row 17."""
import os
import sys
import unittest
import tempfile
from unittest.mock import patch

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
_CSV += ''.join(f'20260905,2330,台積電,{level},0,0,0\n' for level in range(1, 16)
                if level not in (1, 2, 12, 15))


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
        self.assertIn('級距 HHI', labels)
        self.assertIn('級距分布熵', labels)
        hhi_row = next(r for r in scored['marketRows'] if r['k'] == '級距 HHI')
        self.assertIsNone(hhi_row['score'])
        mutated = dict(row)
        mutated['hhi'] = 9000
        self.assertEqual(th.score_concentration([row])['score'],
                         th.score_concentration([mutated])['score'])

    def test_uniform_buckets_have_lower_hhi_than_concentrated(self):
        concentrated = {**dict.fromkeys(range(1, 16), 0), 1: 90.0, 2: 10.0}
        spread = {i: 100.0 / 15.0 for i in range(1, 16)}
        hhi_c, ent_c = th._hhi_entropy(concentrated)
        hhi_s, ent_s = th._hhi_entropy(spread)
        self.assertGreater(hhi_c, hhi_s)
        self.assertLess(ent_c, ent_s)
        self.assertIsNone(th._hhi_entropy({17: 100.0})[0])
        only_valid = th._hhi_entropy({1: 50.0, 18: 50.0})
        self.assertIsNone(only_valid[0])

    def test_invalid_or_duplicate_buckets_do_not_publish_extreme_concentration(self):
        self.assertIsNone(th._hhi_entropy({1: 50})[0])
        valid = dict.fromkeys(range(1, 16), 100 / 15)
        for invalid in (float('nan'), float('inf'), -1):
            self.assertIsNone(th._hhi_entropy({**valid, 1: invalid})[0])
        row = th._parse_csv_bytes((_CSV + '20260905,2330,台積電,1,100,1000,10\n').encode())[0]
        self.assertIsNone(row['hhi'])

    def test_legacy_unvalidated_values_are_hidden_without_deleting_history(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(th, 'DATA', folder), \
                patch.object(th, 'DB_PATH', os.path.join(folder, 'holders.db')):
            row = th._parse_csv_bytes(_CSV.encode())[0]
            old = {**row, 'date': '2026-08-29', 'distribution_version': None}
            th.upsert_rows([old, row])
            loaded = th.load_stock_series('2330')
            self.assertEqual(len(loaded), 2)
            self.assertIsNone(loaded[0]['hhi'])
            self.assertEqual(loaded[1]['hhi'], 3000)
            self.assertEqual(loaded[0]['major_pct'], 70)


if __name__ == '__main__':
    unittest.main()

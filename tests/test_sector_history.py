# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import sector_history  # noqa: E402


class SectorHistoryTest(unittest.TestCase):
    def test_persistent_21_session_return_and_benchmark(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'sector.db')
            for i in range(21):
                sector_history.store_snapshot(
                    f'202601{i + 1:02d}',
                    [{'name': '電子零組件類指數', 'close': 100 + i},
                     {'name': '電腦及週邊設備類指數', 'close': 200 + i * 2},
                     {'name': '發行量加權股價指數', 'close': 1000 + i * 10}],
                    path,
                )
            returns = sector_history.return20_by_sector(path)
            self.assertAlmostEqual(returns['電子零組件'], 20.0, places=4)
            self.assertAlmostEqual(returns['電腦及週邊設備'], 20.0, places=4)
            bars = [{'close': 100 + i * 0.5} for i in range(21)]
            self.assertAlmostEqual(sector_history.benchmark_return20(bars), 10.0, places=4)

    def test_enrichment_uses_cache_without_network_bootstrap(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'sector.db')
            for i in range(21):
                sector_history.store_snapshot(
                    f'202602{i + 1:02d}',
                    [{'name': '半導體類指數', 'close': 100 + i},
                     {'name': '發行量加權股價指數', 'close': 1000 + i * 10}], path)
            rows, status = sector_history.enrich_sector_rows(
                [{'name': '半導體類指數', 'close': 120, 'changePct': 1.2}],
                as_of='20260221', benchmark_bars=None,
                industry_turnover_yi={'半導體業': 500}, path=path, bootstrap=False)
            self.assertEqual(rows[0]['turnoverYi'], 500)
            self.assertEqual(rows[0]['return20Pct'], 20.0)
            self.assertTrue(status['rs20Available'])
            self.assertEqual(status['benchmarkReturn20Pct'], 20.0)
            self.assertIn('MI_INDEX', status['benchmarkSource'])


if __name__ == '__main__':
    unittest.main()

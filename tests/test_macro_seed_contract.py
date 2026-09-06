#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""總經種子 CSV 的格式、來源與市場時間契約。"""
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

import macro_track as mt  # noqa: E402


class TestMacroSeedContract(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original = mt.SEED_DIR
        mt.SEED_DIR = self._tmpdir.name

    def tearDown(self):
        mt.SEED_DIR = self._original
        self._tmpdir.cleanup()

    def test_atomic_roundtrip_and_precise_source(self):
        points = [
            {'date': '2026-08-28', 'value': 3.63},
            {'date': '2026-08-31', 'value': 3.63},
        ]
        mt._save_seed_csv('fedfunds.csv', points)
        self.assertEqual(mt._load_seed_csv('fedfunds.csv'), points)
        self.assertFalse(any(name.endswith('.tmp') for name in os.listdir(self._tmpdir.name)))
        resolved, source = mt._resolve_series_points(
            {'seed': 'fedfunds.csv', 'seedSource': 'NY Fed EFFR',
             'canonical': 'nyfed_effr', 'source': 'fred'},
            years=5,
            force_live=False,
        )
        self.assertEqual(resolved, points)
        self.assertEqual(source, 'seed:fedfunds.csv · NY Fed EFFR')

    def test_rejects_partial_malformed_future_and_unsorted_files(self):
        path = os.path.join(self._tmpdir.name, 'bad.csv')
        cases = (
            'date,value\n2026-08-28,3.63\n壞日期,3.64\n',
            'date,value\n2999-01-01,3.63\n',
            'date,value\n2026-08-31,3.63\n2026-08-28,3.64\n',
            'wrong,value\n2026-08-28,3.63\n',
        )
        for content in cases:
            with self.subTest(content=content.splitlines()[0]):
                with open(path, 'w', encoding='utf-8', newline='') as f:
                    f.write(content)
                self.assertEqual(mt._load_seed_csv('bad.csv'), [])

    def test_save_rejects_future_seed_points(self):
        with self.assertRaises(ValueError):
            mt._save_seed_csv('future.csv', [{'date': '2999-01-01', 'value': 1.0}])
        self.assertFalse(os.path.exists(os.path.join(self._tmpdir.name, 'future.csv')))

    def test_freshness_uses_cadence_and_taipei_date(self):
        daily = mt.series_freshness(
            '2026-08-28', {'cadence': 'daily', 'maxBusinessDays': 2},
            today=date(2026, 9, 2),
        )
        monthly = mt.series_freshness(
            '2026-07-01', {'cadence': 'monthly', 'maxCalendarDays': 75},
            today=date(2026, 9, 2),
        )
        self.assertEqual(daily['freshness'], 'stale')
        self.assertEqual(daily['age'], 3)
        self.assertEqual(monthly['freshness'], 'fresh')

    def test_canonical_provider_does_not_fall_back_to_incompatible_fred(self):
        spec = {
            'seed': 'baml_hy.csv', 'seedSource': 'Yahoo HYG adj',
            'source': 'fred', 'fred': 'BAMLHY0A0HYMTRIV',
            'fallback': 'yahoo_adj', 'canonical': 'yahoo_adj', 'symbol': 'HYG',
        }
        with mock.patch.object(mt, '_yahoo_closes', return_value=[]) as yahoo, \
                mock.patch.object(mt, '_fred_points') as fred:
            points, source = mt._resolve_series_points(spec, years=5, force_live=True)
        yahoo.assert_called_once_with('HYG', years=5, adj=True)
        fred.assert_not_called()
        self.assertEqual(points, [])
        self.assertEqual(source, 'canonical:yahoo_adj · 指定來源無資料')


if __name__ == '__main__':
    unittest.main()

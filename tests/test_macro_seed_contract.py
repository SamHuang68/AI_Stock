#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""總經種子 CSV 的格式、來源與市場時間契約。"""
import os
import json
import hashlib
import threading
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
        mt._save_seed_source({'seed': 'fedfunds.csv', 'canonical': 'nyfed_effr'})
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
            'date,value\n2026-08-28,NaN\n',
            'date,value\n2026-08-28,inf\n',
            'date,value\n2026-08-28,1,extra\n',
            'date,value\n2026-08-28junk,1\n',
            'date,value\n2026-8-28,1\n',
            'date,value\n2026-08-28,1\n2026-08-28,2\n',
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

    def test_legacy_history_is_replaced_then_verified_history_is_merged(self):
        spec = {'seed': 'hyg.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG',
                'seedSource': 'Yahoo HYG adj', 'source': 'fred', 'fred': 'BAML'}
        old = [{'date': '2020-01-01', 'value': 3000}]
        first = [{'date': '2026-08-28', 'value': 80}]
        next_points = [{'date': '2026-08-31', 'value': 81}]
        mt._save_seed_csv('hyg.csv', old)
        self.assertIn('unverified', mt._resolve_series_points(spec, 5)[1])
        with mock.patch.object(mt, '_yahoo_closes', return_value=first), \
                mock.patch.object(mt, '_fred_points') as fred:
            self.assertEqual(mt._resolve_series_points(spec, 5, True)[0], first)
        fred.assert_not_called()
        self.assertTrue(mt._seed_verified(spec))
        backups = [name for name in os.listdir(self._tmpdir.name) if name.endswith('.bak')]
        self.assertEqual(len(backups), 1)
        with open(os.path.join(self._tmpdir.name, backups[0]), encoding='utf-8') as f:
            self.assertIn('2020-01-01,3000', f.read())
        with mock.patch.object(mt, '_yahoo_closes', return_value=first + next_points):
            self.assertEqual(mt._resolve_series_points(spec, 5, True)[0], first + next_points)
        mt._save_seed_csv('hyg.csv', old)
        self.assertFalse(mt._seed_verified(spec))
        with mock.patch.object(mt, '_yahoo_closes', return_value=next_points):
            self.assertEqual(mt._resolve_series_points(spec, 5, True)[0], next_points)

    def test_invalid_live_does_not_overwrite_valid_seed(self):
        spec = {'seed': 'hyg.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        old = [{'date': '2026-08-28', 'value': 80}]
        mt._save_seed_csv('hyg.csv', old)
        for point in ({'date': '2999-01-01', 'value': 1},
                      {'date': '2026-08-31', 'value': float('nan')},
                      {'date': '2026-08-31junk', 'value': 1}):
            with self.subTest(point=point), mock.patch.object(mt, '_yahoo_closes', return_value=[point]):
                self.assertEqual(mt._resolve_series_points(spec, 5, True)[0], old)
                self.assertEqual(mt._load_seed_csv('hyg.csv'), old)

    def test_unknown_canonical_never_uses_legacy_fallback(self):
        with mock.patch.object(mt, '_fred_points') as fred, \
                mock.patch.object(mt, '_yahoo_closes') as yahoo:
            self.assertEqual(mt._resolve_series_points(
                {'canonical': 'typo', 'source': 'fred', 'fred': 'DGS2',
                 'fallback': 'yahoo', 'symbol': '^IRX'}, 5, True)[0], [])
        fred.assert_not_called()
        yahoo.assert_not_called()

    def test_failed_replace_preserves_original_file(self):
        points = [{'date': '2026-08-28', 'value': 80}]
        mt._save_seed_csv('hyg.csv', points)
        with mock.patch.object(mt.os, 'replace', side_effect=OSError('blocked')):
            with self.assertRaises(OSError):
                mt._save_seed_csv('hyg.csv', [{'date': '2026-08-31', 'value': 81}])
        self.assertEqual(mt._load_seed_csv('hyg.csv'), points)
        self.assertFalse(any(name.endswith('.tmp') for name in os.listdir(self._tmpdir.name)))

    def test_failed_backup_is_not_published_and_retry_repairs_partial_backup(self):
        spec = {'seed': 'hyg.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        old = [{'date': '2020-01-01', 'value': 3000}]
        live = [{'date': '2026-08-28', 'value': 80}]
        mt._save_seed_csv(spec['seed'], old)
        with mock.patch.object(mt, '_yahoo_closes', return_value=live), \
                mock.patch.object(mt.os, 'fsync', side_effect=OSError('disk failure')):
            mt._resolve_series_points(spec, 5, True)
        self.assertEqual(mt._load_seed_csv(spec['seed']), old)
        self.assertFalse(any(name.endswith('.bak') or name.endswith('.tmp')
                             for name in os.listdir(self._tmpdir.name)))
        with open(mt._seed_path(spec['seed']), 'rb') as f:
            original = f.read()
        backup = mt._seed_path(spec['seed']) + '.unverified.' + hashlib.sha256(original).hexdigest() + '.bak'
        with open(backup, 'wb') as f:
            f.write(b'partial')
        with mock.patch.object(mt, '_yahoo_closes', return_value=live):
            mt._resolve_series_points(spec, 5, True)
        with open(backup, 'rb') as f:
            self.assertEqual(f.read(), original)

    def test_provenance_is_checked_against_the_same_csv_snapshot(self):
        spec = {'seed': 'hyg.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        old = [{'date': '2026-08-28', 'value': 3000}]
        new = [{'date': '2026-08-31', 'value': 80}]
        mt._save_seed_csv(spec['seed'], old)
        load = mt._load_seed_csv
        def concurrent_update(name, content=None):
            points = load(name, content)
            mt._save_seed_csv(name, new)
            mt._save_seed_source(spec)
            return points
        with mock.patch.object(mt, '_load_seed_csv', side_effect=concurrent_update):
            points, verified = mt._seed_snapshot(spec)
        self.assertEqual(points, old)
        self.assertFalse(verified)

    def test_slow_refresh_does_not_block_other_cached_seed(self):
        spec = {'seed': 'slow.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        fast = {'seed': 'fast.csv', 'canonical': 'nyfed_effr'}
        points = [{'date': '2026-08-28', 'value': 80}]
        mt._save_seed_csv(fast['seed'], points)
        started = threading.Event()
        release = threading.Event()
        done = threading.Event()
        def slow(*args, **kwargs):
            started.set()
            release.wait(3)
            return points
        with mock.patch.object(mt, '_yahoo_closes', side_effect=slow):
            thread = threading.Thread(target=mt._resolve_series_points, args=(spec, 5, True))
            thread.start()
            self.assertTrue(started.wait(2))
            reader = threading.Thread(target=lambda: (mt._resolve_series_points(fast, 5), done.set()))
            reader.start()
            try:
                self.assertTrue(done.wait(1))
            finally:
                release.set()
                thread.join(3)
                reader.join(3)

    def test_yahoo_adjusted_provider_requires_adjusted_close(self):
        payload = {'chart': {'result': [{'timestamp': [1787875200],
            'indicators': {'quote': [{'close': [3000]}]}}]}}
        with mock.patch.object(mt, '_http_json', return_value=payload):
            self.assertEqual(mt._yahoo_closes('HYG', 5, adj=True), [])
            self.assertEqual(mt._yahoo_closes('HYG', 5, adj=False)[0]['value'], 3000)

    def test_partial_adjusted_refresh_preserves_one_adjustment_basis(self):
        spec = {'seed': 'hyg.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        old = [{'date': '2007-01-03', 'value': 40}, {'date': '2026-08-28', 'value': 80}]
        mt._save_seed_csv(spec['seed'], old)
        mt._save_seed_source(spec)
        with mock.patch.object(mt, '_yahoo_closes', return_value=[{'date': '2026-08-28', 'value': 78}]) as fetch:
            points, note = mt._resolve_series_points(spec, 5, True)
        self.assertEqual(points, old)
        self.assertTrue(note.startswith('refresh-incomplete'))
        self.assertGreater(fetch.call_args.kwargs['years'], 5)
        self.assertEqual(mt._load_seed_csv(spec['seed']), old)
        full = [{'date': '2007-01-03', 'value': 39}, {'date': '2026-08-28', 'value': 78}]
        with mock.patch.object(mt, '_yahoo_closes', return_value=full):
            self.assertEqual(mt._resolve_series_points(spec, 5, True)[0], full)

    def test_commit_failures_are_explicit_refresh_errors(self):
        live = [{'date': '2026-08-28', 'value': 80}]
        spec = {'seed': 'hyg.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        for stage in ('_backup_seed', '_save_seed_csv', '_save_seed_source'):
            with self.subTest(stage=stage), mock.patch.object(mt, '_yahoo_closes', return_value=live), \
                    mock.patch.object(mt, stage, side_effect=OSError('disk failure')):
                _, note = mt._resolve_series_points(spec, 5, True)
                self.assertTrue(note.startswith('refresh-save-failed'))
        with mock.patch.object(mt, '_nyfed_effr', return_value=live), \
                mock.patch.object(mt, '_yahoo_closes', return_value=live), \
                mock.patch.object(mt, '_save_seed_csv', side_effect=OSError('disk failure')):
            result = mt.refresh_chart('__US_RATES_CREDIT__')
        self.assertFalse(result['ok'])
        self.assertTrue(result['refreshErrors'])


if __name__ == '__main__':
    unittest.main()

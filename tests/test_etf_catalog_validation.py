"""Catalog recovery through the real tracker; only the provider returns fixtures."""
from contextlib import redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import test_runtime_workers as runtime_fixture


class EtfCatalogValidationTests(unittest.TestCase):
    def setUp(self):
        self.runtime = runtime_fixture.RuntimeWorkerTests('test_etf_catalog_changes_apply_to_the_next_run_in_the_same_process')
        self.addCleanup(self.runtime.doCleanups)
        self.runtime.setUp()
        self.tracker = self.runtime.tracker
        self.catalog = Path(self.tracker.CATALOG_FILE)

    def write(self, value):
        self.catalog.write_text(json.dumps(value), encoding='utf-8')

    @staticmethod
    def pool(prefix='00'):
        return {'categories': [{'etfs': [
            {'code': f'{prefix}{i:03d}', 'name': 'fixture', 'enabled': True, 'market': 'TW'}
            for i in range(10)]}]}

    def test_invalid_catalog_preserves_last_good_snapshot_and_recovers(self):
        day = dt.date(2026, 9, 29)
        seen = []
        def provider(code, target):
            seen.append(code)
            return [{'rank': 1, 'code': '2330', 'name': 'fixture', 'weight': 20, 'shares': 1000}], day.isoformat(), 'fixture'
        invalid = [
            {'categories': [{'etfs': [{'code': 123, 'enabled': True}]}]},
            [], None, {}, {'categories': {}}, {'categories': [None]},
            {'categories': [{'etfs': None}]}, {'categories': [{'etfs': [123]}]},
            {'categories': [{'etfs': [{'code': '00000', 'enabled': 'false'}]}]},
            {'categories': [{'etfs': [{'code': '00000', 'enabled': True, 'name': {'private': 'DO_NOT_LOG_THIS'}}]}]},
            {'categories': [{'etfs': [{'code': '00000', 'enabled': True, 'market': ['DO_NOT_LOG_THIS']}]}]},
            {'categories': [{'etfs': [{'code': None, 'enabled': True}]}]},
            {'categories': [{'etfs': [{'code': '   ', 'enabled': True}]}]},
        ]
        self.write(self.pool())
        with mock.patch.object(self.tracker, 'fetch_one', side_effect=provider):
            self.assertTrue(self.tracker.run(day, run_id=uuid.uuid4().hex))
            snapshot = self.runtime.history / f'top10_active_etf_holdings_{day.isoformat()}.json'
            original = snapshot.read_bytes()
            original_codes = sorted(json.loads(original)['meta']['expectedCodes'])
            for index, payload in enumerate(invalid):
                with self.subTest(invalid_schema=index):
                    self.write(payload)
                    log = io.StringIO()
                    with redirect_stdout(log):
                        self.assertTrue(self.tracker.run(day, run_id=uuid.uuid4().hex))
                    self.assertEqual(snapshot.read_bytes(), original)
                    self.assertEqual(sorted(self.tracker.ETFS), original_codes)
                    self.assertEqual(len(seen), 10, 'valid existing snapshot must not refetch on invalid catalog')
                    self.assertIn('[ERR]', log.getvalue())
                    self.assertNotIn('DO_NOT_LOG_THIS', log.getvalue())
                    self.assertNotIn(str(self.catalog), log.getvalue())
            self.write(self.pool('01'))
            self.assertTrue(self.tracker.run(day, run_id=uuid.uuid4().hex))
            recovered = json.loads(snapshot.read_bytes())
            self.assertEqual(recovered['meta']['expectedCodes'], [f'01{i:03d}' for i in range(10)])
            self.assertEqual(set(seen[10:]), {f'01{i:03d}' for i in range(10)})

    def test_optional_fields_and_zero_enabled_fallback_are_unchanged(self):
        self.write({'categories': [{'etfs': [{'code': ' 0050 ', 'enabled': True}]}]})
        self.assertEqual(self.tracker.load_catalog(), {'0050': ('0050', '0050')})
        self.write({'categories': [{'etfs': [{'code': 'SPY', 'enabled': True, 'market': 'US'},
                                            {'code': '0050', 'enabled': False}]}]})
        fallback = self.tracker.load_catalog()
        self.assertEqual(len(fallback), 10)
        self.assertIn('00992A', fallback)
        self.write({'categories': []})
        self.assertEqual(self.tracker.load_catalog(), fallback)

    def test_unexpected_parser_bug_is_not_silenced(self):
        self.write(self.pool())
        with mock.patch.object(self.tracker, '_catalog_from', side_effect=RuntimeError('unexpected parser bug')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected parser bug'):
                self.tracker.load_catalog()


if __name__ == '__main__':
    unittest.main()

"""研究查詢邊界：不啟動完整服務、不連網，所有資料僅在暫存目錄。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import ModuleType
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import 研究工作流 as research
import 研究工作流路由 as routes


class Handler(routes.ResearchWorkflowRoutesMixin):
    def __init__(self, path):
        self.path = path
        self.response = None

    def _ok(self, body):
        self.response = (200, json.loads(body))

    def _err(self, message, status):
        self.response = (status, {'error': message})


class ResearchBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'fixture.db'
        decision = ModuleType('decision_context')
        decision.DB_PATH = self.db
        decision._active_db_path = None
        self.early = ModuleType('early_warning')
        self.early.DB_PATH = self.db
        self.early.observation_page = mock.Mock(return_value={'ok': True, 'status': 'not_started',
            'observations': [], 'nextOffset': None, 'researchValidation': {'observations': 0, 'strata': []}})
        self.early.replay_observation = mock.Mock(return_value={'ok': True, 'status': 'matched'})
        portfolio = ModuleType('突破組合研究')
        portfolio.build_saved_portfolio = mock.Mock(return_value={'ok': True, 'status': 'unavailable', 'rules': []})
        data = ModuleType('datastore')
        data.DB_PATH = self.db
        patcher = mock.patch.dict(sys.modules, {'decision_context': decision, 'early_warning': self.early,
            '突破組合研究': portfolio, 'datastore': data})
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, name, query=''):
        handler = Handler('/research/' + name + query)
        getattr(handler, '_handle_research_' + name)()
        return handler.response

    def seed(self, raw=None):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE decision_commits(revision INTEGER,snapshot_id TEXT,context_json TEXT)')
            value = raw if raw is not None else json.dumps({'snapshotId': 'dc-1', 'revision': 1,
                'persistence': 'committed', 'asOf': '2026-10-01', 'evidence': []})
            conn.execute('INSERT INTO decision_commits VALUES(1,?,?)', ('dc-1', value))

    def test_unknown_duplicate_blank_and_bad_encoding_rejected_before_read(self):
        cases = {
            'workflow': ['?wat=1', '?limit=2&limit=3', '?current=', '?before=0', '?limit=101',
                '?before=01', '?before=1.0', '?before=-1', '?current=%FF', '?current=%XX', '?current'],
            'subject': ['', '?symbol=', '?symbol=2330&symbol=0050', '?symbol=2330&refresh=1'],
            'validation': ['?replay=', '?replay=x', '?offset=-1', '?offset=0&offset=1', '?offset=1&limit=',
                '?before=2', '?limit=101', '?replay=' + 'a' * 64 + '&offset=0'],
            'portfolio': ['?refresh=1', '?symbol=2330', '?limit=1', '?x='],
        }
        for name, queries in cases.items():
            for query in queries:
                with self.subTest(name=name, query=query):
                    self.assertEqual(400, self.call(name, query)[0])
        self.early.observation_page.assert_not_called()
        self.early.replay_observation.assert_not_called()
        self.assertFalse(self.db.exists())

    def test_empty_snapshot_is_actionable_and_does_not_create_database(self):
        status, result = self.call('workflow')
        self.assertEqual(200, status)
        self.assertEqual('not_started', result['status'])
        self.assertIn('更新工作中心', result['note'])
        self.assertTrue(result['cacheOnly'])
        self.assertFalse(self.db.exists())
        self.assertEqual(404, self.call('workflow', '?current=missing')[0])

    def test_corrupt_snapshot_returns_503_and_preserves_bytes(self):
        self.seed('{損毀內容')
        before = self.db.read_bytes()
        self.assertEqual(503, self.call('workflow')[0])
        self.assertEqual(before, self.db.read_bytes())

    def test_duplicate_evidence_and_nonfinite_values_are_data_errors(self):
        for evidence in [[{'id': 'x'}, {'id': 'x'}], [{'id': 'x', 'value': float('nan')}], ['錯誤資料列']]:
            value = {'snapshotId': 'dc-1', 'revision': 1, 'persistence': 'committed', 'evidence': evidence}
            with self.assertRaises(research.ResearchDataError):
                research._snapshot((1, 'dc-1', json.dumps(value)))

    def test_non_database_file_is_503_without_replacement(self):
        self.db.write_bytes(b'broken-database')
        self.assertEqual(503, self.call('workflow')[0])
        self.assertEqual(b'broken-database', self.db.read_bytes())

    def test_validation_pages_delegate_to_shared_denominator_engine(self):
        self.assertEqual(200, self.call('validation', '?offset=30&limit=10')[0])
        self.early.observation_page.assert_called_once_with(n=10, path=self.db, offset=30)
        self.assertFalse(self.db.exists())

    def test_replay_status_mapping_is_stable(self):
        for code, expected in [('not_found', 404), ('unavailable', 503), ('invalid_request', 400),
                               ('version_unavailable', 409), ('digest_mismatch', 409), ('mismatch', 409)]:
            self.early.replay_observation.return_value = {'ok': False, 'status': code, 'reason': '凍結觀測無法核對'}
            self.assertEqual(expected, self.call('validation', '?replay=' + 'a' * 64)[0])
        self.early.replay_observation.assert_called_with('a' * 64, self.db)

    def test_provider_exception_cannot_be_successful_empty_report(self):
        self.early.observation_page.side_effect = sqlite3.DatabaseError('測試損毀')
        self.assertEqual(503, self.call('validation')[0])


if __name__ == '__main__':
    unittest.main()

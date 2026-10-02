"""研究快照、差異及唯讀邊界的行為回歸。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from copy import deepcopy
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import 研究工作流 as research


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'decision.db'

    def seed(self, count=3):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE decision_commits(revision INTEGER,snapshot_id TEXT,context_json TEXT)')
            for n in range(1, count + 1):
                context = {'snapshotId': f'dc-{n}', 'revision': n, 'persistence': 'committed',
                    'regime': {'id': 'neutral'}, 'asOf': f'2026-09-{n:02d}',
                    'holdings': [{'sym': '私人'}], 'riskProfile': {'secret': 1},
                    'evidence': [{'id': 'breadth', 'metric': '廣度', 'value': n, 'source': '官方',
                                  'quality': 'observed', 'asOf': f'2026-09-{n:02d}'},
                                 {'id': 'portfolio.private', 'value': '私人'}]}
                conn.execute('INSERT INTO decision_commits VALUES(?,?,?)', (n, f'dc-{n}', json.dumps(context)))

    def test_missing_database_remains_missing(self):
        self.assertIsNone(research.workspace(self.path)['current'])
        self.assertFalse(self.path.exists())

    def test_read_preserves_bytes_and_filters_private_overlay(self):
        self.seed()
        before = self.path.read_bytes()
        value = research.workspace(self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(3, value['current']['revision'])
        self.assertEqual(2, value['previous']['revision'])
        self.assertNotIn('holdings', value['current'])
        self.assertNotIn('riskProfile', value['current'])
        self.assertEqual(['breadth'], [x['id'] for x in value['current']['evidence']])
        self.assertEqual('dc-3:breadth', value['current']['evidence'][0]['evidenceId'])

    def test_material_difference_keeps_both_versions(self):
        self.seed()
        row = research.workspace(self.path)['changes'][0]
        self.assertEqual('evidence', row['kind'])
        self.assertEqual(2, row['before']['value'])
        self.assertEqual(3, row['after']['value'])
        self.assertEqual('dc-2', row['fromSnapshotId'])

    def test_source_clock_is_not_market_change(self):
        a = {'snapshotId': 'a', 'evidence': [{'id': 'x', 'value': 10, 'asOf': '2026-01-01'}]}
        b = {'snapshotId': 'b', 'evidence': [{'id': 'x', 'value': 10, 'asOf': '2026-01-02'}]}
        self.assertEqual('source_time', research.differences(a, b)[0]['kind'])

    def test_every_public_decision_content_field_is_compared(self):
        non_content = {'asOf', 'snapshotId', 'revision', 'inputHash', 'rulesDigest', 'model',
                       'validUntil', 'expiresAt', 'publishedAt', 'persistence', 'contractVersion'}
        self.assertEqual(set(research.PUBLIC_FIELDS) - non_content, {key for key, _ in research.STATE_FIELDS})
        for key, title in research.STATE_FIELDS:
            with self.subTest(key=key):
                before = {'snapshotId': 'a', 'evidence': [], key: {'value': '原條件', 'asOf': '2026-09-21'}}
                after = {'snapshotId': 'b', 'evidence': [], key: {'value': '新條件', 'asOf': '2026-09-22'}}
                original = deepcopy((before, after))
                rows = research.differences(before, after)
                self.assertEqual(1, len(rows))
                self.assertEqual((key, title, 'state'), (rows[0]['key'], rows[0]['title'], rows[0]['kind']))
                self.assertEqual(before[key], rows[0]['before'])
                self.assertEqual(after[key], rows[0]['after'])
                self.assertEqual(original, (before, after))

    def test_confirmations_invalidation_scenario_and_warning_cannot_report_no_change(self):
        before = {'snapshotId': 'a', 'evidence': [], 'confirmation': ['等待站穩前高'],
                  'invalidation': ['跌破支撐失效'], 'scenario': {'bull': 0.4},
                  'earlyWarnings': {'signals': [{'signalId': 'breadth', 'state': 'WATCH'}]}}
        after = deepcopy(before)
        after.update(snapshotId='b', confirmation=['等待成交量確認'],
                     invalidation=['回測前高失敗'], scenario={'bull': 0.6})
        after['earlyWarnings']['signals'][0]['state'] = 'CONFIRMED'
        rows = research.differences(before, after)
        self.assertEqual({'confirmation', 'invalidation', 'scenario', 'earlyWarnings'}, {row['key'] for row in rows})
        self.assertTrue(all(row['kind'] != 'source_time' for row in rows))

    def test_identity_version_and_nested_source_clocks_do_not_create_market_changes(self):
        before = {'snapshotId': 'a', 'revision': 1, 'asOf': '2026-09-21', 'model': 'v1',
                  'evidence': [], 'dataQuality': {'status': 'valid', 'checkedAt': '2026-09-21'},
                  'scenario': {'version': 'v1', 'inputHash': 'a', 'raw': {'value': 100, 'asOf': '2026-09-21'}},
                  'earlyWarnings': {'engineVersion': 'v1', 'model': 'v1', 'observationKey': 'a',
                                    'temporalContext': {'computedAt': '2026-09-21', 'baseline': {'ageSeconds': 30}},
                                    'signals': [{'state': 'WATCH', 'sourceAsOf': '2026-09-21'}]}}
        after = deepcopy(before)
        after.update(snapshotId='b', revision=2, asOf='2026-09-22', model='v2', rulesDigest='new')
        after['dataQuality']['checkedAt'] = '2026-09-22'
        after['scenario'].update(version='v2', inputHash='b')
        after['scenario']['raw']['asOf'] = '2026-09-22'
        after['earlyWarnings']['engineVersion'] = 'v2'
        after['earlyWarnings'].update(model='v2', observationKey='b')
        after['earlyWarnings']['temporalContext'] = {'computedAt': '2026-09-22', 'baseline': {'ageSeconds': 60}}
        after['earlyWarnings']['signals'][0]['sourceAsOf'] = '2026-09-22'
        self.assertEqual([], research.differences(before, after))
        after['dataQuality']['status'] = 'stale'
        self.assertEqual(['dataQuality'], [row['key'] for row in research.differences(before, after)])

    def test_event_expiry_session_and_evidence_reference_remain_material(self):
        before = {'snapshotId': 'a', 'evidence': [{'id': 'x', 'value': 10, 'reference': {'value': 9}}],
                  'earlyWarnings': {'signals': [{'state': 'WATCH', 'expiresAt': '2026-09-22', 'sessionDate': '2026-09-21'}]}}
        after = deepcopy(before)
        after['snapshotId'] = 'b'
        after['earlyWarnings']['signals'][0].update(expiresAt='2026-09-23', sessionDate='2026-09-22')
        after['evidence'][0]['reference']['value'] = 8
        self.assertEqual({'earlyWarnings', 'x'}, {row['key'] for row in research.differences(before, after)})

    def test_history_pages_no_silent_loss(self):
        self.seed(8)
        value = research.workspace(self.path, limit=3)
        revisions = []
        while True:
            revisions.extend(x['revision'] for x in value['history'])
            if not value['nextBefore']:
                break
            value = research.workspace(self.path, limit=3, before=value['nextBefore'])
        self.assertEqual(list(range(8, 0, -1)), revisions)

    def test_missing_snapshot_and_reverse_comparison_fail(self):
        self.seed()
        with self.assertRaises(LookupError):
            research.workspace(self.path, current_id='dc-100')
        with self.assertRaises(ValueError):
            research.workspace(self.path, current_id='dc-1', previous_id='dc-3')
        with self.assertRaises(ValueError):
            research.workspace(self.path, current_id="' OR 1=1")

    def test_mismatched_committed_identity_rejected(self):
        self.seed()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE decision_commits SET snapshot_id='wrong' WHERE revision=3")
        with self.assertRaises(ValueError):
            research.workspace(self.path)

    def test_observations_paginate_without_mutation_or_replay_payload(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE signal_research_observations(record_json TEXT)')
            for number in range(8):
                conn.execute('INSERT INTO signal_research_observations VALUES(?)',
                             (json.dumps({'observationId': str(number), 'replay': {'private': '不得列入清單'}}),))
        before = self.path.read_bytes()
        cursor, identifiers = None, []
        while True:
            page = research.observation_page(self.path, before=cursor, limit=3)
            self.assertTrue(all('replay' not in row for row in page['observations']))
            identifiers.extend(row['observationId'] for row in page['observations'])
            cursor = page['nextBefore']
            if cursor is None:
                break
        self.assertEqual(identifiers, [str(n) for n in reversed(range(8))])
        self.assertEqual(before, self.path.read_bytes())

    def test_observation_empty_read_does_not_create_storage(self):
        self.assertEqual([], research.observation_page(self.path)['observations'])
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            research.observation_page(self.path, before=-1)


if __name__ == '__main__':
    unittest.main()

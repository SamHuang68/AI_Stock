"""以真實暫存 SQLite 驗證提交、恢復及對外副作用邊界。"""
import copy
import json
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import decision_context as dc
import decision_store as store
import early_warning as ew
from tests.test_決策資料品質 import observed_pulse


class DurablePublicationTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = str(Path(folder.name) / 'decision.db')
        self.signal_db = str(Path(folder.name) / 'market_signals.db')
        self.trace = str(Path(folder.name) / 'trace.jsonl')
        self.delivery = Mock(return_value={'ok': True, 'delivered': 0})
        for replacement in (
            patch.object(dc, '_latest_context', None), patch.object(dc, '_latest_inputs', None),
            patch.object(dc, '_active_db_path', self.db), patch.object(dc, 'DB_PATH', self.db),
            patch.object(ew, 'DB_PATH', self.signal_db),
            patch.dict(sys.modules, {'overnight_intraday': types.SimpleNamespace(latest_cached=lambda *a: None),
                                     'alert_daemon': types.SimpleNamespace(deliver_signal_events=self.delivery)}),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def publish(self, minute=0, **kwargs):
        p = observed_pulse(f'2026-08-11T09:{minute:02d}:00+08:00')
        options = {'now': datetime.fromisoformat(p['updatedAt']), **kwargs}
        context = dc.build_decision_context(p, **options)
        return dc.publish_context(context, pulse=p, build_kwargs=options, db_path=self.db, trace_path=self.trace)

    def rows(self, path, table):
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()

    def restart(self):
        dc._latest_context = None
        dc._latest_inputs = None

    def block_history(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TRIGGER reject_history BEFORE INSERT ON decision_history "
                         "BEGIN SELECT RAISE(ABORT, '注入提交失敗'); END")

    def unblock_history(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TRIGGER reject_history')

    def test_commit_failure_keeps_ram_history_success_time_and_delivery(self):
        first = self.publish()
        success = dc._status['lastSuccess']
        self.block_history()
        with self.assertRaises(dc.SnapshotPublicationError):
            self.publish(1)
        self.assertEqual(dc._latest_context['snapshotId'], first['snapshotId'])
        self.assertEqual(store.load(self.db)['context']['snapshotId'], first['snapshotId'])
        self.assertEqual(dc.history(path=self.db)['rows'][0]['context']['snapshotId'], first['snapshotId'])
        self.assertEqual(dc._status['lastSuccess'], success)
        self.assertEqual(self.delivery.call_count, 1)
        self.assertEqual(len(store.pending(self.db)), 1)
        self.assertEqual(len(self.rows(self.db, 'decision_delivery_attempts')), 1)

    def test_restart_recovers_inputs_watermark_and_original_observation_time(self):
        first = self.publish(2)
        self.restart()
        view = dc.latest_context(now=datetime.fromisoformat('2026-09-21T10:00:00+08:00'))
        self.assertEqual(view['snapshotId'], first['snapshotId'])
        self.assertEqual(view['asOf'], first['asOf'])
        self.assertEqual(view['viewState'], 'source_expired')
        self.assertEqual(view['regime']['id'], 'INSUFFICIENT_DATA')
        self.assertEqual(dc.latest_pulse()['updatedAt'], first['asOf'])
        rejected = self.publish(1)
        self.assertEqual(rejected['publicationStatus'], 'superseded')
        self.assertEqual(rejected['snapshotId'], first['snapshotId'])
        self.assertEqual(self.delivery.call_count, 1)

    def test_prepared_intent_replays_receipt_before_accepting_newer_publication(self):
        self.publish()
        self.block_history()
        with self.assertRaises(dc.SnapshotPublicationError):
            self.publish(1)
        prepared = store.pending(self.db)[0]
        signal_before = self.rows(self.signal_db, 'signal_state')
        events_before = self.rows(self.signal_db, 'signal_events')
        self.unblock_history()
        self.restart()
        # 先讀前版，不在讀取時恢復意圖或發送通知。
        self.assertEqual(dc.latest_context()['revision'], 1)
        self.assertEqual(self.delivery.call_count, 1)
        # 較早請求先恢復待提交版本，隨後遭水位拒絕。
        restored = self.publish(0)
        self.assertEqual(restored['snapshotId'], prepared['snapshotId'])
        self.assertEqual(restored['revision'], 2)
        self.assertEqual(restored['publicationStatus'], 'superseded')
        self.assertEqual(store.pending(self.db), [])
        self.assertEqual(self.rows(self.signal_db, 'signal_state'), signal_before)
        self.assertEqual(self.rows(self.signal_db, 'signal_events'), events_before)
        self.assertEqual(self.delivery.call_count, 2)

    def test_unwritable_prepare_has_no_warning_or_delivery(self):
        target = Path(self.db)
        target.mkdir()
        with patch.object(ew, 'process_context', wraps=ew.process_context) as warning:
            with self.assertRaises(dc.SnapshotPublicationError):
                self.publish()
        warning.assert_not_called()
        self.delivery.assert_not_called()
        self.assertIsNone(dc._latest_context)

    def test_same_payload_deduplicates_commit_warning_and_delivery(self):
        first = self.publish()
        duplicate = self.publish()
        self.assertEqual(duplicate['snapshotId'], first['snapshotId'])
        self.assertEqual(duplicate['revision'], first['revision'])
        self.assertEqual(len(self.rows(self.db, 'decision_commits')), 1)
        self.assertEqual(self.delivery.call_count, 1)

    def test_options_revision_changes_identity_and_does_not_rewind_on_replay(self):
        first = self.publish(options_structure={'status': 'first'})
        second = self.publish(options_structure={'status': 'second'})
        replay = self.publish(options_structure={'status': 'first'})
        self.assertEqual(second['revision'], first['revision'] + 1)
        self.assertNotEqual(first['snapshotId'], second['snapshotId'])
        self.assertEqual(replay['snapshotId'], second['snapshotId'])
        self.assertEqual(replay['publicationStatus'], 'superseded')

    def test_return_value_and_compact_projection_cannot_mutate_canonical_context(self):
        first = self.publish()
        snapshot_id = first['snapshotId']
        first['regime']['id'] = 'CALLER_MUTATION'
        self.assertNotEqual(dc._latest_context['regime']['id'], 'CALLER_MUTATION')
        self.assertEqual(store.load(self.db)['context']['snapshotId'], snapshot_id)
        full = dc.latest_context()
        summary = dc.latest_pulse()['decisionSummary']
        for key in ('snapshotId', 'revision', 'inputHash', 'rulesDigest', 'persistence', 'viewState'):
            self.assertEqual(full[key], summary[key], key)

    def test_personal_view_has_lineage_but_no_committed_snapshot_identity(self):
        first = self.publish()
        personal = dc.rebuild_latest(risk_profile={'baseGrossExposure': 50})
        self.assertEqual(personal['parentSnapshotId'], first['snapshotId'])
        self.assertEqual(personal['persistence'], 'ephemeral')
        self.assertNotIn('snapshotId', personal)
        self.assertNotIn('revision', personal)
        self.assertEqual(len(self.rows(self.db, 'decision_commits')), 1)

    def test_rules_change_preserves_pending_intent_and_blocks_new_side_effects(self):
        self.publish()
        self.block_history()
        with self.assertRaises(dc.SnapshotPublicationError):
            self.publish(1)
        self.unblock_history()
        with patch.object(dc, 'RULES_VERSION', '另一版規則'), patch.object(ew, 'process_context') as warning:
            with self.assertRaises(dc.SnapshotPublicationError):
                self.publish(2)
        warning.assert_not_called()
        self.assertEqual(len(store.pending(self.db)), 1)
        self.assertEqual(self.delivery.call_count, 1)

    def test_read_only_empty_store_creates_no_files(self):
        self.assertIsNone(dc.latest_context())
        self.assertEqual(dc.engine_status()['pendingPublications'], 0)
        self.assertFalse(Path(self.db).exists())

    def test_notification_failure_is_recorded_without_repeating_attempt(self):
        self.delivery.side_effect = RuntimeError('注入傳送失敗')
        first = self.publish()
        self.assertEqual(first['persistence'], 'committed')
        self.assertEqual(store.status(self.db)['deliveryAttempts'], {'failed': 1})
        self.publish()
        self.assertEqual(self.delivery.call_count, 1)

    def test_partial_notification_failure_keeps_original_channel_results(self):
        result = {'ok': True, 'delivered': 1, 'results': [
            {'eventId': '事件甲', 'ok': False, 'detail': {'webhook': 'HTTP 503'}},
            {'eventId': '事件乙', 'ok': True, 'detail': {'webhook': 'HTTP 200'}},
        ]}
        self.delivery.return_value = result
        self.publish()
        row = self.rows(self.db, 'decision_delivery_attempts')[0]
        self.assertEqual(row[2], 'failed')
        self.assertEqual(json.loads(row[3]), result)

    def test_read_of_committed_context_does_not_wait_for_notification(self):
        self.publish()
        entered = threading.Event()
        release = threading.Event()
        def delayed(events):
            entered.set()
            release.wait(3)
            return {'ok': True}
        self.delivery.side_effect = delayed
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(self.publish, 1)
            self.assertTrue(entered.wait(2))
            try:
                reader = pool.submit(dc.latest_context)
                self.assertEqual(reader.result(timeout=0.5)['revision'], 2)
            finally:
                release.set()
            writer.result(timeout=2)

    def test_receipt_ack_failure_does_not_turn_committed_result_into_failure(self):
        with patch.object(ew, 'acknowledge_publication', side_effect=OSError('注入收據確認失敗')):
            first = self.publish()
        self.assertEqual(first['persistence'], 'committed')
        self.assertEqual(store.load(self.db)['context']['snapshotId'], first['snapshotId'])
        self.assertIn('signal-receipt:', dc._status['lastError'])
        self.restart()
        self.publish()
        receipt = self.rows(self.signal_db, 'signal_publication_receipts')[0]
        self.assertIsNotNone(receipt[-1])

    def test_corrupt_identity_is_not_loaded_as_a_committed_snapshot(self):
        self.publish()
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute("UPDATE decision_commits SET snapshot_id='毀損識別'")
        self.restart()
        with self.assertRaisesRegex(ValueError, '識別或輸入不完整'):
            dc.latest_context()


if __name__ == '__main__':
    unittest.main()

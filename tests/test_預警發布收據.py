# -*- coding: utf-8 -*-
"""使用暫存 SQLite 驗證預警發布收據與生命週期的交易邊界。"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.test_early_warning import ew, fixture, memory


class PublicationReceiptTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='預警收據-')
        self.addCleanup(self.folder.cleanup)
        self.db = str(Path(self.folder.name) / 'signals.db')
        self.start = datetime(2026, 8, 26, 1, 10, tzinfo=timezone.utc)

    def publish(self, publication_id=None, *, at=None, direction=1):
        at = at or self.start
        context, pulse = fixture(direction, as_of=at.isoformat())
        return ew.process_context(context, pulse, memory_snapshot=memory(), db_path=self.db,
                                  now=at, publication_id=publication_id)

    def rows(self):
        tables = ('signal_state', 'signal_observations', 'signal_events', 'signal_market_sessions',
                  'signal_trials', 'signal_outcomes', 'signal_publication_receipts')
        with closing(sqlite3.connect(self.db)) as conn:
            return {table: conn.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                    for table in tables}

    def test_replay_returns_original_events_and_never_recalculates_expired_observation(self):
        first = self.publish('發布甲')
        self.assertTrue(first['newEvents'])
        self.assertTrue(self.rows()['signal_trials'])
        original = json.loads(json.dumps(first))
        before = self.rows()
        first['newEvents'].clear()
        # 即使已超過效期且輸入不同，重播同一發布識別仍回復首次完整結果。
        with patch.object(ew, 'evaluate_context', side_effect=AssertionError('重播不得重新計算')):
            replayed = self.publish('發布甲', at=self.start + timedelta(days=30), direction=-1)
        self.assertEqual(replayed, original)
        self.assertEqual(self.rows(), before)

    def test_receipt_insert_failure_rolls_back_state_events_and_trials(self):
        self.publish('已提交甲')
        before = self.rows()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TRIGGER 阻擋收據 BEFORE INSERT ON signal_publication_receipts "
                         "BEGIN SELECT RAISE(FAIL, '測試收據失敗'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, '測試收據失敗'):
            self.publish('發布乙', at=self.start + timedelta(minutes=1), direction=-1)
        self.assertEqual(self.rows(), before)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TRIGGER 阻擋收據')
        recovered = self.publish('發布乙', at=self.start + timedelta(minutes=1), direction=-1)
        self.assertTrue(recovered['newEvents'])
        self.assertEqual(len(self.rows()['signal_publication_receipts']), 2)

    def test_receipt_survives_connection_and_schema_cache_reset(self):
        first = self.publish('重新載入甲')
        before = self.rows()
        with patch.object(ew, '_db_ready', set()), \
                patch.object(ew, 'evaluate_context', side_effect=AssertionError('收據須由磁碟恢復')):
            replayed = self.publish('重新載入甲', at=self.start + timedelta(days=1))
        self.assertEqual(first, replayed)
        self.assertEqual(self.rows(), before)

    def test_concurrent_replays_commit_one_receipt_and_one_transition(self):
        ew._init_db(self.db)
        barrier = threading.Barrier(2)

        def publish_once():
            barrier.wait(timeout=5)
            return self.publish('並行發布甲')

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(publish_once) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results[0], results[1])
        rows = self.rows()
        self.assertEqual(len(rows['signal_publication_receipts']), 1)
        self.assertEqual(len(rows['signal_events']), len(results[0]['newEvents']))
        with closing(sqlite3.connect(self.db)) as conn:
            state = conn.execute('SELECT state,consecutive_hits FROM signal_state '
                                 "WHERE signal_id='TW_ATTACK_BUILDUP'").fetchone()
        self.assertEqual(state, ('WATCH', 1))

    def test_legacy_call_keeps_observation_deduplication_without_receipts(self):
        first = self.publish()
        replayed = self.publish()
        self.assertTrue(first['newEvents'])
        self.assertEqual(replayed['newEvents'], [])
        self.assertEqual(self.rows()['signal_publication_receipts'], [])

    def test_invalid_publication_id_is_rejected_before_creating_database(self):
        for invalid in ('', '  ', 5):
            with self.subTest(publication_id=invalid), self.assertRaises(ValueError):
                self.publish(invalid)
        self.assertFalse(Path(self.db).exists())

    def test_acknowledgement_keeps_unconfirmed_and_recent_confirmed_receipts(self):
        pending = self.publish('尚未確認')
        results = {key: self.publish(key) for key in ('已確認甲', '已確認乙', '已確認丙')}
        with patch.object(ew, '_PUBLICATION_RECEIPT_RETAIN', 2):
            for key in results:
                self.assertTrue(ew.acknowledge_publication(key, db_path=self.db))
        with closing(sqlite3.connect(self.db)) as conn:
            receipts = dict(conn.execute('SELECT publication_id,committed_at FROM signal_publication_receipts'))
        self.assertEqual(set(receipts), {'尚未確認', '已確認乙', '已確認丙'})
        self.assertIsNone(receipts['尚未確認'])
        self.assertTrue(receipts['已確認乙'])
        self.assertTrue(receipts['已確認丙'])
        with patch.object(ew, 'evaluate_context', side_effect=AssertionError('保留收據不得重新計算')):
            self.assertEqual(self.publish('尚未確認', at=self.start + timedelta(days=1)), pending)
            self.assertEqual(self.publish('已確認乙', at=self.start + timedelta(days=1)), results['已確認乙'])
            self.assertEqual(self.publish('已確認丙', at=self.start + timedelta(days=1)), results['已確認丙'])

    def test_repeated_acknowledgement_preserves_first_commit_time_and_signal_state(self):
        self.publish('確認一次')
        before = self.rows()
        self.assertTrue(ew.acknowledge_publication('確認一次', db_path=self.db))
        confirmed = self.rows()
        self.assertTrue(ew.acknowledge_publication('確認一次', db_path=self.db))
        self.assertEqual(self.rows(), confirmed)
        self.assertFalse(ew.acknowledge_publication('不存在', db_path=self.db))
        self.assertEqual(self.rows(), confirmed)
        for table in before:
            if table != 'signal_publication_receipts':
                self.assertEqual(before[table], confirmed[table])

    def test_existing_receipt_schema_is_migrated_without_implicit_acknowledgement(self):
        stored = {'newEvents': [{'eventId': '既有事件'}], 'signals': [], 'asOf': self.start.isoformat()}
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute('CREATE TABLE signal_publication_receipts('
                             'publication_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,result_json TEXT NOT NULL)')
                conn.execute('INSERT INTO signal_publication_receipts VALUES(?,?,?)',
                             ('既有收據', self.start.isoformat(), json.dumps(stored)))
        with patch.object(ew, 'evaluate_context', side_effect=AssertionError('遷移不得重播生命週期')):
            self.assertEqual(self.publish('既有收據'), stored)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertIsNone(conn.execute('SELECT committed_at FROM signal_publication_receipts').fetchone()[0])
        self.assertTrue(ew.acknowledge_publication('既有收據', db_path=self.db))
        self.assertEqual(self.publish('既有收據'), stored)

    def test_cleanup_failure_rolls_back_acknowledgement(self):
        self.publish('保留甲')
        self.publish('等待乙')
        self.assertTrue(ew.acknowledge_publication('保留甲', db_path=self.db))
        before = self.rows()
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TRIGGER 阻擋清理 BEFORE DELETE ON signal_publication_receipts "
                         "BEGIN SELECT RAISE(FAIL, '測試清理失敗'); END")
        with patch.object(ew, '_PUBLICATION_RECEIPT_RETAIN', 1), \
                self.assertRaisesRegex(sqlite3.IntegrityError, '測試清理失敗'):
            ew.acknowledge_publication('等待乙', db_path=self.db)
        self.assertEqual(self.rows(), before)


if __name__ == '__main__':
    unittest.main()

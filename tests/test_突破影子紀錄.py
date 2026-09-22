"""驗證前瞻觀察不由讀取建立、不重複、不因歷史修訂覆寫。"""
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import 突破影子紀錄 as ledger


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'market.db'
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('CREATE TABLE action_coverage(market TEXT,symbol TEXT)')
        self.now = datetime(2026, 9, 20, 8, tzinfo=ledger.TZ)
        self.result = {'sym': '2330', 'asOf': '2026-09-18',
                       'freshness': {'fresh': True, 'expectedSession': '2026-09-18'},
                       'research': {'version': '研究測試版', 'latest': {
                           'date': '2026-09-18', 'close': 100, 'inputDigest': '原始',
                           'conditions': {'breakout_252': True}, 'signals': ['breakout_252']}}}

    def test_read_does_not_create_table_and_weekend_rerun_is_deduplicated(self):
        before = self.db.read_bytes()
        empty = ledger.summary(self.db, '2330', self.result['research'], '2026-09-18')
        self.assertEqual(empty['count'], 0)
        self.assertEqual(before, self.db.read_bytes())
        self.assertTrue(ledger.append_observation(self.db, self.result, self.now))
        self.assertFalse(ledger.append_observation(self.db, self.result, self.now))
        found = ledger.summary(self.db, '2330', self.result['research'], '2026-09-18')
        self.assertEqual(found['count'], 1)
        self.assertEqual(found['observedAt'], self.now.isoformat())

    def test_revision_keeps_original_evidence_and_excludes_future_sessions(self):
        ledger.append_observation(self.db, self.result, self.now)
        revised = copy.deepcopy(self.result)
        revised['research']['latest'].update(inputDigest='修訂', close=101)
        self.assertFalse(ledger.append_observation(self.db, revised, self.now))
        found = ledger.summary(self.db, '2330', revised['research'], '2026-09-18')
        self.assertTrue(found['revised'])
        self.assertEqual(found['evidence']['close'], 100)
        self.assertEqual(ledger.summary(self.db, '2330', revised['research'], '2026-09-17')['count'], 0)

    def test_stale_or_historical_report_never_becomes_prospective(self):
        for change in ('stale', 'historical', 'no_digest'):
            result = copy.deepcopy(self.result)
            if change == 'stale':
                result['freshness']['fresh'] = False
            elif change == 'historical':
                result['asOf'] = result['research']['latest']['date'] = '2026-09-17'
            else:
                result['research']['latest']['inputDigest'] = None
            self.assertFalse(ledger.append_observation(self.db, result, self.now))
        with self.assertRaises(ValueError):
            ledger.append_observation(self.db, self.result, datetime(2026, 9, 20))

    def test_daily_writer_uses_existing_research_universe(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO action_coverage VALUES('TW','2330')")
        with patch('K線事件.report', return_value=self.result) as report:
            outcome = ledger.record_daily(self.db, now=self.now)
        self.assertEqual((outcome['checked'], outcome['added'], outcome['failures']), (1, 1, []))
        report.assert_called_once_with(self.db, '2330', now=self.now, period='30d')

    def test_observation_time_is_separate_from_session_evaluation_time(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO action_coverage VALUES('TW','2330')")
        recorded = self.now.replace(hour=9)
        with patch('K線事件.report', return_value=self.result):
            ledger.record_daily(self.db, now=self.now, observed_at=recorded)
        found = ledger.summary(self.db, '2330', self.result['research'], '2026-09-18')
        self.assertEqual(found['observedAt'], recorded.isoformat())

    def test_writer_failure_is_visible_without_creating_ledger(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE daily_update_state(id INTEGER PRIMARY KEY,payload TEXT)')
            conn.execute('INSERT INTO daily_update_state VALUES(1,?)', (json.dumps({
                'researchShadow': {'status': '紀錄失敗', 'reason': 'OperationalError'}}),))
        before = self.db.read_bytes()
        found = ledger.summary(self.db, '2330', self.result['research'], '2026-09-18')
        self.assertEqual(found['writer']['status'], '紀錄失敗')
        self.assertIn('未完整完成', found['note'])
        self.assertEqual(before, self.db.read_bytes())


if __name__ == '__main__':
    unittest.main()

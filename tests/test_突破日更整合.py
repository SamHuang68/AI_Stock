"""成功日更才附加影子紀錄，失敗可見且取消例外保留。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 台股日線 as daily
import 突破影子紀錄 as shadow


class 日更影子整合測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / '研究.db'
        datastore.init_db(self.db)
        self.now = datetime(2026, 9, 11, 18, tzinfo=daily.TZ)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            for exchange in ('TWSE', 'TPEX'):
                conn.execute('INSERT INTO daily_imports VALUES(?,?,?,?,?)', (exchange, '2026-09-11', 1, '測試', self.now.isoformat()))

    def run_daily(self, **kwargs):
        with patch.object(daily, 'stored_calendar', return_value=(set(), set())), patch.object(daily, 'reconcile_sessions', return_value={self.now.date()}):
            return daily.run_update(self.db, now=self.now, fetch=lambda url: self.fail('不應抓取'), **kwargs)

    def test_資料成功先存狀態再附加影子且只傳本機來源(self):
        def record(db, *, now, check):
            check()
            with closing(sqlite3.connect(db)) as conn:
                state = json.loads(conn.execute('SELECT payload FROM daily_update_state').fetchone()[0])
            self.assertTrue(state['ok'])
            return {'status': '已檢查', 'checked': 0, 'added': 0, 'failures': []}
        with patch.object(shadow, 'record_daily', side_effect=record) as writer:
            result = self.run_daily()
        self.assertTrue(result['ok'])
        self.assertEqual(result['researchShadow']['status'], '已檢查')
        self.assertEqual(writer.call_count, 1)

    def test_影子故障不偽裝成功且不取消已完成行情(self):
        with patch.object(shadow, 'record_daily', side_effect=RuntimeError('測試錯誤')):
            result = self.run_daily()
        self.assertTrue(result['ok'])
        self.assertEqual(result['researchShadow'], {'status': '紀錄失敗', 'reason': 'RuntimeError'})

    def test_不完整更新不得保存影子(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM daily_imports WHERE exchange='TPEX'")
        with patch.object(shadow, 'record_daily') as writer:
            with patch.object(daily, 'parse_daily', side_effect=ValueError('資料不足')):
                result = self.run_daily()
        self.assertFalse(result['ok'])
        self.assertEqual(result['researchShadow']['status'], '未紀錄')
        writer.assert_not_called()

    def test_取消穿過影子與日更例外層且留下取消狀態(self):
        class 取消(Exception):
            pass
        cancelled = False
        def check():
            if cancelled:
                raise 取消('已取消')
        def record(db, *, now, check):
            nonlocal cancelled
            cancelled = True
            check()
        with patch.object(shadow, 'record_daily', side_effect=record):
            with self.assertRaises(取消):
                self.run_daily(check=check)
        with closing(sqlite3.connect(self.db)) as conn:
            state = json.loads(conn.execute('SELECT payload FROM daily_update_state').fetchone()[0])
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='breakout_observations'").fetchone())
        self.assertFalse(state['ok'])
        self.assertEqual(state['researchShadow']['status'], '已取消')

    def test_個股研究完成後取消不得落盤(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO action_coverage VALUES('TW','2330','2025-01-01','2026-09-11','TWSE')")
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('取消')
        with patch('突破觀察.report', return_value={}), patch.object(shadow, 'append_observation') as writer:
            with self.assertRaisesRegex(RuntimeError, '取消'):
                shadow.record_daily(self.db, now=self.now, check=check)
        writer.assert_not_called()


if __name__ == '__main__':
    unittest.main()

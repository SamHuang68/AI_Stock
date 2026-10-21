"""審查 CAL-02：JSON 未涵蓋的之後年度改讀資料庫內的 TWSE 官方日曆；更早年度與缺資料時維持原行為。不連網。"""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server'))

import datastore  # noqa: E402
import etf_paths  # noqa: E402
import options_exposure  # noqa: E402
import 台股交易參考 as ref  # noqa: E402

TPE = timezone(timedelta(hours=8))
CLOSED_2027 = ['2027-01-01', '2027-02-08', '2027-02-09']
OPENED_2027 = ['2027-02-20']          # 假設的補班星期六


class TwCalendarDbFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, 'market.db')
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE calendar_years(year INTEGER PRIMARY KEY, closed TEXT, opened TEXT, refreshed_at TEXT)')
            for year, closed, opened in ((2027, CLOSED_2027, OPENED_2027), (2025, ['2025-01-01'], [])):
                conn.execute('INSERT INTO calendar_years VALUES(?,?,?,?)', (year, json.dumps(closed), json.dumps(opened), 'x'))
        patcher = mock.patch.object(datastore, 'DB_PATH', self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clear_cache()
        self.addCleanup(self.clear_cache)

    @staticmethod
    def clear_cache():
        getattr(ref, '_db_calendar_cache', {}).clear()

    def test_later_year_uses_official_db_calendar(self):
        self.assertEqual(ref.session(date(2027, 1, 1))['status'], 'closed')
        monday = ref.session(date(2027, 1, 4))
        self.assertEqual(monday['status'], 'scheduled')
        self.assertEqual(monday['source'], ref.DB_CALENDAR_SOURCE)
        self.assertEqual(ref.session(date(2027, 2, 9))['status'], 'closed')
        self.assertEqual(ref.session(date(2027, 2, 20))['status'], 'scheduled')   # 補班日
        self.assertEqual(ref.session(date(2027, 2, 27))['status'], 'closed')      # 一般週六
        self.assertTrue(ref.calendar_covers(2027))

    def test_previous_session_crosses_year_end(self):
        # 2027-01-04（一）往前：1/3 日、1/2 六、1/1 元旦皆休市 → 2026-12-31（JSON 表定交易日）
        self.assertEqual(ref.previous_session('2027-01-04'), '2026-12-31')
        self.assertEqual(ref.previous_session('2027-01-05'), '2027-01-04')

    def test_options_chain_ready_in_new_year(self):
        now = datetime(2027, 1, 5, 10, 0, tzinfo=TPE)
        self.assertTrue(options_exposure._date_ready('2027-01-04', now))

    def test_missing_year_in_db_stays_unknown(self):
        self.assertEqual(ref.session(date(2028, 1, 4))['status'], 'unknown')
        self.assertIsNone(ref.previous_session('2028-01-04'))
        self.assertFalse(ref.calendar_covers(2028))

    def test_earlier_years_unchanged_even_if_db_has_them(self):
        # 資料庫有 2025，但 JSON 年度之前的行為不變：平日仍為未知，不改變既有歷史計算
        self.assertEqual(ref.session(date(2025, 3, 3))['status'], 'unknown')
        self.assertFalse(ref.calendar_covers(2025))

    def test_contradictory_db_row_is_rejected(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('UPDATE calendar_years SET opened=? WHERE year=2027', (json.dumps(['2027-01-01']),))
        self.clear_cache()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ref.session(date(2027, 1, 4))['status'], 'unknown')

    def test_etf_freshness_disclosure_counts_db_year_as_covered(self):
        info = etf_paths.freshness_calendar([date(2026, 12, 28)], date(2027, 1, 6))
        self.assertEqual(info['unknownYears'], [])
        self.assertEqual(info['basis'], 'twse_calendar')


if __name__ == '__main__':
    unittest.main()

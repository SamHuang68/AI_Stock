"""全市場日線缺口：偵測、追補與排程接線的回歸驗證。

起因：2026-10 本機有 9 個交易日、正式站有 2 個交易日缺全市場日線，原因是收盤後排程只在平日 14:00～21:00 的窗口內
處理「當天」，服務沒在窗口內運行就永遠缺；官方更新器預設只取最近一日，不會追補。"""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 全市場日線缺口 as gap
import 台股日線 as daily
import 個股研究維護 as maintenance

TODAY = date(2026, 7, 27)          # 週一；前 31 日內（6/26～7/26）沒有休市日
TZ = daily.TZ


def weekdays(end, count):
    day, out = end, []
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day -= timedelta(days=1)
    return sorted(out)


class GapCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'market.db'
        self.old_path = datastore.DB_PATH
        datastore.DB_PATH = str(self.db)
        datastore.init_db()
        daily.save_calendar(self.db, 2026, set(), set())     # 休市日清單為空：平日皆為交易日
        self.sessions = weekdays(TODAY - timedelta(days=1), 22)

    def tearDown(self):
        datastore.DB_PATH = self.old_path
        self.temp.cleanup()

    def fill(self, per_day):
        """per_day: {date: 該日有資料的股票數}；其餘交易日視為 600 檔。"""
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM bars WHERE market='TW'")
            rows = []
            for day in self.sessions:
                for i in range(per_day.get(day, 600)):
                    rows.append((f'{1000 + i}', 'TW', daily.stamp(day), 10, 11, 9, 10, 1000))
            conn.executemany('INSERT INTO bars(symbol,market,ts,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?,?)', rows)


class MissingSessionTests(GapCase):
    def test_flags_days_with_almost_no_or_half_missing_market_data(self):
        flagged = (self.sessions[5], self.sessions[10], self.sessions[15])
        self.fill({flagged[0]: 2, flagged[1]: 250, flagged[2]: 0})
        self.assertEqual(gap.missing_sessions(self.db, TODAY), [d.isoformat() for d in flagged])

    def test_a_day_with_most_symbols_present_is_not_a_gap(self):
        self.fill({self.sessions[5]: 330})                  # 55%：高於門檻
        self.assertEqual(gap.missing_sessions(self.db, TODAY), [])

    def test_complete_database_has_no_gap_and_today_is_never_judged(self):
        self.fill({})                                       # 今天（TODAY）沒有任何資料，仍不得被判定為缺口
        self.assertEqual(gap.missing_sessions(self.db, TODAY), [])

    def test_a_watchlist_only_database_is_not_judged_against_the_market(self):
        self.fill({**{day: 40 for day in self.sessions}, self.sessions[8]: 0})   # 只存自選股：中位數低於 MIN_MARKET_SIZE
        self.assertEqual(gap.missing_sessions(self.db, TODAY), [])

    def test_days_outside_the_31_day_window_are_ignored(self):
        outside, inside = self.sessions[0], self.sessions[6]
        self.assertLess(outside, TODAY - timedelta(days=gap.WINDOW_DAYS))
        self.fill({outside: 0, inside: 0})
        self.assertEqual(gap.missing_sessions(self.db, TODAY), [inside.isoformat()])

    def test_unknown_calendar_returns_nothing_instead_of_guessing(self):
        self.fill({self.sessions[3]: 0})
        with patch('台股交易參考.verified_sessions', return_value=None):
            self.assertEqual(gap.missing_sessions(self.db, TODAY), [])


class CatchUpTests(GapCase):
    def now(self):
        return datetime(2026, 7, 27, 9, 0, tzinfo=TZ)

    def test_runs_the_official_updater_once_per_missing_day_in_historical_mode(self):
        missing = [self.sessions[3], self.sessions[10]]
        self.fill({d: 0 for d in missing})
        calls = []

        def run(db, **kwargs):
            calls.append((db, kwargs))
            return {'ok': True, 'status': '已更新', 'failures': []}

        result = gap.catch_up(self.db, self.now(), run=run)
        self.assertEqual([c[1]['start'] for c in calls], missing)
        for (_, kwargs), day in zip(calls, missing):
            self.assertTrue(kwargs['historical'])
            self.assertEqual(kwargs['now'], datetime(day.year, day.month, day.day, 23, 0, tzinfo=TZ))
        self.assertEqual(result['remaining'], 0)
        self.assertEqual(result['missing'], [d.isoformat() for d in missing])

    def test_stops_after_the_first_failure_and_reports_what_remains(self):
        missing = [self.sessions[2], self.sessions[6], self.sessions[9]]
        self.fill({d: 0 for d in missing})
        outcomes = iter([{'ok': True, 'status': '已更新'}, {'ok': False, 'status': '資料不完整', 'failures': [{'reason': 'x'}]}])
        calls = []

        def run(db, **kwargs):
            calls.append(kwargs['start'])
            return next(outcomes)

        result = gap.catch_up(self.db, self.now(), run=run)
        self.assertEqual(calls, missing[:2])
        self.assertEqual(result['remaining'], 2)
        self.assertFalse(result['attempted'][1]['ok'])

    def test_limit_bounds_the_number_of_days_per_run(self):
        missing = self.sessions[1:8]
        self.fill({d: 0 for d in missing})
        calls = []
        gap.catch_up(self.db, self.now(), limit=3, run=lambda db, **kw: calls.append(kw['start']) or {'ok': True})
        self.assertEqual(calls, missing[:3])

    def test_nothing_to_do_makes_no_source_request(self):
        self.fill({})
        gap.catch_up(self.db, self.now(), run=lambda *a, **k: self.fail('沒有缺口時不得呼叫來源'))


class HistoricalRunUpdateTests(unittest.TestCase):
    """run_update(historical=True)：補較早的日子，不得動到每日更新狀態、研究觀察與公司行動核對。"""

    def setUp(self):
        from tests.test_台股日線 import DatabaseCase
        self.case = DatabaseCase('setUp')
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown()

    def test_backfills_an_older_day_without_side_effects(self):
        case, db = self.case, self.case.db
        daily.run_update(db, start=date(2026, 9, 10), now=datetime(2026, 9, 13, 8, tzinfo=TZ), fetch=case.fetch)
        with closing(sqlite3.connect(db)) as conn:
            state_before = conn.execute('SELECT payload FROM daily_update_state WHERE id=1').fetchone()[0]
        with patch('突破影子紀錄.record_daily', side_effect=AssertionError('歷史回補不得新增研究觀察')):
            result = daily.run_update(db, start=date(2026, 9, 8), now=datetime(2026, 9, 8, 23, tzinfo=TZ),
                                      fetch=case.fetch, historical=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual([(r['exchange'], r['date']) for r in result['completedDays']],
                         [('TWSE', '2026-09-08'), ('TPEX', '2026-09-08')])
        self.assertEqual(result['researchShadow']['status'], '回補略過')
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT payload FROM daily_update_state WHERE id=1').fetchone()[0], state_before)
            self.assertEqual(conn.execute("SELECT COUNT(DISTINCT symbol) FROM bars WHERE ts=?", (daily.stamp(date(2026, 9, 8)),)).fetchone()[0], 1000)

    def test_a_failed_historical_day_is_reported_not_ok(self):
        case, db = self.case, self.case.db

        def broken(url):
            if 'tpex.org' in url and 'dailyQuotes' in url:
                raise TimeoutError('測試中斷')
            return case.fetch(url)

        result = daily.run_update(db, start=date(2026, 9, 8), now=datetime(2026, 9, 8, 23, tzinfo=TZ), fetch=broken, historical=True)
        self.assertFalse(result['ok'])
        self.assertTrue(result['failures'])


class ScheduleWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(datastore, 'DB_PATH', str(Path(self.temp.name) / 'market.db'))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_requires_the_owner_setting_and_submits_once_per_calendar_day(self):
        saturday = datetime(2026, 10, 24, 10, 0, tzinfo=TZ)        # 週六、窗口之外也要能補
        with patch.object(maintenance.job_queue, 'submit', return_value={'queued': True}) as submit, \
                patch.object(maintenance, 'start_daemon'):
            self.assertFalse(maintenance.catch_up_tick(saturday))
            submit.assert_not_called()
            maintenance.configure_schedule(True)
            self.assertTrue(maintenance.catch_up_tick(saturday))
            self.assertFalse(maintenance.catch_up_tick(saturday.replace(hour=11)))
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(submit.call_args.args[0], maintenance.GAP_JOB)
            self.assertTrue(maintenance.catch_up_tick(saturday + timedelta(days=1)))
            maintenance.configure_schedule(False)
            self.assertFalse(maintenance.catch_up_tick(saturday + timedelta(days=2)))

    def test_job_persists_a_visible_result_in_schedule_status(self):
        now = datetime(2026, 10, 28, 9, 0, tzinfo=TZ)
        summary = {'checkedAt': now.isoformat(), 'missing': ['2026-10-19'], 'attempted': [{'date': '2026-10-19', 'ok': True}], 'remaining': 0}
        with patch.object(gap, 'catch_up', return_value=summary), patch.object(maintenance, 'start_daemon'):
            maintenance.gap_catch_up_job(now)
            self.assertEqual(maintenance.schedule_status()['lastGapCatchUp'], summary)


if __name__ == '__main__':
    unittest.main()

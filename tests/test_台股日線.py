"""官方日線日期、缺值、原子匯入與事件統計的回歸驗證。"""
import copy
import json
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 台股日線 as daily
import K線事件 as events


def payload(exchange, day, count=500):
    fields = ['證券代號', '證券名稱', '開盤價', '最高價', '最低價', '收盤價', '成交股數'] if exchange == 'TWSE' else ['代號', '名稱', '開盤', '最高', '最低', '收盤', '成交股數']
    base = 1000 if exchange == 'TWSE' else 5000
    return {'stat': 'OK', 'date': day.strftime('%Y%m%d'), 'tables': [{'fields': fields, 'data': [[str(base + i), '測試股票', '100', '103', '99', '102', '1,000'] for i in range(count)]}]}


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'market.db'
        self.old_path = datastore.DB_PATH
        datastore.DB_PATH = str(self.db)
        datastore.init_db()

    def tearDown(self):
        datastore.DB_PATH = self.old_path
        self.temp.cleanup()

    def fetch(self, url):
        qs = parse_qs(urlparse(url).query)
        if 'holidaySchedule' in url:
            year = int(qs['date'][0][:4])
            return {'fields': ['日期', '名稱', '說明'], 'data': [[f'{year}-01-01', '元旦', '休市']]}, '曆'
        if 'FMTQIK' in url:
            day = datetime.strptime(qs['date'][0], '%Y%m%d').date()
            days = []
            while day.month == 9 and day <= date(2026, 9, 11):
                if day.weekday() < 5:
                    days.append([f'{day.year - 1911}/{day.month:02}/{day.day:02}'])
                day += timedelta(days=1)
            return {'stat': 'OK', 'date': qs['date'][0], 'fields': ['日期'], 'data': days}, '成交日'
        exchange = 'TWSE' if 'twse.com' in url else 'TPEX'
        day = date.fromisoformat(qs['date'][0].replace('/', '-')) if exchange == 'TPEX' else datetime.strptime(qs['date'][0], '%Y%m%d').date()
        return payload(exchange, day), '資料雜湊'

    def history(self, count=75):
        daily.save_calendar(self.db, 2026, set(), set())
        day, rows = date(2026, 6, 1), []
        while len(rows) < count:
            if day.weekday() < 5:
                rows.append((daily.stamp(day), 100, 101, 99, 100, 1000))
            day += timedelta(days=1)
        datastore.upsert_bars('2330', 'TW', rows, source='TWSE')
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)', ('TW', '2330', '2026-01-01', '2026-12-31', 'TWSE'))
        return rows

    def report(self, as_of='2026-09-11'):
        return events.report(self.db, '2330', as_of, datetime(2026, 9, 13, 8, tzinfo=daily.TZ))

    def test_missing_prices_are_not_fabricated_by_yahoo(self):
        response = {'chart': {'result': [{'timestamp': [1, 2], 'indicators': {'quote': [{'close': [100, float('nan')], 'open': [None, 1], 'high': [None, 1], 'low': [None, 1], 'volume': [None, 1]}]}}]}}
        from io import StringIO
        with patch('datastore.urllib.request.urlopen', return_value=StringIO(json.dumps(response))):
            rows = datastore.fetch_yahoo_daily('2330', 'TW')
        self.assertEqual(rows, [(1, None, None, None, 100, None)])

    def test_official_missing_values_and_zero_volume_remain(self):
        p = payload('TWSE', date(2026, 9, 11), 1)
        p['tables'][0]['data'][0][2] = '--'
        p['tables'][0]['data'][0][-1] = '0'
        rows = daily.parse_daily(p, 'TWSE', date(2026, 9, 11))
        self.assertIsNone(rows[0]['prices'][0])
        self.assertEqual(rows[0]['volume'], 0)
        self.assertEqual(len(rows[0]['issues']), 2)

    def test_wrong_date_and_duplicate_symbol_rejected(self):
        p = payload('TWSE', date(2026, 9, 10), 1)
        with self.assertRaises(ValueError):
            daily.parse_daily(p, 'TWSE', date(2026, 9, 11))
        p['tables'][0]['data'] *= 2
        with self.assertRaises(ValueError):
            daily.parse_daily(p, 'TWSE', date(2026, 9, 10))

    def test_atomic_rollback_and_us_identity_preserved(self):
        day = date(2026, 9, 11)
        rows = daily.parse_daily(payload('TWSE', day, 2), 'TWSE', day)
        datastore.upsert_bars('1000', 'US', [(daily.stamp(day), 5, 6, 4, 5, 20)])
        bad = copy.deepcopy(rows)
        bad[1]['symbol'] = None
        with self.assertRaises(sqlite3.IntegrityError):
            daily.import_day(self.db, 'TWSE', day, bad, '甲', min_rows=2)
        self.assertEqual(datastore.get_bars('1000', market='TW'), [])
        daily.import_day(self.db, 'TWSE', day, rows, '乙', min_rows=2)
        daily.import_day(self.db, 'TWSE', day, rows, '乙', min_rows=2)
        self.assertEqual(len(datastore.get_bars('1000', market='TW')), 1)
        self.assertEqual(datastore.get_bars('1000', market='US')[0][4], 5)

    def test_partial_market_payload_rejected(self):
        with self.assertRaises(ValueError):
            daily.import_day(self.db, 'TWSE', date(2026, 9, 11), [], '雜湊')

    def test_preferred_stocks_etfs_and_tdr_are_included_without_warrants(self):
        for code in ('2330', '2881A', '2882A', '2891B', '0050', '00403A', '910322'):
            self.assertIsNotNone(daily.CODE.fullmatch(code), code)
        self.assertIsNone(daily.CODE.fullmatch('030001'))

    def test_yahoo_cannot_replace_official_bar(self):
        row = (daily.stamp(date(2026, 9, 11)), 100, 102, 99, 101, 1000)
        datastore.upsert_bars('2330', 'TW', [row], source='TWSE')
        self.assertEqual(datastore.upsert_bars('2330', 'TW', [(row[0], 1, 1, 1, 1, 1)]), 0)
        self.assertEqual(datastore.upsert_bars('2330', 'TW', [(row[0] + 3600, 1, 1, 1, 1, 1)]), 0)
        self.assertEqual(datastore.get_bars('2330')[0], row)

    def test_official_seed_removes_same_session_legacy_timestamp(self):
        stamp = daily.stamp(date(2026, 9, 11))
        datastore.upsert_bars('2330', 'TW', [(stamp + 3600, 1, 1, 1, 1, 1)])
        official = (stamp, 100, 102, 99, 101, 1000)
        datastore.upsert_bars('2330', 'TW', [official], source='TWSE')
        self.assertEqual(datastore.get_bars('2330'), [official])

    def test_portfolio_preserves_return_dates_around_missing_close(self):
        from portfolio import _dated_rets, compute
        self.assertEqual(_dated_rets({1: 100, 2: None, 3: 110, 4: 121}, [1, 2, 3, 4]), {4: 121 / 110 - 1})
        rows = [(i, 100, 100, 100, 100 + i, 1000) for i in range(90)]
        missing = list(rows)
        missing[45] = (45, None, None, None, None, 0)
        with patch('datastore.get_bars_bulk', return_value={'2330': missing, '^TWII': rows}):
            result = compute([{'sym': '2330', 'weight': 1}])
        self.assertEqual(result['portfolio']['days'], 87)

    def test_actual_session_gap_survives_calendar_refresh(self):
        daily.save_calendar(self.db, 2026, set(), set())
        def fetch(url):
            return {'stat': 'OK', 'date': '20260701', 'fields': ['日期'], 'data': [['115/07/09'], ['115/07/13']]}, '雜湊'
        actual = daily.reconcile_sessions(self.db, date(2026, 7, 1), date(2026, 7, 13), fetch)
        self.assertNotIn(date(2026, 7, 10), actual)
        daily.save_calendar(self.db, 2026, set(), set())
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM market_sessions WHERE session_date='2026-07-10'").fetchone())

    def test_calendar_has_actual_year_and_open_days(self):
        def fetch(url):
            self.assertIn('date=20250101', url)
            return {'fields': ['日期', '名稱', '說明'], 'data': [['2025-01-01', '元旦', '休市'], ['2025-01-02', '開始交易', '']]}, ''
        closed, opened = daily.calendar(2025, fetch)
        self.assertEqual(closed, {date(2025, 1, 1)})
        self.assertEqual(opened, {date(2025, 1, 2)})

    def test_weekend_holiday_and_evening_cutoff(self):
        closed = {date(2026, 9, 11)}
        self.assertEqual(daily.latest_session(datetime(2026, 9, 14, 7, 30, tzinfo=daily.TZ), closed, set()), date(2026, 9, 10))
        self.assertEqual(daily.latest_session(datetime(2026, 9, 14, 18, tzinfo=daily.TZ), closed, set()), date(2026, 9, 14))

    def test_update_resumes_missing_day_and_is_idempotent(self):
        failed = False
        def unreliable(url):
            nonlocal failed
            if not failed and 'tpex.org' in url:
                failed = True
                raise TimeoutError('測試中斷')
            return self.fetch(url)
        now = datetime(2026, 9, 13, 8, tzinfo=daily.TZ)
        result = daily.run_update(self.db, start=date(2026, 9, 10), now=now, fetch=unreliable)
        self.assertFalse(result['ok'])
        result = daily.run_update(self.db, now=now, fetch=self.fetch)
        self.assertTrue(result['ok'])
        self.assertEqual([(r['exchange'], r['date']) for r in result['completedDays']], [('TPEX', '2026-09-10')])
        self.assertEqual(daily.run_update(self.db, now=now, fetch=self.fetch)['completedDays'], [])

    def test_many_stale_rows_do_not_mean_fresh(self):
        self.history()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            result = events.freshness(conn, '2330', datetime(2026, 9, 14, 8, tzinfo=daily.TZ))
        self.assertFalse(result['fresh'])
        self.assertEqual(result['expectedSession'], '2026-09-11')

    def test_missing_ohlc_never_becomes_doji(self):
        rows = self.history()
        t = rows[-1][0]
        datastore.upsert_bars('2330', 'TW', [(t, None, 101, 99, 100, 1000)], source='TWSE')
        record = next(r for r in self.report()['candles'] if r['time'] == t)
        self.assertEqual(record['signals'], [])
        self.assertFalse(record['eligible'])

    def test_legacy_quality_is_explicitly_unverified(self):
        self.history()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DELETE FROM bar_quality')
        result = self.report()
        self.assertEqual(result['eligibleDays'], 0)
        self.assertEqual(result['unverifiedRows'], 75)

    def test_exact_thresholds_and_current_bar_excluded(self):
        previous = [{'high': 102, 'low': 99, 'volume': 1000}] * 20
        keys, metrics = events.signals({'open': 100, 'close': 101.5, 'volume': 1500}, previous)
        self.assertEqual(keys, ['long_red'])
        keys, _ = events.signals({'open': 100, 'close': 100.2, 'volume': 1501}, previous)
        self.assertEqual(keys, ['doji', 'volume'])
        keys, _ = events.signals({'open': 101, 'close': 103, 'volume': 1000}, previous)
        self.assertIn('break_high', keys)
        self.assertEqual(metrics['volumeRatio'], 1.5)

    def test_maturity_is_per_horizon_and_asof_does_not_use_future(self):
        rows = self.history()
        asof = datetime.fromtimestamp(rows[-5][0], daily.TZ).date().isoformat()
        before = self.report(asof)
        latest = before['candles'][-1]
        self.assertIsNone(latest['returns']['1']['value'])
        self.assertIn('尚未', latest['returns']['1']['reason'])
        datastore.upsert_bars('2330', 'TW', [(rows[-1][0], 200, 201, 199, 200, 1000)], source='TWSE')
        self.assertEqual(before['stats'], self.report(asof)['stats'])
        doji = next(s for s in before['stats'] if s['key'] == 'doji')
        self.assertGreater(doji['horizons']['1']['raw']['n'], doji['horizons']['10']['raw']['n'])

    def test_missing_session_does_not_shift_forward_horizon(self):
        rows = self.history()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM bars WHERE symbol='2330' AND ts=?", (rows[-2][0],))
        result = self.report()
        prior = next(r for r in result['candles'] if r['time'] == rows[-3][0])
        self.assertIsNone(prior['returns']['1']['value'])
        self.assertIn('缺值', prior['returns']['1']['reason'])

    def test_corporate_action_crossing_excluded(self):
        rows = self.history()
        day = datetime.fromtimestamp(rows[-2][0], daily.TZ).date().isoformat()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO corporate_actions VALUES(?,?,?,?,?)', ('TW', '2330', day, '除權息', 'TWSE'))
        result = self.report()
        prior = next(r for r in result['candles'] if r['time'] == rows[-3][0])
        self.assertIn('公司行動', prior['returns']['1']['reason'])

    def test_nonoverlap_and_baseline_counts_are_visible(self):
        self.history()
        doji = next(s for s in self.report()['stats'] if s['key'] == 'doji')
        h = doji['horizons']['10']
        self.assertLess(h['nonOverlapping']['n'], h['raw']['n'])
        self.assertEqual(h['baseline']['n'], h['raw']['n'])
        self.assertEqual(h['difference'], 0)

    def test_company_action_coverage_not_advanced_on_failure(self):
        self.history()
        def fail(url):
            if 'change/' in url:
                raise TimeoutError('測試失敗')
            return {'stat': '很抱歉，沒有符合條件的資料!'}, ''
        with self.assertRaises(TimeoutError):
            daily.refresh_actions(self.db, '2330', date(2026, 9, 1), date(2026, 9, 11), fail)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(conn.execute('SELECT end_date FROM action_coverage').fetchone()[0], '2026-12-31')


if __name__ == '__main__':
    unittest.main()

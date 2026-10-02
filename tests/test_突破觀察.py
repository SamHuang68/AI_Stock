"""長期訊號與本機資料接合的獨立 fixtures；不連網。"""
import copy
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 台股日線 as daily
import 突破觀察 as observation
from 突破成交研究 import execution_outcome, net_return, build_execution

MID, YEAR = 'breakout_120_mid', 'breakout_252'


def fixture(count=300):
    rows, day = [], date(2025, 1, 6)
    while len(rows) < count:
        if day.weekday() < 5:
            rows.append({'date': day.isoformat(), 'open': 100, 'high': 100, 'low': 99,
                         'close': 100, 'volume': 1000, 'source': 'TWSE', 'issues': [], 'priceBasis': 'unadjusted'})
        day += timedelta(days=1)
    return rows


class 純研究測試(unittest.TestCase):
    def setUp(self):
        self.rows = fixture()
        self.args = {'calendar_years': {2025, 2026}, 'action_days': set(),
                     'action_coverage': ('2025-01-01', '2026-12-31', 'TWSE')}

    def calculate(self, **kwargs):
        return observation.build_research(self.rows, **(self.args | kwargs))

    def price(self, at, value, high=None):
        self.rows[at].update(open=value, close=value, high=high or value, low=value - 1)

    def test_嚴格突破與兩種窗口邊界(self):
        self.price(100, 100, 110)
        for at, price in ((254, 101), (255, 102), (256, 110), (257, 111)):
            self.price(at, price)
        r = self.calculate()['rows']
        self.assertEqual(r[254]['signals'], [MID])
        self.assertEqual(r[255]['signals'], [])
        self.assertTrue(r[256]['conditions'][MID])
        self.assertFalse(r[256]['conditions'][YEAR])
        self.assertEqual(r[257]['signals'], [YEAR])

    def test_不能用未知前日冒充首次成立(self):
        for at, price in ((252, 101), (253, 102), (254, 100), (255, 103)):
            self.price(at, price)
        r = self.calculate()['rows']
        self.assertTrue(r[252]['conditions'][YEAR])
        self.assertFalse(r[252]['eligible'][YEAR])
        self.assertEqual(r[253]['signals'], [])
        self.assertEqual(r[255]['signals'], [YEAR])

    def test_當日最高價不進比較且不更動輸入(self):
        self.price(299, 101, 130)
        before = copy.deepcopy(self.rows)
        r = self.calculate()['latest']
        self.assertEqual(r['metrics']['priorHigh252'], 100)
        self.assertEqual(r['signals'], [YEAR])
        self.assertEqual(before, self.rows)

    def test_缺日與未知公司行動不壓縮(self):
        self.rows[200]['issues'] = ['交易日資料缺漏']
        self.assertFalse(any(self.calculate()['latest']['eligible'].values()))
        self.rows[200]['issues'] = []
        self.assertFalse(any(self.calculate(action_coverage=None)['latest']['eligible'].values()))
        self.assertIn('公司行動', self.calculate(action_days={self.rows[200]['date']})['latest']['reason'][YEAR])

    def test_期間裁切不重發持續訊號(self):
        self.price(270, 101)
        self.price(271, 102)
        r = self.calculate(sample_start=271)
        self.assertEqual(next(s for s in r['stats'] if s['key'] == YEAR)['cases'], 0)

    def test_前253日摘要包含有效證據範圍(self):
        before = self.calculate()['latest']['inputDigest']
        self.price(45, 100, 110)
        self.assertEqual(before, self.calculate()['latest']['inputDigest'])
        self.price(46, 100, 110)
        self.assertNotEqual(before, self.calculate()['latest']['inputDigest'])

    def test_手算成本與訊號隔日開盤(self):
        rows = self.rows[:4]
        rows[1].update(open=110, high=113, close=112)
        rows[3].update(open=113, high=116, close=115)
        one = execution_outcome(rows, 0, 1, **self.args)
        self.assertEqual((one['entryDate'], one['exitDate']), (rows[1]['date'], rows[1]['date']))
        self.assertAlmostEqual(one['grossReturn'], 112 / 110 - 1)
        self.assertAlmostEqual(one['netReturn'], 111.72 / 110.275 - 1)
        self.assertAlmostEqual(net_return(110, 112, .005), 111.44 / 110.55 - 1)
        three = execution_outcome(rows, 0, 3, **self.args)
        self.assertAlmostEqual(three['grossReturn'], 115 / 110 - 1)
        self.assertEqual(three['exitDate'], rows[3]['date'])

    def test_尚未進場與未平倉不計零報酬(self):
        no_next = execution_outcome(self.rows[:1], 0, 1, **self.args)
        opened = execution_outcome(self.rows[:2], 0, 3, **self.args)
        self.assertEqual(no_next['positionStatus'], 'not_entered')
        self.assertEqual(opened['positionStatus'], 'open')
        self.assertEqual(opened['entryPrice'], 100)
        self.assertIsNone(opened['netReturn'])

    def test_停牌單價與缺nextbar不得順延(self):
        rows = self.rows[:4]
        rows[1].update(low=100)
        self.assertEqual(execution_outcome(rows, 0, 1, **self.args)['status'], 'excluded')
        rows[1].update(low=99)
        missing = execution_outcome([rows[0], rows[2], rows[3]], 0, 1, session_dates=[r['date'] for r in rows], **self.args)
        self.assertEqual(missing['status'], 'excluded')
        self.assertEqual(missing['entryDate'], rows[1]['date'])
        stopped = [{**rows[0], 'date': '2026-09-16'}, {**rows[1], 'date': '2026-09-17'}]
        self.assertEqual(execution_outcome(stopped, 0, 1, symbol='1441', **self.args)['status'], 'excluded')

    def test_固定切分不使用跨界交易(self):
        rows = [{**r, 'date': d, 'research': {'eligible': {YEAR: True}, 'signals': [YEAR]}}
                for r, d in zip(self.rows, ['2023-12-28', '2023-12-29', '2024-01-02', '2024-01-03'])]
        result = build_execution(rows, symbol='2330', calendar_years={2023, 2024}, action_days=set(),
                                 action_coverage=('2023-01-01', '2024-12-31', 'TWSE'))
        h = next(r for r in result['rules'] if r['key'] == YEAR)['horizons']['1']['fixedSplit']
        self.assertEqual((h['train']['n'], h['test']['n'], h['boundaryExcluded']), (1, 1, 1))
        self.assertFalse(h['tunedOnTest'])


class 本機資料契約測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / '研究.db'
        datastore.init_db(self.db)
        daily.save_calendar(self.db, 2025, set(), set())
        self.days = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)]
        for symbol in ('2330', '0050'):
            datastore.upsert_bars(symbol, 'TW', [(daily.stamp(d), 100, 101, 99, 100, 1000) for d in self.days], source='TWSE', path=self.db)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            for symbol in ('2330', '0050'):
                conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)', ('TW', symbol, '2025-01-01', '2025-12-31', 'TWSE除權息'))

    def load(self, symbol='2330'):
        with datastore.read_snapshot(self.db) as conn:
            return observation.load_dataset(conn, symbol, '2025-01-08')

    def test_既有原始價格基準明確正規化(self):
        result = self.load()
        self.assertEqual(result['rows'][0]['priceBasis'], 'unadjusted')
        self.assertEqual(result['rows'][0]['issues'], [])
        self.assertEqual(result['rows'][0]['sourceDate'], '2025-01-06')

    def test_個股與基準及市場表共同缺日仍保留(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DELETE FROM bars WHERE ts=?', (daily.stamp(self.days[1]),))
            conn.execute("DELETE FROM market_sessions WHERE session_date='2025-01-07'")
        own, etf = self.load(), self.load('0050')
        self.assertEqual(own['session_dates'], ['2025-01-06', '2025-01-07', '2025-01-08'])
        self.assertIsNone(own['rows'][1]['close'])
        self.assertIsNone(etf['rows'][1]['close'])

    def test_ETF不冒用股票涵蓋(self):
        self.assertIsNone(self.load('0050')['action_coverage'])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE action_coverage SET source='TWSE ETF分割及除權息' WHERE symbol='0050'")
        self.assertEqual(self.load('0050')['action_coverage_kind'], 'etf')

    def test_官方來源日期錯誤即封鎖(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bar_quality SET session_date='2025-01-05' WHERE symbol='2330'")
        self.assertIn('官方來源日期與行情日期不一致', self.load()['rows'][0]['issues'])

    def test_缺資料回傳可操作狀態且唯讀不建表(self):
        before = self.db.read_bytes()
        result = observation.report(self.db, '9999', '2025-01-08', datetime(2025, 1, 8, 18, tzinfo=daily.TZ))
        self.assertIsNone(result['research']['latest'])
        self.assertTrue(result['missingData'])
        self.assertEqual(before, self.db.read_bytes())


if __name__ == '__main__':
    unittest.main()

"""官方日線研究標籤的完整資料庫驗證；不連網、不修改執行資料。"""
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 台股日線 as daily
import K線事件 as events


MID = 'breakout_120_mid'
YEAR = 'breakout_252'
REPAIR = 'repair_risk'
KEYS = (MID, YEAR, REPAIR)


class 突破觀察資料庫測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / '研究行情.db'
        self.old_db = datastore.DB_PATH
        datastore.DB_PATH = str(self.db)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(setattr, datastore, 'DB_PATH', self.old_db)
        datastore.init_db()
        self.days = []

    def history(self, count=300):
        day = date(2025, 1, 6)
        while len(self.days) < count:
            if day.weekday() < 5:
                self.days.append(day)
            day += timedelta(days=1)
        for year in range(self.days[0].year, self.days[-1].year + 1):
            daily.save_calendar(self.db, year, set(), set())
        datastore.upsert_bars('2330', 'TW', [
            (daily.stamp(d), 100, 100, 99, 100, 1000) for d in self.days
        ], source='TWSE')
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)', (
                'TW', '2330', self.days[0].isoformat(), self.days[-1].isoformat(), 'TWSE'))

    def price(self, index, close, *, high=None):
        high = close if high is None else high
        datastore.upsert_bars('2330', 'TW', [
            (daily.stamp(self.days[index]), close, high, close - 1, close, 1000)
        ], source='TWSE')

    def report(self, *, end=None, start=None, now=None):
        end = self.days[-1] if end is None else end
        now = now or datetime.combine(end, datetime.min.time(), daily.TZ).replace(hour=18)
        return events.report(self.db, '2330', end.isoformat(), now,
                             period='all' if start is None else 'custom',
                             start_date=start.isoformat() if start else None)

    def at(self, report, index):
        return next(r for r in report['candles'] if r['date'] == self.days[index].isoformat())

    def test_120日與252日等號邊界不同(self):
        self.history()
        self.price(100, 100, high=110)
        self.price(254, 101)
        self.price(255, 102)
        self.price(256, 110)
        self.price(257, 111)
        report = self.report()
        self.assertFalse(self.at(report, 253)['research']['conditions'][MID])
        self.assertEqual(self.at(report, 254)['research']['signals'], [MID])
        self.assertEqual(self.at(report, 255)['research']['signals'], [])
        equal_year = self.at(report, 256)['research']
        self.assertTrue(equal_year['conditions'][MID])
        self.assertFalse(equal_year['conditions'][YEAR])
        above_year = self.at(report, 257)['research']
        self.assertFalse(above_year['conditions'][MID])
        self.assertEqual(above_year['signals'], [YEAR])

    def test_參考高點排除當日最高價(self):
        self.history()
        self.price(100, 100, high=110)
        self.price(299, 101, high=130)
        latest = self.at(self.report(), 299)['research']
        self.assertEqual(latest['metrics']['priorHigh120'], 100)
        self.assertEqual(latest['metrics']['priorHigh252'], 110)
        self.assertEqual(latest['signals'], [MID])

    def test_首次需前日已知且連續突破不重複(self):
        self.history()
        self.price(252, 101)
        self.price(253, 102)
        self.price(254, 100)
        self.price(255, 103)
        self.price(256, 104)
        report = self.report()
        unknown = self.at(report, 252)['research']
        self.assertTrue(unknown['conditions'][YEAR])
        self.assertFalse(unknown['eligible'][YEAR])
        self.assertEqual(unknown['signals'], [])
        self.assertIn('前一', unknown['reason'][YEAR])
        self.assertTrue(self.at(report, 253)['research']['eligible'][YEAR])
        self.assertEqual(self.at(report, 253)['research']['signals'], [])
        self.assertEqual(self.at(report, 255)['research']['signals'], [YEAR])
        self.assertEqual(self.at(report, 256)['research']['signals'], [])

    def test_未滿252日仍保留原20日事件與統計(self):
        self.history(80)
        report = self.report()
        latest = self.at(report, 79)
        self.assertTrue(latest['eligible'])
        self.assertEqual(latest['signals'], ['doji'])
        self.assertEqual(report['eligibleDays'], 60)
        self.assertFalse(any(latest['research']['eligible'].values()))
        self.assertTrue(all(v is None for v in latest['research']['conditions'].values()))
        doji = next(s for s in report['stats'] if s['key'] == 'doji')
        self.assertEqual(doji['cases'], 60)
        self.assertEqual(doji['horizons']['10']['raw']['n'], 50)

    def test_缺交易日不可用跨缺口252筆替代(self):
        self.history(330)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM bars WHERE symbol='2330' AND ts=?", (daily.stamp(self.days[200]),))
        report = self.report()
        self.assertIsNone(self.at(report, 200)['time'])
        latest = self.at(report, 329)
        self.assertTrue(latest['eligible'])
        self.assertFalse(any(latest['research']['eligible'].values()))
        self.assertTrue(all(v is None for v in latest['research']['conditions'].values()))
        self.assertTrue(all('缺' in reason for reason in latest['research']['reason'].values()))

    def test_前一比較窗未知不能當作未成立(self):
        self.history(330)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM bars WHERE symbol='2330' AND ts=?", (daily.stamp(self.days[76]),))
        self.price(329, 101)
        latest = self.at(self.report(), 329)['research']
        self.assertTrue(latest['conditions'][YEAR])
        self.assertFalse(latest['eligible'][YEAR])
        self.assertEqual(latest['signals'], [])
        self.assertIn('前一', latest['reason'][YEAR])

    def test_公司行動污染長窗口但不誤停用乾淨20日(self):
        self.history()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO corporate_actions VALUES(?,?,?,?,?)', (
                'TW', '2330', self.days[200].isoformat(), '除權息', 'TWSE'))
        latest = self.at(self.report(), 299)
        self.assertTrue(latest['eligible'])
        self.assertFalse(any(latest['research']['eligible'].values()))
        self.assertTrue(all('公司行動' in reason for reason in latest['research']['reason'].values()))

    def test_公司行動涵蓋不足不認證252日(self):
        self.history()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('UPDATE action_coverage SET start_date=?', (self.days[200].isoformat(),))
        latest = self.at(self.report(), 299)
        self.assertTrue(latest['eligible'])
        self.assertFalse(any(latest['research']['eligible'].values()))
        self.assertTrue(all('公司行動' in reason for reason in latest['research']['reason'].values()))

    def test_未經官方核對的暖機不能參與研究(self):
        self.history()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM bar_quality WHERE symbol='2330' AND ts=?", (daily.stamp(self.days[150]),))
        latest = self.at(self.report(), 299)
        self.assertTrue(latest['eligible'])
        self.assertFalse(any(latest['research']['eligible'].values()))

    def test_未來日線不能改變過去判斷或統計(self):
        self.history()
        self.price(275, 101)
        cutoff = self.days[280]
        before = self.report(end=cutoff)
        self.price(281, 300)
        self.price(295, 1)
        after = self.report(end=cutoff)
        self.assertEqual(before['candles'], after['candles'])
        self.assertEqual(before['stats'], after['stats'])
        self.assertEqual(before['research'], after['research'])

    def test_週末沿用週五事件而不重新觸發(self):
        self.history()
        self.assertEqual(self.days[-1].weekday(), 4)
        self.price(299, 101)
        friday = self.report()
        sunday = self.days[-1] + timedelta(days=2)
        weekend = self.report(end=sunday)
        self.assertEqual(weekend['asOf'], self.days[-1].isoformat())
        self.assertEqual(weekend['candles'], friday['candles'])
        self.assertEqual(weekend['research'], friday['research'])
        self.assertEqual(weekend['research']['latest']['date'], self.days[-1].isoformat())

    def repair_history(self):
        self.history()
        for index, close in ((210, 125), (211, 115), (212, 105)):
            self.price(index, close)
        # 漸進上升至高點，避免被既有重大價格斷點防線排除。
        self.price(208, 110)
        self.price(209, 120)
        self.price(299, 106.25, high=130)

    def test_修復風險精確含20百分比回撤與15百分比距離等號(self):
        self.repair_history()
        latest = self.at(self.report(), 299)['research']
        self.assertTrue(latest['conditions'][REPAIR])
        self.assertIn(REPAIR, latest['signals'])
        self.assertEqual(latest['metrics']['priorHigh20'], 100)
        self.assertEqual(latest['metrics']['priorHigh252'], 125)
        self.assertAlmostEqual(latest['metrics']['distance252HighPct'], -15)

    def test_修復風險未達回撤或距離門檻均不成立(self):
        self.repair_history()
        self.price(299, 106.26)
        self.assertFalse(self.at(self.report(), 299)['research']['conditions'][REPAIR])
        self.price(299, 106.25)
        for i in range(213, 299):
            self.price(i, 100.01)
        self.assertFalse(self.at(self.report(), 299)['research']['conditions'][REPAIR])

    def test_研究期間與各規則統計母體一致且暖機不計入樣本(self):
        self.history()
        self.price(100, 100, high=110)
        for index, close in ((260, 101), (270, 102), (271, 103), (280, 104), (290, 105), (295, 111)):
            self.price(index, close)
        whole = self.report()
        limited = self.report(start=self.days[270])
        self.assertEqual(limited['historyStart'], self.days[270].isoformat())
        self.assertEqual(limited['timelineDays'], 30)
        self.assertEqual(limited['warmupDays'], 20)
        self.assertEqual(limited['research']['warmupDays'], 253)
        self.assertEqual(limited['candles'], [r for r in whole['candles'] if r['date'] >= self.days[270].isoformat()])
        stats = {s['key']: s for s in limited['research']['stats']}
        self.assertEqual(stats[MID]['cases'], 3)
        self.assertEqual(stats[YEAR]['cases'], 1)
        self.assertEqual(stats[REPAIR]['cases'], 0)
        self.assertEqual(next(s for s in whole['research']['stats'] if s['key'] == MID)['cases'], 4)
        for key in KEYS:
            with self.subTest(規則=key):
                self.assertEqual(stats[key]['eligibleDays'], 30)
                for horizon, count in ((1, 29), (3, 27), (5, 25), (10, 20)):
                    self.assertEqual(stats[key]['horizons'][str(horizon)]['baseline']['n'], count)
        mid_ten = stats[MID]['horizons']['10']
        self.assertEqual(mid_ten['raw']['n'], 2)
        self.assertEqual(mid_ten['nonOverlapping']['n'], 1)
        self.assertAlmostEqual(mid_ten['raw']['mean'], ((104 / 102 - 1) + (105 / 104 - 1)) * 50)
        self.assertEqual(stats[YEAR]['horizons']['3']['raw']['n'], 1)
        self.assertEqual(stats[YEAR]['horizons']['5']['raw']['n'], 0)
        self.assertEqual(stats[REPAIR]['horizons']['1']['raw']['n'], 0)
        self.assertIsNone(stats[REPAIR]['horizons']['1']['difference'])

    def test_開始日已持續成立不因裁切研究期間重發(self):
        self.history()
        self.price(270, 101)
        self.price(271, 102)
        result = self.report(start=self.days[271])
        first = result['candles'][0]['research']
        self.assertTrue(first['eligible'][YEAR])
        self.assertTrue(first['conditions'][YEAR])
        self.assertEqual(first['signals'], [])
        self.assertEqual(next(s for s in result['research']['stats'] if s['key'] == YEAR)['cases'], 0)

    def test_最新交易日缺資料保留缺口而不偽裝沿用前日(self):
        self.history()
        self.price(298, 101)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("DELETE FROM bars WHERE symbol='2330' AND ts=?", (daily.stamp(self.days[299]),))
        latest = self.report()['research']['latest']
        self.assertEqual(latest['date'], self.days[299].isoformat())
        self.assertIsNone(latest['close'])
        self.assertEqual(latest['signals'], [])
        self.assertFalse(any(latest['eligible'].values()))

    def test_研究基準排除公司行動污染的後續報酬(self):
        self.history()
        self.price(290, 101)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO corporate_actions VALUES(?,?,?,?,?)', (
                'TW', '2330', self.days[295].isoformat(), '除權息', 'TWSE'))
        stats = {s['key']: s for s in self.report()['research']['stats']}
        for key in KEYS:
            with self.subTest(規則=key):
                self.assertEqual(stats[key]['eligibleDays'], 42)
                for horizon, count in ((1, 41), (3, 39), (5, 37), (10, 32)):
                    self.assertEqual(stats[key]['horizons'][str(horizon)]['baseline']['n'], count)
        self.assertEqual(stats[YEAR]['cases'], 1)
        self.assertEqual(stats[YEAR]['horizons']['3']['raw']['n'], 1)
        self.assertEqual(stats[YEAR]['horizons']['5']['raw']['n'], 0)

    def test_跨年日曆缺核對不可壓縮成完整252日(self):
        self.history()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DELETE FROM calendar_years WHERE year=2025')
        latest = self.at(self.report(), 299)
        self.assertTrue(latest['eligible'])
        self.assertFalse(any(latest['research']['eligible'].values()))
        self.assertTrue(all('交易日曆' in reason for reason in latest['research']['reason'].values()))

    def test_輸入摘要包含前日判斷所需的第253日且排除更舊資料(self):
        self.history()
        before = self.report()['research']['latest']
        self.price(45, 100, high=110)
        outside = self.report()['research']['latest']
        self.assertEqual(before['inputDigest'], outside['inputDigest'])
        self.price(46, 100, high=110)
        revised = self.report()['research']['latest']
        self.assertEqual(before['conditions'], revised['conditions'])
        self.assertEqual(before['metrics'], revised['metrics'])
        self.assertNotEqual(before['inputDigest'], revised['inputDigest'])
        self.assertRegex(revised['inputDigest'], r'^[0-9a-f]{64}$')

    def test_讀取研究報告不改寫日線或其他資料表(self):
        self.history()
        with closing(sqlite3.connect(self.db)) as conn:
            before = list(conn.iterdump())
        self.report()
        self.report(start=self.days[280])
        with closing(sqlite3.connect(self.db)) as conn:
            after = list(conn.iterdump())
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()

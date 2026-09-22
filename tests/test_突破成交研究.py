"""成交與配對控制的獨立驗證；只使用暫存官方行情資料庫。"""
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
import copy
import random
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 台股日線 as daily
import K線事件 as events
import 突破成交研究 as execution

YEAR = 'breakout_252'
KEYS = ('breakout_120_mid', YEAR, 'repair_risk')


def trading_days(start, count):
    result = []
    while len(result) < count:
        if start.weekday() < 5:
            result.append(start)
        start += timedelta(days=1)
    return result


def group(result, horizon=1, key=YEAR):
    return next(rule for rule in result['rules'] if rule['key'] == key)['horizons'][str(horizon)]


def net(entry, exit_price, cost):
    return (exit_price * (1 - cost) / (entry * (1 + cost)) - 1) * 100


class 突破成交資料庫測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / '成交研究.db'
        self.old_db = datastore.DB_PATH
        datastore.DB_PATH = str(self.db)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(setattr, datastore, 'DB_PATH', self.old_db)
        datastore.init_db()
        self.days = trading_days(date(2025, 1, 6), 300)
        for year in {day.year for day in self.days}:
            daily.save_calendar(self.db, year, set(), set())
        for symbol, price in (('2330', 100), ('0050', 50)):
            datastore.upsert_bars(symbol, 'TW', [
                (daily.stamp(day), price, price + 1, price - 1, price, 1000) for day in self.days
            ], source='TWSE')
            with closing(sqlite3.connect(self.db)) as conn, conn:
                conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)', (
                    'TW', symbol, self.days[0].isoformat(), self.days[-1].isoformat(), 'TWSE'))

    def price(self, index, *, symbol='2330', opening=100, close=100, high=None, low=None, volume=1000):
        high = max(opening, close) + 1 if high is None else high
        low = min(opening, close) - 1 if low is None else low
        datastore.upsert_bars(symbol, 'TW', [
            (daily.stamp(self.days[index]), opening, high, low, close, volume)
        ], source='TWSE')

    def report(self, *, end=299, start=None, include_execution=True):
        day = self.days[end]
        now = datetime.combine(day, datetime.min.time(), daily.TZ).replace(hour=18)
        return events.report(self.db, '2330', day.isoformat(), now,
                             period='all' if start is None else 'custom',
                             start_date=self.days[start].isoformat() if start is not None else None,
                             include_execution=include_execution)

    def result(self, **kwargs):
        return self.report(**kwargs)['research']['execution']

    def trade(self, result, index=280, horizon=1):
        return next(item for item in group(result, horizon)['trades'] if item['signalDate'] == self.days[index].isoformat())

    def sql(self, query, params=()):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute(query, params)

    def signal(self, index=280, close=102):
        self.price(index, close=close)

    def test_隔日跳空採開盤成交且雙邊成本使用資金比率(self):
        self.signal()
        self.price(281, opening=110, close=112)
        trade = self.trade(self.result())
        self.assertEqual(trade['status'], 'mature')
        self.assertEqual(trade['entryDate'], self.days[281].isoformat())
        self.assertEqual(trade['exitDate'], self.days[281].isoformat())
        self.assertEqual(trade['entryPrice'], 110)
        self.assertEqual(trade['exitPrice'], 112)
        self.assertAlmostEqual(trade['gross'], (112 / 110 - 1) * 100)
        self.assertAlmostEqual(trade['baseNet'], net(110, 112, .0025))
        self.assertAlmostEqual(trade['stressNet'], net(110, 112, .005))
        self.assertNotAlmostEqual(trade['gross'], (112 / 102 - 1) * 100)

    def test_第三日出場從訊號日計數而非進場再加三日(self):
        self.signal()
        self.price(281, opening=104, close=103)
        self.price(283, close=106)
        self.price(284, close=107)
        trade = self.trade(self.result(), horizon=3)
        self.assertEqual(trade['exitDate'], self.days[283].isoformat())
        self.assertEqual(trade['exitPrice'], 106)
        self.assertAlmostEqual(trade['gross'], (106 / 104 - 1) * 100)

    def test_截至日之後的行情不能影響成交或隨機分布(self):
        self.signal()
        before = self.result(end=281)
        self.price(282, opening=10, close=11)
        self.price(295, opening=500, close=505)
        self.price(282, symbol='0050', opening=3, close=4)
        after = self.result(end=281)
        self.assertEqual(before, after)
        self.assertEqual(self.trade(after, horizon=1)['status'], 'mature')
        self.assertEqual(self.trade(after, horizon=3)['status'], 'immature')

    def test_期末事件未成熟不計零報酬(self):
        self.signal(index=299)
        result = self.result()
        for horizon in (1, 3, 5, 10):
            cell = group(result, horizon)
            self.assertEqual(self.trade(result, index=299, horizon=horizon)['status'], 'immature')
            self.assertEqual(cell['counts']['immature'], 1)
            self.assertEqual(cell['raw']['n'], 0)
            self.assertIsNone(cell['raw']['baseNet']['mean'])
            self.assertEqual(cell['benchmark']['pairedCount'], 0)

    def test_暖機期間訊號不列入成交或控制組筆數(self):
        self.signal(index=260, close=102)
        self.signal(index=290, close=104)
        result = self.result(start=280)
        rule = next(item for item in result['rules'] if item['key'] == YEAR)
        self.assertEqual(rule['signalCount'], 1)
        self.assertEqual([trade['signalDate'] for trade in group(result)['trades']], [self.days[290].isoformat()])
        self.assertEqual(group(result)['random']['n'], 1)

    def test_研究讀取不改寫任何資料表(self):
        self.signal()
        with closing(sqlite3.connect(self.db)) as conn:
            before = list(conn.iterdump())
        self.result()
        self.result(start=280)
        with closing(sqlite3.connect(self.db)) as conn:
            after = list(conn.iterdump())
        self.assertEqual(before, after)

    def test_個股與0050共用讀取快照而下次研究才看見並行更新(self):
        self.signal()
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower(), 'wal')
        original_read = events._read_bars
        committed = []

        def read_then_update(conn, symbol, cutoff):
            actual = original_read(conn, symbol, cutoff)
            if symbol == '2330':
                # 在個股已讀取、0050 尚未讀取之間，以真實第二條連線提交更新。
                with closing(sqlite3.connect(self.db, timeout=3)) as writer, writer:
                    writer.execute("UPDATE bars SET close=55,high=56 WHERE market='TW' AND symbol='0050' AND ts=?",
                                   (daily.stamp(self.days[281]),))
                with closing(sqlite3.connect(self.db)) as witness:
                    committed.append(witness.execute("SELECT close FROM bars WHERE symbol='0050' AND ts=?",
                                                     (daily.stamp(self.days[281]),)).fetchone()[0])
            return actual

        with patch.object(events, '_read_bars', side_effect=read_then_update):
            current = self.trade(self.result())['benchmark']
        self.assertEqual(committed, [55])
        self.assertEqual(current['status'], 'mature')
        self.assertEqual(current['entryPrice'], 50)
        self.assertEqual(current['exitPrice'], 50)
        self.assertAlmostEqual(current['gross'], 0)
        following = self.trade(self.result())['benchmark']
        self.assertEqual(following['status'], 'mature')
        self.assertEqual(following['exitPrice'], 55)
        self.assertAlmostEqual(following['gross'], 10)

    def test_影子紀錄省略成交研究但保留第一階段完全一致(self):
        self.signal()
        complete = self.report()
        expected = copy.deepcopy(complete)
        expected['research'].pop('execution')
        with patch.object(events, 'build_execution', side_effect=AssertionError('此路徑不應計算成交研究')):
            compact = self.report(include_execution=False)
        self.assertEqual(compact, expected)

    def test_進場日停牌缺資料不得跳至下一根日線(self):
        self.signal()
        self.sql("DELETE FROM bars WHERE symbol='2330' AND ts=?", (daily.stamp(self.days[281]),))
        trade = self.trade(self.result(), horizon=3)
        self.assertEqual(trade['status'], 'excluded')
        self.assertEqual(trade['entryDate'], self.days[281].isoformat())
        self.assertIsNone(trade['baseNet'])

    def test_持有區間缺交易日也不能壓縮時間軸(self):
        self.signal()
        self.sql("DELETE FROM bars WHERE symbol='2330' AND ts=?", (daily.stamp(self.days[282]),))
        result = self.result()
        self.assertEqual(self.trade(result, horizon=1)['status'], 'mature')
        self.assertEqual(self.trade(result, horizon=3)['status'], 'excluded')
        self.assertEqual(self.trade(result, horizon=3)['exitDate'], self.days[283].isoformat())

    def test_非官方成交資料不可進統計(self):
        self.signal()
        self.sql("UPDATE bar_quality SET source='YAHOO' WHERE symbol='2330' AND ts=?", (daily.stamp(self.days[281]),))
        self.assertEqual(self.trade(self.result())['status'], 'excluded')

    def test_公司行動涵蓋不足排除未核對的出場(self):
        self.signal()
        self.sql("UPDATE action_coverage SET end_date=? WHERE symbol='2330'", (self.days[281].isoformat(),))
        result = self.result()
        self.assertEqual(self.trade(result, horizon=1)['status'], 'mature')
        self.assertEqual(self.trade(result, horizon=3)['status'], 'excluded')

    def test_持有跨公司行動不得把原始價格落差當損益(self):
        self.signal()
        self.sql('INSERT INTO corporate_actions VALUES(?,?,?,?,?)', ('TW', '2330', self.days[282].isoformat(), '股票分割', 'TWSE'))
        result = self.result()
        self.assertEqual(self.trade(result, horizon=1)['status'], 'mature')
        self.assertEqual(self.trade(result, horizon=3)['status'], 'excluded')

    def test_進場或出場一價日不能假設一定成交(self):
        self.signal()
        self.price(281, opening=100, close=100, high=100, low=100)
        self.assertEqual(self.trade(self.result(), horizon=3)['status'], 'excluded')
        self.price(281)
        self.price(283, opening=100, close=100, high=100, low=100)
        self.assertEqual(self.trade(self.result(), horizon=3)['status'], 'excluded')

    def test_0050缺資料時股票與指標只用相同配對樣本(self):
        self.signal(index=280, close=102)
        self.price(281, opening=104, close=105)
        self.signal(index=290, close=107)
        self.price(291, opening=109, close=108)
        self.price(291, symbol='0050', opening=51, close=52)
        self.sql("DELETE FROM bars WHERE symbol='0050' AND ts=?", (daily.stamp(self.days[281]),))
        cell = group(self.result())
        pair = cell['benchmark']
        self.assertEqual(cell['raw']['n'], 2)
        self.assertEqual(pair['eligibleStockCount'], 2)
        self.assertEqual(pair['pairedCount'], 1)
        self.assertEqual(pair['excludedCount'], 1)
        self.assertEqual(pair['stock']['n'], 1)
        self.assertEqual(pair['benchmark']['n'], 1)
        self.assertEqual(pair['excess']['n'], 1)
        self.assertAlmostEqual(pair['stock']['baseNet']['mean'], net(109, 108, .0025))
        self.assertAlmostEqual(pair['benchmark']['baseNet']['mean'], net(51, 52, .0025))
        self.assertAlmostEqual(pair['excess']['baseNet']['mean'], net(109, 108, .0025) - net(51, 52, .0025))

    def test_0050分割與缺涵蓋不得以零報酬補入配對(self):
        self.signal()
        self.sql('INSERT INTO corporate_actions VALUES(?,?,?,?,?)', ('TW', '0050', self.days[282].isoformat(), '股票分割', 'TWSE'))
        cell = group(self.result(), 3)
        self.assertEqual(cell['raw']['n'], 1)
        self.assertEqual(cell['benchmark']['pairedCount'], 0)
        self.assertEqual(cell['benchmark']['excludedCount'], 1)
        self.assertIsNone(cell['benchmark']['benchmark']['baseNet']['mean'])
        self.sql("DELETE FROM corporate_actions WHERE symbol='0050'")
        self.sql("DELETE FROM action_coverage WHERE symbol='0050'")
        pair = group(self.result())['benchmark']
        self.assertEqual(pair['pairedCount'], 0)
        self.assertIsNone(pair['excess']['baseNet']['mean'])


class 突破成交純計算測試(unittest.TestCase):
    def rows(self, *, count=18, signals=(0, 3), eligible=None):
        days = trading_days(date(2025, 12, 29), count)
        rows = []
        for i, day in enumerate(days):
            rows.append({'date': day.isoformat(), 'open': 100, 'high': 110, 'low': 90,
                         'close': 100 + i / 10, 'volume': 1000, 'source': 'TWSE', 'issues': [],
                         'research': {'eligible': {key: key == YEAR and (eligible is None or i in eligible) for key in KEYS},
                                      'signals': [YEAR] if i in signals else []}})
        return rows

    def compute(self, rows, **kwargs):
        return execution.build_execution(rows, symbol='2330', calendar_years={2025, 2026}, action_days=set(),
                                         action_coverage=(rows[0]['date'], rows[-1]['date'], 'TWSE'), **kwargs)

    def test_隨機同年份筆數且千次結果可重現而不污染全域亂數(self):
        rows = self.rows(signals=(0, 4))
        original = copy.deepcopy(rows)
        state = random.getstate()
        first = group(self.compute(rows))['random']
        second = group(self.compute(rows))['random']
        self.assertEqual(first, second)
        self.assertEqual(random.getstate(), state)
        self.assertEqual(rows, original)
        self.assertEqual(first['draws'], 1000)
        self.assertEqual(first['n'], 2)
        strata = {item['year']: item for item in first['yearStrata']}
        self.assertEqual(strata['2025']['signals'], 1)
        self.assertEqual(strata['2025']['candidates'], 3)
        self.assertEqual(strata['2026']['signals'], 1)
        self.assertEqual(strata['2026']['candidates'], 14)

    def test_隨機無放回且候選包含事件日(self):
        # 全部候選同時都是事件日。每輪無放回抽完候選，均值必須完全相同。
        rows = self.rows(signals=(0, 1, 2, 3, 4), eligible={0, 1, 2, 3, 4})
        cell = group(self.compute(rows))
        control = cell['random']
        expected = sum((rows[i + 1]['close'] / rows[i + 1]['open'] - 1) * 100 for i in range(5)) / 5
        self.assertEqual(control['n'], 5)
        self.assertEqual(sum(item['candidates'] for item in control['yearStrata']), 5)
        for key in ('p025', 'median', 'p975'):
            self.assertAlmostEqual(control['metrics']['gross'][key], expected)
        self.assertAlmostEqual(control['metrics']['gross']['signalMean'], expected)

    def test_非重疊依實際開盤至收盤持有區間(self):
        rows = self.rows(signals=(0, 2, 3))
        cell = group(self.compute(rows), 3)
        self.assertEqual(cell['counts']['mature'], 3)
        self.assertEqual(cell['counts']['nonOverlapping'], 2)
        self.assertEqual(cell['counts']['overlapExcluded'], 1)
        chosen = [trade['signalDate'] for trade in cell['trades'] if trade['nonOverlapping']]
        self.assertEqual(chosen, [rows[0]['date'], rows[3]['date']])

    def test_無事件不產生虛構平均值(self):
        cell = group(self.compute(self.rows(signals=())))
        self.assertEqual(cell['raw']['n'], 0)
        self.assertIsNone(cell['raw']['baseNet']['mean'])
        self.assertEqual(cell['benchmark']['pairedCount'], 0)


if __name__ == '__main__':
    unittest.main()

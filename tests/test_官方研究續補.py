"""官方研究日常續補的選擇、月份、證據沿用及共用預算；禁止連外。"""
from contextlib import closing
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import datastore
import 官方研究續補 as extension
from 公司行動更新 import PARSER_VERSION, ensure_action_schema
from 台股日線 import TZ, stamp


class 官方研究續補測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'market.db'
        datastore.init_db(self.db)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            ensure_action_schema(conn)
        self.now = datetime(2026, 10, 14, 19, tzinfo=TZ)
        self.days = ['2026-09-30', '2026-10-13', '2026-10-14']
        self.ready = set()
        self.addCleanup(patch.stopall)
        patch.object(extension, 'verified_sessions', side_effect=lambda *a, **k: self.days).start()
        patch.object(extension, 'trading_status', return_value=None).start()
        patch.object(extension, 'quality_evidence', side_effect=self.quality).start()
        patch('http_client.request', side_effect=AssertionError('續補契約測試不得連外')).start()

    def add(self, symbol='2330', *, first='2025-01-02', end='2026-10-14', coverage_start='2025-01-01', parser=PARSER_VERSION):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO action_price_coverage VALUES(?,?,?,?,?,?)',
                         ('TW', symbol, coverage_start, end, parser, '[]'))
            conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)',
                         (symbol, 'TW', stamp(date.fromisoformat(first)), 100, 101, 99, 100, 1000))

    def quality(self, conn, symbol, **kwargs):
        return {day: {'officialPrices': {'status': 'verified', 'receiptIds': ['原始收據']},
                      'rawPresent': True, 'receiptComplete': True,
                      'priceConflict': True, 'volumeConflict': True}
                for day in self.days if (symbol, day) in self.ready}

    def make_ready(self, symbol):
        self.ready.update((symbol, day) for day in self.days)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('UPDATE action_price_coverage SET end_date=? WHERE symbol=?',
                         (self.now.date().isoformat(), symbol))

    def seed(self, db, symbol, **kwargs):
        self.make_ready(symbol)
        return {'quality': {'conflicts': 1}, 'qualityComplete': False,
                'fetchedMonths': ['2026-10'], 'reusedMonths': []}

    def run_refresh(self, **kwargs):
        return extension.refresh(self.db, self.now.date().isoformat(), now=self.now, **kwargs)

    def test_只選已有官方完整起點及正確解析版本的股票(self):
        self.add()
        self.add('0050', coverage_start='2025-02-01')
        self.add('2317', parser='舊解析器')
        self.add('00631L')
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)',
                         ('2454', 'TW', stamp(date(2025, 1, 2)), 100, 101, 99, 100, 1000))
        self.assertEqual([row['symbol'] for row in extension._candidates(self.db)], ['2330'])

    def test_同日兩種涵蓋完整零來源請求且不改量價品質(self):
        self.add()
        self.make_ready('2330')
        with patch.object(extension, 'seed_research', side_effect=AssertionError('完整涵蓋不得重抓')):
            result = self.run_refresh()
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['results']['2330']['reused'])
        self.assertEqual(result['sourceRequests'], 0)
        self.assertTrue(self.quality(None, '2330')['2026-10-14']['priceConflict'])

    def test_actions已到當日仍補缺少的月收據並保留原品質結果(self):
        self.add()
        self.ready.update(('2330', day) for day in self.days[:-1])
        with patch.object(extension, 'seed_research', side_effect=self.seed) as seed:
            result = self.run_refresh()
        self.assertEqual(seed.call_args.kwargs['begin'], date(2026, 10, 1))
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(result['results']['2330']['seedQualityComplete'])
        self.assertEqual(result['results']['2330']['seedQuality']['conflicts'], 1)
        self.assertFalse(result['results']['2330']['reused'])

    def test_來源完成但最新收據仍缺不得標完成(self):
        self.add()
        self.ready.update(('2330', day) for day in self.days[:-1])
        with patch.object(extension, 'seed_research', return_value={'ok': True, 'qualityComplete': True}):
            result = self.run_refresh()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pendingSymbols'], ['2330'])
        self.assertEqual(result['results']['2330']['receiptMissingDates'], ['2026-10-14'])

    def test_日曆未知仍嘗試有界續補且補後再次核對(self):
        self.add()
        for after, expected in ((None, 'partial'), (self.days, 'completed')):
            with self.subTest(expected=expected), \
                    patch.object(extension, 'verified_sessions', side_effect=[None, after]), \
                    patch.object(extension, 'seed_research', side_effect=self.seed) as seed:
                result = self.run_refresh()
            seed.assert_called_once()
            self.assertEqual(seed.call_args.kwargs['begin'], date(2026, 9, 1))
            self.assertEqual(result['status'], expected)
            self.assertEqual(result['results']['2330']['calendarComplete'], after is not None)
            self.assertEqual(result['results']['2330']['complete'], after is not None)

    def test_跨年續補含前月與中間休市日不截短涵蓋(self):
        self.now = datetime(2027, 1, 4, 19, tzinfo=TZ)
        self.days = ['2026-12-30', '2027-01-04']
        self.add(end='2026-12-30')
        self.ready.add(('2330', self.days[0]))
        with patch.object(extension, 'seed_research', side_effect=self.seed) as seed:
            result = self.run_refresh()
        self.assertEqual(seed.call_args.kwargs['begin'], date(2026, 12, 1))
        self.assertEqual(result['status'], 'completed')
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT start_date,end_date FROM action_price_coverage').fetchone(),
                             ('2025-01-01', '2027-01-04'))

    def test_舊缺口超過前月當月維持待補且不掃歷史(self):
        self.add(end='2026-08-01')
        with patch.object(extension, 'seed_research') as seed:
            result = self.run_refresh()
        seed.assert_not_called()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pendingSymbols'], ['2330'])
        self.assertTrue(result['results']['2330']['blocked'])

    def test_共享有界預算與待補優先且逾時不另起第二份(self):
        self.add()
        self.add('0050')
        calls, budgets = [], []
        def seed(db, symbol, **kwargs):
            calls.append(symbol)
            budgets.append(kwargs['fetch'].__self__)
            self.assertIs(kwargs['check'].__self__, budgets[-1])
            if len(calls) == 2:
                raise TimeoutError('已達共用期限')
            return self.seed(db, symbol, **kwargs)
        with patch.object(extension, 'seed_research', side_effect=seed):
            result = self.run_refresh(previous_attempts={'2330': 99, '0050': 1}, previous_pending=['2330'])
        self.assertEqual(calls, ['2330', '0050'])
        self.assertIs(budgets[0], budgets[1])
        self.assertEqual(budgets[0].limit, 20)
        self.assertLessEqual(budgets[0].remaining(), 60)
        self.assertEqual(result['pendingSymbols'], ['0050'])
        self.assertEqual(result['status'], 'partial')

    def test_鎖被既有工作持有時不重入(self):
        self.add()
        with patch.object(extension, 'acquire_daemon_lock', return_value=None), \
                patch.object(extension, 'seed_research') as seed:
            result = self.run_refresh()
        seed.assert_not_called()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['sourceRequests'], 0)

    def test_禁止擴大預算及未收盤目標(self):
        for limits in ({'budget_seconds': 61}, {'request_limit': 21}, {'budget_seconds': 0}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                self.run_refresh(**limits)
        result = extension.refresh(self.db, '2026-10-14', now=self.now.replace(hour=14))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['sourceRequests'], 0)

    def test_每日入口重新查官方依賴並保留原五來源與快照(self):
        import 個股每日資料 as sources
        fixed = self.now
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed
        names = ['TWSE 日線', 'TPEx 日線', '大盤日線', '上市法人', '上櫃法人', '官方研究續補', '還原快照']
        previous = {'sessionDate': fixed.date().isoformat(), 'sources': [
            {'name': name, 'status': 'completed', 'result': {'receivedSymbols': ['2330']}}
            for name in names]}
        previous['sources'][-2]['result'].update(attemptedAt={'2330': 1}, pendingSymbols=['2330'])
        (self.db.parent / 'stock_daily_sources.json').write_text(json.dumps(previous), encoding='utf-8')
        with patch.object(datastore, 'DB_PATH', str(self.db)), patch.object(sources, 'datetime', Clock), \
                patch.object(sources, 'session', return_value={'status': 'scheduled'}), \
                patch.object(datastore, 'list_symbols', return_value=['2330']), \
                patch.object(extension, 'refresh', return_value={'status': 'partial', 'pendingSymbols': ['2330']}) as refresh, \
                patch('個股還原研究.refresh_snapshots', return_value={'status': 'completed'}) as snapshots, \
                patch.object(sources.http_client, 'fetch_json', side_effect=AssertionError('已完成批次來源不得重抓')):
            result = sources.run()
        self.assertEqual([row['name'] for row in result['sources']], names)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(refresh.call_args.kwargs['previous_pending'], ['2330'])
        self.assertEqual(refresh.call_args.kwargs['previous_attempts'], {'2330': 1})
        snapshots.assert_called_once()


if __name__ == '__main__':
    unittest.main()

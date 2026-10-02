"""真實共用 loader 與 SQLite 快取整合；不替換來源介接、不呼叫遠端服務。"""
import importlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
portfolio = importlib.import_module('突破組合研究')
breakout = importlib.import_module('突破觀察')
execution = importlib.import_module('突破成交研究')
quality = importlib.import_module('daily_quality')

DAYS = ['2026-03-02', '2026-03-03', '2026-03-04', '2026-03-05', '2026-03-06',
        '2026-03-09', '2026-03-10', '2026-03-11', '2026-03-12', '2026-03-13']
CLOSES = [100, 100, 100, 102, 103, 104, 100, 99, 98, 100]
NOW = datetime(2026, 3, 13, 20, tzinfo=portfolio.TZ)
CONFIG = {'vidyaLength': 2, 'cmoLength': 1, 'warmupBars': 3,
          'initialCapital': 1000, 'allocationFraction': .5}


def timestamp(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=portfolio.TZ).timestamp())


def create_cache(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(quality.SCHEMA)
        conn.executescript('''
            CREATE TABLE bars(symbol TEXT,market TEXT,ts INTEGER,open REAL,high REAL,
                              low REAL,close REAL,volume REAL,PRIMARY KEY(market,symbol,ts));
            CREATE TABLE meta(symbol TEXT,market TEXT,name TEXT,last_update INTEGER,
                              PRIMARY KEY(market,symbol));
        ''')
        conn.execute('INSERT INTO calendar_years VALUES(?,?,?,?)', (2026, '[]', '[]', NOW.isoformat()))
        conn.executemany('INSERT INTO market_sessions VALUES(?,?)', [(d, 'TWSE開休市') for d in DAYS])
        for exchange in ('TWSE', 'TPEX'):
            conn.execute('INSERT INTO daily_imports VALUES(?,?,?,?,?)',
                         (exchange, DAYS[-1], 2, '整合測試來源雜湊', NOW.isoformat()))
        for symbol in ('2330', '0050'):
            conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)',
                         ('TW', symbol, DAYS[0], DAYS[-1], 'TWSE股票除權息'))
            conn.execute('INSERT INTO meta VALUES(?,?,?,?)', (symbol, 'TW', symbol, timestamp(DAYS[-1])))
            for day, close in zip(DAYS, CLOSES):
                op = 100 if day == DAYS[4] else close
                conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)',
                             (symbol, 'TW', timestamp(day), op, max(op, close) + 1, min(op, close) - 1, close, 1000))
                conn.execute('INSERT INTO bar_quality VALUES(?,?,?,?,?,?,?,?,?,?)',
                             ('TW', symbol, timestamp(day), day, 'TWSE', '股', '原始價格', '[]', NOW.isoformat(), '整合測試來源雜湊'))


class RealLoaderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / '投組整合.sqlite'
        create_cache(self.path)

    def load(self, symbol='2330', cutoff=DAYS[-1]):
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            return breakout.load_dataset(conn, symbol, cutoff)

    def report(self, as_of=None):
        return portfolio.build_saved_portfolio(self.path, as_of=as_of, now=NOW, config=CONFIG)

    def test_shared_costs_and_actual_loader_keep_unadjusted_prices(self):
        data = self.load()
        self.assertEqual(data['rows'][4]['open'], 100)
        self.assertEqual(data['rows'][4]['close'], 103)
        self.assertEqual(data['rows'][4]['priceBasis'], 'unadjusted')
        self.assertEqual(portfolio.SCENARIOS, execution.SCENARIOS)
        self.assertAlmostEqual(execution.net_return(100, 105, .01), 103.95 / 101 - 1)
        report = portfolio.build_portfolio({'2330': data}, data['session_dates'], sample_start=3, config=CONFIG)
        result = report['rules'][0]['scenarios']['baseNet']
        self.assertEqual(result['status'], 'complete', result['decisionIssues'])
        self.assertEqual(result['trades'][0]['entryPrice'], 100)
        self.assertEqual(result['trades'][0]['shares'], 4)
        self.assertAlmostEqual(result['trades'][0]['entryCash'], 401)

    def test_saved_adapter_true_loader_is_readonly_and_etf_is_unknown(self):
        before = self.path.read_bytes()
        report = self.report()
        self.assertEqual(report['status'], 'limited', report)
        self.assertEqual(report['range']['start'], DAYS[3])
        self.assertEqual(report['range']['end'], DAYS[-1])
        result = report['rules'][0]['scenarios']['baseNet']
        self.assertIsNone(result['totalReturnPct'])
        self.assertIsNone(result['dailyExcessSharpe'])
        self.assertTrue(any('ETF' in issue['reason'] or '公司行動' in issue['reason'] for issue in result['decisionIssues']))
        self.assertEqual(self.path.read_bytes(), before)
        json.dumps(report, ensure_ascii=False, allow_nan=False)

    def test_common_missing_session_stays_in_curve(self):
        missing = DAYS[4]
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('DELETE FROM bars WHERE ts=?', (timestamp(missing),))
            conn.execute('DELETE FROM bar_quality WHERE session_date=?', (missing,))
            conn.execute('DELETE FROM market_sessions WHERE session_date=?', (missing,))
        data = self.load()
        self.assertIn(missing, data['session_dates'])
        row = next(r for r in data['rows'] if r['date'] == missing)
        self.assertIsNone(row.get('close'))
        report = self.report()
        result = report['rules'][0]['scenarios']['gross']
        self.assertIn(missing, [row['date'] for row in result['curve']])
        self.assertTrue(any(r['date'] == missing and r['kind'] == 'entry' for r in result['rejected']))
        self.assertIsNone(result['totalReturnPct'])

    def test_unverified_basis_and_source_date_are_not_upgraded(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE bar_quality SET price_basis=? WHERE symbol=? AND session_date=?',
                         ('未知', '2330', DAYS[3]))
            conn.execute('UPDATE bar_quality SET session_date=? WHERE symbol=? AND ts=?',
                         ('2026-03-08', '2330', timestamp(DAYS[4])))
        data = self.load()
        report = portfolio.build_portfolio({'2330': data}, data['session_dates'], sample_start=3, config=CONFIG)
        result = report['rules'][0]['scenarios']['gross']
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['totalReturnPct'])
        self.assertEqual(result['closedTrades'], 0)

    def test_tail_missing_preserves_expected_session_and_unknown_valuation(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('DELETE FROM bars WHERE ts=?', (timestamp(DAYS[-1]),))
            conn.execute('DELETE FROM bar_quality WHERE session_date=?', (DAYS[-1],))
            conn.execute('DELETE FROM market_sessions WHERE session_date=?', (DAYS[-1],))
        report = self.report()
        self.assertNotEqual(report['status'], 'unavailable', report)
        self.assertEqual(report['range']['end'], DAYS[-1])
        result = report['rules'][0]['scenarios']['baseNet']
        self.assertEqual(result['curve'][-1]['date'], DAYS[-1])
        self.assertIsNone(result['totalReturnPct'])

    def test_historical_cutoff_does_not_use_later_close_or_actions(self):
        before = self.report(as_of=DAYS[6])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE bars SET open=1000,high=1100,low=900,close=1000 WHERE ts>?', (timestamp(DAYS[6]),))
            conn.execute('INSERT INTO corporate_actions VALUES(?,?,?,?,?)', ('TW', '2330', DAYS[8], '分割', 'TWSE'))
        after = self.report(as_of=DAYS[6])
        self.assertEqual(before['inputDigest'], after['inputDigest'])
        self.assertEqual(before['rules'], after['rules'])
        self.assertEqual(before['assets'], after['assets'])

    def test_nonofficial_calendar_source_cannot_promote_a_session(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO market_sessions VALUES(?,?)', ('2026-03-07', '未知來源'))
        report = self.report()
        self.assertEqual(report['status'], 'unavailable')
        self.assertIn('日曆來源', report['reason'])


if __name__ == '__main__':
    unittest.main()

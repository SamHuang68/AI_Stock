"""第三階段跨模組契約：真實 SQLite 快照、價格基準及版本化證據。"""
from contextlib import closing
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 台股日線 as daily
import K線事件 as events
import 突破影子紀錄 as shadow

VERSION = 'twse-reference-ratio-v1'
ADJUSTED = 'breakout-observation-adjusted-v1'
ROUTES = ('exRight/TWT49U', 'reducation/TWTAUU', 'change/TWTB8U', 'split/TWTCAU')


class 第三階段整合測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / '研究整合.db'
        self.old_path = datastore.DB_PATH
        datastore.DB_PATH = str(self.db)
        self.addCleanup(setattr, datastore, 'DB_PATH', self.old_path)
        datastore.init_db()
        self.days = []
        day = date(2025, 1, 6)
        while len(self.days) < 300:
            if day.weekday() < 5:
                self.days.append(day)
            day += timedelta(days=1)
        self.now = datetime.combine(self.days[-1], datetime.min.time(), daily.TZ).replace(hour=18)
        for year in {d.year for d in self.days}:
            daily.save_calendar(self.db, year, set(), set())
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('UPDATE calendar_years SET refreshed_at=?', (self.now.isoformat(),))
            conn.executemany('INSERT INTO daily_imports VALUES(?,?,?,?,?)',
                             [(exchange, self.days[-1].isoformat(), 1, 'a' * 64, self.now.isoformat())
                              for exchange in ('TWSE', 'TPEX')])
        self.sources = [{'url': f'https://wwwc.twse.com.tw/rwd/zh/{route}', 'sourceHash': 'a' * 64,
                         'retrievedAt': self.now.isoformat(), 'stat': 'OK', 'route': route,
                         'start': f'{year}-01-01', 'end': f'{year}-12-31'}
                        for year in {d.year for d in self.days} for route in ROUTES]
        for symbol in ('2330', '0050'):
            rows = []
            for i, day in enumerate(self.days):
                close = 50 if symbol == '0050' else 100 if i < 100 else 90 if i < 280 else 94
                rows.append((daily.stamp(day), close, close + 1, close - 1, close, 10000))
            datastore.upsert_bars(symbol, 'TW', rows, source='TWSE')
            with closing(sqlite3.connect(self.db)) as conn, conn:
                conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)',
                             ('TW', symbol, self.days[0].isoformat(), self.days[-1].isoformat(), 'TWSE'))
                conn.execute('INSERT INTO action_price_coverage VALUES(?,?,?,?,?,?)',
                             ('TW', symbol, self.days[0].isoformat(), self.days[-1].isoformat(), VERSION,
                              json.dumps(self.sources)))
        action_day = self.days[100]
        self.payload = {'fields': ['資料日期', '股票代號', '權/息', '除權息前收盤價', '除權息參考價'],
                        'row': [f'{action_day.year - 1911}/{action_day.month:02}/{action_day.day:02}', '2330', '息', '100', '90'],
                        'request': {'start': '2025-01-01', 'end': '2025-12-31'}}
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO corporate_actions VALUES(?,?,?,?,?)',
                         ('TW', '2330', action_day.isoformat(), '除權息', 'TWSE'))
            conn.execute('INSERT INTO action_price_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         ('TW', '2330', action_day.isoformat(), '除權息', 100, 90, .9, 'supported', None,
                          'https://wwwc.twse.com.tw/rwd/zh/exRight/TWT49U', 'a' * 64, self.now.isoformat(),
                          VERSION, json.dumps(self.payload)))

    def report(self, **kwargs):
        return events.report(self.db, '2330', self.days[-1].isoformat(), self.now, period='all', **kwargs)

    def test_原始研究保留且調整訊號仍用原始成交價格(self):
        with closing(sqlite3.connect(self.db)) as conn:
            before = conn.execute('SELECT * FROM bars ORDER BY market,symbol,ts').fetchall()
        result = self.report()
        raw = result['research']
        self.assertEqual(raw['version'], 'breakout-observation-v1')
        self.assertEqual(raw['adjusted']['version'], ADJUSTED)
        row = next(r for r in result['candles'] if r['date'] == self.days[280].isoformat())
        self.assertFalse(row['research']['eligible']['breakout_252'])
        self.assertIn('breakout_252', row['adjustedResearch']['signals'])
        group = next(r for r in raw['adjusted']['execution']['rules'] if r['key'] == 'breakout_252')
        trade = group['horizons']['1']['trades'][0]
        self.assertEqual((trade['entryPrice'], trade['exitPrice']), (94, 94))
        self.assertEqual(trade['benchmark']['entryPrice'], 50)
        self.assertEqual(trade['benchmark']['exitPrice'], 50)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(before, conn.execute('SELECT * FROM bars ORDER BY market,symbol,ts').fetchall())

    def test_因子和日線使用真實並行提交的一致快照(self):
        original = events._read_bars
        committed = []
        def interleave(conn, symbol, cutoff):
            values = original(conn, symbol, cutoff)
            if symbol == '2330' and not committed:
                payload = json.loads(json.dumps(self.payload))
                payload['row'][-1] = '95'
                with closing(sqlite3.connect(self.db)) as writer, writer:
                    writer.execute("UPDATE action_price_evidence SET reference_price=95,factor=.95,payload_json=? WHERE symbol='2330'", (json.dumps(payload),))
                with closing(sqlite3.connect(self.db)) as observer:
                    committed.append(observer.execute('SELECT reference_price FROM action_price_evidence').fetchone()[0])
            return values
        with patch.object(events, '_read_bars', side_effect=interleave):
            current = self.report()
        following = self.report()
        self.assertEqual(committed, [95])
        current_row = next(r for r in current['candles'] if r['date'] == self.days[280].isoformat())
        next_row = next(r for r in following['candles'] if r['date'] == self.days[280].isoformat())
        self.assertTrue(current_row['adjustedResearch']['conditions']['breakout_252'])
        self.assertFalse(next_row['adjustedResearch']['conditions']['breakout_252'])

    def test_舊資料庫可唯讀回應而不建立新表(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DROP TABLE action_price_evidence')
            conn.execute('DROP TABLE action_price_coverage')
        digest = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = self.report(include_execution=False)
        self.assertTrue(all(s['eligibleDays'] == 0 for s in result['research']['adjusted']['stats']))
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), digest)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='action_price_evidence'").fetchone())

    def test_錯誤價格基準不得作為原始成交價格(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bar_quality SET price_basis='未知調整價格' WHERE symbol='2330' AND ts=?", (daily.stamp(self.days[281]),))
        result = self.report()
        group = next(r for r in result['research']['adjusted']['execution']['rules'] if r['key'] == 'breakout_252')
        trade = group['horizons']['1']['trades'][0]
        self.assertEqual(trade['status'], 'excluded')
        self.assertIsNone(trade['entryPrice'])
        self.assertIn('原始價格基準', trade['reason'])

    def test_兩種版本各留首次證據且讀取不寫入(self):
        result = self.report(include_execution=False)
        adjusted_result = {**result, 'research': result['research']['adjusted']}
        self.assertTrue(shadow.append_observation(self.db, result, self.now))
        self.assertTrue(shadow.append_observation(self.db, adjusted_result, self.now))
        self.assertFalse(shadow.append_observation(self.db, adjusted_result, self.now))
        self.assertEqual(shadow.summary(self.db, '2330', result['research'], result['asOf'])['count'], 1)
        self.assertEqual(shadow.summary(self.db, '2330', result['research']['adjusted'], result['asOf'])['count'], 1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM breakout_observations').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()

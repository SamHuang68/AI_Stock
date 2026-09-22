"""官方行動證據與月份回補的離線契約；只寫暫存資料庫。"""
import copy
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 台股日線 as daily


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode('utf-8')).hexdigest()


def source_data():
    # 2025 年官方欄名與已核對的 2330 除息、0050 分割數值；省略非必要展示欄位。
    return {
        'TWT49U': {'stat': 'OK', 'fields': ['資料日期', '股票代號', '除權息前收盤價', '除權息參考價', '權/息'],
                   'data': [['114年03月18日', '2330', '970.00', '965.49', '息']]},
        'TWTAUU': {'stat': 'OK', 'fields': ['恢復買賣日期', '股票代號', '停止買賣前收盤價格', '恢復買賣參考價'], 'data': []},
        'TWTB8U': {'stat': 'OK', 'fields': ['恢復買賣日期', '股票代號', '停止買賣前收盤價格', '恢復買賣參考價'], 'data': []},
        'TWTCAU': {'stat': 'OK', 'fields': ['恢復買賣日期', 'ETF代號', '分割(反分割)', '停止買賣前收盤價格', '恢復買賣參考價'],
                   'data': [['114/06/18', '0050', '分割', '188.65', '47.16']]},
    }


class EvidenceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / '證據.db'
        self.old_path = datastore.DB_PATH
        datastore.DB_PATH = str(self.db)
        datastore.init_db()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(setattr, datastore, 'DB_PATH', self.old_path)
        self.sources = source_data()
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        result = copy.deepcopy(self.sources[urlparse(url).path.rsplit('/', 1)[-1]])
        return result, digest(result)

    def refresh(self, symbol='2330', first=date(2025, 1, 1), end=date(2025, 12, 31)):
        return daily.refresh_actions(self.db, symbol, first, end, self.fetch)

    def rows(self, table):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute('SELECT * FROM ' + table)]


class EvidenceTests(EvidenceCase):
    def test_純息保存官方參考價與完整來源證據(self):
        self.assertEqual(self.refresh(), 1)
        row = self.rows('action_price_evidence')[0]
        self.assertEqual(row['status'], 'supported')
        self.assertEqual(row['previous_close'], 970)
        self.assertEqual(row['reference_price'], 965.49)
        self.assertAlmostEqual(row['factor'], 965.49 / 970)
        self.assertEqual(row['parser_version'], 'twse-reference-ratio-v1')
        payload = json.loads(row['payload_json'])
        self.assertEqual(payload['fields'], self.sources['TWT49U']['fields'])
        self.assertEqual(payload['row'], self.sources['TWT49U']['data'][0])
        self.assertEqual(payload['request'], {'start': '2025-01-01', 'end': '2025-12-31'})
        self.assertEqual(len(row['source_hash']), 64)
        sources = json.loads(self.rows('action_price_coverage')[0]['sources_json'])
        self.assertEqual(len(sources), 4)
        self.assertTrue(all(set(('url', 'sourceHash', 'retrievedAt', 'stat', 'start', 'end', 'route')) <= source.keys() for source in sources))

    def test_ETF分割使用捨入參考價比例且保留獨立來源(self):
        self.refresh('0050')
        row = self.rows('action_price_evidence')[0]
        self.assertEqual(row['kind'], 'ETF分割')
        self.assertEqual(row['status'], 'supported')
        self.assertAlmostEqual(row['factor'], 47.16 / 188.65)
        self.assertNotEqual(row['factor'], .25)
        self.assertIn('/split/TWTCAU?', row['source_url'])
        self.assertEqual(self.rows('corporate_actions')[0]['kind'], 'ETF分割')

    def test_反分割可建立比例而未知類型不可(self):
        row = self.sources['TWTCAU']['data'][0]
        row[2:] = ['反分割', '10', '100']
        self.refresh('0050')
        self.assertEqual(self.rows('action_price_evidence')[0]['factor'], 10)
        row[2] = '未知'
        self.refresh('0050')
        result = self.rows('action_price_evidence')[0]
        self.assertEqual(result['status'], 'unsupported')
        self.assertIsNone(result['factor'])

    def test_除權及權息混合保留事件但不放行(self):
        for event_type in ('權', '權息', '未知'):
            with self.subTest(event_type=event_type):
                self.sources['TWT49U']['data'][0][4] = event_type
                self.refresh()
                row = self.rows('action_price_evidence')[0]
                self.assertEqual(row['status'], 'unsupported')
                self.assertIsNone(row['factor'])
                self.assertTrue(row['reason'])

    def test_減資及面額變更不默認成一(self):
        self.sources['TWT49U']['data'] = []
        for route in ('TWTAUU', 'TWTB8U'):
            self.sources[route]['data'] = [['114/03/18', '2330', '100', '200']]
        self.refresh()
        rows = self.rows('action_price_evidence')
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['status'] == 'unsupported' and row['factor'] is None for row in rows))

    def test_零負值及缺值因子都不放行(self):
        for value in ('0', '-1', '--', 'NaN', 'Infinity'):
            with self.subTest(value=value):
                self.sources['TWT49U']['data'][0][3] = value
                self.refresh()
                row = self.rows('action_price_evidence')[0]
                self.assertEqual(row['status'], 'unsupported')
                self.assertIsNone(row['factor'])

    def test_第四來源失敗原始事件證據與兩種涵蓋都不前進(self):
        self.refresh()
        tables = ('corporate_actions', 'action_coverage', 'action_price_evidence', 'action_price_coverage')
        before = {table: self.rows(table) for table in tables}
        self.sources['TWT49U']['data'][0][3] = '960'
        self.sources['TWTCAU']['fields'].remove('ETF代號')
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(before, {table: self.rows(table) for table in tables})

    def test_空集合也保存四個來源證據(self):
        self.sources = {key: {'stat': '很抱歉，沒有符合條件的資料!'} for key in self.sources}
        self.assertEqual(self.refresh(), 0)
        self.assertEqual(self.rows('action_price_evidence'), [])
        self.assertEqual(len(json.loads(self.rows('action_price_coverage')[0]['sources_json'])), 4)

    def test_同類重複與超出日期整次拒絕(self):
        self.sources['TWT49U']['data'] *= 2
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(self.rows('action_price_coverage'), [])
        self.sources['TWT49U']['data'] = [['115/03/18', '2330', '970', '965.49', '息']]
        with self.assertRaises(ValueError):
            self.refresh()

    def test_缺來源雜湊不得建立涵蓋(self):
        with self.assertRaises(ValueError):
            daily.refresh_actions(self.db, '2330', date(2025, 1, 1), date(2025, 12, 31), lambda url: ({'stat': '很抱歉，沒有符合條件的資料!'}, ''))
        self.assertEqual(self.rows('action_price_coverage'), [])

    def test_空集合狀態不能掩蓋非空資料(self):
        self.sources['TWT49U']['stat'] = '很抱歉，沒有符合條件的資料!'
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(self.rows('action_price_coverage'), [])

    def test_同日不同事件全部保留供讀端拒絕(self):
        self.sources['TWTB8U']['data'] = [['114/03/18', '2330', '970', '97']]
        self.refresh()
        self.assertEqual(len(self.rows('corporate_actions')), 2)
        self.assertEqual(len(self.rows('action_price_evidence')), 2)

    def test_非連續涵蓋不跨越未查區間(self):
        self.sources = {key: {'stat': '很抱歉，沒有符合條件的資料!'} for key in self.sources}
        self.refresh(first=date(2025, 1, 1), end=date(2025, 1, 31))
        self.refresh(first=date(2025, 3, 1), end=date(2025, 3, 31))
        coverage = self.rows('action_price_coverage')[0]
        self.assertEqual((coverage['start_date'], coverage['end_date']), ('2025-03-01', '2025-03-31'))
        self.assertEqual(len(json.loads(coverage['sources_json'])), 4)


class MonthTests(EvidenceCase):
    def setUp(self):
        super().setUp()
        self.month_calls = []
        self.missing = '2025-09-15'
        self.bad_month = None
        self.fields = ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價']

    def month_fetch(self, url):
        qs = parse_qs(urlparse(url).query)
        if 'STOCK_DAY' in url:
            month = qs['date'][0]
            self.month_calls.append(month)
            begin = datetime.strptime(month, '%Y%m%d').date()
            end = min(date(2026, 9, 21), date(begin.year + (begin.month == 12), begin.month % 12 + 1, 1) - timedelta(days=1))
            rows = []
            day = begin
            while day <= end:
                if day.weekday() < 5 and day.isoformat() != self.missing:
                    rows.append([f'{day.year - 1911}/{day.month:02}/{day.day:02}', '1,000', '100,000', '100', '101', '99', '100'])
                day += timedelta(days=1)
            if month == self.bad_month:
                rows[-1][3] = '--'
            data = {'stat': 'OK', 'date': month, 'title': '0050 測試月份', 'fields': self.fields, 'data': rows}
        else:
            data = {'stat': '很抱歉，沒有符合條件的資料!'}
        return data, digest(data)

    def seed(self):
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 21, 18, tzinfo=daily.TZ)
        def calendar(db, year, fetch):
            daily.save_calendar(db, year, set(), set())
            return set(), set()
        with patch.object(daily, 'datetime', FixedDatetime), patch.object(daily, 'stored_calendar', calendar), patch.object(daily, 'reconcile_sessions', return_value=set()):
            return daily.seed_research(self.db, '0050', 1, fetch=self.month_fetch)

    def test_缺日保存收據但不冒充完整月份(self):
        first = self.seed()
        self.assertTrue(first['retrievalComplete'])
        self.assertFalse(first['dataComplete'])
        self.assertEqual(first['missingDates'], [self.missing])
        self.assertEqual(len(self.month_calls), 13)
        receipts = self.rows('research_month_receipts')
        self.assertEqual(len(receipts), 13)
        self.assertEqual(json.loads(receipts[0]['payload_json'])['missingDates'], [self.missing])
        self.month_calls.clear()
        again = self.seed()
        self.assertEqual(self.month_calls, ['20250901'])
        self.assertEqual(again['missingDates'], [self.missing])

    def test_首次缺日後官方補齊可恢復完整且後續跳過(self):
        self.seed()
        self.month_calls.clear()
        self.missing = None
        repaired = self.seed()
        self.assertEqual(self.month_calls, ['20250901'])
        self.assertTrue(repaired['dataComplete'])
        self.assertEqual(repaired['missingDates'], [])
        self.month_calls.clear()
        self.seed()
        self.assertEqual(self.month_calls, [])

    def test_收據不能掩蓋之後破壞的行情(self):
        self.seed()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bars SET close=NULL WHERE market='TW' AND symbol='0050' AND ts=?", (daily.stamp(date(2025, 9, 16)),))
        self.month_calls.clear()
        result = self.seed()
        self.assertEqual(self.month_calls, ['20250901'])
        self.assertEqual(result['missingDates'], [self.missing])

    def test_月末壞資料不留下該月前半段寫入(self):
        self.bad_month = '20250901'
        with self.assertRaises(ValueError):
            self.seed()
        self.assertEqual(self.rows('bars'), [])
        self.assertEqual(self.rows('research_month_receipts'), [])

    def test_日期重複錯月及未來列拒絕(self):
        month, target = date(2025, 9, 1), date(2025, 9, 2)
        row = ['114/09/01', '1000', '100000', '100', '101', '99', '100']
        for data_rows in ([row, row], [[*['114/10/01'], *row[1:]]], [[*['114/09/03'], *row[1:]]]):
            with self.subTest(data_rows=data_rows), self.assertRaises(ValueError):
                daily._research_month({'stat': 'OK', 'date': '20250901', 'fields': self.fields, 'data': data_rows}, '0050', month, target, {'2025-09-01', '2025-09-02'})

    def test_CLI可指定兩檔與五年並保留預設(self):
        with patch.object(sys, 'argv', ['日線', '--seed-research', '--symbols', '2330', '0050', '--years', '5']), patch.object(daily, 'seed_research', return_value={'ok': True}) as seed:
            self.assertEqual(daily.main(), 0)
            self.assertEqual([call.args[1:] for call in seed.call_args_list], [('2330', 5), ('0050', 5)])
        with patch.object(sys, 'argv', ['日線', '--seed-research']), patch.object(daily, 'seed_research', return_value={'ok': True}) as seed:
            self.assertEqual(daily.main(), 0)
            self.assertEqual(seed.call_args.args[1:], ('2330', 3))


if __name__ == '__main__':
    unittest.main()

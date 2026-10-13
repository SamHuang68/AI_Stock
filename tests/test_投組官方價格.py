"""完整官方參考價投組的來源、範圍及分割基準；不連外。"""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from tests.已核對資料 import 建立日曆, 交易日
from tests.test_日線分欄品質 import quality, datastore
import portfolio
import 公司行動更新 as actions
from 台股日線 import stamp


class 官方投組價格(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'market.db'
        datastore.init_db(self.db)
        self.days = 交易日('2025-01-02', 100)
        self.symbol = '2330'

    def seed(self, *, split=False, converted=False, raw_error=False):
        self.symbol = '0050' if split else '2330'
        self.rows = [(stamp(day), *((100 if i < 50 else 24.99 if split else 98),) * 4, 1000)
                     for i, day in enumerate(self.days)]
        original = list(self.rows)
        if converted:
            original[0] = (original[0][0], *(v / 4 for v in original[0][1:5]), original[0][5])
        if raw_error:
            original[0] = (original[0][0], 101, 101, 101, 101, 1000)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            建立日曆(conn, [2025])
            conn.executemany('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', [(self.symbol, 'TW', *r) for r in original])
            conn.executemany('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', [('^TWII', 'TW', stamp(d), 100+i, 100+i, 100+i, 100+i, 1000) for i, d in enumerate(self.days)])
        months = sorted({d.strftime('%Y%m') for d in self.days})
        for month in months:
            rows = [r for r in self.rows if datetime.fromtimestamp(r[0], quality.TAIPEI).strftime('%Y%m') == month]
            data = {'stat': 'OK', 'date': month+'01', 'title': f'{int(month[:4])-1911}年{month[4:]}月 {self.symbol} 測試資料',
                    'fields': quality.MONTH_FIELDS, 'notes': ['合成官方原始月回應'],
                    'data': [[datetime.fromtimestamp(r[0], quality.TAIPEI).strftime('114/%m/%d'), r[5], '100000', *r[1:5]] for r in rows]}
            raw = json.dumps(data, ensure_ascii=False)
            receipt = {'url': f'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={month}01&stockNo={self.symbol}',
                       'raw_text': raw, 'retrieved_at': '2025-12-31T12:00:00+00:00', 'parser_version': quality.RECEIPT_PARSER_VERSION}
            datastore.upsert_bars(self.symbol, 'TW', rows, source='TWSE', source_hash=hashlib.sha256(raw.encode()).hexdigest(), path=self.db, source_receipt=receipt)
        first, last = self.days[0], self.days[-1]
        def fetch(url):
            data = {'stat': '很抱歉，沒有符合條件的資料!'}
            route = '/split/' if split else '/exRight/'
            if route in url:
                fields = ['恢復買賣日期', 'ETF代號', '停止買賣前收盤價格', '恢復買賣參考價', '分割(反分割)'] if split else ['資料日期', '股票代號', '除權息前收盤價', '除權息參考價', '權/息']
                data = {'stat': 'OK', 'startDate': first.strftime('%Y%m%d'), 'endDate': last.strftime('%Y%m%d'), 'fields': fields,
                        'data': [[self.days[50].strftime('114/%m/%d'), self.symbol, '100', '24.99' if split else '98', '分割' if split else '息']]}
            return data, hashlib.sha256(json.dumps(data).encode()).hexdigest()
        actions.refresh_actions(self.db, self.symbol, first, last, fetch)
        self.original = original

    def result(self, *, split=False):
        refs = [{'date': self.days[50].isoformat(), 'ratio': 4, 'source': '合成官方分割公告'}] if split else []
        with patch.object(datastore, 'DB_PATH', str(self.db)), patch('投組官方價格.split_references', return_value=refs):
            result = portfolio.compute([{'sym': self.symbol, 'weight': 1}])
        return result

    def test_完整官方除息涵蓋產出風險且保留所有日期(self):
        self.seed()
        result = self.result()
        self.assertTrue(result['quality']['available'], result['quality'])
        self.assertEqual(result['portfolio']['days'], 99)
        self.assertEqual(result['portfolio']['vol'], 0)
        self.assertFalse(result['quality']['calendarPeriod']['startTrimmed'])
        detail = result['quality']['priceCoverage']['2330']
        self.assertEqual(detail['priceBasis'], 'twse-reference-comparison')
        self.assertEqual(detail['anchorDate'], self.days[-1].isoformat())
        self.assertEqual(detail['excludedDates'], [])
        with datastore.read_snapshot(self.db) as conn:
            values, issue = portfolio._risk_series(conn, self.symbol, self.original)
        self.assertIsNone(issue)
        self.assertEqual(len(values), 100)
        self.assertTrue(all(type(v) is float for v in values.values()))
        self.assertEqual(values[self.days[0].isoformat()], 98)

    def test_明示分割基準轉換保留原價且不混用股數比與參考價比(self):
        self.seed(split=True, converted=True)
        result = self.result(split=True)
        self.assertTrue(result['quality']['available'], result['quality'])
        detail = result['quality']['priceCoverage']['0050']
        self.assertEqual(detail['basisConversions'][0]['ratio'], 4)
        self.assertEqual(detail['adjustmentEvidence']['events'][0]['factor'], 24.99 / 100)
        self.assertEqual(result['portfolio']['vol'], 0)
        with datastore.read_snapshot(self.db) as conn:
            self.assertEqual(conn.execute("SELECT close FROM bars WHERE symbol='0050' ORDER BY ts LIMIT 1").fetchone()[0], 25)
            self.assertTrue(quality.quality_evidence(conn, '0050')[self.days[0].isoformat()]['priceConflict'])

    def test_未解釋的原價衝突仍拒絕(self):
        self.seed(raw_error=True)
        result = self.result()
        self.assertFalse(result['quality']['available'])
        self.assertIsNone(result['portfolio']['vol'])

    def test_第二官方原件整合保留原價與衝突證據(self):
        from 官方價格交叉核對 import save_receipt, VERSION
        self.seed(raw_error=True)
        day = self.days[0]
        data = {'stat': 'OK', 'date': day.strftime('%Y%m%d'), 'tables': [{
            'fields': ['證券代號', '開盤價', '最高價', '最低價', '收盤價'],
            'data': [['2330', '100', '100', '100', '100']]}]}
        raw = json.dumps(data, ensure_ascii=False)
        receipt = {'url': 'https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALLBUT0999&date='+data['date'],
                   'raw_text': raw, 'retrieved_at': '2025-12-31T12:00:00+00:00', 'parser_version': VERSION}
        with closing(sqlite3.connect(self.db)) as conn, conn:
            before = conn.execute('SELECT * FROM bars ORDER BY market,symbol,ts').fetchall()
            save_receipt(conn, '2330', hashlib.sha256(raw.encode()).hexdigest(), receipt)
        result = self.result()
        self.assertTrue(result['quality']['available'], result['quality'])
        self.assertEqual(result['portfolio']['days'], 99)
        self.assertEqual(result['quality']['priceCoverage']['2330']['reconciledPrices'][0]['date'], day.isoformat())
        with datastore.read_snapshot(self.db) as conn:
            self.assertEqual(conn.execute('SELECT * FROM bars ORDER BY market,symbol,ts').fetchall(), before)
            self.assertTrue(quality.quality_evidence(conn,'2330')[day.isoformat()]['priceConflict'])

    def test_損壞交叉原件只拒絕該股且保留具體原因(self):
        self.seed(raw_error=True)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE official_price_crosschecks(id TEXT,symbol TEXT,source_hash TEXT,receipt TEXT)')
            conn.execute("INSERT INTO official_price_crosschecks VALUES('x','2330','x','{}')")
        result = self.result()
        self.assertFalse(result['quality']['available'])
        self.assertNotIn('source', result['quality']['priceIssues'])
        self.assertIn('第二官方收據', result['quality']['priceCoverage']['2330']['officialRejectedReason'])

    def test_基準更早但持股完整日曆不可被連帶截斷(self):
        self.seed()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('^TWII','TW',stamp(date(2014,1,2)),90,90,90,90,1000))
        result = self.result()
        self.assertTrue(result['quality']['calendarPeriod']['startTrimmed'])
        self.assertTrue(result['quality']['available'], result['quality'])
        self.assertEqual(result['portfolio']['days'],99)

    def test_供應商缺最新日改用全段官方且保留錨點(self):
        self.seed()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE stock_adjustment_snapshots(market TEXT,symbol TEXT,fetched_at INTEGER,payload TEXT)')
            payload = {'rows': [{'date': d.isoformat(), 'rawClose': r[4], 'adjClose': r[4]} for d,r in zip(self.days[:-1],self.rows[:-1])], 'events': {}}
            conn.execute('INSERT INTO stock_adjustment_snapshots VALUES(?,?,?,?)', ('TW',self.symbol,1,json.dumps(payload)))
        result = self.result()
        self.assertTrue(result['quality']['available'], result['quality'])
        self.assertEqual(result['portfolio']['days'],99)
        detail = result['quality']['priceCoverage']['2330']
        self.assertEqual(detail['anchorDate'],self.days[-1].isoformat())
        self.assertIn('最新日線',detail['snapshotRejectedReason'])

    def test_缺任一日原始收據不可用舊品質標記替代(self):
        self.seed()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DELETE FROM official_daily_observations WHERE session_date=?', (self.days[10].isoformat(),))
        result = self.result()
        self.assertFalse(result['quality']['available'])
        self.assertIsNone(result['portfolio']['var95'])

    def test_缺日不得用相鄰官方前收略過(self):
        self.seed()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DELETE FROM bars WHERE symbol=? AND ts=?', (self.symbol, stamp(self.days[49])))
        self.assertFalse(self.result()['quality']['available'])

    def test_全歷史日曆或四類涵蓋缺口均拒絕(self):
        self.seed()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE action_price_coverage SET start_date='2025-01-03'")
        self.assertFalse(self.result()['quality']['available'])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE action_price_coverage SET start_date='2025-01-02',end_date='2025-05-01'")
        self.assertFalse(self.result()['quality']['available'])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE action_price_coverage SET end_date='2025-12-31'")
            conn.execute('DELETE FROM calendar_years')
        self.assertFalse(self.result()['quality']['available'])

    def test_拒絕的供應商衝突日使用完整官方基準而非刪日(self):
        self.seed()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE stock_adjustment_snapshots(market TEXT,symbol TEXT,fetched_at INTEGER,payload TEXT)')
            payload = {'rows': [{'date': d.isoformat(), 'rawClose': r[4]+1, 'adjClose': r[4]} for d,r in zip(self.days,self.rows)], 'events': {}}
            conn.execute('INSERT INTO stock_adjustment_snapshots VALUES(?,?,?,?)', ('TW',self.symbol,1,json.dumps(payload)))
        result = self.result()
        self.assertTrue(result['quality']['available'])
        self.assertEqual(result['portfolio']['days'],99)
        self.assertIn('衝突',result['quality']['priceCoverage']['2330']['snapshotRejectedReason'])


if __name__ == '__main__':
    unittest.main()

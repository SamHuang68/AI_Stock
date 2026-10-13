"""第二官方報表的窄收據與價格核對；固定原件、離線且不修改行情。"""
import copy
import hashlib
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import 官方價格交叉核對 as cross


class OfficialPriceCrosscheckTests(unittest.TestCase):
    def receipt(self, *, market=False, data=None, url=None, retrieved='2024-01-20T08:00:00+00:00', raw=None):
        if data is None:
            data = ({'stat': 'OK', 'date': '20240110', 'tables': [
                {'fields': ['證券代號', '開盤價', '最高價', '最低價', '收盤價'],
                 'data': [['0050', '90', '92', '89', '91'], ['2330', '100', '103', '99', '101']]}]}
                if market else {'stat': 'OK', 'date': '20240101', 'title': '113年01月 2330 台積電',
                    'fields': ['日期', '收盤價'], 'data': [['113/01/10', '101'], ['月平均收盤價', '101']]})
        text = raw if raw is not None else json.dumps(data, ensure_ascii=False, indent=2)
        receipt = {'url': url or ('https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date=20240110&type=ALLBUT0999'
                    if market else 'https://www.twse.com.tw/exchangeReport/STOCK_DAY_AVG?response=json&date=20240101&stockNo=2330'),
                   'retrieved_at': retrieved, 'raw_text': text, 'parser_version': cross.VERSION}
        return hashlib.sha256(text.encode('utf-8')).hexdigest(), receipt

    def proofs(self, prices):
        return {'2024-01-10': [{'id': '已保存收據', 'sourceHash': 'a' * 64,
                               'url': 'https://www.twse.com.tw/exchangeReport/MI_INDEX', 'prices': prices}]}

    def test_valid_month_close_preserves_exact_receipt_and_ignores_average_summary(self):
        digest, receipt = self.receipt()
        original = copy.deepcopy(receipt)
        self.assertEqual(cross.parse_receipt('2330', digest, receipt), {'2024-01-10': {'close': 101}})
        self.assertEqual(receipt, original)

    def test_valid_market_report_selects_exact_symbol_ohlc(self):
        digest, receipt = self.receipt(market=True)
        self.assertEqual(cross.parse_receipt('2330', digest, receipt),
                         {'2024-01-10': {'open': 100, 'high': 103, 'low': 99, 'close': 101}})

    def test_回應結構非物件即使雜湊自洽仍拒絕(self):
        for data in ([], None, '無效回應', 1, True):
            digest, receipt = self.receipt(raw=json.dumps(data, ensure_ascii=False))
            with self.subTest(回應=data), self.assertRaisesRegex(ValueError, '回應必須是物件'):
                cross.parse_receipt('2330', digest, receipt)

    def test_收據網址與取得時間必須是文字(self):
        digest, receipt = self.receipt()
        for key in ('url', 'retrieved_at'):
            for value in (None, [], {}, 1):
                with self.subTest(欄位=key, 內容=value), self.assertRaisesRegex(ValueError, '網址或取得時間格式無效'):
                    cross.parse_receipt('2330', digest, {**receipt, key: value})

    def test_月收盤資料列與日期型別無效均拒絕(self):
        _, receipt = self.receipt()
        original = json.loads(receipt['raw_text'])
        cases = [('資料非清單', value) for value in (None, {}, '無效資料', 1)]
        cases += [('列非清單', [value]) for value in (None, {}, '無效列', 1)]
        cases += [('日期非文字', [[value, '101']]) for value in (None, [], {}, 1)]
        for label, rows in cases:
            digest, item = self.receipt(data={**original, 'data': rows})
            with self.subTest(原因=label, 內容=rows), self.assertRaises(ValueError):
                cross.parse_receipt('2330', digest, item)

    def test_全市場表格欄位與資料列型別無效均拒絕(self):
        _, receipt = self.receipt(market=True)
        original = json.loads(receipt['raw_text'])
        table = original['tables'][0]
        cases = [('表格集合非清單', value) for value in (None, {}, '無效表格', 1)]
        cases += [('表格非物件', [value]) for value in (None, [], '無效表格', 1)]
        cases += [('欄位非文字清單', [{**table, 'fields': value}]) for value in (None, {}, '無效欄位', [None], [[]])]
        cases += [('資料非清單', [{**table, 'data': value}]) for value in (None, {}, '無效資料', 1)]
        cases += [('列非清單', [{**table, 'data': [value, *table['data']]}]) for value in (None, {}, '無效列', 1)]
        for label, tables in cases:
            digest, item = self.receipt(market=True, data={**original, 'tables': tables})
            with self.subTest(原因=label, 內容=tables), self.assertRaises(ValueError):
                cross.parse_receipt('2330', digest, item)

    def test_wrong_hash_route_host_version_and_duplicate_request_are_rejected(self):
        digest, receipt = self.receipt()
        variants = [('hash', '0' * 64, receipt),
                    ('route', digest, {**receipt, 'url': receipt['url'].replace('STOCK_DAY_AVG', 'STOCK_DAY')}),
                    ('host', digest, {**receipt, 'url': receipt['url'].replace('www.twse.com.tw', 'www.twse.com.tw.invalid')}),
                    ('version', digest, {**receipt, 'parser_version': '未知版本'}),
                    ('duplicate', digest, {**receipt, 'url': receipt['url'] + '&date=20240101'}),
                    ('response', digest, {**receipt, 'url': receipt['url'].replace('response=json', 'response=csv')})]
        for label, value, item in variants:
            with self.subTest(reason=label), self.assertRaises(ValueError):
                cross.parse_receipt('2330', value, item)

    def test_wrong_symbol_in_query_title_or_market_rows_is_rejected(self):
        for mode in ('query', 'title', 'market'):
            digest, receipt = self.receipt(market=mode == 'market')
            data = json.loads(receipt['raw_text'])
            if mode == 'query':
                receipt['url'] = receipt['url'].replace('stockNo=2330', 'stockNo=0050')
            elif mode == 'title':
                data['title'] = '113年01月 0050 元大台灣50'
                digest, receipt = self.receipt(data=data)
            else:
                data['tables'][0]['data'][1][0] = '2331'
                digest, receipt = self.receipt(market=True, data=data)
            with self.subTest(reason=mode), self.assertRaises(ValueError):
                cross.parse_receipt('2330', digest, receipt)

    def test_wrong_month_response_day_duplicate_day_and_json_keys_are_rejected(self):
        _, receipt = self.receipt()
        for mode in ('month', 'response_day', 'duplicate_day', 'duplicate_key'):
            data = json.loads(receipt['raw_text'])
            if mode == 'month':
                data['data'][0][0] = '113/02/10'
            elif mode == 'response_day':
                data['date'] = '20240102'
            elif mode == 'duplicate_day':
                data['data'].append(list(data['data'][0]))
            raw = json.dumps(data, ensure_ascii=False)
            if mode == 'duplicate_key':
                raw = raw.replace('"stat": "OK"', '"stat": "OK", "stat": "OK"')
            digest, item = self.receipt(raw=raw)
            with self.subTest(reason=mode), self.assertRaises(ValueError):
                cross.parse_receipt('2330', digest, item)

    def test_month_rows_after_receipt_day_and_future_receipt_time_are_rejected(self):
        _, receipt = self.receipt()
        data = json.loads(receipt['raw_text'])
        data['data'][0][0] = '113/01/21'
        for digest, item in (self.receipt(data=data), self.receipt(retrieved='2099-01-20T08:00:00+00:00')):
            with self.subTest(receipt=item['retrieved_at']), self.assertRaises(ValueError):
                cross.parse_receipt('2330', digest, item)
        data['data'][0][0] = '113/01/20'
        digest, item = self.receipt(data=data, retrieved='2024-01-19T23:30:00+00:00')
        self.assertEqual(cross.parse_receipt('2330', digest, item), {'2024-01-20': {'close': 101}},
                         '報表日期依臺灣時區，不把同一瞬間的 UTC 前一天當成晚於取得日')

    def test_market_duplicate_fields_symbol_and_price_table_are_rejected(self):
        for mode in ('fields', 'symbol', 'table'):
            _, receipt = self.receipt(market=True)
            data = json.loads(receipt['raw_text'])
            table = data['tables'][0]
            if mode == 'fields':
                table['fields'].append('收盤價')
                for row in table['data']:
                    row.append(row[-1])
            elif mode == 'symbol':
                table['data'].append(list(table['data'][1]))
            else:
                data['tables'].append(copy.deepcopy(table))
            digest, item = self.receipt(market=True, data=data)
            with self.subTest(reason=mode), self.assertRaises(ValueError):
                cross.parse_receipt('2330', digest, item)

    def test_matching_avg_close_resolves_only_observed_difference_without_mutation(self):
        original, official = [100, 103, 99, 102], [100, 103, 99, 101]
        proofs = self.proofs({'close': 101})
        before = copy.deepcopy((original, official, proofs))
        result = cross.reconcile('2024-01-10', original, official, proofs)
        self.assertEqual(result['differences'], {'close': [102, 101]})
        self.assertEqual(result['classification'], 'two-official-reports-agree')
        self.assertEqual((original, official, proofs), before)

    def test_matching_market_ohlc_supports_all_different_fields(self):
        result = cross.reconcile('2024-01-10', [98, 102, 97, 100], [100, 103, 99, 101],
                                 self.proofs({'open': 100, 'high': 103, 'low': 99, 'close': 101}))
        self.assertEqual(set(result['differences']), {'open', 'high', 'low', 'close'})

    def test_any_secondary_field_conflict_blocks_even_when_original_field_matches(self):
        official = [100, 103, 99, 101]
        for field in ('open', 'high', 'low', 'close'):
            prices = dict(zip(('open', 'high', 'low', 'close'), official))
            prices[field] += 1
            with self.subTest(field=field):
                self.assertIsNone(cross.reconcile('2024-01-10', [100, 103, 99, 102], official, self.proofs(prices)))
        proofs = self.proofs({'close': 101})
        proofs['2024-01-10'].extend(self.proofs({'open': 100, 'high': 104, 'low': 99, 'close': 101})['2024-01-10'])
        self.assertIsNone(cross.reconcile('2024-01-10', [100, 103, 99, 102], official, proofs))

    def test_missing_difference_field_proof_empty_or_incomplete_input_is_rejected(self):
        official = [100, 103, 99, 101]
        self.assertIsNone(cross.reconcile('2024-01-10', [98, 103, 99, 102], official, self.proofs({'close': 101})))
        self.assertIsNone(cross.reconcile('2024-01-10', [100, 103, 99, 102], official, {}))
        self.assertIsNone(cross.reconcile('2024-01-10', [100, 103, 99, 102], official, self.proofs({})))
        self.assertIsNone(cross.reconcile('2024-01-10', [100, 103, 99], official, self.proofs({'close': 101})))
        self.assertIsNone(cross.reconcile('2024-01-10', official, official, self.proofs({'close': 101})))

    def test_receipts_are_append_only_idempotent_and_raw_bars_remain_unchanged(self):
        with sqlite3.connect(':memory:') as conn:
            conn.execute('CREATE TABLE bars(symbol TEXT,session_date TEXT,open REAL,high REAL,low REAL,close REAL)')
            conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?)', ('2330', '2024-01-10', 100, 103, 99, 102))
            original_bars = conn.execute('SELECT * FROM bars').fetchall()
            digest, receipt = self.receipt()
            saved = cross.save_receipt(conn, '2330', digest, receipt)
            self.assertEqual(cross.save_receipt(conn, '2330', digest, receipt), saved)
            first = conn.execute(f'SELECT * FROM {cross.TABLE}').fetchone()
            cross.save_receipt(conn, '2330', *self.receipt(market=True))
            self.assertEqual(conn.execute(f'SELECT count(*) FROM {cross.TABLE}').fetchone()[0], 2)
            self.assertEqual(len(cross.load_receipts(conn, '2330')['2024-01-10']), 2)
            for sql in (f'UPDATE {cross.TABLE} SET receipt=? WHERE id=?', f'DELETE FROM {cross.TABLE} WHERE id=?'):
                args = ('{}', saved['id']) if sql.startswith('UPDATE') else (saved['id'],)
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(sql, args)
            self.assertEqual(conn.execute(f'SELECT * FROM {cross.TABLE} WHERE id=?', (saved['id'],)).fetchone(), first)
            self.assertEqual(conn.execute('SELECT * FROM bars').fetchall(), original_bars)

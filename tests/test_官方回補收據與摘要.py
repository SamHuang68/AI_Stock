"""來源原始位元組與回補摘要；固定日期 fixtures，不連外。"""
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import daily_cache_jobs as jobs
import 台股日線 as daily
from source_receipts import JsonSourceResponse


class ReceiptTransportTests(unittest.TestCase):
    url = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20261001&stockNo=2330'

    def test_both_fetchers_preserve_exact_bytes_hash_and_two_item_unpack(self):
        raw = b'{ "fields": ["date"], "notes": [], "data": [] }\n'
        budget = jobs.Budget(threading.Event())
        for module, fetch in ((daily, daily.get_json), (jobs, budget.get_json)):
            with patch.object(module, 'urlopen', return_value=io.BytesIO(raw)), patch.object(daily.time, 'sleep'):
                result = fetch(self.url)
            value, digest = result
            self.assertEqual(value, json.loads(raw))
            self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
            self.assertEqual(result.source_receipt['raw_text'].encode(), raw)
            self.assertEqual(result.source_receipt['parser_version'], 'twse-stock-day-v1')
            self.assertIsNotNone(datetime.fromisoformat(result.source_receipt['retrieved_at']).tzinfo)


    def test_invalid_utf8_already_follows_existing_fetch_failure_path(self):
        trace = []
        raw = b'{"broken": "\xff"}'
        with patch.object(daily, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(raw)) as fetch, \
             patch.object(daily.time, 'sleep'), self.assertRaises(UnicodeDecodeError):
            daily.get_json(self.url, lambda event, **details: trace.append((event, details)))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([row[0] for row in trace], ['來源失敗'] * 3)
        self.assertTrue(all(row[1]['error'] == 'UnicodeDecodeError' for row in trace))


class SeedQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'market.db'
        datastore.init_db(self.db)
        self.now = datetime(2026, 10, 2, 20, tzinfo=daily.TZ)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            months = [(2025, m) for m in range(10, 13)] + [(2026, m) for m in range(1, 10)]
            for year, month in months:
                day = date(year, month, 1)
                conn.execute('INSERT INTO market_sessions VALUES(?,?)', (day.isoformat(), 'TWSE測試'))
                row = (daily.stamp(day), 100, 102, 99, 101, 1000)
                conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330', 'TW', *row))
                conn.execute('INSERT INTO official_daily_observations VALUES(?,?,?,?,?,?,?)',
                             ('TW', '2330', day.isoformat(), 'TWSE', 'a' * 64, json.dumps(row), self.now.isoformat()))
            for day in ('2026-10-01', '2026-10-02'):
                conn.execute('INSERT INTO market_sessions VALUES(?,?)', (day, 'TWSE測試'))
            conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)',
                         ('2330', 'TW', daily.stamp(date(2026, 10, 1)), 100, 102, 99, 101, 900))
        for year, month in months:
            day = date(year, month, 1)
            raw = json.dumps({'stat': 'OK', 'date': day.strftime('%Y%m%d'),
                              'title': f'{year - 1911}年{month}月 2330 台積電 各日成交資訊',
                              'fields': ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價'],
                              'notes': ['成交股數'],
                              'data': [[f'{year - 1911}/{month:02}/01', '1000', '101000', '100', '102', '99', '101']]}, ensure_ascii=False)
            receipt = {'url': f'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={day:%Y%m%d}&stockNo=2330',
                       'raw_text': raw, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'parser_version': 'twse-stock-day-v1'}
            datastore.upsert_bars('2330', 'TW', [(daily.stamp(day), 100, 102, 99, 101, 1000)], source='TWSE',
                                  source_hash=hashlib.sha256(raw.encode()).hexdigest(), source_receipt=receipt, path=self.db)

    def source(self, *, receipt=True, missing=False):
        def fetch(url):
            self.assertIn('STOCK_DAY', url)
            self.assertIn('date=20261001', url)
            rows = [['115/10/01', '1000', '101000', '100', '102', '99', '101']]
            if not missing:
                rows.append(['115/10/02', '1000', '101000', '100', '102', '99', '101'])
            raw = json.dumps({'stat': 'OK', 'date': '20261001', 'title': '115年10月 2330 台積電 各日成交資訊',
                              'fields': ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價'],
                              'notes': ['當日統計含一般、零股、盤後定價及鉅額交易。'], 'data': rows}, ensure_ascii=False)
            value, digest = json.loads(raw), hashlib.sha256(raw.encode()).hexdigest()
            return JsonSourceResponse(value, digest, {'url': url, 'raw_text': raw,
                'retrieved_at': datetime.now(timezone.utc).isoformat(), 'parser_version': 'twse-stock-day-v1'}) if receipt else (value, digest)
        return fetch

    def run_seed(self, fetch):
        with patch.object(daily, 'stored_calendar', return_value=(set(), set())), \
             patch.object(daily, 'reconcile_sessions'), patch.object(daily, 'refresh_actions', return_value=0):
            return daily.seed_research(self.db, '2330', 1, now=self.now, fetch=fetch)

    def test_summary_counts_receipts_conflicts_and_cached_observations_separately(self):
        result = self.run_seed(self.source())
        quality = result['quality']
        self.assertEqual(quality['expected'], 14)
        self.assertEqual(quality['observed'], 14)
        self.assertEqual(quality['accepted'], 13)
        self.assertEqual(quality['conflicts'], 1)
        self.assertEqual(quality['missing'], 0)
        self.assertEqual(quality['receiptMissing'], 0)
        self.assertEqual(quality['conflictsDates'], ['2026-10-01'])
        self.assertFalse(result['qualityComplete'])
        again = self.run_seed(lambda url: self.fail('已有來源不應重抓；仍須誠實列出品質限制'))
        self.assertEqual(again['quality'], quality)
        self.assertEqual(result['fetchedMonths'], ['2026-10'])
        self.assertEqual(len(result['reusedMonths']), 12)
        self.assertEqual(again['fetchedMonths'], [])

    def test_legacy_two_item_response_is_observed_without_fabricated_receipt(self):
        result = self.run_seed(self.source(receipt=False))
        self.assertTrue(result['ok'])
        self.assertFalse(result['qualityComplete'])
        self.assertEqual(result['quality']['observed'], 14)
        self.assertEqual(result['quality']['accepted'], 12)
        self.assertEqual(result['quality']['receiptMissing'], 2)
        repaired = self.run_seed(self.source())
        self.assertEqual(repaired['fetchedMonths'], ['2026-10'])
        self.assertEqual(repaired['quality']['receiptMissing'], 0)
        self.assertEqual(repaired['quality']['accepted'], 13)

    def test_missing_official_day_is_not_counted_as_complete(self):
        result = self.run_seed(self.source(missing=True))
        self.assertEqual(result['quality']['observed'], 13)
        self.assertEqual(result['quality']['missing'], 1)
        self.assertEqual(result['quality']['missingDates'], ['2026-10-02'])
        self.assertFalse(result['qualityComplete'])

    def test_summary_reports_actual_accepted_and_excluded_incomplete_rows(self):
        with patch.object(datastore, 'completed_daily_cutoff', return_value=date(2026, 10, 1)):
            result = self.run_seed(self.source())
        self.assertEqual(result['rows'], 12)
        self.assertEqual(result['excludedIncomplete'], 1)
        self.assertEqual(result['quality']['observed'], 13)
        self.assertEqual(result['quality']['missingDates'], ['2026-10-02'])
        self.assertFalse(result['qualityComplete'])

    def test_reused_month_count_uses_accepted_quality_and_reveals_no_new_exclusions(self):
        result = self.run_seed(self.source())
        again = self.run_seed(lambda url: self.fail('完整收據不應重抓'))
        self.assertEqual(result['rows'], 13)
        self.assertEqual(again['rows'], 13)
        self.assertEqual(again['excludedIncomplete'], 0)


if __name__ == '__main__':
    unittest.main()

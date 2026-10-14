# -*- coding: utf-8 -*-
"""Yahoo 日線首次來源收據：原始回應保存、與新增 bars 的關聯、不可覆寫，以及不拖累既有寫入。"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'server'))

from server import datastore  # noqa: E402

# 台北 09:00 = UTC 01:00；兩個已完成的台股交易日。
T1 = int(datetime(2024, 3, 4, 1, 0, tzinfo=timezone.utc).timestamp())
T2 = int(datetime(2024, 3, 5, 1, 0, tzinfo=timezone.utc).timestamp())


def yahoo_payload(symbol='2330.TW', closes=(100.0, 101.0), stamps=(T1, T2)):
    return json.dumps({'chart': {'result': [{
        'meta': {'symbol': symbol, 'exchangeTimezoneName': 'Asia/Taipei', 'dataGranularity': '1d'},
        'timestamp': list(stamps),
        'indicators': {'quote': [{
            'open': [c - 1 for c in closes], 'high': [c + 1 for c in closes],
            'low': [c - 2 for c in closes], 'close': list(closes), 'volume': [1000, 2000][:len(closes)]}]},
    }]}}).encode('utf-8')


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DailySourceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, 'market.db')
        patch = mock.patch.object(datastore, 'DB_PATH', self.db_path)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.temp.cleanup)
        datastore.init_db()

    def fetch(self, raw, symbol='2330'):
        receipt = {}
        with mock.patch('urllib.request.urlopen', side_effect=lambda *a, **k: _Response(raw)):
            rows = datastore.fetch_yahoo_daily(symbol, 'TW', '5d', retries=1, receipt_out=receipt)
        return rows, receipt

    def scalar(self, sql, *args):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(sql, args).fetchone()[0]

    def test_first_insert_stores_raw_response_and_links_each_new_bar(self):
        raw = yahoo_payload()
        rows, receipt = self.fetch(raw)
        self.assertEqual(len(rows), 2)
        result = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt, job_id='job-1')
        self.assertEqual(result['inserted'], 2)
        self.assertEqual(result['sourceReceiptId'], receipt['receiptId'])
        self.assertEqual(result['jobId'], 'job-1')
        with closing(sqlite3.connect(self.db_path)) as conn:
            stored = conn.execute('SELECT raw_payload, source_hash FROM bar_source_receipts').fetchall()
            self.assertEqual(stored, [(raw, receipt['sha256'])])
            linked = conn.execute('SELECT ts, run_id, receipt_id FROM bar_first_ingest ORDER BY ts').fetchall()
        self.assertEqual([row[0] for row in linked], [T1, T2])
        self.assertEqual({row[1:] for row in linked}, {(result['runId'], receipt['receiptId'])})

    def test_no_change_update_does_not_accumulate_another_raw_copy(self):
        rows, receipt = self.fetch(yahoo_payload())
        datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        rows2, receipt2 = self.fetch(yahoo_payload())
        again = datastore.merge_source_bars('2330', 'TW', rows2, 'Yahoo Finance', ingest_receipt=receipt2)
        self.assertEqual((again['inserted'], again['unchanged']), (0, 2))
        self.assertNotIn('sourceReceiptId', again)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_source_receipts'), 1)

    def test_conflicting_value_keeps_original_and_links_the_revision(self):
        rows, receipt = self.fetch(yahoo_payload())
        datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        rows2, receipt2 = self.fetch(yahoo_payload(closes=(100.0, 150.0)))
        result = datastore.merge_source_bars('2330', 'TW', rows2, 'Yahoo Finance', ingest_receipt=receipt2)
        self.assertEqual(result['conflicts'], 1)
        self.assertEqual(self.scalar('SELECT close FROM bars WHERE ts=?', T2), 101.0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_revision_ingest WHERE receipt_id=?', receipt2['receiptId']), 1)

    def test_evidence_tables_reject_update_and_delete(self):
        rows, receipt = self.fetch(yahoo_payload())
        datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        for sql in ("UPDATE bar_source_receipts SET source_hash='x'", 'DELETE FROM bar_source_receipts',
                    "UPDATE bar_first_ingest SET receipt_id='x'", 'DELETE FROM bar_first_ingest'):
            with self.subTest(sql=sql), closing(sqlite3.connect(self.db_path)) as conn:
                with self.assertRaises(sqlite3.DatabaseError):
                    conn.execute(sql)

    def test_empty_receipt_writes_like_before_without_evidence(self):
        rows, _ = self.fetch(yahoo_payload())
        result = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt={})
        self.assertEqual(result['inserted'], 2)
        self.assertNotIn('sourceReceiptId', result)

    def test_receipt_for_another_symbol_is_rejected_and_nothing_is_written(self):
        rows, receipt = self.fetch(yahoo_payload())
        with self.assertRaises(ValueError):
            datastore.merge_source_bars('2317', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), 0)

    def test_rows_outside_the_captured_response_are_rejected(self):
        rows, receipt = self.fetch(yahoo_payload())
        forged = rows + [(T2 + 86400, 1.0, 2.0, 0.5, 1.5, 10)]
        with self.assertRaises(ValueError):
            datastore.merge_source_bars('2330', 'TW', forged, 'Yahoo Finance', ingest_receipt=receipt)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), 0)

    def test_tampered_raw_response_fails_the_hash_check(self):
        rows, receipt = self.fetch(yahoo_payload())
        receipt['raw'] = receipt['raw'] + b' '
        with self.assertRaises(ValueError):
            datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)

    def test_receipt_is_limited_to_yahoo_through_upsert_bars(self):
        rows, receipt = self.fetch(yahoo_payload())
        with self.assertRaises(ValueError):
            datastore.upsert_bars('2330', 'TW', rows, source='TWSE', ingest_receipt=receipt)

    def test_parse_contract_still_rejects_wrong_symbol_and_timezone(self):
        with self.assertRaisesRegex(RuntimeError, '來源證券代號與請求不符'):
            self.fetch(yahoo_payload(symbol='9999.TW'))


if __name__ == '__main__':
    unittest.main()

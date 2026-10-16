# -*- coding: utf-8 -*-
"""Yahoo 日線首次來源收據：原始回應保存、與新增 bars 的關聯、不可覆寫，以及不拖累既有寫入。"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import time
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
        self.assertEqual(again['sourceReceipt'], 'not_needed')
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

    def assert_rejected_receipt_still_writes_bars(self, symbol, rows, receipt, expected_bars):
        result = datastore.merge_source_bars(symbol, 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        self.assertEqual(result['sourceReceipt'], 'rejected')
        self.assertIn('sourceReceiptError', result)
        self.assertNotIn('sourceReceiptId', result)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), expected_bars)
        with closing(sqlite3.connect(self.db_path)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('bar_source_receipts', 'bar_first_ingest'):
                # 核對失敗發生在建表之前：表不存在，或存在但沒有任何證據列。
                if table in tables:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_receipt_for_another_symbol_is_flagged_and_does_not_block_the_write(self):
        rows, receipt = self.fetch(yahoo_payload())
        self.assert_rejected_receipt_still_writes_bars('2317', rows, receipt, 2)

    def test_rows_outside_the_captured_response_are_flagged_and_do_not_block_the_write(self):
        rows, receipt = self.fetch(yahoo_payload())
        forged = rows + [(T2 + 86400, 1.0, 2.0, 0.5, 1.5, 10)]
        self.assert_rejected_receipt_still_writes_bars('2330', forged, receipt, 3)

    def test_tampered_raw_response_is_flagged_and_does_not_block_the_write(self):
        rows, receipt = self.fetch(yahoo_payload())
        receipt['raw'] = receipt['raw'] + b' '
        self.assert_rejected_receipt_still_writes_bars('2330', rows, receipt, 2)

    def test_missing_receipt_is_visible_in_the_result(self):
        rows, _ = self.fetch(yahoo_payload())
        result = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance')
        self.assertEqual(result['sourceReceipt'], 'absent')

    def test_persistent_conflict_does_not_store_another_raw_copy_each_run(self):
        rows, receipt = self.fetch(yahoo_payload())
        datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        for _ in range(3):
            rows2, receipt2 = self.fetch(yahoo_payload(closes=(100.0, 150.0)))
            datastore.merge_source_bars('2330', 'TW', rows2, 'Yahoo Finance', ingest_receipt=receipt2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_source_receipts'), 2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_revision_ingest'), 1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_source_revisions'), 1)

    def test_bar_removed_elsewhere_can_be_fetched_again_and_keeps_the_original_evidence(self):
        rows, receipt = self.fetch(yahoo_payload())
        datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute('DELETE FROM bars WHERE ts=?', (T2,))
            conn.commit()
        rows2, receipt2 = self.fetch(yahoo_payload())
        again = datastore.merge_source_bars('2330', 'TW', rows2, 'Yahoo Finance', ingest_receipt=receipt2)
        self.assertEqual(again['inserted'], 1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), 2)
        self.assertEqual(self.scalar('SELECT receipt_id FROM bar_first_ingest WHERE ts=?', T2), receipt['receiptId'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_first_ingest'), 2)

    def test_bar_removed_and_fetched_again_with_different_values_keeps_both_traces(self):
        rows, receipt = self.fetch(yahoo_payload())
        datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute('DELETE FROM bars WHERE ts=?', (T2,))
            conn.commit()
        rows2, receipt2 = self.fetch(yahoo_payload(closes=(100.0, 150.0)))
        again = datastore.merge_source_bars('2330', 'TW', rows2, 'Yahoo Finance', ingest_receipt=receipt2)
        self.assertEqual(again['inserted'], 1)
        self.assertEqual(self.scalar('SELECT close FROM bars WHERE ts=?', T2), 150.0)
        # 原首次證據保留，重插以另一筆不可覆寫的關聯指向新的收據。
        self.assertEqual(self.scalar('SELECT receipt_id FROM bar_first_ingest WHERE ts=?', T2), receipt['receiptId'])
        self.assertEqual(self.scalar('SELECT receipt_id FROM bar_reinsert_ingest WHERE ts=?', T2), receipt2['receiptId'])
        self.assertEqual(self.scalar('SELECT run_id FROM bar_reinsert_ingest WHERE ts=?', T2), again['runId'])

    def test_evidence_tables_have_no_hidden_rowid_to_replace_through(self):
        rows, receipt = self.fetch(yahoo_payload())
        datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        with closing(sqlite3.connect(self.db_path)) as conn:
            for table in ('bar_source_receipts', 'bar_first_ingest', 'bar_reinsert_ingest', 'bar_revision_ingest'):
                with self.subTest(table=table), self.assertRaises(sqlite3.DatabaseError):
                    conn.execute('SELECT rowid FROM %s' % table)
            before = conn.execute('SELECT receipt_id, raw_payload FROM bar_source_receipts').fetchall()
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute('INSERT OR REPLACE INTO bar_source_receipts(rowid,receipt_id,source,symbol,market,'
                             'source_url,raw_payload,source_hash,retrieved_at,parser_version,volume_contract) '
                             "VALUES(1,'B','Yahoo Finance','2330','TW','u',x'02','h',1.0,'p','v')")
            self.assertEqual(conn.execute('SELECT receipt_id, raw_payload FROM bar_source_receipts').fetchall(), before)

    def test_evidence_table_created_with_a_rowid_is_not_reused(self):
        # 早期版本（沒有 WITHOUT ROWID）建立的表：IF NOT EXISTS 不會升級，不可靜默沿用而讓防覆寫失效。
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute('CREATE TABLE bar_source_receipts(receipt_id TEXT PRIMARY KEY,source TEXT NOT NULL,'
                         'symbol TEXT NOT NULL,market TEXT NOT NULL,source_url TEXT NOT NULL,raw_payload BLOB NOT NULL,'
                         'source_hash TEXT NOT NULL,retrieved_at REAL NOT NULL,parser_version TEXT NOT NULL,'
                         'volume_contract TEXT NOT NULL)')
            conn.commit()
        rows, receipt = self.fetch(yahoo_payload())
        result = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        self.assertEqual(result['sourceReceipt'], 'rejected')
        self.assertIn('WITHOUT ROWID', result['sourceReceiptError'])
        self.assertEqual(result['inserted'], 2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), 2)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_source_receipts'), 0)

    def test_another_process_committing_the_same_day_meanwhile_does_not_fail_the_batch(self):
        # 另一個連線（等同另一個程序，不受 _db_write_lock 約束）持有寫入交易並已寫入同一天；
        # merge 必須等它提交後再讀 existing，把該日視為未變動，而不是在 INSERT 時撞主鍵讓整批失敗。
        import threading
        rows, receipt = self.fetch(yahoo_payload())
        # 正式庫的兩張帳本表早已存在：此時 CREATE TABLE IF NOT EXISTS 不需要寫入鎖，舊寫法會在對方提交前
        # 就讀走過期的 existing。若測試庫是全新的，DDL 需要寫入鎖而恰好等到對方提交，就重現不了這個競態。
        with closing(sqlite3.connect(self.db_path)) as warm:
            warm.execute('CREATE TABLE IF NOT EXISTS bar_source_revisions('
                         'id TEXT PRIMARY KEY,symbol TEXT,market TEXT,session_date TEXT,observed_at REAL,payload TEXT)')
            warm.execute('CREATE TABLE IF NOT EXISTS bar_ingest_runs(id TEXT PRIMARY KEY,payload TEXT)')
            warm.commit()
        other = sqlite3.connect(self.db_path, timeout=30)
        other.execute('BEGIN IMMEDIATE')
        other.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330', 'TW', rows[0][0], *rows[0][1:]))
        outcome = {}

        def run():
            try:
                outcome['result'] = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
            except Exception as exc:  # 測試要看到實際例外
                outcome['error'] = repr(exc)

        worker = threading.Thread(target=run)
        worker.start()
        time.sleep(0.5)
        self.assertTrue(worker.is_alive(), 'merge 應在等待另一個寫入交易')
        other.commit()
        other.close()
        worker.join(30)
        self.assertNotIn('error', outcome)
        self.assertEqual((outcome['result']['inserted'], outcome['result']['unchanged']), (1, 1))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), 2)
        # 第一天是另一個程序寫的，沒有首次證據；只有本次新增的那天有。
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_first_ingest'), 1)

    def test_evidence_layer_sqlite_errors_degrade_without_blocking_the_bars(self):
        broken = {
            'bar_source_receipts': 'CREATE TABLE bar_source_receipts(receipt_id TEXT PRIMARY KEY, x TEXT) WITHOUT ROWID',
            'bar_first_ingest': 'CREATE TABLE bar_first_ingest(market TEXT, symbol TEXT, ts INTEGER, PRIMARY KEY(market,symbol,ts)) WITHOUT ROWID',
        }
        for table, ddl in broken.items():
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.db_path)) as conn:
                    for name in ('bar_source_receipts', 'bar_first_ingest', 'bar_reinsert_ingest', 'bar_revision_ingest'):
                        conn.execute('DROP TABLE IF EXISTS ' + name)
                    conn.execute('DELETE FROM bars')
                    conn.execute(ddl)
                    conn.commit()
                rows, receipt = self.fetch(yahoo_payload())
                result = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
                # 證據表欄位不符（sqlite3.OperationalError）：日線照舊寫入，旗標與錯誤如實標示，不丟例外。
                self.assertEqual(result['inserted'], 2)
                self.assertIn(result['sourceReceipt'], ('rejected', 'partial'))
                self.assertIn('OperationalError', result['sourceReceiptError'])
                self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), 2)
                self.assertEqual(self.scalar('PRAGMA integrity_check'), 'ok')

    def test_evidence_failure_rolls_back_only_the_evidence_step(self):
        # 失敗步驟若已建立表或寫入列，必須隨 SAVEPOINT 一併撤銷，不留半套證據。
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute('CREATE TABLE bar_first_ingest(market TEXT, symbol TEXT, ts INTEGER, '
                         'PRIMARY KEY(market,symbol,ts)) WITHOUT ROWID')
            conn.commit()
        rows, receipt = self.fetch(yahoo_payload())
        result = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        self.assertEqual(result['sourceReceipt'], 'partial')
        # 收據步驟已成功釋放；失敗的是第一筆關聯，之後不再嘗試其他證據步驟。
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_source_receipts'), 1)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bar_first_ingest'), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), 2)

    def test_malformed_receipt_structure_does_not_break_the_write(self):
        import hashlib
        rows, receipt = self.fetch(yahoo_payload())
        cases = {
            'sourceSymbol 型別錯誤（TypeError）': dict(receipt, sourceSymbol=['x']),
            '雜湊正確但結構無效（KeyError）': dict(receipt, raw=b'{}', sha256=hashlib.sha256(b'{}').hexdigest()),
        }
        for name, bad in cases.items():
            with self.subTest(name):
                result = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=bad)
                self.assertEqual(result['sourceReceipt'], 'rejected')
                self.assertIn('sourceReceiptError', result)
                self.assertEqual(self.scalar('SELECT COUNT(*) FROM bars'), 2)
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.execute('DELETE FROM bars')
                    conn.commit()

    def test_insert_or_replace_cannot_overwrite_any_evidence_table(self):
        rows, receipt = self.fetch(yahoo_payload())
        result = datastore.merge_source_bars('2330', 'TW', rows, 'Yahoo Finance', ingest_receipt=receipt)
        with closing(sqlite3.connect(self.db_path)) as conn:
            revision = ('rev', result['runId'], receipt['receiptId'])
            conn.execute('INSERT INTO bar_revision_ingest VALUES(?,?,?)', revision)
            for sql, args in (
                    ('INSERT OR REPLACE INTO bar_source_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (receipt['receiptId'], 'Yahoo Finance', '2330', 'TW', 'u', b'x', 'h', 1.0, 'p', 'v')),
                    ('INSERT OR REPLACE INTO bar_first_ingest VALUES(?,?,?,?,?,?,?)',
                     ('TW', '2330', T1, 'r', 'x', 1.0, '{}')),
                    ('INSERT OR REPLACE INTO bar_revision_ingest VALUES(?,?,?)', ('rev', result['runId'], 'other'))):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                    conn.execute(sql, args)
            for table in ('bar_revision_ingest',):
                for sql in ("UPDATE %s SET receipt_id='x'" % table, 'DELETE FROM %s' % table):
                    with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                        conn.execute(sql)

    def test_receipt_is_limited_to_yahoo_through_upsert_bars(self):
        rows, receipt = self.fetch(yahoo_payload())
        with self.assertRaises(ValueError):
            datastore.upsert_bars('2330', 'TW', rows, source='TWSE', ingest_receipt=receipt)

    def test_parse_contract_still_rejects_wrong_symbol_and_timezone(self):
        with self.assertRaisesRegex(RuntimeError, '來源證券代號與請求不符'):
            self.fetch(yahoo_payload(symbol='9999.TW'))


if __name__ == '__main__':
    unittest.main()

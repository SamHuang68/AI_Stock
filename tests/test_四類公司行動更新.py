"""四類事件更新的獨立來源 fixtures；不連外、不寫正式資料。"""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore
import 公司行動更新 as actions
import 公司行動比較 as comparison
import 台股日線 as daily


class ActionUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'market.db'
        datastore.init_db(self.db)
        self.calls = []

    def response(self, *, after=50, event=True, failed=None):
        def fetch(url):
            self.calls.append(url)
            if failed and failed in url:
                raise TimeoutError('來源測試失敗')
            value = {'stat': '很抱歉，沒有符合條件的資料!'}
            if '/split/' in url and event:
                value = {'stat': 'OK', 'fields': ['恢復買賣日期', 'ETF代號', '停止買賣前收盤價格', '恢復買賣參考價', '分割(反分割)'],
                         'data': [['115/09/24', '0050', '100', str(after), '分割']]}
                params = parse_qs(urlparse(url).query)
                value.update(startDate=params['startDate'][0], endDate=params['endDate'][0])
            return value, hashlib.sha256(json.dumps(value).encode()).hexdigest()
        return fetch

    def update(self, **kwargs):
        return daily.refresh_actions(self.db, '0050', date(2026, 9, 23), date(2026, 9, 30), self.response(**kwargs))

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return '\n'.join(conn.iterdump())

    def test_four_routes_and_reference_evidence_are_saved_together(self):
        self.assertEqual(self.update(), 1)
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(any('/split/TWTCAU?' in url for url in self.calls))
        with closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute('SELECT kind,previous_close,reference_price,factor FROM action_price_evidence').fetchone()
            self.assertEqual(row, ('ETF分割', 100, 50, .5))
            self.assertEqual(conn.execute('SELECT count(*) FROM action_source_receipts').fetchone()[0], 4)
            coverage = conn.execute('SELECT start_date,end_date,source FROM action_coverage').fetchone()
            self.assertEqual(coverage[:2], ('2026-09-23', '2026-09-30'))
            self.assertIn('ETF分割', coverage[2])

    def test_fourth_source_failure_or_invalid_digest_preserves_every_table(self):
        for fetch in (self.response(failed='split/'), lambda url: ({'stat': '很抱歉，沒有符合條件的資料!'}, '')):
            before = self.snapshot()
            with self.assertRaises((TimeoutError, ValueError)):
                actions.refresh_actions(self.db, '0050', date(2026, 9, 23), date(2026, 9, 30), fetch)
            self.assertEqual(self.snapshot(), before)

    def test_cancel_inside_transaction_rolls_back_schema_and_receipts(self):
        before = self.snapshot()
        original = actions.ensure_action_schema
        cancelled = [False]
        def create(conn):
            original(conn)
            cancelled[0] = True
        def check():
            if cancelled[0]:
                raise RuntimeError('已取消')
        with patch.object(actions, 'ensure_action_schema', side_effect=create), self.assertRaises(RuntimeError):
            daily.refresh_actions(self.db, '0050', date(2026, 9, 23), date(2026, 9, 30), self.response(), check)
        self.assertEqual(self.snapshot(), before)

    def test_revision_keeps_first_evidence_and_blocks_reader(self):
        self.update()
        with closing(sqlite3.connect(self.db)) as conn:
            original = conn.execute('SELECT * FROM action_price_evidence').fetchone()
        self.update(after=40)
        self.update(after=40)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM action_price_evidence').fetchone(), original)
            self.assertEqual(conn.execute('SELECT count(*) FROM action_price_revisions').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM action_source_receipts').fetchone()[0], 5)
            parsed = comparison.load_adjustments(conn, '0050', '2026-09-30')
            self.assertEqual(parsed['events'][0]['status'], 'conflict')
            self.assertEqual(parsed['events'][0]['before'], 100)
            self.assertEqual(parsed['events'][0]['after'], 50)

    def test_official_retraction_does_not_delete_event_or_its_evidence(self):
        self.update()
        self.update(event=False)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM corporate_actions').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM action_price_evidence').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT revision_payload FROM action_price_revisions').fetchone()[0], 'null')
            self.assertEqual(comparison.load_adjustments(conn, '0050', '2026-09-30')['events'][0]['status'], 'conflict')

    def test_repeated_same_response_preserves_first_receipt_and_evidence(self):
        self.update()
        before = self.snapshot()
        self.update()
        self.assertEqual(self.snapshot(), before)

    def test_disjoint_ranges_do_not_claim_gap_and_bridge_restores_contiguous_coverage(self):
        ranges = [('2026-09-01', '2026-09-05'), ('2026-09-10', '2026-09-15'), ('2026-09-06', '2026-09-09')]
        for first, last in ranges:
            actions.refresh_actions(self.db, '0050', date.fromisoformat(first), date.fromisoformat(last), self.response(event=False))
            with closing(sqlite3.connect(self.db)) as conn:
                coverage = conn.execute('SELECT start_date,end_date FROM action_price_coverage').fetchone()
            self.assertEqual(coverage, ('2026-09-01', '2026-09-15') if first == '2026-09-06' else (first, last))
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM action_source_receipts').fetchone()[0], 12)

    def test_legacy_three_route_coverage_is_not_promoted_to_four(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)', ('TW', '0050', '2020-01-01', '2026-09-22', 'TWSE除權息、減資、面額變更'))
        self.update()
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT start_date FROM action_coverage').fetchone()[0], '2026-09-23')

    def test_duplicate_or_wrong_date_event_aborts_before_write(self):
        for mode in ('duplicate', 'wrong_date', 'wrong_range'):
            base = self.response()
            def fetch(url):
                value, _ = base(url)
                if '/split/' in url:
                    if mode == 'duplicate':
                        value['data'] *= 2
                    elif mode == 'wrong_date':
                        value['data'][0][0] = '115/10/01'
                    else:
                        value['strDate'] = '20260901'
                return value, hashlib.sha256(json.dumps(value).encode()).hexdigest()
            before = self.snapshot()
            with self.assertRaises(ValueError):
                actions.refresh_actions(self.db, '0050', date(2026, 9, 23), date(2026, 9, 30), fetch)
            self.assertEqual(self.snapshot(), before)


    def test_official_period_variants_are_verified_without_request_fallback(self):
        first, last = date(2026, 9, 23), date(2026, 10, 2)
        # 依四份已保存官方原始回應，三種實際期間欄位各自核對。
        payloads = [
            {'stat': 'OK', 'strDate': '20260923', 'endDate': '20261002'},
            {'stat': 'OK', 'params': {'startDate': '20260923', 'endDate': '20261002'}},
            {'stat': 'OK', 'startDate': '20260923', 'endDate': '20261002'},
        ]
        for payload in payloads:
            actions._response_period(payload, first, last, '測試事件')
        for payload in [
            {'stat': 'OK'},
            {'stat': 'OK', 'startDate': '20260901', 'endDate': '20261002'},
            {'stat': 'OK', 'params': {'startDate': '20260901', 'endDate': '20261002'}},
            {'stat': 'OK', 'strDate': '20260923', 'endDate': '20261002',
             'params': {'startDate': '20260901', 'endDate': '20261002'}},
            {'stat': 'OK', 'params': None},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                actions._response_period(payload, first, last, '測試事件')
        actions._response_period({'stat': '很抱歉，沒有符合條件的資料!'}, first, last, '測試事件')

    def test_incomplete_coverage_has_explicit_error_instead_of_stop_iteration(self):
        with self.assertRaisesRegex(ValueError, '未完整涵蓋'):
            actions._coverage([], date(2026, 9, 23), date(2026, 9, 30))


if __name__ == '__main__':
    unittest.main()

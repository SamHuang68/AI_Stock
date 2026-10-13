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

    def dividend_update(self, *, latest='115年09月22日', nav='111.70', eps='N/A', symbol='0050', changes=None):
        def fetch(url):
            value = {'stat': '很抱歉，沒有符合條件的資料!'}
            if '/exRight/' in url:
                raw = {'資料日期': '115年09月24日', '股票代號': symbol, '股票名稱': '台積電' if symbol == '2330' else '元大台灣50',
                       '除權息前收盤價': '100', '除權息參考價': '99', '權值+息值': '1', '權/息': '息',
                       '最近一次申報資料 季別/日期': latest, '最近一次申報每股 (單位)淨值': nav,
                       '最近一次申報每股 (單位)盈餘': eps}
                raw.update(changes or {})
                params = parse_qs(urlparse(url).query)
                value = {'stat': 'OK', 'startDate': params['startDate'][0], 'endDate': params['endDate'][0],
                         'fields': list(raw), 'data': [list(raw.values())]}
            return value, hashlib.sha256(json.dumps(value).encode()).hexdigest()
        return daily.refresh_actions(self.db, symbol, date(2026, 9, 23), date(2026, 9, 30), fetch)

    def legacy_metadata_revision(self):
        self.dividend_update()
        # 重現修正前的分類方式，留下真實完整來源收據與歷史 revision，而非手製略過標記。
        def previous_meaning(row):
            payload = json.loads(row[13])
            return list(row[2:9]) + [row[12], dict(zip(payload['fields'], payload['row']))]
        with patch.object(actions, '_meaning', side_effect=previous_meaning):
            self.dividend_update(latest='115年10月13日', nav='112.06', eps='1.23')

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

    def test_real_ex_dividend_chinese_date_schema_and_fail_closed_boundaries(self):
        # 2026-10-13 取得 TWT49U 的 20251001–20251231 原始 2330 列，僅裁掉無關欄位。
        # 快取來源：83b86c2ba1787567cd89b57b0468cdc8ceeb05a16b339e350ef9fd2acd441efc.json。
        def response(event_date):
            def fetch(url):
                value = {'stat': '很抱歉，沒有符合條件的資料!'}
                if '/exRight/' in url:
                    value = {'stat': 'OK', 'strDate': '20251001', 'endDate': '20251231',
                        'fields': ['資料日期', '股票代號', '股票名稱', '除權息前收盤價', '除權息參考價', '權/息'],
                        'data': [[event_date, '2330', '台積電', '1,505.00', '1,499.99', '息']]}
                return value, hashlib.sha256(json.dumps(value).encode()).hexdigest()
            return fetch
        first, last = date(2025, 10, 1), date(2025, 12, 31)
        for invalid in ('114年12月11日待確認', '114年12/11日', '114年02月30日', '115年01月01日'):
            with self.subTest(date=invalid):
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    actions.refresh_actions(self.db, '2330', first, last, response(invalid))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(actions.refresh_actions(self.db, '2330', first, last, response('114年12月11日')), 1)
        with closing(sqlite3.connect(self.db)) as conn:
            row = conn.execute('SELECT session_date,kind,previous_close,reference_price,status,payload_json FROM action_price_evidence').fetchone()
            self.assertEqual(row[:5], ('2025-12-11', '除權息', 1505, 1499.99, 'supported'))
            self.assertEqual(json.loads(row[5])['row'][0], '114年12月11日')
            self.assertEqual(conn.execute('SELECT count(*) FROM action_source_receipts').fetchone()[0], 4)

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

    def test_current_filing_metadata_keeps_first_event_and_all_receipts_without_conflict(self):
        self.dividend_update()
        with closing(sqlite3.connect(self.db)) as conn:
            original = conn.execute('SELECT * FROM action_price_evidence').fetchone()
        self.dividend_update(latest='115年10月13日', nav='112.06', eps='1.23')
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM action_price_evidence').fetchone(), original)
            self.assertEqual(conn.execute('SELECT count(*) FROM action_price_revisions').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM action_source_receipts').fetchone()[0], 5)
            parsed = comparison.load_adjustments(conn, '0050', '2026-09-30')
            self.assertEqual(parsed['events'][0]['status'], 'supported')
            self.assertEqual((parsed['events'][0]['before'], parsed['events'][0]['after']), (100, 99))

    def test_普通股最新盈餘僅更新附加資料且保留首次事件(self):
        # 官方 TWT49U notes 明示普通股財報為最近一次申報；此案例只變 EPS。
        self.dividend_update(symbol='2330', latest='115年第1季', eps='23.25')
        with closing(sqlite3.connect(self.db)) as conn:
            original = conn.execute('SELECT * FROM action_price_evidence').fetchone()
        self.dividend_update(symbol='2330', latest='115年第1季', eps='49.33')
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM action_price_evidence').fetchone(), original)
            self.assertEqual(conn.execute('SELECT count(*) FROM action_price_revisions').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM action_source_receipts').fetchone()[0], 5)
            parsed = comparison.load_adjustments(conn, '2330', '2026-09-30')
            self.assertEqual(parsed['events'][0]['status'], 'supported')
            self.assertEqual((parsed['events'][0]['before'], parsed['events'][0]['after']), (100, 99))

    def test_分類改版不重複記錄同一真實修訂且不合併不同原件(self):
        self.dividend_update(eps='1.00')
        old_fields = actions.CURRENT_FILING_FIELDS - {'最近一次申報每股 (單位)盈餘'}
        with patch.object(actions, 'CURRENT_FILING_FIELDS', old_fields):
            self.dividend_update(eps='2.00', changes={'除權息參考價': '98'})
        with closing(sqlite3.connect(self.db)) as conn:
            original = conn.execute('SELECT * FROM action_price_evidence').fetchone()
            revision = conn.execute('SELECT * FROM action_price_revisions').fetchone()
        self.dividend_update(eps='2.00', changes={'除權息參考價': '98'})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM action_price_evidence').fetchone(), original)
            self.assertEqual(conn.execute('SELECT * FROM action_price_revisions').fetchall(), [revision])
            self.assertEqual(comparison.load_adjustments(conn, '0050', '2026-09-30')['events'][0]['status'], 'conflict')
        self.dividend_update(eps='2.00', changes={'除權息參考價': '97'})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM action_price_revisions').fetchone()[0], 2)
            self.assertEqual(conn.execute('SELECT * FROM action_price_revisions WHERE id=?', (revision[0],)).fetchone(), revision)

    def test_existing_metadata_revision_is_reclassified_read_only_with_original_evidence_intact(self):
        self.legacy_metadata_revision()
        before = self.snapshot()
        with closing(sqlite3.connect(self.db)) as conn:
            parsed = comparison.load_adjustments(conn, '0050', '2026-09-30')
            self.assertEqual(parsed['events'][0]['status'], 'supported')
            self.assertEqual(parsed['revisionClassifications'][0]['status'], 'metadata_only')
            self.assertEqual(parsed['revisionClassifications'][0]['classificationVersion'], 'action-revision-classification-2')
            self.assertEqual(set(parsed['revisionClassifications'][0]['changedFields']), actions.CURRENT_FILING_FIELDS)
            rows = [{'date': '2026-09-23', 'close': 100, 'source': 'TWSE', 'priceBasis': 'unadjusted', 'issues': []},
                    {'date': '2026-09-24', 'close': 100, 'source': 'TWSE', 'priceBasis': 'unadjusted', 'issues': []}]
            detail = comparison.Comparison(rows, parsed, {'2026-09-24'}).evidence(0, 1)
            self.assertEqual(detail['revisionClassifications'], parsed['revisionClassifications'])
            without_audit = {**parsed, 'revisionClassifications': []}
            self.assertEqual(comparison.Comparison(rows, parsed, {'2026-09-24'}).digest_evidence(0, 1),
                             comparison.Comparison(rows, without_audit, {'2026-09-24'}).digest_evidence(0, 1))
            self.assertEqual(conn.execute('SELECT count(*) FROM action_price_revisions').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM action_source_receipts').fetchone()[0], 5)
        self.assertEqual(self.snapshot(), before)

    def test_economic_and_unknown_fields_still_block_when_filing_metadata_also_changes(self):
        changes = ({'除權息參考價': '98'}, {'權值+息值': '2'}, {'權/息': '權'},
                   {'新增經濟欄位': '未知條件'}, {'除權息前收盤價': '101'})
        for change in changes:
            with self.subTest(change=change):
                # 每一案例獨立交易範圍；不能讓前一個衝突替後續案例通過斷言。
                with closing(sqlite3.connect(self.db)) as conn, conn:
                    actions.ensure_action_schema(conn)
                    for table in ('action_price_evidence', 'action_price_coverage', 'action_source_receipts', 'action_price_revisions', 'corporate_actions', 'action_coverage'):
                        conn.execute('DELETE FROM ' + table)
                self.dividend_update()
                with closing(sqlite3.connect(self.db)) as conn:
                    original = conn.execute('SELECT * FROM action_price_evidence').fetchone()
                self.dividend_update(latest='115年10月13日', nav='112.06', eps='1.23', changes=change)
                with closing(sqlite3.connect(self.db)) as conn:
                    self.assertEqual(conn.execute('SELECT * FROM action_price_evidence').fetchone(), original)
                    self.assertEqual(conn.execute('SELECT count(*) FROM action_price_revisions').fetchone()[0], 1)
                    parsed = comparison.load_adjustments(conn, '0050', '2026-09-30')
                    self.assertEqual(parsed['events'][0]['status'], 'conflict')
                    self.assertEqual(parsed['revisionClassifications'][0]['status'], 'conflict')

    def test_legacy_revision_missing_or_damaged_provenance_fails_closed_without_writing(self):
        self.legacy_metadata_revision()
        with closing(sqlite3.connect(self.db)) as conn:
            identity, original, revision, receipt_id = conn.execute(
                'SELECT id,original_payload,revision_payload,source_receipt_id FROM action_price_revisions').fetchone()
        old, new = json.loads(original), json.loads(revision)
        bad_old = list(old)
        bad_old[4] = 101
        wrong_symbol = list(new)
        wrong_symbol[1] = '2330'
        duplicate_fields = list(new)
        payload = json.loads(new[13])
        payload['fields'].append(payload['fields'][0])
        payload['row'].append(payload['row'][0])
        duplicate_fields[13] = json.dumps(payload)
        missing_metadata = list(new)
        payload = json.loads(new[13])
        removed = payload['fields'].index('最近一次申報每股 (單位)淨值')
        payload['fields'].pop(removed)
        payload['row'].pop(removed)
        missing_metadata[13] = json.dumps(payload)
        changed_factor = list(new)
        changed_factor[6] = .5
        changed_version = list(new)
        changed_version[12] = '未知解析版本'
        cases = [
            ('撤回', original, 'null', receipt_id),
            ('格式損毀', original, '{', receipt_id),
            ('原件不符', json.dumps(bad_old), revision, receipt_id),
            ('標的不符', original, json.dumps(wrong_symbol), receipt_id),
            ('欄位重複', original, json.dumps(duplicate_fields), receipt_id),
            ('白名單欄位缺失', original, json.dumps(missing_metadata), receipt_id),
            ('因子改變', original, json.dumps(changed_factor), receipt_id),
            ('解析版本改變', original, json.dumps(changed_version), receipt_id),
            ('缺收據', original, revision, '不存在的收據'),
        ]
        for label, old_text, new_text, receipt in cases:
            with self.subTest(reason=label):
                with closing(sqlite3.connect(self.db)) as conn, conn:
                    conn.execute('UPDATE action_price_revisions SET original_payload=?,revision_payload=?,source_receipt_id=? WHERE id=?',
                                 (old_text, new_text, receipt, identity))
                before = self.snapshot()
                with closing(sqlite3.connect(self.db)) as conn:
                    parsed = comparison.load_adjustments(conn, '0050', '2026-09-30')
                    self.assertEqual(parsed['events'][0]['status'], 'conflict')
                    self.assertEqual(parsed['revisionClassifications'][0]['status'], 'conflict')
                self.assertEqual(self.snapshot(), before)

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

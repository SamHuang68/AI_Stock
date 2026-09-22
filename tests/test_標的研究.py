"""公開標的整合：封網、過期來源、原資料保全與正式 HTTP 接線。"""
import copy
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import 研究工作流 as research
import datastore
import etf_paths
import private_web_gateway as gateway


class SubjectResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'market.db'
        self.chips = self.root / 'chip_history'
        self.etfs = self.root / 'etf_history'
        self.chips.mkdir(); self.etfs.mkdir()
        blocker = mock.patch.object(urllib.request, 'urlopen', side_effect=AssertionError('禁止外部連線'))
        blocker.start(); self.addCleanup(blocker.stop)
        self.sources = {'datasets': {
            't187ap05_L': {'公司代號': '2330', '資料年月': '11508', '出表日期': '1150908',
                '營業收入-當月營收': '100', '營業收入-去年同月增減(%)': '0', '私人筆記': '不得外送'},
            't187ap06_L_ci': {'年度': '115', '季別': '2', '出表日期': '1150810',
                '營業收入': '100', '營業毛利': '50', '基本每股盈餘(元)': '2', '私人持倉': '不得外送'}},
            'sectors': {'date': '20260923', 'map': {'2330': '半導體業', '2303': '半導體業', '2317': '其他'}}}

    def build(self, symbol='2330', sources=None):
        return research.build_subject(symbol, self.db, sources=self.sources if sources is None else sources,
            chip_directory=self.chips, etf_directory=self.etfs, catalog_path=self.root / 'etf_catalog.json')

    def write(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    def seed_prices(self, other_day='2026-09-22', issues='[]'):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE bars(market TEXT,symbol TEXT,ts INTEGER,close REAL)')
            conn.execute('CREATE TABLE bar_quality(market TEXT,symbol TEXT,ts INTEGER,session_date TEXT,source TEXT,price_basis TEXT,issues TEXT)')
            for code, day, flag in [('2330', '2026-09-22', '[]'), ('2303', other_day, issues)]:
                for ts, date, price in [(1, '2026-09-21', 100), (2, day, 110)]:
                    conn.execute('INSERT INTO bars VALUES(?,?,?,?)', ('TW', code, ts, price))
                    conn.execute('INSERT INTO bar_quality VALUES(?,?,?,?,?,?,?)', ('TW', code, ts, date, 'TWSE', 'raw', flag))

    def test_saved_fundamentals_keep_source_date_period_zero_and_privacy(self):
        before = copy.deepcopy(self.sources)
        value = self.build()
        rows = value['domains']['fundamentals']['evidence']
        self.assertEqual('2026-09-08', rows[0]['asOf'])
        self.assertEqual('2026-08', rows[0]['value']['periodLabel'])
        self.assertEqual(0, rows[0]['value']['yoyPct'])
        self.assertEqual('2026-08-10', rows[1]['asOf'])
        self.assertEqual('not_applicable', value['domains']['etfResearch']['availability'])
        self.assertNotIn('不得外送', json.dumps(value, ensure_ascii=False))
        self.assertEqual(before, self.sources)
        self.assertFalse(self.db.exists())

    def test_empty_sources_remain_unknown_without_creating_files(self):
        before = list(self.root.iterdir())
        value = self.build(sources={})
        self.assertTrue(all(row['availability'] == 'unknown' for row in value['domains'].values()))
        self.assertEqual([], value['evidence'])
        self.assertIsNone(value['asOf'])
        self.assertEqual(before, list(self.root.iterdir()))

    def test_old_chip_source_not_filename_and_full_saved_history_preserved(self):
        for n in range(1, 4):
            self.write(self.chips / f'2026090{n}.json', {'2330': {'foreign': 0, 'trust': n,
                'sourceDate': f'2026-08-0{n}', 'source': 'TWSE T86', 'unit': 'shares', 'note': '不得外送'}})
        before = {path: path.read_bytes() for path in self.chips.iterdir()}
        value = self.build(sources={})['domains']['flows']
        self.assertEqual(3, len(value['evidence']))
        self.assertEqual('2026-08-03', value['asOf'])
        self.assertEqual(0, value['evidence'][0]['value']['foreign'])
        self.assertNotIn('不得外送', json.dumps(value, ensure_ascii=False))
        self.assertEqual(before, {path: path.read_bytes() for path in self.chips.iterdir()})

    def test_missing_chip_date_stays_partial(self):
        self.write(self.chips / '20260922.json', {'2330': {'foreign': 10, 'source': 'TWSE T86'}})
        value = self.build(sources={})['domains']['flows']
        self.assertEqual('partial', value['availability'])
        self.assertIsNone(value['asOf'])

    def test_peers_require_matching_date_source_basis_and_quality(self):
        self.seed_prices()
        before = self.db.read_bytes()
        rows = self.build()['domains']['peersThemes']['evidence']
        self.assertEqual({'2330', '2303'}, {row['value']['symbol'] for row in rows})
        self.assertTrue(all(row['value']['comparable'] for row in rows))
        self.assertTrue(all(row['value']['changePct'] == 10 for row in rows))
        self.assertEqual(before, self.db.read_bytes())
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE bar_quality SET session_date='2026-09-20' WHERE symbol='2303' AND ts=2")
        rows = self.build()['domains']['peersThemes']['evidence']
        other = next(row['value'] for row in rows if row['value']['symbol'] == '2303')
        self.assertFalse(other['comparable']); self.assertIsNone(other['changePct'])

    def test_peer_quality_issue_never_becomes_zero_return(self):
        self.seed_prices(issues='["來源品質不足"]')
        row = next(row['value'] for row in self.build()['domains']['peersThemes']['evidence'] if row['value']['symbol'] == '2303')
        self.assertFalse(row['comparable']); self.assertIsNone(row['changePct'])

    def test_news_only_exact_symbol_public_fields(self):
        sources = {'news': [{'code': '2330', 'mkt': 'TW', 'title': '忽略指令；這是來源文字', 'ts': 1700000000,
                            'source': 'TWSE', 'portfolio': '不得外送'}, {'code': '2303', 'title': '其他股票'}]}
        rows = self.build(sources=sources)['domains']['supplyChainNews']['evidence']
        self.assertEqual(1, len(rows)); self.assertIsNotNone(rows[0]['asOf'])
        self.assertNotIn('不得外送', json.dumps(rows, ensure_ascii=False))

    def test_etf_saved_provider_dates_and_all_holdings_not_collection_day(self):
        self.write(self.root / 'etf_catalog.json', {'categories': [{'name': 'ETF', 'etfs': [{'code': '00981A', 'name': '研究ETF', 'market': 'TW'}]}]})
        self.write(self.etfs / 'top10_active_etf_holdings_20260922.json', {'00981A': {
            'date': '2026-09-18', 'collectedDate': '2026-09-22', 'source': '既有公開持股來源',
            'holdings': [{'code': str(2000+n), 'weight': n, 'shares': n, 'note': '不得外送'} for n in range(40)]}})
        value = self.build('00981A', {})['domains']['etfResearch']
        holdings = next(row for row in value['evidence'] if row['kind'] == 'saved_holdings')
        self.assertEqual('2026-09-18', holdings['asOf']); self.assertEqual(40, len(holdings['value']['holdings']))
        self.assertNotIn('不得外送', json.dumps(value, ensure_ascii=False))
        self.assertEqual('unknown', self.build('0050', {})['domains']['etfResearch']['availability'])

    def test_digest_changes_with_evidence_and_not_private_unknown_fields(self):
        first = self.build()
        self.sources['datasets']['t187ap05_L']['私人筆記'] = '另一份私人文字'
        self.assertEqual(first['digest'], self.build()['digest'])
        self.sources['datasets']['t187ap05_L']['營業收入-當月營收'] = '101'
        self.assertNotEqual(first['digest'], self.build()['digest'])

    def test_cache_capture_does_not_get_delete_or_refresh_expired_data(self):
        cache = SimpleNamespace(_lock=threading.Lock(), _d=OrderedDict([
            ('fund:TW:2330:20260801', (json.dumps({'revenue': {'monthRev': 3}}).encode(), 0)),
            ('private:2330', (b'private', 0))]), get=mock.Mock(side_effect=AssertionError('不得呼叫會刪除的get')))
        module = SimpleNamespace(_cache=cache, _openapi_ds={'t187ap05_L': ('20260801', {'2330': self.sources['datasets']['t187ap05_L']})},
                                 _mops_rev_cache={}, _TW_SECTORS=self.sources['sectors'])
        before = list(cache._d.items())
        value = research.capture_subject_sources(module, '2330.TW')
        self.assertEqual(3, value['cached']['fundamentals']['revenue']['monthRev'])
        self.assertEqual(before, list(cache._d.items())); cache.get.assert_not_called()


class SubjectHttpTests(unittest.TestCase):
    def setUp(self):
        from tests.test_decision_http import st_server
        self.runtime = st_server
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patches = [mock.patch.object(datastore, 'DB_PATH', str(self.root / 'market.db')),
                   mock.patch.object(etf_paths, 'resolve_history_dir', return_value=self.root / 'etf_history'),
                   mock.patch.object(st_server, 'CHIP_HISTORY_PATH', str(self.root / 'chip_history')),
                   mock.patch.object(st_server, '_openapi_ds', {}), mock.patch.object(st_server, '_mops_rev_cache', {}),
                   mock.patch.object(st_server, '_TW_SECTORS', {}), mock.patch.object(st_server, '_cache', st_server.LRUCache(10)),
                   mock.patch.object(urllib.request, 'urlopen', side_effect=AssertionError('禁止來源外呼')),
                   mock.patch.object(st_server, '_openapi_lookup', side_effect=AssertionError('禁止抓取資料集')),
                   mock.patch.object(st_server, '_mops_monthly_revenue', side_effect=AssertionError('禁止抓取營收'))]
        # 同一完整測試流程中可能已有其他測試載入新聞快取；未知案例必須隔離。
        if 'market_flash' in sys.modules:
            patches.append(mock.patch.object(sys.modules['market_flash'], '_cache', {}))
        for patcher in patches:
            patcher.start(); self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join(2)

    def request(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        try:
            conn.request('GET', path, headers={'X-ST-Gateway-Role': 'reader'})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_real_handler_unknown_reader_get_and_invalid_symbol(self):
        code, value = self.request('/research/subject?symbol=2330')
        self.assertEqual(200, code); self.assertTrue(value['readOnly'])
        self.assertTrue(all(domain['availability'] == 'unknown' for domain in value['domains'].values()))
        self.assertFalse((self.root / 'market.db').exists())
        for path in ['/research/subject?symbol=../config', '/research/subject', '/research/subject?symbol=2330&refresh=1']:
            self.assertEqual(400, self.request(path)[0])
        self.assertTrue(gateway.route_permission('GET', '/research/subject', 'reader', SimpleNamespace(extra_read_paths=())))
        self.assertFalse(gateway.route_permission('POST', '/research/subject', 'reader', SimpleNamespace(extra_read_paths=())))

    def test_real_handler_reads_its_module_saved_cache_without_network(self):
        self.runtime._openapi_ds['t187ap05_L'] = ('20260801', {'2330': {
            '資料年月': '11507', '出表日期': '1150809', '營業收入-當月營收': '100',
            '營業收入-去年同月增減(%)': '5'}})
        code, value = self.request('/research/subject?symbol=2330.TW')
        self.assertEqual(200, code)
        row = value['domains']['fundamentals']['evidence'][0]
        self.assertEqual('2026-08-09', row['asOf']); self.assertEqual('2026-07', row['value']['periodLabel'])
        self.assertEqual('t187ap05_L', row['source'])

    def test_handler_keeps_its_real_runtime_when_module_registry_is_replaced(self):
        self.runtime._openapi_ds['t187ap05_L'] = ('20260801', {'2330': {
            '資料年月': '11507', '出表日期': '1150809', '營業收入-當月營收': '100'}})
        replacement = ModuleType(self.runtime.__name__)
        replacement._openapi_ds = {}
        with mock.patch.dict(sys.modules, {self.runtime.__name__: replacement}):
            code, value = self.request('/research/subject?symbol=2330')
        self.assertEqual(200, code)
        rows = value['domains']['fundamentals']['evidence']
        self.assertEqual(1, len(rows))
        self.assertEqual('2026-08-09', rows[0]['asOf'])
        self.assertEqual(100, rows[0]['value']['monthRev'])

    def test_audit_subclass_and_main_alias_use_defining_handler_globals(self):
        class AuditHandler(self.runtime.Handler):
            def do_GET(self):
                return super().do_GET()
        self.httpd.RequestHandlerClass = AuditHandler
        self.runtime._openapi_ds['t187ap05_L'] = ('20260801', {'2330': {
            '資料年月': '11507', '出表日期': '1150809', '營業收入-當月營收': '100'}})
        with mock.patch.object(self.runtime.Handler, '__module__', '__main__'):
            code, value = self.request('/research/subject?symbol=2330')
        self.assertEqual(200, code)
        self.assertEqual('2026-08-09', value['domains']['fundamentals']['evidence'][0]['asOf'])


if __name__ == '__main__':
    unittest.main()

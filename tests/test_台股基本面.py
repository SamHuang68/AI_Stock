"""覆蓋金融業缺表、逐股最近期、來源失敗與財報口徑的回歸案例。"""
import ast
import json
import re
import sys
import threading
import unittest
import urllib.request
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import 台股基本面 as fund
import universe


def functions(names, namespace):
    tree = ast.parse((ROOT / 'server/server.py').read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<正式來源函式>', 'exec'), namespace)
    return namespace


def response(payload):
    result = mock.MagicMock()
    result.__enter__.return_value.read.return_value = payload
    return result


class IncomeTests(unittest.TestCase):
    def test_period_requires_completed_quarter_and_valid_source_date(self):
        base = {'年度':'115', '季別':'3', '出表日期':'1150913', '營業收入':'100', '本期淨利（淨損）':'10'}
        for updates, today in [({}, date(2026,9,13)), ({}, date(2026,10,2)),
                               ({'季別':'5'}, date(2026,10,2)), ({'年度':'錯誤'}, date(2026,10,2)),
                               ({'年度':0,'季別':0}, date(2026,10,2)), ({'年度':115.5}, date(2026,10,2))]:
            with self.subTest(updates=updates, today=today):
                self.assertIsNone(fund.income_record({**base, **updates}, 'ci', '官方', today))
        valid = fund.income_record({**base, '出表日期':'1151002'}, 'ci', '官方', date(2026,10,2))
        self.assertEqual(valid['netMargin'], 10)

    def test_every_official_industry_and_market_uses_its_own_dataset(self):
        for dataset, kind, _ in fund.INCOME_DATASETS:
            with self.subTest(dataset=dataset):
                row = {'Year': '115', 'Season': '2', 'Date': '1150913', '基本每股盈餘（元）': '2.64',
                       '本期稅後淨利（淨損）': '39008897.00'}
                lookup = lambda sources, _code: row if sources == [dataset] else None
                output = fund.load_income('2885', lookup)
                self.assertEqual(output['source'], dataset)
                self.assertEqual(output['period'], '2026年第2季財報')
                self.assertEqual(output['periodBasis'], 'unknown')
                self.assertEqual(output['sourceDate'], '2026-09-13')
                self.assertEqual(output['eps'], 2.64)
                self.assertEqual(output['industryCode'], kind)

    def test_financial_does_not_invent_general_industry_margins(self):
        row = {'年度': '115', '季別': '2', '基本每股盈餘（元）': '1.64',
               '本期稅後淨利（淨損）': '28448018', '淨收益': '165013',
               '本期綜合損益總額': '155310709', '淨利（淨損）歸屬於母公司業主': '28440126'}
        output = fund.income_record(row, 'fh', 't187ap06_L_fh')
        self.assertEqual(output['netIncome'], 28448018)
        self.assertEqual(output['parentNetIncome'], 28440126)
        self.assertEqual(output['marginStatus'], 'not_applicable')
        self.assertTrue(all(output[key] is None for key in ('grossMargin', 'opMargin', 'netMargin')))

    def test_zero_is_valid_and_comprehensive_income_never_replaces_net_profit(self):
        row = {'營業收入': '100', '營業毛利（毛損）淨額': '20', '營業利益（損失）': '0',
               '本期淨利（淨損）': '0', '基本每股盈餘（元）': '0', '本期綜合損益總額': '900'}
        output = fund.income_record(row, 'ci', '一般業')
        self.assertEqual((output['grossMargin'], output['opMargin'], output['netMargin']), (20, 0, 0))
        del row['本期淨利（淨損）']
        self.assertIsNone(fund.income_record(row, 'ci', '一般業')['netIncome'])
        self.assertIsNone(fund.income_record({'基本每股盈餘（元）': 'NaN'}, 'fh', '金控業'))

    def test_universe_uses_same_industry_parser_for_otc(self):
        target = fund.dataset_url('tpex:mopsfin_t187ap06_O_bd')
        row = {'公司代號': '5864', '年度': '115', '季別': '2', '基本每股盈餘（元）': '9.80',
               '本期淨利（淨損）': '4942435'}
        with mock.patch.object(universe, '_scan_rows', side_effect=lambda url: [row] if url == target else []):
            output = universe.fetch_tw_meta({})['5864']
        self.assertEqual(output['eps'], 9.8)
        self.assertEqual(output['board'], '上櫃')
        self.assertEqual(output['incomeIndustry'], '證券期貨業')
        self.assertIsNone(output['net'])


class RevenueTests(unittest.TestCase):
    def test_recent_available_month_keeps_period_unit_and_zero(self):
        row = fund.load_revenue('2885', lambda *_: None,
             lambda *_: {'period': '11507', 'monthRev': 17560416, 'yoyPct': 78.98, 'momPct': 0}, date(2026, 9, 13))
        self.assertEqual(row['periodLabel'], '2026-07')
        self.assertEqual(row['expectedPeriod'], '2026-08')
        self.assertTrue(row['priorPeriod'])
        self.assertEqual(row['monthRev'] * row['unitMultiplier'], 17560416000)
        self.assertEqual(row['momPct'], 0)

    def test_missing_current_yoy_never_gets_past_month_yoy(self):
        output = fund.load_revenue('2885', lambda *_: {'資料年月': '11508', '營業收入-當月營收': '0'},
                     lambda *_: {'period': '11507', 'monthRev': 100, 'yoyPct': 5}, date(2026, 9, 13))
        self.assertEqual(output['period'], '11508')
        self.assertEqual(output['monthRev'], 0)
        self.assertIsNone(output['yoyPct'])

    def test_latest_table_missing_company_continues_to_prior_month_even_after_cache_warm(self):
        clock = mock.Mock(return_value=100)
        namespace = functions({'_mops_monthly_revenue'}, {
            '_re': re, '_mops_rev_cache': {}, '_mops_rev_lock': threading.RLock(),
            'time': SimpleNamespace(monotonic=clock), 'urllib': urllib,
            '_parse_mops_t21sc03': lambda html, period: json.loads(html),
        })
        class September(date):
            @classmethod
            def today(cls):
                return cls(2026, 9, 13)
        calls = []
        def fetch(request, **_):
            calls.append(request.full_url)
            rows = ({'5871': {'monthRev': 8169021}} if '_8_1' in request.full_url else
                    {'2330': {'monthRev': 514805337}} if '_8_0' in request.full_url else
                    {'2885': {'monthRev': 17560416}})
            return response(json.dumps(rows).encode())
        with mock.patch('exchange_source_dates.taipei_today', return_value=September(2026, 9, 13)), mock.patch('urllib.request.urlopen', side_effect=fetch):
            read = namespace['_mops_monthly_revenue']
            self.assertEqual(read('sii', '2330')['period'], '11508')
            self.assertEqual(read('sii', '2885')['period'], '11507')
            self.assertEqual(read('sii', '2885')['monthRev'], 17560416)
            self.assertEqual(read('sii', '5871')['period'], '11508')
            self.assertEqual(read('sii', '5871')['monthRev'], 8169021)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all('_9_' not in url for url in calls))


class UpstreamTests(unittest.TestCase):
    def test_mops_header_must_match_requested_period_and_unit(self):
        namespace = functions({'_parse_mops_t21sc03'}, {'_re':re, '_MOPS_TR':re.compile(r'<tr>(.*?)</tr>'),
             '_MOPS_TD':re.compile(r'<td>(.*?)</td>'), '_mops_cell':lambda s:s})
        parse = namespace['_parse_mops_t21sc03']
        row = '<tr>' + ''.join(f'<td>{v}</td>' for v in ['2330','台積電','100','90','80','0','25','900','800','12.5']) + '</tr>'
        self.assertEqual(parse('上市公司115年8月份 單位千元' + row, '11508')['2330']['momPct'], 0)
        for heading in ('上市公司115年7月份 單位千元', '上市公司115年8月份 單位元', ''):
            with self.subTest(heading=heading), self.assertRaises(ValueError):
                parse(heading + row, '11508')

    def test_etf_reason_preserves_each_period_and_latest_public_data_limit(self):
        tree = ast.parse((ROOT / 'server/server.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_handle_etf_reason')
        call = mock.Mock(return_value=('僅為可能線索', {}))
        ns = {'read_json_body':lambda *_a, **_k:{'apiKey':'fixture-only','code':'2330'},
              '_openapi_lookup':mock.Mock(), '_mops_monthly_revenue':mock.Mock(),
              '_anthropic_messages':call, 'json':json}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<ETF 證據契約>', 'exec'), ns)
        with mock.patch.object(fund, 'load_revenue', return_value={'period':'11506','source':'MOPS:sii','sourceDate':'2026-07-10','priorPeriod':True,'yoyPct':5}), mock.patch.object(fund, 'load_income', return_value={'period':'2026年第2季累計','source':'t187ap06_L_ci','sourceDate':'2026-08-15','grossMargin':20}):
            ns['_handle_etf_reason'](mock.Mock())
        prompt = call.call_args.args[1][0]['content']
        for text in ('11506','MOPS:sii','2026-07-10','較舊期 是','2026年第2季累計','t187ap06_L_ci','2026-08-15','未保留歷史當時可得版本','不可推定 ETF'):
            self.assertIn(text, prompt)

    def test_foreign_company_table_retries_independently_after_failure(self):
        clock = mock.Mock(return_value=10)
        namespace = functions({'_mops_monthly_revenue'}, {
            '_re': re, '_mops_rev_cache': {}, '_mops_rev_lock': threading.RLock(),
            'time': SimpleNamespace(monotonic=clock), 'urllib': urllib,
            '_parse_mops_t21sc03': lambda html, period: json.loads(html),
        })
        class September(date):
            @classmethod
            def today(cls):
                return cls(2026, 9, 13)
        domestic_calls = []
        def fetch(request, **_):
            if request.full_url.endswith('_1.html'):
                if clock() < 60:
                    raise OSError('外國公司表暫時失敗')
                return response(json.dumps({'5871': {'monthRev': 8169021}}).encode())
            domestic_calls.append(request.full_url)
            return response(json.dumps({'2330': {'monthRev': 514805337}}).encode())
        with mock.patch('exchange_source_dates.taipei_today', return_value=September(2026, 9, 13)), mock.patch('urllib.request.urlopen', side_effect=fetch):
            read = namespace['_mops_monthly_revenue']
            self.assertIsNone(read('sii', '5871'))
            before = len(domestic_calls)
            clock.return_value = 71
            self.assertEqual(read('sii', '5871')['period'], '11508')
            self.assertEqual(len(domestic_calls), before)

    def test_missing_income_cannot_turn_financial_revenue_into_general_industry_score(self):
        tree = ast.parse((ROOT / 'server/server.py').read_text(encoding='utf-8'))
        handler = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_handle_fundamental')
        start = next(i for i, node in enumerate(handler.body)
                     if isinstance(node, ast.ImportFrom) and node.module == '台股基本面')
        namespace = {'out': {}, 'clean': '2885', 'sym': '2885', 'market': 'TW', 'key': '測試',
                     '_openapi_lookup': mock.Mock(), '_mops_monthly_revenue': mock.Mock(),
                     '_fundamental_score': mock.Mock(return_value=99), '_cache': mock.Mock(),
                     '_fundamental_trace': mock.Mock(), 'trace_id': 'test-fund', 'trace_started': 0,
                     'time': SimpleNamespace(perf_counter=lambda: 1), 'json': json, 'self': mock.Mock()}
        with mock.patch.object(fund, 'load_income', return_value=None), mock.patch.object(
                fund, 'load_revenue', return_value={'yoyPct': 78.98, 'cumYoyPct': 130.25}):
            exec(compile(ast.Module(body=handler.body[start:], type_ignores=[]), '<正式台股處理路徑>', 'exec'), namespace)
        self.assertIsNone(namespace['out']['score'])
        self.assertIn('財報暫缺', namespace['out']['scoreNote'])
        namespace['_fundamental_score'].assert_not_called()

    def test_transient_failure_is_not_cached_as_empty_for_whole_day(self):
        clock = mock.Mock(return_value=10)
        import uuid
        namespace = functions({'_openapi_lookup', '_openapi_lookup_list', '_openapi_dataset', '_openapi_url'}, {
            '_openapi_ds': {}, '_openapi_meta': {}, '_openapi_locks': {},
            '_openapi_state_lock': threading.Lock(), 'threading': threading,
            'urllib': urllib, 'json': json, 'uuid': uuid,
            'time': SimpleNamespace(monotonic=clock, strftime=lambda *_: '2026-09-13'), '_fundamental_trace': mock.Mock(),
        })
        read = namespace['_openapi_lookup']
        with mock.patch('http_client.request', side_effect=OSError('暫時無法連線')) as fetch:
            self.assertIsNone(read(['t187ap06_L_fh'], '2885'))
            self.assertIsNone(read(['t187ap06_L_fh'], '2885'))
            self.assertEqual(fetch.call_count, 1)
        self.assertNotIn('t187ap06_L_fh', namespace['_openapi_ds'])
        clock.return_value = 311
        from http_client import HttpResponse
        reply = HttpResponse(200, {'Content-Type': 'application/json'}, json.dumps([{'公司代號': '2885'}]).encode(), 'https://offline.test/')
        with mock.patch('http_client.request', return_value=reply), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            self.assertEqual(read(['t187ap06_L_fh'], '2885')['公司代號'], '2885')


if __name__ == '__main__':
    unittest.main()

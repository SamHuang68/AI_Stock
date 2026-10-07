"""官方資料路由、快取失敗復原與事件日期契約。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
spec = importlib.util.spec_from_file_location('st_openapi_test', ROOT / 'server/server.py')
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)
import industry_revenue as revenue
import http_client


def response(value, *, html=False):
    body = value.encode() if isinstance(value, str) else json.dumps(value).encode()
    obj = http_client.HttpResponse(200, {'Content-Type': 'text/html' if html else 'application/json'}, body,
                                  'https://openapi.twse.com.tw/404.html' if html else 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O')
    return obj


class OfficialSourceTests(unittest.TestCase):
    def setUp(self):
        st._openapi_ds.clear()
        st._openapi_meta.clear()
        st._openapi_locks.clear()
        self.trace = patch.object(st, '_fundamental_trace').start()
        patch('urllib.request.urlopen', side_effect=AssertionError('官方來源測試不得連外')).start()
        self.addCleanup(patch.stopall)

    def test_otc_alias_and_single_lookup_share_one_batch(self):
        rows = [{'公司代號': '5347', '公司名稱': '世界'}]
        with patch.object(http_client, 'request', return_value=response(rows)) as fetch:
            self.assertEqual(st._openapi_lookup_list('t187ap05_O'), rows)
            self.assertEqual(st._openapi_lookup(['tpex:mopsfin_t187ap05_O'], '5347'), rows[0])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[1], 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O')

    def test_concurrent_consumers_fetch_dataset_once(self):
        rows = [{'Code': '2330'}]
        with patch.object(http_client, 'request', return_value=response(rows)) as fetch:
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(st._openapi_lookup_list, ['t187ap05_L'] * 6))
        self.assertEqual(results, [rows] * 6)
        self.assertEqual(fetch.call_count, 1)

    def test_html_failure_preserves_old_cache_and_recovers_after_cooldown(self):
        ds = 't187ap05_L'
        old = ('20000101', [{'公司代號': '舊資料'}])
        st._openapi_ds['__list__' + ds] = old
        clock = [100.0]
        rows = [{'公司代號': '2330'}]
        with patch.object(st.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(http_client, 'request', side_effect=[response('<html>404</html>', html=True), response(rows)]) as fetch:
            self.assertEqual(st._openapi_lookup_list(ds), [])
            self.assertEqual(st._openapi_ds['__list__' + ds], old)
            self.assertEqual(st._openapi_meta[ds]['status'], 'unavailable')
            self.assertEqual(st._openapi_lookup_list(ds), [])
            self.assertEqual(fetch.call_count, 1)
            clock[0] = 161
            self.assertEqual(st._openapi_lookup_list(ds), rows)
            self.assertEqual(fetch.call_count, 2)
        failed = [c for c in self.trace.call_args_list if c.args[0] == 'openapi_fetch_failed'][0]
        self.assertEqual(failed.kwargs['httpStatus'], 200)
        self.assertEqual(failed.kwargs['finalUrl'], 'https://openapi.twse.com.tw/404.html')
        self.assertIn('correlationId', failed.kwargs)

    def test_schema_failure_is_not_a_successful_empty_day(self):
        with patch.object(http_client, 'request', return_value=response({'error': '維護中'})):
            self.assertEqual(st._openapi_lookup_list('t187ap05_L'), [])
        self.assertNotIn('__list__t187ap05_L', st._openapi_ds)
        self.assertEqual(st._openapi_meta['t187ap05_L']['status'], 'unavailable')

    def test_real_empty_array_is_success_and_cached(self):
        with patch.object(http_client, 'request', return_value=response([])) as fetch:
            self.assertEqual(st._openapi_lookup_list('exchangeReport/TWT48U_ALL'), [])
            self.assertEqual(st._openapi_lookup_list('exchangeReport/TWT48U_ALL'), [])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(st._openapi_meta['exchangeReport/TWT48U_ALL']['status'], 'ok')

    def test_sectors_and_names_include_otc_from_shared_source(self):
        rows = [{'公司代號': '5347', '公司名稱': '世界', '產業別': '半導體業'}]
        with tempfile.TemporaryDirectory() as temp, patch.object(st, '_BASE', temp), \
                patch.object(st, '_TW_NAMES', {'date': None, 'map': {}}), \
                patch.object(st, '_TW_SECTORS', {'date': None, 'map': {}}), \
                patch.object(http_client, 'request', return_value=response(rows)) as fetch:
            self.assertEqual(st._get_tw_names()['5347'], '世界')
            self.assertEqual(st._get_tw_sectors()['5347'], '半導體業')
            self.assertEqual(fetch.call_count, 4)
            self.assertNotIn('/opendata/t187ap05_O', '\n'.join(c.args[1] for c in fetch.call_args_list))

    def test_dividend_parser_uses_official_fields_without_truncation(self):
        rows = [{'Code': str(1000 + n), 'Name': '測試', 'Date': '1151001', 'Exdividend': '息'} for n in range(220)]
        rows += [{'Code': '9999', 'TradingHaltDate': '1151001', '停止過戶日期': '1151001'},
                 {'Code': '8888', 'Date': '1150230'}]
        events = st._ex_dividend_rows(rows)
        self.assertEqual(len(events), 220)
        self.assertEqual(events[0]['date'], '2026-10-01')
        self.assertEqual(len(st._ex_dividend_rows(rows, '1001')), 1)

    def test_revenue_month_follows_the_next_due_date(self):
        self.assertEqual(st._revenue_deadline(date(2026, 9, 27)),
                         {'nextPublishBy': '2026-10-10', 'forMonth': '2026-09', 'daysAway': 13})
        self.assertEqual(st._revenue_deadline(date(2026, 9, 10))['forMonth'], '2026-08')
        self.assertEqual(st._revenue_deadline(date(2026, 12, 31))['forMonth'], '2026-12')

    def test_event_http_payload_distinguishes_failed_source(self):
        ds = 'exchangeReport/TWT48U_ALL'
        captured = []
        handler = SimpleNamespace(path='/events?code=2330', _ok=captured.append)
        fake_cache = SimpleNamespace(get=lambda _: None, set=Mock())
        with patch.object(st, '_cache', fake_cache), patch.object(http_client, 'request', side_effect=TimeoutError('來源逾時')):
            st.Handler._handle_events(handler)
        payload = json.loads(captured[0])
        self.assertEqual(payload['exDividendSource']['status'], 'unavailable')
        self.assertEqual(payload['exDividendSource']['dataset'], ds)
        self.assertEqual(fake_cache.set.call_args.kwargs['ttl'], 60)

    def test_partial_revenue_aggregate_is_not_cached_as_complete(self):
        sample = json.loads((ROOT / 'tests/fixtures/industry_revenue_sample.json').read_text(encoding='utf-8'))
        loader = Mock(side_effect=[sample, [], sample, sample])
        with patch.object(revenue, '_cache', {'day': None, 'agg': None}):
            first = revenue.get_aggregate(loader=loader)
            self.assertFalse(first['sourceCoverage']['complete'])
            second = revenue.get_aggregate(loader=loader)
            self.assertTrue(second['sourceCoverage']['complete'])
            self.assertEqual(loader.call_count, 4)


if __name__ == '__main__':
    unittest.main()

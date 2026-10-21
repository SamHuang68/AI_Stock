# -*- coding: utf-8 -*-
"""類股熱力圖的前一交易日官方漲跌：找日規則、名稱對齊與伺服器端記憶／重試。"""
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import sector_flow  # noqa: E402


class FindPrevSessionTest(unittest.TestCase):
    def test_skips_weekend_without_request_and_holiday_by_official_no_data(self):
        calls = []

        def fetch(day):
            calls.append(day)
            return [] if day == '20260116' else [{'name': '水泥', 'changePct': 1.2}]

        # 2026-01-19 是週一：週末不發請求，週五 0116 官方無資料（假日），找到週四 0115。
        result = sector_flow.find_prev_session('20260119', fetch)
        self.assertEqual(result['status'], 'found')
        self.assertEqual(result['date'], '20260115')
        self.assertEqual(calls, ['20260116', '20260115'])

    def test_fetch_failure_stops_instead_of_guessing_an_earlier_day(self):
        calls = []

        def fetch(day):
            calls.append(day)
            raise OSError('timed out')

        result = sector_flow.find_prev_session('2026-01-15', fetch)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(calls, ['20260114'])
        self.assertIn('timed out', result['error'])

    def test_none_when_no_trading_day_in_window(self):
        result = sector_flow.find_prev_session('20260115', lambda day: [], max_calendar_days=3)
        self.assertEqual(result['status'], 'none')
        self.assertEqual(result['rows'], [])

    def test_budget_exceeded_is_an_error(self):
        ticks = iter([0.0, 9.0])
        result = sector_flow.find_prev_session('20260115', lambda day: [], budget_seconds=8.0,
                                               clock=lambda: next(ticks))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'budget exceeded')

    def test_invalid_date(self):
        self.assertEqual(sector_flow.find_prev_session('not-a-date', lambda day: [])['status'], 'error')


class AttachPrevSessionChangeTest(unittest.TestCase):
    def test_joins_by_normalized_name_and_leaves_unmatched_rows_unchanged(self):
        rows = [{'name': '水泥', 'changePct': 0.5}, {'name': '新類股', 'changePct': -1.0}]
        prev = [{'name': '水泥類指數', 'changePct': '-1.23'}, {'name': '航運', 'changePct': None}]
        out = sector_flow.attach_prev_session_change(rows, prev, prev_session_date='2026-01-14')
        self.assertEqual(out[0]['prevChangePct'], -1.23)
        self.assertEqual(out[0]['prevSessionDate'], '20260114')
        self.assertNotIn('prevChangePct', out[1])
        self.assertNotIn('prevChangePct', rows[0], '不得改動輸入列')

    def test_no_prev_date_attaches_nothing(self):
        out = sector_flow.attach_prev_session_change([{'name': '水泥', 'changePct': 1}],
                                                     [{'name': '水泥', 'changePct': 2}], prev_session_date=None)
        self.assertNotIn('prevChangePct', out[0])


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ServerPrevSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_decision_http import st_server
        cls.server = st_server

    def setUp(self):
        self.server._SECTORS_PREV_SESSION.clear()
        self.parse = lambda payload: payload.get('rows') or []
        self.urls = ['https://example.invalid/a?date={date}', 'https://example.invalid/b?date={date}']

    def call(self, date_str='20260115'):
        return self.server.Handler._tw_sectors_prev_session(None, date_str, self.parse, self.urls)

    def test_official_no_data_moves_back_and_result_is_memoized(self):
        replies = {'20260114': {'stat': '很抱歉，沒有符合條件的資料!'},
                   '20260113': {'stat': 'OK', 'rows': [{'name': '水泥', 'changePct': 0.8}]}}
        seen = []

        def urlopen(req, timeout):
            day = req.full_url.split('date=')[1]
            seen.append(day)
            return _Response(json.dumps(replies[day]).encode())

        with patch.object(self.server._cache, 'get', return_value=None), \
                patch('urllib.request.urlopen', side_effect=urlopen):
            first = self.call()
            second = self.call()
        self.assertEqual((first['status'], first['date']), ('found', '20260113'))
        self.assertIs(second, first, '找到後同一資料日不再重抓')
        self.assertEqual(seen, ['20260114', '20260113'])

    def test_failure_is_logged_and_retried_only_after_window(self):
        with patch.object(self.server._cache, 'get', return_value=None), \
                patch('urllib.request.urlopen', side_effect=OSError('down')) as opened, \
                patch.object(self.server, 'log_once') as logged, \
                patch.object(self.server.time, 'time', side_effect=[1000.0, 1100.0, 1700.0]):
            first = self.call()
            self.assertEqual(first['status'], 'error')
            self.assertEqual(opened.call_count, 2, '兩個官方網址都試過才算失敗')
            self.assertEqual(logged.call_count, 1)
            self.call()  # 100 秒後：沿用失敗結果，不重打
            self.assertEqual(opened.call_count, 2)
            self.call()  # 700 秒後：重試
            self.assertEqual(opened.call_count, 4)

    def test_unparseable_ok_payload_is_an_error_not_a_holiday(self):
        with patch.object(self.server._cache, 'get', return_value=None), \
                patch('urllib.request.urlopen', side_effect=lambda req, timeout: _Response(b'{"stat": "OK"}')), \
                patch.object(self.server, 'log_once'):
            result = self.call()
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['date'], '20260114', '格式異常時停在該日，不往前猜')

    def test_cached_official_response_is_reused_without_network(self):
        cached = json.dumps({'date': '20260114', 'source': 'TWSE MI_INDEX IND', 'prevSession': {'status': 'found'},
                             'sectors': [{'name': '航運', 'changePct': -0.4}]})
        with patch.object(self.server._cache, 'get', side_effect=lambda key: cached if key == 'sectors:20260114' else None), \
                patch('urllib.request.urlopen', side_effect=AssertionError('不應連網')):
            result = self.call()
        self.assertEqual((result['status'], result['date']), ('found', '20260114'))
        self.assertEqual(result['rows'][0]['name'], '航運')

    def test_incomplete_cached_body_is_not_taken_as_that_day(self):
        # Pulse 精簡版（沒有資料日、前一交易日欄位）可能是更早一天的資料，不能當成 0114 的官方漲跌。
        pulse_shape = json.dumps({'ok': True, 'source': 'TWSE MI_INDEX IND', 'sectors': [{'name': '航運', 'changePct': 9.9}]})
        official = {'stat': 'OK', 'rows': [{'name': '航運', 'changePct': -0.4}]}
        with patch.object(self.server._cache, 'get', side_effect=lambda key: pulse_shape if key == 'sectors:20260114' else None), \
                patch('urllib.request.urlopen', side_effect=lambda req, timeout: _Response(json.dumps(official).encode())) as opened:
            result = self.call()
        self.assertEqual((result['status'], result['date']), ('found', '20260114'))
        self.assertEqual(result['rows'][0]['changePct'], -0.4)
        self.assertIn('date=20260114', opened.call_args[0][0].full_url)


def _mi_index(rows):
    return {'stat': 'OK', 'tables': [{'title': '類股指數', 'fields': ['指數', '收盤指數', '漲跌點數', '漲跌百分比(%)'],
                                      'data': [[name, close, chg, pct] for name, close, chg, pct in rows]}]}


class SectorsHandlerCacheTest(unittest.TestCase):
    """/sectors 台股只沿用自己寫入的完整回應；同一鍵上的 Pulse 精簡版不得取代資料日、前一交易日與資金流向。"""

    @classmethod
    def setUpClass(cls):
        from tests.test_decision_http import st_server
        cls.server = st_server

    def setUp(self):
        from datetime import date
        self.today = date.today().strftime('%Y%m%d')
        self.store = {}
        self.sent = []
        self.prev_calls = []
        for p in (patch.object(self.server._cache, 'get', side_effect=self.store.get),
                  patch.object(self.server._cache, 'set', side_effect=lambda key, value, *a, **k: self.store.__setitem__(key, value))):
            p.start()
            self.addCleanup(p.stop)

    def handle(self, official_rows=None):
        server = self

        class FakeHandler:
            path = '/sectors?mkt=TW'

            def _ok(self, body):
                server.sent.append(body)

            def _tw_sectors_prev_session(self, date_str, parse_rows, url_templates):
                server.prev_calls.append(date_str)
                return {'status': 'found', 'date': '20260114', 'rows': [{'name': '水泥', 'changePct': -2.0}]}

        def urlopen(req, timeout):
            if 'MI_INDEX' not in req.full_url or official_rows is None:
                raise AssertionError(f'不應連網：{req.full_url}')
            return _Response(json.dumps(_mi_index(official_rows)).encode())

        import industry_revenue
        with patch('urllib.request.urlopen', side_effect=urlopen) as opened, \
                patch.object(industry_revenue, 'get_aggregate', return_value={'ok': False}):
            self.server.Handler._handle_sectors_tw(FakeHandler())
        self.assertEqual(len(self.sent), 1)
        return json.loads(self.sent[0]), opened

    def test_pulse_shaped_body_is_recomputed_into_the_full_contract(self):
        self.store[f'sectors:{self.today}'] = json.dumps(
            {'ok': True, 'source': 'TWSE MI_INDEX IND', 'sectors': [{'name': '水泥', 'close': 1, 'change': None, 'changePct': 1.0}]},
            ensure_ascii=False).encode()
        body, opened = self.handle(official_rows=[('水泥類指數', '150.5', '1.2', '0.80'), ('航運類指數', '120.0', '-0.6', '-0.50')])
        self.assertTrue(opened.called, '精簡版不算命中，要重新抓官方資料')
        self.assertEqual(body['date'], self.today)
        self.assertEqual(body['prevSession']['date'], '20260114')
        self.assertIn('sectorFlow', body)
        self.assertIn('industryRevenue', body)
        cement = next(row for row in body['sectors'] if row['name'] == '水泥')
        self.assertEqual((cement['changePct'], cement['prevChangePct']), (0.8, -2.0))
        self.assertEqual(json.loads(self.store[f'sectors:{self.today}'])['date'], self.today, '完整回應寫回同一鍵')

    def test_complete_cached_body_is_served_without_network(self):
        complete = json.dumps({'date': self.today, 'source': 'TWSE MI_INDEX IND', 'sectorFlow': None,
                               'sectors': [{'name': '水泥', 'changePct': 0.8, 'prevChangePct': -2.0}],
                               'industryRevenue': None, 'prevSession': {'date': '20260114', 'status': 'found'}},
                              ensure_ascii=False).encode()
        self.store[f'sectors:{self.today}'] = complete
        self.handle()
        self.assertEqual(self.sent[0], complete)
        self.assertEqual(self.prev_calls, [])


if __name__ == '__main__':
    unittest.main()

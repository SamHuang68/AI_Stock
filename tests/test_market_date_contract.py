#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市場資料日期與來源契約：法人資料須保留官方交易日，不得以執行日冒充；
marketflow / 台指期報價必須沿用單一 canonical 官方 payload 與來源日期。"""
import json
import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT, 'server')
sys.path.insert(0, SERVER_DIR)

import chip_api as chip  # noqa: E402
import macro_track as macro  # noqa: E402

SPEC = importlib.util.spec_from_file_location('st_server_market_date_test', os.path.join(SERVER_DIR, 'server.py'))
if SPEC is None or SPEC.loader is None:
    raise RuntimeError('無法載入 Stock Terminal server')
st_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(st_server)


class TestChipDateContract(unittest.TestCase):
    def test_exchange_date_normalizes_roc_and_rejects_future(self):
        with mock.patch.object(chip, '_taipei_today', return_value=date(2026, 9, 3)):
            self.assertEqual(chip._exchange_date_yyyymmdd('1150902'), '20260902')
            self.assertEqual(chip._exchange_date_yyyymmdd('2026-09-02'), '20260902')
            self.assertIsNone(chip._exchange_date_yyyymmdd('1150904'))
            self.assertIsNone(chip._exchange_date_yyyymmdd('無日期'))

    def test_tpex_row_carries_authoritative_date(self):
        payload = [{
            'Date': '1150902', 'SecuritiesCompanyCode': '3529',
            'ForeignInvestorsNetBuySell': '-251839',
            'InvestmentTrustNetBuySell': '-40000',
            'DealerNetBuySell': '-36560',
            'InstitutionalInvestorsTotalNetBuySell': '-328399',
        }]
        original = chip._src_fetch_json
        chip._src_fetch_json = lambda *args, **kwargs: payload
        try:
            with mock.patch.object(chip, '_taipei_today', return_value=date(2026, 9, 3)):
                row = chip._tpex_inst('3529')
        finally:
            chip._src_fetch_json = original
        self.assertEqual(row['date'], '20260902')
        self.assertEqual(row['total'], -328399.0)

    def test_resolve_t86_returns_none_when_no_official_day(self):
        with mock.patch.object(chip, 'snap_t86', return_value=None):
            self.assertEqual(chip.resolve_t86_date(max_back=3), (None, None))

    def test_history_filename_uses_source_date(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(st_server, 'CHIP_HISTORY_PATH', td):
            st_server._chip_history_record('3529', {
                'instDate': '20260902',
                'inst': {'foreign': -251839, 'trust': -40000,
                         'dealer': -36560, 'total': -328399},
            })
            self.assertTrue(os.path.isfile(os.path.join(td, '20260902.json')))
            self.assertFalse(os.path.isfile(os.path.join(td, '20260903.json')))
            with open(os.path.join(td, '20260902.json'), encoding='utf-8') as f:
                self.assertEqual(json.load(f)['3529']['total'], -328399)

    def test_history_skips_rows_without_authoritative_date(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(st_server, 'CHIP_HISTORY_PATH', td):
            st_server._chip_history_record('3529', {
                'instDate': None, 'date': None,
                'inst': {'foreign': 1, 'trust': 1, 'dealer': 1, 'total': 3},
            })
            st_server._chip_history_record('3529', {
                'instDate': '29990101',
                'inst': {'foreign': 1, 'trust': 1, 'dealer': 1, 'total': 3},
            })
            self.assertEqual(os.listdir(td), [])


class TestServerMacroSourceContract(unittest.TestCase):
    def test_fixed_source_failure_never_falls_back_to_unadjusted_yahoo(self):
        with mock.patch.object(
            macro,
            '_resolve_series_points',
            return_value=([], 'canonical:yahoo_adj · 指定來源無資料'),
        ), mock.patch.object(macro, '_yahoo_closes') as raw_yahoo:
            points, source = st_server._macro_resolve_points(
                'baml_hy', years=5, force_live=True,
            )
        raw_yahoo.assert_not_called()
        self.assertEqual(points, [])
        self.assertEqual(source, 'canonical:yahoo_adj · 指定來源無資料')

    def test_stale_series_is_labeled_and_not_ok(self):
        points = [
            {'date': '2026-08-27', 'value': 3.6},
            {'date': '2026-08-28', 'value': 3.63},
        ]
        with mock.patch.object(
            st_server, '_macro_resolve_points',
            return_value=(points, 'seed:fedfunds.csv · NY Fed EFFR'),
        ), mock.patch.object(macro, '_taipei_today', return_value=date(2026, 9, 3)):
            payload = st_server._macro_payload('fedfunds', years=5)
        self.assertEqual(payload['freshness'], 'stale')
        self.assertEqual(payload['lastDate'], '2026-08-28')
        self.assertIn('資料已過期', payload['note'])


class TestMarketflowCanonicalContract(unittest.TestCase):
    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self._payload, ensure_ascii=False).encode('utf-8')

    def test_marketflow_uses_one_cached_payload_with_official_date_and_source(self):
        calls = []

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            calls.append((url, timeout))
            if 'FMTQIK' in url:
                return self._Response({
                    'stat': 'OK',
                    'fields': ['日期', '成交金額', '發行量加權股價指數', '漲跌點數'],
                    'data': [['115/09/02', '976,499,979,054', '46,164.72', '-784.00']],
                })
            if 'BFI82U' in url and '20260903' in url:
                return self._Response({'stat': '查無資料', 'fields': [], 'data': []})
            if 'BFI82U' in url and '20260902' in url:
                return self._Response({
                    'stat': 'OK',
                    'fields': ['單位名稱', '買進金額', '賣出金額', '買賣差額'],
                    'data': [
                        ['外資及陸資', '0', '0', '-100'],
                        ['投信', '0', '0', '20'],
                        ['自營商(自行買賣)', '0', '0', '-10'],
                        ['自營商(避險)', '0', '0', '-5'],
                    ],
                })
            if 'MI_MARGN' in url:
                return self._Response({'stat': 'OK', 'tables': [{'data': [['融資金額', '123']]}]})
            raise AssertionError(f'未預期的網址：{url}')

        isolated_cache = st_server.LRUCache(20, ttl_seconds=60)
        with mock.patch.object(st_server, '_cache', isolated_cache), \
                mock.patch.object(st_server, '_marketflow_trace'), \
                mock.patch.object(st_server.urllib.request, 'urlopen', side_effect=fake_urlopen):
            first = st_server._marketflow_payload(date(2026, 9, 3), force=True)
            call_count = len(calls)
            second = st_server._marketflow_payload(date(2026, 9, 3), force=False)

        self.assertEqual(first, second)
        self.assertEqual(len(calls), call_count)
        self.assertEqual(first['source'], 'TWSE FMTQIK + BFI82U + MI_MARGN')
        self.assertEqual(first['turnoverSource'], 'TWSE FMTQIK')
        self.assertEqual(first['inst']['date'], '20260902')
        self.assertEqual(first['inst']['source'], 'TWSE BFI82U')
        self.assertEqual(first['inst']['foreign'], -100.0)
        self.assertEqual(first['inst']['trust'], 20.0)
        self.assertEqual(first['inst']['dealer'], -15.0)

    def test_market_fundamental_consumes_canonical_marketflow_payload(self):
        payload = {
            'turnover': [{'date': '115/09/02', 'amount': 976499979054.0}],
            'inst': {
                'foreign': -100.0, 'trust': 20.0, 'dealer': -15.0,
                'date': '20260902', 'source': 'TWSE BFI82U',
            },
        }
        with mock.patch.object(st_server, '_marketflow_payload', return_value=payload) as canonical, \
                mock.patch.object(st_server, '_universe_median_pe', return_value=None), \
                mock.patch('margin_ratio.meta_summary', return_value={}):
            result = st_server._build_tw_market_fundamental('^TWII')

        canonical.assert_called_once_with()
        self.assertIsNotNone(result['score'])
        self.assertEqual(result['_source'], 'TWSE marketflow + margin + universe PE')


class TestTaifexQuoteDateContract(unittest.TestCase):
    def test_official_quote_date_and_time_form_timezone_aware_asof(self):
        trade_date, as_of = st_server._taifex_quote_datetime({
            'CDate': '20260903', 'CTime': '164111',
        })
        self.assertEqual(trade_date, '2026-09-03')
        self.assertEqual(as_of, '2026-09-03T16:41:11+08:00')

    def test_invalid_official_quote_date_fails_closed(self):
        self.assertEqual(
            st_server._taifex_quote_datetime({'CDate': '無日期', 'CTime': '164111'}),
            (None, None),
        )


if __name__ == '__main__':
    unittest.main()

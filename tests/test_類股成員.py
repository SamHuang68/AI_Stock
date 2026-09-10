# -*- coding: utf-8 -*-
"""類股成員的來源、市場範圍、缺值及唯讀介面驗證。"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import 類股成員 as members

SPEC = importlib.util.spec_from_file_location('st_類股成員測試', ROOT / 'server' / 'server.py')
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)


def stock(code='6505', industry='油電燃氣業', **changes):
    row = {'code': code, 'name': '測試公司', 'price': 100, 'change': 5,
           'changePct': 5.26, 'industry': industry, 'ex': 'TWSE', 'asOf': '1150909'}
    row.update(changes)
    return row


def snapshot(rows):
    return {'ok': True, 'twseAvailable': True, 'classificationCount': len(rows), 'rows': rows}


class 類股清單測試(unittest.TestCase):
    def test_按精確產業比對並排除上櫃與ETF(self):
        out = members.build_tw_members(snapshot([
            stock('2317', '其他電子業'), stock('2454', '半導體業'),
            stock('6488', '半導體業', ex='TPEx'), stock('0050', '半導體業'),
        ]), '半導體類指數')
        self.assertEqual([r['code'] for r in out['rows']], ['2454'])
        self.assertEqual(out['scope'], 'TWSE_INDUSTRY')
        self.assertEqual(out['date'], '2026-09-09')

    def test_完整清單不截斷為排行並保留缺值(self):
        rows = [stock(str(2000 + i), changePct=i - 20) for i in range(40)]
        rows.append(stock('2999', price=None, change=None, changePct=None, asOf=None))
        out = members.build_tw_members(snapshot(rows), '油電燃氣')
        self.assertEqual(out['count'], 41)
        self.assertEqual(out['rows'][0]['code'], '2039')
        self.assertEqual(out['rows'][-1]['code'], '2999')
        self.assertIsNone(out['rows'][-1]['changePct'])
        self.assertIsNone(out['date'])

    def test_同名重複及非有限數字不污染清單(self):
        out = members.build_tw_members(snapshot([
            stock(price='NaN', change=float('inf'), changePct=True), stock(),
        ]), '油電燃氣')
        self.assertEqual(out['count'], 1)
        self.assertIsNone(out['rows'][0]['price'])
        self.assertIsNone(out['rows'][0]['change'])
        self.assertIsNone(out['rows'][0]['changePct'])

    def test_電子群組明示範圍且不包含非電子產業(self):
        out = members.build_tw_members(snapshot([
            stock('2317', '其他電子業'), stock('2454', '半導體業'), stock(),
        ]), '電子工業')
        self.assertEqual(out['scope'], 'TWSE_INDUSTRY_GROUP')
        self.assertEqual({row['code'] for row in out['rows']}, {'2317', '2454'})

    def test_主題指數不能套用代表股(self):
        out = members.build_tw_members(snapshot([stock()]), '臺灣高股息')
        self.assertTrue(out['ok'])
        self.assertEqual(out['scope'], 'UNAVAILABLE')
        self.assertEqual(out['rows'], [])
        self.assertIn('成分來源', out['unavailableReason'])

    def test_來源失敗與缺少分類明確回報(self):
        out = members.build_tw_members({'twseAvailable': False}, '油電燃氣')
        self.assertFalse(out['ok'])
        out = members.build_tw_members({'twseAvailable': True, 'rows': [stock()]}, '油電燃氣')
        self.assertFalse(out['ok'])

    def test_資料日不得由今天或其他股票補值(self):
        for value in (None, '20260230', 'not-a-date'):
            self.assertIsNone(members.source_date(value))
        rows = [stock(), stock('9918', asOf='20260908')]
        out = members.build_tw_members(snapshot(rows), '油電燃氣')
        self.assertIsNone(out['date'])
        self.assertEqual({row['asOf'] for row in out['rows']}, {'2026-09-09', '2026-09-08'})

    def test_總覽快取保留真實日期及完整來源欄位(self):
        payload = {'ok': True, 'date': '20260908', 'source': 'TWSE MI_INDEX IND',
                   'sectors': [{'name': '半導體', 'changePct': 1.2}]}
        out = members.sector_cache_payload(payload)
        self.assertEqual(out['date'], '20260908')
        self.assertEqual(out['sectorFlow']['asOf'], '2026-09-08')
        self.assertEqual(out['sectorFlow']['rows'][0]['asOf'], '2026-09-08')
        self.assertNotIn('sectorFlow', payload)
        missing = members.sector_cache_payload({'sectors': payload['sectors']})
        self.assertIsNone(missing['sectorFlow']['asOf'])
        custom = {'asOf': '2026-09-08', 'source': '既有完整資料'}
        self.assertEqual(members.sector_cache_payload({**payload, 'sectorFlow': custom})['sectorFlow'], custom)


class 類股來源介面測試(unittest.TestCase):
    def test_沿用市場來源且無成交股票仍在成員資料(self):
        twse = [
            {'Code': '6505', 'Name': '測試公司', 'ClosingPrice': '100', 'Change': '5', 'Date': '1150909'},
            {'Code': '9918', 'Name': '未成交公司', 'ClosingPrice': '--', 'Change': '--', 'Date': '1150909'},
            {'Code': '9926', 'Name': '平盤公司', 'ClosingPrice': '30', 'Change': '0', 'Date': '1150909'},
        ]
        def urlopen(req, timeout=None):
            data = twse if 'STOCK_DAY_ALL' in req.full_url else []
            return io.BytesIO(json.dumps(data).encode())
        with mock.patch.object(ST.urllib.request, 'urlopen', side_effect=urlopen), mock.patch.object(
                ST, '_get_tw_sectors', return_value={row['Code']: '油電燃氣業' for row in twse}):
            out = ST._fetch_day_movers(n=1, include_rows=True)
            self.assertEqual(len(out['gainers']), 1)
            self.assertEqual(len(out['rows']), 3)
            clean = members.build_tw_members(out, '油電燃氣')
            self.assertEqual(clean['count'], 3)
            self.assertEqual(clean['date'], '2026-09-09')
            self.assertIsNone(clean['rows'][-1]['price'])
            regular = ST._fetch_day_movers(n=1)
            self.assertNotIn('rows', regular)

    def call(self, **query):
        handler = SimpleNamespace(path='/sectors/members?' + urlencode(query), _ok=mock.Mock(), _err=mock.Mock())
        ST.Handler._handle_sector_members(handler)
        return handler

    def test_介面沿用全市場快取且不呼叫焦點掃描(self):
        source = snapshot([stock()])
        with mock.patch.object(ST, '_cache') as cache, mock.patch.object(ST, '_fetch_day_movers') as fetch:
            cache.get.return_value = json.dumps(source).encode()
            result = self.call(mkt='TW', sector='油電燃氣')
        fetch.assert_not_called()
        out = json.loads(result._ok.call_args.args[0])
        self.assertEqual(out['rows'][0]['code'], '6505')

    def test_重新整理取得完整資料而非前幾名(self):
        with mock.patch.object(ST, '_cache') as cache, mock.patch.object(
                ST, '_fetch_day_movers', return_value=snapshot([stock()])) as fetch:
            self.call(mkt='TW', sector='油電燃氣', refresh='1')
        fetch.assert_called_once_with(include_rows=True)
        cache.get.assert_not_called()

    def test_無效市場與缺少類股拒絕處理(self):
        for query in ({'mkt': 'CN', 'sector': '油電燃氣'}, {'mkt': 'TW'}, {'sector': 'a' * 161}):
            result = self.call(**query)
            self.assertEqual(result._err.call_args.args[1], 400)

    def test_美股僅接受既有產業ETF並交由官方持股來源處理(self):
        provider = SimpleNamespace(get_members=mock.Mock(return_value={
            'ok': True, 'market': 'US', 'rows': [{'code': 'AAPL'}], 'count': 1}))
        with mock.patch.dict(sys.modules, {'美股類股成員': provider}):
            result = self.call(mkt='US', sector='科技 Technology')
        provider.get_members.assert_called_once_with('XLK', ST._yf_batch_quotes)
        self.assertEqual(json.loads(result._ok.call_args.args[0])['rows'][0]['code'], 'AAPL')
        for query in ({'sector': '臺灣50'}, {'sector': '科技 Technology', 'symbol': 'XLF'}, {'sector': 'SPY'}):
            result = self.call(mkt='US', **query)
            self.assertEqual(result._err.call_args.args[1], 400)


if __name__ == '__main__':
    unittest.main()

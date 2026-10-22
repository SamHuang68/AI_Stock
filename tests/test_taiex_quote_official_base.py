# -*- coding: utf-8 -*-
"""加權指數 ^TWII 的 /quote 與 /quote-batch 必須和 /twindex 使用同一個官方昨收。

重現（2026-10-14）：Yahoo chartPreviousClose = previousClose = 49302.0，官方昨收 48341.31。
Yahoo 昨收會讓現價 48625.83 變成 -676.17 (-1.37%)，官方口徑是 +284.52 (+0.59%)。
以正式 Handler 驗證：^TWII 只信 TWSE MIS，不碰 Yahoo；MIS 沒有成交價時仍退回 Yahoo。
"""
import importlib.util
import json
import os
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'server'))

with open(os.path.join(os.path.dirname(__file__), 'fixtures', '大盤昨收分歧.json'),
          encoding='utf-8') as 案例檔:
    案例資料 = json.load(案例檔)
OFFICIAL_T00 = 案例資料['official']


_REAL_URLOPEN = urllib.request.urlopen


def _yahoo_must_not_be_called(*args, **kwargs):
    raise AssertionError('^TWII 不應再請求 Yahoo 昨收')


def _urlopen_but_never_yahoo(request, *args, **kwargs):
    """測試本身也用 urlopen 打本機伺服器；只攔下對 Yahoo 的請求。"""
    url = request if isinstance(request, str) else request.full_url
    if 'yahoo' in url:
        _yahoo_must_not_be_called()
    return _REAL_URLOPEN(request, *args, **kwargs)


class TaiexQuoteOfficialBaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'st_server_taiex_quote_test', os.path.join(ROOT, 'server', 'server.py'))
        cls.st = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.st)
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), cls.st.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def get_json(self, path):
        with _REAL_URLOPEN(self.base + path, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return json.loads(response.read().decode('utf-8'))

    def test_the_override_table_lists_both_taiwan_indices(self):
        self.assertEqual(self.st._BAD_YF['^TWII'][:2], ('tse_t00.tw', 't00'))
        self.assertEqual(self.st._BAD_YF['^TWOII'][:2], ('otc_o00.tw', 'o00'))

    def test_quote_uses_the_official_previous_close_and_never_asks_yahoo(self):
        with mock.patch.object(self.st, '_twse_mis_index', return_value={'t00': OFFICIAL_T00}) as mis, \
             mock.patch.object(self.st.urllib.request, 'urlopen', side_effect=_urlopen_but_never_yahoo):
            # 前端用 encodeURIComponent 與未編碼兩種寫法都要走官方口徑
            quotes = [self.get_json('/quote/%5ETWII'), self.get_json('/quote/^TWII')]
        for quote in quotes:
            self.assertEqual(quote['prevClose'], 48341.31)
            self.assertEqual(quote['price'], 48625.83)
            self.assertAlmostEqual(quote['change'], 284.52, places=2)
            self.assertAlmostEqual(quote['changePct'], 0.5885, places=3)
            self.assertEqual(quote['source'], 'twse-mis')
            self.assertEqual((quote['open'], quote['high'], quote['low']), (48400.0, 48700.5, 48310.25))
            self.assertFalse(quote['suspect'])
        self.assertEqual(mis.call_args_list[0].args, ('tse_t00.tw',))

    def test_quote_batch_returns_the_same_base_as_the_twindex_row(self):
        with mock.patch.object(self.st, '_twse_mis_index', return_value={'t00': OFFICIAL_T00}), \
             mock.patch.object(self.st, 'fetch_one', side_effect=_yahoo_must_not_be_called):
            batch = self.get_json('/quote-batch?syms=%5ETWII')
        row = batch['^TWII']
        self.assertEqual(row['prevClose'], 48341.31)
        self.assertEqual(row['price'], 48625.83)
        self.assertAlmostEqual(row['changePct'], OFFICIAL_T00['changePct'], places=9)
        self.assertEqual(row['source'], 'twse-mis')

    def test_同一官方快照通過三個正式HTTP端點仍保持昨收與漲跌一致(self):
        """只替換外部 MIS 回應；正式解析器與三條 HTTP 路由都須實際執行。"""
        官方快照 = {'msgArray': [{
            'ch': 't00.tw', 'n': OFFICIAL_T00['name'],
            'z': str(OFFICIAL_T00['price']), 'y': str(OFFICIAL_T00['prevClose']),
            'o': str(OFFICIAL_T00['open']), 'h': str(OFFICIAL_T00['high']),
            'l': str(OFFICIAL_T00['low']),
            'd': 案例資料['tradeDate'].replace('-', ''), 't': '13:30:00',
        }]}
        原始連線 = socket.create_connection

        def 僅允許測試伺服器連線(address, *args, **kwargs):
            if address != ('127.0.0.1', self.httpd.server_port):
                raise AssertionError('一致性案例禁止外部網路連線')
            return 原始連線(address, *args, **kwargs)

        with mock.patch.object(self.st, '_src_fetch_json', return_value=官方快照) as 官方來源, \
             mock.patch.object(self.st, '_cache') as 隔離快取, \
             mock.patch.object(self.st, 'fetch_one', side_effect=_yahoo_must_not_be_called) as Yahoo來源, \
             mock.patch.object(socket, 'create_connection', side_effect=僅允許測試伺服器連線):
            隔離快取.get.return_value = None
            大盤回應 = self.get_json('/twindex')
            單檔回應 = self.get_json('/quote/%5ETWII')
            批次回應 = self.get_json('/quote-batch?syms=%5ETWII')['^TWII']

        self.assertTrue(大盤回應['ok'])
        self.assertEqual(大盤回應['source'], 'twse-mis')
        大盤報價 = 大盤回應['indices']['t00']
        for 端點, 報價 in (('/twindex', 大盤報價), ('/quote', 單檔回應),
                          ('/quote-batch', 批次回應)):
            with self.subTest(端點=端點):
                for 欄位 in ('price', 'prevClose', 'changePct'):
                    self.assertAlmostEqual(報價[欄位], OFFICIAL_T00[欄位], places=9)
                    self.assertAlmostEqual(報價[欄位], 大盤報價[欄位], places=9)
                self.assertEqual(報價['source'], 'twse-mis')
                self.assertNotEqual(報價['prevClose'], 案例資料['yahoo']['prevClose'])
                self.assertGreater(報價['changePct'], 0)

        # 日期目前僅由 /twindex 暴露；不得拿 serverTime 當市場日期。
        self.assertEqual(大盤報價['tradeDate'], 案例資料['tradeDate'])
        self.assertEqual(大盤報價['asOf'], 案例資料['tradeDate'] + 'T13:30:00+08:00')
        self.assertEqual(大盤報價['market']['asOf'], 大盤報價['asOf'])
        self.assertEqual(大盤報價['referencePrice'], OFFICIAL_T00['prevClose'])
        self.assertEqual(大盤報價['referenceType'], 'previous_close')
        self.assertAlmostEqual(大盤報價['displayChange'], OFFICIAL_T00['change'], places=9)
        self.assertEqual(大盤報價['displayChangePct'], round(OFFICIAL_T00['changePct'], 4))
        self.assertAlmostEqual(單檔回應['change'], 大盤報價['change'], places=9)
        self.assertEqual(官方來源.call_count, 3)
        for 呼叫, 頻道 in zip(官方來源.call_args_list,
                             ('tse_t00.tw|otc_o00.tw', 'tse_t00.tw', 'tse_t00.tw')):
            self.assertEqual(呼叫.args[0], 'twse-mis')
            self.assertIn('ex_ch=' + 頻道 + '&', 呼叫.args[1])
        Yahoo來源.assert_not_called()

    def test_市場快照路由使用同一官方昨收並輸出前端實際讀取的欄位(self):
        """前端下方小框與主圖標頭讀的是 /market/snapshot 的 market 欄位，不是 /twindex 原始欄位。"""
        官方快照 = {'msgArray': [{
            'ch': 't00.tw', 'n': OFFICIAL_T00['name'],
            'z': str(OFFICIAL_T00['price']), 'y': str(OFFICIAL_T00['prevClose']),
            'o': str(OFFICIAL_T00['open']), 'h': str(OFFICIAL_T00['high']),
            'l': str(OFFICIAL_T00['low']),
            'd': 案例資料['tradeDate'].replace('-', ''), 't': '13:30:00',
        }]}
        原始連線 = socket.create_connection

        def 僅允許測試伺服器連線(address, *args, **kwargs):
            if address != ('127.0.0.1', self.httpd.server_port):
                raise AssertionError('快照案例禁止外部網路連線')
            return 原始連線(address, *args, **kwargs)

        with mock.patch.object(self.st, '_src_fetch_json', return_value=官方快照),              mock.patch.object(self.st, '_cache') as 隔離快取,              mock.patch.object(self.st, 'fetch_one', side_effect=_yahoo_must_not_be_called) as Yahoo來源,              mock.patch.object(self.st.Handler, '_txf_mis_session', return_value=None),              mock.patch.object(socket, 'create_connection', side_effect=僅允許測試伺服器連線):
            隔離快取.get.return_value = None
            快照 = self.get_json('/market/snapshot')

        self.assertTrue(快照['ok'])
        市場 = 快照['quotes']['^TWII']['market']
        預期 = 案例資料['expected']['snapshotMarket']
        self.assertEqual(市場['source'], 'twse-mis')
        self.assertEqual(市場['referenceType'], 預期['referenceType'])
        self.assertAlmostEqual(市場['price'], 預期['price'], places=9)
        self.assertAlmostEqual(市場['referencePrice'], 預期['referencePrice'], places=9)
        self.assertAlmostEqual(市場['displayChange'], 預期['displayChange'], places=9)
        self.assertEqual(市場['displayChangePct'], 預期['displayChangePct'])
        self.assertNotEqual(市場['referencePrice'], 案例資料['yahoo']['prevClose'])
        Yahoo來源.assert_not_called()

    def test_yahoo_value_is_not_used_even_when_it_is_the_only_wrong_number(self):
        """Yahoo 回 49302.0 時，批次與單檔都不得把 -676.17 算進去。"""
        wrong_yahoo = {'chart': {'result': [{
            'meta': {'regularMarketPrice': 48625.83, 'chartPreviousClose': 49302.0, 'previousClose': 49302.0},
            'timestamp': [1760419800], 'indicators': {'quote': [{'close': [48625.83]}]}}]}}
        payload = json.dumps(wrong_yahoo).encode('utf-8')
        with mock.patch.object(self.st, '_twse_mis_index', return_value={'t00': OFFICIAL_T00}), \
             mock.patch.object(self.st, 'fetch_one', return_value=('^TWII', payload, False)):
            batch = self.get_json('/quote-batch?syms=%5ETWII')
        self.assertGreater(batch['^TWII']['changePct'], 0)

    def test_without_an_official_trade_the_quote_falls_back_to_yahoo(self):
        """盤前 MIS 沒有成交價與開盤價：維持原本行為，不回空。"""
        empty = dict(OFFICIAL_T00, price=None, change=None, changePct=None)
        self.assertIsNone(self.st._trusted_quote_override('2330'))
        with mock.patch.object(self.st, '_twse_mis_index', return_value={'t00': empty}):
            self.assertIsNone(self.st._trusted_quote_override('^TWII'))
        with mock.patch.object(self.st, '_twse_mis_index', side_effect=RuntimeError('MIS down')):
            self.assertIsNone(self.st._trusted_quote_override('^TWII'))

    def _盤前_MIS_只有官方昨收(self):
        return dict(OFFICIAL_T00, price=None, change=None, changePct=None, open=None, high=None, low=None)

    def _錯誤的_Yahoo(self):
        wrong = {'chart': {'result': [{
            'meta': {'regularMarketPrice': 48625.83, 'chartPreviousClose': 案例資料['yahoo']['prevClose'],
                     'previousClose': 案例資料['yahoo']['prevClose'], 'symbol': '^TWII'},
            'timestamp': [1760419800], 'indicators': {'quote': [{'close': [48625.83]}]}}]}}
        return json.dumps(wrong).encode('utf-8')

    def test_QB12_盤前MIS只有官方昨收時_備援報價仍採官方昨收_批次與單檔一致(self):
        """MIS 沒有成交價與開盤價時走 Yahoo，但 Yahoo 的昨收曾與官方差 1%；Yahoo 價必須配官方昨收。"""
        with mock.patch.object(self.st, '_twse_mis_index', return_value={'t00': self._盤前_MIS_只有官方昨收()}),              mock.patch.object(self.st, 'fetch_one', return_value=('^TWII', self._錯誤的_Yahoo(), False)),              mock.patch.object(self.st.urllib.request, 'urlopen', side_effect=self._yahoo_chart_urlopen):
            批次 = self.get_json('/quote-batch?syms=%5ETWII')['^TWII']
            單檔 = self.get_json('/quote/%5ETWII')
        for 名稱, 報價 in (('批次', 批次), ('單檔', 單檔)):
            with self.subTest(端點=名稱):
                self.assertAlmostEqual(報價['prevClose'], OFFICIAL_T00['prevClose'], places=9)
                self.assertNotEqual(報價['prevClose'], 案例資料['yahoo']['prevClose'])
                self.assertGreater(報價['changePct'], 0)
                self.assertAlmostEqual(報價['changePct'], (48625.83 - OFFICIAL_T00['prevClose']) / OFFICIAL_T00['prevClose'] * 100, places=6)
                self.assertIn('twse-mis-prev', 報價['source'])

    def _yahoo_chart_urlopen(self, request, *args, **kwargs):
        """/quote 單檔的 Yahoo 分支直接用 urlopen；只攔 Yahoo，其他（測試伺服器）放行。"""
        url = request if isinstance(request, str) else request.full_url
        if 'yahoo' in url:
            class _回應:
                def __enter__(self_inner): return self_inner
                def __exit__(self_inner, *a): return False
                def read(self_inner): return self._錯誤的_Yahoo()
            return _回應()
        return _REAL_URLOPEN(request, *args, **kwargs)

    def test_QB12_MIS完全失敗時維持原本行為_沿用Yahoo昨收(self):
        with mock.patch.object(self.st, '_twse_mis_index', side_effect=RuntimeError('MIS down')),              mock.patch.object(self.st, 'fetch_one', return_value=('^TWII', self._錯誤的_Yahoo(), False)):
            批次 = self.get_json('/quote-batch?syms=%5ETWII')['^TWII']
        self.assertEqual(批次['prevClose'], 案例資料['yahoo']['prevClose'])
        self.assertEqual(批次['source'], 'yahoo-v8-chart')

    def test_QB12_官方昨收只用於Yahoo不可信的指數(self):
        with mock.patch.object(self.st, '_twse_mis_index') as mis:
            self.assertIsNone(self.st._trusted_prev_close('^GSPC'))
            self.assertIsNone(self.st._trusted_prev_close('2330.TW'))
        mis.assert_not_called()
        with mock.patch.object(self.st, '_twse_mis_index', return_value={'t00': dict(OFFICIAL_T00, prevClose=0)}):
            self.assertIsNone(self.st._trusted_prev_close('^TWII'), '昨收為 0 不可採用')
        with mock.patch.object(self.st, '_twse_mis_index', return_value={'t00': OFFICIAL_T00}):
            self.assertEqual(self.st._trusted_prev_close('^TWII'), OFFICIAL_T00['prevClose'])

    def test_other_symbols_are_unaffected(self):
        with mock.patch.object(self.st, '_twse_mis_index') as mis:
            self.assertIsNone(self.st._trusted_quote_override('^GSPC'))
            self.assertIsNone(self.st._trusted_quote_override('^N225'))
        mis.assert_not_called()


if __name__ == '__main__':
    unittest.main()

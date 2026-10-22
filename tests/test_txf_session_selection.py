# -*- coding: utf-8 -*-
"""台指期日盤／夜盤場次選擇（審查 QB-01、QB-04、QB-08、D-01、D-02、D-09）。

日盤時段 08:45–13:45 若仍拿夜盤清單有值就不查日盤，`/market/snapshot`、`/txf` 與 Pulse 期現價差
會用前一晚 05:00 的夜盤收盤。所有消費端改用同一個依時間戳選擇的函式 `txf_for_snapshot`。
以真實 Handler 與 HTTP 驗證；外部來源（TAIFEX MIS、Yahoo、證交所 MIS）與時鐘由測試替換。
"""
import importlib.util
import json
import os
import sys
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'server'))

import pulse_orchestration as po  # noqa: E402

TW = timezone(timedelta(hours=8))


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=TW)


def quote(session, price, as_of, prev=44800.0, **extra):
    base = {'asOf': as_of, 'sourceDate': as_of[:10], 'timeUnverified': False,
            'price': price, 'prevClose': prev,
            'change': None if prev is None else price - prev,
            'changePct': None if prev is None else round((price - prev) / prev * 100, 4),
            'session': session, 'sessionLabel': '夜盤' if session == 'night' else '日盤',
            'source': 'taifex-mis-' + session, 'time': as_of[11:19]}
    base.update(extra)
    return base


# 週四 10:30（日盤中）：夜盤是今天 04:59 收的，日盤是剛成交的
NIGHT_OLD = quote('night', 45000.0, '2026-10-22T04:59:50+08:00')
DAY_LIVE = quote('day', 45200.0, '2026-10-22T10:29:55+08:00')


class SelectionHelpers(unittest.TestCase):
    def test_D09_日盤主報價不得冒充夜盤區塊(self):
        # 過去只要主報價有 ampRate 就當夜盤；日盤報價的 ampRate 也有值，日盤時段會把日盤價放進 txf_night
        day_only = {'ok': True, **DAY_LIVE, 'ampRate': 0.9}
        self.assertIsNone(po.night_block(day_only))
        night_primary = {'ok': True, **quote('night', 45000.0, '2026-10-21T23:00:00+08:00')}
        self.assertIs(po.night_block(night_primary), night_primary)
        with_block = {'ok': True, **DAY_LIVE, 'night': NIGHT_OLD}
        self.assertIs(po.night_block(with_block), NIGHT_OLD)
        self.assertIsNone(po.night_block({'ok': False}))
        self.assertIsNone(po.night_block(None))

    def test_D01_期現價差用同一個場次選擇_日盤時段不拿過期夜盤(self):
        now = at('2026-10-22T10:30:00')
        picked = po.strip_txf({'ok': True, **DAY_LIVE}, NIGHT_OLD, now)
        self.assertEqual((picked['session'], picked['price']), ('day', 45200.0))
        # 夜盤時段：夜盤較新
        night_live = quote('night', 45300.0, '2026-10-22T18:00:00+08:00')
        picked = po.strip_txf({'ok': True, **quote('day', 45200.0, '2026-10-22T13:44:59+08:00')}, night_live,
                              at('2026-10-22T18:00:10'))
        self.assertEqual((picked['session'], picked['price']), ('night', 45300.0))
        # 兩者都缺：沒有選擇
        self.assertIsNone(po.strip_txf(None, None, now))
        # 只有主報價（沒有夜盤區塊）時退回主報價
        self.assertEqual(po.strip_txf({'ok': True, **DAY_LIVE}, None, now)['price'], 45200.0)


class HandlerSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('st_server_txf_session_test', os.path.join(ROOT, 'server', 'server.py'))
        cls.st = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.st)
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), cls.st.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:%d' % cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.st._cache._d.clear()
        self.calls = []

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))

    def run_with(self, now, day, night, yahoo=None, path='/market/snapshot', keep_cache=False):
        if not keep_cache:
            self.st._cache._d.clear()
        def session(handler, market_type):
            self.calls.append(str(market_type))
            value = night if str(market_type) == '1' else day
            if isinstance(value, Exception):
                raise value
            return dict(value) if value else None
        patches = (
            mock.patch.object(self.st.Handler, '_txf_mis_session', session),
            mock.patch.object(self.st.Handler, '_txf_now', lambda handler: now, create=True),
            mock.patch.object(self.st.Handler, '_txf_yahoo_quote', lambda handler: (dict(yahoo) if yahoo else None, {})),
            mock.patch.object(self.st, '_twse_mis_index', return_value={}),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return self.get(path)

    # --- QB-01 -------------------------------------------------------------
    def test_QB01_日盤時段_market_snapshot_用日盤不用前一晚夜盤(self):
        out = self.run_with(at('2026-10-22T10:30:00'), DAY_LIVE, NIGHT_OLD)
        txf = out['quotes']['__TXF__']
        self.assertEqual((txf['session'], txf['price']), ('day', 45200.0))
        self.assertEqual(txf['market']['session'], 'day')

    def test_QB01_夜盤時段與盤前仍用夜盤(self):
        night_live = quote('night', 45300.0, '2026-10-22T18:00:00+08:00')
        day_close = quote('day', 45200.0, '2026-10-22T13:44:59+08:00')
        out = self.run_with(at('2026-10-22T18:00:10'), day_close, night_live)
        self.assertEqual(out['quotes']['__TXF__']['session'], 'night')
        # 05:00–08:45：日盤是前一天的收盤，夜盤剛收，仍是夜盤
        yesterday_day = quote('day', 45100.0, '2026-10-21T13:44:59+08:00')
        out = self.run_with(at('2026-10-22T06:00:00'), yesterday_day, NIGHT_OLD)
        self.assertEqual(out['quotes']['__TXF__']['session'], 'night')

    def test_QB01_夜盤沒有資料時用日盤_日盤沒有資料時用夜盤(self):
        out = self.run_with(at('2026-10-22T10:30:00'), DAY_LIVE, None)
        self.assertEqual(out['quotes']['__TXF__']['session'], 'day')
        out = self.run_with(at('2026-10-22T06:00:00'), None, NIGHT_OLD)
        self.assertEqual(out['quotes']['__TXF__']['session'], 'night')

    def test_QB01_兩個場次都失敗時沒有台指期報價但仍回加權(self):
        out = self.run_with(at('2026-10-22T10:30:00'), RuntimeError('x'), RuntimeError('y'))
        self.assertNotIn('__TXF__', out.get('quotes', {}))

    # --- QB-08 -------------------------------------------------------------
    def test_QB08_market_snapshot_短時間內重複請求不重複查詢_失敗也快取(self):
        for _ in range(3):
            self.run_with(at('2026-10-22T10:30:00'), DAY_LIVE, NIGHT_OLD, keep_cache=True)
        self.assertEqual(sorted(self.calls), ['0', '1'], '三次請求只應各查一次場次')
        self.st._cache._d.clear()
        self.calls.clear()
        for _ in range(3):
            self.run_with(at('2026-10-22T10:30:00'), RuntimeError('x'), RuntimeError('y'), keep_cache=True)
        self.assertEqual(sorted(self.calls), ['0', '1'], '失敗結果也要短暫快取，避免來源異常時每次請求都連線')

    def test_QB08_同時未命中只查一次_等待者共用成功或失敗結果(self):
        for outcome in ('成功', '失敗'):
            self.st._cache._d.clear()
            started, release, calls, results = threading.Event(), threading.Event(), [], []

            def slow_session(handler, market_type):
                calls.append(str(market_type))
                started.set()
                release.wait(3)
                if outcome == '失敗':
                    raise RuntimeError('逾時')
                return dict(DAY_LIVE)
            handler = mock.Mock(spec=self.st.Handler)
            handler._txf_mis_session = lambda mt: slow_session(handler, mt)

            def call():
                try:
                    results.append(('ok', self.st.Handler._txf_mis_cached(handler, 0)))
                except RuntimeError as exc:
                    results.append(('err', str(exc)))
            threads = [threading.Thread(target=call) for _ in range(6)]
            for t in threads:
                t.start()
            self.assertTrue(started.wait(3))
            release.set()
            for t in threads:
                t.join(5)
            self.assertEqual(calls, ['0'], outcome + '：六個同時請求只應連線一次')
            self.assertEqual(len(results), 6)
            self.assertEqual({r[0] for r in results}, {'ok' if outcome == '成功' else 'err'})

    def test_QB08_快取到期後重新查詢(self):
        base = 1_000_000.0
        with mock.patch('time.time', return_value=base):
            self.run_with(at('2026-10-22T10:30:00'), DAY_LIVE, NIGHT_OLD, keep_cache=False)
            self.assertEqual(len(self.calls), 2)
            self.run_with(at('2026-10-22T10:30:05'), DAY_LIVE, NIGHT_OLD, keep_cache=True)
            self.assertEqual(len(self.calls), 2, '15 秒內不重查')
        with mock.patch('time.time', return_value=base + 16):
            self.run_with(at('2026-10-22T10:30:16'), DAY_LIVE, NIGHT_OLD, keep_cache=True)
            self.assertEqual(len(self.calls), 4, '超過 15 秒要重查')

    def test_QB01_只有一個場次失敗時用另一個場次(self):
        out = self.run_with(at('2026-10-22T10:30:00'), DAY_LIVE, RuntimeError('夜盤查詢逾時'))
        self.assertEqual(out['quotes']['__TXF__']['session'], 'day')
        out = self.run_with(at('2026-10-22T06:00:00'), RuntimeError('日盤查詢逾時'), NIGHT_OLD)
        self.assertEqual(out['quotes']['__TXF__']['session'], 'night')

    def test_QB01_切盤邊界_快取內仍是TTL內最後已知場次_過期後切到夜盤(self):
        # 14:59:59 暖快取，15:00:01 夜盤已有新成交：快取有效期間（≤15 秒）仍回日盤收盤，這與 /txf 既有 20 秒快取同類；
        # 快取到期後必須切到較新的夜盤。
        day_close = quote('day', 45200.0, '2026-10-22T13:44:59+08:00')
        new_night = quote('night', 45250.0, '2026-10-22T15:00:01+08:00')
        base = 2_000_000.0
        with mock.patch('time.time', return_value=base):
            out = self.run_with(at('2026-10-22T14:59:59'), day_close, NIGHT_OLD)
            self.assertEqual(out['quotes']['__TXF__']['session'], 'day')
            out = self.run_with(at('2026-10-22T15:00:01'), day_close, new_night, keep_cache=True)
            self.assertEqual(out['quotes']['__TXF__']['session'], 'day', '快取有效期間內沿用上一輪的場次資料')
        with mock.patch('time.time', return_value=base + 16):
            out = self.run_with(at('2026-10-22T15:00:16'), day_close, new_night, keep_cache=True)
            self.assertEqual((out['quotes']['__TXF__']['session'], out['quotes']['__TXF__']['price']), ('night', 45250.0))

    def test_D02_asOf_未核實時_日盤時段仍有確定的行為(self):
        # 兩筆時間都無法核實：維持既有函式的行為（夜盤區塊），並且不拋例外
        day_unverified = quote('day', 45200.0, '2026-10-22T10:29:55+08:00', asOf=None, timeUnverified=True)
        night_unverified = quote('night', 45000.0, '2026-10-22T04:59:50+08:00', asOf=None, timeUnverified=True)
        out = self.run_with(at('2026-10-22T10:30:00'), day_unverified, night_unverified, path='/txf')
        self.assertTrue(out['ok'])
        self.assertIn(out['session'], ('day', 'night'))

    def test_QB04_Yahoo只補MIS缺的欄位_不覆蓋MIS已有的欄位(self):
        day_partial = quote('day', 45200.0, '2026-10-22T10:29:55+08:00', open=None, high=None, low=None, ampRate=None)
        yahoo = {'price': 45500.0, 'open': 45100.0, 'high': 45300.0, 'low': 44900.0, 'ampRate': 0.9,
                 'prevClose': 40000.0, 'change': 5500.0, 'changePct': 13.7, 'source': 'yahoo'}
        out = self.run_with(at('2026-10-22T10:30:00'), day_partial, NIGHT_OLD, yahoo=yahoo, path='/txf')
        self.assertEqual((out['open'], out['high'], out['low'], out['ampRate']), (45100.0, 45300.0, 44900.0, 0.9))
        self.assertEqual((out['price'], out['prevClose'], out['change']), (45200.0, 44800.0, 400.0))

    # --- QB-02 -------------------------------------------------------------
    def test_QB02_MIS參考價是結算價_snapshot與txf都標settlement(self):
        out = self.run_with(at('2026-10-22T10:30:00'), DAY_LIVE, NIGHT_OLD)
        self.assertEqual(out['quotes']['__TXF__']['market']['referenceType'], 'settlement')
        self.assertEqual(out['quotes']['__TXF__']['referenceType'], 'settlement')
        out = self.run_with(at('2026-10-22T10:30:00'), DAY_LIVE, NIGHT_OLD, path='/txf')
        self.assertEqual(out['market']['referenceType'], 'settlement')

    def test_QB02_昨收由Yahoo補入或只有Yahoo時不標settlement(self):
        day_no_prev = quote('day', 45200.0, '2026-10-22T10:29:55+08:00', prev=None, change=None, changePct=None)
        yahoo = {'price': 45500.0, 'prevClose': 44800.0, 'source': 'yahoo'}
        out = self.run_with(at('2026-10-22T10:30:00'), day_no_prev, NIGHT_OLD, yahoo=yahoo, path='/txf')
        self.assertEqual(out['prevClose'], 44800.0)
        self.assertEqual(out['market']['referenceType'], 'previous_close', 'Yahoo 昨收不是結算價')
        out = self.run_with(at('2026-10-22T10:30:00'), None, None, yahoo=yahoo, path='/txf')
        self.assertEqual(out['market']['referenceType'], 'previous_close')

    # --- D-02 --------------------------------------------------------------
    def test_D02_txf_日盤開盤附近Yahoo價接近夜盤收盤也不選過期夜盤(self):
        # 日盤剛開，價格與夜盤收盤只差 10 點（落在舊的 ±22 點容許內），舊判定會把過期夜盤當主報價
        day_open = quote('day', 45010.0, '2026-10-22T08:46:10+08:00')
        out = self.run_with(at('2026-10-22T08:46:30'), day_open, NIGHT_OLD,
                            yahoo={'price': 45005.0, 'prevClose': 44800.0, 'source': 'yahoo'}, path='/txf')
        self.assertEqual((out['session'], out['price']), ('day', 45010.0))
        self.assertEqual(out['night']['price'], 45000.0)

    def test_D02_txf_夜盤時段選夜盤_盤前選夜盤(self):
        night_live = quote('night', 45300.0, '2026-10-22T18:00:00+08:00')
        day_close = quote('day', 45200.0, '2026-10-22T13:44:59+08:00')
        out = self.run_with(at('2026-10-22T18:00:10'), day_close, night_live, path='/txf')
        self.assertEqual((out['session'], out['price']), ('night', 45300.0))
        self.st._cache._d.clear()
        out = self.run_with(at('2026-10-22T06:00:00'), quote('day', 45100.0, '2026-10-21T13:44:59+08:00'),
                            NIGHT_OLD, path='/txf')
        self.assertEqual(out['session'], 'night')

    # --- QB-04 -------------------------------------------------------------
    def test_QB04_MIS缺昨收向Yahoo補昨收時漲跌用MIS價格重算(self):
        day_no_prev = quote('day', 45200.0, '2026-10-22T10:29:55+08:00', prev=None, change=None, changePct=None)
        yahoo = {'price': 45500.0, 'prevClose': 44800.0, 'change': 700.0, 'changePct': 1.5625, 'source': 'yahoo'}
        out = self.run_with(at('2026-10-22T10:30:00'), day_no_prev, NIGHT_OLD, yahoo=yahoo, path='/txf')
        self.assertEqual(out['session'], 'day')
        self.assertEqual(out['prevClose'], 44800.0)
        self.assertEqual(out['change'], 400.0, '漲跌必須是 MIS 價格減補入的昨收，不是 Yahoo 自己的價差')
        self.assertAlmostEqual(out['changePct'], 400.0 / 44800.0 * 100, places=3)

    def test_QB04_MIS有昨收時不採用Yahoo的漲跌(self):
        yahoo = {'price': 45500.0, 'prevClose': 44000.0, 'change': 1500.0, 'changePct': 3.4, 'source': 'yahoo'}
        out = self.run_with(at('2026-10-22T10:30:00'), DAY_LIVE, NIGHT_OLD, yahoo=yahoo, path='/txf')
        self.assertEqual((out['prevClose'], out['change']), (44800.0, 400.0))


if __name__ == '__main__':
    unittest.main()

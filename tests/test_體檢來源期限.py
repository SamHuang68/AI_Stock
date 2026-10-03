"""隔離來源停滯測試；不使用真實網路、資料庫、HTTP 服務或付費模型。"""
import sys
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import stock_signals as ss
import stock_signals_routes as routes
import datastore
from deadline import BoundedExecutor


class StockHealthDeadlineTests(unittest.TestCase):
    def setUp(self):
        routes.clear_cache()
        self.pool = BoundedExecutor(max_workers=2, max_in_flight=2, prefix='health-fixture')
        self.release = threading.Event()
        self.now = datetime(2026, 10, 3, 18, tzinfo=timezone(timedelta(hours=8)))
        self.rows = [(int((self.now - timedelta(days=200 - i)).timestamp()), 100, 101, 99, 100, 1000)
                     for i in range(150)]
        self.ds = SimpleNamespace(get_bars=mock.Mock(return_value=self.rows),
                                  upsert_bars=mock.Mock(), fetch_yahoo_daily=mock.Mock())
        self.patches = [mock.patch.object(routes, '_datastore', return_value=self.ds),
                        mock.patch.object(routes, '_remote_pool', self.pool),
                        mock.patch.object(routes, 'REMOTE_FETCH_SECONDS', .025)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        self.release.set()
        self.pool.shutdown()
        for patch in reversed(self.patches):
            patch.stop()
        routes.clear_cache()

    def test_stalled_source_returns_local_bars_before_worker_finishes_and_never_writes_late(self):
        entered = threading.Event()

        def stalled(*args, **kwargs):
            self.assertLessEqual(kwargs['deadline'].remaining(), .025)
            self.assertEqual(args[:2], ('2330', 'TW'))
            entered.set()
            self.release.wait()
            return [(int(self.now.timestamp()), 500, 501, 499, 500, 5000)]

        self.ds.fetch_yahoo_daily.side_effect = stalled
        real_wait = routes.wait
        observed_timeouts = []

        def wait_after_source_started(futures, timeout):
            # 先確認固定來源已啟動；執行緒建立速度不是產品等待期限。
            self.assertTrue(entered.wait(5), '測試來源工作未能啟動')
            observed_timeouts.append(timeout)
            return real_wait(futures, timeout=timeout)

        with mock.patch.object(routes, 'wait', side_effect=wait_after_source_started):
            result = routes.load_bars('2330', 'TW', now=self.now)
        self.assertEqual(len(observed_timeouts), 1)
        self.assertGreaterEqual(observed_timeouts[0], 0)
        self.assertLessEqual(observed_timeouts[0], .025)
        self.assertTrue(entered.is_set())
        self.assertFalse(self.release.is_set(), 'HTTP 結果不可等待仍被阻塞的來源')
        self.assertEqual(result['source'], 'local-db')
        self.assertEqual(len(result['bars']), len(self.rows))
        self.assertEqual(result['bars'][-1]['close'], 100)
        self.assertGreater(result['staleDays'], 0)
        self.assertIn('超過本次時間預算', result['error'])
        self.assertTrue(result['retrySoon'])
        self.assertEqual(self.pool.status()['timeouts'], 1)
        self.release.set(); self.pool.shutdown()
        self.ds.upsert_bars.assert_not_called()

    def test_saturated_source_is_bounded_visible_and_empty_bars_fail_closed(self):
        entered = {'2330': threading.Event(), '2454': threading.Event()}

        def stalled(code, *args, **kwargs):
            entered[code].set()
            self.release.wait(2)
            return []

        self.ds.fetch_yahoo_daily.side_effect = stalled
        running = [self.pool.submit(self.ds.fetch_yahoo_daily, code, 'TW', '5d') for code in entered]
        for event in entered.values():
            self.assertTrue(event.wait(1), '先確認來源工作已啟動，再驗證飽和狀態')
        self.ds.get_bars.return_value = []
        result = routes.load_bars('1101', 'TW', now=self.now)
        self.assertIn('工作繁忙', result['error'])
        self.assertNotIn(('1101', 'TW'), routes._remote_fail)
        self.assertTrue(result['retrySoon'])
        self.assertEqual(self.ds.fetch_yahoo_daily.call_count, 2)
        self.assertEqual(self.pool.status()['inFlight'], 2)
        self.assertEqual(result['bars'], [])
        analysis = ss.analyze(result['bars'], symbol='1101', market='TW')
        self.assertFalse(analysis['ok'])
        self.assertEqual(analysis['reason'], 'INSUFFICIENT_BARS')
        self.assertEqual(self.pool.status()['timeouts'], 0, '額滿不可計為等待總預算到期')
        self.release.set()
        for future in running:
            self.assertEqual(future.result(timeout=1), [])
        self.ds.upsert_bars.assert_not_called()

    def test_source_timeout_is_distinct_from_wait_budget_expiry(self):
        self.ds.fetch_yahoo_daily.side_effect = TimeoutError('模擬來源逾時')
        with mock.patch.object(routes, 'REMOTE_FETCH_SECONDS', 1):
            with self.assertRaisesRegex(TimeoutError, '^行情來源逾時$'):
                routes._fetch_remote('2330', 'TW', '5d')
        self.assertEqual(self.pool.status()['timeouts'], 0)

    def test_actual_yahoo_fetch_accepts_deadline_and_bounds_mock_socket_timeout(self):
        payload = {'chart': {'result': [{'meta': {'symbol': '2330.TW', 'exchangeTimezoneName': 'Asia/Taipei',
                                                'dataGranularity': '1d'},
                                         'timestamp': [1000], 'indicators': {'quote': [
                                             {'open': [100], 'high': [101], 'low': [99],
                                              'close': [100], 'volume': [1000]}]}}]}}
        self.ds.fetch_yahoo_daily.side_effect = datastore.fetch_yahoo_daily
        with mock.patch.object(routes, 'REMOTE_FETCH_SECONDS', 1), \
                mock.patch.object(datastore.urllib.request, 'urlopen',
                                  return_value=io.StringIO(json.dumps(payload))) as request:
            result = routes._fetch_remote('2330', 'TW', '5d')
        self.assertEqual(result, [(1000, 100, 101, 99, 100, 1000)])
        request.assert_called_once()
        self.assertIn('2330.TW', request.call_args.args[0].full_url)
        self.assertGreater(request.call_args.kwargs['timeout'], 0)
        self.assertLessEqual(request.call_args.kwargs['timeout'], 1)
        self.assertIn('deadline', self.ds.fetch_yahoo_daily.call_args.kwargs)
        self.ds.upsert_bars.assert_not_called()

    def test_cache_only_never_submits_source_work(self):
        result = routes.load_bars('2330', 'TW', allow_network=False, now=self.now)
        self.assertEqual(len(result['bars']), len(self.rows))
        self.ds.fetch_yahoo_daily.assert_not_called()
        self.ds.upsert_bars.assert_not_called()
        self.assertEqual(self.pool.status()['submitted'], 0)

    def test_only_new_source_timeout_or_saturation_uses_short_result_cache(self):
        with mock.patch.dict(sys.modules, {'datastore': self.ds}), \
                mock.patch.object(ss, 'load_chip_series', return_value=[]):
            for code, short_cache in [('2330', True), ('2454', False)]:
                loaded = {'bars': [], 'source': 'local-db', 'error': '來源提示', 'retrySoon': short_cache}
                before = time.time()
                result = routes.analyze_symbol(code, 'TW', with_stats=False, allow_network=False,
                                               bars_loader=lambda *args, **kwargs: loaded)
                self.assertFalse(result['ok'])
                self.assertEqual(result['dataWarning'], '來源提示')
                expires = routes._cache[(code, 'TW', False)][0]
                self.assertAlmostEqual(expires - before, 60 if short_cache else 1800, delta=1)

    def test_negative_source_cache_keeps_short_result_ttl_and_allows_retry_after_ten_minutes(self):
        with mock.patch.dict(sys.modules, {'datastore': self.ds}), \
                mock.patch.object(ss, 'load_chip_series', return_value=[]), \
                mock.patch.object(routes.time, 'time', return_value=1000.0) as clock, \
                mock.patch.object(routes, '_fetch_remote',
                                  side_effect=[TimeoutError('行情更新超過本次時間預算'), []]) as fetcher:
            key = ('2330', 'TW', False)
            first = routes.analyze_symbol('2330', 'TW', with_stats=False, now=self.now)
            self.assertIn('超過本次時間預算', first['dataWarning'])
            self.assertEqual(routes._cache[key][0], 1060.0)
            self.assertEqual(routes._remote_fail[('2330', 'TW')], 1600.0)

            clock.return_value = 1061.0
            waiting = routes.analyze_symbol('2330', 'TW', with_stats=False, now=self.now)
            self.assertEqual(waiting['dataWarning'], '最近一次行情更新未完成，暫用本機資料；重試間隔10分鐘')
            self.assertEqual(routes._cache[key][0], 1121.0, '第61秒的結果仍只保留60秒')
            self.assertEqual(routes._remote_fail[('2330', 'TW')], 1600.0, '來源負快取不可縮短或續期')
            self.assertEqual(fetcher.call_count, 1, '負快取期間不新增來源請求')

            clock.return_value = 1600.0
            routes.analyze_symbol('2330', 'TW', with_stats=False, now=self.now)
            self.assertEqual(fetcher.call_count, 2, '600秒來源重試間隔屆滿後可以再次嘗試')
        self.ds.upsert_bars.assert_not_called()


if __name__ == '__main__':
    unittest.main()

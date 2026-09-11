"""以合成資料驗證焦點掃描協調，不連線至行情來源。"""
import ast
import json
import sys
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import focus_cache
from focus_cache import FocusScanCache


def payload(symbol='2330'):
    return {'ok': True, 'scanned': 1, 'buy': [{'sym': symbol}], 'short': []}


class FocusCacheTests(unittest.TestCase):
    def test_concurrent_refreshes_share_one_scan(self):
        cache = FocusScanCache()
        release, joined = threading.Event(), threading.Event()
        barrier, lock = threading.Barrier(8), threading.Lock()
        waiting = [0]

        class ObservedFuture(Future):
            def result(self, timeout=None):
                with lock:
                    waiting[0] += 1
                    if waiting[0] == 7:
                        joined.set()
                return super().result(timeout=timeout)

        def scan():
            if not release.wait(5):
                raise TimeoutError('測試未釋放掃描')
            return payload()

        loader = Mock(side_effect=scan)
        def request():
            barrier.wait(5)
            return cache.get_or_scan(('TW', ''), loader, force=True)

        with patch.object(focus_cache, 'Future', ObservedFuture), ThreadPoolExecutor(max_workers=8) as pool:
            jobs = [pool.submit(request) for _ in range(8)]
            try:
                self.assertTrue(joined.wait(5), '所有相同範圍請求應共用同一工作')
            finally:
                release.set()
            answers = [job.result(5) for job in jobs]
        self.assertEqual(loader.call_count, 1)
        self.assertEqual(len({answer['scan']['id'] for answer in answers}), 1)
        self.assertEqual(sum(answer['scan']['shared'] for answer in answers), 7)
        answers[0]['buy'][0]['sym'] = '呼叫端修改'
        self.assertEqual(cache.get_or_scan(('TW', ''), loader)['buy'][0]['sym'], '2330')

    def test_ttl_starts_after_slow_scan_finishes(self):
        clock = [100.0]
        cache = FocusScanCache(clock=lambda: clock[0], wall_clock=lambda: 1000.0)
        def slow_scan():
            clock[0] += 300
            return payload()
        scan = Mock(side_effect=slow_scan)
        first = cache.get_or_scan('TW', scan)
        self.assertEqual(first['scan']['durationMs'], 300000)
        self.assertEqual(first['scan']['ageSeconds'], 0)
        clock[0] += 179
        cached = cache.get_or_scan('TW', scan)
        self.assertTrue(cached['scan']['cacheHit'])
        self.assertEqual(cached['scan']['id'], first['scan']['id'])
        self.assertEqual(scan.call_count, 1)
        clock[0] += 1
        self.assertNotEqual(cache.get_or_scan('TW', scan)['scan']['id'], first['scan']['id'])
        self.assertEqual(scan.call_count, 2)

    def test_independent_scopes_do_not_block_each_other(self):
        cache, barrier = FocusScanCache(), threading.Barrier(2)
        def request(key):
            def scan():
                barrier.wait(5)
                return payload(key)
            return cache.get_or_scan(key, scan)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, ['TW', 'US']))
        self.assertEqual([result['buy'][0]['sym'] for result in results], ['TW', 'US'])

    def test_failure_does_not_poison_cache_or_leave_work_locked(self):
        cache = FocusScanCache()
        first = cache.get_or_scan('TW', payload)
        failing = Mock(side_effect=RuntimeError('合成來源失敗'))
        with self.assertRaises(RuntimeError):
            cache.get_or_scan('TW', failing, force=True)
        self.assertEqual(cache.get_or_scan('TW', failing)['scan']['id'], first['scan']['id'])
        next_result = cache.get_or_scan('TW', payload, force=True)
        self.assertNotEqual(next_result['scan']['id'], first['scan']['id'])
        with self.assertRaises(ValueError):
            cache.get_or_scan('US', lambda: {'ok': False})
        self.assertTrue(cache.get_or_scan('US', payload)['ok'])

    def test_waiter_timeout_does_not_cancel_owner(self):
        cache = FocusScanCache(wait_timeout_sec=0)
        entered, release = threading.Event(), threading.Event()
        def scan():
            entered.set()
            release.wait(5)
            return payload()
        with ThreadPoolExecutor(max_workers=1) as pool:
            owner = pool.submit(cache.get_or_scan, 'TW', scan)
            self.assertTrue(entered.wait(5))
            try:
                with self.assertRaises(TimeoutError):
                    cache.get_or_scan('TW', lambda: self.fail('不應重複掃描'))
            finally:
                release.set()
            result = owner.result(5)
        self.assertEqual(cache.get_or_scan('TW', payload)['scan']['id'], result['scan']['id'])

    def test_cache_is_bounded_and_retains_recently_used_scopes(self):
        cache = FocusScanCache(max_entries=2)
        scan = Mock(side_effect=payload)
        cache.get_or_scan('A', scan)
        cache.get_or_scan('B', scan)
        cache.get_or_scan('A', scan)
        cache.get_or_scan('C', scan)
        cache.get_or_scan('A', scan)
        self.assertEqual(scan.call_count, 3)
        cache.get_or_scan('B', scan)
        self.assertEqual(scan.call_count, 4)


class FocusHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 執行實際處理方法；隔離大型服務的匯入副作用與行情背景工作。
        tree = ast.parse((ROOT / 'server/server.py').read_text(encoding='utf-8'))
        handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Handler')
        method = next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == '_handle_focus')
        cls.handler_type = type('Handler', (), {})
        namespace = {'Handler': cls.handler_type, 'json': json, 'parse_qs': parse_qs, 'urlparse': urlparse}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '焦點處理程序', 'exec'), namespace)
        cls.handler_type._handle_focus = namespace['_handle_focus']

    def setUp(self):
        self.handler_type._FOCUS_CACHE = FocusScanCache()

    def request(self, path, builder):
        handler = self.handler_type()
        handler.path, handler._build_focus = path, builder
        handler._ok, handler._err = Mock(), Mock()
        handler._handle_focus()
        return handler

    def test_aliases_share_cache_but_markets_and_sectors_remain_separate(self):
        builder = Mock(return_value=payload())
        for url in ['/focus', '/focus?mkt=tw&sector=all', '/focus?sector=全部']:
            handler = self.request(url, builder)
            self.assertTrue(json.loads(handler._ok.call_args.args[0])['ok'])
        self.assertEqual(builder.call_count, 1)
        self.request('/focus?mkt=US&sector=電子', builder)
        self.request('/focus?mkt=US', builder)
        self.assertEqual(builder.call_count, 2)
        self.request('/focus?mkt=TW&sector=電子', builder)
        self.assertEqual(builder.call_count, 3)
        self.request('/focus?refresh=1', builder)
        self.assertEqual(builder.call_count, 4)

    def test_failures_are_explicit_and_retry_is_possible(self):
        for failure in [TimeoutError('合成逾時'), RuntimeError('不應外洩的錯誤內容')]:
            failed = self.request('/focus', Mock(side_effect=failure))
            failed._ok.assert_not_called()
            self.assertEqual(failed._err.call_args.args[1], 503)
            self.assertNotIn('不應外洩', failed._err.call_args.args[0])
        success = self.request('/focus', Mock(return_value=payload()))
        success._ok.assert_called_once()

    def test_http_requests_share_scan_and_return_completion_metadata(self):
        entered, joined, release = threading.Event(), threading.Event(), threading.Event()
        calls = []

        class ObservedFuture(Future):
            def result(self, timeout=None):
                joined.set()
                return super().result(timeout=timeout)

        class HTTPHandler(self.handler_type, BaseHTTPRequestHandler):
            def do_GET(self):
                self._handle_focus()

            def _build_focus(self, market, sector):
                calls.append((market, sector))
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('測試未釋放 HTTP 掃描')
                return payload()

            def _ok(self, body):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), HTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port) + '/focus'
        def request(path):
            with urlopen(base + path, timeout=5) as response:
                return json.load(response)
        try:
            with patch.object(focus_cache, 'Future', ObservedFuture), ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(request, '?refresh=1')
                self.assertTrue(entered.wait(5))
                second = pool.submit(request, '?refresh=1')
                try:
                    self.assertTrue(joined.wait(5))
                finally:
                    release.set()
                results = [first.result(5), second.result(5)]
            cached = request('')
            self.assertEqual(calls, [('TW', '')])
            self.assertEqual(len({result['scan']['id'] for result in results + [cached]}), 1)
            self.assertEqual(sum(result['scan']['shared'] for result in results), 1)
            self.assertTrue(cached['scan']['cacheHit'])
            self.assertRegex(cached['scan']['completedAt'], r'^\d{4}-\d{2}-\d{2}T')
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(5)


if __name__ == '__main__':
    unittest.main()

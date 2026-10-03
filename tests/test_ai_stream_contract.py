"""模型串流生命週期；所有推理為 fixtures，HTTP 僅使用暫時的 loopback 測試伺服器。"""
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import ai_local
import ai_routes
from daemon_lock import acquire_daemon_lock, release_daemon_lock


class Response(io.BytesIO):
    def __init__(self, items, sse=True):
        data = ''.join(('data: ' if sse else '') + (item if isinstance(item, str) else json.dumps(item)) + '\n' for item in items)
        super().__init__(data.encode())


class Handler(ai_routes.AiRoutesMixin):
    def __init__(self, accept='text/event-stream'):
        self.payload = {'prompt': '測試', 'context': '已知快照'}
        self.headers = {'Accept': accept}
        self.wfile = io.BytesIO()
        self.sent = {}

    def _ensure_trace_id(self): return 'ai-test'
    def send_response(self, code): self.code = code
    def send_header(self, key, value): self.sent[key] = value
    def end_headers(self): pass
    def _err(self, message, code=500): self.code = code; self.wfile.write(message.encode())


class AiStreamContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        metadata = {'available': True, 'mode': 'fast', 'provider': 'fixture', 'model': 'fixture', 'dataBoundary': 'local-only'}
        for patcher in [
            mock.patch.object(ai_local, 'TRACE_PATH', self.root / 'trace.jsonl'),
            mock.patch.object(ai_local, 'FAST_LOCK_DIR', self.root / 'locks'),
            mock.patch.object(ai_local, 'route_metadata', return_value=metadata),
            mock.patch.object(ai_local, '_acquire_st_slot', return_value=(True, None)),
            mock.patch.object(ai_local, '_release_st_slot'),
            mock.patch.object(ai_routes, 'read_json_body', side_effect=lambda handler, **kw: handler.payload),
            mock.patch.dict(sys.modules, {'wavedeck_bus': SimpleNamespace(record_st_local=lambda *a: None)}),
        ]:
            patcher.start(); self.addCleanup(patcher.stop)

    def test_lmstudio_eof_and_nonstop_finish_are_not_success(self):
        for reason in [None, 'length', 'content_filter', 'tool_calls', 'other']:
            with self.subTest(reason=reason):
                items = [{'choices': [{'delta': {'content': '部分正文'}, 'finish_reason': reason}]}]
                if reason is not None: items.append('[DONE]')
                with mock.patch.object(ai_local.urllib.request, 'urlopen', return_value=Response(items)):
                    with self.assertRaises(ai_local.AiCompletionError):
                        list(ai_local._stream_lmstudio('測試'))

    def test_bad_model_frame_cannot_be_silently_dropped(self):
        for sse, stream in [(True, ai_local._stream_lmstudio), (False, ai_local._stream_ollama)]:
            with mock.patch.object(ai_local.urllib.request, 'urlopen', return_value=Response(['{broken'], sse)):
                with self.assertRaises(ai_local.AiCompletionError): list(stream('測試'))

    def test_ollama_requires_done_and_visible_text(self):
        for items in [
            [{'message': {'content': '部分正文'}}],
            [{'message': {'content': '部分正文'}, 'done': True, 'done_reason': 'length'}],
            [{'done': True}],
            [{'message': {'content': '  \n'}, 'done': True}],
            [{'error': '供應商失敗'}],
        ]:
            with self.subTest(items=items), mock.patch.object(ai_local.urllib.request, 'urlopen', return_value=Response(items, False)):
                with self.assertRaises(ai_local.AiCompletionError): list(ai_local._stream_ollama('測試'))
        with mock.patch.object(ai_local.urllib.request, 'urlopen', return_value=Response([
            {'message': {'content': '正文'}, 'done': True, 'done_reason': 'stop'},
        ], False)):
            self.assertEqual(''.join(ai_local._stream_ollama('測試')), '正文')

    def test_whitespace_stop_is_not_a_visible_answer(self):
        with mock.patch.object(ai_local.urllib.request, 'urlopen', return_value=Response([
            {'choices': [{'delta': {'content': '  \n'}, 'finish_reason': 'stop'}]}, '[DONE]',
        ])):
            with self.assertRaisesRegex(ai_local.AiCompletionError, '未回傳可見正文'):
                list(ai_local._stream_lmstudio('測試'))

    def test_http_success_done_plain_compatibility_and_error_without_done(self):
        for accept in ['text/event-stream', 'text/plain']:
            handler = Handler(accept)
            with mock.patch.object(ai_local, 'chat_stream', return_value=iter(['正文'])):
                handler._handle_ai_local()
            body = handler.wfile.getvalue().decode()
            if accept == 'text/plain': self.assertEqual(body, '正文')
            else: self.assertEqual([json.loads(f[6:])['type'] for f in body.strip().split('\n\n')], ['delta', 'done'])
        def fail(*args, **kw):
            yield '部分正文'
            raise ai_local.AiCompletionError('內容未完成')
        handler = Handler()
        with mock.patch.object(ai_local, 'chat_stream', side_effect=fail): handler._handle_ai_local()
        body = handler.wfile.getvalue().decode()
        self.assertIn('"type": "error"', body)
        self.assertNotIn('"type": "done"', body)

    def test_empty_http_stream_is_error(self):
        handler = Handler()
        with mock.patch.object(ai_local, 'chat_stream', return_value=iter(['  '])): handler._handle_ai_local()
        self.assertNotIn('"type": "done"', handler.wfile.getvalue().decode())

    def test_disconnect_before_first_token_cancels_worker(self):
        finished = threading.Event()
        class BrokenWriter(io.BytesIO):
            def write(self, value): raise BrokenPipeError()
        def wait_for_cancel(*args, cancel_event=None, **kw):
            try:
                cancel_event.wait(3)
                if not cancel_event.is_set(): raise AssertionError('未通知取消')
                yield '不可送出'
            finally: finished.set()
        handler = Handler(); handler.wfile = BrokenWriter()
        with mock.patch.object(ai_local, 'chat_stream', side_effect=wait_for_cancel): handler._handle_ai_local()
        self.assertTrue(finished.wait(1))

    def test_same_process_overlap_and_generator_close_release_lock(self):
        with mock.patch.object(ai_local, '_stream_lmstudio', return_value=iter(['正文', '續文'])):
            first = ai_local.chat_stream('測試')
            self.assertEqual(next(first), '正文')
            with self.assertRaisesRegex(ai_local.AiRuntimeError, '另一份分析'):
                next(ai_local.chat_stream('第二份'))
            first.close()
        lock = acquire_daemon_lock('fast-ai', lock_dir=self.root / 'locks')
        self.assertIsNotNone(lock); release_daemon_lock(lock)

    def test_cross_process_model_lock(self):
        lock = acquire_daemon_lock('fast-ai', lock_dir=self.root / 'locks')
        try:
            script = 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from daemon_lock import acquire_daemon_lock; print(acquire_daemon_lock("fast-ai", lock_dir=Path(sys.argv[2])) is None)'
            result = subprocess.run([sys.executable, '-c', script, str(Path(ai_local.__file__).parent), str(self.root / 'locks')], capture_output=True, text=True, timeout=10, check=True)
            self.assertEqual(result.stdout.strip(), 'True')
        finally: release_daemon_lock(lock)

    def test_socket_timeout_uses_precise_deadline_not_stale_windows_tick(self):
        # 固定在前一個 15.625ms tick，重現 Windows socket 先逾時、粗時計尚未跳動。
        # 不依賴排程運氣，亦驗證 HTTP timeout budget 與期限使用相同精時計。
        for provider in ['lmstudio', 'ollama']:
            with self.subTest(provider=provider):
                clock = [100.0]
                coarse = [100.0]
                seen_timeout = []
                class ExpiredResponse(io.BytesIO):
                    def __iter__(self):
                        clock[0] = 100.301
                        coarse[0] = 100.296875
                        raise TimeoutError('timed out')
                def open_response(request, timeout):
                    seen_timeout.append(timeout)
                    return ExpiredResponse()
                def acquire_slot():
                    clock[0] = 100.05
                    coarse[0] = 100.046875
                    return True, None
                with mock.patch.object(ai_local.time, 'monotonic', side_effect=lambda: coarse[0]), \
                     mock.patch.object(ai_local.time, 'perf_counter', side_effect=lambda: clock[0]), \
                     mock.patch.object(ai_local, 'FAST_SOCKET_TIMEOUT', 0.3), \
                     mock.patch.object(ai_local, 'FAST_PROVIDER', provider), \
                     mock.patch.object(ai_local, '_acquire_st_slot', side_effect=acquire_slot), \
                     mock.patch.object(ai_local._StreamControl, 'watch'), \
                     mock.patch.object(ai_local.urllib.request, 'urlopen', side_effect=open_response):
                    with self.assertRaisesRegex(ai_local.AiRuntimeError, '超過等待上限'):
                        list(ai_local.chat_stream('測試'))
                self.assertAlmostEqual(seen_timeout[0], 0.25)

    def test_early_transport_timeout_is_not_claimed_as_total_deadline(self):
        clock = [100.0]
        def early_failure(*args, **kw):
            clock[0] = 100.1
            raise TimeoutError('供應商提早逾時')
        with mock.patch.object(ai_local.time, 'perf_counter', side_effect=lambda: clock[0]), \
             mock.patch.object(ai_local, 'FAST_SOCKET_TIMEOUT', 10), \
             mock.patch.object(ai_local.urllib.request, 'urlopen', side_effect=early_failure):
            with self.assertRaisesRegex(ai_local.AiRuntimeError, '快速摘要失敗：TimeoutError'):
                list(ai_local.chat_stream('測試'))

    def test_coarse_socket_timeout_waits_for_actual_precise_deadline(self):
        for wrapped in [False, True]:
            with self.subTest(wrapped=wrapped):
                clock = [100.0]
                cancelled = threading.Event()
                waits = []
                def timeout(*args, **kwargs):
                    clock[0] = 100.29
                    error = TimeoutError('timed out')
                    raise ai_local.urllib.error.URLError(error) if wrapped else error
                def wait(remaining):
                    waits.append(remaining)
                    self.assertLess(clock[0], 100.3)
                    clock[0] = 100.301
                    return False
                with mock.patch.object(ai_local.time, 'perf_counter', side_effect=lambda: clock[0]), \
                     mock.patch.object(ai_local.time, 'get_clock_info', return_value=SimpleNamespace(resolution=0.015625)), \
                     mock.patch.object(ai_local, 'FAST_SOCKET_TIMEOUT', 0.3), \
                     mock.patch.object(cancelled, 'wait', side_effect=wait), \
                     mock.patch.object(ai_local.urllib.request, 'urlopen', side_effect=timeout):
                    with self.assertRaisesRegex(ai_local.AiRuntimeError, '超過等待上限'):
                        list(ai_local.chat_stream('測試', cancel_event=cancelled))
                self.assertEqual(len(waits), 1)
                self.assertAlmostEqual(waits[0], 0.01)

    def test_cancel_during_clock_alignment_keeps_cancel_semantics(self):
        clock = [100.0]
        cancelled = threading.Event()
        def timeout(*args, **kwargs):
            clock[0] = 100.29
            raise TimeoutError('timed out')
        def cancel(remaining):
            cancelled.set()
            return True
        with mock.patch.object(ai_local.time, 'perf_counter', side_effect=lambda: clock[0]), \
             mock.patch.object(ai_local.time, 'get_clock_info', return_value=SimpleNamespace(resolution=0.015625)), \
             mock.patch.object(ai_local, 'FAST_SOCKET_TIMEOUT', 0.3), \
             mock.patch.object(cancelled, 'wait', side_effect=cancel), \
             mock.patch.object(ai_local.urllib.request, 'urlopen', side_effect=timeout):
            with self.assertRaisesRegex(ai_local.AiCancelledError, '已取消'):
                list(ai_local.chat_stream('測試', cancel_event=cancelled))

    def test_cancel_wins_over_simultaneous_deadline_and_socket_error(self):
        clock = [100.0]
        cancelled = threading.Event()
        def interrupted_failure(*args, **kw):
            clock[0] = 100.301
            cancelled.set()
            raise TimeoutError('timed out')
        with mock.patch.object(ai_local.time, 'perf_counter', side_effect=lambda: clock[0]), \
             mock.patch.object(ai_local, 'FAST_SOCKET_TIMEOUT', 0.3), \
             mock.patch.object(ai_local.urllib.request, 'urlopen', side_effect=interrupted_failure):
            with self.assertRaisesRegex(ai_local.AiCancelledError, '已取消'):
                list(ai_local.chat_stream('測試', cancel_event=cancelled))

    def test_total_deadline_and_cancel_interrupt_a_silent_socket(self):
        ready = threading.Event(); stop = threading.Event()
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                self.wfile.flush(); ready.set(); stop.wait(3)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        server.daemon_threads = True
        serving = threading.Thread(target=server.serve_forever, daemon=True); serving.start()
        try:
            for cancel in [False, True]:
                ready.clear(); cancelled = threading.Event()
                timer = None
                if cancel:
                    timer = threading.Timer(0.25, cancelled.set); timer.start()
                started = time.monotonic()
                with mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', 'http://127.0.0.1:%d/' % server.server_port), \
                     mock.patch.object(ai_local, 'FAST_SOCKET_TIMEOUT', 2 if cancel else 0.3):
                    with self.assertRaisesRegex(ai_local.AiRuntimeError, '取消' if cancel else '超過等待上限'):
                        list(ai_local.chat_stream('測試', cancel_event=cancelled))
                if timer: timer.join()
                self.assertTrue(ready.is_set())
                self.assertLess(time.monotonic() - started, 1.5)
        finally:
            stop.set(); server.shutdown(); server.server_close(); serving.join()

    def test_deep_cancel_kills_and_reaps_without_success(self):
        cancelled = threading.Event()
        process = mock.Mock(returncode=None)
        def communicate(input=None, timeout=None):
            if timeout is None:
                process.returncode = -1
                return '', ''
            cancelled.set()
            raise subprocess.TimeoutExpired('fixture', timeout)
        process.communicate.side_effect = communicate
        with mock.patch.object(ai_local, '_resolve_hermes_exe', return_value=Path('fixture.exe')), \
             mock.patch.object(ai_local.subprocess, 'Popen', return_value=process):
            with self.assertRaises(ai_local.AiCancelledError): list(ai_local.deep_stream('測試', cancel_event=cancelled))
        process.kill.assert_called_once()
        self.assertEqual(process.returncode, -1)
        self.assertNotIn('"event": "completed"', (self.root / 'trace.jsonl').read_text(encoding='utf-8'))


if __name__ == '__main__': unittest.main()

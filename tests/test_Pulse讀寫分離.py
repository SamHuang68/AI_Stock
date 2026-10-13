"""真實 HTTP、SQLite 與受控工作驗證 Pulse 讀寫邊界。"""
import copy
import json
import os
import shutil
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_decision_http import st_server, dc, ew, _pulse
import decision_store
from pulse_updates import PulseUpdates


class PulseReadWriteTest(unittest.TestCase):
    def _boundary_connection(self):
        import http.client
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port,
                                                 timeout=3)
        self.addCleanup(connection.close)
        return connection

    def _boundary_following_status(self, connection, previous_socket, *, reusable):
        connection.request('GET', '/pulse/update-status')
        if reusable:
            self.assertIs(connection.sock, previous_socket)
        else:
            self.assertIsNot(connection.sock, previous_socket)
        with connection.getresponse() as response:
            self.assertEqual(response.status, 200)
            json.loads(response.read())
        self.assertFalse(self.queue_db.exists())

    def test_stdlib_errors_close_declared_body_and_next_request_is_clean(self):
        missing = str(Path(self.temp.name) / 'missing-static.txt')
        self.assertFalse(Path(missing).exists())
        close_original = st_server.close_rejected_body
        for method, path, expected in (
                ('PUT', '/boundary-no-route', 501),
                ('PATCH', '/boundary-no-route', 501),
                ('DELETE', '/boundary-no-route', 501),
                ('GET', '/assets/boundary-missing.txt', 404)):
            with self.subTest(method=method, expected=expected):
                connection = self._boundary_connection()
                # 真 stdlib send_head 缺檔，路徑限定在本測試的隔離目錄。
                with patch.object(st_server.Handler, 'translate_path', return_value=missing), \
                        patch.object(st_server, 'close_rejected_body', wraps=close_original) as close:
                    connection.request(method, path, body=b'{}')
                    previous_socket = connection.sock
                    with connection.getresponse() as response:
                        self.assertEqual(response.status, expected)
                        self.assertEqual(response.getheader('Connection'), 'close')
                        self.assertTrue(response.will_close)
                        response.read()
                    close.assert_called_once()
                    self._boundary_following_status(connection, previous_socket, reusable=False)
                    close.assert_called_once()
                connection.close()

    def test_header_parser_error_before_headers_assignment_returns_431(self):
        import http.client
        original_parser = http.client.parse_headers
        test_thread = threading.current_thread()
        raised = threading.Event()

        def read_then_reject(*args, **kwargs):
            headers = original_parser(*args, **kwargs)
            # 先由真正 parser 讀完 header，避免把未讀 header 的 RST 混進 guard。
            # client 接收回應時仍走原 parser，僅拒絕服務端第一次解析。
            if threading.current_thread() is not test_thread and not raised.is_set():
                raised.set()
                raise http.client.HTTPException('合成標頭解析失敗')
            return headers

        connection = self._boundary_connection()
        with patch.object(http.client, 'parse_headers', side_effect=read_then_reject), \
                patch.object(st_server, 'close_rejected_body', wraps=st_server.close_rejected_body) as close:
            connection.request('GET', '/pulse/update-status')
            with connection.getresponse() as response:
                self.assertEqual(response.status, 431)
                self.assertEqual(response.getheader('Connection'), 'close')
                response.read()
            self.assertTrue(raised.is_set())
            close.assert_not_called()
        self.assertFalse(self.queue_db.exists())

    def test_request_line_error_before_headers_exists_returns_original_error(self):
        import socket
        with socket.create_connection(('127.0.0.1', self.http.server_port), timeout=3) as connection:
            connection.sendall(b'GET / HTTP/not-a-number\r\n')
            result = bytearray()
            while True:
                part = connection.recv(4096)
                if not part:
                    break
                result.extend(part)
            # stdlib 在 request_version 尚未建立時使用 HTTP/0.9 形式的 HTML 本文。
            self.assertIn(b'Error code: 400', result)
            self.assertIn(b'Bad request version', result)
        self.assertFalse(self.queue_db.exists())

    def test_options_with_declared_body_closes_but_preserves_204(self):
        connection = self._boundary_connection()
        with patch.object(st_server, 'close_rejected_body', wraps=st_server.close_rejected_body) as close:
            connection.request('OPTIONS', '/bridge/wavedeck', body=b'{}',
                               headers={'Origin': 'http://127.0.0.1:18433'})
            previous_socket = connection.sock
            with connection.getresponse() as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(response.getheader('Connection'), 'close')
                self.assertTrue(response.will_close)
                self.assertEqual(response.getheader('Access-Control-Allow-Origin'),
                                 'http://127.0.0.1:18433')
                self.assertEqual(response.read(), b'')
            close.assert_called_once()
            self._boundary_following_status(connection, previous_socket, reusable=False)
            close.assert_called_once()

    def test_options_without_body_preserves_204_and_same_connection(self):
        connection = self._boundary_connection()
        with patch.object(st_server, 'close_rejected_body', wraps=st_server.close_rejected_body) as close:
            # 直接送標頭，保證沒有被 client 自動補 Content-Length: 0。
            connection.putrequest('OPTIONS', '/bridge/wavedeck')
            connection.putheader('Origin', 'http://127.0.0.1:18433')
            connection.endheaders()
            previous_socket = connection.sock
            with connection.getresponse() as response:
                self.assertEqual(response.status, 204)
                self.assertIsNone(response.getheader('Connection'))
                self.assertFalse(response.will_close)
                self.assertEqual(response.read(), b'')
            close.assert_not_called()
            self._boundary_following_status(connection, previous_socket, reusable=True)
            close.assert_not_called()


    def run(self, result=None):
        own_result = result is None
        self.test_result = self.defaultTestResult() if own_result else result
        if own_result:
            self.test_result.startTestRun()
        try:
            return super().run(self.test_result)
        finally:
            if own_result:
                self.test_result.stopTestRun()

    def setUp(self):
        self._cleanup_attempted = False
        self.temp = types.SimpleNamespace(name=tempfile.mkdtemp(prefix='pulse-rw-'))
        self.temp_root = Path(tempfile.gettempdir()).resolve()
        self.release = threading.Event()
        self.queue = self.http = self.thread = None
        self.patches = []
        self.addCleanup(self.cleanup_isolation)
        flags = patch.dict(os.environ, {'ST_SHADOW_EARLY_WARNING': '1'})
        flags.start(); self.patches.append(flags)
        folder = Path(self.temp.name)
        self.db = str(folder / 'decision.db')
        self.queue_db = folder / 'updates.db'
        self.release = threading.Event()
        self.queue = PulseUpdates(db_path=str(self.queue_db), trace_path=str(folder / 'updates.jsonl'))
        self.delivery = Mock(return_value={'ok': True, 'delivered': 0})
        patches = [
            patch.object(dc, '_latest_context', None), patch.object(dc, '_latest_inputs', None),
            patch.object(dc, '_active_db_path', self.db), patch.object(dc, 'DB_PATH', self.db),
            patch.object(ew, 'DB_PATH', str(folder / 'signals.db')),
            patch.object(st_server, '_pulse_updates', self.queue),
            patch.dict('sys.modules', {
                'overnight_intraday': types.SimpleNamespace(latest_cached=lambda *a: None),
                'alert_daemon': types.SimpleNamespace(deliver_signal_events=self.delivery),
            }),
        ]
        for item in patches:
            item.start()
            self.patches.append(item)
        self.http = st_server.ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.cleanup_isolation()

    def cleanup_isolation(self):
        if self._cleanup_attempted:
            return
        self._cleanup_attempted = True
        self.release.set()
        failures = []
        if self.http is not None:
            try:
                if self.thread is not None and self.thread.is_alive():
                    self.http.shutdown()
                    self.thread.join(2)
                self.http.server_close()
                if self.thread is not None and self.thread.is_alive():
                    failures.append('HTTP 服務未停止')
            except Exception as error:
                failures.append('HTTP 清理：' + type(error).__name__)
        # HTTP 停止失敗仍須通知佇列；原有停止期限維持不變。
        if self.queue is not None:
            try:
                if not self.queue.stop(timeout=3):
                    failures.append('工作者未停止')
            except Exception as error:
                failures.append('工作者停止：' + type(error).__name__)
        if failures:
            # 保留目錄與替身並停止批次，避免未停止的工作者在恢復全域後繼續外寫。
            self.test_result.stop()
            self.fail('；'.join(failures) + '；保留證據目錄與隔離設定：' + self.temp.name)
        for item in reversed(self.patches):
            item.stop()
        target = Path(self.temp.name).resolve()
        if target == self.temp_root or not target.is_relative_to(self.temp_root):
            self.fail('拒絕清理不在測試暫存區內的路徑：' + str(target))
        shutil.rmtree(target)

    def request(self, path, data=None, origin=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(self.base + path, data=(json.dumps(data).encode() if data is not None else None), headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def publish(self, job_id='前版', guard=None):
        pulse = _pulse()
        pulse['updateJobId'] = job_id
        context = dc.build_decision_context(pulse)
        context = dc.publish_context(context, pulse=pulse, db_path=self.db,
                                     trace_path=str(Path(self.temp.name) / 'decision.jsonl'),
                                     publication_guard=guard)
        pulse['decisionSummary'] = dc.compact_context(context)
        return pulse

    def terminal(self, job_id):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            status, result = self.request('/pulse/update-status?jobId=' + job_id)
            self.assertEqual(status, 200)
            if result['job']['status'] not in ('queued', 'running'):
                return result['job']
            threading.Event().wait(0.02)
        import faulthandler
        faulthandler.dump_traceback()
        self.fail('測試工作未在期限內結束；工作收據：' + json.dumps(self.queue.status(), ensure_ascii=False))

    def test_cold_get_refresh_and_status_do_not_create_or_enqueue(self):
        with patch.object(st_server, '_build_pulse_update', side_effect=AssertionError('讀取不可建置')) as builder, \
                patch.object(self.queue, 'submit', side_effect=AssertionError('讀取不可提交')) as submit:
            for route in ('/pulse', '/pulse?refresh=1', '/pulse?refresh=true'):
                status, body = self.request(route)
                self.assertEqual(status, 200)
                self.assertFalse(body['ok'])
                self.assertEqual(body['error'], '尚未有已提交快照')
            self.assertEqual(self.request('/pulse/update-status')[0], 200)
            builder.assert_not_called()
            submit.assert_not_called()
        self.assertFalse(self.queue_db.exists())
        self.assertFalse(Path(self.db).exists())
        self.delivery.assert_not_called()

    def test_worker_entry_uses_existing_orchestration_without_http_constructor(self):
        guard = Mock()
        with patch.object(st_server.Handler, '__init__', side_effect=AssertionError('不能建立 HTTP 請求')), \
                patch.object(st_server._pulse_orchestration, 'build_pulse_payload',
                             return_value=b'{"ok":true,"updateJobId":"fixture"}') as build:
            result = st_server._build_pulse_update('fixture', guard)
        self.assertEqual(result, {'ok': True, 'updateJobId': 'fixture'})
        args, kwargs = build.call_args
        self.assertIsInstance(args[0], st_server.Handler)
        self.assertEqual(args[1], '/pulse?refresh=1')
        self.assertEqual(kwargs, {'job_id': 'fixture', 'publication_guard': guard})
        self.assertFalse(self.queue_db.exists())

    def test_expired_worker_stops_before_cache_or_source_access(self):
        orchestration = st_server._pulse_orchestration
        with patch.object(orchestration._deps, 'cache') as cache:
            guard = Mock(side_effect=RuntimeError('合成工作已逾時'))
            with self.assertRaisesRegex(RuntimeError, '已逾時'):
                orchestration.build_pulse_payload(object(), '/pulse?refresh=1',
                                                 job_id='fixture', publication_guard=guard)
            guard.assert_called_once()
            cache.get.assert_not_called()
            cache.set.assert_not_called()

    def test_get_keeps_committed_identity_and_history_during_blocked_update(self):
        before = self.publish()
        rows = decision_store.read_rows(self.db, 'SELECT revision,snapshot_id FROM decision_commits')
        entered = threading.Event()
        def builder(job_id, guard):
            entered.set()
            self.release.wait(3)
            return self.publish(job_id, guard)
        self.queue.start(builder, dc.latest_pulse)
        self.assertTrue(entered.wait(2))
        started = time.monotonic()
        _, pulse = self.request('/pulse?refresh=1')
        _, full = self.request('/decision/context')
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(pulse['decisionSummary']['snapshotId'], before['decisionSummary']['snapshotId'])
        self.assertEqual(full['snapshotId'], before['decisionSummary']['snapshotId'])
        self.assertEqual(rows, decision_store.read_rows(self.db, 'SELECT revision,snapshot_id FROM decision_commits'))
        self.assertEqual(self.delivery.call_count, 1)
        code, accepted = self.request('/pulse/refresh', {})
        self.assertEqual(code, 202)
        self.assertTrue(accepted['coalesced'])
        self.release.set()
        job = self.terminal(accepted['job']['jobId'])
        self.assertEqual(job['status'], 'succeeded')
        _, pulse = self.request('/pulse')
        self.assertEqual(pulse['updateJobId'], job['jobId'])
        self.assertEqual(pulse['decisionSummary']['snapshotId'], job['result']['snapshotId'])

    def test_failure_is_queryable_and_does_not_replace_previous_snapshot(self):
        before = self.publish()
        def builder(job_id, guard):
            self.release.wait(2)
            raise OSError('注入更新失敗')
        self.queue.start(builder, dc.latest_pulse)
        code, accepted = self.request('/pulse/refresh', {})
        self.assertEqual(code, 202)
        self.release.set()
        job = self.terminal(accepted['job']['jobId'])
        self.assertEqual(job['status'], 'failed')
        self.assertIn('注入更新失敗', job['error'])
        _, after = self.request('/pulse')
        self.assertEqual(before['decisionSummary']['snapshotId'], after['decisionSummary']['snapshotId'])
        self.assertEqual(after['updateState']['job']['status'], 'failed')

    def test_post_validation_origin_and_unknown_status(self):
        self.assertEqual(self.request('/pulse/refresh', {'force': True})[0], 400)
        self.assertEqual(self.request('/pulse/refresh', [], origin=None)[0], 422)
        # 空本文與真正 JSON 本文都必須收到明確拒絕。
        self.assertEqual(self.request('/pulse/refresh', origin='https://example.invalid', method='POST')[0], 403)
        self.assertEqual(self.request('/pulse/refresh', {}, origin='https://example.invalid')[0], 403)
        self.assertEqual(self.request('/pulse/update-status?jobId=missing')[0], 404)
        self.assertEqual(self.request('/pulse/update-status?jobId=..%2Fsecret')[0], 400)
        self.assertFalse(self.queue_db.exists())

    def test_get_method_rejection_also_closes_declared_body(self):
        import http.client
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
        try:
            connection.request('GET', '/sync', body=b'{}')
            with connection.getresponse() as response:
                self.assertEqual(response.status, 405)
                self.assertEqual(response.getheader('Connection'), 'close')
                self.assertTrue(response.will_close)
                response.read()
        finally:
            connection.close()

    def test_early_post_rejection_closes_connection_without_parsing_leftover_body(self):
        import http.client
        for status, headers, body in (
                (403, {'Origin': 'https://example.invalid', 'Content-Type': 'application/json'}, b'{}'),
                (415, {'Content-Type': 'text/plain'}, b'{}'),
                (413, {'Content-Type': 'application/json', 'Content-Length': '999999'}, b'{}'),
                (400, {'Content-Type': 'application/json', 'Content-Length': 'invalid'}, b'{}'),
                (400, {'Content-Type': 'application/json', 'Content-Length': '-1'}, b'{}')):
            with self.subTest(status=status):
                connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
                try:
                    connection.request('POST', '/pulse/refresh', body=body, headers=headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, status)
                    self.assertEqual(response.getheader('Connection'), 'close')
                    self.assertTrue(response.will_close)
                    self.assertIn('error', json.loads(response.read()))
                    connection.request('GET', '/pulse/update-status')
                    with connection.getresponse() as next_response:
                        self.assertEqual(next_response.status, 200)
                        next_response.read()
                finally:
                    connection.close()
        self.assertFalse(self.queue_db.exists())

    def test_expired_publication_is_rejected_before_intent_warning_and_commit(self):
        before = self.publish()
        def expired():
            raise TimeoutError('更新已超過期限')
        with self.assertRaises(dc.SnapshotPublicationError):
            self.publish('逾時工作', expired)
        self.assertEqual(dc.latest_context()['snapshotId'], before['decisionSummary']['snapshotId'])
        self.assertEqual(decision_store.pending(self.db), [])
        self.assertEqual(self.delivery.call_count, 1)

    def test_gateway_reader_can_read_but_only_owner_can_submit(self):
        import private_web_gateway as gateway
        settings = types.SimpleNamespace(extra_read_paths=(), extra_control_paths=())
        for role in ('reader', 'owner'):
            self.assertTrue(gateway.route_permission('GET', '/pulse', role, settings))
            self.assertTrue(gateway.route_permission('GET', '/pulse/update-status', role, settings))
        self.assertFalse(gateway.route_permission('POST', '/pulse/refresh', 'reader', settings))
        self.assertTrue(gateway.route_permission('POST', '/pulse/refresh', 'owner', settings))

    def test_completed_job_lookup_finds_older_revision_without_advancing_latest(self):
        first = self.publish('工作甲')
        second = self.publish('工作乙')
        restored = dc.committed_pulse_for_job('工作甲')
        self.assertEqual(restored['decisionSummary']['snapshotId'], first['decisionSummary']['snapshotId'])
        self.assertEqual(dc.latest_context()['snapshotId'], second['decisionSummary']['snapshotId'])
        self.assertIsNone(dc.committed_pulse_for_job('未知工作'))


if __name__ == '__main__':
    unittest.main()

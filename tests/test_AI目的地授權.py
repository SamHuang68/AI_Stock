"""模型目的地綁定：所有 HTTP 與模型皆為離線替身。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import ai_local
import ai_routes
from tests.test_ai_routes_stream import Handler


class DestinationConsentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for patcher in [
            mock.patch.object(ai_local, 'FAST_PROVIDER', 'lmstudio'),
            mock.patch.object(ai_local, 'FAST_MODEL', '測試模型'),
            mock.patch.object(ai_local, 'LMSTUDIO_BASE', 'http://127.0.0.1:1234/v1'),
            mock.patch.object(ai_local, 'LMSTUDIO_MODELS_URL', 'http://127.0.0.1:1234/v1/models'),
            mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', 'http://127.0.0.1:1234/v1/chat/completions'),
            mock.patch.object(ai_local, 'FAST_LOCK_DIR', Path(self.temp.name)),
            mock.patch.object(ai_local, 'TRACE_PATH', Path(self.temp.name) / 'trace.jsonl'),
            mock.patch.object(ai_local, '_acquire_st_slot', return_value=(True, None)),
            mock.patch.object(ai_local, '_release_st_slot'),
            mock.patch.object(ai_local.urllib.request, 'urlopen', side_effect=AssertionError('禁止連線')),
            mock.patch.object(ai_local, '_open_bound', side_effect=AssertionError('禁止連線')),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def expected(self):
        metadata = ai_local.route_metadata('fast', probe=False)
        return {key: metadata[key] for key in ai_local.ROUTE_FIELDS}

    def credential_fixture(self):
        # 具名離線假資料；組合完整認證 URL 驗證去識別化，來源檔不放認證格式字串。
        fixture = {'scheme': 'https', 'username': 'name', 'password': 'secret',
                   'hostname': 'research-endpoint.invalid', 'port': 9443,
                   'path': '/v1', 'query': 'token=secret', 'fragment': 'private'}
        return (f"{fixture['scheme']}://{fixture['username']}:{fixture['password']}@"
                f"{fixture['hostname']}:{fixture['port']}{fixture['path']}"
                f"?{fixture['query']}#{fixture['fragment']}")

    def test_loopback_is_literal_and_destination_never_discloses_secrets(self):
        for host in ['localhost', '127.0.0.1', '[::1]']:
            safe, boundary, valid = ai_local._safe_destination('http://' + host + ':1234/v1')
            self.assertEqual('local-only', boundary)
            self.assertTrue(valid)
        for host in ['127.1', '127.0.0.2', 'localhost.example', 'localhost.', '192.168.1.8', 'example.test']:
            self.assertEqual('external', ai_local._safe_destination('https://' + host + '/v1')[1])
        safe, boundary, valid = ai_local._safe_destination(self.credential_fixture())
        self.assertEqual('https://research-endpoint.invalid:9443/v1', safe)
        self.assertEqual('external', boundary)
        self.assertTrue(valid)
        self.assertFalse(ai_local._safe_destination('file:///private/config')[2])

    def test_status_never_probes_external_models_url(self):
        with mock.patch.object(ai_local, 'LMSTUDIO_MODELS_URL', 'https://example.test/models'), \
             mock.patch.object(ai_local, '_lmstudio_models') as models:
            fast = ai_local.runtime_status()['modes']['fast']
        self.assertEqual('external', fast['dataBoundary'])
        self.assertTrue(fast['probeDeferred'])
        models.assert_not_called()

    def test_endpoint_and_provider_configuration_changes_identity(self):
        before = self.expected()
        for key, value in [
            ('LMSTUDIO_CHAT_URL', 'https://other.test/chat'),
            ('LMSTUDIO_MODELS_URL', 'https://other.test/models'),
            ('LMSTUDIO_BASE', 'https://other.test/v1'),
            ('FAST_MODEL', '另一模型'),
            ('FAST_PROVIDER', 'ollama'),
        ]:
            with self.subTest(key=key), mock.patch.object(ai_local, key, value):
                self.assertNotEqual(before['destinationId'], self.expected()['destinationId'])

    def test_changed_destination_rejected_before_any_probe(self):
        expected = self.expected()
        with mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', 'https://other.test/chat'), \
             mock.patch.object(ai_local, '_lmstudio_models') as models:
            with self.assertRaises(ai_local.AiRouteChangedError):
                ai_local.route_metadata('fast', probe=True, expected_route=expected)
            with self.assertRaises(ai_local.AiRouteChangedError):
                list(ai_local.chat_stream('私人內容', expected_route=expected))
        models.assert_not_called()

    def test_stream_binds_confirmed_url_and_model_after_probe(self):
        expected = self.expected()
        original_url = ai_local.LMSTUDIO_CHAT_URL
        def probe(*args, **kwargs):
            ai_local.LMSTUDIO_CHAT_URL = 'https://changed.test/chat'
            ai_local.FAST_MODEL = '變更模型'
            return ['測試模型']
        with mock.patch.object(ai_local, '_lmstudio_models', side_effect=probe) as models, \
             mock.patch.object(ai_local, '_stream_lmstudio', return_value=iter(['正文'])) as stream:
            self.assertEqual(['正文'], list(ai_local.chat_stream('分析', expected_route=expected)))
        self.assertTrue(models.call_args.kwargs['bound'])
        self.assertEqual(original_url, stream.call_args.kwargs['route']['chatUrl'])
        self.assertEqual('測試模型', stream.call_args.kwargs['route']['model'])

    def test_transport_uses_frozen_route_instead_of_changed_globals(self):
        route = ai_local._fast_settings()
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                return iter([b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n'])
        with mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', 'https://changed.test/chat'), \
             mock.patch.object(ai_local, 'FAST_MODEL', '變更模型'), \
             mock.patch.object(ai_local, '_open_bound', return_value=Response()) as opened:
            self.assertEqual(['ok'], list(ai_local._stream_lmstudio('資料', route=route)))
        request = opened.call_args.args[0]
        self.assertEqual(route['chatUrl'], request.full_url)
        self.assertEqual(route['model'], json.loads(request.data)['model'])

    def test_ollama_external_endpoint_and_bound_transport(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                return iter([b'{"message":{"content":"ok"},"done":true,"done_reason":"stop"}\n'])
        with mock.patch.object(ai_local, 'FAST_PROVIDER', 'ollama'), \
             mock.patch.object(ai_local, 'OLLAMA_CHAT_URL', 'https://example.test/api/chat'), \
             mock.patch.object(ai_local, 'OLLAMA_MODELS_URL', 'https://example.test/api/tags'), \
             mock.patch.object(ai_local, '_ollama_models', return_value=['測試模型']) as models, \
             mock.patch.object(ai_local, '_open_bound', return_value=Response()) as opened:
            metadata = ai_local.route_metadata('fast', probe=False)
            self.assertEqual('external', metadata['dataBoundary'])
            expected = {key: metadata[key] for key in ai_local.ROUTE_FIELDS}
            self.assertEqual(['ok'], list(ai_local.chat_stream('分析', expected_route=expected)))
        self.assertTrue(models.call_args.kwargs['bound'])
        self.assertEqual('https://example.test/api/chat', opened.call_args.args[0].full_url)

    def test_real_http_guard_rejects_stale_destination_without_probe(self):
        expected = self.expected()
        handler = Handler({'prompt': '不得傳送', 'expectedRoute': expected})
        with mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', 'https://other.test/chat'), \
             mock.patch.object(ai_routes, 'read_json_body', return_value=handler.payload), \
             mock.patch.object(ai_local, '_lmstudio_models') as models:
            handler._handle_ai_local()
        self.assertEqual(409, handler.code)
        models.assert_not_called()

    def test_real_http_guard_probes_only_after_matching_and_rechecks_change(self):
        expected = self.expected()
        handler = Handler({'prompt': '不得傳送', 'expectedRoute': expected})
        def probe(*args, **kwargs):
            ai_local.LMSTUDIO_CHAT_URL = 'https://other.test/chat'
            return ['測試模型']
        with mock.patch.object(ai_routes, 'read_json_body', return_value=handler.payload), \
             mock.patch.object(ai_local, '_lmstudio_models', side_effect=probe) as models, \
             mock.patch.object(ai_local, '_stream_lmstudio') as inference:
            handler._handle_ai_local()
        self.assertEqual(409, handler.code)
        self.assertTrue(models.call_args.kwargs['bound'])
        inference.assert_not_called()

    def test_real_http_to_runtime_rebind_prevents_late_endpoint_change(self):
        expected = self.expected()
        handler = Handler({'prompt': '不得傳送', 'expectedRoute': expected})
        def headers_done():
            ai_local.LMSTUDIO_CHAT_URL = 'https://other.test/chat'
        handler.end_headers = headers_done
        with mock.patch.object(ai_routes, 'read_json_body', return_value=handler.payload), \
             mock.patch.object(ai_local, '_lmstudio_models', return_value=['測試模型']) as models, \
             mock.patch.object(ai_local, '_stream_lmstudio') as inference, \
             mock.patch.dict(sys.modules, {'wavedeck_bus': SimpleNamespace(record_st_local=lambda *a, **kw: None)}):
            handler._handle_ai_local()
        self.assertEqual(200, handler.code)
        frames = [json.loads(frame[6:]) for frame in handler.wfile.getvalue().decode().strip().split('\n\n')]
        self.assertEqual(['error'], [frame['type'] for frame in frames])
        self.assertEqual(1, models.call_count)
        inference.assert_not_called()

    def test_hermes_configuration_is_not_inferred_and_structured_call_is_blocked(self):
        with mock.patch.object(ai_local, '_resolve_hermes_exe', return_value=Path('hermes.exe')), \
             mock.patch.object(ai_local.subprocess, 'Popen') as process:
            original = ai_local.route_metadata('deep', probe=False)
            with mock.patch.dict(ai_local.os.environ, {'OPENAI_BASE_URL': self.credential_fixture()}):
                changed = ai_local.route_metadata('deep', probe=False)
            self.assertNotEqual(original['destinationId'], changed['destinationId'])
            self.assertNotIn('secret', json.dumps(changed))
            self.assertFalse(changed['destinationVerified'])
            expected = {key: original[key] for key in ai_local.ROUTE_FIELDS}
            with self.assertRaises(ai_local.AiRouteChangedError):
                list(ai_local.deep_stream('私人內容', expected_route=expected))
        process.assert_not_called()

    def test_redirect_rejected_without_contacting_new_destination(self):
        with self.assertRaises(ai_local.AiRouteChangedError):
            ai_local._NoDestinationRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test')


if __name__ == '__main__':
    unittest.main()

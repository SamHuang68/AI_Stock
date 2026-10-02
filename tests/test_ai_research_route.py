"""研究路由：全部模型與傳輸均為 mock，不執行真實 AI。"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import ai_local
import ai_routes


class Handler(ai_routes.AiRoutesMixin):
    def __init__(self, expected_route):
        self.payload = {'prompt': '不得傳給其他目的地的研究', 'context': '私人研究快照', 'expectedRoute': expected_route}
        self.headers = {'Accept': 'text/event-stream'}
        self.wfile = io.BytesIO()
        self.sent = {}
    def _ensure_trace_id(self): return 'server-receipt-fixture'
    def send_response(self, code): self.code = code
    def send_header(self, key, value): self.sent[key] = value
    def end_headers(self): pass
    def _err(self, message, status=500): self.code = status; self.wfile.write(message.encode())


class ResearchRouteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for patcher in [
            mock.patch.object(ai_local, 'FAST_PROVIDER', 'lmstudio'),
            mock.patch.object(ai_local, 'FAST_MODEL', 'fixture-model'),
            mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', 'http://127.0.0.1:1234/v1/chat/completions'),
            mock.patch.object(ai_local, '_lmstudio_models', return_value=['fixture-model']),
            mock.patch.object(ai_local.urllib.request, 'getproxies', return_value={}),
            mock.patch.object(ai_local, '_acquire_st_slot', return_value=(True, None)),
            mock.patch.object(ai_local, '_release_st_slot'),
            mock.patch.object(ai_local, 'FAST_LOCK_DIR', self.root / 'locks'),
            mock.patch.object(ai_local, 'TRACE_PATH', self.root / 'trace.jsonl'),
            mock.patch.object(ai_routes, 'read_json_body', side_effect=lambda handler, **kw: handler.payload),
            mock.patch.dict(sys.modules, {'wavedeck_bus': SimpleNamespace(record_st_local=lambda *a: None)}),
        ]:
            patcher.start(); self.addCleanup(patcher.stop)
        self.metadata = ai_local.route_metadata('fast', probe=False)
        self.expected = self.metadata['expectedRoute']

    def response(self):
        return io.BytesIO(('data: ' + json.dumps({'choices': [{'delta': {'content': '完成正文'}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n').encode())

    def test_status_identity_is_stable_public_and_matches_actual_boundary(self):
        local = ai_local.route_metadata('fast', probe=False)
        self.assertTrue(local['destinationVerified'])
        self.assertEqual(local['destination'], 'http://127.0.0.1:1234')
        self.assertEqual(local['dataBoundary'], 'local-only')
        self.assertEqual(local['destinationId'], self.metadata['destinationId'])
        for url, boundary in [('http://[::1]:1234/v1/chat/completions', 'local-only'),
                              ('https://research.example/v1/chat/completions', 'external')]:
            with self.subTest(url=url), mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', url):
                item = ai_local.route_metadata('fast', probe=False)
                self.assertTrue(item['destinationVerified'])
                self.assertEqual(item['dataBoundary'], boundary)
                self.assertNotEqual(item['destinationId'], local['destinationId'])

    def test_sensitive_or_ambiguous_destination_is_not_published_as_verified(self):
        for url in ['http://user:private-password@example.test/v1', 'http://example.test/v1?api_key=secret-token',
                    'http://example.test/v1#secret-fragment', 'file:///private/config', 'http://localhost:0/v1', 'http://localhost:bad/v1']:
            with self.subTest(url=url), mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', url):
                metadata = ai_local.route_metadata('fast', probe=False)
                self.assertFalse(metadata['destinationVerified'])
                self.assertEqual(metadata['destination'], '')
                self.assertEqual(metadata['destinationId'], '')
                self.assertIsNone(metadata['expectedRoute'])
                self.assertNotIn('private-password', json.dumps(metadata))
                self.assertNotIn('secret-token', json.dumps(metadata))
                self.assertNotIn('secret-fragment', json.dumps(metadata))

    def test_active_proxy_is_not_silently_bypassed_or_published(self):
        with mock.patch.object(ai_local.urllib.request, 'getproxies', return_value={'http': 'http://user:proxy-secret@proxy.example:8080'}), \
             mock.patch.object(ai_local.urllib.request, 'proxy_bypass', return_value=False), \
             mock.patch.object(ai_local, '_research_urlopen') as opened:
            metadata = ai_local.route_metadata('fast', probe=False)
            self.assertFalse(metadata['destinationVerified'])
            self.assertIn('環境代理', metadata['destinationReason'])
            self.assertNotIn('proxy-secret', json.dumps(metadata))
            with self.assertRaises(ai_local.AiRouteMismatchError):
                list(ai_local.chat_stream('研究', expected_route=self.expected))
            opened.assert_not_called()

    def test_ollama_verified_route_uses_its_own_selected_adapter(self):
        response = io.BytesIO(b'{"message":{"content":"fixture"},"done":true,"done_reason":"stop"}\n')
        with mock.patch.object(ai_local, 'FAST_PROVIDER', 'ollama'), \
             mock.patch.object(ai_local, '_ollama_models', return_value=['fixture-model']), \
             mock.patch.object(ai_local, '_research_urlopen', return_value=response) as opened:
            expected = ai_local.route_metadata('fast', probe=False)['expectedRoute']
            self.assertEqual(''.join(ai_local.chat_stream('研究', expected_route=expected)), 'fixture')
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, ai_local.OLLAMA_CHAT_URL)
        self.assertEqual(json.loads(request.data)['model'], 'fixture-model')

    def test_hermes_cannot_claim_verified_destination_from_provider_name(self):
        with mock.patch.object(ai_local, '_resolve_hermes_exe', return_value=Path('mock-hermes.exe')), \
             mock.patch.object(ai_local.subprocess, 'Popen') as process:
            metadata = ai_local.route_metadata('deep', probe=False)
            self.assertTrue(metadata['available'])
            self.assertFalse(metadata['destinationVerified'])
            self.assertIsNone(metadata['expectedRoute'])
            expected = dict(self.expected, mode='deep', provider=metadata['provider'], model=metadata['model'])
            with self.assertRaisesRegex(ai_local.AiRouteMismatchError, '尚未驗證'):
                list(ai_local.deep_stream('研究', expected_route=expected))
            process.assert_not_called()

    def test_http_mismatch_or_missing_fields_never_starts_runtime(self):
        variants = [None, {}, {'model': 'fixture-model'}]
        for key in ai_local._ROUTE_FIELDS:
            variants.append(dict(self.expected, **{key: 'different'}))
        for expected in variants:
            with self.subTest(expected=expected), mock.patch.object(ai_local, 'chat_stream') as stream:
                handler = Handler(expected)
                handler._handle_ai_local()
                self.assertEqual(handler.code, 409)
                stream.assert_not_called()

    def test_matching_http_route_reports_actual_destination_and_receipt(self):
        handler = Handler(self.expected)
        with mock.patch.object(ai_local, '_research_urlopen', return_value=self.response()) as opened:
            handler._handle_ai_local()
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.sent['X-ST-AI-Destination-ID'], self.metadata['destinationId'])
        self.assertEqual(handler.sent['X-ST-AI-Request-ID'], 'server-receipt-fixture')
        self.assertIn('"type": "done"', handler.wfile.getvalue().decode())
        sent = opened.call_args.args[0]
        self.assertEqual(sent.full_url, 'http://127.0.0.1:1234/v1/chat/completions')
        self.assertEqual(json.loads(sent.data)['model'], 'fixture-model')
        self.assertNotIn('expectedRoute', json.loads(sent.data))
        self.assertNotIn('私人研究快照', (self.root / 'trace.jsonl').read_text(encoding='utf-8'))

    def test_change_while_waiting_for_slot_is_rejected_before_transport(self):
        for attribute, new in [('LMSTUDIO_CHAT_URL', 'https://other.example/v1/chat/completions'),
                               ('FAST_MODEL', 'changed-model'), ('FAST_PROVIDER', 'ollama')]:
            with self.subTest(attribute=attribute):
                original = getattr(ai_local, attribute)
                def change():
                    setattr(ai_local, attribute, new)
                    return True, None
                try:
                    with mock.patch.object(ai_local, '_acquire_st_slot', side_effect=change), \
                         mock.patch.object(ai_local, '_research_urlopen') as opened:
                        with self.assertRaisesRegex(ai_local.AiRouteMismatchError, '已改變'):
                            list(ai_local.chat_stream('研究', expected_route=self.expected))
                        opened.assert_not_called()
                finally:
                    setattr(ai_local, attribute, original)

    def test_http_to_worker_route_change_has_error_without_done_or_transport(self):
        handler = Handler(self.expected)
        handler.end_headers = lambda: setattr(ai_local, 'FAST_MODEL', 'after-headers-model')
        with mock.patch.object(ai_local, '_research_urlopen') as opened:
            handler._handle_ai_local()
        body = handler.wfile.getvalue().decode()
        self.assertIn('"type": "error"', body)
        self.assertNotIn('"type": "done"', body)
        opened.assert_not_called()

    def test_verified_transport_uses_frozen_url_and_model(self):
        stream = ai_local._stream_lmstudio
        def changed_globals(*args, **kwargs):
            # 核對後仍固定傳輸快照，不能重新讀 globals 把研究送往另一個端點。
            with mock.patch.object(ai_local, 'FAST_MODEL', 'unselected-model'), \
                 mock.patch.object(ai_local, 'LMSTUDIO_CHAT_URL', 'https://unselected.example/v1'):
                yield from stream(*args, **kwargs)
        with mock.patch.object(ai_local, '_stream_lmstudio', side_effect=changed_globals), \
             mock.patch.object(ai_local, '_research_urlopen', return_value=self.response()) as opened:
            self.assertEqual(''.join(ai_local.chat_stream('研究', expected_route=self.expected)), '完成正文')
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:1234/v1/chat/completions')
        self.assertEqual(json.loads(request.data)['model'], 'fixture-model')

    def test_direct_transport_disables_environment_proxy_and_redirect(self):
        opener = mock.Mock()
        with mock.patch.object(ai_local.urllib.request, 'build_opener', return_value=opener) as build:
            ai_local._research_urlopen(mock.sentinel.request, 12)
        proxy, redirects = build.call_args.args
        self.assertEqual(proxy.proxies, {})
        with self.assertRaises(ai_local.AiRouteMismatchError):
            redirects.redirect_request(None, None, 302, '', {}, 'https://other.example')
        opener.open.assert_called_once_with(mock.sentinel.request, timeout=12)


if __name__ == '__main__': unittest.main()

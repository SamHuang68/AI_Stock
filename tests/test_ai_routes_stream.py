"""AI 串流與報告邊界：僅模擬模型，不呼叫外部推理。"""
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
    def __init__(self, body=None, accept='text/event-stream'):
        self.payload = body or {'prompt': '測試', 'context': '已知快照'}
        self.headers = {'Accept': accept}
        self.wfile = io.BytesIO()
        self.sent = {}
        self.code = None

    def _ensure_trace_id(self): return 'ai-test'
    def send_response(self, code): self.code = code
    def send_header(self, key, value): self.sent[key] = value
    def end_headers(self): pass
    def _ok(self, raw): self.code = 200; self.wfile.write(raw)
    def _err(self, message, code=500): self.code = code; self.wfile.write(json.dumps({'error': message}).encode())


class AiRoutesStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for patcher in [
            mock.patch.object(ai_routes, 'read_json_body', side_effect=lambda handler, **kw: handler.payload),
            mock.patch.object(ai_local, 'TRACE_PATH', Path(self.temp.name) / 'trace.jsonl'),
            mock.patch.object(ai_local, 'route_metadata', return_value={'available': True, 'mode': 'fast', 'dataBoundary': 'local-only'}),
            mock.patch.dict(sys.modules, {'wavedeck_bus': SimpleNamespace(record_st_local=lambda *a, **kw: None, record_st_cloud=lambda *a, **kw: None)}),
        ]:
            patcher.start(); self.addCleanup(patcher.stop)

    def test_structured_error_never_emits_done(self):
        def fail(*a, **kw):
            yield '部分正文'
            raise ai_local.AiCompletionError('內容未完成')
        handler = Handler()
        with mock.patch.object(ai_local, 'chat_stream', side_effect=fail):
            handler._handle_ai_local()
        frames = [json.loads(frame[6:]) for frame in handler.wfile.getvalue().decode().strip().split('\n\n')]
        self.assertEqual([f['type'] for f in frames], ['delta', 'error'])
        self.assertEqual(frames[1]['message'], '內容未完成')
        trace = (Path(self.temp.name) / 'trace.jsonl').read_text()
        self.assertNotIn('http_stream_completed', trace)
        self.assertNotIn('部分正文', trace)

    def test_success_done_and_legacy_plain_text(self):
        for accept in ['text/event-stream', 'text/plain']:
            with self.subTest(accept=accept), mock.patch.object(ai_local, 'chat_stream', return_value=iter(['正文'])):
                handler = Handler(accept=accept)
                handler._handle_ai_local()
                output = handler.wfile.getvalue().decode()
                if accept == 'text/plain': self.assertEqual(output, '正文')
                else: self.assertIn('"type": "done"', output)

    def test_cloud_prompt_only_uses_supplied_market_data(self):
        handler = Handler({'context': '資料日期：2026-09-14；收盤：100', 'positions': {}, 'watches': {}})
        with mock.patch.object(ai_routes.ai_api, 'load_ai_key', return_value='mock-key'), \
             mock.patch.object(ai_routes.ai_api, 'anthropic_messages', return_value=('模擬報告', {'model': 'mock'})) as cloud:
            handler._handle_ai_report()
        self.assertEqual(handler.code, 200)
        prompt = cloud.call_args.args[1][0]['content']
        self.assertIn('資料日期：2026-09-14', prompt)
        self.assertIn('未提供大盤行情', prompt)
        self.assertNotIn('基於昨日', prompt)

    def test_empty_and_truncated_cloud_reports_fail(self):
        for text, reason in [('', 'end_turn'), ('半截報告', 'max_tokens')]:
            handler = Handler()
            with mock.patch.object(ai_routes.ai_api, 'load_ai_key', return_value='mock-key'), \
                 mock.patch.object(ai_routes.ai_api, 'anthropic_messages', return_value=(text, {'stop_reason': reason})):
                handler._handle_ai_report()
            self.assertEqual(handler.code, 502)


if __name__ == '__main__': unittest.main()

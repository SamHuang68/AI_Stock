# -*- coding: utf-8 -*-
"""POST /api/ai/postmarket-daily HTTP 行為 — 驗收 §9：

1. Reader／無 key → 與現有 AI 端點相同拒絕行為
   - 無 key：本機 server 400（同 /ai-proxy 'AI key not set on server'）
   - reader：private_web_gateway route_permission 對 POST 一律拒絕（403）
2. WaveDeck 持有 gate → 503 + Retry-After
3. 成功路徑：200 + X-ST-AI-Request-ID + 回應 schema
4. 批次大小 413 防護
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import ai_api  # noqa: E402
import llm_gate  # noqa: E402
import postmarket_report as pr  # noqa: E402
import private_web_gateway as gateway  # noqa: E402

from http.server import ThreadingHTTPServer  # noqa: E402

# 與 test_decision_http 相同：以無碰撞名稱載入單檔 HTTP server。
_SERVER_SPEC = importlib.util.spec_from_file_location(
    'stock_terminal_http_server_pmd_test', ROOT / 'server' / 'server.py'
)
if _SERVER_SPEC is None or _SERVER_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError('Unable to load Stock Terminal HTTP server for tests')
st_server = importlib.util.module_from_spec(_SERVER_SPEC)
sys.modules[_SERVER_SPEC.name] = st_server
_SERVER_SPEC.loader.exec_module(st_server)


def _bars(days: int = 70):
    end = datetime.now(pr.TZ_TPE)
    rows = []
    for i in range(days):
        day = end - timedelta(days=days - 1 - i)
        close = 500.0 + i
        rows.append((day.timestamp(), close - 2, close + 3, close - 4, close, 8000 + i))
    return rows


def _fake_anthropic(messages, *, system=None, model=None, max_tokens=1024,
                    temperature=None):
    """Research canonical 批次回覆：由 user message 解析 symbols 一次回齊。"""
    import re
    codes = re.findall(r'"symbol":"([0-9A-Z]+)"', messages[0]['content'])
    rows = [{
        'symbol': code,
        'narrative': {
            'conclusion': f'{code} 收盤走高，量能溫和。',
            'drivers': ['收盤價高於 sma20'],
            'hypotheses': ['資金回流權值'],
            'risks': ['短線乖離擴大'],
            'watchTomorrow': ['觀察是否續量'],
        },
        'citations': [{'type': 'quote', 'ref': 'quote.last'}],
    } for code in codes]
    text = json.dumps({'symbols': rows, 'marketBlurb': None}, ensure_ascii=False)
    return text, {'model': model, 'usage': {'input_tokens': 2500, 'output_tokens': 700}}


class PostmarketHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_reports = os.environ.get('ST_REPORTS_DIR')
        os.environ['ST_REPORTS_DIR'] = str(Path(self.tmp.name) / 'reports')
        self._old_gate = llm_gate.GATE_PATH
        llm_gate.GATE_PATH = Path(self.tmp.name) / 'llm_gate.json'
        self._old_load_key = ai_api.load_ai_key
        self._old_model_cache = dict(ai_api._MODEL_CACHE)
        ai_api._MODEL_CACHE.update({'date': datetime.now().strftime('%Y%m%d'),
                                    'id': 'claude-sonnet-4-6'})
        pr.configure(
            bars_fn=lambda code: _bars(),
            chip_fn=lambda code: None,
            news_fn=lambda: {'items': []},
            decision_fn=lambda: None,
            universe_fn=lambda: {},
            sectors_fn=lambda: {},
            anthropic_fn=_fake_anthropic,
        )
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        ai_api.load_ai_key = self._old_load_key
        ai_api._MODEL_CACHE.update(self._old_model_cache)
        llm_gate.GATE_PATH = self._old_gate
        pr.configure(bars_fn=None, chip_fn=None, news_fn=None, decision_fn=None,
                     universe_fn=None, sectors_fn=None, anthropic_fn=None)
        if self._old_reports is None:
            os.environ.pop('ST_REPORTS_DIR', None)
        else:
            os.environ['ST_REPORTS_DIR'] = self._old_reports
        self.tmp.cleanup()

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        return urllib.request.urlopen(req, timeout=15)

    def test_missing_key_rejected_like_existing_ai_endpoints(self):
        """驗收 §9-1：無 key → 與 /ai-proxy 相同拒絕（400 AI key not set）。"""
        ai_api.load_ai_key = lambda: ''
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._post('/api/ai/postmarket-daily', {'symbols': ['2330']})
        self.assertEqual(caught.exception.code, 400)
        body = json.loads(caught.exception.read())
        self.assertIn('AI key not set', body['error'])
        caught.exception.close()

    def test_reader_role_rejected_by_gateway(self):
        """驗收 §9-1：reader 透過 private web gateway → POST 一律 403（route denied）。"""
        settings = SimpleNamespace(extra_control_paths=set(), extra_read_paths=set())
        self.assertIn('/api/ai/postmarket-daily', gateway.CONTROL_POST_EXACT)
        self.assertFalse(gateway.route_permission(
            'POST', '/api/ai/postmarket-daily', 'reader', settings))
        self.assertFalse(gateway.route_permission(
            'POST', '/api/ai/postmarket-daily/abort', 'reader', settings))
        self.assertTrue(gateway.route_permission(
            'POST', '/api/ai/postmarket-daily', 'owner', settings))
        # 與既有 AI 端點一致：owner 可、reader 不可
        self.assertFalse(gateway.route_permission('POST', '/ai-report', 'reader', settings))
        self.assertTrue(gateway.route_permission('POST', '/ai-report', 'owner', settings))

    def test_success_returns_contract_and_request_id_header(self):
        ai_api.load_ai_key = lambda: 'sk-test'
        with self._post('/api/ai/postmarket-daily',
                        {'symbols': ['2330', '2454'], 'locale': 'zh-Hant-TW'}) as resp:
            body = json.loads(resp.read())
            self.assertEqual(resp.status, 200)
            self.assertTrue(resp.headers.get('X-ST-AI-Request-ID'))
        self.assertTrue(body['reportId'].startswith('pmd-'))
        self.assertEqual(body['model'], 'claude-sonnet-4-6')
        self.assertEqual(len(body['symbols']), 2)
        for sym in body['symbols']:
            self.assertIn('evidenceAsOf', sym)
            self.assertIn('quote', sym['evidenceAsOf'])
            narrative = sym['narrative']
            for key in ('conclusion', 'drivers', 'hypotheses', 'risks', 'watchTomorrow'):
                self.assertIn(key, narrative)
        self.assertEqual(body['usage']['inputTokens'], 2500)  # canonical：整批單次呼叫
        self.assertGreater(body['usage']['estUsd'], 0)
        self.assertIn('usageToday', body)
        # 存檔可由 latest 端點讀回
        with urllib.request.urlopen(
                self.base + '/api/ai/postmarket-daily/latest', timeout=5) as resp:
            day = json.loads(resp.read())
        self.assertEqual(day['runs'], 1)
        self.assertEqual(day['latest']['reportId'], body['reportId'])

    def test_wavedeck_gate_returns_503_with_retry_after(self):
        """驗收 §9-5：WD 持有 gate → 503 + Retry-After（不 fallback 本機 deep）。"""
        ai_api.load_ai_key = lambda: 'sk-test'
        self.assertTrue(llm_gate.acquire('wd', ttl_sec=60))
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self._post('/api/ai/postmarket-daily', {'symbols': ['2330']})
            self.assertEqual(caught.exception.code, 503)
            self.assertTrue(caught.exception.headers.get('Retry-After'))
            caught.exception.close()
            self.assertEqual(llm_gate.status()['owner'], 'wd')  # 無雙寫
        finally:
            llm_gate.release('wd')

    def test_oversized_batch_returns_413(self):
        ai_api.load_ai_key = lambda: 'sk-test'
        symbols = [f'{i:04d}' for i in range(1, 23)]
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._post('/api/ai/postmarket-daily', {'symbols': symbols})
        self.assertEqual(caught.exception.code, 413)
        caught.exception.close()

    def test_abort_endpoint_marks_client(self):
        ai_api.load_ai_key = lambda: 'sk-test'
        with self._post('/api/ai/postmarket-daily/abort',
                        {'abortSignalClientId': 'cid-http-1'}) as resp:
            body = json.loads(resp.read())
        self.assertTrue(body['ok'])
        self.assertTrue(pr.is_aborted('cid-http-1'))
        pr.clear_abort('cid-http-1')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._post('/api/ai/postmarket-daily/abort', {})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()


if __name__ == '__main__':
    unittest.main()

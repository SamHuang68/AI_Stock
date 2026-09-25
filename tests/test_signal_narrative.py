# -*- coding: utf-8 -*-
"""P3：AI 白話解讀只能引用證據（逐句驗證）、失敗回模板、批次摘要流程與 HTTP。"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import random
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

import ai_api  # noqa: E402
import signal_digest  # noqa: E402
import signal_narrative as sn  # noqa: E402
import stock_signals as ss  # noqa: E402
import stock_signals_routes as routes  # noqa: E402

TPE = timezone(timedelta(hours=8))


def make_result(seed=7, n=320):
    rnd = random.Random(seed)
    px, bars, d = 100.0, [], date(2025, 1, 2)
    for i in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        px *= 1 + rnd.gauss(0.0005, 0.02)
        vol = 1000.0 if i < n - 1 else 3000.0
        bars.append({'date': d.isoformat(), 'open': px, 'high': px * 1.01, 'low': px * 0.99,
                     'close': px, 'volume': vol})
        d += timedelta(days=1)
    return ss.analyze(bars, symbol='2330', market='TW')


def claude_message(sentences, stop='end_turn'):
    return {'model': 'claude-sonnet-5', 'stop_reason': stop,
            'usage': {'input_tokens': 1500, 'output_tokens': 200, 'cache_read_input_tokens': 1200},
            'content': [{'type': 'text', 'text': json.dumps({'sentences': sentences}, ensure_ascii=False)}]}


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.result = make_result()
        self.pack = sn.build_pack(self.result)

    def test_pack_only_contains_citable_ids(self):
        self.assertIn('health.summary', self.pack)
        self.assertIn('ind.sma60', self.pack)
        for k in self.pack:
            self.assertIn(k, self.result['evidence'])

    def test_accepts_grounded_sentence(self):
        s60 = self.result['indicators']['sma60']
        kept, dropped = sn.validate({'sentences': [
            {'text': f'季線目前在 {s60:.2f}。', 'evidenceIds': ['ind.sma60']}]}, self.pack)
        self.assertEqual(len(kept), 1, dropped)

    def test_percent_maps_to_ratio_and_rounding_tolerance(self):
        pack = {'x': {'value': {'upRatio': 0.4123, 'close': 1234.5}}}
        kept, _ = sn.validate({'sentences': [
            {'text': '上漲比例約 41%，收盤 1,234.5。', 'evidenceIds': ['x']}]}, pack)
        self.assertEqual(len(kept), 1)

    def test_drops_invented_numbers_ids_and_directives(self):
        kept, dropped = sn.validate({'sentences': [
            {'text': '明天會漲到 9999.5。', 'evidenceIds': ['ind.close']},
            {'text': '趨勢向上。', 'evidenceIds': ['light.nope']},
            {'text': '沒有引用。', 'evidenceIds': []},
            {'text': '建議現在買進。', 'evidenceIds': ['health.summary']},
        ]}, self.pack)
        self.assertEqual(kept, [])
        reasons = [d['reason'].split(':')[0] for d in dropped]
        self.assertEqual(reasons, ['unsupported-number', 'unknown-evidence', 'no-evidence', 'banned'])

    def test_schema_failure(self):
        kept, dropped = sn.validate({'text': 'x'}, self.pack)
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]['reason'], 'schema')


class ExplainTests(unittest.TestCase):
    def setUp(self):
        sn._cache.clear()
        self.result = make_result()

    def test_without_key_uses_template_that_cites_real_evidence(self):
        out = sn.explain(self.result, '')
        self.assertEqual(out['source'], 'template')
        self.assertIn('AI Key', out['note'])
        for s in out['sentences']:
            for i in s['evidenceIds']:
                self.assertIn(i, self.result['evidence'])
        kept, dropped = sn.validate({'sentences': out['sentences']}, sn.build_pack(self.result))
        self.assertEqual(len(kept), len(out['sentences']), dropped)   # 模板本身也過得了驗證

    def test_request_payload_shape(self):
        payload = sn.request_payload(self.result, 'claude-sonnet-5')
        self.assertEqual(payload['model'], 'claude-sonnet-5')
        self.assertEqual(payload['system'][0]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(payload['output_config']['format']['type'], 'json_schema')
        self.assertEqual(payload['output_config']['effort'], sn.EFFORT)
        self.assertNotIn('temperature', payload)
        self.assertNotIn('thinking', payload)
        self.assertIn('EVIDENCE = ', payload['messages'][0]['content'])
        self.assertEqual(sn.system_prompt(), payload['system'][0]['text'])   # 固定前綴才能命中快取

    def test_claude_output_is_validated(self):
        close = self.result['indicators']['close']
        good = [{'text': self.result['health']['summary']['sentence'], 'evidenceIds': ['health.summary']},
                {'text': f'最新收盤 {close:.2f}。', 'evidenceIds': ['ind.close']},
                {'text': '明天目標價 999。', 'evidenceIds': ['ind.close']}]
        sent = []
        out = sn.explain(self.result, 'k', model='claude-sonnet-5',
                         call=lambda p: sent.append(p) or claude_message(good))
        self.assertEqual(out['source'], 'claude')
        self.assertEqual(len(out['sentences']), 2)
        self.assertEqual(out['dropped'][0]['reason'].split(':')[0], 'banned')
        self.assertEqual(out['usage']['cache_read_input_tokens'], 1200)
        # 快取：同一張卡不重複花費
        again = sn.explain(self.result, 'k', model='claude-sonnet-5', call=lambda p: self.fail('called twice'))
        self.assertIs(again, out)
        self.assertEqual(len(sent), 1)

    def test_all_sentences_rejected_falls_back_to_template(self):
        bad = [{'text': '一定會漲。', 'evidenceIds': ['health.summary']}]
        out = sn.explain(self.result, 'k', model='m', call=lambda p: claude_message(bad))
        self.assertEqual(out['source'], 'template')
        self.assertIn('未通過證據驗證', out['note'])
        self.assertTrue(out['dropped'])

    def test_refusal_and_http_errors_fall_back(self):
        out = sn.explain(self.result, 'k', model='m', call=lambda p: claude_message([], stop='refusal'))
        self.assertEqual(out['source'], 'template')
        sn._cache.clear()

        def boom(p):
            raise urllib.error.HTTPError('u', 529, 'overloaded', {}, io.BytesIO(b''))
        out = sn.explain(self.result, 'k', model='m', call=boom)
        self.assertEqual(out['source'], 'template')
        self.assertIn('529', out['note'])

    def test_400_on_structured_output_retries_without_format(self):
        calls = []
        summary = self.result['health']['summary']['sentence']

        def call(p):
            calls.append('format' in p.get('output_config', {}))
            if calls[-1]:
                raise urllib.error.HTTPError('u', 400, 'bad', {}, io.BytesIO(b''))
            return claude_message([{'text': summary, 'evidenceIds': ['health.summary']},
                                   {'text': summary, 'evidenceIds': ['health.summary']}])
        out = sn.explain(self.result, 'k', model='old-model', call=call)
        self.assertEqual(calls, [True, False])
        self.assertEqual(out['source'], 'claude')


class BatchDigestTests(unittest.TestCase):
    def test_submit_then_collect(self):
        result = make_result(seed=3)
        summary = result['health']['summary']['sentence']
        created = {}

        def batch_create(key, reqs):
            created['reqs'] = reqs
            return {'id': 'msgbatch_1'}

        state = {}
        with mock.patch.object(ai_api, 'batch_create', batch_create), \
                mock.patch.object(ai_api, 'resolve_model', lambda k: 'claude-sonnet-5'), \
                mock.patch.object(ai_api, 'batch_get', lambda k, i: {'id': i, 'processing_status': 'ended',
                                                                      'results_url': 'x'}), \
                mock.patch.object(ai_api, 'batch_results', lambda k, b: {'TW-2330': {
                    'type': 'succeeded', 'message': claude_message(
                        [{'text': summary, 'evidenceIds': ['health.summary']},
                         {'text': summary, 'evidenceIds': ['health.summary']}])}}), \
                mock.patch.object(signal_digest.routes, 'analyze_symbol', lambda *a, **k: result):
            items = [{'sym': '2330', 'market': 'TW'}]
            ready, narr = signal_digest._ai_batch_step(state, 'TW', '2026-09-25', items, 'k')
            self.assertFalse(ready)
            self.assertEqual(created['reqs'][0]['custom_id'], 'TW-2330')
            self.assertIn('output_config', created['reqs'][0]['params'])
            ready, narr = signal_digest._ai_batch_step(state, 'TW', '2026-09-25', items, 'k')
            self.assertTrue(ready)
            self.assertEqual(narr['2330']['source'], 'claude')
            text = signal_digest.build_digest('TW', items=items, narratives=narr)
        self.assertIn('AI 白話', text)

    def test_timeout_sends_rule_digest(self):
        state = {'aiBatch': {'TW': {'id': 'b', 'day': '2026-09-25', 'submittedAt': 0}}}
        ready, narr = signal_digest._ai_batch_step(state, 'TW', '2026-09-25', [], 'k')
        self.assertTrue(ready)
        self.assertIsNone(narr)

    def test_failed_row_uses_template(self):
        result = make_result(seed=4)
        out = sn.from_batch_result(result, {'type': 'errored'}, 'm')
        self.assertEqual(out['source'], 'template')


class ApiHelperTests(unittest.TestCase):
    def test_default_model_is_current_generation(self):
        self.assertEqual(ai_api.DEFAULT_MODEL, 'claude-sonnet-5')

    def test_payload_without_cache_keeps_plain_system(self):
        p = ai_api.build_messages_payload([], 10, model='m', system='s')
        self.assertEqual(p['system'], 's')
        self.assertNotIn('output_config', p)


SPEC = importlib.util.spec_from_file_location('st_signal_narrative_http_test', SERVER_DIR / 'server.py')
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)


class ExplainHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), ST.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def test_explain_without_key_returns_template(self):
        routes.clear_cache()
        sn._cache.clear()
        def loader(code, market, **kw):
            rnd = random.Random(1)
            px, bars, d = 100.0, [], date(2025, 1, 2)
            for _ in range(300):
                while d.weekday() >= 5:
                    d += timedelta(days=1)
                px *= 1 + rnd.gauss(0, 0.02)
                bars.append({'date': d.isoformat(), 'open': px, 'high': px, 'low': px, 'close': px, 'volume': 1.0})
                d += timedelta(days=1)
            return {'bars': bars, 'source': 'fixture', 'provisional': False, 'staleDays': 0, 'error': None}

        req = urllib.request.Request(self.base + '/stock-signals/explain', method='POST',
                                     data=json.dumps({'sym': '2330'}).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'})
        with mock.patch.object(routes, 'load_bars', loader), \
                mock.patch.object(ai_api, 'load_ai_key', lambda: ''):
            with urllib.request.urlopen(req, timeout=10) as r:
                out = json.load(r)
        self.assertEqual(out['source'], 'template')
        self.assertTrue(out['sentences'])


if __name__ == '__main__':
    unittest.main()

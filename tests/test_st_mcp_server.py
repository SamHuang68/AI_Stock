# -*- coding: utf-8 -*-
"""P3：本機 MCP 伺服器（stdio JSON-RPC、唯讀工具、錯誤處理）。"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('st_mcp_server', ROOT / 'scripts' / 'st_mcp_server.py')
MCP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MCP)


def rpc(method, params=None, mid=1):
    msg = {'jsonrpc': '2.0', 'id': mid, 'method': method}
    if params is not None:
        msg['params'] = params
    return MCP.handle(msg)


class ProtocolTests(unittest.TestCase):
    def test_initialize_negotiates_version(self):
        r = rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}})['result']
        self.assertEqual(r['protocolVersion'], '2025-06-18')
        self.assertIn('tools', r['capabilities'])
        self.assertIn('並非投資建議', r['instructions'])
        self.assertIn('不能宣稱已有優勢', r['instructions'])
        r = rpc('initialize', {'protocolVersion': '1999-01-01'})['result']
        self.assertEqual(r['protocolVersion'], MCP.SUPPORTED_PROTOCOLS[0])

    def test_notifications_get_no_reply(self):
        self.assertIsNone(MCP.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_tools_are_read_only_with_schemas(self):
        tools = rpc('tools/list')['result']['tools']
        names = [t['name'] for t in tools]
        self.assertIn('st_stock_health', names)
        self.assertIn('st_signal_scoreboard', names)
        for t in tools:
            self.assertTrue(t['annotations']['readOnlyHint'])
            self.assertEqual(t['inputSchema']['type'], 'object')
            self.assertFalse(t['inputSchema']['additionalProperties'])

    def test_errors(self):
        self.assertEqual(rpc('nope')['error']['code'], -32601)
        self.assertEqual(rpc('tools/call', {'arguments': {}})['error']['code'], -32602)
        r = rpc('tools/call', {'name': 'missing_tool', 'arguments': {}})['result']
        self.assertTrue(r['isError'])
        r = rpc('tools/call', {'name': 'st_stock_health', 'arguments': {'symbol': '../etc'}})['result']
        self.assertTrue(r['isError'])
        self.assertIn('invalid symbol', r['content'][0]['text'])


class ToolTests(unittest.TestCase):
    def test_stock_health_is_compacted(self):
        card = {'ok': True, 'symbol': '2330', 'market': 'TW', 'asOf': '2026-09-25', 'session': {'provisional': False},
                'health': {'summary': {'sentence': 's', 'overall': 'bull'}, 'invalidation': {'text': 'i'},
                           'lights': [{'key': 'trend', 'label': '趨勢', 'state': 'bull', 'tag': '上升',
                                       'plain': 'p', 'evidenceId': 'light.trend', 'values': {'x': 1}}]},
                'events': [{'signalId': 'a', 'label': 'A', 'direction': 'bull', 'date': 'd', 'status': 'new',
                            'statusLabel': '今日', 'detail': 'dd', 'plain': 'pp', 'evidenceId': 'event.a',
                            'invalidation': {'text': 'x'},
                            'stats': {'horizons': [{'horizon': 5, 'n': 3, 'gate': 'insufficient'}]}}],
                'evidence': {'big': 'x' * 5000}, 'indicators': {'close': 1}}
        seen = []
        with mock.patch.object(MCP, 'http_json', lambda path, body=None: seen.append(path) or card):
            r = rpc('tools/call', {'name': 'st_stock_health', 'arguments': {'symbol': '2330'}})['result']
        self.assertFalse(r['isError'])
        data = json.loads(r['content'][0]['text'])
        self.assertNotIn('evidence', data)
        self.assertEqual(data['events'][0]['stockStats'], [{'horizon': 5, 'n': 3, 'gate': 'insufficient'}])
        self.assertIn('market=TW', seen[0])

    def test_unreachable_st_gives_actionable_message(self):
        def down(path, body=None):
            raise urllib.error.URLError('connection refused')
        with mock.patch.object(MCP, 'http_json', down):
            r = rpc('tools/call', {'name': 'st_signal_catalog', 'arguments': {}})['result']
        self.assertTrue(r['isError'])
        self.assertIn('START_TIP', r['content'][0]['text'])

    def test_decision_compaction(self):
        ctx = {'asOf': 't', 'regime': {'id': 'RISK_ON'}, 'actionEnvelope': {'posture': 'p', 'allowed': list('abcdef')},
               'keyLevels': {'levels': {'r1': 1, 'pivot': 2, 's1': 3, 'r2': 4}}}
        out = MCP.compact_decision(ctx)
        self.assertEqual(out['allowed'], list('abcd'))
        self.assertEqual(out['levels'], {'r1': 1, 'pivot': 2, 's1': 3})


class StdioTests(unittest.TestCase):
    def test_legacy_negotiation_retains_single_text_payload(self):
        for version in ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'):
            lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': version}},
                     {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                     {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'st_signal_catalog'}}]
            output = io.StringIO()
            with mock.patch.object(MCP, 'http_json', return_value={'signals': [], 'engine': 'rules/2'}):
                MCP.serve(io.StringIO('\n'.join(map(json.dumps, lines))), output)
            replies = [json.loads(line)['result'] for line in output.getvalue().splitlines()]
            modern = version in ('2025-06-18', '2025-11-25')
            self.assertEqual('outputSchema' in replies[1]['tools'][0], modern)
            self.assertEqual('structuredContent' in replies[2], modern)
            self.assertEqual(len(replies[2]['content']), 2 if modern else 1)
            self.assertEqual(json.loads(replies[2]['content'][0]['text']), {'signals': [], 'engine': 'rules/2'})

    def test_stdio_framing(self):
        lines = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        ]
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'st_mcp_server.py')],
                              input='\n'.join(json.dumps(x) for x in lines) + '\nnot json\n',
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
        replies = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        self.assertEqual([r.get('id') for r in replies], [1, 2, None])
        self.assertEqual(replies[2]['error']['code'], -32700)
        self.assertEqual(proc.stderr, '')


def assert_schema(test, value, schema):
    """驗證這份輸出 schema 使用的 JSON Schema 關鍵字，維持執行期零套件。"""
    types = {'object': dict, 'array': list, 'string': str, 'null': type(None), 'boolean': bool}
    if 'type' in schema:
        kinds = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        test.assertIsInstance(value, tuple(types[k] for k in kinds))
    if 'const' in schema:
        test.assertEqual(value, schema['const'])
    if 'enum' in schema:
        test.assertIn(value, schema['enum'])
    if isinstance(value, dict):
        test.assertTrue(set(schema.get('required', [])) <= value.keys())
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            test.assertTrue(value.keys() <= props.keys())
        for key, val in value.items():
            if key in props:
                assert_schema(test, val, props[key])
    if isinstance(value, list) and 'items' in schema:
        for val in value:
            assert_schema(test, val, schema['items'])


class StructuredContractTests(unittest.TestCase):
    def call(self, name, backend, args=None):
        with mock.patch.object(MCP, 'http_json', return_value=backend):
            result = MCP.call_tool(name, args or {})
        structured = result['structuredContent']
        assert_schema(self, structured, MCP.OUTPUT_SCHEMA)
        self.assertEqual(json.loads(result['content'][1]['text']), structured)
        return result, structured

    def test_all_seven_tools_success_contract_and_legacy_data(self):
        fixtures = [
            ('st_stock_health', {'ok': True, 'health': {}}, {'symbol': '2330'}),
            ('st_stock_evidence', {'ok': True, 'evidence': {'zero': 0}}, {'symbol': 'AAPL'}),
            ('st_watchlist_health', {'items': []}, {'symbols': '2330,AAPL:US'}),
            ('st_signal_scoreboard', {'available': True, 'scoreboard': []}, {}),
            ('st_signal_catalog', {'signals': []}, {}),
            ('st_market_decision', {'ok': True, 'regime': {'id': 'RISK_ON'}}, {}),
            ('st_key_levels', {'asOf': '2026-09-25', 'source': 'local-daily-series'}, {}),
        ]
        for name, backend, args in fixtures:
            with self.subTest(name=name):
                result, structured = self.call(name, backend, args)
                self.assertFalse(result['isError'])
                self.assertEqual(structured['status'], 'ok')
                self.assertEqual(json.loads(result['content'][0]['text']), structured['data'])

    def test_metadata_preserves_null_zero_and_source_dates(self):
        _, result = self.call('st_stock_health', {
            'ok': True, 'health': {}, 'dataSource': 'local-db', 'asOf': '2026-09-25',
            'generatedAt': '2026-09-28T10:00:00+08:00', 'staleDays': 0,
            'engine': 'stock-signals/2', 'contractVersion': 2, 'session': {'provisional': False},
        }, {'symbol': '2330'})
        meta = result['metadata']
        self.assertEqual(meta['source'], 'local-db')
        self.assertEqual(meta['asOf'], '2026-09-25')
        self.assertEqual(meta['freshness']['staleDays'], 0)
        self.assertIs(meta['freshness']['provisional'], False)
        self.assertEqual(meta['calculationVersion'], 'stock-signals/2')
        _, unknown = self.call('st_signal_catalog', {'generatedAt': 'today'})
        self.assertIsNone(unknown['metadata']['asOf'])
        self.assertIsNone(unknown['metadata']['source'])
        self.assertIn('asOf', unknown['metadata']['missing'])
        self.assertIn('calculationVersion', unknown['metadata']['missing'])

    def test_cache_capability_and_http_query(self):
        listing = {t['name']: t for t in MCP.tools_list_payload()['tools']}
        for name in ('st_stock_health', 'st_stock_evidence', 'st_watchlist_health'):
            args = {'symbols': '2330,AAPL:US'} if name == 'st_watchlist_health' else {'symbol': '2330'}
            args['cacheOnly'] = True
            with mock.patch.object(MCP, 'http_json', return_value={'ok': True}) as request:
                out = MCP.call_tool(name, args)['structuredContent']
                self.assertIn('cacheOnly=1', request.call_args[0][0])
            self.assertEqual(out['metadata']['access']['mode'], 'cache-only')
            self.assertTrue(out['metadata']['access']['backendMayUpdateCache'])
            self.assertFalse(out['metadata']['access']['backendMayAccessNetwork'])
            self.assertTrue(listing[name]['annotations']['openWorldHint'])
        for name in ('st_signal_catalog', 'st_signal_scoreboard', 'st_market_decision', 'st_key_levels'):
            self.assertFalse(listing[name]['annotations']['openWorldHint'])

    def test_backend_unavailable_partial_and_transport_errors(self):
        result, structured = self.call('st_stock_health', {'ok': False, 'reason': 'INSUFFICIENT_BARS'}, {'symbol': '2330'})
        self.assertTrue(result['isError'])
        self.assertEqual(structured['status'], 'unavailable')
        self.assertEqual(structured['error']['code'], 'backend_unavailable')
        _, structured = self.call('st_watchlist_health', {'items': [{'ok': True}, {'ok': False}]}, {'symbols': '2330'})
        self.assertEqual(structured['status'], 'partial')
        _, structured = self.call('st_market_decision', {'regime': {'id': 'INSUFFICIENT_DATA'}})
        self.assertEqual(structured['status'], 'partial')
        for exc, code in [(urllib.error.HTTPError('local', 503, 'unavailable', {}, None), 'backend_http_error'),
                          (urllib.error.URLError('secret must not leak'), 'backend_unreachable'),
                          (TimeoutError(), 'backend_unreachable'),
                          (json.JSONDecodeError('bad json', '', 0), 'invalid_backend_result')]:
            with mock.patch.object(MCP, 'http_json', side_effect=exc):
                out = MCP.call_tool('st_signal_catalog', {})
            assert_schema(self, out['structuredContent'], MCP.OUTPUT_SCHEMA)
            self.assertEqual(out['structuredContent']['error']['code'], code)
            self.assertNotIn('secret must not leak', json.dumps(out))

    def test_invalid_inputs_never_call_backend(self):
        for args in ({'symbol': '2330', 'market': 'XX'}, {'symbol': 2330}, {'symbol': '2330', 'cacheOnly': 1},
                     {'symbol': '2330', 'unexpected': True}):
            with mock.patch.object(MCP, 'http_json') as request:
                self.assertTrue(MCP.call_tool('st_stock_health', args)['isError'])
                request.assert_not_called()
        for params in ([], False, 'bad'):
            self.assertEqual(rpc('tools/list', params)['error']['code'], -32602)
        for args in ([], False, '', None):
            self.assertEqual(rpc('tools/call', {'name': 'st_signal_catalog', 'arguments': args})['error']['code'], -32602)

    def test_malformed_backend_does_not_break_next_request(self):
        for backend in ({'items': 7}, {'signals': float('nan')}, ['not-an-object']):
            with mock.patch.object(MCP, 'http_json', return_value=backend):
                out = MCP.call_tool('st_signal_catalog', {})
            self.assertEqual(out['structuredContent']['error']['code'], 'invalid_backend_result')
            assert_schema(self, out['structuredContent'], MCP.OUTPUT_SCHEMA)
            self.assertEqual(rpc('ping')['result'], {})

    def test_loopback_only_no_proxy_no_redirect_no_post(self):
        # 執行時組出明確的合成測試向量；分享包不保留看似真實憑證／信箱的字面值。
        misleading_host = 'http://127.0.0.1' + chr(64) + 'example.invalid'
        fake_credentials = 'http://' + ':'.join(['fixture-user', 'fixture-password']) + chr(64) + 'localhost'
        for url in ('https://example.com', misleading_host, fake_credentials,
                    'http://localhost/path', 'http://localhost?token=secret'):
            with mock.patch.dict('os.environ', {'ST_MCP_BASE_URL': url}), self.assertRaises(ValueError):
                MCP.base_url()
        with mock.patch.dict('os.environ', {'ST_MCP_BASE_URL': 'http://127.0.0.1:18432'}):
            self.assertEqual(MCP.base_url(), 'http://127.0.0.1:18432')
        with self.assertRaises(ValueError):
            MCP.http_json('/test', {})
        with self.assertRaises(urllib.error.HTTPError) as redirect:
            MCP._NoRedirect().redirect_request(urllib.request.Request('http://localhost'), None, 302, '', {}, 'https://example.com')
        redirect.exception.close()


if __name__ == '__main__':
    unittest.main()

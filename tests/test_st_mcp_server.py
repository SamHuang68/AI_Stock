# -*- coding: utf-8 -*-
"""P3：本機 MCP 伺服器（stdio JSON-RPC、唯讀工具、錯誤處理）。"""
from __future__ import annotations

import importlib.util
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
        self.assertIn('not investment advice', r['instructions'])
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


if __name__ == '__main__':
    unittest.main()

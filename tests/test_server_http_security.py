#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))
SPEC = importlib.util.spec_from_file_location('st_server_http_security_test', SERVER_DIR / 'server.py')
if SPEC is None or SPEC.loader is None:
    raise RuntimeError('unable to load Stock Terminal server')
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)


class _SecurityHandler(ST.Handler):
    def _handle_sync(self):
        try:
            body = ST.read_json_body(self, max_bytes=64)
        except ST.BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        self._ok(json.dumps({'ok': True, 'body': body}).encode())

    def _wavedeck_origin_ok(self, origin):
        return self._bridge_cors_path(self.path.split('?')[0]) and origin == 'http://127.0.0.1:18433'


class ServerHttpSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), _SecurityHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_port
        cls.base = f'http://127.0.0.1:{cls.port}'
        cls.old_port = ST.PORT
        ST.PORT = cls.port

    @classmethod
    def tearDownClass(cls):
        ST.PORT = cls.old_port
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def test_get_mutation_is_method_not_allowed_and_has_trace(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + '/sync', timeout=3)
        self.assertEqual(caught.exception.code, 405)
        body = json.loads(caught.exception.read())
        self.assertEqual(caught.exception.headers['Allow'], 'POST')
        self.assertEqual(body['traceId'], caught.exception.headers['X-ST-Trace-ID'])
        caught.exception.close()

    def test_same_origin_post_succeeds_and_prefix_attack_is_rejected(self):
        good = urllib.request.Request(
            self.base + '/sync', data=b'{"days":1}', method='POST',
            headers={'Content-Type': 'application/json', 'Origin': self.base,
                     'X-ST-Trace-ID': 'security-test-1'})
        with urllib.request.urlopen(good, timeout=3) as response:
            self.assertEqual(json.load(response)['body']['days'], 1)
            self.assertEqual(response.headers['X-ST-Trace-ID'], 'security-test-1')
        bad = urllib.request.Request(
            # This assertion is only about strict Origin matching. An empty
            # body avoids leaving unread request bytes when the handler rejects
            # before parsing; Windows may otherwise reset the loopback socket
            # while urllib is reading the already-sent 403 response.
            self.base + '/sync', data=b'', method='POST',
            headers={'Content-Type': 'application/json', 'Origin': self.base + '.evil.invalid'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad, timeout=3)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_wrong_content_type_and_oversized_body_are_rejected(self):
        wrong = urllib.request.Request(
            self.base + '/sync', data=b'{}', method='POST',
            headers={'Content-Type': 'text/plain'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(wrong, timeout=3)
        self.assertEqual(caught.exception.code, 415)
        caught.exception.close()
        oversized = urllib.request.Request(
            self.base + '/sync', data=b'{}', method='POST',
            headers={'Content-Type': 'application/json', 'Content-Length': '999'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(oversized, timeout=3)
        self.assertEqual(caught.exception.code, 413)
        caught.exception.close()

    def test_cors_is_only_emitted_for_explicit_wavedeck_bridge(self):
        req = urllib.request.Request(
            self.base + '/bridge/wavedeck', method='OPTIONS',
            headers={'Origin': 'http://127.0.0.1:18433'})
        with urllib.request.urlopen(req, timeout=3) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'http://127.0.0.1:18433')
        forbidden = urllib.request.Request(
            self.base + '/sync', method='OPTIONS', headers={'Origin': 'http://127.0.0.1:18433'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(forbidden, timeout=3)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_kline_events_route_validates_input_and_serializes_report(self):
        import K線事件
        payload = {'sym': '2330', 'events': [], 'freshness': {'fresh': False}}
        with patch.object(K線事件, 'report', return_value=payload) as calculate:
            with urllib.request.urlopen(self.base + '/kline-events?sym=2330&asOf=2026-09-01', timeout=5) as response:
                self.assertEqual(json.load(response), payload)
            self.assertEqual(calculate.call_args.args[1:], ('2330', '2026-09-01'))
            calculate.side_effect = ValueError('截至日期無效')
            for query in ('sym=bad!', 'sym=2330&asOf=invalid'):
                with self.subTest(query=query), self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(self.base + '/kline-events?' + query, timeout=5)
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()

    def test_archify_html_has_static_document_security_boundary(self):
        path = '/assets/docs/archify/st-decision-evidence-lineage.html'
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('text/html', response.headers['Content-Type'])
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
            self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertEqual(
                response.headers['Content-Security-Policy'],
                ST.ARCHIFY_DOCUMENT_CSP,
            )
        for directive in (
            "default-src 'none'",
            "connect-src 'none'",
            "worker-src 'none'",
            "frame-src 'none'",
            "object-src 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ):
            self.assertIn(directive, ST.ARCHIFY_DOCUMENT_CSP)

    def test_static_allowlist_rejects_runtime_and_encoded_traversal_paths(self):
        for path in (
            '/data/private_web.json',
            '/assets/docs/archify/%2e%2e/%2e%2e/data/private_web.json',
        ):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(self.base + path, timeout=3)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()

    def test_missing_closes_do_not_abort_screener_or_chain_momentum(self):
        import datastore
        rows = [(i, 100, 101, 99, 100, 1000) for i in range(80)]
        rows[-1] = (79, None, None, None, None, 0)
        with patch.object(datastore, 'get_bars_bulk', return_value={'1472': rows}), patch.object(ST, '_get_tw_universe', return_value=['1472']), patch.object(ST, '_get_tw_names', return_value={}):
            for path, payload in (('/screener', {'symbols': ['1472'], 'preset': 'volume'}), ('/chain-momentum', {'stages': [{'stage': '測試', 'codes': ['1472']}]})):
                with self.subTest(path=path):
                    req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
                    with urllib.request.urlopen(req, timeout=5) as response:
                        result = json.load(response)
                    if path == '/chain-momentum':
                        self.assertEqual(result['stages'][0]['n'], 0)


if __name__ == '__main__':
    unittest.main()

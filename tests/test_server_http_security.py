#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import unittest
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

    # 隔離市場抓取；HTTP 路由、來源判斷與 CORS 標頭使用正式實作。
    def _handle_twindex(self):
        self._ok(json.dumps({'indices': {'t00': {'price': 22000}}}).encode())

    def _handle_breadth(self):
        self._ok(json.dumps({'stocks': {'advRatio': 0.6}}).encode())

    def _handle_fundamental(self, sym):
        self._ok(json.dumps({'symbol': sym, 'score': 60}).encode())


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
        # 此處驗證標頭拒絕；不留未讀本文，避免 Windows 在回應讀取前重設連線。
        wrong = urllib.request.Request(
            self.base + '/sync', data=b'', method='POST',
            headers={'Content-Type': 'text/plain'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(wrong, timeout=3)
        self.assertEqual(caught.exception.code, 415)
        caught.exception.close()
        oversized = urllib.request.Request(
            self.base + '/sync', data=b'', method='POST',
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

    def test_wavedeck_market_reads_preserve_payload_and_allowlisted_origins(self):
        cases = (
            ('/twindex', 'indices'), ('/breadth?view=wd', 'stocks'),
            ('/fundamental/^TWII', 'score'), ('/fundamental/%5ETWII', 'score'),
        )
        for host in ('127.0.0.1', 'localhost'):
            for port in (18433, 18765, 28765, 38433, 8765):
                origin = f'http://{host}:{port}'
                for path, key in cases:
                    with self.subTest(origin=origin, path=path):
                        req = urllib.request.Request(self.base + path, headers={'Origin': origin})
                        with urllib.request.urlopen(req, timeout=3) as response:
                            self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
                            self.assertEqual(response.headers['Vary'], 'Origin')
                            self.assertIsNone(response.headers['Access-Control-Allow-Credentials'])
                            self.assertIn(key, json.load(response))

    def test_wavedeck_market_preflight_and_post_keep_read_only_boundary(self):
        origin = 'http://127.0.0.1:18433'
        for path in ('/twindex', '/breadth', '/fundamental/%5ETWII'):
            req = urllib.request.Request(self.base + path, method='OPTIONS', headers={
                'Origin': origin, 'Access-Control-Request-Method': 'GET'})
            with urllib.request.urlopen(req, timeout=3) as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(response.headers['Access-Control-Allow-Methods'], 'GET, OPTIONS')
            for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'):
                req = urllib.request.Request(self.base + path, method='OPTIONS', headers={
                    'Origin': origin, 'Access-Control-Request-Method': method})
                with self.subTest(path=path, preflight=method):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(req, timeout=3)
                    self.assertEqual(caught.exception.code, 403)
                    self.assertIsNone(caught.exception.headers['Access-Control-Allow-Origin'])
                    caught.exception.close()
            req = urllib.request.Request(self.base + path, data=b'', method='POST',
                                         headers={'Origin': origin})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req, timeout=3)
            self.assertEqual(caught.exception.code, 403)
            self.assertIsNone(caught.exception.headers['Access-Control-Allow-Origin'])
            caught.exception.close()

    def test_market_cors_rejects_other_origins_and_other_symbols(self):
        for origin in (
            'http://127.0.0.1:18432', 'http://127.0.0.1:18434',
            'http://127.0.0.1:18435', 'http://127.0.0.1:9999',
            'https://evil.example', 'http://127.0.0.1.evil.example:18433',
            'null', 'https://127.0.0.1:18433',
        ):
            for path in ('/twindex', '/breadth', '/fundamental/%5ETWII'):
                with self.subTest(origin=origin, path=path):
                    req = urllib.request.Request(self.base + path, headers={'Origin': origin})
                    with urllib.request.urlopen(req, timeout=3) as response:
                        self.assertIsNone(response.headers['Access-Control-Allow-Origin'])
        for path in ('/fundamental/2330', '/fundamental/^TWOII',
                     '/fundamental/%255ETWII', '/twindex/extra', '/health', '/sync'):
            with self.subTest(path=path):
                req = urllib.request.Request(self.base + path, method='OPTIONS', headers={
                    'Origin': 'http://127.0.0.1:18433', 'Access-Control-Request-Method': 'GET'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(req, timeout=3)
                self.assertEqual(caught.exception.code, 403)
                self.assertIsNone(caught.exception.headers['Access-Control-Allow-Origin'])
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


if __name__ == '__main__':
    unittest.main()

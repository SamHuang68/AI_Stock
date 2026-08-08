# -*- coding: utf-8 -*-
"""http_client：連線池複用、暫態重試、JSON 解析。"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import http_client as hc  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    hits = 0
    fail_first = 0
    lock = threading.Lock()

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        with _Handler.lock:
            _Handler.hits += 1
            n = _Handler.hits
            fail_n = _Handler.fail_first
        if self.path.startswith('/json'):
            if n <= fail_n:
                body = b'busy'
                self.send_response(503)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({'ok': True, 'n': n}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith('/text'):
            body = b'hello-pool'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            self.wfile.write(body)
            return
        body = b'missing'
        self.send_response(404)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)


class TestHttpClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Handler.hits = 0
        _Handler.fail_first = 0
        cls.httpd = HTTPServer(('127.0.0.1', 0), _Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls):
        try:
            hc.get_default_client().clear_pools()
        except Exception:
            pass
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        with _Handler.lock:
            _Handler.hits = 0
            _Handler.fail_first = 0
        self.client = hc.HttpClient(max_per_host=4)
        self.addCleanup(self.client.clear_pools)

    def test_fetch_json(self):
        d = self.client.get_json(self.base + '/json', timeout=3, retries=0)
        self.assertTrue(d['ok'])
        self.assertEqual(d['n'], 1)

    def test_fetch_text(self):
        t = self.client.get_text(self.base + '/text', timeout=3, retries=0)
        self.assertEqual(t, 'hello-pool')

    def test_retry_on_503(self):
        with _Handler.lock:
            _Handler.fail_first = 1
        d = self.client.get_json(self.base + '/json', timeout=3, retries=2)
        self.assertTrue(d['ok'])
        st = self.client.stats()
        self.assertGreaterEqual(st['retries'], 1)

    def test_connection_reuse(self):
        self.client.get_text(self.base + '/text', timeout=3, retries=0)
        self.client.get_text(self.base + '/text', timeout=3, retries=0)
        self.client.get_text(self.base + '/text', timeout=3, retries=0)
        st = self.client.stats()
        self.assertEqual(st['requests'], 3)
        # 至少應複用 1 次（同 host keep-alive）
        self.assertGreaterEqual(st['reused'], 1)
        self.assertLessEqual(st['opened'], 2)

    def test_module_shortcuts(self):
        client = hc.get_default_client()
        client.clear_pools()
        try:
            d = hc.fetch_json(self.base + '/json', timeout=3, retries=0)
            self.assertTrue(d.get('ok'))
        finally:
            client.clear_pools()

    def test_bad_scheme(self):
        with self.assertRaises(hc.HttpError):
            self.client.get_bytes('ftp://example.com/x', timeout=1, retries=0)

    def test_http_404_raises(self):
        with self.assertRaises(hc.HttpError) as ctx:
            self.client.get_bytes(self.base + '/missing', timeout=3, retries=0)
        self.assertEqual(ctx.exception.status, 404)

    def test_is_transient_winerror(self):
        err = OSError('conn aborted')
        err.winerror = 10053
        self.assertTrue(hc._is_transient(err))


if __name__ == '__main__':
    unittest.main()

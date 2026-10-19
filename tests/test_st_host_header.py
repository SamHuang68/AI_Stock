# -*- coding: utf-8 -*-
"""本機 ST 後端拒絕非 loopback 的 Host 標頭（防 DNS rebinding 讀取 GET 回應）。"""
import http.client
import importlib.util
import os
import sys
import threading
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'server'))
from http_boundary import is_local_host_header  # noqa: E402


class HostHeaderRuleTests(unittest.TestCase):
    def test_loopback_hosts_with_the_bound_port_are_allowed(self):
        for host in ('127.0.0.1:18432', 'localhost:18432', '[::1]:18432', 'LOCALHOST:18432', '127.0.0.1', None, ''):
            with self.subTest(host=host):
                self.assertTrue(is_local_host_header(host, 18432))

    def test_rebinding_and_other_ports_are_rejected(self):
        for host in ('evil.example:18432', 'evil.example', '127.0.0.1.evil.example:18432',
                     '127.0.0.1:18433', 'localhost:80', '0.0.0.0:18432', '192.168.1.5:18432'):
            with self.subTest(host=host):
                self.assertFalse(is_local_host_header(host, 18432))


class HandlerHostHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('st_server_host_header_test', os.path.join(ROOT, 'server', 'server.py'))
        cls.st = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.st)
        cls.httpd = cls.st.ThreadingHTTPServer(('127.0.0.1', 0), cls.st.Handler)
        cls.port = cls.httpd.server_port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def status(self, host, method='GET', path='/health/live'):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.putrequest(method, path, skip_host=True)
            conn.putheader('Host', host)
            conn.putheader('Connection', 'close')
            if method == 'POST':
                conn.putheader('Content-Type', 'application/json')
                conn.putheader('Content-Length', '2')
                conn.endheaders(b'{}')
            else:
                conn.endheaders()
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def test_loopback_host_is_served(self):
        self.assertEqual(self.status(f'127.0.0.1:{self.port}'), 200)
        self.assertEqual(self.status(f'localhost:{self.port}'), 200)

    def test_rebound_external_host_is_rejected_for_reads_and_writes(self):
        self.assertEqual(self.status(f'evil.example:{self.port}'), 403)
        self.assertEqual(self.status(f'evil.example:{self.port}', method='POST', path='/diagnostics/ui-route'), 403)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))
SPEC = importlib.util.spec_from_file_location('st_features_http_test', SERVER_DIR / 'server.py')
if SPEC is None or SPEC.loader is None:
    raise RuntimeError('unable to load Stock Terminal server')
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)


class FeaturesHttpTests(unittest.TestCase):
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

    def test_features_endpoint_lists_defaults_off(self):
        with urllib.request.urlopen(self.base + '/features', timeout=3) as response:
            payload = json.load(response)
        self.assertTrue(payload['ok'])
        self.assertFalse(payload['flags']['shadowOvernightIntraday'])
        self.assertFalse(payload['flags']['shadowEarlyWarning'])
        self.assertFalse(payload['flags']['shadowConsensusAttention'])
        self.assertFalse(payload['flags']['shadowConditionalExpectation'])
        self.assertFalse(payload['flags']['shadowMultifactor'])
        self.assertIn('ST_ENABLE_SHADOW_RESEARCH', payload['enable']['masterEnv'])


if __name__ == '__main__':
    unittest.main()

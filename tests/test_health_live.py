#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"


def _load_server_module():
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location(
        "st_server_health_live_test", SERVER_DIR / "server.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HealthLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_server_module()
        cls.server = cls.module.ThreadingHTTPServer(
            ("127.0.0.1", 0), cls.module.Handler
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/health/live"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_liveness_is_small_and_does_not_run_full_health_collectors(self):
        original = self.module.find_etf_dir
        self.module.find_etf_dir = lambda: (_ for _ in ()).throw(
            AssertionError("full health collector must not run")
        )
        try:
            started = time.monotonic()
            with urllib.request.urlopen(self.url, timeout=2) as response:
                payload = json.load(response)
            elapsed = time.monotonic() - started
        finally:
            self.module.find_etf_dir = original
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["liveness"])
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()

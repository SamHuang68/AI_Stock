#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

from lru_cache import LRUCache


class LRUCacheTests(unittest.TestCase):
    def test_set_get_and_eviction(self):
        cache = LRUCache(2, ttl_seconds=60)
        cache.set('a', 1)
        cache.set('b', 2)
        self.assertEqual(cache.get('a'), 1)
        cache.set('c', 3)
        self.assertIsNone(cache.get('b'))
        self.assertEqual(cache.get('c'), 3)

    def test_ttl_expiry(self):
        cache = LRUCache(4, ttl_seconds=0.05)
        cache.set('x', 'value')
        self.assertEqual(cache.get('x'), 'value')
        time.sleep(0.06)
        self.assertIsNone(cache.get('x'))

    def test_status_reports_bounds(self):
        cache = LRUCache(10, ttl_seconds=30)
        cache.set('k', 'v')
        status = cache.status()
        self.assertEqual(status['used'], 1)
        self.assertEqual(status['max'], 10)
        self.assertEqual(status['ttlSeconds'], 30.0)


if __name__ == '__main__':
    unittest.main()

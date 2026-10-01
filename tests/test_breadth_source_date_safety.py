"""Behavioral coverage for versioned breadth/marketflow cache consumption."""
import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'server'))
import breadth_build as bb
from exchange_source_dates import marketflow_cache_key

class RecordingCache:
    def __init__(self, entries):
        self.entries = entries
        self.reads = []
    def get(self, key):
        self.reads.append(key)
        return self.entries.get(key)
    def set(self, key, value, ttl):
        self.entries[key] = value

class BreadthSourceDateCacheTests(unittest.TestCase):
    def build(self, cache):
        with patch.object(bb, 'taipei_today', return_value=date(2026, 10, 1)), patch.object(bb, 'breadth_trace'), patch.object(bb.urllib.request, 'urlopen', side_effect=OSError('offline fixture')):
            return bb.build_breadth_payload(cache, base_dir='unused', yf_headers={},
                twse_mis_index=lambda *args: {}, build_tw_market_fundamental=lambda *args: {})

    def test_reads_canonical_marketflow_and_ignores_legacy_cache(self):
        official = {'foreign': 10, 'date': '20260930', 'sourceDate': '2026-09-30', 'source': 'TWSE BFI82U'}
        cache = RecordingCache({
            'breadth:v1:20261001': json.dumps({'inst': {'foreign': 999}}).encode(),
            'marketflow:20261001': json.dumps({'inst': {'foreign': 888}}).encode(),
            'marketflow:2026-10-01': json.dumps({'inst': {'foreign': 777}}).encode(),
            marketflow_cache_key(date(2026, 10, 1)): json.dumps({'inst': official}).encode(),
        })
        result = self.build(cache)
        self.assertEqual(result['inst'], official)
        self.assertEqual(cache.reads, ['breadth:source-date-v1:20261001', 'marketflow:source-date-v1:20261001'])
        self.assertIn('breadth:source-date-v1:20261001', cache.entries)

    def test_legacy_marketflow_alone_does_not_supply_institutional_data(self):
        cache = RecordingCache({'marketflow:20261001': json.dumps({'inst': {'foreign': 888}}).encode(),
                                'marketflow:2026-10-01': json.dumps({'inst': {'foreign': 777}}).encode()})
        result = self.build(cache)
        self.assertIsNone(result.get('inst'))
        self.assertEqual(cache.reads, ['breadth:source-date-v1:20261001', 'marketflow:source-date-v1:20261001'])

    def test_current_version_breadth_cache_is_reused(self):
        cached = {'ok': True, 'date': '2026-09-30', 'inst': {'foreign': 10, 'source': 'TWSE BFI82U'}}
        cache = RecordingCache({'breadth:source-date-v1:20261001': json.dumps(cached).encode()})
        self.assertEqual(self.build(cache), cached)
        self.assertEqual(cache.reads, ['breadth:source-date-v1:20261001'])

if __name__ == '__main__': unittest.main()

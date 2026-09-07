#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

from ohlc_ledger import (
    OhlcBar,
    append_bars,
    availability_predicate,
    bars_from_yahoo_chart,
    filter_bars_pit,
    ingest_yahoo_chart_payload,
    new_generation_id,
    query_bars,
    query_bars_pit,
)
from feature_settings import is_enabled


FIXTURE_PATH = ROOT / 'tests' / 'fixtures' / 'ohlc_ledger' / 'sample_bars.json'


class OhlcLedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name
        self._saved_env = os.environ.get('ST_OHLC_LEDGER')
        os.environ.pop('ST_OHLC_LEDGER', None)

    def tearDown(self):
        self._tmp.cleanup()
        if self._saved_env is None:
            os.environ.pop('ST_OHLC_LEDGER', None)
        else:
            os.environ['ST_OHLC_LEDGER'] = self._saved_env

    def _fixture_bars(self):
        return json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))

    def test_append_and_query_roundtrip(self):
        result = append_bars(self._fixture_bars(), base_dir=self.base_dir)
        self.assertEqual(result['inserted'], 3)
        self.assertEqual(result['ignored'], 0)
        rows = query_bars('2330', base_dir=self.base_dir)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].session_date, '2026-01-02')

    def test_append_idempotency_same_generation(self):
        bars = self._fixture_bars()[:1]
        first = append_bars(bars, base_dir=self.base_dir)
        second = append_bars(bars, base_dir=self.base_dir)
        self.assertEqual(first['inserted'], 1)
        self.assertEqual(second['inserted'], 0)
        self.assertEqual(second['ignored'], 1)
        self.assertEqual(len(query_bars('2330', base_dir=self.base_dir)), 1)

    def test_generation_isolation_keeps_old_rows(self):
        base = dict(self._fixture_bars()[0])
        base.pop('generation_id', None)
        append_bars([base], generation_id='gen-old', base_dir=self.base_dir)
        rewritten = dict(base)
        rewritten['open'] = 118.0
        rewritten['close'] = 120.0
        rewritten['high'] = 125.0
        rewritten['low'] = 115.0
        rewritten['ingested_at'] = '2026-01-05T13:30:00+08:00'
        append_bars([rewritten], generation_id='gen-new', base_dir=self.base_dir)

        old_rows = query_bars('2330', generation_id='gen-old', base_dir=self.base_dir)
        new_rows = query_bars('2330', generation_id='gen-new', base_dir=self.base_dir)
        self.assertEqual(old_rows[0].close, 104.0)
        self.assertEqual(new_rows[0].close, 120.0)

        pit_latest = query_bars_pit(
            '2330',
            as_of='2026-01-10',
            knowledge_cutoff='2026-01-05T14:00:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(len(pit_latest), 1)
        self.assertEqual(pit_latest[0].generation_id, 'gen-new')
        self.assertEqual(pit_latest[0].close, 120.0)

    def test_pit_filter_excludes_future_ingestion(self):
        append_bars(self._fixture_bars(), base_dir=self.base_dir)
        visible = query_bars_pit(
            '2330',
            as_of='2026-01-10',
            knowledge_cutoff='2026-01-03T23:59:59+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual([row.session_date for row in visible], ['2026-01-02', '2026-01-03'])
        hidden = query_bars_pit(
            '2330',
            as_of='2026-01-10',
            knowledge_cutoff='2026-01-02T23:59:59+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual([row.session_date for row in hidden], ['2026-01-02'])

    def test_pure_filter_bars_pit_matches_query(self):
        bars = [OhlcBar(**{
            'symbol': '2330',
            'session_date': '2026-01-02',
            'price_basis': 'unadj_close',
            'open': 1.0,
            'high': 2.0,
            'low': 1.0,
            'close': 2.0,
            'source': 'x',
            'ingested_at': '2026-01-02T13:30:00+08:00',
            'generation_id': 'g1',
        })]
        self.assertTrue(availability_predicate(
            bars[0], as_of='2026-01-02', knowledge_cutoff='2026-01-02T20:00:00+08:00'))
        self.assertFalse(availability_predicate(
            bars[0], as_of='2026-01-01', knowledge_cutoff='2026-01-02T20:00:00+08:00'))
        filtered = filter_bars_pit(
            bars, as_of='2026-01-02', knowledge_cutoff='2026-01-02T20:00:00+08:00')
        self.assertEqual(len(filtered), 1)

    def test_yahoo_chart_adapter_unadj(self):
        payload = {
            'chart': {
                'result': [{
                    'timestamp': [1704067200],
                    'meta': {'exchangeTimezoneName': 'UTC'},
                    'indicators': {
                        'quote': [{
                            'open': [100.0],
                            'high': [110.0],
                            'low': [95.0],
                            'close': [105.0],
                        }],
                        'adjclose': [{'adjclose': [105.0]}],
                    },
                }],
            },
        }
        bars = bars_from_yahoo_chart(payload, '2330', price_basis='unadj_close')
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]['close'], 105.0)
        self.assertEqual(bars[0]['open'], 100.0)

    def test_ingest_respects_feature_flag(self):
        os.environ['ST_OHLC_LEDGER'] = '0'
        payload = {
            'chart': {
                'result': [{
                    'timestamp': [1704067200],
                    'meta': {'exchangeTimezoneName': 'UTC'},
                    'indicators': {
                        'quote': [{
                            'open': [100.0],
                            'high': [110.0],
                            'low': [95.0],
                            'close': [105.0],
                        }],
                        'adjclose': [{'adjclose': [105.0]}],
                    },
                }],
            },
        }
        self.assertFalse(is_enabled('ohlcLedger', self.base_dir))
        result = ingest_yahoo_chart_payload(payload, '2330', base_dir=self.base_dir)
        self.assertFalse(result['enabled'])
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(len(query_bars('2330', base_dir=self.base_dir)), 0)

    def test_new_generation_id_is_unique(self):
        self.assertNotEqual(new_generation_id(), new_generation_id())


if __name__ == '__main__':
    unittest.main()

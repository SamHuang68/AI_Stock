#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for st-peak-v0.1 observation-only peak distance (CONDITIONAL)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

import peak_observation as po  # noqa: E402
from ohlc_ledger import append_bars, query_bars_pit  # noqa: E402

FIXTURE_PATH = ROOT / 'tests' / 'fixtures' / 'ohlc_ledger' / 'sample_bars.json'


class PeakObservationComputeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name
        append_bars(json.loads(FIXTURE_PATH.read_text(encoding='utf-8')), base_dir=self.base_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_peak_kind_a_on_fixture_bars(self):
        obs = po.build_observation(
            '2330',
            as_of='2026-01-03',
            knowledge_cutoff='2026-01-10T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['contractId'], po.CONTRACT_ID)
        self.assertEqual(obs['peakKind'], 'A')
        self.assertEqual(obs['label'], 'CONDITIONAL')
        self.assertIsNone(obs['hostApprovalHash'])
        self.assertEqual(obs['disclaimerKey'], po.DISCLAIMER_KEY)
        self.assertEqual(obs['peakClose'], 107.0)
        self.assertEqual(obs['peakDate'], '2026-01-03')
        self.assertEqual(obs['lastClose'], 107.0)
        self.assertEqual(obs['pctBelowPeak'], 0.0)
        self.assertEqual(obs['source'], po.DEFAULT_SOURCE_LEDGER)
        self.assertTrue(obs['evidenceHash'])

    def test_pit_excludes_post_cutoff_ingestion(self):
        obs = po.build_observation(
            '2330',
            as_of='2026-01-04',
            knowledge_cutoff='2026-01-05T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['lastClose'], 107.0)
        self.assertEqual(obs['peakClose'], 107.0)
        self.assertEqual(obs['pctBelowPeak'], 0.0)
        pit_rows = query_bars_pit(
            '2330',
            as_of='2026-01-04',
            knowledge_cutoff='2026-01-05T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(len(pit_rows), 2)

    def test_pct_below_peak_negative_when_below_peak(self):
        bars = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
        extra = {
            'symbol': '2330',
            'session_date': '2026-01-05',
            'price_basis': 'unadj_close',
            'open': 105.0,
            'high': 106.0,
            'low': 100.0,
            'close': 101.0,
            'source': 'fixture/test',
            'ingested_at': '2026-01-05T13:30:00+08:00',
            'generation_id': 'gen-fixture-a',
        }
        append_bars([*bars, extra], base_dir=self.base_dir)
        obs = po.build_observation(
            '2330',
            as_of='2026-01-05',
            knowledge_cutoff='2026-01-15T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['peakClose'], 109.0)
        self.assertEqual(obs['lastClose'], 101.0)
        self.assertAlmostEqual(obs['pctBelowPeak'], 101.0 / 109.0 - 1.0, places=6)
        self.assertGreaterEqual(obs['pctBelowPeak'], -1.0)
        self.assertLessEqual(obs['pctBelowPeak'], 0.0)

    def test_adj_close_missing_metadata_returns_null(self):
        obs = po.build_observation(
            '2330',
            as_of='2026-01-03',
            knowledge_cutoff='2026-01-10T13:30:00+08:00',
            price_basis='adj_close',
            base_dir=self.base_dir,
        )
        self.assertIsNone(obs['pctBelowPeak'])
        self.assertIn('basisAsOf', obs['nullReason'])
        self.assertEqual(obs['label'], 'CONDITIONAL')

    def test_rejects_non_a_peak_kind(self):
        obs = po.build_observation(
            '2330',
            as_of='2026-01-03',
            knowledge_cutoff='2026-01-10T13:30:00+08:00',
            peak_kind='B',
            base_dir=self.base_dir,
        )
        self.assertIsNone(obs['pctBelowPeak'])
        self.assertIn('only A supported', obs['nullReason'])

    def test_label_always_conditional(self):
        obs = po.build_observation(
            '2330',
            as_of='2026-01-03',
            knowledge_cutoff='2026-01-10T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['label'], 'CONDITIONAL')
        self.assertEqual(obs['epistemic'] if 'epistemic' in obs else po.LABEL, 'CONDITIONAL')

    def test_no_decision_context_writes(self):
        source = Path(SERVER_DIR / 'peak_observation.py').read_text(encoding='utf-8')
        self.assertNotIn('import decision_context', source)
        self.assertNotIn('publish_context(', source)
        self.assertNotIn('actionEnvelope', source.replace('actionEnvelope, or FACT labels', ''))


class PeakObservationEvidencePackTests(unittest.TestCase):
    def setUp(self):
        import postmarket_report as pr

        self._pr = pr
        end = datetime.now(pr.TZ_TPE)
        rows = []
        for i in range(30):
            d = end - timedelta(days=29 - i)
            close = 100.0 + i
            rows.append((d.timestamp(), close - 1, close + 1, close - 2, close, 1000))
        self._rows = rows
        pr.configure(bars_fn=lambda _code: self._rows)

    def tearDown(self):
        self._pr.configure(bars_fn=None)

    def test_evidence_pack_attaches_peak_when_flag_on(self):
        pack = self._pr.build_evidence_pack(
            '2330',
            include={'quotes': True},
            now=datetime.now(self._pr.TZ_TPE).replace(hour=15, minute=5, second=0, microsecond=0),
        )
        self.assertIn('peakObservation', pack)
        peak = pack['peakObservation']
        self.assertEqual(peak['label'], 'CONDITIONAL')
        self.assertEqual(peak['contractId'], po.CONTRACT_ID)
        self.assertEqual(peak['disclaimerKey'], po.DISCLAIMER_KEY)
        self.assertIsNotNone(peak.get('pctBelowPeak'))


class PeakObservationRouteTests(unittest.TestCase):
    def test_disabled_payload_is_conditional(self):
        payload = po.disabled_payload()
        self.assertEqual(payload['label'], 'CONDITIONAL')
        self.assertEqual(payload['disclaimerKey'], po.DISCLAIMER_KEY)
        self.assertIsNone(payload['hostApprovalHash'])


if __name__ == '__main__':
    unittest.main()

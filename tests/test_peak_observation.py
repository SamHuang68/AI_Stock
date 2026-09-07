#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for st-peak-v0.1 observation-only peak distance (CONDITIONAL / FACT binding)."""
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

import peak_approvals as pa  # noqa: E402
import peak_observation as po  # noqa: E402
from ohlc_ledger import append_bars, query_bars_pit  # noqa: E402

try:
    import postmarket_report as _postmarket_report  # noqa: E402
except ImportError:
    _postmarket_report = None

FIXTURE_PATH = ROOT / 'tests' / 'fixtures' / 'ohlc_ledger' / 'sample_bars.json'


def _build_fixture_obs(**kwargs):
    defaults = {
        'as_of': '2026-01-03',
        'knowledge_cutoff': '2026-01-10T13:30:00+08:00',
    }
    defaults.update(kwargs)
    return po.build_observation('2330', **defaults)


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

    def test_label_conditional_without_approval(self):
        obs = _build_fixture_obs(base_dir=self.base_dir)
        self.assertEqual(obs['label'], po.LABEL_CONDITIONAL)
        self.assertIsNone(obs['hostApprovalHash'])

    def test_fact_binding_requires_host_approval(self):
        obs = _build_fixture_obs(base_dir=self.base_dir)
        self.assertEqual(obs['label'], po.LABEL_CONDITIONAL)
        pa.bind_fixture_approval(
            obs['evidenceHash'],
            approved_by='test-host',
            symbol='2330',
            as_of=obs['asOf'],
            base_dir=self.base_dir,
        )
        promoted = _build_fixture_obs(base_dir=self.base_dir)
        self.assertEqual(promoted['label'], po.LABEL_FACT)
        self.assertIsNotNone(promoted['hostApprovalHash'])
        self.assertEqual(promoted['evidenceHash'], obs['evidenceHash'])

    def test_implicit_knowledge_cutoff_cannot_fact_even_with_approval(self):
        obs = _build_fixture_obs(base_dir=self.base_dir)
        pa.bind_fixture_approval(obs['evidenceHash'], base_dir=self.base_dir)
        implicit = po.build_observation(
            '2330',
            as_of='2026-01-03',
            base_dir=self.base_dir,
            now=datetime.fromisoformat('2026-01-10T15:00:00+08:00'),
        )
        self.assertEqual(implicit['label'], po.LABEL_CONDITIONAL)

    def test_pit_limitation_cannot_fact_even_with_approval(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            live_bars = [
                (datetime(2026, 1, 2, 13, 30).timestamp(), 100.0, 105.0, 99.0, 104.0, 1000),
                (datetime(2026, 1, 3, 13, 30).timestamp(), 104.0, 108.0, 103.0, 107.0, 1000),
            ]
            fallback = po.build_observation(
                '2330',
                as_of='2026-01-03',
                knowledge_cutoff='2026-01-10T13:30:00+08:00',
                bars=live_bars,
                base_dir=empty_dir,
            )
            pa.bind_fixture_approval(fallback['evidenceHash'], base_dir=empty_dir)
            rebound = po.build_observation(
                '2330',
                as_of='2026-01-03',
                knowledge_cutoff='2026-01-10T13:30:00+08:00',
                bars=live_bars,
                base_dir=empty_dir,
            )
            self.assertIn('pitLimitation', rebound)
            self.assertEqual(rebound['label'], po.LABEL_CONDITIONAL)

    def test_fixed_snapshot_replay_is_bit_identical(self):
        kwargs = {
            'as_of': '2026-01-03',
            'knowledge_cutoff': '2026-01-10T13:30:00+08:00',
            'price_basis': 'unadj_close',
            'generation_id': None,
            'base_dir': self.base_dir,
        }
        first = po.build_observation('2330', **kwargs)
        second = po.build_observation('2330', **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first['evidenceHash'], second['evidenceHash'])

    def test_revision_isolation_old_generation_replayable(self):
        base = dict(json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))[0])
        base.pop('generation_id', None)
        append_bars([base], generation_id='gen-old', base_dir=self.base_dir)
        rewritten = dict(base)
        rewritten['close'] = 120.0
        rewritten['high'] = 125.0
        rewritten['open'] = 118.0
        rewritten['low'] = 115.0
        rewritten['ingested_at'] = '2026-01-05T13:30:00+08:00'
        append_bars([rewritten], generation_id='gen-new', base_dir=self.base_dir)

        old_snapshot = po.build_observation(
            '2330',
            as_of='2026-01-02',
            knowledge_cutoff='2026-01-04T13:30:00+08:00',
            generation_id='gen-old',
            base_dir=self.base_dir,
        )
        replay_old = po.build_observation(
            '2330',
            as_of='2026-01-02',
            knowledge_cutoff='2026-01-04T13:30:00+08:00',
            generation_id='gen-old',
            base_dir=self.base_dir,
        )
        self.assertEqual(old_snapshot, replay_old)
        self.assertEqual(old_snapshot['peakClose'], 104.0)

        new_latest = po.build_observation(
            '2330',
            as_of='2026-01-02',
            knowledge_cutoff='2026-01-10T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(new_latest['peakClose'], 120.0)
        self.assertNotEqual(new_latest['evidenceHash'], old_snapshot['evidenceHash'])

    def test_evidence_hash_includes_outputs(self):
        obs = _build_fixture_obs(base_dir=self.base_dir)
        pit_rows = query_bars_pit(
            '2330',
            as_of=obs['asOf'],
            knowledge_cutoff=obs['knowledgeCutoff'],
            base_dir=self.base_dir,
        )
        bar_dicts = [row.as_dict() for row in pit_rows]
        inputs = po._evidence_hash_inputs(
            symbol='2330',
            as_of=obs['asOf'],
            history_start=obs['historyStart'],
            price_basis=obs['priceBasis'],
            knowledge_cutoff=obs['knowledgeCutoff'],
            peak_kind='A',
            bars=bar_dicts,
            basis_as_of=None,
            generation_id=None,
            generation_content_hash=None,
            source=obs['source'],
            peak_close=obs['peakClose'],
            peak_date=obs['peakDate'],
            last_close=obs['lastClose'],
            pct_below_peak=obs['pctBelowPeak'],
        )
        self.assertEqual(po.compute_evidence_hash(inputs), obs['evidenceHash'])

    def test_no_decision_context_writes(self):
        source = Path(SERVER_DIR / 'peak_observation.py').read_text(encoding='utf-8')
        self.assertNotIn('import decision_context', source)
        self.assertNotIn('publish_context(', source)
        self.assertNotIn('actionEnvelope', source.replace('actionEnvelope.', ''))


@unittest.skipUnless(_postmarket_report, 'postmarket_report 不在 tip UX，EvidencePack 掛接僅 main 線')
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

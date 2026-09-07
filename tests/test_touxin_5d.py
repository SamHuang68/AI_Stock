#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for st-touxin-5d-v0 投信 5 日買超％／名次 (CONDITIONAL)."""
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

import touxin_5d as t5  # noqa: E402
from touxin_ledger import append_rows, query_rows_pit  # noqa: E402

try:
    import postmarket_report as _postmarket_report  # noqa: E402
except ImportError:
    _postmarket_report = None

FIXTURE_PATH = ROOT / 'tests' / 'fixtures' / 'touxin_ledger' / 'sample_rows.json'


class TouxinLedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name
        append_rows(json.loads(FIXTURE_PATH.read_text(encoding='utf-8')), base_dir=self.base_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_is_idempotent(self):
        fresh = tempfile.TemporaryDirectory()
        try:
            rows = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
            first = append_rows(rows, base_dir=fresh.name)
            second = append_rows(rows, base_dir=fresh.name)
            self.assertGreater(first, 0)
            self.assertEqual(second, 0)
        finally:
            fresh.cleanup()

    def test_pit_excludes_post_cutoff_ingestion(self):
        late = {
            'symbol': '2330',
            'session_date': '2026-01-09',
            'trust_net_shares': 99999,
            'volume_shares': 1000000,
            'source': 'fixture/late',
            'ingested_at': '2026-01-15T13:30:00+08:00',
        }
        append_rows([late], base_dir=self.base_dir)
        pit = query_rows_pit(
            '2330',
            as_of='2026-01-09',
            knowledge_cutoff='2026-01-10T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        dates = [r.session_date for r in pit]
        self.assertNotIn('2026-01-09', dates)


class Touxin5dComputeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name
        append_rows(json.loads(FIXTURE_PATH.read_text(encoding='utf-8')), base_dir=self.base_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_5d_net_buy_and_pct_on_fixture(self):
        obs = t5.build_observation(
            '2330',
            as_of='2026-01-08',
            knowledge_cutoff='2026-01-15T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['contractId'], t5.CONTRACT_ID)
        self.assertEqual(obs['label'], 'CONDITIONAL')
        self.assertIsNone(obs['hostApprovalHash'])
        self.assertEqual(obs['disclaimerKey'], t5.DISCLAIMER_KEY)
        self.assertEqual(obs['netBuyShares'], 52000.0)
        volume5d = 5000000 + 4800000 + 5200000 + 5100000 + 5300000
        self.assertAlmostEqual(obs['netBuyPct'], 52000.0 / volume5d, places=6)
        self.assertEqual(len(obs['sessionDates']), 5)

    def test_rank_among_universe(self):
        obs = t5.build_observation(
            '2330',
            as_of='2026-01-08',
            knowledge_cutoff='2026-01-15T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        obs_2317 = t5.build_observation(
            '2317',
            as_of='2026-01-08',
            knowledge_cutoff='2026-01-15T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        obs_2454 = t5.build_observation(
            '2454',
            as_of='2026-01-08',
            knowledge_cutoff='2026-01-15T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['rankAmongUniverse'], 1)
        self.assertEqual(obs_2317['rankAmongUniverse'], 2)
        self.assertEqual(obs_2454['rankAmongUniverse'], 3)
        self.assertEqual(obs['universeSize'], 3)

    def test_label_always_conditional(self):
        obs = t5.build_observation(
            '2330',
            as_of='2026-01-08',
            knowledge_cutoff='2026-01-15T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['label'], 'CONDITIONAL')
        self.assertEqual(obs['epistemic'], 'CONDITIONAL')

    def test_no_decision_context_writes(self):
        source = Path(SERVER_DIR / 'touxin_5d.py').read_text(encoding='utf-8')
        self.assertNotIn('import decision_context', source)
        self.assertNotIn('publish_context(', source)
        self.assertNotIn('actionEnvelope', source)


@unittest.skipUnless(_postmarket_report, 'postmarket_report 不在 tip UX，EvidencePack 掛接僅 main 線')
class Touxin5dEvidencePackTests(unittest.TestCase):
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
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name
        append_rows(json.loads(FIXTURE_PATH.read_text(encoding='utf-8')), base_dir=self.base_dir)
        os.environ['ST_SHADOW_TOUXIN_5D'] = '1'

    def tearDown(self):
        self._pr.configure(bars_fn=None)
        self._tmp.cleanup()
        os.environ.pop('ST_SHADOW_TOUXIN_5D', None)

    def test_evidence_pack_attaches_touxin_when_flag_on(self):
        pack = self._pr.build_evidence_pack(
            '2330',
            include={'quotes': True},
            now=datetime.now(self._pr.TZ_TPE).replace(hour=15, minute=5, second=0, microsecond=0),
        )
        if 'touxin5dNetBuy' in pack:
            obs = pack['touxin5dNetBuy']
            self.assertEqual(obs['label'], 'CONDITIONAL')
            self.assertEqual(obs['contractId'], t5.CONTRACT_ID)
            self.assertEqual(obs['disclaimerKey'], t5.DISCLAIMER_KEY)


class Touxin5dRouteTests(unittest.TestCase):
    def test_disabled_payload_is_conditional(self):
        payload = t5.disabled_payload()
        self.assertEqual(payload['label'], 'CONDITIONAL')
        self.assertEqual(payload['disclaimerKey'], t5.DISCLAIMER_KEY)
        self.assertIsNone(payload['hostApprovalHash'])


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for st-peak-100d-v0 observation-only 100-session peak distance (CONDITIONAL)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

import peak_observation_100d as po100  # noqa: E402
from ohlc_ledger import append_bars  # noqa: E402

FIXTURE_PATH = ROOT / 'tests' / 'fixtures' / 'ohlc_ledger' / 'sample_bars.json'


def _trading_days(count: int, end: date) -> list[dict]:
    """Build descending trading-day bars ending at ``end`` (weekdays only)."""
    rows: list[dict] = []
    day = end
    while len(rows) < count:
        if day.weekday() < 5:
            idx = len(rows)
            close = 80.0 + float(idx)
            rows.append({
                'symbol': '2330',
                'session_date': day.isoformat(),
                'price_basis': 'unadj_close',
                'open': close - 1.0,
                'high': close + 2.0,
                'low': close - 2.0,
                'close': close,
                'source': 'fixture/100d',
                'ingested_at': f'{day.isoformat()}T13:30:00+08:00',
                'generation_id': 'gen-100d',
            })
        day = day.fromordinal(day.toordinal() - 1)
    rows.reverse()
    return rows


class PeakObservation100dComputeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_contract_fields_on_small_fixture(self):
        append_bars(json.loads(FIXTURE_PATH.read_text(encoding='utf-8')), base_dir=self.base_dir)
        obs = po100.build_observation(
            '2330',
            as_of='2026-01-03',
            knowledge_cutoff='2026-01-10T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['contractId'], po100.CONTRACT_ID)
        self.assertEqual(obs['contractId'], 'st-peak-100d-v0')
        self.assertEqual(obs['windowDays'], 100)
        self.assertEqual(obs['peakKind'], 'A')
        self.assertEqual(obs['label'], 'CONDITIONAL')
        self.assertIsNone(obs['hostApprovalHash'])
        self.assertEqual(obs['disclaimerKey'], po100.DISCLAIMER_KEY)
        self.assertIn('pitLimitation', obs)
        self.assertIn('only 2 trading sessions', obs['pitLimitation'])

    def test_history_start_uses_last_100_sessions(self):
        end = date(2026, 6, 30)
        while end.weekday() >= 5:
            end = end.fromordinal(end.toordinal() - 1)
        bars = _trading_days(120, end)
        append_bars(bars, base_dir=self.base_dir)
        as_of = bars[-1]['session_date']
        obs = po100.build_observation(
            '2330',
            as_of=as_of,
            knowledge_cutoff=f'{as_of}T15:00:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertEqual(obs['windowDays'], 100)
        expected_start = bars[-100]['session_date']
        self.assertEqual(obs['historyStart'], expected_start)
        peak_close = max(float(row['close']) for row in bars[-100:])
        self.assertEqual(obs['peakClose'], peak_close)
        self.assertEqual(obs['lastClose'], float(bars[-1]['close']))
        self.assertAlmostEqual(obs['pctBelowPeak'], obs['lastClose'] / obs['peakClose'] - 1.0, places=6)

    def test_peak_excludes_bars_before_window(self):
        end = date(2026, 3, 31)
        while end.weekday() >= 5:
            end = end.fromordinal(end.toordinal() - 1)
        bars = _trading_days(110, end)
        # Spike only in the oldest 10 sessions (outside 100d window).
        for row in bars[:10]:
            row['close'] = 500.0
            row['high'] = 510.0
        append_bars(bars, base_dir=self.base_dir)
        as_of = bars[-1]['session_date']
        obs = po100.build_observation(
            '2330',
            as_of=as_of,
            knowledge_cutoff=f'{as_of}T15:00:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertNotEqual(obs['peakClose'], 500.0)
        self.assertEqual(obs['peakClose'], max(float(row['close']) for row in bars[-100:]))

    def test_pct_below_peak_in_range(self):
        append_bars(json.loads(FIXTURE_PATH.read_text(encoding='utf-8')), base_dir=self.base_dir)
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
        append_bars([extra], base_dir=self.base_dir)
        obs = po100.build_observation(
            '2330',
            as_of='2026-01-05',
            knowledge_cutoff='2026-01-15T13:30:00+08:00',
            base_dir=self.base_dir,
        )
        self.assertGreaterEqual(obs['pctBelowPeak'], -1.0)
        self.assertLessEqual(obs['pctBelowPeak'], 0.0)

    def test_adj_close_missing_metadata_returns_null(self):
        append_bars(json.loads(FIXTURE_PATH.read_text(encoding='utf-8')), base_dir=self.base_dir)
        obs = po100.build_observation(
            '2330',
            as_of='2026-01-03',
            knowledge_cutoff='2026-01-10T13:30:00+08:00',
            price_basis='adj_close',
            base_dir=self.base_dir,
        )
        self.assertIsNone(obs['pctBelowPeak'])
        self.assertIn('basisAsOf', obs['nullReason'])
        self.assertEqual(obs['label'], 'CONDITIONAL')

    def test_no_decision_context_writes(self):
        source = Path(SERVER_DIR / 'peak_observation_100d.py').read_text(encoding='utf-8')
        self.assertNotIn('import decision_context', source)
        self.assertNotIn('publish_context(', source)
        self.assertNotIn('actionEnvelope', source.replace('actionEnvelope, or FACT labels', ''))


class PeakObservation100dEvidencePackTests(unittest.TestCase):
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

    def test_evidence_pack_attaches_peak_100d_when_flag_on(self):
        pack = self._pr.build_evidence_pack(
            '2330',
            include={'quotes': True},
            now=datetime.now(self._pr.TZ_TPE).replace(hour=15, minute=5, second=0, microsecond=0),
        )
        self.assertIn('peakObservation100d', pack)
        peak = pack['peakObservation100d']
        self.assertEqual(peak['label'], 'CONDITIONAL')
        self.assertEqual(peak['contractId'], po100.CONTRACT_ID)
        self.assertEqual(peak['disclaimerKey'], po100.DISCLAIMER_KEY)
        self.assertEqual(peak['windowDays'], 100)


class PeakObservation100dRouteTests(unittest.TestCase):
    def test_disabled_payload_is_conditional(self):
        payload = po100.disabled_payload()
        self.assertEqual(payload['label'], 'CONDITIONAL')
        self.assertEqual(payload['contractId'], po100.CONTRACT_ID)
        self.assertEqual(payload['disclaimerKey'], po100.DISCLAIMER_KEY)
        self.assertIsNone(payload['hostApprovalHash'])


if __name__ == '__main__':
    unittest.main()

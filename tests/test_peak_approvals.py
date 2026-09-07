#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import peak_approvals as pa


class PeakApprovalsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_and_lookup_roundtrip(self):
        evidence = 'abc123deadbeef'
        first = pa.record_approval(
            evidence,
            approved_by='Sam',
            approval_note='fixture',
            base_dir=self.base_dir,
        )
        self.assertTrue(first['inserted'])
        host_hash = first['hostApprovalHash']
        self.assertEqual(pa.lookup_host_approval_hash(evidence, base_dir=self.base_dir), host_hash)

        second = pa.record_approval(evidence, approved_by='Sam', base_dir=self.base_dir)
        self.assertFalse(second['inserted'])
        self.assertEqual(second['hostApprovalHash'], host_hash)

    def test_host_approval_hash_is_stable(self):
        evidence = 'stable-evidence-hash'
        approved_at = '2026-01-10T05:30:00+00:00'
        h1 = pa.compute_host_approval_hash(
            contract_id=pa.CONTRACT_ID,
            evidence_hash=evidence,
            approved_by='Sam',
            approved_at=approved_at,
            approval_note='note',
        )
        h2 = pa.compute_host_approval_hash(
            contract_id=pa.CONTRACT_ID,
            evidence_hash=evidence,
            approved_by='Sam',
            approved_at=approved_at,
            approval_note='note',
        )
        self.assertEqual(h1, h2)


if __name__ == '__main__':
    unittest.main()

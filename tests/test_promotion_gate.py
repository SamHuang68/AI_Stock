#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for promotion gate checklist (default FAIL until criteria met)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import promotion_gate as pg  # noqa: E402


class PromotionGateTests(unittest.TestCase):
    def test_default_verdict_is_fail(self):
        result = pg.evaluate(None)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertFalse(result['autoPromote'])
        self.assertEqual(len(result['checks']), 4)
        self.assertTrue(all(not check['passed'] for check in result['checks']))

    def test_default_fail_payload_matches_evaluate(self):
        self.assertEqual(pg.default_fail_payload()['verdict'], 'FAIL')

    def test_full_bundle_passes_all_checks(self):
        bundle = {
            'oosReport': {
                'status': 'complete',
                'reportId': 'oos-2026-09',
                'asOf': '2026-09-01',
                'sampleSize': 80,
                'windows': [{'id': 'w1'}, {'id': 'w2'}, {'id': 'w3'}],
            },
            'costTurnoverNotes': {
                'status': 'documented',
                'turnoverBps': 50.0,
                'costBps': 15.0,
                'summary': 'TW equity round-trip cost model',
            },
            'decayMonitor': {
                'status': 'active',
                'metric': 'rank_ic_20d',
                'lookbackDays': 90,
                'alertThreshold': 0.2,
            },
            'features': ['deviationZ', 'relativeStrengthPct', 'momentum60d'],
        }
        result = pg.evaluate(bundle)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertTrue(all(check['passed'] for check in result['checks']))

    def test_feature_count_over_cap_fails(self):
        bundle = {
            'oosReport': {
                'status': 'complete',
                'reportId': 'x',
                'asOf': '2026-09-01',
                'sampleSize': 80,
                'windows': [{'id': 'w1'}, {'id': 'w2'}, {'id': 'w3'}],
            },
            'costTurnoverNotes': {
                'status': 'documented',
                'turnoverBps': 50.0,
                'costBps': 15.0,
                'summary': 'ok',
            },
            'decayMonitor': {
                'status': 'active',
                'metric': 'ic',
                'lookbackDays': 60,
                'alertThreshold': 0.1,
            },
            'features': [f'f{i}' for i in range(pg.FEATURE_COUNT_CAP + 1)],
        }
        result = pg.evaluate(bundle)
        self.assertEqual(result['verdict'], 'FAIL')
        cap_check = next(c for c in result['checks'] if c['id'] == 'featureCountCap')
        self.assertFalse(cap_check['passed'])


if __name__ == '__main__':
    unittest.main()

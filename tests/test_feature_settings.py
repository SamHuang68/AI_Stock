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

from feature_settings import FEATURE_KEYS, feature_flags, is_enabled, public_payload


class FeatureSettingsTests(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in (
            'ST_ENABLE_SHADOW_RESEARCH',
            'ST_SHADOW_OVERNIGHT_INTRADAY',
            'ST_SHADOW_EARLY_WARNING',
            'ST_SHADOW_CONSENSUS_ATTENTION',
        )}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_defaults_are_off(self):
        flags = feature_flags()
        for key in FEATURE_KEYS:
            if key in ('ohlcLedger', 'shadowPeakObservation', 'shadowTouxin5d'):
                self.assertTrue(flags[key])
            else:
                self.assertFalse(flags[key])

    def test_master_env_enables_all(self):
        os.environ['ST_ENABLE_SHADOW_RESEARCH'] = '1'
        flags = feature_flags()
        for key in FEATURE_KEYS:
            self.assertTrue(flags[key])

    def test_local_override_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / 'data'
            data_dir.mkdir()
            (data_dir / 'feature_flags.local.json').write_text(
                json.dumps({'shadowEarlyWarning': True}), encoding='utf-8'
            )
            flags = feature_flags(tmp)
            self.assertTrue(flags['shadowEarlyWarning'])
            self.assertFalse(flags['shadowOvernightIntraday'])

    def test_public_payload_documents_enable_path(self):
        payload = public_payload()
        self.assertTrue(payload['ok'])
        self.assertIn('flags', payload)
        self.assertIn('enable', payload)
        self.assertEqual(payload['enable']['masterEnv'], 'ST_ENABLE_SHADOW_RESEARCH')


if __name__ == '__main__':
    unittest.main()

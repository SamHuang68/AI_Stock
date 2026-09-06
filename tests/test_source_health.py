#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Characterization tests for extracted source_health module."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import source_health as sh  # noqa: E402


class SourceHealthTests(unittest.TestCase):
    def setUp(self):
        with sh._LOCK:
            sh.HEALTH.clear()
            sh.LAST_CALL.clear()

    def test_record_opens_breaker_after_threshold(self):
        for _ in range(sh.CB_THRESHOLD):
            sh.record('twse-mis', False, 10, 'timeout')
        self.assertTrue(sh.breaker_open('twse-mis'))
        snap = sh.snapshot()['twse-mis']
        self.assertFalse(snap['healthy'])
        self.assertTrue(snap['breakerOpen'])

    def test_success_resets_fail_streak(self):
        for _ in range(sh.CB_THRESHOLD - 1):
            sh.record('taifex-mis', False, 5, 'err')
        sh.record('taifex-mis', True, 8)
        self.assertFalse(sh.breaker_open('taifex-mis'))
        snap = sh.snapshot()['taifex-mis']
        self.assertTrue(snap['healthy'])
        self.assertEqual(snap['failStreak'], 0)

    def test_fetch_json_raises_when_breaker_open(self):
        with sh._LOCK:
            sh.HEALTH['yahoo-keystats'] = {
                'ok_ct': 0,
                'err_ct': sh.CB_THRESHOLD,
                'last_ok': 0,
                'last_err': time.time(),
                'last_ms': 1,
                'fail_streak': sh.CB_THRESHOLD,
                'last_error': 'boom',
                'open_until': time.time() + 60,
            }
        with self.assertRaises(sh.SourceBreakerOpen):
            sh.fetch_json('yahoo-keystats', 'http://example.invalid')

    def test_fetch_json_records_success(self):
        payload = {'ok': True}
        with patch('http_client.request') as req:
            req.return_value = type('Resp', (), {'body': b'{"ok": true}'})()
            out = sh.fetch_json('twse-chip', 'http://example.test', retries=0)
        self.assertEqual(out, payload)
        snap = sh.snapshot()['twse-chip']
        self.assertTrue(snap['healthy'])
        self.assertEqual(snap['calls'], 1)


if __name__ == '__main__':
    unittest.main()

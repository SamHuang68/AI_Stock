#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'server')
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import datastore
import options_schedule as sched

TW = ZoneInfo('Asia/Taipei')
WEDNESDAY = (2026, 10, 7)
SATURDAY = (2026, 10, 10)


def at(day, hour, minute=0):
    return datetime(*day, hour, minute, tzinfo=TW)


class OptionsScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        for patcher in (mock.patch.object(datastore, 'DB_PATH', str(self.data / 'market.db')),
                        mock.patch.object(sched.options_exposure, 'latest_cached', lambda: self.cached)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cached = None
        self.calls = []

    def submit(self, kind, params=None):
        self.calls.append((kind, params))
        return {'ok': True}

    def enable(self, value=True):
        (self.data / 'options_daily_schedule.json').write_text(json.dumps({'enabled': value}), encoding='utf-8')

    def attempts(self):
        return json.loads((self.data / 'options_daily_attempts.json').read_text(encoding='utf-8'))

    def test_disabled_by_default_and_for_non_true_values(self):
        self.assertFalse(sched.tick(at(WEDNESDAY, 18, 40), self.submit))
        (self.data / 'options_daily_schedule.json').write_text('{"enabled": "yes"}', encoding='utf-8')
        self.assertFalse(sched.tick(at(WEDNESDAY, 18, 40), self.submit))
        self.assertEqual(self.calls, [])

    def test_submits_force_options_job_once_per_slot(self):
        self.enable()
        self.assertTrue(sched.tick(at(WEDNESDAY, 18, 40), self.submit))
        self.assertFalse(sched.tick(at(WEDNESDAY, 18, 50), self.submit))
        self.assertEqual(self.calls, [('options', {'force': True})])
        self.assertEqual(self.attempts()['2026-10-07/1110']['status'], 'queued')

    def test_next_slot_retries_when_chain_still_old(self):
        self.enable()
        self.cached = {'observed': {'tradeDate': '2026-10-06'}}
        self.assertTrue(sched.tick(at(WEDNESDAY, 18, 40), self.submit))
        self.assertTrue(sched.tick(at(WEDNESDAY, 19, 31), self.submit))
        self.assertTrue(sched.tick(at(WEDNESDAY, 20, 31), self.submit))
        self.assertEqual(len(self.calls), 3)

    def test_stops_when_todays_chain_is_cached(self):
        self.enable()
        self.cached = {'observed': {'tradeDate': '2026-10-07'}}
        self.assertFalse(sched.tick(at(WEDNESDAY, 19, 31), self.submit))
        self.assertEqual(self.calls, [])

    def test_outside_window_and_closed_days_do_nothing(self):
        self.enable()
        for moment in (at(WEDNESDAY, 17, 59), at(WEDNESDAY, 18, 29), at(WEDNESDAY, 21, 0), at(SATURDAY, 19, 0)):
            self.assertFalse(sched.tick(moment, self.submit), moment.isoformat())
        self.assertEqual(self.calls, [])

    def test_rejected_submit_is_recorded_and_not_retried_in_same_slot(self):
        self.enable()

        def reject(kind, params=None):
            raise RuntimeError('queue full')
        self.assertFalse(sched.tick(at(WEDNESDAY, 18, 40), reject))
        self.assertEqual(self.attempts()['2026-10-07/1110']['status'], 'rejected')
        self.assertFalse(sched.tick(at(WEDNESDAY, 18, 50), self.submit))
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import threading
import unittest

from server.deadline import BoundedExecutor, Deadline, collect_named


class DeadlineTests(unittest.TestCase):
    def test_collect_returns_at_deadline_and_pool_rejects_overload(self):
        executor = BoundedExecutor(1, 1, prefix='deadline-test')
        started = time.monotonic()
        future = executor.submit(time.sleep, 0.25)
        values, outcomes = collect_named({'slow': future}, timeout=0.02, executor=executor)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.12)
        self.assertEqual(values, {})
        self.assertEqual(outcomes['slow'], 'timeout')
        self.assertIsNone(executor.submit(lambda: 1))
        future.result(timeout=1)
        self.assertEqual(executor.submit(lambda: 2).result(timeout=1), 2)
        executor.shutdown()

    def test_deadline_uses_remaining_monotonic_budget(self):
        deadline = Deadline(0.08)
        first = deadline.remaining()
        time.sleep(0.02)
        self.assertLess(deadline.remaining(), first)
        self.assertFalse(deadline.expired())

    def test_cancelled_queued_work_releases_its_capacity_slot(self):
        executor = BoundedExecutor(1, 2, prefix='deadline-cancel-test')
        release = threading.Event()
        first = executor.submit(release.wait, 1)
        queued = executor.submit(lambda: 'never')
        self.assertIsNotNone(first)
        self.assertIsNotNone(queued)
        _, outcomes = collect_named({'queued': queued}, timeout=0.01, executor=executor)
        self.assertEqual(outcomes['queued'], 'timeout')
        release.set()
        first.result(timeout=1)
        deadline = time.monotonic() + 1
        while executor.status()['inFlight'] and time.monotonic() < deadline:
            time.sleep(0.01)
        a = executor.submit(lambda: 1)
        b = executor.submit(lambda: 2)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(a.result(timeout=1), 1)
        self.assertEqual(b.result(timeout=1), 2)
        executor.shutdown()


if __name__ == '__main__':
    unittest.main()

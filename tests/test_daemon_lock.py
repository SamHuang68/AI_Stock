#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from daemon_lock import acquire_daemon_lock, release_daemon_lock  # noqa: E402


class DaemonLockTests(unittest.TestCase):
    def test_second_owner_is_blocked_and_release_allows_reacquire(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_dir = Path(temp_dir)
            first = acquire_daemon_lock("watch_daemon", lock_dir=lock_dir)
            self.assertIsNotNone(first)
            try:
                second = acquire_daemon_lock("watch_daemon", lock_dir=lock_dir)
                self.assertIsNone(second)
            finally:
                release_daemon_lock(first)
            third = acquire_daemon_lock("watch_daemon", lock_dir=lock_dir)
            self.assertIsNotNone(third)
            release_daemon_lock(third)

    def test_invalid_lock_name_is_rejected(self):
        with self.assertRaises(ValueError):
            acquire_daemon_lock("../outside")


if __name__ == "__main__":
    unittest.main()

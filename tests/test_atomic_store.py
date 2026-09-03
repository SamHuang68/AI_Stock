#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from server import atomic_store


class AtomicStoreTests(unittest.TestCase):
    def test_failed_replace_preserves_previous_value(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            atomic_store.atomic_write_json(path, {'v': 1})
            real_replace = atomic_store.os.replace

            def fail_target(src, dst):
                if Path(dst) == path:
                    raise OSError('injected replace failure')
                return real_replace(src, dst)

            with mock.patch.object(atomic_store.os, 'replace', side_effect=fail_target):
                with self.assertRaises(OSError):
                    atomic_store.atomic_write_json(path, {'v': 2})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'v': 1})

    def test_corrupt_primary_recovers_backup_and_quarantines(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            atomic_store.atomic_write_json(path, {'v': 1})
            atomic_store.atomic_write_json(path, {'v': 2})
            path.write_text('{', encoding='utf-8')
            self.assertEqual(atomic_store.load_json(path, default={}, expected_type=dict), {'v': 1})
            self.assertTrue(list(Path(td).glob('state.json.corrupt-*')))

    def test_concurrent_writers_leave_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            errors = []

            def write(value):
                try:
                    atomic_store.atomic_write_json(path, {'v': value})
                except Exception as exc:  # A background failure must fail the test.
                    errors.append(exc)

            threads = [
                threading.Thread(target=write, args=(i,))
                for i in range(40)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            value = json.loads(path.read_text(encoding='utf-8'))
            self.assertIn(value['v'], range(40))

    def test_windows_sharing_violation_is_retried(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            real_replace = atomic_store.os.replace
            attempts = 0

            def transient_replace(src, dst):
                nonlocal attempts
                if Path(dst) == path and attempts == 0:
                    attempts += 1
                    exc = PermissionError('transient sharing violation')
                    exc.winerror = 5
                    raise exc
                return real_replace(src, dst)

            # Patch the module's platform seam rather than ``os.name`` itself.
            # ``atomic_store.os`` is Python's process-wide os module, so changing
            # its name makes pathlib attempt to construct WindowsPath on Linux.
            with mock.patch.object(atomic_store, '_IS_WINDOWS', True):
                with mock.patch.object(atomic_store.os, 'replace', side_effect=transient_replace):
                    atomic_store.atomic_write_json(path, {'v': 7})
            self.assertEqual(attempts, 1)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'v': 7})


if __name__ == '__main__':
    unittest.main()

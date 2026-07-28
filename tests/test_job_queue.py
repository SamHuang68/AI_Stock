# -*- coding: utf-8 -*-
"""H5 job_queue coalesce / status."""
import time
import threading
import unittest
import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import job_queue as jq  # noqa: E402


class TestJobQueue(unittest.TestCase):
    def test_coalesce_while_running(self):
        name = 'test_coalesce_' + uuid.uuid4().hex[:8]
        started = threading.Event()
        release = threading.Event()

        def slow():
            started.set()
            release.wait(timeout=3)

        r1 = jq.submit(name, slow, coalesce=True)
        self.assertTrue(r1.get('queued'))
        self.assertTrue(started.wait(timeout=2), 'worker did not start')
        r2 = jq.submit(name, slow, coalesce=True)
        self.assertTrue(r2.get('skipped'))
        release.set()
        for _ in range(80):
            st = jq.status()
            run = st.get('running')
            if (not run or run.get('name') != name) and name not in st.get('pending', []):
                break
            time.sleep(0.05)

    def test_status_shape(self):
        st = jq.status()
        self.assertIn('pending', st)
        self.assertIn('running', st)
        self.assertIn('history', st)


if __name__ == '__main__':
    unittest.main()

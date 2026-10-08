"""受管工作期限與終態註冊清理。"""
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import job_queue
import daily_cache_jobs as daily
import datastore


class FakeClock:
    def __init__(self):
        self.value = 100.0
    def __call__(self):
        return self.value


class ManagedCallableBudgetTests(unittest.TestCase):
    def setUp(self):
        directory = os.environ.get('ST_QUEUE_TEST_EVIDENCE_DIR')
        self.temp = tempfile.TemporaryDirectory(prefix='queue-case-', dir=directory)
        self.root = Path(self.temp.name)
        self.clock = FakeClock()
        self.queue = job_queue.DurableJobQueue(self.root / 'jobs.sqlite3', capacity=4, monotonic=self.clock)
        self.old_default = job_queue._durable_default
        self.old_active, self.old_cancel = daily._active, daily._cancel
        daily._active, daily._cancel = None, threading.Event()
        self.release_events = []
        self.queue.start()
        job_queue.use_durable_queue(self.queue)

    def tearDown(self):
        for event in self.release_events:
            event.set()
        stopped = self.queue.stop(timeout=3)
        self.assertTrue(stopped, '工作者須結束後才能刪除鎖檔目錄。')
        self.assertIsNone(self.queue._lease)
        job_queue.use_durable_queue(self.old_default)
        daily._active, daily._cancel = self.old_active, self.old_cancel
        self.temp.cleanup()

    def terminal(self, job_id):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            job = self.queue.get(job_id)
            if job and job['status'] not in ('queued', 'running') and job_id not in self.queue._callables:
                return job
            time.sleep(0.005)
        self.fail('持久終態與 callback 清理未於期限內完成。')

    def daily_scenario(self, seconds, fetch_hook=None):
        cutoff = date(2026, 10, 7)
        ts = int(datetime.combine(cutoff, datetime.min.time().replace(hour=12), daily._TZ['US']).timestamp())
        def fetch(*args, **kwargs):
            self.assertEqual(kwargs['deadline'].remaining(), 600)
            self.clock.value += seconds
            if fetch_hook is not None:
                fetch_hook()
            return [(ts, 100, 102, 99, 101, 1000)]
        with patch.object(datastore, 'DB_PATH', str(self.root / 'market.sqlite3')), \
             patch.object(datastore, 'completed_daily_cutoff', return_value=cutoff), \
             patch.object(datastore, 'fetch_yahoo_daily', side_effect=fetch), \
             patch.object(daily, 'time', SimpleNamespace(monotonic=self.clock, time=time.time)):
            result = daily.submit({'symbols': [{'symbol': 'AAPL', 'market': 'US'}], 'range': '1y'})
            self.assertTrue(result['ok'])
            queue_job = self.queue.status()['jobs'][0]
            terminal = self.terminal(queue_job['jobId'])
            return daily.status(), terminal, datastore.get_bars('AAPL', market='US')

    def test_daily_350_seconds_succeeds_with_unchanged_600_source_budget(self):
        state, terminal, bars = self.daily_scenario(350)
        self.assertEqual(state['limits']['seconds'], 600)
        self.assertEqual(terminal['timeoutSeconds'], 660)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(terminal['status'], 'succeeded')
        self.assertEqual(terminal['result']['status'], 'completed')
        self.assertEqual(terminal['result']['jobId'], state['jobId'])
        self.assertEqual(len(bars), 1)
        self.assertNotIn(terminal['type'], self.queue._handlers)

    def test_daily_650_does_not_relax_source_budget_or_write_late_bars(self):
        state, terminal, bars = self.daily_scenario(650)
        self.assertEqual(state['limits']['seconds'], 600)
        self.assertEqual(terminal['timeoutSeconds'], 660)
        self.assertEqual(state['status'], 'failed')
        self.assertIn('十分鐘', state['error'])
        self.assertEqual(bars, [])
        self.assertEqual(terminal['status'], 'failed')
        self.assertIn(state['error'], terminal['error'])

    def test_actual_source_error_is_failed_in_both_status_paths(self):
        def source_failure():
            raise ValueError('source-fixture-error')
        state, terminal, bars = self.daily_scenario(20, source_failure)
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(terminal['status'], 'failed')
        self.assertIn('source-fixture-error', terminal['error'])
        self.assertEqual(bars, [])

    def test_running_cancel_returns_cancelled_result_without_write(self):
        def cancel_running():
            daily.cancel(daily.status()['jobId'])
        state, terminal, bars = self.daily_scenario(20, cancel_running)
        self.assertEqual(state['status'], 'cancelled')
        self.assertEqual(terminal['status'], 'succeeded')
        self.assertEqual(terminal['result']['status'], 'cancelled')
        self.assertEqual(terminal['result']['jobId'], state['jobId'])
        self.assertEqual(bars, [])

    def test_invocation_uses_own_snapshot_when_new_job_replaces_global_state(self):
        run = daily._run
        def replace_after_snapshot(*args):
            outcome = run(*args)
            with daily._lock:
                daily._active = {'jobId': 'replacement-job', 'status': 'failed', 'error': 'replacement-error'}
            return outcome
        with patch.object(daily, '_run', side_effect=replace_after_snapshot):
            state, terminal, bars = self.daily_scenario(350)
        self.assertEqual(state['jobId'], 'replacement-job')
        self.assertEqual(terminal['status'], 'succeeded')
        self.assertEqual(terminal['result']['status'], 'completed')
        self.assertNotEqual(terminal['result']['jobId'], 'replacement-job')
        self.assertNotIn('replacement-error', str(terminal['result']))
        self.assertEqual(len(bars), 1)

    def test_private_sync_run_returns_failed_snapshot_without_raising(self):
        with patch.object(datastore, 'DB_PATH', str(self.root / 'market.sqlite3')), \
             patch.object(datastore, 'completed_daily_cutoff', return_value=date(2026, 10, 7)), \
             patch.object(datastore, 'fetch_yahoo_daily', side_effect=ValueError('direct-source-error')), \
             patch.object(job_queue, 'submit', return_value={'ok': True}):
            result = daily.submit({'symbols': [{'symbol': 'AAPL', 'market': 'US'}], 'range': '1y'})
            outcome = daily._run([{'symbol': 'AAPL', 'market': 'US'}], '1y', 'history',
                                 daily.Budget(daily._cancel), result['jobId'])
        self.assertEqual(outcome['status'], 'failed')
        self.assertIn('direct-source-error', outcome['error'])
        outcome['results'].append('caller-mutation')
        self.assertEqual(daily.status()['results'], [])

    def test_cancelled_queued_old_callback_returns_none_without_fetch(self):
        callback, entered, release = self.blocking_callback()
        block = self.queue.submit_callable('queue-gate', callback)
        self.assertTrue(entered.wait(2))
        result = daily.submit({'symbols': [{'symbol': 'AAPL', 'market': 'US'}], 'range': '1y'})
        queued = next(job for job in self.queue.status()['jobs'] if job['type'].startswith('legacy:selected-daily-cache:'))
        daily.cancel(result['jobId'])
        with patch.object(datastore, 'fetch_yahoo_daily') as fetch:
            release.set()
            self.terminal(block['job']['jobId'])
            terminal = self.terminal(queued['jobId'])
        fetch.assert_not_called()
        self.assertEqual(daily.status()['status'], 'cancelled')
        self.assertEqual(terminal['status'], 'succeeded')
        self.assertIsNone(terminal['result'])

    def test_default_300_callable_reports_timeout_after_650(self):
        def callback():
            self.clock.value += 650
            return {'value': 'returned'}
        result = job_queue.submit('default-budget', callback)
        terminal = self.terminal(result['job']['jobId'])
        self.assertEqual(terminal['timeoutSeconds'], 300)
        self.assertEqual(terminal['status'], 'timed_out')
        self.assertNotIn(terminal['type'], self.queue._handlers)

    def test_explicit_660_accepts_650_and_rejects_661(self):
        for elapsed, expected in ((650, 'succeeded'), (661, 'timed_out')):
            with self.subTest(elapsed=elapsed):
                def callback():
                    self.clock.value += elapsed
                    return {'value': 'returned'}
                result = job_queue.submit('outer-' + str(elapsed), callback, timeout=660)
                terminal = self.terminal(result['job']['jobId'])
                self.assertEqual(terminal['timeoutSeconds'], 660)
                self.assertEqual(terminal['status'], expected)
                self.assertNotIn(terminal['type'], self.queue._handlers)

    def test_callback_error_and_stop_release_after_persisted_terminal(self):
        def error():
            raise ValueError('callback-fixture-error')
        first = self.queue.submit_callable('fails', error)
        failed = self.terminal(first['job']['jobId'])
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('callback-fixture-error', failed['error'])
        self.assertNotIn(failed['type'], self.queue._handlers)
        def stop():
            self.queue._stop.set()
        second = self.queue.submit_callable('stopped', stop)
        interrupted = self.terminal(second['job']['jobId'])
        self.assertEqual(interrupted['status'], 'interrupted')
        self.assertNotIn(interrupted['type'], self.queue._handlers)

    def test_terminal_sql_failure_retains_callback_until_commit(self):
        attempted, allow_commit = threading.Event(), threading.Event()
        self.release_events.append(allow_commit)
        finish = self.queue._finish
        def flaky_finish(*args):
            attempted.set()
            if not allow_commit.wait(0.05):
                raise sqlite3.OperationalError('terminal fixture write blocked')
            return finish(*args)
        with patch.object(self.queue, '_finish', side_effect=flaky_finish):
            result = self.queue.submit_callable('persisting', lambda: {'value': 1})
            self.assertTrue(attempted.wait(2))
            job = result['job']
            self.assertEqual(self.queue.get(job['jobId'])['status'], 'running')
            self.assertIn(job['jobId'], self.queue._callables)
            self.assertIn(job['type'], self.queue._handlers)
            allow_commit.set()
            terminal = self.terminal(job['jobId'])
        self.assertEqual(terminal['status'], 'succeeded')
        self.assertNotIn(job['type'], self.queue._handlers)

    def blocking_callback(self):
        entered, release = threading.Event(), threading.Event()
        self.release_events.append(release)
        def callback():
            entered.set()
            if not release.wait(3):
                raise AssertionError('阻塞 fixture 必須由測試放行。')
            return {'value': 1}
        return callback, entered, release

    def test_queue_reject_and_coalesce_preserve_only_active_kind(self):
        self.queue.capacity = 1
        callback, entered, release = self.blocking_callback()
        first = self.queue.submit_callable('active', callback)
        self.assertTrue(entered.wait(2))
        for name in ('new-rejected', 'active'):
            with self.assertRaises(job_queue.QueueFull):
                self.queue.submit_callable(name, lambda: None, coalesce=False)
        self.assertNotIn('legacy:new-rejected', self.queue._handlers)
        self.assertIn('legacy:active', self.queue._handlers)
        self.assertEqual(set(self.queue._callables), {first['job']['jobId']})
        called = []
        coalesced = self.queue.submit_callable('active', lambda: called.append('wrong'))
        self.assertTrue(coalesced['coalesced'])
        self.assertFalse(coalesced['ok'])
        self.assertEqual(coalesced['job']['jobId'], first['job']['jobId'])
        release.set()
        self.assertEqual(self.terminal(first['job']['jobId'])['status'], 'succeeded')
        self.assertEqual(called, [])
        self.assertNotIn('legacy:active', self.queue._handlers)

    def test_first_terminal_does_not_remove_same_kind_second_queued(self):
        first_fn, first_entered, first_release = self.blocking_callback()
        second_fn, second_entered, second_release = self.blocking_callback()
        first = self.queue.submit_callable('two-jobs', first_fn, coalesce=False)
        self.assertTrue(first_entered.wait(2))
        second = self.queue.submit_callable('two-jobs', second_fn, coalesce=False)
        first_release.set()
        self.assertTrue(second_entered.wait(2))
        self.assertEqual(self.terminal(first['job']['jobId'])['status'], 'succeeded')
        self.assertIn('legacy:two-jobs', self.queue._handlers)
        self.assertIn(second['job']['jobId'], self.queue._callables)
        second_release.set()
        self.assertEqual(self.terminal(second['job']['jobId'])['status'], 'succeeded')
        self.assertNotIn('legacy:two-jobs', self.queue._handlers)

    def test_registered_handler_survives_success(self):
        self.queue.register('research', lambda context, params: {'value': 1}, timeout=600)
        result = self.queue.submit_registered('research')
        self.assertEqual(self.terminal(result['job']['jobId'])['status'], 'succeeded')
        self.assertIn('research', self.queue._handlers)

    def test_restart_cleans_running_and_queued_legacy_orphans_after_commit(self):
        self.assertTrue(self.queue.stop(timeout=3))
        called = []
        first = self.queue.submit_callable('running-orphan', lambda: called.append('wrong'))
        second = self.queue.submit_callable('queued-orphan', lambda: called.append('wrong'))
        claimed = self.queue._claim()
        self.assertIn(claimed['jobId'], (first['job']['jobId'], second['job']['jobId']))
        self.assertEqual(len(self.queue._callables), 2)
        self.queue.start()
        for result in (first, second):
            terminal = self.terminal(result['job']['jobId'])
            self.assertEqual(terminal['status'], 'interrupted')
            self.assertNotIn(terminal['type'], self.queue._handlers)
        self.assertEqual(called, [])


if __name__ == '__main__':
    unittest.main()

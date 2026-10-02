"""Pulse 更新的持久提交、讀取隔離與程序生命週期驗收。"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import pulse_updates as pu


def committed(job_id):
    return {'ok': True, 'updateJobId': job_id, '未保存的完整行情': {'price': 123},
            'decisionSummary': {'persistence': 'committed', 'snapshotId': '快照-' + job_id,
                                'revision': 1, 'inputHash': '輸入雜湊', 'rulesDigest': '規則摘要'}}


class PulseUpdatesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='Pulse佇列-')
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.db = str(self.path / 'jobs.sqlite3')
        self.trace = str(self.path / 'trace.jsonl')
        self.queues = []
        self.addCleanup(self.stop_all)

    def queue(self, **kwargs):
        queue = pu.PulseUpdates(self.db, self.trace, **kwargs)
        self.queues.append(queue)
        return queue

    def stop_all(self):
        for queue in self.queues:
            queue.stop(timeout=3)

    def wait_job(self, queue, job_id, state, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = queue.status(job_id)['job']
            if job and job['status'] == state:
                return job
            time.sleep(0.01)
        self.fail(f'工作未進入預期狀態 {state}：{queue.status(job_id)}')

    def previous_running(self, queue):
        job = queue.submit()['job']
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute(f"UPDATE {pu.TABLE} SET status='running',started_at=? WHERE job_id=?",
                             (time.time() - 20, job['jobId']))
        return job['jobId']

    def wait_worker_error(self, queue, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = queue.status()
            if status['workerError']:
                return status
            time.sleep(0.01)
        self.fail('未觀測到工作者的持久寫入錯誤')

    def block_update(self, column):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute(f'CREATE TRIGGER 阻擋寫入 BEFORE UPDATE OF {column} ON {pu.TABLE} '
                         "BEGIN SELECT RAISE(ABORT, '注入工作收據失敗'); END")

    def unblock_update(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TRIGGER 阻擋寫入')

    def test_status_on_empty_store_creates_no_files_or_worker(self):
        queue = self.queue()
        self.assertIsNone(queue.status()['job'])
        self.assertFalse(queue.status()['worker'])
        self.assertIsNone(queue.status('不存在')['job'])
        self.assertEqual(list(self.path.iterdir()), [])

    def test_status_does_not_migrate_or_modify_legacy_queue(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('CREATE TABLE old_jobs(id TEXT)')
        before = Path(self.db).read_bytes()
        queue = self.queue()
        self.assertEqual(queue.status()['jobs'], [])
        self.assertEqual(Path(self.db).read_bytes(), before)
        queue.submit()
        with closing(sqlite3.connect(self.db)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn('old_jobs', tables)
        self.assertIn(pu.TABLE, tables)

    def test_older_pulse_table_is_readable_and_migrates_only_on_start(self):
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute(f'CREATE TABLE {pu.TABLE}('
                             'job_id TEXT PRIMARY KEY,reason TEXT,status TEXT,queued_at REAL,'
                             'started_at REAL,finished_at REAL,error TEXT,result_json TEXT)')
                conn.execute(f'INSERT INTO {pu.TABLE}(job_id,reason,status,queued_at) VALUES(?,?,?,?)',
                             ('舊工作', 'manual', 'queued', time.time()))
        queue = self.queue()
        self.assertIsNone(queue.status()['job']['recovery'])
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertNotIn('recovery_json', {row[1] for row in conn.execute(f'PRAGMA table_info({pu.TABLE})')})
        queue.start(lambda current, guard: committed(current), lambda: None)
        self.wait_job(queue, '舊工作', 'succeeded')
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertIn('recovery_json', {row[1] for row in conn.execute(f'PRAGMA table_info({pu.TABLE})')})

    def test_concurrent_submissions_coalesce_across_instances_without_starting_worker(self):
        left, right = self.queue(), self.queue()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda index: (left if index % 2 else right).submit(), range(16)))
        self.assertEqual(len({row['job']['jobId'] for row in results}), 1)
        self.assertEqual(sum(not row['coalesced'] for row in results), 1)
        self.assertEqual(len(left.status()['jobs']), 1)
        self.assertFalse(left.status()['worker'])
        before = Path(self.trace).read_bytes()
        left.status()
        self.assertEqual(Path(self.trace).read_bytes(), before)

    def test_success_requires_commit_and_persists_only_snapshot_identity(self):
        queue = self.queue()
        job_id = queue.submit()['job']['jobId']
        def builder(current, guard):
            self.assertEqual(queue.status(current)['job']['status'], 'running')
            guard()
            return committed(current)
        self.assertTrue(queue.start(builder, lambda: None))
        job = self.wait_job(queue, job_id, 'succeeded')
        self.assertEqual(set(job['result']), {'snapshotId', 'revision', 'inputHash', 'rulesDigest'})
        self.assertTrue(queue.stop(timeout=1))
        events = [json.loads(line) for line in Path(self.trace).read_text(encoding='utf-8').splitlines()]
        self.assertTrue(any(row['jobId'] == job_id and row['event'] == 'succeeded' for row in events))

    def test_invalid_or_failed_builder_is_traceable_and_allows_new_submission(self):
        for mode in ('exception', 'uncommitted', 'different_job'):
            with self.subTest(mode=mode):
                queue = self.queue()
                job_id = queue.submit()['job']['jobId']
                def builder(current, guard):
                    if mode == 'exception':
                        raise RuntimeError('注入來源失敗')
                    result = committed(current)
                    if mode == 'different_job':
                        result['updateJobId'] = '其他工作'
                    else:
                        result['decisionSummary']['persistence'] = 'ephemeral'
                    return result
                self.assertTrue(queue.start(builder, lambda: None))
                job = self.wait_job(queue, job_id, 'failed')
                self.assertTrue(job['error'])
                self.assertIsNone(job['result'])
                self.assertTrue(queue.stop(timeout=1))
                self.assertNotEqual(queue.submit()['job']['jobId'], job_id)

    def test_restart_resumes_queued_job_without_replacing_identifier(self):
        original = self.queue()
        job_id = original.submit()['job']['jobId']
        restarted = self.queue()
        observed = []
        self.assertTrue(restarted.start(lambda current, guard: observed.append(current) or committed(current), lambda: None))
        self.wait_job(restarted, job_id, 'succeeded')
        self.assertEqual(observed, [job_id])

    def test_restart_running_without_matching_snapshot_is_interrupted_and_gets_new_job(self):
        queue = self.queue()
        old_id = self.previous_running(queue)
        observed = []
        self.assertTrue(queue.start(lambda current, guard: observed.append(current) or committed(current), lambda: None))
        self.assertEqual(queue.status(old_id)['job']['status'], 'interrupted')
        deadline = time.monotonic() + 3
        while not observed and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(observed), 1)
        self.assertNotEqual(observed[0], old_id)

    def test_restart_running_with_matching_committed_snapshot_repairs_success(self):
        queue = self.queue()
        old_id = self.previous_running(queue)
        self.assertTrue(queue.start(lambda current, guard: committed(current), lambda: committed(old_id)))
        job = queue.status(old_id)['job']
        self.assertEqual(job['status'], 'succeeded')
        self.assertEqual(job['result']['snapshotId'], '快照-' + old_id)

    def test_overdue_running_job_is_observable_and_guard_rejects_late_publication(self):
        clock = [0.0]
        queue = self.queue(clock=lambda: 1000 + clock[0], monotonic=lambda: clock[0])
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def builder(current, guard):
            entered.set()
            release.wait(timeout=3)
            guard()
            return committed(current)
        job_id = queue.submit()['job']['jobId']
        queue.start(builder, lambda: None)
        self.assertTrue(entered.wait(timeout=2))
        clock[0] = 301
        job = queue.status(job_id)['job']
        self.assertEqual(job['status'], 'running')
        self.assertTrue(job['overdue'])
        self.assertTrue(queue.submit()['coalesced'])
        release.set()
        failed = self.wait_job(queue, job_id, 'failed')
        self.assertIn('PulseUpdateExpired', failed['error'])

    def test_stop_timeout_does_not_claim_cancellation_and_guard_prevents_late_publish(self):
        queue = self.queue()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def builder(current, guard):
            entered.set()
            release.wait(timeout=3)
            guard()
            return committed(current)
        job_id = queue.submit()['job']['jobId']
        queue.start(builder, lambda: None)
        self.assertTrue(entered.wait(timeout=2))
        self.assertFalse(queue.stop(timeout=0.01))
        self.assertEqual(queue.status(job_id)['job']['status'], 'running')
        release.set()
        self.assertTrue(queue.stop(timeout=2))
        self.assertEqual(queue.status(job_id)['job']['status'], 'interrupted')

    def test_commit_started_in_time_remains_success_after_deadline(self):
        clock = [0.0]
        queue = self.queue(clock=lambda: 1000 + clock[0], monotonic=lambda: clock[0])
        def builder(current, guard):
            guard()
            # Host 已在時限內準備發布；提交與通知的後續工作可以晚於時限完成。
            clock[0] = 301
            return committed(current)
        job_id = queue.submit()['job']['jobId']
        queue.start(builder, lambda: None)
        self.wait_job(queue, job_id, 'succeeded')

    def test_only_one_worker_owns_same_database_and_stop_releases_ownership(self):
        first, second = self.queue(), self.queue()
        self.assertTrue(first.start(lambda current, guard: committed(current), lambda: None))
        self.assertFalse(second.start(lambda current, guard: committed(current), lambda: None))
        self.assertTrue(first.stop(timeout=2))
        self.assertTrue(second.start(lambda current, guard: committed(current), lambda: None))

    def test_boot_and_interval_enqueue_without_any_reader(self):
        queue = self.queue(interval_seconds=0.03)
        twice = threading.Event()
        seen = []
        def builder(current, guard):
            seen.append(current)
            if len(seen) == 2:
                twice.set()
            return committed(current)
        self.assertTrue(queue.start(builder, lambda: None))
        self.assertTrue(twice.wait(timeout=2))
        self.assertTrue(queue.stop(timeout=2))
        reasons = {job['reason'] for job in queue.status()['jobs']}
        self.assertIn('boot', reasons)
        self.assertIn('scheduled', reasons)

    def test_retention_removes_only_old_terminal_jobs(self):
        queue = self.queue()
        original = queue.submit()['job']['jobId']
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute(f"UPDATE {pu.TABLE} SET status='failed',finished_at=1 WHERE job_id=?", (original,))
                for index in range(1, 5):
                    conn.execute(f'INSERT INTO {pu.TABLE}(job_id,reason,status,queued_at,finished_at) VALUES(?,?,?,?,?)',
                                 (str(index), 'manual', 'interrupted', index, index + 1))
        with patch.object(pu, 'TERMINAL_RETAIN', 3):
            active = queue.submit()['job']['jobId']
        jobs = queue.status()['jobs']
        self.assertEqual(len(jobs), 4)
        self.assertEqual(queue.status(active)['job']['status'], 'queued')
        self.assertIsNone(queue.status(original)['job'])

    def test_terminal_write_failure_retries_receipt_without_rebuilding(self):
        queue = self.queue()
        job_id = queue.submit()['job']['jobId']
        self.block_update('finished_at')
        seen = []
        queue.start(lambda current, guard: seen.append(current) or committed(current), lambda: None)
        failed_write = self.wait_worker_error(queue)
        self.assertTrue(failed_write['worker'])
        self.assertEqual(failed_write['job']['status'], 'running')
        self.assertTrue(queue.submit()['coalesced'])
        self.unblock_update()
        self.wait_job(queue, job_id, 'succeeded')
        self.assertEqual(seen, [job_id])
        self.assertIsNone(queue.status()['workerError'])

    def test_claim_failure_keeps_worker_alive_and_recovers_queued_job(self):
        queue = self.queue()
        job_id = queue.submit()['job']['jobId']
        self.block_update('started_at')
        seen = []
        queue.start(lambda current, guard: seen.append(current) or committed(current), lambda: None)
        failed_claim = self.wait_worker_error(queue)
        self.assertTrue(failed_claim['worker'])
        self.assertEqual(failed_claim['job']['status'], 'queued')
        self.assertEqual(seen, [])
        self.unblock_update()
        self.wait_job(queue, job_id, 'succeeded')
        self.assertEqual(seen, [job_id])

    def test_stop_during_terminal_retry_preserves_running_for_committed_recovery(self):
        queue = self.queue()
        job_id = queue.submit()['job']['jobId']
        self.block_update('finished_at')
        saved = {}
        def builder(current, guard):
            saved[current] = committed(current)
            return saved[current]
        queue.start(builder, lambda: None)
        self.wait_worker_error(queue)
        self.assertTrue(queue.stop(timeout=1))
        self.assertEqual(queue.status(job_id)['job']['status'], 'running')
        self.unblock_update()
        restarted = self.queue()
        restarted.start(lambda current, guard: committed(current), lambda: saved[job_id], saved.get)
        self.assertEqual(restarted.status(job_id)['job']['status'], 'succeeded')
        self.assertEqual(restarted.status(job_id)['job']['recovery']['previousStatus'], 'running')

    def test_new_job_reconciles_prior_interrupted_commit_and_preserves_error(self):
        queue = self.queue()
        old_id = self.previous_running(queue)
        saved = {}
        new_ids = []
        def builder(current, guard):
            new_ids.append(current)
            # 新發布恢復先前已 prepare 的工作，再提交自己的快照。
            saved[old_id] = committed(old_id)
            saved[old_id]['decisionSummary']['revision'] = 2
            saved[current] = committed(current)
            saved[current]['decisionSummary']['revision'] = 3
            return saved[current]
        queue.start(builder, lambda: None, saved.get)
        recovered = self.wait_job(queue, old_id, 'succeeded')
        self.assertEqual(recovered['result']['revision'], 2)
        self.assertEqual(recovered['recovery']['previousStatus'], 'interrupted')
        self.assertIn('前次程序中斷', recovered['recovery']['previousError'])
        self.assertEqual(len(new_ids), 1)
        self.assertNotEqual(new_ids[0], old_id)

    def test_failed_job_is_reconciled_when_commit_became_visible(self):
        queue = self.queue()
        old_id = queue.submit()['job']['jobId']
        with closing(sqlite3.connect(self.db)) as conn:
            with conn:
                conn.execute(f"UPDATE {pu.TABLE} SET status='failed',finished_at=?,error=? WHERE job_id=?",
                             (time.time(), '原始結果未確認', old_id))
        queue.start(lambda current, guard: committed(current), lambda: None,
                    lambda current: committed(current) if current == old_id else None)
        recovered = queue.status(old_id)['job']
        self.assertEqual(recovered['status'], 'succeeded')
        self.assertEqual(recovered['recovery']['previousError'], '原始結果未確認')

    def test_unexpected_worker_exit_rejects_new_submissions(self):
        queue = self.queue()
        with patch.object(queue, '_claim', side_effect=ValueError('注入非持久化錯誤')):
            queue.start(lambda current, guard: committed(current), lambda: None)
            self.wait_worker_error(queue)
            queue._thread.join(timeout=1)
            self.assertFalse(queue.status()['worker'])
            with self.assertRaisesRegex(RuntimeError, '工作者已停止'):
                queue.submit()


if __name__ == '__main__':
    unittest.main()

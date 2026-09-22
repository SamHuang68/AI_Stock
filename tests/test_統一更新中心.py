"""持久更新中心：真實 SQLite、工作者、故障與來源提交邊界；全部離線。"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import job_queue as jq
import options_exposure as options
import overnight_intraday as overnight
from pulse_updates import PulseUpdates
from 更新路由 import UpdateCoordinator, UpdateRoutesMixin


def wait_for(predicate, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('工作沒有在測試期限內完成')


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = jq.DurableJobQueue(Path(self.tmp.name) / 'jobs.db')
        self.queue.register('test', lambda context, params: {'value': params.get('value')})

    def tearDown(self):
        self.queue.stop()
        self.tmp.cleanup()

    def test_read_does_not_create_files_or_start_worker(self):
        self.assertEqual(self.queue.status()['jobs'], [])
        self.assertIsNone(self.queue.get('unknown'))
        self.assertFalse(Path(self.queue.db_path).exists())
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_concurrent_dedup_is_persistent(self):
        ids = []
        threads = [threading.Thread(target=lambda: ids.append(self.queue.submit_registered('test')['job']['jobId'])) for _ in range(20)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(set(ids)), 1)
        other = jq.DurableJobQueue(self.queue.db_path)
        self.assertEqual(other.status()['jobs'][0]['jobId'], ids[0])

    def test_capacity_and_priority(self):
        self.queue.capacity = 2
        order = []
        self.queue.register('low', lambda context, params: order.append('low'), priority=80)
        self.queue.register('high', lambda context, params: order.append('high'), priority=10)
        self.queue.submit_registered('low')
        self.queue.submit_registered('high')
        with self.assertRaises(jq.QueueFull): self.queue.submit_registered('test')
        self.assertTrue(self.queue.submit_registered('low')['coalesced'])
        self.queue.start()
        wait_for(lambda: len(order) == 2)
        self.assertEqual(order, ['high', 'low'])

    def test_aging_prevents_starvation(self):
        clock = [1000.0]
        self.queue.clock = lambda: clock[0]
        order = []
        self.queue.register('low', lambda context, params: order.append('low'), priority=80)
        self.queue.register('high', lambda context, params: order.append('high'), priority=10)
        self.queue.submit_registered('low')
        clock[0] += 61
        self.queue.submit_registered('high')
        self.queue.start()
        wait_for(lambda: len(order) == 2)
        self.assertEqual(order, ['low', 'high'])

    def test_failed_retry_preserves_parent_and_params(self):
        def fail(context, params): raise ValueError('合成來源失敗')
        self.queue.register('test', fail)
        first = self.queue.submit_registered('test', {'value': 23})['job']
        self.queue.start()
        wait_for(lambda: self.queue.get(first['jobId'])['status'] == 'failed')
        self.queue.register('test', lambda context, params: params)
        second = self.queue.retry(first['jobId'])['job']
        wait_for(lambda: self.queue.get(second['jobId'])['status'] == 'succeeded')
        self.assertEqual(second['parentJobId'], first['jobId'])
        self.assertEqual(second['rootJobId'], first['jobId'])
        self.assertEqual(second['attempt'], 2)
        self.assertEqual(self.queue.get(second['jobId'])['result'], {'value': 23})
        self.assertEqual(self.queue.get(first['jobId'])['error'], '合成來源失敗')

    def test_restart_resumes_registered_queue_but_marks_running_interrupted(self):
        running = self.queue.submit_registered('test', {'value': 1})['job']
        queued = self.queue.submit_registered('test', {'value': 2})['job']
        with closing(self.queue._connect()) as conn, conn:
            conn.execute(f"UPDATE {jq._JOB_TABLE} SET status='running',started_at=? WHERE job_id=?", (time.time(), running['jobId']))
        self.queue.start()
        wait_for(lambda: self.queue.get(queued['jobId'])['status'] == 'succeeded')
        self.assertEqual(self.queue.get(running['jobId'])['status'], 'interrupted')
        self.assertTrue(self.queue.get(running['jobId'])['canRetry'])

    def test_lease_rejects_second_worker(self):
        self.queue.start()
        other = jq.DurableJobQueue(self.queue.db_path)
        with self.assertRaises(RuntimeError): other.start()
        self.assertFalse(other.status()['worker'])

    def test_overdue_keeps_lane_until_actual_return(self):
        started, release, next_started = threading.Event(), threading.Event(), threading.Event()
        clock = [100.0]
        self.queue.monotonic = lambda: clock[0]
        def slow(context, params):
            started.set()
            release.wait(2)
            context.check()
            next_started.set()  # 期限後不得到達此處。
        self.queue.register('slow', slow, timeout=1)
        self.queue.register('next', lambda context, params: next_started.set())
        first = self.queue.submit_registered('slow')['job']
        self.queue.start()
        self.assertTrue(started.wait(1))
        clock[0] += 2
        self.queue.submit_registered('next')
        self.assertTrue(self.queue.get(first['jobId'])['overdue'])
        self.assertFalse(next_started.wait(.05))
        with self.assertRaises(ValueError): self.queue.retry(first['jobId'])
        release.set()
        wait_for(lambda: self.queue.get(first['jobId'])['status'] == 'timed_out')
        self.assertTrue(next_started.wait(1))

    def test_terminal_storage_failure_never_reexecutes_source(self):
        runs = []
        self.queue.register('test', lambda context, params: runs.append(1))
        first = self.queue.submit_registered('test')['job']
        original = self.queue._finish
        failures = [0]
        def finish(*args):
            if failures[0] == 0:
                failures[0] += 1
                raise jq.sqlite3.OperationalError('合成儲存失敗')
            return original(*args)
        with patch.object(self.queue, '_finish', side_effect=finish):
            self.queue.start()
            wait_for(lambda: self.queue.get(first['jobId'])['status'] == 'succeeded')
        self.assertEqual(runs, [1])

    def test_stop_retains_lease_until_noncooperative_source_returns(self):
        started, release = threading.Event(), threading.Event()
        def source(context, params): started.set(); release.wait(2); context.check()
        self.queue.register('test', source)
        job = self.queue.submit_registered('test')['job']
        self.queue.start()
        self.assertTrue(started.wait(1))
        self.assertFalse(self.queue.stop(timeout=.01))
        other = jq.DurableJobQueue(self.queue.db_path)
        with self.assertRaises(RuntimeError): other.start()
        release.set()
        wait_for(lambda: not self.queue.status()['worker'])
        self.assertEqual(self.queue.get(job['jobId'])['status'], 'interrupted')

    def test_existing_tables_remain_untouched(self):
        with closing(self.queue._connect()) as conn, conn:
            conn.execute('CREATE TABLE original(value TEXT)')
            conn.execute("INSERT INTO original VALUES('原資料')")
        self.queue.submit_registered('test')
        self.queue.start()
        wait_for(lambda: self.queue.status()['jobs'][0]['status'] == 'succeeded')
        with closing(self.queue._connect()) as conn:
            self.assertEqual(conn.execute('SELECT value FROM original').fetchone()[0], '原資料')

    def test_legacy_callbacks_do_not_replace_each_other(self):
        values = []
        self.queue.submit_callable('legacy', lambda: values.append(1), coalesce=False)
        self.queue.submit_callable('legacy', lambda: values.append(2), coalesce=False)
        # 同一程序接受的 callback 在啟動前仍有可恢復函式。
        self.queue.start()
        # 啟動重建刻意中止未持久化的 callback；之後的新工作才可執行。
        self.assertEqual(values, [])
        self.queue.submit_callable('legacy', lambda: values.append(3), coalesce=False)
        self.queue.submit_callable('legacy', lambda: values.append(4), coalesce=False)
        wait_for(lambda: len(values) == 2)
        self.assertEqual(values, [3, 4])


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pulse = PulseUpdates(Path(self.tmp.name) / 'jobs.db', Path(self.tmp.name) / 'trace.jsonl')
        self.queue = jq.DurableJobQueue(self.pulse.db_path)
        self.service = UpdateCoordinator(self.pulse, self.queue)

    def tearDown(self):
        self.queue.stop()
        self.tmp.cleanup()

    def test_read_neither_creates_db_nor_jobs(self):
        self.assertEqual(self.service.status()['jobs'], [])
        self.assertFalse(Path(self.pulse.db_path).exists())

    def test_market_uses_original_pulse_record_and_dedup(self):
        first = self.service.submit('pulse')
        second = self.service.submit('pulse')
        self.assertTrue(first['job']['jobId'].startswith('p-'))
        self.assertEqual(first['job']['jobId'], second['job']['jobId'])
        self.assertTrue(second['coalesced'])
        self.assertEqual(self.queue.status()['jobs'], [])
        self.assertEqual(len(self.pulse.status()['jobs']), 1)

    def test_options_only_enqueues_canonical_market_writer(self):
        import decision_context
        source = {'ok': True, 'status': 'fresh', 'observed': {'tradeDate': '2026-09-22'}}
        with patch.object(decision_context, 'latest_market_reference', return_value={'price': 100}), \
             patch.object(options, 'refresh', return_value=source) as refresh, \
             patch.object(decision_context, 'update_options_structure') as forbidden:
            first = self.service.submit('options')
            self.queue.start()
            wait_for(lambda: self.queue.get(first['job']['jobId'][2:])['status'] == 'succeeded')
            job = self.queue.get(first['job']['jobId'][2:])
            self.assertTrue(job['result']['marketJobId'].startswith('p-'))
            self.assertTrue(callable(refresh.call_args.kwargs['commit_guard']))
            forbidden.assert_not_called()

    def test_source_failure_does_not_publish_market(self):
        with patch.object(overnight, 'get_snapshot', return_value={'ok': False}):
            job = self.service.submit('research')['job']
            self.queue.start()
            wait_for(lambda: self.queue.get(job['jobId'][2:])['status'] == 'failed')
        self.assertEqual(self.pulse.status()['jobs'], [])

    def test_research_waits_for_older_market_job_before_linking_new_one(self):
        old = self.pulse.submit('old')['job']
        with closing(self.pulse._connect()) as conn, conn:
            conn.execute("UPDATE pulse_update_jobs_v1 SET status='running',started_at=? WHERE job_id=?",
                         (time.time() - 1, old['jobId']))
        with patch.object(overnight, 'get_snapshot', return_value={'ok': True, 'asOf': '2026-09-22'}):
            work = self.service.submit('research')['job']
            self.queue.start()
            wait_for(lambda: self.queue.get(work['jobId'][2:])['stage'] == '等待既有市場工作結束，再發布新來源')
            self.assertEqual(len(self.pulse.status()['jobs']), 1)
            with closing(self.pulse._connect()) as conn, conn:
                conn.execute("UPDATE pulse_update_jobs_v1 SET status='succeeded',finished_at=? WHERE job_id=?",
                             (time.time(), old['jobId']))
            wait_for(lambda: self.queue.get(work['jobId'][2:])['status'] == 'succeeded')
            linked = self.queue.get(work['jobId'][2:])['result']['marketJobId']
            self.assertNotEqual(linked, 'p-' + old['jobId'])
            self.assertEqual(len(self.pulse.status()['jobs']), 2)

    def test_parameters_fail_closed(self):
        invalid = [('pulse', {'force': True}), ('options', {'force': 'yes'}),
                   ('options', {'expiry': '../secret'}), ('research', {'market': 'JP'}),
                   ('legacy:evil', {}), ('pulse', []), ('research', {'path': 'x'})]
        for kind, params in invalid:
            with self.subTest(kind=kind, params=params), self.assertRaises(ValueError):
                self.service.submit(kind, params)
        self.assertFalse(Path(self.pulse.db_path).exists())

    def test_reader_and_unknown_role_cannot_submit(self):
        class Handler(UpdateRoutesMixin):
            def __init__(self, role): self.headers, self.error = {'X-ST-Gateway-Role': role}, None
            def _err(self, message, status): self.error = status
        for role in ('reader', 'untrusted'):
            handler = Handler(role)
            handler._handle_updates_post()
            self.assertEqual(handler.error, 403)
        self.assertTrue(Handler('owner')._update_capabilities()['canSubmit'])
        self.assertFalse(Path(self.pulse.db_path).exists())

    def test_market_retry_lineage_uses_persisted_reason(self):
        job = self.service.submit('pulse')['job']
        with closing(self.pulse._connect()) as conn, conn:
            conn.execute("UPDATE pulse_update_jobs_v1 SET status='failed' WHERE job_id=?", (job['jobId'][2:],))
        retried = self.service.retry(job['jobId'])['job']
        self.assertEqual(retried['parentJobId'], job['jobId'])
        self.assertEqual(retried['attempt'], 2)
        self.assertEqual(self.service.status()['jobs'][0]['parentJobId'], job['jobId'])


class SourceGuardTests(unittest.TestCase):
    def test_options_expired_fetch_never_persists(self):
        expired = [False]
        def guard():
            if expired[0]: raise jq.JobExpired('合成逾時')
        def fetch(*args, **kwargs): expired[0] = True; return []
        with patch.object(options, 'latest_cached', return_value=None), \
             patch.object(options, '_record_history') as history, patch.object(options, '_write_disk_cache') as disk:
            with self.assertRaises(jq.JobExpired):
                options.refresh(spot=100, spot_as_of=None, force=True, fetcher=fetch, commit_guard=guard)
            history.assert_not_called()
            disk.assert_not_called()

    def test_options_disk_expiry_before_replace_preserves_old_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'cache.json'
            path.write_text('{"old":true}', encoding='utf-8')
            calls = [0]
            def guard():
                calls[0] += 1
                if calls[0] == 2: raise jq.JobExpired('合成逾時')
            with patch.object(options, 'CACHE_PATH', str(path)), self.assertRaises(jq.JobExpired):
                options._write_disk_cache({'new': True}, commit_guard=guard)
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertFalse(Path(str(path) + '.tmp').exists())

    def test_history_expiry_before_replace_preserves_old_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            path.write_text('{"rows":[]}', encoding='utf-8')
            calls = [0]
            def guard():
                calls[0] += 1
                if calls[0] == 2: raise jq.JobExpired('合成逾時')
            with patch.object(options, 'HISTORY_PATH', str(path)), self.assertRaises(jq.JobExpired):
                options._write_history_rows([{'new': True}], commit_guard=guard)
            self.assertEqual(json.loads(path.read_text()), {'rows': []})
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_overnight_expired_build_preserves_memory_cache(self):
        expired = [False]
        def guard():
            if expired[0]: raise jq.JobExpired('合成逾時')
        def build(*args, **kwargs): expired[0] = True; return {'ok': True, 'new': True}
        prior = (0, {'ok': True, 'old': True})
        with patch.dict(overnight._CACHE, {'TW,US': prior}, clear=True), \
             patch.object(overnight, 'build_snapshot', side_effect=build), self.assertRaises(jq.JobExpired):
            try:
                overnight.get_snapshot(force=True, commit_guard=guard)
            finally:
                self.assertEqual(overnight._CACHE['TW,US'], prior)


if __name__ == '__main__':
    unittest.main()

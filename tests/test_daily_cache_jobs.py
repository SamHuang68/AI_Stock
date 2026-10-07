"""選定標的更新的取消、限額、快取及資料寫入邊界。"""
import json
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore as ds
import daily_cache_jobs as jobs
import 台股日線 as daily


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 11, 20, tzinfo=daily.TZ).astimezone(tz or timezone.utc)


class DailyCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(ds, 'DB_PATH', str(Path(self.temp.name) / 'market.db'))
        self.patch.start()
        ds.init_db()
        self.old_active, self.old_cancel = jobs._active, jobs._cancel
        jobs._active = None
        self.callbacks = []
        self.queue = patch.object(jobs.job_queue, 'submit', side_effect=lambda name, fn: self.callbacks.append(fn) or {'ok': True})
        self.queue.start()
        original_cutoff = ds.completed_daily_cutoff
        self.clock = patch.object(ds, 'completed_daily_cutoff',
                                  side_effect=lambda market, **kwargs: original_cutoff(market, now=Clock.now()))
        self.clock.start()

    def tearDown(self):
        jobs._active, jobs._cancel = self.old_active, self.old_cancel
        self.clock.stop(); self.queue.stop(); self.patch.stop(); self.temp.cleanup()

    def submit(self, **kwargs):
        return jobs.submit({'symbols': [{'symbol': '2330', 'market': 'TW'}], 'range': '1y', **kwargs})

    def test_scope_requires_explicit_symbols_and_supported_market(self):
        for body in ({}, {'symbols': []}, {'symbols': [{}] * 6}, {'symbols': [{'symbol': '2330', 'market': 'CN'}]},
                     {'symbols': [{'symbol': 'AAPL', 'market': 'US'}], 'kind': 'official'}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                jobs.submit(body)
        self.assertEqual(jobs.status()['status'], 'idle')

    def test_queue_coalesces_and_cancel_before_start_does_not_fetch(self):
        queued = self.submit()
        self.assertEqual(queued['status'], 'queued')
        self.assertFalse(self.submit()['ok'])
        jobs.cancel(queued['jobId'])
        with patch.object(ds, 'fetch_yahoo_daily') as fetch:
            self.callbacks[0]()
        fetch.assert_not_called()
        self.assertEqual(jobs.status()['status'], 'cancelled')
        with self.assertRaises(ValueError): jobs.cancel('other-job')

    def test_cancel_during_fetch_discards_pending_write(self):
        queued = self.submit()
        def fetch(*args, **kwargs):
            jobs.cancel(queued['jobId'])
            return [(daily.stamp(Clock.now().date()), 100, 102, 99, 101, 1000)]
        with patch.object(ds, 'fetch_yahoo_daily', side_effect=fetch): self.callbacks[0]()
        self.assertEqual(ds.get_bars('2330'), [])
        self.assertEqual(jobs.status()['status'], 'cancelled')

    def test_queued_cancellation_is_immediate_and_old_callback_cannot_touch_new_job(self):
        first = self.submit()
        jobs.cancel(first['jobId'])
        self.assertEqual(jobs.status()['status'], 'cancelled')
        second = self.submit()
        self.assertNotEqual(second['jobId'], first['jobId'])
        with patch.object(ds, 'fetch_yahoo_daily') as fetch:
            self.callbacks[0]()
        fetch.assert_not_called()
        self.assertEqual(jobs.status()['jobId'], second['jobId'])
        self.assertEqual(jobs.status()['status'], 'queued')
        row = (daily.stamp(Clock.now().date()), 100, 102, 99, 101, 1000)
        with patch.object(ds, 'fetch_yahoo_daily', return_value=[row]): self.callbacks[1]()
        self.assertEqual(jobs.status()['status'], 'completed')
        self.assertEqual(jobs.status()['completed'], 1)

    def test_running_cancel_remains_busy_until_worker_finalizes(self):
        queued = self.submit()
        def fetch(*args, **kwargs):
            jobs.cancel(queued['jobId'])
            self.assertEqual(jobs.status()['status'], 'cancelling')
            self.assertFalse(self.submit()['ok'])
            return [(daily.stamp(Clock.now().date()), 100, 102, 99, 101, 1000)]
        with patch.object(ds, 'fetch_yahoo_daily', side_effect=fetch): self.callbacks[0]()
        self.assertEqual(jobs.status()['status'], 'cancelled')

    def test_two_endpoints_without_query_coverage_must_fetch_entire_range(self):
        ds.upsert_bars('2330', 'TW', [(daily.stamp(Clock(2025, 1, 1).date()), 100, 102, 99, 101, 1000),
                                    (daily.stamp(Clock.now().date()), 100, 102, 99, 101, 1000)])
        self.submit()
        with patch.object(ds, 'fetch_yahoo_daily', return_value=ds.get_bars('2330')) as fetch: self.callbacks[0]()
        fetch.assert_called_once()
        self.assertLess(fetch.call_args.kwargs['start_ts'], daily.stamp(Clock(2025, 9, 11).date()))
        self.assertEqual(jobs.status()['status'], 'completed')
        self.submit()
        with patch.object(ds, 'fetch_yahoo_daily') as fetch: self.callbacks[-1]()
        fetch.assert_not_called()
        self.assertTrue(jobs.status()['results'][0]['reused'])

    def test_only_completed_dates_saved_and_revisions_preserved(self):
        old = (daily.stamp(Clock(2026, 9, 10).date()), 100, 102, 99, 101, 1000)
        ds.upsert_bars('2330', 'TW', [old])
        rows = [(old[0], 200, 202, 199, 201, 1000),
                (daily.stamp(Clock(2026, 9, 11).date()), 100, 102, 99, 101, 1000),
                (daily.stamp(Clock(2026, 9, 14).date()), 100, 102, 99, 101, 1000)]
        self.submit()
        with patch.object(ds, 'fetch_yahoo_daily', return_value=rows): self.callbacks[0]()
        self.assertEqual(jobs.status()['status'], 'completed')
        self.assertEqual(ds.get_bars('2330')[0], old)
        self.assertEqual(len(ds.get_bars('2330')), 2)
        self.assertEqual(jobs.status()['results'][0]['conflicts'], 1)

    def test_null_is_preserved_and_not_replaced_with_zero(self):
        self.submit()
        row = (daily.stamp(Clock.now().date()), None, None, None, 100, None)
        with patch.object(ds, 'fetch_yahoo_daily', return_value=[row]): self.callbacks[0]()
        self.assertEqual(ds.get_bars('2330'), [row])

    def test_later_start_coverage_cannot_shorten_requested_history(self):
        with closing(ds.get_conn()) as conn, conn:
            conn.execute('INSERT INTO bar_fetch_coverage VALUES(?,?,?,?,?,?)',
                         ('TW', '2330', 'Yahoo Finance', '2026-01-01', '2026-09-10', 1))
        self.submit()
        row = (daily.stamp(Clock.now().date()), 100, 102, 99, 101, 1000)
        with patch.object(ds, 'fetch_yahoo_daily', return_value=[row]) as fetch:
            self.callbacks[0]()
        requested = datetime.fromtimestamp(fetch.call_args.kwargs['start_ts'], daily.TZ)
        self.assertEqual(requested.isoformat(), '2025-09-10T00:00:00+08:00')
        self.assertEqual(jobs.status()['results'][0]['queryCoverage'], ['2025-09-10', '2026-09-11'])
        self.assertIn('不保證', jobs.status()['results'][0]['coverageMeaning'])

    def test_covered_start_and_overlapping_fetch_form_continuous_query_range(self):
        with closing(ds.get_conn()) as conn, conn:
            conn.execute('INSERT INTO bar_fetch_coverage VALUES(?,?,?,?,?,?)',
                         ('TW', '2330', 'Yahoo Finance', '2025-09-01', '2026-08-31', 1))
        self.submit()
        row = (daily.stamp(Clock.now().date()), 100, 102, 99, 101, 1000)
        with patch.object(ds, 'fetch_yahoo_daily', return_value=[row]) as fetch:
            self.callbacks[0]()
        requested = datetime.fromtimestamp(fetch.call_args.kwargs['start_ts'], daily.TZ)
        self.assertEqual(requested.isoformat(), '2026-08-24T00:00:00+08:00')
        self.assertEqual(jobs.status()['results'][0]['queryCoverage'], ['2025-09-10', '2026-09-11'])
        self.assertEqual(jobs.status()['results'][0]['inserted'], 1)

    def test_status_is_a_copy_and_limit_precedes_any_network(self):
        self.submit()
        external = jobs.status(); external['symbols'].clear()
        self.assertEqual(len(jobs.status()['symbols']), 1)
        budget = jobs.Budget(threading.Event(), requests=0)
        with patch.object(jobs, 'urlopen') as request, self.assertRaises(RuntimeError): budget.get_json('https://example.invalid')
        request.assert_not_called()
        expired = jobs.Budget(threading.Event(), seconds=0)
        with self.assertRaises(TimeoutError): expired.check()

    def test_official_cancel_precedes_any_migration_or_write(self):
        before = Path(ds.DB_PATH).read_bytes()
        def stop(): raise jobs.Cancelled('測試取消')
        with self.assertRaises(jobs.Cancelled), patch.object(daily, 'get_json') as fetch:
            daily.seed_research(Path(ds.DB_PATH), check=stop)
        fetch.assert_not_called()
        self.assertEqual(Path(ds.DB_PATH).read_bytes(), before)

    def test_cancel_waiting_for_write_lock_discards_history_batch(self):
        queued = self.submit()
        fetched = threading.Event()
        def fetch(*args, **kwargs):
            fetched.set()
            return [(daily.stamp(Clock.now().date()), 100, 102, 99, 101, 1000)]
        # 初始化在工作開始先執行，測試直接卡住 fetch 後的寫入鎖。
        with patch.object(ds, 'init_db'), patch.object(ds, 'fetch_yahoo_daily', side_effect=fetch):
            ds._db_write_lock.acquire()
            worker = threading.Thread(target=self.callbacks[0])
            try:
                worker.start(); self.assertTrue(fetched.wait(2)); jobs.cancel(queued['jobId'])
            finally:
                ds._db_write_lock.release(); worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(ds.get_bars('2330'), [])
        self.assertEqual(jobs.status()['status'], 'cancelled')

    def test_official_month_cancellation_rolls_back_all_rows_and_observations(self):
        calls = 0
        def stop_mid_batch():
            nonlocal calls
            calls += 1
            if calls == 4: raise jobs.Cancelled('月批次取消')
        rows = [(daily.stamp(Clock(2026, 9, d).date()), 100, 102, 99, 101, 1000) for d in (9, 10, 11)]
        with self.assertRaises(jobs.Cancelled): ds.upsert_bars('2330', 'TW', rows, source='TWSE', check=stop_mid_batch)
        self.assertEqual(ds.get_bars('2330'), [])
        with ds.read_snapshot() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM official_daily_observations').fetchone()[0], 0)


if __name__ == '__main__': unittest.main()

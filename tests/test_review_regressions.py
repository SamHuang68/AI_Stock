"""A–M 的離線邊界回歸；只使用暫存資料與假造來源。"""
import gzip
import io
import json
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import http_client as hc
import options_schedule as sched
import datastore as ds
import pulse_history as ph
import daily_cache_jobs as jobs
try:
    import private_web_gateway as gateway
except ModuleNotFoundError as error:
    if error.name != 'private_web_gateway':
        raise
    gateway = None  # 單機分享包刻意不含 Private Web；只略過其專屬案例。
import datasources


class ReviewRegressions(unittest.TestCase):
    def test_long_holiday_and_unknown_previous_year(self):
        self.assertEqual(sched.previous_session('2026-02-23'), '2026-02-11')
        self.assertEqual(sched.previous_session('2026-10-05'), '2026-10-02')
        self.assertIsNone(sched.previous_session('2026-01-02'))
        self.assertIsNone(sched.previous_session('2031-01-06'))

    def test_restart_reads_receipt_before_resubmission(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                mock.patch.object(sched.options_exposure, 'latest_cached', return_value=None):
            Path(tmp, 'options_daily_schedule.json').write_text('{"enabled":true}', encoding='utf-8')
            now = datetime(2026, 2, 23, 7, 10, tzinfo=ZoneInfo('Asia/Taipei'))
            def submit(*args):
                receipt = json.loads(Path(tmp, 'options_daily_attempts.json').read_text(encoding='utf-8'))
                self.assertEqual(receipt['2026-02-23/420']['status'], 'reserved')
            self.assertTrue(sched.tick(now, submit))
            with mock.patch.object(sched, '_thread', None):
                self.assertFalse(sched.tick(now, mock.Mock(side_effect=AssertionError('不得重排'))))

    def response(self, body, headers):
        response = mock.Mock(status=200)
        response.length = None
        response.read.return_value = body
        response.getheaders.return_value = headers
        conn = mock.Mock(sock=None)
        conn.getresponse.return_value = response
        pool = mock.MagicMock()
        pool._idle = []
        pool.acquire.return_value = conn
        return conn, pool

    def framed_response(self, body, headers, *, method='GET', status=200):
        wire = f'HTTP/1.1 {status} test\r\n'.encode('ascii')
        wire += b''.join(f'{key}: {value}\r\n'.encode('ascii') for key, value in headers)
        wire += b'\r\n' + body
        sock = mock.Mock()
        sock.makefile.return_value = io.BytesIO(wire)
        response = hc.http.client.HTTPResponse(sock, method=method)
        response.begin()
        self.addCleanup(response.close)
        conn, pool = self.response(b'', [])
        conn.sock = sock
        conn.getresponse.return_value = response
        return conn, pool

    def test_deadline_rejects_short_content_length_valid_json_no_retry(self):
        body = b'{}'
        self.assertEqual(json.loads(body), {})
        for deadline in (None, 5):
            with self.subTest(deadline=deadline):
                conn, pool = self.framed_response(body, [('Content-Length', '10')])
                client = hc.HttpClient()
                with mock.patch.object(client, '_pool', return_value=pool), \
                        mock.patch.object(hc.time, 'monotonic', return_value=0):
                    with self.assertRaises(hc.HttpError) as caught:
                        client.get_json('http://offline.test/', retries=0, deadline=deadline)
                self.assertIsInstance(caught.exception.cause, hc.http.client.IncompleteRead)
                self.assertEqual(caught.exception.cause.partial, body)
                self.assertEqual(caught.exception.cause.expected, 8)
                pool.release.assert_called_once_with(conn, reuse=False)

    def test_deadline_retries_short_content_length(self):
        short, pool = self.framed_response(b'{}', [('Content-Length', '10')])
        complete, _ = self.framed_response(b'{}', [('Content-Length', '2')])
        pool.acquire.side_effect = [short, complete]
        client = hc.HttpClient()
        with mock.patch.object(client, '_pool', return_value=pool), \
                mock.patch.object(hc.time, 'monotonic', return_value=0), \
                mock.patch.object(hc.time, 'sleep') as sleep:
            self.assertEqual(client.get_json('http://offline.test/', retries=1, deadline=5), {})
        self.assertEqual(pool.acquire.call_count, 2)
        self.assertEqual(pool.release.call_args_list, [mock.call(short, reuse=False), mock.call(complete, reuse=True)])
        self.assertEqual(client.stats()['retries'], 1)
        sleep.assert_called_once_with(.5)

    def test_deadline_rejects_truncated_chunked_payload(self):
        conn, pool = self.framed_response(b'A\r\n{}', [('Transfer-Encoding', 'chunked')])
        client = hc.HttpClient()
        with mock.patch.object(client, '_pool', return_value=pool), \
                mock.patch.object(hc.time, 'monotonic', return_value=0):
            with self.assertRaises(hc.HttpError) as caught:
                client.request('GET', 'http://offline.test/', retries=0, deadline=5)
        self.assertIsInstance(caught.exception.cause, hc.http.client.IncompleteRead)
        pool.release.assert_called_once_with(conn, reuse=False)

    def test_deadline_accepts_complete_or_bodyless_framing(self):
        cases = [
            ('GET', 200, [('Content-Length', '2')], b'{}', b'{}'),
            ('GET', 200, [('Content-Length', '0')], b'', b''),
            ('HEAD', 200, [('Content-Length', '10')], b'', b''),
            ('GET', 204, [('Content-Length', '10')], b'', b''),
            ('GET', 304, [('Content-Length', '10')], b'', b''),
            ('GET', 200, [('Connection', 'close')], b'{}', b'{}'),
            ('GET', 200, [('Transfer-Encoding', 'chunked')], b'2\r\n{}\r\n0\r\n\r\n', b'{}'),
        ]
        for method, status, headers, body, expected in cases:
            with self.subTest(method=method, status=status, headers=headers):
                conn, pool = self.framed_response(body, headers, method=method, status=status)
                client = hc.HttpClient()
                with mock.patch.object(client, '_pool', return_value=pool), \
                        mock.patch.object(hc.time, 'monotonic', return_value=0):
                    result = client.request(method, 'http://offline.test/', retries=0, deadline=5)
                self.assertEqual(result.status, status)
                self.assertEqual(result.body, expected)
                pool.release.assert_called_once_with(conn, reuse=('Connection', 'close') not in headers)

    def test_unsolicited_gzip_preserves_body_and_headers(self):
        packed = gzip.compress(b'{"ok":true}')
        conn, pool = self.response(packed, [('Content-Encoding', 'gzip'), ('Content-Length', str(len(packed)))])
        client = hc.HttpClient()
        with mock.patch.object(client, '_pool', return_value=pool):
            result = client.request('GET', 'http://offline.test/', retries=0)
        self.assertEqual(result.body, packed)
        self.assertEqual(result.headers['Content-Encoding'], 'gzip')
        self.assertEqual(result.headers['Content-Length'], str(len(packed)))

    def test_requested_gzip_returns_consistent_body_and_length(self):
        raw = b'{"ok":true}'
        packed = gzip.compress(raw)
        conn, pool = self.response(packed, [('Content-Encoding', 'gzip'), ('Content-Length', str(len(packed)))])
        client = hc.HttpClient()
        with mock.patch.object(client, '_pool', return_value=pool):
            result = client.request('GET', 'http://offline.test/', headers={'Accept-Encoding': 'gzip'}, retries=0)
        self.assertEqual(result.body, raw)
        self.assertNotIn('Content-Encoding', result.headers)
        self.assertEqual(result.headers['Content-Length'], str(len(raw)))

    def test_reused_socket_timeout_tracks_both_directions(self):
        pool = hc._HostPool('http', 'offline.test', 80)
        conn = mock.Mock()
        for timeout in (30, 8, 30):
            pool._idle = [(conn, time.time())]
            self.assertIs(pool.acquire(timeout), conn)
            self.assertEqual(conn.timeout, timeout)
            conn.sock.settimeout.assert_called_with(timeout)

    def test_no_deadline_preserves_none_and_zero_timeout(self):
        for timeout in (None, 0):
            with self.subTest(timeout=timeout):
                conn, pool = self.response(b'[]', [])
                client = hc.HttpClient()
                with mock.patch.object(client, '_pool', return_value=pool):
                    self.assertEqual(client.get_json('http://offline.test/', timeout=timeout, retries=0), [])
                pool.acquire.assert_called_once_with(timeout)

    def test_deadline_does_not_allow_retry_past_budget(self):
        conn, pool = self.response(b'[]', [])
        clock = [0.0]
        def fail():
            clock[0] += 8
            raise TimeoutError('首試用盡預算')
        conn.getresponse.side_effect = fail
        client = hc.HttpClient()
        with mock.patch.object(client, '_pool', return_value=pool), \
                mock.patch.object(hc, 'time', types.SimpleNamespace(monotonic=lambda: clock[0], sleep=mock.Mock(), time=time.time)) as fake_time:
            with self.assertRaises(hc.HttpError):
                client.get_json('http://offline.test/', timeout=8, retries=1, deadline=8.5)
        self.assertEqual(conn.getresponse.call_count, 1)
        self.assertEqual(pool.acquire.call_args_list[0].args[0], 8)
        fake_time.sleep.assert_not_called()

    def test_deadline_clamps_second_attempt_and_rejects_late_success(self):
        conn, pool = self.response(b'[]', [])
        clock = [0.0]
        response = conn.getresponse.return_value
        def response_step():
            if conn.getresponse.call_count == 1:
                clock[0] = 6
                raise ConnectionResetError('首試中斷')
            clock[0] = 9
            return response
        conn.getresponse.side_effect = response_step
        client = hc.HttpClient()
        with mock.patch.object(client, '_pool', return_value=pool), \
                mock.patch.object(hc, 'time', types.SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda delay: clock.__setitem__(0, clock[0] + delay), time=time.time)):
            with self.assertRaises(hc.HttpError):
                client.get_json('http://offline.test/', timeout=8, retries=1, deadline=8.5)
        self.assertEqual(pool.acquire.call_args_list[-1].args[0], 2)

    @unittest.skipUnless(gateway is not None, '單機分享包不包含 Private Web gateway')
    def test_reader_cannot_read_private_alerts_but_owner_can(self):
        settings = types.SimpleNamespace(extra_read_paths=('/alert/status', '/watch/status'), extra_control_paths=())
        for path in ('/alert/status', '/watch/status'):
            self.assertFalse(gateway.route_permission('GET', path, 'reader', settings))
            self.assertTrue(gateway.route_permission('GET', path, 'owner', settings))

    def test_queue_refusal_is_terminal_and_next_submission_is_allowed(self):
        body = {'symbols': [{'symbol': '2330', 'market': 'TW'}], 'range': '1y'}
        with mock.patch.object(jobs, '_active', None), mock.patch.object(jobs, '_cancel', None), \
                mock.patch.object(jobs.job_queue, 'submit', side_effect=jobs.job_queue.QueueFull('佇列已滿')):
            result = jobs.submit(body)
            self.assertFalse(result['ok'])
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['reason'], 'queue_full')
            with mock.patch.object(jobs.job_queue, 'submit', return_value={'ok': True}):
                self.assertTrue(jobs.submit(body)['ok'])

    def test_all_daily_ingest_paths_exclude_incomplete_today(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')):
            ds.init_db()
            today = datetime(2026, 10, 8, 12, tzinfo=ZoneInfo('Asia/Taipei'))
            row = (int(today.replace(hour=9).timestamp()), 100, 101, 99, 100, 20)
            original = ds.completed_daily_rows
            with mock.patch.object(ds, 'completed_daily_rows', side_effect=lambda rows, market, **kw: original(rows, market, **kw, now=today)):
                self.assertEqual(ds.upsert_bars('2330', 'TW', [row]), 0)
                with mock.patch.object(ds, 'fetch_yahoo_daily', return_value=[row]):
                    self.assertEqual(ds.backfill('2330'), 0)
                    self.assertEqual(ds.update('2330'), 0)
                self.assertEqual(ds.get_bars('2330'), [])
            after_close = today.replace(hour=18)
            with mock.patch.object(ds, 'completed_daily_rows', side_effect=lambda rows, market, **kw: original(rows, market, **kw, now=after_close)):
                self.assertEqual(ds.upsert_bars('2330', 'TW', [row], source='Yahoo Finance'), 1)
            self.assertEqual(ds.source_revision_status('2330')['count'], 0)

    def test_margin_derived_series_keeps_observation_date_without_bypassing_equity_cutoff(self):
        now = datetime(2026, 10, 8, 12, tzinfo=ZoneInfo('Asia/Taipei'))
        row = (int(now.replace(hour=0).timestamp()), 150, 150, 150, 150, 0)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')):
            ds.init_db()
            original = ds.completed_daily_rows
            with mock.patch.object(ds, 'completed_daily_rows',
                                   side_effect=lambda rows, market, **kw: original(rows, market, now=now, **kw)):
                self.assertEqual(ds.upsert_bars('__MARGIN_RATIO__', 'TW', [row]), 1)
                self.assertEqual(ds.upsert_bars('2330', 'TW', [row]), 0)
                self.assertEqual(ds.upsert_bars('__UNRECOGNIZED__', 'TW', [row]), 0)
            with ds.read_snapshot() as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM bars WHERE symbol=?', ('__MARGIN_RATIO__',)).fetchone()[0], 1)
        us_row = (int(now.astimezone(ZoneInfo('America/New_York')).replace(hour=9).timestamp()), *row[1:])
        self.assertEqual(ds.completed_daily_rows([us_row], 'US', now=now, symbol='__MARGIN_RATIO__'), [])

    def test_history_reads_remain_available_during_blocked_fetch(self):
        entered, release = threading.Event(), threading.Event()
        def fetch(*args):
            entered.set()
            if not release.wait(3): raise TimeoutError('測試來源未釋放')
            return [], '離線測試'
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ph, 'DB_PATH', str(Path(tmp) / 'pulse.db')), \
                mock.patch.object(ph, 'fetch_index_series', side_effect=fetch), \
                mock.patch.object(ph, 'fetch_breadth_day', return_value=None), \
                mock.patch.object(ph, 'fetch_inst_day', return_value=None):
            ph.init_db()
            worker = threading.Thread(target=lambda: ph.sync(days=0))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                self.assertTrue(ph.status()['running'])
                self.assertTrue(ph.history()['ok'])
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertFalse(ph.sync(days=0)['ok'])
            finally:
                release.set(); worker.join(3)
            self.assertFalse(worker.is_alive())

    def test_db_refresh_requires_explicit_scope_and_uses_existing_job(self):
        with mock.patch.object(datasources, '_spawn', side_effect=AssertionError('不得啟動缺參數 CLI')), \
                mock.patch.object(jobs, 'submit', return_value={'ok': True, 'status': 'queued'}) as submit:
            self.assertFalse(datasources.refresh('db')['ok'])
            symbols = [{'symbol': '2330', 'market': 'TW'}]
            self.assertEqual(datasources.refresh('db', symbols=symbols)['status'], 'queued')
            submit.assert_called_once_with({'symbols': symbols, 'range': '1mo', 'kind': 'history'})

    def test_deadline_allows_slow_successful_gzip_body(self):
        raw = b'{"ok":true}'
        packed = gzip.compress(raw)
        conn, pool = self.response(packed, [('Content-Encoding', 'gzip')])
        clock = [0.0]
        chunks = iter([packed[:10], packed[10:], b''])
        def read(size):
            clock[0] += 2
            return next(chunks)
        conn.getresponse.return_value.read1.side_effect = read
        client = hc.HttpClient()
        with mock.patch.object(client, '_pool', return_value=pool), \
                mock.patch.object(hc, 'time', types.SimpleNamespace(monotonic=lambda: clock[0], sleep=time.sleep, time=time.time)):
            result = client.request('GET', 'http://offline.test/', headers={'Accept-Encoding': 'gzip'},
                                    timeout=8, retries=1, deadline=8.5)
        self.assertEqual(result.body, raw)
        self.assertNotIn('Content-Encoding', result.headers)
        self.assertEqual(conn.getresponse.call_count, 1)
        self.assertEqual(clock[0], 6)

    def test_bad_idle_socket_does_not_consume_request_retry(self):
        pool = hc._HostPool('http', 'offline.test', 80)
        bad, good = mock.Mock(), mock.Mock()
        bad.sock.settimeout.side_effect = OSError('閒置連線已關閉')
        pool._idle = [(good, time.time()), (bad, time.time())]
        self.assertIs(pool.acquire(8), good)
        bad.close.assert_called_once()

    def test_history_read_uri_preserves_special_path_characters(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ph, 'DB_PATH', str(Path(tmp) / 'pulse#%20.db')):
            ph.init_db()
            self.assertTrue(ph.history()['ok'])
            self.assertIn('running', ph.status())

    def test_source_ingest_counts_excluded_today(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')):
            ds.init_db()
            now = datetime(2026, 10, 8, 12, tzinfo=ZoneInfo('Asia/Taipei'))
            row = (int(now.timestamp()), 100, 101, 99, 100, 20)
            original = ds.completed_daily_rows
            with mock.patch.object(ds, 'completed_daily_rows', side_effect=lambda rows, market, **kw: original(rows, market, **kw, now=now)):
                self.assertEqual(ds.upsert_bars('2330', 'TW', [row], source='Yahoo Finance'), 0)
            with ds.read_snapshot() as conn:
                payload = json.loads(conn.execute('SELECT payload FROM bar_ingest_runs').fetchone()[0])
            self.assertEqual(payload['excluded'], 1)

    def test_movers_ignores_late_result_after_timeout_decision(self):
        from tests.test_server_http_security import ST
        threads = []
        class Worker:
            def __init__(self, target, **kwargs):
                self.target = target
                self.index = len(threads)
                threads.append(self)
            def start(self): pass
            def join(self, timeout): pass
            def is_alive(self):
                if self.index == 0: return True
                threads[0].target()
                self.target()
                return False
        rows = [{'Date': '1151006', 'Code': '2330', 'Name': '台積電',
                 'ClosingPrice': '1050', 'Change': '15', 'TradeValue': '50000000'}]
        with mock.patch.object(ST, 'threading', types.SimpleNamespace(Thread=Worker)), \
                mock.patch.object(hc, 'fetch_json', side_effect=lambda url, **kwargs: rows if 'STOCK_DAY_ALL' in url else []), \
                mock.patch.object(ST, '_get_tw_sectors', return_value={'2330': '半導體業'}), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            result = ST._fetch_day_movers(5)
        self.assertFalse(result['ok'])
        self.assertIn('TWSE', result['sourceErrors'])
        self.assertEqual(result['gainers'], [])

    def test_movers_bounds_sector_worker_and_does_not_adopt_late_classification(self):
        from tests.test_server_http_security import ST
        workers = []
        class Worker:
            def __init__(self, target, **kwargs):
                self.target = target
                self.index = len(workers)
                self.waits = []
                workers.append(self)
            def start(self):
                if self.index < 2: self.target()
            def join(self, timeout): self.waits.append(timeout)
            def is_alive(self): return self.index == 2
        rows = [{'Date': '1151006', 'Code': '2330', 'Name': '台積電',
                 'ClosingPrice': '1050', 'Change': '15', 'TradeValue': '50000000'}]
        with mock.patch.object(ST, 'threading', types.SimpleNamespace(Thread=Worker)), \
                mock.patch.object(hc, 'fetch_json', side_effect=lambda url, **kw: rows if 'STOCK_DAY_ALL' in url else []), \
                mock.patch.object(ST, '_get_tw_sectors', return_value={'2330': '半導體業'}) as sectors, \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            result = ST._fetch_day_movers(5, include_rows=True)
            self.assertTrue(result['ok'])
            self.assertIn('sectors', result['sourceErrors'])
            self.assertFalse(result['classificationComplete'])
            self.assertEqual(result['classificationCount'], 0)
            self.assertEqual(len(workers), 3)
            self.assertTrue(all(0 <= timeout <= 8.5 for w in workers for timeout in w.waits))
            workers[2].target()
            self.assertIn('deadline', sectors.call_args.kwargs)
            self.assertEqual(result['classificationCount'], 0)

    def test_sector_lookup_uses_shared_transport_and_deadline_including_lock(self):
        from tests.test_server_http_security import ST
        rows = [{'公司代號': '2330', '產業別': '半導體業'}]
        clock = [100.0]
        lock = threading.Lock()
        lock.acquire()
        with mock.patch.object(ST, '_openapi_locks', {'t187ap05_L': lock}):
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, '快取鎖'):
                ST._openapi_lookup_list('t187ap05_L', deadline=started + .02)
            self.assertLess(time.monotonic() - started, .2)
        lock.release()
        def fetch(method, url, **kw):
            self.assertEqual(method, 'GET')
            self.assertEqual(kw['headers']['Accept-Encoding'], 'gzip')
            self.assertEqual(kw['deadline'], 108.5)
            clock[0] = 109.0
            return hc.HttpResponse(200, {'Content-Type': 'application/json'}, json.dumps(rows).encode(), url)
        with mock.patch.object(ST, '_TW_SECTORS', {'date': None, 'map': {}}), \
                mock.patch.object(ST, '_openapi_ds', {}), mock.patch.object(ST, '_openapi_meta', {}), \
                mock.patch.object(ST, '_openapi_locks', {}), mock.patch.object(ST, '_fundamental_trace'), \
                mock.patch.object(ST, 'time', types.SimpleNamespace(monotonic=lambda: clock[0], strftime=lambda *a: 'fixture')), \
                mock.patch.object(hc, 'request', side_effect=fetch) as request, \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            with self.assertRaisesRegex(TimeoutError, '整體期限'):
                ST._get_tw_sectors(deadline=108.5)
            self.assertEqual(request.call_count, 1)

    def test_partial_sector_lookup_keeps_available_classification_and_error(self):
        from tests.test_server_http_security import ST
        cached = {'5347': '半導體業'}
        def lookup(dataset, **kwargs):
            ST._openapi_meta[dataset] = {'status': 'ok' if dataset.endswith('_L') else 'error'}
            return [{'公司代號': '2330', '產業別': '半導體業'}] if dataset.endswith('_L') else []
        with mock.patch.object(ST, '_TW_SECTORS', {'date': None, 'map': cached}), \
                mock.patch.object(ST, '_openapi_meta', {}), \
                mock.patch.object(ST, '_openapi_lookup_list', side_effect=lookup):
            with self.assertRaisesRegex(RuntimeError, '產業分類來源未完成') as caught:
                ST._get_tw_sectors(deadline=time.monotonic() + 8.5)
            self.assertEqual(caught.exception.partial_sectors, {'2330': '半導體業', '5347': '半導體業'})
            self.assertIsNone(ST._TW_SECTORS['date'])
        rows = [{'Date': '1151006', 'Code': '2330', 'Name': '台積電',
                 'ClosingPrice': '1050', 'Change': '15', 'TradeValue': '50000000'}]
        with mock.patch.object(hc, 'fetch_json', side_effect=lambda url, **kw: rows if 'STOCK_DAY_ALL' in url else []), \
                mock.patch.object(ST, '_get_tw_sectors', side_effect=caught.exception), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            result = ST._fetch_day_movers(5)
        self.assertEqual(result['gainers'][0]['industry'], '半導體業')
        self.assertIn('sectors', result['sourceErrors'])
        self.assertFalse(result['classificationComplete'])

    def test_sector_deadline_keeps_previous_cache_in_failure_snapshot(self):
        from tests.test_server_http_security import ST
        with mock.patch.object(ST, '_TW_SECTORS', {'date': None, 'map': {'2330': '半導體業'}}), \
                mock.patch.object(ST, '_openapi_lookup_list', side_effect=AssertionError('過期不得再抓取')):
            with self.assertRaises(TimeoutError) as caught:
                ST._get_tw_sectors(deadline=time.monotonic() - 1)
            self.assertEqual(caught.exception.partial_sectors, {'2330': '半導體業'})
            self.assertIsNone(ST._TW_SECTORS['date'])

    def test_existing_history_update_excludes_incomplete_today(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')):
            ds.init_db()
            now = datetime(2026, 10, 8, 12, tzinfo=ZoneInfo('Asia/Taipei'))
            old = (int(now.replace(day=7, hour=9).timestamp()), 100, 101, 99, 100, 20)
            today = (int(now.replace(hour=9).timestamp()), 101, 102, 100, 101, 10)
            ds.upsert_bars('2330', 'TW', [old])
            original = ds.completed_daily_rows
            with mock.patch.object(ds, 'completed_daily_rows', side_effect=lambda rows, market, **kw: original(rows, market, **kw, now=now)), \
                    mock.patch.object(ds, 'fetch_yahoo_daily', return_value=[today]), \
                    mock.patch.object(ds, 'backfill', side_effect=AssertionError('已有資料不得走首次回補')):
                self.assertEqual(ds.update('2330'), 0)
            self.assertEqual(ds.get_bars('2330'), [old])

    def test_completed_rows_keep_validation_and_market_calendar(self):
        now = datetime(2026, 10, 8, 14, 30, tzinfo=ZoneInfo('Asia/Taipei'))
        row = (int(now.replace(hour=9).timestamp()), 100, 101, 99, 100, 20)
        self.assertEqual(ds.completed_daily_rows([row], 'TW', now=now), [row])
        self.assertEqual(ds.completed_daily_rows([row], 'TW', now=now.replace(hour=13)), [])
        with self.assertRaises(ValueError):
            ds.completed_daily_rows([(float('nan'), 1, 2, 1, 2, 3)], 'TW', now=now)
        early = datetime(2026, 11, 27, 13, 30, tzinfo=ZoneInfo('America/New_York'))
        us_row = (int(early.replace(hour=9, minute=30).timestamp()), 100, 101, 99, 100, 20)
        self.assertEqual(ds.completed_daily_rows([us_row], 'US', now=early), [us_row])
        self.assertEqual(ds.completed_daily_rows([us_row], 'US', now=early.replace(minute=29)), [])

    def test_direct_official_storage_cannot_bypass_completed_day_gate(self):
        from datetime import date
        from daily_quality import store_official
        import sqlite3
        row = (int(datetime(2026, 10, 8, 9, tzinfo=ZoneInfo('Asia/Taipei')).timestamp()), 100, 102, 99, 101, 1000)
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'market.db'
            ds.init_db(database)
            with closing(sqlite3.connect(database)) as connection, connection, mock.patch.object(ds, 'completed_daily_cutoff', return_value=date(2026, 10, 7)):
                self.assertEqual(store_official(connection, '2330', 'TW', [row], 'TWSE', 'fixture'), 0)
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM bars').fetchone()[0], 0)
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM official_daily_observations').fetchone()[0], 0)
            with closing(sqlite3.connect(database)) as connection, connection, mock.patch.object(ds, 'completed_daily_cutoff', return_value=date(2026, 10, 8)):
                self.assertEqual(store_official(connection, '2330', 'TW', [row], 'TWSE', 'fixture'), 1)

    def test_official_import_does_not_record_incomplete_day_as_completed(self):
        from datetime import date
        import sqlite3
        import 台股日線 as daily
        records = [{'symbol': '2330', 'name': '台積電', 'prices': [100, 102, 99, 101], 'volume': 1000}]
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'market.db'
            ds.init_db(database)
            with mock.patch.object(ds, 'completed_daily_cutoff', return_value=date(2026, 10, 7)):
                with self.assertRaisesRegex(ValueError, '完成交易日'):
                    daily.import_day(database, 'TWSE', date(2026, 10, 8), records, 'fixture', min_rows=1)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM daily_imports').fetchone()[0], 0)
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM bars').fetchone()[0], 0)

    def test_load_bars_after_close_matches_persistence_cutoff(self):
        import stock_signals_routes as routes
        for hour, minute in ((14, 30), (18, 30)):
            with self.subTest(hour=hour), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                    mock.patch.object(routes, '_remote_fail', {}):
                ds.init_db()
                now = datetime(2026, 10, 8, hour, minute, tzinfo=ZoneInfo('Asia/Taipei'))
                row = (int(now.replace(hour=9, minute=0).timestamp()), 100, 101, 99, 100, 20)
                original = ds.completed_daily_rows
                with mock.patch.object(ds, 'completed_daily_rows', side_effect=lambda rows, market, **kw: original(rows, market, **kw, now=now)), \
                        mock.patch.object(routes, '_fetch_remote', return_value=[row]):
                    result = routes.load_bars('2330', 'TW', now=now)
                self.assertEqual(result['bars'][-1]['date'], '2026-10-08')
                self.assertEqual(result['staleDays'], 0)
                self.assertFalse(result['provisional'])

    def test_close_response_updates_the_retained_transport_socket(self):
        conn, pool = self.response(b'[]', [('Connection', 'close')])
        transport = mock.Mock()
        conn.sock = transport
        response = conn.getresponse.return_value
        clock = [0.0]
        def get_response():
            clock[0] = 3
            conn.sock = None
            return response
        conn.getresponse.side_effect = get_response
        response.read1.side_effect = [b'[]', b'']
        client = hc.HttpClient()
        with mock.patch.object(client, '_pool', return_value=pool), \
                mock.patch.object(hc, 'time', types.SimpleNamespace(monotonic=lambda: clock[0], sleep=time.sleep, time=time.time)):
            self.assertEqual(client.get_json('http://offline.test/', timeout=8, retries=0, deadline=8.5), [])
        self.assertEqual(transport.settimeout.call_args.args[0], 5.5)

    def test_movers_reports_rejected_session_as_partial_source(self):
        from tests.test_server_http_security import ST
        twse = {'stat': 'OK', 'date': '20261006', 'tables': [{
            'fields': ['證券代號', '證券名稱', '成交金額', '收盤價', '漲跌(+/-)', '漲跌價差'],
            'data': [['2330', '台積電', '50000000', '1050', '+', '15']]}]}
        tpex = [{'Date': '1151007', 'Code': '6488', 'Name': '環球晶', 'Close': '100', 'Change': '1'}]
        with mock.patch.object(hc, 'fetch_json', side_effect=lambda url, **kwargs: twse if 'MI_INDEX' in url else tpex), \
                mock.patch.object(ST, '_get_tw_sectors', return_value={'2330': '半導體業'}), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            result = ST._fetch_day_movers(5, target_date='2026-10-06', include_rows=True)
        self.assertTrue(result['ok'])
        self.assertTrue(result['partial'])
        self.assertEqual(result['source'], 'TWSE STOCK_DAY_ALL')
        self.assertIn('目標交易日', result['sourceErrors']['TPEx'])
        self.assertIsNone(result['tpexDate'])
        self.assertEqual({r['code'] for r in result['gainers']}, {'2330'})

    def test_movers_rolls_back_partial_ingest_before_reporting_source(self):
        from tests.test_server_http_security import ST
        class BrokenRow(dict):
            def get(self, name, default=None):
                if name == 'ClosingPrice':
                    raise ValueError('來源欄位損壞')
                return super().get(name, default)
        twse = [{'Date': '1151006', 'Code': '2330', 'Name': '台積電', 'ClosingPrice': '1050', 'Change': '15'},
                BrokenRow(Date='1151006', Code='2317', Name='鴻海')]
        tpex = [{'Date': '1151006', 'Code': '6488', 'Name': '環球晶', 'Close': '100', 'Change': '1'}]
        with mock.patch.object(hc, 'fetch_json', side_effect=lambda url, **kwargs: twse if 'STOCK_DAY_ALL' in url else tpex), \
                mock.patch.object(ST, '_get_tw_sectors', return_value={}), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            result = ST._fetch_day_movers(5, include_rows=True)
        self.assertTrue(result['ok'])
        self.assertTrue(result['partial'])
        self.assertEqual(result['source'], 'TPEx daily')
        self.assertFalse(result['twseAvailable'])
        self.assertEqual(result['rows'], [])
        self.assertEqual({r['code'] for r in result['gainers']}, {'6488'})
        self.assertIn('來源欄位損壞', result['sourceErrors']['TWSE'])

    def test_unknown_calendar_keeps_today_provisional_and_out_of_history(self):
        import stock_signals_routes as routes
        now = datetime(2027, 1, 4, 15, tzinfo=ZoneInfo('Asia/Taipei'))
        row = (int(now.replace(hour=9).timestamp()), 100, 101, 99, 100, 20)
        state = routes.session_state('TW', '2027-01-04', now)
        self.assertEqual(state['calendar']['status'], 'unknown')
        self.assertTrue(state['provisional'])
        self.assertIsNone(state['expectedLastDate'])
        self.assertEqual(ds.completed_daily_rows([row], 'TW', now=now), [])

    def test_managed_history_uses_shared_cutoff_after_normal_and_early_close(self):
        moments = [('TW', '2330', datetime(2026, 10, 8, 14, 30, tzinfo=ZoneInfo('Asia/Taipei'))),
                   ('US', 'AAPL', datetime(2026, 11, 27, 13, 30, tzinfo=ZoneInfo('America/New_York')))]
        original = ds.completed_daily_cutoff
        for market, symbol, now in moments:
            with self.subTest(market=market), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                    mock.patch.object(ds, 'completed_daily_cutoff', side_effect=lambda m, **kwargs: original(m, now=now)), \
                    mock.patch.object(ds, 'fetch_yahoo_daily', return_value=[
                        (int(now.replace(hour=9, minute=30).timestamp()), 100, 101, 99, 100, 20)]), \
                    mock.patch.object(jobs, '_active', {'jobId': 'fixture', 'status': 'queued', 'completed': 0, 'results': []}), \
                    mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
                jobs._run([{'symbol': symbol, 'market': market}], '1mo', 'history',
                          jobs.Budget(threading.Event()), 'fixture')
                self.assertEqual(jobs._active['status'], 'completed', jobs._active.get('error'))
                self.assertEqual(jobs._active['results'][0]['inserted'], 1)
                with ds.read_snapshot() as conn:
                    end = conn.execute('SELECT end_date FROM bar_fetch_coverage WHERE symbol=? AND market=?',
                                       (symbol, market)).fetchone()[0]
                self.assertEqual(end, now.date().isoformat())

    def test_failed_worker_stop_retains_isolation_and_stops_the_test_batch(self):
        from tests.test_Pulse讀寫分離 import PulseReadWriteTest
        observed = []
        class Fixture(PulseReadWriteTest):
            def setUp(self):
                self._cleanup_attempted = False
                self.temp = types.SimpleNamespace(name=tempfile.mkdtemp(prefix='pulse-cleanup-proof-'))
                self.temp_root = Path(tempfile.gettempdir()).resolve()
                self.release = threading.Event()
                self.http = self.thread = None
                self.queue = mock.Mock()
                self.queue.stop.return_value = False
                self.patches = [mock.Mock(), mock.Mock()]
                self.addCleanup(self.cleanup_isolation)
                observed.append(self)
            def runTest(self): pass
        marker = mock.Mock()
        result = unittest.TestResult()
        unittest.TestSuite([Fixture(), unittest.FunctionTestCase(marker)]).run(result)
        fixture = observed[0]
        try:
            self.assertEqual(len(result.failures), 1)
            self.assertTrue(result.shouldStop)
            marker.assert_not_called()
            self.assertTrue(Path(fixture.temp.name).is_dir())
            fixture.queue.stop.assert_called_once_with(timeout=3)
            for item in fixture.patches:
                item.stop.assert_not_called()
        finally:
            # 假工作者並不存在；明確釋放這份合成案例留下的目錄。
            import shutil
            shutil.rmtree(fixture.temp.name)

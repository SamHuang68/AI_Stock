"""A–M 的離線邊界回歸；只使用暫存資料與假造來源。"""
import gzip
import io
import json
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
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
    def test_short_sector_deadline_does_not_cool_shared_source(self):
        from tests.test_server_http_security import ST

        first, second = ST._REVENUE_DATASETS
        rows = [{'公司代號': '2330', '產業別': '半導體業'}]
        body = json.dumps(rows).encode()
        for mode in ('late', 'backoff', 'http503', 'source-timeout'):
            with self.subTest(mode=mode):
                clock, second_attempts, calls = [100.0], [0], []

                class Response:
                    def __init__(self, status=200):
                        self.status, self.body, self.length = status, body, len(body)

                    def getheaders(self):
                        return [('Content-Type', 'application/json')]

                    def read1(self, size):
                        part, self.body = self.body[:size], self.body[size:]
                        self.length -= len(part)
                        return part

                    def read(self):
                        return self.read1(len(self.body))

                class Connection:
                    sock = None

                    def request(self, method, path, **kwargs):
                        self.path = path

                    def getresponse(self):
                        if mode == 'source-timeout':
                            raise TimeoutError('來源自身逾時')
                        if 't187ap05_L' in self.path:
                            clock[0] = 108.45 if mode == 'late' else 108.25
                        elif second_attempts[0] == 0:
                            second_attempts[0] += 1
                            if mode == 'late':
                                clock[0] = 108.51
                            elif mode == 'backoff':
                                raise ConnectionResetError('可重試的來源重設')
                            elif mode == 'http503':
                                return Response(503)
                        return Response()

                pool = mock.Mock()
                pool._lock, pool._idle = threading.Lock(), []
                pool.acquire.side_effect = lambda timeout: Connection()
                client = hc.HttpClient()

                def request(method, url, **kwargs):
                    calls.append((url, kwargs.get('deadline')))
                    return client.request(method, url, **kwargs)

                def sleep(seconds):
                    clock[0] += seconds

                with mock.patch.object(ST, '_TW_SECTORS', {'date': None, 'map': {}}), \
                        mock.patch.object(ST, '_openapi_ds', {}), mock.patch.object(ST, '_openapi_meta', {}), \
                        mock.patch.object(ST, '_openapi_locks', {}), mock.patch.object(ST, '_fundamental_trace') as trace, \
                        mock.patch.object(ST, 'time', types.SimpleNamespace(monotonic=lambda: clock[0], strftime=lambda *a: 'fixture')), \
                        mock.patch.object(hc.time, 'monotonic', side_effect=lambda: clock[0]), \
                        mock.patch.object(hc.time, 'sleep', side_effect=sleep), \
                        mock.patch.object(client, '_pool', return_value=pool), \
                        mock.patch.object(hc, 'request', side_effect=request), \
                        mock.patch('socket.create_connection', side_effect=AssertionError('離線案例不得連外')), \
                        mock.patch('urllib.request.urlopen', side_effect=AssertionError('分類不得繞過共用來源')):
                    if mode == 'source-timeout':
                        self.assertEqual(ST._openapi_lookup_list(second), [])
                        self.assertEqual(ST._openapi_lookup_list(second), [])
                        self.assertEqual(len(calls), 1)
                        self.assertGreater(ST._openapi_meta[second]['retryAt'], clock[0])
                    elif mode == 'http503':
                        with self.assertRaises(RuntimeError):
                            ST._get_tw_sectors(deadline=108.5)
                        self.assertEqual(ST._openapi_lookup_list(second), [])
                        self.assertEqual(len(calls), 2)
                        self.assertTrue(any(call.kwargs.get('httpStatus') == 503 for call in trace.call_args_list))
                        self.assertGreater(ST._openapi_meta[second]['retryAt'], clock[0])
                    else:
                        with self.assertRaises(TimeoutError) as caught:
                            ST._get_tw_sectors(deadline=108.5)
                        self.assertEqual(caught.exception.partial_sectors, {'2330': '半導體業'})
                        self.assertNotIn(second, ST._openapi_meta)
                        self.assertEqual(ST._openapi_lookup_list(second), rows)
                        self.assertEqual(len(calls), 3)
                        self.assertIsNone(calls[-1][1])

    def test_simulation_cleanup_retains_every_child_patch_until_workers_stop(self):
        from tests.test_decision_http import DecisionHttpTest, dc, ox, st_server
        from tests.test_情境投組HTTP import SimulationHttpTest
        import shutil

        original_db, original_history = ds.DB_PATH, ox.HISTORY_PATH
        original_fetch, original_socket = ds.fetch_yahoo_daily, socket.create_connection
        observed = []

        def isolated_base(fixture):
            fixture._cleanup_attempted = False
            fixture.temp_root = Path(tempfile.gettempdir()).resolve()
            fixture.tmp = types.SimpleNamespace(name=tempfile.mkdtemp(prefix='simulation-cleanup-proof-'))
            fixture.httpd = fixture.thread = None
            fixture.old_options_history = ox.HISTORY_PATH
            ox.HISTORY_PATH = str(Path(fixture.tmp.name) / 'options-history.json')
            fixture.patches = []
            fixture.queue, fixture.pulse_updates = mock.Mock(), mock.Mock()
            fixture.queue.stop.return_value = False
            fixture.pulse_updates.stop.return_value = True
            fixture.addCleanup(fixture.cleanup_isolation)
            observed.append(fixture)

        class Fixture(SimulationHttpTest):
            def runTest(self):
                pass

        result = unittest.TestResult()
        with mock.patch.object(DecisionHttpTest, 'setUp', isolated_base):
            Fixture('runTest').run(result)
        fixture = observed[0]
        try:
            self.assertEqual(len(result.failures), 1, result.errors)
            self.assertFalse(result.errors)
            self.assertTrue(result.shouldStop)
            fixture.queue.stop.assert_called_once_with()
            fixture.pulse_updates.stop.assert_called_once_with()
            self.assertEqual(ds.DB_PATH, str(fixture.market_path))
            self.assertEqual(st_server._TW_NAMES['map']['2330'], '測試公司')
            self.assertIsNot(ds.fetch_yahoo_daily, original_fetch)
            self.assertIsNot(socket.create_connection, original_socket)
            self.assertEqual(len(fixture.patches), 8)
            self.assertTrue(Path(fixture.tmp.name).is_dir())
        finally:
            # 此案例沒有真實背景工作者；明確釋放所有仍保留的隔離設定。
            fixture.doCleanups()
            for item in reversed(fixture.patches):
                item.stop()
            ox.HISTORY_PATH = original_history
            target = Path(fixture.tmp.name).resolve()
            self.assertTrue(target.is_relative_to(fixture.temp_root))
            shutil.rmtree(target)
        self.assertEqual(ds.DB_PATH, original_db)
        self.assertIs(ds.fetch_yahoo_daily, original_fetch)
        self.assertIs(socket.create_connection, original_socket)

    def test_decision_cleanup_stops_both_workers_and_retains_isolation_on_failure(self):
        from tests.test_decision_http import DecisionHttpTest, dc, ox
        import shutil

        for queue_result, pulse_result, queue_raises in ((False, True, False),
                                                       (True, False, False),
                                                       (False, True, True)):
            with self.subTest(queue=queue_result, pulse=pulse_result, raises=queue_raises):
                observed = []
                original_db_path, original_history = dc._active_db_path, ox.HISTORY_PATH

                class Fixture(DecisionHttpTest):
                    def setUp(self):
                        self._cleanup_attempted = False
                        self.temp_root = Path(tempfile.gettempdir()).resolve()
                        self.tmp = types.SimpleNamespace(name=tempfile.mkdtemp(prefix='decision-cleanup-proof-'))
                        self.httpd = self.thread = None
                        self.old_options_history = ox.HISTORY_PATH
                        ox.HISTORY_PATH = str(Path(self.tmp.name) / 'options-history.json')
                        isolation = mock.patch.object(dc, '_active_db_path', str(Path(self.tmp.name) / 'decision.db'))
                        isolation.start()
                        self.patches = [isolation]
                        self.queue, self.pulse_updates = mock.Mock(), mock.Mock()
                        self.queue.stop.return_value = queue_result
                        self.pulse_updates.stop.return_value = pulse_result
                        if queue_raises:
                            self.queue.stop.side_effect = OSError('合成停止錯誤')
                        self.addCleanup(self.cleanup_isolation)
                        observed.append(self)
                    def runTest(self):
                        pass

                marker = mock.Mock()
                result = unittest.TestResult()
                unittest.TestSuite([Fixture('runTest'), unittest.FunctionTestCase(lambda: marker())]).run(result)
                fixture = observed[0]
                try:
                    self.assertEqual(len(result.failures), 1, result.errors)
                    self.assertFalse(result.errors)
                    self.assertTrue(result.shouldStop)
                    marker.assert_not_called()
                    fixture.queue.stop.assert_called_once_with()
                    fixture.pulse_updates.stop.assert_called_once_with()
                    self.assertTrue(Path(fixture.tmp.name).is_dir())
                    self.assertEqual(dc._active_db_path, str(Path(fixture.tmp.name) / 'decision.db'))
                    self.assertEqual(ox.HISTORY_PATH, str(Path(fixture.tmp.name) / 'options-history.json'))
                finally:
                    # 此合成案例沒有真工作者；由測試本身明確釋放保留的替身與目錄。
                    for item in reversed(fixture.patches):
                        item.stop()
                    ox.HISTORY_PATH = original_history
                    target = Path(fixture.tmp.name).resolve()
                    self.assertTrue(target.is_relative_to(fixture.temp_root))
                    shutil.rmtree(target)
                self.assertEqual(dc._active_db_path, original_db_path)

    def test_decision_cleanup_success_restores_globals_and_removes_isolated_folder(self):
        from tests.test_decision_http import DecisionHttpTest, dc, ox
        observed = []
        original_db_path, original_history = dc._active_db_path, ox.HISTORY_PATH

        class Fixture(DecisionHttpTest):
            def setUp(self):
                self._cleanup_attempted = False
                self.temp_root = Path(tempfile.gettempdir()).resolve()
                self.tmp = types.SimpleNamespace(name=tempfile.mkdtemp(prefix='decision-cleanup-success-'))
                self.httpd = self.thread = None
                self.old_options_history = ox.HISTORY_PATH
                ox.HISTORY_PATH = str(Path(self.tmp.name) / 'options-history.json')
                isolation = mock.patch.object(dc, '_active_db_path', str(Path(self.tmp.name) / 'decision.db'))
                isolation.start()
                self.patches = [isolation]
                self.queue, self.pulse_updates = mock.Mock(), mock.Mock()
                self.queue.stop.return_value = self.pulse_updates.stop.return_value = True
                self.addCleanup(self.cleanup_isolation)
                observed.append(self)
            def runTest(self):
                pass

        marker = mock.Mock()
        result = unittest.TestResult()
        unittest.TestSuite([Fixture('runTest'), unittest.FunctionTestCase(lambda: marker())]).run(result)
        fixture = observed[0]
        self.assertFalse(result.failures, result.failures)
        self.assertFalse(result.errors, result.errors)
        self.assertFalse(result.shouldStop)
        marker.assert_called_once_with()
        fixture.queue.stop.assert_called_once_with()
        fixture.pulse_updates.stop.assert_called_once_with()
        self.assertFalse(Path(fixture.tmp.name).exists())
        self.assertEqual(dc._active_db_path, original_db_path)
        self.assertEqual(ox.HISTORY_PATH, original_history)


    def test_decision_teardown_attempts_both_worker_stops(self):
        from tests.test_decision_http import DecisionHttpTest, ox
        fixture = DecisionHttpTest('runTest')
        fixture._cleanup_attempted = False
        fixture.test_result = unittest.TestResult()
        fixture.httpd, fixture.thread = mock.Mock(), mock.Mock()
        fixture.thread.is_alive.return_value = False
        fixture.queue, fixture.pulse_updates = mock.Mock(), mock.Mock()
        fixture.queue.stop.return_value = False
        fixture.pulse_updates.stop.return_value = True
        fixture.patches = []
        fixture.tmp = None
        fixture.old_options_history = ox.HISTORY_PATH
        with self.assertRaises(AssertionError):
            fixture.tearDown()
        fixture.queue.stop.assert_called_once_with()
        fixture.pulse_updates.stop.assert_called_once_with()
        self.assertTrue(fixture.test_result.shouldStop)

    def test_legacy_daily_update_http_rejections_and_empty_symbols(self):
        """真實 HTTP：舊版六項會回 200，修正後須回 503/409/400。"""
        import http.client
        from http.server import ThreadingHTTPServer
        import daily_cache_jobs as jobs
        from tests.test_server_http_security import ST
        server = ThreadingHTTPServer(('127.0.0.1', 0), ST.Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            rows = [('queue_full', 503), ('queue_error', 503), ('busy', 409)]
            for reason, expected in rows:
                with self.subTest(reason=reason), mock.patch.object(jobs, 'submit',
                        return_value={'ok': False, 'reason': reason, 'error': '固定拒收案例'}) as submit:
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    try:
                        body = {'id': 'db', 'symbols': [{'symbol': '2330', 'market': 'TW'}]}
                        connection.request('POST', '/datasource/refresh', json.dumps(body), {'Content-Type': 'application/json'})
                        response = connection.getresponse()
                        data = json.loads(response.read())
                        self.assertEqual(response.status, expected)
                        self.assertEqual(data['error'], '固定拒收案例')
                        submit.assert_called_once_with({'symbols': body['symbols'], 'range': '1mo', 'kind': 'history'})
                    finally:
                        connection.close()
            for symbols in (None, [], False):
                with self.subTest(symbols=symbols), mock.patch.object(jobs, 'submit',
                        side_effect=AssertionError('無標的不得進入提交')) as submit:
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    try:
                        connection.request('POST', '/datasource/refresh', json.dumps({'id': 'db', 'symbols': symbols}),
                                           {'Content-Type': 'application/json'})
                        response = connection.getresponse()
                        data = json.loads(response.read())
                        self.assertEqual(response.status, 400)
                        self.assertTrue(data['error'])
                        submit.assert_not_called()
                    finally:
                        connection.close()
            with mock.patch.object(jobs, 'submit', return_value={'ok': True, 'status': 'queued'}) as submit:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                try:
                    connection.request('POST', '/datasource/refresh', json.dumps(
                        {'id': 'db', 'symbols': [{'symbol': '2330', 'market': 'TW'}]}), {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read())['ok'])
                    submit.assert_called_once()
                finally:
                    connection.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_unknown_source_calendar_is_not_reported_as_closed(self):
        """不新增來源狀態；未知日曆走既有 ValueError 邊界且不抓資料。"""
        import 個股每日資料 as sources
        fixed = datetime(2027, 1, 4, 18, tzinfo=ZoneInfo('Asia/Taipei'))
        class CalendarClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz or ZoneInfo('Asia/Taipei'))
        with mock.patch.object(sources, 'datetime', CalendarClock), \
                mock.patch.object(sources.http_client, 'fetch_json', side_effect=AssertionError('未知年度不得抓取')) as fetch, \
                mock.patch.object(sources.datastore, 'list_symbols', side_effect=AssertionError('未知年度不得讀行情')):
            with self.assertRaisesRegex(ValueError, '日曆'):
                sources.run()
            fetch.assert_not_called()

    def test_stored_calendar_expiry_future_and_source_validation(self):
        """真實 SQLite 僅用 tempfile；這些是舊碼應已通過的缺漏案例。"""
        import datastore as ds
        import 台股日線 as daily
        for year, current, fresh_closed in (
                (2026, datetime(2026, 10, 8, 20, tzinfo=ZoneInfo('Asia/Taipei')), {date(2026, 1, 1), date(2026, 10, 8)}),
                (2027, datetime(2027, 1, 4, 20, tzinfo=ZoneInfo('Asia/Taipei')), {date(2027, 1, 1)})):
            with self.subTest(year=year), tempfile.TemporaryDirectory() as tmp:
                database = Path(tmp) / 'calendar-fixture.db'
                ds.init_db(database)
                daily.save_calendar(database, year, fresh_closed, set())
                for age, expected in (
                        (timedelta(days=1), current.date() - timedelta(days=1) if year == 2026 else current.date()),
                        (timedelta(days=7), current.date() - timedelta(days=1) if year == 2026 else current.date()),
                        (timedelta(days=8), current.date() if year == 2026 else current.date() - timedelta(days=1)),
                        (-timedelta(seconds=1), current.date() if year == 2026 else current.date() - timedelta(days=1))):
                    with self.subTest(age=age), closing(sqlite3.connect(database)) as connection, connection:
                        connection.execute('UPDATE calendar_years SET refreshed_at=? WHERE year=?',
                                           ((current - age).isoformat(), year))
                    self.assertEqual(ds.completed_daily_cutoff('TW', now=current, path=database), expected)
                    with ds.read_snapshot(database) as connection:
                        observed = connection.execute('SELECT refreshed_at FROM calendar_years WHERE year=?', (year,)).fetchone()[0]
                    self.assertEqual(observed, (current - age).isoformat())
                # 開市日才會查 source；以 2027 已存新鮮年度驗證合法來源與未知來源。
                if year == 2027:
                    with closing(sqlite3.connect(database)) as connection, connection:
                        connection.execute('UPDATE calendar_years SET refreshed_at=? WHERE year=?', (current.isoformat(), year))
                    for source in ('TWSE開休市', 'TWSE實際成交日', 'fixture-unverified-source'):
                        with self.subTest(source=source), closing(sqlite3.connect(database)) as connection, connection:
                            connection.execute('UPDATE market_sessions SET source=? WHERE session_date=?', (source, current.date().isoformat()))
                        if source.startswith('fixture-'):
                            with self.assertRaisesRegex(ValueError, '來源未核對'):
                                ds.completed_daily_cutoff('TW', now=current, path=database)
                        else:
                            self.assertEqual(ds.completed_daily_cutoff('TW', now=current, path=database), current.date())

    def test_unknown_calendar_metadata_and_warning_remain_visible(self):
        """沿既有 metadata 驗證未知；沒有新增 calendar metadata API。"""
        import datastore as ds
        import stock_signals_routes as routes
        now = datetime(2031, 1, 6, 20, tzinfo=ZoneInfo('Asia/Taipei'))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')):
            ds.init_db()
            with mock.patch.object(routes, '_fetch_remote', side_effect=AssertionError('唯讀不得抓取')):
                loaded = routes.load_bars('2330', 'TW', allow_network=False, now=now)
                analyzed = routes.analyze_symbol('2330', 'TW', with_stats=False, allow_network=False,
                    use_cache=False, bars_loader=lambda *args, **kwargs: loaded, chip_dir=tmp, now=now)
            self.assertEqual(loaded['session']['calendar']['status'], 'unknown')
            self.assertIsNone(loaded['session']['calendar']['source'])
            self.assertIsNone(loaded['session']['expectedLastDate'])
            self.assertIn('尚無', loaded['session']['calendar']['reason'])
            self.assertIn('日曆', analyzed['dataWarning'])
            self.assertEqual(analyzed['session']['calendar']['status'], 'unknown')

    def test_storage_failure_uses_short_cache_preserves_reason_and_retries(self):
        """分層驗證儲存、讀回與修訂中繼資料故障，原原因及短快取皆保留。"""
        import datastore as ds
        import stock_signals_routes as routes
        now = datetime(2026, 10, 8, 18, 30, tzinfo=ZoneInfo('Asia/Taipei'))
        old = (int(now.replace(day=7, hour=9, minute=0).timestamp()), 100, 102, 99, 101, 1000)
        fresh = (int(now.replace(hour=9, minute=0).timestamp()), 110, 112, 109, 111, 2000)
        for phase in ('upsert', 'read-after-write', 'revision-status'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                    mock.patch.object(routes, '_cache', {}), mock.patch.object(routes, '_remote_fail', {}), \
                    mock.patch.object(routes, '_remote_fail_errors', {}), \
                    mock.patch.object(routes, '_revision_status_unknown', {}):
                ds.init_db()
                with closing(ds.get_conn()) as connection, connection:
                    connection.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330', 'TW', *old))
                clock = [1000.0]
                failure = [True]
                after_write = [False]
                original_get = ds.get_bars
                original_upsert = ds.upsert_bars
                original_revision = ds.source_revision_status
                original_cutoff = ds.completed_daily_cutoff
                def get_bars(*args, **kwargs):
                    if failure[0] and phase == 'read-after-write' and after_write[0]:
                        after_write[0] = False
                        raise sqlite3.OperationalError('固定讀回失敗')
                    return original_get(*args, **kwargs)
                def upsert(*args, **kwargs):
                    if failure[0]:
                        if phase == 'upsert':
                            raise ValueError('固定日曆寫入失敗')
                        after_write[0] = True
                    return original_upsert(*args, **kwargs)
                def revision(*args, **kwargs):
                    if failure[0] and phase == 'revision-status':
                        raise OSError('固定收據讀取失敗')
                    return original_revision(*args, **kwargs)
                with mock.patch.object(routes, 'time', types.SimpleNamespace(time=lambda: clock[0])), \
                        mock.patch.object(ds, 'completed_daily_cutoff', side_effect=lambda market, **kwargs:
                            original_cutoff(market, **{**kwargs, 'now': now})), \
                        mock.patch.object(ds, 'get_bars', side_effect=get_bars), \
                        mock.patch.object(ds, 'upsert_bars', side_effect=upsert), \
                        mock.patch.object(ds, 'source_revision_status', side_effect=revision), \
                        mock.patch.object(routes, '_fetch_remote', return_value=[fresh]) as fetch:
                    loaded = routes.load_bars('2330', 'TW', now=now)
                    self.assertTrue(loaded['retrySoon'])
                    persisted_readback = phase == 'revision-status'
                    self.assertEqual(loaded['source'], 'local-db+yahoo' if persisted_readback else 'local-db')
                    self.assertEqual(loaded['bars'][-1]['date'], '2026-10-08' if persisted_readback else '2026-10-07')
                    self.assertEqual(loaded['sourceRevisionStatusUnknown'], persisted_readback)
                    self.assertIn('固定', loaded['error'])
                    repeated = routes.load_bars('2330', 'TW', now=now)
                    self.assertEqual(fetch.call_count, 1)
                    self.assertTrue(repeated['retrySoon'])
                    self.assertIn(loaded['error'], repeated['error'])
                    analyzed = routes.analyze_symbol('2330', 'TW', with_stats=False, use_cache=True,
                        bars_loader=lambda *args, **kwargs: loaded, chip_dir=tmp, now=now)
                    self.assertEqual(analyzed['dataWarning'], loaded['error'])
                    ttl = routes._cache[('2330', 'TW', False)][0] - clock[0]
                    self.assertGreater(ttl, 0)
                    self.assertLessEqual(ttl, 60)
                    clock[0] += 61
                    failure[0] = False
                    recovered = routes.load_bars('2330', 'TW', now=now)
                    self.assertEqual(fetch.call_count, 2)
                    self.assertFalse(recovered['retrySoon'])
                    self.assertEqual(recovered['source'], 'local-db+yahoo')
                    self.assertEqual(recovered['bars'][-1]['date'], '2026-10-08')


    def test_movers_and_member_cache_retry_partial_after_thirty_seconds(self):
        from tests.test_decision_http import st_server as ST
        import lru_cache
        import 類股成員 as members
        for partial in (True, False):
            for route, method in (('/movers', '_handle_movers'),
                                  ('/sector-members?sector=半導體業', '_handle_sector_members')):
                with self.subTest(partial=partial, route=route):
                    now = [0]
                    snapshot = {'ok': True, 'partial': partial, 'twseAvailable': True,
                                'classificationCount': 1, 'sourceErrors': {'tpex': '中斷'} if partial else {}}
                    handler = ST.Handler.__new__(ST.Handler)
                    handler.path = route
                    handler._ok = mock.Mock()
                    with mock.patch.object(lru_cache, 'time', types.SimpleNamespace(time=lambda: now[0])), \
                            mock.patch.object(ST, '_cache', ST.LRUCache(10)), \
                            mock.patch.object(ST, '_fetch_day_movers', return_value=snapshot) as fetch, \
                            mock.patch.object(members, 'build_tw_members', return_value={'ok': True}):
                        getattr(handler, method)()
                        now[0] = 29
                        getattr(handler, method)()
                        self.assertEqual(fetch.call_count, 1)
                        now[0] = 31
                        getattr(handler, method)()
                        self.assertEqual(fetch.call_count, 2 if partial else 1)
                        if not partial:
                            now[0] = 301
                            getattr(handler, method)()
                            self.assertEqual(fetch.call_count, 2)

    def test_backoff_exhaustion_preserves_cause_status_and_terminal_stats(self):
        import http.client
        for original in (ConnectionResetError('首試中斷'), http.client.IncompleteRead(b'x', 2), None):
            with self.subTest(error=type(original).__name__):
                conn, pool = self.framed_response(b'{}', [('Content-Length', '2')], status=503)
                if original is not None:
                    conn.request.side_effect = original
                client = hc.HttpClient()
                with mock.patch.object(client, '_pool', return_value=pool), \
                        mock.patch.object(hc, 'time', types.SimpleNamespace(
                            monotonic=lambda: 100, sleep=mock.Mock(), time=time.time)) as clock:
                    with self.assertRaises(hc.HttpError) as caught:
                        client.request('GET', 'http://offline.test/', retries=1, deadline=100.4)
                self.assertIsInstance(caught.exception.cause, TimeoutError)
                self.assertIn('整體期限', str(caught.exception.cause))
                if original is None:
                    self.assertEqual(caught.exception.status, 503)
                    self.assertEqual(caught.exception.cause.__cause__.status, 503)
                else:
                    self.assertIs(caught.exception.cause.__cause__, original)
                self.assertEqual(client.stats()['errors'], 1)
                self.assertEqual(client.stats()['retries'], 0)
                self.assertEqual(pool.acquire.call_count, 1)
                clock.sleep.assert_not_called()

    def test_backoff_oversleep_preserves_original_error_without_counting_another_attempt(self):
        for original in (ConnectionResetError('首試中斷'), None):
            with self.subTest(error=type(original).__name__):
                conn, pool = self.framed_response(b'{}', [('Content-Length', '2')], status=503)
                if original is not None:
                    conn.request.side_effect = original
                client, now = hc.HttpClient(), [100.0]

                def oversleep(delay):
                    self.assertEqual(delay, .5)
                    now[0] += .7

                with mock.patch.object(client, '_pool', return_value=pool), \
                        mock.patch.object(hc, 'time', types.SimpleNamespace(
                            monotonic=lambda: now[0], sleep=oversleep, time=time.time)):
                    with self.assertRaises(hc.HttpError) as caught:
                        client.request('GET', 'http://offline.test/', retries=1, deadline=100.6)
                self.assertIsInstance(caught.exception.cause, TimeoutError)
                if original is None:
                    self.assertEqual(caught.exception.status, 503)
                    self.assertEqual(caught.exception.cause.__cause__.status, 503)
                else:
                    self.assertIs(caught.exception.cause.__cause__, original)
                self.assertEqual(client.stats()['errors'], 1)
                self.assertEqual(client.stats()['retries'], 0)
                self.assertEqual(pool.acquire.call_count, 1)
                self.assertEqual(conn.request.call_count, 1)

    def test_response_size_limit_bounds_plain_and_decompressed_gzip(self):
        for compressed in (False, True):
            for deadline in (None, time.monotonic() + 5):
                with self.subTest(compressed=compressed, deadline=deadline):
                    raw = b' ' * 256 + b'{}'
                    body = gzip.compress(raw) if compressed else raw
                    headers = [('Content-Length', str(len(body)))]
                    if compressed:
                        headers.append(('Content-Encoding', 'gzip'))
                    conn, pool = self.framed_response(body, headers)
                    client = hc.HttpClient()
                    with mock.patch.object(client, '_pool', return_value=pool):
                        with self.assertRaises(hc.HttpError) as caught:
                            client.request('GET', 'http://offline.test/', retries=0,
                                           headers={'Accept-Encoding': 'gzip'},
                                           max_body_bytes=128, deadline=deadline)
                    self.assertIsInstance(caught.exception.cause, ValueError)
                    pool.release.assert_called_once_with(conn, reuse=False)

    def test_official_budget_preserves_exact_raw_receipt_through_shared_client(self):
        import hashlib
        raw = '{ "stat": "OK", "name": "台積電" }\n'.encode('utf-8')
        conn, pool = self.framed_response(gzip.compress(raw), [('Content-Encoding', 'gzip')])
        budget = jobs.Budget(threading.Event())
        client = hc.HttpClient()
        url = 'http://offline.test/STOCK_DAY?stockNo=2330'
        with mock.patch.object(client, '_pool', return_value=pool), \
                mock.patch.object(hc, 'request', wraps=client.request) as request, \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('不得另走抓取管線')):
            result = budget.get_json(url)
        self.assertEqual(result[0], json.loads(raw))
        self.assertEqual(result[1], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result.source_receipt['raw_text'], raw.decode('utf-8'))
        self.assertEqual(result.source_receipt['url'], url)
        self.assertEqual(request.call_args.kwargs['max_body_bytes'], 12_000_000)
        self.assertEqual(request.call_args.kwargs['retries'], 0)
        self.assertEqual(request.call_args.kwargs['headers']['Accept-Encoding'], 'gzip')
        self.assertLessEqual(request.call_args.kwargs['deadline'], budget.ends)
        self.assertEqual(budget.used, 1)

    def test_official_budget_stops_slow_headers_and_slow_body(self):
        for headers in (True, False):
            with self.subTest(headers=headers), closing(socket.socket()) as listener:
                listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(2)
                stop = threading.Event()
                def source():
                    with closing(listener.accept()[0]) as connection:
                        connection.recv(4096)
                        connection.sendall(b'HTTP/1.1 200 OK\r\nX-Slow: ' if headers else
                                           b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n')
                        try:
                            for _ in range(40):
                                if stop.wait(.03):
                                    return
                                connection.sendall(b' ')
                        except OSError:
                            return
                worker = threading.Thread(target=source); worker.start()
                budget = jobs.Budget(threading.Event(), seconds=.18)
                started = time.monotonic()
                try:
                    with self.assertRaises(TimeoutError):
                        budget.get_json(f'http://127.0.0.1:{listener.getsockname()[1]}/')
                    self.assertLess(time.monotonic() - started, .6)
                finally:
                    stop.set(); hc.get_default_client().clear_pools(); worker.join(2)
                self.assertFalse(worker.is_alive())

    def test_official_source_deadline_is_explicit_before_overall_budget_expires(self):
        budget = jobs.Budget(threading.Event())
        failure = hc.HttpError('來源回應已超過整體期限', cause=TimeoutError())
        with mock.patch.object(hc, 'request', side_effect=failure), self.assertRaises(TimeoutError):
            budget.get_json('http://offline.test/STOCK_DAY?stockNo=2330')
        self.assertGreater(budget.remaining(), 590)

    def test_calendar_write_failure_preserves_read_response_and_remains_fail_closed(self):
        import stock_signals_routes as routes
        now = datetime(2026, 10, 8, 18, 30, tzinfo=ZoneInfo('Asia/Taipei'))
        old = (int(now.replace(day=7, hour=9, minute=0).timestamp()), 100, 102, 99, 101, 1000)
        fresh = (int(now.replace(hour=9, minute=0).timestamp()), 110, 112, 109, 111, 2000)
        for broken_schema in (False, True):
            with self.subTest(broken_schema=broken_schema), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                    mock.patch.object(routes, '_remote_fail', {}):
                ds.init_db()
                with closing(ds.get_conn()) as connection, connection:
                    connection.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', ('2330', 'TW', *old))
                    if broken_schema:
                        connection.execute('ALTER TABLE calendar_years RENAME COLUMN closed TO fixture_closed')
                    connection.execute('INSERT INTO calendar_years VALUES(?,?,?,?)', (2026, 'invalid', '[]', now.isoformat()))
                original = ds.completed_daily_rows
                with mock.patch.object(ds, 'completed_daily_rows', side_effect=lambda rows, market, **kw: original(rows, market, **{**kw, 'now': now})), \
                        mock.patch.object(routes, '_fetch_remote', return_value=[fresh]) as fetch:
                    loaded = routes.load_bars('2330', 'TW', now=now)
                self.assertEqual(loaded['source'], 'local-db')
                self.assertEqual(loaded['bars'][-1]['date'], '2026-10-07')
                self.assertIn('保留已讀本機資料', loaded['error'])
                analyzed = routes.analyze_symbol('2330', 'TW', with_stats=False, use_cache=False,
                    bars_loader=lambda *args, **kw: loaded, chip_dir=tmp, now=now)
                self.assertEqual(analyzed['dataSource'], 'local-db')
                self.assertEqual(analyzed['dataWarning'], loaded['error'])
                fetch.assert_called_once()
                self.assertEqual(ds.get_bars('2330', market='TW'), [old])
                with self.assertRaises(ValueError):
                    ds.completed_daily_cutoff('TW', now=now)

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

    def test_deadline_interrupts_slow_response_headers(self):
        stop = threading.Event()
        with closing(socket.socket()) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            listener.settimeout(2)
            def source():
                with closing(listener.accept()[0]) as connection:
                    connection.recv(4096)
                    connection.sendall(b'HTTP/1.1 200 OK\r\nX-Slow: ')
                    try:
                        for _ in range(40):
                            if stop.wait(.03):
                                return
                            connection.sendall(b'x')
                        connection.sendall(b'\r\nContent-Length: 2\r\n\r\n{}')
                    except OSError:
                        # 呼叫端期限到達後關閉本案連線，來源不再寫入。
                        return
            worker = threading.Thread(target=source)
            worker.start()
            client = hc.HttpClient()
            started = time.monotonic()
            try:
                with self.assertRaises(hc.HttpError) as caught:
                    client.get_json(f'http://127.0.0.1:{listener.getsockname()[1]}/',
                                    timeout=.1, retries=0, deadline=started + .18)
                self.assertIsInstance(caught.exception.cause, TimeoutError)
                self.assertLess(time.monotonic() - started, .6)
                self.assertEqual(client.stats()['requests'], 1)
                self.assertFalse(any(pool._idle for pool in client._pools.values()))
            finally:
                stop.set()
                client.clear_pools()
                worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_deadline_callback_finishes_before_connection_can_be_reused(self):
        conn, pool = self.framed_response(b'{}', [('Content-Length', '2')])
        client = hc.HttpClient()
        def timer(delay, callback):
            handle = mock.Mock()
            handle.join.side_effect = callback
            return handle
        with mock.patch.object(client, '_pool', return_value=pool), \
                mock.patch.object(hc.time, 'monotonic', return_value=0), \
                mock.patch.object(hc.threading, 'Timer', side_effect=timer):
            with self.assertRaises(hc.HttpError) as caught:
                client.get_json('http://offline.test/', retries=0, deadline=5)
        self.assertIsInstance(caught.exception.cause, TimeoutError)
        conn.sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        pool.release.assert_called_once_with(conn, reuse=False)

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

    def test_queue_submission_errors_do_not_run_late_callbacks(self):
        body = {'symbols': [{'symbol': '2330', 'market': 'TW'}], 'range': '1y'}
        for error in (sqlite3.OperationalError('資料庫已鎖定'), RuntimeError('收據提交後綁定失敗')):
            with self.subTest(error=type(error).__name__), mock.patch.object(jobs, '_active', None), \
                    mock.patch.object(jobs, '_cancel', None), \
                    mock.patch.object(jobs.job_queue, 'submit', side_effect=error) as enqueue, \
                    mock.patch.object(ds, 'init_db', side_effect=AssertionError('拒收回呼不得讀取或寫入資料')):
                result = jobs.submit(body)
                self.assertFalse(result['ok'])
                self.assertEqual(result['reason'], 'queue_error')
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['errorType'], type(error).__name__)
                self.assertEqual(result['sourceRequests'], 0)
                self.assertIn('finishedAt', result)
                callback = enqueue.call_args.args[1]
                callback()
                self.assertEqual(jobs.status()['status'], 'failed')
                with mock.patch.object(jobs.job_queue, 'submit', return_value={'ok': True}):
                    next_job = jobs.submit(body)
                self.assertTrue(next_job['ok'])
                callback()
                self.assertEqual(jobs.status()['jobId'], next_job['jobId'])
                self.assertEqual(jobs.status()['status'], 'queued')

    def test_verified_same_year_calendar_takes_precedence_over_static_days(self):
        import 台股日線 as daily
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'official.db'
            ds.init_db(database)
            after = datetime(2026, 10, 8, 20, tzinfo=ZoneInfo('Asia/Taipei'))
            class CalendarClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return after.astimezone(tz or daily.TZ)
            with mock.patch.object(daily, 'datetime', CalendarClock):
                daily.save_calendar(database, 2026, {date(2026, 1, 1), after.date()}, {date(2026, 10, 10)})
            self.assertEqual(ds.completed_daily_cutoff('TW', now=after, path=database), date(2026, 10, 7))
            saturday = after.replace(day=10)
            self.assertEqual(ds.completed_daily_cutoff('TW', now=saturday, path=database), saturday.date())
            self.assertEqual(ds.completed_daily_cutoff('TW', now=saturday.replace(hour=12), path=database), date(2026, 10, 9))
            missing = Path(tmp) / 'missing.db'
            self.assertEqual(ds.completed_daily_cutoff('TW', now=after, path=missing), after.date())
            self.assertEqual(ds.completed_daily_cutoff('TW', now=saturday, path=missing), date(2026, 10, 9))
            self.assertFalse(missing.exists())
            row = (int(after.replace(hour=9).timestamp()), 100, 102, 99, 101, 1000)
            original = ds.completed_daily_cutoff
            with mock.patch.object(ds, 'completed_daily_cutoff', side_effect=lambda market, **kw: original(market, **{**kw, 'now': after})):
                self.assertEqual(ds.upsert_bars('2330', 'TW', [row], source='TWSE', path=database), 0)
            with ds.read_snapshot(database) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM bars').fetchone()[0], 0)

    def test_unknown_static_year_reuses_same_database_verified_calendar(self):
        import 台股日線 as daily
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ds, 'DB_PATH', str(Path(tmp) / 'other.db')):
            database = Path(tmp) / 'official.db'
            ds.init_db(database)
            after = datetime(2027, 1, 4, 20, tzinfo=ZoneInfo('Asia/Taipei'))
            class CalendarClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return after.astimezone(tz or daily.TZ)
            with mock.patch.object(daily, 'datetime', CalendarClock):
                daily.save_calendar(database, 2027, {date(2027, 1, 1)}, {date(2027, 1, 9)})
            row = (int(after.replace(hour=9).timestamp()), 100, 102, 99, 101, 1000)
            self.assertEqual(ds.completed_daily_rows([row], 'TW', now=after, path=database), [row])
            self.assertEqual(ds.completed_daily_rows([row], 'TW', now=after), [])
            self.assertEqual(ds.completed_daily_rows([row], 'TW', now=after.replace(hour=12), path=database), [])
            saturday = after.replace(day=9)
            self.assertEqual(ds.completed_daily_cutoff('TW', now=saturday, path=database), saturday.date())
            self.assertEqual(ds.completed_daily_cutoff('TW', now=after.replace(day=1), path=database), date(2026, 12, 31))
            self.assertEqual(ds.completed_daily_cutoff('TW', now=after.replace(year=2031), path=database), date(2031, 1, 3))
            self.assertEqual(ds.completed_daily_cutoff('TW', now=after.replace(day=12), path=database), date(2027, 1, 11))
            original = ds.completed_daily_cutoff
            with mock.patch.object(ds, 'completed_daily_cutoff',
                                   side_effect=lambda market, **kw: original(market, **dict(kw, now=after))):
                self.assertEqual(ds.upsert_bars('2330', 'TW', [row], source='TWSE', path=database), 1)
                with ds.read_snapshot(database) as conn:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM official_daily_observations').fetchone()[0], 1)
                daily.import_day(database, 'TWSE', after.date(),
                                 [{'symbol': '2330', 'name': '離線年度案例', 'prices': [100, 102, 99, 101], 'volume': 1000}],
                                 'fixture-all-market', min_rows=1)
                with ds.read_snapshot(database) as conn:
                    self.assertEqual(conn.execute('SELECT row_count FROM daily_imports WHERE exchange=? AND session_date=?',
                                                  ('TWSE', after.date().isoformat())).fetchone()[0], 1)
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("UPDATE calendar_years SET closed='invalid' WHERE year=2027")
            with self.assertRaisesRegex(ValueError, '年度日曆無效'):
                ds.completed_daily_rows([row], 'TW', now=after, path=database)

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
            with self.assertRaises(ValueError):
                datasources.refresh('db')
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

    def test_sector_lookup_follows_bounded_same_origin_redirects(self):
        from tests.test_server_http_security import ST
        rows = [{'公司代號': '2330', '產業別': '半導體業'}]
        url = ST._openapi_url('t187ap05_L')
        target = 'https://openapi.twse.com.tw/v1/redirected'
        responses = [hc.HttpResponse(301, {'Location': '/v1/redirected'}, b'', url),
                     hc.HttpResponse(200, {'Content-Type': 'application/json'}, json.dumps(rows).encode(), target)]
        with mock.patch.object(ST, '_openapi_ds', {}), mock.patch.object(ST, '_openapi_meta', {}), \
                mock.patch.object(ST, '_openapi_locks', {}), mock.patch.object(ST, '_fundamental_trace'), \
                mock.patch.object(hc, 'request', side_effect=responses) as request, \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            self.assertEqual(ST._openapi_lookup_list('t187ap05_L', deadline=12345), rows)
            self.assertEqual([call.args[1] for call in request.call_args_list], [url, target])
            self.assertTrue(all(call.kwargs['deadline'] == 12345 for call in request.call_args_list))
            self.assertEqual(ST._openapi_meta['t187ap05_L']['status'], 'ok')

    def test_sector_lookup_rejects_external_missing_or_looping_redirects(self):
        from tests.test_server_http_security import ST
        url = ST._openapi_url('t187ap05_L')
        for location, calls in [('https://unrelated.invalid/data', 1), (None, 1),
                                ('https://' + 'user' + '@' + 'openapi.twse.com.tw/data', 1), (url, 4)]:
            with self.subTest(location=location), mock.patch.object(ST, '_openapi_ds', {}), \
                    mock.patch.object(ST, '_openapi_meta', {}), mock.patch.object(ST, '_openapi_locks', {}), \
                    mock.patch.object(ST, '_fundamental_trace'), \
                    mock.patch.object(hc, 'request', return_value=hc.HttpResponse(
                        302, {} if location is None else {'Location': location}, b'', url)) as request:
                self.assertEqual(ST._openapi_lookup_list('t187ap05_L'), [])
                self.assertEqual(request.call_count, calls)
                self.assertEqual(ST._openapi_meta['t187ap05_L']['status'], 'unavailable')
                self.assertIn('轉址', ST._openapi_meta['t187ap05_L']['error'])

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

    def test_pulse_http_stop_failure_retains_isolation_and_still_stops_queue(self):
        from tests.test_Pulse讀寫分離 import PulseReadWriteTest, dc
        import shutil

        original_db = dc.DB_PATH
        for shutdown_error in (None, OSError('隔離 HTTP 停止失敗')):
            with self.subTest(shutdown_error=shutdown_error is not None):
                observed = []

                class Fixture(PulseReadWriteTest):
                    def setUp(self):
                        self._cleanup_attempted = False
                        self.temp_root = Path(tempfile.gettempdir()).resolve()
                        self.temp = types.SimpleNamespace(name=tempfile.mkdtemp(prefix='pulse-http-stop-proof-'))
                        self.release = threading.Event()
                        self.http, self.thread, self.queue = mock.Mock(), mock.Mock(), mock.Mock()
                        self.thread.is_alive.return_value = True  # 有界替身，不建立真的掛住執行緒。
                        self.http.shutdown.side_effect = shutdown_error
                        self.queue.stop.return_value = True
                        isolated_db = str(Path(self.temp.name) / 'decision.db')
                        replacement = mock.patch.object(dc, 'DB_PATH', isolated_db)
                        replacement.start()
                        self.patches = [replacement]
                        self.addCleanup(self.cleanup_isolation)
                        observed.append(self)

                    def runTest(self):
                        pass

                marker = mock.Mock()
                result = unittest.TestResult()
                unittest.TestSuite([Fixture('runTest'), unittest.FunctionTestCase(lambda: marker())]).run(result)
                fixture = observed[0]
                try:
                    self.assertEqual(len(result.failures), 1, result.errors)
                    self.assertFalse(result.errors)
                    self.assertTrue(result.shouldStop)
                    marker.assert_not_called()
                    self.assertTrue(Path(fixture.temp.name).exists())
                    self.assertEqual(dc.DB_PATH, str(Path(fixture.temp.name) / 'decision.db'))
                    fixture.queue.stop.assert_called_once_with(timeout=3)
                    fixture.http.shutdown.assert_called_once_with()
                    if shutdown_error is None:
                        fixture.thread.join.assert_called_once_with(2)
                        fixture.http.server_close.assert_called_once_with()
                    else:
                        fixture.thread.join.assert_not_called()
                finally:
                    for replacement in reversed(fixture.patches):
                        replacement.stop()
                    target = Path(fixture.temp.name).resolve()
                    self.assertTrue(target.is_relative_to(fixture.temp_root) and target != fixture.temp_root)
                    if target.exists():
                        shutil.rmtree(target)
                self.assertEqual(dc.DB_PATH, original_db)

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

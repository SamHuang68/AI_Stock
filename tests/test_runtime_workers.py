"""Real worker/gate functions with isolated data and no external providers."""
import ast
from contextlib import ExitStack
import datetime as dt
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

from server import data_paths
from server import runtime_storage
from server.http_boundary import BodyReadError, read_json_body

ROOT = Path(__file__).resolve().parents[1]


def source_functions(relative, names, namespace, *, class_name=None):
    """Load the exact product functions without importing unrelated daemons.

    The HTTP entrypoint imports every route/provider; the research module also
    imports unrelated database consumers. These tests compile their unchanged
    function ASTs and inject only their surrounding module/service boundaries.
    """
    source = ROOT / relative
    tree = ast.parse(source.read_text(encoding='utf-8-sig'), filename=str(source))
    nodes = tree.body
    if class_name:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == class_name).body
    selected = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    if len(selected) != len(names):
        raise AssertionError('product function missing')
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


class RuntimeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'fixture'
        self.data.mkdir()
        (self.data / data_paths.FIXTURE_FILE).write_text(json.dumps(
            {'schemaVersion': 1, 'kind': 'fixture', 'fixtureId': str(uuid.uuid4())}), encoding='utf-8')
        (self.data / 'market.db').write_bytes(b'fixture-database-not-opened')
        self.history = self.data / 'etf_history'
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(sys, '_st_runtime_binding', None, create=True))
        self.stack.enter_context(mock.patch.object(sys, '_st_runtime_leases', {}, create=True))
        self.stack.enter_context(mock.patch.object(sys, '_st_gateway_auth', None, create=True))
        self.stack.enter_context(mock.patch.object(sys, '_st_runtime_lease_guard', threading.RLock(), create=True))
        self.stack.enter_context(mock.patch.dict(os.environ, {
            'ST_RUNTIME_ROLE': 'fixture', 'ST_DATA_ROOT': str(self.data),
            'ST_ETF_HISTORY_DIR': str(self.history),
        }, clear=True))
        self.binding = data_paths.binding_for(code_root=ROOT)
        self.stack.enter_context(runtime_storage.bootstrap_runtime(binding=self.binding))
        self.stack.enter_context(mock.patch.object(sys, 'path', [str(ROOT / 'server'), *sys.path]))
        self.stack.enter_context(mock.patch.dict(sys.modules))
        for name in ('etf_paths', 'etf_delta_tracker', 'etf_api', 'ETF更新診斷'):
            sys.modules.pop(name, None)
        slog = importlib.import_module('slog')
        self.stack.enter_context(mock.patch.object(slog, 'get_logger', return_value=mock.Mock()))
        self.tracker = importlib.import_module('etf_delta_tracker')
        self.api = importlib.import_module('etf_api')
        self.diagnostics = importlib.import_module('ETF更新診斷')
        self.etf_paths = importlib.import_module('etf_paths')
        self.stack.enter_context(mock.patch.object(self.tracker.urllib.request, 'urlopen', side_effect=AssertionError('external network forbidden')))

    def test_etf_update_stays_in_the_owning_process_and_records_completion(self):
        run_id = uuid.uuid4().hex
        called = []
        def run(day, *, run_id, deadline_monotonic):
            called.append((os.getpid(), day, deadline_monotonic))
            self.diagnostics.UpdateTrace(run_id).finish(accepted=True, state='updated')
            return True
        with mock.patch.object(self.api, '_tracker_state', {'runId': run_id}), \
             mock.patch.object(self.tracker, 'run', side_effect=run), \
             mock.patch.object(self.api.subprocess, 'run', side_effect=AssertionError('external writer subprocess forbidden')) as spawn:
            self.api._run_tracker_async()
            self.assertEqual(0, self.api._tracker_state['lastReturnCode'])
            self.assertFalse(self.api._tracker_state['running'])
            self.assertTrue(self.api._tracker_state['report']['accepted'])
            self.assertEqual(os.getpid(), called[0][0])
            self.assertEqual(dt.date.today(), called[0][1])
            self.assertGreater(called[0][2], self.api.time.monotonic())
            spawn.assert_not_called()

    def test_etf_timeout_finishes_job_without_claiming_success(self):
        run_id = uuid.uuid4().hex
        with mock.patch.object(self.api, '_tracker_state', {'runId': run_id}), \
             mock.patch.object(self.tracker, 'run', side_effect=TimeoutError('fixture deadline')):
            self.api._run_tracker_async()
            self.assertEqual(-2, self.api._tracker_state['lastReturnCode'])
            self.assertFalse(self.api._tracker_state['running'])
            self.assertFalse(self.api._tracker_state['report']['accepted'])
            self.assertEqual('timeout', self.diagnostics.read_report(run_id)['state'])

    def test_expired_etf_budget_does_not_start_http_or_retry(self):
        self.tracker._request_context.deadline = 1.0
        try:
            with mock.patch.object(self.tracker.time, 'monotonic', return_value=2.0), \
                 mock.patch.object(self.tracker.time, 'sleep') as sleep:
                with self.assertRaises(TimeoutError):
                    self.tracker.http_get('https://fixture.invalid/data')
                self.tracker.urllib.request.urlopen.assert_not_called()
                sleep.assert_not_called()
        finally:
            del self.tracker._request_context.deadline

    def test_etf_response_body_deadline_aborts_without_retry(self):
        clock = [0.0]
        response = mock.MagicMock()
        response.__enter__.return_value = response
        def read(_size):
            clock[0] = 301.0
            return b'late body'
        response.read1.side_effect = read
        self.tracker._request_context.deadline = 300.0
        try:
            with mock.patch.object(self.tracker.time, 'monotonic', side_effect=lambda: clock[0]), \
                 mock.patch.object(self.tracker.time, 'sleep') as sleep, \
                 mock.patch.object(self.tracker.urllib.request, 'urlopen', return_value=response) as opened:
                with self.assertRaises(TimeoutError):
                    self.tracker.http_get('https://fixture.invalid/data')
                opened.assert_called_once()
                self.assertEqual(self.tracker.TIMEOUT, opened.call_args.kwargs['timeout'])
                response.read1.assert_called_once()
                sleep.assert_not_called()
        finally:
            del self.tracker._request_context.deadline

    def test_etf_deadline_before_snapshot_commit_preserves_existing_file(self):
        day = dt.date(2026, 9, 29)
        self.history.mkdir()
        snapshot = self.history / f'top10_active_etf_holdings_{day}.json'
        original = b'keep-corrupt-evidence'
        snapshot.write_bytes(original)
        clock = [0.0]
        acceptance = self.etf_paths.snapshot_acceptance
        def expire_when_candidate_is_accepted(*args, **kwargs):
            result = acceptance(*args, **kwargs)
            if result['accepted']:
                clock[0] = 301.0
            return result
        row = {'code': '2330', 'market': 'TW', 'name': 'fixture', 'weight': 20, 'shares': 1000}
        run_id = uuid.uuid4().hex
        with mock.patch.object(self.tracker, 'ETFS', {f'{i:05d}': (f'{i:05d}', 'fixture') for i in range(10)}), \
             mock.patch.object(self.tracker, 'fetch_one', return_value=([row], str(day), 'fixture')), \
             mock.patch.object(self.tracker.time, 'monotonic', side_effect=lambda: clock[0]), \
             mock.patch.object(self.etf_paths, 'snapshot_acceptance', side_effect=expire_when_candidate_is_accepted), \
             mock.patch.object(self.tracker, 'atomic_write_json') as commit:
            with self.assertRaises(TimeoutError):
                self.tracker.run(day, run_id=run_id, deadline_monotonic=300.0)
            commit.assert_not_called()
        self.assertEqual(original, snapshot.read_bytes())
        self.assertEqual([], list(self.history.glob('*.invalid-*')))
        self.assertEqual('timeout', self.diagnostics.read_report(run_id)['state'])

    def test_research_update_uses_same_process_runner_and_bound_logs(self):
        import atomic_store
        calls = []
        def worker(argv, *, parent_run_id, trace_output):
            calls.append((os.getpid(), argv, parent_run_id))
            trace_output.write('fixture source finished\n')
            return 0
        pool_result = {'symbols': 1, 'window': {'to': '2026-09-29'},
                       'generatedAt': 'fixture', 'research': {'selection': {}}}
        state = self.data / 'stock_research_maintenance.json'
        namespace = {'Path': Path, 'datetime': dt.datetime, 'timedelta': dt.timedelta,
                     'time': self.api.time, 'uuid': uuid, 'json': json, 'sys': sys, 'os': os,
                     'ROOT': self.root / 'code', 'subprocess': mock.Mock(),
                     'binding_for': data_paths.binding_for, 'log_path': data_paths.log_path,
                     'assert_write_allowed': runtime_storage.assert_write_allowed,
                     'atomic_write_json': atomic_store.atomic_write_json, 'load_json': atomic_store.load_json,
                     'paths': lambda: (state, self.data / 'daily.db'),
                     'datastore': SimpleNamespace(DB_PATH=str(self.data / 'market.db')),
                     'ss': SimpleNamespace(_TZ={'TW': dt.timezone.utc}),
                     'pool': SimpleNamespace(refresh=lambda _market: pool_result),
                     'inventory': lambda: {}, 'capture': lambda _now: {}, 'check_evidence': lambda **_: {},
                     '_run_source_update': worker}
        source_functions('server/個股研究維護.py', {'run'}, namespace)
        with mock.patch.dict(sys.modules, {'stock_signals_routes': SimpleNamespace(clear_cache=lambda: None)}):
            result = namespace['run'](download_sources=True, now=dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc))
        self.assertEqual('completed', result['status'])
        self.assertEqual(os.getpid(), calls[0][0])
        self.assertIn(str(self.data), calls[0][1])
        self.assertEqual(result['runId'], calls[0][2])
        namespace['subprocess'].run.assert_not_called()
        self.assertTrue((self.data / 'logs' / 'stock_research_maintenance.jsonl').is_file())
        self.assertFalse((self.root / 'logs').exists())

    def test_research_runner_passes_parent_receipt_stream_and_deadline(self):
        worker = mock.Mock(return_value=0)
        namespace = {'Path': Path, 'sys': sys, 'time': self.api.time, 'importlib': importlib,
                     'ROOT': ROOT, '_source_module_lock': threading.Lock(),
                     'datastore': SimpleNamespace(DB_PATH=str(self.data / 'market.db')),
                     'assert_write_allowed': runtime_storage.assert_write_allowed}
        source_functions('server/個股研究維護.py', {'_run_source_update'}, namespace)
        output = io.StringIO()
        argv = ['--start', '2026-09-28', '--end', '2026-09-29', '--data-dir', str(self.data)]
        with mock.patch.dict(sys.modules, {'_st_research_source_update': SimpleNamespace(run_update=worker)}):
            result = namespace['_run_source_update'](argv, parent_run_id='fixture-parent', trace_output=output)
        self.assertEqual(0, result)
        self.assertEqual((argv,), worker.call_args.args)
        self.assertEqual('fixture-parent', worker.call_args.kwargs['parent_run_id'])
        self.assertIs(output, worker.call_args.kwargs['trace_output'])
        self.assertGreater(worker.call_args.kwargs['deadline_monotonic'], self.api.time.monotonic())


class RuntimeGateTests(unittest.TestCase):
    def setUp(self):
        self.identity = {'storageMode': 'external', 'runtimeRole': 'backend', 'dataRootId': str(uuid.uuid4()),
                         'capabilityVersion': 1, 'storageCapability': 1}
        self.namespace = {'json': json, 'read_json_body': read_json_body, 'BodyReadError': BodyReadError,
                          '_storage_identity': lambda: self.identity}
        source_functions('server/server.py', {'_handle_llm_gate_post'}, self.namespace, class_name='Handler')

    def post(self, body, gate):
        raw = json.dumps(body).encode()
        response = {}
        handler = SimpleNamespace(rfile=io.BytesIO(raw), headers={'Content-Length': str(len(raw)), 'Content-Type': 'application/json'},
                                  connection=mock.Mock(), _ok=lambda value: response.update(status=200, body=json.loads(value)),
                                  _err=lambda value, status: response.update(status=status, error=value))
        with mock.patch.dict(sys.modules, {'llm_gate': gate}):
            self.namespace['_handle_llm_gate_post'](handler)
        return response

    def test_external_gate_checks_expected_root_before_mutation(self):
        gate = mock.Mock()
        for op in ('acquire', 'release'):
            for expected in (None, str(uuid.uuid4())):
                with self.subTest(op=op, expected=expected):
                    result = self.post({'op': op, 'owner': 'wd', 'expectedDataRootId': expected}, gate)
                    self.assertEqual(409, result['status'])
        gate.acquire.assert_not_called()
        gate.release.assert_not_called()

    def test_busy_gate_does_not_overwrite_acquisition_failure_with_status_ok(self):
        gate = mock.Mock()
        gate.acquire.return_value = False
        gate.status.return_value = {'ok': True, 'owner': 'other', 'held': True}
        result = self.post({'op': 'acquire', 'owner': 'wd', 'expectedDataRootId': self.identity['dataRootId']}, gate)
        self.assertEqual(200, result['status'])
        self.assertFalse(result['body']['ok'])
        self.assertFalse(result['body']['acquired'])
        self.assertEqual(self.identity['dataRootId'], result['body']['dataRootId'])

    def test_release_reports_verified_result_and_root_identity(self):
        gate = mock.Mock()
        gate.status.return_value = {'ok': True, 'owner': None, 'held': False}
        result = self.post({'op': 'release', 'owner': 'wd', 'expectedDataRootId': self.identity['dataRootId']}, gate)
        gate.release.assert_called_once_with('wd')
        self.assertTrue(result['body']['released'])
        self.assertEqual(self.identity['dataRootId'], result['body']['dataRootId'])


if __name__ == '__main__':
    unittest.main()

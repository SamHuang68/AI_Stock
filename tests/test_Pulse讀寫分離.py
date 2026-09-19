"""真實 HTTP、SQLite 與受控工作驗證 Pulse 讀寫邊界。"""
import copy
import json
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_decision_http import st_server, dc, ew, _pulse
import decision_store
from pulse_updates import PulseUpdates


class PulseReadWriteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        self.db = str(folder / 'decision.db')
        self.queue_db = folder / 'updates.db'
        self.release = threading.Event()
        self.queue = PulseUpdates(db_path=str(self.queue_db), trace_path=str(folder / 'updates.jsonl'))
        self.delivery = Mock(return_value={'ok': True, 'delivered': 0})
        self.patches = [
            patch.object(dc, '_latest_context', None), patch.object(dc, '_latest_inputs', None),
            patch.object(dc, '_active_db_path', self.db), patch.object(dc, 'DB_PATH', self.db),
            patch.object(ew, 'DB_PATH', str(folder / 'signals.db')),
            patch.object(st_server, '_pulse_updates', self.queue),
            patch.dict('sys.modules', {
                'overnight_intraday': types.SimpleNamespace(latest_cached=lambda *a: None),
                'alert_daemon': types.SimpleNamespace(deliver_signal_events=self.delivery),
            }),
        ]
        for item in self.patches:
            item.start()
        self.http = st_server.ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.release.set()
        self.queue.stop(timeout=3)
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def request(self, path, data=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(self.base + path, data=(json.dumps(data).encode() if data is not None else None), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def publish(self, job_id='前版', guard=None):
        pulse = _pulse()
        pulse['updateJobId'] = job_id
        context = dc.build_decision_context(pulse)
        context = dc.publish_context(context, pulse=pulse, db_path=self.db,
                                     trace_path=str(Path(self.temp.name) / 'decision.jsonl'),
                                     publication_guard=guard)
        pulse['decisionSummary'] = dc.compact_context(context)
        return pulse

    def terminal(self, job_id):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            status, result = self.request('/pulse/update-status?jobId=' + job_id)
            self.assertEqual(status, 200)
            if result['job']['status'] not in ('queued', 'running'):
                return result['job']
            threading.Event().wait(0.02)
        self.fail('測試工作未在期限內結束')

    def test_cold_get_refresh_and_status_do_not_create_or_enqueue(self):
        with patch.object(st_server, '_build_pulse_update', side_effect=AssertionError('讀取不可建置')) as builder, \
                patch.object(self.queue, 'submit', side_effect=AssertionError('讀取不可提交')) as submit:
            for route in ('/pulse', '/pulse?refresh=1', '/pulse?refresh=true'):
                status, body = self.request(route)
                self.assertEqual(status, 200)
                self.assertFalse(body['ok'])
                self.assertEqual(body['error'], '尚未有已提交快照')
            self.assertEqual(self.request('/pulse/update-status')[0], 200)
            builder.assert_not_called()
            submit.assert_not_called()
        self.assertFalse(self.queue_db.exists())
        self.assertFalse(Path(self.db).exists())
        self.delivery.assert_not_called()

    def test_get_keeps_committed_identity_and_history_during_blocked_update(self):
        before = self.publish()
        rows = decision_store.read_rows(self.db, 'SELECT revision,snapshot_id FROM decision_commits')
        entered = threading.Event()
        def builder(job_id, guard):
            entered.set()
            self.release.wait(3)
            return self.publish(job_id, guard)
        self.queue.start(builder, dc.latest_pulse)
        self.assertTrue(entered.wait(2))
        started = time.monotonic()
        _, pulse = self.request('/pulse?refresh=1')
        _, full = self.request('/decision/context')
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(pulse['decisionSummary']['snapshotId'], before['decisionSummary']['snapshotId'])
        self.assertEqual(full['snapshotId'], before['decisionSummary']['snapshotId'])
        self.assertEqual(rows, decision_store.read_rows(self.db, 'SELECT revision,snapshot_id FROM decision_commits'))
        self.assertEqual(self.delivery.call_count, 1)
        code, accepted = self.request('/pulse/refresh', {})
        self.assertEqual(code, 202)
        self.assertTrue(accepted['coalesced'])
        self.release.set()
        job = self.terminal(accepted['job']['jobId'])
        self.assertEqual(job['status'], 'succeeded')
        _, pulse = self.request('/pulse')
        self.assertEqual(pulse['updateJobId'], job['jobId'])
        self.assertEqual(pulse['decisionSummary']['snapshotId'], job['result']['snapshotId'])

    def test_failure_is_queryable_and_does_not_replace_previous_snapshot(self):
        before = self.publish()
        def builder(job_id, guard):
            self.release.wait(2)
            raise OSError('注入更新失敗')
        self.queue.start(builder, dc.latest_pulse)
        code, accepted = self.request('/pulse/refresh', {})
        self.assertEqual(code, 202)
        self.release.set()
        job = self.terminal(accepted['job']['jobId'])
        self.assertEqual(job['status'], 'failed')
        self.assertIn('注入更新失敗', job['error'])
        _, after = self.request('/pulse')
        self.assertEqual(before['decisionSummary']['snapshotId'], after['decisionSummary']['snapshotId'])
        self.assertEqual(after['updateState']['job']['status'], 'failed')

    def test_post_validation_origin_and_unknown_status(self):
        self.assertEqual(self.request('/pulse/refresh', {'force': True})[0], 400)
        self.assertEqual(self.request('/pulse/refresh', [], origin=None)[0], 422)
        self.assertEqual(self.request('/pulse/refresh', {}, origin='https://example.invalid')[0], 403)
        self.assertEqual(self.request('/pulse/update-status?jobId=missing')[0], 404)
        self.assertEqual(self.request('/pulse/update-status?jobId=..%2Fsecret')[0], 400)
        self.assertFalse(self.queue_db.exists())

    def test_expired_publication_is_rejected_before_intent_warning_and_commit(self):
        before = self.publish()
        def expired():
            raise TimeoutError('更新已超過期限')
        with self.assertRaises(dc.SnapshotPublicationError):
            self.publish('逾時工作', expired)
        self.assertEqual(dc.latest_context()['snapshotId'], before['decisionSummary']['snapshotId'])
        self.assertEqual(decision_store.pending(self.db), [])
        self.assertEqual(self.delivery.call_count, 1)

    def test_gateway_reader_can_read_but_only_owner_can_submit(self):
        import private_web_gateway as gateway
        settings = types.SimpleNamespace(extra_read_paths=(), extra_control_paths=())
        for role in ('reader', 'owner'):
            self.assertTrue(gateway.route_permission('GET', '/pulse', role, settings))
            self.assertTrue(gateway.route_permission('GET', '/pulse/update-status', role, settings))
        self.assertFalse(gateway.route_permission('POST', '/pulse/refresh', 'reader', settings))
        self.assertTrue(gateway.route_permission('POST', '/pulse/refresh', 'owner', settings))

    def test_completed_job_lookup_finds_older_revision_without_advancing_latest(self):
        first = self.publish('工作甲')
        second = self.publish('工作乙')
        restored = dc.committed_pulse_for_job('工作甲')
        self.assertEqual(restored['decisionSummary']['snapshotId'], first['decisionSummary']['snapshotId'])
        self.assertEqual(dc.latest_context()['snapshotId'], second['decisionSummary']['snapshotId'])
        self.assertIsNone(dc.committed_pulse_for_job('未知工作'))


if __name__ == '__main__':
    unittest.main()

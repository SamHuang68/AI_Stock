"""只驗證 F06／F09／F11／F12；真實 HTTP 契約使用暫存來源與動態本機埠。"""
from __future__ import annotations

import copy
import http.client
import importlib
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class 警報與權限案例(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='st-alert-contract-')
        cls.root = Path(cls.directory.name)
        shutil.copytree(ROOT / 'server', cls.root / 'server',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(ROOT / 'VERSION', cls.root / 'VERSION')
        (cls.root / 'data').mkdir(exist_ok=True)
        cls.saved_path = sys.path[:]
        sys.path.insert(0, str(cls.root / 'server'))
        connect = socket.create_connection

        def local_only(address, *args, **kwargs):
            if address[0] not in ('127.0.0.1', 'localhost', '::1'):
                raise AssertionError('局部案例禁止連外。')
            return connect(address, *args, **kwargs)

        cls.network = mock.patch('socket.create_connection', side_effect=local_only)
        cls.network.start()
        cls.addClassCleanup(cls.network.stop)
        cls.addClassCleanup(lambda: setattr(sys, 'path', cls.saved_path))
        spec = importlib.util.spec_from_file_location('st_alert_review_http', cls.root / 'server/server.py')
        cls.backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.backend)
        cls.alert = cls.backend.alert_daemon
        if cls.alert is None:
            raise AssertionError('正式警報模組必須成功匯入，不能以 fixture 補上。')
        cls.gateway_module = importlib.import_module('private_web_gateway')

    @classmethod
    def tearDownClass(cls):
        logging.shutdown()
        cls.directory.cleanup()

    def setUp(self):
        self.case_directory = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case_directory.cleanup)
        case_root = Path(self.case_directory.name)
        self.rules = case_root / 'rules.json'
        self.config = case_root / 'config.json'
        self.secrets = case_root / 'secrets.bin'
        for field, value in (('RULES_FILE', self.rules), ('CONFIG_FILE', self.config),
                             ('SECRETS_FILE', self.secrets), ('LOG_DIR', case_root / 'logs')):
            patch = mock.patch.object(self.alert, field, str(value))
            patch.start()
            self.addCleanup(patch.stop)
        self.http = self.backend.ThreadingHTTPServer(('127.0.0.1', 0), self.backend.Handler)
        port_patch = mock.patch.object(self.backend, 'PORT', self.http.server_port)
        port_patch.start()
        self.addCleanup(port_patch.stop)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close_server, self.http, self.thread)
        gateway = self.gateway_module
        settings = gateway.Settings(
            listen_host='127.0.0.1', listen_port=0, upstream_host='127.0.0.1',
            upstream_port=self.http.server_port, owner_token='owner-fixture', read_token='reader-fixture',
            allowed_hosts=('127.0.0.1', 'localhost'), allowed_host_suffixes=(),
            max_body_bytes=65536, read_rate_per_minute=500, write_rate_per_minute=500,
            upstream_timeout_seconds=3, audit_path=case_root / 'audit.jsonl',
            access_request_path=case_root / 'requests.json', client_trace_path=case_root / 'trace.jsonl',
            extra_read_paths=('/macro/backfill-mix', '/macro/refresh'),
        )
        self.gateway = gateway.PrivateWebServer(('127.0.0.1', 0), gateway.Handler, settings)
        self.gateway_thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.gateway_thread.start()
        self.addCleanup(self._close_server, self.gateway, self.gateway_thread)

    @staticmethod
    def _close_server(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    def request(self, method, path, value=None, *, gateway=False, token=None, headers=None):
        port = self.gateway.server_port if gateway else self.http.server_port
        request_headers = {'Origin': f'http://127.0.0.1:{port}', **(headers or {})}
        body = None
        if value is not None:
            body = json.dumps(value).encode('utf-8')
            request_headers['Content-Type'] = 'application/json'
        if token:
            request_headers['Authorization'] = 'Bearer ' + token
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), json.loads(raw) if raw else None
        finally:
            connection.close()

    def test_規則版本衝突保留最新內容且可經閘道保存(self):
        original = [{'id': 'a', 'sym': '2330', 'price': 100, '_last_side': 'below'}]
        self.alert.save_rules(original)
        code, headers, rules = self.request('GET', '/alert/rules', gateway=True, token='owner-fixture')
        self.assertEqual(code, 200)
        self.assertEqual(rules, original)
        revision = headers['ETag']
        self.assertIn('ETag', headers['Access-Control-Expose-Headers'])
        latest = original + [{'id': 'b', 'sym': '2317', 'price': 50}]
        self.alert.save_rules(latest)
        code, _, body = self.request('POST', '/alert/rules', original, gateway=True,
                                     token='owner-fixture', headers={'If-Match': revision})
        self.assertEqual(code, 409, body)
        self.assertEqual(self.alert.load_rules(strict=True), latest)
        _, fresh_headers, fresh_rules = self.request('GET', '/alert/rules', gateway=True, token='owner-fixture')
        fresh_rules[0]['price'] = 101
        code, saved_headers, body = self.request('POST', '/alert/rules', fresh_rules, gateway=True,
                                                token='owner-fixture', headers={'If-Match': fresh_headers['ETag']})
        self.assertEqual(code, 200, body)
        self.assertTrue(body['ok'])
        self.assertEqual(saved_headers['ETag'], self.alert.rules_revision(fresh_rules))

    def test_毀損規則讀取失敗不變成空陣列覆寫(self):
        self.rules.write_text('{', encoding='utf-8')
        before = self.rules.read_bytes()
        code, _, body = self.request('GET', '/alert/rules')
        self.assertEqual(code, 503, body)
        code, _, _ = self.request('POST', '/alert/rules', [])
        self.assertGreaterEqual(code, 400)
        self.assertEqual(self.rules.read_bytes(), before)

    def test_背景合併保留新增與修改且不復活刪除(self):
        before = [{'id': 'a', 'price': 1}, {'id': 'b', 'price': 2}, {'id': 'c', 'price': 3}]
        evaluated = [dict(rule, _last_side='above') for rule in before]
        current = [{'id': 'b', 'price': 22}, before[2], {'id': 'd', 'price': 4}]
        self.alert.save_rules(current)
        self.alert._merge_rule_state(copy.deepcopy(before), evaluated)
        result = self.alert.load_rules(strict=True)
        self.assertEqual(result, [current[0], dict(before[2], _last_side='above'), current[2]])

    def test_相同設定保存保留最新評估狀態且版本不受輪詢影響(self):
        before = [{'id': 'a', 'price': 1, '_last_side': 'below', '_last_fired': 1}]
        self.alert.save_rules(before)
        revision = self.alert.rules_revision(before)
        self.alert._merge_rule_state(before, [dict(before[0], _last_side='above', _last_fired=9)])
        self.assertEqual(self.alert.rules_snapshot()[1], revision)
        self.alert.save_rules(before, expected_revision=revision)
        self.assertEqual(self.alert.load_rules(strict=True)[0]['_last_fired'], 9)

    def test_局部設定與遮罩不重寫金鑰且明確空字串才清除(self):
        value = copy.deepcopy(self.alert._DEFAULT_CONFIG)
        value['telegram']['bot_token'] = 'fixture-secret'
        value['telegram']['chat_id'] = 'fixture-chat'
        self.alert.save_config(value)
        secret_before = self.secrets.read_bytes()
        with mock.patch.object(self.alert, 'save_secret_json', wraps=self.alert.save_secret_json) as save:
            self.alert.update_config({'watch_enabled': True, 'telegram': {'bot_token': '***set***'}})
            save.assert_not_called()
        self.assertEqual(self.secrets.read_bytes(), secret_before)
        loaded = self.alert.load_config(strict=True)
        self.assertEqual(loaded['telegram']['bot_token'], 'fixture-secret')
        self.assertEqual(loaded['telegram']['chat_id'], 'fixture-chat')
        self.assertTrue(loaded['watch_enabled'])
        for path in (self.config, Path(str(self.config) + '.bak')):
            self.assertNotIn('fixture-secret', path.read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):
            self.alert.update_config({'telegram': {'bot_token': None}})
        self.alert.update_config({'telegram': {'bot_token': ''}})
        self.assertEqual(self.alert.load_config(strict=True)['telegram']['bot_token'], '')

    def test_解密失敗中止讀寫並保留設定原檔(self):
        self.alert.save_config(copy.deepcopy(self.alert._DEFAULT_CONFIG))
        self.secrets.write_bytes(b'fixture-protected')
        before = {path: path.read_bytes() for path in (self.config, self.secrets)}
        with mock.patch.object(self.alert, 'load_secret_json', side_effect=OSError('fixture')):
            code, _, _ = self.request('GET', '/alert/config')
            self.assertEqual(code, 503)
            code, _, _ = self.request('POST', '/alert/config', {'watch_enabled': True})
            self.assertEqual(code, 500)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_有副作用的總經讀取在後端與閘道均拒絕(self):
        for path in ('/macro/refresh', '/macro/refresh/ALL', '/macro/backfill-mix', '/macro/track/backfill-mix'):
            with self.subTest(path=path):
                code, headers, _ = self.request('GET', path)
                self.assertEqual(code, 405)
                self.assertEqual(headers['Allow'], 'POST')
                for role in ('owner-fixture', 'reader-fixture'):
                    code, _, _ = self.request('GET', path, gateway=True, token=role)
                    self.assertEqual(code, 403)
        code, _, _ = self.request('POST', '/macro/backfill-mix', {}, gateway=True, token='reader-fixture')
        self.assertEqual(code, 403)

    def test_本機回補保留受控寫入且驗證輸入(self):
        macro = importlib.import_module('macro_track')
        called = threading.Event()

        def backfill(start, *, step_days):
            self.assertEqual(start.isoformat(), '2026-10-01')
            self.assertEqual(step_days, 3)
            called.set()
            return 1

        with mock.patch.object(macro, 'backfill_margin_mix', side_effect=backfill) as action:
            code, _, _ = self.request('POST', '/macro/backfill-mix', {'start': 'invalid'})
            self.assertEqual(code, 400)
            action.assert_not_called()
            code, _, body = self.request('POST', '/macro/track/backfill-mix', {'start': '2026-10-01', 'step': 3})
            self.assertEqual(code, 200, body)
            self.assertTrue(body['started'])
            self.assertTrue(called.wait(2))
            action.assert_called_once()


if __name__ == '__main__':
    unittest.main()

"""Read-only launcher checks with synthetic responses; never start a service."""
import json
import os
from pathlib import Path
import sys
import subprocess
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT / 'tests'))
import local_release as local
import private_web_host as host
import private_web_gateway as gateway
from test_external_runtime_release import fixture, write


def gateway_settings(code):
    return SimpleNamespace(
        access_request_path=code / 'data' / 'private_web_access_requests.json',
        audit_path=code / 'logs' / 'private_web_audit.jsonl',
        client_trace_path=code / 'logs' / 'private_web_client.jsonl')


class SharedBackendLauncherTests(unittest.TestCase):
    def test_external_gateway_startup_rejects_protected_outputs_before_writing(self):
        fields = ('access_request_path', 'audit_path', 'client_trace_path', 'pid', 'startup')
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, recovery = fixture(Path(tmp).resolve())
            code = install / 'current'
            write(code / 'runtime_storage_capability.json', {'schemaVersion': 1,
                  'capabilityVersion': 1, 'storageModes': ['external']})
            write(recovery / 'sentinel.json', {'sentinel': 'recovery'})
            sentinels = (runtime / 'business.json', recovery / 'sentinel.json')
            before = {path: path.read_bytes() for path in sentinels}
            targets = (*sentinels, runtime, recovery, runtime.parent)
            for field in fields:
                for target in targets:
                    with self.subTest(field=field, target=target.name):
                        settings = gateway_settings(code)
                        env = {}
                        startup = code / 'logs' / 'private_web_gateway_startup.jsonl'
                        if field == 'pid':
                            env['ST_WEB_PID_PATH'] = str(target)
                        elif field == 'startup':
                            startup = target
                        else:
                            setattr(settings, field, target)
                        with patch.object(gateway, 'ROOT', code), \
                             patch.object(gateway, 'STARTUP_TRACE', startup), \
                             patch.dict(os.environ, env), \
                             patch.object(gateway.Settings, 'load', return_value=settings), \
                             patch.object(gateway, '_serve_gateway') as serve:
                            with self.assertRaisesRegex(RuntimeError, 'protected'):
                                gateway.main()
                            serve.assert_not_called()
                        self.assertEqual({path: path.read_bytes() for path in sentinels}, before)
                        self.assertFalse((code / 'data').exists())
                        self.assertFalse((code / 'logs').exists())

    def test_external_gateway_startup_rejects_hard_link_output_aliases(self):
        for field in ('access_request_path', 'audit_path', 'client_trace_path', 'pid', 'startup'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp, \
                 patch.dict(os.environ, {}, clear=True):
                install, runtime, _ = fixture(Path(tmp).resolve())
                code = install / 'current'
                write(code / 'runtime_storage_capability.json', {'schemaVersion': 1,
                      'capabilityVersion': 1, 'storageModes': ['external']})
                sentinel = runtime / 'unregistered.json'
                write(sentinel, {'sentinel': 'keep'})
                before = sentinel.read_bytes()
                alias = code / 'output.json'
                os.link(sentinel, alias)
                settings = gateway_settings(code)
                env = {}
                startup = code / 'logs' / 'private_web_gateway_startup.jsonl'
                if field == 'pid':
                    env['ST_WEB_PID_PATH'] = str(alias)
                elif field == 'startup':
                    startup = alias
                else:
                    setattr(settings, field, alias)
                with patch.object(gateway, 'ROOT', code), \
                     patch.object(gateway, 'STARTUP_TRACE', startup), \
                     patch.dict(os.environ, env), \
                     patch.object(gateway.Settings, 'load', return_value=settings), \
                     patch.object(gateway, '_serve_gateway') as serve:
                    with self.assertRaisesRegex(RuntimeError, 'hard-link'):
                        gateway.main()
                    serve.assert_not_called()
                self.assertEqual(sentinel.read_bytes(), before)
                self.assertFalse((code / 'data').exists())
                self.assertFalse((code / 'logs').exists())

    def test_external_host_rejects_log_and_pid_aliases_before_probe_or_spawn(self):
        outputs = ('logs/private_web_host.jsonl', 'logs/private_web_backend.log',
                   'logs/private_web_gateway.log', 'data/private_web_host.pid')
        for relative in outputs:
            with self.subTest(output=relative), tempfile.TemporaryDirectory() as tmp, \
                 patch.dict(os.environ, {}, clear=True):
                install, runtime, _ = fixture(Path(tmp).resolve())
                code = install / 'current'
                (code / 'server').mkdir(parents=True)
                shutil.copy2(ROOT / 'server/data_paths.py', code / 'server/data_paths.py')
                write(code / 'runtime_storage_capability.json', {'schemaVersion': 1,
                      'capabilityVersion': 1, 'storageModes': ['external']})
                sentinel = runtime / 'unregistered.json'
                write(sentinel, {'sentinel': 'keep'})
                before = sentinel.read_bytes()
                alias = code / relative
                alias.parent.mkdir(parents=True, exist_ok=True)
                os.link(sentinel, alias)
                with patch.object(host, 'ROOT', code), patch.object(host, 'LOGS', code / 'logs'), \
                     patch.object(host, '_health_payload') as probe, patch.object(host, '_spawn') as spawn:
                    with self.assertRaisesRegex(RuntimeError, 'hard-link'):
                        host.run(backend_port=18435, gateway_port=18434, max_restarts=1)
                    probe.assert_not_called()
                    spawn.assert_not_called()
                self.assertEqual(sentinel.read_bytes(), before)

    def test_external_host_main_rejects_a_pid_alias_before_any_write(self):
        # main() 在呼叫 run() 之前就會建立並覆寫 PID 檔；PID 檔若是受保護檔案的硬連結，必須在截斷之前被拒絕。
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, _ = fixture(Path(tmp).resolve())
            code = install / 'current'
            (code / 'server').mkdir(parents=True)
            shutil.copy2(ROOT / 'server/data_paths.py', code / 'server/data_paths.py')
            write(code / 'runtime_storage_capability.json', {'schemaVersion': 1,
                  'capabilityVersion': 1, 'storageModes': ['external']})
            sentinel = runtime / 'unregistered.json'
            write(sentinel, {'sentinel': 'keep'})
            before = sentinel.read_bytes()
            alias = code / 'data' / 'private_web_host.pid'
            alias.parent.mkdir(parents=True, exist_ok=True)
            os.link(sentinel, alias)
            with patch.object(host, 'ROOT', code), patch.object(host, 'LOGS', code / 'logs'),                  patch.object(sys, 'argv', ['private_web_host.py']),                  patch.object(host, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'hard-link'):
                    host.main()
                run.assert_not_called()
            self.assertEqual(sentinel.read_bytes(), before, '受保護檔案在檢查之前被改寫')

    def test_external_host_requires_installation_sidecar_for_gateway(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp).resolve()
            install, runtime, _ = fixture(root)
            code = install / 'current'
            (code / 'server').mkdir(parents=True)
            shutil.copy2(ROOT / 'server/data_paths.py', code / 'server/data_paths.py')
            write(code / 'runtime_storage_capability.json', {'schemaVersion': 1,
                  'capabilityVersion': 1, 'storageModes': ['external']})
            binding_path = root / 'explicit-binding.json'
            (install / 'runtime_binding.json').rename(binding_path)
            with patch.object(host, 'ROOT', code), patch.dict(os.environ,
                    {'ST_DATA_BINDING': str(binding_path), 'ST_DATA_ROOT': str(runtime), 'ST_RUNTIME_ROLE': 'backend'}):
                with self.assertRaisesRegex(RuntimeError, 'managed runtime_binding.json'):
                    host._runtime_environment(18435, 18434)
            self.assertFalse((code / 'logs').exists())
            self.assertFalse((code / 'data').exists())

    def test_external_gateway_can_save_auth_requests_but_cannot_write_business_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, _ = fixture(Path(tmp).resolve())
            code = install / 'current'
            write(code / 'runtime_storage_capability.json', {'schemaVersion': 1,
                  'capabilityVersion': 1, 'storageModes': ['external']})
            auth = code / 'data' / 'private_web_access_requests.json'
            settings = gateway_settings(code)
            with patch.object(gateway, 'ROOT', code), \
                 patch.object(gateway, 'STARTUP_TRACE', code / 'logs' / 'private_web_gateway_startup.jsonl'):
                lease = gateway._gateway_auth_bootstrap(settings)
            self.assertFalse((code / 'logs').exists())
            try:
                store = gateway.AccessRequestStore(auth)
                row, created = store.create(display_name='Fixture User', contact_email='fixture@example.com',
                    tailscale_email='fixture@example.com', platform='windows')
                self.assertTrue(created)
                store.update_status(row['id'], status='approved')
                self.assertEqual(store.list_requests()[0]['status'], 'approved')
                from atomic_store import atomic_write_json
                for forbidden in (runtime / 'business.json', code / 'data' / 'market.db'):
                    with self.subTest(path=forbidden.name), self.assertRaises(RuntimeError):
                        atomic_write_json(forbidden, {'mustNotWrite': True})
                self.assertEqual(json.loads((runtime / 'business.json').read_text()), {'sentinel': 'keep'})
                self.assertFalse((code / 'data' / 'market.db').exists())
            finally:
                lease.close()

    def test_host_only_backend_inherits_business_binding(self):
        source = {'ST_DATA_ROOT': 'fixture-runtime', 'ST_DATA_BINDING': 'fixture-binding',
                  'ST_RUNTIME_ROLE': 'backend', 'ST_WEB_CONFIG': 'existing-auth-config'}
        backend, proxy = host._child_environments(source, 18435, 18434, 'fixture-instance')
        for key in ('ST_DATA_ROOT', 'ST_DATA_BINDING', 'ST_RUNTIME_ROLE'):
            self.assertEqual(backend[key], source[key])
            self.assertNotIn(key, proxy)
        self.assertEqual(proxy['ST_WEB_CONFIG'], source['ST_WEB_CONFIG'])
        self.assertEqual(proxy['ST_WEB_UPSTREAM'], 'http://127.0.0.1:18435')
        self.assertEqual(source['ST_RUNTIME_ROLE'], 'backend')

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell launcher contract')
    def test_powershell_shared_check_returns_before_local_receipts_locks_or_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / 'local_install.json', {'python': sys.executable, 'storageMode': 'external'})
            # Stub only the Python CLI boundary; execute the real PowerShell entry.
            (root / 'local_release.py').write_text(
                "import json,sys\n"
                "assert sys.argv[-1] == 'shared-status', sys.argv\n"
                "print(json.dumps({'storageMode':'external','runtimeRole':'client',"
                "'publicUrl':'http://127.0.0.1:1'}))\n", encoding='utf-8')
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('ST_DATA_') and key != 'ST_RUNTIME_ROLE'}
            powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
            result = subprocess.run([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(ROOT / 'scripts/start_local.ps1'), '-InstallRoot', str(root), '-CheckOnly', '-NoBrowser'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({p.name for p in root.iterdir()}, {'local_install.json', 'local_release.py'})

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell launcher contract')
    def test_go_worktree_refuses_production_binding_before_python_pin_or_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            (root / 'scripts/go.ps1').write_bytes((ROOT / 'scripts/go.ps1').read_bytes())
            (root / 'build_v2.py').write_text("raise AssertionError('must not build')", encoding='utf-8')
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith('ST_DATA_') and key != 'ST_RUNTIME_ROLE'}
            env.update(ST_DATA_BINDING=str(root / 'runtime_binding.json'), ST_RUNTIME_ROLE='backend')
            powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
            result = subprocess.run([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(root / 'scripts/go.ps1'), '-Worktree', '-NoBrowser'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ST-RUNTIME-GUARD', result.stderr)
            self.assertFalse((root / 'data').exists())

    def test_host_validates_binding_before_probe_or_spawn(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ST_DATA_ROOT': tmp}, clear=True), \
             patch.object(host, '_health_payload') as probe, patch.object(host, '_spawn') as spawn:
            with self.assertRaises(RuntimeError):
                host.run(backend_port=18435, gateway_port=18434, max_restarts=1)
            probe.assert_not_called()
            spawn.assert_not_called()

    def test_gateway_health_publishes_only_actual_upstream_identity(self):
        upstream = {'ok': True, 'dataRootId': '7bb30b9a-3e26-448f-8579-70c85e204aa4',
                    'storageMode': 'external', 'runtimeRole': 'backend', 'capabilityVersion': 1,
                    'runtimeCommit': 'a' * 40, 'dataRoot': 'secret-path', 'token': 'secret-token'}
        response = Mock(status=200)
        response.read.return_value = json.dumps(upstream).encode()
        handler = gateway.Handler.__new__(gateway.Handler)
        handler.server = SimpleNamespace(settings=SimpleNamespace(
            upstream_host='127.0.0.1', upstream_port=1,
            mode='isolated-host', instance_id='fixture'))
        handler._json = Mock()
        with patch.object(gateway.http.client, 'HTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response
            handler._gateway_health()
        payload = handler._json.call_args.args[1]
        self.assertIs(payload['ok'], True)
        self.assertIs(payload['upstream'], True)
        self.assertEqual(payload['gateway'], 'private-web')
        self.assertEqual(payload['mode'], 'isolated-host')
        self.assertEqual(payload['instance'], 'fixture')
        self.assertEqual(payload['runtime'], {
            'dataRootId': upstream['dataRootId'], 'storageMode': 'external',
            'runtimeRole': 'backend', 'capabilityVersion': 1, 'runtimeCommit': 'a' * 40})
        self.assertNotIn('secret', json.dumps(payload))
        self.assertEqual(payload['capabilities'], {'wavedeck': False, 'remoteTrading': False})

    def test_shared_client_refuses_missing_health_identity_and_capability_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, _ = fixture(Path(tmp).resolve())
            config = {'storageMode': 'external', 'dataBinding': str(install / 'runtime_binding.json'),
                      'sourceInstallRoot': str(install)}
            write(install / 'current' / 'runtime_storage_capability.json', {'schemaVersion': 1,
                  'capabilityVersion': 1, 'storageModes': ['external']})
            write(install / 'current' / local.MANIFEST, {'commit': 'a' * 40})
            with patch.object(local, '_shared_health', return_value={'ok': True}) as request:
                with self.assertRaisesRegex(RuntimeError, 'identity'):
                    local.shared_client_status(install, config)
            identity = json.loads((runtime / '.st-data-root.json').read_text())['dataRootId']
            health = {'ok': True, 'gateway': 'private-web', 'upstream': True,
                      'runtime': {'storageMode': 'external', 'runtimeRole': 'backend',
                                  'dataRootId': identity, 'capabilityVersion': 1, 'runtimeCommit': 'a' * 40},
                      'capabilities': {'wavedeck': False, 'remoteTrading': False}}
            with patch.object(local, '_shared_health', return_value=health), \
                 patch.object(local, 'backup_data') as backup, patch.object(local, 'assert_stopped') as stop:
                with self.assertRaisesRegex(RuntimeError, 'capabilit'):
                    local.shared_client_status(install, config)
            backup.assert_not_called()
            stop.assert_not_called()
            self.assertFalse((install / '.launcher.lock').exists())

    def test_shared_client_returns_gateway_only_after_matching_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, _ = fixture(Path(tmp).resolve())
            config = {'storageMode': 'external', 'dataBinding': str(install / 'runtime_binding.json'),
                      'sourceInstallRoot': str(install)}
            write(install / 'current' / 'runtime_storage_capability.json', {'schemaVersion': 1,
                  'capabilityVersion': 1, 'storageModes': ['external']})
            write(install / 'current' / local.MANIFEST, {'commit': 'a' * 40})
            identity = json.loads((runtime / '.st-data-root.json').read_text())['dataRootId']
            health = {'ok': True, 'gateway': 'private-web', 'upstream': True,
                      'runtime': {'storageMode': 'external', 'runtimeRole': 'backend',
                                  'dataRootId': identity, 'capabilityVersion': 1, 'runtimeCommit': 'a' * 40},
                      'capabilities': {'wavedeck': True, 'remoteTrading': True}}
            with patch.object(local, '_shared_health', return_value=health):
                result = local.shared_client_status(install, config)
            self.assertEqual(result['publicUrl'], 'http://127.0.0.1:18434')
            self.assertFalse(result['needsSync'])
            self.assertNotIn('dataRoot', result)
            for invalid in (False, None, 1, 'true'):
                with self.subTest(ok=invalid), patch.object(local, '_shared_health', return_value={**health, 'ok': invalid}):
                    with self.assertRaisesRegex(RuntimeError, 'identity'):
                        local.shared_client_status(install, config)


if __name__ == '__main__':
    unittest.main()

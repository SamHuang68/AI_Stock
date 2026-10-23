"""External release fixtures: no archive, server, network, or production paths."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import private_web_release as release
import local_release as local


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def fixture(root):
    install = root / 'install'
    runtime = root / 'storage' / 'runtime'
    recovery = runtime.with_name('recovery')
    identity = str(uuid.uuid4())
    write(runtime / '.st-data-root.json', {'schemaVersion': 1, 'kind': 'production', 'dataRootId': identity})
    write(runtime / '.st-cutover.json', {'schemaVersion': 1, 'dataRootId': identity,
          'state': 'ready', 'capabilityVersion': 1, 'requiredPaths': ['business.json']})
    write(runtime / 'business.json', {'sentinel': 'keep'})
    write(install / 'runtime_binding.json', {'schemaVersion': 1, 'storageMode': 'external',
          'dataRoot': str(runtime), 'dataRootId': identity, 'recoveryRoot': str(recovery),
          'capabilityVersion': 1, 'allowedCodeRoots': [str(install / 'current')],
          'backendUrl': 'http://127.0.0.1:18435', 'publicUrl': 'http://127.0.0.1:18434'})
    return install, runtime, recovery


class ExternalRuntimeReleaseTests(unittest.TestCase):
    def test_external_release_uses_only_installation_administrative_lock(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, _ = fixture(Path(tmp).resolve())
            before = {path.name: path.read_bytes() for path in runtime.iterdir()}
            with patch.dict(os.environ, {'ST_DATA_BINDING': str(install / 'runtime_binding.json'),
                                        'ST_DATA_ROOT': str(runtime), 'ST_RUNTIME_ROLE': 'backend'}):
                with release._release_lock(install):
                    self.assertTrue((install / '.locks/private-web-release.lock').is_file())
                    self.assertFalse((runtime / 'runtime_locks').exists())
            self.assertEqual({path.name: path.read_bytes() for path in runtime.iterdir()}, before)

    def test_legacy_local_cannot_sync_from_an_external_private_web_installation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp).resolve()
            source, _, _ = fixture(root)
            local_install = root / 'local'
            config = {'sourceInstallRoot': str(source), 'originalCheckout': str(root / 'checkout'),
                      'python': sys.executable}
            with patch.object(local, 'backup_data') as backup, patch.object(local, 'assert_stopped') as stop:
                with self.assertRaisesRegex(RuntimeError, 'shared client'):
                    local.sync_install(local_install, release, config)
            backup.assert_not_called()
            stop.assert_not_called()
            self.assertFalse(local_install.exists())

    def test_external_receipt_without_binding_never_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install = Path(tmp).resolve() / 'install'
            write(install / 'current' / release.MANIFEST_NAME,
                  {'storageBinding': {'storageMode': 'external'}})
            with self.assertRaisesRegex(RuntimeError, 'binding'):
                release._release_binding(install)

    def test_environment_override_conflict_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, _, _ = fixture(Path(tmp).resolve())
            with patch.dict(os.environ, {'ST_DATA_ROOT': str(Path(tmp).resolve() / 'wrong')}):
                with self.assertRaisesRegex(RuntimeError, 'conflict'):
                    release._release_binding(install)

    def test_binding_requires_ready_existing_data_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, _ = fixture(Path(tmp).resolve())
            (runtime / '.st-cutover.json').unlink()
            with self.assertRaises(RuntimeError):
                release._release_binding(install)
            self.assertFalse((install / 'backups').exists())

    def test_release_refuses_root_overlap_even_outside_reserved_path_names(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, _ = fixture(Path(tmp).resolve())
            with self.assertRaisesRegex(RuntimeError, 'protected'):
                release._release_preflight(install, runtime.parent)
            self.assertTrue((runtime / 'business.json').is_file())

    def test_external_rejects_old_release_before_creating_candidate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, _, _ = fixture(Path(tmp).resolve())
            old = install / 'old'
            old.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'capability'):
                release._release_preflight(install, old, release_tree=old)
            self.assertFalse((install / 'backups').exists())

    def test_legacy_transition_cannot_recover_under_external_binding(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, _, _ = fixture(Path(tmp).resolve())
            write(install / release.TRANSITION_NAME, {'candidate': 'candidate-1', 'previous': 'backups/previous-1'})
            with self.assertRaisesRegex(RuntimeError, 'binding'):
                release._recover_transition(install)
            self.assertTrue((install / release.TRANSITION_NAME).exists())

    def test_external_switch_does_not_seed_business_data(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            install, runtime, recovery = fixture(Path(tmp).resolve())
            candidate = install / 'candidate-1'
            write(candidate / 'runtime_storage_capability.json', {'schemaVersion': 1,
                  'capabilityVersion': 1, 'storageModes': ['external']})
            write(candidate / 'code.json', {'version': 2})
            write(install / 'current' / 'data' / 'private_web.json', {'private': 'keep'})
            seeds = install / 'seeds' / 'data'
            write(seeds / 'unexpected.json', {'mustNotSeed': True})
            before = (runtime / 'business.json').read_bytes()
            release._switch_tree(install, candidate, install / 'backups' / 'previous-1', seed_source=seeds)
            self.assertEqual((runtime / 'business.json').read_bytes(), before)
            self.assertFalse((runtime / 'unexpected.json').exists())
            self.assertFalse((install / 'current' / 'data' / 'unexpected.json').exists())
            self.assertTrue((install / 'current' / 'data' / 'private_web.json').is_file())
            self.assertFalse(recovery.exists())

    def test_external_local_sync_does_not_copy_or_backup_data(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp).resolve()
            config = {'storageMode': 'external', 'dataBinding': str(root / 'binding.json')}
            with patch.object(local, 'shared_client_status', return_value={'storageMode': 'external'}) as status, \
                 patch.object(local, 'backup_data') as backup, patch.object(local, 'import_stage') as copy:
                result = local.sync_install(root / 'local', release, config)
            status.assert_called_once()
            backup.assert_not_called()
            copy.assert_not_called()
            self.assertFalse(result['changed'])


if __name__ == '__main__':
    unittest.main()

"""Runtime binding and ownership tests using small, synthetic local fixtures."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import uuid

from server import data_paths as paths
from server import runtime_storage as storage


class RuntimeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.code = self.root / 'managed-current'
        self.data = self.root / 'runtime'
        self.code.mkdir()
        self.data.mkdir()
        self.root_id = str(uuid.uuid4())
        self.config = {'schemaVersion': 1, 'storageMode': 'external',
                       'dataRoot': str(self.data), 'dataRootId': self.root_id,
                       'recoveryRoot': str(self.root / 'recovery'), 'capabilityVersion': 1,
                       'allowedCodeRoots': [str(self.code)],
                       'backendUrl': 'http://127.0.0.1:18435', 'publicUrl': 'http://127.0.0.1:18434'}
        self.write(self.data / paths.IDENTITY_FILE,
                   {'schemaVersion': 1, 'dataRootId': self.root_id, 'kind': 'production'})
        self.write(self.data / paths.CUTOVER_FILE,
                   {'schemaVersion': 1, 'dataRootId': self.root_id, 'state': 'ready',
                    'capabilityVersion': 1, 'requiredPaths': ['market.db']})
        # Binding validation checks presence, without opening SQLite or trying
        # to generate an empty schema. The fixture deliberately isn't a DB.
        (self.data / 'market.db').write_bytes(b'fixture-data-not-opened')
        self.write(self.code / paths.CAPABILITY_FILE,
                   {'schemaVersion': 1, 'capabilityVersion': 1, 'storageModes': ['legacy', 'external', 'fixture']})
        self.binding_file = self.root / 'binding-input.json'
        self.write(self.binding_file, self.config)
        self.patches = [mock.patch.object(sys, '_st_runtime_binding', None, create=True),
                        mock.patch.object(sys, '_st_runtime_leases', {}, create=True),
                        mock.patch.object(sys, '_st_gateway_auth', None, create=True),
                        mock.patch.object(sys, '_st_runtime_lease_guard', threading.RLock(), create=True)]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.close_leases)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    @staticmethod
    def close_leases():
        auxiliary = getattr(sys, '_st_gateway_auth', None)
        if auxiliary is not None:
            auxiliary.close()
        for lease in list(sys._st_runtime_leases.values()):
            lease.close()

    def binding(self, *, role='backend', **env):
        return paths.resolve_binding(code_root=self.code,
                                     environ={'ST_RUNTIME_ROLE': role, **env}, installation_binding=self.config)

    def fixture(self):
        directory = self.root / 'fixture'
        directory.mkdir()
        self.write(directory / paths.FIXTURE_FILE,
                   {'schemaVersion': 1, 'kind': 'fixture', 'fixtureId': str(uuid.uuid4())})
        return paths.validate_binding(paths.resolve_binding(code_root=self.code, environ={}, fixture_root=directory))

    def test_legacy_keeps_code_data_logs_and_constructor_override_priority(self):
        bound = paths.resolve_binding(code_root=self.code, environ={'ST_UPDATE_JOBS_DB': str(self.root / 'env.db')})
        self.assertEqual('legacy', bound.mode)
        self.assertEqual(self.code / 'data' / 'market.db', paths.data_path('market.db', binding=bound))
        self.assertEqual(self.code / 'logs' / 'boot.log', paths.log_path('boot.log', binding=bound))
        self.assertEqual(self.root / 'arg.db', paths.data_path('jobs.db', binding=bound,
                         override=self.root / 'arg.db', override_env='ST_UPDATE_JOBS_DB'))
        storage.assert_write_allowed(self.root / 'other' / 'file.tmp', binding=bound)
        self.assertFalse((self.root / 'other').exists())

    def test_incomplete_external_never_falls_back_or_creates_root(self):
        missing = self.root / 'missing'
        for env in ({'ST_DATA_ROOT': str(missing)}, {'ST_RUNTIME_ROLE': 'backend'},
                    {'ST_RUNTIME_ROLE': 'unknown'}, {'ST_DATA_ROOT': ''}):
            with self.subTest(env=env), self.assertRaises(paths.BindingError):
                paths.resolve_binding(code_root=self.code, environ=env)
        config = {**self.config, 'dataRoot': str(missing)}
        bound = paths.resolve_binding(code_root=self.code, environ={'ST_RUNTIME_ROLE': 'backend'}, installation_binding=config)
        with self.assertRaises(paths.BindingError):
            paths.validate_binding(bound)
        self.assertFalse(missing.exists())

    def test_installed_sidecar_or_receipt_prevents_missing_environment_downgrade(self):
        sidecar = self.root / 'runtime_binding.json'
        self.write(sidecar, self.config)
        with self.assertRaises(paths.BindingError):
            paths.resolve_binding(code_root=self.code, environ={})
        resolved = paths.resolve_binding(code_root=self.code, environ={'ST_RUNTIME_ROLE': 'backend'})
        self.assertEqual(self.root_id, resolved.data_root_id)
        sidecar.unlink()
        self.write(self.code / '.private_web_release.json',
                   {'storageBinding': {'storageMode': 'external', 'dataRootId': self.root_id, 'capabilityVersion': 1}})
        with self.assertRaises(paths.BindingError):
            paths.resolve_binding(code_root=self.code, environ={})
        self.assertFalse((self.code / 'data').exists())

    def test_conflicting_bindings_and_relative_overrides_are_refused(self):
        with self.assertRaises(paths.BindingError):
            self.binding(ST_DATA_ROOT=str(self.root / 'other'))
        other = {**self.config, 'dataRootId': str(uuid.uuid4())}
        with self.assertRaises(paths.BindingError):
            paths.resolve_binding(code_root=self.code, environ={'ST_RUNTIME_ROLE': 'backend', 'ST_DATA_BINDING': str(self.binding_file)}, installation_binding=other)
        bound = self.binding()
        with self.assertRaises(paths.BindingError):
            paths.data_path('market.db', binding=bound, override=os.path.relpath(self.data / 'market.db'))
        with self.assertRaises(paths.BindingError):
            paths.data_path('market.db', binding=bound, override=self.root / 'other.db')
        self.assertEqual(self.data / 'market.db', paths.data_path('market.db', binding=bound, override=self.data / 'market.db'))

    def test_valid_binding_is_read_only_and_identity_is_public_without_paths(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        bound = paths.validate_binding(self.binding())
        identity = paths.public_identity(bound)
        self.assertEqual(self.root_id, identity['dataRootId'])
        self.assertEqual('backend', identity['runtimeRole'])
        self.assertNotIn('dataRoot', identity)
        self.assertEqual((self.data, self.root / 'recovery'), paths.protected_roots(bound))
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))

    def test_cutover_identity_and_required_file_are_mandatory(self):
        bound = self.binding()
        receipt = self.data / paths.CUTOVER_FILE
        valid = json.loads(receipt.read_text(encoding='utf-8'))
        for changed in ({**valid, 'state': 'pending'}, {**valid, 'dataRootId': str(uuid.uuid4())},
                        {**valid, 'requiredPaths': []}, {**valid, 'requiredPaths': ['missing.db']},
                        {**valid, 'requiredPaths': ['../managed-current/runtime_storage_capability.json']}):
            self.write(receipt, changed)
            with self.subTest(receipt=changed), self.assertRaises(paths.BindingError):
                paths.validate_binding(bound)
        self.write(receipt, valid)
        self.write(self.data / paths.IDENTITY_FILE, {'schemaVersion': 1, 'dataRootId': str(uuid.uuid4()), 'kind': 'production'})
        with self.assertRaises(paths.BindingError):
            paths.validate_binding(bound)

    def test_worktree_and_nested_recovery_cannot_become_production_writer(self):
        bound = replace(self.binding(), code_root=self.root / 'worktree')
        with self.assertRaises(paths.BindingError):
            paths.validate_binding(bound)
        # Release inspection may read identity for a not-yet-promoted tree,
        # but bootstrap still performs the full check.
        paths.validate_binding(bound, check_code_root=False)
        with self.assertRaises(paths.BindingError):
            storage.bootstrap_runtime(binding=bound)
        with self.assertRaises(paths.BindingError):
            paths.validate_binding(replace(self.binding(), recovery_root=self.data / 'backups'))

    def test_boot_required_paths_must_exist_and_be_registered_in_cutover(self):
        required = ['wavedeck/runtime_state.json', 'wavedeck/wavedeck_config.json']
        bound = self.binding(role='wavedeck')
        (self.data / 'wavedeck').mkdir()
        for relative in required:
            self.write(self.data / relative, {'fixture': True})
        with self.assertRaises(paths.BindingError):
            paths.require_runtime_paths(required, binding=bound)
        receipt_path = self.data / paths.CUTOVER_FILE
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['requiredPaths'].extend(required)
        self.write(receipt_path, receipt)
        paths.require_runtime_paths(required, binding=bound)
        (self.data / required[0]).unlink()
        with self.assertRaises(paths.BindingError):
            paths.require_runtime_paths(required, binding=bound)
        self.assertFalse((self.data / required[0]).exists())

    def test_fixture_requires_marker_and_cannot_use_production_ancestor(self):
        unmarked = self.root / 'unmarked'
        unmarked.mkdir()
        bound = paths.resolve_binding(code_root=self.code, environ={}, fixture_root=unmarked)
        with self.assertRaises(paths.BindingError):
            paths.validate_binding(bound)
        self.assertEqual([], list(unmarked.iterdir()))
        nested = self.data / 'fixture'
        nested.mkdir()
        self.write(nested / paths.FIXTURE_FILE, {'schemaVersion': 1, 'kind': 'fixture', 'fixtureId': str(uuid.uuid4())})
        with self.assertRaises(paths.BindingError):
            paths.validate_binding(paths.resolve_binding(code_root=self.code, environ={}, fixture_root=nested))
        self.assertEqual('fixture', self.fixture().mode)

    def test_fixture_rejects_old_unmarked_installed_root_without_mutation(self):
        local = self.root / 'local-app-data'
        previous = local / 'StockTerminalLocal' / 'current' / 'data'
        previous.mkdir(parents=True)
        self.write(previous / paths.FIXTURE_FILE, {'schemaVersion': 1, 'kind': 'fixture', 'fixtureId': str(uuid.uuid4())})
        sentinel = previous / 'market.db'
        sentinel.write_bytes(b'keep-original')
        with mock.patch.dict(os.environ, {'LOCALAPPDATA': str(local)}):
            with self.assertRaises(paths.BindingError):
                paths.validate_binding(paths.resolve_binding(code_root=self.code, environ={}, fixture_root=previous))
        self.assertEqual(b'keep-original', sentinel.read_bytes())
        self.assertFalse((previous / 'runtime_locks').exists())

    def test_relative_traversal_reserved_case_and_alias_paths_are_refused(self):
        bound = self.binding()
        for value in ('../x', '/x', 'C:/x', 'market.db:stream', '.ST-DATA-ROOT.JSON',
                      '.st-cutover.json.', 'RUNTIME_LOCKS/x', 'WaveDeck/state.json'):
            with self.subTest(path=value), self.assertRaises(paths.BindingError):
                paths.data_path(value, binding=bound)
        fake = mock.Mock(st_mode=0, st_file_attributes=0x400)
        with mock.patch.object(Path, 'lstat', return_value=fake):
            with self.assertRaises(paths.BindingError):
                paths.validate_binding(bound)

    def test_external_write_needs_lease_and_existing_database(self):
        bound = self.binding()
        target = self.data / 'market.db'
        with self.assertRaises(storage.StorageOwnershipError):
            storage.assert_write_allowed(target, binding=bound, must_exist=True)
        with storage.bootstrap_runtime(binding=bound):
            storage.assert_write_allowed(target, binding=bound, must_exist=True)
            storage.assert_write_allowed(self.data / 'new.json.tmp', binding=bound)
            storage.assert_write_allowed(self.data / 'new.json.bak', binding=bound)
            with self.assertRaises(storage.StorageOwnershipError):
                storage.assert_write_allowed(self.data / 'missing.db', binding=bound, must_exist=True)
        with self.assertRaises(storage.StorageOwnershipError):
            storage.assert_write_allowed(target, binding=bound)
        self.assertFalse((self.data / 'missing.db').exists())

    def test_client_cannot_bootstrap_and_st_cannot_write_wavedeck_or_metadata(self):
        with self.assertRaises(storage.StorageOwnershipError):
            storage.bootstrap_runtime(binding=self.binding(role='client'))
        bound = self.binding()
        with storage.bootstrap_runtime(binding=bound):
            for target in (self.data / 'wavedeck' / 'state.json', self.root / 'outside.json',
                           self.data / '.ST-DATA-ROOT.JSON', self.data / '.St-Cutover.Json',
                           self.data / 'RUNTIME_LOCKS' / 'st-backend.WRITER.LOCK'):
                with self.subTest(path=target), self.assertRaises(storage.StorageOwnershipError):
                    storage.assert_write_allowed(target, namespace=None, binding=bound)

    def test_wavedeck_lease_does_not_grant_st_writes(self):
        bound = self.binding(role='wavedeck')
        with storage.bootstrap_runtime(binding=bound, namespace='wavedeck'):
            storage.assert_write_allowed(self.data / 'wavedeck' / 'state.json', namespace=None, binding=bound)
            with self.assertRaises(storage.StorageOwnershipError):
                storage.assert_write_allowed(self.data / 'llm_gate.json', namespace=None, binding=bound)

    def test_unbound_legacy_cli_cannot_write_marked_production_root(self):
        bound = paths.resolve_binding(code_root=self.code, environ={})
        with self.assertRaises(storage.StorageOwnershipError):
            storage.assert_write_allowed(self.data / 'market.db', binding=bound)

    def test_legacy_file_alias_cannot_hide_a_production_ancestor(self):
        bound = paths.resolve_binding(code_root=self.code, environ={})
        # The platform-neutral alias boundary avoids requiring Windows
        # symlink privilege; all destination marker checks remain real.
        alias = self.root / 'legacy' / 'alias.db'
        original_realpath = os.path.realpath
        def realpath(value, *args, **kwargs):
            if Path(value) == alias:
                return str(self.data / 'market.db')
            return original_realpath(value, *args, **kwargs)
        with mock.patch.object(storage.os.path, 'realpath', side_effect=realpath):
            with self.assertRaises(storage.StorageOwnershipError):
                storage.assert_write_allowed(alias, binding=bound)
        self.assertFalse(alias.parent.exists())

    def test_release_without_capability_cannot_bootstrap(self):
        (self.code / paths.CAPABILITY_FILE).unlink()
        with self.assertRaises(paths.BindingError):
            storage.bootstrap_runtime(binding=self.binding())
        self.assertFalse((self.data / 'runtime_locks').exists())

    def test_gateway_auxiliary_context_only_allows_its_atomic_file_family(self):
        bound = self.binding(role='client')
        auth = self.code / 'data' / 'access_requests.json'
        with storage.bootstrap_gateway_auth(bound, writable_file=auth):
            self.assertEqual({}, sys._st_runtime_leases)
            for filename in ('access_requests.json', 'access_requests.json.bak',
                             'access_requests.json.corrupt-20261023-102030',
                             'access_requests.json.corrupt-20261023-102030-2',
                             '.access_requests.json.abc12345.tmp', '.access_requests.json.bak.abc12345.tmp'):
                storage.assert_write_allowed(auth.parent / filename, namespace=None)
            for target in (auth.parent / 'market.db', self.data / 'market.db', self.root / 'recovery' / 'copy.json',
                           auth.parent / 'access_requests.json.corrupt-anything', auth.parent / '.access_requests.json.other.tmp',
                           auth.parent / 'child' / 'access_requests.json'):
                with self.subTest(target=target), self.assertRaises(storage.StorageOwnershipError):
                    storage.assert_write_allowed(target, namespace=None)
            with self.assertRaises(storage.StorageOwnershipError):
                storage.assert_write_allowed(auth, namespace='st')
        with self.assertRaises(storage.StorageOwnershipError):
            storage.assert_write_allowed(auth, namespace=None, binding=bound)
        self.assertFalse(auth.parent.exists())

    def test_gateway_cannot_register_business_or_recovery_file_as_auth(self):
        bound = self.binding(role='client')
        for target in (self.data / 'access.json', self.root / 'recovery' / 'access.json'):
            with self.subTest(target=target), self.assertRaises(storage.StorageOwnershipError):
                storage.bootstrap_gateway_auth(bound, writable_file=target)
        with self.assertRaises(paths.BindingError):
            storage.bootstrap_gateway_auth(self.binding(), writable_file=self.code / 'auth.json')
        self.assertFalse((self.data / 'runtime_locks').exists())

    def test_fast_ai_keeps_one_fixed_machine_resource_lock_without_general_escape(self):
        from server.daemon_lock import acquire_daemon_lock, release_daemon_lock
        # Patch only the OS temporary-directory boundary. No real global lock
        # or installed AI tool is touched by this test.
        with mock.patch.object(storage.tempfile, 'gettempdir', return_value=str(self.root / 'machine-temp')):
            directory = self.root / 'machine-temp' / 'StockTerminal' / 'ai-runtime'
            self.assertTrue(storage.is_fast_ai_resource_lock('fast-ai', directory))
            self.assertFalse(storage.is_fast_ai_resource_lock('other', directory))
            self.assertFalse(storage.is_fast_ai_resource_lock('fast-ai', self.root / 'other'))
            with storage.bootstrap_runtime(binding=self.binding()):
                handle = acquire_daemon_lock('fast-ai', lock_dir=directory)
                self.assertIsNotNone(handle)
                release_daemon_lock(handle)
                with self.assertRaises(storage.StorageOwnershipError):
                    acquire_daemon_lock('other', lock_dir=directory)
                with self.assertRaises(storage.StorageOwnershipError):
                    acquire_daemon_lock('fast-ai', lock_dir=self.root / 'outside')
            with storage.bootstrap_gateway_auth(self.binding(role='client'), writable_file=self.code / 'auth.json'):
                with self.assertRaises(storage.StorageOwnershipError):
                    acquire_daemon_lock('fast-ai', lock_dir=directory)
            self.assertFalse((self.root / 'outside').exists())

    def test_hard_link_alias_and_closed_writer_handle_are_rejected(self):
        alias = self.root / 'alias.db'
        os.link(self.data / 'market.db', alias)
        try:
            with self.assertRaises(paths.BindingError):
                paths.validate_binding(self.binding())
        finally:
            alias.unlink()
        lease = storage.bootstrap_runtime(binding=self.binding())
        lease.handle.close()
        with self.assertRaises(storage.StorageOwnershipError):
            storage.assert_write_allowed(self.data / 'market.db', binding=lease.binding)
        lease.close()

    def test_writer_lease_is_exclusive_across_processes_and_released_on_close(self):
        child = """
import sys
sys.path.insert(0, sys.argv[1])
from data_paths import resolve_binding
from runtime_storage import bootstrap_runtime, StorageOwnershipError
binding = resolve_binding(code_root=sys.argv[2], environ={'ST_RUNTIME_ROLE':'backend'}, installation_binding=sys.argv[3])
try:
    with bootstrap_runtime(binding=binding):
        print('owned')
except StorageOwnershipError:
    print('busy')
"""
        argv = [sys.executable, '-B', '-c', child, str(Path(__file__).resolve().parents[1] / 'server'),
                str(self.code), str(self.binding_file)]
        with storage.bootstrap_runtime(binding=self.binding()):
            first = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=True)
        second = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual('busy', first.stdout.strip())
        self.assertEqual('owned', second.stdout.strip())


if __name__ == '__main__':
    unittest.main()

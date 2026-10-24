"""External storage preserves the two existing credential files, using fakes only."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock
import uuid

from server import data_paths, runtime_storage, secret_store


class RuntimeSecretTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()  # 8.3 短檔名（RUNNER~1）須展開為正規拼寫
        self.code = self.root / 'managed-current'
        self.data = self.root / 'runtime'
        self.code.mkdir()
        self.data.mkdir()
        identity = str(uuid.uuid4())
        def write(path, value):
            path.write_text(json.dumps(value), encoding='utf-8')
        write(self.data / data_paths.IDENTITY_FILE,
              {'schemaVersion': 1, 'kind': 'production', 'dataRootId': identity})
        write(self.data / data_paths.CUTOVER_FILE,
              {'schemaVersion': 1, 'dataRootId': identity, 'state': 'ready',
               'capabilityVersion': 1, 'requiredPaths': ['market.db']})
        (self.data / 'market.db').write_bytes(b'synthetic-not-opened')
        write(self.code / data_paths.CAPABILITY_FILE,
              {'schemaVersion': 1, 'capabilityVersion': 1, 'storageModes': ['external']})
        config = {'schemaVersion': 1, 'storageMode': 'external',
                  'dataRoot': str(self.data), 'dataRootId': identity,
                  'recoveryRoot': str(self.root / 'recovery'), 'capabilityVersion': 1,
                  'allowedCodeRoots': [str(self.code)],
                  'backendUrl': 'http://127.0.0.1:18435', 'publicUrl': 'http://127.0.0.1:18434'}
        self.binding = data_paths.validate_binding(data_paths.resolve_binding(
            code_root=self.code, environ={'ST_RUNTIME_ROLE': 'backend'}, installation_binding=config))
        for name, value in (('_st_runtime_binding', self.binding), ('_st_runtime_leases', {}),
                            ('_st_gateway_auth', None), ('_st_runtime_lease_guard', threading.RLock())):
            self.stack.enter_context(mock.patch.object(sys, name, value, create=True))
        # Exercise the real secret and atomic stores; only replace OS encryption.
        self.stack.enter_context(mock.patch.object(secret_store, '_protect', side_effect=lambda data, **kw: b'fixture:' + data))
        self.stack.enter_context(mock.patch.object(secret_store, '_unprotect', side_effect=lambda data: data.removeprefix(b'fixture:')))

    def own_st(self):
        return self.stack.enter_context(runtime_storage.bootstrap_runtime(binding=self.binding))

    def test_existing_credentials_roundtrip_backup_and_clear_in_original_location(self):
        self.own_st()
        for name in ('ai_key.bin', 'alert_secrets.bin'):
            with self.subTest(name=name):
                path = self.code / 'data' / name
                secret_store.save_secret(path, 'fake-first')
                secret_store.save_secret(path, 'fake-second')
                self.assertEqual('fake-second', secret_store.load_secret(path))
                self.assertEqual('fake-first', secret_store.load_secret(str(path) + '.bak'))
                secret_store.save_secret(path, '')
                self.assertEqual('', secret_store.load_secret(path))
                self.assertFalse((self.data / name).exists())
        self.assertFalse(list((self.code / 'data').glob('*.tmp')))

    def test_credentials_without_writer_are_denied_before_directory_creation(self):
        for name in ('ai_key.bin', 'alert_secrets.bin'):
            with self.subTest(name=name), self.assertRaises(runtime_storage.StorageOwnershipError):
                secret_store.save_secret(self.code / 'data' / name, 'fake')
        self.assertFalse((self.code / 'data').exists())

    def test_closed_or_wavedeck_writer_cannot_write_st_credentials(self):
        lease = self.own_st()
        lease.close()
        with mock.patch.object(sys, '_st_runtime_binding', self.binding):
            with self.assertRaises(runtime_storage.StorageOwnershipError):
                secret_store.save_secret(self.code / 'data' / 'ai_key.bin', 'fake')
        from dataclasses import replace
        binding = replace(self.binding, role='wavedeck')
        with runtime_storage.bootstrap_runtime(binding=binding, namespace='wavedeck'):
            with self.assertRaises(runtime_storage.StorageOwnershipError):
                secret_store.save_secret(self.code / 'data' / 'ai_key.bin', 'fake')
        self.assertFalse((self.code / 'data').exists())

    def test_permission_does_not_extend_to_other_files_paths_or_aliases(self):
        self.own_st()
        denied = [self.code / 'data' / name for name in
                  ('market.db', 'ai_key.txt', 'ai_key.bin.extra', '.ai_key.bin.short.tmp',
                   'alert_secrets.bin.corrupt-20261023-123456')]
        denied += [self.root / 'other' / 'data' / 'ai_key.bin', self.code / 'other' / 'ai_key.bin']
        for path in denied:
            with self.subTest(path=path), self.assertRaises(runtime_storage.StorageOwnershipError):
                secret_store.save_secret(path, 'fake')
        self.assertFalse((self.code / 'data').exists())
        (self.code / 'data').mkdir()
        source = self.root / 'sentinel'
        source.write_bytes(b'preserve')
        os.link(source, self.code / 'data' / 'ai_key.bin')
        with self.assertRaises(data_paths.BindingError):
            secret_store.save_secret(self.code / 'data' / 'ai_key.bin', 'fake')
        self.assertEqual(b'preserve', source.read_bytes())


if __name__ == '__main__':
    unittest.main()

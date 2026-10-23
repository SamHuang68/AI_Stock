"""Small directory/member fixtures only: never build or write an archive."""
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import local_release as local
import private_web_release as release
import runtime_release_policy as policy


def distribution_module():
    spec = importlib.util.spec_from_file_location('st_dist_runtime_policy_test', ROOT / 'scripts/build_dist.py')
    dist = importlib.util.module_from_spec(spec)
    with patch('subprocess.run') as command:
        command.return_value.returncode = 1
        spec.loader.exec_module(dist)
    return dist


class RuntimePackagePolicyTests(unittest.TestCase):
    def setUp(self):
        env = {key: value for key, value in os.environ.items()
               if key not in {'ST_DATA_ROOT', 'ST_DATA_BINDING', 'ST_RUNTIME_ROLE'}}
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_regular_file_is_checked_without_directory_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / '.private_web_release.json'
            target.write_bytes(b'{}')
            with patch.object(policy.os, 'walk', side_effect=AssertionError('一般檔案不可下降列舉')) as walk:
                policy.assert_safe_tree(target)
            walk.assert_not_called()
            self.assertEqual(target.read_bytes(), b'{}')

    def test_single_protected_file_is_rejected_before_directory_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'data' / 'runtime' / 'sentinel.json'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'{}')
            with patch.object(policy.os, 'walk') as walk:
                with self.assertRaisesRegex(RuntimeError, 'protected'):
                    policy.assert_safe_tree(target)
            walk.assert_not_called()
            self.assertEqual(target.read_bytes(), b'{}')

    def test_windows_reparse_attribute_is_rejected_before_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'junction'
            observed = Path.lstat
            def lstat(path):
                if path == target:
                    return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
                return observed(path)
            with patch.object(Path, 'lstat', lstat), patch.object(policy.os, 'walk') as walk:
                with self.assertRaisesRegex(RuntimeError, 'link'):
                    policy.assert_safe_tree(target)
            walk.assert_not_called()

    def test_share_preflight_requires_wavedeck_runtime_adapter(self):
        dist = distribution_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in dist.REQUIRED_SHARE_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            (root / 'wavedeck/runtime_paths.py').unlink()
            with patch.object(dist, 'ROOT', root), patch.object(dist, 'TRACKED_FILES', None):
                with self.assertRaisesRegex(RuntimeError, 'missing: wavedeck/runtime_paths.py'):
                    dist.validate_required_share_files()

    def test_legacy_backup_rejects_runtime_and_recovery_before_creating_backup(self):
        for reserved in ('runtime', 'recovery', 'RuNtImE', 'RECOVERY'):
            with self.subTest(reserved=reserved), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                data = root / 'checkout' / 'data'
                protected = data / reserved
                protected.mkdir(parents=True)
                sentinel = protected / 'unknown.extension'
                sentinel.write_bytes(b'private-runtime')
                with self.assertRaisesRegex((ValueError, RuntimeError), 'protected|runtime|recovery'):
                    local.backup_data(data, root / 'install', 'a' * 40, 'code sync')
                self.assertEqual(sentinel.read_bytes(), b'private-runtime')
                self.assertFalse((root / 'install' / 'backups').exists())

    def test_release_hashing_rejects_reserved_data_before_reading_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / 'data' / 'runtime' / 'user.json'
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text('private', encoding='utf-8')
            with self.assertRaisesRegex((ValueError, RuntimeError), 'protected|runtime'):
                release._content_hashes(root / 'data', include_runtime=True)

    def test_share_copy_prunes_reserved_tree_even_when_files_are_tracked(self):
        dist = distribution_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'input'
            secret = source / 'data' / 'RuNtImE' / 'unlisted.json'
            secret.parent.mkdir(parents=True)
            secret.write_bytes(b'private')
            (source / 'safe.js').write_text('safe', encoding='utf-8')
            with patch.object(dist, 'TRACKED_FILES', None):
                dist.copy_tree_filtered(source, root / 'output')
            self.assertFalse((root / 'output' / 'data' / 'RuNtImE').exists())
            self.assertEqual((root / 'output' / 'safe.js').read_text(), 'safe')

    def test_archive_metadata_is_rejected_before_extraction(self):
        class Member:
            filename = 'data/recovery/private.bin'
            external_attr = 0

        with tempfile.TemporaryDirectory() as tmp, patch.object(release.zipfile, 'ZipFile') as archive:
            archive.return_value.__enter__.return_value.infolist.return_value = [Member()]
            with self.assertRaisesRegex((ValueError, RuntimeError), 'protected|recovery'):
                release._safe_extract(Path(tmp) / 'unused.zip', Path(tmp) / 'output')
            archive.return_value.__enter__.return_value.extractall.assert_not_called()

    def test_git_archive_is_not_started_for_tracked_runtime(self):
        with patch.object(release, '_run') as command:
            command.return_value.stdout = 'data/runtime/market.db\0server/server.py\0'
            with self.assertRaisesRegex((ValueError, RuntimeError), 'protected|runtime'):
                release._validate_git_archive_members('a' * 40)
        self.assertEqual(command.call_count, 1)
        self.assertIn('ls-tree', command.call_args.args[0])


if __name__ == '__main__':
    unittest.main()

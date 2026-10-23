"""Persistence sinks reject denied writes before any filesystem mutation."""
import sys
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import atomic_store
import jsonl_trace
import runtime_storage


class RuntimeStoreGuards(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.denial = mock.patch.object(runtime_storage, 'assert_write_allowed',
                                       side_effect=PermissionError('no writer lease'))

    def test_atomic_denial_does_not_create_parent_or_temporary_files(self):
        target = self.root / 'absent' / 'state.json'
        with self.denial, self.assertRaises(PermissionError):
            atomic_store.atomic_write_json(target, {'new': True})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_replacement_denial_preserves_source_and_target(self):
        source, target = self.root / 'candidate.tmp', self.root / 'state.json'
        source.write_bytes(b'candidate'); target.write_bytes(b'original')
        with self.denial, self.assertRaises(PermissionError):
            atomic_store._replace_with_retry(source, target)
        self.assertEqual(source.read_bytes(), b'candidate')
        self.assertEqual(target.read_bytes(), b'original')

    def test_recovery_denial_preserves_corrupt_primary_and_backup(self):
        target = self.root / 'state.json'
        backup = self.root / 'state.json.bak'
        target.write_bytes(b'{broken'); backup.write_bytes(b'{"saved": true}')
        before = {p.name:p.read_bytes() for p in self.root.iterdir()}
        with self.denial, self.assertRaises(PermissionError):
            atomic_store.load_json(target, default={}, expected_type=dict)
        self.assertEqual({p.name:p.read_bytes() for p in self.root.iterdir()}, before)

    def test_valid_read_does_not_require_a_writer(self):
        target = self.root / 'state.json'; target.write_bytes(b'{"saved": true}')
        with self.denial:
            self.assertEqual(atomic_store.load_json(target, default={}, expected_type=dict), {'saved': True})

    def test_trace_denial_does_not_create_parent(self):
        with self.denial, self.assertRaises(PermissionError):
            jsonl_trace.append_jsonl(str(self.root / 'absent' / 'trace.jsonl'), {'event':'test'},
                                    max_bytes=10, tail_lines=2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_package_import_does_not_require_top_level_server_modules(self):
        script = '''
from pathlib import Path
import sys
import tempfile
sys.path[:] = [p for p in sys.path if Path(p).name != 'server']
from server import atomic_store
with tempfile.TemporaryDirectory() as directory:
    target = Path(directory) / 'fixture.json'
    atomic_store.atomic_write_json(target, {'fixture': True})
    assert atomic_store.load_json(target, default={}, expected_type=dict) == {'fixture': True}
'''
        result = subprocess.run([sys.executable, '-B', '-c', script],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

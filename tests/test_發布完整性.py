"""發布故障注入：原程式與執行期資料必須可以回復。"""
import json
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests')]
import private_web_release as release
from test_private_web_release import _fake_release, _write


class 發布完整性測試(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '安裝目錄'
        self.root.mkdir()
        # Windows CI 的 TEMP 可能是 8.3 別名；與發布器使用同一解析路徑，確保故障注入命中。
        self.root = self.root.resolve()
        self.staged = _fake_release(self.root, 'abc123')
        self.current = self.root / 'current'
        _write(self.current / 'server/old.py', '原程式')
        _write(self.current / 'data/personal.db', '原始資料')
        _write(self.current / 'logs/audit.txt', '原始紀錄')
        _write(self.current / '自訂設定.txt', '使用者設定')
        _write(self.current / release.MANIFEST_NAME, json.dumps({
            'releaseId': 'old', 'commit': 'b' * 40, 'tests': 'passed',
            'managedTopLevel': ['server', release.MANIFEST_NAME],
        }))

    def assert原版完整(self):
        self.assertEqual((self.current / 'server/old.py').read_text(encoding='utf-8'), '原程式')
        self.assertEqual((self.current / 'data/personal.db').read_text(encoding='utf-8'), '原始資料')
        self.assertEqual((self.current / 'logs/audit.txt').read_text(encoding='utf-8'), '原始紀錄')
        self.assertEqual((self.current / '自訂設定.txt').read_text(encoding='utf-8'), '使用者設定')

    def test_複製失敗不移除原版(self):
        with patch.object(release, '_copy_item', side_effect=OSError('模擬磁碟錯誤')):
            with self.assertRaises(OSError):
                release.promote_release(self.root, release_id='abc123', approved=True)
        self.assert原版完整()

    def test_目錄切換失敗會回復原版與資料(self):
        original = Path.rename

        def rename(path, target):
            if path.name.startswith('candidate-') and Path(target) == self.current:
                raise OSError('模擬 Windows 目錄鎖定')
            return original(path, target)

        with patch.object(Path, 'rename', rename), self.assertRaises(OSError):
            release.promote_release(self.root, release_id='abc123', approved=True)
        self.assert原版完整()
        self.assertFalse((self.root / release.TRANSITION_NAME).exists())

    def test_程序中斷後可依交易紀錄復原(self):
        candidate = self.root / 'candidate-crash'
        candidate.mkdir()
        previous = self.root / 'backups/previous-crash'
        previous.parent.mkdir()
        release._write_json(self.root / release.TRANSITION_NAME, {
            'candidate': candidate.name, 'previous': 'backups/previous-crash',
            'hadCurrent': True,
            'candidateContentSha256': release._program_hashes(candidate),
            'previousContentSha256': release._program_hashes(self.current),
        })
        self.current.rename(previous)
        (previous / 'data').rename(candidate / 'data')
        release.recover_transition(self.root)
        self.assert原版完整()
        self.assertFalse((self.root / release.TRANSITION_NAME).exists())

    def test_修改新增刪除暫存內容均拒絕發布(self):
        for action in ['修改', '新增', '刪除']:
            with self.subTest(action=action):
                path = self.staged / 'server/server.py'
                original = path.read_bytes()
                extra = self.staged / 'server/extra.py'
                if action == '修改':
                    path.write_text('已變動', encoding='utf-8')
                elif action == '新增':
                    extra.write_text('新內容', encoding='utf-8')
                else:
                    path.unlink()
                with self.assertRaises(RuntimeError):
                    release.promote_release(self.root, release_id='abc123', approved=True)
                self.assert原版完整()
                path.write_bytes(original)
                extra.unlink(missing_ok=True)

    def test_無雜湊的舊暫存必須重新驗證(self):
        path = self.staged / release.MANIFEST_NAME
        manifest = json.loads(path.read_text())
        manifest.pop('contentSha256')
        path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, '缺少受測內容雜湊'):
            release.promote_release(self.root, release_id='abc123', approved=True)
        self.assert原版完整()

    def test_重用暫存也會驗證內容(self):
        commit = 'a' * 40
        staged = _fake_release(self.root, commit[:12])
        manifest_path = staged / release.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text())
        manifest['commit'] = commit
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        (staged / 'server/server.py').write_text('變更', encoding='utf-8')
        with patch.object(release, 'resolve_commit', return_value=(commit, commit[:12])):
            with self.assertRaisesRegex(RuntimeError, '內容與受測版本不符'):
                release.stage_release(self.root, ref=commit)

    def test_回復版本保留新寫入的執行期資料(self):
        release.promote_release(self.root, release_id='abc123', approved=True)
        self.assertTrue((self.current / 'server/server.py').exists())
        self.assertTrue((self.current / '自訂設定.txt').exists())
        _write(self.current / 'data/personal.db', '更新後資料')
        release.rollback_release(self.root, approved=True)
        self.assertTrue((self.current / 'server/old.py').exists())
        self.assertEqual((self.current / 'data/personal.db').read_text(encoding='utf-8'), '更新後資料')
        self.assertEqual((self.current / 'logs/audit.txt').read_text(encoding='utf-8'), '原始紀錄')

    def test_前版內容漂移不能自動回復(self):
        release.promote_release(self.root, release_id='abc123', approved=True)
        manifest = json.loads((self.current / release.MANIFEST_NAME).read_text(encoding='utf-8'))
        _write(self.root / manifest['previousDirectory'] / 'server/old.py', '已變更')
        with self.assertRaisesRegex(RuntimeError, '前版內容已改變'):
            release.rollback_release(self.root, approved=True)

    def test_種子與新增位元組碼均受完整性保護(self):
        for relative in ['data/public_seed.csv', 'server/extra.pyc', 'server/__pycache__/extra.pyc']:
            with self.subTest(relative=relative):
                path = self.staged / relative
                original = path.read_bytes() if path.exists() else None
                _write(path, '未經測試的內容')
                with self.assertRaisesRegex(RuntimeError, '內容與受測版本不符'):
                    release.promote_release(self.root, release_id='abc123', approved=True)
                self.assert原版完整()
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def test_候選複製期間種子變動會在切換前拒絕(self):
        copy_item = release._copy_item

        def copy(source, target):
            if source == self.staged / 'data':
                _write(source / 'public_seed.csv', '複製期間已變動')
            return copy_item(source, target)

        with patch.object(release, '_copy_item', copy):
            with self.assertRaisesRegex(RuntimeError, '內容與受測版本不符'):
                release.promote_release(self.root, release_id='abc123', approved=True)
        self.assert原版完整()

    def test_前版識別檔變動不能自動回復(self):
        release.promote_release(self.root, release_id='abc123', approved=True)
        active = release._read_manifest(self.current / release.MANIFEST_NAME)
        previous_manifest = self.root / active['previousDirectory'] / release.MANIFEST_NAME
        old = release._read_manifest(previous_manifest)
        old['commit'] = 'e' * 40
        _write(previous_manifest, json.dumps(old))
        with self.assertRaisesRegex(RuntimeError, '前版內容已改變'):
            release.rollback_release(self.root, approved=True)
        self.assertTrue((self.current / 'server/server.py').exists())

    def test_切換後清除交易紀錄失敗仍為成功且可重新核對(self):
        unlink = Path.unlink

        def locked(path, *args, **kwargs):
            if path == self.root / release.TRANSITION_NAME:
                raise PermissionError('模擬交易紀錄鎖定')
            return unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', locked):
            release.promote_release(self.root, release_id='abc123', approved=True)
        self.assertTrue((self.current / 'server/server.py').exists())
        self.assertTrue((self.root / release.TRANSITION_NAME).exists())
        py_compile.compile(str(self.current / 'server/server.py'), doraise=True)
        release.recover_transition(self.root)
        self.assertFalse((self.root / release.TRANSITION_NAME).exists())
        release.rollback_release(self.root, approved=True)
        self.assert原版完整()

    def test_回復前清除可再生快取但拒絕無來源位元組碼(self):
        cache = Path(py_compile.compile(str(self.current / 'server/old.py'), doraise=True))
        relative = cache.relative_to(self.current)
        release.promote_release(self.root, release_id='abc123', approved=True)
        active = release._read_manifest(self.current / release.MANIFEST_NAME)
        previous = self.root / active['previousDirectory']
        (previous / relative).write_bytes(b'changed-cache')
        _write(previous / 'server/unknown.pyc', '無來源執行內容')
        with self.assertRaisesRegex(RuntimeError, '前版內容已改變'):
            release.rollback_release(self.root, approved=True)
        (previous / 'server/unknown.pyc').unlink()
        release.rollback_release(self.root, approved=True)
        self.assert原版完整()
        self.assertFalse((self.current / relative).exists())

    def test_模糊交易狀態保留所有目錄與紀錄(self):
        release._write_json(self.root / release.TRANSITION_NAME, {
            'candidate': 'candidate-missing', 'previous': 'backups/previous-missing',
            'hadCurrent': True, 'candidateContentSha256': {'other.py': '不符'},
            'previousContentSha256': release._program_hashes(self.current),
        })
        with self.assertRaisesRegex(RuntimeError, '交易狀態不明'):
            release.recover_transition(self.root)
        self.assert原版完整()
        self.assertTrue((self.root / release.TRANSITION_NAME).exists())

    def test_首次安裝故障後可重試(self):
        root = self.root / '首次安裝'
        root.mkdir()
        _fake_release(root, 'abc123')
        original = Path.rename

        def rename(path, target):
            if path.name.startswith('candidate-') and Path(target) == root / 'current':
                raise PermissionError('模擬首次切換故障')
            return original(path, target)

        with patch.object(Path, 'rename', rename), self.assertRaises(PermissionError):
            release.promote_release(root, release_id='abc123', approved=True)
        self.assertFalse((root / 'current').exists())
        self.assertFalse((root / release.TRANSITION_NAME).exists())
        release.promote_release(root, release_id='abc123', approved=True)
        self.assertEqual((root / 'current/data/public_seed.csv').read_text(encoding='utf-8'), 'seed')

    def test_連續回復保留最新資料與舊識別格式(self):
        release.promote_release(self.root, release_id='abc123', approved=True)
        _fake_release(self.root, 'def456')
        release.promote_release(self.root, release_id='def456', approved=True)
        _write(self.current / 'data/personal.db', '最新資料')
        release.rollback_release(self.root, approved=True)
        self.assertEqual(release._read_manifest(self.current / release.MANIFEST_NAME)['releaseId'], 'abc123')
        release.rollback_release(self.root, approved=True)
        self.assertTrue((self.current / 'server/old.py').exists())
        self.assertEqual((self.current / 'data/personal.db').read_text(encoding='utf-8'), '最新資料')
        self.assertEqual((self.current / 'logs/audit.txt').read_text(encoding='utf-8'), '原始紀錄')

    def test_並行發布在變更目錄前拒絕且程序結束會釋放鎖(self):
        code = "\n".join([
            'import sys', 'from pathlib import Path',
            'sys.path.insert(0, sys.argv[1])', 'import private_web_release as r',
            'with r._release_lock(Path(sys.argv[2])):',
            "    print('locked', flush=True)", '    sys.stdin.readline()',
        ])
        process = subprocess.Popen(
            [sys.executable, '-c', code, str(ROOT / 'scripts'), str(self.root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8',
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            with self.assertRaisesRegex(RuntimeError, '另一個發布或回復程序'):
                release.promote_release(self.root, release_id='abc123', approved=True)
            self.assert原版完整()
        finally:
            process.communicate('\n', timeout=10)
        self.assertEqual(process.returncode, 0)
        release.promote_release(self.root, release_id='abc123', approved=True)


if __name__ == '__main__':
    unittest.main()

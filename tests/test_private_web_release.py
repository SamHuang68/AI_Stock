#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import private_web_release as release  # noqa: E402


def _write(path: Path, value: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fake_release(root: Path, release_id: str) -> Path:
    target = root / "releases" / release_id
    for relative in release.REQUIRED_RELEASE_FILES:
        _write(target / relative, "new")
    _write(target / "server" / "new_module.py", "new-code")
    _write(target / "data" / "public_seed.csv", "seed")
    manifest = {
        "releaseId": release_id,
        "commit": release_id.ljust(40, "0"),
        "tests": "passed",
        "managedTopLevel": sorted(item.name for item in target.iterdir()
                                  if item.name not in release.PRESERVE_NAMES),
        "contentSha256": release._content_hashes(target),
        "seedSha256": release._content_hashes(target / 'data', include_runtime=True),
    }
    _write(
        target / ".private_web_release.json",
        json.dumps(manifest, ensure_ascii=False),
    )
    return target


class PrivateWebReleaseTests(unittest.TestCase):
    def test_manifest_readers_survive_cp950_default(self):
        original = Path.read_text

        def read_with_cp950(path, *args, **kwargs):
            if path.name == release.MANIFEST_NAME and not args and kwargs.get('encoding') is None:
                kwargs = dict(kwargs, encoding='cp950')
            return original(path, *args, **kwargs)

        # 執行真正的兩個清單讀取情境；只模擬清單的非 UTF-8 預設，不修改系統 locale。
        suite = unittest.TestSuite(PrivateWebReleaseTests(name) for name in (
            'test_promote_replaces_code_but_preserves_runtime_data_and_logs',
            'test_unverified_release_is_not_promoted',
        ))
        result = unittest.TestResult()
        with patch.object(Path, 'read_text', new=read_with_cp950):
            suite.run(result)
        self.assertEqual(result.testsRun, 2)
        self.assertFalse(result.errors, result.errors)
        self.assertFalse(result.failures, result.failures)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.install_root = Path(self.temp.name) / "private" / "install"
        self.install_root.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def prepare_cli_stage(self):
        staged = _fake_release(self.install_root, 'abc123')
        for relative in ('scripts/private_web_release.py', 'scripts/runtime_release_policy.py',
                         'server/daemon_lock.py', 'server/data_paths.py', 'server/runtime_storage.py',
                         'runtime_storage_capability.json'):
            shutil.copy2(ROOT / relative, staged / relative)
        manifest = release._read_manifest(staged / release.MANIFEST_NAME)
        manifest['contentSha256'] = release._content_hashes(staged)
        _write(staged / release.MANIFEST_NAME, json.dumps(manifest))
        return staged, manifest

    def run_stage_cli(self, staged, action='promote'):
        # 子程序刻意不帶 -B，亦不依賴呼叫者已設定的環境保護。
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        env.pop('PYTHONPYCACHEPREFIX', None)
        command = [
            sys.executable, str(staged / 'scripts/private_web_release.py'),
            '--install-root', str(self.install_root), action, '--approve',
        ]
        if action == 'promote':
            command.extend(['--release', 'abc123'])
        return subprocess.run(command, cwd=self.install_root, env=env, capture_output=True,
                              text=True, encoding='utf-8', timeout=30)

    def test_直接執行封存stage的CLI不新增快取且可發布(self):
        staged, manifest = self.prepare_cli_stage()
        current = self.install_root / 'current'
        old_source = current / 'server/old_module.py'
        _write(old_source, 'VALUE = 1\n')
        _write(current / 'data/personal.db', '必須保留的原始資料')
        _write(current / 'data/user-cache.pyc', '資料目錄內的本機檔案也必須保留')
        _write(current / 'logs/audit.log', '原始紀錄')
        _write(current / release.MANIFEST_NAME, json.dumps({
            'releaseId': 'bbbbbbbbbbbb', 'commit': 'b' * 40, 'tests': 'passed',
            'managedTopLevel': ['server'], 'contentSha256': release._content_hashes(current),
        }))
        py_compile.compile(str(old_source), doraise=True)
        before = release._content_hashes(staged, include_runtime=True, include_manifest=True)
        result = self.run_stage_cli(staged)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, release._content_hashes(staged, include_runtime=True, include_manifest=True))
        release._validate_integrity(staged, manifest)
        self.assertFalse(any(path.name == '__pycache__' for path in staged.rglob('*')))
        self.assertFalse((current / 'server/__pycache__').exists())
        self.assertEqual((current / 'data/public_seed.csv').read_text(), 'seed')
        self.assertEqual((current / 'data/personal.db').read_text(encoding='utf-8'), '必須保留的原始資料')
        result = self.run_stage_cli(staged, 'rollback')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(old_source.read_text(), 'VALUE = 1\n')
        self.assertFalse(any(path.suffix in {'.pyc', '.pyo'} for path in (current / 'server').rglob('*')))
        self.assertEqual((current / 'data/personal.db').read_text(encoding='utf-8'), '必須保留的原始資料')
        self.assertEqual((current / 'data/user-cache.pyc').read_text(encoding='utf-8'), '資料目錄內的本機檔案也必須保留')
        self.assertEqual((current / 'logs/audit.log').read_text(encoding='utf-8'), '原始紀錄')

    def test_既有daemon快取不得在完整性拒絕前執行(self):
        staged, _ = self.prepare_cli_stage()
        source = staged / 'server/daemon_lock.py'
        original = source.read_bytes()
        old_stat = source.stat()
        marker = self.install_root / '不應執行的快取.txt'
        malicious = ('from pathlib import Path\nPath(' + repr(str(marker)) + ").write_text('未受測快取')\n").encode('utf-8')
        self.assertLess(len(malicious), len(original))
        source.write_bytes(malicious + b'#' * (len(original) - len(malicious)))
        os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        py_compile.compile(str(source), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
        source.write_bytes(original)
        os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        result = self.run_stage_cli(staged)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('不得包含 Python 位元組快取', result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse((self.install_root / 'current').exists())

    def test_列入manifest也不允許發布位元組快取(self):
        staged, manifest = self.prepare_cli_stage()
        for relative in ('server/extra.pyc', 'server/extra.pyo', 'server/extra.PYC', 'server/__pycache__/extra.pyc'):
            with self.subTest(relative=relative):
                path = staged / relative
                _write(path, '禁止作為程式封存內容')
                manifest['contentSha256'] = release._content_hashes(staged)
                with self.assertRaisesRegex(RuntimeError, '不得包含 Python 位元組快取'):
                    release._validate_integrity(staged, manifest)
                path.unlink()
                if path.parent.name == '__pycache__':
                    path.parent.rmdir()

    def test_new_stop_requires_companions_without_blocking_legacy_rollback(self):
        target = _fake_release(self.install_root, 'abc123')
        # 舊版本完整停止器仍可作為 rollback，無須不存在的新配套。
        release._validate_release(target)
        _write(target / 'STOP_PRIVATE_WEB.cmd', 'powershell -File scripts/停止私有網站.ps1')
        with self.assertRaisesRegex(RuntimeError, '停止私有網站'):
            release._validate_release(target)
        _write(target / 'scripts/停止私有網站.ps1')
        with self.assertRaisesRegex(RuntimeError, '私有停止安全'):
            release._validate_release(target)
        _write(target / 'tests/test_私有停止安全.py')
        release._validate_release(target)

    def test_promotion_requires_explicit_approval(self):
        _fake_release(self.install_root, "abc123")
        with self.assertRaises(PermissionError):
            release.promote_release(
                self.install_root,
                release_id="abc123",
                approved=False,
            )

    def test_release_archive_disables_host_eol_conversion(self):
        archive_path = self.install_root / "release.zip"
        argv = release._git_archive_argv(archive_path, "a" * 40)
        self.assertEqual(argv[:4], ["git", "-c", "core.autocrlf=false", "archive"])
        self.assertEqual(argv[-1], "a" * 40)
        self.assertIn(str(archive_path), argv)

    def test_exact_stage_archive_preserves_all_launcher_crlf_bytes(self):
        filenames = ('START_ALL.cmd', 'START_LOCAL_AND_WEB.cmd', 'START_WAVEDECK.cmd',
                     'wavedeck/START_WAVEDECK.cmd')
        with tempfile.TemporaryDirectory(prefix='st-launcher-archive-') as temporary:
            base = Path(temporary)
            repository = base / 'fixture'
            repository.mkdir()
            hooks = base / 'empty-hooks'
            hooks.mkdir()
            (repository / '.gitattributes').write_bytes((ROOT / '.gitattributes').read_bytes())
            expected = {}
            for filename in filenames:
                # fixture 的初始 CMD 模擬 Windows checkout；只正規化複本，不改受審來源。
                raw = (ROOT / filename).read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                raw.decode('ascii')
                expected[filename] = raw
                target = repository / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)

            def run(command):
                result = subprocess.run(command, cwd=repository, capture_output=True,
                    text=True, encoding='utf-8', timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout.strip()

            run(['git', '-c', 'init.defaultBranch=fixture', '-c', 'init.templateDir=', 'init'])
            run(['git', '-c', 'core.autocrlf=true', 'add', '--', '.gitattributes', *filenames])
            run(['git', '-c', 'user.name=Launcher Fixture',
                 '-c', 'user.email=launcher-fixture@example.invalid',
                 '-c', 'commit.gpgsign=false', '-c', f'core.hooksPath={hooks}',
                 'commit', '-m', '驗證啟動器封存位元組'])
            commit = run(['git', 'rev-parse', 'HEAD'])
            archive_path = base / 'exact-stage.zip'
            run(release._git_archive_argv(archive_path, commit))
            with zipfile.ZipFile(archive_path) as archive:
                for filename in filenames:
                    with self.subTest(filename=filename):
                        actual = archive.read(filename)
                        actual.decode('ascii')
                        self.assertIn(b'\r\n', actual)
                        self.assertNotIn(b'\n', actual.replace(b'\r\n', b''))
                        self.assertEqual(actual, expected[filename])

    def test_promote_replaces_code_but_preserves_runtime_data_and_logs(self):
        _fake_release(self.install_root, "abc123")
        current = self.install_root / "current"
        _write(current / "server" / "old_module.py", "old-code")
        _write(current / "data" / "private_web_owner.token", "secret")
        _write(current / "data" / "personal.db", "personal")
        _write(current / "logs" / "audit.jsonl", "audit")
        shared_snapshot = self.install_root / "shared-data" / "etf_history" / "sentinel.json"
        _write(shared_snapshot, "runtime-etf-history")
        shared_before = shared_snapshot.read_bytes()
        _write(
            current / ".private_web_release.json",
            json.dumps(
                {
                    "releaseId": "old000",
                    "tests": "passed",
                    "managedTopLevel": ["server", ".private_web_release.json"],
                    "contentSha256": {"server/old_module.py": "既有管理檔案"},
                }
            ),
        )

        promoted = release.promote_release(
            self.install_root,
            release_id="abc123",
            approved=True,
        )
        # Windows runners may expose the same temp directory through a long
        # path and its 8.3 alias (runneradmin vs RUNNER~1). Compare filesystem
        # identity instead of path spelling.
        self.assertTrue(os.path.samefile(promoted, current))
        self.assertFalse((current / "server" / "old_module.py").exists())
        self.assertEqual((current / "server" / "new_module.py").read_text(), "new-code")
        self.assertEqual((current / "data" / "private_web_owner.token").read_text(), "secret")
        self.assertEqual((current / "data" / "personal.db").read_text(), "personal")
        self.assertEqual((current / "data" / "public_seed.csv").read_text(), "seed")
        self.assertEqual((current / "logs" / "audit.jsonl").read_text(), "audit")
        self.assertEqual(shared_snapshot.read_bytes(), shared_before)
        active = json.loads((current / ".private_web_release.json").read_text(encoding="utf-8"))
        self.assertEqual(active["releaseId"], "abc123")
        self.assertIn("promotedAt", active)

    def test_unverified_release_is_not_promoted(self):
        target = _fake_release(self.install_root, "def456")
        manifest_path = target / ".private_web_release.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["tests"] = "skipped"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "passed tests"):
            release.promote_release(
                self.install_root,
                release_id="def456",
                approved=True,
            )

    def test_private_release_omits_wavedeck_runtime(self):
        tree = self.install_root / "candidate"
        _write(tree / "wavedeck" / "run.py", "wd")
        _write(tree / "START_WAVEDECK.cmd", "wd")
        _write(tree / "START_ALL.cmd", "combined")
        _write(tree / "server" / "server.py", "st")
        release._strip_private_release_extras(tree)
        self.assertFalse((tree / "wavedeck").exists())
        self.assertFalse((tree / "START_WAVEDECK.cmd").exists())
        self.assertFalse((tree / "START_ALL.cmd").exists())
        self.assertTrue((tree / "server" / "server.py").is_file())

    def stage_fixture(self, *, include_plan=True, run_tests=True):
        commit = 'a' * 40
        calls = []
        validations = []
        extras = ['wavedeck/run.py', 'START_WAVEDECK.cmd', 'START_ALL.cmd']
        identity = {'schemaVersion': 1, 'runner': 'c' * 64, 'case': '局部流程',
                    'kind': 'unittest', 'targets': ['tests.test_private_web_release'],
                    'inputs': {'server/server.py': 'd' * 64}, 'environment': {'python': '測試環境'}}
        fingerprint = release.hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        receipt = {
            'schemaVersion': 1, 'status': 'passed', 'commit': commit,
            'baseCommit': 'b' * 40, 'tree': 'e' * 40, 'changedFiles': ['server/server.py'],
            'cases': [{'id': '局部流程', 'decision': 'EXECUTED', 'fingerprint': fingerprint,
                       'identity': identity, 'status': 'passed', 'commit': commit,
                       'command': ['python', '-m', 'unittest', 'tests.test_private_web_release'],
                       'inputs': identity['inputs'], 'environment': identity['environment'],
                       'exitCode': 0, 'evidence': '局部驗證證據'}],
        }

        def run(argv, *, cwd, capture=False):
            calls.append(argv)
            if argv[:2] == ['git', 'ls-tree']:
                # stage 前的封存成員檢查（_validate_git_archive_members）：列出與封存相同的成員
                members = sorted(release.REQUIRED_RELEASE_FILES | set(extras))
                if include_plan:
                    members.append('.github/驗證計畫.json')
                return type('Listing', (), {'stdout': '\0'.join(members) + '\0'})()
            if argv[0] == 'git':
                with zipfile.ZipFile(argv[argv.index('--output') + 1], 'w') as archive:
                    for relative in release.REQUIRED_RELEASE_FILES | set(extras):
                        archive.writestr(relative, '原始內容')
                    if include_plan:
                        archive.writestr('.github/驗證計畫.json', '{}')
            elif 'build_v2.py' in argv:
                _write(cwd / 'server/__pycache__/daemon_lock.cpython-312.pyc', '組建產生的快取')

        def read_plan(root, path, *, base_root, target_commit):
            self.assertEqual(base_root, release.ROOT)
            self.assertEqual(target_commit, commit)
            self.assertTrue(path.is_file())
            self.assertNotEqual(root, base_root)
            return {'commit': target_commit}

        def run_plan(root, path, evidence_dir, *, base_root, target_commit):
            validations.append((root, path, evidence_dir, target_commit))
            for relative in extras:
                self.assertTrue((root / relative).is_file())
            _write(root / 'stock_terminal_v2.html', '清理測試改寫')
            _write(root / 'src/測試殘留.js', '不得出貨')
            return receipt

        helpers = {'read_plan': read_plan, 'run_plan': run_plan}
        with patch.object(release, 'resolve_commit', return_value=(commit, commit[:12])), \
                patch.object(release, '_run', run), \
                patch.object(release, '_validation_helpers', return_value=helpers) as loader:
            staged = release.stage_release(self.install_root, ref=commit, run_tests=run_tests)
            if run_tests:
                loader.assert_called_once_with(validations[0][0])
        return staged, calls, validations

    def test_驗證器從封存入口載入且缺少核心拒絕(self):
        tree = self.install_root / '封存樹'
        _write(tree / 'scripts/變更驗證.py', (ROOT / 'scripts/變更驗證.py').read_text(encoding='utf-8'))
        with self.assertRaisesRegex(RuntimeError, '封存版本缺少'):
            release._validation_helpers(tree)
        _write(tree / 'tools/codex/變更驗證.py', "封存識別 = '封存核心'\n")
        helpers = release._validation_helpers(tree)
        self.assertEqual(helpers['封存識別'], '封存核心')

    def test_發布只執行明列計畫且重建排除測試殘留(self):
        staged, calls, validations = self.stage_fixture()
        self.assertEqual(len(validations), 1)
        self.assertFalse(any('discover' in command for command in calls))
        self.assertFalse(any(command[0] == 'node' for command in calls))
        self.assertEqual(sum('build_v2.py' in command for command in calls), 2)
        self.assertFalse((staged / 'wavedeck').exists())
        self.assertFalse((staged / 'src/測試殘留.js').exists())
        self.assertEqual((staged / 'stock_terminal_v2.html').read_text(encoding='utf-8'), '原始內容')
        self.assertFalse(any(path.name == '__pycache__' for path in staged.rglob('*')))
        manifest = release._read_manifest(staged / release.MANIFEST_NAME)
        self.assertEqual(manifest['manifestVersion'], 3)
        self.assertEqual(len(manifest['validationCommands']), 1)
        release._validate_integrity(staged, manifest)

    def test_發布缺少計畫不自動擴大測試(self):
        with self.assertRaisesRegex(RuntimeError, '缺少明確驗證計畫'):
            self.stage_fixture(include_plan=False)
        self.assertFalse((self.install_root / 'releases' / ('a' * 12)).exists())

    def test_相同SHA的舊版通過證據不重跑(self):
        staged = _fake_release(self.install_root, 'abc123')
        commit = 'abc123'.ljust(40, '0')
        with patch.object(release, 'resolve_commit', return_value=(commit, 'abc123')), \
                patch.object(release, '_run') as run, \
                patch.object(release, '_validation_helpers') as helpers:
            run.return_value.stdout = 'server/server.py\0'
            result = release.stage_release(self.install_root, ref=commit)
        self.assertTrue(os.path.samefile(result, staged))
        run.assert_called_once_with(['git', 'ls-tree', '-r', '--name-only', '-z', commit],
                                    cwd=release.ROOT, capture=True)
        helpers.assert_not_called()

    def test_新收據stage的CLI發布不需要驗證模組(self):
        staged, _, _ = self.stage_fixture()
        # 被測的發布腳本啟動時會載入 runtime_release_policy.py，替身內容不是有效程式，需一併換成正式檔
        for relative in ('scripts/private_web_release.py', 'scripts/runtime_release_policy.py', 'server/daemon_lock.py'):
            shutil.copy2(ROOT / relative, staged / relative)
        manifest = release._read_manifest(staged / release.MANIFEST_NAME)
        manifest['contentSha256'] = release._content_hashes(staged)
        _write(staged / release.MANIFEST_NAME, json.dumps(manifest))
        command = [sys.executable, str(staged / 'scripts/private_web_release.py'),
                   '--install-root', str(self.install_root), 'promote', '--approve',
                   '--release', staged.name]
        result = subprocess.run(command, cwd=self.install_root, capture_output=True,
                                text=True, encoding='utf-8', timeout=30,
                                env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((staged / 'scripts/變更驗證.py').exists())
        release._validate_integrity(staged, manifest)

    def test_略過計畫的stage不能發布(self):
        staged, _, validations = self.stage_fixture(include_plan=False, run_tests=False)
        self.assertFalse(validations)
        with self.assertRaisesRegex(RuntimeError, 'passed tests'):
            release.promote_release(self.install_root, release_id=staged.name, approved=True)

    def test_新版本發布拒絕缺失或篡改驗證收據(self):
        staged, _, _ = self.stage_fixture()
        manifest_path = staged / release.MANIFEST_NAME
        original_manifest = release._read_manifest(manifest_path)
        receipt_path = staged / release.VALIDATION_RECEIPT_NAME
        original_bytes = receipt_path.read_bytes()
        for mode in ('遺失', '篡改', '不同版本', '失敗案例', '缺少描述', '空案例',
                     '缺少命令', '缺少環境', '缺少輸入', '缺少樹', '錯誤指紋', '身分摘要不符'):
            with self.subTest(mode=mode):
                receipt_path.write_bytes(original_bytes)
                manifest = dict(original_manifest)
                if mode == '遺失':
                    receipt_path.unlink()
                elif mode == '篡改':
                    receipt_path.write_text('{}', encoding='utf-8')
                elif mode == '缺少描述':
                    manifest.pop('validationReceipt')
                else:
                    receipt = json.loads(original_bytes)
                    if mode == '不同版本':
                        receipt['commit'] = 'b' * 40
                    elif mode == '失敗案例':
                        receipt['cases'][0]['exitCode'] = 1
                    elif mode == '空案例':
                        receipt['cases'] = []
                    elif mode == '缺少樹':
                        receipt.pop('tree')
                    elif mode == '錯誤指紋':
                        receipt['cases'][0]['fingerprint'] = '通過'
                    elif mode == '身分摘要不符':
                        receipt['cases'][0]['identity']['runner'] = 'f' * 64
                    else:
                        receipt['cases'][0].pop({'缺少命令': 'command', '缺少環境': 'environment',
                                                 '缺少輸入': 'inputs'}[mode])
                    _write(receipt_path, json.dumps(receipt))
                    manifest['validationReceipt'] = {
                        'path': release.VALIDATION_RECEIPT_NAME,
                        'sha256': release.hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                    }
                # 即使內容清單被重算，仍須獨立核對驗證收據。
                manifest['contentSha256'] = release._content_hashes(staged)
                manifest['managedTopLevel'] = sorted(item.name for item in staged.iterdir()
                    if item.name not in release.PRESERVE_NAMES | {release.MANIFEST_NAME})
                _write(manifest_path, json.dumps(manifest))
                with self.assertRaisesRegex(RuntimeError, '驗證收據'):
                    release.promote_release(self.install_root, release_id=staged.name, approved=True)
                self.assertFalse((self.install_root / 'current').exists())

    def test_沿用案例保留舊SHA而整體收據綁定新SHA(self):
        staged, _, _ = self.stage_fixture()
        manifest = release._read_manifest(staged / release.MANIFEST_NAME)
        path = staged / release.VALIDATION_RECEIPT_NAME
        receipt = release._read_manifest(path)
        receipt['cases'][0].update(decision='REUSE', commit='b' * 40)
        _write(path, json.dumps(receipt))
        manifest['validationReceipt']['sha256'] = release.hashlib.sha256(path.read_bytes()).hexdigest()
        release._validate_receipt(staged, manifest)

    def test_standard_discovery_includes_dist_scrub_without_running_it_twice(self):
        # 只收集這個模組，確認正式 discovery 會涵蓋它；不執行分享包建置。
        suite = unittest.TestLoader().discover(str(ROOT / 'tests'), pattern='test_dist_scrub.py')

        def cases(group):
            for item in group:
                if isinstance(item, unittest.TestSuite):
                    yield from cases(item)
                else:
                    yield item

        ids = [case.id() for case in cases(suite)]
        self.assertTrue(ids)
        self.assertTrue(all('.TestDistScrub.test_' in name for name in ids), ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_release_requires_archify_manifest_documents_and_validator(self):
        expected = {
            "docs/architecture/archify-manifest.json",
            "docs/architecture/st-decision-evidence-lineage.dataflow.json",
            "docs/architecture/st-private-web-trust-ai-execution.architecture.json",
            "docs/architecture/st-private-web-release-gate.workflow.json",
            "docs/architecture/st-pulse-refresh-degradation.sequence.json",
            "docs/architecture/st-responsive-shell-ownership.workflow.json",
            "docs/architecture/st-signal-passport-early-warning.lifecycle.json",
            "tests/test_archify_artifacts.py",
            "assets/docs/archify/st-decision-evidence-lineage.html",
            "assets/docs/archify/st-private-web-trust-ai-execution.html",
            "assets/docs/archify/st-private-web-release-gate.html",
            "assets/docs/archify/st-pulse-refresh-degradation.html",
            "assets/docs/archify/st-responsive-shell-ownership.html",
            "assets/docs/archify/st-signal-passport-early-warning.html",
        }
        self.assertTrue(expected.issubset(release.REQUIRED_RELEASE_FILES))

    def test_release_tests_cannot_mutate_committed_seed_bytes(self):
        archive_path = self.install_root / "release.zip"
        committed_seed = b"date,value\r\n2026-08-28,1.0\r\n"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("data/public_seed.csv", committed_seed)
            archive.writestr("server/server.py", b"server")

        tree = self.install_root / "candidate"
        _write(tree / "data" / "public_seed.csv", "mutated\n")
        _write(tree / "data" / "runtime-only.json", "runtime")
        _write(tree / "logs" / "test.log", "test")

        release._restore_preserved_from_archive(archive_path, tree)

        self.assertEqual((tree / "data" / "public_seed.csv").read_bytes(), committed_seed)
        self.assertFalse((tree / "data" / "runtime-only.json").exists())
        self.assertFalse((tree / "logs").exists())


if __name__ == "__main__":
    unittest.main()

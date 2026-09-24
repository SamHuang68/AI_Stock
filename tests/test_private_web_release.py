#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path


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
        "managedTopLevel": ["server", "scripts", "stock_terminal_v2.html"],
        "contentSha256": release._content_hashes(target),
    }
    _write(
        target / ".private_web_release.json",
        json.dumps(manifest),
    )
    return target


class PrivateWebReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.install_root = Path(self.temp.name) / "private" / "install"
        self.install_root.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

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
        manifest = json.loads(manifest_path.read_text())
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
        _write(tree / "server" / "server.py", "st")
        release._strip_private_release_extras(tree)
        self.assertFalse((tree / "wavedeck").exists())
        self.assertFalse((tree / "START_WAVEDECK.cmd").exists())
        self.assertTrue((tree / "server" / "server.py").is_file())

    def test_two_faces_must_sync_before_promote(self):
        rules = (ROOT / ".cursorrules").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        docs = (ROOT / "docs/PRIVATE_WEB_ST.md").read_text(encoding="utf-8")
        script = (ROOT / "scripts/sync_private_web.ps1").read_text(encoding="utf-8")
        self.assertIn("一體兩面", rules)
        self.assertIn("http://localhost:18432/#pulse", rules)
        self.assertIn("evo-t1-st.tailbc3519.ts.net", rules)
        self.assertIn("一體兩面", agents)
        self.assertIn("two faces of the same ST", docs)
        self.assertIn("sync_private_web.ps1", docs)
        self.assertIn("-LayoutVerified", script)
        self.assertIn("http://localhost:18432/#pulse", script)
        self.assertIn("https://evo-t1-st.tailbc3519.ts.net/#pulse", script)
        self.assertIn("拒絕發布", script)
        self.assertNotIn("Start-Process -FilePath 'python'", script)

    def test_verified_stage_is_reusable_without_rebuilding(self):
        commit = "a" * 40
        target = _fake_release(self.install_root, commit[:12])
        manifest = target / ".private_web_release.json"
        value = json.loads(manifest.read_text())
        value["commit"] = commit
        manifest.write_text(json.dumps(value), encoding="utf-8")
        with patch.object(release, "resolve_commit", return_value=(commit, commit[:12])), patch.object(release, "_run") as run:
            reused = release.stage_release(self.install_root, ref=commit)
        self.assertTrue(os.path.samefile(reused, target))
        run.assert_not_called()

    def test_existing_stage_rejects_skipped_tests_or_wrong_commit(self):
        commit = "b" * 40
        target = _fake_release(self.install_root, commit[:12])
        manifest = target / ".private_web_release.json"
        for stored_commit, tests in [(commit, "skipped"), ("c" * 40, "passed")]:
            with self.subTest(commit=stored_commit, tests=tests):
                manifest.write_text(json.dumps({"commit": stored_commit, "releaseId": commit[:12], "tests": tests}), encoding="utf-8")
                with patch.object(release, "resolve_commit", return_value=(commit, commit[:12])):
                    with self.assertRaises(RuntimeError):
                        release.stage_release(self.install_root, ref=commit)

    def test_release_gate_includes_etf_and_shell_node_regressions(self):
        source = (ROOT / "scripts" / "private_web_release.py").read_text(encoding="utf-8")
        self.assertIn('"tests.test_archify_artifacts"', source)
        self.assertIn('shutil.which("node")', source)
        self.assertIn('shutil.which("npm")', source)
        self.assertIn('"-m", "unittest", "-b"', source)
        self.assertIn('"ci", "--include=dev"', source)

    def test_發布階段執行暫存版本全部排序後的前端自測及決策回歸(self):
        commit = 'a' * 40
        selftests = [
            'tests/shell_v5_selftest.js', 'tests/etf_flow_v3_selftest.js',
            'tests/ai_panels_selftest.js', 'tests/台股即時報價_selftest.js',
            'tests/LIVE報價一致性_selftest.js', 'tests/新增_selftest.js',
            'tests/wavedeck_onepage_selftest.js',
            'tests/分類範圍標示_selftest.js',
            'tests/決策更新狀態_selftest.js',
            'tests/個股健診歷史分析_selftest.js',
        ]
        extras = {'wavedeck/web/css/deck.css', 'START_WAVEDECK.cmd'}
        calls = []
        npm_cwd = []

        receipts = []

        def run(argv, *, cwd, capture=False, env=None):
            calls.append(argv)
            if argv[0] == 'git':
                with zipfile.ZipFile(argv[argv.index('--output') + 1], 'w') as archive:
                    for relative in sorted(release.REQUIRED_RELEASE_FILES | set(selftests) | extras):
                        archive.writestr(relative, '受測內容')
                    archive.writestr('package.json', '{"devDependencies":{"playwright":"1.62.1"}}\n')
                    archive.writestr('package-lock.json', '{"lockfileVersion":3}\n')
            else:
                for relative in extras:
                    self.assertEqual((cwd / relative).read_text(encoding='utf-8'), '受測內容',
                                     '完整封存內容必須保留至組建與全部自測結束')
                if argv[:2] == ['npm', 'ci']:
                    self.assertEqual(argv, ['npm', 'ci', '--include=dev'])
                    self.assertTrue((cwd / 'package-lock.json').is_file())
                    self.assertNotEqual(cwd.resolve(), ROOT.resolve())
                    self.assertEqual(cwd.name, 'tree')
                    npm_cwd.append(cwd)
                    playwright = cwd / 'node_modules' / 'playwright'
                    playwright.mkdir(parents=True)
                    (playwright / 'index.js').write_text('module.exports = {};', encoding='utf-8')
                if argv[0] == 'node' and argv[1].endswith('_browser.cjs'):
                    output = Path(env['ST_BROWSER_OUTPUT']).resolve()
                    self.assertFalse(output.is_relative_to(cwd.resolve()))
                    self.assertTrue(output.is_relative_to(self.install_root.resolve()))
                    self.assertTrue((cwd / 'node_modules' / 'playwright' / 'index.js').is_file())
                    receipt = output / '版面驗收.json'
                    receipt.write_text('{"通過":true}', encoding='utf-8')
                    receipts.append(receipt)

        def which(name):
            return {'node': 'node', 'npm': 'npm'}.get(name)

        with patch.object(release, 'resolve_commit', return_value=(commit, commit[:12])), \
                patch.object(release, '_run', run), patch.object(release.shutil, 'which', side_effect=which):
            staged = release.stage_release(self.install_root, ref=commit)
        node_scripts = [argv[1] for argv in calls if argv[0] == 'node']
        self.assertEqual(node_scripts, sorted(selftests) +
                         ['tests/研究工作台_browser.cjs', 'tests/手機橫向五欄_browser.cjs',
                          'tests/外殼研究互動_browser.cjs', 'tests/選股候選_browser.cjs'])
        npm_at = next(i for i, argv in enumerate(calls) if argv[:2] == ['npm', 'ci'])
        browser_at = next(i for i, argv in enumerate(calls) if argv[0] == 'node' and argv[1].endswith('_browser.cjs'))
        self.assertLess(npm_at, browser_at)
        self.assertEqual(len(npm_cwd), 1)
        python_tests = next(argv for argv in calls if '-m' in argv)
        for test in ['tests.test_決策資料品質', 'tests.test_發布完整性',
                     'tests.test_decision_context', 'tests.test_decision_http',
                     'tests.test_情境投組HTTP']:
            self.assertIn(test, python_tests)
        manifest = release._read_manifest(staged / release.MANIFEST_NAME)
        release._validate_integrity(staged, manifest)
        self.assertEqual(len(receipts), 4)
        self.assertTrue(all(receipt.is_file() for receipt in receipts))
        self.assertFalse((staged / 'scratch').exists())
        self.assertFalse((staged / 'node_modules').exists())
        self.assertNotIn('scratch', manifest['managedTopLevel'])
        self.assertNotIn('node_modules', manifest['managedTopLevel'])
        self.assertNotIn('node_modules/playwright/index.js', manifest['contentSha256'])
        for name in release.PRIVATE_RELEASE_EXCLUDES:
            self.assertFalse((staged / name).exists(), '私人網站發布產物不得包含 WaveDeck 執行內容')
            self.assertNotIn(name, manifest['managedTopLevel'])
        self.assertFalse(any(key.split('/')[0] in release.PRIVATE_RELEASE_EXCLUDES
                             for key in manifest['contentSha256']))

    def test_browser_stage_requires_npm_when_lockfile_present(self):
        commit = 'd' * 40
        calls = []

        def run(argv, *, cwd, capture=False, env=None):
            calls.append(argv)
            if argv[0] == 'git':
                with zipfile.ZipFile(argv[argv.index('--output') + 1], 'w') as archive:
                    for relative in release.REQUIRED_RELEASE_FILES:
                        archive.writestr(relative, '受測內容')
                    archive.writestr('package-lock.json', '{"lockfileVersion":3}\n')

        def which(name):
            return 'node' if name == 'node' else None

        with patch.object(release, 'resolve_commit', return_value=(commit, commit[:12])), \
                patch.object(release, '_run', run), patch.object(release.shutil, 'which', side_effect=which):
            with self.assertRaisesRegex(RuntimeError, 'npm is required'):
                release.stage_release(self.install_root, ref=commit)
        self.assertFalse(any(argv[0] == 'node' and argv[1].endswith('_browser.cjs') for argv in calls))
        self.assertFalse(any(argv[:2] == ['npm', 'ci'] for argv in calls))

    def test_windows_npm_cmd_runs_through_cmd(self):
        npm = r'C:\Program Files\nodejs\npm.cmd'
        with patch.object(release.subprocess, 'run') as run, patch.object(release.os, 'name', 'nt'):
            release._run([npm, 'ci', '--include=dev'], cwd=self.install_root)
        args, kwargs = run.call_args
        self.assertTrue(kwargs['shell'])
        self.assertIsInstance(args[0], str)
        self.assertIn('npm.cmd', args[0])
        self.assertIn('ci', args[0])
        self.assertIn('--include=dev', args[0])
        self.assertEqual(kwargs['cwd'], self.install_root)
        self.assertNotEqual(kwargs['cwd'], ROOT)

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

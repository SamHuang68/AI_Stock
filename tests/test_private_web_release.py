#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
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
        active = json.loads((current / ".private_web_release.json").read_text())
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

    def test_release_gate_includes_etf_and_shell_node_regressions(self):
        # 驗證實際命令及順序，包含新增的自測；不靠寫死的檔名通過。
        commit = 'a' * 40
        calls = []
        selftests = ['tests/etf_flow_v3_selftest.js', 'tests/shell_v5_selftest.js',
                     'tests/新增_selftest.js']
        extras = ['wavedeck/run.py', 'START_WAVEDECK.cmd']
        def run(argv, *, cwd, capture=False):
            calls.append(argv)
            if argv[0] == 'git':
                with zipfile.ZipFile(argv[argv.index('--output') + 1], 'w') as archive:
                    for relative in release.REQUIRED_RELEASE_FILES | set(selftests + extras):
                        archive.writestr(relative, '原始內容')
            else:
                for relative in extras:
                    self.assertTrue((cwd / relative).is_file())
                if 'unittest' in argv:
                    _write(cwd / 'stock_terminal_v2.html', '清理測試改寫')
                    _write(cwd / 'src/測試殘留.js', '不得出貨')
                if argv[0] == 'node':
                    self.assertEqual((cwd / 'stock_terminal_v2.html').read_text(encoding='utf-8'), '原始內容')
                    self.assertFalse((cwd / 'src/測試殘留.js').exists())
        with patch.object(release, 'resolve_commit', return_value=(commit, commit[:12])), \
                patch.object(release, '_run', run), patch.object(release.shutil, 'which', return_value='node'):
            staged = release.stage_release(self.install_root, ref=commit)
        self.assertEqual([argv[1] for argv in calls if argv[0] == 'node'], sorted(selftests))
        self.assertTrue(any(argv[1:] == ['-m', 'unittest', 'discover', '-s', 'tests', '-b'] for argv in calls))
        self.assertTrue(any('wavedeck.tests.test_smoke' in argv for argv in calls))
        self.assertTrue(any('tests.test_dist_scrub' in argv for argv in calls))
        self.assertEqual(sum('build_v2.py' in argv for argv in calls), 3)
        for relative in extras:
            self.assertFalse((staged / relative).exists())
        self.assertFalse((staged / 'src/測試殘留.js').exists())
        release._validate_integrity(staged, release._read_manifest(staged / release.MANIFEST_NAME))

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

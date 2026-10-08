# -*- coding: utf-8 -*-
"""Distribution builds must be complete, reproducible and privacy-safe."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_dist  # noqa: E402


class TestDistScrub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix='st-dist-tests-'))
        cls.pending_share_processes = []
        cls.zip_path = cls.temp_dir / "Stock_Terminal_v5.0.zip"
        build_dist.build(cls.zip_path)
        cls.checksum_path, cls.manifest_path = build_dist.sidecar_paths(cls.zip_path)
        with zipfile.ZipFile(cls.zip_path, "r") as archive:
            cls.names = {name.replace("\\", "/") for name in archive.namelist()}

    @classmethod
    def tearDownClass(cls):
        if cls.pending_share_processes:
            # 未確認終態的子程序可能仍使用分享包；保留它與輸出，不猜測子樹已停止。
            return
        resolved = cls.temp_dir.resolve()
        if resolved.parent != Path(tempfile.gettempdir()).resolve() or not resolved.name.startswith('st-dist-tests-'):
            raise AssertionError('拒絕清理未知的發布測試目錄')
        shutil.rmtree(resolved)

    def test_archive_passes_same_post_compression_scanner(self):
        self.assertEqual(build_dist.verify_archive(self.zip_path), [])

    def test_review_regressions_run_from_the_actual_single_machine_share(self):
        target = self.temp_dir / 'share-regression-fixture'
        target.mkdir()
        with zipfile.ZipFile(self.zip_path) as archive:
            for item in archive.infolist():
                self.assertTrue((target / item.filename).resolve().is_relative_to(target.resolve()))
            archive.extractall(target)
        share = target / 'Stock_Terminal'
        self.assertFalse((share / 'server/private_web_gateway.py').exists())
        for name in ('test_server_http_security.py', 'test_Pulse讀寫分離.py', 'test_decision_http.py'):
            self.assertTrue((share / 'tests' / name).is_file(), name)
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'unittest',
                                 'tests.test_review_regressions', '-v'], cwd=share,
                                env=dict(os.environ, PYTHONUTF8='1'), capture_output=True,
                                text=True, encoding='utf-8', timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('單機分享包不包含 Private Web gateway', result.stderr)
        self.assertIn('OK (skipped=1)', result.stderr)
        discovery = """
import json, unittest
def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item.id()
print(json.dumps(list(cases(unittest.defaultTestLoader.loadTestsFromName('tests.test_launcher_cmd')))))
"""
        listing = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', discovery], cwd=share,
                                 env=dict(os.environ, PYTHONUTF8='1'), capture_output=True,
                                 text=True, encoding='utf-8', timeout=15)
        self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
        ids = json.loads(listing.stdout)
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(name.startswith('tests.test_launcher_cmd.') for name in ids), ids)
        self.assertTrue(any('.LauncherJsonHealthOfflineTests.' in name for name in ids))
        self.assertTrue(any('.LauncherNativeWaitTests.' in name for name in ids))
        records = []
        # 複合情境已拆開；每個具名案例保留原外層90秒，內層CMD30／PS15不變。
        for number, name in enumerate(ids):
            argv = [sys.executable, '-B', '-u', '-X', 'utf8', '-m', 'unittest', name, '-v']
            started = time.monotonic()
            stdout_path = target / f'launcher-case-{number}-stdout.log'
            stderr_path = target / f'launcher-case-{number}-stderr.log'
            # Windows 的 PIPE reader 可能等到 EOF 才交回部分輸出；從啟動起直接留檔。
            with stdout_path.open('wb') as out, stderr_path.open('wb') as err:
                process = subprocess.Popen(argv, cwd=share, env=dict(os.environ, PYTHONUTF8='1'),
                                           stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                try:
                    process.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    type(self).pending_share_processes.append(process)
                    self.fail(f'分享包案例 {name} 超時；保留自有程序 handle、PID {process.pid}、fixture {target} 與已寫日誌，未終止子樹。')
            stdout = stdout_path.read_text(encoding='utf-8')
            stderr = stderr_path.read_text(encoding='utf-8')
            records.append({'id': name, 'seconds': time.monotonic() - started,
                            'exitCode': process.returncode, 'outerSeconds': 90})
            (target / 'launcher-case-results.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            self.assertEqual(process.returncode, 0, name + '\n' + stdout + stderr)
            self.assertIn('OK', stderr)
            if os.name == 'nt':
                self.assertNotIn('skipped=', stderr, 'Windows 分享包必須真的執行每個啟動器案例：' + name)
        self.assertEqual({record['id'] for record in records}, set(ids))

    def test_has_core_share_files(self):
        required = {
            "Stock_Terminal/README.md",
            "Stock_Terminal/LICENSE",
            "Stock_Terminal/START_TIP.cmd",
            "Stock_Terminal/START_LOCAL_AND_WEB.cmd",
            "Stock_Terminal/server/server.py",
            "Stock_Terminal/server/daemon_lock.py",
            "Stock_Terminal/server/market_contract.py",
            "Stock_Terminal/server/decision_context.py",
            "Stock_Terminal/server/decision_routes.py",
            "Stock_Terminal/server/exposure_lab.py",
            "Stock_Terminal/server/benchmark_research.py",
            "Stock_Terminal/server/international_fundamental.py",
            "Stock_Terminal/server/options_exposure.py",
            "Stock_Terminal/server/options_routes.py",
            "Stock_Terminal/server/options_schedule.py",
            "Stock_Terminal/server/overnight_intraday.py",
            "Stock_Terminal/server/overnight_intraday_routes.py",
            "Stock_Terminal/server/sector_history.py",
            "Stock_Terminal/src/core/market_data_v5.js",
            "Stock_Terminal/src/core/app_kernel_v5.js",
            "Stock_Terminal/src/core/decision_data_v5.js",
            "Stock_Terminal/src/core/market_intel_v5.js",
            "Stock_Terminal/src/core/table_sort_v5.js",
            "Stock_Terminal/src/ui/chart_visual_v5.js",
            "Stock_Terminal/src/ui/pulse_v5.js",
            "Stock_Terminal/src/ui/decision_v5.js",
            "Stock_Terminal/src/ui/visual_system_v5.js",
            "Stock_Terminal/tests/test_market_contract.py",
            "Stock_Terminal/tests/test_decision_context.py",
            "Stock_Terminal/tests/test_exposure_lab.py",
            "Stock_Terminal/tests/test_benchmark_research.py",
            "Stock_Terminal/tests/test_options_exposure.py",
            "Stock_Terminal/tests/test_options_schedule.py",
            "Stock_Terminal/tests/test_review_regressions.py",
            "Stock_Terminal/tests/test_launcher_cmd.py",
            "Stock_Terminal/tests/test_launcher_pull.py",
            "Stock_Terminal/tests/review_market_state_selftest.js",
            "Stock_Terminal/tests/test_server_startup_order.py",
            "Stock_Terminal/tests/test_overnight_intraday.py",
            "Stock_Terminal/tests/layout_visual_v5_selftest.js",
            "Stock_Terminal/docs/ST_ARCHITECTURE_REMEDIATION_2026-08-16.md",
            "Stock_Terminal/docs/OVERNIGHT_INTRADAY_RESEARCH.md",
            "Stock_Terminal/wavedeck/run.py",
            "Stock_Terminal/wavedeck/docs/ARCHITECTURE.md",
        }
        self.assertTrue(required.issubset(self.names), required - self.names)

    def test_archify_package_is_complete_without_visual_or_receipt_sidecars(self):
        expected = {
            "Stock_Terminal/docs/architecture/archify-manifest.json",
            "Stock_Terminal/docs/architecture/st-decision-evidence-lineage.dataflow.json",
            "Stock_Terminal/docs/architecture/st-private-web-trust-ai-execution.architecture.json",
            "Stock_Terminal/docs/architecture/st-private-web-release-gate.workflow.json",
            "Stock_Terminal/docs/architecture/st-pulse-refresh-degradation.sequence.json",
            "Stock_Terminal/docs/architecture/st-responsive-shell-ownership.workflow.json",
            "Stock_Terminal/docs/architecture/st-signal-passport-early-warning.lifecycle.json",
            "Stock_Terminal/assets/docs/archify/st-decision-evidence-lineage.html",
            "Stock_Terminal/assets/docs/archify/st-private-web-trust-ai-execution.html",
            "Stock_Terminal/assets/docs/archify/st-private-web-release-gate.html",
            "Stock_Terminal/assets/docs/archify/st-pulse-refresh-degradation.html",
            "Stock_Terminal/assets/docs/archify/st-responsive-shell-ownership.html",
            "Stock_Terminal/assets/docs/archify/st-signal-passport-early-warning.html",
        }
        self.assertTrue(expected.issubset(self.names), expected - self.names)
        for name in self.names:
            if "/assets/docs/archify/" not in name:
                continue
            lower = name.lower()
            self.assertNotIn("visual-check", lower, msg=name)
            self.assertNotIn(".archify-delivery-", lower, msg=name)
            self.assertNotIn("receipt", lower, msg=name)

    def test_excludes_internal_context_and_runtime_state(self):
        forbidden_parts = {
            ".git",
            ".cursorrules",
            "TIP_BRANCH",
            "logs",
            "revision.md",
            "antigravity_handoff_audit.md",
            "stock_python.path",
            "runtime_state.json",
            "wavedeck.port",
            "decision_history.db",
            "decision_history.db-wal",
            "decision_history.db-shm",
        }
        for name in self.names:
            parts = set(Path(name).parts)
            self.assertFalse(parts & forbidden_parts, msg=name)

    def test_single_machine_share_excludes_private_web_overlay(self):
        forbidden = {
            "Stock_Terminal/START_PRIVATE_WEB.cmd",
            "Stock_Terminal/START_PRIVATE_WEB_HOST.cmd",
            "Stock_Terminal/server/private_web_gateway.py",
            "Stock_Terminal/server/private_web_access.py",
            "Stock_Terminal/scripts/private_web_host.py",
            "Stock_Terminal/scripts/private_web_release.py",
            "Stock_Terminal/scripts/setup_private_web.py",
            "Stock_Terminal/tests/test_private_web_gateway.py",
            "Stock_Terminal/tests/test_private_web_access.py",
            "Stock_Terminal/tests/test_private_web_host.py",
            "Stock_Terminal/tests/test_private_web_release.py",
            "Stock_Terminal/docs/PRIVATE_WEB_ST.md",
            "Stock_Terminal/docs/PRIVATE_WEB_LOGIN_GUIDE.md",
            "Stock_Terminal/data/private_web_access_requests.json",
        }
        self.assertFalse(forbidden & self.names, forbidden & self.names)

    def test_personal_history_directories_only_have_readme(self):
        for name in self.names:
            parts = [part.lower() for part in Path(name).parts]
            if "chip_history" in parts or "etf_history" in parts:
                self.assertEqual(Path(name).name.lower(), "readme.txt", msg=name)
            if "wavedeck" in parts and "data" in parts:
                self.assertEqual(Path(name).name.lower(), "readme.txt", msg=name)

    def test_checksum_and_manifest_match_archive(self):
        self.assertTrue(self.checksum_path.is_file())
        self.assertTrue(self.manifest_path.is_file())
        expected = hashlib.sha256(self.zip_path.read_bytes()).hexdigest()
        self.assertTrue(self.checksum_path.read_text(encoding="ascii").startswith(expected))
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["sha256"], expected)
        self.assertEqual(manifest["privacyChecks"]["archiveRescan"], "passed")
        self.assertGreater(manifest["files"], 100)

    def test_content_scanner_recognizes_constructed_sensitive_values(self):
        fake_key = "sk-" + ("x" * 24)
        fake_path = "C:" + "\\" + "Users" + "\\" + "ExamplePerson" + "\\project"
        issues = build_dist.scan_text("sample.txt", fake_key + "\n" + fake_path)
        rules = {issue["rule"] for issue in issues}
        self.assertIn("openai-anthropic-key", rules)
        self.assertIn("windows-user-path", rules)

    def test_decision_runtime_database_is_explicitly_blocked(self):
        for name in ("decision_history.db", "decision_history.db-wal", "decision_history.db-shm"):
            self.assertIn(name, build_dist.DATA_BLOCK_FILES)

    def test_options_runtime_snapshots_are_explicitly_blocked(self):
        for name in ("options_structure_cache.json", "options_structure_history.json"):
            self.assertIn(name, build_dist.DATA_BLOCK_FILES)
            self.assertTrue(build_dist.is_blocked_name(name))
        self.assertTrue(build_dist.is_blocked_name("options_structure_history.json.123.456.tmp"))

    def test_preflight_rejects_required_files_outside_git_index(self):
        required = set(build_dist.REQUIRED_SHARE_FILES)
        with mock.patch.object(build_dist, "TRACKED_FILES", set()):
            with self.assertRaisesRegex(RuntimeError, "not in Git index"):
                build_dist.validate_required_share_files()
        self.assertIn("server/decision_context.py", required)
        self.assertIn("server/options_exposure.py", required)
        self.assertIn("docs/architecture/archify-manifest.json", required)
        self.assertIn("tests/test_archify_artifacts.py", required)


if __name__ == "__main__":
    unittest.main()

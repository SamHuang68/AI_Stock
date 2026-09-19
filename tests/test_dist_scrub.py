# -*- coding: utf-8 -*-
"""Distribution builds must be complete, reproducible and privacy-safe."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_dist  # noqa: E402


class TestModulePrivacyScan(unittest.TestCase):
    WORKER_PATH = "assets/vendor/pdfjs/6.3.289/pdf.worker.min.mjs"

    def scan_fixture(self, relative_name, data, extra_files=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / build_dist.STAGE_NAME
            target = stage / relative_name
            target.parent.mkdir(parents=True)
            target.write_bytes(data)
            for relative, content in (extra_files or {}).items():
                extra = stage / relative
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_bytes(content)
            staged = build_dist.scan_stage_content(stage)
            archive = root / "模組檢查.zip"
            build_dist.make_zip(stage, archive)
            return staged, build_dist.verify_archive(archive)

    def test_module_formats_are_scanned_before_and_after_compression(self):
        credential = ("sk-" + "x" * 24).encode("ascii")
        for suffix in (".mjs", ".cjs"):
            with self.subTest(format=suffix):
                for issues in self.scan_fixture("src/module" + suffix, credential):
                    self.assertEqual({issue["rule"] for issue in issues}, {"openai-anthropic-key"})

    def test_original_worker_email_false_positive_requires_exact_path(self):
        original = (ROOT / self.WORKER_PATH).read_bytes()
        for issues in self.scan_fixture(self.WORKER_PATH, original):
            self.assertEqual(issues, [])
        for issues in self.scan_fixture("assets/copied.worker.mjs", original):
            self.assertIn("email-address", {issue["rule"] for issue in issues})

    def test_changed_worker_cannot_reauthorize_itself_through_manifest(self):
        original = (ROOT / self.WORKER_PATH).read_bytes()
        changed = original + ("\n// " + "sk-" + "x" * 24).encode("ascii")
        forged = json.dumps({"檔案SHA256": {
            "pdf.worker.min.mjs": hashlib.sha256(changed).hexdigest(),
        }}, ensure_ascii=False).encode("utf-8")
        manifest_path = str(Path(self.WORKER_PATH).parent / "來源資訊.json")
        for issues in self.scan_fixture(self.WORKER_PATH, changed, {manifest_path: forged}):
            rules = {issue["rule"] for issue in issues}
            self.assertIn("email-address", rules)
            self.assertIn("openai-anthropic-key", rules)

    def test_newline_change_does_not_preserve_original_byte_exception(self):
        original = (ROOT / self.WORKER_PATH).read_bytes()
        self.assertIn(b"\n", original)
        changed = original.replace(b"\n", b"\r\n", 1)
        for issues in self.scan_fixture(self.WORKER_PATH, changed):
            self.assertIn("email-address", {issue["rule"] for issue in issues})

    def test_verified_worker_still_runs_other_scan_rules(self):
        original = (ROOT / self.WORKER_PATH).read_bytes()
        # 用確定出現在原檔的內容驗證其他規則仍會執行，不修改受信任雜湊。
        rules = build_dist.SENSITIVE_CONTENT_RULES + (("測試其他規則", re.compile("PDF")),)
        with mock.patch.object(build_dist, "SENSITIVE_CONTENT_RULES", rules):
            for issues in self.scan_fixture(self.WORKER_PATH, original):
                self.assertEqual({issue["rule"] for issue in issues}, {"測試其他規則"})


class TestDistScrub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.zip_path = Path(cls.temp_dir.name) / "Stock_Terminal_v5.0.zip"
        build_dist.build(cls.zip_path)
        cls.checksum_path, cls.manifest_path = build_dist.sidecar_paths(cls.zip_path)
        with zipfile.ZipFile(cls.zip_path, "r") as archive:
            cls.names = {name.replace("\\", "/") for name in archive.namelist()}

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_archive_passes_same_post_compression_scanner(self):
        self.assertEqual(build_dist.verify_archive(self.zip_path), [])

    def test_has_core_share_files(self):
        required = {
            "Stock_Terminal/README.md",
            "Stock_Terminal/LICENSE",
            "Stock_Terminal/assets/vendor/pdfjs/6.3.289/pdf.min.mjs",
            "Stock_Terminal/assets/vendor/pdfjs/6.3.289/pdf.worker.min.mjs",
            "Stock_Terminal/assets/vendor/pdfjs/6.3.289/來源資訊.json",
            "Stock_Terminal/START_TIP.cmd",
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

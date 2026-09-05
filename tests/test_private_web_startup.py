#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_private_web_startup.ps1"


def _powershell() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")


def _write(path: Path, value: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _fake_current(install_root: Path, *, tests: str = "passed") -> tuple[Path, Path]:
    current = install_root / "current"
    marker = current / "host-was-started.txt"
    _write(
        current / "scripts" / "private_web_host.py",
        "from pathlib import Path\nPath(__file__).resolve().parents[1].joinpath('host-was-started.txt').write_text('started')\n",
    )
    _write(current / "server" / "server.py")
    _write(current / "server" / "private_web_gateway.py")
    _write(current / "data" / "private_web_owner.token", "測試用非正式資料")
    _write(current / "data" / "stock_python.path", str(Path(sys.executable).resolve()))
    commit = "a" * 40
    _write(
        current / ".private_web_release.json",
        json.dumps(
            {
                "releaseId": commit[:12],
                "commit": commit,
                "tests": tests,
                "promotedAt": "2026-09-05T00:00:00+08:00",
            }
        ),
    )
    return current, marker


@unittest.skipUnless(os.name == "nt" and _powershell(), "需要 Windows PowerShell")
class PrivateWebStartupTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                _powershell(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                *args,
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=20,
            check=False,
        )

    def test_inspect_builds_interactive_logon_contract_from_promoted_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "private-web"
            current, _ = _fake_current(install_root)
            result = self._run("-Mode", "Inspect", "-InstallRoot", str(install_root))

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout.lstrip("\ufeff"))
            self.assertEqual(payload["TaskName"], "StockTerminal_PrivateWeb_Host")
            self.assertEqual(payload["StartupMode"], "InteractiveAtLogOn")
            self.assertEqual(payload["TriggerType"], "AtLogOn")
            self.assertFalse(payload["CanRunBeforeLogon"])
            self.assertFalse(payload["RequiresCredential"])
            self.assertEqual(payload["ExpectedLogonType"], "Interactive")
            self.assertEqual(payload["TriggerDelay"], "PT30S")
            self.assertEqual(payload["MultipleInstances"], "IgnoreNew")
            self.assertEqual(payload["RestartCount"], 12)
            self.assertEqual(payload["RestartInterval"], "PT1M")
            self.assertEqual(payload["ExecutionTimeLimit"], "PT0S")
            self.assertTrue(payload["StartWhenAvailable"])
            self.assertEqual(Path(payload["CurrentRoot"]), current)
            self.assertEqual(Path(payload["ActionWorkingDirectory"]), current)
            self.assertEqual(
                Path(payload["RunnerPath"]), install_root / "startup" / "private_web_startup.ps1"
            )
            self.assertFalse((current / "scripts" / SCRIPT.name).exists())
            self.assertIn("-Mode RunHost", payload["ActionArguments"])
            self.assertIn("-WindowStyle Hidden", payload["ActionArguments"])
            self.assertIn(str(install_root), payload["ActionArguments"])
            self.assertNotIn("private_web_owner.token", payload["ActionArguments"])

    def test_password_startup_is_explicit_and_never_selected_silently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "private-web"
            _fake_current(install_root)
            result = self._run(
                "-Mode",
                "Inspect",
                "-StartupMode",
                "PasswordAtStartup",
                "-InstallRoot",
                str(install_root),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout.lstrip("\ufeff"))
            self.assertEqual(payload["TriggerType"], "AtStartup")
            self.assertEqual(payload["ExpectedLogonType"], "Password")
            self.assertTrue(payload["CanRunBeforeLogon"])
            self.assertTrue(payload["RequiresCredential"])

    def test_unverified_current_is_rejected_before_task_access(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "private-web"
            _fake_current(install_root, tests="skipped")
            result = self._run("-Mode", "Inspect", "-InstallRoot", str(install_root))

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("尚未通過 release tests", result.stderr)

    def _serve_health(self, payload: dict) -> tuple[http.server.ThreadingHTTPServer, threading.Thread]:
        encoded = json.dumps(payload).encode("utf-8")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - HTTP handler API
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format, *_args):
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_runhost_keeps_an_existing_healthy_isolated_host(self):
        server, thread = self._serve_health(
            {"ok": True, "gateway": "private-web", "mode": "isolated-host", "upstream": True}
        )
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                install_root = Path(temp_dir) / "private-web"
                _, marker = _fake_current(install_root)
                result = self._run(
                    "-Mode",
                    "RunHost",
                    "-InstallRoot",
                    str(install_root),
                    "-GatewayPort",
                    str(server.server_port),
                    "-BackendPort",
                    str(18436 if server.server_port == 18435 else 18435),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("未重新啟動", result.stdout)
                self.assertFalse(marker.exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_runhost_does_not_kill_or_replace_a_dev_linked_gateway(self):
        server, thread = self._serve_health(
            {"ok": True, "gateway": "private-web", "mode": "dev-linked", "upstream": True}
        )
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                install_root = Path(temp_dir) / "private-web"
                _, marker = _fake_current(install_root)
                result = self._run(
                    "-Mode",
                    "RunHost",
                    "-InstallRoot",
                    str(install_root),
                    "-GatewayPort",
                    str(server.server_port),
                    "-BackendPort",
                    str(18436 if server.server_port == 18435 else 18435),
                )
                self.assertEqual(result.returncode, 23, result.stderr)
                self.assertIn("不終止或取代", result.stderr)
                self.assertFalse(marker.exists())
                self.assertIsNotNone(thread)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class PrivateWebStartupStaticTests(unittest.TestCase):
    def test_script_never_places_a_password_or_token_in_task_arguments(self):
        source = SCRIPT.read_text(encoding="utf-8")
        action_block = source.split("$arguments =", 1)[1].split("$isBoot =", 1)[0]
        self.assertNotIn("Credential", action_block)
        self.assertNotIn("Password", action_block)
        self.assertNotIn("owner.token", action_block)
        self.assertIn("-Mode RunHost", action_block)

    def test_script_has_no_stop_or_kill_operation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("Stop-Process", source)
        self.assertNotIn("taskkill", source.lower())
        self.assertNotIn("Stop-ScheduledTask", source)

    def test_idempotent_match_returns_before_any_credential_prompt(self):
        source = SCRIPT.read_text(encoding="utf-8")
        installer = source.split("function Install-PrivateWebTask", 1)[1]
        self.assertLess(installer.index("Test-TaskMatchesDefinition"), installer.index("Get-Credential"))
        self.assertIn("未改動排程，也未重啟既存 host", installer)

    def test_stable_runner_copy_is_hash_verified_and_outside_current(self):
        source = SCRIPT.read_text(encoding="utf-8")
        copy_block = source.split("function Install-StableRunner", 1)[1].split(
            "function Test-TaskMatchesDefinition", 1
        )[0]
        self.assertIn("startup\\private_web_startup.ps1", source)
        self.assertGreaterEqual(copy_block.count("Get-Sha256"), 4)
        self.assertIn("Move-Item", copy_block)
        self.assertNotIn("current\\scripts\\install_private_web_startup.ps1", source)

    def test_same_name_task_requires_installer_ownership_markers(self):
        source = SCRIPT.read_text(encoding="utf-8")
        ownership = source.split("function Test-TaskOwnedByInstaller", 1)[1].split(
            "function Write-StartupEvent", 1
        )[0]
        self.assertIn("PrincipalSid", ownership)
        self.assertIn("Description", ownership)
        self.assertIn("RunnerPath", ownership)
        self.assertIn("-Mode RunHost", ownership)
        self.assertIn("避免覆寫無關工作", source)


if __name__ == "__main__":
    unittest.main()

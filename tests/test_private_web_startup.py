#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import socket
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
        # 先把主控台輸出編碼設成 UTF-8（與其他啟動器測試相同）：腳本輸出中文，
        # 碼頁為 CP950 的機器或英文碼頁的 CI 若直接以 UTF-8 解碼會失敗。
        tokens = [a if re.fullmatch(r"-[A-Za-z]+", a) else "'" + a.replace("'", "''") + "'" for a in args]
        command = (
            "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
            + "& '" + str(SCRIPT).replace("'", "''") + "' " + " ".join(tokens)
            + "; exit $LASTEXITCODE"
        )
        return subprocess.run(
            [
                _powershell(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
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

    def test_runhost_starts_the_host_in_its_own_console_and_logs_its_exit(self):
        # 2026-11 事故：host 與啟動器共用同一個隱藏主控台，視窗一被關閉兩者一起無聲死亡。
        # 假 host 回報自己主控台上的程序清單；啟動器（host 的父程序）不能在其中。
        host = (
            "import ctypes, json, os\n"
            "from pathlib import Path\n"
            "buf = (ctypes.c_uint32 * 64)()\n"
            "n = ctypes.windll.kernel32.GetConsoleProcessList(buf, 64)\n"
            "Path(__file__).resolve().parents[1].joinpath('console.json').write_text(\n"
            "    json.dumps({'pid': os.getpid(), 'ppid': os.getppid(), 'console': list(buf)[:n]}))\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            install_root = Path(temp_dir) / "private-web"
            current, _ = _fake_current(install_root)
            _write(current / "scripts" / "private_web_host.py", host)
            sockets = [socket.socket() for _ in range(2)]
            try:
                for sock in sockets:
                    sock.bind(("127.0.0.1", 0))
                backend_port, gateway_port = (sock.getsockname()[1] for sock in sockets)
            finally:
                for sock in sockets:
                    sock.close()
            result = self._run(
                "-Mode", "RunHost", "-InstallRoot", str(install_root),
                "-GatewayPort", str(gateway_port), "-BackendPort", str(backend_port),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((current / "console.json").read_text(encoding="utf-8"))
            self.assertNotIn(report["ppid"], report["console"], "host 與啟動器共用了主控台")
            lines = (current / "logs" / "private_web_startup.jsonl").read_text(encoding="utf-8-sig").splitlines()
            events = [json.loads(line) for line in lines if line.strip()]
            self.assertEqual(
                [e["event"] for e in events if e["event"] in ("host_start", "host_spawned", "host_exit")],
                ["host_start", "host_spawned", "host_exit"],
            )
            self.assertEqual(next(e for e in events if e["event"] == "host_spawned")["hostPid"], report["pid"])
            self.assertEqual(next(e for e in events if e["event"] == "host_exit")["exitCode"], 0)


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

    def test_host_is_started_with_its_own_console_not_a_foreground_call(self):
        source = SCRIPT.read_text(encoding="utf-8")
        launcher = source.split("function Invoke-CurrentHost", 1)[1].split("function Install-PrivateWebTask", 1)[0]
        self.assertIn("CreateNoWindow = $true", launcher)
        self.assertIn("UseShellExecute = $false", launcher)
        self.assertIn("WaitForExit()", launcher)
        # `& python` 前景呼叫會與啟動器共用主控台，正是 2026-11 三次消失的結構。
        self.assertNotIn("& $Release.PythonPath", launcher)
        self.assertIn("host_exit", launcher)

    def test_console_control_events_are_logged_and_not_swallowed(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Register-ConsoleCtrlLogger -Release $Release", source.split("function Invoke-CurrentHost", 1)[1])
        handler = source.split("private static bool OnControl", 1)[1].split("PrivateWebCtrlLogSource", 1)[0]
        self.assertIn("console_ctrl", handler)
        self.assertIn("recentProcesses", handler)
        self.assertIn("return false;", handler)  # 記錄後交還預設處理，不吞掉事件
        # 記錄器失敗不能擋住 host 啟動。
        register = source.split("function Register-ConsoleCtrlLogger", 1)[1].split("function Invoke-CurrentHost", 1)[0]
        self.assertIn("catch", register)
        self.assertIn("ctrl_logger_unavailable", register)


if __name__ == "__main__":
    unittest.main()

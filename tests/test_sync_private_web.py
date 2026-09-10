"""以真正 PowerShell 執行發布分支，隔離 Git、發布器及程序副作用。"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = shutil.which("powershell.exe") if os.name == "nt" else None
COMMIT = "a" * 40


@unittest.skipUnless(PS, "需要 Windows PowerShell 5.1")
class SyncPrivateWebTests(unittest.TestCase):
    def test_unknown_listener_is_rejected_before_any_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "程序驗證.ps1"
            helper = str(ROOT / "scripts/private_web_runtime.ps1").replace("'", "''")
            harness.write_text(". '" + helper + "'\n" + r"""
$ErrorActionPreference = 'Stop'
function Get-CimInstance { @() }
function Get-NetTCPConnection { [pscustomobject]@{LocalPort=18434;OwningProcess=12345} }
function Stop-Process { throw '不應到達停止程序' }
try { Stop-PrivateWebRuntime -Current 'C:\測試\current'; exit 1 }
catch { if ($_.Exception.Message -notmatch '拒絕停止無法確認身分') { throw }; exit 0 }
""", encoding="utf-8-sig")
            result = subprocess.run([PS, "-NoProfile", "-File", str(harness)], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_wrong_live_revision_never_reports_success(self):
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / "版本驗證.ps1"
            helper = str(ROOT / "scripts/private_web_runtime.ps1").replace("'", "''")
            harness.write_text(". '" + helper + "'\n" + """
$ErrorActionPreference = 'Stop'
function Invoke-RestMethod { [pscustomobject]@{ok=$true;releaseCommit=('b' * 40)} }
try { Assert-PrivateWebRevision -Url 'http://localhost/health/live' -Commit ('a' * 40); exit 1 }
catch { if ($_.Exception.Message -notmatch '服務版本驗證失敗') { throw }; exit 0 }
""", encoding="utf-8-sig")
            result = subprocess.run([PS, "-NoProfile", "-File", str(harness)], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def run_sync(self, switches, fail_stage=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "current").mkdir()
            (root / "current/data").mkdir()
            (root / "current/data/private_web_owner.token").write_text("測試用憑證", encoding="utf-8")
            (root / "current/.private_web_release.json").write_text(json.dumps({"commit": COMMIT, "tests": "passed"}), encoding="utf-8")
            (root / "build_v2.py").touch()
            source = (ROOT / "scripts/sync_private_web.ps1").read_text(encoding="utf-8-sig")
            # 只替換外部邊界；參數繫結、版本選取、分支與發布順序均執行原碼。
            begin = source.index("function Invoke-StockPy {")
            end = source.index("\n. (Join-Path", begin)
            stub = """
function Invoke-StockPy {
  param([string[]]$PyArgs)
  Add-Content -Encoding UTF8 -LiteralPath $env:SYNC_TRACE -Value ($PyArgs -join '|')
  $code = 0
  if ($PyArgs[1] -eq 'stage' -and $env:SYNC_FAIL -eq '1') { $code = 1 }
  return [pscustomobject]@{ ExitCode=$code; Text=''; Stdout=(@{installRoot=$Root} | ConvertTo-Json) }
}
"""
            (root / "scripts/sync_private_web.ps1").write_text(source[:begin] + stub + source[end:], encoding="utf-8-sig")
            (root / "scripts/private_web_runtime.ps1").write_text("""
function Assert-PrivateWebRevision { param($Url, $Commit, $Headers, $Attempts); Add-Content -Encoding UTF8 $env:SYNC_TRACE ('驗證|' + $Url + '|' + $Commit) }
function Stop-PrivateWebRuntime { param($Current); Add-Content -Encoding UTF8 $env:SYNC_TRACE '停止' }
function Start-PrivateWebRuntime { param($Current, $Python); Add-Content -Encoding UTF8 $env:SYNC_TRACE '啟動' }
""", encoding="utf-8-sig")
            harness = root / "驗證.ps1"
            harness.write_text("""
$ErrorActionPreference = 'Stop'
function git {
  $global:LASTEXITCODE = 0
  if ($args[0] -eq 'rev-parse') { return ('a' * 40) }
}
& (Join-Path $PSScriptRoot 'scripts/sync_private_web.ps1') """ + switches, encoding="utf-8-sig")
            trace = root / "流程.txt"
            env = dict(os.environ, ST_PYTHON=str(Path(PS)), SYNC_TRACE=str(trace), SYNC_FAIL="1" if fail_stage else "0")
            result = subprocess.run([PS, "-NoProfile", "-File", str(harness)], env=env, capture_output=True, timeout=30)
            events = trace.read_text(encoding="utf-8-sig").splitlines() if trace.exists() else []
            return result, events

    def test_approved_stage_reaches_restart_and_both_live_checks(self):
        result, events = self.run_sync("-Promote -LayoutVerified")
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertIn(f"scripts\\private_web_release.py|stage|--ref|{COMMIT}", events)
        promotion = f"scripts\\private_web_release.py|promote|--release|{COMMIT[:12]}|--approve"
        self.assertLess(events.index("停止"), events.index(promotion))
        self.assertLess(events.index(promotion), events.index("啟動"))
        self.assertEqual(sum("/health/live" in event for event in events), 4)

    def test_stage_only_never_stops_or_promotes(self):
        result, events = self.run_sync("")
        self.assertEqual(result.returncode, 0)
        self.assertFalse(any("promote|" in event or event == "停止" for event in events))

    def test_missing_layout_approval_fails_before_stage(self):
        result, events = self.run_sync("-Promote")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])

    def test_stage_failure_does_not_stop_service_or_promote(self):
        result, events = self.run_sync("-Promote -LayoutVerified", fail_stage=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("停止", events)
        self.assertFalse(any("promote|" in event for event in events))

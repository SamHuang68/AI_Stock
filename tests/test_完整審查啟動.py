"""F24 局部離線驗證；所有程序、健康回應與排程邊界均指向暫存案例。"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "此案例須使用 Windows CMD 與 PowerShell")
class 啟動修正測試(unittest.TestCase):
    def test_檢查入口拒絕舊版與錯誤程序並接受受管服務(self):
        # 沿用既有暫存 PowerShell 執行器，只載入測試模組而不執行其其他案例。
        spec = importlib.util.spec_from_file_location("_本機啟動隔離基礎", ROOT / "tests/test_local_release.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory(prefix="st-check-only-") as temporary:
            root = Path(temporary)
            (root / "current").mkdir()
            (root / "local_install.json").write_text(json.dumps({"python": sys.executable}), encoding="utf-8")
            (root / "local_release.py").write_text(
                "import json,os,sys\nfrom pathlib import Path\n"
                "assert sys.argv[-1]=='status'\n"
                "Path(os.environ['ST_TEST_ROOT'],'版本呼叫.txt').write_text(sys.argv[-1],encoding='utf-8')\n"
                "print(json.dumps({'needsSync':os.environ['ST_TEST_CASE']=='舊版','installedCommit':'a'*40}))\n", encoding="utf-8")
            script = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$root=$env:ST_TEST_ROOT
$python=$env:ST_TEST_PYTHON
$base=Join-Path $root 'current'
$command='"'+$python+'" -B -u "'+(Join-Path $base 'server\server.py')+'"'
$global:StReviewProcess=[pscustomobject]@{ProcessId=123;CreationDate=[datetime]'2026-10-03T01:00:00Z';ExecutablePath=$python;CommandLine=$command}
$receipt=@{pid=123;createdAt=$global:StReviewProcess.CreationDate.ToUniversalTime().ToString('o');commandLine=$command;baseDir=$base}
$receipt|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $root 'local_process.json') -Encoding UTF8
if ($env:ST_TEST_CASE -eq '錯誤程序') {$global:StReviewProcess.CommandLine='其他程序'}
# 受測腳本有自己的 script scope；fixture 跨入口回傳明確的同一程序。
function Get-CimInstance { return $global:StReviewProcess }
function Get-NetTCPConnection { return [pscustomobject]@{LocalAddress='127.0.0.1';LocalPort=18432;OwningProcess=123} }
function Invoke-RestMethod {
  param($Uri,$TimeoutSec)
  if ($Uri -ne 'http://127.0.0.1:18432/health' -or $TimeoutSec -ne 3) {throw '非預期健康查詢'}
  $commit='a'*40
  if ($env:ST_TEST_CASE -eq '健康舊版') {$commit='b'*40}
  return [pscustomobject]@{status='ok';runtimeCommit=$commit;bind='127.0.0.1';port=18432;baseDir=$base;pythonExe=$python}
}
function Start-Process { throw '純檢查不得啟動程序' }
function Stop-Process { throw '純檢查不得終止程序' }
$failure=$null
try { & $env:ST_TEST_LAUNCHER -InstallRoot $root -CheckOnly } catch {$failure=$_.Exception.Message}
switch ($env:ST_TEST_CASE) {
  '正常' {if ($failure) {throw $failure}}
  '舊版' {if ($failure -notlike '*尚未同步正式版本*') {throw ('未拒絕舊版：'+$failure)}}
  '錯誤程序' {if ($failure -notlike '*不是已登記*') {throw ('未拒絕錯誤程序：'+$failure)}}
  '健康舊版' {if ($failure -notlike '*身分不符*') {throw ('未拒絕健康舊版：'+$failure)}}
}
if (Test-Path -LiteralPath (Join-Path $root '.launcher.lock')) {throw '純檢查不應建立啟動鎖'}
'''
            for case in ("正常", "舊版", "錯誤程序", "健康舊版"):
                with self.subTest(情境=case):
                    fixture.LocalPowerShellTests.run_ps(self, script, env=dict(os.environ,
                        ST_TEST_ROOT=str(root), ST_TEST_PYTHON=sys.executable,
                        ST_TEST_LAUNCHER=str(ROOT / "scripts/start_local.ps1"), ST_TEST_CASE=case))
                    self.assertEqual((root / "版本呼叫.txt").read_text(encoding="utf-8"), "status")

    def test_冷暖啟動都經受管入口且各頁只開一次(self):
        # 與既有 CMD fixture 相同，只替換外部動作；保留原有分支及退出碼。
        source = (ROOT / "START_LOCAL_AND_WEB.cmd").read_text(encoding="ascii")
        powershell = r'(?im)^([ \t]*)(?:powershell\.exe|"%SystemRoot%\\System32\\WindowsPowerShell\\v1\.0\\powershell\.exe")(?=\s)'
        source, count = re.subn(powershell, r'\1call "%ST_TEST_ROOT%\\外部命令.cmd"', source)
        self.assertEqual(count, 5, "外部 PowerShell 清單變動，須重新核對隔離")
        source, count = re.subn(r'(?im)^start "" "http://127\.0\.0\.1:18432/#pulse"$', lambda _: 'call "%ST_TEST_ROOT%\\本機開頁.cmd"', source)
        self.assertEqual(count, 1)
        source, count = re.subn(r'(?im)^schtasks /run /tn "StockTerminal_PrivateWeb_Host"$', lambda _: 'call "%ST_TEST_ROOT%\\排程.cmd"', source)
        self.assertEqual(count, 1)
        # CMD 原始檔為 ASCII；fixture 亦使用 ASCII 檔名，避免主控台碼頁影響測試。
        source = source.replace("外部命令.cmd", "external.cmd").replace("本機開頁.cmd", "open.cmd").replace("排程.cmd", "task.cmd")
        stub = r'''@echo off
if /i "%~8"=="-CheckOnly" (
  >>"%ST_TEST_ROOT%\calls.txt" echo check
  if exist "%ST_TEST_ROOT%\ready.flag" exit /b 0
  exit /b 1
)
if /i "%~8"=="-OpenBrowser" (
  >>"%ST_TEST_ROOT%\calls.txt" echo web-page
  exit /b 0
)
if /i "%~4"=="-Command" exit /b 0
exit /b 99
'''
        managed = r'''@echo off
>>"%ST_TEST_ROOT%\calls.txt" echo managed %*
if "%ST_TEST_CASE%"=="failed" exit /b 1
>"%ST_TEST_ROOT%\ready.flag" echo 1
exit /b 0
'''
        cmd = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
        for case, no_browser in (("warm", False), ("cold", False), ("cold", True), ("failed", False)):
            with self.subTest(情境=case, 不開頁=no_browser), tempfile.TemporaryDirectory(prefix="st-combined-") as temporary:
                root = Path(temporary)
                files = {"launcher.cmd": source, "START_TIP.cmd": managed, "external.cmd": stub,
                         "open.cmd": '@echo off\n>>"%ST_TEST_ROOT%\\calls.txt" echo local-page\nexit /b 0\n',
                         "task.cmd": '@echo off\n>>"%ST_TEST_ROOT%\\calls.txt" echo unexpected-task\nexit /b 99\n'}
                for name, body in files.items():
                    (root / name).write_bytes(body.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))
                if case == "warm":
                    (root / "ready.flag").write_bytes(b"1")
                argument = " --no-browser" if no_browser else ""
                result = subprocess.run(f'"{cmd}" /d /s /c ""{root / "launcher.cmd"}"{argument}"',
                    env=dict(os.environ, ST_TEST_ROOT=str(root), ST_TEST_CASE=case), cwd=root,
                    capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 1 if case == "failed" else 0, result.stdout + result.stderr)
                calls = (root / "calls.txt").read_text(encoding="ascii").splitlines()
                self.assertEqual(calls[0], "managed -NoBrowser")
                self.assertEqual(calls.count("managed -NoBrowser"), 1)
                self.assertEqual(calls.count("check"), 1)
                self.assertEqual(calls.count("local-page"), int(not no_browser and case != "failed"))
                self.assertEqual(calls.count("web-page"), int(not no_browser))
                self.assertNotIn("unexpected-task", calls)


if __name__ == "__main__":
    unittest.main()

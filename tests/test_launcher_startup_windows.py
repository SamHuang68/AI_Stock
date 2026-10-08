"""Windows 啟動流程驗收；明確設定 ST_LAUNCHER_E2E=1 才執行真實伺服器。

使用獨立程式複本、空白 data、隔離 AppData 與動態埠。只攔截視窗呈現及
瀏覽器開啟：仍呼叫原生 Start-Process，實際建置、伺服器、HTTP 與收據均不替換。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

from tests.test_launcher_safety import ROOT, _powershell_engines, _go_ps1_process_helpers


_LAUNCH_DRIVER = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
function Start-Process {
  param([string]$FilePath, [string]$WorkingDirectory, [string]$WindowStyle, [switch]$PassThru)
  if ($FilePath -match '^http://') {
    Write-Host "BROWSER-REQUEST=$FilePath"
    return
  }
  $p = Microsoft.PowerShell.Management\Start-Process -FilePath $FilePath -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput $env:ST_TEST_STDOUT -RedirectStandardError $env:ST_TEST_STDERR
  @{pid=$p.Id; ticks=$p.StartTime.ToUniversalTime().Ticks} | ConvertTo-Json | Set-Content -LiteralPath $env:ST_TEST_LAUNCH_RECEIPT -Encoding UTF8
  return $p
}
& $env:ST_TEST_GO -Worktree
"""

_CLEANUP_DRIVER = r"""
$ErrorActionPreference = 'Stop'
. $env:ST_TEST_FUNCS
if (Test-Path -LiteralPath $env:ST_TEST_SERVER_RECEIPT) {
  Stop-OwnedPortListeners -PortNum ([int]$env:ST_PORT) -ReceiptPath $env:ST_TEST_SERVER_RECEIPT -OwnerRoot $env:ST_TEST_ROOT
}
# 失敗情境只清理由本測試的 CMD 直接啟動、命令列指向隔離複本的 Python。
function Stop-TestOwnedChild($Record, [int]$ExpectedParent) {
  $childProcess = Get-Process -Id $Record.ProcessId -ErrorAction SilentlyContinue
  if (-not $childProcess) { return }
  if ($childProcess.HasExited) { return }
  try {
    $null = $childProcess.Handle
    $processTicks = $childProcess.StartTime.ToUniversalTime().Ticks
  } catch {
    if ($childProcess.HasExited) { return }
    throw
  }
  if ([Math]::Abs($processTicks - $Record.CreationDate.ToUniversalTime().Ticks) -gt 9) {
    throw 'TEST-CLEANUP: 子程序建立時間不符，拒絕停止。'
  }
  $identity = Get-CimInstance Win32_Process -Filter "ProcessId=$($childProcess.Id)" -ErrorAction Stop
  if ($identity.ParentProcessId -ne $ExpectedParent -or
      $identity.CommandLine -notmatch [regex]::Escape((Join-Path $env:ST_TEST_ROOT 'server\server.py'))) {
    throw 'TEST-CLEANUP: 子程序父鏈或命令不符，拒絕停止。'
  }
  if (-not $childProcess.HasExited) { Stop-Process -InputObject $childProcess -Force -ErrorAction Stop }
}
$launches = @(Get-ChildItem -LiteralPath $env:ST_TEST_ROOT -Filter 'launch-*.json')
foreach ($file in $launches) {
  $r = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
  $p = Get-Process -Id $r.pid -ErrorAction SilentlyContinue
  if ($p -and $p.StartTime.ToUniversalTime().Ticks -eq [int64]$r.ticks) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)")
    foreach ($child in $children) {
      if ($child.CommandLine -match [regex]::Escape((Join-Path $env:ST_TEST_ROOT 'server\server.py'))) {
        # Windows venv 的 python.exe 是轉接器，真正 Python 可能再下一層。
        foreach ($grandchild in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($child.ProcessId)")) {
          if ($grandchild.CommandLine -match [regex]::Escape((Join-Path $env:ST_TEST_ROOT 'server\server.py'))) {
            Stop-TestOwnedChild $grandchild ([int]$child.ProcessId)
          }
        }
        Stop-TestOwnedChild $child ([int]$p.Id)
      }
    }
    Stop-Process -InputObject $p -Force -ErrorAction Stop
  }
}
"""


@unittest.skipUnless(os.name == 'nt' and os.environ.get('ST_LAUNCHER_E2E') == '1',
                     '僅在 Windows 且明確啟用隔離啟動驗收時執行')
class IsolatedLauncherStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='st-launcher-', dir=os.environ.get('ST_LAUNCHER_TEMP_ROOT'))
        self.addCleanup(self.temp.cleanup)
        # 同時覆蓋 Unicode 與空白；這是可清除的測試輸入，非正式專案目錄。
        self.repo = Path(self.temp.name) / 'repo space 驗收'
        self.repo.mkdir()
        paths = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.py', '*.html',
                                         'server', 'src', 'assets', 'scripts', 'VERSION', 'TIP_BRANCH'],
                                        cwd=ROOT).decode('utf-8').split('\0')
        for rel in filter(None, paths):
            if rel.startswith(('data/', 'wavedeck/data/')):
                continue
            source = ROOT / rel
            if source.is_file():
                dest = self.repo / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
        subprocess.run(['git', 'init', '-q', '--initial-branch=main'], cwd=self.repo, check=True)
        subprocess.run(['git', 'add', '--', 'VERSION', 'TIP_BRANCH'], cwd=self.repo, check=True)
        subprocess.run(['git', '-c', 'user.name=Launcher acceptance', '-c',
                        'user.email=acceptance@localhost', 'commit', '-q', '-m', '隔離啟動驗收基線'],
                       cwd=self.repo, check=True)
        self.funcs = self.repo / 'process_helpers.ps1'
        self.funcs.write_text(_go_ps1_process_helpers(), encoding='utf-8-sig')
        self.receipt = self.repo / 'logs' / 'dev_server.receipt.json'
        self.python = os.environ.get('ST_LAUNCHER_PYTHON', sys.executable)
        self.env = dict(os.environ, ST_PYTHON=self.python, PYTHONUTF8='1',
                        PYTHONPATH=str(ROOT / 'tests/fixtures/launcher_loopback_only'),
                        LOCALAPPDATA=str(self.repo / 'LocalAppData'), APPDATA=str(self.repo / 'AppData'),
                        ST_ETF_HISTORY_DIR=str(self.repo / 'etf_history'),
                        ST_AI_TRACE_PATH=str(self.repo / 'logs' / 'ai_trace.jsonl'),
                        ST_REPORTS_DIR=str(self.repo / 'data' / 'reports'),
                        LLM_GATE_PATH=str(self.repo / 'data' / 'llm_gate.json'),
                        ST_TEST_ROOT=str(self.repo), ST_TEST_FUNCS=str(self.funcs),
                        ST_TEST_SERVER_RECEIPT=str(self.receipt),
                        ST_TEST_GO=str(self.repo / 'scripts' / 'go.ps1'))
        self.runs = 0
        self.active_port = None
        self.addCleanup(self.cleanup_processes)
        self.evidence = Path(os.environ.get('ST_LAUNCHER_EVIDENCE', str(self.repo / 'evidence'))) / self._testMethodName
        self.evidence.mkdir(parents=True, exist_ok=True)

    def run_ps(self, engine, text, label):
        driver = self.repo / (label + '.ps1')
        driver.write_text(text, encoding='utf-8-sig')
        log = self.evidence / (label + '.log')
        # Windows 的 CMD 子程序可能繼承主控台 handle；用檔案收集，避免
        # PowerShell 已結束但 communicate() 仍等子程序關閉匿名 pipe。
        with log.open('wb') as stream:
            done = subprocess.run([engine, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(driver)],
                                  cwd=self.repo, env=self.env, stdout=stream, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, timeout=180)
        output = log.read_text(encoding='utf-8', errors='replace')
        return done.returncode, output

    def run_go(self, engine, port):
        self.runs += 1
        label = 'startup-%d' % self.runs
        self.env.update(ST_PORT=str(port), ST_TEST_STDOUT=str(self.evidence / (label + '-server.out.log')),
                        ST_TEST_STDERR=str(self.evidence / (label + '-server.err.log')),
                        ST_TEST_LAUNCH_RECEIPT=str(self.repo / ('launch-%d.json' % self.runs)))
        self.active_port = port
        return self.run_ps(engine, _LAUNCH_DRIVER, label)

    def cleanup_processes(self):
        if self.active_port is not None:
            engine = _powershell_engines()['powershell']
            code, out = self.run_ps(engine, _CLEANUP_DRIVER, 'cleanup-%d' % self.runs)
            self.assertEqual(code, 0, out)
            self.active_port = None

    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    @staticmethod
    def health(port):
        with urllib.request.urlopen('http://127.0.0.1:%d/health' % port, timeout=15) as response:
            return json.load(response)

    def test_build_start_health_receipt_and_restart_on_isolated_port(self):
        summary = []
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                port = self.free_port()
                for turn in range(2):
                    previous = json.loads(self.receipt.read_text(encoding='utf-8-sig')) if turn else None
                    code, out = self.run_go(engine, port)
                    self.assertEqual(code, 0, out)
                    self.assertIn('DONE.', out)
                    self.assertIn('[receipt]', out)
                    self.assertIn('BROWSER-REQUEST=http://localhost:%d/#pulse' % port, out)
                    receipt = json.loads(self.receipt.read_text(encoding='utf-8-sig'))
                    health = self.health(port)
                    self.assertEqual(receipt['port'], port)
                    self.assertEqual(Path(receipt['root']).resolve(), self.repo.resolve())
                    self.assertEqual(Path(health['baseDir']).resolve(), self.repo.resolve())
                    self.assertEqual(Path(health['pythonExe']).resolve(), Path(self.python).resolve())
                    self.assertEqual(health['port'], port)
                    if previous:
                        self.assertIn('[stop]', out)
                        self.assertNotEqual((receipt['pid'], receipt['startTicksUtc']),
                                            (previous['pid'], previous['startTicksUtc']))
                    summary.append(dict(engine=name, turn=turn, receipt=receipt, health=health))
                self.cleanup_processes()
                with socket.socket() as sock:
                    self.assertNotEqual(sock.connect_ex(('127.0.0.1', port)), 0,
                                        '驗收清理後隔離埠仍在監聽')
        source = ROOT / 'scripts' / 'go.ps1'
        (self.evidence / 'startup-summary.json').write_text(json.dumps({
            'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
            'launcherSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'realBuild': True, 'realServer': True, 'browserOpened': False, 'windowHidden': True,
            'runs': summary}, ensure_ascii=False, indent=2), encoding='utf-8')

    def test_full_launcher_refuses_a_real_unknown_listener(self):
        code_src = ("import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(5); "
                    "print(s.getsockname()[1], flush=True); time.sleep(600)")
        with subprocess.Popen([sys.executable, '-c', code_src], stdout=subprocess.PIPE, text=True) as foreign:
            try:
                port = int(foreign.stdout.readline())
                for name, engine in _powershell_engines().items():
                    with self.subTest(engine=name):
                        code, out = self.run_go(engine, port)
                        self.assertNotEqual(code, 0, out)
                        self.assertIn('ST-PORT-GUARD', out)
                        self.assertIn('PID %d' % foreign.pid, out)
                        self.assertIsNone(foreign.poll(), '未知監聽程序被終止')
                        self.assertFalse(self.receipt.exists())
                        self.assertFalse(list(self.repo.glob('launch-*.json')))
            finally:
                foreign.kill()
                foreign.wait(timeout=10)

    def test_unicode_python_venv_can_start_and_reuse_its_pin(self):
        venv = self.repo / 'Python space 驗收'
        subprocess.run([self.python, '-m', 'venv', '--without-pip', str(venv)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        self.python = str(venv / 'Scripts' / 'python.exe')
        self.env['ST_PYTHON'] = self.python
        engine = _powershell_engines()['powershell']
        port = self.free_port()
        for turn in range(2):
            if turn:
                del self.env['ST_PYTHON']
            code, out = self.run_go(engine, port)
            self.assertEqual(code, 0, out)
            self.assertIn('DONE.', out)
            pin = self.repo / 'data' / 'stock_python.path'
            self.assertEqual(pin.read_text(encoding='utf-8-sig').strip(), self.python)
            self.assertEqual(Path(self.health(port)['pythonExe']).resolve(), Path(self.python).resolve())
            if turn:
                self.assertIn('OK pin -> ' + self.python, out)

    def test_bind_race_does_not_register_the_foreign_server(self):
        race = r"""
  # 模擬 guard 後、自己的 CMD 啟動前，另一個服務搶先占埠。
  # 它提供相同 root／Python／HTML，故 /health 不能取代程序來源驗證。
  $foreign = Microsoft.PowerShell.Management\Start-Process -FilePath $env:ST_PYTHON -ArgumentList @('-u', ('"' + (Join-Path $env:ST_TEST_ROOT 'server\server.py') + '"')) -WorkingDirectory $env:ST_TEST_ROOT -WindowStyle Hidden -PassThru -RedirectStandardOutput ($env:ST_TEST_STDOUT + '.race') -RedirectStandardError ($env:ST_TEST_STDERR + '.race')
  @{pid=$foreign.Id; ticks=$foreign.StartTime.ToUniversalTime().Ticks} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $env:ST_TEST_ROOT 'race.json') -Encoding UTF8
  $ready = $false
  for ($i=0; $i -lt 50; $i++) {
    try { $null = Invoke-WebRequest -Uri ("http://127.0.0.1:" + $env:ST_PORT + '/health') -UseBasicParsing -TimeoutSec 2; $ready=$true; break }
    catch { Start-Sleep -Milliseconds 200 }
  }
  if (-not $ready) { throw 'RACE-SETUP: 隔離搶占服務未就緒' }
"""
        # 放在真正的 Start-Process 呼叫之前；程式建置、guard 與後續流程不改寫。
        driver = _LAUNCH_DRIVER.replace('  $p = Microsoft.PowerShell.Management\\Start-Process',
                                        race + '\n  $p = Microsoft.PowerShell.Management\\Start-Process')
        engine = _powershell_engines()['powershell']
        port = self.free_port()
        self.runs += 1
        self.active_port = port
        self.env.update(ST_PORT=str(port), ST_TEST_STDOUT=str(self.evidence / 'race-server.out.log'),
                        ST_TEST_STDERR=str(self.evidence / 'race-server.err.log'),
                        ST_TEST_LAUNCH_RECEIPT=str(self.repo / 'launch-1.json'))
        try:
            code, out = self.run_ps(engine, driver, 'bind-race')
            self.assertNotEqual(code, 0, out)
            self.assertIn('ST-RECEIPT-GUARD', out)
            self.assertFalse(self.receipt.exists(), '搶占者不得被登記為自有程序')
            self.assertEqual(Path(self.health(port)['baseDir']).resolve(), self.repo.resolve())
            # 再次啟動須仍拒絕未知占用者，不能把前一輪誤認的收據拿來終止它。
            code, out = self.run_go(engine, port)
            self.assertNotEqual(code, 0, out)
            self.assertIn('ST-PORT-GUARD', out)
            self.assertEqual(self.health(port)['port'], port)
        finally:
            # race.json 是本測試親自啟動的程序證據；核對時間與路徑後才清理。
            cleanup_code, cleanup_out = self.run_ps(engine, r"""
$r = Get-Content -LiteralPath (Join-Path $env:ST_TEST_ROOT 'race.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$p = Get-Process -Id $r.pid -ErrorAction Stop
$c = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)"
if ($p.StartTime.ToUniversalTime().Ticks -ne [int64]$r.ticks -or $c.CommandLine -notmatch [regex]::Escape((Join-Path $env:ST_TEST_ROOT 'server\server.py'))) { throw 'RACE-CLEANUP: 程序身分不符' }
Stop-Process -InputObject $p -Force -ErrorAction Stop
""", 'race-cleanup')
            self.assertEqual(cleanup_code, 0, cleanup_out)


if __name__ == '__main__':
    unittest.main()

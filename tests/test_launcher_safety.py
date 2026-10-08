#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherSafetyTests(unittest.TestCase):
    def test_windows_unicode_entrypoints_preserve_crlf_bytes(self):
        attrs = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        for name in ('STOP_PRIVATE_WEB.cmd', 'START_LOCAL_AND_WEB.cmd', 'wavedeck/START_WAVEDECK.cmd'):
            with self.subTest(name=name):
                raw = (ROOT / name).read_bytes()
                self.assertIn(b'\r\n', raw)
                self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
                self.assertIn(name + ' -text', attrs)

    def test_canonical_windows_launcher_never_discards_work(self):
        script = (ROOT / 'scripts' / 'go.ps1').read_text(encoding='utf-8')
        lowered = script.lower()
        for destructive in ('reset --hard', 'checkout -f', 'git stash', 'clean -fd'):
            self.assertNotIn(destructive, lowered)
        self.assertRegex(script, r'git(?: -c core\.quotepath=false)? status --porcelain')
        self.assertIn('git merge --ff-only', script)
        self.assertIn('Resolve-StockPython', script)

    def test_batch_files_are_ascii_shims_and_delegate_before_process_actions(self):
        go = (ROOT / 'scripts' / 'go.bat').read_bytes()
        start = (ROOT / 'START_TIP.cmd').read_bytes()
        go.decode('ascii')
        start.decode('ascii')
        go_text = go.decode('ascii').lower()
        start_text = start.decode('ascii').lower()
        self.assertIn('go.ps1', go_text)
        self.assertNotRegex(go_text, r'(?m)^\s*git\s+')
        self.assertIn('go.ps1', start_text)
        self.assertNotIn('taskkill', start_text)

    def test_launcher_refuses_to_kill_the_managed_local_listener_from_an_unregistered_checkout(self):
        raw = (ROOT / 'scripts' / 'go.ps1').read_bytes()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'), 'go.ps1 含中文訊息，必須保留 UTF-8 BOM（Windows PowerShell 5.1 才不會亂碼）')
        script = raw.decode('utf-8-sig')
        guard = script.index('ST-LAUNCHER-GUARD')
        # 防呆必須在任何會關閉 18432 埠的動作之前，且只在「一般啟動」（沒有明確開發參數）時生效。
        self.assertLess(guard, script.index('Stop-OwnedPortListeners -PortNum $Port'))
        gate = script.index('-not ($Worktree -or $Pull -or $UpdateOnly -or $RebuildOnly)')
        self.assertLess(gate, guard)
        self.assertLess(guard, script.index('$TipBranch ='))

    def test_launcher_never_kills_by_port(self):
        # 規則 0015 §4：腳本不得依埠任意終止程序。開發流程只能結束「收據登記的自己的程序」，
        # 其他占用者一律拒絕。Stop-Process 只能出現在 Stop-OwnedPortListeners 內，且在 ST-PORT-GUARD 之後。
        # Windows 的 CI 會把檔案檢出成 CRLF；以下用 \n 比對位置，所以先統一換行。
        script = (ROOT / 'scripts' / 'go.ps1').read_bytes().decode('utf-8-sig').replace('\r\n', '\n')
        # 行為驗收器會以字串識別並拒絕舊命令；不可把拒絕清單誤當成實際執行。
        # 真 PowerShell AST 的函式內／外停止與 taskkill 拒絕另由 test_launcher_pull 覆蓋。
        self.assertNotRegex(script, r'(?im)^\s*(?:function\s+)?Stop-PortListeners(?=[\s(])')
        self.assertNotRegex(script, r'(?im)^\s*(?:&\s*)?taskkill(?:\.exe)?(?=\s|$)')
        start = script.index('function Stop-OwnedPortListeners')
        end = script.index('\nfunction ', start + 10)
        body = script[start:end]
        stop_command = r'(?m)^\s*Stop-Process(?=\s|$)'
        self.assertEqual(len(re.findall(stop_command, script)), len(re.findall(stop_command, body)))
        self.assertEqual(len(re.findall(stop_command, body)), 1)
        self.assertLess(body.index('ST-PORT-GUARD'), body.index('Stop-Process'))
        # 啟動後要登記收據，下次才認得出自己的程序。
        self.assertLess(script.index('\nWait-TipServer\n'), script.index('\nWrite-DevServerReceipt -PortNum'))

    def test_retired_apply_bat_has_no_destructive_actions(self):
        raw = (ROOT / 'scripts' / 'apply.bat').read_bytes()
        lines = raw.decode('ascii').lower().splitlines()        # .bat 訊息一律 ASCII（.cursorrules）
        # 註解（REM）可以說明舊腳本做過什麼；只檢查會執行或印出的行。
        text = '\n'.join(line for line in lines if not line.lstrip().startswith('rem '))
        for forbidden in ('taskkill', 'stop-process', 'git checkout', 'git stash', 'git reset', 'git clean',
                          'netstat', 'server.py', 'build_v2'):
            self.assertNotIn(forbidden, text)
        self.assertIn('exit /b 2', text)
        self.assertIn('[retired]', text)

    def test_etf_scheduler_uses_pinned_python_shared_history_and_health_gate(self):
        wrapper = (ROOT / 'scripts' / 'daily_etf.bat').read_bytes()
        wrapper_text = wrapper.decode('ascii').lower()
        script = (ROOT / 'scripts' / 'daily_etf.ps1').read_text(encoding='utf-8')
        installer = (ROOT / 'scripts' / 'install_scheduler.bat').read_text(encoding='ascii')
        self.assertNotIn(b'\x00', wrapper)
        self.assertIn('%~dp0daily_etf.ps1', wrapper_text)
        self.assertIn('%*', wrapper_text)
        self.assertIn('Resolve-StockPython', script)
        self.assertIn('stock_python.path', script)
        self.assertIn('ST_ETF_HISTORY_DIR', script)
        self.assertIn(r'shared-data\etf_history', script)
        self.assertIn('etf_snapshot_health.py', script)
        self.assertIn('exit $TrackerRc', script)
        self.assertIn('exit $HealthRc', script)
        self.assertIn('-WorkingDirectory', installer)
        self.assertIn('-RequireApi', installer)
        self.assertIn('http://127.0.0.1:18435/etf-delta', installer)
        self.assertIn('New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 7pm', installer)


def _powershell_engines():
    """所有找得到的 PowerShell。START_TIP.cmd 實際呼叫的是 Windows PowerShell 5.1（powershell.exe），
    所以 Windows 上兩種都要跑；只挑 pwsh 會讓 5.1 的行為沒被驗證。"""
    found = {}
    for name in ('powershell', 'pwsh'):
        path = shutil.which(name)
        if path:
            found[name] = path
    return found


@unittest.skipIf(not _powershell_engines(), '找不到 PowerShell（CI 的 Windows／Ubuntu 都有）')
class ManagedInstallGuardBehaviorTests(unittest.TestCase):
    """真的執行 go.ps1：防呆在任何會關閉程序的動作之前就結束，所以在暫存目錄裡跑是安全的。"""

    def run_go(self, engine, original_checkout):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            (repo / 'scripts').mkdir(parents=True)
            shutil.copy(ROOT / 'scripts' / 'go.ps1', repo / 'scripts' / 'go.ps1')
            (repo / 'build_v2.py').write_text('', encoding='utf-8')
            local = Path(tmp) / 'LocalAppData'
            (local / 'StockTerminalLocal').mkdir(parents=True)
            checkout = str(repo) if original_checkout == 'self' else original_checkout
            (local / 'StockTerminalLocal' / 'local_install.json').write_text(
                json.dumps({'originalCheckout': checkout}), encoding='utf-8')
            env = dict(os.environ, LOCALAPPDATA=str(local))
            args = [engine, '-NoProfile']
            if os.name == 'nt':
                args += ['-ExecutionPolicy', 'Bypass']
            args += ['-File', str(repo / 'scripts' / 'go.ps1')]
            done = subprocess.run(args, cwd=tmp, env=env, capture_output=True, timeout=120)
            return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')

    def test_windows_runs_cover_windows_powershell_5_1(self):
        # START_TIP.cmd 實際呼叫 Windows PowerShell 5.1（powershell.exe）。Windows 上若找不到它，
        # 行為測試就只剩 pwsh，5.1 的行為等於沒被驗證（曾因此寫出不準確的涵蓋聲明）。
        if os.name != 'nt':
            self.skipTest('只在 Windows 檢查 Windows PowerShell 5.1 是否被涵蓋')
        engines = _powershell_engines()
        self.assertIn('powershell', engines, '找不到 powershell.exe：5.1 沒有被行為測試涵蓋')
        print('guard behaviour tests engines:', sorted(engines))

    def test_unregistered_checkout_is_refused_before_anything_is_stopped(self):
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, output = self.run_go(engine, str(Path(tempfile.gettempdir()) / 'some-other-checkout'))
                self.assertNotEqual(code, 0)
                self.assertIn('ST-LAUNCHER-GUARD', output)
                self.assertNotIn('[stop]', output)

    def test_registered_checkout_is_not_intercepted_by_the_guard(self):
        # 已登記的資料夾要走原本的轉接流程（這裡沒有 start_local.ps1，所以以既有錯誤結束），不能被防呆擋下。
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, output = self.run_go(engine, 'self')
                self.assertNotEqual(code, 0)
                self.assertNotIn('ST-LAUNCHER-GUARD', output)
                self.assertNotIn('[stop]', output)


_TEST_LEGACY_RECEIPT_SEED = """\
# 只供 Stop-Owned 行為測試，明示建立舊收據；不冒充正式強 writer。
function Seed-TestOwnedLegacyReceipt([int]$PortNum, [int[]]$ListenerPids, [string]$ReceiptPath, [string]$OwnerRoot) {
  if ($ListenerPids.Count -ne 1) { throw '測試收據只接受一個 listener。' }
  $childId = $ListenerPids[0]
  $child = Get-CimInstance Win32_Process -Filter "ProcessId=$childId" -ErrorAction Stop
  $parentId = [int]$env:ST_TEST_PARENT_ID
  $childTicks = Get-ProcessStartTicks $childId
  $parentTicks = Get-ProcessStartTicks $parentId
  if (-not $child -or $child.Name -notin @('python.exe','pythonw.exe') -or
      [int]$child.ParentProcessId -ne $parentId -or $null -eq $childTicks -or
      $null -eq $parentTicks -or $childTicks -lt $parentTicks -or -not $child.CommandLine) {
    throw '測試 child 的父程序、CIM、啟動時間或命令列不符；不建立收據。'
  }
  $receipt = [ordered]@{pid=$childId;startTicksUtc=[int64]$childTicks;root=$OwnerRoot;port=$PortNum;commandLine=[string]$child.CommandLine}
  $receipt | ConvertTo-Json | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
}
"""


_RECEIPT_DRIVER = _TEST_LEGACY_RECEIPT_SEED + """\
$ErrorActionPreference = 'Stop'
. $env:ST_TEST_FUNCS
function Get-PortListenerPids([int]$PortNum) { return @($script:ListenerPids) }
function ConvertTo-PidList([string]$text) { return @($text -split ',' | Where-Object { $_ } | ForEach-Object { [int]$_ }) }
$script:ListenerPids = ConvertTo-PidList $env:ST_TEST_WRITE_PIDS
if ($env:ST_TEST_WRITE_ROOT) {
  Seed-TestOwnedLegacyReceipt -PortNum 18432 -ListenerPids $script:ListenerPids -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_WRITE_ROOT
}
$script:ListenerPids = ConvertTo-PidList $env:ST_TEST_STOP_PIDS
Stop-OwnedPortListeners -PortNum 18432 -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_STOP_ROOT
Write-Host 'STOP-RETURNED'
"""

_REAL_PORT_DRIVER = _TEST_LEGACY_RECEIPT_SEED + """\
$ErrorActionPreference = 'Stop'
. $env:ST_TEST_FUNCS
$port = [int]$env:ST_TEST_PORT
Write-Host ('FOUND=' + ((Get-PortListenerPids $port) -join ','))
try {
  Stop-OwnedPortListeners -PortNum $port -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_ROOT
  Write-Host 'NOT-REFUSED'
} catch {
  if ($_.Exception.Message -notmatch '^ST-PORT-GUARD:') { throw }
  Write-Host 'REFUSED:ST-PORT-GUARD'
}
Seed-TestOwnedLegacyReceipt -PortNum $port -ListenerPids @(Get-PortListenerPids $port) -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_ROOT
Stop-OwnedPortListeners -PortNum $port -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_ROOT
Write-Host 'STOPPED'
"""


def _go_ps1_process_helpers():
    """go.ps1 內「找出埠上的程序、登記收據、只結束自己的程序」那一整段函式（原樣取出，不改寫）。"""
    script = (ROOT / 'scripts' / 'go.ps1').read_bytes().decode('utf-8-sig')
    return script[script.index('function Get-PortListenerPids'):script.index('function Assert-TipHtml')]


@unittest.skipIf(os.name != 'nt' or not _powershell_engines(), '收據身分核對依賴 Windows CIM；其他平台保留 AST 與防呆測試')
class DevServerReceiptBehaviorTests(unittest.TestCase):
    """真的在 PowerShell 裡執行 go.ps1 的程序處置函式。埠上的程序用真的睡眠程序代表；
    「哪些 PID 在聽」用替身回報（跨平台），Windows 上另有真實埠的測試。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.funcs = self.dir / 'process_helpers.ps1'
        self.funcs.write_bytes(b'\xef\xbb\xbf' + _go_ps1_process_helpers().encode('utf-8'))
        self.receipt = self.dir / 'dev_server.receipt.json'
        self.root = str(self.dir / 'checkout-a')
        self.procs = []
        self.addCleanup(self._kill_all)

    def _kill_all(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
            if proc.stdout:
                proc.stdout.close()

    def sleeper(self):
        # 此組案例驗證直接父程序；venv 轉接另由完整程序鏈案例驗證。
        proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable),
                                 '-c', 'import time; time.sleep(600)'])
        self.procs.append(proc)
        return proc

    def run_ps(self, engine, driver, **env):
        script = self.dir / 'driver.ps1'
        script.write_bytes(b'\xef\xbb\xbf' + driver.encode('utf-8'))
        full_env = dict(os.environ, ST_TEST_PARENT_ID=str(os.getpid()), ST_TEST_FUNCS=str(self.funcs), ST_TEST_RECEIPT=str(self.receipt),
                        ST_TEST_WRITE_PIDS='', ST_TEST_WRITE_ROOT='', ST_TEST_STOP_PIDS='',
                        ST_TEST_STOP_ROOT=self.root)
        full_env.update({k: str(v) for k, v in env.items()})
        args = [engine, '-NoProfile']
        if os.name == 'nt':
            args += ['-ExecutionPolicy', 'Bypass']
        args += ['-File', str(script)]
        done = subprocess.run(args, cwd=self.tmp.name, env=full_env, capture_output=True, timeout=120)
        return done.returncode, (done.stdout + done.stderr).decode('utf-8', 'replace')

    def assertAlive(self, *procs):
        for proc in procs:
            self.assertIsNone(proc.poll(), '不該被終止的程序被終止了')

    def test_identity_lookup_failure_does_not_abort_or_write_receipt(self):
        mine = self.sleeper()
        driver = r""". $env:ST_TEST_FUNCS
function Get-PortListenerPids([int]$PortNum) { return @([int]$env:ST_TEST_WRITE_PIDS) }
function Get-CimInstance { Write-Host 'CIM-FIXTURE-CALLED'; throw '合成身分讀取失敗' }
Write-DevServerReceipt -PortNum 18432 -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_ROOT -ExpectedParent ([int]$env:ST_TEST_PARENT_ID) -ExpectedPython 'C:\fixture\python.exe' -ExpectedBasePython 'C:\fixture\base-python.exe' -ExpectedLauncher 'C:\fixture\run_server_tip.cmd'
Write-Host 'RECEIPT-RETURNED'
"""
        for name, engine in _powershell_engines().items():
            code, output = self.run_ps(engine, driver, ST_TEST_WRITE_PIDS=mine.pid, ST_TEST_ROOT=self.root)
            self.assertEqual(code, 0, output)
            self.assertIn('RECEIPT-RETURNED', output)
            self.assertIn('CIM-FIXTURE-CALLED', output)
            self.assertFalse(self.receipt.exists())
            self.assertAlive(mine)

    def test_python_proxy_requires_pin_root_and_captured_launcher_identity(self):
        driver = r""". $env:ST_TEST_FUNCS
$owner = $env:ST_TEST_ROOT
$pin = Join-Path $owner 'venv\Scripts\python.exe'
$base = Join-Path $owner 'base\python.exe'
$launcher = Join-Path $owner 'logs\run_server_tip.cmd'
$command = '"' + $pin + '" -u "' + (Join-Path $owner 'server\server.py') + '"'
$script:Processes = @{
  50 = [pscustomobject]@{ ProcessId=50; Name='cmd.exe'; ParentProcessId=40; CommandLine=('cmd.exe /c "' + $launcher + '"') }
  60 = [pscustomobject]@{ ProcessId=60; Name='python.exe'; ParentProcessId=50; ExecutablePath=$pin; CommandLine=$command }
  70 = [pscustomobject]@{ ProcessId=70; Name='python.exe'; ParentProcessId=60; ExecutablePath=$base; CommandLine=$command }
}
$script:Ticks = @{ 50=[int64]100; 60=[int64]200; 70=[int64]300 }
switch ($env:ST_TEST_CASE) {
  'direct' { $script:Processes[70].ParentProcessId=50; $script:Processes[70].ExecutablePath=$pin }
  'parent-reused' { $script:Ticks[50]=[int64]101 }
  'future-proxy' { $script:Ticks[60]=[int64]400 }
  'deeper' { $script:Processes[60].ParentProcessId=61 }
  'non-python' { $script:Processes[60].Name='cmd.exe' }
  'wrong-pin' { $script:Processes[60].ExecutablePath='C:\other\python.exe' }
  'wrong-leaf' { $script:Processes[70].ExecutablePath='C:\other\python.exe' }
  'different-command' { $script:Processes[60].CommandLine += ' extra' }
  'wrong-root' { $script:Processes[70].CommandLine='python.exe -u C:\other\server\server.py' }
  'wrong-launcher' { $script:Processes[50].CommandLine='cmd.exe /c C:\other\run_server_tip.cmd' }
}
function Get-PortListenerPids([int]$PortNum) { return @(70) }
function Get-ProcessStartTicks([int]$ProcId) { return $script:Ticks[$ProcId] }
function Get-CimInstance([string]$ClassName, [string]$Filter, $ErrorAction) {
  if ($Filter -notmatch '^ProcessId=(\d+)$') { throw '無效測試查詢' }
  return $script:Processes[[int]$Matches[1]]
}
Write-DevServerReceipt -PortNum 18432 -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $owner -ExpectedParent 50 -ExpectedParentTicks 100 -ExpectedPython $pin -ExpectedBasePython $base -ExpectedLauncher $launcher
Write-Host ('WRITTEN=' + (Test-Path -LiteralPath $env:ST_TEST_RECEIPT))
$script:Stopped = @()
function Get-ProcessCommandLine([int]$ProcId) { return [string]$script:Processes[$ProcId].CommandLine }
function Stop-Process([int]$Id,[switch]$Force,$ErrorAction) {
  if ($Id -ne 70) { throw '合成停止只接受本例 leaf 70。' }
  $script:Stopped += $Id
}
function Start-Sleep([int]$Seconds) {}
if (Test-Path -LiteralPath $env:ST_TEST_RECEIPT) {
  Stop-OwnedPortListeners -PortNum 18432 -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $owner
}
Write-Host ('FAKESTOP=' + ($script:Stopped -join ','))
"""
        cases = ('direct', 'venv', 'parent-reused', 'future-proxy', 'deeper',
                 'non-python', 'wrong-pin', 'wrong-leaf', 'different-command',
                 'wrong-root', 'wrong-launcher')
        for name, engine in _powershell_engines().items():
            for case in cases:
                with self.subTest(engine=name, case=case):
                    self.receipt.unlink(missing_ok=True)
                    code, output = self.run_ps(engine, driver, ST_TEST_CASE=case,
                                               ST_TEST_ROOT=self.root)
                    self.assertEqual(code, 0, output)
                    accepted = case in ('direct', 'venv')
                    self.assertEqual(self.receipt.exists(), accepted, output)
                    stopped = re.search(r'(?m)^FAKESTOP=(.*)$', output)
                    self.assertIsNotNone(stopped, output)
                    self.assertEqual(stopped.group(1).strip(), '70' if accepted else '', output)
                    if accepted:
                        receipt = json.loads(self.receipt.read_text(encoding='utf-8-sig'))
                        self.assertEqual(receipt['pid'], 70)
                        self.assertEqual(receipt['startTicksUtc'], 300)


    def test_blank_strong_identity_is_refused_even_with_indirect_invocation(self):
        """空白或缺省強身分一律拒絕；只有完整值可建立收據。"""
        driver = r""". $env:ST_TEST_FUNCS
$owner = $env:ST_TEST_ROOT
$pin = Join-Path $owner 'venv\Scripts\python.exe'
$base = Join-Path $owner 'base\python.exe'
$launcher = Join-Path $owner 'logs\run_server_tip.cmd'
$command = '"' + $pin + '" -u "' + (Join-Path $owner 'server\server.py') + '"'
$script:Processes = @{
  50 = [pscustomobject]@{ProcessId=50;Name='cmd.exe';ParentProcessId=40;CommandLine=('cmd.exe /c "' + $launcher + '"')}
  70 = [pscustomobject]@{ProcessId=70;Name='python.exe';ParentProcessId=50;ExecutablePath=$pin;CommandLine=$command}
}
$script:Stopped = @()
function Get-PortListenerPids([int]$PortNum) {return @(70)}
function Get-ProcessStartTicks([int]$ProcId) {return $(if($ProcId -eq 50){[int64]100}else{[int64]300})}
function Get-CimInstance([string]$ClassName,[string]$Filter,$ErrorAction) {
  if($Filter -notmatch '^ProcessId=(\d+)$') {throw '無效合成查詢'}
  return $script:Processes[[int]$Matches[1]]
}
function Get-ProcessCommandLine([int]$ProcId) {return [string]$script:Processes[$ProcId].CommandLine}
function Stop-Process([int]$Id,[switch]$Force,$ErrorAction) {$script:Stopped += $Id}
function Start-Sleep([int]$Seconds) {}
$values = @{PortNum=18432;ReceiptPath=$env:ST_TEST_RECEIPT;OwnerRoot=$owner;ExpectedParent=50;ExpectedParentTicks=100;ExpectedPython=$pin;ExpectedBasePython=$base;ExpectedLauncher=$launcher}
if($env:ST_TEST_WEAK_PARAM) {
  if($env:ST_TEST_WEAK_KIND -eq 'omitted') {$values.Remove($env:ST_TEST_WEAK_PARAM)}
  elseif($env:ST_TEST_WEAK_KIND -eq 'space') {$values[$env:ST_TEST_WEAK_PARAM]='  '}
  elseif($env:ST_TEST_WEAK_KIND -eq 'tab') {$values[$env:ST_TEST_WEAK_PARAM]=[string][char]9}
  else {$values[$env:ST_TEST_WEAK_PARAM]=''}
}
$functionName = 'Write-' + 'DevServerReceipt'
& $functionName @values
if(Test-Path -LiteralPath $env:ST_TEST_RECEIPT) {
  Stop-OwnedPortListeners -PortNum 18432 -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $owner
}
Write-Host ('FAKESTOP=' + ($script:Stopped -join ','))
"""
        for name, engine in _powershell_engines().items():
            for parameter in ('ExpectedPython', 'ExpectedBasePython', 'ExpectedLauncher', ''):
                kinds = ('empty', 'space', 'tab', 'omitted') if parameter else ('complete',)
                for kind in kinds:
                    with self.subTest(engine=name, parameter=parameter, kind=kind):
                        self.receipt.unlink(missing_ok=True)
                        code, output = self.run_ps(engine, driver, ST_TEST_ROOT=self.root,
                                                   ST_TEST_WEAK_PARAM=parameter, ST_TEST_WEAK_KIND=kind)
                        self.assertEqual(code, 0, output)
                        accepted = not parameter
                        self.assertEqual(self.receipt.exists(), accepted, output)
                        stopped = re.search(r'(?m)^FAKESTOP=(.*)$', output)
                        self.assertIsNotNone(stopped, output)
                        self.assertEqual(stopped.group(1).strip(), '70' if accepted else '', output)

    def test_unknown_listener_is_refused_and_not_touched(self):
        # 沒有收據：占用者可能是本機受管 ST 或任何別的程式，一律不碰。
        other = self.sleeper()
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, out = self.run_ps(engine, _RECEIPT_DRIVER, ST_TEST_STOP_PIDS=other.pid)
                self.assertNotEqual(code, 0, out)
                self.assertIn('ST-PORT-GUARD', out)
                self.assertIn('PID %d' % other.pid, out)
                self.assertNotIn('STOP-RETURNED', out)
                self.assertAlive(other)

    def test_pull_behavior_check_ignores_comments_and_rejects_actual_redirect(self):
        script = self.dir / 'candidate.ps1'
        driver = ". $env:ST_TEST_FUNCS\nAssert-LauncherBehavior -Path $env:ST_TEST_SOURCE\nWrite-Host 'BEHAVIOR-OK'\n"
        source = (ROOT / 'scripts/go.ps1').read_text(encoding='utf-8-sig')
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                script.write_text(source, encoding='utf-8-sig')
                code, out = self.run_ps(engine, driver, ST_TEST_SOURCE=str(script))
                self.assertEqual(code, 0, out)
                self.assertIn('BEHAVIOR-OK', out)
                script.write_text(source + '\nStart-Process sample -RedirectStandardOutput sample.log\n', encoding='utf-8-sig')
                code, out = self.run_ps(engine, driver, ST_TEST_SOURCE=str(script))
                self.assertNotEqual(code, 0)
                self.assertNotIn('BEHAVIOR-OK', out)

    def test_pull_behavior_check_rejects_omitted_strong_receipt_parameters(self):
        script = self.dir / 'candidate.ps1'
        driver = ". $env:ST_TEST_FUNCS\nAssert-LauncherBehavior -Path $env:ST_TEST_SOURCE\nWrite-Host 'BEHAVIOR-OK'\n"
        source = (ROOT / 'scripts/go.ps1').read_text(encoding='utf-8-sig')
        fragments = (' -ExpectedPython $Python',
                     ' -ExpectedBasePython $basePythonLines[0].Trim()',
                     ' -ExpectedLauncher $launcher')
        for fragment in fragments:
            self.assertEqual(source.count(fragment), 1)
        weak_new_call = "\nWrite-DevServerReceipt -PortNum 18432 -ReceiptPath sample -OwnerRoot sample -ExpectedParent 50\n"
        good_new_call = weak_new_call.rstrip() + ' -ExpectedPython python -ExpectedBasePython base -ExpectedLauncher launcher\n'
        for name, engine in _powershell_engines().items():
            for label, candidate, expected in (
                ('original', source, 0),
                ('comment-only', source + '# Write-DevServerReceipt -ExpectedParent 50\n', 0),
                ('explicit-new-call', source + good_new_call, 0),
                *[(fragment, source.replace(fragment, '', 1), 1) for fragment in fragments],
                ('omitted-new-call', source + weak_new_call, 1),
            ):
                with self.subTest(engine=name, mutation=label):
                    script.write_text(candidate, encoding='utf-8-sig')
                    code, output = self.run_ps(engine, driver, ST_TEST_SOURCE=str(script))
                    if expected == 0:
                        self.assertEqual(code, 0, output)
                        self.assertIn('BEHAVIOR-OK', output)
                    else:
                        self.assertNotEqual(code, 0, output)
                        self.assertNotIn('BEHAVIOR-OK', output)

    def test_changed_command_line_receipt_is_refused(self):
        mine = self.sleeper()
        for name, engine in _powershell_engines().items():
            driver = _RECEIPT_DRIVER.replace(
                '$script:ListenerPids = ConvertTo-PidList $env:ST_TEST_STOP_PIDS',
                "$r = Get-Content $env:ST_TEST_RECEIPT -Raw | ConvertFrom-Json\n$r.commandLine = '其他程序'\n$r | ConvertTo-Json | Set-Content $env:ST_TEST_RECEIPT -Encoding UTF8\n$script:ListenerPids = ConvertTo-PidList $env:ST_TEST_STOP_PIDS")
            code, out = self.run_ps(engine, driver, ST_TEST_WRITE_PIDS=mine.pid,
                                    ST_TEST_WRITE_ROOT=self.root, ST_TEST_STOP_PIDS=mine.pid)
            self.assertNotEqual(code, 0, out)
            self.assertIn('ST-PORT-GUARD', out)
            self.assertAlive(mine)

    def test_registered_dev_server_is_the_only_thing_stopped(self):
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                self.receipt.unlink(missing_ok=True)
                mine = self.sleeper()
                code, out = self.run_ps(engine, _RECEIPT_DRIVER, ST_TEST_WRITE_PIDS=mine.pid,
                                        ST_TEST_WRITE_ROOT=self.root, ST_TEST_STOP_PIDS=mine.pid)
                self.assertEqual(code, 0, out)
                self.assertIn('STOP-RETURNED', out)
                mine.wait(timeout=15)
                self.assertIsNotNone(mine.poll())

    def test_receipt_from_another_checkout_is_not_trusted(self):
        mine = self.sleeper()
        other_root = str(self.dir / 'checkout-b')
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, out = self.run_ps(engine, _RECEIPT_DRIVER, ST_TEST_WRITE_PIDS=mine.pid,
                                        ST_TEST_WRITE_ROOT=other_root, ST_TEST_STOP_PIDS=mine.pid)
                self.assertNotEqual(code, 0, out)
                self.assertIn('ST-PORT-GUARD', out)
                self.assertAlive(mine)

    def test_receipt_with_a_different_start_time_is_not_trusted(self):
        # PID 會被作業系統重複使用；收據的啟動時間對不上就不是同一個程序。
        stale = self.sleeper()
        self.receipt.write_text(json.dumps({'pid': stale.pid, 'startTicksUtc': 1, 'root': self.root, 'port': 18432}),
                                encoding='utf-8')
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, out = self.run_ps(engine, _RECEIPT_DRIVER, ST_TEST_STOP_PIDS=stale.pid)
                self.assertNotEqual(code, 0, out)
                self.assertIn('ST-PORT-GUARD', out)
                self.assertAlive(stale)

    def test_another_listener_beside_the_registered_one_stops_everything(self):
        mine = self.sleeper()
        other = self.sleeper()
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, out = self.run_ps(engine, _RECEIPT_DRIVER, ST_TEST_WRITE_PIDS=mine.pid,
                                        ST_TEST_WRITE_ROOT=self.root,
                                        ST_TEST_STOP_PIDS='%d,%d' % (mine.pid, other.pid))
                self.assertNotEqual(code, 0, out)
                self.assertIn('ST-PORT-GUARD', out)
                self.assertAlive(mine, other)

    def test_nothing_listening_returns_quietly(self):
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, out = self.run_ps(engine, _RECEIPT_DRIVER)
                self.assertEqual(code, 0, out)
                self.assertIn('STOP-RETURNED', out)

    def test_real_listener_driver_rejects_unrelated_exception(self):
        driver = _REAL_PORT_DRIVER.replace(
            "Write-Host ('FOUND=' + ((Get-PortListenerPids $port) -join ','))",
            "function Stop-OwnedPortListeners { throw 'UNRELATED-FIXTURE-ERROR' }")
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                code, out = self.run_ps(engine, driver, ST_TEST_PORT=0, ST_TEST_ROOT=self.root)
                self.assertNotEqual(code, 0, out)
                self.assertIn('UNRELATED-FIXTURE-ERROR', out)
                self.assertNotIn('REFUSED:ST-PORT-GUARD', out)
                self.assertNotIn('STOPPED', out)

    @unittest.skipUnless(os.name == 'nt', '依埠找程序用 Windows 的 Get-NetTCPConnection／netstat')
    def test_real_listener_round_trip_on_windows(self):
        code_src = ("import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(5); "
                    "print(s.getsockname()[1], flush=True); time.sleep(600)")
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                self.receipt.unlink(missing_ok=True)
                proc = subprocess.Popen([getattr(sys, '_base_executable', sys.executable),
                                         '-c', code_src], stdout=subprocess.PIPE, text=True)
                self.procs.append(proc)
                port = int(proc.stdout.readline())
                code, out = self.run_ps(engine, _REAL_PORT_DRIVER, ST_TEST_PORT=port, ST_TEST_ROOT=self.root)
                self.assertEqual(code, 0, out)
                self.assertIn('FOUND=%d' % proc.pid, out)
                self.assertIn('REFUSED:ST-PORT-GUARD', out)
                self.assertLess(out.index('REFUSED:ST-PORT-GUARD'), out.index('STOPPED'))
                self.assertNotIn('NOT-REFUSED', out)
                proc.wait(timeout=15)
                self.assertIsNotNone(proc.poll())


if __name__ == '__main__':
    unittest.main()

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
        for name in ('STOP_PRIVATE_WEB.cmd', 'wavedeck/START_WAVEDECK.cmd'):
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
        self.assertNotIn('Stop-PortListeners', script)
        self.assertNotIn('taskkill', script.lower())
        start = script.index('function Stop-OwnedPortListeners')
        end = script.index('\nfunction ', start + 10)
        body = script[start:end]
        self.assertEqual(script.count('Stop-Process'), body.count('Stop-Process'))
        self.assertEqual(body.count('Stop-Process'), 1)
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


_RECEIPT_DRIVER = """\
$ErrorActionPreference = 'Stop'
. $env:ST_TEST_FUNCS
function Get-PortListenerPids([int]$PortNum) { return @($script:ListenerPids) }
function ConvertTo-PidList([string]$text) { return @($text -split ',' | Where-Object { $_ } | ForEach-Object { [int]$_ }) }
$script:ListenerPids = ConvertTo-PidList $env:ST_TEST_WRITE_PIDS
if ($env:ST_TEST_WRITE_ROOT) {
  Write-DevServerReceipt -PortNum 18432 -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_WRITE_ROOT
}
$script:ListenerPids = ConvertTo-PidList $env:ST_TEST_STOP_PIDS
Stop-OwnedPortListeners -PortNum 18432 -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_STOP_ROOT
Write-Host 'STOP-RETURNED'
"""

_REAL_PORT_DRIVER = """\
$ErrorActionPreference = 'Stop'
. $env:ST_TEST_FUNCS
$port = [int]$env:ST_TEST_PORT
Write-Host ('FOUND=' + ((Get-PortListenerPids $port) -join ','))
try {
  Stop-OwnedPortListeners -PortNum $port -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_ROOT
  Write-Host 'NOT-REFUSED'
} catch {
  Write-Host 'REFUSED'
}
Write-DevServerReceipt -PortNum $port -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_ROOT
Stop-OwnedPortListeners -PortNum $port -ReceiptPath $env:ST_TEST_RECEIPT -OwnerRoot $env:ST_TEST_ROOT
Write-Host 'STOPPED'
"""


def _go_ps1_process_helpers():
    """go.ps1 內「找出埠上的程序、登記收據、只結束自己的程序」那一整段函式（原樣取出，不改寫）。"""
    script = (ROOT / 'scripts' / 'go.ps1').read_bytes().decode('utf-8-sig')
    return script[script.index('function Get-PortListenerPids'):script.index('function Assert-TipHtml')]


@unittest.skipIf(not _powershell_engines(), '找不到 PowerShell（CI 的 Windows／Ubuntu 都有）')
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
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])
        self.procs.append(proc)
        return proc

    def run_ps(self, engine, driver, **env):
        script = self.dir / 'driver.ps1'
        script.write_bytes(b'\xef\xbb\xbf' + driver.encode('utf-8'))
        full_env = dict(os.environ, ST_TEST_FUNCS=str(self.funcs), ST_TEST_RECEIPT=str(self.receipt),
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

    @unittest.skipUnless(os.name == 'nt', '依埠找程序用 Windows 的 Get-NetTCPConnection／netstat')
    def test_real_listener_round_trip_on_windows(self):
        code_src = ("import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(5); "
                    "print(s.getsockname()[1], flush=True); time.sleep(600)")
        for name, engine in _powershell_engines().items():
            with self.subTest(engine=name):
                self.receipt.unlink(missing_ok=True)
                proc = subprocess.Popen([sys.executable, '-c', code_src], stdout=subprocess.PIPE, text=True)
                self.procs.append(proc)
                port = int(proc.stdout.readline())
                code, out = self.run_ps(engine, _REAL_PORT_DRIVER, ST_TEST_PORT=port, ST_TEST_ROOT=self.root)
                self.assertEqual(code, 0, out)
                self.assertIn('FOUND=%d' % proc.pid, out)
                self.assertLess(out.index('REFUSED'), out.index('STOPPED'))
                self.assertNotIn('NOT-REFUSED', out)
                proc.wait(timeout=15)
                self.assertIsNotNone(proc.poll())


if __name__ == '__main__':
    unittest.main()

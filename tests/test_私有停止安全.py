"""以隔離程序驗證停止器，不啟動或關閉正式服務。"""
from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', '僅 Windows 具有 CIM 程序身分')
class PrivateStopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ST停止測試 ')
        self.base = Path(self.tmp.name)
        self.owned = self.base / 'owned'
        self.production = self.base / 'production'
        self.foreign = self.base / 'foreign'
        self.processes = []
        for root in (self.owned, self.production, self.foreign):
            for folder in ('scripts', 'server', 'data'):
                (root / folder).mkdir(parents=True, exist_ok=True)
            for file in ('scripts/private_web_host.py', 'server/private_web_gateway.py', 'server/server.py'):
                (root / file).write_text('import time\ntime.sleep(90)\n', encoding='utf-8')

    def tearDown(self):
        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
        self.tmp.cleanup()

    def spawn(self, root, script, *, relative=False):
        proc = subprocess.Popen([sys.executable, '-u', script if relative else str(root / script)],
                                cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(proc)
        return proc

    def stop(self):
        return subprocess.run(['cmd', '/d', '/c', str(ROOT / 'STOP_PRIVATE_WEB.cmd'),
                               '-InstallRoot', str(self.owned), '-ProductionRoot', str(self.production)],
                              capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)

    def test_stops_owned_host_children_and_gateway_preserves_foreign_and_dev(self):
        host_script = self.owned / 'scripts/private_web_host.py'
        host_script.write_text(
            'import pathlib,subprocess,sys,time\n'
            'root=pathlib.Path(__file__).resolve().parents[1]\n'
            'p=subprocess.Popen([sys.executable,"-u",str(root/"server/server.py")])\n'
            '(root/"data/child.pid").write_text(str(p.pid))\n'
            'time.sleep(90)\n', encoding='utf-8')
        host = self.spawn(self.owned, 'scripts/private_web_host.py')
        gateway = self.spawn(self.production, 'server/private_web_gateway.py')
        foreign = self.spawn(self.foreign, 'scripts/private_web_host.py')
        dev = self.spawn(self.owned, 'server/server.py')
        pid_file = self.owned / 'data/child.pid'
        for _ in range(100):
            if pid_file.exists():
                break
            time.sleep(.05)
        self.assertTrue(pid_file.exists())
        child_pid = int(pid_file.read_text())
        (self.owned / 'data/private_web_host.pid').write_text(str(host.pid), encoding='ascii')
        (self.production / 'data/private_web_gateway.pid').write_text(str(gateway.pid), encoding='ascii')
        try:
            result = self.stop()
            self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
            self.assertIsNotNone(host.wait(timeout=5))
            self.assertIsNotNone(gateway.wait(timeout=5))
            self.assertIsNone(foreign.poll())
            self.assertIsNone(dev.poll())
            check = subprocess.run(['powershell', '-NoProfile', '-Command',
                                    f'if (Get-Process -Id {child_pid} -ErrorAction SilentlyContinue) {{exit 1}}'],
                                   capture_output=True, timeout=10)
            self.assertEqual(check.returncode, 0, '隸屬已核對 host 的 backend 必須停止')
        finally:
            # 僅清理本測試親自啟動且仍隸屬同一 host 的子程序。
            subprocess.run(['powershell', '-NoProfile', '-Command',
                            f'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {child_pid}"; '
                            f'if ($p -and $p.ParentProcessId -eq {host.pid}) {{Stop-Process -Id {child_pid} -Force}}'],
                           capture_output=True, timeout=10)

    def test_stale_pid_does_not_kill_another_python(self):
        foreign = self.spawn(self.foreign, 'scripts/private_web_host.py')
        record = self.owned / 'data/private_web_host.pid'
        record.write_text(str(foreign.pid), encoding='ascii')
        result = self.stop()
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(foreign.poll())
        self.assertEqual(record.read_text(), str(foreign.pid))

    def test_relative_identity_is_rejected_without_ending_unverified_process(self):
        host = self.spawn(self.owned, 'scripts/private_web_host.py', relative=True)
        (self.owned / 'data/private_web_host.pid').write_text(str(host.pid), encoding='ascii')
        self.assertEqual(self.stop().returncode, 1)
        self.assertIsNone(host.poll())

    def test_no_services_and_invalid_pid_are_safe(self):
        self.assertEqual(self.stop().returncode, 0)
        record = self.owned / 'data/private_web_gateway.pid'
        record.write_text('not-a-pid', encoding='ascii')
        self.assertEqual(self.stop().returncode, 1)
        self.assertTrue(record.exists())

    def test_short_install_path_matches_full_script_path(self):
        import ctypes
        buf = ctypes.create_unicode_buffer(4096)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(self.owned), buf, len(buf))
        self.assertGreater(length, 0)
        host = self.spawn(self.owned, 'scripts/private_web_host.py')
        (self.owned / 'data/private_web_host.pid').write_text(str(host.pid), encoding='ascii')
        self.owned = Path(buf.value)
        result = self.stop()
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertIsNotNone(host.wait(timeout=5))

    def run_powershell_fixture(self, body):
        fixture = self.base / '排程測試.ps1'
        fixture.write_text(body, encoding='utf-8-sig')
        return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(fixture)],
                              capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)

    def task_fixture(self):
        root = self.base / 'installation/current'
        (root / 'scripts').mkdir(parents=True)
        (root / 'scripts/private_web_host.py').write_text('', encoding='utf-8')
        runner = root.parent / 'startup/private_web_startup.ps1'
        runner.parent.mkdir()
        runner.write_text('', encoding='utf-8')
        # 此假排程只交給函式；不註冊、修改或停止 Windows 的真實排程。
        return root, f'''
$root = '{root}'
$action = [pscustomobject]@{{Execute=(Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'); WorkingDirectory=$root;
    Arguments='-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{runner}" -Mode RunHost -InstallRoot "{root.parent}" -BackendPort 18435 -GatewayPort 18434'}}
$task = [pscustomobject]@{{TaskName='StockTerminal_PrivateWeb_Host'; TaskPath='\\'; Actions=@($action); State=4}}
'''

    def test_scheduled_task_identity_rejects_foreign_and_ambiguous_actions(self):
        root, setup = self.task_fixture()
        body = f". '{ROOT / 'scripts/停止私有網站.ps1'}' -FunctionsOnly\n" + setup + r'''
if (-not (Test-PrivateWebScheduledTask $task $root)) { throw '合法排程未通過' }
$original = $action.Arguments
foreach ($bad in @(
    ($original -replace '-Mode RunHost', '-Mode Install'),
    ($original + ' -InstallRoot "C:\other"'),
    ($original + ' -c "Write-Output test"'),
    ($original + ' -EncodedCommand anything'),
    ($original -replace '-File "[^"]+"', '-File "relative.ps1"'),
    ($original -replace '-InstallRoot "[^"]+"', '-InstallRoot "."'),
    ($original -replace '-File "[^"]+"', '-File "C:\absent.ps1"')
)) {
    $action.Arguments = $bad
    if (Test-PrivateWebScheduledTask $task $root) { throw '接受了不明啟動參數' }
}
$action.Arguments = $original
$task.TaskPath = '\other\'
if (Test-PrivateWebScheduledTask $task $root) { throw '接受了其他排程資料夾' }
$task.TaskPath = '\'
$task.Actions = @($action, $action)
if (Test-PrivateWebScheduledTask $task $root) { throw '接受了多個啟動動作' }
$task.Actions = @($action)
$action.Execute = 'powershell.exe'
if (Test-PrivateWebScheduledTask $task $root) { throw '接受了未核對的 shell' }
$action.Execute = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action.WorkingDirectory = Split-Path $root -Parent
if (Test-PrivateWebScheduledTask $task $root) { throw '接受了不同的工作目錄' }
'''
        result = self.run_powershell_fixture(body)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))

    def test_scheduled_stop_precedes_host_and_fails_closed_on_scheduler_error(self):
        root, setup = self.task_fixture()
        for scenario, expected_code, expected_events in (
            ('owned', 0, ['task', 'process']),
            ('foreign', 0, ['process']),
            ('missing', 0, ['process']),
            ('read_error', 1, []),
            ('stop_error', 1, []),
        ):
            with self.subTest(scenario=scenario):
                events = self.base / '動作.jsonl'
                events.write_text('', encoding='utf-8')
                body = setup + f'''
$scenario = '{scenario}'
$events = '{events}'
$global:gone = $false
$global:stopped = $false
function Get-ScheduledTask {{
    [CmdletBinding()]param($TaskName, $TaskPath)
    if ($scenario -eq 'missing') {{ Write-Error '不存在' -Category ObjectNotFound; return }}
    if ($scenario -eq 'read_error') {{ throw '拒絕讀取排程' }}
    if ($scenario -eq 'foreign') {{ $task.TaskPath = '\\foreign\\' }}
    if ($global:stopped) {{ $task.State = 3 }}
    return $task
}}
function Stop-ScheduledTask {{
    [CmdletBinding()]param($TaskName, $TaskPath)
    if ($scenario -eq 'stop_error') {{ throw '停止排程失敗' }}
    Add-Content -LiteralPath $events -Value '"task"'
    $global:stopped = $true
}}
function Get-CimInstance {{
    param($ClassName, $Filter)
    if (-not $global:gone) {{
        [pscustomobject]@{{Name='python.exe'; CommandLine='"C:\\Python\\python.exe" -u "{root / 'scripts/private_web_host.py'}"';
            ProcessId=99999; ParentProcessId=88888; CreationDate='2026-10-02'}}
    }}
}}
function Stop-Process {{
    [CmdletBinding()]param($Id, [switch]$Force)
    Add-Content -LiteralPath $events -Value '"process"'
    $global:gone = $true
}}
& '{ROOT / 'scripts/停止私有網站.ps1'}' -InstallRoot $root -ProductionRoot $root
exit $LASTEXITCODE
'''
                result = self.run_powershell_fixture(body)
                self.assertEqual(result.returncode, expected_code, (scenario, result.stdout, result.stderr))
                self.assertEqual([json.loads(line) for line in events.read_text().splitlines()], expected_events)


if __name__ == '__main__':
    unittest.main()

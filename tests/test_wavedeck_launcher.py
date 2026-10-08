#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaveDeck 啟動器的離線 PowerShell 5.1 邊界驗證，不啟動產品或瀏覽器。"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'wavedeck' / 'start_wavedeck.ps1'
POWERSHELL = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'

_FIXTURE = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$env:WAVEDECK_HOST = $null
$env:WAVEDECK_PORT = $null
$homePath = $env:WD_TEST_HOME
$pythonPath = $env:WD_TEST_PYTHON
. $env:WD_TEST_LAUNCHER
function Assert-That([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw ('定向測試失敗：' + $Message) }
}
function Reset-Fixture {
    $script:Responses = @{}
    $script:Probes = [Collections.Generic.List[int]]::new()
    $script:Starts = [Collections.Generic.List[object]]::new()
    $script:ServeAfterStart = $null
    $script:FailStart = $false
    $script:Exited = $false
    $script:PythonResolves = 0
    $env:WAVEDECK_PORT = $null
    $receipt = Join-Path $homePath 'data\wavedeck.port'
    if (Test-Path -LiteralPath $receipt) { Remove-Item -LiteralPath $receipt -Force }
}
function New-Health([int]$Port, [string]$Base = $homePath) {
    return [pscustomobject]@{ok=$true;service='WaveDeck';baseDir=$Base;port=$Port}
}
function Invoke-RestMethod {
    [CmdletBinding()]
    param([string]$Uri, [int]$TimeoutSec)
    Assert-That ($Uri -match '\Ahttp://127\.0\.0\.1:(\d+)/health\z') '只能探測 loopback 的 health'
    $port = [int]$Matches[1]
    Assert-That ($port -notin @(18432,18434,18435)) '不得探測 Stock Terminal 或 Private Web 保留埠'
    Assert-That ($TimeoutSec -eq 1) '單次探測必須有一秒上限'
    $script:Probes.Add($port)
    if ($script:Responses.ContainsKey($port)) { return $script:Responses[$port] }
    throw '離線 fixture：此候選埠尚未就緒'
}
function Start-Process {
    [CmdletBinding()]
    param([string]$FilePath, $ArgumentList, [string]$WorkingDirectory,
          [string]$WindowStyle, [string]$RedirectStandardOutput,
          [string]$RedirectStandardError, [switch]$PassThru)
    $kind = if ($FilePath.StartsWith('http://')) { 'browser' } else { 'server' }
    $script:Starts.Add([pscustomobject]@{kind=$kind;file=$FilePath;arguments=@($ArgumentList);
        directory=$WorkingDirectory;window=$WindowStyle;stdout=$RedirectStandardOutput;
        stderr=$RedirectStandardError;passThru=[bool]$PassThru})
    if ($kind -eq 'server') {
        if ($script:FailStart) { throw '離線 fixture：程序建立失敗' }
        if ($null -ne $script:ServeAfterStart) {
            $script:Responses[[int]$script:ServeAfterStart] = New-Health ([int]$script:ServeAfterStart)
        }
        return [pscustomobject]@{Id=12345;HasExited=$script:Exited;ExitCode=7}
    }
}
function Resolve-WaveDeckPython {
    param([string]$WaveDeckRoot)
    Assert-That ($WaveDeckRoot -eq $homePath) 'Python 解析必須使用本次 home'
    $script:PythonResolves++
    return $pythonPath
}
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }
function Stop-Process { throw '定向測試禁止終止任何程序' }
function Invoke-WebRequest { throw '定向測試禁止另一條 HTTP 入口' }
Reset-Fixture
'''


@unittest.skipUnless(os.name == 'nt' and POWERSHELL.is_file(), '此定向測試需要 Windows PowerShell 5.1')
class WaveDeckLauncher(unittest.TestCase):
    def run_ps(self, source: str, *, fixture: bool = True, timeout: int = 12):
        with tempfile.TemporaryDirectory(prefix='wd-launcher-offline-') as temporary:
            base = Path(temporary)
            home = base / 'project with spaces' / 'wavedeck'
            (home / 'data').mkdir(parents=True)
            (home / 'run.py').write_text('# 離線入口占位，禁止執行\n', encoding='utf-8')
            python = base / 'python with spaces.exe'
            python.write_bytes(b'fixture')
            driver = base / 'driver.ps1'
            prefix = _FIXTURE if fixture else r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$env:WAVEDECK_HOST = $null
$env:WAVEDECK_PORT = $null
$homePath = $env:WD_TEST_HOME
$pythonPath = $env:WD_TEST_PYTHON
. $env:WD_TEST_LAUNCHER
function Assert-That([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw ('定向測試失敗：' + $Message) }
}
function Start-Process { throw '定向測試禁止啟動任何程序' }
function Invoke-RestMethod { throw '定向測試禁止實際網路' }
'''
            driver.write_text(prefix + source + '\nWrite-Output "WD-TEST-OK"\n', encoding='utf-8-sig')
            environment = dict(os.environ, WD_TEST_HOME=str(home), WD_TEST_PYTHON=str(python),
                               WD_TEST_LAUNCHER=str(LAUNCHER))
            result = subprocess.run(
                [str(POWERSHELL), '-NoLogo', '-NoProfile', '-NonInteractive',
                 '-ExecutionPolicy', 'Bypass', '-File', str(driver)],
                cwd=base, env=environment, capture_output=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
            self.assertEqual(result.returncode, 0, output)
            self.assertIn('WD-TEST-OK', output)
            return output

    def test_port_receipts_environment_and_reserved_ports(self):
        self.run_ps(r'''
$receipt = Join-Path $homePath 'data\wavedeck.port'
Set-Content -LiteralPath $receipt -Value 19000 -Encoding UTF8
$env:WAVEDECK_PORT = '19001'
$ports = @(Get-WaveDeckPorts -WaveDeckRoot $homePath)
Assert-That ($ports -contains 19000 -and $ports -contains 19001) '收據及自訂候選必須保留'
Assert-That ($ports.Count -eq (@($ports | Select-Object -Unique)).Count) '候選埠不得重複'
foreach ($reserved in @(18432,18434,18435)) {
    Set-Content -LiteralPath $receipt -Value $reserved -Encoding ASCII
    $env:WAVEDECK_PORT = $null
    $ports = @(Get-WaveDeckPorts -WaveDeckRoot $homePath)
    Assert-That ($ports -notcontains $reserved) '保留埠收據不得成為候選'
    $env:WAVEDECK_PORT = [string]$reserved
    $rejected = $false
    try { $null = Get-WaveDeckPorts -WaveDeckRoot $homePath } catch { $rejected = $true }
    Assert-That $rejected '保留埠環境設定必須拒絕'
}
foreach ($invalid in @('0','65536','not-a-port')) {
    $env:WAVEDECK_PORT = $invalid
    $rejected = $false
    try { $null = Get-WaveDeckPorts -WaveDeckRoot $homePath } catch { $rejected = $true }
    Assert-That $rejected '無效環境設定必須拒絕'
}
Reset-Fixture
$null = Find-WaveDeckService -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($script:Probes.Count -eq 5) '離線情境須查既有五個候選'
''')

    def test_existing_same_home_is_reused_and_no_browser_is_respected(self):
        self.run_ps(r'''
$script:Responses[18433] = New-Health 18433
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($rc -eq 0) '同 home 的服務應成功重用'
Assert-That ($script:Starts.Count -eq 1 -and $script:Starts[0].kind -eq 'browser') '重用只能開瀏覽器'
Assert-That ($script:Starts[0].file -eq 'http://127.0.0.1:18433/') '開啟確認過的服務網址'
Assert-That ($script:PythonResolves -eq 0) '已在線時不再解析或啟動 Python'
Reset-Fixture
$script:Responses[18433] = New-Health 18433
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1 -NoBrowser
Assert-That ($rc -eq 0 -and $script:Starts.Count -eq 0) 'NoBrowser 不開頁且不重啟'
''')

    def test_identity_checks_skip_foreign_services_and_reject_old_wavedeck(self):
        self.run_ps(r'''
$script:Responses[18433] = New-Health 18433 (Join-Path $homePath 'other-home')
$script:Responses[18765] = [pscustomobject]@{ok=$true;service='OtherService';baseDir=$homePath;port=18765}
$script:Responses[28765] = New-Health 28765
$port = Find-WaveDeckService -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($port -eq 28765) '不同 home 與其他服務不得誤重用'
Assert-That ($script:Starts.Count -eq 0) '探測不得啟動服務或開頁'
foreach ($wrong in @('false-ok','string-ok','string-port','wrong-port','wrong-case-service')) {
    Reset-Fixture
    $health = New-Health 18433
    switch ($wrong) {
        'false-ok' {$health.ok=$false}
        'string-ok' {$health.ok='true'}
        'string-port' {$health.port='18433'}
        'wrong-port' {$health.port=18765}
        'wrong-case-service' {$health.service='wavedeck'}
    }
    $script:Responses[18433] = $health
    Assert-That ($null -eq (Find-WaveDeckService -WaveDeckRoot $homePath -TimeoutSec 1)) '不完整或型別錯誤的就緒身分不得成功'
}
foreach ($missing in @('baseDir','port')) {
    Reset-Fixture
    $health = @{ok=$true;service='WaveDeck';baseDir=$homePath;port=18433}
    $health.Remove($missing)
    $script:Responses[18433] = [pscustomobject]$health
    $rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1
    Assert-That ($rc -eq 1 -and $script:Starts.Count -eq 0) '舊 WaveDeck 缺身分須拒絕新增服務及開頁'
}
''')

    def test_new_service_uses_pinned_hidden_process_and_actual_fallback_url(self):
        self.run_ps(r'''
$script:Responses[18433] = [pscustomobject]@{ok=$true;service='OtherService';baseDir=$homePath;port=18433}
$script:ServeAfterStart = 28765
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($rc -eq 0 -and $script:Starts.Count -eq 2) '新服務成功後只開一次服務及一次頁面'
$server = $script:Starts[0]
Assert-That ($server.kind -eq 'server' -and $server.file -eq $pythonPath) '使用絕對釘選 Python'
Assert-That ($server.directory -eq $homePath -and $server.window -eq 'Hidden' -and $server.passThru) '程序須隱藏並綁定 home'
Assert-That ($server.arguments.Count -eq 3 -and $server.arguments[0] -eq '-B' -and $server.arguments[1] -eq '-u') '沿用既有 run.py 並禁寫 bytecode'
Assert-That ($server.arguments[2] -eq ('"' + (Join-Path $homePath 'run.py') + '"')) 'run.py 必須為引號包住的絕對路徑'
Assert-That ($server.stdout -and $server.stderr -and $server.stdout -ne $server.stderr) 'stdout 與 stderr 診斷必須保留'
Assert-That ($script:Starts[1].file -eq 'http://127.0.0.1:28765/') '必須開啟實際 fallback 埠'
Reset-Fixture
$script:ServeAfterStart = 18765
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1 -NoBrowser
Assert-That ($rc -eq 0 -and $script:Starts.Count -eq 1 -and $script:Starts[0].kind -eq 'server') '新服務的 NoBrowser 不開頁'
''')

    def test_start_failure_exited_process_and_deadline_do_not_open_browser(self):
        self.run_ps(r'''
$script:FailStart = $true
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($rc -eq 1 -and $script:Starts.Count -eq 1 -and $script:Starts[0].kind -eq 'server') '建立程序失敗不開頁'
Reset-Fixture
$script:Exited = $true
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($rc -eq 1 -and $script:Starts.Count -eq 1 -and $script:Starts[0].kind -eq 'server') '服務提前結束不開頁'
Reset-Fixture
$watch = [Diagnostics.Stopwatch]::StartNew()
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($watch.Elapsed.TotalSeconds -lt 4) '就緒等待必須有明確有限上限'
Assert-That ($rc -eq 1 -and $script:Starts.Count -eq 1 -and $script:Starts[0].kind -eq 'server') '未就緒逾時不開頁'
''')

    def test_elapsed_initial_probe_does_not_start_late_process(self):
        self.run_ps(r'''
function Find-WaveDeckService {
    param([string]$WaveDeckRoot, [double]$TimeoutSec)
    Microsoft.PowerShell.Utility\Start-Sleep -Milliseconds 1100
    return $null
}
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($rc -eq 1 -and $script:Starts.Count -eq 0) '初次探測已耗盡期限，不可再建立未被等待的服務或開頁'
Assert-That ($script:PythonResolves -eq 0) '初次探測逾時後不可再解析 Python'
Reset-Fixture
function Find-WaveDeckService {
    param([string]$WaveDeckRoot, [double]$TimeoutSec)
    return $null
}
function Resolve-WaveDeckPython {
    param([string]$WaveDeckRoot)
    Microsoft.PowerShell.Utility\Start-Sleep -Milliseconds 1100
    return $pythonPath
}
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -TimeoutSec 1
Assert-That ($rc -eq 1 -and $script:Starts.Count -eq 0) 'Python 解析已耗盡期限，不可再建立未被等待的服務或開頁'
''')

    def test_parent_and_grandparent_utf8_python_pins(self):
        self.run_ps(r'''
$parent = Split-Path -Parent $homePath
$grandparent = Split-Path -Parent $parent
foreach ($project in @($parent,$grandparent)) {
    $pinDirectory = Join-Path $project 'data'
    New-Item -ItemType Directory -Path $pinDirectory -Force | Out-Null
    $pin = Join-Path $pinDirectory 'stock_python.path'
    [IO.File]::WriteAllText($pin, $pythonPath, [Text.UTF8Encoding]::new($true))
    $actual = Resolve-WaveDeckPython -WaveDeckRoot $homePath
    Assert-That ($actual -eq $pythonPath) '父或祖父專案的 UTF-8 BOM 釘選須可讀取'
    [IO.File]::WriteAllText($pin, 'python.exe', [Text.UTF8Encoding]::new($false))
    $rejected = $false
    try { $null = Resolve-WaveDeckPython -WaveDeckRoot $homePath } catch { $rejected = $true }
    Assert-That $rejected '相對 Python pin 不可執行或退回裸 Python'
    Remove-Item -LiteralPath $pin -Force
}
''', fixture=False)


if __name__ == '__main__':
    unittest.main()

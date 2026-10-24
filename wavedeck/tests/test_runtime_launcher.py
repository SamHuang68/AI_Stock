"""Offline launcher binding cases; all service and process operations are mocked."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"

PREFIX = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$homePath = [IO.Path]::GetFullPath($env:WD_CASE_HOME)
$codePath = Split-Path -Parent $homePath
$installPath = Split-Path -Parent $codePath
. $env:WD_CASE_LAUNCHER -WaveDeckRoot $homePath -NoBrowser
function Assert-That([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
$script:Starts = 0
$script:Resolves = 0
$script:Ready = $true
$script:WrongRoot = $false
function Resolve-WaveDeckPython {
    param([string]$WaveDeckRoot)
    $script:Resolves++
    Assert-That ($env:ST_RUNTIME_ROLE -eq 'wavedeck') 'child role must be WaveDeck'
    return (Join-Path $installPath 'python.exe')
}
function Get-WaveDeckRuntime {
    param([string]$WaveDeckRoot, [string]$PythonExe)
    return [pscustomobject]@{storageMode='external';runtimeRole='wavedeck';dataRootId='fixture-root';
        storageCapability=1;dataDir=(Join-Path $installPath 'runtime\wavedeck');
        portFile=(Join-Path $installPath 'runtime\wavedeck\wavedeck.port');
        logDir=(Join-Path $installPath 'runtime\wavedeck\logs')}
}
function Invoke-RestMethod {
    param([string]$Uri, [int]$TimeoutSec)
    if (-not $script:Ready) { throw 'offline: no listener' }
    Assert-That ($Uri -match '\Ahttp://127\.0\.0\.1:(\d+)/health\z') 'only health probes are allowed'
    $rootId = if ($script:WrongRoot) { 'other-root' } else { 'fixture-root' }
    return [pscustomobject]@{ok=$true;service='WaveDeck';baseDir=$homePath;port=[int]$Matches[1];
        storageMode='external';runtimeRole='wavedeck';dataRootId=$rootId;storageCapability=1;
        dataDir=(Join-Path $installPath 'runtime\wavedeck')}
}
function Start-Process {
    param([string]$FilePath, $ArgumentList, [string]$WorkingDirectory, [string]$WindowStyle,
          [switch]$PassThru, [string]$RedirectStandardOutput, [string]$RedirectStandardError)
    Assert-That ($env:ST_RUNTIME_ROLE -eq 'wavedeck') 'started process inherited another role'
    Assert-That ($WindowStyle -eq 'Hidden') 'child must remain hidden'
    Assert-That (-not $RedirectStandardOutput -and -not $RedirectStandardError) 'launcher wrote runtime logs before lease'
    Assert-That ($ArgumentList -contains '--launcher-log-id') 'child must own its log setup'
    $script:Starts++
    $script:Ready = $true
    return [pscustomobject]@{HasExited=$false;ExitCode=0}
}
function Start-Sleep { param([int]$Milliseconds) }
function Stop-Process { throw 'process termination forbidden' }
'''


@unittest.skipUnless(os.name == "nt" and POWERSHELL.is_file(), "Requires Windows PowerShell 5.1")
class LauncherBindingTests(unittest.TestCase):
    def run_case(self, source):
        with tempfile.TemporaryDirectory(prefix="wd-binding-launcher-") as temporary:
            install = Path(os.path.realpath(temporary))  # 8.3 短檔名（RUNNER~1）須展開為正規拼寫
            home = install / "current/wavedeck"
            home.mkdir(parents=True)
            (home / "run.py").write_text("# offline placeholder; must never run\n", encoding="utf-8")
            driver = install / "case.ps1"
            driver.write_text(PREFIX + source, encoding="utf-8-sig")
            env = {k: v for k, v in os.environ.items() if k not in {
                "ST_DATA_ROOT", "ST_DATA_BINDING", "ST_RUNTIME_ROLE", "ST_PYTHON", "WAVEDECK_HOST", "WAVEDECK_PORT"}}
            env.update(WD_CASE_HOME=str(home), WD_CASE_LAUNCHER=str(ROOT / "wavedeck/start_wavedeck.ps1"))
            done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
                                  cwd=temporary, env=env, capture_output=True, timeout=15,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(done.returncode, 0, (done.stdout + done.stderr).decode("utf-8", errors="replace"))

    def test_installed_sidecar_child_role_and_environment_restore(self):
        self.run_case(r'''
Set-Content -LiteralPath (Join-Path $installPath 'runtime_binding.json') -Value '{}' -Encoding UTF8
$env:ST_RUNTIME_ROLE = 'client'
$script:Ready = $false
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -NoBrowser -TimeoutSec 3
Assert-That ($rc -eq 0 -and $script:Starts -eq 1) 'registered sidecar did not start one mocked child'
Assert-That ($env:ST_RUNTIME_ROLE -eq 'client') 'parent role changed after launch'
Assert-That (-not (Test-Path Env:ST_DATA_BINDING)) 'discovered binding leaked into caller'
Assert-That (-not (Test-Path -LiteralPath (Join-Path $installPath 'runtime'))) 'launcher created runtime data before child lease'
''')

    def test_external_receipt_without_binding_refuses_before_python(self):
        self.run_case(r'''
Set-Content -LiteralPath (Join-Path $codePath '.private_web_release.json') -Value '{"storageBinding":{"storageMode":"external"}}' -Encoding UTF8
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -NoBrowser
Assert-That ($rc -eq 1 -and $script:Resolves -eq 0 -and $script:Starts -eq 0) 'missing binding fell back to legacy'
Assert-That (-not (Test-Path Env:ST_RUNTIME_ROLE)) 'failed launch leaked role'
''')

    def test_wrong_health_data_root_never_starts_duplicate(self):
        self.run_case(r'''
$env:ST_DATA_BINDING = Join-Path $installPath 'explicit-binding.json'
$env:ST_RUNTIME_ROLE = 'backend'
$original = $env:ST_DATA_BINDING
$script:WrongRoot = $true
$rc = Invoke-WaveDeckLaunch -WaveDeckRoot $homePath -NoBrowser
Assert-That ($rc -eq 1 -and $script:Starts -eq 0) 'wrong health identity accepted'
Assert-That ($env:ST_RUNTIME_ROLE -eq 'backend' -and $env:ST_DATA_BINDING -eq $original) 'failed launch changed caller environment'
''')

    def test_standalone_guard_detects_receipt_and_sidecar_without_environment(self):
        self.run_case(r'''
$guard = Join-Path (Split-Path -Parent (Split-Path -Parent $env:WD_CASE_LAUNCHER)) 'scripts\assert_standalone_runtime.ps1'
Set-Content -LiteralPath (Join-Path $codePath '.private_web_release.json') -Value '{"storageBinding":{"storageMode":"external"}}' -Encoding UTF8
$rejected = $false
try { & $guard -CodeRoot $codePath } catch { $rejected = $true }
Assert-That $rejected 'standalone guard ignored external receipt'
Set-Content -LiteralPath (Join-Path $codePath '.private_web_release.json') -Value '{}' -Encoding UTF8
Set-Content -LiteralPath (Join-Path $installPath 'runtime_binding.json') -Value '{}' -Encoding UTF8
$rejected = $false
try { & $guard -CodeRoot $codePath } catch { $rejected = $true }
Assert-That $rejected 'standalone guard ignored installed binding'
''')


if __name__ == "__main__":
    unittest.main()

# Quick diagnosis for 「仍兩框 / Hermes 空白窗」
# Usage: powershell -ExecutionPolicy Bypass -File .\scripts\diagnose_tip.ps1
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host '=== Stock Terminal tip diagnose ==='
Write-Host "repo: $Root"
Write-Host "branch: $(git branch --show-current 2>$null)"
Write-Host "HEAD:   $(git rev-parse --short HEAD 2>$null)"

$go = Join-Path $Root 'scripts\go.ps1'
$pulse = Join-Path $Root 'src\ui\pulse_v5.js'
Write-Host ("go.ps1 has Resolve-StockPython: " + ((Test-Path $go) -and ((Get-Content $go -Raw) -match 'Resolve-StockPython')))
Write-Host ("pulse has ANCHOR_4col2z:      " + ((Test-Path $pulse) -and ((Get-Content $pulse -Raw) -match 'PULSE_LAYOUT_ANCHOR_4col2z')))
Write-Host ("pulse has 4col-priority:      " + ((Test-Path $pulse) -and ((Get-Content $pulse -Raw) -match '4col-priority')))
Write-Host ("pulse has media 1280 crush:   " + ((Test-Path $pulse) -and ((Get-Content $pulse -Raw) -match 'max-width:1280')))

Write-Host ''
Write-Host '--- where python ---'
try { where.exe python 2>$null | ForEach-Object { Write-Host "  $_" } } catch {}
try {
  $py = & py -3 -c "import sys; print(sys.executable)" 2>$null
  Write-Host "  py -3 => $py"
} catch { Write-Host '  py -3 => (none)' }

Write-Host ''
Write-Host '--- listeners :18432 ---'
try {
  Get-NetTCPConnection -LocalPort 18432 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    Write-Host ("  PID {0}  {1}" -f $_.OwningProcess, $p.Path)
  }
} catch {
  netstat -ano | Select-String ':18432\s+.*LISTENING'
}

Write-Host ''
Write-Host '--- /health ---'
try {
  $h = Invoke-RestMethod -Uri 'http://127.0.0.1:18432/health' -TimeoutSec 3
  Write-Host ("  tipUx={0} version={1}" -f $h.tipUx, $h.version)
  Write-Host ("  pythonExe={0}" -f $h.pythonExe)
  Write-Host ("  pythonBlocked={0}" -f $h.pythonBlocked)
  Write-Host ("  baseDir={0}" -f $h.baseDir)
  Write-Host ("  layoutAnchor={0}" -f $h.pulseLayout.layoutAnchor)
  Write-Host ("  hasFourColPriority={0}" -f $h.pulseLayout.hasFourColPriority)
} catch {
  Write-Host "  /health FAILED: $_"
}

$boot = Join-Path $Root 'logs\SERVER_BOOT.txt'
Write-Host ''
Write-Host "--- last lines of $boot ---"
if (Test-Path $boot) {
  Get-Content $boot -Tail 12
} else {
  Write-Host '  (missing — server never wrote boot log)'
}

Write-Host ''
Write-Host 'Expected OK: layoutAnchor=PULSE_LAYOUT_ANCHOR_4col2z, pythonBlocked=False, no hermes path'
Write-Host 'Fix: double-click START_TIP.cmd in repo root'

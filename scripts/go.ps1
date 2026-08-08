# Stock Terminal v5.0 — tip UX only (PowerShell)
# Usage (from repo root):
#   DOUBLE-CLICK:  START_TIP.cmd   ← preferred when Hermes steals python
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 -Pull
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 -RebuildOnly
#   powershell -ExecutionPolicy Bypass -File .\scripts\diagnose_tip.ps1
#
# CRITICAL: never use Hermes / agent venv python.exe — that opens a blank
# console and leaves an old :18432 process serving 兩框 UI.
param(
  [switch]$Pull,
  [switch]$RebuildOnly
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root 'build_v2.py'))) {
  $Root = (Get-Location).Path
}
Set-Location $Root

$TipBranch = 'cursor/st51-docs-ux-on-tip-3497'
$TipFile = Join-Path $Root 'TIP_BRANCH'
if (Test-Path $TipFile) {
  $TipBranch = (Get-Content $TipFile -Raw).Trim()
}
$Port = 18432
$Url = "http://localhost:${Port}/#pulse"

function Write-Banner {
  Write-Host ''
  Write-Host '============================================'
  Write-Host ' Stock Terminal v5.0  - tip UX (PowerShell)'
  Write-Host " $Url"
  Write-Host '============================================'
  Write-Host " repo: $Root"
  Write-Host " tip:  $TipBranch"
}

function Test-BlockedPython([string]$ExePath) {
  if (-not $ExePath) { return $true }
  $low = $ExePath.ToLowerInvariant()
  # Hermes / Cursor agent / random venv — these steal "python" on PATH and
  # produce the blank console the user reported.
  return ($low -match 'hermes' -or
          $low -match '\\hermes-agent\\' -or
          $low -match 'cursor.*agent' -or
          $low -match '\\antigravity\\' -or
          $low -match '\\miniconda\\envs\\' -or
          $low -match '\\anaconda\\envs\\')
}

function Resolve-StockPython {
  Write-Host '[python] resolve interpreter (block hermes/agent venv)'
  $candidates = New-Object System.Collections.Generic.List[string]

  # 1) Official Windows py launcher → real install, not Hermes
  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCmd) {
    try {
      $exe = (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
      if ($exe) { [void]$candidates.Add($exe.Trim()) }
    } catch {}
  }

  # 2) where.exe all pythons on PATH (may include hermes — filtered later)
  try {
    $whereOut = & where.exe python 2>$null
    foreach ($line in $whereOut) {
      if ($line -and (Test-Path $line)) { [void]$candidates.Add($line.Trim()) }
    }
  } catch {}
  foreach ($name in @('python', 'python3')) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { [void]$candidates.Add($cmd.Source) }
  }

  # 3) Common python.org locations
  foreach ($ver in @('314', '313', '312', '311', '310', '39')) {
    [void]$candidates.Add("$env:LOCALAPPDATA\Programs\Python\Python$ver\python.exe")
    [void]$candidates.Add("${env:ProgramFiles}\Python$ver\python.exe")
    [void]$candidates.Add("C:\Python$ver\python.exe")
  }

  $seen = @{}
  foreach ($c in $candidates) {
    if (-not $c) { continue }
    $full = $c
    try { $full = [System.IO.Path]::GetFullPath($c) } catch {}
    $key = $full.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { continue }
    $seen[$key] = $true
    if (-not (Test-Path -LiteralPath $full)) { continue }
    if (Test-BlockedPython $full) {
      Write-Host "       SKIP blocked: $full"
      continue
    }
    try {
      $ver = (& $full -c "import sys; print('%d.%d'%sys.version_info[:2])" 2>$null | Select-Object -First 1)
      if (-not $ver) { continue }
      # Prefer 3.x
      if ($ver -notmatch '^3\.') {
        Write-Host "       SKIP non-3.x ($ver): $full"
        continue
      }
      Write-Host "       OK python $ver -> $full"
      return $full
    } catch {
      Write-Host "       SKIP broken: $full"
    }
  }

  throw @"
No suitable Python 3 found.

Blocked (do NOT use): Hermes / agent venv, e.g.
  C:\Users\...\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe

Install from https://www.python.org/downloads/ and tick 'Add python.exe to PATH',
or ensure ``py -3`` works. Then re-run this script.
"@
}

function Assert-TipBranch {
  $cur = (git branch --show-current 2>$null)
  Write-Host " branch: $cur"
  $legacy = @('main', 'master', 'cursor/http-client-pool-3497', 'cursor/range-period-change-b5cf')
  if ($legacy -contains $cur) {
    throw "BLOCK: current branch '$cur' is legacy. Run: powershell -File .\scripts\go.ps1 -Pull"
  }
}

function Stop-PortListeners([int]$PortNum) {
  Write-Host "[stop] free port $PortNum (+ kill stray hermes python on that port)"
  $pids = New-Object System.Collections.Generic.HashSet[int]

  try {
    Get-NetTCPConnection -LocalPort $PortNum -State Listen -ErrorAction SilentlyContinue |
      ForEach-Object { [void]$pids.Add([int]$_.OwningProcess) }
  } catch {}

  $lines = netstat -ano 2>$null | Select-String ":$PortNum\s+.*LISTENING"
  foreach ($ln in $lines) {
    $parts = ($ln.ToString() -split '\s+') | Where-Object { $_ -ne '' }
    $procId = $parts[-1]
    if ($procId -match '^\d+$') { [void]$pids.Add([int]$procId) }
  }

  foreach ($procId in $pids) {
    if ($procId -le 4) { continue }
    $path = $null
    try { $path = (Get-Process -Id $procId -ErrorAction SilentlyContinue).Path } catch {}
    Write-Host "       kill PID $procId  path=$path"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  }

  # Also stop obvious Hermes python processes that may respawn / confuse the user
  try {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.ExecutablePath -and (Test-BlockedPython $_.ExecutablePath) } |
      ForEach-Object {
        Write-Host "       kill hermes/agent python PID $($_.ProcessId)  $($_.ExecutablePath)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
      }
  } catch {}

  Start-Sleep -Seconds 1
}

function Assert-TipHtml {
  $html = Join-Path $Root 'stock_terminal_v2.html'
  if (-not (Test-Path $html)) { throw "missing $html — run build_v2.py" }
  $txt = Get-Content $html -Raw -Encoding UTF8
  foreach ($need in @('shell_v5.js', 'pulse_v5.js', 'st5-tip-boot')) {
    if ($txt -notmatch [regex]::Escape($need)) {
      throw "HTML is NOT tip UX (missing $need). Stay on tip and rebuild."
    }
  }
  Write-Host '[ok] HTML contains shell_v5 + pulse_v5 + st5-tip-boot'

  $pulse = Join-Path $Root 'src\ui\pulse_v5.js'
  if (-not (Test-Path $pulse)) { throw "missing $pulse" }
  $pjs = Get-Content $pulse -Raw -Encoding UTF8
  if ($pjs -match '4col-priority') {
    throw "pulse_v5.js still has 4-col layout — reset tip branch and rebuild"
  }
  if ($pjs -notmatch '5col-2zone' -or $pjs -notmatch 'repeat\(5,minmax\(0,1fr\)\)') {
    throw "pulse_v5.js missing 5-col×2-zone layout markers"
  }
  if ($pjs -notmatch 'PULSE_LAYOUT_ANCHOR_3cab212') {
    throw "pulse_v5.js missing PULSE_LAYOUT_ANCHOR_3cab212 — wrong/old tree"
  }
  Write-Host '[ok] pulse layout = 一行五框 × 上下兩區 (5col-2zone + ANCHOR_3cab212)'
}

function Wait-TipServer {
  Write-Host '[wait] tip server health'
  for ($i = 1; $i -le 30; $i++) {
    try {
      $h = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
      $j = $h.Content | ConvertFrom-Json
      if ($j.tipUx -eq $true -or $j.ux -eq 'tip') {
        Write-Host "[ok] /health tipUx=true (try $i) version=$($j.version)"
        return
      }
      Write-Host "[warn] /health up but tipUx missing (try $i) — wrong server?"
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  throw "Server on :$Port is not tip UX. Check the 'Stock Terminal Server' console window for traceback."
}

function Assert-IndexIsTip {
  $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5
  $hdr = $resp.Headers['X-Stock-Terminal-UX']
  if ($hdr -ne 'tip') {
    Write-Host "[warn] X-Stock-Terminal-UX=$hdr (expected tip)"
  }
  $body = $resp.Content
  if ($body -notmatch 'shell_v5\.js' -or $body -notmatch 'pulse_v5\.js') {
    throw 'GET / did not return tip HTML modules — still serving OLD tree'
  }
  if ($body -notmatch 'st5-tip-boot') {
    throw 'GET / missing st5-tip-boot — still serving OLD HTML'
  }
  Write-Host '[ok] GET / is tip UX HTML'

  $pjs = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/src/ui/pulse_v5.js" -UseBasicParsing -TimeoutSec 5
  $ptxt = $pjs.Content
  if ($ptxt -match '4col-priority') {
    throw 'Server is still serving 4-col pulse_v5.js — kill ALL python on :18432 and retry'
  }
  if ($ptxt -notmatch '5col-2zone' -or $ptxt -notmatch 'repeat\(5,minmax\(0,1fr\)\)') {
    throw 'Server pulse_v5.js is not 5-col×2-zone — wrong tree / stale process'
  }
  if ($ptxt -notmatch 'PULSE_LAYOUT_ANCHOR_3cab212') {
    throw 'Server pulse_v5.js missing PULSE_LAYOUT_ANCHOR_3cab212 — STALE process. Kill listeners and retry.'
  }
  Write-Host '[ok] GET /src/ui/pulse_v5.js is 5col-2zone + ANCHOR_3cab212'
}

function Assert-ListenerNotBlocked {
  Write-Host '[check] listening process is not hermes/agent python'
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
      $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
      $path = $null
      if ($proc) { $path = $proc.Path }
      Write-Host "       listen PID $($c.OwningProcess) path=$path"
      if ($path -and (Test-BlockedPython $path)) {
        throw "Port $Port is still held by blocked python: $path"
      }
    }
  } catch {
    if ("$_" -match 'blocked python') { throw }
    # Get-NetTCPConnection may be unavailable — non-fatal
  }
}

Write-Banner

$Python = Resolve-StockPython
Write-Host " PYTHON: $Python"

if ($Pull) {
  Write-Host "[pull] fetch + FORCE reset $TipBranch (discard local HTML drift)"
  Write-Host "       NOTE: local edits to stock_terminal*.html will be discarded"
  git fetch origin $TipBranch
  if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
  # -f：避免「local changes would be overwritten」後腳本卻繼續用舊 HEAD（災難根因）
  git checkout -f -B $TipBranch "origin/$TipBranch"
  if ($LASTEXITCODE -ne 0) { throw "git checkout -f failed — refuse to continue on stale HEAD" }
  git reset --hard "origin/$TipBranch"
  if ($LASTEXITCODE -ne 0) { throw "git reset --hard failed" }
  $expect = (git rev-parse "origin/$TipBranch").Trim()
  $got = (git rev-parse HEAD).Trim()
  if ($got -ne $expect) {
    throw "pull incomplete: HEAD=$got expected=$expect — aborting (will NOT start old server)"
  }
  Write-Host "       synced HEAD=$($got.Substring(0,7))"
}

Assert-TipBranch
$head = (git rev-parse --short HEAD)
Write-Host " HEAD: $head"
if ($Pull) {
  # 舊 go.ps1 特徵：沒有 Resolve-StockPython。若仍看到 RedirectStandardOutput 啟動＝拉碼失敗。
  $self = Get-Content -LiteralPath $PSCommandPath -Raw -Encoding UTF8
  if ($self -notmatch 'Resolve-StockPython' -or $self -match 'RedirectStandardOutput') {
    throw "This go.ps1 is STALE (pre-hermes-fix). Delete scripts\\go.ps1 cache and re-run START_TIP.cmd"
  }
}

Write-Host "[build] `"$Python`" build_v2.py"
& $Python build_v2.py
if ($LASTEXITCODE -ne 0) { throw "build_v2.py failed (exit $LASTEXITCODE)" }
Assert-TipHtml

if ($RebuildOnly) {
  Write-Host '[done] rebuild only'
  exit 0
}

Stop-PortListeners -PortNum $Port

# Live console (NOT RedirectStandardOutput) so the window shows server logs.
# Title is set via cmd so user never sees a blank hermes python window.
$logDir = Join-Path $Root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logOut = Join-Path $logDir 'server_go_ps.out.log'
$logErr = Join-Path $logDir 'server_go_ps.err.log'

Write-Host "[start] Stock Terminal Server via:"
Write-Host "        $Python"
Write-Host "        cwd=$Root"
Write-Host "        logs: $logOut / $logErr"

# Write a tiny launcher .cmd so quoting is reliable and the window shows live logs
# (/k keeps console open on crash — no more blank hermes window with zero status).
$launcher = Join-Path $logDir 'run_server_tip.cmd'
@(
  '@echo off'
  'chcp 65001 >nul'
  'title Stock Terminal Server v5 tip'
  "cd /d `"$Root`""
  "echo ============================================"
  "echo  Stock Terminal Server v5 tip"
  "echo  HEAD=$head"
  "echo  PYTHON=$Python"
  "echo  cwd=$Root"
  "echo  url=$Url"
  "echo ============================================"
  "echo."
  "`"$Python`" -u server\server.py"
  'echo.'
  'echo SERVER EXITED — window stays open so you can read the error.'
  'pause'
) | Set-Content -Path $launcher -Encoding ASCII

$p = Start-Process -FilePath $launcher `
  -WorkingDirectory $Root `
  -WindowStyle Normal `
  -PassThru
Write-Host "       launcher PID $($p.Id)"
Write-Host "       window title MUST be: Stock Terminal Server v5 tip"
Write-Host "       launcher script: $launcher"

Wait-TipServer
Assert-IndexIsTip
Assert-ListenerNotBlocked

Write-Host "[open] $Url"
Start-Process $Url

Write-Host ''
Write-Host 'DONE. In browser (必看):'
Write-Host "  HEAD=$head"
Write-Host "  PYTHON=$Python"
Write-Host '  Server window title MUST be: Stock Terminal Server v5 tip'
Write-Host '  If you see hermes-agent\venv\...\python.exe = WRONG (script bug / old script)'
Write-Host '  1) Close ALL localhost:18432 tabs'
Write-Host '  2) Ctrl+F5'
Write-Host '  3) Title badge must show: 實測 5+5'
Write-Host '  4) F12: PULSE_LAYOUT_ANCHOR_3cab212 ... ok=true'
Write-Host ''

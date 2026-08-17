# Stock Terminal v5.0 — tip UX + WaveDeck integrate (PowerShell)
# Usage (from repo root):
#   DOUBLE-CLICK:  START_TIP.cmd
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 -UpdateOnly
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 -RebuildOnly
#
# Discipline: NEVER launch with bare PATH "python". Always resolve an absolute
# interpreter, pin it to data\stock_python.path, and reuse the pin. Tooling
# venvs (Hermes/agent) are deprioritized — not banned as a product policy.
param(
  # Backward-compatible safe update+run. Prefer -UpdateOnly, then launch.
  [switch]$Pull,
  [switch]$UpdateOnly,
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

function Test-ToolingPython([string]$ExePath) {
  # Soft ranking only — not a ban. Prefer system / python.org installs.
  if (-not $ExePath) { return $true }
  $low = $ExePath.ToLowerInvariant()
  return ($low -match 'hermes' -or
          $low -match '\\hermes-agent\\' -or
          $low -match 'cursor.*agent' -or
          $low -match '\\antigravity\\' -or
          $low -match '\\miniconda\\envs\\' -or
          $low -match '\\anaconda\\envs\\')
}

function Save-StockPythonPin([string]$ExePath) {
  $pinDir = Join-Path $Root 'data'
  if (-not (Test-Path $pinDir)) { New-Item -ItemType Directory -Path $pinDir | Out-Null }
  $pin = Join-Path $pinDir 'stock_python.path'
  Set-Content -LiteralPath $pin -Value $ExePath -Encoding ASCII
  Write-Host "[python] pinned -> $pin"
}

function Read-StockPythonPin {
  $pin = Join-Path $Root 'data\stock_python.path'
  if (-not (Test-Path -LiteralPath $pin)) { return $null }
  $p = (Get-Content -LiteralPath $pin -Raw).Trim()
  if ($p -and (Test-Path -LiteralPath $p)) { return $p }
  return $null
}

function Test-PythonUsable([string]$ExePath) {
  try {
    $ver = (& $ExePath -c "import sys; print('%d.%d'%sys.version_info[:2])" 2>$null | Select-Object -First 1)
    if (-not $ver) { return $false }
    if ($ver -notmatch '^3\.') { return $false }
    return $true
  } catch { return $false }
}

function Resolve-StockPython {
  Write-Host '[python] resolve absolute Stock Python (pin; deprioritize tooling venvs)'

  # 0) Explicit override
  if ($env:ST_PYTHON -and (Test-Path -LiteralPath $env:ST_PYTHON)) {
    if (Test-PythonUsable $env:ST_PYTHON) {
      Write-Host "       OK ST_PYTHON -> $($env:ST_PYTHON)"
      Save-StockPythonPin $env:ST_PYTHON
      return $env:ST_PYTHON
    }
  }

  # 1) Reuse previous pin (stable across PATH churn)
  $pinned = Read-StockPythonPin
  if ($pinned -and -not (Test-ToolingPython $pinned) -and (Test-PythonUsable $pinned)) {
    Write-Host "       OK pin -> $pinned"
    return $pinned
  }

  $preferred = New-Object System.Collections.Generic.List[string]
  $fallback = New-Object System.Collections.Generic.List[string]

  # 2) py -3 (Windows launcher → usually python.org)
  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCmd) {
    try {
      $exe = (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
      if ($exe) { [void]$preferred.Add($exe.Trim()) }
    } catch {}
  }

  # 3) Known python.org locations (high priority)
  foreach ($ver in @('314', '313', '312', '311', '310', '39')) {
    [void]$preferred.Add("$env:LOCALAPPDATA\Programs\Python\Python$ver\python.exe")
    [void]$preferred.Add("${env:ProgramFiles}\Python$ver\python.exe")
    [void]$preferred.Add("C:\Python$ver\python.exe")
  }

  # 4) PATH entries last (may include tooling) — split by ranking
  try {
    $whereOut = & where.exe python 2>$null
    foreach ($line in $whereOut) {
      if ($line -and (Test-Path $line)) {
        if (Test-ToolingPython $line) { [void]$fallback.Add($line.Trim()) }
        else { [void]$preferred.Add($line.Trim()) }
      }
    }
  } catch {}

  $seen = @{}
  foreach ($c in ($preferred + $fallback)) {
    if (-not $c) { continue }
    $full = $c
    try { $full = [System.IO.Path]::GetFullPath($c) } catch {}
    $key = $full.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { continue }
    $seen[$key] = $true
    if (-not (Test-Path -LiteralPath $full)) { continue }
    $tooling = Test-ToolingPython $full
    if ($tooling -and -not $env:ST_ALLOW_TOOLING_PYTHON) {
      Write-Host "       defer tooling python: $full"
      continue
    }
    if (-not (Test-PythonUsable $full)) {
      Write-Host "       SKIP unusable: $full"
      continue
    }
    Write-Host "       OK -> $full"
    Save-StockPythonPin $full
    return $full
  }

  # Last resort: allow tooling only if explicitly opted in, else clear error
  foreach ($c in $fallback) {
    if ($c -and (Test-Path $c) -and (Test-PythonUsable $c)) {
      if ($env:ST_ALLOW_TOOLING_PYTHON) {
        Write-Host "       OK tooling (ST_ALLOW_TOOLING_PYTHON) -> $c"
        Save-StockPythonPin $c
        return $c
      }
    }
  }

  throw @"
No usable Python 3 absolute path found.

Fix (pick one):
  1) Install https://www.python.org/downloads/ and ensure ``py -3`` works
  2) Set env ST_PYTHON to your python.exe absolute path, then re-run
  3) Emergency only: `$env:ST_ALLOW_TOOLING_PYTHON=1` then re-run

Root cause of past blank windows: scripts called bare ``python`` on PATH.
This launcher pins an absolute path under data\stock_python.path instead.
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
  # Only free OUR port — never taskkill every python.exe on the machine.
  Write-Host "[stop] free port $PortNum (listeners only)"
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
    throw 'Server is still serving 4-col pulse_v5.js — free :18432 listener and retry'
  }
  if ($ptxt -notmatch '5col-2zone' -or $ptxt -notmatch 'repeat\(5,minmax\(0,1fr\)\)') {
    throw 'Server pulse_v5.js is not 5-col×2-zone — wrong tree / stale process'
  }
  if ($ptxt -notmatch 'PULSE_LAYOUT_ANCHOR_3cab212') {
    throw 'Server pulse_v5.js missing PULSE_LAYOUT_ANCHOR_3cab212 — STALE process. Kill listeners and retry.'
  }
  Write-Host '[ok] GET /src/ui/pulse_v5.js is 5col-2zone + ANCHOR_3cab212'
}

function Assert-ListenerMatchesPin {
  Write-Host '[check] :18432 listener uses pinned Stock Python (warn only if tooling)'
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
      $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
      $path = $null
      if ($proc) { $path = $proc.Path }
      Write-Host "       listen PID $($c.OwningProcess) path=$path"
      if ($path -and (Test-ToolingPython $path)) {
        Write-Host "       WARN listener is tooling python — launcher should have pinned Stock Python"
      }
    }
  } catch {
    # Get-NetTCPConnection may be unavailable — non-fatal
  }
}

Write-Banner

if ($Pull -or $UpdateOnly) {
  Write-Host "[update] fetch + fast-forward only: $TipBranch"
  $dirty = @(git status --porcelain 2>$null)
  if ($LASTEXITCODE -ne 0) { throw "git status failed" }
  if ($dirty.Count -gt 0) {
    git status --short
    throw "BLOCK: worktree is dirty. Commit or preserve changes explicitly; updater will not stash, force, reset, or discard them."
  }
  git fetch origin $TipBranch
  if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
  $cur = (git branch --show-current 2>$null).Trim()
  if ($cur -ne $TipBranch) {
    git show-ref --verify --quiet "refs/heads/$TipBranch"
    $localExists = ($LASTEXITCODE -eq 0)
    if ($localExists) {
      git switch $TipBranch
    } else {
      git switch --create $TipBranch --track "origin/$TipBranch"
    }
    if ($LASTEXITCODE -ne 0) { throw "git switch failed; no files were forced or reset" }
  }
  git merge --ff-only "origin/$TipBranch"
  if ($LASTEXITCODE -ne 0) { throw "fast-forward failed; updater left local work untouched" }
  $expect = (git rev-parse "origin/$TipBranch").Trim()
  $got = (git rev-parse HEAD).Trim()
  if ($got -ne $expect) {
    throw "update incomplete: HEAD=$got expected=$expect"
  }
  Write-Host "       synced HEAD=$($got.Substring(0,7))"
  if ($UpdateOnly) {
    Write-Host "[OK] update complete. Re-run START_TIP.cmd to build and launch."
    exit 0
  }
}

$Python = Resolve-StockPython
Write-Host " PYTHON: $Python"

Assert-TipBranch
$head = (git rev-parse --short HEAD)
Write-Host " HEAD: $head"
if ($Pull) {
  # 舊 go.ps1 特徵：沒有 Resolve-StockPython。若仍看到 RedirectStandardOutput 啟動＝拉碼失敗。
  $self = Get-Content -LiteralPath $PSCommandPath -Raw -Encoding UTF8
  if ($self -notmatch 'Resolve-StockPython' -or $self -match 'RedirectStandardOutput') {
    throw "This go.ps1 is STALE (pre pin-python fix). Re-pull tip and re-run START_TIP.cmd"
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

# Live console (NOT RedirectStandardOutput) — absolute PYTHON from pin.
$logDir = Join-Path $Root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logOut = Join-Path $logDir 'server_go_ps.out.log'
$logErr = Join-Path $logDir 'server_go_ps.err.log'

Write-Host "[start] Stock Terminal Server via pinned absolute python:"
Write-Host "        $Python"
Write-Host "        cwd=$Root"
Write-Host "        logs: $logOut / $logErr"

$launcher = Join-Path $logDir 'run_server_tip.cmd'
@(
  '@echo off'
  'chcp 65001 >nul'
  'title Stock Terminal Server v5 tip'
  "cd /d `"$Root`""
  'set ST_LAUNCHED_BY=go.ps1'
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
Assert-ListenerMatchesPin

Write-Host "[open] $Url"
Start-Process $Url

Write-Host ''
Write-Host 'DONE.'
Write-Host "  HEAD=$head"
Write-Host "  PYTHON=$Python  (pinned in data\stock_python.path)"
Write-Host '  Server window title: Stock Terminal Server v5 tip'
Write-Host '  Browser: Ctrl+F5 → badge 實測 5+5'
Write-Host ''

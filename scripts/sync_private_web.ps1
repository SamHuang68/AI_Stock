# Stock Terminal — sync both faces (local START_TIP + Tailscale Private Web).
# Usage from repo root:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_private_web.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_private_web.ps1 -Promote -LayoutVerified
#
# Stage never copies a dirty worktree. Promote requires -LayoutVerified after
# both http://localhost:18432/#pulse and the Tailscale URL show the same layout.
param(
  [switch]$Promote,
  [switch]$LayoutVerified
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root 'build_v2.py'))) {
  throw 'sync_private_web.ps1 must run from the AI_Stock repository (build_v2.py missing)'
}
Set-Location $Root

$TipBranch = 'cursor/st-wd-tip-integrate-3497'
$TipFile = Join-Path $Root 'TIP_BRANCH'
if (Test-Path $TipFile) {
  $TipBranch = (Get-Content $TipFile -Raw).Trim()
}
$LocalUrl = 'http://localhost:18432/#pulse'
$TailscaleUrl = 'https://evo-t1-st.tailbc3519.ts.net/#pulse'

function Get-StockPython {
  if ($env:ST_PYTHON -and (Test-Path -LiteralPath $env:ST_PYTHON)) { return $env:ST_PYTHON }
  $pin = Join-Path $Root 'data\stock_python.path'
  if (Test-Path -LiteralPath $pin) {
    $p = (Get-Content -LiteralPath $pin -Raw).Trim()
    if ($p -and (Test-Path -LiteralPath $p)) { return $p }
  }
  $fromPy = & py -3 -c 'import sys; print(sys.executable)' 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $fromPy) {
    throw 'Stock Python not found. Run START_TIP.cmd once to pin data\stock_python.path'
  }
  return $fromPy.Trim()
}

function Invoke-StockPy {
  param([Parameter(Mandatory)][string[]]$PyArgs)
  $logs = Join-Path $Root 'logs'
  if (-not (Test-Path $logs)) {
    New-Item -ItemType Directory -Path $logs | Out-Null
  }
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $stdoutPath = Join-Path $logs "sync_private_web-$stamp.out.log"
  $stderrPath = Join-Path $logs "sync_private_web-$stamp.err.log"
  # PS 5.1 turns native stderr into a terminating NativeCommandError when
  # ErrorActionPreference=Stop. Release tests print expected [FAIL] lines to
  # stderr while a live Tailscale gateway is on :18434; that must not abort stage.
  $proc = Start-Process -FilePath $script:Py -ArgumentList $PyArgs -WorkingDirectory $Root -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
  $text = ''
  if (Test-Path -LiteralPath $stdoutPath) { $text += [IO.File]::ReadAllText($stdoutPath) }
  if (Test-Path -LiteralPath $stderrPath) { $text += [IO.File]::ReadAllText($stderrPath) }
  if ($text) { Write-Host $text }
  return [pscustomobject]@{ ExitCode = $proc.ExitCode; Text = $text }
}

Write-Host ''
Write-Host '============================================'
Write-Host ' ST two faces: local + Private Web'
Write-Host " local:     $LocalUrl"
Write-Host " tailscale: $TailscaleUrl"
Write-Host " tip:       $TipBranch"
Write-Host '============================================'

git fetch origin $TipBranch
if ($LASTEXITCODE -ne 0) { throw "git fetch origin $TipBranch failed" }

$originTip = (git rev-parse --short=12 "origin/$TipBranch").Trim()
$localHead = (git rev-parse --short=12 HEAD).Trim()
Write-Host "[git] local HEAD=$localHead  origin/$TipBranch=$originTip"

$script:Py = Get-StockPython
Write-Host "[python] $script:Py"

$status = Invoke-StockPy @('scripts\private_web_release.py', 'status')
if ($status.ExitCode -ne 0) { throw 'private_web_release.py status failed' }

Write-Host "[stage] exact commit origin/$TipBranch ($originTip)"
$stage = Invoke-StockPy @('scripts\private_web_release.py', 'stage', '--ref', "origin/$TipBranch")
if ($stage.ExitCode -ne 0) {
  if ($stage.Text -match 'release already staged') {
    Write-Host '[stage] already staged; continue'
  } else {
    throw 'private_web_release.py stage failed'
  }
}

if (-not $Promote) {
  Write-Host ''
  Write-Host 'Staged. Next:'
  Write-Host "  1. Open $LocalUrl  (START_TIP.cmd) and check layout"
  Write-Host "  2. After promote+restart, open $TailscaleUrl and check the same layout"
  Write-Host '  3. Only then:'
  Write-Host '     powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_private_web.ps1 -Promote -LayoutVerified'
  Write-Host ''
  exit 0
}

if (-not $LayoutVerified) {
  throw 'Refuse to promote: check BOTH faces first, then pass -LayoutVerified'
}

Write-Host "[promote] $originTip --approve"
$promote = Invoke-StockPy @('scripts\private_web_release.py', 'promote', '--release', $originTip, '--approve')
if ($promote.ExitCode -ne 0) { throw 'private_web_release.py promote failed' }

Write-Host ''
Write-Host 'Promoted. Restart isolated host so Tailscale serves the new tree:'
Write-Host '  .\STOP_PRIVATE_WEB.cmd'
Write-Host '  Set-Location "$env:LOCALAPPDATA\StockTerminalPrivateWeb\current"'
Write-Host '  .\START_PRIVATE_WEB_HOST.cmd'
Write-Host "Then hard-refresh $TailscaleUrl and confirm layout matches $LocalUrl"

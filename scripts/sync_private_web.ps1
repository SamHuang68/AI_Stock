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

$Py = Get-StockPython
Write-Host "[python] $Py"

& $Py 'scripts\private_web_release.py' 'status'
if ($LASTEXITCODE -ne 0) { throw 'private_web_release.py status failed' }

Write-Host "[stage] exact commit origin/$TipBranch ($originTip)"
$stageOut = & $Py 'scripts\private_web_release.py' 'stage' '--ref' "origin/$TipBranch" 2>&1
$stageText = ($stageOut | Out-String)
Write-Host $stageText
if ($LASTEXITCODE -ne 0) {
  if ($stageText -match 'release already staged') {
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
& $Py 'scripts\private_web_release.py' 'promote' '--release' $originTip '--approve'
if ($LASTEXITCODE -ne 0) { throw 'private_web_release.py promote failed' }

Write-Host ''
Write-Host 'Promoted. Restart isolated host so Tailscale serves the new tree:'
Write-Host '  .\STOP_PRIVATE_WEB.cmd'
Write-Host '  Set-Location "$env:LOCALAPPDATA\StockTerminalPrivateWeb\current"'
Write-Host '  .\START_PRIVATE_WEB_HOST.cmd'
Write-Host "Then hard-refresh $TailscaleUrl and confirm layout matches $LocalUrl"

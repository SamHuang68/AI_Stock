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
  $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N')
  $stdoutPath = Join-Path $logs "sync_private_web-$stamp.out.log"
  $stderrPath = Join-Path $logs "sync_private_web-$stamp.err.log"
  # PS 5.1 turns native stderr into a terminating NativeCommandError when
  # ErrorActionPreference=Stop. Release tests print expected [FAIL] lines to
  # stderr while a live Tailscale gateway is on :18434; that must not abort stage.
  $proc = Start-Process -FilePath $script:Py -ArgumentList $PyArgs -WorkingDirectory $Root -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
  $text = ''
  if (Test-Path -LiteralPath $stdoutPath) { $text += [IO.File]::ReadAllText($stdoutPath) }
  if (Test-Path -LiteralPath $stderrPath) { $text += [IO.File]::ReadAllText($stderrPath) }
  if ($text) { Write-Host $text }
  if ($null -eq $proc.ExitCode) { throw "無法取得發布程序結束碼；請檢查 $stdoutPath 與 $stderrPath" }
  Write-Host "[程序] $($PyArgs[1]) 結束碼=$($proc.ExitCode) 紀錄=$stdoutPath"
  return [pscustomobject]@{ ExitCode = $proc.ExitCode; Text = $text; Stdout = [IO.File]::ReadAllText($stdoutPath) }
}

. (Join-Path $PSScriptRoot 'private_web_runtime.ps1')

if ($Promote -and -not $LayoutVerified) {
  throw '拒絕發布：請先驗證兩個入口的版面，再傳入 -LayoutVerified'
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

$originCommit = (git rev-parse "origin/$TipBranch^{commit}").Trim()
if ($LASTEXITCODE -ne 0 -or $originCommit -notmatch '^[0-9a-f]{40}$') { throw '無法解析遠端 tip 的完整 SHA' }
$originTip = $originCommit.Substring(0, 12)
$localHead = (git rev-parse --short=12 HEAD).Trim()
Write-Host "[git] local HEAD=$localHead  origin/$TipBranch=$originTip"

$script:Py = Get-StockPython
Write-Host "[python] $script:Py"

$status = Invoke-StockPy @('scripts\private_web_release.py', 'status')
if ($status.ExitCode -ne 0) { throw 'private_web_release.py status failed' }

Write-Host "[stage] exact commit origin/$TipBranch ($originTip)"
$stage = Invoke-StockPy @('scripts\private_web_release.py', 'stage', '--ref', $originCommit)
if ($stage.ExitCode -ne 0) { throw '版本暫存失敗；尚未停止服務或變更 current' }

if (-not $Promote) {
  Write-Host ''
  Write-Host '版本已暫存；本次未指定 -Promote，因此尚未切換 current 或重啟服務。'
  Write-Host "  請先驗證 $LocalUrl 與 $TailscaleUrl 的版面，再執行："
  Write-Host '     powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync_private_web.ps1 -Promote -LayoutVerified'
  Write-Host ''
  exit 0
}

$releaseState = $status.Stdout | ConvertFrom-Json
$installRoot = $releaseState.installRoot
$current = Join-Path $installRoot 'current'
$syncLock = [IO.File]::Open((Join-Path $installRoot '.private-web-sync.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
try {
$previousManifest = $null
$activeManifestPath = Join-Path $current '.private_web_release.json'
if (Test-Path -LiteralPath $activeManifestPath) {
  $previousManifest = Get-Content -LiteralPath $activeManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
Assert-PrivateWebRevision -Url 'http://localhost:18432/health/live' -Commit $originCommit
Stop-PrivateWebRuntime -Current $current

Write-Host "[promote] $originTip --approve"
$promoted = $false
try {
  $promoteResult = Invoke-StockPy @('scripts\private_web_release.py', 'promote', '--release', $originTip, '--approve')
  if ($promoteResult.ExitCode -ne 0) { throw '版本切換失敗；發布器已嘗試還原原目錄' }
  $promoted = $true
  $manifest = Get-Content -LiteralPath (Join-Path $current '.private_web_release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($manifest.commit -ne $originCommit -or $manifest.tests -ne 'passed') { throw 'current 的 SHA 或測試狀態不符' }
  Start-PrivateWebRuntime -Current $current -Python $script:Py
  Assert-PrivateWebRevision -Url 'http://127.0.0.1:18435/health/live' -Commit $originCommit -Attempts 60
  $ownerToken = (Get-Content -LiteralPath (Join-Path $current 'data\private_web_owner.token') -Raw).Trim()
  $headers = @{ Authorization = 'Bearer ' + $ownerToken }
  Assert-PrivateWebRevision -Url ($TailscaleUrl.Split('#')[0].TrimEnd('/') + '/health/live') -Commit $originCommit -Headers $headers -Attempts 30
  Assert-PrivateWebRevision -Url 'http://localhost:18432/health/live' -Commit $originCommit
} catch {
  $publishFailure = $_.Exception.Message
  try {
    if (-not $promoted) {
      $recovery = Invoke-StockPy @('scripts\private_web_release.py', 'recover', '--approve')
      if ($recovery.ExitCode -ne 0) { throw '發布交易回復失敗，已保留目錄及紀錄' }
      if (Test-Path -LiteralPath $activeManifestPath) {
        $active = Get-Content -LiteralPath $activeManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $promoted = $active.promotionId -and ($active.promotionId -ne $previousManifest.promotionId)
      }
    }
    if ($promoted) {
      Stop-PrivateWebRuntime -Current $current
      if (-not $previousManifest) { throw '首次安裝啟動失敗，沒有可回復的前版；已停止新版並保留資料' }
      $rollback = Invoke-StockPy @('scripts\private_web_release.py', 'rollback', '--approve')
      if ($rollback.ExitCode -ne 0) { throw '前版目錄回復失敗' }
    }
    $restored = Get-Content -LiteralPath (Join-Path $current '.private_web_release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $restored.commit) { throw '無法確認回復版本' }
    Start-PrivateWebRuntime -Current $current -Python $script:Py
    Assert-PrivateWebRevision -Url 'http://127.0.0.1:18435/health/live' -Commit $restored.commit -Attempts 60
  } catch {
    throw "發布失敗：$publishFailure；自動回復尚未完成：$($_.Exception.Message)"
  }
  throw "發布未完成，已啟動回復版本 $($restored.commit)：$publishFailure"
}
Write-Host "[發布完成] current、localhost 與 Tailscale 程序 SHA 均為 $originCommit；請保留發布後版面驗證紀錄。"
} finally {
  $syncLock.Dispose()
}

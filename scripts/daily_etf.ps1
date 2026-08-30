[CmdletBinding()]
param(
  [string]$ProbeUrl = 'http://127.0.0.1:18435/etf-delta',
  [switch]$RequireApi
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $ScriptRoot '..'))
$PinPath = Join-Path $RepoRoot 'data\stock_python.path'

function Test-StockPython([string]$Candidate) {
  if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
  try {
    & $Candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 2)"
    return $LASTEXITCODE -eq 0
  } catch { return $false }
}

function Resolve-StockPython {
  if (Test-StockPython $env:ST_PYTHON) { return [IO.Path]::GetFullPath($env:ST_PYTHON) }
  if (Test-Path -LiteralPath $PinPath -PathType Leaf) {
    $Pinned = (Get-Content -LiteralPath $PinPath -Raw).Trim()
    if (Test-StockPython $Pinned) { return [IO.Path]::GetFullPath($Pinned) }
  }
  $Py = Get-Command py.exe -ErrorAction SilentlyContinue
  if (-not $Py) { $Py = Get-Command py -ErrorAction SilentlyContinue }
  if ($Py) {
    $Resolved = (& $Py.Source -3 -c "import sys; print(sys.executable)").Trim()
    if (Test-StockPython $Resolved) {
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $PinPath) | Out-Null
      Set-Content -LiteralPath $PinPath -Value ([IO.Path]::GetFullPath($Resolved)) -Encoding Ascii
      return [IO.Path]::GetFullPath($Resolved)
    }
  }
  throw 'No usable Stock Terminal Python found. Set ST_PYTHON or run scripts\go.ps1 once.'
}

$HistoryOverride = [string]$env:ST_ETF_HISTORY_DIR
if ($HistoryOverride -and -not [IO.Path]::IsPathRooted($HistoryOverride)) {
  throw 'ST_ETF_HISTORY_DIR must be absolute.'
}
$HistoryDir = if ($HistoryOverride) {
  [IO.Path]::GetFullPath($HistoryOverride)
} else {
  if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is required when ST_ETF_HISTORY_DIR is not set.' }
  Join-Path $env:LOCALAPPDATA 'StockTerminalPrivateWeb\shared-data\etf_history'
}
$env:ST_ETF_HISTORY_DIR = [IO.Path]::GetFullPath($HistoryDir)
$SharedRoot = Split-Path -Parent $env:ST_ETF_HISTORY_DIR
$LogDir = Join-Path $SharedRoot 'logs'
New-Item -ItemType Directory -Force -Path $env:ST_ETF_HISTORY_DIR, $LogDir | Out-Null

$Python = Resolve-StockPython
$DateTag = Get-Date -Format 'yyyy-MM-dd'
$LogPath = Join-Path $LogDir "etf_$DateTag.log"
$Tracker = Join-Path $RepoRoot 'server\etf_delta_tracker.py'
$Health = Join-Path $RepoRoot 'server\etf_snapshot_health.py'

"=== Run $(Get-Date -Format o) ===" | Add-Content -LiteralPath $LogPath -Encoding UTF8
"repo=$RepoRoot" | Add-Content -LiteralPath $LogPath -Encoding UTF8
"python=$Python" | Add-Content -LiteralPath $LogPath -Encoding UTF8
"history=$env:ST_ETF_HISTORY_DIR" | Add-Content -LiteralPath $LogPath -Encoding UTF8

& $Python $Tracker 2>&1 | Tee-Object -FilePath $LogPath -Append
$TrackerRc = $LASTEXITCODE
if ($TrackerRc -ne 0) {
  "=== Tracker exit $TrackerRc ===" | Add-Content -LiteralPath $LogPath -Encoding UTF8
  exit $TrackerRc
}

$HealthArgs = @($Health, '--probe-url', $ProbeUrl)
if ($RequireApi) { $HealthArgs += '--require-api' }
& $Python @HealthArgs 2>&1 | Tee-Object -FilePath $LogPath -Append
$HealthRc = $LASTEXITCODE
"=== Exit $HealthRc $(Get-Date -Format o) ===" | Add-Content -LiteralPath $LogPath -Encoding UTF8

Get-ChildItem -LiteralPath $LogDir -Filter 'etf_*.log' -File -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
  Remove-Item -Force -ErrorAction SilentlyContinue

exit $HealthRc

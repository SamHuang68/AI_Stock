# WaveDeck 本機診斷 — 在 wavedeck 目錄執行：
#   powershell -ExecutionPolicy Bypass -File .\CHECK_WAVEDECK.ps1
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
Write-Host ''
Write-Host '=== WaveDeck CHECK ===' -ForegroundColor Cyan
Write-Host "cwd : $PWD"
Write-Host "run.py exists : $(Test-Path .\run.py)"
Write-Host "server.py exists : $(Test-Path .\server\server.py)"

$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $py = 'py -3' }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = 'python' }
Write-Host "python : $py"
if (-not $py) { Write-Host '[ERR] 無 Python' -ForegroundColor Red; exit 1 }

Write-Host ''
Write-Host '--- import / boot smoke ---' -ForegroundColor Yellow
cmd /c "$py -c `"import run; print('import-ok')`""
Write-Host "exit=$LASTEXITCODE"

Write-Host ''
Write-Host '--- port 18433 ---' -ForegroundColor Yellow
try {
  $c = Get-NetTCPConnection -LocalPort 18433 -ErrorAction Stop | Select-Object -First 3
  $c | Format-Table -AutoSize
} catch {
  netstat -ano | Select-String ':18433'
}

Write-Host ''
Write-Host '--- GET /health ---' -ForegroundColor Yellow
try {
  $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:18433/health' -TimeoutSec 3
  Write-Host "status=$($r.StatusCode) body=$($r.Content)"
} catch {
  Write-Host "[ERR] $($_.Exception.Message)" -ForegroundColor Red
  Write-Host '伺服器可能沒起來。請執行: py -3 run.py  並看 Traceback'
}
Write-Host ''

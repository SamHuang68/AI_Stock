# 平日早晨簡報先執行本腳本；失敗以非零結束碼回報，已完成日期可安全重跑。
param([switch]$SeedResearch)

$ErrorActionPreference = 'Stop'
$StockRoot = Split-Path -Parent $PSScriptRoot
$StockPython = $env:ST_PYTHON
if (-not $StockPython) {
  $StockPin = Join-Path $StockRoot 'data\stock_python.path'
  if (-not (Test-Path -LiteralPath $StockPin -PathType Leaf)) { throw '找不到股票系統 Python 路徑，請先啟動 START_TIP.cmd。' }
  $StockPython = (Get-Content -LiteralPath $StockPin -Raw).Trim()
}
if (-not (Test-Path -LiteralPath $StockPython -PathType Leaf)) { throw '股票系統 Python 路徑不存在。' }
$StockArguments = @((Join-Path $StockRoot 'server\台股日線.py'), '--database', (Join-Path $StockRoot 'data\market.db'), '--include-private')
if ($SeedResearch) { $StockArguments += '--seed-research' }
& $StockPython @StockArguments
$StockExitCode = $LASTEXITCODE
if ($null -eq $StockExitCode) { throw '無法取得日線更新結束碼。' }
if ($StockExitCode -ne 0) { Write-Warning '日線更新未全部完成，請依輸出的失敗日期重試；不得把舊資料標為最新。' }
exit $StockExitCode

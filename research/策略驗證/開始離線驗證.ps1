param(
    [string]$標的 = '2330',
    [double]$買進基點 = 25,
    [double]$賣出基點 = 55,
    [string]$NodePath = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$python = (Get-Content -LiteralPath (Join-Path $root 'data\stock_python.path') -Raw).Trim()
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw '找不到 ST 指定的 Python，請先設定 Stock Terminal。' }
if (-not $NodePath) {
    $nodeCommand = Get-Command node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($nodeCommand) { $NodePath = $nodeCommand.Source }
    if (-not $NodePath) {
        $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
        if (Test-Path -LiteralPath $bundled -PathType Leaf) { $NodePath = $bundled }
    }
}
if (-not $NodePath -or -not (Test-Path -LiteralPath $NodePath -PathType Leaf)) {
    throw '需要本機 Node.js 核對既有回測核心；請以 -NodePath 指定執行檔。本程式不會自動下載。'
}
$output = Join-Path $root ('scratch\離線策略驗證-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $python -E -B -X utf8 (Join-Path $PSScriptRoot '離線驗證.py') --標的 $標的 --買進基點 $買進基點 --賣出基點 $賣出基點 --輸出 $output
if ($LASTEXITCODE -ne 0) { throw '離線研究失敗；已保留當次輸出供診斷。' }
& $NodePath (Join-Path $PSScriptRoot '核對既有核心.js') $output
if ($LASTEXITCODE -ne 0) { throw '既有核心核對失敗，不能宣稱驗證完成。' }
Write-Output ('離線研究與核心核對完成：' + (Join-Path $output '研究報告.html'))

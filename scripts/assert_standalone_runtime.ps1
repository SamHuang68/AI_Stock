param([Parameter(Mandatory = $true)][string]$CodeRoot)
$ErrorActionPreference = 'Stop'
$CodeRoot = [IO.Path]::GetFullPath($CodeRoot)
$bound = (Test-Path Env:ST_DATA_BINDING) -or (Test-Path Env:ST_DATA_ROOT) -or (Test-Path Env:ST_RUNTIME_ROLE)
$sidecar = Join-Path (Split-Path -Parent $CodeRoot) 'runtime_binding.json'
$bound = $bound -or (Test-Path -LiteralPath $sidecar)
$receipt = Join-Path $CodeRoot '.private_web_release.json'
if (Test-Path -LiteralPath $receipt -PathType Leaf) {
    $metadata = Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    if ($metadata -isnot [System.Management.Automation.PSCustomObject]) { throw '發布收據格式無效；未啟動獨立寫入程序。' }
    $storage = $metadata.PSObject.Properties['storageBinding']
    $bound = $bound -or ($null -ne $storage -and $storage.Value.storageMode -eq 'external')
}
if ($bound) {
    throw '綁定資料模式禁止獨立更新與寄信程序。請使用已登記 Stock Terminal 的更新中心；ETF 報表的既有入口為 POST /etf-report/email。本入口未建立資料、寄信或登記排程。'
}

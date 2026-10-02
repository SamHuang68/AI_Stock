param(
    [string]$InstallRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$ProductionRoot = (Join-Path $env:LOCALAPPDATA 'StockTerminalPrivateWeb\current'),
    [switch]$FunctionsOnly
)
$ErrorActionPreference = 'Stop'

function Test-PrivateWebIdentity($Process, [string]$Root, [string]$Script) {
    if (-not $Process -or $Process.Name -notmatch '^python(?:w|\d+(?:\.\d+)?)?\.exe$') { return $false }
    # 只接受獨立的絕對腳本參數；-c 字串、別的安裝目錄與相對路徑均不足以證明身分。
    $parts = @([regex]::Matches([string]$Process.CommandLine, '"[^"]*"|[^\s"]+') | ForEach-Object { $_.Value.Trim('"') })
    if ($parts.Count -lt 2) { return $false }
    $index = 1
    while ($index -lt $parts.Count -and $parts[$index] -in @('-u', '-B', '-E', '-s', '-S', '-I')) { $index++ }
    if ($index -ge $parts.Count) { return $false }
    $expected = [IO.Path]::GetFullPath((Join-Path $Root $Script))
    $candidate = $parts[$index].Replace('/', '\')
    if (-not [IO.Path]::IsPathRooted($candidate) -or
        [IO.Path]::GetPathRoot($candidate) -ne [IO.Path]::GetPathRoot($expected)) { return $false }
    # Windows 暫存目錄可能同時以 RUNNER~1 與完整名稱呈現，先核對實際檔案路徑。
    $actualFile = Get-Item -LiteralPath $candidate -ErrorAction SilentlyContinue
    $expectedFile = Get-Item -LiteralPath $expected -ErrorAction SilentlyContinue
    return $actualFile -and $expectedFile -and -not $actualFile.PSIsContainer -and
        [string]::Equals($actualFile.FullName, $expectedFile.FullName, [StringComparison]::OrdinalIgnoreCase)
}

function Get-PrivateWebTargets($Processes, [string[]]$Roots) {
    $targets = @{}
    foreach ($root in $Roots) {
        foreach ($hostProcess in $Processes) {
            if (-not (Test-PrivateWebIdentity $hostProcess $root 'scripts\private_web_host.py')) { continue }
            $targets[[int]$hostProcess.ProcessId] = $hostProcess
            foreach ($child in $Processes) {
                if ($child.ParentProcessId -eq $hostProcess.ProcessId -and
                    ((Test-PrivateWebIdentity $child $root 'server\server.py') -or
                     (Test-PrivateWebIdentity $child $root 'server\private_web_gateway.py'))) {
                    $targets[[int]$child.ProcessId] = $child
                }
            }
        }
        foreach ($gateway in $Processes) {
            if (Test-PrivateWebIdentity $gateway $root 'server\private_web_gateway.py') {
                $targets[[int]$gateway.ProcessId] = $gateway
            }
        }
    }
    # 先停止監督程序，防止子程序在關閉期間被重新啟動。
    return @($targets.Values | Sort-Object @{Expression={ if ($_.CommandLine -match 'private_web_host\.py') { 0 } else { 1 } }}, ProcessId)
}

if ($FunctionsOnly) { return }
$roots = @($InstallRoot, $ProductionRoot | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') } | Select-Object -Unique)
Write-Output '正在停止 Private Web ST；依安裝目錄與程序身分核對。'
$processes = @(Get-CimInstance Win32_Process)
$targets = @(Get-PrivateWebTargets $processes $roots)
$unverified = $false
foreach ($root in $roots) {
    foreach ($pidName in @('private_web_host.pid', 'private_web_gateway.pid')) {
        $pidPath = Join-Path $root ('data\' + $pidName)
        if (-not (Test-Path -LiteralPath $pidPath)) { continue }
        $value = 0
        if (-not [int]::TryParse((Get-Content -LiteralPath $pidPath -Raw).Trim(), [ref]$value)) {
            Write-Warning "PID 紀錄無法辨識，保留原檔：$pidPath"
            $unverified = $true
            continue
        }
        if (($processes | Where-Object ProcessId -eq $value) -and -not ($targets | Where-Object ProcessId -eq $value)) {
            Write-Warning "PID $value 不符合此安裝目錄的 Private Web 身分，未終止。"
            $unverified = $true
        }
    }
}
foreach ($target in $targets) {
    $live = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $target.ProcessId)
    if (-not $live) { continue }
    if ($live.CreationDate -ne $target.CreationDate -or $live.CommandLine -cne $target.CommandLine -or
        $live.ParentProcessId -ne $target.ParentProcessId) {
        Write-Warning "PID $($target.ProcessId) 身分已變更，未終止。"
        $unverified = $true
        continue
    }
    Stop-Process -Id $live.ProcessId -Force -ErrorAction Stop
}
if (@(Get-PrivateWebTargets @(Get-CimInstance Win32_Process) $roots).Count) {
    Write-Warning '仍有已辨識的 Private Web 程序，停止未完成。'
    $unverified = $true
}
if ($unverified) {
    Write-Warning '部分 PID 無法確認；已保留程序及紀錄，請核對原啟動方式。'
    exit 1
}
Write-Output 'Private Web ST 已停止；未依埠號掃除其他程序。'
exit 0

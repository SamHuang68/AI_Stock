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

function Test-PrivateWebScheduledTask($Task, [string]$Root) {
    if (-not $Task -or $Task.TaskName -ne 'StockTerminal_PrivateWeb_Host' -or $Task.TaskPath -ne '\' -or @($Task.Actions).Count -ne 1) { return $false }
    $action = $Task.Actions[0]
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if ($action.Execute -ine $shell -or -not [IO.Path]::IsPathRooted($action.WorkingDirectory)) { return $false }
    $working = Get-Item -LiteralPath $action.WorkingDirectory -ErrorAction SilentlyContinue
    $rootItem = Get-Item -LiteralPath $Root -ErrorAction SilentlyContinue
    if (-not $working -or -not $rootItem -or $working.FullName -ine $rootItem.FullName) { return $false }
    $parts = @([regex]::Matches([string]$action.Arguments, '"[^"]*"|[^\s"]+') | ForEach-Object { $_.Value.Trim('"') })
    $values = @{}
    for ($index = 0; $index -lt $parts.Count; $index++) {
        if ($parts[$index] -in @('-NoLogo', '-NoProfile', '-NonInteractive')) { continue }
        if ($parts[$index] -notin @('-File', '-Mode', '-InstallRoot', '-WindowStyle', '-ExecutionPolicy', '-BackendPort', '-GatewayPort')) { return $false }
        if ($values.ContainsKey($parts[$index]) -or $index + 1 -ge $parts.Count) { return $false }
        $values[$parts[$index]] = $parts[$index + 1]
        $index++
    }
    if (-not $values['-File'] -or -not $values['-InstallRoot'] -or $values['-Mode'] -ne 'RunHost' -or
        -not [IO.Path]::IsPathRooted($values['-File']) -or -not [IO.Path]::IsPathRooted($values['-InstallRoot'])) { return $false }
    $parent = Split-Path $rootItem.FullName -Parent
    $expectedRunner = Get-Item -LiteralPath (Join-Path $parent 'startup\private_web_startup.ps1') -ErrorAction SilentlyContinue
    $runner = Get-Item -LiteralPath $values['-File'] -ErrorAction SilentlyContinue
    $install = Get-Item -LiteralPath $values['-InstallRoot'] -ErrorAction SilentlyContinue
    return $expectedRunner -and $runner -and $install -and
        $expectedRunner.FullName -ieq $runner.FullName -and $install.FullName -ieq $parent
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
# 先停止經完整動作與目錄核對的既有排程，避免其失敗重啟策略再次拉起 host。
# 不停用或修改排程設定；下次使用者啟動或既有觸發條件仍可沿用。
$registeredTask = $null
try { $registeredTask = Get-ScheduledTask -TaskPath '\' -TaskName 'StockTerminal_PrivateWeb_Host' -ErrorAction Stop }
catch {
    if ($_.CategoryInfo.Category -ne 'ObjectNotFound') { throw '無法核對既有私有排程，未執行程序停止。' }
}
$taskOwned = $false
foreach ($root in $roots) {
    if (Test-PrivateWebScheduledTask $registeredTask $root) { $taskOwned = $true }
}
if ($taskOwned) {
    Stop-ScheduledTask -TaskPath '\' -TaskName $registeredTask.TaskName -ErrorAction Stop
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        if ([int](Get-ScheduledTask -TaskPath '\' -TaskName $registeredTask.TaskName).State -ne 4) { break }
        Start-Sleep -Milliseconds 100
    }
    if ($attempt -eq 50) { throw '私有排程尚未停止，未執行程序停止。' }
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
if ($taskOwned -and [int](Get-ScheduledTask -TaskPath '\' -TaskName $registeredTask.TaskName).State -eq 4) {
    Write-Warning '私有排程尚未停止，請核對排程狀態。'
    $unverified = $true
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

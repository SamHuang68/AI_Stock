param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'StockTerminalLocal'),
    [switch]$NoBrowser,
    [switch]$FunctionsOnly
)
$ErrorActionPreference = 'Stop'

function Test-SameLocalPath([string]$Left, [string]$Right) {
    if (-not $Left -or -not $Right) { return $false }
    return [string]::Equals([IO.Path]::GetFullPath($Left).TrimEnd('\'),
        [IO.Path]::GetFullPath($Right).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
}

function Get-LocalCreation($Process) {
    return ([datetime]$Process.CreationDate).ToUniversalTime().ToString('o')
}

function Test-NewLocalProcess($Started, $Observed) {
    if (-not $Started -or -not $Observed -or [int]$Started.Id -ne [int]$Observed.ProcessId) { return $false }
    # CIM 保留微秒；.NET 保留 100ns。只容許表示精度差異，不接受另一個建立時間。
    $startTicks = ([datetime]$Started.StartTime).ToUniversalTime().Ticks
    $observedTicks = ([datetime]$Observed.CreationDate).ToUniversalTime().Ticks
    return [Math]::Abs($startTicks - $observedTicks) -lt 10
}

function Test-ManagedLocalIdentity($Process, $Receipt, [string]$BaseDir, [string]$Python) {
    if (-not $Process -or -not $Receipt -or
        [int]$Process.ProcessId -ne [int]$Receipt.pid -or
        (Get-LocalCreation $Process) -cne [string]$Receipt.createdAt -or
        [string]$Process.CommandLine -cne [string]$Receipt.commandLine -or
        -not (Test-SameLocalPath $Receipt.baseDir $BaseDir) -or
        -not (Test-SameLocalPath $Process.ExecutablePath $Python)) { return $false }
    $parts = @([regex]::Matches([string]$Process.CommandLine, '"[^"]*"|[^\s"]+') | ForEach-Object { $_.Value.Trim('"') })
    return $parts.Count -eq 4 -and (Test-SameLocalPath $parts[0] $Python) -and
        $parts[1] -ceq '-B' -and $parts[2] -ceq '-u' -and
        (Test-SameLocalPath $parts[3] (Join-Path $BaseDir 'server\server.py'))
}

function Assert-LocalListeners($Listeners, $Process, $Receipt, [string]$BaseDir, [string]$Python) {
    foreach ($listener in @($Listeners)) {
        if (-not $listener) { continue }
        if ($listener.LocalAddress -ne '127.0.0.1' -or [int]$listener.LocalPort -ne 18432 -or
            [int]$listener.OwningProcess -ne [int]$Receipt.pid -or
            -not (Test-ManagedLocalIdentity $Process $Receipt $BaseDir $Python)) {
            throw '18432 的程序不是已登記的本機 ST；未停止程序或修改資料。'
        }
    }
}

function Test-LocalHealth($Health, [string]$BaseDir, [string]$Commit, [string]$Python) {
    return $Health -and $Health.status -eq 'ok' -and $Health.runtimeCommit -ceq $Commit -and
        $Health.bind -eq '127.0.0.1' -and [int]$Health.port -eq 18432 -and
        (Test-SameLocalPath $Health.baseDir $BaseDir) -and
        (Test-SameLocalPath $Health.pythonExe $Python)
}

function Invoke-LocalRelease([string]$Python, [string]$Root, [string]$Command) {
    $result = & $Python -B (Join-Path $Root 'local_release.py') --install-root $Root $Command
    if ($LASTEXITCODE -ne 0) { throw "本機版本 $Command 失敗；保留資料與版本收據。" }
    return (($result -join "`n") | ConvertFrom-Json)
}

function Write-LocalReceipt([string]$Path, $Value) {
    $temporary = $Path + '.tmp-' + [guid]::NewGuid().ToString('N')
    try {
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}

if ($FunctionsOnly) { return }
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$configPath = Join-Path $InstallRoot 'local_install.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw '尚未建立本機受管理安裝；請先用明確路徑執行 local_release.py setup。'
}
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$python = [string]$config.python
if (-not [IO.Path]::IsPathRooted($python) -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw '本機安裝沒有有效的絕對 Python 路徑。'
}
$baseDir = Join-Path $InstallRoot 'current'
$receiptPath = Join-Path $InstallRoot 'local_process.json'
$lockPath = Join-Path $InstallRoot '.launcher.lock'
$launchLock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$previousUtf8 = $env:PYTHONUTF8; $previousPythonEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $receipt = if (Test-Path -LiteralPath $receiptPath) { Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
    $owned = if ($receipt) { Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$receipt.pid) } else { $null }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 18432 -ErrorAction SilentlyContinue)
    Assert-LocalListeners $listeners $owned $receipt $baseDir $python
    if ($owned -and -not (Test-ManagedLocalIdentity $owned $receipt $baseDir $python)) {
        throw '登記 PID 的程序身分已改變；未停止程序或修改資料。'
    }
    $state = Invoke-LocalRelease $python $InstallRoot 'status'
    if ($state.needsSync -and $owned) {
        # 再核對一次 PID 建立時間、執行檔及完整命令列，避免 PID 重用。
        $again = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$receipt.pid)
        if (-not (Test-ManagedLocalIdentity $again $receipt $baseDir $python)) {
            throw '停止前程序身分改變；未執行停止。'
        }
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:18432/health' -TimeoutSec 20
        if (-not (Test-LocalHealth $health $baseDir $state.installedCommit $python)) {
            throw '既有程序版本或資料目錄無法核對；未執行停止。'
        }
        $again = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$receipt.pid)
        if (-not (Test-ManagedLocalIdentity $again $receipt $baseDir $python)) {
            throw '健康核對後程序身分改變；未執行停止。'
        }
        Stop-Process -Id ([int]$again.ProcessId) -Force -ErrorAction Stop
        Wait-Process -Id ([int]$again.ProcessId) -Timeout 15 -ErrorAction SilentlyContinue
        $owned = $null
    }
    if ($state.needsSync) {
        $sync = Invoke-LocalRelease $python $InstallRoot 'sync'
        Write-LocalReceipt (Join-Path $InstallRoot 'last_sync.json') $sync
        $state = Invoke-LocalRelease $python $InstallRoot 'status'
        if ($state.needsSync) { throw '正式版本已變更；請重新啟動以同步，未宣稱本機已更新。' }
    }
    if (-not $owned) {
        if (@(Get-NetTCPConnection -State Listen -LocalPort 18432 -ErrorAction SilentlyContinue).Count) {
            throw '啟動前 18432 已被其他程序使用；未終止任何程序。'
        }
        $logDir = Join-Path $InstallRoot 'logs'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        $stamp = [datetime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
        $previousHost = $env:ST_HOST; $previousPort = $env:ST_PORT; $previousLauncher = $env:ST_LAUNCHED_BY
        try {
            $env:ST_HOST = '127.0.0.1'; $env:ST_PORT = '18432'; $env:ST_LAUNCHED_BY = 'start_local.ps1'
            $serverFile = Join-Path $baseDir 'server\server.py'
            $started = Start-Process -FilePath $python -ArgumentList @('-B', '-u', ('"' + $serverFile + '"')) `
                -WorkingDirectory $baseDir -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $logDir ($stamp + '.out.log')) `
                -RedirectStandardError (Join-Path $logDir ($stamp + '.err.log'))
        } finally {
            $env:ST_HOST = $previousHost; $env:ST_PORT = $previousPort; $env:ST_LAUNCHED_BY = $previousLauncher
        }
        $owned = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $started.Id)
        if (-not (Test-NewLocalProcess $started $owned)) { throw '新程序已退出或建立時間不符；未登記或停止其他程序。' }
        $receipt = [pscustomobject]@{
            pid = [int]$owned.ProcessId; createdAt = (Get-LocalCreation $owned)
            commandLine = [string]$owned.CommandLine; baseDir = $baseDir
            executable = $python; commit = $state.installedCommit
        }
        if (-not (Test-ManagedLocalIdentity $owned $receipt $baseDir $python)) {
            throw '新程序身分不符合指定命令；未對未確認的程序發出停止。'
        }
        Write-LocalReceipt $receiptPath $receipt
    }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $currentProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$receipt.pid)
        if (-not (Test-ManagedLocalIdentity $currentProcess $receipt $baseDir $python)) {
            throw '本機 ST 已退出或程序身分改變；請查看啟動日誌。'
        }
        try {
            $live = Invoke-RestMethod -Uri 'http://127.0.0.1:18432/health/live' -TimeoutSec 1
            if ($live.ok -and $live.runtimeCommit -ceq $state.installedCommit -and $live.bind -eq '127.0.0.1' -and [int]$live.port -eq 18432) { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw '本機 ST 尚未通過啟動核對；請查看啟動日誌。' }
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:18432/health' -TimeoutSec 30
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 18432 -ErrorAction Stop)
    $owned = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$receipt.pid)
    Assert-LocalListeners $listeners $owned $receipt $baseDir $python
    if (-not $listeners.Count -or -not (Test-LocalHealth $health $baseDir $state.installedCommit $python)) {
        throw '本機 ST 的版本、資料目錄或埠核對失敗；未開啟瀏覽器。'
    }
    Write-Output ('本機 ST 已就緒：' + $state.installedCommit + '，127.0.0.1:18432')
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:18432/#pulse' }
} finally {
    $env:PYTHONUTF8 = $previousUtf8; $env:PYTHONIOENCODING = $previousPythonEncoding
    $launchLock.Dispose()
}

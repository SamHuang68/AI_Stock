param(
    [string]$WaveDeckRoot = $PSScriptRoot,
    [switch]$NoBrowser,
    [ValidateRange(1, 120)][int]$TimeoutSec = 30
)

function Get-WaveDeckPorts {
    param([string]$WaveDeckRoot)
    $ports = [Collections.Generic.List[int]]::new()
    $receipt = Join-Path $WaveDeckRoot 'data\wavedeck.port'
    if (Test-Path -LiteralPath $receipt -PathType Leaf) {
        $value = [IO.File]::ReadAllText($receipt, [Text.Encoding]::UTF8).Trim()
        $number = 0
        if ([int]::TryParse($value, [ref]$number) -and $number -ge 1 -and $number -le 65535 -and $number -notin @(18432, 18434, 18435)) {
            $ports.Add($number)
        } else {
            Write-Warning '忽略無效或保留埠的 WaveDeck 埠收據。'
        }
    }
    $preferred = 18433
    if ($env:WAVEDECK_PORT) {
        if (-not [int]::TryParse($env:WAVEDECK_PORT, [ref]$preferred) -or $preferred -lt 1 -or $preferred -gt 65535 -or $preferred -in @(18432, 18434, 18435)) {
            throw 'WAVEDECK_PORT 必須是有效埠，且不能使用 Stock Terminal／Private Web 保留埠。'
        }
    }
    foreach ($number in @($preferred, 18765, 28765, 38433, 8765)) {
        if (-not $ports.Contains($number)) { $ports.Add($number) }
    }
    return $ports.ToArray()
}

function Find-WaveDeckService {
    param([string]$WaveDeckRoot, [double]$TimeoutSec = 5)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    foreach ($port in @(Get-WaveDeckPorts -WaveDeckRoot $WaveDeckRoot)) {
        if ($watch.Elapsed.TotalSeconds -ge $TimeoutSec) { break }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 1 -ErrorAction Stop
        } catch {
            # 尚未啟動或未知服務的連線失敗屬預期探測結果；保留可開啟的診斷。
            Write-Verbose "WaveDeck 健康探測 $port 未成功：$($_.Exception.Message)"
            continue
        }
        if ($health.service -cne 'WaveDeck') { continue }
        if ($health.baseDir -isnot [string] -or -not $health.baseDir -or $null -eq $health.port) {
            throw "埠 $port 的舊 WaveDeck 缺少目錄身分；請在原 WaveDeck 視窗停止後，再使用本入口。未啟動另一份服務。"
        }
        try {
            $baseDir = [IO.Path]::GetFullPath($health.baseDir).TrimEnd('\', '/')
        } catch {
            throw "埠 $port 的 WaveDeck 目錄身分無效。"
        }
        $sameRoot = $baseDir -ieq $WaveDeckRoot.TrimEnd('\', '/')
        $numericPort = $health.port -is [int] -or $health.port -is [long]
        if ($sameRoot -and $health.ok -is [bool] -and $health.ok -and $numericPort -and $health.port -eq $port) {
            return $port
        }
    }
    return $null
}

function Resolve-WaveDeckPython {
    param([string]$WaveDeckRoot)
    $parent = Split-Path -Parent $WaveDeckRoot
    foreach ($project in @($parent, (Split-Path -Parent $parent))) {
        $pin = Join-Path $project 'data\stock_python.path'
        if (Test-Path -LiteralPath $pin -PathType Leaf) {
            $pythonExe = [IO.File]::ReadAllText($pin, [Text.Encoding]::UTF8).Trim()
            if (-not [IO.Path]::IsPathRooted($pythonExe) -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
                throw "釘選 Python 路徑無效：$pin；請先執行 Stock Terminal 的 START_TIP.cmd。"
            }
            return $pythonExe
        }
    }
    $launcher = Get-Command py.exe -ErrorAction Stop
    $pythonExe = (& $launcher.Source -3 -c 'import sys; print(sys.executable)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not [IO.Path]::IsPathRooted($pythonExe) -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw '找不到 Python；請先執行 START_TIP.cmd，或安裝 Python 3。'
    }
    return $pythonExe
}

function Open-WaveDeckBrowser {
    param([int]$Port)
    Start-Process -FilePath "http://127.0.0.1:$Port/" -ErrorAction Stop
}

function Invoke-WaveDeckLaunch {
    param([string]$WaveDeckRoot, [switch]$NoBrowser, [int]$TimeoutSec = 30)
    try {
        $WaveDeckRoot = (Resolve-Path -LiteralPath $WaveDeckRoot -ErrorAction Stop).ProviderPath.TrimEnd('\', '/')
        $runFile = Join-Path $WaveDeckRoot 'run.py'
        if (-not (Test-Path -LiteralPath $runFile -PathType Leaf)) { throw "找不到 WaveDeck 入口：$runFile" }
        if ($env:WAVEDECK_HOST -and $env:WAVEDECK_HOST -ne '127.0.0.1') { throw '此本機啟動器要求 WAVEDECK_HOST 為 127.0.0.1。' }
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $port = Find-WaveDeckService -WaveDeckRoot $WaveDeckRoot -TimeoutSec ([Math]::Min(5, $TimeoutSec))
        if ($null -eq $port) {
            if ($watch.Elapsed.TotalSeconds -ge $TimeoutSec) { throw '既有服務探測已用完等待期限，未啟動另一份程序。' }
            $pythonExe = Resolve-WaveDeckPython -WaveDeckRoot $WaveDeckRoot
            if ($watch.Elapsed.TotalSeconds -ge $TimeoutSec) { throw 'Python 路徑解析已用完等待期限，未啟動程序。' }
            $logs = Join-Path $WaveDeckRoot 'logs'
            New-Item -ItemType Directory -Path $logs -Force -ErrorAction Stop | Out-Null
            $logId = [Guid]::NewGuid().ToString('N')
            $stdout = Join-Path $logs "launcher-$logId-stdout.log"
            $stderr = Join-Path $logs "launcher-$logId-stderr.log"
            $process = Start-Process -FilePath $pythonExe -ArgumentList @('-B', '-u', ('"' + $runFile + '"')) -WorkingDirectory $WaveDeckRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -ErrorAction Stop
            Write-Host "WaveDeck 正在啟動；診斷日誌：$stderr"
            while ($watch.Elapsed.TotalSeconds -lt $TimeoutSec) {
                $port = Find-WaveDeckService -WaveDeckRoot $WaveDeckRoot -TimeoutSec ($TimeoutSec - $watch.Elapsed.TotalSeconds)
                if ($null -ne $port) { break }
                if ($process.HasExited) { throw "WaveDeck 程序已結束，退出碼 $($process.ExitCode)；請查看 $stderr" }
                Start-Sleep -Milliseconds 400
            }
        }
        if ($null -eq $port) { throw "WaveDeck 未在 $TimeoutSec 秒內就緒；保留日誌，未停止任何程序。" }
        Write-Host "WaveDeck 已就緒：http://127.0.0.1:$port/"
        if (-not $NoBrowser) { Open-WaveDeckBrowser -Port $port }
        return 0
    } catch {
        Write-Warning "WaveDeck 啟動未完成：$($_.Exception.Message)"
        return 1
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    exit (Invoke-WaveDeckLaunch -WaveDeckRoot $WaveDeckRoot -NoBrowser:$NoBrowser -TimeoutSec $TimeoutSec)
}

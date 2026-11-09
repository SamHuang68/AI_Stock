#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Inspect', 'RunHost')]
    [string]$Mode = 'Install',

    [ValidateSet('PasswordAtStartup', 'InteractiveAtLogOn')]
    [string]$StartupMode = 'InteractiveAtLogOn',

    [string]$InstallRoot = '',

    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$TaskName = 'StockTerminal_PrivateWeb_Host',

    [System.Management.Automation.PSCredential]$Credential,

    [ValidateRange(1024, 65535)]
    [int]$BackendPort = 18435,

    [ValidateRange(1024, 65535)]
    [int]$GatewayPort = 18434
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-DefaultInstallRoot {
    $base = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if ([string]::IsNullOrWhiteSpace($base)) {
        throw '找不到目前帳號的 LocalAppData，請明確指定 -InstallRoot。'
    }
    return Join-Path $base 'StockTerminalPrivateWeb'
}

function Resolve-SafeInstallRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    $full = [IO.Path]::GetFullPath($expanded).TrimEnd('\', '/')
    $driveRoot = [IO.Path]::GetPathRoot($full).TrimEnd('\', '/')
    if ([string]::IsNullOrWhiteSpace($full) -or $full -eq $driveRoot) {
        throw "安裝根目錄不可為磁碟根目錄：$full"
    }
    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        throw "找不到 Private Web 安裝根目錄：$full"
    }
    return $full
}

function Get-ReleaseContract {
    param([Parameter(Mandatory = $true)][string]$Root)

    $currentRoot = Join-Path $Root 'current'
    $manifestPath = Join-Path $currentRoot '.private_web_release.json'
    if (-not (Test-Path -LiteralPath $currentRoot -PathType Container)) {
        throw "找不到已提升的 current 版本：$currentRoot"
    }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "current 缺少 release manifest：$manifestPath"
    }

    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "release manifest 不是有效 JSON：$manifestPath"
    }

    $commit = [string]$manifest.commit
    $releaseId = [string]$manifest.releaseId
    $tests = [string]$manifest.tests
    $promotedAt = [string]$manifest.promotedAt
    if ($commit -notmatch '^[0-9a-fA-F]{40}$') {
        throw 'current release manifest 缺少完整的 40 碼 Git commit。'
    }
    if ($releaseId -ne $commit.Substring(0, 12)) {
        throw 'current releaseId 與 Git commit 不一致。'
    }
    if ($tests -ne 'passed') {
        throw 'current release 尚未通過 release tests，拒絕建立開機工作。'
    }
    if ([string]::IsNullOrWhiteSpace($promotedAt)) {
        throw 'current release 缺少 promotedAt，不能證明這是已提升版本。'
    }

    $required = [ordered]@{
        Host = Join-Path $currentRoot 'scripts\private_web_host.py'
        Backend = Join-Path $currentRoot 'server\server.py'
        Gateway = Join-Path $currentRoot 'server\private_web_gateway.py'
        OwnerToken = Join-Path $currentRoot 'data\private_web_owner.token'
        PythonPointer = Join-Path $currentRoot 'data\stock_python.path'
    }
    foreach ($entry in $required.GetEnumerator()) {
        if (-not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) {
            throw "current release 缺少必要檔案 $($entry.Key)：$($entry.Value)"
        }
    }
    if ((Get-Item -LiteralPath $required.OwnerToken).Length -le 0) {
        throw 'Private Web owner token 檔案為空，拒絕啟動。'
    }

    $pythonPath = (Get-Content -LiteralPath $required.PythonPointer -Raw -Encoding UTF8).Trim()
    if ([string]::IsNullOrWhiteSpace($pythonPath) -or -not [IO.Path]::IsPathRooted($pythonPath)) {
        throw 'data\stock_python.path 必須包含絕對 Python 路徑。'
    }
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "找不到 current 指定的 Python：$pythonPath"
    }

    return [pscustomobject]@{
        InstallRoot = $Root
        CurrentRoot = $currentRoot
        ManifestPath = $manifestPath
        Commit = $commit.ToLowerInvariant()
        ReleaseId = $releaseId.ToLowerInvariant()
        PromotedAt = $promotedAt
        HostPath = $required.Host
        PythonPath = $pythonPath
    }
}

function Get-CurrentIdentityContract {
    if ($env:OS -ne 'Windows_NT') {
        throw 'Windows 工作排程安裝器只能在 Windows 執行。'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($null -eq $identity.User -or [string]::IsNullOrWhiteSpace($identity.Name)) {
        throw '無法判定目前 Windows 帳號。'
    }
    return [pscustomobject]@{
        Name = $identity.Name
        Sid = $identity.User.Value
        Identity = $identity
    }
}

function Test-IsAdministrator {
    param([Parameter(Mandatory = $true)]$IdentityContract)

    $principal = [Security.Principal.WindowsPrincipal]::new($IdentityContract.Identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-AccountSid {
    param([Parameter(Mandatory = $true)][string]$Account)

    if ($Account -match '^S-\d-(?:\d+-){1,14}\d+$') {
        return $Account
    }
    try {
        $name = [Security.Principal.NTAccount]::new($Account)
        return $name.Translate([Security.Principal.SecurityIdentifier]).Value
    }
    catch {
        throw "無法解析 Windows 帳號：$Account"
    }
}

function Get-TaskDefinitionContract {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)]$Identity,
        [Parameter(Mandatory = $true)][string]$SelectedStartupMode,
        [Parameter(Mandatory = $true)][string]$SelectedTaskName,
        [Parameter(Mandatory = $true)][int]$SelectedBackendPort,
        [Parameter(Mandatory = $true)][int]$SelectedGatewayPort
    )

    $powerShellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powerShellPath -PathType Leaf)) {
        throw "找不到 Windows PowerShell：$powerShellPath"
    }

    $runnerPath = Join-Path $Release.InstallRoot 'startup\private_web_startup.ps1'
    $arguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass ' +
        "-File `"$runnerPath`" -Mode RunHost " +
        "-InstallRoot `"$($Release.InstallRoot)`" " +
        "-BackendPort $SelectedBackendPort -GatewayPort $SelectedGatewayPort"
    $isBoot = $SelectedStartupMode -eq 'PasswordAtStartup'

    return [pscustomobject]@{
        TaskName = $SelectedTaskName
        TaskPath = '\'
        Description = 'Stock Terminal Private Web：從已驗證的 current 版本啟動隔離 host。'
        StartupMode = $SelectedStartupMode
        CanRunBeforeLogon = $isBoot
        RequiresCredential = $isBoot
        AccountPolicy = if ($isBoot) { '目前帳號、相同 SID、Password logon' } else { '目前帳號、Interactive logon' }
        PrincipalUser = $Identity.Name
        PrincipalSid = $Identity.Sid
        ExpectedLogonType = if ($isBoot) { 'Password' } else { 'Interactive' }
        TriggerType = if ($isBoot) { 'AtStartup' } else { 'AtLogOn' }
        TriggerDelay = 'PT30S'
        ActionExecute = $powerShellPath
        ActionArguments = $arguments
        ActionWorkingDirectory = $Release.CurrentRoot
        RunnerPath = $runnerPath
        MultipleInstances = 'IgnoreNew'
        RestartCount = 12
        RestartInterval = 'PT1M'
        StartWhenAvailable = $true
        ExecutionTimeLimit = 'PT0S'
        Commit = $Release.Commit
        ReleaseId = $Release.ReleaseId
        CurrentRoot = $Release.CurrentRoot
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Install-StableRunner {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)]$Definition
    )

    $source = [IO.Path]::GetFullPath($PSCommandPath)
    $target = [IO.Path]::GetFullPath($Definition.RunnerPath)
    $startupRoot = [IO.Path]::GetFullPath((Join-Path $Release.InstallRoot 'startup')).TrimEnd('\')
    if (-not $target.StartsWith($startupRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "穩定啟動器路徑超出允許範圍：$target"
    }
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "找不到安裝器來源：$source"
    }

    New-Item -ItemType Directory -Path $startupRoot -Force | Out-Null
    $sourceHash = Get-Sha256 -Path $source
    if ([string]::Equals($source, $target, [StringComparison]::OrdinalIgnoreCase)) {
        if ((Get-Sha256 -Path $target) -ne $sourceHash) {
            throw '穩定啟動器自我驗證失敗。'
        }
        return $false
    }
    if ((Test-Path -LiteralPath $target -PathType Leaf) -and (Get-Sha256 -Path $target) -eq $sourceHash) {
        return $false
    }

    $temporary = Join-Path $startupRoot ('.private_web_startup.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        Copy-Item -LiteralPath $source -Destination $temporary -ErrorAction Stop
        if ((Get-Sha256 -Path $temporary) -ne $sourceHash) {
            throw '穩定啟動器暫存副本的 SHA-256 不一致。'
        }
        Move-Item -LiteralPath $temporary -Destination $target -Force -ErrorAction Stop
        if ((Get-Sha256 -Path $target) -ne $sourceHash) {
            throw '穩定啟動器寫入後的 SHA-256 不一致。'
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
    return $true
}

function Test-TaskMatchesDefinition {
    param(
        [Parameter(Mandatory = $true)]$Task,
        [Parameter(Mandatory = $true)]$Definition
    )

    $actions = @($Task.Actions)
    $triggers = @($Task.Triggers)
    if ($actions.Count -ne 1 -or $triggers.Count -ne 1) { return $false }
    $action = $actions[0]
    if (-not [string]::Equals([string]$action.Execute, $Definition.ActionExecute, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    if (-not [string]::Equals([string]$action.Arguments, $Definition.ActionArguments, [StringComparison]::Ordinal)) { return $false }
    if (-not [string]::Equals([string]$action.WorkingDirectory, $Definition.ActionWorkingDirectory, [StringComparison]::OrdinalIgnoreCase)) { return $false }

    try {
        if ((Resolve-AccountSid ([string]$Task.Principal.UserId)) -ne $Definition.PrincipalSid) { return $false }
    }
    catch { return $false }
    if ([string]$Task.Principal.LogonType -ne $Definition.ExpectedLogonType) { return $false }

    $expectedTriggerClass = if ($Definition.TriggerType -eq 'AtStartup') { 'MSFT_TaskBootTrigger' } else { 'MSFT_TaskLogonTrigger' }
    if ([string]$triggers[0].CimClass.CimClassName -ne $expectedTriggerClass) { return $false }
    if (-not [bool]$triggers[0].Enabled) { return $false }
    if ([string]$triggers[0].Delay -ne $Definition.TriggerDelay) { return $false }

    if ([string]$Task.Settings.MultipleInstances -ne $Definition.MultipleInstances) { return $false }
    if ([int]$Task.Settings.RestartCount -ne $Definition.RestartCount) { return $false }
    if ([string]$Task.Settings.RestartInterval -ne $Definition.RestartInterval) { return $false }
    if (-not [bool]$Task.Settings.StartWhenAvailable) { return $false }
    if ([string]$Task.Settings.ExecutionTimeLimit -ne $Definition.ExecutionTimeLimit) { return $false }
    return $true
}

function Test-TaskOwnedByInstaller {
    param(
        [Parameter(Mandatory = $true)]$Task,
        [Parameter(Mandatory = $true)]$Definition
    )

    try { $taskSid = Resolve-AccountSid -Account ([string]$Task.Principal.UserId) }
    catch { return $false }
    if ($taskSid -ne $Definition.PrincipalSid) { return $false }
    if ([string]$Task.Description -ne $Definition.Description) { return $false }

    $actions = @($Task.Actions)
    if ($actions.Count -ne 1) { return $false }
    $action = $actions[0]
    if (-not [string]::Equals([string]$action.Execute, $Definition.ActionExecute, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    $arguments = [string]$action.Arguments
    if ($arguments.IndexOf($Definition.RunnerPath, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return $false }
    if ($arguments.IndexOf('-Mode RunHost', [StringComparison]::Ordinal) -lt 0) { return $false }
    return $true
}

function Write-StartupEvent {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$Event,
        [Parameter(Mandatory = $true)][string]$Message,
        [hashtable]$Details = @{}
    )

    $logDirectory = Join-Path $Release.CurrentRoot 'logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $record = [ordered]@{
        timestamp = [DateTimeOffset]::UtcNow.ToString('o')
        component = 'private_web_startup'
        event = $Event
        message = $Message
        releaseId = $Release.ReleaseId
    }
    foreach ($key in $Details.Keys) { $record[$key] = $Details[$key] }
    Add-Content -LiteralPath (Join-Path $logDirectory 'private_web_startup.jsonl') -Value ($record | ConvertTo-Json -Compress) -Encoding UTF8
}

function Get-GatewayHealth {
    param([Parameter(Mandatory = $true)][int]$Port)

    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/gateway/health" -Method Get -TimeoutSec 3
    }
    catch {
        return $null
    }
}

function Test-LocalPortOpen {
    param([Parameter(Mandatory = $true)][int]$Port)

    $client = [Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($result)
        return $true
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Invoke-CurrentHost {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][int]$SelectedBackendPort,
        [Parameter(Mandatory = $true)][int]$SelectedGatewayPort
    )

    $health = Get-GatewayHealth -Port $SelectedGatewayPort
    if ($null -ne $health -and [string]$health.gateway -eq 'private-web') {
        $mode = [string]$health.mode
        $upstream = [bool]$health.upstream
        if ($mode -eq 'isolated-host' -and $upstream) {
            Write-StartupEvent -Release $Release -Event 'already_healthy' -Message '已存在健康的 isolated-host；維持現況，不重啟。'
            [Console]::Out.WriteLine('[完成] Private Web isolated-host 已健康執行；未重新啟動。')
            return 0
        }
        Write-StartupEvent -Release $Release -Event 'gateway_occupied' -Message 'Gateway 已由其他模式占用；未停止既存程序。' -Details @{ mode = $mode; upstream = $upstream; gatewayPort = $SelectedGatewayPort }
        [Console]::Error.WriteLine("[等候] 連接埠 $SelectedGatewayPort 目前是 Private Web $mode；為保護既存服務，本次不終止或取代它。")
        return 23
    }
    if (Test-LocalPortOpen -Port $SelectedGatewayPort) {
        Write-StartupEvent -Release $Release -Event 'gateway_port_occupied' -Message 'Gateway 連接埠由無法識別的程序占用；未停止既存程序。' -Details @{ gatewayPort = $SelectedGatewayPort }
        [Console]::Error.WriteLine("[失敗] 連接埠 $SelectedGatewayPort 已被無法識別的程序占用；未停止既存程序。")
        return 24
    }

    Write-StartupEvent -Release $Release -Event 'host_start' -Message '從已驗證的 current 版本啟動 Private Web host。' -Details @{ backendPort = $SelectedBackendPort; gatewayPort = $SelectedGatewayPort }
    Push-Location -LiteralPath $Release.CurrentRoot
    try {
        & $Release.PythonPath -u $Release.HostPath --backend-port $SelectedBackendPort --gateway-port $SelectedGatewayPort
        $hostExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($null -eq $hostExitCode) { $hostExitCode = 1 }
    Write-StartupEvent -Release $Release -Event 'host_exit' -Message 'Private Web host 已結束。' -Details @{ exitCode = [int]$hostExitCode }
    return [int]$hostExitCode
}

function Install-PrivateWebTask {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)]$Identity,
        [Parameter(Mandatory = $true)]$Definition,
        [System.Management.Automation.PSCredential]$SuppliedCredential
    )

    if ($Definition.StartupMode -eq 'PasswordAtStartup' -and -not (Test-IsAdministrator -IdentityContract $Identity)) {
        throw 'PasswordAtStartup 模式需要系統管理員權限；請以系統管理員身分重新執行。'
    }

    $existing = Get-ScheduledTask -TaskName $Definition.TaskName -TaskPath $Definition.TaskPath -ErrorAction SilentlyContinue
    if ($null -ne $existing -and -not (Test-TaskOwnedByInstaller -Task $existing -Definition $Definition)) {
        throw "同名工作 $($Definition.TaskName) 缺少本安裝器的帳號、描述或啟動器簽章；為避免覆寫無關工作，已停止。"
    }

    $runnerChanged = Install-StableRunner -Release $Release -Definition $Definition
    if ($null -ne $existing -and (Test-TaskMatchesDefinition -Task $existing -Definition $Definition)) {
        $runnerState = if ($runnerChanged) { '已更新穩定啟動器；' } else { '穩定啟動器未變；' }
        [Console]::Out.WriteLine("[完成] $runnerState 工作 $($Definition.TaskName) 已符合 current release $($Definition.ReleaseId)，未改動排程，也未重啟既存 host。")
        return 0
    }

    $action = New-ScheduledTaskAction -Execute $Definition.ActionExecute -Argument $Definition.ActionArguments -WorkingDirectory $Definition.ActionWorkingDirectory
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount $Definition.RestartCount -RestartInterval (New-TimeSpan -Minutes 1)

    if ($Definition.StartupMode -eq 'PasswordAtStartup') {
        $effectiveCredential = $SuppliedCredential
        if ($null -eq $effectiveCredential) {
            $effectiveCredential = Get-Credential -UserName $Identity.Name -Message '請輸入此 Windows 帳號的密碼（不是 Windows Hello PIN）。密碼只交給工作排程服務，不會寫入檔案或命令列。'
        }
        if ($null -eq $effectiveCredential) {
            throw '未取得 Windows 帳號密碼，未建立開機工作。'
        }
        $credentialSid = Resolve-AccountSid -Account $effectiveCredential.UserName
        if ($credentialSid -ne $Identity.Sid) {
            throw '排程帳號與目前帳號 SID 不同；為避免 DPAPI 憑證失效，已拒絕安裝。'
        }

        $trigger = New-ScheduledTaskTrigger -AtStartup
        $trigger.Delay = $Definition.TriggerDelay
        $plainPassword = $effectiveCredential.GetNetworkCredential().Password
        try {
            Register-ScheduledTask -TaskName $Definition.TaskName -TaskPath $Definition.TaskPath -Description $Definition.Description -Action $action -Trigger $trigger -Settings $settings -User $Identity.Name -Password $plainPassword -RunLevel Limited -Force | Out-Null
        }
        finally {
            $plainPassword = $null
            $effectiveCredential = $null
        }
    }
    else {
        if ($null -ne $SuppliedCredential) {
            throw 'InteractiveAtLogOn 模式不接受 -Credential；此模式只會在相同帳號登入後啟動。'
        }
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity.Name
        $trigger.Delay = $Definition.TriggerDelay
        $principal = New-ScheduledTaskPrincipal -UserId $Identity.Name -LogonType Interactive -RunLevel Limited
        $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $Definition.Description
        Register-ScheduledTask -TaskName $Definition.TaskName -TaskPath $Definition.TaskPath -InputObject $task -Force | Out-Null
    }

    $installed = Get-ScheduledTask -TaskName $Definition.TaskName -TaskPath $Definition.TaskPath -ErrorAction Stop
    if (-not (Test-TaskMatchesDefinition -Task $installed -Definition $Definition)) {
        throw '工作已建立，但驗證結果與預期定義不一致。'
    }
    [Console]::Out.WriteLine("[完成] 已建立 $($Definition.TriggerType) 工作 $($Definition.TaskName)，目標為 current release $($Definition.ReleaseId)。")
    [Console]::Out.WriteLine('[說明] 安裝器不會啟動工作，也不會停止或重啟目前的 Private Web 程序。')
    return 0
}

try {
    if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $InstallRoot = Get-DefaultInstallRoot }
    $safeRoot = Resolve-SafeInstallRoot -Path $InstallRoot
    $release = Get-ReleaseContract -Root $safeRoot

    if ($Mode -eq 'RunHost') {
        exit (Invoke-CurrentHost -Release $release -SelectedBackendPort $BackendPort -SelectedGatewayPort $GatewayPort)
    }

    $identity = Get-CurrentIdentityContract
    $definition = Get-TaskDefinitionContract -Release $release -Identity $identity -SelectedStartupMode $StartupMode -SelectedTaskName $TaskName -SelectedBackendPort $BackendPort -SelectedGatewayPort $GatewayPort
    if ($Mode -eq 'Inspect') {
        $definition | ConvertTo-Json -Depth 5
        exit 0
    }

    exit (Install-PrivateWebTask -Release $release -Identity $identity -Definition $definition -SuppliedCredential $Credential)
}
catch {
    [Console]::Error.WriteLine("[失敗] $($_.Exception.Message)")
    exit 1
}

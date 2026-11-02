# Register (or replace) the logon task that starts the managed local Stock Terminal (127.0.0.1:18432).
# Same shape as StockTerminal_PrivateWeb_Host: current user, interactive logon, limited run level (no admin).
# The action runs the installed start_local.ps1, which is idempotent and refuses to touch an unknown 18432 owner.
# ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less files with the ANSI code page.
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'StockTerminalLocal'),
    [string]$TaskName = 'StockTerminal_Local_Host',
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed task $TaskName."
    } else {
        Write-Output "Task $TaskName does not exist."
    }
    return
}

$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$starter = Join-Path $InstallRoot 'start_local.ps1'
if (-not (Test-Path -LiteralPath $starter -PathType Leaf)) {
    throw "No managed local install at $InstallRoot (start_local.ps1 missing). Run local_release.py setup first."
}
$log = Join-Path $InstallRoot 'logs\local_host_task.log'
$command = "Start-Transcript -Path '$log' -Force | Out-Null; " +
    "try { & '$starter' -InstallRoot '$InstallRoot' -NoBrowser; exit 0 } " +
    "catch { Write-Output ('FAILED: ' + `$_.Exception.Message); exit 1 }"
$argument = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command "' +
    $command.Replace('"', '\"') + '"'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action = New-ScheduledTaskAction -Execute $powershell -Argument $argument -WorkingDirectory (Join-Path $InstallRoot 'current')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$trigger.Delay = 'PT60S'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description 'Start the managed local Stock Terminal (127.0.0.1:18432) at logon.'
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Write-Output "Registered $TaskName (logon + 60 s, user $identity). Log: $log"

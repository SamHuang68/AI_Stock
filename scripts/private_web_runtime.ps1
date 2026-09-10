# Private Web 發布時的程序身分、重啟及版本驗證。
function Assert-PrivateWebRevision {
  param([string]$Url, [string]$Commit, [hashtable]$Headers = @{}, [int]$Attempts = 1)
  $observed = $null
  $lastError = $null
  for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    try {
      $health = Invoke-RestMethod -Uri $Url -Headers $Headers -TimeoutSec 3
      $observed = [string]$health.releaseCommit
      if ($health.ok -and $observed -eq $Commit) {
        Write-Host "[版本驗證] $Url SHA=$Commit"
        return
      }
    } catch {
      $lastError = $_.Exception.Message
    }
    if ($attempt -lt $Attempts) { Start-Sleep -Milliseconds 500 }
  }
  $got = if ($observed) { $observed } else { 'unreachable' }
  $hint = if ($lastError) { "；連線=$lastError" } else { '' }
  throw "服務版本驗證失敗：$Url，預期 SHA=$Commit，程序 SHA=$got$hint；磁碟 current 不能代替程序版本證據"
}

function Stop-PrivateWebRuntime {
  param([string]$Current)
  $resolved = [IO.Path]::GetFullPath($Current).TrimEnd('\')
  $entries = @('scripts\private_web_host.py', 'server\server.py', 'server\private_web_gateway.py')
  $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
  $owned = @($processes | Where-Object {
    $candidate = $_
    $candidate.Name -match '^python(?:w)?(?:\d+(?:\.\d+)*)?\.exe$' -and
      @($entries | Where-Object {
        $path = Join-Path $resolved $_
        $candidate.CommandLine -match ('(?i)(?:^|[\s"])' + [regex]::Escape($path) + '(?:[\s"]|$)')
      }).Count -gt 0
  })
  $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in @(18434, 18435) })
  foreach ($listener in $listeners) {
    if ($listener.OwningProcess -notin @($owned.ProcessId)) {
      throw "拒絕停止無法確認身分的程序：連接埠=$($listener.LocalPort)，PID=$($listener.OwningProcess)"
    }
  }
  # 先停止監督程序，避免它在子程序停止時重新啟動。
  $ordered = @($owned | Sort-Object @{ Expression = { if ($_.CommandLine -match 'private_web_host\.py') { 0 } else { 1 } } })
  foreach ($candidate in $ordered) {
    $live = Get-CimInstance Win32_Process -Filter "ProcessId=$($candidate.ProcessId)" -ErrorAction Stop
    if (-not $live) { continue }
    if ($live.CreationDate -ne $candidate.CreationDate -or $live.CommandLine -ne $candidate.CommandLine) {
      throw "程序身分已變更，拒絕停止 PID=$($candidate.ProcessId)"
    }
    Write-Host "[停止] 已確認 current 程序 PID=$($candidate.ProcessId)"
    Stop-Process -Id $candidate.ProcessId -Force -ErrorAction Stop
    Wait-Process -Id $candidate.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
  }
}

function Start-PrivateWebRuntime {
  param([string]$Current, [string]$Python)
  $entry = Join-Path $Current 'scripts\private_web_host.py'
  # 保留 Windows ShellExecute 的獨立程序語意；重新導向會讓子程序
  # 繼承呼叫端的管線，使發布命令等到服務停止才返回。
  # 監督程序及子程序仍自行寫入 current/logs 的既有持久紀錄。
  $process = Start-Process -FilePath $Python -ArgumentList @('-u', ('"' + $entry + '"')) -WorkingDirectory $Current -WindowStyle Hidden -PassThru
  Write-Host "[啟動] current 監督程序 PID=$($process.Id)"
}

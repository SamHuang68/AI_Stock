# Stock Terminal v5.0 — tip UX + WaveDeck integrate (PowerShell)
# Usage (from repo root):
#   DOUBLE-CLICK:  START_TIP.cmd
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 -UpdateOnly
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 -RebuildOnly
#
# Discipline: NEVER launch with bare PATH "python". Always resolve an absolute
# interpreter, pin it to data\stock_python.path, and reuse the pin. Tooling
# venvs (Hermes/agent) are deprioritized — not banned as a product policy.
param(
  # Backward-compatible safe update+run. Prefer -UpdateOnly, then launch.
  [switch]$Pull,
  [switch]$UpdateOnly,
  [switch]$RebuildOnly,
  [switch]$Worktree
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root 'build_v2.py'))) {
  $Root = (Get-Location).Path
}
Set-Location $Root

# 只有已登記的原工作樹正常啟動會轉接；隔離工作樹與明確開發動作維持原行為。
# 此處必須早於 Python pin、建置、Git 檢查及任何停止程序的動作。
if ($env:LOCALAPPDATA -and -not ($Worktree -or $Pull -or $UpdateOnly -or $RebuildOnly)) {
  $managedLocalRoot = Join-Path $env:LOCALAPPDATA 'StockTerminalLocal'
  $managedLocalConfig = Join-Path $managedLocalRoot 'local_install.json'
  if (Test-Path -LiteralPath $managedLocalConfig) {
  $localConfig = Get-Content -LiteralPath $managedLocalConfig -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($localConfig.originalCheckout -and [string]::Equals(
      [IO.Path]::GetFullPath([string]$localConfig.originalCheckout).TrimEnd('\'),
      [IO.Path]::GetFullPath($Root).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
    $managedLauncher = Join-Path $managedLocalRoot 'start_local.ps1'
    if (-not (Test-Path -LiteralPath $managedLauncher -PathType Leaf)) {
      throw '本機受管理啟動器缺少，未退回重建原工作樹；請修復本機安裝。'
    }
    & (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -ExecutionPolicy Bypass -File $managedLauncher -InstallRoot $managedLocalRoot
    exit $LASTEXITCODE
  }
  # 已有受管本機安裝，但目前資料夾不是登記的原工作樹：不能走下方開發流程，
  # 開發流程不得搶用正在使用的受管本機 ST 埠。
  if ($localConfig.originalCheckout) {
    throw ("ST-LAUNCHER-GUARD: 本機已有受管安裝，且此資料夾不是登記的原工作樹，已停止，未關閉任何程序。`n" +
      "  登記的原工作樹：$($localConfig.originalCheckout)`n" +
      "  目前資料夾　　：$Root`n" +
      "  請到登記的資料夾執行 START_TIP.cmd；若確實要在此資料夾開發，請明確加 -Worktree（只允許結束收據核對相符的開發程序；未知占用者會拒絕）。")
  }
  }
}

$TipBranch = 'cursor/st51-docs-ux-on-tip-3497'
$TipFile = Join-Path $Root 'TIP_BRANCH'
if (Test-Path $TipFile) {
  $TipBranch = (Get-Content $TipFile -Raw).Trim()
}
$Port = 18432
$DevReceipt = Join-Path $Root 'logs\dev_server.receipt.json'
$Url = "http://localhost:${Port}/#pulse"

function Write-Banner {
  Write-Host ''
  Write-Host '============================================'
  Write-Host ' Stock Terminal v5.0  - tip UX (PowerShell)'
  Write-Host " $Url"
  Write-Host '============================================'
  Write-Host " repo: $Root"
  Write-Host " tip:  $TipBranch"
}

function Test-ToolingPython([string]$ExePath) {
  # Soft ranking only — not a ban. Prefer system / python.org installs.
  if (-not $ExePath) { return $true }
  $low = $ExePath.ToLowerInvariant()
  return ($low -match 'hermes' -or
          $low -match '\\hermes-agent\\' -or
          $low -match 'cursor.*agent' -or
          $low -match '\\antigravity\\' -or
          $low -match '\\miniconda\\envs\\' -or
          $low -match '\\anaconda\\envs\\')
}

function Save-StockPythonPin([string]$ExePath) {
  $pinDir = Join-Path $Root 'data'
  if (-not (Test-Path $pinDir)) { New-Item -ItemType Directory -Path $pinDir | Out-Null }
  $pin = Join-Path $pinDir 'stock_python.path'
  Set-Content -LiteralPath $pin -Value $ExePath -Encoding ASCII
  Write-Host "[python] pinned -> $pin"
}

function Read-StockPythonPin {
  $pin = Join-Path $Root 'data\stock_python.path'
  if (-not (Test-Path -LiteralPath $pin)) { return $null }
  $p = (Get-Content -LiteralPath $pin -Raw).Trim()
  if ($p -and (Test-Path -LiteralPath $p)) { return $p }
  return $null
}

function Test-PythonUsable([string]$ExePath) {
  try {
    $ver = (& $ExePath -c "import sys; print('%d.%d'%sys.version_info[:2])" 2>$null | Select-Object -First 1)
    if (-not $ver) { return $false }
    if ($ver -notmatch '^3\.') { return $false }
    return $true
  } catch { return $false }
}

function Resolve-StockPython {
  Write-Host '[python] resolve absolute Stock Python (pin; deprioritize tooling venvs)'

  # 0) Explicit override
  if ($env:ST_PYTHON -and (Test-Path -LiteralPath $env:ST_PYTHON)) {
    if (Test-PythonUsable $env:ST_PYTHON) {
      Write-Host "       OK ST_PYTHON -> $($env:ST_PYTHON)"
      Save-StockPythonPin $env:ST_PYTHON
      return $env:ST_PYTHON
    }
  }

  # 1) Reuse previous pin (stable across PATH churn)
  $pinned = Read-StockPythonPin
  if ($pinned -and -not (Test-ToolingPython $pinned) -and (Test-PythonUsable $pinned)) {
    Write-Host "       OK pin -> $pinned"
    return $pinned
  }

  $preferred = New-Object System.Collections.Generic.List[string]
  $fallback = New-Object System.Collections.Generic.List[string]

  # 2) py -3 (Windows launcher → usually python.org)
  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCmd) {
    try {
      $exe = (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
      if ($exe) { [void]$preferred.Add($exe.Trim()) }
    } catch {}
  }

  # 3) Known python.org locations (high priority)
  foreach ($ver in @('314', '313', '312', '311', '310', '39')) {
    [void]$preferred.Add("$env:LOCALAPPDATA\Programs\Python\Python$ver\python.exe")
    [void]$preferred.Add("${env:ProgramFiles}\Python$ver\python.exe")
    [void]$preferred.Add("C:\Python$ver\python.exe")
  }

  # 4) PATH entries last (may include tooling) — split by ranking
  try {
    $whereOut = & where.exe python 2>$null
    foreach ($line in $whereOut) {
      if ($line -and (Test-Path $line)) {
        if (Test-ToolingPython $line) { [void]$fallback.Add($line.Trim()) }
        else { [void]$preferred.Add($line.Trim()) }
      }
    }
  } catch {}

  $seen = @{}
  foreach ($c in ($preferred + $fallback)) {
    if (-not $c) { continue }
    $full = $c
    try { $full = [System.IO.Path]::GetFullPath($c) } catch {}
    $key = $full.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { continue }
    $seen[$key] = $true
    if (-not (Test-Path -LiteralPath $full)) { continue }
    $tooling = Test-ToolingPython $full
    if ($tooling -and -not $env:ST_ALLOW_TOOLING_PYTHON) {
      Write-Host "       defer tooling python: $full"
      continue
    }
    if (-not (Test-PythonUsable $full)) {
      Write-Host "       SKIP unusable: $full"
      continue
    }
    Write-Host "       OK -> $full"
    Save-StockPythonPin $full
    return $full
  }

  # Last resort: allow tooling only if explicitly opted in, else clear error
  foreach ($c in $fallback) {
    if ($c -and (Test-Path $c) -and (Test-PythonUsable $c)) {
      if ($env:ST_ALLOW_TOOLING_PYTHON) {
        Write-Host "       OK tooling (ST_ALLOW_TOOLING_PYTHON) -> $c"
        Save-StockPythonPin $c
        return $c
      }
    }
  }

  throw @"
No usable Python 3 absolute path found.

Fix (pick one):
  1) Install https://www.python.org/downloads/ and ensure ``py -3`` works
  2) Set env ST_PYTHON to your python.exe absolute path, then re-run
  3) Emergency only: `$env:ST_ALLOW_TOOLING_PYTHON=1` then re-run

Root cause of past blank windows: scripts called bare ``python`` on PATH.
This launcher pins an absolute path under data\stock_python.path instead.
"@
}

function Assert-TipBranch {
  $cur = (git branch --show-current 2>$null)
  Write-Host " branch: $cur"
  # Canonical tip may be main after P0 Conditional Expectation landed on main.
  # Only treat main/master as legacy when TIP_BRANCH still points at a tip feature branch.
  $legacyTips = @('cursor/http-client-pool-3497', 'cursor/range-period-change-b5cf')
  if ($legacyTips -contains $cur) {
    throw "BLOCK: current branch '$cur' is legacy. Run: powershell -File .\scripts\go.ps1 -Pull"
  }
  if (($cur -eq 'main' -or $cur -eq 'master') -and ($TipBranch -ne 'main' -and $TipBranch -ne 'master')) {
    throw "BLOCK: current branch '$cur' is legacy vs tip '$TipBranch'. Run: powershell -File .\scripts\go.ps1 -Pull"
  }
  if ($cur -ne $TipBranch) {
    throw "BLOCK: on '$cur' but tip is '$TipBranch'. Run: powershell -File .\scripts\go.ps1 -Pull"
  }
}

# 依埠找出正在 LISTEN 的程序 PID。只回報，不終止任何程序。
function Get-PortListenerPids([int]$PortNum) {
  $pids = New-Object System.Collections.Generic.HashSet[int]

  try {
    Get-NetTCPConnection -LocalPort $PortNum -State Listen -ErrorAction SilentlyContinue |
      ForEach-Object { [void]$pids.Add([int]$_.OwningProcess) }
  } catch {}

  $lines = netstat -ano 2>$null | Select-String ":$PortNum\s+.*LISTENING"
  foreach ($ln in $lines) {
    $parts = ($ln.ToString() -split '\s+') | Where-Object { $_ -ne '' }
    $procId = $parts[-1]
    if ($procId -match '^\d+$') { [void]$pids.Add([int]$procId) }
  }

  return @($pids | Where-Object { $_ -gt 4 })
}

# 程序身分：啟動時間（UTC ticks）。PID 會被作業系統重複使用，所以收據要連啟動時間一起核對。
function Get-ProcessStartTicks([int]$ProcId) {
  try { return [int64](Get-Process -Id $ProcId -ErrorAction Stop).StartTime.ToUniversalTime().Ticks } catch { return $null }
}

function Get-ProcessCommandLine([int]$ProcId) {
  try { return [string](Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction Stop).CommandLine } catch { return '(讀不到命令列)' }
}

# 開發伺服器啟動後登記它的身分（PID、啟動時間、資料夾）。之後只有收據登記的程序可以被這個腳本終止。
function Write-DevServerReceipt([int]$PortNum, [string]$ReceiptPath, [string]$OwnerRoot, [int]$ExpectedParent, [int64]$ExpectedParentTicks = 0, [string]$ExpectedPython = '', [string]$ExpectedBasePython = '', [string]$ExpectedLauncher = '') {
  if ($ExpectedParent -gt 4 -and ([string]::IsNullOrWhiteSpace($ExpectedPython) -or
      [string]::IsNullOrWhiteSpace($ExpectedBasePython) -or [string]::IsNullOrWhiteSpace($ExpectedLauncher))) {
    Write-Host '[warn] 缺少本次釘選 Python、基礎 Python 或 CMD 身分；保持程序運行，不寫入自動終止收據。'
    return
  }
  $listeners = @(Get-PortListenerPids $PortNum)
  $ticks = $null
  if ($listeners.Count -eq 1) { $ticks = Get-ProcessStartTicks $listeners[0] }
  $commandLine = $null
  if ($null -ne $ticks -and $ExpectedParent -gt 4) {
    try {
      $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listeners[0])" -ErrorAction Stop
      $launchTicks = Get-ProcessStartTicks $ExpectedParent
      if ($ExpectedParentTicks -eq 0) { $ExpectedParentTicks = $launchTicks }
      if ($ExpectedPython) {
        $allowedPaths = @($ExpectedPython, $ExpectedBasePython) | Where-Object { $_ }
        if ($allowedPaths -notcontains [string]$process.ExecutablePath -or
            [string]$process.CommandLine -notmatch [regex]::Escape((Join-Path $OwnerRoot 'server\server.py'))) {
          throw '伺服器命令與釘選 Python 或工作樹不符。'
        }
      }
      if ($ExpectedLauncher) {
        $launcherProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$ExpectedParent" -ErrorAction Stop
        if ([string]$launcherProcess.Name -ne 'cmd.exe' -or
            [string]$launcherProcess.CommandLine -notmatch [regex]::Escape($ExpectedLauncher)) {
          throw '啟動程序與本次產生的 CMD 不符。'
        }
      }
      if ($null -ne $launchTicks -and $launchTicks -eq $ExpectedParentTicks -and $launchTicks -le $ticks) {
        if ([int]$process.ParentProcessId -eq $ExpectedParent) {
          $commandLine = [string]$process.CommandLine
        } elseif ([string]$process.Name -eq 'python.exe') {
          # Windows venv 有一層 Python 轉接器；只接受同一命令列及時間順序相符的直接轉接。
          $proxy = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)" -ErrorAction Stop
          $proxyTicks = Get-ProcessStartTicks ([int]$proxy.ProcessId)
          if ($ExpectedPython -and ([string]$proxy.ExecutablePath -eq $ExpectedPython) -and
              [string]$proxy.Name -eq 'python.exe' -and [int]$proxy.ParentProcessId -eq $ExpectedParent -and
              $proxy.CommandLine -and ([string]$proxy.CommandLine -ceq [string]$process.CommandLine) -and
              $null -ne $proxyTicks -and $launchTicks -le $proxyTicks -and $proxyTicks -le $ticks) {
            $commandLine = [string]$process.CommandLine
          }
        }
      }
    } catch {
      Write-Host '[warn] 無法讀取程序身分；保持伺服器運行，不寫入自動終止收據。'
    }
  }
  if (-not $commandLine) { $ticks = $null }
  if ($null -eq $ticks) {
    Write-Host "[warn] 無法確認 :$PortNum 上唯一的開發伺服器程序，未寫入收據；下次啟動若該埠仍被占用會拒絕，不會自動終止。"
    return
  }
  $dir = Split-Path -Parent $ReceiptPath
  if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  $receipt = [ordered]@{ pid = [int]$listeners[0]; startTicksUtc = [int64]$ticks; root = $OwnerRoot; port = $PortNum; commandLine = $commandLine }
  ($receipt | ConvertTo-Json) | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
  Write-Host "[receipt] 已登記開發伺服器 PID $($listeners[0])：$ReceiptPath"
}

# 只結束「這個資料夾自己啟動、且收據核對得上（PID、啟動時間、資料夾、埠）」的開發伺服器。
# 埠上有任何其他程序（含本機受管 ST 18432）就拒絕，不終止任何程序，由人處置。
function Stop-OwnedPortListeners([int]$PortNum, [string]$ReceiptPath, [string]$OwnerRoot) {
  $listeners = @(Get-PortListenerPids $PortNum)
  if ($listeners.Count -eq 0) { return }

  $owned = 0
  if (Test-Path -LiteralPath $ReceiptPath) {
    try {
      $r = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
      $sameRoot = [string]::Equals(
        [IO.Path]::GetFullPath([string]$r.root).TrimEnd('\', '/'),
        [IO.Path]::GetFullPath($OwnerRoot).TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)
      $nowTicks = Get-ProcessStartTicks ([int]$r.pid)
      $sameCommand = $r.commandLine -and ([string]$r.commandLine -ceq (Get-ProcessCommandLine ([int]$r.pid)))
      if ($sameRoot -and $sameCommand -and ([int]$r.port -eq $PortNum) -and ($null -ne $nowTicks) -and ($nowTicks -eq [int64]$r.startTicksUtc)) {
        $owned = [int]$r.pid
      }
    } catch {}
  }

  $foreign = @($listeners | Where-Object { $_ -ne $owned })
  if ($foreign.Count -gt 0) {
    $detail = ($foreign | ForEach-Object { "  占用者：PID $_  命令列：$(Get-ProcessCommandLine $_)" }) -join "`n"
    throw ("ST-PORT-GUARD: 埠 $PortNum 被不是由此資料夾的開發流程啟動的程序占用，已停止，未終止任何程序。`n" +
      $detail + "`n" +
      "  若占用者是本機受管 ST（命令列含 StockTerminalLocal\current），請不要終止它；開發請改在別的埠或別的工作樹。`n" +
      "  確認該程序不需要後，請自行手動結束它再重試。")
  }

  Write-Host "[stop] 結束此資料夾自己啟動的開發伺服器 PID $owned（埠 $PortNum）"
  if ((Get-ProcessStartTicks $owned) -ne [int64]$r.startTicksUtc -or (Get-ProcessCommandLine $owned) -cne [string]$r.commandLine) {
    throw 'ST-PORT-GUARD: 終止前程序身分已變動，拒絕終止。'
  }
  Stop-Process -Id $owned -Force -ErrorAction Stop
  Start-Sleep -Seconds 1
}

function Assert-LauncherBehavior([string]$Path) {
  # 依 PowerShell AST 檢查實際函式與啟動參數，註解不參與版本判斷。
  $tokens = $null; $parseErrors = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$parseErrors)
  $resolver = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Resolve-StockPython' }, $true)
  $ownedStop = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Stop-OwnedPortListeners' }, $true)
  $receipt = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Write-DevServerReceipt' }, $true)
  $receiptCalls = @($ast.FindAll({ param($n)
    $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Write-DevServerReceipt'
  }, $true))
  $weakReceiptCalls = @($receiptCalls | Where-Object {
    $names = @($_.CommandElements | Where-Object {
      $_ -is [System.Management.Automation.Language.CommandParameterAst]
    } | ForEach-Object { $_.ParameterName })
    $missing = @('ExpectedPython', 'ExpectedBasePython', 'ExpectedLauncher') | Where-Object { $names -notcontains $_ }
    @($missing).Count -gt 0
  })
  $unsafeStop = $ast.FindAll({ param($n)
    ($n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Stop-PortListeners') -or
    ($n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Stop-PortListeners')
  }, $true)
  $redirect = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandParameterAst] -and $n.ParameterName -eq 'RedirectStandardOutput' }, $true)
  $unownedKill = $ast.FindAll({ param($n)
    if ($n -isnot [System.Management.Automation.Language.CommandAst]) { return $false }
    $command = $n.GetCommandName()
    if ($command -eq 'taskkill' -or $command -eq 'taskkill.exe') { return $true }
    if ($command -ne 'Stop-Process') { return $false }
    $scope = $n.Parent
    while ($null -ne $scope -and $scope -isnot [System.Management.Automation.Language.FunctionDefinitionAst]) { $scope = $scope.Parent }
    return $null -eq $scope -or $scope.Name -ne 'Stop-OwnedPortListeners'
  }, $true)
  if ($parseErrors.Count -gt 0 -or $resolver.Count -ne 1 -or $ownedStop.Count -ne 1 -or $receipt.Count -ne 1 -or $receiptCalls.Count -lt 1 -or $weakReceiptCalls.Count -gt 0 -or $unsafeStop.Count -gt 0 -or $redirect.Count -gt 0 -or $unownedKill.Count -gt 0) {
    throw '啟動腳本行為檢查失敗，請核對拉取版本。'
  }
}

function Assert-TipHtml {
  $html = Join-Path $Root 'stock_terminal_v2.html'
  if (-not (Test-Path $html)) { throw "missing $html — run build_v2.py" }
  $txt = Get-Content $html -Raw -Encoding UTF8
  foreach ($need in @('shell_v5.js', 'pulse_v5.js', 'st5-tip-boot')) {
    if ($txt -notmatch [regex]::Escape($need)) {
      throw "HTML is NOT tip UX (missing $need). Stay on tip and rebuild."
    }
  }
  Write-Host '[ok] HTML contains shell_v5 + pulse_v5 + st5-tip-boot'

  $pulse = Join-Path $Root 'src\ui\pulse_v5.js'
  if (-not (Test-Path $pulse)) { throw "missing $pulse" }
  $pjs = Get-Content $pulse -Raw -Encoding UTF8
  if ($pjs -match '4col-priority') {
    throw "pulse_v5.js still has 4-col layout — reset tip branch and rebuild"
  }
  if ($pjs -notmatch '5col-2zone' -or $pjs -notmatch 'repeat\(5,minmax\(0,1fr\)\)') {
    throw "pulse_v5.js missing 5-col×2-zone layout markers"
  }
  if ($pjs -notmatch 'PULSE_LAYOUT_ANCHOR_3cab212') {
    throw "pulse_v5.js missing PULSE_LAYOUT_ANCHOR_3cab212 — wrong/old tree"
  }
  Write-Host '[ok] pulse layout = 一行五框 × 上下兩區 (5col-2zone + ANCHOR_3cab212)'
}

function Wait-TipServer {
  Write-Host '[wait] tip server health'
  for ($i = 1; $i -le 30; $i++) {
    try {
      $h = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
      $j = $h.Content | ConvertFrom-Json
      if ($j.tipUx -eq $true -or $j.ux -eq 'tip') {
        Write-Host "[ok] /health tipUx=true (try $i) version=$($j.version)"
        return
      }
      Write-Host "[warn] /health up but tipUx missing (try $i) — wrong server?"
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  throw "Server on :$Port is not tip UX. Check the 'Stock Terminal Server' console window for traceback."
}

function Assert-IndexIsTip {
  $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5
  $hdr = $resp.Headers['X-Stock-Terminal-UX']
  if ($hdr -ne 'tip') {
    Write-Host "[warn] X-Stock-Terminal-UX=$hdr (expected tip)"
  }
  $body = $resp.Content
  if ($body -notmatch 'shell_v5\.js' -or $body -notmatch 'pulse_v5\.js') {
    throw 'GET / did not return tip HTML modules — still serving OLD tree'
  }
  if ($body -notmatch 'st5-tip-boot') {
    throw 'GET / missing st5-tip-boot — still serving OLD HTML'
  }
  Write-Host '[ok] GET / is tip UX HTML'

  $pjs = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/src/ui/pulse_v5.js" -UseBasicParsing -TimeoutSec 5
  $ptxt = $pjs.Content
  if ($ptxt -match '4col-priority') {
    throw 'Server is still serving 4-col pulse_v5.js — free :18432 listener and retry'
  }
  if ($ptxt -notmatch '5col-2zone' -or $ptxt -notmatch 'repeat\(5,minmax\(0,1fr\)\)') {
    throw 'Server pulse_v5.js is not 5-col×2-zone — wrong tree / stale process'
  }
  if ($ptxt -notmatch 'PULSE_LAYOUT_ANCHOR_3cab212') {
    throw 'Server pulse_v5.js missing PULSE_LAYOUT_ANCHOR_3cab212 — STALE process. Kill listeners and retry.'
  }
  Write-Host '[ok] GET /src/ui/pulse_v5.js is 5col-2zone + ANCHOR_3cab212'
}

function Assert-ListenerMatchesPin {
  Write-Host '[check] :18432 listener uses pinned Stock Python (warn only if tooling)'
  try {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
      $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
      $path = $null
      if ($proc) { $path = $proc.Path }
      Write-Host "       listen PID $($c.OwningProcess) path=$path"
      if ($path -and (Test-ToolingPython $path)) {
        Write-Host "       WARN listener is tooling python — launcher should have pinned Stock Python"
      }
    }
  } catch {
    # Get-NetTCPConnection may be unavailable — non-fatal
  }
}

function Get-PorcelainPath([string]$Line) {
  if (-not $Line -or $Line.Length -lt 4) { return $null }
  # 改名與 Git 引號跳脫無法用一般字串安全還原，一律保留原本阻擋。
  if ($Line.Substring(0, 2) -match '[RCU]' -or $Line.Substring(3).StartsWith('"')) { return $null }
  return $Line.Substring(3).Replace('\', '/')
}

function Test-IgnorableUpdateDirt([string]$Line) {
  $runtimePath = Get-PorcelainPath $Line
  if (-not $runtimePath) { return $false }
  return ($runtimePath -match '^data/[^/]+\.(csv|sqlite3)$' -or
          $runtimePath -match '^data/[^/]*backup[^/]*\.json$' -or
          $runtimePath -match '^\.loop-engineering/')
}

function Assert-NoRuntimeUpdateOverlap([string[]]$RuntimeLines, [string]$TargetRef) {
  if ($RuntimeLines.Count -eq 0) { return }
  $incoming = @(git -c core.quotepath=false diff --no-renames --name-only HEAD $TargetRef -- data .loop-engineering)
  if ($LASTEXITCODE -ne 0) { throw '無法核對更新涉及的執行期資料，尚未切換版本。' }
  foreach ($line in $RuntimeLines) {
    $runtimePath = Get-PorcelainPath $line
    foreach ($changedPath in $incoming) {
      if ($changedPath -eq $runtimePath -or $changedPath.StartsWith($runtimePath.TrimEnd('/') + '/', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "更新也會改動本機資料 $runtimePath；請先明確保留或處理衝突，更新器不會暫存或丟棄變更。"
      }
    }
  }
}

Write-Banner

if ($Pull -or $UpdateOnly) {
  Write-Host "[update] fetch + fast-forward only: $TipBranch"
  $dirty = @(git -c core.quotepath=false status --porcelain 2>$null)
  if ($LASTEXITCODE -ne 0) { throw "git status failed" }
  $blocking = @($dirty | Where-Object { -not (Test-IgnorableUpdateDirt $_) })
  $runtimeDirty = @($dirty | Where-Object { Test-IgnorableUpdateDirt $_ })
  if ($blocking.Count -gt 0) {
    $blocking | ForEach-Object { Write-Host $_ }
    throw '工作區有非執行期資料的變更，請先明確保留；更新器不會暫存、重設或丟棄變更。'
  }
  git fetch origin $TipBranch
  if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
  Assert-NoRuntimeUpdateOverlap -RuntimeLines $runtimeDirty -TargetRef "origin/$TipBranch"
  if ($runtimeDirty.Count -gt 0) { Write-Host '[update] 保留本機行情 CSV／SQLite／備份資料，僅更新沒有資料衝突的程式。' }
  $cur = (git branch --show-current 2>$null).Trim()
  if ($cur -ne $TipBranch) {
    git show-ref --verify --quiet "refs/heads/$TipBranch"
    $localExists = ($LASTEXITCODE -eq 0)
    if ($localExists) {
      git switch $TipBranch
    } else {
      git switch --create $TipBranch --track "origin/$TipBranch"
    }
    if ($LASTEXITCODE -ne 0) { throw "git switch failed; no files were forced or reset" }
  }
  git merge --ff-only "origin/$TipBranch"
  if ($LASTEXITCODE -ne 0) { throw "fast-forward failed; updater left local work untouched" }
  $expect = (git rev-parse "origin/$TipBranch").Trim()
  $got = (git rev-parse HEAD).Trim()
  if ($got -ne $expect) {
    throw "update incomplete: HEAD=$got expected=$expect"
  }
  Write-Host "       synced HEAD=$($got.Substring(0,7))"
  if ($UpdateOnly) {
    Write-Host "[OK] update complete. Re-run START_TIP.cmd to build and launch."
    exit 0
  }
  # 更新後重入磁碟上的新腳本，讓本次啟動也使用新版的程序保護函式。
  Assert-LauncherBehavior -Path $PSCommandPath
  & $PSCommandPath -Worktree -RebuildOnly:$RebuildOnly
  exit $LASTEXITCODE
}

$Python = Resolve-StockPython
Write-Host " PYTHON: $Python"

Assert-TipBranch
$head = (git rev-parse --short HEAD)
Write-Host " HEAD: $head"

Write-Host "[build] `"$Python`" build_v2.py"
& $Python build_v2.py
if ($LASTEXITCODE -ne 0) { throw "build_v2.py failed (exit $LASTEXITCODE)" }
Assert-TipHtml

if ($RebuildOnly) {
  Write-Host '[done] rebuild only'
  exit 0
}

Stop-OwnedPortListeners -PortNum $Port -ReceiptPath $DevReceipt -OwnerRoot $Root

# Live console (NOT RedirectStandardOutput) — absolute PYTHON from pin.
$logDir = Join-Path $Root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logOut = Join-Path $logDir 'server_go_ps.out.log'
$logErr = Join-Path $logDir 'server_go_ps.err.log'

Write-Host "[start] Stock Terminal Server via pinned absolute python:"
Write-Host "        $Python"
Write-Host "        cwd=$Root"
Write-Host "        logs: $logOut / $logErr"

$launcher = Join-Path $logDir 'run_server_tip.cmd'
@(
  '@echo off'
  'chcp 65001 >nul'
  'title Stock Terminal Server v5 tip'
  "cd /d `"$Root`""
  'set ST_LAUNCHED_BY=go.ps1'
  "echo ============================================"
  "echo  Stock Terminal Server v5 tip"
  "echo  HEAD=$head"
  "echo  PYTHON=$Python"
  "echo  cwd=$Root"
  "echo  url=$Url"
  "echo ============================================"
  "echo."
  "`"$Python`" -u `"$(Join-Path $Root 'server\server.py')`""
  'echo.'
  'echo SERVER EXITED — window stays open so you can read the error.'
  'pause'
) | Set-Content -Path $launcher -Encoding ASCII

$p = Start-Process -FilePath $launcher `
  -WorkingDirectory $Root `
  -WindowStyle Normal `
  -PassThru
$launcherStartTicks = $p.StartTime.ToUniversalTime().Ticks
Write-Host "       launcher PID $($p.Id)"
Write-Host "       window title MUST be: Stock Terminal Server v5 tip"
Write-Host "       launcher script: $launcher"

Wait-TipServer
Assert-ListenerMatchesPin
$basePythonLines = @(& $Python -c "import sys; print(sys._base_executable)")
$basePythonExit = $LASTEXITCODE
if ($basePythonExit -ne 0 -or $basePythonLines.Count -ne 1 -or -not $basePythonLines[0]) { throw '無法讀取釘選 Python 的基礎執行檔身分。' }
Write-DevServerReceipt -PortNum $Port -ReceiptPath $DevReceipt -OwnerRoot $Root -ExpectedParent $p.Id -ExpectedParentTicks $launcherStartTicks -ExpectedPython $Python -ExpectedBasePython $basePythonLines[0].Trim() -ExpectedLauncher $launcher
Assert-IndexIsTip
Assert-ListenerMatchesPin

Write-Host "[open] $Url"
Start-Process $Url

Write-Host ''
Write-Host 'DONE.'
Write-Host "  HEAD=$head"
Write-Host "  PYTHON=$Python  (pinned in data\stock_python.path)"
Write-Host '  Server window title: Stock Terminal Server v5 tip'
Write-Host '  Browser: Ctrl+F5 → badge 實測 5+5'
Write-Host ''

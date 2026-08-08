# Stock Terminal v5.0 — tip UX only (PowerShell)
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 -Pull
#   powershell -ExecutionPolicy Bypass -File .\scripts\go.ps1 -RebuildOnly
param(
  [switch]$Pull,
  [switch]$RebuildOnly
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root 'build_v2.py'))) {
  $Root = (Get-Location).Path
}
Set-Location $Root

$TipBranch = 'cursor/st51-docs-ux-on-tip-3497'
$TipFile = Join-Path $Root 'TIP_BRANCH'
if (Test-Path $TipFile) {
  $TipBranch = (Get-Content $TipFile -Raw).Trim()
}
$Port = 18432
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

function Assert-TipBranch {
  $cur = (git branch --show-current 2>$null)
  Write-Host " branch: $cur"
  $legacy = @('main', 'master', 'cursor/http-client-pool-3497', 'cursor/range-period-change-b5cf')
  if ($legacy -contains $cur) {
    throw "BLOCK: current branch '$cur' is legacy. Run: powershell -File .\scripts\go.ps1 -Pull"
  }
}

function Stop-PortListeners([int]$PortNum) {
  Write-Host "[stop] free port $PortNum"
  try {
    Get-NetTCPConnection -LocalPort $PortNum -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique |
      ForEach-Object {
        Write-Host "       kill PID $_"
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
      }
  } catch {}
  # fallback via netstat (older Windows)
  $lines = netstat -ano 2>$null | Select-String ":$PortNum\s+.*LISTENING"
  foreach ($ln in $lines) {
    $parts = ($ln.ToString() -split '\s+') | Where-Object { $_ -ne '' }
    $procId = $parts[-1]
    if ($procId -match '^\d+$') {
      Write-Host "       kill PID $procId (netstat)"
      Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
    }
  }
  Start-Sleep -Seconds 1
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

  # 版面契約：必須是一行五框（5col-2zone），禁止還停在 4 欄壓成兩框的舊改動
  $pulse = Join-Path $Root 'src\ui\pulse_v5.js'
  if (-not (Test-Path $pulse)) { throw "missing $pulse" }
  $pjs = Get-Content $pulse -Raw -Encoding UTF8
  if ($pjs -match '4col-priority' -or $pjs -match 'repeat\(4,minmax\(0,1fr\)\)') {
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
  for ($i = 1; $i -le 20; $i++) {
    try {
      $h = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
      $j = $h.Content | ConvertFrom-Json
      if ($j.tipUx -eq $true -or $j.ux -eq 'tip') {
        Write-Host "[ok] /health tipUx=true (try $i) version=$($j.version)"
        return
      }
      Write-Host "[warn] /health up but tipUx missing (try $i) — wrong server?"
    } catch {
      Start-Sleep -Milliseconds 400
    }
  }
  throw "Server on :$Port is not tip UX. Kill other python and retry."
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
    throw 'Server is still serving 4-col pulse_v5.js — kill ALL python on :18432 and retry'
  }
  if ($ptxt -notmatch '5col-2zone' -or $ptxt -notmatch 'repeat\(5,minmax\(0,1fr\)\)') {
    throw 'Server pulse_v5.js is not 5-col×2-zone — wrong tree / stale process'
  }
  if ($ptxt -notmatch 'PULSE_LAYOUT_ANCHOR_3cab212') {
    throw 'Server pulse_v5.js missing PULSE_LAYOUT_ANCHOR_3cab212 — STALE python still serving old tree. Kill ALL python.exe and retry.'
  }
  Write-Host '[ok] GET /src/ui/pulse_v5.js is 5col-2zone + ANCHOR_3cab212'
}

Write-Banner

if ($Pull) {
  Write-Host "[pull] fetch + hard reset $TipBranch (discard local HTML drift)"
  git fetch origin $TipBranch
  git checkout -B $TipBranch "origin/$TipBranch"
  git reset --hard "origin/$TipBranch"
  git checkout -- "src/ui/pulse_v5.js" "src/ui/shell_v5.js" "stock_terminal.html" "stock_terminal_v2.html" 2>$null
}

Assert-TipBranch
$head = (git rev-parse --short HEAD)
Write-Host " HEAD: $head"

Write-Host '[build] python build_v2.py'
python build_v2.py
Assert-TipHtml

if ($RebuildOnly) {
  Write-Host '[done] rebuild only'
  exit 0
}

Stop-PortListeners -PortNum $Port

Write-Host "[start] python server\server.py (cwd=$Root)"
$logDir = Join-Path $Root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logOut = Join-Path $logDir 'server_go_ps.out.log'
$logErr = Join-Path $logDir 'server_go_ps.err.log'
# PowerShell 禁止 stdout/stderr 導向同一檔；分開寫
$p = Start-Process -FilePath 'python' `
  -ArgumentList 'server\server.py' `
  -WorkingDirectory $Root `
  -WindowStyle Minimized `
  -RedirectStandardOutput $logOut `
  -RedirectStandardError $logErr `
  -PassThru
Write-Host "       server PID $($p.Id)"
Write-Host "       stdout=$logOut"
Write-Host "       stderr=$logErr"

Wait-TipServer
Assert-IndexIsTip

Write-Host "[open] $Url"
Start-Process $Url

Write-Host ''
Write-Host 'DONE. In browser (必看):'
Write-Host "  HEAD=$head"
Write-Host '  1) 關掉所有 localhost:18432 分頁（含小視窗）'
Write-Host '  2) URL = http://localhost:18432/#pulse'
Write-Host '  3) Ctrl+F5'
Write-Host '  4) 標題「市場總覽」旁必須出現藍標：實測 5+5'
Write-Host '  5) F12 Console 必須有: PULSE_LAYOUT_ANCHOR_3cab212 ... ok=true'
Write-Host '  6) 若仍兩框且沒有「實測 5+5」= 舊 JS／舊 python，執行:'
Write-Host '       Get-Process python* | Stop-Process -Force'
Write-Host '       然後重跑本腳本 -Pull'
Write-Host ''

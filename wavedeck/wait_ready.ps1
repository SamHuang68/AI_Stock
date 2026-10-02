# Wait until WaveDeck /health responds; write port to data/wavedeck.port
$ErrorActionPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot
$portFile = Join-Path $PSScriptRoot 'data\wavedeck.port'
$candidates = @(18433, 18765, 28765, 38433, 8765)
$deadline = (Get-Date).AddSeconds(25)

while ((Get-Date) -lt $deadline) {
  if (Test-Path $portFile) {
    $p = (Get-Content $portFile -Raw).Trim()
    if ($p -match '^\d+$' -and [int]$p -ge 1 -and [int]$p -le 65535 -and [int]$p -notin @(18434, 18435)) {
      try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$p/health" -TimeoutSec 1
        if ($r.StatusCode -eq 200) { exit 0 }
      } catch {}
    }
  }
  foreach ($p in $candidates) {
    try {
      $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$p/health" -TimeoutSec 1
      if ($r.StatusCode -eq 200) {
        Set-Content -Path $portFile -Value "$p" -Encoding ascii
        exit 0
      }
    } catch {}
  }
  Start-Sleep -Milliseconds 700
}
exit 1

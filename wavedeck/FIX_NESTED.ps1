# Fix accidental Stock_Terminal\wavedeck\wavedeck nesting from zip extract.
# Run from AI_Stock root:
#   powershell -ExecutionPolicy Bypass -File .\wavedeck\FIX_NESTED.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$nested = Join-Path $here 'wavedeck'
$root = Split-Path -Parent $here

Write-Host "AI_Stock : $root"
Write-Host "wavedeck : $here"
Write-Host "nested?  : $nested"

if (-not (Test-Path (Join-Path $nested 'run.py'))) {
  Write-Host 'No nested wavedeck\wavedeck — nothing to fix.'
  exit 0
}

Write-Host 'Found nested wavedeck\wavedeck. Flattening into parent wavedeck\ ...'
Get-ChildItem -Force $nested | ForEach-Object {
  $dest = Join-Path $here $_.Name
  if (Test-Path $dest) {
    if ($_.PSIsContainer) {
      Copy-Item -Recurse -Force $_.FullName\* $dest
    } else {
      Copy-Item -Force $_.FullName $dest
    }
  } else {
    Move-Item -Force $_.FullName $dest
  }
}
Remove-Item -Recurse -Force $nested
Write-Host 'Done. Run: .\START_WAVEDECK.cmd from AI_Stock root'

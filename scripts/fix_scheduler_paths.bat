@echo off
REM ============================================================
REM  fix_scheduler_paths.bat
REM  Re-points existing Stock scheduled tasks to the new
REM  scripts\ location (after P4b backend move).
REM  - Only updates tasks that already exist (skips the rest)
REM  - Keeps each task's existing schedule/trigger
REM  - Self-elevates to Administrator (needed to edit tasks)
REM ============================================================
setlocal

REM --- self-elevate if not admin ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "SCR=%~dp0"
echo Scripts folder: %SCR%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$map = @{ 'Stock_Chip_Daily_Snapshot'='daily_chip.bat'; 'Stock_Data_Daily_Backup'='daily_backup.bat'; 'Stock_Morning_Brief'='daily_morning_brief.bat'; 'Stock_ETF_Report_Email'='daily_etf_report.bat'; 'ETF_Daily_Snapshot'='daily_etf.bat' };" ^
  "foreach ($n in $map.Keys) {" ^
  "  $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue;" ^
  "  if ($t) {" ^
  "    $tgt = Join-Path $env:SCR $map[$n];" ^
  "    $a = New-ScheduledTaskAction -Execute $tgt;" ^
  "    try { Set-ScheduledTask -TaskName $n -Action $a | Out-Null; Write-Host ('  UPDATED  ' + $n + '  ->  ' + $tgt) }" ^
  "    catch { Write-Host ('  FAILED   ' + $n + '  : ' + $_.Exception.Message) }" ^
  "  } else { Write-Host ('  skip     ' + $n + '  (not installed)') }" ^
  "}"

echo.
echo Done. Press any key to close.
pause >nul

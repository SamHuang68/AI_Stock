@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ============================================
echo  Register Daily Chip Snapshot Task (v3.8)
echo  Mon-Fri 17:40 - runs chip_history_tracker.py
echo ============================================
echo.

set "TARGET=%~dp0daily_chip.bat"
echo Target: %TARGET%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Register-ScheduledTask -TaskName 'Stock_Chip_Daily_Snapshot' -Force " ^
  "-Action  (New-ScheduledTaskAction -Execute '%TARGET%') " ^
  "-Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 5:40pm) " ^
  "-Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 15))"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] Registration failed. Try running as Administrator.
    pause
    exit /b 1
)

echo.
echo [OK] Task registered. Verify:
echo   Get-ScheduledTask -TaskName "Stock_Chip_Daily_Snapshot"
echo.
echo Manual trigger now:
echo   Start-ScheduledTask -TaskName "Stock_Chip_Daily_Snapshot"
echo.
echo Remove later: schtasks /delete /tn "Stock_Chip_Daily_Snapshot" /f
echo.
pause

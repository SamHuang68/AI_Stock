@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ============================================
echo  Register Daily ETF Snapshot Task Scheduler
echo  Mon-Fri 19:00 - runs etf_delta_tracker.py
echo ============================================
echo.

REM Build absolute path to daily_etf.bat
set "TARGET=%~dp0daily_etf.bat"
echo Target: %TARGET%
echo.

REM Register via PowerShell (more reliable than schtasks for path quoting)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Register-ScheduledTask -TaskName 'ETF_Daily_Snapshot' -Force " ^
  "-Action  (New-ScheduledTaskAction -Execute '%TARGET%') " ^
  "-Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 7pm) " ^
  "-Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 15))"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] Registration failed.
    echo Try running this script as Administrator.
    pause
    exit /b 1
)

echo.
echo [OK] Task registered. Verify with:
echo   Get-ScheduledTask -TaskName "ETF_Daily_Snapshot"
echo.
echo Manual trigger now:
echo   Start-ScheduledTask -TaskName "ETF_Daily_Snapshot"
echo.
pause

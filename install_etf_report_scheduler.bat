@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo  Register Daily ETF Report Email (v3.8)
echo  Mon-Fri 18:30 - emails consensus report
echo  (server.py must be running; email set in alert_config.json)
echo ============================================
echo.

set "TARGET=%~dp0daily_etf_report.bat"
echo Target: %TARGET%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Register-ScheduledTask -TaskName 'Stock_ETF_Report_Email' -Force " ^
  "-Action  (New-ScheduledTaskAction -Execute '%TARGET%') " ^
  "-Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 6:30pm) " ^
  "-Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10))"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] Registration failed. Try running as Administrator.
    pause
    exit /b 1
)

echo.
echo [OK] Task registered. Verify:
echo   Get-ScheduledTask -TaskName "Stock_ETF_Report_Email"
echo.
echo Manual run now:  Start-ScheduledTask -TaskName "Stock_ETF_Report_Email"
echo Remove:          schtasks /delete /tn "Stock_ETF_Report_Email" /f
echo.
pause

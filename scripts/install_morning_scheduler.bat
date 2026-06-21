@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."
echo ============================================
echo  Register Daily TSMC Morning Brief (v3.8)
echo  Mon-Fri 07:30 - emails pre-market brief
echo  (server.py running + email set in alert_config.json)
echo ============================================
echo.
set "TARGET=%~dp0daily_morning_brief.bat"
echo Target: %TARGET%
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Register-ScheduledTask -TaskName 'Stock_Morning_Brief' -Force " ^
  "-Action  (New-ScheduledTaskAction -Execute '%TARGET%') " ^
  "-Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 7:30am) " ^
  "-Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10))"
if %ERRORLEVEL% NEQ 0 ( echo [FAIL] Try running as Administrator. & pause & exit /b 1 )
echo.
echo [OK] Task registered. Manual run: Start-ScheduledTask -TaskName "Stock_Morning_Brief"
echo Remove: schtasks /delete /tn "Stock_Morning_Brief" /f
echo.
pause

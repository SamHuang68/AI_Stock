@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ============================================
echo  Register Daily Data Backup Task (v3.9)
echo  Mon-Fri 18:00 - runs backup_data.py
echo ============================================
echo.

set "TARGET=%~dp0daily_backup.bat"
echo Target: %TARGET%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Register-ScheduledTask -TaskName 'Stock_Data_Daily_Backup' -Force " ^
  "-Action  (New-ScheduledTaskAction -Execute '%TARGET%') " ^
  "-Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 6:00pm) " ^
  "-Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10))"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] Registration failed. Try running as Administrator.
    pause
    exit /b 1
)

echo.
echo [OK] Task registered. Verify:
echo   Get-ScheduledTask -TaskName "Stock_Data_Daily_Backup"
echo.
echo Manual trigger now:
echo   Start-ScheduledTask -TaskName "Stock_Data_Daily_Backup"
echo.
echo Remove later: schtasks /delete /tn "Stock_Data_Daily_Backup" /f
echo.
pause

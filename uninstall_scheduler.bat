@echo off
chcp 65001 > nul
echo ============================================
echo  Remove Daily ETF Snapshot Task Scheduler
echo ============================================
echo.

powershell -NoProfile -Command "Unregister-ScheduledTask -TaskName 'ETF_Daily_Snapshot' -Confirm:$false -ErrorAction SilentlyContinue"

if %ERRORLEVEL% EQU 0 (
    echo [OK] Task removed.
) else (
    echo [INFO] Task not found or already removed.
)
echo.
pause

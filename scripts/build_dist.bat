@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0.."

echo ============================================
echo  Build Stock_Terminal distribution zip (v4.1)
echo ============================================
echo.

python scripts\build_dist.py
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] build_dist.py failed
    pause
    exit /b 1
)

echo.
echo Done. Share Stock_Terminal_v4.1.zip with anyone.
echo Recipient: unzip, then double-click scripts\go.bat
echo Optional: scripts\install_scheduler.bat / scripts\install_chip_scheduler.bat
echo Alerts: open the bell button to set Telegram/Email push (never share those configs).
echo.
pause

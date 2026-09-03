@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0.."

echo ============================================
echo  Build Stock_Terminal distribution zip (v5.0)
echo ============================================
echo.

python scripts\build_dist.py
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] build_dist.py failed
    pause
    exit /b 1
)

echo.
echo Done. Share these three files together:
echo   Stock_Terminal_v5.0.zip
echo   Stock_Terminal_v5.0.zip.sha256
echo   Stock_Terminal_v5.0.manifest.json
echo Recipient: unzip, read README.md, then double-click START_TIP.cmd
echo Optional: scripts\install_scheduler.bat / scripts\install_chip_scheduler.bat
echo Alerts: open the bell button to set Telegram/Email push (never share those configs).
echo.
pause

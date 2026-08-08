@echo off
chcp 65001 > nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

set "ST_VER=5.0"
if exist "VERSION" set /p ST_VER=<"VERSION"
for /f "tokens=* delims= " %%v in ("!ST_VER!") do set "ST_VER=%%v"

echo ============================================
echo  Build Stock_Terminal distribution zip (v!ST_VER!)
echo ============================================
echo.

python scripts\build_dist.py
if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] build_dist.py failed
    pause
    exit /b 1
)

echo.
echo Done. Share Stock_Terminal_v!ST_VER!.zip with anyone.
echo Recipient: unzip, then double-click scripts\go.bat
echo Optional: scripts\install_scheduler.bat / scripts\install_chip_scheduler.bat
echo Alerts: open the bell button to set Telegram/Email push (never share those configs).
echo.
pause

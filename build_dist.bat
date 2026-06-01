@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo  Build Stock_Terminal distribution zip (v2.0)
echo ============================================
echo.

set "ZIP=Stock_Terminal_v2.0.zip"
set "STAGE=Stock_Terminal"

REM Clean prior leftovers
if exist "%STAGE%" rmdir /s /q "%STAGE%"
if exist "%ZIP%"   del /q "%ZIP%"

mkdir "%STAGE%"
mkdir "%STAGE%\etf_history"

REM Build v2 first so stock_terminal_v2.html is fresh
if exist "stock_terminal.html" if exist "build_v2.py" (
    echo Building v2 ...
    python build_v2.py
    echo.
)

REM Files to bundle (skip user data: etf_history JSONs, logs, __pycache__)
REM Core
set FILES=README.md server.py etf_delta_tracker.py
REM v1 UI + launchers
set FILES=%FILES% stock_terminal.html start_terminal.bat
REM v2 UI + modules + launcher
set FILES=%FILES% stock_terminal_v2.html start_terminal_v2.bat build_v2.py
set FILES=%FILES% position_v2.js watch_v2.js info_v2.js pro_v2.js pattern_v2.js pattern_v3.js pattern_v3_test.html live_v2.js etf_v2.js mobile_v2.css etf_catalog.json
set FILES=%FILES% chip_v3.js heatmap_v3.js screener_v3.js ai_report_v3.js polish_v3.js
REM ETF tracker launchers + scheduler
set FILES=%FILES% run_tracker.bat daily_etf.bat
set FILES=%FILES% install_scheduler.bat uninstall_scheduler.bat

for %%F in (%FILES%) do (
    if exist "%%F" (
        copy /Y "%%F" "%STAGE%\" > nul
        echo + %%F
    ) else (
        echo [MISS] %%F not found
    )
)

> "%STAGE%\etf_history\README.txt" echo ETF holding snapshots will appear here after running etf_delta_tracker.py

echo.
echo Compressing %STAGE% to %ZIP% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -Path '%STAGE%' -DestinationPath '%ZIP%' -CompressionLevel Optimal -Force"

if %ERRORLEVEL% NEQ 0 (
    echo [FAIL] Compress-Archive failed
    rmdir /s /q "%STAGE%"
    pause
    exit /b 1
)

REM Cleanup staging folder
rmdir /s /q "%STAGE%"

if exist "%ZIP%" (
    echo.
    echo [OK] Built distribution zip:
    powershell -NoProfile -Command "Get-Item '%ZIP%' | Select-Object Name,Length,LastWriteTime | Format-List"
    echo.
    echo Contents:
    powershell -NoProfile -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path '%ZIP%').Path).Entries | Select-Object FullName, @{N='KB';E={[math]::Round($_.Length/1024,1)}} | Format-Table -AutoSize"
) else (
    echo [FAIL] zip not created
)

echo.
echo Done. Share %ZIP% with anyone.
echo Recipient: unzip, then double-click start_terminal_v2.bat for v2 (POS + WATCH).
echo            Or start_terminal.bat for v1 (chart-only).
echo.
pause

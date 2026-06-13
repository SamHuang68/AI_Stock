@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo  Build Stock_Terminal distribution zip (v3.9)
echo ============================================
echo.

set "ZIP=Stock_Terminal_v3.9.zip"
set "STAGE=Stock_Terminal"

REM Clean prior leftovers
if exist "%STAGE%" rmdir /s /q "%STAGE%"
if exist "%ZIP%"   del /q "%ZIP%"

mkdir "%STAGE%"
mkdir "%STAGE%\etf_history"

REM Build v2 first so stock_terminal_v2.html is fresh (embeds all v3.8 scripts)
if exist "stock_terminal.html" if exist "build_v2.py" (
    echo Building v2 ...
    python build_v2.py
    echo.
)

REM ---- Files to bundle (skip user data: etf_history/chip_history JSON, logs, __pycache__, alert_config/rules) ----
REM Core servers / trackers
set FILES=README.md server.py etf_delta_tracker.py chip_history_tracker.py alert_daemon.py etf_report_email.py etf_report.py watch_daemon.py daily_morning_brief.py
REM v1 UI + launcher
set FILES=%FILES% stock_terminal.html start_terminal.bat
REM v2/v3 UI + build + launchers
set FILES=%FILES% stock_terminal_v2.html start_terminal_v2.bat start_terminal_v3.bat build_v2.py rebuild_and_restart.bat restart_server.bat
REM v2 base modules
set FILES=%FILES% position_v2.js watch_v2.js info_v2.js pro_v2.js pattern_v2.js live_v2.js etf_v2.js mobile_v2.css etf_catalog.json
REM v3 modules (must match build_v2.py V2_SCRIPTS so v2.html scripts resolve)
set FILES=%FILES% volume_profile_v3.js pattern_v3.js pattern_v3_test.html chip_v3.js fundamental_v3.js
set FILES=%FILES% heatmap_v3.js screener_v3.js ai_report_v3.js polish_v3.js wl_live_v3.js
set FILES=%FILES% plan_history_v3.js plan_position_v3.js plan_v3.js pdf_import_v3.js pdf_export_v3.js peg_v3.js
set FILES=%FILES% alert_v3.js alert_push_v3.js backtest_v3.js backtest_ui_v3.js enhance_v3.js aftermarket_v3.js overnight_v3.js supplychain_v3.js valuation_v3.js marketflow_v3.js instrank_v3.js calendar_v3.js layout_v3.js etf_v3.js
REM v3.9 modules (multichart/hotkeys/spread/strategy builder+script/drawtools/screener3; macro_v3.js disabled but bundled dormant)
set FILES=%FILES% multichart_v3.js spread_v3.js hotkeys_v3.js strategy_builder_v3.js strategy_script_v3.js drawtools_v3.js screener3_v3.js macro_v3.js
REM ETF + chip tracker launchers + schedulers
set FILES=%FILES% run_tracker.bat daily_etf.bat daily_chip.bat daily_etf_report.bat daily_morning_brief.bat
set FILES=%FILES% install_scheduler.bat uninstall_scheduler.bat install_chip_scheduler.bat install_etf_report_scheduler.bat install_morning_scheduler.bat

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
echo Recipient: unzip, then double-click start_terminal_v3.bat (auto-builds v2 + opens).
echo Optional: install_scheduler.bat (ETF daily) / install_chip_scheduler.bat (chip daily).
echo Alerts: open the bell button to set Telegram/Email push.
echo.
pause

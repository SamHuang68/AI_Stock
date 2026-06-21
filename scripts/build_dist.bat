@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ============================================
echo  Build Stock_Terminal distribution zip (v3.9)
echo ============================================
echo.

set "ZIP=Stock_Terminal_v3.9.zip"
set "STAGE=Stock_Terminal"

REM Clean prior leftovers
if exist "%STAGE%" rmdir /s /q "%STAGE%"
if exist "%ZIP%"   del /q "%ZIP%"

REM Build v2 first so stock_terminal_v2.html is fresh
if exist "stock_terminal.html" if exist "build_v2.py" (
    echo Building v2 ...
    python build_v2.py
    echo.
)

mkdir "%STAGE%\data\etf_history"
mkdir "%STAGE%\data\chip_history"

echo Staging folder trees (src / server / scripts / docs) ...
REM Copy whole module/server/script/doc trees; skip caches, logs, node_modules
robocopy "src"     "%STAGE%\src"     /E /XD __pycache__ node_modules /XF *.pyc *.log /NFL /NDL /NJH /NJS /NC /NS /NP >nul
robocopy "server"  "%STAGE%\server"  /E /XD __pycache__ /XF *.pyc *.log         /NFL /NDL /NJH /NJS /NC /NS /NP >nul
robocopy "scripts" "%STAGE%\scripts" /E /XF *.log                               /NFL /NDL /NJH /NJS /NC /NS /NP >nul
robocopy "docs"    "%STAGE%\docs"    /E                                          /NFL /NDL /NJH /NJS /NC /NS /NP >nul

echo Staging root files ...
for %%F in (stock_terminal.html stock_terminal_v2.html build_v2.py build_order.py) do (
    if exist "%%F" ( copy /Y "%%F" "%STAGE%\" >nul & echo + %%F ) else ( echo [MISS] %%F )
)

REM Catalog only -- NO secrets (ai_key/alert_config/rules), NO history JSON
if exist "data\etf_catalog.json" ( copy /Y "data\etf_catalog.json" "%STAGE%\data\" >nul & echo + data\etf_catalog.json )
> "%STAGE%\data\etf_history\README.txt" echo ETF holding snapshots appear here after running server\etf_delta_tracker.py

REM Safety net: make sure no secret slipped into the stage
del /q "%STAGE%\data\ai_key.txt" "%STAGE%\data\alert_config.json" "%STAGE%\data\alert_rules.json" "%STAGE%\data\watch_rules.json" "%STAGE%\data\watch_state.json" "%STAGE%\data\draw_store.json" 2>nul

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
    powershell -NoProfile -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path '%ZIP%').Path).Entries | Where-Object { $_.Length -gt 0 } | Select-Object FullName, @{N='KB';E={[math]::Round($_.Length/1024,1)}} | Format-Table -AutoSize"
) else (
    echo [FAIL] zip not created
)

echo.
echo Done. Share %ZIP% with anyone.
echo Recipient: unzip, then double-click scripts\start_terminal_v3.bat (auto-builds v2 + opens).
echo Optional: scripts\install_scheduler.bat (ETF daily) / scripts\install_chip_scheduler.bat (chip daily).
echo Alerts: open the bell button to set Telegram/Email push.
echo.
pause

@echo off
REM Daily TSMC morning brief email (v3.8) - Mon-Fri 07:30
REM Needs server.py running on :18432 + alert_config.json email set
setlocal enabledelayedexpansion
chcp 65001 > nul
if defined ST_DATA_BINDING goto bound_runtime_refused
if defined ST_DATA_ROOT goto bound_runtime_refused
if defined ST_RUNTIME_ROLE goto bound_runtime_refused
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0assert_standalone_runtime.ps1" -CodeRoot "%~dp0.."
if errorlevel 1 goto bound_runtime_refused
cd /d "%~dp0.."
if not exist "logs" mkdir "logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set DATE_TAG=%%I
set LOG=logs\morning_%DATE_TAG%.log
echo === Run at %DATE% %TIME% === >> "%LOG%"
python daily_morning_brief.py >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo === Exit %RC% === >> "%LOG%"
forfiles /p "logs" /m "morning_*.log" /d -30 /c "cmd /c del @path" 2>nul
exit /b %RC%

:bound_runtime_refused
echo [拒絕] 綁定資料模式不允許獨立晨報；未建立或清理日誌，未啟動外送。
exit /b 2

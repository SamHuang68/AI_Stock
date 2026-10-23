@echo off
REM ===========================================================
REM  Daily chip snapshot - run by Task Scheduler (v3.8)
REM  Mon-Fri 17:40 (TWSE T86 institutional data posts after 17:30)
REM  Logs go to logs\chip_YYYY-MM-DD.log
REM ===========================================================
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
set LOG=logs\chip_%DATE_TAG%.log

echo === Run at %DATE% %TIME% === >> "%LOG%"
python server\chip_history_tracker.py >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo === Exit %RC% === >> "%LOG%"

REM Cleanup logs older than 30 days
forfiles /p "logs" /m "chip_*.log" /d -30 /c "cmd /c del @path" 2>nul

exit /b %RC%

:bound_runtime_refused
echo [拒絕] 綁定資料模式不允許獨立籌碼更新；未建立或清理日誌。
exit /b 2

@echo off
REM ===========================================================
REM  Daily ETF consensus report email (v3.8)
REM  Needs server.py running on :18432 + alert_config.json email set
REM  Logs to logs\etf_report_YYYY-MM-DD.log
REM ===========================================================
setlocal enabledelayedexpansion
if defined ST_DATA_BINDING goto bound_runtime_refused
if defined ST_DATA_ROOT goto bound_runtime_refused
if defined ST_RUNTIME_ROLE goto bound_runtime_refused
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0assert_standalone_runtime.ps1" -CodeRoot "%~dp0.."
if errorlevel 1 goto bound_runtime_refused
chcp 65001 > nul
cd /d "%~dp0.."

if not exist "logs" mkdir "logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set DATE_TAG=%%I
set LOG=logs\etf_report_%DATE_TAG%.log

echo === Run at %DATE% %TIME% === >> "%LOG%"
python etf_report_email.py >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo === Exit %RC% === >> "%LOG%"

forfiles /p "logs" /m "etf_report_*.log" /d -30 /c "cmd /c del @path" 2>nul
exit /b %RC%

:bound_runtime_refused
echo [REFUSED] Bound runtime: use the registered backend POST /etf-report/email.
echo No local report, log directory, email, or scheduled task was started.
exit /b 2

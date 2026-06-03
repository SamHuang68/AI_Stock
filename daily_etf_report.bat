@echo off
REM ===========================================================
REM  Daily ETF consensus report email (v3.8)
REM  Needs server.py running on :18432 + alert_config.json email set
REM  Logs to logs\etf_report_YYYY-MM-DD.log
REM ===========================================================
setlocal enabledelayedexpansion
chcp 65001 > nul
cd /d "%~dp0"

if not exist "logs" mkdir "logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set DATE_TAG=%%I
set LOG=logs\etf_report_%DATE_TAG%.log

echo === Run at %DATE% %TIME% === >> "%LOG%"
python etf_report_email.py >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo === Exit %RC% === >> "%LOG%"

forfiles /p "logs" /m "etf_report_*.log" /d -30 /c "cmd /c del @path" 2>nul
exit /b %RC%

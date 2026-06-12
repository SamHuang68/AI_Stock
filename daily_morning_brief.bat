@echo off
REM Daily TSMC morning brief email (v3.8) - Mon-Fri 07:30
REM Needs server.py running on :18432 + alert_config.json email set
setlocal enabledelayedexpansion
chcp 65001 > nul
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set DATE_TAG=%%I
set LOG=logs\morning_%DATE_TAG%.log
echo === Run at %DATE% %TIME% === >> "%LOG%"
python daily_morning_brief.py >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo === Exit %RC% === >> "%LOG%"
forfiles /p "logs" /m "morning_*.log" /d -30 /c "cmd /c del @path" 2>nul
exit /b %RC%

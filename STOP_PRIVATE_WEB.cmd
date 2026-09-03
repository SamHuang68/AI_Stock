@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo Stopping Private Web ST only. Local development ST :18432 is preserved.

if exist "data\private_web_host.pid" (
  set /p ST_WEB_PID=<"data\private_web_host.pid"
  if defined ST_WEB_PID taskkill /PID !ST_WEB_PID! /T /F >nul 2>&1
)

if exist "data\private_web_gateway.pid" (
  set /p ST_WEB_PID=<"data\private_web_gateway.pid"
  if defined ST_WEB_PID taskkill /PID !ST_WEB_PID! /T /F >nul 2>&1
)

for %%p in (18434 18435) do (
  for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%%p" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" taskkill /PID %%a /T /F >nul 2>&1
  )
)

del /q "data\private_web_gateway.pid" "data\private_web_host.pid" >nul 2>&1
echo Private Web ST stopped. Development ST :18432 was not touched.
exit /b 0

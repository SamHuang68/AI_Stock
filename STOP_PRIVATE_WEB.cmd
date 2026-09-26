@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo Stopping Private Web ST only. Local development ST :18432 is preserved.

rem The isolated-host supervisor restarts its gateway/backend as soon as they die,
rem so it has to go first. Its pid file lives in whichever copy started it: this
rem folder (dev-linked) or the promoted production copy, so check both. A pid file
rem can outlive its process (e.g. a reboot), so only a live python.exe is killed.
for %%d in ("%~dp0." "%LOCALAPPDATA%\StockTerminalPrivateWeb\current") do (
  if exist "%%~d\data\private_web_host.pid" (
    set "ST_WEB_PID="
    set /p ST_WEB_PID=<"%%~d\data\private_web_host.pid"
    if defined ST_WEB_PID (
      for /f "tokens=1" %%i in ('tasklist /FI "PID eq !ST_WEB_PID!" /NH 2^>nul') do (
        if /I "%%i"=="python.exe" taskkill /PID !ST_WEB_PID! /T /F >nul 2>&1
        if /I "%%i"=="pythonw.exe" taskkill /PID !ST_WEB_PID! /T /F >nul 2>&1
      )
    )
    del /q "%%~d\data\private_web_host.pid" >nul 2>&1
  )
)

rem A supervisor started from any other install root has no pid file here:
rem match its command line instead (never the development server.py).
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'py*' -and $_.CommandLine -like '*private_web_host.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

for %%d in ("%~dp0." "%LOCALAPPDATA%\StockTerminalPrivateWeb\current") do (
  if exist "%%~d\data\private_web_gateway.pid" (
    set "ST_WEB_PID="
    set /p ST_WEB_PID=<"%%~d\data\private_web_gateway.pid"
    if defined ST_WEB_PID (
      for /f "tokens=1" %%i in ('tasklist /FI "PID eq !ST_WEB_PID!" /NH 2^>nul') do (
        if /I "%%i"=="python.exe" taskkill /PID !ST_WEB_PID! /T /F >nul 2>&1
        if /I "%%i"=="pythonw.exe" taskkill /PID !ST_WEB_PID! /T /F >nul 2>&1
      )
    )
    del /q "%%~d\data\private_web_gateway.pid" >nul 2>&1
  )
)

for %%p in (18434 18435) do (
  for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%%p" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" taskkill /PID %%a /T /F >nul 2>&1
  )
)

rem Confirm nothing came back on the private ports.
ping -n 3 127.0.0.1 >nul
set "ST_WEB_LEFT="
for %%p in (18434 18435) do (
  for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%%p" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" set "ST_WEB_LEFT=!ST_WEB_LEFT! %%p(pid %%a)"
  )
)
if defined ST_WEB_LEFT (
  echo [WARN] Still listening:!ST_WEB_LEFT!
  echo        Close that window, or run: taskkill /PID ^<pid^> /T /F
  exit /b 1
)

echo Private Web ST stopped. Development ST :18432 was not touched.
exit /b 0

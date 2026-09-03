@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo 正在停止 Private Web ST；本機開發用 ST :18432 會保留。

call :stop_owned_pid "data\private_web_host.pid" "private_web_host.py"
call :stop_owned_pid "data\private_web_gateway.pid" "private_web_gateway.py"

del /q "data\private_web_gateway.pid" "data\private_web_host.pid" >nul 2>&1
echo Private Web ST 已停止；未變更本機開發用 ST :18432。
exit /b 0

:stop_owned_pid
set "ST_WEB_PID_FILE=%~1"
set "ST_WEB_PROCESS_MARKER=%~2"
if not exist "%ST_WEB_PID_FILE%" exit /b 0
set "ST_WEB_PID="
set /p ST_WEB_PID=<"%ST_WEB_PID_FILE%"
if not defined ST_WEB_PID exit /b 0

REM 安全失敗：過期或重複使用的 PID 不得終止 WaveDeck 或其他程式。
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$value = 0;" ^
  "if (-not [int]::TryParse($env:ST_WEB_PID, [ref]$value)) { exit 2 };" ^
  "$proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $value) -ErrorAction SilentlyContinue;" ^
  "if (-not $proc) { exit 3 };" ^
  "if ([string]$proc.CommandLine -notlike ('*' + $env:ST_WEB_PROCESS_MARKER + '*')) { exit 4 };" ^
  "exit 0"
if errorlevel 1 (
  echo [WARN] 略過不符合 Private Web 身分的 PID !ST_WEB_PID!。
  exit /b 0
)

taskkill /PID !ST_WEB_PID! /T /F >nul 2>&1
exit /b 0

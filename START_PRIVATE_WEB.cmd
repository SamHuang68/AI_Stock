@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "ST_WEB_PYTHON="
if exist "data\stock_python.path" set /p ST_WEB_PYTHON=<"data\stock_python.path"
if defined ST_WEB_PYTHON if not exist "!ST_WEB_PYTHON!" set "ST_WEB_PYTHON="
if not defined ST_WEB_PYTHON for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "ST_WEB_PYTHON=%%P"
if not defined ST_WEB_PYTHON (
  echo [FAIL] Python 3 not found. Start ST once with START_TIP.cmd first.
  pause
  exit /b 1
)

if not exist "data\private_web_owner.token" (
  echo [setup] Creating local Private Web ST tokens...
  "!ST_WEB_PYTHON!" "scripts\setup_private_web.py"
  if errorlevel 1 (
    pause
    exit /b 1
  )
  echo Save the owner token shown above in your password manager.
  pause
)

"!ST_WEB_PYTHON!" -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:18434/gateway/health',timeout=2)); raise SystemExit(0 if d.get('gateway')=='private-web' else 1)" >nul 2>&1
if not errorlevel 1 (
  echo ============================================================
  echo  Private Web ST is already running.
  echo  Web:      http://127.0.0.1:18434/
  echo  No second gateway was started.
  echo  To switch modes, run STOP_PRIVATE_WEB.cmd first.
  echo ============================================================
  exit /b 0
)

echo ============================================================
echo  Private Web ST - development-linked mode
echo  Web:      http://127.0.0.1:18434/
echo  Backend:  http://127.0.0.1:18432/  ^(existing local ST^)
echo  Login:    user owner + owner token
echo  Stop:     Ctrl+C
echo ============================================================
echo Start START_TIP.cmd first if the gateway health says upstream=false.
echo.
"!ST_WEB_PYTHON!" -u "server\private_web_gateway.py"
exit /b !ERRORLEVEL!

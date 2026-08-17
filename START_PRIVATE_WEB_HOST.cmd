@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "ST_WEB_PYTHON="
if exist "data\stock_python.path" set /p ST_WEB_PYTHON=<"data\stock_python.path"
if defined ST_WEB_PYTHON if not exist "!ST_WEB_PYTHON!" set "ST_WEB_PYTHON="
if not defined ST_WEB_PYTHON for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "ST_WEB_PYTHON=%%P"
if not defined ST_WEB_PYTHON (
  echo [FAIL] Python 3 not found.
  pause
  exit /b 1
)

if not exist "data\private_web_owner.token" (
  "!ST_WEB_PYTHON!" "scripts\setup_private_web.py"
  if errorlevel 1 (
    pause
    exit /b 1
  )
  echo Save the owner token shown above in your password manager.
  pause
)

echo ============================================================
echo  Private Web ST - isolated host mode
echo  Gateway:  http://127.0.0.1:18434/
echo  Backend:  http://127.0.0.1:18435/  ^(production-only^)
echo  Local development ST remains available on :18432.
echo ============================================================
echo.
"!ST_WEB_PYTHON!" -u "scripts\private_web_host.py"
exit /b !ERRORLEVEL!

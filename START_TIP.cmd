@echo off
REM ============================================================
REM  Stock Terminal tip UX — DOUBLE-CLICK THIS FILE
REM  Forces git tip branch, frees :18432 only, then go.ps1
REM  (go.ps1 pins absolute Stock Python — never bare PATH python).
REM ============================================================
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not exist "build_v2.py" (
  echo [FAIL] START_TIP.cmd must sit in the AI_Stock repo root.
  echo        Current: %CD%
  pause
  exit /b 1
)

echo.
echo ============================================
echo  START_TIP — free :18432 + pull tip + go.ps1
echo  repo: %CD%
echo ============================================
echo.

echo [0] free port 18432 only (do NOT kill every python.exe on the PC)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":18432" ^| findstr "LISTENING"') do (
  echo      kill port 18432 PID %%a
  taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [1] git fetch + hard reset tip branch
set "TIP_BRANCH=cursor/st51-docs-ux-on-tip-3497"
if exist "TIP_BRANCH" set /p TIP_BRANCH=<TIP_BRANCH
for /f "tokens=* delims= " %%v in ("!TIP_BRANCH!") do set "TIP_BRANCH=%%v"
git fetch origin !TIP_BRANCH!
if errorlevel 1 (
  echo [FAIL] git fetch failed
  pause
  exit /b 1
)
REM -f discards local stock_terminal*.html so checkout cannot abort and leave stale HEAD
git checkout -f -B !TIP_BRANCH! origin/!TIP_BRANCH!
if errorlevel 1 (
  echo [FAIL] git checkout -f failed
  pause
  exit /b 1
)
git reset --hard origin/!TIP_BRANCH!
if errorlevel 1 (
  echo [FAIL] git reset failed
  pause
  exit /b 1
)

echo [2] verify new go.ps1 is on disk
findstr /C:"Resolve-StockPython" "scripts\go.ps1" >nul
if errorlevel 1 (
  echo [FAIL] scripts\go.ps1 missing Resolve-StockPython — pull did not update files.
  echo        Check you are in C:\Users\Sam\AI_Stock and remote is SamHuang68/AI_Stock.
  pause
  exit /b 1
)
findstr /C:"PULSE_LAYOUT_ANCHOR_3cab212" "src\ui\pulse_v5.js" >nul
if errorlevel 1 (
  echo [FAIL] pulse_v5.js missing layout anchor — wrong tree.
  pause
  exit /b 1
)
for /f %%h in ('git rev-parse --short HEAD') do set "HEAD=%%h"
echo      HEAD=!HEAD!  go.ps1 OK  pulse anchor OK

echo [3] launch scripts\go.ps1  (no -Pull; already reset above)
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\go.ps1"
set "RC=!ERRORLEVEL!"
echo.
echo go.ps1 exit=!RC!
echo If browser still 兩框: open logs\SERVER_BOOT.txt and http://127.0.0.1:18432/health
echo Server window title must be: Stock Terminal Server v5 tip
echo Browser badge must show: 實測 5+5
echo.
pause
exit /b !RC!

@echo off
REM ============================================================
REM  Stock Terminal tip UX — DOUBLE-CLICK THIS FILE
REM  Safe local launch: frees :18432 only, then go.ps1.
REM  It never changes Git state or discards local work.
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

echo [1] preserve Git state (no fetch, checkout, or reset)
for /f %%h in ('git rev-parse --short HEAD 2^>nul') do set "HEAD=%%h"
git status --short
echo      HEAD=!HEAD!
echo      To update deliberately: git fetch origin ^&^& git pull --ff-only

echo [2] verify launcher files are on disk
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
echo      go.ps1 OK  pulse anchor OK

echo [3] launch scripts\go.ps1
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

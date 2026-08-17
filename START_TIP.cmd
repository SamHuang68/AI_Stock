@echo off
REM Stock Terminal safe local launcher. ASCII-only compatibility entrypoint.
REM It never fetches, checks out, resets, stashes, or discards Git work.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not exist "build_v2.py" (
  echo [FAIL] START_TIP.cmd must be in the AI_Stock repository root.
  pause
  exit /b 1
)

echo.
echo ============================================
echo  START_TIP - safe local launch on port 18432
echo  repo: %CD%
echo ============================================
echo.

echo [0] Free port 18432 only.
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":18432" ^| findstr "LISTENING"') do (
  echo      stop PID %%a
  taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [1] Preserve Git state.
git status --short
echo      To update safely: powershell -File .\scripts\go.ps1 -UpdateOnly

echo [2] Verify launcher and TIP layout.
findstr /C:"Resolve-StockPython" "scripts\go.ps1" >nul
if errorlevel 1 (
  echo [FAIL] scripts\go.ps1 is missing the pinned Python resolver.
  pause
  exit /b 1
)
findstr /C:"PULSE_LAYOUT_ANCHOR_3cab212" "src\ui\pulse_v5.js" >nul
if errorlevel 1 (
  echo [FAIL] pulse_v5.js is missing the required layout anchor.
  pause
  exit /b 1
)

echo [3] Launch through the canonical PowerShell entrypoint.
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\go.ps1"
set "RC=!ERRORLEVEL!"
echo.
echo go.ps1 exit=!RC!
pause
exit /b !RC!

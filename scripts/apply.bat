@echo off
REM ============================================================
REM  強制套用指定遠端分支（解決「修正沒 apply」）
REM  用法（在專案根目錄）:
REM    scripts\apply.bat
REM    scripts\apply.bat cursor/mktcap-fix-4e66
REM ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "BR=%~1"
if "%BR%"=="" set "BR=cursor/market-fund-blank-4e66"

echo.
echo === APPLY %BR% ===
echo.

echo [1/5] stash local dirty files (含 stock_terminal_v2.html)
git stash push -u -m "auto-stash before apply %BR%" >nul 2>&1

echo [2/5] fetch + force checkout remote branch
git fetch origin
if errorlevel 1 (
  echo [FAIL] git fetch failed
  pause
  exit /b 1
)
git checkout -B "%BR%" "origin/%BR%"
if errorlevel 1 (
  echo [FAIL] checkout %BR% failed
  pause
  exit /b 1
)

echo [3/5] rebuild stock_terminal_v2.html
python build_v2.py
if errorlevel 1 (
  echo [FAIL] build_v2.py failed
  pause
  exit /b 1
)

echo [4/5] restart server :18432
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18432" ^| findstr "LISTENING"') do (
  echo   kill PID %%a
  taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul
start "Stock Terminal Server" /MIN cmd /c "python server\server.py"
timeout /t 2 /nobreak >nul

echo [5/5] open browser
start "" "http://localhost:18432/stock_terminal_v2.html"

echo.
echo Done. Now on:
git branch --show-current
git rev-parse --short HEAD
echo.
echo 請 Ctrl+F5。確認 badge tech·387；^TWII／融資維持應有「大盤體質」評分
echo.
pause
endlocal

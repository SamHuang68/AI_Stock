@echo off
REM ============================================================
REM  強制套用指定遠端分支（解決「修正沒 apply」）
REM  用法（在專案根目錄）:
REM    scripts\apply.bat
REM    scripts\apply.bat cursor/share-dist-readme-4e66
REM
REM  注意：checkout 會覆寫磁碟上的本腳本；因此 checkout 成功後
REM  必須用 --continue 重新啟動，避免 cmd 讀到錯位內容而假失敗。
REM ============================================================
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0.."

set "BR=%~1"
set "PHASE=%~2"

REM 預設：含大盤體質／融資週期／TDCC 集中度／README＋分享打包的最新 tip
if "%BR%"=="" set "BR=cursor/share-dist-readme-4e66"

REM ---------- phase 2: rebuild / restart（checkout 之後的新檔）----------
if /I "%PHASE%"=="--continue" goto :CONTINUE

echo.
echo === APPLY %BR% ===
echo.

echo [1/5] stash local dirty files (含 stock_terminal_v2.html)
git stash push -u -m "auto-stash before apply %BR%" >nul 2>&1

echo [2/5] fetch + force checkout remote branch
git fetch origin
if not "%ERRORLEVEL%"=="0" (
  echo [FAIL] git fetch failed  ^(exit %ERRORLEVEL%^)
  pause
  exit /b 1
)

git checkout -B "%BR%" "origin/%BR%"
if not "%ERRORLEVEL%"=="0" (
  echo [FAIL] checkout %BR% failed  ^(exit %ERRORLEVEL%^)
  pause
  exit /b 1
)

echo        checked out OK — re-launch script for rebuild ^(avoid bat self-replace bug^)
REM checkout 已可能改寫 apply.bat；用 call 重跑新版本的後續步驟
call "%~dp0apply.bat" "%BR%" --continue
set "EC=%ERRORLEVEL%"
exit /b %EC%

:CONTINUE
echo [3/5] rebuild stock_terminal_v2.html
python build_v2.py
if not "%ERRORLEVEL%"=="0" (
  echo [FAIL] build_v2.py failed  ^(exit %ERRORLEVEL%^)
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
echo 請 Ctrl+F5。完整 tip：大盤／市場 tab、融資週期、TDCC 集中度、分享打包腳本。
echo.
pause
endlocal
exit /b 0

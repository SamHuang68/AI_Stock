@echo off
REM ============================================================
REM  Stock Terminal — sole local launch / update script
REM ------------------------------------------------------------
REM  Usage:
REM    scripts\go.bat                 rebuild + restart + browser
REM    scripts\go.bat pull            git pull, then same
REM    scripts\go.bat pull <branch>   checkout branch + pull + same
REM    scripts\go.bat rebuild         rebuild + restart (no browser)
REM
REM  Prefer scripts\apply.bat <branch> when switching long-lived
REM  feature tips (e.g. housekeeping / range-period-change).
REM
REM  NOTE: avoid Chinese / UTF-8 inside "if (...)" blocks — cmd.exe
REM  can mis-parse multi-byte bytes as ")" and corrupt the script.
REM ============================================================
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

set "MODE=%~1"
set "TARGET_BRANCH=%~2"
if "%MODE%"=="" set "MODE=run"
set "OPEN_BROWSER=1"
if /I "%MODE%"=="rebuild" set "OPEN_BROWSER=0"

echo.
echo ============================================
echo  Stock Terminal v4.1
echo  http://localhost:18432/stock_terminal_v2.html
echo ============================================
echo.
for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%b"
if defined CUR_BRANCH echo  branch: !CUR_BRANCH!
echo.

if /I not "%MODE%"=="pull" goto SKIP_PULL

echo [1/4] git fetch / pull

REM stash any dirty tracked files so checkout/pull is never blocked
set "_DIRTY=0"
git diff --quiet 2>nul
if errorlevel 1 set "_DIRTY=1"
git diff --cached --quiet 2>nul
if errorlevel 1 set "_DIRTY=1"
if "!_DIRTY!"=="0" goto AFTER_STASH
echo        stash local changes (data / html / ...)
git stash push -m "auto: go.bat pull before switch"
if errorlevel 1 goto FAIL_STASH
:AFTER_STASH

git fetch origin
if errorlevel 1 goto FAIL_FETCH

if "%TARGET_BRANCH%"=="" goto AFTER_CHECKOUT
echo        checkout %TARGET_BRANCH%
git checkout "%TARGET_BRANCH%"
if errorlevel 1 goto FAIL_CHECKOUT
:AFTER_CHECKOUT

git pull --ff-only
if errorlevel 1 goto FAIL_PULL

for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%b"
if defined CUR_BRANCH echo        now on: !CUR_BRANCH!
echo.

REM After branch switch, re-enter THIS script from disk so later steps
REM always use the go.bat belonging to the checked-out branch.
echo        re-launch go.bat from checked-out branch...
call "%~dp0go.bat" run
exit /b %ERRORLEVEL%

:SKIP_PULL
echo [1/4] skip git pull  (use: scripts\go.bat pull)
echo.

echo [2/4] build_v2.py
python build_v2.py
if errorlevel 1 goto FAIL_BUILD
echo.

echo [3/4] restart server on :18432
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18432" ^| findstr "LISTENING"') do (
    echo        kill PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul
start "Stock Terminal Server" /MIN cmd /c "python server\server.py"
timeout /t 2 /nobreak >nul
echo.

echo [4/4] done
if "%OPEN_BROWSER%"=="1" start "" "http://localhost:18432/stock_terminal_v2.html"

echo.
echo  Opened. Press Ctrl+F5 to hard-reload.
echo  Next AI update:  scripts\go.bat pull
echo  Or force tip:    scripts\apply.bat cursor/range-period-change-b5cf
echo.
pause
endlocal
exit /b 0

:FAIL_STASH
echo [FAIL] git stash failed. Try: git stash push -m "manual"
pause
exit /b 1

:FAIL_FETCH
echo [FAIL] git fetch failed. Check network / credentials.
pause
exit /b 1

:FAIL_CHECKOUT
echo [FAIL] git checkout %TARGET_BRANCH% failed.
echo        Try: git stash push -m "manual before switch"
echo             scripts\go.bat pull %TARGET_BRANCH%
pause
exit /b 1

:FAIL_PULL
echo [FAIL] git pull failed. Resolve conflicts or check network.
echo        Example: scripts\go.bat pull cursor/range-period-change-b5cf
pause
exit /b 1

:FAIL_BUILD
echo [FAIL] build_v2.py failed
pause
exit /b 1

@echo off
REM ============================================================
REM  Stock Terminal — sole local launch / update script
REM ------------------------------------------------------------
REM  Usage:
REM    scripts\go.bat                 rebuild + restart + browser
REM    scripts\go.bat pull            git pull, then same
REM    scripts\go.bat pull <branch>   checkout branch + pull + same
REM    scripts\go.bat rebuild         rebuild + restart - no browser
REM
REM  Prefer scripts\apply.bat <branch> when switching long-lived tips.
REM
REM  NOTE: avoid Chinese / UTF-8 inside "if (...)" blocks — cmd.exe
REM  can mis-parse multi-byte bytes as ")" and corrupt the script.
REM  Also avoid "(" ")" in echo text — mid-pull self-replace can
REM  desync the parser and treat echo tails as commands.
REM
REM  Windows caveats handled here:
REM  1) git checkout may DELETE this running .bat on a stale branch
REM  2) git pull may OVERWRITE this running .bat mid-execution
REM  Pull mode always copies to %%TEMP%% first, does git there,
REM  then starts a FRESH cmd.exe for scripts\go.bat run.
REM ============================================================
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "MODE=%~1"
set "TARGET_BRANCH=%~2"
set "FROM_TEMP=%~3"
set "REPO_ROOT=%~4"
if "%MODE%"=="" set "MODE=run"
set "OPEN_BROWSER=1"
if /I "%MODE%"=="rebuild" set "OPEN_BROWSER=0"

REM Resolve repo root
if defined REPO_ROOT goto HAVE_ROOT
cd /d "%~dp0.."
if errorlevel 1 goto FAIL_CD
set "REPO_ROOT=%CD%"
goto AFTER_ROOT
:HAVE_ROOT
cd /d "%REPO_ROOT%"
if errorlevel 1 goto FAIL_CD
:AFTER_ROOT

echo.
echo ============================================
echo  Stock Terminal v4.1
echo  http://localhost:18432/stock_terminal_v2.html
echo ============================================
echo.
echo  repo: %REPO_ROOT%
for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%b"
if defined CUR_BRANCH echo  branch: !CUR_BRANCH!
echo.

if /I not "%MODE%"=="pull" goto SKIP_PULL

REM ---- pull mode: MUST leave the in-repo file before git ops ----
if /I "%FROM_TEMP%"=="__from_temp__" goto PULL_BODY

REM Resolve TEMP with fallbacks - empty TEMP caused copy/call "" failures
if not defined TEMP if defined TMP set "TEMP=%TMP%"
if not defined TEMP if defined LOCALAPPDATA set "TEMP=%LOCALAPPDATA%\Temp"
if not defined TEMP set "TEMP=%USERPROFILE%\AppData\Local\Temp"
if not defined TEMP goto FAIL_TEMP_COPY
if not exist "%TEMP%\" mkdir "%TEMP%" >nul 2>&1

set "GO_TMP=%TEMP%\ai_stock_go.bat"
echo [1/4] prepare pull - copy go.bat to TEMP then continue
copy /Y "%REPO_ROOT%\scripts\go.bat" "%GO_TMP%" >nul
if errorlevel 1 goto FAIL_TEMP_COPY
if not exist "%GO_TMP%" goto FAIL_TEMP_COPY

REM Fresh cmd so this in-repo script can be overwritten safely by pull
cmd /c ""%GO_TMP%" pull "%TARGET_BRANCH%" __from_temp__ "%REPO_ROOT%""
set "_RC=%ERRORLEVEL%"
endlocal & exit /b %_RC%

:PULL_BODY
echo [1/4] git fetch / pull
cd /d "%REPO_ROOT%"
if errorlevel 1 goto FAIL_CD

REM stash any dirty tracked files so checkout/pull is never blocked
set "_DIRTY=0"
git diff --quiet 2>nul
if errorlevel 1 set "_DIRTY=1"
git diff --cached --quiet 2>nul
if errorlevel 1 set "_DIRTY=1"
if "!_DIRTY!"=="0" goto AFTER_STASH
echo        stash local changes - data / html / ...
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

if "%TARGET_BRANCH%"=="" goto PULL_CURRENT
echo        fast-forward to origin/%TARGET_BRANCH%
git merge --ff-only "origin/%TARGET_BRANCH%"
if errorlevel 1 goto FAIL_PULL
goto AFTER_PULL

:PULL_CURRENT
git pull --ff-only
if errorlevel 1 goto FAIL_PULL

:AFTER_PULL
for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%b"
if defined CUR_BRANCH echo        now on: !CUR_BRANCH!
echo.

if not exist "%REPO_ROOT%\scripts\go.bat" goto FAIL_MISSING_GO
echo        start fresh scripts\go.bat run from updated tree...
REM Fresh process - never "call" a file that pull may have just rewritten under us
cmd /c ""%REPO_ROOT%\scripts\go.bat" run"
exit /b %ERRORLEVEL%

:SKIP_PULL
echo [1/4] skip git pull - use: scripts\go.bat pull
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

:FAIL_CD
echo [FAIL] cannot cd to repo root.
echo        REPO_ROOT=%REPO_ROOT%
pause
exit /b 1

:FAIL_TEMP_COPY
echo [FAIL] cannot stage go.bat in TEMP.
echo        TEMP=%TEMP%
echo        Manual recovery - code already pulled? Just run:
echo          scripts\go.bat
pause
exit /b 1

:FAIL_MISSING_GO
echo [FAIL] scripts\go.bat missing after pull/checkout.
echo        Manual recovery:
echo          git merge --ff-only origin/main
echo          scripts\go.bat
pause
exit /b 1

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
echo [FAIL] git pull / fast-forward failed.
echo        Manual recovery if stuck behind origin/main:
echo          git checkout main
echo          git merge --ff-only origin/main
echo          scripts\go.bat
pause
exit /b 1

:FAIL_BUILD
echo [FAIL] build_v2.py failed
pause
exit /b 1

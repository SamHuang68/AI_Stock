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

REM ---- Tip UX only: never silently fall back to main / pre-tip branches ----
set "TIP_BRANCH=cursor/st51-docs-ux-on-tip-3497"
if exist "%REPO_ROOT%\TIP_BRANCH" (
  set /p TIP_BRANCH=<"%REPO_ROOT%\TIP_BRANCH"
)
for /f "tokens=* delims= " %%v in ("!TIP_BRANCH!") do set "TIP_BRANCH=%%v"

set "ST_VER=5.0"
if exist "%REPO_ROOT%\VERSION" (
  set /p ST_VER=<"%REPO_ROOT%\VERSION"
)
for /f "tokens=* delims= " %%v in ("!ST_VER!") do set "ST_VER=%%v"

echo.
echo ============================================
echo  Stock Terminal v!ST_VER!  - tip UX
echo  http://localhost:18432/#pulse
echo ============================================
echo.
echo  repo: %REPO_ROOT%
echo  tip:  !TIP_BRANCH!
for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%b"
if defined CUR_BRANCH echo  branch: !CUR_BRANCH!
echo.

REM pull mode recovers FROM legacy -> tip. run/rebuild while ON legacy is blocked.
if /I "%MODE%"=="pull" goto AFTER_CUR_GUARD
if /I "%FORCE_LEGACY%"=="1" goto AFTER_CUR_GUARD
if /I "!CUR_BRANCH!"=="main" goto FAIL_LEGACY_CURRENT
if /I "!CUR_BRANCH!"=="master" goto FAIL_LEGACY_CURRENT
if /I "!CUR_BRANCH!"=="cursor/http-client-pool-3497" goto FAIL_LEGACY_CURRENT
:AFTER_CUR_GUARD

if /I not "%MODE%"=="pull" goto SKIP_PULL

REM pull with empty target -> always tip UX branch
if "%TARGET_BRANCH%"=="" set "TARGET_BRANCH=!TIP_BRANCH!"

REM Block checkout targets that drop tip UX
if /I "%FORCE_LEGACY%"=="1" goto AFTER_LEGACY_GUARD
if /I "%TARGET_BRANCH%"=="main" goto FAIL_LEGACY_TARGET
if /I "%TARGET_BRANCH%"=="master" goto FAIL_LEGACY_TARGET
if /I "%TARGET_BRANCH%"=="cursor/http-client-pool-3497" goto FAIL_LEGACY_TARGET
:AFTER_LEGACY_GUARD

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

echo [2/4] resolve python + build_v2.py
REM Prefer py -3 / python.org; NEVER use hermes-agent venv (blank window + stale UI)
set "ST_PYTHON="
where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "ST_PYTHON=%%P"
)
if not defined ST_PYTHON (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined ST_PYTHON (
      echo %%P | findstr /I "hermes hermes-agent antigravity" >nul
      if errorlevel 1 set "ST_PYTHON=%%P"
    )
  )
)
if not defined ST_PYTHON goto FAIL_PYTHON
echo !ST_PYTHON! | findstr /I "hermes hermes-agent" >nul
if not errorlevel 1 goto FAIL_PYTHON_HERMES
echo  PYTHON: !ST_PYTHON!
"!ST_PYTHON!" build_v2.py
if errorlevel 1 goto FAIL_BUILD
REM tip UX contract: refuse to open a tree that would flash the old chart shell
findstr /C:"shell_v5.js" "%REPO_ROOT%\stock_terminal_v2.html" >nul
if errorlevel 1 goto FAIL_TIP_HTML
findstr /C:"pulse_v5.js" "%REPO_ROOT%\stock_terminal_v2.html" >nul
if errorlevel 1 goto FAIL_TIP_HTML
findstr /C:"st5-tip-boot" "%REPO_ROOT%\stock_terminal_v2.html" >nul
if errorlevel 1 goto FAIL_TIP_HTML
findstr /C:"PULSE_LAYOUT_ANCHOR_4col2z" "%REPO_ROOT%\src\ui\pulse_v5.js" >nul
if errorlevel 1 goto FAIL_TIP_HTML
findstr /C:"max-width:1280" "%REPO_ROOT%\src\ui\pulse_v5.js" >nul
if not errorlevel 1 goto FAIL_TIP_HTML
echo.

echo [3/4] restart server on :18432
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18432" ^| findstr "LISTENING"') do (
    echo        kill PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul
if not exist "%REPO_ROOT%\logs" mkdir "%REPO_ROOT%\logs"
> "%REPO_ROOT%\logs\run_server_tip.cmd" echo @echo off
>>"%REPO_ROOT%\logs\run_server_tip.cmd" echo chcp 65001 ^>nul
>>"%REPO_ROOT%\logs\run_server_tip.cmd" echo title Stock Terminal Server v5 tip
>>"%REPO_ROOT%\logs\run_server_tip.cmd" echo cd /d "%REPO_ROOT%"
>>"%REPO_ROOT%\logs\run_server_tip.cmd" echo echo PYTHON=!ST_PYTHON!
>>"%REPO_ROOT%\logs\run_server_tip.cmd" echo "!ST_PYTHON!" -u server\server.py
>>"%REPO_ROOT%\logs\run_server_tip.cmd" echo pause
start "Stock Terminal Server v5 tip" "%REPO_ROOT%\logs\run_server_tip.cmd"
timeout /t 2 /nobreak >nul
echo.

echo [4/4] done
if "%OPEN_BROWSER%"=="1" start "" "http://localhost:18432/#pulse"

echo.
echo  Opened. Press Ctrl+F5 to hard-reload.
echo  Server window title must be: Stock Terminal Server v5 tip
echo  Browser badge must show: 5+5
echo  Next:  scripts\go.bat pull
echo  Tip:   scripts\go.bat pull !TIP_BRANCH!
echo.
pause
endlocal
exit /b 0

:FAIL_LEGACY_CURRENT
echo [BLOCK] Current branch is NOT tip UX: !CUR_BRANCH!
echo        Tip UX only. Switch with:
echo          scripts\go.bat pull !TIP_BRANCH!
echo        Override not recommended: set FORCE_LEGACY=1
pause
exit /b 2

:FAIL_LEGACY_TARGET
echo [BLOCK] Refusing checkout of legacy branch: %TARGET_BRANCH%
echo        That line drops tip UX back to old UI. Tip only:
echo          scripts\go.bat pull !TIP_BRANCH!
echo        Override not recommended: set FORCE_LEGACY=1
pause
exit /b 2

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
echo          scripts\go.bat pull !TIP_BRANCH!
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
echo             scripts\go.bat pull !TIP_BRANCH!
pause
exit /b 1

:FAIL_PULL
echo [FAIL] git pull / fast-forward failed.
echo        Stay on tip UX:
echo          scripts\go.bat pull !TIP_BRANCH!
pause
exit /b 1

:FAIL_BUILD
echo [FAIL] build_v2.py failed
pause
exit /b 1

:FAIL_TIP_HTML
echo [FAIL] Built HTML is NOT tip UX - missing shell_v5 / pulse_v5 / st5-tip-boot / layout anchor.
echo        You are about to open the OLD chart shell. Stay on tip:
echo          scripts\go.bat pull !TIP_BRANCH!
pause
exit /b 3

:FAIL_PYTHON
echo [FAIL] No suitable Python 3 found.
echo        Install https://www.python.org/downloads/ and tick Add to PATH,
echo        or ensure: py -3 -c "import sys; print(sys.executable)"
echo        Do NOT use Hermes agent venv python.
pause
exit /b 4

:FAIL_PYTHON_HERMES
echo [FAIL] Resolved python is Hermes/agent venv — blocked.
echo        Path: !ST_PYTHON!
echo        That opens a blank window and keeps serving old 兩框 UI.
echo        Fix PATH / install python.org Python, then retry.
pause
exit /b 4

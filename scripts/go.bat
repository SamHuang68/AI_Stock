@echo off
REM ============================================================
REM  Stock Terminal — 唯一建議的本機啟動／更新腳本
REM ------------------------------------------------------------
REM  用法（在專案根或 scripts\ 下雙擊／執行皆可）:
REM    scripts\go.bat           重建 v2 + 重啟 server + 開瀏覽器
REM    scripts\go.bat pull      先 git pull，再同上（每次 AI 更新後用這個）
REM    scripts\go.bat pull <branch>  切換分支 + pull + 重建 + 重啟
REM    scripts\go.bat rebuild   只重建 + 重啟（不開瀏覽器）
REM ============================================================
chcp 65001 >nul
setlocal EnableExtensions
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
if defined CUR_BRANCH echo  branch: %CUR_BRANCH%
echo.

REM ---- optional: git pull（AI 更新後）----
if /I "%MODE%"=="pull" (
    echo [1/4] git fetch / pull
    REM 本機若改過 v2，先 stash，避免 pull/checkout 被擋（你遇過的狀況）
    git diff --quiet -- stock_terminal_v2.html 2>nul
    if errorlevel 1 (
        echo        stash local stock_terminal_v2.html
        git stash push -m "auto: local v2 before go.bat pull" -- stock_terminal_v2.html >nul 2>&1
    )
    git fetch origin
    if not "%TARGET_BRANCH%"=="" (
        echo        checkout %TARGET_BRANCH%
        git checkout "%TARGET_BRANCH%"
        if errorlevel 1 (
            echo [FAIL] checkout %TARGET_BRANCH% 失敗
            pause
            exit /b 1
        )
    )
    git pull --ff-only
    if errorlevel 1 (
        echo.
        echo [FAIL] git pull 失敗。請先處理衝突或確認網路／權限。
        echo        換分支範例:  scripts\go.bat pull cursor/fix-tech-fund-score-4e66
        pause
        exit /b 1
    )
    for /f "delims=" %%b in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%b"
    if defined CUR_BRANCH echo        now on: %CUR_BRANCH%
    echo.
) else (
    echo [1/4] skip git pull  ^(要更新請用: scripts\go.bat pull^)
    echo.
)

REM ---- rebuild v2 from stock_terminal.html + src/ ----
echo [2/4] build_v2.py
python build_v2.py
if errorlevel 1 (
    echo [FAIL] build_v2.py failed
    pause
    exit /b 1
)
echo.

REM ---- kill old server on :18432 ----
echo [3/4] restart server on :18432
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":18432" ^| findstr "LISTENING"') do (
    echo        kill PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

start "Stock Terminal Server" /MIN cmd /c "python server\server.py"
timeout /t 2 /nobreak >nul
echo.

REM ---- open browser ----
echo [4/4] done
if "%OPEN_BROWSER%"=="1" (
    start "" "http://localhost:18432/stock_terminal_v2.html"
)

echo.
echo  開啟後請 Ctrl+F5 硬重新整理。
echo  雙軸卡技術面 tag 應出現 tech·385（沒有 = 舊快取）。
echo.
if /I "%MODE%"=="pull" (
    echo  下次 AI 更新後只要再跑:
    echo    scripts\go.bat pull
    echo.
)
pause
endlocal

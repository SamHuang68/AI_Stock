@echo off
REM Push local main to GitHub (ASCII-only). Reusable any time.
cd /d "%~dp0"

echo ============================================
echo  Push to https://github.com/SamHuang68/stock-terminal
echo ============================================
echo.
echo Local latest commits:
git log --oneline -3
echo.
echo Remote (last known) position:
git log --oneline -1 origin/main
echo.

git push origin main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] Push rejected or auth failed.
    echo  - If asked for login: a browser/credential window may have opened.
    echo  - If remote has newer commits, run these two commands in cmd:
    echo        git pull --rebase origin main
    echo        git push origin main
    pause
    exit /b 1
)

echo.
echo [OK] Pushed. Verify at:
echo   https://github.com/SamHuang68/stock-terminal
git log --oneline -1 origin/main
pause

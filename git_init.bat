@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

echo ============================================
echo  Initialize Git repository for Stock_Terminal_v2.0
echo ============================================
echo.

REM Check git is installed
git --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git not found. Install from https://git-scm.com/download/win
    pause
    exit /b 1
)

if exist ".git" (
    echo [INFO] .git already exists - this folder is already a Git repo.
    echo        Skipping init. Showing status:
    echo.
    git status -sb
    echo.
    pause
    exit /b 0
)

echo Initializing repo...
git init -b main
if errorlevel 1 (
    REM Older git: -b flag not supported, use init then rename
    git init
    git branch -M main
)

echo.
echo Configuring local user (only if global is unset)...
git config user.name  >nul 2>&1 || git config user.name  "Stock Terminal User"
git config user.email >nul 2>&1 || git config user.email "stock-terminal@local"

echo.
echo Adding files (respecting .gitignore)...
git add .

echo.
echo Files staged:
git status -sb

echo.
echo Creating initial commit...
git commit -m "Initial commit: Stock Terminal v2.0 — multi-signal WATCH + POS + i-icon docs + drag-sort watchlist"
if errorlevel 1 (
    echo [WARN] Commit failed. You may need to set git config user.name / user.email globally first:
    echo        git config --global user.name  "Sam Huang"
    echo        git config --global user.email "samhuang68@gmail.com"
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Done. Local repo ready.
echo ============================================
echo.
echo Next steps (push to GitHub / GitLab):
echo   1. Create empty repo at https://github.com/new   (name it stock-terminal)
echo   2. git remote add origin https://github.com/SamHuang68/stock-terminal.git
echo   3. git push -u origin main
echo.
echo Or push to a private GitLab / Gitea / Bitbucket the same way.
echo.
pause

@echo off
REM Stock Terminal - remove obsolete files (ASCII-only). Run AFTER commit_v3_9.bat for separate commits,
REM or run alone (it will commit + push the removals). Tracked files use git rm; ignored files use del.
cd /d "%~dp0"

if exist ".git\index.lock" del /F /Q ".git\index.lock"

echo === Removing old commit scripts ===
git rm -f --ignore-unmatch commit_v3_5.bat commit_v3_6.bat commit_v3_6_7.bat commit_v3_7.bat commit_v3_8.bat commit_v3_8_1.bat commit_v3_8_2.bat commit_v3_8_3.bat commit_v3_8_4.bat

echo === Removing old build runners + one-time init ===
git rm -f --ignore-unmatch build_v2_run.py build_v2_run2.py build_v2_run3.py git_init.bat

echo === Removing deprecated / prototype modules ===
git rm -f --ignore-unmatch stock_terminal.jsx stock_terminal_api.html layout_v3.js pattern_v3_test.html

echo === Removing old docs ===
git rm -f --ignore-unmatch PLAN_v3.8.md FEATURES.html

echo === Removing untracked backups / old dist zips ===
del /Q etf_catalog.json.bak 2>nul
del /Q Stock_Terminal_v1.0.zip Stock_Terminal_v2.0.zip Stock_Terminal_v3.8.zip Stock_Terminal_v3.8.2.zip 2>nul

echo.
echo === Committing cleanup + pushing ===
git add -A
git commit -m "chore: remove obsolete files (old commit scripts, build runners, deprecated modules/prototypes, old docs, old dist zips)"
git push origin main
if %ERRORLEVEL% NEQ 0 echo [WARN] push failed - run push_github.bat to retry.

echo.
echo Done. Kept: commit_v3_9.bat, push_github.bat, build_v2.py, build_dist.bat, Stock_Terminal_v3.9.zip
echo Removed self can be run only once; safe to delete this cleanup_old.bat afterwards if you like.
pause

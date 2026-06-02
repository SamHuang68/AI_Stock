@echo off
REM Stock Terminal v3.8.1 hotfix commit (ASCII-only)
cd /d "%~dp0"

if exist ".git\index.lock" del /F /Q ".git\index.lock"

git add enhance_v3.js

git commit ^
 -m "v3.8.1 fix: VP numeric panel recomputes from current candles" ^
 -m "STATS volume-profile panel read stale global VP.lastVP, so after switching symbol it showed the previous stock's POC/VAH/VAL. Now it recomputes via computeVolumeProfile(current candles), matching the chart."

echo.
echo === Hotfix committed ===
git log --oneline -1
pause

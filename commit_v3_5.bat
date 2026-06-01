@echo off
REM v3.5 commit - Yahoo daily-K lag + user-local timezone fix
chcp 65001 >nul
cd /d "%~dp0"

REM Clean up any stale lock file from sandbox attempts
if exist ".git\index.lock" del /F /Q ".git\index.lock"

REM Write commit message to temp file (UTF-8)
(
echo v3.5: fix Yahoo daily-K lag + user-local timezone for chart axis
echo.
echo Background:
echo   Yahoo Finance query1/query2 frequently desync - daily candle array
echo   stays at previous trading day while regularMarketPrice already
echo   reflects today's close. Caused:
echo    - Watchlist chips flickering between today and yesterday
echo    - Screener returning yesterday's gainers
echo    - Index bar stuck at 0.00%%
echo    - TW/US Sectors heatmap off
echo    - chart-info + 昨收 line wrong after click
echo.
echo Unified fix: detect rmt - last_candle.time ^> 20h, then use rmp as
echo today and last_candle.close as yesterday. For chart display,
echo synthesize an extra today-bar so chart/ci-chg/chip all align.
echo.
echo Files changed:
echo   wl_live_v3.js          range=1d-^>5d + rmt alignment
echo   stock_terminal_v2.html loadSym synthesizes today-K daily/weekly;
echo                          intraday uses chartPreviousClose;
echo                          chart timestamps shifted by user-local TZ
echo                          (TW shows 09:00-13:30, US shows 21:30-04:00
echo                          in Taipei). Crosshair uses getUTC* read-back.
echo   polish_v3.js           refreshMktBar 2d-^>5d + rmt alignment;
echo                          prev-close line + ci-chg color read
echo                          S.data.yesterdayClose in intraday.
echo                          Volume re-set uses S.tzOffset.
echo   heatmap_v3.js          extractChg: 5d + rmt alignment.
echo   server.py              _handle_screener_post synthesizes today-K;
echo                          sectors_us + sectors_tw 1d-^>5d + alignment.
echo   restart_server.bat     helper: kill+restart server.py on :18432.
echo.
echo README.md updated with new v3.5 section.
) > .git\COMMIT_MSG_v35.txt

REM Stage v3.5 bug fix files
git add README.md server.py stock_terminal_v2.html polish_v3.js wl_live_v3.js heatmap_v3.js restart_server.bat

echo === Staged files: ===
git diff --cached --name-only
echo.

git commit -F .git\COMMIT_MSG_v35.txt

del /F /Q .git\COMMIT_MSG_v35.txt

echo.
echo === Result: ===
git log --oneline -3
pause

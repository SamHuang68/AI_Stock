@echo off
REM Stock Terminal v3.8.2 commit (ASCII-only)
cd /d "%~dp0"

if exist ".git\index.lock" del /F /Q ".git\index.lock"

REM Stage everything (fundamental fix, aftermarket, ETF catalog + UI changes).
REM alert_config.json / alert_rules.json stay .gitignored.
git add -A

git commit ^
 -m "v3.8.2: fundamental field fix + aftermarket + ETF TW/US split" ^
 -m "Fundamental: TWSE OpenAPI fields matched by substring (handles 'revenue-' prefix and full-width parens) so YoY/MoM/cum/margins/EPS populate" ^
 -m "Aftermarket: US pre/post-market price in /quote (includePrePost), chart-info tag + STATS block + watchlist US chip dot (aftermarket_v3.js); alert daemon uses ext price" ^
 -m "VP numeric panel recomputes from current candles (no stale symbol)" ^
 -m "ETF catalog expanded: market split TW/US, +84 US ETFs (enabled=false), expand_etf_catalog.py generator" ^
 -m "ETF delta card name falls back to catalog when ETF_NAME_MAP missing" ^
 -m "ETF manager: TW/US/all tabs + market tag + click-to-load; add-form market selector + US ticker validation" ^
 -m "ETF main tab: dedicated US section with live quotes, click loads with US market" ^
 -m "Fix: modules used window.S but state is lexical global 'S' (let S) -> backtest/dual-axis/aftermarket/VP-resync now read S correctly" ^
 -m "Backtest panel clears results on close (no stale data when reopening on another symbol)"

echo.
echo === v3.8.2 committed ===
git log --oneline -1
pause

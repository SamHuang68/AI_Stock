@echo off
REM Stock Terminal v3.8.2 commit (ASCII-only to avoid CP950/.bat encoding issues)
cd /d "%~dp0"

if exist ".git\index.lock" del /F /Q ".git\index.lock"

REM Stage everything. alert_config/alert_rules/watch_rules etc. are .gitignored.
git add -A

git commit ^
 -m "v3.8.2: candle data fixes + valuation TW/US + supply chain TW/US tabs + tech-score canon + chart-info layout" ^
 -m "Fix synthetic daily candle: use meta DayHigh/Low/Volume + regularMarketOpen (fallback prev close clamped to day range); never use chartPreviousClose as yesterday close (it is range-start prev close; caused fake +109pct candle and volume 0)" ^
 -m "Fix last daily candle volume null/0: backfill from regularMarketVolume" ^
 -m "Tech score canonical: always 1y daily basis via computeCanonTech; leverage/inverse ETF map to base (00631L->0050, inverse flipped); score no longer depends on visible range (enhance_v3.js)" ^
 -m "Valuation TW: BWIBBU_ALL moved to /v1/exchangeReport (EN fields Code/PEratio/PBratio/DividendYield, no close); TPEx peratio fallback for OTC; close price via STOCK_DAY_ALL then Yahoo (server.py)" ^
 -m "Valuation US: reuse keystats chain yfinance->v10->html (v10 alone needs crumb, 401); PER<->EPS derivable; market tag + source shown in modal (valuation_v3.js)" ^
 -m "Supply chain: TW chain 7->11 stages 54 names (add memory, passive components incl 2327 Yageo, mech/connector/rail, power infra; add 2317/2449/2383/3529 etc); new US AI chain tab 8 stages (equip/EDA->foundry->chip->memory->optics->server->power->CSP); follows current market, US green-up (supplychain_v3.js)" ^
 -m "chart-info: OHLC float window half size, snug right of price, legend (SMA/BB/prevclose) merged into window bottom-right, no candle overlap (polish_v3.js)" ^
 -m "README v3.8.2 + build_dist v3.8.2"

echo.
echo === Commit done. ===
git log --oneline -1
echo.
echo Next steps:
echo   1. build_dist.bat            (pack Stock_Terminal_v3.8.2.zip)
echo   2. rebuild_and_restart.bat   (apply server.py changes) then Ctrl+F5
pause

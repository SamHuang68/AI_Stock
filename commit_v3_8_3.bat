@echo off
REM Stock Terminal v3.8.3 commit (ASCII-only)
cd /d "%~dp0"

if exist ".git\index.lock" del /F /Q ".git\index.lock"

REM Stage everything. alert_config.json / alert_rules.json stay .gitignored.
git add -A

git commit ^
 -m "v3.8.3: ETF consensus report + email, full-market screener, fixes" ^
 -m "ETF report: cross-ETF new/remove/add-reduce aggregation; dual board + net-score; multi-section HTML (etf_report.py); full + lite(Top summary) email; daily 18:30 scheduler; HIGH_PRIORITY_RANK tunable" ^
 -m "Screener: full TW market (TWSE+TPEx ~2000 stocks via OpenAPI, cached); long/short presets; sector filter (tech/industry); panel 1/3 top 2/3 results layout" ^
 -m "POS auto-updates current price via wl_live poll (no click needed)" ^
 -m "AI report: prompt forces code-as-truth, no name guessing (fix 2408 mislabel)" ^
 -m "Market bar: add KOSPI / gold / silver / crude oil" ^
 -m "Volume Profile: avg(amount+volume) mode, stops at price axis (no candle overlap), short POC/VAH/VAL lines on right" ^
 -m "Close labels: today/prev close as half-size tags beside price axis; LIVE session inferred from local time when Yahoo marketState missing/wrong" ^
 -m "Dual-axis card / collapsible right panel / tab memory / pre-post market; README v3.8 updated"

echo.
echo === v3.8.3 committed ===
git log --oneline -1
pause

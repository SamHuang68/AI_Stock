@echo off
REM Stock Terminal v3.8 commit (ASCII-only to avoid CP950/.bat encoding issues)
cd /d "%~dp0"

if exist ".git\index.lock" del /F /Q ".git\index.lock"

REM Stage everything (v3.4-3.7 leftovers + all of v3.8).
REM alert_config.json / alert_rules.json are .gitignored (tokens stay local).
git add -A

git commit ^
 -m "v3.8: chip/fundamental/backtest/alert + turnover Volume Profile + layout" ^
 -m "E Volume Profile: turnover & volume normalized-average on Y axis; POC/VAH/VAL/main-cost zone (volume_profile_v3.js)" ^
 -m "A Chip: borrow-short TWT72U / day-trade ratio TWTB4U / institutional buy-sell streak; chip_history_tracker.py + daily_chip + scheduler" ^
 -m "B Fundamental: TWSE OpenAPI monthly revenue YoY/MoM + income-statement margins + score (fundamental_v3.js, /fundamental)" ^
 -m "C Backtest: unified core (winrate/payoff/expectancy/maxDD/sharpe/equity-curve) + pattern hit-rate + portfolio (backtest_v3.js/backtest_ui_v3.js)" ^
 -m "D Alert push: server-side daemon (browser-free) Telegram+Email; alert_daemon.py + /alert endpoints + alert_push_v3.js" ^
 -m "UI: right panel 40pct + market-bar 2 rows + toolbar 2 rows; dual-axis card / VP numeric panel / collapse / tab-memory (enhance_v3.js)" ^
 -m "Fix: signal notifications evaluate on daily timeframe only (no flip-flop spam on week/month/intraday switch)"

echo.
echo === Commit done. Next: rebuild_and_restart.bat to apply, then Ctrl+F5 ===
git log --oneline -1
pause

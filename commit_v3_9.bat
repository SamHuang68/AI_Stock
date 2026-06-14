@echo off
REM Stock Terminal v3.9 commit (ASCII-only to avoid CP950/.bat encoding issues)
cd /d "%~dp0"

if exist ".git\index.lock" del /F /Q ".git\index.lock"

REM Stage everything. alert_config/alert_rules/watch_rules/draw_store etc. are .gitignored.
git add -A

git commit ^
 -m "v3.9: TradingView-style upgrades - multi-chart, hotkeys, spread, visual backtest, drawing tools, 3-in-1 screener, complex alerts + webhook, ETF volume-share + AI reason" ^
 -m "P1 multichart_v3.js: 2x1/2x2/1x3 grid overlay over chart area, per-pane symbol/timeframe, synced crosshair (setCrosshairPosition) + synced logical time range, presets (multi-timeframe / supply-chain / watchlist), localStorage mc_layouts; intraday last-bar volume backfill from regularMarketVolume" ^
 -m "P1 hotkeys_v3.js: type-to-search quick switch, Space/Shift+Space cycle watchlist, Alt+1..0 timeframe, Alt+M/D/T, Esc, ? cheatsheet; ignores inputs" ^
 -m "P1 spread_v3.js: formula ratio/spread charts (2330/2303, ^TWII/^SOX, 2330-TSM*TWD=X) via own tokenizer + recursive-descent parser (no eval), time-aligned /yf/batch" ^
 -m "P2 backtest_v3.js: add profitFactor/avgHoldBars/maxWin-LossStreak/best-worst/annualized sharpe + trade list; new runLS (entry+exit dual-signal)" ^
 -m "P2 strategy_builder_v3.js: lego AND/OR condition builder -> runLS, deep perf card + equity curve + trade table + chart markers; ships window.StratLib (sma/ema/rsi/kd/macd/bb/crossover...)" ^
 -m "P2 strategy_script_v3.js: Pine-like safe DSL (own tokenizer + recursive-descent interpreter, whitelist funcs, no eval), buy/sell -> runLS, plot overlays, markers" ^
 -m "P3 drawtools_v3.js: canvas overlay trendline/hline/vline/fibonacci/rect/channel/text, time+price anchors survive range/device, select+drag+delete, localStorage draw_v3 + best-effort server /draw cloud memory" ^
 -m "P3 server /draw/<sym> GET/POST -> draw_store.json (gitignored)" ^
 -m "P4 screener3_v3.js + server /screen3: technical x fundamental x chip intersection scan, scrollable results, one-click add to watchlist" ^
 -m "P5 webhook: alert_daemon push_webhook in central notify (price + watch alerts); alert_push_v3 webhook config" ^
 -m "P5 composite alerts: alert_daemon composite rule type (daily candles + indicators, AND/OR conditions); alert_push_v3 composite builder" ^
 -m "P5 ETF volume-share + AI reason: consensus report shows trust est buy lots vs 20d avg volume; etf_v3 reason button -> server /etf-reason (Anthropic one-liner with fundamentals)" ^
 -m "Macro overlay (macro_v3.js, server /macro) implemented then disabled in build (FRED latency + TW gov data source instability); files kept dormant for later" ^
 -m "Setup Wizard wizard_v3.js: 4-question flow (use/horizon/risk/capital) + analysis engine (tech score/ATR/support-resistance/scanStrategies/fundamental/valuation/chip) -> one-click apply WATCH signals + alerts (incl composite buy-zone) + position/buy-plan (ATR or fixed stop, suggested shares) + support/resistance draw (fib optional) + verdict (rule or Claude via /ai-note); idempotent source:wizard" ^
 -m "server /ai-note generic Anthropic relay; drawtools window.drawToolsAdd programmatic add" ^
 -m "Fixes: toolbar wraps to multiple rows (release fixed height so right panel does not cover buttons); wizard preserves watch.sym (was undefined title/undeletable); watch_v2 self-heals missing sym from key; wizard fib off by default; build_v2 banner/title v3.9" ^
 -m "Wizard W2: auto-prompt toast on watchlist add (renderWl hook), per-signal checkboxes effective (applyCore sel.sigsIdx), batch apply across watchlist (fetch 1y per stock -> computeFrom -> applyCore), config templates (wizard_templates); refactor compute/buildSuggestions/ruleConclusion to take params + split applyCore" ^
 -m "README v3.9 + build_dist v3.9 (+wizard_v3.js)"

echo.
echo === Commit done. Pushing to GitHub... ===
git log --oneline -1

git push origin main
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] Push failed - run push_github.bat to retry.
)

echo.
echo Next steps:
echo   1. build_dist.bat            (pack Stock_Terminal_v3.9.zip)
echo   2. rebuild_and_restart.bat   (apply server.py changes) then Ctrl+F5
pause

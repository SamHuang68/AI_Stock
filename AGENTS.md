# AGENTS.md

## Cursor Cloud specific instructions

Stock Terminal v4.1 is a **local-first** research terminal: a browser frontend (Vanilla JS +
TradingView Lightweight Charts) talks over HTTP to a local Python server that proxies external
data sources and computes technical indicators. It is a single product, not a monorepo of
services.

### Runtime & dependencies
- **Pure Python standard library — no `pip install` is required or expected** (the project is
  intentionally zero-dependency). The VM has Python 3.12; the project needs 3.10+.
- The optional `yfinance` fallback (fundamentals key-stats) is deliberately **not** installed;
  the server imports it lazily and degrades gracefully without it. Don't add it unless asked.
- **Outbound internet is required** for live data (Yahoo Finance, TWSE MIS, MoneyDJ, FRED).
  Without egress, charts/quotes will fail.

### Build (frontend)
- `python3 build_v2.py` assembles `stock_terminal_v2.html` from `stock_terminal.html` +
  the `src/**/*.js` modules. This is a build command, not a dependency step.
- The built `stock_terminal_v2.html` is committed. **Rebuilding injects cache-busting
  `?v=<timestamp>` query strings, so a fresh build produces a huge but semantically no-op diff.**
  Do not commit the regenerated artifact unless you actually changed something in `src/`.

### Run (backend + UI)
- `python3 server/server.py` serves both the UI and the API on `http://localhost:18432`
  (binds to `localhost` only). Then open `http://localhost:18432/stock_terminal_v2.html`.
  Load a symbol by typing e.g. `2330` (Taiwan) and pressing GO; click `US` first for US tickers.
- Optional background daemons (alerts / watch) only start if enabled in `alert_config.json`;
  they are off by default.

### Lint / test
- There is **no formal linter and no test framework**. Use `python3 -m compileall server *.py`
  as a syntax check.
- Backend unit tests are exposed at runtime: `GET http://localhost:18432/selftest` returns JSON
  (`allPass`, 13 data-integrity checks). Hit it while the server is running.
- Frontend parse tests (`tests/parse_selftest.js`) are a browser-console snippet, not a Node test.

### Platform note
- All `scripts/*.bat` and the `installer/` (PyInstaller + Inno Setup) are **Windows-only** and do
  not run on this Linux VM. Run the Python commands above directly instead.

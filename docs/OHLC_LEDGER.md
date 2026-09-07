# OHLC Ledger (T2)

Append-only daily OHLC bar storage for future peak-v0.1 / chip features. This
ledger is infrastructure only — it does **not** write `DecisionContext`,
EvidencePack, or any LLM-derived numbers.

## Purpose

- Single shared source of truth for historical session bars.
- Supports **point-in-time (PIT)** queries so backtests and peak features never
  read bars that were not knowable at a decision timestamp.
- Enables **T1 EvidencePack peak UI** later (CONDITIONAL) without a parallel
  price pipeline.

## Schema

SQLite table `ohlc_bars` under `data/ohlc_ledger/ohlc_ledger.db`:

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT | e.g. `2330`, `^TWII` |
| `session_date` | TEXT | `YYYY-MM-DD` trading session |
| `price_basis` | TEXT | `unadj_close` or `adj_close` |
| `open`, `high`, `low`, `close` | REAL | OHLC consistent with `price_basis` |
| `source` | TEXT | e.g. `yahoo/v8-chart`, `fixture/test` |
| `ingested_at` | TEXT | ISO-8601 UTC (or offset) ingestion time |
| `generation_id` | TEXT | cohort id for adjustment rewrites |

Primary key: `(symbol, session_date, price_basis, generation_id)`.

## Append-only rule

- Rows are **never updated or deleted** in place.
- Re-ingesting the same primary key is a **no-op** (`INSERT OR IGNORE`).
- Corporate-action / ADJ restatements append under a **new** `generation_id`;
  prior generations remain queryable.

Use `new_generation_id()` when restating adjusted history.

## PIT / availability predicate

A bar is visible at decision time when **both** hold:

1. `session_date <= as_of` — no future session bars.
2. `ingested_at <= knowledge_cutoff` — no lookahead ingestion.

Pure helpers:

- `availability_predicate(bar, as_of=..., knowledge_cutoff=...)`
- `filter_bars_pit(bars, as_of=..., knowledge_cutoff=...)`

SQLite query:

- `query_bars_pit(symbol, as_of=..., knowledge_cutoff=..., ...)`

When `latest_generation=True` (default), multiple generations for the same
`(symbol, session_date, price_basis)` collapse to the row with the latest
`ingested_at` still `<= knowledge_cutoff`.

## Ingest paths

- `append_bars([...])` — direct append from dict rows or fixtures.
- `bars_from_yahoo_chart(payload, symbol, price_basis=...)` — parse Yahoo v8 JSON.
- `ingest_yahoo_chart_payload(...)` — gated by feature flag `ohlcLedger`.

Unit tests ship tiny fixtures under `tests/fixtures/ohlc_ledger/`; large market
CSVs are **not** committed.

## Feature flag

| Key | Env | Default |
|-----|-----|---------|
| `ohlcLedger` | `ST_OHLC_LEDGER` | **on** |

Set `ST_OHLC_LEDGER=0` or `data/feature_flags.local.json` → `"ohlcLedger": false`
to disable Yahoo ingest writes. Direct `append_bars()` still works for tests and
offline tooling.

## Explicit non-goals (this module)

- No DecisionContext / actionEnvelope writes
- No dual-axis strategy engine or sim positions

Peak observation UI (T1, CONDITIONAL) lives in `server/peak_observation.py` — see
`docs/ST_PEAK_V01.md`.

## Module

`server/ohlc_ledger.py`

# st-peak-100d-v0 — 100-Trading-Day Peak Observation (CONDITIONAL only)

Observation-only `% below peak` over a **bounded 100 trading-session** lookback
(投信雙軸軸 A style). **T4 scope:** this PR ships **CONDITIONAL** labels only —
no FACT binding, no DecisionContext writes, no deploy/gate thresholds.

**This contract is separate from `st-peak-v0.1`:** different `contractId`, different
window semantics, no ATH / all-time-high wording, no Decision write, no deploy-gate FACT.

## Contract summary

| Field | Value / rule |
|-------|----------------|
| `contractId` | **`st-peak-100d-v0`** (≠ `st-peak-v0.1`) |
| `windowDays` | **`100`** — trading sessions, not calendar days |
| `peakKind` | **`A` only** — `peakClose = max(close)` from `historyStart` through `asOf` (inclusive) on declared `priceBasis` |
| Window | Last **100 trading sessions** ending at `asOf` (inclusive). `historyStart` = session date of the earliest bar in that window. If fewer than 100 sessions exist, use all available sessions and set `pitLimitation`. |
| Formula | `pctBelowPeak = lastClose / peakClose - 1`, range `[-1, 0]` |
| Default basis | `unadj_close` + peakKind A |
| `adj_close` | Requires `basisAsOf`, `generationId`, `generationContentHash`; else numerics `null` + `nullReason` |
| `label` | Always **`CONDITIONAL`** in this PR |
| `hostApprovalHash` | Always `null` (no FACT / deploy gate in this PR) |
| `disclaimerKey` | `st-peak-100d-non-recommendation` (symbol-parameterized in UI) |

**Trading sessions vs calendar days:** Stock Terminal bars are **one row per TW trading
session** (`session_date`). The 100-day window counts **100 such sessions**, not 100
calendar days. Weekends and market holidays are naturally excluded because they have no
bars.

Banned wording in UI/copy: ATH, all-time-high, 「歷史高點」, history-high.

## PIT / ledger

Prefer T2 helpers in `server/ohlc_ledger.py`:

- `query_bars_pit(symbol, as_of=..., knowledge_cutoff=...)`
- `filter_bars_pit(bars, as_of=..., knowledge_cutoff=...)`

When the ledger is empty, `peak_observation_100d.build_observation()` may fall back to
live chart bars with synthetic `ingested_at = knowledgeCutoff`. The response includes
`pitLimitation` and **remains CONDITIONAL**.

## Modules

| Path | Role |
|------|------|
| `server/peak_observation_100d.py` | Pure compute + EvidencePack attach helper |
| `server/peak_observation_100d_routes.py` | `GET /research/peak-observation-100d?symbol=` |
| `src/ui/peak_observation_100d_v5.js` | CONDITIONAL card (distinct from st-peak-v0.1) |
| `tests/test_peak_observation_100d.py` | Unit tests (100d window, PIT, label) |

EvidencePack wiring: `postmarket_report.build_evidence_pack()` adds
`peakObservation100d` when flag `shadowPeak100d` is enabled (default **on**;
disable via `ST_SHADOW_PEAK_100D=0`).

## Feature flag

| Key | Env | Default |
|-----|-----|---------|
| `shadowPeak100d` | `ST_SHADOW_PEAK_100D` | **on** (observation-only) |

Independent from `shadowPeakObservation` (`st-peak-v0.1`).

## Explicit non-goals (this PR)

- No DecisionContext / `actionEnvelope` / regime scores
- No threshold / gate / deploy objects or FACT promotion
- No dual-axis composite score or breakout buy signal
- No strategy engine / gated DCA
- No LLM numbers; no FantasyMaya sigma ranking
- Not a merge or alias of `st-peak-v0.1`

## Related

- Full-history peak (separate contract): `docs/ST_PEAK_V01.md`
- T2 ledger: `docs/OHLC_LEDGER.md`
- Epistemic UI badges: `src/core/epistemic_badges_v5.js`

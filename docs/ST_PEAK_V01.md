# st-peak-v0.1 — Peak Observation (CONDITIONAL only)

Observation-only `% below peak` feature for EvidencePack. **T1 scope:**
this PR ships **CONDITIONAL** labels only — no FACT binding (T3), no
DecisionContext writes, no deploy/gate thresholds.

## Contract summary

| Field | Value / rule |
|-------|----------------|
| `contractId` | `st-peak-v0.1` |
| `peakKind` | **`A` only** — `peakClose = max(close)` from `historyStart` through `asOf` (inclusive) on declared `priceBasis` |
| Formula | `pctBelowPeak = lastClose / peakClose - 1`, range `[-1, 0]` |
| Default basis | `unadj_close` + peakKind A |
| `adj_close` | Requires `basisAsOf`, `generationId`, `generationContentHash`; else numerics `null` + `nullReason` |
| `label` | Always **`CONDITIONAL`** in this PR |
| `hostApprovalHash` | Always `null` (FACT / T3 later) |
| `disclaimerKey` | `st-peak-v0.1-non-recommendation` |

Banned wording in UI/copy: ATH, all-time-high, 「歷史高點」, history-high.

## PIT / ledger

Prefer T2 helpers in `server/ohlc_ledger.py`:

- `query_bars_pit(symbol, as_of=..., knowledge_cutoff=...)`
- `filter_bars_pit(bars, as_of=..., knowledge_cutoff=...)`
- `availability_predicate(bar, as_of=..., knowledge_cutoff=...)`

A bar is visible when:

1. `session_date <= asOf`
2. `ingested_at <= knowledgeCutoff`

When the ledger is empty, `peak_observation.build_observation()` may fall back to
live chart bars (`datastore.get_bars`) with synthetic `ingested_at = knowledgeCutoff`.
The response includes `pitLimitation` and **remains CONDITIONAL**.

## Modules

| Path | Role |
|------|------|
| `server/peak_observation.py` | Pure compute + EvidencePack attach helper |
| `server/peak_observation_routes.py` | `GET /research/peak-observation?symbol=` |
| `src/ui/peak_observation_v5.js` | CONDITIONAL card (postmarket + stats panel) |
| `tests/test_peak_observation.py` | Unit tests (peak A, PIT, adj null, label) |

EvidencePack wiring: `postmarket_report.build_evidence_pack()` adds
`peakObservation` when flag `shadowPeakObservation` is enabled (default **on**;
disable via `ST_SHADOW_PEAK_OBSERVATION=0`).

## Feature flag

| Key | Env | Default |
|-----|-----|---------|
| `shadowPeakObservation` | `ST_SHADOW_PEAK_OBSERVATION` | **on** (observation-only) |

## Explicit non-goals (this PR)

- No DecisionContext / `actionEnvelope` / regime scores
- No threshold / gate / deploy objects
- No FACT label or `hostApprovalHash`
- No dual-axis / breakout / sim positions
- No implication that wait-to-buy beats DCA

## Related

- T2 ledger: `docs/OHLC_LEDGER.md`
- Epistemic UI badges: `src/core/epistemic_badges_v5.js`

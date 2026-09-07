# st-peak-v0.1 — Peak Observation (CONDITIONAL default; FACT via T3 binding)

Observation-only `% below peak` feature for EvidencePack. Default label is
**CONDITIONAL**. **FACT** requires complete §6 binding (PIT ledger path,
explicit `knowledgeCutoff`, numerics, `evidenceHash`, Host `hostApprovalHash`,
no `pitLimitation`). No DecisionContext writes, no deploy/gate thresholds.

## Contract summary

| Field | Value / rule |
|-------|----------------|
| `contractId` | `st-peak-v0.1` |
| `peakKind` | **`A` only** — `peakClose = max(close)` from `historyStart` through `asOf` (inclusive) on declared `priceBasis` |
| Formula | `pctBelowPeak = lastClose / peakClose - 1`, range `[-1, 0]` |
| Default basis | `unadj_close` + peakKind A |
| `adj_close` | Requires `basisAsOf`, `generationId`, `generationContentHash`; else numerics `null` + `nullReason` |
| `label` | **`CONDITIONAL`** by default; **`FACT`** only when §6 binding complete |
| `evidenceHash` | SHA-256 of canonical JSON: symbol, asOf, historyStart, priceBasis, knowledgeCutoff, generation metadata, PIT bar set, and computed outputs (`peakClose`, `peakDate`, `lastClose`, `pctBelowPeak`) |
| `hostApprovalHash` | SHA-256 of Host approval record binding `evidenceHash`; `null` until approved |
| `disclaimerKey` | `st-peak-v0.1-non-recommendation` |

Banned wording in UI/copy: ATH, all-time-high, 「歷史高點」, history-high.

## §6 FACT binding (T3)

`label=FACT` **only if all** of:

1. Bars loaded from T2 ledger (`source=ohlc_ledger/pit`), not live-chart fallback
2. Caller supplied explicit `knowledgeCutoff` (no implicit default)
3. Every bar has non-empty `ingested_at` and passes PIT (`session <= asOf`, `ingested_at <= knowledgeCutoff`)
4. Numerics non-null (`peakClose`, `peakDate`, `lastClose`, `pctBelowPeak`)
5. `evidenceHash` non-null
6. `hostApprovalHash` non-null (Host approval exists for this `evidenceHash`)
7. `peakKind=A`
8. No `pitLimitation` field

Otherwise `label=CONDITIONAL` and `hostApprovalHash` stays `null` unless an approval exists but other gates fail (approval hash may be present but label remains CONDITIONAL).

### evidenceHash

Stable content hash of the exact bar set and compute inputs. Replaying the same
`(symbol, asOf, priceBasis, generationId, knowledgeCutoff, contractId)` with the
same ledger snapshot yields bit-identical payload and the same `evidenceHash`.

### hostApprovalHash

Non-null only when a Host-approved binding exists in the append-only approval
store (`data/peak_approvals/peak_approvals.db`, gitignored).

Approval record hash inputs:

```json
{
  "approvalNote": "",
  "approvedAt": "2026-01-10T05:30:00+00:00",
  "approvedBy": "Sam",
  "contractId": "st-peak-v0.1",
  "evidenceHash": "<sha256>"
}
```

### How Sam / Host records approval

1. Compute or fetch `evidenceHash` from a CONDITIONAL observation (API, test, or replay).
2. Review PIT bars and numerics offline.
3. Record approval (PowerShell, repo root):

```powershell
python scripts/peak_approve.py record `
  --evidence-hash <sha256> `
  --by "Sam" `
  --symbol 2330 `
  --as-of 2026-01-03 `
  --knowledge-cutoff 2026-01-10T13:30:00+08:00 `
  --note "Reviewed ledger PIT snapshot"
```

4. Re-query the same snapshot parameters — `label` becomes `FACT` when all §6 gates pass.

Lookup:

```powershell
python scripts/peak_approve.py lookup --evidence-hash <sha256>
```

Tests may use `peak_approvals.bind_fixture_approval(evidence_hash, base_dir=...)`.

**Safe default:** without approval, behavior matches T1 (CONDITIONAL only).

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
The response includes `pitLimitation` and **remains CONDITIONAL** (cannot FACT).

## Modules

| Path | Role |
|------|------|
| `server/peak_observation.py` | Pure compute + §6 FACT binding + EvidencePack attach helper |
| `server/peak_approvals.py` | Append-only Host approval store |
| `scripts/peak_approve.py` | CLI to record / lookup approvals |
| `server/peak_observation_routes.py` | `GET /research/peak-observation?symbol=` |
| `src/ui/peak_observation_v5.js` | Observation card (FACT or CONDITIONAL badge + disclaimer) |
| `tests/test_peak_observation.py` | Unit tests (peak A, PIT, adj null, FACT binding, replay) |

EvidencePack wiring: `postmarket_report.build_evidence_pack()` adds
`peakObservation` when flag `shadowPeakObservation` is enabled (default **on**;
disable via `ST_SHADOW_PEAK_OBSERVATION=0`).

## Feature flag

| Key | Env | Default |
|-----|-----|---------|
| `shadowPeakObservation` | `ST_SHADOW_PEAK_OBSERVATION` | **on** (observation-only) |

FACT promotion has no separate flag — it is opt-in via Host approval only.

## Explicit non-goals (this contract)

- No DecisionContext / `actionEnvelope` / regime scores
- No threshold / gate / deploy objects (POLICY forever, never FACT)
- No dual-axis / breakout / sim positions
- No implication that wait-to-buy beats DCA

## Related

- T2 ledger: `docs/OHLC_LEDGER.md`
- Epistemic UI badges: `src/core/epistemic_badges_v5.js`

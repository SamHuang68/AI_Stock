# Promotion Gate — Shadow Research → Decision Wiring

**Policy:** manual Host review only; **no auto-promote**.  
**Module:** `server/promotion_gate.py`  
**Default verdict:** `FAIL`

---

## Purpose

Shadow research surfaces (P2 multifactor ranking, ML experiment stubs, longer-horizon
conditional cards) must not write into Decision or exposure envelopes until this gate
passes with documented evidence.

## Required criteria

| Check | Requirement | Rationale |
|-------|-------------|-----------|
| **OOS report** | `status=complete`, `reportId`, `asOf`, `sampleSize≥60`, `windows≥3` | Walk-forward out-of-sample evidence |
| **Cost / turnover** | `status=documented`, `costBps`, `turnoverBps`, non-empty `summary` | Net-of-cost feasibility |
| **Decay monitor** | `status=active`, `metric`, `lookbackDays`, `alertThreshold` | 失效 / drift detection before promotion |
| **Feature count cap** | `1 ≤ featureCount ≤ 8` | Complexity guard per Host Gate |

## API / code hooks

```python
from promotion_gate import evaluate

result = evaluate(evidence_bundle)  # verdict: 'FAIL' until all checks pass
assert result['autoPromote'] is False
```

- `GET /research/promotion-gate` — returns default `FAIL` checklist (read-only).
- Shadow multifactor payload embeds `promotionGate` for UI visibility.
- `?demoPass=1` on the gate endpoint is **test-only**; production callers must supply a real bundle.

## NON-GOALS

- No production Decision wiring from this document alone.
- No guaranteed-alpha marketing copy.
- No LLM Decision score ingestion.
- No `llm_gate` acquisition from promotion workflows.

## Epistemic discipline

| Tier | Example in P2 |
|------|----------------|
| **FACT** | Chip path state (P1), quote `asOf` timestamps |
| **CONDITIONAL** | Multifactor rank scores, long-horizon bin stats |
| **HYPOTHESIS** | ML experiment stub (`st-ml-linear-stub/v0`) |

Stale `asOf` degrades rank scores (50% penalty) and marks `degraded: true` on basket rows.

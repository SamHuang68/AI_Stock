# FINDINGS — Conditional Expectation P0 (advisory / patch_proposal)

**Policy:** advisory / patch_proposal  
**Author:** Cloud Agent (composer-2.5)  
**Date:** 2026-09-06  
**Branch:** `cursor/conditional-expectation-findings-b422`  
**Host Gate:** P0 approved — descriptive → conditional indicators; ForecastPack / ML deferred.

---

## Executive summary

Stock Terminal already has strong **FACT** (deterministic DecisionContext) and **HYPOTHESIS** (postmarket LLM narrative) lanes, plus mature **shadow** patterns (`shadowOnly`, `actionAuthority: none`, prospective ledgers). What is **missing for P0** is a symbol-scoped **CONDITIONAL** card: rule-binned historical conditional expectations with an explicit **asOf gate** that can invalidate prediction usability when quote/chips are stale.

This document maps existing surfaces, lists gaps with file anchors, proposes the smallest shippable slice, ranks follow-ups by edge/effort, and notes look-ahead risks. A tiny scaffold (`server/conditional_expectation.py`, flag `shadowConditionalExpectation`, default **OFF**) lands in the same PR for contract alignment only — no bin engine yet.

---

## 1. Surface map — what exists today

### 1.1 Pulse (market overview) — mostly descriptive FACT

| Area | Role | Key paths | Stats vs predictive |
|------|------|-----------|---------------------|
| Orchestration | Canonical `/pulse` payload | `server/pulse_orchestration.py`, `server/pulse_routes.py` | Descriptive: `healthScore`, `riskScore`, breadth, sectors, global, strip KPIs |
| UI | 5+5 desktop grid | `src/ui/pulse_v5.js` | Renders pulse + **read-only** decision summary (`decisionRegime`, `decisionAsOf`) — does not compute predictions |
| Freshness | Shell quote age | `src/core/market_freshness_v5.js` | `fresh` ≤120s, `delayed` ≤900s, else `stale` — **display only**, not a prediction gate |
| asOf | Per-quote + pulse time | `marketSnapshot.quotes.*.market.asOf`, `pulse.updatedAt` | Shown in pulse subline (`pulse_v5.js` ~3907) |

**Verdict:** Pulse is **FACT/descriptive** at market level. No symbol conditional return bins.

### 1.2 Decision (Strategic Decision) — canonical FACT + shadow research

| Area | Role | Key paths | Stats vs predictive |
|------|------|-----------|---------------------|
| Engine | Regime, envelope, levels | `server/decision_context.py` | **FACT:** `regime`, `actionEnvelope`, `keyLevels`, `volatility`, `divergences` — all rule-produced, replayable |
| Freshness | Market-level quality | `decision_context.dataQuality` (`freshness`, `staleFields`, `missingCore`) | Ages from pulse `asOf` (~300s/1800s/21600s tiers, lines 865–873) |
| Store | Single writer | `src/core/decision_data_v5.js` | Publishes summary; **does not** merge prediction scores into envelope |
| UI | Auditable decision page | `src/ui/decision_v5.js` | Exposure numbers, shadow panels labeled “Shadow · 觀察” |
| Shadow: Early Warning | Cross-market precursors | `server/early_warning.py` | **Prospective validation** ledger: horizons `(1,3,5)` sessions, rates withheld until `n≥20` (`OUTCOME_MIN_SAMPLE`) |
| Shadow: Overnight×Intraday | Regime observation | `server/overnight_intraday.py`, `docs/OVERNIGHT_INTRADAY_RESEARCH.md` | Bounded `evidenceStrength` — explicitly **not** win rate |
| Shadow: Consensus Attention | Ranking only | `server/consensus_attention.py` | `strengthIsProbability: false`, `authority: attention_only` |

**Verdict:** Decision numbers are **FACT**. Closest predictive-adjacent pattern is `early_warning` **prospective ledger** (empirical rates after forward resolution, not same-day bins).

### 1.3 Postmarket daily — EvidencePack FACT + narrative HYPOTHESIS

| Area | Role | Key paths | Epistemic tier |
|------|------|-----------|----------------|
| Evidence builder | Per-symbol pack, no LLM | `server/postmarket_report.py::build_evidence_pack` | **FACT:** `quote`, `techSummary` (Wilder RSI/SMA via `indicators`), `chips`, `news`, `decisionSummary` |
| asOf map | Per-field timestamps | `pack.evidenceAsOf` | quote/tech/chips/news/decision keys |
| Staleness gate | Quote-only today | `postmarket_report.staleness()` | **Partial asOf gate:** post-close >6h or intraday >1h → `stale`, `staleReasons`; chips **not** gated |
| LLM narrative | drivers/hypotheses/risks/watchTomorrow | `validate_narrative`, `system_prompt` | **HYPOTHESIS** — must not recompute regime/exposure (`decisionSummary` read-only) |
| UI | Report drawer | `src/ui/postmarket_v5.js` | Shows stale badge, evidence asOf; labels “非投資建議” |

**Gap note:** User spec mentions “EvidencePack **anomalies**” → tomorrow validation points. **No structured `anomalies[]` field exists** in EvidencePack today. Closest proxies: `techSummary` thresholds, `chips` streaks, narrative `watchTomorrow` (LLM prose, not rule IDs).

### 1.4 asOf / freshness — fragmented but reusable

| Layer | File | Scope | Prediction gate? |
|-------|------|-------|------------------|
| Shell health | `src/core/market_freshness_v5.js` | Worst quote age in snapshot | No |
| Decision quality | `server/decision_context.py` | Market pulse `asOf` → `dataQuality.freshness` score | Degrades confidence, not a card-level “expired” |
| Postmarket | `server/postmarket_report.py` | Quote `asOf` vs report time | **Yes** for narrative risks injection |
| Consensus attention | `server/consensus_attention.py::_freshness` | Per attention item | Ranking degrade only |

**P0 opportunity:** Centralize symbol-level gate in one helper (scaffold: `conditional_expectation.evaluate_asof_gate`) and reuse postmarket hour thresholds for quote; extend to chips lag.

### 1.5 Feature flags / shadow discipline — ready for P0

| Mechanism | Path | Notes |
|-----------|------|-------|
| Server flags | `server/feature_settings.py`, `GET /features` | `ST_ENABLE_SHADOW_RESEARCH` master; per-flag env |
| Client mirror | `src/core/feature_flags_v5.js` | Defaults all shadow flags `false` |
| Contract fields | Shadow payloads | `shadowOnly`, `actionAuthority: none`, `decisionUse: research_only` |
| Tests | `tests/test_shadow_feature_gates.py` | Disabled routes return 200 + cheap payload |

---

## 2. Gap analysis — P0 Conditional Expectation + asOf Gate

### 2.1 Conditional Expectation card (rule bins) — **MISSING**

**Required (Host Gate P0):** For symbol state \(S\), show historical **conditional** median return, win rate, N, max-drawdown quantile, invalidation rules, horizons \(H \in \{1,5,20\}\), labeled **CONDITIONAL**.

**What we have that can feed state \(S\) (do not duplicate pipelines):**

| State feature | Existing source | Path |
|---------------|-----------------|------|
| OHLC + RSI/SMA | Daily bars + `indicators` | `datastore.get_bars`, `postmarket_report.tech_summary_from_bars` |
| Chips | Institutional / margin / streak | `chip_api.build_chip`, `postmarket_report._chip_evidence` |
| Market regime context | Read-only snapshot | `decision_context.latest_context()` via `decision_snapshot` |
| Sector | TWSE mapping | `postmarket_report._universe_meta` / `_get_tw_sectors` |

**What we lack:**

1. **Bin definition contract** — discrete rule bins (e.g. `RSI14∈[30,40)` ∧ `inst_net_3d>0`) with versioned `binModelId`.
2. **Point-in-time outcome table** — forward returns at T+1/T+5/T+20 **computed without look-ahead** (see §4).
3. **Aggregation** — median return, win rate, N, max-DD quantile per bin×horizon.
4. **invalid-if** — explicit predicates that zero the card (stale asOf, N&lt;min, listing gap, etc.).
5. **UI card** — epistemic badge `CONDITIONAL`, never merged into `actionEnvelope` / position range.
6. **API** — e.g. `GET /research/conditional-expectation?symbol=` behind `shadowConditionalExpectation`.

**Reference implementation patterns to copy (not reinvent):**

- Sample gating: `early_warning.OUTCOME_MIN_SAMPLE` (20) — use **≥30** for return bins (more tail noise).
- Shadow HTTP: `server/overnight_intraday_routes.py` (200 + disabled payload when flag off).
- Epistemic separation: `docs/POSTMARKET_DAILY.md` red lines + `decision_context` “never LLM for regime”.

### 2.2 asOf Gate — **PARTIAL**

| Check | Today | P0 need |
|-------|-------|---------|
| Quote stale for prediction | `postmarket_report.staleness` | Reuse + expose on conditional card |
| Chips stale (T+2 lag) | Only `evidenceAsOf.chips` string | Compare chip date vs last session; degrade card |
| Tech asOf | Same as quote (daily bar close) | Tie to bar `asOf` |
| Card status | N/A | `usable: false`, `status: expired`, `invalidIf: [...]` |

Scaffold lands `evaluate_asof_gate()` in `server/conditional_expectation.py` calling postmarket `staleness` for quote and adding chip session lag check.

### 2.3 Postmarket → tomorrow validation points — **PARTIAL**

| Item | Status |
|------|--------|
| `watchTomorrow` in narrative | Exists — **HYPOTHESIS** (LLM) |
| Rule-derived validation points | **Missing** — need deterministic checklist from EvidencePack state (e.g. “若明日收盤 &lt; SMA20 則 bin invalid”) |
| Structured anomalies | **Missing** — recommend `evidencePack.anomalies[]` with `{id, metric, value, threshold, epistemic: "FACT"}` in **postmarket builder only** (no new fetch) |

### 2.4 UX labels FACT \| CONDITIONAL \| HYPOTHESIS — **NOT UNIFIED**

| Tier | Current examples | Gap |
|------|------------------|-----|
| FACT | Decision regime, exposure, EvidencePack numbers | No shared badge component |
| CONDITIONAL | — | Not implemented |
| HYPOTHESIS | Postmarket drivers/hypotheses, AI local advisory | Not labeled consistently in UI |

**P0 UI rule:** Decision / exposure numbers remain **FACT** and immutable by prediction cards. Conditional card is adjacent panel with `CONDITIONAL` chip; postmarket sections keep `HYPOTHESIS`.

### 2.5 Deferred (Hermes) — do NOT implement in P0

- ForecastPack / ML scores before walk-forward — **out of scope** (see `exposure_lab.py` horizon forecast = slow research denominator only).

---

## 3. P0 implementation plan — smallest shippable slices

### Slice 0 (this PR) — advisory + contract scaffold ✅

- This FINDINGS doc.
- `server/conditional_expectation.py` — contract constants, `evaluate_asof_gate`, `disabled_payload`, `build_card` → `status: DISABLED|SCAFFOLD`.
- `server/conditional_expectation_routes.py` — `GET /research/conditional-expectation`.
- Flag `shadowConditionalExpectation` default OFF (`feature_settings.py`, `feature_flags_v5.js`).
- Tests: gate unit tests + disabled route 200.

### Slice 1 — backend bin engine (shadow only)

1. **`bin_state(symbol, as_of_date)`** — reuse `tech_summary_from_bars` + `chip_api` + optional regime tag from `decision_snapshot` (market-level, not leaking future).
2. **`conditional_stats.sqlite`** (or extend `data/market.db`) — nightly job materializes bin×horizon stats from **point-in-time** feature rows.
3. **`build_card(symbol)`** returns:

```json
{
  "epistemic": "CONDITIONAL",
  "shadowOnly": true,
  "actionAuthority": "none",
  "decisionUse": "research_only",
  "symbol": "2330",
  "binId": "rsi14_band×inst3d×regime/v1",
  "horizons": {
    "1": {"medianReturnPct": 0.42, "winRate": 0.58, "n": 47, "maxDrawdownQ90Pct": -3.1},
    "5": { "...": "..." },
    "20": { "...": "..." }
  },
  "invalidIf": ["quote_asof_stale", "n_below_minimum"],
  "asOfGate": {"usable": false, "status": "expired", "reasons": ["..."]},
  "predictiveProbability": false
}
```

4. Wire **no** mutation into `publish_context` / `actionEnvelope`.

### Slice 2 — UI card (flagged)

- Symbol context: chart side panel or postmarket drawer subsection.
- CSS badge: `FACT` (gold), `CONDITIONAL` (cyan), `HYPOTHESIS` (muted purple).
- When `asOfGate.usable === false` → grey card “資料過期 · 不適合作為預測參考”.

### Slice 3 — postmarket validation points

- Add `anomalies[]` + `validationPoints[]` to `build_evidence_pack` (rule-only).
- Map each point to tomorrow session resolution hook (reuse `early_warning` session calendar helpers).
- LLM may **rephrase** validation points in `watchTomorrow` but **cannot invent** metrics (extend `validate_narrative` / citations).

---

## 4. Look-ahead & methodology risks

| Risk | Mitigation |
|------|------------|
| Using full-sample RSI/SMA on date T with knowledge of T+k | Compute features with bars `[:T]` only; materialize in offline job |
| Chip data available only T+2 but labeled T | Bin assignment uses **published** chip date; forward return starts from **next tradable session after chip known** |
| Survivorship / listing changes | Freeze universe per date from `universe` history or exclude young listings (`bars < 60`) |
| Same-bar close → “tomorrow” return | Forward return: open(T+1) or close(T+1) — pick one, document in `binModelId` |
| Multiple hypothesis peeking | Version bins; log `binModelId` + `statsAsOf`; no auto-refresh on every tick |
| Confusing conditional history with Decision confidence | Hard separation: conditional card cannot write `regime.confidence` |
| LLM inventing Decision numbers | Already guarded in postmarket — extend to conditional card (no LLM in slice 1) |

---

## 5. Top improvements ranked (edge × effort)

| Rank | Item | Edge | Effort | Notes |
|------|------|------|--------|-------|
| 1 | Unified **asOf gate** (quote+chips) for any “prediction” surface | High — prevents stale misuse | **S** | Reuse `postmarket_report.staleness`; extend chips |
| 2 | **Conditional Expectation** card (rule bins, H=1/5/20) | High — core P0 | **L** | Offline PIT table; shadow flag |
| 3 | Epistemic badges **FACT\|CONDITIONAL\|HYPOTHESIS** in UI | Medium — trust / compliance | **S** | Shared CSS + `data-epistemic` |
| 4 | EvidencePack **`anomalies[]` + `validationPoints[]`** (rules) | Medium — closes postmarket loop | **M** | Extends `build_evidence_pack` only |
| 5 | Prospective resolution job for validation points | Medium — measurable tomorrow checks | **M** | Pattern from `early_warning` ledger |
| 6 | Symbol card in chart shell (not new page) | Medium — discoverability | **M** | Follow `postmarket_v5` drawer pattern |
| 7 | Central `epistemic_policy.json` manifest | Low immediate edge | **S** | Documentation + lint in tests |
| 8 | ForecastPack / ML (walk-forward) | High long-term | **XL** | **Deferred** per Host Gate |

---

## 6. Files touched / proposed (P0 trajectory)

| File | Action |
|------|--------|
| `docs/FINDINGS_CONDITIONAL_EXPECTATION_P0.md` | **Added** (this doc) |
| `server/conditional_expectation.py` | **Added** scaffold |
| `server/conditional_expectation_routes.py` | **Added** route |
| `server/feature_settings.py` | **Extended** flag |
| `src/core/feature_flags_v5.js` | **Extended** flag |
| `server/server.py` | **Wire** route + mixin |
| `tests/test_conditional_expectation.py` | **Added** |
| `server/postmarket_report.py` | Slice 1: export shared staleness import path (optional refactor) |
| `src/ui/*` | Slice 2: conditional card component |

---

## 7. Acceptance criteria (P0 complete)

- [ ] Conditional card returns rule-binned stats for at least 3 canonical bins on TW equities sample.
- [ ] `asOfGate.usable === false` when quote or chips exceed thresholds; card shows expired state.
- [ ] Decision `actionEnvelope` byte-identical with/without flag enabled.
- [ ] All surfaces label epistemic tier; LLM never emits confidence/regime overrides.
- [ ] Tests: PIT spot checks, gate tests, shadow flag off → no heavy compute.
- [ ] Walk-forward report for bin model before any promotion out of shadow.

---

*End of FINDINGS — advisory / patch_proposal*

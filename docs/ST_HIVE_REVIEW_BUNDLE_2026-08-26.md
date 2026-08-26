# Stock Terminal v5.0 — HIVE Sanitized Review Bundle

Review scope: `st-evolution-review-2026-08-26`  
Repository baseline: `beb38654e270fb0a98c3730e920dd8d197b3c0be`  
Bundle date: 2026-08-26  
Classification: sanitized project summary; external advisory review allowed  
Authority: workers are read-only advisers; ChatGPT/Codex Host remains the sole writer and final integrator

## 1. Review objective

Stock Terminal (ST) is a local-first Taiwan/US market research and decision-support terminal. The owner considers it a high-value personal asset and wants a rigorous multi-model review that identifies how it can become materially more useful, differentiated, trustworthy, and maintainable. The desired endpoint is not “more panels”; it is earlier, auditable recognition of downside precursors and upside acceleration while retaining professional drill-down data.

The product focus is:

- Taiwan market direction and market breadth.
- AI supply-chain leadership, especially a de-duplicated TSMC / Taiwan-50 anchor relationship.
- Taiwan and US memory-industry synchronization.
- Futures, options, institutional flow, leverage, liquidity, and international technology spillover.
- Clear separation between observed facts, derived metrics, modeled scenarios, and shadow research.
- Beginner-readable summaries plus professional evidence and formula inspection.
- Desktop and mobile access through an authenticated private gateway.

This review must challenge the product thesis, not merely praise the current feature list.

## 2. Non-goals and safety boundary

- Do not request or infer credentials, tokens, email addresses, private hostnames, raw holdings, cost bases, personal messages, logs, local databases, or runtime market-data files.
- Do not propose autonomous trading or claim that a score is a probability without prospective calibration.
- Do not edit files, run tools, browse the workspace, or return patches.
- Do not repeat generic dashboard advice unless it is tied to this product’s decision loop and measurable acceptance criteria.
- Do not assume public options open interest reveals dealer inventory direction.

## 3. Current product architecture

### Browser layer

- Classic-script single-page application assembled deterministically by `build_v2.py`.
- `ShellV5` owns routing and page lifecycle.
- `MarketData` is the single market-snapshot writer.
- `DecisionData` is the single deterministic decision-context writer.
- Major experiences: Pulse overview, chart workstation, Decision Center, breadth, sector rotation, institutional flow, global markets, news impact, screening, watchlist, portfolio risk, settings, and optional WaveDeck integration.
- Progressive disclosure: beginner, professional, and decision views; responsive portrait paging and landscape 5+5 layout.

### Local service layer

- Python standard-library HTTP server bound to loopback.
- Authenticated private-Web gateway for remote/mobile use, with same-origin writes, role separation, body limits, route allow/deny lists, audit metadata, and persistent login.
- Canonical market contract carries symbol, market, source, timestamp, session, comparison type, comparison price, and display change.
- Deterministic `DecisionContext` owns regime, confidence, divergences, Action Envelope, confirmation/invalidation conditions, key levels, and Evidence Ledger.
- Domain modules cover exposure research, options structure, overnight/intraday decomposition, sector participation, news impact, key levels, portfolio risk, and precursor alerts.
- File/SQLite persistence is local; share builds use an allow-list and privacy scanner.

### AI boundary

- AI is an explanatory layer, not the authority for market regime or alert activation.
- Local AI can run on the host machine through bounded server-side routes; remote phones are clients and do not perform model inference.
- A dual-route local runtime exists for fast/deep explanations, with load-aware status and bounded commands.

## 4. Capabilities worth protecting

1. One canonical market snapshot prevents header, overview, and chart from calculating the same theme differently.
2. Taiwan and US price-color semantics are explicitly separated.
3. Evidence items retain source, market time, session, comparison basis, scope, and quality.
4. Missing or stale evidence fails closed rather than becoming zero or neutral.
5. Decision rules are deterministic and replayable; AI cannot overwrite them.
6. Position ranges require a complete risk profile and usable portfolio coverage.
7. Options outputs distinguish observed OI, derived neutral density, and modeled signed-GEX/VEX scenarios.
8. Leveraged-exposure research distinguishes a monthly core, weekly monitoring, and daily product mechanics.
9. The precursor engine de-duplicates the TSMC and Taiwan-50 anchors, uses multiple evidence domains, persists lifecycle transitions, applies hysteresis, and labels scores as evidence strength rather than probability.
10. Public release packaging excludes private state and secrets and is reproducible.

## 5. Current decision loop

```text
public market sources
  -> source adapters and bounded cache/fallback
  -> canonical quote and evidence contracts
  -> deterministic market features
  -> DecisionContext + shadow research
  -> Pulse / Decision / chart / remote mobile views
  -> optional explanatory AI
  -> user decision and later replay/audit
```

The intended user answers within seconds:

1. What market regime is active?
2. Is participation broad or concentrated?
3. Which evidence domains agree or conflict?
4. What actions are allowed, restricted, or invalidated?
5. Which data is stale, missing, proxy-based, or modeled?

## 6. Current analytical layers

### Authoritative deterministic layer

- Market snapshot and source/session/reference contract.
- Breadth, trend, flow, risk, key levels, volatility, portfolio constraints.
- Named divergences and Action Envelope.
- Decision history and Evidence Ledger.

### Shadow research layer

- Cross-market precursor radar with five de-duplicated evidence domains and four named signal families.
- Overnight versus intraday repricing/acceptance structure for fixed Taiwan/US memory baskets.
- Options signed exposure and flip scenarios where dealer direction is unobserved.
- Dynamic-leverage / exposure research whose assumptions and benchmark limitations remain explicit.

### Current precursor goals

- Detect broad downside deterioration before a visible Taiwan-index decline when independent domains confirm.
- Detect synchronized upside acceleration rather than reacting to one high-beta stock.
- Emphasize AI dual anchors and memory-cycle confirmation without double counting correlated constituents.
- Use a state machine (`watch`, `confirmed`, `active`, `cooldown`) and transition-only alerts to reduce noise.
- Keep deterministic alerts independent of AI narrative generation.

## 7. Repository and change profile

- 64 Python files under the server layer.
- 90 tracked front-end JavaScript/CSS assets.
- 59 Python/JavaScript test files.
- 22 tracked Markdown documents.
- Recent work added private remote access, mobile paging, local AI, overnight/intraday research, and cross-market precursor alerts in rapid succession.

Largest compatibility surfaces by current line count:

| File | Lines | Risk interpretation |
|---|---:|---|
| `server/server.py` | 7,282 | route dispatch, orchestration, adapters, caches and compatibility remain concentrated |
| `src/ui/pulse_v5.js` | 3,870 | dense overview product logic and rendering |
| `src/ui/shell_v5.js` | 1,903 | route/lifecycle/responsive compatibility surface |
| `src/chart/market_chart_v3.js` | 1,725 | chart behavior and market-specific display logic |
| `src/ui/decision_v5.js` | 1,659 | decision visualization, progressive disclosure, evidence rendering |
| `server/decision_context.py` | 1,475 | deterministic rules and contract assembly |

Static inventory found roughly 249 `window.*` assignments and 140 front-end fetch/API mentions. These are not automatically defects, but they indicate continued sensitivity to script order, implicit globals, duplicated lifecycle hooks, and request fan-out.

## 8. Verification evidence at this baseline

The canonical local command matching CI was executed:

```text
python -m unittest discover -s tests -v
```

Observed result:

- 253 tests discovered.
- 7 import errors.
- 1 explicitly skipped live-provider test.
- No assertion failures among loaded tests.
- The seven errors share one architectural root: `server/server.py` can be imported as top-level module `server`, shadowing the `server/` namespace package. Later tests then cannot import `server.atomic_store`, `server.deadline`, `server.http_boundary`, `server.secret_store`, and related modules.
- The CI workflow runs the same discovery command on Windows and Ubuntu, so this is a release-gate credibility defect, even though targeted domain suites have previously passed.
- The run also exercised deterministic HTML/archive build and privacy scanning successfully.

Interpretation: domain correctness is strong, but a green targeted suite is not equivalent to a green canonical release gate. A product that markets auditability must first make its own verification topology unambiguous.

## 9. Known residual risks

1. Precursor evidence strength is not a calibrated probability. Prospective lead-time, precision, recall, false-positive cost, and regime drift are not yet established.
2. Memory-basket data can be unavailable or stale; it deliberately degrades rather than imputing direction.
3. Taiwan-50 / TSMC historical point-in-time constituent weights are limited; de-duplication depends on the quality and date of the weight input.
4. Public options OI cannot prove market-maker net direction, so signed dealer exposure remains scenario research.
5. External public providers can delay, revise, rate-limit, or omit timestamps.
6. `server.py`, Pulse, Shell, Decision UI, and the classic-script global surface remain large change-radius hotspots.
7. The private remote host is still a local-machine service and depends on host uptime and private-network infrastructure.
8. The current release process has strong reproducible/privacy gates but the canonical test-discovery collision weakens the meaning of “all checks passed.”
9. Feature velocity is high; governance, prospective evaluation, and removal of low-value features may lag feature creation.

## 10. Questions every reviewer must answer

### A. Product value and differentiation

1. What is ST’s defensible product loop beyond aggregating public data?
2. Which three capabilities can create the highest incremental user value during the next 90 days?
3. Which current panels or metrics are redundant, distracting, or should be demoted?
4. How can ST turn evidence into earlier action without becoming an unsafe signal-selling product?
5. Which outcomes should be measured weekly to prove the product is becoming more useful?

### B. Quantitative validity

1. How should precursor signals be prospectively evaluated without look-ahead, survivorship, repeated-peeking, or correlated-domain double counting?
2. What minimum sample sizes, baselines, abstention rules, calibration plots, and alert-cost metrics are required?
3. How should session alignment, holidays, stale inputs, delayed international data, ETF constituent overlap, and options-expiry changes be handled?
4. Which existing research layers should remain shadow-only, which can graduate, and what exact evidence permits graduation?
5. What adversarial fixtures would most likely falsify the current signal thesis?

### C. Architecture, reliability, and security

1. What seams should be extracted first from the current hotspots without a rewrite?
2. How should route ownership, dependency direction, state stores, background jobs, cancellation/deadlines, cache semantics, and observability evolve?
3. How should the canonical release gate be repaired and made trustworthy across Windows and Linux?
4. What failure modes could show a confident but stale or internally inconsistent decision?
5. Which architectural investments produce the best risk reduction per unit of work?

### D. UX, mobile, and decision cognition

1. What should appear in the first three seconds, the next thirty seconds, and professional drill-down?
2. How should alert urgency, confidence/evidence strength, data quality, contradiction, and invalidation be visually distinct?
3. How can mobile portrait remain useful without hiding critical context or relying on accidental browser scrolling?
4. What interactions should be removed or consolidated?
5. What accessibility, typography, touch-target, and layout checks should become automated gates?

### E. AI and operating model

1. Where can local AI create real value while remaining downstream from deterministic evidence?
2. What should AI never be allowed to infer or mutate?
3. How should explanations cite Evidence Ledger items and disclose missing/conflicting data?
4. Is a “morning brief / change since last decision / what invalidated” workflow more valuable than open-ended chat?
5. How should model latency, availability, privacy, and hallucination be measured?

## 11. Required review output contract

Return Markdown with these exact top-level sections:

1. `Verdict`
2. `Strengths to protect`
3. `Top findings` — 8 to 12 numbered findings; each must include priority, evidence from this bundle, user impact, proposed change, and a measurable validation gate.
4. `Three highest-value bets`
5. `Things not to build or to demote`
6. `90-day roadmap` — Now / Next / Later, with dependency order.
7. `Metrics and experiments`
8. `Contradictions or assumptions to challenge`
9. `Questions for the owner`

Rules:

- Clearly distinguish facts from inferences.
- Prefer a smaller number of high-leverage changes over feature accumulation.
- Treat model-generated advice as advisory.
- Do not output chain-of-thought.
- Do not state that a finding was source-code verified; the worker received only this bounded bundle.
- Keep the response under 3,500 words.

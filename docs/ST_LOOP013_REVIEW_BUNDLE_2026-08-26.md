# Stock Terminal LOOP-013 independent implementation review bundle

Classification: `public-sanitized-review`  
Authority: advisory only; no source access; no write permission.

## Objective

Restore a truthful full-suite release gate and add prospective measurement for deterministic cross-market precursor alerts without granting trading authority.

## Implemented contracts

1. Package identity: legacy top-level import of the HTTP entrypoint now exposes its sibling-module search path, removing full-suite package/module collision while preserving the single-file launcher.
2. Prospective ledger: the existing precursor SQLite database gains market-session, trial, and immutable outcome tables. No second price provider was added.
3. Enrollment: one trial per `signal + direction + firstSeenAt` episode, beginning only when a signal first reaches WATCH／ARMED／CONFIRMED／ACTIVE. No retrospective backfill.
4. Reference data: entry uses canonical current TWII from Pulse; exits use existing finalized TWII index-history closes at 1, 3, and 5 future sessions.
5. Outcomes: raw return, direction-signed return, direction correctness, maximum favorable/adverse excursion, 2% favorable-move hit, and lead sessions.
6. Aggregation: the default summary includes only the two headline precursors, preventing correlated AI-wafer and memory-cycle component signals from inflating pooled sample counts. Components remain individually queryable.
7. Small-sample gate: every horizon withholds hit rates, false-alert rate, averages, and median lead until at least 20 resolved trials. The UI shows `n/20`, not a probability.
8. Authority: `shadowOnly=true`, `actionAuthority=none`, `predictiveProbability=false`. Ledger failure is isolated and cannot suppress canonical signal state.
9. Surfaces: read-only `/signals/performance` endpoint, Private Web read allow-list, one Evidence Ledger row, and a compact Decision panel section.
10. Immutability: resolved horizon outcomes are insert-once. Later source corrections can update pending market-session observations but cannot rewrite a resolved outcome.

## Verification evidence

- Canonical Python discovery: 269 tests passed, 1 opt-in live test skipped.
- Added tests cover one-time enrollment, 1／3／5 resolution, immutable outcomes after a source correction, the n=20 publication boundary, API contract, Evidence row, and Private Web read-only access.
- JavaScript syntax and the broad UI contract self-test passed.
- Reproducible build and pre/post-compression privacy scanning passed.
- Chrome visual verification at desktop and 390×844 portrait: the new card is visible, has no local horizontal overflow, uses three compact horizon cells, and the browser console has no product errors.
- No commit, push, deployment, credentials, holdings, private hostnames, runtime databases, or raw source are included here.

## Review request

Perform an adversarial read-only review. Report only:

1. Any P0/P1 correctness or data-integrity defect in episode identity, session alignment, outcome immutability, aggregation, or sample gating.
2. Any way the UI/API wording could still be mistaken for predictive probability or trading authority.
3. Any missing deterministic test that is necessary before accepting LOOP-013.

For every finding, state severity, violated invariant, a concrete counterexample, and the smallest remediation. If no P0/P1 exists, say so explicitly.

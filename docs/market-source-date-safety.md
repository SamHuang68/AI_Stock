# Market Source and Date Safety

Baseline: main `3d1c38d69851a288b15798dd8dc8630f02fda280`, also the verified private-web deployment on 2026-10-01. This selectively reconciles remaining source/date safeguards from conflicting PR65; it does not merge the obsolete TIP branch.

Existing main safeguards remain: official chip payload date agreement, verified chip-history records, serialized/atomic history updates, and live margin source checks. No old PR65 history writer replaces them.

Necessary additions:
- Strict official Gregorian/ROC dates and Taipei calendar boundaries; unknown source dates remain unknown, including chip API and TPEx MIS close.
- TWSE marketflow validates actual FMTQIK/BFI82U/MI_MARGN dates. Missing institutional values remain null; genuine zero remains zero. API, fundamentals, Pulse and breadth share a versioned canonical cache key; old unvalidated cache is excluded.
- TXF requires official CDate and CTime, retains sourceDate/asOf for primary and night sessions, rejects missing/invalid/future timestamps, and does not manufacture quote time for explicit unknown asOf.
- OTC history uses TPEx st41/TWSE MIS only. Successful migration archives legacy rows before replacement under a savepoint; failed migration rolls back, and consumers exclude legacy rows.
- Margin seeds reject malformed, duplicate, unsorted, future or nonfinite rows and preserve rejected files. Writes are atomic with backup. Pulse institutional history requires the observed official response date and labels pending publication.
- Chip UI tolerates unknown official date without crashing.

Optional performance tracing, TXF refresh-time gating, proactive hydration and unrelated UI changes from PR65 are excluded. No deployed service, market seed, production database or original dirty working tree is changed by authoring this PR. Live providers and production deployment are not tested.

Validation: full unittest discovery; 22 JavaScript contract self-tests; compileall; build_order; build_v2 to isolated CI HTML; PowerShell launcher parse; git diff --check. Added source/date regressions include malformed seeds, archive/rollback behavior, absent/mismatched official dates, TXF timestamp fidelity and canonical cache consumption. Local independent cross-review found the stale breadth cache consumer; the fix and three behavioral regressions were independently checked.

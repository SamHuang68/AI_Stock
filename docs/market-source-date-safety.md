# Market Source and Date Safety

Baseline: main `3d1c38d69851a288b15798dd8dc8630f02fda280`, also the verified private-web deployment on 2026-10-01. This selectively reconciles remaining source/date safeguards from conflicting PR65; it does not merge the obsolete TIP branch.

Existing main safeguards remain: official chip payload date agreement, verified chip-history records, serialized/atomic history updates, and live margin source checks. No old PR65 history writer replaces them.

Necessary additions:
- Strict official Gregorian/ROC dates and Taipei calendar boundaries; unknown source dates remain unknown, including chip API and TPEx MIS close.
- TWSE marketflow validates actual FMTQIK/BFI82U/MI_MARGN dates. Missing institutional values remain null; genuine zero remains zero. API, fundamentals, Pulse and breadth share a versioned canonical cache key (one helper per payload: `marketflow_cache_key`, `breadth_cache_key`); old unvalidated cache is excluded. The payload's top-level `date` is the latest observed official source date, never the request day (`null` when nothing was observed). A payload with no turnover and no institutional data (every upstream call failed) is cached for 60 s instead of 30 min, and the three sections are fetched in parallel.
- TXF requires official CDate and CTime, retains sourceDate/asOf for primary and night sessions, rejects missing/invalid timestamps and stamps more than 120 s ahead of the local clock (a few seconds of clock lag is tolerated), and does not manufacture quote time for explicit unknown asOf.
- OTC history uses TPEx st41/TWSE MIS only. Successful migration archives legacy rows before replacement under a savepoint; failed migration rolls back, and consumers exclude legacy rows.
- Margin seeds reject malformed, duplicate, unsorted, future or nonfinite rows and preserve rejected files. Writes are atomic with backup. Pulse institutional history requires the observed official response date and labels pending publication.
- Chip UI tolerates unknown official date without crashing.

Optional performance tracing, TXF refresh-time gating, proactive hydration and unrelated UI changes from PR65 are excluded. No deployed service, market seed, production database or original dirty working tree is changed by authoring this PR. Live providers and production deployment are not tested.

Validation: full unittest discovery; 22 JavaScript contract self-tests; compileall; build_order; build_v2 to isolated CI HTML; PowerShell launcher parse; git diff --check. Added source/date regressions include malformed seeds, archive/rollback behavior, absent/mismatched official dates, TXF timestamp fidelity and canonical cache consumption. Local independent cross-review found the stale breadth cache consumer; the fix and three behavioral regressions were independently checked.

## Review follow-ups and deliberately deferred items

Fixed after the two static reviews of the combined change: a rejected margin seed no longer triggers a crawl-and-fail on every call (it is left untouched; an empty or missing seed is rebuilt); the oldest row of each `^TWOII` window no longer loses its `change_pct`; margin, short-lending and day-trade blocks and the breadth day reject a response that states a different day (a response with no `date` field is still accepted) and are not queried for "today" when no official chip date exists; Pulse read the breadth cache under a stale key; `chip_v3` printed `（//）` for an unknown date; `^TWOII` history now says its open/high/low are derived (`ohlcDerived`).

Deferred (not bugs in this change, or needing a decision):

- The "validate an official date, reject future, format `YYYYMMDD`" pattern is open-coded in about six places and `sector_flow.normalize_session_date` is a second, looser parser that Pulse still uses. A single `official_day()` helper would remove the repetition.
- A few host-local `date.today()` calls remain (`tw_index_charts.py`, and the cache key in `server._handle_chip`). Harmless on a UTC+8 host; wrong at the day boundary elsewhere.
- `^TWOII` rows still store synthesized open/high/low and `volume=0` (only close and change are official). They are flagged, not removed, because consumers do arithmetic on the columns.
- Live provider smoke tests (TWSE, TPEx, TAIFEX, Yahoo) were not run: those hosts are not reachable from the environment the fixes were made in. Run a manual smoke test after deploying.

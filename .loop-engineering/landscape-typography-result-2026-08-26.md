# Stock Terminal mobile-landscape typography result

## Outcome

The short touch-landscape view keeps the accepted `5col-2zone` contract while eliminating the remaining text-paint and compact-chart collisions. The correction is limited to `(orientation:landscape) and (max-height:540px) and (pointer:coarse)`.

## Integrated changes

- Four-cell OHLC, institutional and breadth values use 9px tabular digits, 1.1 line-height, -0.15px tracking and a bounded paint box.
- Every primary value remains complete; no ellipsis is applied to those numbers.
- Redundant sparkline high/low badges and miniature x/y labels are hidden only in short touch landscape. The line/area chart, KPI row and concise metadata remain.
- Trend titles, metadata and summaries have explicit one-line bounds so they cannot wrap into the chart or commentary.
- The institutional stale badge uses `前日 MM-DD` only in short touch landscape; desktop retains `預覽前一日 YYYY-MM-DD`, and the full explanation remains in the title tooltip.

## HIVE advisory

- Reviewed artifact SHA-256: `b2a4cc583217e4d5ec4b276ad6a60cb4642a22ddffb3e67f5eb4ab5242cc7ac5`
- NVIDIA model: `nvidia/nemotron-3-super-120b-a12b`
- Dispatch receipt: `023a36ba7a2cb8e2ad3cea1e54d4555fa07c68d430d4788c1bd46901222eea1a`
- Host acceptance receipt: `2470fd605441273765ffa24ee745f27cc2406ce99d1709aab9b70a15454e1fc2`
- Verdict: PASS candidate direction.
- Google Gemini was retried within the authorized Documents boundary but was rate-limited. This is therefore one-provider advisory evidence, not a verified multi-provider claim.

## Acceptance evidence

| Viewport | Layout | Primary KPI overflow | Compact chart annotations | Result |
|---|---|---:|---|---|
| 956×440 touch landscape | 5 + 5, 184px equal panels | 0 / 12 | hidden | PASS |
| 956×390 touch landscape | 5 + 5, 184px equal panels | 0 / 12 | hidden | PASS |
| 390×844 touch portrait | two 187.5px columns | 0 sampled | visible | PASS |
| 1440×900 desktop | 5 + 5 | desktop 10px unchanged | visible | PASS |

At 956×390, the clipped visible-text geometry audit found zero intersections inside the OHLC, institutional and breadth trend cards. The institutional header also satisfies `scrollWidth <= clientWidth` after the compact stale-label refinement.

## Deterministic gates

- `node --check src/ui/pulse_v5.js` — PASS
- `node tests/shell_v5_selftest.js` — PASS
- bundled Python `build_v2.py` — PASS, generated revision `6df2c1af03ff`
- scoped `git diff --check` — PASS

## Scope boundary

No commit, push or deployment was performed. Runtime-updated `data/tw_names_backup.json` and `data/twoii_daily.csv` were preserved and excluded from this change.

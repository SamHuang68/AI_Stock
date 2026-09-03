# ST mobile landscape 5+5 restoration result

## Outcome

- Restored the compact density of the `3cab212` layout anchor for touch-device landscape viewports only.
- Preserved six KPI cells, five equal cards in each of two dashboard zones, card order, internal scrolling, desktop layout and portrait two-column scrolling.
- No deployment, Git commit or push is part of this loop.

## Root cause

Commit `78e348d` correctly restricted the two-column mobile rule to portrait so landscape returned to 5+5. It did not add a short-landscape density layer. Later desktop typography and padding increases therefore also applied to iPhone landscape and reduced the usable content area inside every card.

## Implemented contract

The new rule is bounded by all three conditions:

```css
@media (orientation: landscape) and (max-height: 540px) and (pointer: coarse)
```

Within that boundary it restores compact strip typography, compact card padding, equal row gaps and an explicit five-column grid. The market-news and watchlist control groups retain their one-row contract.

## HIVE advisory receipt

- Provider: Google
- Worker: `gemini`
- Model: `gemini-3.5-flash`
- Reviewed bundle SHA-256: `7a5372ae0f4c54840d0cec7960b2ac79ca4d6e8a018c0c466ef326f7f1f18658`
- Producer receipt: `93b7e14784ec94f42d9a69da9388f3ca212dba18ba24533f245b92f36dbb023b`
- Output SHA-256: `3b8963506170018f280e90609ba65334bc4080ed092ab62b72f738ef46b2265d`
- Host acceptance: `94bb0ca27e89039259aead298edecab5a3a2d891e338e28d161c7eafa7b1bcd2`
- Accepted contribution: confirmed `78e348d` as the earliest causal transition and recommended restoring the compact `3cab212` values behind a coarse-pointer short-landscape media query.

## Verification

- `node --check src/ui/pulse_v5.js`: passed.
- `node tests/shell_v5_selftest.js`: passed, including the new landscape-only contract assertion.
- Bundled Python `build_v2.py`: passed; generated revision `cd4d49694939`.
- Responsive runtime at `956 × 440`: compact media query matched; zone columns were `[5, 5]`; all 10 cards remained inside the viewport; page `scrollHeight === clientHeight === 440`.
- Responsive runtime at `956 × 390`: compact media query matched; zone columns were `[5, 5]`; all 10 cards ended at y=384; page `scrollHeight === clientHeight === 390`.
- Portrait control at `390 × 844`: compact media query did not match; the existing portrait query matched and zone columns remained `[2, 2]`.
- Desktop control at `1440 × 900`: neither mobile query matched and zone columns remained `[5, 5]`.
- Computed card padding was `6px 8px`; the first non-hero KPI value was `13px` and hero values were intentionally `14px`.
- The browser test enabled touch emulation temporarily, then disabled it, reset the viewport and closed the temporary tab.

## Artifact hashes

- `src/ui/pulse_v5.js`: `10d19687e27ff4c00885b6f495c469c2d5489ba2c5ed7fe2a70d80d573612dc6`
- `tests/shell_v5_selftest.js`: `eb9bc45704a8aaf323472b6fc2db3a07f2f3bdba439b081c22d37c269c551a6c`
- `stock_terminal_v2.html`: `060ea31ab21c48d986b4655bc10c51981855c598b0945b825ea0a7578e1dd14b`

## Residual risks

- Browser or OS text enlargement above normal settings can still reduce visible data rows; internal list/chart regions remain the intended scroll owners.
- The KPI secondary line remains a deliberate single-line summary with ellipsis when its complete diagnostic string exceeds one sixth of the landscape width.

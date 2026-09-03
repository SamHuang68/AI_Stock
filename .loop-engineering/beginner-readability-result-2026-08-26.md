# Stock Terminal Beginner Readability Result

## Outcome

The wide-desktop beginner view now uses its available space for a visible hierarchy instead of shrinking secondary information to 7–10px. When the content exceeds the viewport height, the page scrolls vertically.

## Implemented changes

- Raised hero, signal, market-radar, boundary, input, method, and advanced-observation typography.
- Raised low-contrast supporting colors together with font size so source and method text remains readable.
- Restricted the short-height desktop media rule to 901–1199px and removed its typography reductions.
- Kept compact spacing, gauge geometry, and padding adjustments for medium-height-constrained desktops.
- Tightened expert touch-landscape numeric letter spacing so six-character KPI values fit even at 844px landscape width without reducing the 9px primary KPI font.
- Added self-test gates for the new breakpoint and typography floor.

## Measured browser evidence

- 1366 × 600 desktop: body 13–14px, support 11–12px, zero direct-child overlaps, zero horizontal overflow; content scroll height 797px by design.
- 1024 × 600 desktop: same typography floors, zero direct-child overlaps, zero horizontal overflow; content scroll height 674px.
- 390 × 844 touch portrait: single-column signal/radar cards, body 13px, source 11px, zero primary truncation and zero horizontal overflow.
- 844 × 390 touch landscape beginner: three equal signal and radar columns, body 13px, source 11px, zero primary truncation and zero horizontal overflow.
- 844 × 390 touch landscape expert: five equal columns per zone and zero primary KPI overflow after the boundary refinement.

## Verification levels

- Static: JavaScript syntax passed.
- Integration: the complete ShellV5 self-test passed, including new readability assertions.
- Build: `build_v2.py` reproduced `stock_terminal_v2.html` revision `115aba561f4f`.
- End-to-end UI: local Chrome loaded the generated page, switched modes, emulated all five viewports, and measured computed styles plus DOM geometry.

## Scope boundary

Git commit, push, deployment, market-data mutation, accounts, and credentials are outside this loop.

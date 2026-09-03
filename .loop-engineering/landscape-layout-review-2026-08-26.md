# ST mobile landscape 5+5 layout review bundle

## Scope

- Scope ID: `st-mobile-landscape-5x2-20260826`
- Task: diagnose the regression visible on an iPhone 16 Pro Max in Chrome landscape and recommend a minimal CSS-only correction.
- Write policy: advisory only. The Codex Host remains the sole integration writer.
- Non-goals: do not change desktop layout, portrait two-column scrolling/paging, market data, card order, route behavior, or the 5+5 contract.
- Current source revision: `d412aa86f544afd5f94805893624cfc839ed8e22`
- Reviewed file: `src/ui/pulse_v5.js`
- Current file SHA-256: `01A7E1A1E756B06A0E78F2EE05AA527AEB46286F3AC23034EAC37E7DE9D350FF`

## User-visible evidence

The supplied Chrome landscape screenshot is 2868 × 1320 physical pixels. The ST page keeps five equal cards in each of two zones, but card text and controls are visibly compressed or clipped:

- top KPI secondary text truncates aggressively;
- middle-row OHLC and institutional values collide with their card boundaries;
- bottom-row tables and list content lose useful rows;
- the page uses the desktop density rules because the iPhone landscape CSS viewport is wider than the existing `max-width:900px` portrait-only rule;
- the user explicitly wants the earliest known-good 5+5 density restored only for mobile landscape.

## Known-good anchor

Commit `3cab212` is named `revert(pulse): 還原一行五框 × 上下兩區一屏版面` and is already referenced by the regression self-test as the known-good 5+5 anchor.

Relevant anchor rules:

```css
#view-pulse.sv-panel.on { padding: 4px 6px 6px; }
.pl-strip .cell { padding: 4px 7px; }
.pl-strip .v { font-size: 13px; line-height: 1.15; }
.pl-strip .s { font-size: 8px; line-height: 1.2; }
.pl-dash { gap: 6px; grid-template-rows: minmax(0,1fr) minmax(0,1fr); }
.pl-zone { gap: 6px; grid-template-columns: repeat(5,minmax(0,1fr)); }
.pl-sec { padding: 6px 8px; height: 100%; overflow: hidden; }
.pl-sec h4 { margin: 0 0 4px; font-size: 10px; gap: 4px; flex-wrap: wrap; }
.pl-note { font-size: 8px; line-height: 1.35; margin-top: 3px; }
```

## Current rules that increased density pressure

```css
.pl-strip .cell { padding: 4px 6px; }
.pl-strip .v { font-size: 14px; margin-bottom: 2px; }
.pl-strip .cell.hero .v { font-size: 15px; }
.pl-strip .s { font-size: 10px; line-height: 1.25; }
.pl-strip .vz-ref { margin-top: 3px; margin-bottom: 11px; height: 5px; }
.pl-ttabs span { font-size: 6px; }
.pl-sec { padding: 8px 10px; height: 100%; overflow: hidden; }
.pl-sec h4 { margin: 0 0 6px; flex-wrap: nowrap; }
```

The current mobile override is deliberately portrait-only:

```css
@media (max-width:900px) and (orientation:portrait) { /* 2-column scrolling */ }
```

Commit `78e348d` correctly restored landscape to 5+5 by narrowing that rule to portrait, but added no mobile-landscape density profile. Therefore landscape inherits later desktop typography and padding growth.

## Proposed Host hypothesis

Root cause is not the 5+5 grid itself. It is a missing short-landscape density layer after `78e348d`: the landscape viewport keeps the correct five columns but inherits desktop spacing and enlarged secondary typography introduced after the `3cab212` anchor.

Candidate correction:

```css
@media (orientation:landscape) and (max-height:540px) and (pointer:coarse) {
  /* retain five columns and two equal rows */
  /* restore the anchor's compact card padding and secondary typography */
  /* keep scroll inside existing list/chart regions; do not make the page scroll */
  /* reserve safe-area insets without reducing card width unnecessarily */
}
```

## Review questions

1. Is the missing short-landscape density layer the earliest causal transition supported by the evidence?
2. Which exact overrides are required to restore readability without changing the desktop or portrait contracts?
3. Should the media query use `pointer:coarse`, `hover:none`, viewport height, or a combination to avoid affecting short desktop windows?
4. What deterministic assertions should be added to prevent another landscape regression?
5. Return `PASS` or `FAIL`, P0/P1 findings, recommended CSS selectors/values, and residual risks. Do not provide a full rewrite.

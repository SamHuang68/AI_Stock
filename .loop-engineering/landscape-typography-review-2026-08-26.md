# Stock Terminal mobile-landscape typography collision review

## Review identity

- Scope: `st-loop019-mobile-landscape-typography`
- Baseline Git revision: `06de8bc96f90af32878b3c5f4f9573cfdd90e7cc`
- Deployed feature revision under observation: `3c6bf59112265c8af6818711140d403db58a485b`
- Source: `src/ui/pulse_v5.js`
- Source SHA-256: `10D19687E27FF4C00885B6F495C469C2D5489BA2C5ED7FE2A70D80D573612DC6`
- User screenshot SHA-256: `6E77DC46B5AA74C2C0F16D77E0E0EEF3ADFD8E09FAD4D653800AED37A19D1AFE`
- Runtime viewport: touch/coarse pointer, landscape, `956 x 440` CSS px
- Layout contract: two zones with five equal cards each (`5+5`, `5col-2zone`)

This is a bounded, public-safe UI review artifact. It contains no credentials, personal holdings, brokerage data, private paths, or source files beyond the relevant CSS excerpts below.

## User promise and hard constraints

The user accepts the restored 5+5 layout but rejects any text that visually touches, overlaps, or covers adjacent text. Fix typography and compact chart annotation until the landscape view has no text collisions.

Hard constraints:

1. Keep two rows of five equal panels; do not replace the layout with fewer columns, horizontal paging, or a portrait layout.
2. Primary numeric values must remain legible and must not be silently truncated.
3. Secondary narrative strings may use one-line ellipsis.
4. The fix must be scoped to touch/coarse-pointer landscape views with height at most 540 px.
5. Desktop and portrait typography/layout must remain unchanged.
6. The worker is advisory only. The Codex Host is the single integration writer and final verifier.

## Measured baseline

At `956 x 440`, all ten panels are present and each panel is 184 px wide. The OHLC, institutional flow and breadth KPI grids each have 166 px of inner width split across four columns. Each value cell is 38.5 px wide with only 33 px of client text width.

Current values are rendered at 10 px with tabular digits and negative letter spacing. Representative measurements:

| Grid | Representative value | Client width | Font | Letter spacing | Overflow |
|---|---:|---:|---:|---:|---|
| OHLC | `45,158` | 33 px | 10 px | -0.3 px | visible |
| Institutional | `+366.0` | 33 px | 10 px | -0.2 px | visible |
| Breadth | `4.34` | 33 px | 10 px | -0.2 px | visible |

The glyph runs consume effectively the full 33 px. Because values use `overflow: visible`, there is no safety boundary if a digit is wider, the browser font differs, or text scaling changes. The screenshot therefore reads as touching/overlapping even when the nominal element boxes remain adjacent.

The automated leaf-element geometry audit also found real chart-label intersections in the compact landscape cards:

- OHLC chart header versus high-point badge: 33.2 px horizontal by 6.7 px vertical intersection.
- OHLC high/low axis values versus status commentary: intersections up to 12.1 px.
- Institutional chart header versus high-point badge: 29.0 px by 4.7 px.
- Breadth chart title/meta versus high-point badge: up to 12.1 px by 4.7 px.
- Compact x/y axis labels also intersect neighboring summary text near the bottom of the plot.

Long narrative, news, sector, and theme labels are intentionally ellipsized. Those are not primary KPI collisions and should remain bounded rather than forcing wider cards.

## Relevant current CSS

```css
.pl-inst4,.pl-bd4,.pl-ohlc4 {
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:4px;
}

.pl-inst4 .c .v,.pl-bd4 .c .v,.pl-ohlc4 .c .v {
  font-size:10px;
  font-weight:800;
  line-height:1.15;
  font-variant-numeric:tabular-nums;
  letter-spacing:-0.2px;
  white-space:nowrap;
  overflow:visible;
  max-width:100%;
}

@media (orientation:landscape) and (max-height:540px) and (pointer:coarse) {
  .pl-sec { padding:6px 8px; height:100%; overflow:hidden; }
  .pl-sec h4 { margin:0 0 4px; font-size:10px; gap:4px; flex-wrap:wrap; }
}
```

The shared sparkline renderer shows high/low point badges plus y-unit, y-axis labels, x-axis labels, and a separate card-level header/meta. In a half-height landscape card these annotations duplicate information already available in the KPI row and create the measured intersections.

## Candidate direction for independent challenge

The Host is considering the smallest landscape-only correction:

1. Reduce four-cell KPI values to approximately 8.5-9 px, tighten letter spacing moderately, center them, and change horizontal overflow from `visible` to `hidden`/`clip` so glyphs cannot paint into neighboring cells.
2. Retain full primary digits; verify that each value's `scrollWidth <= clientWidth` at both 956x440 and 956x390.
3. In compact touch landscape only, remove redundant high/low point badges and miniature axis labels from the three sparkline cards, leaving the line/area plot, KPI row, and concise header/meta.
4. Give headers and summary lines explicit line-height and bounded overflow so wrapping cannot collide vertically.
5. Add a deterministic browser geometry Gate that fails when visible leaf text rectangles intersect inside one card, with explicit exemptions only for intentional table-cell borders or same-token decoration.

## Requested advisory output contract

Return a concise engineering review with:

1. `VERDICT`: PASS candidate direction or FAIL with a blocking reason.
2. `ROOT_CAUSES`: rank the actual causes of the observed overlap.
3. `CSS_RECOMMENDATION`: exact landscape-only selector/property recommendations, including safe numeric font size/line-height/overflow.
4. `CHART_POLICY`: which redundant sparkline labels to hide or retain at 956x440 and why.
5. `REGRESSION_RISKS`: desktop, portrait, localization, font fallback, and browser text-scaling risks.
6. `ACCEPTANCE_GATES`: measurable zero-overlap and no-primary-truncation checks for 956x440 and 956x390.

Do not propose deployment, direct file edits, layout-column reduction, trading changes, or unrelated visual redesign.

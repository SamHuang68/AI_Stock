# Stock Terminal Beginner Readability Successor Review

## Scope

This artifact records a public-safe UI readability incident and its successor acceptance contract. It contains no source code, credentials, holdings, private endpoints, or personal data.

## Failed prior gate

The preceding responsive review proved that phone-landscape content stayed inside its card boundaries. It did not test whether text remained readable on a wide but short desktop viewport. The user-visible result therefore passed geometric containment while failing experiential readability.

Classification: verification-definition failure. The acceptance rubric measured overlap and truncation, but omitted minimum font size, visual hierarchy, and use of available whitespace.

## Reproduction evidence

Chrome reproduction at 1366 × 551 CSS pixels, DPR 3:

- Hero heading 20px, advice 13px, explanatory body 10px, quality line 8px.
- Signal cards: heading 9px, primary 15px, body 9px, method label 8px, bar metadata 7px.
- Market radar: market name 10px, risk badge 7px, primary trend 14px, change 13px, body 8px, source 7px.
- Boundary cards: label 9px, value 18px, explanation 8px.
- Signal cards used about 82–83% of their height and radar cards used about 85%, so the tiny type was not forced by card capacity.
- No horizontal overflow was present.

## Root cause

A desktop media query activated whenever viewport height was at most 740px and width was at least 901px. It reduced typography to 7–10px in order to preserve a one-page composition. On a 1366px-wide desktop this optimized containment over normal-distance readability despite ample horizontal space.

## Successor contract

- Wide desktop uses the normal beginner typography hierarchy and permits vertical scrolling.
- The short-height compact rule is limited to medium desktops and reduces padding, gaps, and decorative geometry—not the readability floor.
- Primary hierarchy: hero 26px, advice 17px, card primary 19–20px.
- Body hierarchy: explanatory and card copy 13–14px.
- Supporting evidence: 11–12px.
- No primary text truncation, sibling overlap, or horizontal page overflow.
- Phone portrait remains one-column and phone landscape remains usable without hidden primary content.
- Expert phone-landscape remains two zones of five equal cards, with every primary KPI fully contained.

## Acceptance matrix

| Viewport | Required evidence |
|---|---|
| 1366 × 600 desktop | Body ≥13px, supporting text ≥11px, no sibling overlap, no horizontal overflow; vertical scroll allowed |
| 1024 × 600 desktop | Same typography floors; compact spacing may apply; no overlap or horizontal overflow |
| 390 × 844 touch portrait | One-column beginner cards, no primary truncation or horizontal overflow |
| 844 × 390 touch landscape | Three beginner columns remain readable; no primary truncation or horizontal overflow |
| 844 × 390 expert regression | Exactly five equal columns per zone and zero primary KPI overflow |

## Review questions

1. Does the diagnosis correctly identify a verification-definition failure rather than a content-capacity failure?
2. Are the typography hierarchy and supporting-text floors proportionate for a dense financial dashboard?
3. Are the five browser gates sufficient to prevent recurrence without forcing every viewport into one page?
4. Identify any release-blocking responsive risk.

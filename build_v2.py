#!/usr/bin/env python3
"""
Build stock_terminal_v2.html from stock_terminal.html.

v2 = v1 base + POS tab + WATCH tab + position_v2.js + watch_v2.js.
Re-run any time you update v1 and want v2 to inherit the changes.
"""
import os, re, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(ROOT, 'stock_terminal.html')
DST  = os.path.join(ROOT, 'stock_terminal_v2.html')

# Scripts injected (in order):
#   position_v2.js — defines num/fx helpers used by both watch and info
#   watch_v2.js    — defines STRATEGIES / PRESETS used by info_v2.js
#   info_v2.js     — registers (i) icon tooltips for indicators / strategies / presets
V2_SCRIPTS = ['position_v2.js', 'watch_v2.js', 'info_v2.js', 'pro_v2.js', 'pattern_v2.js', 'live_v2.js']
V2_STYLES  = ['mobile_v2.css']

if not os.path.isfile(SRC):
    sys.exit(f'[ERR] missing {SRC}')
for js in V2_SCRIPTS:
    if not os.path.isfile(os.path.join(ROOT, js)):
        sys.exit(f'[ERR] missing {js} — required for v2')
for css in V2_STYLES:
    if not os.path.isfile(os.path.join(ROOT, css)):
        sys.exit(f'[ERR] missing {css} — required for v2')

with open(SRC, 'r', encoding='utf-8') as f:
    html = f.read()

# 1) Update <title>
html = re.sub(
    r'<title>[^<]*</title>',
    '<title>Stock Terminal v2.0 — Position, Watch & Signals</title>',
    html, count=1)

# 2a) Add POS tab button (before ETF△)
POS_TAB = '<button class="rtab" id="tab-pos" onclick="setTab(\'position\')">POS</button>\n        '
if 'id="tab-pos"' not in html:
    html = html.replace(
        '<button class="rtab" id="tab-etf"',
        POS_TAB + '<button class="rtab" id="tab-etf"',
        1)

# 2b) Add WATCH tab button (between POS and ETF△)
WATCH_TAB = '<button class="rtab" id="tab-watch" onclick="setTab(\'watch\')">WATCH</button>\n        '
if 'id="tab-watch"' not in html:
    html = html.replace(
        '<button class="rtab" id="tab-etf"',
        WATCH_TAB + '<button class="rtab" id="tab-etf"',
        1)

# 3a) Patch v1's renderRpanel — add 'position' dispatch.
RP_POS_OLD = "if (S.tab==='etf')      { el.innerHTML = renderEtfDelta(); return; }"
RP_POS_NEW = (RP_POS_OLD + "\n"
              "  if (S.tab==='position') { el.innerHTML = renderPosition(); attachPosition(); return; }")
if 'renderPosition()' not in html:
    html = html.replace(RP_POS_OLD, RP_POS_NEW, 1)

# 3b) Patch v1's renderRpanel — add 'watch' dispatch (after position).
RP_WATCH_OLD = "if (S.tab==='position') { el.innerHTML = renderPosition(); attachPosition(); return; }"
RP_WATCH_NEW = (RP_WATCH_OLD + "\n"
                "  if (S.tab==='watch')    { el.innerHTML = renderWatch(); attachWatch(); return; }")
if 'renderWatch()' not in html:
    html = html.replace(RP_WATCH_OLD, RP_WATCH_NEW, 1)

# 4a) setTab tabs array: drop BATCH (v2 doesn't need it), add 'position' + 'watch'
TAB_V1   = "const tabs=['stats','research','batch','history','etf'];"
TAB_POS  = "const tabs=['stats','research','batch','history','position','etf'];"
TAB_FULL = "const tabs=['stats','research','batch','history','position','watch','etf'];"
TAB_NOBATCH = "const tabs=['stats','research','history','position','watch','etf'];"
# Replace any prior version with the no-batch full version
for old in [TAB_V1, TAB_POS, TAB_FULL]:
    if old in html:
        html = html.replace(old, TAB_NOBATCH, 1)
        break

# 4a2) Hide the BATCH tab button entirely (v2 doesn't expose Batch — too crowded)
html = re.sub(
    r'\s*<button class="rtab"[^>]*onclick="setTab\(\'batch\'\)"[^>]*>[^<]*</button>',
    '',
    html, count=1
)

# 4b) Patch v1's loadSym — wrap renderRpanel in try/catch + fire `symLoaded` CustomEvent.
LS_OLD = "  if (S.ind) updateEtfFlowInd();\n  renderRpanel();"
LS_NEW = ("  if (S.ind) updateEtfFlowInd();\n"
          "  try { renderRpanel(); } catch (e) { console.error('[v1] renderRpanel threw:', e); }\n"
          "  try { window.dispatchEvent(new CustomEvent('symLoaded', {detail:{sym: S.sym, mkt: S.mkt}})); } catch(e){}")
if 'symLoaded' not in html:
    html = html.replace(LS_OLD, LS_NEW, 1)

# 5) Inject v2 scripts + stylesheets (with cache-busting timestamp)
ts = int(time.time())
# Strip any prior v2 script tags so we can re-emit with fresh ts
for js in V2_SCRIPTS:
    html = re.sub(rf'<script[^>]+{re.escape(js)}[^>]*></script>\s*', '', html)
for css in V2_STYLES:
    html = re.sub(rf'<link[^>]+{re.escape(css)}[^>]*>\s*', '', html)

# Add viewport meta (better mobile rendering)
if 'name="viewport"' not in html:
    html = html.replace('<head>', '<head>\n<meta name="viewport" content="width=device-width,initial-scale=1.0">', 1)

# Inject CSS before </head>
css_block = ''.join(
    f'<link rel="stylesheet" href="{css}?v={ts}">\n'
    for css in V2_STYLES
)
if '</head>' in html:
    html = html.replace('</head>', css_block + '</head>', 1)

# Inject scripts before </body>
script_block = ''.join(
    f'<script src="{js}?v={ts}"></script>\n'
    for js in V2_SCRIPTS
)
if '</body>' in html:
    html = html.replace('</body>', script_block + '</body>', 1)
else:
    html += '\n' + script_block

# 6) Add v2 banner so users can tell v1 vs v2 at a glance
if 'data-v2-banner' not in html:
    html = html.replace(
        '<span class="logo">STOCK TERMINAL</span>',
        '<span class="logo" data-v2-banner>STOCK TERMINAL <span style="color:#67E8F9;font-size:9px;letter-spacing:1px">v2.0</span></span>',
        1)

with open(DST, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'[OK] wrote {DST}  ({len(html):,} bytes)')
print(f'     base:    {SRC}')
print(f'     modules: {", ".join(V2_SCRIPTS)}')
print()
print('Open in browser:')
print(f'  http://localhost:18432/stock_terminal_v2.html')

#!/usr/bin/env python3
"""Wrapper to defeat sandbox mount cache — same logic as build_v2.py."""
import os, re, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(ROOT, 'stock_terminal.html')
DST  = os.path.join(ROOT, 'stock_terminal_v2.html')

V2_SCRIPTS = ['position_v2.js', 'watch_v2.js', 'info_v2.js', 'pro_v2.js', 'pattern_v3.js', 'live_v2.js',
              'chip_v3.js', 'heatmap_v3.js', 'screener_v3.js', 'ai_report_v3.js', 'polish_v3.js',
              'wl_live_v3.js',
              'etf_v3.js']
V2_STYLES  = ['mobile_v2.css']

if not os.path.isfile(SRC):
    sys.exit(f'[ERR] missing {SRC}')
for js in V2_SCRIPTS:
    if not os.path.isfile(os.path.join(ROOT, js)):
        sys.exit(f'[ERR] missing {js}')
for css in V2_STYLES:
    if not os.path.isfile(os.path.join(ROOT, css)):
        sys.exit(f'[ERR] missing {css}')

with open(SRC, 'r', encoding='utf-8') as f:
    html = f.read()

html = re.sub(r'<title>[^<]*</title>',
              '<title>Stock Terminal v3.0 — 19 Patterns · ETF Top10 · Mkt Bar</title>',
              html, count=1)

POS_TAB = '<button class="rtab" id="tab-pos" onclick="setTab(\'position\')">POS</button>\n        '
if 'id="tab-pos"' not in html:
    html = html.replace('<button class="rtab" id="tab-etf"',
                        POS_TAB + '<button class="rtab" id="tab-etf"', 1)

WATCH_TAB = '<button class="rtab" id="tab-watch" onclick="setTab(\'watch\')">WATCH</button>\n        '
if 'id="tab-watch"' not in html:
    html = html.replace('<button class="rtab" id="tab-etf"',
                        WATCH_TAB + '<button class="rtab" id="tab-etf"', 1)

RP_POS_OLD = "if (S.tab==='etf')      { el.innerHTML = renderEtfDelta(); return; }"
RP_POS_NEW = (RP_POS_OLD + "\n"
              "  if (S.tab==='position') { el.innerHTML = renderPosition(); attachPosition(); return; }")
if 'renderPosition()' not in html:
    html = html.replace(RP_POS_OLD, RP_POS_NEW, 1)

RP_WATCH_OLD = "if (S.tab==='position') { el.innerHTML = renderPosition(); attachPosition(); return; }"
RP_WATCH_NEW = (RP_WATCH_OLD + "\n"
                "  if (S.tab==='watch')    { el.innerHTML = renderWatch(); attachWatch(); return; }")
if 'renderWatch()' not in html:
    html = html.replace(RP_WATCH_OLD, RP_WATCH_NEW, 1)

ETF_RP_OLD = "if (S.tab==='etf')      { el.innerHTML = renderEtfDelta(); return; }"
ETF_RP_NEW = "if (S.tab==='etf')      { el.innerHTML = (window.renderEtfDelta || renderEtfDelta)(); return; }"
if '(window.renderEtfDelta || renderEtfDelta)' not in html:
    html = html.replace(ETF_RP_OLD, ETF_RP_NEW, 1)

FETCH_ETF_OLD = "fetchEtfDelta();"
FETCH_ETF_NEW = "(window.fetchEtfDelta || fetchEtfDelta)();"
if '(window.fetchEtfDelta || fetchEtfDelta)' not in html:
    html = html.replace(FETCH_ETF_OLD, FETCH_ETF_NEW, 1)

HOLD_OLD = "${renderEtfHoldingsForStock(S.sym)}"
HOLD_NEW = "${(window.renderEtfHoldingsForStock||renderEtfHoldingsForStock)(S.sym)}"
if '(window.renderEtfHoldingsForStock||renderEtfHoldingsForStock)' not in html:
    html = html.replace(HOLD_OLD, HOLD_NEW, 1)

# 3f) NUKE v1 ETF rendering section (keeps "各ETF訊號強度" etc. out of v2 HTML)
html = re.sub(
    r'// ── ETF Delta Tab ─+[\s\S]*?function etfBatchAllNew\(\) \{[\s\S]*?setTab\(\'batch\'\);\s*\}',
    '// ── v1 ETF section removed by build — see etf_v3.js ──',
    html, count=1
)
html = re.sub(
    r'function renderEtfHoldingsForStock\(sym\) \{[\s\S]*?return `<div class="stat-sect">ETF 持股動態（今日）</div>` \+[\s\S]*?\.join\(\'\'\);\s*\}',
    'function renderEtfHoldingsForStock(sym) { return ""; }',
    html, count=1
)

TAB_V1       = "const tabs=['stats','research','batch','history','etf'];"
TAB_POS      = "const tabs=['stats','research','batch','history','position','etf'];"
TAB_FULL     = "const tabs=['stats','research','batch','history','position','watch','etf'];"
TAB_NOBATCH  = "const tabs=['stats','research','history','position','watch','etf'];"
TAB_LEAN     = "const tabs=['stats','research','position','watch','etf'];"
for old in [TAB_V1, TAB_POS, TAB_FULL, TAB_NOBATCH]:
    if old in html:
        html = html.replace(old, TAB_LEAN, 1)
        break

html = re.sub(r'\s*<button class="rtab"[^>]*onclick="setTab\(\'batch\'\)"[^>]*>[^<]*</button>',
              '', html, count=1)
html = re.sub(r'\s*<button class="rtab"[^>]*onclick="setTab\(\'history\'\)"[^>]*>[^<]*</button>',
              '', html, count=1)

LS_OLD = "  if (S.ind) updateEtfFlowInd();\n  renderRpanel();"
LS_NEW = ("  if (S.ind) updateEtfFlowInd();\n"
          "  try { renderRpanel(); } catch (e) { console.error('[v1] renderRpanel threw:', e); }\n"
          "  try { window.dispatchEvent(new CustomEvent('symLoaded', {detail:{sym: S.sym, mkt: S.mkt}})); } catch(e){}")
if 'symLoaded' not in html:
    html = html.replace(LS_OLD, LS_NEW, 1)

ts = int(time.time())
for js in V2_SCRIPTS:
    html = re.sub(rf'<script[^>]+{re.escape(js)}[^>]*></script>\s*', '', html)
html = re.sub(r'<script[^>]+etf_v2\.js[^>]*></script>\s*', '', html)
for css in V2_STYLES:
    html = re.sub(rf'<link[^>]+{re.escape(css)}[^>]*>\s*', '', html)

if 'name="viewport"' not in html:
    html = html.replace('<head>', '<head>\n<meta name="viewport" content="width=device-width,initial-scale=1.0">', 1)

css_block = ''.join(f'<link rel="stylesheet" href="{css}?v={ts}">\n' for css in V2_STYLES)
if '</head>' in html:
    html = html.replace('</head>', css_block + '</head>', 1)

script_block = ''.join(f'<script src="{js}?v={ts}"></script>\n' for js in V2_SCRIPTS)
if '</body>' in html:
    html = html.replace('</body>', script_block + '</body>', 1)
else:
    html += '\n' + script_block

if 'data-v2-banner' not in html:
    html = html.replace(
        '<span class="logo">STOCK TERMINAL</span>',
        '<span class="logo" data-v2-banner>STOCK TERMINAL <span style="color:#FBBF24;font-size:9px;letter-spacing:1px;font-weight:700">v3.0</span></span>',
        1)

with open(DST, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'[OK] wrote {DST}  ({len(html):,} bytes)')
print(f'     modules: {", ".join(V2_SCRIPTS)}')

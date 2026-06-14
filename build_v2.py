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
V2_SCRIPTS = ['position_v2.js', 'watch_v2.js', 'info_v2.js', 'pro_v2.js',
              'volume_profile_v3.js',           # v3.8 E: 成交金額 Volume Profile (覆寫 pro_v2 POC，須在其後)
              'pattern_v3.js', 'live_v2.js',
              'chip_v3.js',
              'fundamental_v3.js',              # v3.8 B: 基本面 (月營收/三率/評分)
              'heatmap_v3.js', 'screener_v3.js', 'ai_report_v3.js', 'polish_v3.js',
              'wl_live_v3.js',
              'plan_history_v3.js',
              'plan_position_v3.js',
              'plan_v3.js',
              'pdf_import_v3.js',
              'pdf_export_v3.js',
              'peg_v3.js',
              'alert_v3.js',
              'alert_push_v3.js',               # v3.8 D: 後端警報推播設定 UI (須在 alert_v3 後)
              'backtest_v3.js',                 # v3.8 C: 回測核心
              'backtest_ui_v3.js',              # v3.8 C: 回測 UI (須在 backtest_v3 後)
              'enhance_v3.js',                  # v3.8: 雙軸卡/量價面板/右側收合/分頁記憶
              'aftermarket_v3.js',              # v3.8: 美股盤後/盤前延伸交易顯示
              'overnight_v3.js',                # v3.8: 夜盤連動預警(美股期貨→台股隔日)
              'supplychain_v3.js',              # v3.8: 台灣AI供應鏈族群連動
              'valuation_v3.js',                # v3.8: 長線估值錨(本益比河流)
              'marketflow_v3.js',               # v3.8: 大盤資金流儀表板
              'instrank_v3.js',                 # v3.8: 外資/投信買賣超排行榜
              'calendar_v3.js',                 # v3.8: 事件行事曆+提醒
              'multichart_v3.js',               # v3.9 P1: 多圖連動布局 (grid overlay)
              'spread_v3.js',                   # v3.9 P1: 價差/比值圖
              'hotkeys_v3.js',                  # v3.9 P1: 全鍵盤快捷 (打字即搜尋/Space切自選/Alt切時框)
              'strategy_builder_v3.js',         # v3.9 P2: 樂高式策略條件組合器 (提供 window.StratLib，須在 backtest_v3 後)
              'strategy_script_v3.js',          # v3.9 P2: 迷你策略腳本 DSL (依賴 StratLib，須在 strategy_builder 後)
              'drawtools_v3.js',                # v3.9 P3: 進階畫線(canvas overlay)+雲端記憶
              'screener3_v3.js',                # v3.9 P4: 三合一進階選股(技術+基本面+籌碼)
              # 'macro_v3.js',                  # v3.9 P4: 總經疊圖 — 已停用(資料源不穩,2026-06-14 移除;檔案與 server /macro 保留待日後)
              'etf_v3.js',
              'wizard_v3.js']                   # v3.9: 加股設定精靈(依賴 StratLib/Backtest/drawtools/setPosition/saveWatches，排最後)
V2_STYLES  = ['mobile_v2.css']

if not os.path.isfile(SRC):
    sys.exit(f'[ERR] missing {SRC}')
for js in V2_SCRIPTS:
    if not os.path.isfile(os.path.join(ROOT, js)):
        sys.exit(f'[ERR] missing {js} - required for v2')
for css in V2_STYLES:
    if not os.path.isfile(os.path.join(ROOT, css)):
        sys.exit(f'[ERR] missing {css} - required for v2')

with open(SRC, 'r', encoding='utf-8') as f:
    html = f.read()

# 1) Update title
html = re.sub(
    r'<title>[^<]*</title>',
    '<title>Stock Terminal v3.9 - Multi-chart / Backtest / Wizard</title>',
    html, count=1)

# 2a) POS tab
POS_TAB = '<button class="rtab" id="tab-pos" onclick="setTab(\'position\')">POS</button>\n        '
if 'id="tab-pos"' not in html:
    html = html.replace('<button class="rtab" id="tab-etf"', POS_TAB + '<button class="rtab" id="tab-etf"', 1)

# 2b) WATCH tab
WATCH_TAB = '<button class="rtab" id="tab-watch" onclick="setTab(\'watch\')">WATCH</button>\n        '
if 'id="tab-watch"' not in html:
    html = html.replace('<button class="rtab" id="tab-etf"', WATCH_TAB + '<button class="rtab" id="tab-etf"', 1)

# 2c) PLAN tab (v3.5)
PLAN_TAB = '<button class="rtab" id="tab-plan" onclick="setTab(\'plan\')">PLAN</button>\n        '
if 'id="tab-plan"' not in html:
    html = html.replace('<button class="rtab" id="tab-etf"', PLAN_TAB + '<button class="rtab" id="tab-etf"', 1)

# 3a) renderRpanel - position dispatch
RP_POS_OLD = "if (S.tab==='etf')      { el.innerHTML = renderEtfDelta(); return; }"
RP_POS_NEW = (RP_POS_OLD + "\n"
              "  if (S.tab==='position') { el.innerHTML = renderPosition(); attachPosition(); return; }")
if 'renderPosition()' not in html:
    html = html.replace(RP_POS_OLD, RP_POS_NEW, 1)

# 3b) renderRpanel - watch dispatch
RP_WATCH_OLD = "if (S.tab==='position') { el.innerHTML = renderPosition(); attachPosition(); return; }"
RP_WATCH_NEW = (RP_WATCH_OLD + "\n"
                "  if (S.tab==='watch')    { el.innerHTML = renderWatch(); attachWatch(); return; }")
if 'renderWatch()' not in html:
    html = html.replace(RP_WATCH_OLD, RP_WATCH_NEW, 1)

# 3b2) renderRpanel - plan dispatch (v3.5)
RP_PLAN_OLD = "if (S.tab==='watch')    { el.innerHTML = renderWatch(); attachWatch(); return; }"
RP_PLAN_NEW = (RP_PLAN_OLD + "\n"
               "  if (S.tab==='plan')     { el.innerHTML = renderPlan(); attachPlan(); return; }")
if 'renderPlan()' not in html:
    html = html.replace(RP_PLAN_OLD, RP_PLAN_NEW, 1)

# 3c) etf -> window dispatch
ETF_RP_OLD = "if (S.tab==='etf')      { el.innerHTML = renderEtfDelta(); return; }"
ETF_RP_NEW = "if (S.tab==='etf')      { el.innerHTML = (window.renderEtfDelta || renderEtfDelta)(); return; }"
if '(window.renderEtfDelta || renderEtfDelta)' not in html:
    html = html.replace(ETF_RP_OLD, ETF_RP_NEW, 1)

# 3d) fetchEtfDelta -> window
FETCH_ETF_OLD = "fetchEtfDelta();"
FETCH_ETF_NEW = "(window.fetchEtfDelta || fetchEtfDelta)();"
if '(window.fetchEtfDelta || fetchEtfDelta)' not in html:
    html = html.replace(FETCH_ETF_OLD, FETCH_ETF_NEW, 1)

# 3e) renderEtfHoldingsForStock -> window
HOLD_OLD = "${renderEtfHoldingsForStock(S.sym)}"
HOLD_NEW = "${(window.renderEtfHoldingsForStock||renderEtfHoldingsForStock)(S.sym)}"
if '(window.renderEtfHoldingsForStock||renderEtfHoldingsForStock)' not in html:
    html = html.replace(HOLD_OLD, HOLD_NEW, 1)

# 3f) Remove v1 ETF section
html = re.sub(
    r'// .. ETF Delta Tab .+[\s\S]*?function etfBatchAllNew\(\) \{[\s\S]*?setTab\(\'batch\'\);\s*\}',
    '// -- v1 ETF section removed by build_v2.py --',
    html, count=1
)
html = re.sub(
    r'function renderEtfHoldingsForStock\(sym\) \{[\s\S]*?\.join\(\'\'\);\s*\}',
    'function renderEtfHoldingsForStock(sym) { return ""; }',
    html, count=1
)

# 4a) tabs array
TAB_V1       = "const tabs=['stats','research','batch','history','etf'];"
TAB_POS      = "const tabs=['stats','research','batch','history','position','etf'];"
TAB_FULL     = "const tabs=['stats','research','batch','history','position','watch','etf'];"
TAB_NOBATCH  = "const tabs=['stats','research','history','position','watch','etf'];"
TAB_PREV     = "const tabs=['stats','research','position','watch','etf'];"
TAB_LEAN     = "const tabs=['stats','research','position','watch','plan','etf'];"
for old in [TAB_V1, TAB_POS, TAB_FULL, TAB_NOBATCH, TAB_PREV]:
    if old in html:
        html = html.replace(old, TAB_LEAN, 1)
        break

# 4a2) Hide BATCH + HISTORY tab buttons
html = re.sub(r'\s*<button class="rtab"[^>]*onclick="setTab\(\'batch\'\)"[^>]*>[^<]*</button>', '', html, count=1)
html = re.sub(r'\s*<button class="rtab"[^>]*onclick="setTab\(\'history\'\)"[^>]*>[^<]*</button>', '', html, count=1)

# 4a3) default chart range 6mo
RNG_OLD = "range: '5y',                 // iOS-style chart range: 1d/3w/1mo/3mo/6mo/ytd/1y/2y/5y/10y/max"
RNG_NEW = "range: '6mo',                // iOS-style chart range: 1d/3w/1mo/3mo/6mo/ytd/1y/2y/5y/10y/max"
if RNG_OLD in html:
    html = html.replace(RNG_OLD, RNG_NEW, 1)

# 4b) wrap renderRpanel + symLoaded event
LS_OLD = "  if (S.ind) updateEtfFlowInd();\n  renderRpanel();"
LS_NEW = ("  if (S.ind) updateEtfFlowInd();\n"
          "  try { renderRpanel(); } catch (e) { console.error('[v1] renderRpanel threw:', e); }\n"
          "  try { window.dispatchEvent(new CustomEvent('symLoaded', {detail:{sym: S.sym, mkt: S.mkt}})); } catch(e){}")
if 'symLoaded' not in html:
    html = html.replace(LS_OLD, LS_NEW, 1)

# 5) inject scripts + stylesheets
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

# 6) banner
if 'data-v2-banner' not in html:
    html = html.replace(
        '<span class="logo">STOCK TERMINAL</span>',
        '<span class="logo" data-v2-banner>STOCK TERMINAL <span style="color:#FBBF24;font-size:9px;letter-spacing:1px;font-weight:700">v3.9</span></span>',
        1)
# Bump existing v3.x banner to v3.9
html = re.sub(
    r'(data-v2-banner>STOCK TERMINAL <span[^>]+>)v3\.\d+(</span>)',
    r'\g<1>v3.9\g<2>', html, count=1)

with open(DST, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'[OK] wrote {DST}  ({len(html):,} bytes)')
print(f'     base:    {SRC}')
print(f'     modules: {", ".join(V2_SCRIPTS)}')
print()
print('Open in browser:')
print(f'  http://localhost:18432/stock_terminal_v2.html')

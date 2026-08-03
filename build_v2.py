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
V2_SCRIPTS = ['src/core/colors_v3.js',   # 顏色管理表(單一真理來源,須最先載入)
              'src/core/market_v3.js',   # 台股/美股 universe lookup(權威判市場+名稱,可更新)
              'src/core/fields_v3.js',   # 欄位型別定義+全域滾輪防護(單一真理來源,須最先載入)
              'src/core/chart_registry_v3.js',  # H0: macro/特殊圖 primaryKey（須在 polish 前）
              'src/ui/share_v3.js',      # 分析結果寄送 Telegram/Email(單一來源,各分析面板共用)
              'src/ui/datasources_v3.js',# 資料源管理表 + 一鍵更新
              'src/core/etf_flow_tip_v3.js',  # 自選股 ETF 增減碼徽章浮動視窗(列出是哪幾檔 ETF)
              'src/core/position_v2.js', 'src/core/watch_v2.js', 'src/core/info_v2.js', 'src/core/pro_v2.js',
              'src/chart/volume_profile_v3.js',           # v3.8 E: 成交金額 Volume Profile (覆寫 pro_v2 POC，須在其後)
              'src/chart/pattern_v3.js', 'src/core/live_v2.js',
              'src/fundamental/chip_v3.js',
              'src/fundamental/fundamental_v3.js',              # v3.8 B: 基本面 (月營收/三率/評分)
              # 'src/chart/heatmap_v3.js',                # v3.9: 📊類股(產業熱力圖)停用 — 改成點下面大盤列 cell 直接帶K線;檔案保留待恢復
              'src/screener/screener_v3.js', 'src/ai/ai_report_v3.js', 'src/ui/polish_v3.js',
              'src/core/wl_live_v3.js',
              'src/fundamental/plan_history_v3.js',
              'src/fundamental/plan_position_v3.js',
              'src/fundamental/plan_v3.js',
              'src/ui/pdf_import_v3.js',
              'src/ui/pdf_export_v3.js',
              'src/core/peg_v3.js',
              'src/alert/alert_v3.js',
              'src/alert/alert_push_v3.js',               # v3.8 D: 後端警報推播設定 UI (須在 alert_v3 後)
              'src/screener/backtest_v3.js',                 # v3.8 C: 回測核心
              'src/screener/backtest_ui_v3.js',              # v3.8 C: 回測 UI (須在 backtest_v3 後)
              'src/ui/enhance_v3.js',                  # v3.8: 雙軸卡/量價面板/右側收合/分頁記憶
              'src/chart/aftermarket_v3.js',              # v3.8: 美股盤後/盤前延伸交易顯示
              'src/chart/overnight_v3.js',                # v3.8: 夜盤連動預警(美股期貨→台股隔日)
              'src/fundamental/supplychain_v3.js',              # v3.8: 台灣AI供應鏈族群連動
              'src/portfolio/portfolio_v3.js',                  # v4.0: 投組風險面板(相關性/VaR/產業·供應鏈曝險,依賴 SC_STAGE 須在 supplychain 後)
              'src/fundamental/chainmom_v3.js',                 # v4.0: 供應鏈輪動(多時框動能,依賴 SC_CHAINS 須在 supplychain 後)
              'src/fundamental/valuation_v3.js',                # v3.8: 長線估值錨(本益比河流)
              'src/fundamental/marketflow_v3.js',               # v3.8: 大盤資金流儀表板
              'src/fundamental/instrank_v3.js',                 # v3.8: 外資/投信買賣超排行榜
              'src/alert/calendar_v3.js',                 # v3.8: 事件行事曆+提醒
              'src/chart/multichart_v3.js',               # v3.9 P1: 多圖連動布局 (grid overlay)
              'src/chart/spread_v3.js',                   # v3.9 P1: 價差/比值圖
              'src/chart/hotkeys_v3.js',                  # v3.9 P1: 全鍵盤快捷 (打字即搜尋/Space切自選/Alt切時框)
              'src/screener/strategy_builder_v3.js',         # v3.9 P2: 樂高式策略條件組合器 (提供 window.StratLib，須在 backtest_v3 後)
              'src/screener/strategy_script_v3.js',          # v3.9 P2: 迷你策略腳本 DSL (依賴 StratLib，須在 strategy_builder 後)
              'src/chart/drawtools_v3.js',                # v3.9 P3: 進階畫線(canvas overlay)+雲端記憶
              'src/screener/screener3_v3.js',                # v3.9 P4: 三合一進階選股(技術+基本面+籌碼)
              # 'src/screener/macro_v3.js',                  # v3.9 P4: 總經疊圖 — 已停用(資料源不穩,2026-06-14 移除;檔案與 server /macro 保留待日後)
              'src/core/etf_v3.js',
              'src/fundamental/stockfut_v3.js',                 # v3.9: 個股期夜盤領先(市值前十大,TAIFEX MIS)
              'src/core/indices_v3.js',                  # v3.9: 大盤指數加入自選(台股加權/櫃買+美股四大)
              'src/alert/datahealth_v3.js',               # v3.9 Phase-0: 資料源健檢燈(讀 /health sources)
              # 'src/core/wlgroup_v3.js',                # v3.9: 自選股分組停用 — 使用者覺得篩選列佔版面且未使用;檔案保留待恢復

              'src/alert/toast_v3.js',                    # v3.9 Phase-1: 桌面/頁內 toast 通知(window.notifyToast)
              'src/alert/settle_v3.js',                   # v3.9: 台股結算日(每月第三個週三)前3天浮動toast提醒
              'src/ai/cmdpalette_v3.js',               # v3.9 Phase-3: Command Palette(Ctrl+K 搜尋股票/功能)
              'src/ui/dragwin_v3.js',                  # v3.9 Phase-3: 可拖拉功能視窗(標題列拖曳+記憶位置)
              'src/core/liverefresh_v3.js',              # v3.9: 「1天」盤中每45s靜默自動刷新(動態看盤)
              'src/core/namesearch_v3.js',               # v3.9: 代號框打公司名自動完成(/search 反查台股名)
              'src/core/realtime_v3.js',                 # v3.9: 台股盤中真即時(TWSE MIS 每10s 更新當前分鐘K,解 Yahoo 延遲)
              'src/ai/focus_v3.js',                    # v3.9: 焦點掃描精靈(多訊號組合自動找做多/做空焦點,/focus)
              'src/ai/copilot_v3.js',                  # v4.0: AI 副駕面板(本機 LM Studio,/ai/local)
              'src/screener/wizard_v3.js',                   # v3.9: 加股設定精靈(依賴 StratLib/Backtest/drawtools/setPosition/saveWatches，排最後)
              'src/ui/shell_v5.js',                    # v5.0: 側欄殼層+視圖路由(show/hide，預設圖表工作區；須在 toolbar 前掛好 DOM)
              'src/ui/breadth_v5.js',                  # v5.0 S2: 大盤廣度面板(/breadth，掛 #view-breadth；須在 shell 後)
              'src/ui/toolbar_v3.js',                  # v3.9: 工具列模組化(一階分類+二階下拉,設定驅動;須排最後,整理所有功能鈕)
              'src/chart/market_score_bar_v3.js',      # v4.1: 主圖大盤體質／市場風險資訊列（須在 market_chart 前）
              'src/chart/market_chart_v3.js']          # v4.1: 總經/大盤折線模組（融資維持率等，必須最後掛鉤蓋過 K 線 patch）
V2_STYLES  = ['src/ui/mobile_v2.css']

# v3.9 P5: 依相依關係自動排序模組(取代人工「須在X後」)。失敗則退回原順序,不影響打包。
try:
    from build_order import order_scripts
    V2_SCRIPTS = order_scripts(V2_SCRIPTS)
except Exception as _e:
    print('[build_order] 略過自動排序，用原順序:', _e)

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
    '<title>Stock Terminal v4.1 - Local DB / Portfolio / AI Copilot</title>',
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
              "  if (S.tab==='position') { var _ae=document.activeElement; if(!(_ae&&/^pos-(entry|shares|target|stop|notes|unit)$/.test(_ae.id||''))){ el.innerHTML = renderPosition(); attachPosition(); } return; }")
if 'renderPosition()' not in html:
    html = html.replace(RP_POS_OLD, RP_POS_NEW, 1)

# 3b) renderRpanel - watch dispatch
RP_WATCH_OLD = "if (S.tab==='position') { var _ae=document.activeElement; if(!(_ae&&/^pos-(entry|shares|target|stop|notes|unit)$/.test(_ae.id||''))){ el.innerHTML = renderPosition(); attachPosition(); } return; }"
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
    # 注入到「最後一個」</body>(真正頁尾)。用 rpartition 避免命中 JS 字串裡的字面 </body>。
    _head, _sep, _tail = html.rpartition('</body>')
    html = _head + script_block + _sep + _tail
else:
    html += '\n' + script_block

# 6) banner
if 'data-v2-banner' not in html:
    html = html.replace(
        '<span class="logo">STOCK TERMINAL</span>',
        '<span class="logo" data-v2-banner>STOCK TERMINAL <span style="color:#FBBF24;font-size:9px;letter-spacing:1px;font-weight:700">v4.1</span></span>',
        1)
# Bump existing banner to v4.1
html = re.sub(
    r'(data-v2-banner>STOCK TERMINAL <span[^>]+>)v[0-9]+\.\d+(</span>)',
    r'\g<1>v4.1\g<2>', html, count=1)

with open(DST, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'[OK] wrote {DST}  ({len(html):,} bytes)')
print(f'     base:    {SRC}')
print(f'     modules: {", ".join(V2_SCRIPTS)}')
print()
print('Open in browser:')
print(f'  http://localhost:18432/stock_terminal_v2.html')

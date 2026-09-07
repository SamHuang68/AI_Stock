#!/usr/bin/env python3
"""
Build stock_terminal_v2.html from stock_terminal.html.

v2 = v1 base + POS tab + WATCH tab + position_v2.js + watch_v2.js.
Re-run any time you update v1 and want v2 to inherit the changes.
"""
import argparse, hashlib, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(ROOT, 'stock_terminal.html')
_parser = argparse.ArgumentParser(description='Build deterministic Stock Terminal HTML')
_parser.add_argument('--out', default=os.path.join(ROOT, 'stock_terminal_v2.html'))
_args = _parser.parse_args()
DST = os.path.abspath(_args.out)


def _read_version():
    """單一真理：根目錄 VERSION。"""
    path = os.path.join(ROOT, 'VERSION')
    try:
        with open(path, 'r', encoding='utf-8') as vf:
            for line in vf:
                v = line.strip()
                if v and not v.startswith('#'):
                    return v
    except Exception:
        pass
    return '5.0'


ST_VERSION = _read_version()

# Scripts injected (in order):
V2_SCRIPTS = ['src/core/colors_v3.js',   # 顏色管理表(單一真理來源,須最先載入)
              'src/core/table_sort_v5.js',  # 全域資料表三段排序（動態面板自動接入）
              'src/ui/viz_v5.js',        # v5.0: 文字→視覺共用元件(須在 colors 後、各面板前)
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
              'src/fundamental/instrank_v3.js',                 # 外資/投信/自營商買賣超排行榜
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
              'src/core/intraday_volume_v3.js',          # 累積量單位／來源切換／缺分鐘保護（須在 realtime 前）
              'src/core/realtime_v3.js',                 # v3.9: 台股盤中真即時(TWSE MIS 每10s 更新當前分鐘K,解 Yahoo 延遲)
              'src/ai/focus_v3.js',                    # v3.9: 焦點掃描精靈(多訊號組合自動找做多/做空焦點,/focus)
              'src/ai/copilot_v3.js',                  # v4.0: AI 副駕面板(本機 LM Studio,/ai/local)
              'src/screener/wizard_v3.js',                   # v3.9: 加股設定精靈(依賴 StratLib/Backtest/drawtools/setPosition/saveWatches，排最後)
              'src/ui/shell_v5.js',                    # v5.0: 轉盤殼層+視圖路由(show/hide，預設 #pulse；須在 toolbar 前掛好 DOM)
              'src/ui/wavedeck_bridge_v5.js',          # v5.0: WaveDeck 浪潮執行台入口／ST→WD 橋接
              'src/ui/hub_v5.js',                      # v5.0: TW Pulse 對齊模組（指數/法人/國際/訊號/自選/風險/設定）
              'src/ui/pulse_v5.js',                    # v5.0: TW Pulse 市場脈動總覽（組合既有 API，掛 #view-pulse）
              'src/ui/decision_v5.js',                 # v5.x: 策略決策中心（DecisionContext／Evidence／Scenario Matrix）
              'src/ui/consensus_attention_v5.js',       # v5.x: 共識雷達（DecisionContext 注意力投影；無獨立輪詢）
              'src/ui/heat_v5.js',                     # v5.0: 類股熱力+/focus 輔區（掛 #view-heat）
              'src/ui/book_v5.js',                     # v5.0: 投組風險側欄（POST /portfolio，掛 #view-book）
              'src/ui/scan_v5.js',                     # v5.0: 三合一選股側欄（POST /screen3，掛 #view-scan）
              'src/ui/ai_v5.js',                       # v5.0: AI 中樞（報告/副駕/焦點，掛 #view-ai）
              'src/ui/breadth_v5.js',                  # v5.0: 大盤廣度面板(/breadth，掛 #view-breadth；須在 shell 後)
              'src/ui/afterhours_v5.js',               # v5.0: 盤後整理(/txf+/stockfut+/marketflow，掛 #view-afterhours)
              'src/ui/news_v5.js',                     # v5.0: 快訊中樞(/events+結算日，掛 #view-news；非新聞爬蟲)
              'src/ui/postmarket_v5.js',               # v5.x: 盤後敘事日報 drawer(/api/ai/postmarket-daily，由 ai_v5「盤後日報」開啟)
              'src/ui/conditional_expectation_v5.js',  # v5.x: shadow Conditional Expectation card (/research/conditional-expectation)
              'src/ui/peak_observation_v5.js',         # v5.x: st-peak-v0.1 CONDITIONAL observation (/research/peak-observation)
              'src/ui/peak_observation_100d_v5.js',    # v5.x: st-peak-100d-v0 CONDITIONAL observation (/research/peak-observation-100d)
              'src/ui/touxin_5d_v5.js',                # v5.x: st-touxin-5d-v0 CONDITIONAL 投信5日買超 (/research/touxin-5d-netbuy)
              'src/ui/bridge_v5.js',                   # v5.0: 工具列→側欄橋接（須在 *Open 定義後、toolbar 前）
              'src/ui/visual_system_v5.js',            # v5.0: 全站 elevation / border / shadow 視覺契約
              'src/ui/chart_visual_v5.js',             # v5.0: 圖表工作站色票／層級／膠囊與數據卡契約
              'src/ui/toolbar_v3.js',                  # v3.9: 工具列模組化(一階分類+二階下拉,設定驅動;須排最後,整理所有功能鈕)
              'src/chart/market_score_bar_v3.js',      # v4.1: 主圖大盤體質／市場風險資訊列（須在 market_chart 前）
              'src/chart/market_chart_v3.js']          # v4.1: 總經/大盤折線模組（融資維持率等，必須最後掛鉤蓋過 K 線 patch）
V2_STYLES  = ['src/ui/mobile_v2.css']

# v3.9 P5: 依相依關係自動排序模組(取代人工「須在X後」)。失敗則退回原順序,不影響打包。
V2_SCRIPTS.insert(1, 'src/core/app_kernel_v5.js')  # single API + panel lifecycle boundary
V2_SCRIPTS.insert(2, 'src/core/feature_flags_v5.js')  # shadow / experimental gates (default off)
V2_SCRIPTS.insert(3, 'src/core/epistemic_badges_v5.js')  # FACT | CONDITIONAL | HYPOTHESIS badges
V2_SCRIPTS.insert(4, 'src/core/market_freshness_v5.js')  # per-quote asOf freshness helpers
V2_SCRIPTS.insert(5, 'src/core/market_data_v5.js')  # canonical market quote store
V2_SCRIPTS.insert(6, 'src/core/decision_data_v5.js')  # canonical DecisionContext store
V2_SCRIPTS.insert(7, 'src/core/market_intel_v5.js')  # shared theme resonance + news/watch linkage

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

# 1) Update title（跟 VERSION）
html = re.sub(
    r'<title>[^<]*</title>',
    f'<title>Stock Terminal v{ST_VERSION} - Market Intelligence / Local DB / AI Copilot</title>',
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
ETF_RP_NEW = "if (S.tab==='etf')      { el.innerHTML = window.renderEtfV3 ? window.renderEtfV3() : ''; return; }"
if 'window.renderEtfV3 ? window.renderEtfV3()' not in html:
    html = html.replace(ETF_RP_OLD, ETF_RP_NEW, 1)
html = html.replace(
    "if (S.tab==='etf')      { el.innerHTML = (window.renderEtfDelta || renderEtfDelta)(); return; }",
    ETF_RP_NEW,
)

# 3d) fetchEtfDelta -> window
FETCH_ETF_OLD = "fetchEtfDelta();"
FETCH_ETF_NEW = "if (typeof window.etfV3FetchDelta === 'function') window.etfV3FetchDelta();"
if 'window.etfV3FetchDelta' not in html:
    html = html.replace(FETCH_ETF_OLD, FETCH_ETF_NEW, 1)
html = html.replace("(window.fetchEtfDelta || fetchEtfDelta)();", FETCH_ETF_NEW)

# 3e) renderEtfHoldingsForStock -> window
HOLD_OLD = "${renderEtfHoldingsForStock(S.sym)}"
HOLD_NEW = "${window.renderEtfHoldingsV3 ? window.renderEtfHoldingsV3(S.sym) : ''}"
if 'window.renderEtfHoldingsV3 ? window.renderEtfHoldingsV3(S.sym)' not in html:
    html = html.replace(HOLD_OLD, HOLD_NEW, 1)
html = html.replace(
    "${(window.renderEtfHoldingsForStock||renderEtfHoldingsForStock)(S.sym)}",
    HOLD_NEW,
)

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
LS_NEW = ("  if (S.ind && typeof window.updateEtfFlowIndV3 === 'function') window.updateEtfFlowIndV3();\n"
          "  try { renderRpanel(); } catch (e) { console.error('[v1] renderRpanel threw:', e); }\n"
          "  try { window.dispatchEvent(new CustomEvent('symLoaded', {detail:{sym: S.sym, mkt: S.mkt}})); } catch(e){}")
if 'symLoaded' not in html:
    html = html.replace(LS_OLD, LS_NEW, 1)
html = html.replace("if (S.ind) updateEtfFlowInd();", "if (S.ind && typeof window.updateEtfFlowIndV3 === 'function') window.updateEtfFlowIndV3();")

# 5) inject scripts + stylesheets
asset_digest = hashlib.sha256(ST_VERSION.encode('utf-8'))
for asset in V2_SCRIPTS + V2_STYLES:
    asset_digest.update(asset.encode('utf-8'))
    with open(os.path.join(ROOT, asset), 'rb') as source:
        asset_digest.update(source.read())
revision = asset_digest.hexdigest()[:12]
for js in V2_SCRIPTS:
    html = re.sub(rf'<script[^>]+{re.escape(js)}[^>]*></script>\s*', '', html)
html = re.sub(r'<script[^>]+etf_v2\.js[^>]*></script>\s*', '', html)
for css in V2_STYLES:
    html = re.sub(rf'<link[^>]+{re.escape(css)}[^>]*>\s*', '', html)

if 'name="viewport"' not in html:
    html = html.replace('<head>', '<head>\n<meta name="viewport" content="width=device-width,initial-scale=1.0">', 1)

# tip UX boot：無 hash → #pulse；shell 掛上前隱藏舊圖表殼（防合完／重開閃回舊 UI）
TIP_BOOT = (
    '<!-- tip-ux-boot -->\n'
    '<meta name="st-ux" content="tip">\n'
    '<style id="st5-tip-boot">'
    'html:not(.st5-booted) #body,html:not(.st5-booted) #wlbar,html:not(.st5-booted) #mkt-bar'
    '{display:none!important}'
    '</style>\n'
    '<script id="st5-tip-hash">'
    '(function(){try{var h=(location.hash||"").replace(/^#/,"").trim();'
    'if(!h){location.replace(location.pathname+location.search+"#pulse");}}catch(e){}})();'
    '</script>\n'
)
# 避免重複注入
html = re.sub(r'<!-- tip-ux-boot -->[\s\S]*?<script id="st5-tip-hash">[\s\S]*?</script>\s*', '', html)
if 'id="st5-tip-boot"' not in html:
    if '<head>' in html:
        html = html.replace('<head>', '<head>\n' + TIP_BOOT, 1)
    else:
        html = TIP_BOOT + html

css_block = ''.join(f'<link rel="stylesheet" href="{css}?v={revision}">\n' for css in V2_STYLES)
if '</head>' in html:
    html = html.replace('</head>', css_block + '</head>', 1)

script_block = ''.join(f'<script src="{js}?v={revision}"></script>\n' for js in V2_SCRIPTS)
if '</body>' in html:
    # 注入到「最後一個」</body>(真正頁尾)。用 rpartition 避免命中 JS 字串裡的字面 </body>。
    _head, _sep, _tail = html.rpartition('</body>')
    html = _head + script_block + _sep + _tail
else:
    html += '\n' + script_block

# 6) banner（跟 VERSION）
if 'data-v2-banner' not in html:
    html = html.replace(
        '<span class="logo">STOCK TERMINAL</span>',
        f'<span class="logo" data-v2-banner>STOCK TERMINAL <span style="color:#FBBF24;font-size:9px;letter-spacing:1px;font-weight:700">v{ST_VERSION}</span></span>',
        1)
html = re.sub(
    r'(data-v2-banner>STOCK TERMINAL <span[^>]+>)v[0-9]+(?:\.\d+)*(?:-[A-Za-z0-9.]+)?(</span>)',
    rf'\g<1>v{ST_VERSION}\g<2>', html, count=1)

os.makedirs(os.path.dirname(DST), exist_ok=True)
with open(DST, 'w', encoding='utf-8', newline='\n') as f:
    f.write(html)

# tip UX 契約：建置失敗硬停，避免使用者開到半套舊殼
if any(x not in html for x in ('app_kernel_v5.js', 'shell_v5.js', 'pulse_v5.js', 'decision_data_v5.js',
                               'decision_v5.js', 'consensus_attention_v5.js')):
    print('[FAIL] tip UX modules missing from built HTML (shell / pulse / DecisionContext)')
    sys.exit(1)
_after_html = html.partition('</html>')[2]
if _after_html.strip():
    print('[FAIL] content found after closing </html>; legacy owner may override modules')
    sys.exit(1)
if 'function fetchEtfDelta' in html or '(window.fetchEtfDelta || fetchEtfDelta)' in html:
    print('[FAIL] legacy ETF fetch owner remains in built HTML')
    sys.exit(1)
if 'id="st5-tip-boot"' not in html:
    print('[FAIL] tip UX boot CSS/hash guard missing from built HTML')
    sys.exit(1)

print(f'[OK] wrote {DST} ({len(html):,} bytes, revision {revision})')
print(f'     version: v{ST_VERSION}  (from VERSION)  tip UX')
print(f'     immutable input: {SRC}')
print(f'     modules: {", ".join(V2_SCRIPTS)}')
print()
print('Open in browser (tip UX only):')
print(f'  http://localhost:18432/#pulse')

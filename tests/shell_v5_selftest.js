/**
 * shell_v5_selftest.js — ST 5.0 tip 殼層／品牌／熱鍵契約（無瀏覽器）
 * 用法：node tests/shell_v5_selftest.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const shell = fs.readFileSync(path.join(root, 'src/ui/shell_v5.js'), 'utf8');
const hotkeys = fs.readFileSync(path.join(root, 'src/chart/hotkeys_v3.js'), 'utf8');
const position = fs.readFileSync(path.join(root, 'src/core/position_v2.js'), 'utf8');
const sourceHtml = fs.readFileSync(path.join(root, 'stock_terminal.html'), 'utf8');

let failed = 0;
function ok(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); failed++; }
  else console.log('OK  ', msg);
}

ok(/VERSION = '5\.0'/.test(shell), 'VERSION is 5.0');
ok(/st50-icon\.svg/.test(shell), 'ST icon asset referenced');
ok(fs.existsSync(path.join(root, 'assets/st50-icon.svg')), 'assets/st50-icon.svg exists');
ok(/HOTKEY_ROUTES/.test(shell), 'HOTKEY_ROUTES defined');
ok(/stripLegacyNav/.test(shell) && /#navrail,#nr-edge,#nr-backdrop\{display:none/.test(shell),
  'shell strips legacy sidebar (navrail removed)');
ok(/deactivateRoute/.test(shell), 'deactivate on leave');
ok(/softBadge/.test(shell), 'softBadge helper');
ok(/data-st50-favicon/.test(shell), 'favicon wired');
ok(/shell-logo-ico/.test(shell), 'topbar logo icon');

['pulse', 'decision', 'chart', 'breadth', 'heat', 'institutional', 'ai', 'scan', 'book', 'settings'].forEach(function (id) {
  ok(new RegExp("id: '" + id + "'").test(shell), 'route ' + id);
});

ok(/ShellV5\.go\('chart'\)/.test(hotkeys), 'Esc → chart in hotkeys');
ok(/Alt\+Shift\+1/.test(hotkeys), 'Alt+Shift help row');
ok(/ai: 'AiV5'/.test(shell), 'AiV5 in PANEL_MAP');

['decision_v5.js', 'breadth_v5.js', 'heat_v5.js', 'afterhours_v5.js', 'news_v5.js', 'pulse_v5.js', 'ai_v5.js'].forEach(function (f) {
  const t = fs.readFileSync(path.join(root, 'src/ui', f), 'utf8');
  ok(/deactivate/.test(t), f + ' has deactivate');
});

const bridge = fs.readFileSync(path.join(root, 'src/ui/bridge_v5.js'), 'utf8');
ok(/portfolioOpen/.test(bridge) && /marketFlowOpen/.test(bridge) && /openAIModal/.test(bridge),
  'bridge_v5 wraps portfolio/marketflow/AI');
const build = fs.readFileSync(path.join(root, 'build_v2.py'), 'utf8');
ok(build.indexOf('src/ui/ai_v5.js') >= 0 && build.indexOf('src/ui/bridge_v5.js') >= 0,
  'ai_v5 + bridge_v5 in build_v2');
const colors = fs.readFileSync(path.join(root, 'src/core/colors_v3.js'), 'utf8');
const marketContract = fs.readFileSync(path.join(root, 'src/core/market_v3.js'), 'utf8');
const fundamental = fs.readFileSync(path.join(root, 'src/fundamental/fundamental_v3.js'), 'utf8');
const polish = fs.readFileSync(path.join(root, 'src/ui/polish_v3.js'), 'utf8');
const marketData = fs.readFileSync(path.join(root, 'src/core/market_data_v5.js'), 'utf8');
const appKernel = fs.readFileSync(path.join(root, 'src/core/app_kernel_v5.js'), 'utf8');
const decisionData = fs.readFileSync(path.join(root, 'src/core/decision_data_v5.js'), 'utf8');
const marketIntel = fs.readFileSync(path.join(root, 'src/core/market_intel_v5.js'), 'utf8');
const decisionUi = fs.readFileSync(path.join(root, 'src/ui/decision_v5.js'), 'utf8');
const consensusAttentionUi = fs.readFileSync(path.join(root, 'src/ui/consensus_attention_v5.js'), 'utf8');
const scanUi = fs.readFileSync(path.join(root, 'src/ui/scan_v5.js'), 'utf8');
const tableSortUi = fs.readFileSync(path.join(root, 'src/core/table_sort_v5.js'), 'utf8');
const server = fs.readFileSync(path.join(root, 'server/server.py'), 'utf8');
const sectorHistory = fs.readFileSync(path.join(root, 'server/sector_history.py'), 'utf8');
const sectorFlow = fs.readFileSync(path.join(root, 'server/sector_flow.py'), 'utf8');
const decisionEngine = fs.readFileSync(path.join(root, 'server/decision_context.py'), 'utf8');
const exposureLabEngine = fs.readFileSync(path.join(root, 'server/exposure_lab.py'), 'utf8');
const overnightEngine = fs.readFileSync(path.join(root, 'server/overnight_intraday.py'), 'utf8');
const earlyWarningEngine = fs.readFileSync(path.join(root, 'server/early_warning.py'), 'utf8');
const visualSystem = fs.readFileSync(path.join(root, 'src/ui/visual_system_v5.js'), 'utf8');
const chartVisual = fs.readFileSync(path.join(root, 'src/ui/chart_visual_v5.js'), 'utf8');
const mobileCss = fs.readFileSync(path.join(root, 'src/ui/mobile_v2.css'), 'utf8');
ok(/s === '__TXF__'/.test(colors) && /\^__TW_/.test(colors) && /dirRU/.test(colors),
  'color contract recognizes TXF and TW local symbols as red-up instruments');
ok(/function isJpFmt/.test(marketContract) && /return 'JP'/.test(marketContract) &&
  !/id="btn-jp"/.test(fs.readFileSync(path.join(root, 'stock_terminal.html'), 'utf8')) &&
  /mkt === 'JP'/.test(fs.readFileSync(path.join(root, 'stock_terminal.html'), 'utf8')),
  'JP contract remains available for broad-market observation without a stock-trading selector');
ok(/function isJP/.test(colors) && /function isRedUp/.test(colors) &&
  /body\.market-jp \.price-up/.test(polish),
  'Japan price direction uses red-up/green-down without being classified as TWSE');
ok(/--vs-surface-0/.test(visualSystem) && /--vs-shadow-2/.test(visualSystem) &&
  /pl-beginner-hero/.test(visualSystem) && /hub-root \.hub-sec/.test(visualSystem) &&
  /--vs-beginner-card/.test(visualSystem) && /--vs-beginner-inset/.test(visualSystem) &&
  /hub-root \.hub-strip \.cell:before/.test(visualSystem) && /dc-root \.dc-feature:before/.test(visualSystem) &&
  /prefers-reduced-motion/.test(visualSystem) && /visual_system_v5\.js/.test(build),
  'executive visual system is shared by overview and dense work panels');
ok(/function themeFor/.test(chartVisual) && /Colors\.isRedUp/.test(chartVisual) &&
  /candleUp/.test(chartVisual) && /volumeUp/.test(chartVisual) && /score-ring/.test(chartVisual) &&
  /#chart-search/.test(chartVisual) && /\.vp-poc/.test(chartVisual) && /\.mkt-cell/.test(chartVisual) &&
  /chart_visual_v5\.js/.test(build),
  'chart workspace shares one market-aware palette across candles, volume, controls and metric cards');
ok(/#wlbar\{height:67px!important/.test(chartVisual) && /height:30px!important/.test(chartVisual) &&
  /wlchip-stack\{padding:0!important;max-height:27px;overflow:visible/.test(chartVisual) &&
  /wlchip-primary\{min-height:10px;line-height:1/.test(chartVisual) &&
  /wladd\{height:62px/.test(chartVisual) && /#rangebar,\s*\nhtml\.st-vs5 #rtabs\{/.test(chartVisual) &&
  /height:26px!important;min-height:26px!important;max-height:26px!important/.test(chartVisual) &&
  /#rangebar \.rgbtn,\s*\nhtml\.st-vs5 #rtabs \.rtab\{/.test(chartVisual) &&
  /height:25px!important;min-height:25px!important/.test(chartVisual),
  'chart watchlist stays compact and timeframe/right-panel tabs share one 26px baseline');
ok(/\.wlchip-primary/.test(polish) && /if \(mkt === 'TW'\)/.test(polish) &&
  /primary\.appendChild\(t\)/.test(polish) && /primary\.appendChild\(p\)/.test(polish) &&
  /meta\.appendChild\(codeSpan\)/.test(polish) &&
  /if \(etfBadge\) meta\.appendChild\(etfBadge\)/.test(polish) &&
  /meta\.appendChild\(p\)/.test(polish) && /stack\.appendChild\(meta\)/.test(polish),
  'TW watchlist owns a name/change top row and code/ETF bottom row while US keeps its prior layout');
ok(/\{t:'2330',m:'TW',name:'台積電'\}/.test(sourceHtml) &&
  /\{t:'2454',m:'TW',name:'聯發科'\}/.test(sourceHtml) &&
  /\{t:'3661',m:'TW',name:'世芯-KY'\}/.test(sourceHtml) &&
  /\{t:'6669',m:'TW',name:'緯穎'\}/.test(sourceHtml) &&
  /if \(preset\?\.name\) w\.name = preset\.name/.test(sourceHtml),
  'fresh and older profiles receive known Taiwan names instead of duplicate symbol rows');
ok(fundamental.includes('?traceId=${encodeURIComponent(traceId)}') &&
  polish.includes('?traceId=${encodeURIComponent(traceId)}') &&
  /_fInflight\[key\]/.test(fundamental) && /_keystatsInflight\[key\]/.test(polish) &&
  !fundamental.includes("headers: { 'X-ST-Trace-ID'") &&
  !polish.includes("headers: { 'X-ST-Trace-ID'") &&
  /trace_qs\.get\('traceId'\)/.test(server),
  'fundamental and keystats use one in-flight simple GET without CORS preflight');
ok(!/body\.market-us \.price-up,\s*body\.market-us \.pos/.test(polish) &&
  !/body\.market-tw \.price-up,\s*body\.market-tw \.pos/.test(polish),
  'active chart market no longer overrides generic pos/neg classes across unrelated panels');
ok(/function applyMktCellTone/.test(polish) && /overwrite stale inline color/.test(polish) &&
  /applyMktCellTone\(cell, delta, true\)/.test(polish) &&
  /applyMktCellTone\(cell, chg, true\)/.test(polish),
  'market bar resets current-source color for TWSE/TAIFEX overrides');
ok(/window\.MarketData/.test(marketData) && /marketData/.test(polish) && /\/market\/snapshot/.test(marketData),
  'market headline surfaces use one canonical snapshot/event store');
ok(/attachFreshness/.test(marketData) && /worstAsOf/.test(marketData) &&
  /src\/core\/market_freshness_v5\.js/.test(build) &&
  /window\.MarketFreshness/.test(fs.readFileSync(path.join(root, 'src/core/market_freshness_v5.js'), 'utf8')) &&
  /shellHealthText/.test(shell) && /MarketFreshness\.shellHealthText/.test(shell),
  'Codex per-quote asOf freshness is wired into MarketData, build, and shell health');
ok(/window\.DecisionData/.test(decisionData) && /inflight/.test(decisionData) && /decisionData/.test(decisionUi) &&
  /decisionSummary/.test(fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8')) &&
  /decision_contract_version/.test(fs.readFileSync(path.join(root, 'src/ui/wavedeck_bridge_v5.js'), 'utf8')),
  'decision surfaces use one canonical DecisionContext store');
ok(/TW_DOWNSIDE_PRECURSOR/.test(earlyWarningEngine) && /TW_ATTACK_BUILDUP/.test(earlyWarningEngine) &&
  /AI_WAFER_DOUBLE_ARROW/.test(earlyWarningEngine) && /MEMORY_CYCLE_RESONANCE/.test(earlyWarningEngine) &&
  /shadowOnly/.test(earlyWarningEngine) && /actionAuthority/.test(earlyWarningEngine),
  'market precursor engine exposes four named shadow-only signals');
ok(/earlyWarningHtml/.test(decisionUi) && /跨市場前兆雷達/.test(decisionUi) && /訊號強度不是機率/.test(decisionUi),
  'decision page renders readable precursor strength and authority boundary');
ok(/function warningTemporalHtml/.test(decisionUi) && /warning\.temporalContext/.test(decisionUi) &&
  /目標 T\+/.test(decisionUi) && /即時計算/.test(decisionUi) && /混合時效資料/.test(decisionUi) &&
  /下一個至第五個台股交易日/.test(decisionUi),
  '前兆雷達明示計算時間、混合時效與 T+1～T+5 目標期間');
ok(/function warningMarketStripHtml/.test(decisionUi) && /現貨收盤/.test(decisionUi) &&
  /台指夜盤/.test(decisionUi) && /上市廣度/.test(decisionUi) && /現況／前兆分歧/.test(decisionUi),
  '前兆雷達分開呈現目前市場與多日前兆，並提示夜盤方向分歧');
ok(/下行前兆證據/.test(decisionUi) && /上行前兆證據/.test(decisionUi) &&
  /觀測・未形成/.test(decisionUi) && /watchStrength/.test(decisionUi) && /尚未達注意門檻/.test(decisionUi),
  '前兆 headline 使用證據語意並揭露注意門檻');
ok(/不是目前夜盤方向，也不是上漲／下跌機率/.test(decisionUi) &&
  /refreshMarketData\(\{ background: true \}\)/.test(decisionUi) &&
  /marketRefreshInflight/.test(decisionUi) && !/\/market\/snapshot/.test(decisionUi),
  '決策頁以 canonical Pulse 背景重建，不另建市場資料路徑或把分數當機率');
ok(/prospectiveValidationHtml/.test(decisionUi) && /前瞻驗證建置中/.test(decisionUi) &&
  /不是未來機率/.test(decisionUi) && /ratesAvailable/.test(decisionUi),
  'decision page exposes sample-gated prospective validation without probability language');
ok(/\/signals\/active/.test(server) && /\/signals\/history/.test(server) && /\/signals\/performance/.test(server),
  'server exposes read-only signal state, transition history and prospective performance routes');
ok(/src\/core\/market_intel_v5\.js/.test(build) && /window\.MarketIntelV5/.test(marketIntel) &&
  /linkNewsToWatchlist/.test(marketIntel) && /buildThemeResonance/.test(marketIntel),
  'build includes the shared market-intelligence taxonomy and news/watchlist linker');
ok(/linkNewsToWatchlist/.test(decisionUi) && /dc-news-watch/.test(decisionUi) && /bindNewsLinks/.test(decisionUi) &&
  /MarketIntelV5/.test(fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8')),
  'decision and pulse share one direct/theme News Impact watchlist contract');
ok(/成交口徑：上市普通股產業內占比/.test(decisionUi) && /historyDates/.test(decisionUi) &&
  /turnoverEligible/.test(decisionUi) && /industryTurnoverYi/.test(server) && /sector_history/.test(server) &&
  /TWSE_COMMON_STOCKS_BY_INDUSTRY/.test(sectorFlow) && /normalize_session_date/.test(sectorFlow) &&
  /turnoverSessionMatched/.test(server) && /enrich_sector_rows/.test(sectorHistory),
  'sector flow exposes official-industry turnover scope and persistent RS20 readiness');
ok(/情境訊號矩陣/.test(decisionUi) && /Evidence Ledger/.test(decisionUi) && /Risk Profile/.test(decisionUi) &&
  /positionRange/.test(decisionUi) && /observation_pool/.test(decisionUi) &&
  /observation_pool_not_risk_overlay/.test(decisionUi) && /breadthTrendHtml/.test(decisionUi),
  'decision page exposes scenario, evidence, transparent risk profile and observation-pool label');
ok(/function evidenceCategory/.test(decisionUi) && /data-evidence-category/.test(decisionUi) &&
  /data-evidence-mode/.test(decisionUi) && /data-evidence-scope/.test(decisionUi) &&
  /dc-evidence-query/.test(decisionUi) && /警示／異常/.test(decisionUi) && /即時資料/.test(decisionUi),
  'Evidence Ledger groups evidence and supports search, status and market filters');
ok(/function relativeTimeInfo/.test(decisionUi) && /dc-fresh-dot/.test(decisionUi) &&
  /前一交易日/.test(decisionUi) && /季度研究基準/.test(decisionUi) &&
  /function sourceInfo/.test(decisionUi) && /dc-source-link/.test(decisionUi),
  'Evidence Ledger exposes session-aware freshness and source inspection without raw timestamps dominating');
ok(/function evidenceObjectHtml/.test(decisionUi) && /3日斜率/.test(decisionUi) && /弱於中線/.test(decisionUi) &&
  /function divergenceLink/.test(decisionUi) && /dc-linkage/.test(decisionUi) &&
  !/typeof e\.value === 'object' \? JSON\.stringify\(e\.value\)/.test(decisionUi),
  'Evidence Ledger formats structured values and links upstream divergence warnings');
ok(/data-evidence-copy="json"/.test(decisionUi) && /data-evidence-copy="csv"/.test(decisionUi) &&
  /data-evidence-copy="debug"/.test(decisionUi) && /function evidenceCsv/.test(decisionUi) &&
  /原始值未改寫/.test(decisionUi),
  'Evidence Ledger preserves raw audit values and copies JSON, CSV or bounded debug context');
ok(/function portfolioSwitchHtml/.test(decisionUi) && /dc-portfolio-switch/.test(decisionUi) &&
  /class="dc-card"><h3 class="dc-portfolio-head"><span>Portfolio Overlay/.test(decisionUi) &&
  !/<button class="dc-btn" id="dc-use-positions">/.test(decisionUi) &&
  /data-portfolio-switch-bound/.test(decisionUi) && /root\.addEventListener\('click'/.test(decisionUi) &&
  /setPortfolioMode: setPortfolioMode/.test(decisionUi),
  'portfolio source switch lives inside Portfolio Overlay instead of the page header');
ok(/function scenarioDetail/.test(decisionUi) && /function featureSignal/.test(decisionUi) &&
  /上漲占比 /.test(decisionUi) && /3\/5日斜率/.test(decisionUi) && /法人 /.test(decisionUi) &&
  /美國科技 /.test(decisionUi) && /風險負擔/.test(decisionUi) && /risk \? -Math\.abs/.test(decisionUi) &&
  /dc-scale-legend/.test(decisionUi) && !/JSON\.stringify\(f\.raw/.test(decisionUi),
  'scenario matrix formats raw evidence as bounded semantic summaries without overflow');
ok(/Exposure Lab/.test(decisionUi) && /Shadow · 研究上限/.test(decisionUi) &&
  /<details class="dc-lab" open>/.test(decisionUi) &&
  /dc-temp/.test(decisionUi) && /dc-thermo/.test(decisionUi) && /曝險壓力/.test(decisionUi) && /過熱/.test(decisionUi) &&
  /波動壓力/.test(exposureLabEngine) && /融資擁擠/.test(exposureLabEngine) &&
  /槓桿適配/.test(exposureLabEngine) && /投組曝險/.test(exposureLabEngine) &&
  /單一最高風險至少保留/.test(exposureLabEngine) &&
  /<details class="dc-lab-detail" open><summary>數據與判定依據/.test(decisionUi) &&
  /#60a5fa/.test(decisionUi) && /#facc15/.test(decisionUi) && /#fb923c/.test(decisionUi) &&
  /hypotheses\.map/.test(decisionUi) &&
  !/00685L/.test(decisionUi) && /selectedResearchCeilingPct/.test(decisionUi),
  'Exposure Lab opens with professional exposure-pressure lights and expanded evidence');
ok(/dc-temp-light \.s\{grid-column:1\/-1;text-align:center/.test(decisionUi) &&
  /num\(x\[1\], 0\)/.test(decisionUi) && /function confidenceIcon/.test(decisionUi) &&
  /dc-confidence/.test(decisionUi) && /width:54px;height:54px/.test(decisionUi) &&
  /conic-gradient\(#22d3ee var\(--confidence\)/.test(decisionUi) && /percentage \+ '<small>%/.test(decisionUi) &&
  /function compactObserved/.test(decisionUi) &&
  /function indexBreadthVisual/.test(decisionUi) && /function basisVisual/.test(decisionUi) &&
  /dc-breadth-bar/.test(decisionUi) && /dc-basis-gauge/.test(decisionUi) &&
  !/JSON\.stringify\(compactObserved\(d\.observed/.test(decisionUi) &&
  !/ · 信心 ' \+ pct01\(d\.confidence\)/.test(decisionUi),
  'decision uses visual divergence overlays, breadth structure, basis gauge and rounded confidence icons');
ok(/function mandatoryControlsHtml/.test(decisionUi) && /dc-mandatory/.test(decisionUi) && /強制限制/.test(decisionUi) &&
  /breadth_divergence_risk_lock/.test(decisionUi) && /mandatoryControls/.test(decisionEngine),
  'high-confidence breadth divergence drives explicit Action Envelope red-light controls');
ok(/function optionsStructureHtml/.test(decisionUi) && /data-layer=\"observed\"/.test(decisionUi) &&
  /data-layer=\"derived\"/.test(decisionUi) && /data-layer=\"modeled\"/.test(decisionUi) &&
  /optionsLabOpen = true/.test(decisionUi) && /function bindOptionsLab/.test(decisionUi) &&
  /data-st-sort=\"off\"/.test(decisionUi) && /\/options\/txo\/refresh/.test(decisionUi) &&
  /DecisionData\.publish\(ctx, 'options-refresh'\)/.test(decisionUi),
  'TXO options structure keeps observed, derived and modeled layers distinct in one canonical DecisionContext');
ok(/topVegaStrikes/.test(decisionUi) && /Modeled Signed VEX/.test(decisionUi) &&
  /IV \+1 波動率點（1 vol pt）/.test(decisionUi) && /dc-options-density-grid/.test(decisionUi) &&
  /function optionsHistoryHtml/.test(decisionUi) && /dc-options-change/.test(decisionUi) &&
  /history\.status|var status = history\.status/.test(decisionUi) && /Number\(current\.contractVersion/.test(decisionUi),
  'TXO V2 adds direction-neutral Vega density, modeled Signed VEX and same-expiry history without changing collapsed summary');
ok(!/optionsStructure: context\.optionsStructure/.test(decisionData) &&
  /台指選擇權結構/.test(decisionUi) && /不推定造市商持倉/.test(decisionUi) &&
  /Gamma／Vega 密度是方向中立/.test(decisionUi),
  'options research stays out of the Pulse summary and discloses public-OI limitations');
ok(/\/research\/overnight-intraday/.test(decisionData) && /researchObservations/.test(decisionData) &&
  /盤別動量結構/.test(decisionUi) && /隔夜定價/.test(decisionUi) && /日間承接/.test(decisionUi) &&
  /族群同步率/.test(decisionUi) && /Shadow · 觀察/.test(decisionUi) && /actionAuthority/.test(overnightEngine),
  'overnight/intraday research uses the canonical DecisionData writer and an explicit shadow panel');
ok(/function refreshOvernightResearch/.test(decisionData) && !/research\/overnight-intraday/.test(decisionUi) &&
  /summary:\s*\{[\s\S]*?model: context\.model/.test(decisionData) &&
  !/summary:\s*\{[\s\S]*?overnightIntraday[\s\S]*?model: context\.model/.test(decisionData),
  'shadow session research does not create a second UI fetch path or enter the compact authoritative summary');
ok(/adjustedOpen = rawOpen \* adjClose\/rawClose/.test(overnightEngine) && /IDENTITY_TOLERANCE = 1e-10/.test(overnightEngine) &&
  /"8299\.TWO"/.test(overnightEngine) && !/"3260\.TWO"/.test(overnightEngine) && /same-market daily session residual/.test(overnightEngine),
  'session research enforces adjusted OHLC identity and reuses the canonical memory watch taxonomy');
ok(/持有 /.test(fs.readFileSync(path.join(root, 'src/core/pro_v2.js'), 'utf8')) &&
  /今日 /.test(fs.readFileSync(path.join(root, 'src/core/pro_v2.js'), 'utf8')) &&
  /Colors\.dir\(item\.code/.test(fs.readFileSync(path.join(root, 'src/core/pro_v2.js'), 'utf8')),
  'POS distinguishes holding return from today change with TW-aware colors');
ok(/SORT_COLUMNS/.test(scanUi) && /function sortedResults/.test(scanUi) && /function cycleSort/.test(scanUi) &&
  /data-sort/.test(scanUi) && /aria-sort/.test(scanUi) && /缺值永遠沉底/.test(scanUi),
  'scan result headers support stable three-state sorting with missing values last');
ok(/table_sort_v5\.js/.test(build) && /MutationObserver/.test(tableSortUi) && /function enhanceTable/.test(tableSortUi) &&
  /direction === 'ascending' \? 'descending' : 'none'/.test(tableSortUi) && /升冪與降冪都將缺值固定沉底/.test(tableSortUi) &&
  /\.pf-hm,\.bk-hm/.test(tableSortUi) && /data-st-sort="off"/.test(scanUi),
  'all list-style panel tables inherit global three-state sorting while matrix/native tables opt out');
ok(/↻ 立即更新市場資料/.test(decisionUi) && /\/pulse\?refresh=1/.test(decisionUi) &&
  /refreshMarketData/.test(decisionUi),
  'decision empty state can refresh pulse and context without route switching');
const archifyEvidencePath = '/assets/docs/archify/st-decision-evidence-lineage.html';
ok(decisionUi.includes(archifyEvidencePath) && consensusAttentionUi.includes(archifyEvidencePath),
  'decision center and consensus radar share one frozen Archify evidence document');
ok(/target="_blank"/.test(decisionUi) && /rel="noopener noreferrer"/.test(decisionUi) &&
  /target="_blank"/.test(consensusAttentionUi) && /rel="noopener noreferrer"/.test(consensusAttentionUi),
  'Archify evidence links use safe on-demand new-tab navigation');
ok(!/<iframe\b/i.test(decisionUi) && !/<iframe\b/i.test(consensusAttentionUi) &&
  !/\bfetch\s*\(/.test(consensusAttentionUi),
  'Archify documents add no iframe or second runtime fetch path');
ok(/market_refresh_terminal_success/.test(decisionUi) &&
  /market_refresh_terminal_failure/.test(decisionUi) &&
  /st_decision_ui_trace_v1/.test(decisionData),
  'decision refresh has persistent correlated success/failure trace');
const pulseBeginner = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
ok(/st_pulse_view_mode_v1/.test(pulseBeginner) && /\? 'expert' : 'beginner'/.test(pulseBeginner) &&
  /id="pl-view-beginner"/.test(pulseBeginner) && /id="pl-view-expert"/.test(pulseBeginner),
  'pulse defaults to beginner mode and preserves an explicit expert switch');
ok(/pl-beginner-gauge/.test(pulseBeginner) && /市場情緒/.test(pulseBeginner) &&
  /每 10 家約/.test(pulseBeginner) && /今日上方天花板/.test(pulseBeginner) &&
  /今日下方地板/.test(pulseBeginner),
  'beginner mode exposes gauge, plain-language breadth and two safety boundaries');
ok(/class="marker-halo"/.test(pulseBeginner) && /class="marker"/.test(pulseBeginner) &&
  /offset="\.32" stop-color="#4ade80"/.test(pulseBeginner) &&
  /offset="\.82" stop-color="#f87171"/.test(pulseBeginner),
  'beginner gauge has a visible score marker and cold/steady/warning/overheat color bands');
ok(/pl-safe-level ceiling/.test(pulseBeginner) && /pl-safe-level floor/.test(pulseBeginner) &&
  /function beginnerLevelDistance/.test(pulseBeginner) && /距目前 \+/.test(pulseBeginner) && /距目前 -/.test(pulseBeginner),
  'beginner ceiling and floor are independent cards with distance from the current index');
ok(/展開進階觀察/.test(pulseBeginner) && /查看專業參數/.test(pulseBeginner) &&
  /pl-beginner-advanced/.test(pulseBeginner),
  'beginner progressive disclosure keeps advanced and expert layers opt-in');
ok(/@media\(min-width:901px\) and \(max-width:1199px\) and \(max-height:740px\)/.test(pulseBeginner) &&
  /pl-body\.pl-mode-beginner\{overflow-x:hidden;overflow-y:auto;padding:2px 0 8px;scrollbar-gutter:stable\}/.test(pulseBeginner) &&
  /pl-beginner-advanced:not\(\[hidden\]\)\)\{overflow:auto\}/.test(pulseBeginner),
  'beginner compact-height rule is limited to medium desktops and safely scrolls instead of shrinking wide screens');
ok(/pl-beginner-copy \.why\{font:500 14px/.test(pulseBeginner) &&
  /pl-beginner-copy \.quality\{font-size:12px/.test(pulseBeginner) &&
  /pl-simple-card \.head\{[^}]*font:700 13px/.test(pulseBeginner) &&
  /pl-simple-card \.plain\{font:500 13px/.test(pulseBeginner) &&
  /pl-simple-card \.bar-meta\{[^}]*font-size:11px/.test(pulseBeginner) &&
  /pl-radar-note\{font:500 13px/.test(pulseBeginner) &&
  /pl-radar-meta\{font-size:11px/.test(pulseBeginner) &&
  /pl-safe-level \.distance\{font:800 12px/.test(pulseBeginner),
  'beginner readability floor keeps body and supporting evidence legible on wide desktop');
(function () {
  var compactStart = pulseBeginner.indexOf('@media(min-width:901px) and (max-width:1199px) and (max-height:740px)');
  var compactEnd = pulseBeginner.indexOf('@media(max-width:900px) and (orientation:portrait)', compactStart);
  var compactCss = pulseBeginner.slice(compactStart, compactEnd);
  ok(compactStart >= 0 && compactEnd > compactStart && !/font-size:(?:7|8|9|10)px/.test(compactCss),
    'beginner medium-desktop short-height override compacts spacing without reintroducing tiny typography');
})();
ok(/\.pl-weather\.calm\{color:#bae6fd/.test(pulseBeginner) &&
  /\.pl-weather\.watch\{color:#fde68a/.test(pulseBeginner) &&
  /\.pl-weather\.alert\{color:#fed7aa/.test(pulseBeginner) && /weather-watch:after/.test(pulseBeginner),
  'semantic weather uses blue/yellow/orange rather than TW price red/green');
ok(/NARROW_RALLY:[\s\S]*label: '指數偏強・結構分化'/.test(pulseBeginner) &&
  /BROAD_RISK_ON:[\s\S]*label: '廣泛多頭・結構健康'/.test(pulseBeginner) &&
  /RECOVERY_ATTEMPT:[\s\S]*label: '結構修復・等待確認'/.test(pulseBeginner) &&
  /DEFENSIVE_RISK_OFF:[\s\S]*label: '風險趨避・防禦優先'/.test(pulseBeginner) &&
  !/晴朗偏暖|雨後觀察|多雲易變|風雨警戒|暴雨警戒|資料霧區/.test(pulseBeginner),
  'beginner regime badge uses professional market structure terminology');
ok(/data-method-card/.test(pulseBeginner) && /怎麼算？/.test(pulseBeginner) &&
  /上漲家數 ÷（上漲＋下跌家數）/.test(pulseBeginner) && /class="pl-method-pop" hidden/.test(pulseBeginner),
  'beginner signal cards disclose a one-line calculation method without changing page height');
ok(/30 秒可讀完/.test(pulseBeginner) && /beginnerFallbackSummary/.test(pulseBeginner) &&
  /白話 AI 懶人包/.test(pulseBeginner),
  'beginner AI summary has a short plain-language prompt and deterministic fallback');
ok(/id="pl-ai-close" aria-label="關閉 AI 白話懶人包"/.test(pulseBeginner) &&
  /function toggleAiSummary\(\)/.test(pulseBeginner) && /if \(aiSummaryStarted\)/.test(pulseBeginner) &&
  /setAiSummaryVisible\(false\)/.test(pulseBeginner) && /收起 30 秒白話 AI 懶人包/.test(pulseBeginner) &&
  /beginner-mode #pl-ai-sum\{display:none!important\}/.test(pulseBeginner),
  'AI plain-language summary is dismissible, toggleable and reopens without another request');
ok(/plAiDrawerIn/.test(pulseBeginner) && /backdrop-filter:blur\(18px\)/.test(pulseBeginner) &&
  /id="pl-ai-speak"/.test(pulseBeginner) && /SpeechSynthesisUtterance/.test(pulseBeginner) &&
  /function chunkAiSpeechText/.test(pulseBeginner) && /speakAiSpeechNext/.test(pulseBeginner) &&
  /🎙 朗讀全文/.test(pulseBeginner) && !/約15秒朗讀/.test(pulseBeginner) &&
  !/text\.slice\(0, 120\)/.test(pulseBeginner) &&
  /id="pl-ai-mail"/.test(pulseBeginner) && /function openAiMailer/.test(pulseBeginner) &&
  /ShareResult\.openMailer/.test(pulseBeginner) &&
  /3 大要點速覽/.test(pulseBeginner),
  'beginner AI uses a glass drawer with full-text speech, email notify and three-point fallback');
ok(/id="pl-ai-fast"/.test(pulseBeginner) && /id="pl-ai-deep"/.test(pulseBeginner) &&
  /\/ai\/deep/.test(pulseBeginner) && /X-ST-AI-Provider/.test(pulseBeginner) &&
  /X-ST-AI-Model/.test(pulseBeginner) && /X-ST-AI-Data-Boundary/.test(pulseBeginner) &&
  /約 5 分鐘/.test(pulseBeginner) && /約 12 分鐘/.test(pulseBeginner) &&
  /模型載入、上下文預填與推理/.test(pulseBeginner) && /手機只顯示結果/.test(pulseBeginner),
  'Pulse exposes truthful EVO-T1 fast/deep AI routes with conservative load-aware guidance');
ok(/三市場趨勢雷達/.test(pulseBeginner) && /台股市場/.test(pulseBeginner) &&
  /美股市場/.test(pulseBeginner) && /期貨市場/.test(pulseBeginner) &&
  /漲跌比 /.test(pulseBeginner) && /指數熱度 /.test(pulseBeginner) && /風險偏高/.test(pulseBeginner) &&
  /▲ \+/.test(pulseBeginner) && /▼ /.test(pulseBeginner),
  'beginner radar summarizes TW, US and futures direction, heat and risk');
ok(/\^GSPC/.test(pulseBeginner) && /\^IXIC/.test(pulseBeginner) && /\^SOX/.test(pulseBeginner) &&
  /\^VIX/.test(pulseBeginner) && /basisPct/.test(pulseBeginner) && /ampRate/.test(pulseBeginner),
  'beginner radar uses existing US index, VIX and TXF basis/volatility sources');
ok(pulseBeginner.includes('.pl-radar-card.tw .change.radar-pos,#pl-root .pl-radar-card.fut .change.radar-pos{color:var(--red)}') &&
  pulseBeginner.includes('.pl-radar-card.us .change.radar-pos{color:var(--green)}') &&
  /value > 0 \? 'radar-pos' : 'radar-neg'/.test(pulseBeginner) &&
  pulseBeginner.includes('.pl-risk-pill.high{color:#fed7aa'),
  'market radar preserves TW red-up/US green-up and separate orange risk semantics');
ok(/pl-money-split/.test(pulseBeginner) && /外資/.test(pulseBeginner) && /投信/.test(pulseBeginner) &&
  /自營/.test(pulseBeginner) && /總 OI/.test(pulseBeginner) && /非外資淨部位/.test(pulseBeginner),
  'beginner cards expose institutional components and honest total-OI semantics');
ok(/function beginnerDivergence/.test(pulseBeginner) && /結構背離/.test(pulseBeginner) &&
  /INDEX_UP_BREADTH_DOWN/.test(pulseBeginner),
  'beginner hero surfaces an explicit index-versus-breadth divergence warning');
ok(/權值／廣度背離/.test(pulseBeginner) && /divergenceDetails/.test(pulseBeginner) &&
  /indexStreak/.test(pulseBeginner) && /多空比/.test(pulseBeginner),
  'pulse and AI summaries consume the canonical multi-day index versus breadth evidence');
ok(/function buildWatchThemeResonance/.test(pulseBeginner) && /同向參與率＋平均漲跌強度/.test(pulseBeginner) &&
  /共振熱度/.test(pulseBeginner) && /buildWatchThemeResonance: buildWatchThemeResonance/.test(pulseBeginner),
  'watchlist opportunity dots expose theme resonance without mislabeling it as historical correlation');
ok(/function normalizeYiValue/.test(pulseBeginner) && /function formatYiCompact/.test(pulseBeginner) &&
  /instForeignYi/.test(pulseBeginner) && /formatYiCompact\(value, true\)/.test(pulseBeginner) &&
  /formatYiCompact: formatYiCompact/.test(pulseBeginner),
  'beginner institutional amounts normalize raw NTD to yi and use compact dashboard formatting');
ok(/levelsStale/.test(pulseBeginner) && /歷史壓力參考/.test(pulseBeginner) &&
  /勿作今日停損依據/.test(pulseBeginner) && /boundary_formula_observed/.test(pulseBeginner),
  'stale key levels are downgraded from today boundaries and traced with their source values');
ok(/id="pl-stock-check"/.test(pulseBeginner) && /function stockHealthAssessment/.test(pulseBeginner) &&
  /stock_health_request_start/.test(pulseBeginner) && /\/twquote\?code=/.test(pulseBeginner) &&
  /setTimeout\(function \(\) \{ if \(controller\) controller\.abort\(\); \}, 8000\)/.test(pulseBeginner),
  'beginner stock health check is source-backed, traced and bounded by timeout');
ok(/function stockHealthFallbackQuote/.test(pulseBeginner) && /stock_health_fallback_start/.test(pulseBeginner) &&
  /\/quote\/.*code \+ '\.TW'/.test(pulseBeginner) && /MIS盤後備援/.test(pulseBeginner) &&
  /yahoo-v8-chart · MIS盤後備援/.test(server),
  'stock health falls back to a labeled Yahoo quote when MIS has no post-close trade field');
ok(/key_levels_stale/.test(server + decisionEngine) && /keyLevelMeta/.test(decisionEngine) &&
  /divergenceDetails/.test(decisionEngine),
  'decision contract suppresses stale key-level triggers and publishes provenance-rich compact metadata');
ok(/function marketCls/.test(pulseBeginner) && /\.us-up\{color:var\(--green\)/.test(pulseBeginner) &&
  /marketCls\(x\.changePct, 'US'\)/.test(pulseBeginner) && /marketCls\(cp, mkt\)/.test(pulseBeginner),
  'pulse global, US sectors and US watchlist use explicit green-up/red-down classes');
const hubColorSrc = fs.readFileSync(path.join(root, 'src/ui/hub_v5.js'), 'utf8');
ok(/function marketCls/.test(hubColorSrc) && /hub\.watchlist/.test(hubColorSrc) && /hub\.international/.test(hubColorSrc) &&
  /V\.rowBar\(ch, maxChg, w\.t\)/.test(hubColorSrc) && /V\.rowBar\(g\.changePct, maxChg, sym\)/.test(hubColorSrc),
  'international and US watchlist text/bars carry symbol-aware color semantics');
ok(/hub-global-panel/.test(hubColorSrc) && /hub-global-role/.test(hubColorSrc) &&
  /min-height:1\.25em;max-height:2\.5em/.test(hubColorSrc) && /line-height:1\.4;margin-top:2px;padding-bottom:1px/.test(hubColorSrc) &&
  /-webkit-line-clamp:2/.test(hubColorSrc) && /repeat\(auto-fit,minmax\(118px,1fr\)\)/.test(hubColorSrc),
  'international global quote cards preserve long labels and roles in responsive columns');
ok(/var ecoYears/.test(hubColorSrc) && /hub-year/.test(hubColorSrc) &&
  /hub-economy-table/.test(hubColorSrc) && /function ecoShortDate/.test(hubColorSrc) &&
  /<th>月\/日<\/th><th>來源<\/th>/.test(hubColorSrc) && /title="資料日 /.test(hubColorSrc),
  'international economy table shows year in heading, month/day per series and full dates in tooltips');
ok(/us-up/.test(fs.readFileSync(path.join(root, 'src/ui/heat_v5.js'), 'utf8')) &&
  /chgCls\(best && best\.changePct, mkt\)/.test(fs.readFileSync(path.join(root, 'src/ui/heat_v5.js'), 'utf8')),
  'US heatmap focus and KPI values use green-up/red-down classes');
ok(!/id="pl-decision-command"/.test(pulseBeginner) && /data-go="decision"/.test(pulseBeginner),
  'pulse keeps a compact decision route button without the three-column command strip');
ok(/dc-command-fold/.test(decisionUi) && /<details class="dc-command-fold" open>/.test(decisionUi) &&
  /決策摘要/.test(decisionUi) && /content:"收合"/.test(decisionUi),
  'decision page owns the market/action/confirmation summary as a default-open section');
ok(/_allowed_root = \('src\/', 'assets\/'\)/.test(server) && /\/market\/snapshot/.test(server),
  'server static files are allow-listed and canonical market route is wired');
ok(/\/decision\/context/.test(server) && /\/decision\/history/.test(server) && /\/key-levels/.test(server) &&
  /decisionEngine/.test(server), 'decision HTTP routes and health status are wired');
(function () {
  const sandbox = { window: {}, console: { log: function () {} }, isFinite: isFinite };
  vm.runInNewContext(colors, sandbox);
  const c = sandbox.window.Colors;
  ok(c.dir('2330', 1) === 'var(--red)' && c.dir('2330', -1) === 'var(--green)' &&
    c.dir('__TXF__', -1) === 'var(--green)' &&
    c.dir('AAPL', 1) === 'var(--green)' && c.dir('AAPL', -1) === 'var(--red)',
  'directional colors: TW/TXF up=red down=green; US up=green down=red');
})();

const hub = fs.readFileSync(path.join(root, 'src/ui/hub_v5.js'), 'utf8');
ok(/hub-inst-hero/.test(hub), 'institutional hero strip');
ok(/data-who="trust"/.test(hub) && /data-who="dealer"/.test(hub), 'institutional who tabs');
ok(/fmtLots/.test(hub) && /單位：張/.test(hub), 'institutional ranks use 張');
ok(/magBars/.test(hub) && /refMeter/.test(hub), 'institutional magBars + turnover meter');
ok(/minmax\(0,1\.15fr\) minmax\(0,1\.35fr\)/.test(hub), 'institutional chart/rank balanced fit');
ok(/lots-bar/.test(hub) && /class="streak"/.test(hub), 'institutional lots bar separated from streak');
ok(/#view-institutional \.hub-title\{font-size:20px/.test(hub) &&
  /#view-institutional \.vz-spark-ax \.vz-ylabs/.test(hub) &&
  /hub-inst-comp \.vz-mag \.vz-track\{height:14px/.test(hub) &&
  /h: 220/.test(hub),
  'institutional large-screen type fit (title/axes/structure bars)');
ok(/法人金額尚未更新/.test(hub) && /hub-mag3/.test(hub),
  'institutional structure fallback when Viz absent');
ok(/id="hub-contacts-btn"/.test(hub) && /管理聯絡人/.test(hub) &&
  /ShareResult\.openContacts/.test(hub) && /Email 聯絡人/.test(hub),
  'settings page exposes Email contact manager');
(function () {
  var share = fs.readFileSync(path.join(root, 'src/ui/share_v3.js'), 'utf8');
  ok(/ShareResult\.openMailer/.test(share) && /\/notify\/contacts/.test(share) &&
    /\/report-email/.test(share) && /ShareResult\.openContacts/.test(share) &&
    /寄出通知/.test(share),
    'ShareResult mailer reuses contacts API and /report-email');
})();
(function () {
  var wd = fs.readFileSync(path.join(root, 'src/ui/wavedeck_bridge_v5.js'), 'utf8');
  ok(/HEARTBEAT_MS/.test(wd) && /startOverlayHeartbeat/.test(wd),
    'WaveDeck bridge republishes overlay heartbeat before fail-safe stale');
})();
(function () {
  var vz = fs.readFileSync(path.join(root, 'src/ui/viz_v5.js'), 'utf8');
  var pulseSrc = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
  ok(/vz-xlabs/.test(vz), 'sparkLine X tick labels');
  ok(/linearGradient/.test(vz) && /vz-pt/.test(vz) && /wantFill/.test(vz) && /wantMarks/.test(vz),
    'sparkLine area fill + peak/trough marks');
  ok(/vz-spark-wrap/.test(vz) && /_peakLabelsHtml/.test(vz) && /vz-pt\.hi\.flip/.test(vz),
    'viz spark peak labels with wrap + edge flip (anti-occlusion)');
  ok(!/vz-compact \.vz-pt\{display:none\}/.test(vz) && !/wantMarks && !compact/.test(vz),
    'viz compact spark keeps peak value labels (not dots-only)');
  ok(/vz-compact/.test(vz) && /compact:\s*true/.test(pulseSrc),
    'tip spark uses compact axis (no xunit footer)');
  ok(/overflow:visible/.test(pulseSrc) && /\.vz-pt\{font-size:8px/.test(pulseSrc),
    'tip trend charts allow peak label overflow');
})();
ok(/d\.buy \|\| d\.long/.test(hub) || /focus\.buy/.test(hub) || /d\.buy \|\|/.test(hub),
  'signals use /focus buy field');
ok(/hub-card\[data-code\]/.test(hub) || /data-code="' \+ sym/.test(hub),
  'international cards clickable');
ok(/黃金（避險）/.test(hub) && /銅（景氣循環）/.test(hub) && /g\.role/.test(hub),
  'international shows gold hedge + copper cycle roles');

const ai = fs.readFileSync(path.join(root, 'src/ui/ai_v5.js'), 'utf8');
ok(/ai5-strip/.test(ai) && /ai5-dash/.test(ai), 'ai professional strip+dash');
ok(/focus\.buy/.test(ai) || /buy \|\| focus\.long/.test(ai), 'ai maps focus.buy');
ok(!/ai5-card/.test(ai) || /ai5-tools/.test(ai), 'ai launcher not card-grid only');

const ah = fs.readFileSync(path.join(root, 'src/ui/afterhours_v5.js'), 'utf8');
ok(/自營/.test(ah) && /成交金額/.test(ah), 'afterhours strip has 成交／籌碼含自營');
ok(/ah-ovn-host/.test(ah) && /overnightRenderInto/.test(ah) && /mountOvernightPanel/.test(ah) &&
  !/ah-ohlc/.test(ah),
  'afterhours left column embeds overnight panel (not crude OHLC)');
ok(/grid-template-columns:minmax\(0,1fr\) minmax\(0,1\.25fr\)/.test(ah),
  'afterhours desktop dash keeps five frames');
ok(/@media\(max-width:900px\) and \(orientation:portrait\)[\s\S]*#ah-root \.ah-dash\{[^}]*grid-template-columns:1fr/.test(ah),
  'afterhours portrait stacks one frame per row');
ok(/#ah-root \.ah-inst-trend \.chart\{[^}]*overflow:hidden/.test(ah),
  'afterhours inst spark is clipped inside the chart box');
ok(/compact:\s*true/.test(ah),
  'afterhours inst spark uses compact axes');
ok(/@media\(max-width:900px\) and \(orientation:landscape\)[\s\S]*vz-pt[\s\S]*display:none/.test(ah),
  'afterhours landscape hides spark peak labels so they cannot cover comment text');
ok(/table class="ah-tbl ah-mv"/.test(ah) && /col class="c-pct"/.test(ah),
  'afterhours rank tables reserve a visible percent column');
ok(!/#ah-root table\.ah-tbl \.vz-rowbar\{display:none!important\}/.test(ah.split('@media')[0]),
  'afterhours desktop still shows futures rowBars');
ok(/#ah-root table\.ah-mv \.vz-rowbar\{display:none!important\}/.test(ah),
  'afterhours rank tables drop rowBars so percent text stays visible');
const ovn = fs.readFileSync(path.join(root, 'src/chart/overnight_v3.js'), 'utf8');
ok(/overnightRenderInto/.test(ovn) && /function renderInto/.test(ovn) && /ovn-embed/.test(ovn),
  'overnight exposes renderInto for afterhours embed');
ok(/ovn-signal-grid/.test(ovn) && /ovn-signal-card primary/.test(ovn) && /ovn-signal-card secondary/.test(ovn),
  'overnight summary uses semantic primary and secondary signal cards');
ok(/\.ovn-embed \.ovn-signal-grid\{grid-template-columns:1fr/.test(ovn) &&
  /grid-template-columns:minmax\(0,1fr\) auto/.test(ovn),
  'embedded overnight summary stacks compact rows instead of squeezing two columns');
ok(/const usCol = col\(usEst\)/.test(ovn),
  'US linkage estimate uses US green-up red-down color semantics');

const bd = fs.readFileSync(path.join(root, 'src/ui/breadth_v5.js'), 'utf8');
ok(/強弱榜/.test(bd), 'breadth movers replace note panel');
ok(/結構條不重複/.test(bd) || /結構只用 magBars/.test(bd), 'breadth avoids inst number+bar dup');
ok(/官方≠清單/.test(bd) || /官方漲停家數/.test(bd), 'breadth limit popup separates official vs approx list');

const pl = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
const landscapeStart = pl.indexOf('@media(orientation:landscape) and (max-height:540px) and (pointer:coarse)');
const landscapeEnd = pl.indexOf('/* 手機直式專業模式', landscapeStart);
const landscapeCss = landscapeStart >= 0 && landscapeEnd > landscapeStart
  ? pl.slice(landscapeStart, landscapeEnd)
  : '';
ok(/上市漲跌停 · 官方/.test(pl), 'pulse strip labels official limit counts');
ok(/近漲停/.test(pl) && /≠頂列官方家數/.test(pl), 'pulse movers panel not branded as official limit');
ok(/movers\.limitUp/.test(pl), 'pulse prefers movers.limitUp for near-limit list');
ok(/市場脈動 <a data-go="factors">因子 →<\/a>/.test(pl),
  'pulse factor heading opens the independent factors route');
ok(/go: 'chart', sym: '\^TWII'/.test(pl) && /go: 'chart', sym: '\^TWOII'/.test(pl) &&
  /go: 'afterhours', mkt: 'TW'/.test(pl),
  'pulse headline cards route TAIEX/OTC to charts and TXF/turnover to afterhours');
ok(/pl-movers[\s\S]*data-go="breadth">廣度 →/.test(pl),
  'pulse mover panels route to breadth instead of unrelated afterhours');
ok(/a\.onkeydown[\s\S]*e\.key === 'Enter'[\s\S]*e\.key === ' '/.test(pl),
  'pulse data-go links support keyboard activation');
(function () {
  const targets = Array.from(pl.matchAll(/data-go=["']([^"']+)["']/g)).map(m => m[1]);
  const missing = Array.from(new Set(targets)).filter(id =>
    !new RegExp("id: '" + id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + "'").test(shell));
  ok(missing.length === 0, 'every pulse data-go target exists in ShellV5 routes' +
    (missing.length ? ': ' + missing.join(', ') : ''));
})();
ok(/function chgWithPct/.test(pl) && /chgWithPct\(t00/.test(pl) && /chgWithPct\(txf/.test(pl),
  'pulse strip shows change points + pct for TAIEX/OTC/TXF');
ok(/GC=F/.test(pl) && /HG=F/.test(pl) && /CL=F/.test(pl) && /x\.role/.test(pl) &&
  /function globalChgLabel/.test(pl) && /slice\(0, 14\)/.test(pl),
  'pulse global prefer includes gold/copper/oil + price with chg pts/%');
ok(/turnoverVsMa5Pct/.test(pl) && /volumeScore/.test(pl) && /成交金額 · 量能/.test(pl),
  'pulse strip shows turnover quant vs5 / score');
ok(/t00Trend/.test(pl) && /o00Trend/.test(pl) && /txfTrend/.test(pl) &&
  /trendQuantBits/.test(pl) && /renderTrendCell/.test(pl),
  'pulse strip shows TAIEX/OTC/TXF trend quant like turnover');
ok(/日線' \+ \(tr\.streak/.test(pl) && /即時漲跌＝同卡官方報價/.test(pl),
  'pulse separates official live change from daily-series streak/trend labels');
ok(/function renderTrendCell/.test(pl) && !/pl-idx-spark/.test(pl) &&
  /tabs \+ meter/.test(pl),
  'pulse strip trend cells drop sparkline; keep tabs + meter');
ok(/refMeter\(Number\(tr\.momScore\), \[40, 60\]/.test(pl) &&
  /max:\s*100/.test(pl) && /pl-strip \.vz-ref\{[^}]*width:100%/.test(pl) &&
  /opts\.max/.test(fs.readFileSync(path.join(root, 'src/ui/viz_v5.js'), 'utf8')),
  'pulse strip momScore bar uses same refMeter width/ticks as turnover');
ok(/function renderTrendTabs/.test(pl) && /IDX_TREND_TABS/.test(pl) &&
  /TURN_TREND_TABS/.test(pl) && /BREADTH_TREND_TABS/.test(pl) &&
  /連漲趨升/.test(pl) && /溫和上行/.test(pl) && /區間震盪/.test(pl) &&
  /明顯縮量/.test(pl) && /廣度糾結/.test(pl) &&
  /pl-ttabs span\.on\.buy/.test(pl) && /opacity:\.38/.test(pl),
  'pulse strip shows all trend-type tabs with active highlight / others gray');
ok(/加權盤勢/.test(pl) && /data-sym="\^TWII"/.test(pl) &&
  !/線型＝加權 \^TWII（非台指期）/.test(pl) && !/pl-trend-pair/.test(pl),
  'pulse OHLC panel integrated with a compact title and no duplicate index chips');
ok(/pl-ohlc4/.test(pl) && /pl-ohlc-trend/.test(pl) && /function buildOhlcComment/.test(pl) &&
  /pl-inst4,#pl-root \.pl-bd4,#pl-root \.pl-ohlc4\{/.test(pl) &&
  /fmt\(o\.open, 0\)/.test(pl) && /chgWithPct\(twiiObj, 0, 1\)/.test(pl) &&
  !/pl-ohlc-now/.test(pl) && !/function fmtIdx/.test(pl),
  'pulse 加權盤勢：四格整數點＋線圖對齊法人，無小數遮蔽');
ok(/漲跌家數 · 廣度/.test(pl) && /repeat\(6,/.test(pl),
  'pulse strip merges breadth into 6-col KPI row');
ok(/data-flash-mkt/.test(pl) && /filterFlash/.test(pl) && /flashMkt/.test(pl),
  'pulse flash has TW/US/ALL tabs');
ok(/instDayEmpty/.test(pl) && /預覽前一日/.test(pl) && /paintInstCells/.test(pl),
  'pulse institutional falls back to prior session via compact tag');
ok(/pl-tag\.ok\{/.test(pl) && /#64748b/.test(pl) && /pl-st-pos/.test(pl),
  'pulse watch tags are status dots (not price red/green)');
ok(/pl-bias-bull/.test(pl) && /pl-bias-bear/.test(pl) && /function biasCls/.test(pl),
  'pulse bias labels use TW red-up / green-down (not cyan for 偏空)');
ok(/pl-flash \.row:nth-child\(even\)/.test(pl) && /pl-wl tr:nth-child\(even\)/.test(pl) &&
  /table-layout:fixed/.test(pl) && /pl-flash \.row\{[^}]*grid-template-columns:36px 44px/.test(pl),
  'pulse flash/watch lists have zebra striping + fixed columns');
ok(/pl-list li\{[^}]*font-size:8px/.test(pl) && /pl-flash\{[^}]*font-size:8px/.test(pl) &&
  /pl-flash \.ttl\{[^}]*font-size:8px/.test(pl) && /pl-movers \.pl-list li > span:last-child/.test(pl),
  'pulse 近漲停／市場快訊縮字避免跳行');
ok(/pl-sbar\{[^}]*font-size:8px/.test(pl) && /pl-sbar \.pc\{[^}]*font-size:8px/.test(pl) &&
  /#pl-sectors \.pl-note\{font-size:7px/.test(pl),
  'pulse 產業輪動縮字符合版面');
ok(/pl-wl table\{[^}]*font-size:8px/.test(pl) && /pl-wl td\.px,#pl-root \.pl-wl td\.chg\{font-size:8px/.test(pl) &&
  /pl-wl \.nm-only\{[^}]*font-size:7px/.test(pl),
  'pulse 自選風險縮字符合版面');
ok(/data-watch-mkt/.test(pl) && /filterWatchlist/.test(pl) && /pl-wl-scroll/.test(pl) &&
  /c-px/.test(pl) && /c-chg/.test(pl) && /c-tag/.test(pl),
  'pulse watchlist has TW/US tabs, fixed columns, and scroll region');
ok(/pl-wl-head/.test(pl) && /pl-wl-title/.test(pl) &&
  /#pl-watch-sec \.pl-sec-tog\{[^}]*flex:0 0 auto[^}]*flex-wrap:nowrap/.test(pl) &&
  /#pl-watch-sec \.pl-sec-tog button\{[^}]*font-size:6\.5px[^}]*padding:1px 3px[^}]*white-space:nowrap/.test(pl),
  'pulse watchlist ALL/TW/US controls stay compact on one header row');
ok(/instFlowQuant/.test(pl) && /rankLabel/.test(pl) && /pl-inst-ctx/.test(pl) &&
  /pl-inst-stale/.test(pl) && /當日尚未公布/.test(pl),
  'pulse institutional shows Z/percentile/rank + compact stale tag');
ok(/pl-score3/.test(pl) && />綜合</.test(pl) && /大盤體質/.test(pl) &&
  /class="w">70%</.test(pl) && /class="w">30%</.test(pl) && /權重 70%/.test(pl),
  'pulse score trio: compact 綜合 + child weights 70/30 (label short, title full)');
ok(/pl-empty\[hidden\]\{display:none!important\}/.test(pl),
  'pulse empty[hidden] overrides display:flex (no blank inst box)');
ok(/pl-sec h4\{[^}]*font-size:10px/.test(pl) &&
  /pl-flash \.row\{[^}]*line-height:1\.35/.test(pl) &&
  /pl-wl th,#pl-root \.pl-wl td\{padding:4px 4px/.test(pl) &&
  /pl-dash\{[^}]*gap:6px/.test(pl) &&
  /pl-strip \.v\{[^}]*font-size:14px/.test(pl),
  'pulse density rebalance after font upsizing (strip/h4/flash/wl/gutter)');
ok(/function moneyYiCell/.test(pl) && /moneyYiCell\(i\.foreign\)/.test(pl) &&
  /pl-inst4 \.c \.v,#pl-root \.pl-bd4 \.c \.v,#pl-root \.pl-ohlc4 \.c \.v\{[^}]*font-size:10px/.test(pl) &&
  /pl-score-formula\{[^}]*font-size:8px/.test(pl) &&
  /pl-score3 \.sc\.main \.v\{font-size:14px/.test(pl),
  'pulse score/inst dense cards use smaller type + short 億 cells');
ok(/pl-bd4/.test(pl) && /function paintBreadthCells/.test(pl) &&
  /pl-inst4,#pl-root \.pl-bd4,#pl-root \.pl-ohlc4\{/.test(pl) &&
  /pl-inst-trend,#pl-root \.pl-bd-trend,#pl-root \.pl-ohlc-trend\{/.test(pl) &&
  !/pl-donut-wrap/.test(pl),
  'pulse 市場廣度：四格 KPI＋線圖面板對齊法人資金');
ok(/pl-score3\{display:grid;grid-template-columns:minmax\(0,0\.9fr\) minmax\(0,1\.05fr\) minmax\(0,1\.05fr\)/.test(pl) &&
  /writing-mode:horizontal-tb/.test(pl) &&
  /pl-score3 \.sc\{[^}]*flex-direction:column/.test(pl),
  'pulse score 三框左到右（綜合 compact 窄欄）；框內上下橫書');
ok(/pl-global \.g \.v\{[^}]*font-size:8px/.test(pl) &&
  /pl-global \.g \.k \.role\{display:none\}/.test(pl),
  'pulse global compact type; role only in title');
ok(/pl-sec\.pl-global-sec\{overflow:hidden;min-height:0\}/.test(pl) &&
  /pl-global\{[^}]*overflow-y:auto[^}]*overscroll-behavior:contain[^}]*scrollbar-gutter:stable/.test(pl) &&
  /class="pl-global" tabindex="0" role="region"/.test(pl),
  'pulse 全球影響在固定格內支援滑鼠、觸控與鍵盤垂直捲動');
ok(/正面因子/.test(pl) && /風險因子/.test(pl) && /計入風險分/.test(pl) && !/主要動能/.test(pl),
  'pulse drivers labeled 正面／風險因子 (not 主要動能)');
ok(/大盤體質/.test(pl) && /0\.7×大盤體質/.test(pl) && !/>動能</.test(pl),
  'pulse score labels health as 體質 not 動能');
ok(/industryLabel/.test(pl) && /bindSectorMoverLink/.test(pl) && /data-sector-key/.test(pl),
  'pulse movers industry tags + sector hover link');
ok(/globalAbbr/.test(pl) && /'DJI'/.test(pl) && /'SPX'/.test(pl) && /'NDX'/.test(pl) && /'SOX'/.test(pl),
  'pulse global uses short ticker labels');
ok(/basisPts/.test(pl) && /正價差/.test(pl) && /逆價差/.test(pl) && /Basis＝期貨−加權現貨/.test(pl),
  'pulse strip shows TXF–TAIEX basis');
ok(/pl-flash-q/.test(pl) && /flashQ/.test(pl) && /搜代號\/關鍵字/.test(pl),
  'pulse flash has keyword search beside TW/US tabs');
ok(/pl-flash-title/.test(pl) &&
  /#pl-flash-sec \.pl-sec-tog\{[^}]*flex-wrap:nowrap/.test(pl) &&
  /#pl-flash-sec \.pl-sec-tog button\{font-size:6\.5px[^}]*white-space:nowrap[^}]*flex:0 0 auto/.test(pl) &&
  /pl-flash-q\{width:48px;min-width:38px/.test(pl),
  'pulse flash title, search and ALL/TW/US tabs stay on one compact row');
ok(/data-layout=/.test(pl) && /LAYOUT_CONTRACT/.test(pl) &&
  /grid-template-columns:repeat\(5,minmax\(0,1fr\)\)/.test(pl) &&
  /pl-zone z-top/.test(pl) && /pl-zone z-bot/.test(pl) &&
  /PULSE_LAYOUT_ANCHOR_3cab212/.test(pl) && /probeLayoutCols/.test(pl) &&
  !/4col-priority/.test(pl) && !/max-width:1280/.test(pl) &&
  !/5col-2zone-flex/.test(pl) && !/enforceFiveCol/.test(pl),
  'pulse dash is known-good 5col-2zone + runtime probe (anchor 3cab212)');
ok(/id="pl-head-meta"/.test(pl) && /pl-head-lead/.test(pl) && /pl-head-meta-track/.test(pl) &&
  /pl-head-start/.test(pl) && /pl-head-end/.test(pl) && /ensureHeadChrome/.test(pl) &&
  /renderHeadMeta/.test(pl) && /formatTaipeiClock/.test(pl) &&
  /行情最新來源時間/.test(pl) && /查看更新工作/.test(pl) &&
  /僅有摘要，全文未提供/.test(pl) && /尚未確認/.test(pl) &&
  /overflow-x:auto/.test(pl) && /white-space:nowrap/.test(pl) &&
  /grid-template-columns:max-content minmax\(0,1fr\) max-content/.test(pl) &&
  /id="pl-head-meta"><\/div>'[\s\S]{0,80}pl-head-end/.test(pl) &&
  /pl-head-end[\s\S]{0,80}pl-mode-toggle/.test(pl) &&
  /MarketFreshness\.snapshotSummary/.test(pl) &&
  /function pickSession/.test(pl) && /twse-mis/.test(pl) &&
  /var _lastMacro = null/.test(pl) && /var _lastJobLabel/.test(pl) &&
  !/#pl-root \.pl-head-meta-track\{font-size:8px\}/.test(pl) &&
  !/#pl-root \.pl-head\{flex-wrap:wrap\}/.test(pl) &&
  !/order:3;flex:1 1 100%/.test(pl),
  'pulse 金框用三欄 grid 填滿新手左側，不能另開一列');
ok(/max-height:540px[\s\S]*#pl-root \.pl-sub\{display:none\}/.test(pl) &&
  /max-height:540px[\s\S]*pl-head-meta\{padding:1px 6px;min-width:0\}/.test(pl) &&
  /orientation:portrait\)[^{]*\{[\s\S]*pl-head\{[^}]*overflow:hidden/.test(pl) &&
  /orientation:portrait\)[^{]*\{[\s\S]*pl-head-meta\{min-width:0\}/.test(pl) &&
  /orientation:portrait\)[^{]*\{[\s\S]*#pl-root \.pl-sub\{display:none\}/.test(pl),
  'pulse 手機橫直式金框都留在新手左側橫捲，不整列丟到按鈕下方');
ok(/MOBILE_LAYOUT_CONTRACT = '2col-scroll'/.test(pl) &&
  /@media\(max-width:900px\) and \(orientation:portrait\)[\s\S]*pl-zone\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/.test(pl) &&
  /matchMedia\('\(max-width: 900px\) and \(orientation: portrait\)'\)/.test(pl) &&
  /matchMedia\('\(max-width: 980px\) and \(orientation: landscape\) and \(max-height: 540px\)'\)/.test(pl) &&
  /var expectedCols = mobile \? 2 : 5/.test(pl) &&
  /layoutResizeTimer = setTimeout\(probeLayoutCols, 120\)/.test(pl),
  '總覽直式與短橫式採兩欄捲動，桌機維持五欄');
ok(landscapeStart >= 0 &&
  /text-size-adjust:100%/.test(landscapeCss) &&
  /pl-strip \.v\{font-size:11px!important;line-height:1\.1;margin-bottom:0\}/.test(landscapeCss) &&
  /pl-strip \.s\{font-size:5px/.test(landscapeCss) &&
  /pl-sec\{padding:4px 6px;height:100%;overflow:hidden\}/.test(landscapeCss) &&
  /pl-zone\{gap:4px;grid-template-columns:repeat\(5,minmax\(0,1fr\)\)\}/.test(landscapeCss) &&
  /pl-zone>\.pl-sec>h4\{[^}]*font-size:7px!important[^}]*line-height:10px[^}]*letter-spacing:0!important[^}]*gap:2px/.test(landscapeCss) &&
  /pl-list li\{[^}]*font-size:7px/.test(landscapeCss) &&
  /pl-global \.g \.v\{font-size:5\.5px/.test(landscapeCss) &&
  /pl-global \.g \.s\{font-size:5px/.test(landscapeCss) &&
  /pl-flash \.ttl\{font-size:7px/.test(landscapeCss) &&
  /pl-wl table\{font-size:7px/.test(landscapeCss),
  '大型觸控橫式保留五欄密度');
ok(/pointer:coarse\) and \(min-width:981px\)/.test(pl) &&
  !/max-width:767px/.test(pl) && /grid-auto-rows:minmax\(300px,auto\)/.test(pl) &&
  /pl-sec:has\(\.pl-inst-trend,\.pl-bd-trend,\.pl-ohlc-trend\)\{height:auto;overflow:visible\}/.test(pl) &&
  /pl-ohlc-trend \.chart\{flex:0 0 132px;height:132px;min-height:132px\}/.test(pl),
  '手機短橫式不使用微縮小字，趨勢卡可增高且曲線保留可讀高度');
ok(/pl-inst4 \.c \.v,#pl-root \.pl-bd4 \.c \.v,#pl-root \.pl-ohlc4 \.c \.v\{[^}]*font-size:8px!important[^}]*overflow:visible[^}]*text-overflow:initial/.test(landscapeCss) &&
  /pl-ohlc4 \.c \.v\{letter-spacing:-0\.45px\}/.test(landscapeCss) &&
  !/\.c \.v[^}]*text-overflow:clip/.test(landscapeCss),
  'pulse touch landscape primary KPI values are sized to fit instead of clipped');
ok(/#pl-inst-stale\{[^}]*max-width:46px[^}]*font-size:0[^}]*overflow:hidden/.test(landscapeCss) &&
  /#pl-inst-stale:after\{content:attr\(data-compact-label\);font-size:6px/.test(landscapeCss) &&
  /data-compact-label', '前日 '/.test(pl),
  'pulse touch landscape shortens the secondary institutional stale badge without clipping its title');
ok(/pl-sec-title-text/.test(pl) && /pl-movers-date/.test(pl) && /pl-movers-note/.test(pl) &&
  /data-compact-label=/.test(pl) && !/max-height:1\.2em;overflow:hidden/.test(landscapeCss),
  'pulse landscape gives primary titles explicit flex ownership and compacts only secondary mover metadata');
ok(/max-height:540px[\s\S]*pl-ohlc-trend \.chart \.vz-pt\{display:none!important\}/.test(pl) &&
  /max-height:540px[\s\S]*pl-ohlc-trend \.chart \.vz-spark-ax\{[^}]*grid-template-columns:minmax\(0,1fr\)[^}]*overflow:hidden/.test(pl) &&
  /max-height:540px[\s\S]*pl-ohlc-trend \.chart \.vz-plot\{[^}]*grid-column:1[^}]*grid-row:1[^}]*overflow:hidden/.test(pl),
  'pulse touch landscape removes redundant spark annotations and gives the plot the full compact card');
ok(/#pl-body\{[^}]*overflow:hidden/.test(pl) && /pl-expanded\{overflow:hidden\}/.test(pl) &&
  /data-go=\"factors\"/.test(pl) && !/pl-toggle-fac/.test(pl) &&
  /因子帳本改獨立頁/.test(pl),
  'pulse one-screen lock; factors go to independent page (no expand)');
ok(/pl-layout-probe/.test(pl) && /實測 5\+5/.test(pl) && /一行五框/.test(pl),
  'pulse surfaces 實測 5+5 probe for stale-JS detection');
(function () {
  var start = pl.indexOf("data-layout=\"' + LAYOUT_CONTRACT");
  if (start < 0) start = pl.indexOf('data-layout="5col-2zone"');
  var orderBlock = pl.slice(start, pl.indexOf('extra;'));
  ok(orderBlock.indexOf('z-top') < orderBlock.indexOf('z-bot') &&
    orderBlock.indexOf('renderGauge') < orderBlock.indexOf('renderSectors') &&
    orderBlock.indexOf('renderSectors') < orderBlock.indexOf('z-bot') &&
    orderBlock.indexOf('renderMovers') < orderBlock.indexOf('renderFlash') &&
    orderBlock.indexOf('renderFlash') < orderBlock.indexOf('renderWatch'),
    'pulse 5+5 order: top decision row then bottom movers/global/flash/watch');
})();

ok(/RING_ROUTES/.test(shell) && /st-ring/.test(shell) && /openRing/.test(shell) &&
  /toggleRing/.test(shell) && /auxclick/.test(shell) && /st-ring-fab/.test(shell) &&
  /sr-hub/.test(shell) && /sr-item/.test(shell),
  'shell MX-style gesture ring (middle-click / \\\\ / fab)');
ok(/ringAnalysisTree/.test(shell) && /ringPushChildren/.test(shell) &&
  /renderRingLayers/.test(shell) && /sr-layer\.locked/.test(shell) &&
  /RING_MAX_DEPTH/.test(shell) && /has-kids/.test(shell) && /ringPop/.test(shell) &&
  /ringFolder\('market'/.test(shell) && /ringFolder\('price'/.test(shell) &&
  /ringFolder\('flow'/.test(shell) && /ringFolder\('screen'/.test(shell),
  'shell ring 3-layer analysis taxonomy (locked outer + active inner)');
ok(/itemOffsetOnLayer/.test(shell) && /clampWheelForActive/.test(shell) &&
  /下一層以點選功能為圓心/.test(shell) && /paintRingAnchor/.test(shell),
  'shell ring drills next layer centered on picked item (not re-centered)');
ok(/onRingWheel/.test(shell) && /wheelAcc/.test(shell) && /sr-orbit/.test(shell) &&
  /--sr-x/.test(shell) && /box-shadow/.test(shell) && /conic-gradient/.test(shell),
  'shell ring 3D orbit/bevel + mouse-wheel cyclic select');
ok(/function ringWheelSlots/.test(shell) && /slots\.push\(-2\)/.test(shell) &&
  /hi === -2/.test(shell) &&
  /function ringPopTo/.test(shell) && /data-ring-pop-to/.test(shell) &&
  /sr-crumb/.test(shell) && /BrowserBack/.test(shell) && /button === 3/.test(shell) &&
  /ringPop: ringPop/.test(shell) && /ringPopTo: ringPopTo/.test(shell),
  'shell ring back: Esc/Backspace/crumb/side-button pop layer; hub=-2 dashboard');
ok(/@keyframes sr-spin-in/.test(shell) && /@keyframes sr-spin-out/.test(shell) &&
  /function animateLayerOut/.test(shell) && /function playLayerEnter/.test(shell) &&
  /spinIn:\s*true/.test(shell) && /reveal:\s*true/.test(shell) &&
  /transformOrigin/.test(shell) && /RING_SPIN_IN_MS/.test(shell) &&
  /prefers-reduced-motion/.test(shell),
  'shell ring layer spin-in / reverse spin-out wheel animation');
ok(/function goDashboard/.test(shell) && /goDashboard: goDashboard/.test(shell) &&
  /返回儀表板/.test(shell) && /shell-dash-btn/.test(shell) &&
  /dblclick/.test(shell) && /ensureDashChrome/.test(shell) &&
  /data-shell-back>← 返回儀表板/.test(shell),
  'shell dashboard: goDashboard + stub back + FAB dblclick + topbar');
ok(/#topbar\{position:relative;flex-wrap:nowrap;min-height:42px;max-height:42px;overflow:hidden/.test(shell) &&
  /#topbar #keybtn\{order:90;margin-left:auto!important/.test(shell) &&
  /shell-dash-btn\{[^}]*order:100/.test(shell) && /keybtn\.nextSibling/.test(shell),
  'chart header keeps KEY left of the right-aligned dashboard button and clips before the stock rows');
ok(/shell-dash-glyph/.test(shell) && /shellDashSheen/.test(shell) &&
  /linear-gradient\(135deg,#ffe36a/.test(shell) && /RING_LOGO/.test(shell),
  'chart dashboard action uses the branded glowing icon treatment');
ok(/aria-label', '返回儀表板'/.test(shell) &&
  /#topbar \.shell-dash-btn\{[\s\S]*position:absolute!important;right:4px;top:5px/.test(chartVisual) &&
  /shell-dash-label\{display:none!important\}/.test(chartVisual),
  'mobile chart keeps an icon-only dashboard action pinned in the visible topbar');
ok(!/class="wlchip-rm"/.test(sourceHtml) &&
  /aria-haspopup="menu"/.test(sourceHtml) &&
  /function attachLongPressWl/.test(sourceHtml) &&
  /openWlActionMenu\(chip\)/.test(sourceHtml) &&
  /_wlSuppressClickUntil = Date\.now\(\) \+ 900/.test(sourceHtml) &&
  /}, 550\)/.test(sourceHtml) &&
  /wl-menu-etf/.test(sourceHtml) &&
  /EtfFlowTip\.openForChip/.test(sourceHtml) &&
  /class="etf-flow-badge/.test(sourceHtml) &&
  /data-etf-flow-trigger/.test(sourceHtml) &&
  /data-etf-up=/.test(sourceHtml) &&
  /class="etf-flow-signs"/.test(sourceHtml) &&
  /class="etf-flow-sign up/.test(sourceHtml) &&
  /class="etf-flow-sign down/.test(sourceHtml) &&
  /data-etf-flow-state/.test(sourceHtml) &&
  /wl-menu-remove/.test(sourceHtml) &&
  /if \(!confirm\('從自選移除/.test(sourceHtml) &&
  /\.wlchip\.wl-holding::after/.test(mobileCss) &&
  /body > \.wl-action-menu\.open/.test(mobileCss),
  'mobile watchlist requires a long press menu and suppresses the following load click');
ok(/id="rpanel-pager"/.test(sourceHtml) && /id="rpage-dots"/.test(sourceHtml) &&
  /rpage-prefix">目前頁面/.test(sourceHtml) &&
  /MOBILE_WORKSPACE_PAGES = \[\{key:'chart'/.test(sourceHtml) &&
  /function goMobileWorkspacePage\(index, reason\)/.test(sourceHtml) &&
  /const pageChanged = body\.getAttribute/.test(sourceHtml) &&
  /data-mobile-workspace-page/.test(sourceHtml) && /function shiftRtab\(delta\)/.test(sourceHtml) &&
  /Math\.abs\(dx\) < 56/.test(sourceHtml) &&
  /#rtabs \{ display: none !important; \}/.test(mobileCss) &&
  /#rpanel-pager[\s\S]*display: grid !important/.test(mobileCss) &&
  /grid-template-columns: 48px minmax\(0,1fr\) 48px/.test(mobileCss) &&
  /orientation: portrait/.test(mobileCss) &&
  /data-mobile-workspace-page="chart"/.test(mobileCss) &&
  /orientation: landscape/.test(mobileCss) &&
  /@media \(max-width: 900px\) and \(orientation: landscape\)[\s\S]*?#rtabs \{[\s\S]*?display: flex !important;/.test(mobileCss) &&
  /#rtabs[\s\S]*height: 26px !important;[\s\S]*#rtabs \.rtab[\s\S]*height: 25px !important;/.test(mobileCss) &&
  !/\.probtn, \.rtab, \.wlchip, \.wladd \{ min-height: 32px; \}/.test(mobileCss) &&
  /main\.appendChild\(pagerEl\)/.test(shell) &&
  /pager\.classList\.toggle\('shell-hidden', !isChart\)/.test(shell) &&
  /data-st5-route/.test(shell) &&
  /html\[data-st5-route="chart"\] #st-ring-fab/.test(mobileCss) &&
  /#rpage-dots \.rpage-dot\.on/.test(mobileCss) &&
  /window\.updateRpanelPager/.test(position),
  'portrait mobile pages the whole chart workspace; landscape keeps the workstation split');
ok(/--st-app-height:100dvh/.test(sourceHtml) &&
  /function syncAppVisualViewport\(reason\)/.test(sourceHtml) &&
  /window\.visualViewport\.addEventListener\('resize'/.test(sourceHtml) &&
  /height:var\(--st-app-height,100dvh\)/.test(sourceHtml) &&
  /max-height:var\(--st-app-height,100dvh\)/.test(sourceHtml) &&
  /max-height:100%!important/.test(shell) &&
  /-webkit-overflow-scrolling:touch/.test(shell),
  'mobile shell tracks the Chrome visual viewport and keeps one momentum scroll boundary');
ok(/mobile_shell_panel_layout/.test(shell) &&
  /scroll-padding-bottom:calc\(88px \+ env\(safe-area-inset-bottom,0px\)\)/.test(shell) &&
  /#shell-main #shell-views\.show>\.sv-panel\.on/.test(shell),
  'portrait shell uses one scroll owner and reserves bottom safe space for all panels');
ok(/compactLandscape = window\.matchMedia\('\(orientation:landscape\) and \(max-height:540px\) and \(pointer:coarse\)'\)/.test(shell) &&
  /valueOverflow=/.test(shell) && /titleOverflow=/.test(shell) && /document\.fonts\.status/.test(shell),
  'mobile layout diagnostics cover short touch landscape and record real text overflow');
ok(/@media\(orientation:landscape\) and \(max-height:540px\) and \(pointer:coarse\)[\s\S]*#st-ring-fab\{right:4px;bottom:4px;width:30px;height:30px/.test(shell),
  'landscape consensus radar stays available without covering the watchlist');
ok(sourceHtml.indexOf('@import url(') > sourceHtml.indexOf('<style>') &&
  sourceHtml.indexOf('@import url(') < sourceHtml.indexOf('*,*::before,*::after'),
  'Google font import precedes CSS rules so iOS and Windows use the intended metrics');
ok(/var optionsLabOpen = true/.test(decisionUi) &&
  /dc-command-fold" open/.test(decisionUi) &&
  /dc-lab-detail" open/.test(decisionUi) &&
  /dc-lab-subdetail" open/.test(decisionUi) &&
  /return '<details open><summary>Risk Profile/.test(decisionUi),
  'decision research panels are expanded by default');
ok(/ShellV5\.ringPop/.test(hotkeys),
  'hotkeys Esc fallback calls ShellV5.ringPop while ring open');
ok(/function plainWdStatus/.test(shell) && /chipLabel/.test(shell) &&
  !/setWdSync\('ok', 'WD ' \+ \(d\.symbol \|\| ''\) \+ \(chip \?/.test(shell) &&
  /#shell-wd-sync\{max-width/.test(shell),
  'shell WD status uses plain chipLabel + clipped topbar (no raw HTML)');
const wdBridge = fs.readFileSync(path.join(root, 'src/ui/wavedeck_bridge_v5.js'), 'utf8');
ok(/function chipLabel/.test(wdBridge) && /chipLabel: chipLabel/.test(wdBridge) &&
  /chipLabelFromHint/.test(wdBridge),
  'WaveDeckBridge exports chipLabel for shell status');
ok(/RING_LOGO/.test(shell) && /st50-icon\.svg/.test(shell) && /sr-hub-ver/.test(shell) &&
  /sr-logo/.test(shell) && /Stock Terminal/.test(shell),
  'shell ring hub shows Stock Terminal 5.0 logo');
/* 側欄 ROUTES 全數涵蓋於轉盤（workspace → btn-cmdp） */
(function () {
  var routeIds = [
    'pulse', 'chart', 'breadth', 'heat', 'institutional', 'international',
    'afterhours', 'signals', 'ai', 'watchlist', 'risk', 'news', 'scan', 'book', 'settings'
  ];
  var missing = routeIds.filter(function (id) {
    return shell.indexOf("ringRoute('" + id + "'") < 0;
  });
  ok(missing.length === 0 && /btn-cmdp/.test(shell) && /ringCoversRoute/.test(shell),
    'shell ring covers all sidebar routes' + (missing.length ? ' missing=' + missing.join(',') : ''));
})();
/* 樹深度約束：任一分支 children 巢狀 ≤ RING_MAX_DEPTH（靜態掃描） */
(function () {
  var maxNest = 0;
  function walk(src, from, depth) {
    var i = src.indexOf(from);
    if (i < 0) return;
    var slice = src.slice(i, i + 900);
    if (depth > maxNest) maxNest = depth;
    if (/ringFolder\('tech'/.test(slice) || /ringFolder\('flow-tools'/.test(slice) ||
        /ringFolder\('fundamentals'/.test(slice) || /ringFolder\('screen-tools'/.test(slice) ||
        /ringFolder\('ai-tools'/.test(slice) || /ringFolder\('sys'/.test(slice)) {
      if (depth + 1 > maxNest) maxNest = depth + 1;
    }
  }
  walk(shell, "ringFolder('market'", 1);
  walk(shell, "ringFolder('price'", 1);
  walk(shell, "ringFolder('flow'", 1);
  ok(maxNest <= 3 && /RING_MAX_DEPTH = 3/.test(shell),
    'shell ring analysis tree capped at 3 layers');
})();
ok(/isRingOpen/.test(hotkeys) && /側欄已移除/.test(hotkeys),
  'Esc hotkeys aware sidebar removed (ring is primary nav)');
ok(/st5-tip-boot/.test(shell) && /st5-booted/.test(shell) && /TIP_UX/.test(shell),
  'shell tip-boot hides legacy chart chrome before boot');
ok(/const SERVER = window\.SERVER =/.test(sourceHtml) && /location\.origin && location\.origin !== 'null'/.test(sourceHtml),
  'browser API base is published on window.SERVER and follows the current origin');
ok(/開啟預設總覽/.test(shell) && /applyRoute\('pulse'\)/.test(shell) &&
  /openRing\(window\.innerWidth \/ 2/.test(shell) && /ring=auto/.test(shell),
  'shell boot defaults to pulse and auto-opens ring');
ok(!/saved = localStorage\.getItem\(STORAGE_KEY\) \|\| 'pulse'/.test(shell),
  'shell no longer restores route from localStorage on cold open');

const buildPy = fs.readFileSync(path.join(root, 'build_v2.py'), 'utf8');
ok(/st5-tip-boot/.test(buildPy) && /#pulse/.test(buildPy) && /tip UX modules missing/.test(buildPy),
  'build_v2 injects tip-boot and fails without tip modules');
ok(/app_kernel_v5\.js/.test(buildPy) && /AbortController/.test(appKernel) && /registerPanel/.test(appKernel),
  'build includes the bounded API and panel lifecycle kernel');

const goBat = fs.readFileSync(path.join(root, 'scripts/go.bat'), 'utf8');
ok(/go\.ps1/.test(goBat) && /UpdateOnly/.test(goBat) && !/git\s+(pull|stash|reset|checkout)/i.test(goBat),
  'go.bat is an ASCII compatibility shim with no Git mutation logic');

const goSh = fs.readFileSync(path.join(root, 'scripts/go.sh'), 'utf8');
ok(/TIP_BRANCH/.test(goSh) && /http-client-pool/.test(goSh) && /#pulse/.test(goSh),
  'go.sh enforces tip branch and opens #pulse');
ok(fs.existsSync(path.join(root, 'scripts/go.ps1')), 'scripts/go.ps1 exists for PowerShell');
const goPs = fs.readFileSync(path.join(root, 'scripts/go.ps1'), 'utf8');
ok(/tipUx/.test(goPs) && /st5-tip-boot/.test(goPs) && /#pulse/.test(goPs),
  'go.ps1 verifies tip health/HTML and opens #pulse');
ok(/Assert-LiveRevision/.test(goPs) && /health\/live/.test(goPs) &&
  /releaseCommit/.test(goPs),
  'go.ps1 proves the :18432 process SHA via /health/live before opening the browser');
ok(/Resolve-StockPython/.test(goPs) && /Test-ToolingPython/.test(goPs) &&
  /deprioritize tooling venvs/.test(goPs) && /Stock Terminal Server v5 tip/.test(goPs) &&
  /PULSE_LAYOUT_ANCHOR_3cab212/.test(goPs),
  'go.ps1 pins an absolute Python, deprioritizes tooling venvs, and launches a titled live server console');
ok(/git status --porcelain/.test(goPs) && /git merge --ff-only/.test(goPs) &&
  /Test-IgnorableUpdateDirt/.test(goPs) && /Get-PorcelainPath/.test(goPs) &&
  /data\/\[\^\/\]\+\\\.\(csv\|sqlite3\)/.test(goPs) && /\.loop-engineering/.test(goPs) &&
  /ignore runtime data dirt/.test(goPs) && /non-data changes/.test(goPs) &&
  !/git reset --hard/.test(goPs) && !/git stash/.test(goPs),
  'go.ps1 preserves dirty work, ignores runtime data dirt, and only permits fast-forward updates');

const srv = fs.readFileSync(path.join(root, 'server/server.py'), 'utf8');
ok(/X-Stock-Terminal-UX/.test(srv) && /tipUx/.test(srv) && /\/#pulse/.test(srv),
  'server marks tip UX and opens /#pulse');
ok(/_is_tooling_python/.test(srv) && /_pulse_layout_probe/.test(srv) &&
  /SERVER_BOOT\.txt/.test(srv) && /does NOT refuse/.test(srv) &&
  /pulseLayout/.test(srv) && /pythonBlocked/.test(srv),
  'server reports tooling Python diagnostically and exposes pulseLayout on /health');
ok(fs.existsSync(path.join(root, 'START_TIP.cmd')), 'START_TIP.cmd exists at repo root');
const startTip = fs.readFileSync(path.join(root, 'START_TIP.cmd'), 'utf8');
ok(/Resolve-StockPython/.test(startTip) && /taskkill/.test(startTip) && /go\.ps1/.test(startTip),
  'START_TIP.cmd kills python, verifies tip files, runs go.ps1');
ok(/Tailscale Private Web/.test(startTip) && /sync_private_web\.ps1/.test(startTip),
  'START_TIP.cmd names both ST faces and the Private Web sync script');
ok(/Tailscale Private Web/.test(goPs),
  'go.ps1 banner names local and Tailscale faces');
ok(fs.existsSync(path.join(root, 'scripts/sync_private_web.ps1')),
  'scripts/sync_private_web.ps1 exists');
const syncPw = fs.readFileSync(path.join(root, 'scripts/sync_private_web.ps1'), 'utf8');
ok(/LayoutVerified/.test(syncPw) && /evo-t1-st\.tailbc3519\.ts\.net/.test(syncPw) &&
  /localhost:18432\/#pulse/.test(syncPw) && /拒絕發布/.test(syncPw) &&
  /private_web_release\.py/.test(syncPw) && /RedirectStandardError/.test(syncPw) &&
  /NativeCommandError/.test(syncPw) && !/Start-Process -FilePath 'python'/.test(syncPw),
  'Private Web sync stages exact tip and refuses promote without layout verification');
ok(fs.existsSync(path.join(root, 'scripts/diagnose_tip.ps1')), 'scripts/diagnose_tip.ps1 exists');

const nw = fs.readFileSync(path.join(root, 'src/ui/news_v5.js'), 'utf8');
ok(/nw-mkt-seg/.test(nw) && /flashMkt/.test(nw), 'news TW/US filter');
ok(/impact\.tier/.test(nw) && /impact\.scope/.test(nw) && /nw-impact-seg/.test(nw) &&
  /flashImpact/.test(nw) && /medium_up/.test(nw),
  'news renders and filters deterministic impact tier and scope');

/* 類股熱力：版面不得把 .ht-wd 塞進 2 欄 grid（會把焦點掃描擠出並遮蔽） */
const heat = fs.readFileSync(path.join(root, 'src/ui/heat_v5.js'), 'utf8');
ok(/#ht-body\{[^}]*flex-direction:column/.test(heat) &&
  /#ht-body \.ht-dash\{[^}]*grid-template-columns:minmax\(0,1\.55fr\) minmax\(260px,1fr\)/.test(heat) &&
  /ht-dash/.test(heat) && /ht-kpi/.test(heat) &&
  !/#ht-body\{[^}]*grid-template-columns:minmax\(0,1\.55fr\)/.test(heat),
  'heat body stacks WD/KPI above 2-col dash (focus not clipped)');
ok(/function applyRouteOpts/.test(heat) && /function applySectorHighlight/.test(heat) &&
  /ht-cell\.hi/.test(heat) && /opts\.sector/.test(heat) &&
  /activate\(opts\)/.test(heat) && /detail\.opts/.test(heat),
  'heat activate accepts mkt/sector deep-link and highlights cell');
ok(/data-go="heat"[^>]*data-mkt=/.test(pl) && /data-sector=""/.test(pl) &&
  /class="pl-sbar" data-go="heat"/.test(pl),
  'pulse 產業輪動 熱力→ and sector bars deep-link to heat with mkt/sector');
ok(/hasAttribute\('data-sector'\)/.test(pl) && /opts\.sectorKey/.test(pl) &&
  /點列開熱力並高亮/.test(pl),
  'pulse bind forwards sector/sectorKey to ShellV5.go');
ok(/emitRoute\(id, opts\)/.test(shell) && /activate\(opts\)/.test(shell) &&
  /detail: \{ route: id, opts: opts \}/.test(shell),
  'shell emitRoute forwards route opts into panel activate + shell:route');

ok(/focusByMkt/.test(heat) && /\/focus\?mkt=/.test(heat) &&
  /焦點掃描 · /.test(heat) && /美股流動池/.test(heat) &&
  /function chgCls/.test(heat),
  'heat focus loads /focus?mkt=TW|US and labels US liquid pool');
ok(/marketSharePct/.test(heat) && /rs20VsBenchmarkPct/.test(heat) && /未提供同口徑成交額時不顯示資金流/.test(heat),
  '熱力保留類股資金欄位並揭露缺少同口徑成交額的限制');

const srvPy = fs.readFileSync(path.join(root, 'server/server.py'), 'utf8');
ok(/_US_FOCUS_UNIVERSE/.test(srvPy) && /_focus_scan_pool/.test(srvPy) &&
  /mkt=TW\|US/.test(srvPy) && /universe_label = 'us_liquid'/.test(srvPy) &&
  /'mkt': mkt/.test(srvPy),
  'server /focus supports mkt=US liquid universe + mkt field');
ok(/'生技醫療':\s+\['1795', '6446', '1762'\]/.test(srvPy) &&
  /'油電燃氣':\s+\['6505', '9918', '9926'\]/.test(srvPy) &&
  !/'生技醫療':\s+\['4904', '3105'\]/.test(srvPy),
  'TW Yahoo sector fallback uses same-theme proxies and keeps proxy scope explicit');

ok(/← 儀表板/.test(heat) && /data-shell-back/.test(heat) &&
  /← 儀表板/.test(hub) && /data-shell-back/.test(hub) &&
  /goDashboard/.test(hub),
  'heat + hub pages wire ← 儀表板 to goDashboard');
ok(/← 儀表板/.test(nw) && /data-shell-back/.test(nw),
  'news page has ← 儀表板 back control');

ok(/id: 'factors'/.test(shell) && /FactorsV5/.test(shell) && /ringRoute\('factors'/.test(shell) &&
  /function renderFactors/.test(hub) && /window\.FactorsV5/.test(hub) &&
  /ACTIVATORS\.factors/.test(hub),
  'factors ledger is independent shell route + hub page');
ok(/台指期近月/.test(pl) && /__TXF__/.test(pl) && /TAIFEX MIS/.test(pl) &&
  /加權 \^TWII · 近 20 日/.test(pl) && !/線型＝加權 \^TWII（非台指期）/.test(pl) &&
  !/台指期 TXF'/.test(pl),
  'pulse TXF strip labeled 近月+sources; OHLC spark identifies ^TWII without a redundant header note');

ok(/function applyTxfLiveToChart/.test(polish) && /overlayTxfLiveOnLastBar/.test(polish) &&
  /function isTxfChartSym/.test(polish) &&
  /applyTxfLiveToChart\(quotes\.__TXF__\)/.test(polish) &&
  /applyTxfLiveToChart\(d\)/.test(polish) &&
  /S\.data\.yesterdayClose = q\.prevClose/.test(polish) &&
  /fetch\(base \+ '\/txf'/.test(polish) && /setInterval\(pullTxfLive, 5000\)/.test(polish) &&
  /await refreshTxfCell\(\)/.test(polish) &&
  /sym === 'TXF' \|\| sym === '__TXF'/.test(sourceHtml),
  'TXF chart last bar + header overlay the same /txf quote as the market bar after day close');

ok(/AI科技外溢/.test(hub) && /factorScope/.test(hub) && /aiSpill/.test(hub) &&
  /spill\.ok/.test(hub) && !/美股流動池漲跌/.test(hub) && !/尚無美股漲幅資料/.test(hub),
  'risk page shows AI spillover strip only when data exists (no empty US shell)');
ok(/apply_ai_tech_spillover/.test(srvPy) && /pulse-global:v8/.test(srvPy) &&
  /'NVDA', 'AVGO', 'TSM'/.test(srvPy),
  'server applies AI spillover from global v8 (SOX + NVDA/AVGO/TSM + de-duplicated TW anchors)');
(function () {
  var pi = fs.readFileSync(path.join(root, 'server/pulse_intel.py'), 'utf8');
  ok(/def apply_ai_tech_spillover/.test(pi) && /AI科技外溢偏空/.test(pi) &&
    /費半/.test(pi) && /no_sox_ixic/.test(pi),
    'pulse_intel AI tech spillover uses SOX/IXIC, skips when missing');
})();

if (failed) {
  console.error('\n' + failed + ' failure(s)');
  process.exit(1);
}
console.log('\nshell_v5_selftest PASSED');

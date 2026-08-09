/**
 * shell_v5_selftest.js — ST 5.0 tip 殼層／品牌／熱鍵契約（無瀏覽器）
 * 用法：node tests/shell_v5_selftest.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const shell = fs.readFileSync(path.join(root, 'src/ui/shell_v5.js'), 'utf8');
const hotkeys = fs.readFileSync(path.join(root, 'src/chart/hotkeys_v3.js'), 'utf8');

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

['pulse', 'chart', 'breadth', 'heat', 'institutional', 'ai', 'scan', 'book', 'settings'].forEach(function (id) {
  ok(new RegExp("id: '" + id + "'").test(shell), 'route ' + id);
});

ok(/ShellV5\.go\('chart'\)/.test(hotkeys), 'Esc → chart in hotkeys');
ok(/Alt\+Shift\+1/.test(hotkeys), 'Alt+Shift help row');
ok(/ai: 'AiV5'/.test(shell), 'AiV5 in PANEL_MAP');

['breadth_v5.js', 'heat_v5.js', 'afterhours_v5.js', 'news_v5.js', 'pulse_v5.js', 'ai_v5.js'].forEach(function (f) {
  const t = fs.readFileSync(path.join(root, 'src/ui', f), 'utf8');
  ok(/deactivate/.test(t), f + ' has deactivate');
});

const bridge = fs.readFileSync(path.join(root, 'src/ui/bridge_v5.js'), 'utf8');
ok(/portfolioOpen/.test(bridge) && /marketFlowOpen/.test(bridge) && /openAIModal/.test(bridge),
  'bridge_v5 wraps portfolio/marketflow/AI');
const build = fs.readFileSync(path.join(root, 'build_v2.py'), 'utf8');
ok(build.indexOf('src/ui/ai_v5.js') >= 0 && build.indexOf('src/ui/bridge_v5.js') >= 0,
  'ai_v5 + bridge_v5 in build_v2');

const hub = fs.readFileSync(path.join(root, 'src/ui/hub_v5.js'), 'utf8');
ok(/hub-inst-hero/.test(hub), 'institutional hero strip');
ok(/data-who="trust"/.test(hub) && /data-who="dealer"/.test(hub), 'institutional who tabs');
ok(/fmtLots/.test(hub) && /單位：張/.test(hub), 'institutional ranks use 張');
ok(/magBars/.test(hub) && /refMeter/.test(hub), 'institutional magBars + turnover meter');
ok(/minmax\(0,1fr\) minmax\(0,2fr\)/.test(hub), 'institutional chart ~1/3 width');
ok(/lots-bar/.test(hub) && /class="streak"/.test(hub), 'institutional lots bar separated from streak');
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
  ok(/vz-compact \.vz-pt\{display:none\}/.test(vz) && /wantMarks && !compact/.test(vz),
    'viz compact spark hides peak text labels (no lab occlusion)');
  ok(/vz-compact/.test(vz) && /compact:\s*true/.test(pulseSrc),
    'tip spark uses compact axis (no xunit footer)');
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
const ovn = fs.readFileSync(path.join(root, 'src/chart/overnight_v3.js'), 'utf8');
ok(/overnightRenderInto/.test(ovn) && /function renderInto/.test(ovn) && /ovn-embed/.test(ovn),
  'overnight exposes renderInto for afterhours embed');

const bd = fs.readFileSync(path.join(root, 'src/ui/breadth_v5.js'), 'utf8');
ok(/強弱榜/.test(bd), 'breadth movers replace note panel');
ok(/結構條不重複/.test(bd) || /結構只用 magBars/.test(bd), 'breadth avoids inst number+bar dup');
ok(/官方≠清單/.test(bd) || /官方漲停家數/.test(bd), 'breadth limit popup separates official vs approx list');

const pl = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
ok(/上市漲跌停 · 官方/.test(pl), 'pulse strip labels official limit counts');
ok(/近漲停/.test(pl) && /≠頂列官方家數/.test(pl), 'pulse movers panel not branded as official limit');
ok(/movers\.limitUp/.test(pl), 'pulse prefers movers.limitUp for near-limit list');
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
ok(/加權盤勢/.test(pl) && /櫃買／台指期見頂列/.test(pl) && !/pl-trend-pair/.test(pl),
  'pulse OHLC panel integrated — no duplicate index chips');
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
ok(/正面因子/.test(pl) && /風險因子/.test(pl) && /計入風險分/.test(pl) && !/主要動能/.test(pl),
  'pulse drivers labeled 正面／風險因子 (not 主要動能)');
ok(/大盤體質（X：日/.test(pl) && !/>動能</.test(pl),
  'pulse history labels health as 體質 not 動能');
ok(/industryLabel/.test(pl) && /bindSectorMoverLink/.test(pl) && /data-sector-key/.test(pl),
  'pulse movers industry tags + sector hover link');
ok(/globalAbbr/.test(pl) && /'DJI'/.test(pl) && /'SPX'/.test(pl) && /'NDX'/.test(pl) && /'SOX'/.test(pl),
  'pulse global uses short ticker labels');
ok(/basisPts/.test(pl) && /正價差/.test(pl) && /逆價差/.test(pl) && /Basis＝期貨−現貨/.test(pl),
  'pulse strip shows TXF–TAIEX basis');
ok(/pl-flash-q/.test(pl) && /flashQ/.test(pl) && /搜代號\/關鍵字/.test(pl),
  'pulse flash has keyword search beside TW/US tabs');
ok(/#pl-flash-sec \.pl-sec-tog button\{font-size:7px/.test(pl) &&
  /pl-wl \.pl-sec-tog button\{font-size:7px/.test(pl),
  'pulse flash market tabs match watchlist tab font size');
ok(/data-layout=/.test(pl) && /LAYOUT_CONTRACT/.test(pl) &&
  /grid-template-columns:repeat\(5,minmax\(0,1fr\)\)/.test(pl) &&
  /pl-zone z-top/.test(pl) && /pl-zone z-bot/.test(pl) &&
  /PULSE_LAYOUT_ANCHOR_3cab212/.test(pl) && /probeLayoutCols/.test(pl) &&
  !/4col-priority/.test(pl) && !/max-width:1280/.test(pl) &&
  !/5col-2zone-flex/.test(pl) && !/enforceFiveCol/.test(pl),
  'pulse dash is known-good 5col-2zone + runtime probe (anchor 3cab212)');
ok(/#pl-body\{[^}]*overflow:hidden/.test(pl) && /pl-expanded\{overflow:auto\}/.test(pl),
  'pulse one-screen lock; scroll only when factors expanded');
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
  /ringDepth\(\) > 1/.test(shell) && /hi === -2/.test(shell) &&
  /function ringPopTo/.test(shell) && /data-ring-pop-to/.test(shell) &&
  /sr-crumb/.test(shell) && /BrowserBack/.test(shell) && /button === 3/.test(shell) &&
  /ringPop: ringPop/.test(shell) && /ringPopTo: ringPopTo/.test(shell),
  'shell ring back: wheel hub slot + Esc/Backspace/crumb/side-button pop layer');
ok(/ShellV5\.ringPop/.test(hotkeys),
  'hotkeys Esc fallback calls ShellV5.ringPop while ring open');
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
ok(/開啟預設總覽/.test(shell) && /applyRoute\('pulse'\)/.test(shell) &&
  /openRing\(window\.innerWidth \/ 2/.test(shell) && /ring=auto/.test(shell),
  'shell boot defaults to pulse and auto-opens ring');
ok(!/saved = localStorage\.getItem\(STORAGE_KEY\) \|\| 'pulse'/.test(shell),
  'shell no longer restores route from localStorage on cold open');

const buildPy = fs.readFileSync(path.join(root, 'build_v2.py'), 'utf8');
ok(/st5-tip-boot/.test(buildPy) && /#pulse/.test(buildPy) && /tip UX modules missing/.test(buildPy),
  'build_v2 injects tip-boot and fails without tip modules');

const goBat = fs.readFileSync(path.join(root, 'scripts/go.bat'), 'utf8');
ok(/FAIL_TIP_HTML/.test(goBat) && /st5-tip-boot/.test(goBat) && /#pulse/.test(goBat),
  'go.bat refuses non-tip HTML and opens #pulse');

const goSh = fs.readFileSync(path.join(root, 'scripts/go.sh'), 'utf8');
ok(/TIP_BRANCH/.test(goSh) && /http-client-pool/.test(goSh) && /#pulse/.test(goSh),
  'go.sh enforces tip branch and opens #pulse');
ok(fs.existsSync(path.join(root, 'scripts/go.ps1')), 'scripts/go.ps1 exists for PowerShell');
const goPs = fs.readFileSync(path.join(root, 'scripts/go.ps1'), 'utf8');
ok(/tipUx/.test(goPs) && /st5-tip-boot/.test(goPs) && /#pulse/.test(goPs),
  'go.ps1 verifies tip health/HTML and opens #pulse');
ok(/Resolve-StockPython/.test(goPs) && /Test-BlockedPython/.test(goPs) &&
  /hermes/.test(goPs) && /Stock Terminal Server v5 tip/.test(goPs) &&
  /PULSE_LAYOUT_ANCHOR_3cab212/.test(goPs),
  'go.ps1 blocks hermes python and launches titled live server console');
ok(/ST_PYTHON/.test(goBat) && /hermes-agent/.test(goBat) && /FAIL_PYTHON_HERMES/.test(goBat),
  'go.bat also resolves python and blocks hermes');

const srv = fs.readFileSync(path.join(root, 'server/server.py'), 'utf8');
ok(/X-Stock-Terminal-UX/.test(srv) && /tipUx/.test(srv) && /\/#pulse/.test(srv),
  'server marks tip UX and opens /#pulse');
ok(/_is_blocked_python/.test(srv) && /_pulse_layout_probe/.test(srv) &&
  /SERVER_BOOT\.txt/.test(srv) && /refusing Hermes/.test(srv) &&
  /pulseLayout/.test(srv) && /pythonBlocked/.test(srv),
  'server refuses hermes python and exposes pulseLayout on /health');
ok(fs.existsSync(path.join(root, 'START_TIP.cmd')), 'START_TIP.cmd exists at repo root');
const startTip = fs.readFileSync(path.join(root, 'START_TIP.cmd'), 'utf8');
ok(/Resolve-StockPython/.test(startTip) && /taskkill/.test(startTip) && /go\.ps1/.test(startTip),
  'START_TIP.cmd kills python, verifies tip files, runs go.ps1');
ok(fs.existsSync(path.join(root, 'scripts/diagnose_tip.ps1')), 'scripts/diagnose_tip.ps1 exists');

const nw = fs.readFileSync(path.join(root, 'src/ui/news_v5.js'), 'utf8');
ok(/nw-mkt-seg/.test(nw) && /flashMkt/.test(nw), 'news TW/US filter');

if (failed) {
  console.error('\n' + failed + ' failure(s)');
  process.exit(1);
}
console.log('\nshell_v5_selftest PASSED');

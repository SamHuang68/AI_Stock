/**
 * mobile_portrait_layout_selftest.js
 *
 * 手機直立功能頁的靜態版型契約。此測試不取代真實瀏覽器幾何驗收；
 * 它負責阻止已知的 CSS 根因（模組搶走外層捲動、多欄固定高度、隱藏主區）復發。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const uiDir = path.join(root, 'src', 'ui');
const readUi = (name) => fs.readFileSync(path.join(uiDir, name), 'utf8');

let failed = 0;
function ok(value, message) {
  if (!value) {
    console.error('FAIL:', message);
    failed += 1;
    return;
  }
  console.log('OK  ', message);
}

const modules = {
  breadth: readUi('breadth_v5.js'),
  heat: readUi('heat_v5.js'),
  hub: readUi('hub_v5.js'),
  afterhours: readUi('afterhours_v5.js'),
  news: readUi('news_v5.js'),
  ai: readUi('ai_v5.js'),
  scan: readUi('scan_v5.js'),
  book: readUi('book_v5.js')
};
const shell = readUi('shell_v5.js');
const mobileChart = readUi('mobile_v2.css');
ok(modules.heat.includes('@media(orientation:landscape) and (max-height:540px)') &&
  modules.heat.includes('height:380px;min-height:380px') &&
  modules.heat.includes('grid-template-columns:minmax(0,1.55fr) minmax(240px,1fr)'),
  '類股短橫式保留左右主區及最低可讀高度，不退回零高度堆疊');

ok(
  shell.includes('html[data-st5-route]:not([data-st5-route="chart"]) body #app #shell-main #shell-views.show'),
  'Shell 以高權重選擇器擔任非圖表功能頁的唯一直立捲動容器'
);
ok(
  shell.includes('overflow-x:hidden!important;overflow-y:auto!important') &&
    shell.includes('scroll-padding-bottom:calc(88px + env(safe-area-inset-bottom,0px))'),
  'Shell 保留垂直捲動並避開 iOS 安全區與浮動控制'
);
ok(
  shell.includes("'#pl-root,#dc-root,#bd-root,#ht-root,.hub-root,#ah-root,#ai5-root,#nw-root,#sc-root,#bk-root'"),
  '手機版型診斷涵蓋全部主要功能頁根節點'
);
ok(
  shell.includes('setTimeout(function () { traceMobilePanelLayout(id); }, 1200);'),
  '非同步資料完成後會再次量測手機版型'
);
ok(
  shell.includes('if (state.route === id) views.scrollTop = 0;'),
  '切換功能頁後會重設共用捲動位置，避免從上一頁中段開始'
);
ok(
  shell.includes("var hasDeepLink = !!(rawHash && initialRoute && !initialRoute.action);") &&
    shell.includes("var initialId = hasDeepLink ? rawHash : 'pulse';"),
  '冷啟動保留合法功能深連結，無效或空白網址仍回總覽'
);
ok(
  shell.includes('var resolvedHash = resolveAlias(h, {});') &&
    shell.includes('findRoute(resolvedHash.id)') &&
    shell.includes("go(h, resolvedHash.opts || {});"),
  '同頁 hashchange 也解析舊路由別名，不會留下網址與畫面不一致'
);

const forbiddenShellOwner = /#shell-views:has\([^)]*\)\{[^}]*overflow:hidden!important/;
Object.entries(modules).forEach(([name, source]) => {
  ok(
    source.includes('@media(max-width:900px) and (orientation:portrait)'),
    `${name} 具備明確的手機直立版型契約`
  );
  ok(
    !forbiddenShellOwner.test(source),
    `${name} 不會在桌機規則中搶走 Shell 的外層捲動權`
  );
});

ok(
  modules.breadth.includes('#bd-root .bd-strip{grid-template-columns:repeat(2,minmax(0,1fr))') &&
    modules.breadth.includes('#bd-root .bd-dash{display:flex!important;flex-direction:column') &&
    modules.breadth.includes('#bd-root .bd-mover-groups{grid-template-columns:minmax(0,1fr)!important}'),
  '大盤廣度在直立模式採兩欄摘要、主區上下排、強弱榜上下排'
);
ok(
  modules.heat.includes('#ht-body .ht-kpi{grid-template-columns:repeat(2,minmax(0,1fr))') &&
    modules.heat.includes('#ht-body .ht-dash{display:flex!important;flex-direction:column') &&
    modules.heat.includes('#ht-root .ht-grid{grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:minmax(64px,auto)') &&
    modules.heat.includes('#ht-root .ht-two{display:flex!important;flex-direction:column'),
  '產業輪動在直立模式顯示兩欄完整熱力格，焦點清單上下排'
);
ok(
  modules.hub.includes('.hub-root .hub-strip{grid-template-columns:repeat(2,minmax(0,1fr))') &&
    modules.hub.includes('display:flex!important;flex-direction:column;grid-template-columns:none!important') &&
    modules.hub.includes('grid-template-columns:minmax(0,1fr)!important;grid-template-rows:auto!important') &&
    modules.hub.includes('.hub-root .hub-inst-rankhd .meta{flex:1 1 100%;min-width:0;max-width:100%;white-space:normal'),
  'Hub 七個功能頁在直立模式採兩欄摘要與單欄內容流'
);
ok(
  modules.afterhours.includes('#ah-root .ah-strip{grid-template-columns:repeat(2,minmax(0,1fr))') &&
    modules.afterhours.includes('#ah-root .ah-dash{display:flex!important;flex-direction:column'),
  '盤後頁在直立模式採兩欄摘要與五區上下排'
);
ok(
  modules.news.includes('#nw-root .nw-left,#nw-root .nw-mid,#nw-root .nw-right{') &&
    modules.news.includes('display:flex!important;height:auto!important') &&
    modules.news.includes('#nw-root .nw-dash{display:flex!important;flex-direction:column') &&
    modules.news.includes('@media (min-width:901px) and (max-width:1100px){#nw-root .nw-left{display:none}}'),
  '快訊頁在直立模式保留左中右三區並改為上下排'
);
ok(
  modules.ai.includes('#ai5-root .ai5-strip{grid-template-columns:repeat(2,minmax(0,1fr))') &&
    modules.ai.includes('#ai5-root .ai5-dash{display:flex!important;flex-direction:column'),
  'AI 頁在直立模式採兩欄摘要與做多／做空上下排'
);
ok(
  modules.scan.includes('#sc-root .sc-layout{display:flex!important;flex-direction:column') &&
    modules.scan.includes('#sc-root #sc-results table{min-width:760px'),
  '選股頁在直立模式將條件與結果上下排，寬表只在局部水平捲動'
);
ok(
  modules.book.includes('#bk-root .bk-strip{grid-template-columns:repeat(2,minmax(0,1fr))') &&
    modules.book.includes('#bk-root .bk-zone{display:flex!important;flex-direction:column') &&
    modules.book.includes('#bk-root .bk-empty-steps{grid-template-columns:1fr'),
  '投組頁在直立模式採兩欄摘要、主區與空狀態步驟上下排'
);

[
  'pulse', 'decision', 'breadth', 'heat', 'institutional', 'international',
  'afterhours', 'signals', 'ai', 'watchlist', 'risk', 'factors', 'news',
  'scan', 'book', 'settings'
].forEach((route) => {
  ok(new RegExp(`id: '${route}'`).test(shell), `Shell 仍註冊功能路由 ${route}`);
});

ok(
  /@media\s*\(max-width:\s*768px\)\s*and\s*\(orientation:\s*portrait\)/.test(mobileChart) &&
    mobileChart.includes('data-mobile-workspace-page'),
  '圖表頁維持獨立的手機直立整頁分頁契約'
);
ok(
  /@media\s*\(max-width:\s*900px\)\s*and\s*\(orientation:\s*landscape\)/.test(mobileChart),
  '手機橫式工作站契約未被功能頁直立修正覆蓋'
);
ok(mobileChart.includes('width: 24px;') && mobileChart.includes('height: 24px;'),
  '分頁圓點保留至少 24px 的實際觸控區');
ok(mobileChart.includes('body.right-collapsed #body > #right') && mobileChart.includes('#right-collapse { display: none !important; }'),
  '手機直式不承接桌機收合狀態，也不顯示遮擋內容的收合把手');
ok(shell.includes('resolvedHash.id !== state.route || resolvedHash.opts.sym'),
  '同圖表路由的功能別名仍執行股票切換');

ok(
  modules.hub.includes("typeof AbortController === 'function'") &&
    modules.hub.includes("jget('/pulse?refresh=0', 8000)") &&
    modules.hub.includes('jget(ecoUrl, 8000)') &&
    modules.hub.includes("jget('/sync/status', 8000)"),
  '國際頁資料請求具備有界逾時，不會因單一來源懸掛而永久留在載入畫面'
);

if (failed) {
  console.error(`\nmobile_portrait_layout_selftest FAILED (${failed})`);
  process.exit(1);
}
console.log('\nmobile_portrait_layout_selftest PASSED');

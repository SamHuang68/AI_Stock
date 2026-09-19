'use strict';

// 載入完整正式模組，只匯出封閉作用域內的實際 render，驗證後端資料形狀。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
function load(file, marker, expose) {
  const nodes = new Map(), meters = [], pending = [];
  const context = {
    console, Date, Math, Promise,
    document: { getElementById: id => nodes.get(id) || null },
    addEventListener() {}, setTimeout() { return 1; }, clearTimeout() {},
    localStorage: { getItem() { return null; } },
    fetch() { return new Promise(resolve => pending.push(resolve)); },
    Viz: Object.fromEntries(['ratioMeter', 'scoreMeter', 'magBar'].map(name => [name, (...args) => {
      meters.push({ name, args }); return '<i data-meter="' + name + '"></i>';
    }]))
  };
  context.window = context;
  vm.createContext(context);
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  assert.equal(source.split(marker).length, 2, '測試接線須唯一：' + file);
  vm.runInContext(source.replace(marker, 'window.testRender = {' + expose + '};\n' + marker), context, { filename: file });
  return { context, nodes, meters, pending, render: context.testRender };
}
function node() { return { innerHTML: '', textContent: '', querySelectorAll() { return []; } }; }
function fixture() {
  return {
    stocks: { '2330': { name: '台積電', weight: 50, vol: 20, beta: 1.2 } },
    portfolio: { vol: null, var95: null, days: 60 }, corr: {}, sector: { 半導體: 50 },
    skipped: ['9999'], benchmark: '^TWII',
    quality: { available: false, holdingCoveragePct: 50, betaCoveragePct: 50,
      commonSampleDays: 60, reasons: ['部分持倉缺少足夠歷史'] }
  };
}
const legacy = load('src/portfolio/portfolio_v3.js', '  window.portfolioOpen = open;', 'render:render, text:portfolioText');
const book = load('src/ui/book_v5.js', '  window.BookV5 = {', 'render:render');
book.nodes.set('bk-body', node()); book.nodes.set('bk-sub', node());
function checkViews(data) {
  book.meters.length = 0;
  book.render.render(data);
  return [legacy.render.render(data), legacy.render.text(data), book.nodes.get('bk-body').innerHTML];
}
let views = checkViews(fixture());
for (const text of views) {
  assert.match(text, /年化波動(?:<\/div><div class="val">| )資料不足/);
  assert.match(text, /持倉涵蓋率 50\.0%/);
  assert.match(text, /Beta 涵蓋率 50\.0%/);
  assert.match(text, /共同有效報酬 60 筆/);
  assert.match(text, /部分持倉缺少足夠歷史/);
  assert.match(text, /台積電/); assert.match(text, /9999/);
  assert.doesNotMatch(text, /(?:年化波動|1日95%VaR) 0\.0/);
}
assert.equal(book.meters.length, 0, '未知波動、VaR、相關性、完整投組 Beta 不可畫成零風險');

const betaMissing = fixture();
betaMissing.skipped = [];
betaMissing.stocks['2317'] = { name: '鴻海', weight: 50, vol: 15, beta: null };
betaMissing.portfolio = { vol: 12.3, var95: 1.25, days: 60 };
betaMissing.quality.holdingCoveragePct = 100;
betaMissing.quality.reasons = ['部分持倉缺少可驗證的基準 Beta'];
views = checkViews(betaMissing);
for (const text of views) {
  assert.match(text, /12\.3%/); assert.match(text, /1\.25%/);
  assert.match(text, /投組 ?Beta(?:<\/div><div class="val">| )資料不足/);
}
assert.equal(book.meters.filter(x => x.name === 'magBar').length, 0, '不得將已知一半 Beta 當作整體 Beta');
assert.equal(book.meters.length, 2, '缺 Beta 仍保留可量測的波動與 VaR');

const zero = fixture();
zero.skipped = [];
zero.stocks['2330'] = { name: '台積電', weight: 100, vol: 0, beta: 0 };
zero.portfolio = { vol: 0, var95: 0, days: 60 };
zero.corr = { '2330|2317': 0 };
zero.quality = { available: true, holdingCoveragePct: 100, betaCoveragePct: 100, commonSampleDays: 60, reasons: [] };
views = checkViews(zero);
for (const text of views) {
  assert.match(text, /0\.0%/); assert.match(text, /0\.00%/);
  assert.doesNotMatch(text, /資料不足/);
}
assert.equal(book.meters.length, 4, '有效零值仍要保留完整視覺化');
const escaped = fixture(); escaped.quality.reasons = ['缺少 <img src=x onerror=alert(1)>'];
assert(!legacy.render.render(escaped).includes('<img'));
book.render.render(escaped); assert(!book.nodes.get('bk-body').innerHTML.includes('<img'));

const decision = load('src/ui/decision_v5.js', '  window.DecisionV5 = {',
  'portfolio:portfolioHtml, warning:warningTemporalHtml, constraint:constraintLabel');
const note = decision.render.portfolio({ portfolioOverlay: { available: false, quality: fixture().quality } });
assert.match(note, /持倉涵蓋率 50\.0%/); assert.match(note, /部分持倉缺少足夠歷史/);
assert.doesNotMatch(note, /null%/);
assert.match(decision.render.constraint('source_data_expired'), /來源資料已過期/);
const oldAsOf = new Date(Date.now() - 2 * 86400000).toISOString();
const oldWarning = { asOf: oldAsOf, temporalContext: {
  computedAt: oldAsOf, evaluationMode: 'intraday_monitor',
  freshness: { allInputsLive: true, status: 'live' }, liveOverlay: { status: 'live' }
} };
const expired = decision.render.warning(oldWarning, { freshness: 0.2 });
assert.match(expired, /目前不可用：決策來源已過期/);
assert(expired.includes(oldAsOf)); assert.match(expired, /已保存評估/);
assert.doesNotMatch(expired, /即時資料|即時計算/);
const staleLive = decision.render.warning(oldWarning, { freshness: 1 });
assert.doesNotMatch(staleLive, /即時資料/); assert.match(staleLive, /即時效期待更新/);
const currentWarning = JSON.parse(JSON.stringify(oldWarning));
currentWarning.temporalContext.computedAt = new Date().toISOString();
assert.match(decision.render.warning(currentWarning, { freshness: 1 }), /即時資料/);

const pulse = load('src/ui/pulse_v5.js', '  window.PulseV5 = {', 'head:renderHeadMeta');
pulse.nodes.set('pl-head-meta', node());
function head(freshness) {
  pulse.render.head({ pulse: { updatedAt: new Date().toISOString(), dataCompleteness: 100,
    marketSnapshot: { freshness: { freshness: 'fresh', worstAsOf: new Date().toISOString() } },
    decisionSummary: { dataQuality: { completeness: 1, freshness, staleFields: freshness < 1 ? ['breadth'] : [] } }
  } });
  return pulse.nodes.get('pl-head-meta').innerHTML;
}
assert.match(head(0.2), /效期：<b>過期（決策來源）/);
assert.match(head(0.5), /效期：<b>降級/);
assert.match(head(1), /效期：<b>有效/);
(async () => {
  head(1); head(0.2);
  pulse.pending[3]({ ok: true, json: async () => ({ running: false, lastOk: true }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.match(pulse.nodes.get('pl-head-meta').innerHTML, /效期：<b>過期（決策來源）/,
    '較舊同步工作回應不可將目前過期效期覆寫成有效');
  console.log('投組缺值與效期呈現：完整模組 render、文字、零值、涵蓋率、計量圖與來源效期通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

/* 驗證實際面板渲染、金額單位、期別、缺值重試及切換股票後的非同步結果。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/fundamental/fundamental_v3.js'), 'utf8');

function harness(fetcher) {
  let html = '', clock = 1000;
  const section = { set outerHTML(value) { html = value; } };
  const state = { sym: '2885', mkt: 'TW', tab: 'stats' };
  const context = { S: state, console, setTimeout, Date: { now: () => clock },
    fetch: fetcher, renderStats: () => '',
    document: { getElementById: id => id === 'fund-sect' ? section : { insertAdjacentHTML: (_, value) => { html = value; } } } };
  context.window = context;
  vm.runInNewContext(source, context);
  return { context, state, html: () => html, advance: n => { clock += n; } };
}
const ready = () => new Promise(resolve => setImmediate(resolve));
const financial = {
  symbol: '2885', market: 'TW', score: null, revenueStatus: 'prior_period',
  revenue: { periodLabel: '2026-07', monthRev: 17560416, unitMultiplier: 1000,
    yoyPct: 78.98, momPct: -10.29, cumYoyPct: 130.25, priorPeriod: true, expectedPeriod: '2026-08', source: 'MOPS:sii' },
  income: { period: '2026年第2季累計', eps: 2.64, industry: '金控業', marginStatus: 'not_applicable',
    netIncome: 39008897, parentNetIncome: 36572168, unitMultiplier: 1000, source: 't187ap06_L_fh',
    sourceDate: '2026-09-13', marginNote: '此業別不套用一般業三率與評分。' }
};
(async () => {
  let calls = 0;
  const view = harness(async () => { calls++; return { ok: true, json: async () => financial }; });
  view.context.renderStats(); await ready();
  assert.match(view.html(), /月營收 2026-07/);
  assert.match(view.html(), /175\.6 億/);
  assert.match(view.html(), /EPS 2\.64/);
  assert.match(view.html(), /2026年第2季累計/);
  assert.match(view.html(), /390\.1 億/);
  assert.match(view.html(), /2026-08 尚無此股資料/);
  assert.doesNotMatch(view.html(), /基本面評分|<span class="stat-k">毛利率/);
  await view.context.fetchFund('2885', 'TW'); assert.equal(calls, 1);
  view.advance(60001);
  await view.context.fetchFund('2885', 'TW'); assert.equal(calls, 2);

  const partial = harness(async () => ({ ok: true, json: async () => ({ market: 'TW', revenue: { period: '11508', yoyPct: 0 }, income: null }) }));
  partial.context.renderStats(); await ready();
  assert.match(partial.html(), /YoY 年增/);
  assert.match(partial.html(), /\+0\.0%/);
  assert.doesNotMatch(partial.html(), /Yahoo|盈餘成長/);

  let resolve;
  const switched = harness(() => new Promise(done => { resolve = done; }));
  switched.context.renderStats();
  switched.state.sym = '2883';
  resolve({ ok: true, json: async () => financial }); await ready();
  assert.equal(switched.html(), '');
  console.log('台股基本面顯示：期別、單位、金融業口徑、缺值重試與切股驗證通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

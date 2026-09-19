'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const tick = () => new Promise(resolve => setImmediate(resolve));
function pending() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
function harness(file, api, setup = '') {
  const nodes = new Map(), requests = [], badges = [], rendered = [];
  const element = () => ({ innerHTML: '', textContent: '', querySelector: () => null, querySelectorAll: () => [],
    classList: { remove() {}, add() {} }, appendChild() {} });
  for (const [route, prefix] of [['news', 'nw'], ['afterhours', 'ah']]) {
    for (const id of ['view-' + route, 'mount-' + route, prefix + '-root', prefix + '-body', prefix + '-sub', route + '-v5-css']) nodes.set(id, element());
  }
  nodes.set('dc-history', element()); nodes.set('dc-hist-meta', element());
  const context = {
    Date, Math, console, Promise, location: { origin: 'http://test.invalid' }, testRendered: rendered, testBody: element(),
    document: { getElementById: id => nodes.get(id) || null, createElement: element,
      querySelector: () => null, head: { appendChild() {} } },
    addEventListener() {}, setInterval() { return 1; }, clearInterval() {}, setTimeout() { return 1; }, clearTimeout() {},
    ShellV5: { route: () => api === 'HeatV5' ? 'heat' : '', softBadge: (...args) => badges.push(args) },
    localStorage: { getItem() { return null; } },
    fetch(url) {
      const p = pending(); requests.push({ ...p, url }); return p.promise;
    }
  };
  context.window = context; vm.createContext(context);
  let source = fs.readFileSync(path.join(root, file), 'utf8');
  const marker = '  window.' + api + ' = ';
  if (setup) source = source.replace(marker, setup + '\n' + marker);
  vm.runInContext(source, context, { filename: file });
  return { context, api: context[api], nodes, requests, badges, rendered };
}
function complete(request, data) { request.resolve({ ok: true, json: async () => data, text: async () => JSON.stringify(data) }); }

async function groupedPanel(route, prefix, api, count) {
  const h = harness('src/ui/' + route + '_v5.js', api);
  async function finish(batch, label, fail = false) {
    for (let i = 0; i < count; i++) {
      const r = h.requests[batch * count + i];
      if (fail) r.reject(new Error('測試失敗'));
      else complete(r, route === 'news' ? { items: [{ title: label, mkt: 'TW', cat: '測試', date: label }] }
        : { ok: true, results: [{ cid: 'CDF', name: label, price: 100, changePct: 1 }], date: label, source: label });
    }
    await tick();
  }
  h.api.activate(); h.api.refresh({ soft: true });
  await finish(0, '舊資料');
  assert.equal(h.badges.at(-1)[1], true, route + ' 舊請求不可清新標示');
  await finish(1, '新資料');
  const body = h.nodes.get(prefix + '-body');
  assert.match(body.innerHTML, /新資料/);
  const current = body.innerHTML;
  h.api.refresh({ soft: true }); h.api.deactivate();
  const badgeCount = h.badges.length;
  await finish(2, '離頁資料');
  assert.equal(body.innerHTML, current); assert.equal(h.badges.length, badgeCount);
  h.api.activate(); h.api.deactivate(); h.api.activate();
  await finish(4, '重入資料');
  const newest = body.innerHTML;
  await finish(3, '舊失敗', true);
  assert.equal(body.innerHTML, newest); assert.match(newest, /重入資料/);
  console.log('通過：' + route + ' 完整 render、逆序、離頁及失敗回應所有權');
}

async function decision() {
  const h = harness('src/ui/decision_v5.js', 'DecisionV5',
    'ensureMount = function () { return window.testBody; };\n' +
    'render = function (ctx) { window.testRendered.push(ctx.id); };\n' +
    'window.testLoadHistory = loadHistory;');
  const work = [];
  h.context.DecisionData = { refresh() { const p = pending(); work.push(p); return p.promise; } };
  h.api.refresh(false); h.api.deactivate();
  work[0].resolve({ context: { id: '離頁資料' } }); await tick();
  assert.equal(h.rendered.length, 0);
  h.api.refresh(false); h.api.refresh(true);
  work[2].resolve({ context: { id: '新資料' } }); await tick();
  work[1].resolve({ context: { id: '舊資料' } }); await tick();
  assert.deepEqual(h.rendered, ['新資料']);
  h.context.testLoadHistory(); h.api.deactivate();
  complete(h.requests[0], { rows: [{ asOf: '2026-09-18T08:00:00Z', regime: '離頁歷史' }] }); await tick();
  assert.equal(h.nodes.get('dc-history').innerHTML, '');
  h.context.testLoadHistory(); h.context.testLoadHistory();
  complete(h.requests[2], { rows: [{ asOf: '2026-09-19T08:00:00Z', regime: '新歷史' }] }); await tick();
  complete(h.requests[1], { rows: [{ asOf: '2026-09-18T08:00:00Z', regime: '舊歷史' }] }); await tick();
  assert.match(h.nodes.get('dc-history').innerHTML, /新歷史/);
  assert.doesNotMatch(h.nodes.get('dc-history').innerHTML, /舊歷史/);
  const oldMarket = h.api.refreshMarketData();
  h.api.deactivate();
  const newMarket = h.api.refreshMarketData();
  complete(h.requests[3], { ok: true }); await oldMarket;
  assert.equal(work.length, 3, '離頁的市場更新不可再啟動決策刷新');
  assert.equal(h.api.refreshMarketData(), newMarket, '舊 finally 不可清除新市場請求');
  complete(h.requests[4], { ok: true }); await tick();
  work[3].resolve({ context: { id: '重入市場資料' } }); await newMarket;
  assert.deepEqual(h.rendered, ['新資料', '重入市場資料']);
  console.log('通過：決策正式 load 與歷史回應的離頁、逆序');
}

async function heat() {
  const h = harness('src/ui/heat_v5.js', 'HeatV5',
    'renderFocus = function (data) { window.testRendered.push(data && data.id); };\n' +
    'window.testFocus = loadFocus; window.testFocusState = state;');
  h.context.testFocus(true); h.context.testFocus(true);
  complete(h.requests[1], { id: '新資料' }); await tick();
  complete(h.requests[0], { id: '舊資料' }); await tick();
  assert.deepEqual(h.rendered, ['新資料']);
  assert.equal(h.context.testFocusState.focusByMkt.TW.id, '新資料');
  h.context.testFocus(true); h.api.deactivate();
  complete(h.requests[2], { id: '離頁資料' }); await tick();
  assert.deepEqual(h.rendered, ['新資料']);
  h.context.testFocus(true); h.context.testFocus(true);
  complete(h.requests[4], { id: '重入資料' }); await tick();
  h.requests[3].reject(new Error('舊請求失敗')); await tick();
  assert.equal(h.context.testFocusState.focusByMkt.TW.id, '重入資料');
  assert.deepEqual(h.rendered, ['新資料', '重入資料']);
  console.log('通過：類股焦點正式請求、快取及渲染的逆序與離頁');
}

(async () => {
  await groupedPanel('news', 'nw', 'NewsV5', 3);
  await groupedPanel('afterhours', 'ah', 'AfterhoursV5', 5);
  await decision(); await heat();
  console.log('面板非同步生命週期：全部通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

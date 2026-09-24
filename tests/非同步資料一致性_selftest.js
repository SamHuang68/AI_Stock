'use strict';

// 使用正式模組、路由函式及受控 Promise，驗證亂序回應與跨模組生命週期。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function pending() {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function scoped(source, name) {
  const start = source.indexOf('  function ' + name + '(');
  const next = source.indexOf('\n  function ', start + 1);
  assert(start >= 0 && next > start, '須找到正式函式：' + name);
  return source.slice(start, next);
}
function response(value, status = 200) {
  return { ok: status === 200, status, text: async () => JSON.stringify(value), json: async () => value };
}

async function checkDecisionStore() {
  const requests = [], publications = [], saved = new Map();
  const context = {
    location: { origin: 'http://test.invalid' }, Date, Math, console,
    localStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) },
    CustomEvent: function (type, init) { this.type = type; this.detail = init.detail; },
    dispatchEvent: event => publications.push(event.detail.state.context),
    fetch(url, options) {
      if (!url.endsWith('/decision/context')) return Promise.resolve(response({ ok: true }));
      const request = pending(); requests.push({ ...request, options }); return request.promise;
    }
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(read('src/core/decision_data_v5.js'), context);
  const store = context.DecisionData;
  const oldInput = { holdings: [{ symbol: '2330' }], portfolioKind: 'actual' };
  const newInput = { holdings: [{ symbol: '2317' }], portfolioKind: 'observation_pool' };
  const payload = (id, asOf) => ({ regime: { id }, portfolio: { symbol: id }, asOf });
  const oldWork = store.refresh(oldInput);
  assert.equal(store.refresh(oldInput), oldWork, '相同輸入的非強制更新應共用進行中請求');
  const newWork = store.refresh(newInput);
  assert.notEqual(oldWork, newWork, '不同輸入不可共用舊請求');
  assert.equal(requests.length, 2);
  assert.equal(JSON.parse(requests[1].options.body).portfolioKind, 'observation_pool');
  requests[1].resolve(response(payload('新投組', '2026-09-19T10:01:00Z')));
  await newWork;
  requests[0].resolve(response(payload('舊投組', '2026-09-19T10:00:00Z')));
  const oldResult = await oldWork;
  assert.equal(store.get().context.portfolio.symbol, '新投組', '較晚舊回應不可回滾投組');
  assert.equal(oldResult.context.portfolio.symbol, '新投組', '舊呼叫者也只能取得目前狀態');
  assert(!publications.some(value => value.portfolio.symbol === '舊投組'));

  const firstForce = store.refresh({ ...oldInput, force: true });
  const latestForce = store.refresh({ ...newInput, force: true });
  requests[2].resolve(response(payload('過期強制更新', '2026-09-19T10:02:00Z')));
  await tick();
  assert.equal(store.refresh(newInput), latestForce, '舊請求完成不可清除最新 in-flight');
  assert.equal(requests.length, 4, '最新請求仍在進行時不可意外再送');
  requests[3].resolve(response(payload('最新強制更新', '2026-09-19T10:03:00Z')));
  const results = await Promise.all([firstForce, latestForce]);
  assert(results.every(value => value.context.portfolio.symbol === '最新強制更新'));
  assert(!publications.some(value => value.portfolio.symbol === '過期強制更新'));

  const failedOld = store.refresh({ ...oldInput, force: true });
  const goodNew = store.refresh({ ...newInput, force: true });
  requests[4].reject(new Error('模擬舊連線中斷'));
  await tick();
  assert.equal(store.refresh(newInput), goodNew, '舊請求失敗也不可清除新請求');
  requests[5].resolve(response(payload('保留最新輸入', '2026-09-19T10:04:00Z')));
  await Promise.all([failedOld, goodNew]);
  assert.equal(store.get().context.portfolio.symbol, '保留最新輸入');
  console.log('通過：決策相同輸入去重、不同輸入更新、強制更新亂序與失敗清理');
}

async function checkSectorMarkets() {
  const requests = [], paints = [];
  const source = read('src/ui/pulse_v5.js');
  const context = {
    sectorMkt: 'TW', sectorCache: { TW: null, US: null }, lastPack: {}, $: () => ({}),
    render: () => paints.push(context.sectorMkt),
    jget(url) { const request = pending(); requests.push({ ...request, url }); return request.promise; }
  };
  vm.createContext(context);
  vm.runInContext(scoped(source, 'loadSectorsMkt') + '\n' + scoped(source, 'sectorsFromPack'), context);
  context.loadSectorsMkt('US');
  assert.equal(context.sectorsFromPack({ sectorsRanked: [{ name: '台灣半導體' }] }).length, 0,
    '美股尚未載入時不可退回台股資料');
  context.loadSectorsMkt('TW');
  requests[1].resolve({ sectors: [{ name: '台灣半導體', changePct: 1 }] }); await tick();
  requests[0].resolve({ sectors: [{ name: '美國能源', changePct: 2 }] }); await tick();
  assert.equal(context.sectorCache.TW[0].name, '台灣半導體');
  assert.equal(context.sectorCache.US[0].name, '美國能源');
  assert.deepEqual(paints, ['TW'], '背景市場的晚到資料不可重繪目前頁面');
  context.loadSectorsMkt('US');
  assert.equal(requests.length, 2, '各市場快取仍可重用');
  assert.equal(context.sectorsFromPack({}).at(0).name, '美國能源');
  console.log('通過：TW／US 快取隔離、無錯市場備援、保留快取重用');
}

function element() {
  return { innerHTML: '', textContent: '', value: '', style: {}, dataset: {},
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute() {}, removeAttribute() {}, querySelector: () => null, querySelectorAll: () => [],
    appendChild() {}, addEventListener() {} };
}

async function checkPanelLifecycle() {
  const ids = new Map(), listeners = new Map(), timers = new Map(), requests = [], events = [];
  let timerId = 0;
  for (const id of ['book-v5-css', 'view-book', 'mount-book', 'bk-root', 'bk-edit', 'bk-body']) ids.set(id, element());
  ids.get('bk-edit').value = '2330 100';
  const context = {
    state: { route: 'chart', prevRoute: 'chart' }, routeSequence: 0,
    routeScroll: Object.create(null), scrollSequence: 0, scrollFrame: null,
    PANEL_MAP: { book: 'BookV5', heat: 'HeatV5', institutional: 'InstitutionalV5' },
    ROUTES: ['book', 'chart', 'heat', 'institutional'].map(id => ({ id })), ROUTE_ALIASES: {},
    STORAGE_KEY: '測試路由', ringState: { open: false },
    S: { positions: { '2330': { shares: 100, lastPrice: 1000, mkt: 'TW' } }, wl: [] },
    document: { readyState: 'loading', body: element(), documentElement: element(), head: element(),
      getElementById: id => ids.get(id), createElement: () => element(), querySelectorAll: () => [],
      addEventListener(type, callback) { const key = 'document:' + type; listeners.set(key, [...(listeners.get(key) || []), callback]); } },
    location: { origin: 'http://test.invalid', pathname: '/', search: '' }, history: { replaceState() {} },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener(type, callback) { listeners.set(type, [...(listeners.get(type) || []), callback]); },
    dispatchEvent(event) { events.push(event); for (const callback of listeners.get(event.type) || []) callback(event); },
    setTimeout(callback, ms) { timers.set(++timerId, { callback, ms }); return timerId; },
    clearTimeout(id) { timers.delete(id); }, clearInterval() {},
    CustomEvent: function (type, init) { this.type = type; this.detail = init.detail; },
    Event: function (type) { this.type = type; }, AbortController, Date, Math, console,
    fetch(url, options) { const request = pending(); requests.push({ ...request, url, options }); return request.promise; },
    $: id => ids.get(id), traceMobilePanelLayout() {},
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(read('src/core/app_kernel_v5.js'), context);
  vm.runInContext(read('src/core/投組資料契約_v5.js'), context);
  vm.runInContext(read('src/ui/book_v5.js'), context);
  const shell = read('src/ui/shell_v5.js');
  vm.runInContext(['scrollSurfaces', 'rememberRouteScroll', 'restoreRouteScroll', 'panelApi', 'deactivateRoute', 'emitRoute', 'findRoute', 'resolveAlias', 'applyRoute']
    .map(name => scoped(shell, name)).join('\n'), context);
  context.ShellV5 = { go: context.applyRoute, route: () => context.state.route };
  let leaveCount = 0;
  const originalDeactivate = context.BookV5.deactivate;
  context.BookV5.deactivate = () => { leaveCount++; originalDeactivate(); };
  context.applyRoute('book');
  assert.equal(requests.length, 1, '實際 Shell、AppKernel、Book 接線只能送一次投組請求');
  assert.equal(requests[0].url, '/portfolio');
  assert.equal(JSON.parse(requests[0].options.body).holdings[0].sym, '2330');
  assert.equal(JSON.parse(requests[0].options.body).holdings[0].weight, 100000, '正式持倉請求須來自股數乘上最新價格');
  for (const callback of listeners.get('document:DOMContentLoaded') || []) callback();
  for (const [id, timer] of [...timers]) if (timer.ms === 240) { timers.delete(id); timer.callback(); }
  assert.equal(requests.length, 1, '頁面就緒不得再由面板自行延遲啟動');
  context.applyRoute('chart');
  assert.equal(leaveCount, 1, '離頁只清理一次');
  assert.equal(context.AppKernel.status().activePanel, null, '返回圖表後 Kernel 不保留舊面板');
  const unchanged = ids.get('bk-body').innerHTML;
  requests[0].resolve(response({ error: '過期回應' }, 500)); await tick();
  assert.equal(ids.get('bk-body').innerHTML, unchanged, '離頁後回應不可再覆寫面板');

  let oldModalCalls = 0;
  context.portfolioOpen = () => { oldModalCalls++; };
  vm.runInContext(read('src/ui/bridge_v5.js'), context);
  context.portfolioOpen();
  assert.equal(requests.length, 2, '舊工具列橋接仍能以一次導航啟動 Book');
  assert.equal(oldModalCalls, 0, 'Shell 可用時不重開舊模態');
  let heatActivations = 0;
  context.applyRoute('heat', { mkt: 'US', sector: '能源' });
  assert.equal(leaveCount, 2, '從 Book 轉至尚未載入的模組亦清理一次');
  const oldRetry = [...timers.values()].filter(timer => timer.ms === 50).at(-1);
  assert(oldRetry, '模組未就緒時保留 Shell 重試');
  context.applyRoute('chart');
  context.HeatV5 = { activate() { heatActivations++; }, deactivate() {} };
  oldRetry.callback();
  assert.equal(heatActivations, 0, '離頁後舊模組重試不可重新啟動');
  context.applyRoute('heat', { mkt: 'US', sector: '能源' });
  assert.equal(heatActivations, 1);
  const heatEvent = events.filter(event => event.type === 'shell:route' && event.detail.route === 'heat').at(-1);
  assert.equal(heatEvent.detail.opts.sector, '能源', '路由通知及深層參數仍保留');

  // 同一路由模組尚未載入時重新導航，只允許最新一次重試啟動。
  context.applyRoute('institutional', { test: 'old' });
  const firstRetry = [...timers.values()].filter(timer => timer.ms === 50).at(-1);
  context.applyRoute('institutional', { test: 'new' });
  const secondRetry = [...timers.values()].filter(timer => timer.ms === 50).at(-1);
  const activated = [];
  context.InstitutionalV5 = { activate: opts => activated.push(opts.test), deactivate() {} };
  firstRetry.callback(); secondRetry.callback();
  assert.deepEqual(activated, ['new']);
  context.applyRoute('chart');
  context.AppKernel = null;
  context.applyRoute('book');
  assert.equal(requests.length, 3, '沒有 Kernel 時仍保留 Shell 的單次直接啟動備援');
  const leaveBeforeFallback = leaveCount;
  context.applyRoute('chart');
  assert.equal(leaveCount, leaveBeforeFallback + 1, '沒有 Kernel 時仍保留直接離頁清理');
  console.log('通過：實際 Shell／Kernel／Book 單次啟動、離頁清理、舊橋接與延遲模組導航');
}

async function checkPulseLeave() {
  const source = read('src/ui/pulse_v5.js'), requests = [], paints = [], timers = new Map();
  const body = element(); let timerId = 0;
  const context = {
    refreshSequence: 0, refreshController: null, refreshPromise: null, refreshIsUpdate: false, timer: null, showFactors: false, lastPack: null,
    stockHealthSequence: 0, stockHealthController: null, stockHealthView: null, routeTrace() {},
    ensureMount: () => body, $: id => id === 'pl-body' ? body : null,
    document: { querySelector: () => null }, Date,
    DecisionData: { refreshPulse() { const request = pending(); requests.push(request); return request.promise.then(pulse => ({ pulse })); } },
    fetchWlQuotes: async () => ({}), render: value => paints.push(value), showPulseUpdateStatus() {},
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; }, clearTimeout: id => timers.delete(id),
    setInterval: () => 1, clearInterval() {},
    ShellV5: { route: () => 'pulse' }
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(['cancelStockHealth', 'refresh', 'activate', 'deactivate'].map(name => {
    if (name === 'deactivate') {
      const start = source.indexOf('  function deactivate(');
      return source.slice(start, source.indexOf('\n  window.PulseV5', start));
    }
    return scoped(source, name);
  }).join('\n'), context);
  context.activate(); context.deactivate(); context.activate();
  requests[1].resolve({ ok: true, breadthOk: true, id: '新頁面' }); await tick();
  requests[0].resolve({ ok: true, breadthOk: false, id: '舊頁面' }); await tick();
  assert.deepEqual(paints.map(value => value.pulse.id), ['新頁面']);
  assert.equal(timers.size, 0, '離頁前的晚到資料不得啟動補建重試');
  context.refresh();
  requests[2].resolve({ ok: true, breadthOk: false }); await tick();
  assert.equal(timers.size, 0, '目前頁面資料不完整也只能讀取，不得安排補建重試');
  context.deactivate();
  assert.equal(timers.size, 0, '離頁後不可留下補建計時器');
  console.log('通過：Pulse 離頁／返回後拒收舊資料，不因缺值自動補建');
}

(async () => {
  await checkDecisionStore();
  await checkSectorMarkets();
  await checkPanelLifecycle();
  await checkPulseLeave();
  console.log('非同步資料一致性行為測試全部通過。');
})().catch(error => { console.error(error); process.exitCode = 1; });

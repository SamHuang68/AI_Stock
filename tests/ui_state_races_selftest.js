'use strict';

// 離線回歸：讀取正式來源；DOM、網路與計時器是可控邊界，不啟動產品或連線。
// node tests/ui_state_races_selftest.js [stats|weekly|macro|keyboard]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');
const html = read('stock_terminal.html');

function section(source, start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, '正式來源擷取邊界必須存在：' + start);
  return source.slice(a, b);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const response = data => ({ ok: true, status: 200, json: async () => data });
function element() {
  let outer = '';
  return {
    style: {}, dataset: {}, disabled: false, textContent: '', innerHTML: '', writes: 0,
    get outerHTML() { return outer; },
    set outerHTML(value) { outer = value; this.writes++; },
    insertAdjacentHTML(where, value) { this.innerHTML += value; },
    addEventListener() {},
  };
}
function harness(initial = {}) {
  const elements = new Map(), selectors = new Map(), listeners = {}, timers = [], calls = [];
  const storage = new Map();
  const scope = {
    console: { log() {}, info() {}, warn() {}, error() {} },
    SERVER: 'http://fixture.invalid', SERVER_P: 'http://fixture.invalid', __loadSeq: 1,
    document: {
      readyState: 'loading', getElementById: id => elements.get(id) || null,
      querySelector: selector => selectors.get(selector) || null,
      addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
    },
    localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
    addEventListener() {},
    setTimeout(fn, ms) { timers.push({ fn, ms }); return timers.length; },
    clearTimeout() {}, setInterval() { return 0; }, clearInterval() {},
    renderStats() { return '<div>原始統計</div>'; },
    fetch(url, options) {
      const pending = deferred();
      calls.push({ url: String(url), options, ...pending });
      return pending.promise;
    },
    setStat(message) { scope.status = message; },
  };
  scope.window = scope;
  vm.createContext(scope);
  // stock_terminal.html 的 S 是全域 const，不能用 window.S 替代。
  vm.runInContext('const S = ' + JSON.stringify({
    sym: '2330', mkt: 'TW', tab: 'stats', range: '1y', wl: [],
    data: { candles: [], meta: {} }, ind: null, ...initial,
  }) + ';', scope);
  assert.equal(scope.S, undefined, 'fixture 必須保留全域詞法 S');
  const state = vm.runInContext('S', scope);
  return {
    scope, state, elements, selectors, listeners, timers, calls,
    evaluate(source, filename = 'production-extract.js') { return vm.runInContext(source, scope, { filename }); },
    load(file) { return this.evaluate(read(file), file); },
    add(id) { const el = element(); elements.set(id, el); return el; },
    switchTo(sym, mkt = 'TW') {
      scope.__loadSeq++;
      state.sym = sym; state.mkt = mkt; state.data = { candles: [], meta: {} };
    },
  };
}

const polishStats = () => section(read('src/ui/polish_v3.js'), 'const _keystatsCache = {};', '// (#3) Patch renderWl');
const parseSource = () => section(html, 'function parseYF(raw)', 'function traceIntradaySessionFilter');
function statsHarness(kind) {
  const h = harness();
  h.add('rpanel');
  h.output = h.add(kind === 'chip' ? 'chip-sect' : kind === 'polish' ? 'keystats-sect' : 'dual-card');
  h.cap = h.add('rp-MKTCAP');
  h.funds = [];
  if (kind === 'chip') h.load('src/fundamental/chip_v3.js');
  if (kind === 'polish') h.evaluate(polishStats(), 'polish_v3.js:keystats');
  if (kind === 'enhance') {
    h.add('enh3-style');
    h.selectors.set('#rpanel .dual-card', h.output);
    h.scope.fetchFund = (sym, mkt) => {
      const pending = deferred();
      h.funds.push({ sym, mkt, ...pending });
      return pending.promise;
    };
    h.load('src/ui/enhance_v3.js');
  }
  h.pending = () => kind === 'enhance' ? h.funds : h.calls;
  h.fulfill = (index, value) => {
    const payload = kind === 'chip' ? { inst: { foreign: value }, date: '20261021' }
      : kind === 'polish' ? { marketCap: value, currency: 'TWD', trailingPE: 22 }
        : { score: value };
    h.pending()[index].resolve(kind === 'enhance' ? payload : response(payload));
  };
  return h;
}

async function statsCases() {
  for (const kind of ['chip', 'polish', 'enhance']) {
    // B 完成後 A 才回覆；DOM 與 B 的 meta 都必須保留 B。
    const h = statsHarness(kind);
    h.scope.renderStats();
    h.switchTo('2317');
    h.scope.renderStats();
    assert.equal(h.pending().length, 2, kind + ' 兩檔應有不同請求');
    h.fulfill(1, 72); await flush();
    assert.ok(h.output.outerHTML, kind + ' 目前請求必須能正常更新');
    const current = h.output.outerHTML, writes = h.output.writes;
    if (kind === 'polish') assert.equal(h.state.data.meta.marketCap, 72);
    h.fulfill(0, 11); await flush();
    assert.equal(h.output.outerHTML, current, kind + ' 舊回覆不能改寫 B');
    assert.equal(h.output.writes, writes, kind + ' 舊回覆不能重畫');
    if (kind === 'polish') assert.equal(h.state.data.meta.marketCap, 72, '舊市值不能寫入新股 meta');

    // 不假設切股一定重畫 STATS；分別檢查代次、代號、市場與分頁。
    for (const stale of ['generation', 'symbol', 'market', 'tab']) {
      const x = statsHarness(kind);
      x.scope.renderStats();
      if (stale === 'generation') x.scope.__loadSeq++;
      if (stale === 'symbol') x.state.sym = '2317';
      if (stale === 'market') x.state.mkt = 'US';
      if (stale === 'tab') x.state.tab = 'health';
      x.output.outerHTML = '目前畫面';
      x.fulfill(0, 11); await flush();
      assert.equal(x.output.outerHTML, '目前畫面', kind + ' 必須擋下 ' + stale + ' 過期回覆');
      assert.equal(x.state.data.meta.marketCap, undefined);
    }

    // 同一次載入兩次 render：最新 callback 仍生效，舊 callback 不得再寫一次。
    const x = statsHarness(kind);
    x.scope.renderStats(); x.scope.renderStats();
    if (kind === 'polish') {
      assert.equal(x.calls.length, 1, '估值沿用正式 inflight 合併');
      x.fulfill(0, 72); await flush();
    } else {
      x.fulfill(1, 72); await flush();
      x.fulfill(0, 11); await flush();
    }
    assert.equal(x.output.writes, 1, kind + ' 同代次只有最新 render 可以寫入');
  }

  // canonical 技術分數完成後的第二層 fetchFund，也必須遵守原 render 身分。
  const h = statsHarness('enhance');
  h.evaluate(parseSource(), 'stock_terminal.html:parseYF');
  h.scope.runWorker = async () => ({ rsi14: 60, sma20: 100, sma60: 100 });
  const values = Array(25).fill(100);
  const raw = { chart: { result: [{ meta: { symbol: '2330.TW' },
    timestamp: values.map((_, i) => 1790000000 + i * 86400),
    indicators: { quote: [{ open: values, high: values, low: values, close: values, volume: values }] },
  }] } };
  h.scope.renderStats();
  h.calls[0].resolve(response(raw)); await flush();
  assert.equal(h.funds.length, 2, '正式 canonical 路徑必須發出巢狀基本面請求');
  h.switchTo('2317');
  h.scope.renderStats();
  h.fulfill(2, 72); await flush();
  const current = h.output.outerHTML, writes = h.output.writes;
  h.fulfill(1, 11); h.fulfill(0, 12); await flush();
  assert.equal(h.output.outerHTML, current, '巢狀基本面舊回覆不能改寫 B');
  assert.equal(h.output.writes, writes);
}

async function weeklyCases() {
  const h = harness();
  h.evaluate(section(html, 'const RANGE_DEFS = [', 'function renderRangeBar()'));
  h.evaluate(section(html, 'function _posPrice(v)', '/**'));
  h.evaluate(section(html, 'function patchTodayDailyBarWithLive(', '/**'));
  h.evaluate('function applyFreshness(parsed, rdef) {\n' + section(html,
    '  // ── Yahoo data freshness fix', '  // ── Intraday yesterdayClose') + '\nreturn parsed;\n}');
  const weekly = h.evaluate('RANGE_DEFS.find(r => r.key === "max")');
  const daily = h.evaluate('RANGE_DEFS.find(r => r.key === "1y")');
  assert.equal(weekly.interval, '1wk', '正式「全部」仍使用週線');
  assert.equal(daily.interval, '1d');
  const monday = Date.parse('2026-10-19T01:00:00Z') / 1000;
  const fixture = () => ({
    candles: Array.from({ length: 21 }, (_, i) => ({
      time: monday - (20 - i) * 7 * 86400, open: 100, high: i === 20 ? 110 : 102,
      low: 98, close: i === 20 ? 108 : 100, volume: 300000,
    })),
    meta: { regularMarketTime: monday + 2 * 86400 + 4 * 3600,
      regularMarketPrice: 108, regularMarketOpen: 106,
      regularMarketDayHigh: 109, regularMarketDayLow: 105, regularMarketVolume: 100000 },
  });
  for (const days of [0, 7]) {
    const data = fixture();
    data.meta.regularMarketTime += days * 86400;
    const before = JSON.stringify(data.candles);
    h.scope.applyFreshness(data, weekly);
    assert.equal(JSON.stringify(data.candles), before, '週線不能混入當日日 K（含跨週快照）');
    assert.equal(data.candles.at(-1).volume, 300000, '原週量必須保留');
    assert.equal(data.candles.slice(-20).reduce((s, c) => s + c.close, 0) / 20, 100.4);
  }
  const missingDay = fixture();
  h.scope.applyFreshness(missingDay, daily);
  assert.equal(missingDay.candles.length, 22, '日線落後時仍補當日日 K');
  assert.equal(missingDay.candles.at(-1)._synthetic, true);
  assert.equal(missingDay.candles.at(-1).volume, 100000);
  const noVolume = fixture();
  noVolume.candles.at(-1).time = noVolume.meta.regularMarketTime;
  noVolume.candles.at(-1).volume = 0;
  h.scope.applyFreshness(noVolume, daily);
  assert.equal(noVolume.candles.length, 21);
  assert.equal(noVolume.candles.at(-1).volume, 100000, '同日日線補量保留');
  const sameDay = fixture();
  sameDay.candles.at(-1).time = sameDay.meta.regularMarketTime;
  sameDay.candles.at(-1).close = 107;
  h.scope.applyFreshness(sameDay, daily);
  assert.equal(sameDay.candles.at(-1).close, 108, '同日日線對齊現價保留');
  assert.equal(sameDay.candles.at(-1)._livePatched, true);
}

function macroHarness(id = '__TW_RATES__') {
  const h = harness({ sym: id });
  h.loading = h.add('chart-loading');
  h.button = h.add('market-chart-refresh');
  h.button.dataset.chartId = id;
  h.button.textContent = '↻ 更新資料';
  h.load('src/chart/market_chart_v3.js');
  h.finishEquity = () => {
    h.switchTo('2330');
    h.loading.style.display = 'none'; h.loading.textContent = '';
    h.scope.status = 'OK · 2330';
  };
  h.fire = async ms => {
    const ready = h.timers.filter(t => t.ms === ms && !t.fired);
    assert.ok(ready.length, '應建立 ' + ms + 'ms 計時器');
    for (const timer of ready) { timer.fired = true; timer.fn(); }
    await flush();
  };
  return h;
}
async function macroCases() {
  for (const id of ['__TW_RATES__', '__MARGIN_RATIO__']) {
    for (const failure of ['network', 'http', 'json']) {
      const h = macroHarness(id);
      const pending = h.scope.MarketChart.load(id);
      assert.equal(h.state.sym, id);
      assert.notEqual(h.scope.S, h.state, '正式 load 建立的 window.S 不能取代詞法 S');
      assert.match(h.calls[0].url, id === '__TW_RATES__' ? /\/macro\/chart\// : /\/yf\//);
      h.finishEquity();
      if (failure === 'network') h.calls[0].reject(new Error('離線延後失敗'));
      if (failure === 'http') h.calls[0].resolve({ ok: false, status: 503 });
      if (failure === 'json') h.calls[0].resolve({ ok: true, json: async () => { throw new Error('離線解析失敗'); } });
      assert.equal(await pending, false);
      assert.equal(h.loading.style.display, 'none', id + ' 舊 ' + failure + ' 不得遮蓋新股');
      assert.equal(h.scope.status, 'OK · 2330');
    }
    const current = macroHarness(id);
    const pending = current.scope.MarketChart.load(id);
    current.calls[0].reject(new Error('目前請求失敗'));
    assert.equal(await pending, false);
    assert.equal(current.loading.style.display, 'flex', '目前請求失敗仍呈現錯誤');
    assert.match(current.scope.status, /載入失敗/);

    for (const phase of ['before-response', 'during-delay', 'return-same-id']) {
      const h = macroHarness(id);
      const refresh = h.scope.MarketChart.refresh(id);
      assert.equal(h.calls[0].options.method, 'POST');
      if (phase === 'before-response') h.finishEquity();
      h.calls[0].resolve(response({ ok: true, count: 1 }));
      await refresh;
      if (phase !== 'before-response') {
        h.finishEquity();
        if (phase === 'return-same-id') h.switchTo(id);
        const selected = h.state.sym;
        await h.fire(600);
        assert.equal(h.state.sym, selected, '舊延遲回呼不得改變目前代號');
      }
      assert.equal(h.calls.length, 1, id + ' ' + phase + ' 不得發出舊圖 GET');
      assert.equal(h.button.disabled, false, '過期更新必須釋放自己的按鈕');
      assert.equal(h.scope.status, 'OK · 2330', '過期更新不得覆寫目前狀態');
    }
    const valid = macroHarness(id);
    const refresh = valid.scope.MarketChart.refresh(id);
    valid.calls[0].resolve(response({ ok: true })); await refresh;
    await valid.fire(600);
    assert.equal(valid.calls.length, 2, '仍在原圖時正常重新載入');
    assert.equal(valid.state.sym, id);
    valid.calls[1].resolve({ ok: false, status: 503 }); await flush();
    assert.equal(valid.button.disabled, false, '重新載入完成後釋放按鈕');
  }

  // 新更新已佔用共用按鈕時，舊成功／失敗／延遲回呼都不能解除新請求。
  for (const completion of ['success', 'failure', 'timer']) {
    const h = macroHarness();
    const old = h.scope.MarketChart.refresh('__TW_RATES__');
    if (completion === 'timer') {
      h.calls[0].resolve(response({ ok: true })); await old;
    }
    h.switchTo('__MARGIN_RATIO__');
    // 正式 ensureRefreshBtn 在新圖完成時會重設這兩個欄位。
    h.button.dataset.chartId = '__MARGIN_RATIO__'; h.button.disabled = false;
    const newer = h.scope.MarketChart.refresh('__MARGIN_RATIO__');
    const status = h.scope.status;
    if (completion === 'success') h.calls[0].resolve(response({ ok: true }));
    if (completion === 'failure') h.calls[0].reject(new Error('舊更新失敗'));
    if (completion === 'timer') await h.fire(600);
    await old;
    assert.equal(h.button.disabled, true, '舊 ' + completion + ' 不得解除新按鈕鎖定');
    assert.equal(h.button.textContent, '更新中…');
    assert.equal(h.scope.status, status);
    assert.equal(h.calls.length, 2, '舊延遲回呼不得插入額外載入');
    h.calls[1].resolve(response({ ok: true })); await newer;
  }
}

function keyTarget(tagName, selector = null) {
  return { tagName, closest: query => selector && query.split(',').includes(selector) ? {} : null };
}
async function keyboardCases() {
  const h = harness({ wl: [{ t: '2317', m: 'TW' }, { t: '2330', m: 'TW' }, { t: '2454', m: 'TW' }] });
  const loads = [];
  h.scope.loadSym = (...args) => loads.push(args);
  h.load('src/chart/hotkeys_v3.js');
  const handler = h.listeners.keydown[0];
  const key = (target, extra = {}) => {
    const e = { key: ' ', code: 'Space', target, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; }, ...extra };
    handler(e); return e;
  };
  const controls = [keyTarget('BUTTON', 'button'), keyTarget('SPAN', 'button'),
    keyTarget('A', 'a[href]'), keyTarget('SUMMARY', 'summary'),
    ...['button', 'link', 'menuitem', 'tab'].map(role => keyTarget('DIV', '[role="' + role + '"]')),
    keyTarget('INPUT'), keyTarget('TEXTAREA'), keyTarget('SELECT'),
    { ...keyTarget('DIV'), isContentEditable: true }];
  for (const target of controls) {
    assert.equal(key(target).defaultPrevented, false, '互動控制項 Space 必須保留原生行為');
    assert.equal(loads.length, 0);
  }
  const background = keyTarget('DIV');
  for (const modifier of ['ctrlKey', 'metaKey', 'altKey']) {
    assert.equal(key(background, { [modifier]: true }).defaultPrevented, false);
    assert.equal(loads.length, 0);
  }
  h.selectors.set('dialog[open]', {});
  assert.equal(key(background).defaultPrevented, false);
  h.selectors.delete('dialog[open]');
  key(background, { defaultPrevented: true });
  assert.equal(loads.length, 0);
  assert.equal(key(background).defaultPrevented, true);
  assert.deepEqual(loads.pop(), ['2454', 'TW'], '背景 Space 仍切下一檔');
  assert.equal(key(background, { shiftKey: true }).defaultPrevented, true);
  assert.deepEqual(loads.pop(), ['2317', 'TW'], '背景 Shift+Space 仍切上一檔');
}

const groups = { stats: statsCases, weekly: weeklyCases, macro: macroCases, keyboard: keyboardCases };
(async () => {
  const selected = process.argv.slice(2);
  for (const name of selected.length ? selected : Object.keys(groups)) {
    assert.ok(groups[name], '未知案例組：' + name);
    await groups[name]();
    console.log('通過：' + name);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

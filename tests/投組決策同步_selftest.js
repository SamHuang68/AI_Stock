'use strict';

// 完整正式資料層與 UI：保留 ensureMount、render 及事件接線，只替換 DOM、網路與時鐘。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const tick = async () => { for (let i = 0; i < 50; i++) await Promise.resolve(); };
const snapshot = id => ({ ok: true, updatedAt: '2026-09-20T09:00:00Z',
  decisionSummary: { snapshotId: 'dc-' + id, revision: 1, regime: { id } } });
const contextPayload = id => ({ regime: { id, label: id }, asOf: '2026-09-20T09:00:00Z',
  snapshotId: 'dc-' + id, contractVersion: 1, dataQuality: {}, actionEnvelope: {} });
const job = status => ({ jobId: 'pulse-更新測試', status });

function harness(role = 'owner') {
  const nodes = new Map(), requests = [], timers = new Map(), intervals = new Map(), listeners = new Map(), saved = new Map();
  let now = 1000000, timerId = 0, route = 'decision';
  function element() {
    let html = '';
    const item = { id: '', textContent: '', disabled: false, hidden: false, open: false, style: {},
      attributes: {}, classList: { add() {}, remove() {}, toggle() {} },
      setAttribute(name, value) { this.attributes[name] = String(value); },
      getAttribute(name) { return this.attributes[name] || null; }, hasAttribute(name) { return name in this.attributes; },
      querySelector() { return null; }, querySelectorAll() { return []; },
      appendChild(child) { if (child.id) nodes.set(child.id, child); },
      addEventListener(type, fn) { this['on' + type] = fn; } };
    Object.defineProperty(item, 'innerHTML', {
      get() { return html; },
      set(value) {
        // 建立正式 HTML 的具名節點，讓 ensureMount 的建置分支與後續 render 使用同一批元素。
        for (const match of html.matchAll(/\bid="([^"]+)"/g)) nodes.delete(match[1]);
        html = String(value);
        for (const match of html.matchAll(/\bid="([^"]+)"/g)) {
          const child = element(); child.id = match[1]; nodes.set(child.id, child);
        }
      }
    });
    return item;
  }
  nodes.set('view-decision', element());
  const c = {
    console, Promise, Math, AbortController, URL,
    Date: class extends Date { static now() { return now; } },
    SERVER: 'http://test.invalid', location: { origin: 'http://test.invalid' },
    ST_PRIVATE_WEB_PROFILE: { role }, S: { positions: { '2330': { shares: 100, lastPrice: 1000, entry: 900, notes: '私人筆記' } }, wl: [{ t: '0050', m: 'TW' }] },
    localStorage: { getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value) },
    document: { getElementById: id => nodes.get(id) || null, createElement: element,
      querySelector() { return null; }, querySelectorAll() { return []; }, head: element() },
    ShellV5: { route: () => route },
    CustomEvent: function (type, init) { this.type = type; this.detail = init.detail; },
    addEventListener(type, fn) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(fn); },
    dispatchEvent(event) { for (const fn of listeners.get(event.type) || []) fn(event); },
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, at: now + ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval(fn, ms) { const id = ++timerId; intervals.set(id, { fn, ms }); return id; },
    clearInterval(id) { intervals.delete(id); },
    fetch(url, options = {}) {
      let resolve, reject;
      const promise = new Promise((a, b) => { resolve = a; reject = b; });
      const parsed = new URL(url);
      const request = { path: parsed.pathname + parsed.search, method: options.method || 'GET', options,
        resolve, reject, completed: false, ignoreAbort: false };
      requests.push(request);
      const abort = () => {
        if (request.ignoreAbort) return;
        const error = new Error('測試請求已取消'); error.name = 'AbortError'; reject(error);
      };
      if (options.signal) {
        if (options.signal.aborted) abort();
        else options.signal.addEventListener('abort', abort, { once: true });
      }
      return promise;
    }
  };
  c.window = c; vm.createContext(c);
  for (const file of ['src/core/投組資料契約_v5.js', 'src/core/decision_data_v5.js', 'src/ui/decision_v5.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), c, { filename: file });
  }
  return {
    c, nodes, requests, timers,
    pending(url, method) {
      const request = requests.find(item => !item.completed && item.path === url && (!method || item.method === method));
      assert(request, '缺少待完成請求：' + (method || '') + ' ' + url); return request;
    },
    async complete(request, payload, status = 200) {
      request.completed = true;
      request.resolve({ ok: status >= 200 && status < 300, status,
        json: async () => payload, text: async () => JSON.stringify(payload) });
      await tick();
    },
    async completeRaw(request, raw, status = 200) {
      request.completed = true;
      request.resolve({ ok: status >= 200 && status < 300, status,
        json: async () => JSON.parse(raw), text: async () => raw });
      await tick();
    },
    async fail(request) {
      request.completed = true; request.reject(new Error('測試網路失敗')); await tick();
    },
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        const first = [...timers].filter(([, timer]) => timer.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!first) break;
        now = first[1].at; timers.delete(first[0]); first[1].fn(); await tick();
      }
      now = end; await tick();
    },
    leave() { route = 'pulse'; c.DecisionV5.deactivate(); },
    enter() { route = 'decision'; },
    button() { return nodes.get('dc-refresh'); },
    status() { return nodes.get('dc-update-status').textContent; },
    body() { return nodes.get('dc-body').innerHTML; },
    seed(id) { c.DecisionData.publish(contextPayload(id), '測試既有決策'); },
    trace() { return JSON.parse(saved.get(c.DecisionData.traceKey) || '[]'); }
  };
}

(async () => {
  const h = harness();
  h.c.DecisionV5.refresh(true);
  const actual = h.pending('/decision/context', 'POST');
  const actualInput = JSON.parse(actual.options.body);
  assert.equal(actualInput.portfolioKind, 'actual');
  assert.equal(actualInput.portfolioInputStatus, 'complete');
  assert.equal(actualInput.holdings[0].weight, 100000);
  assert(!actual.options.body.includes('私人筆記')); assert(!actual.options.body.includes('entry'));
  h.c.PortfolioContext.setMode('observation_pool');
  const watch = h.requests.filter(r => r.path === '/decision/context').at(-1);
  const watchInput = JSON.parse(watch.options.body);
  assert.equal(watchInput.portfolioKind, 'observation_pool');
  assert.equal(watchInput.holdings[0].sym, '0050'); assert.equal(watchInput.holdings[0].weight, 1);
  await h.complete(watch, contextPayload('最新觀察池'));
  await h.complete(actual, contextPayload('舊持倉回應'));
  assert.match(h.body(), /最新觀察池/); assert.doesNotMatch(h.body(), /舊持倉回應/);
  assert.equal(h.c.DecisionData.get().context.regime.id, '最新觀察池');
  h.c.S.positions = {};
  h.c.dispatchEvent({ type: 'storage', key: 'st_portfolio_mode_v1', newValue: 'actual' });
  const empty = h.requests.filter(r => r.path === '/decision/context').at(-1);
  const emptyInput = JSON.parse(empty.options.body);
  assert.equal(emptyInput.portfolioKind, 'actual'); assert.equal(emptyInput.portfolioInputStatus, 'empty');
  assert.equal(emptyInput.holdings.length, 0);
  await h.complete(empty, contextPayload('空持倉市場決策'));
  assert.match(h.body(), /尚未建立實際持倉/);
  console.log('通過：決策與共用模式跨分頁同步、空持倉、逆序回應及私人欄位隔離');

  const incomplete = harness();
  incomplete.c.S.positions['0050'] = { shares: 10, entry: 50 };
  incomplete.c.DecisionV5.refresh(true, { baseGrossExposure: 80 });
  const request = incomplete.pending('/decision/context', 'POST');
  const input = JSON.parse(request.options.body);
  assert.equal(input.portfolioInputStatus, 'incomplete'); assert.equal(input.holdings.length, 0);
  assert.equal(input.riskProfile, null);
  const payload = contextPayload('不完整投組');
  payload.actionEnvelope.positionRange = { targetPct: 88, lowerPct: 77, upperPct: 99 };
  payload.exposureLab = { finalEligibleRange: payload.actionEnvelope.positionRange };
  await incomplete.complete(request, payload);
  assert.match(incomplete.body(), /個別資料有效 1／2 檔/);
  assert.match(incomplete.body(), /數量或最新價格缺漏/);
  assert.doesNotMatch(incomplete.body(), /88\.0%|77\.0%|99\.0%/);
  console.log('通過：部分缺值保留分母、禁止送出片段持倉與風險設定，範圍不沿用');

  const changed = harness(); changed.c.DecisionV5.refresh(true);
  const obsolete = changed.pending('/decision/context', 'POST');
  changed.c.S.positions = {};
  await changed.complete(obsolete, contextPayload('來源已變更的回應'));
  assert.equal(changed.c.DecisionData.get().context, null, '同模式下來源已變更也不能發布舊結果');
  assert.match(changed.body(), /投組資料已變更/);
  console.log('通過：請求期間來源變更不發布過期個人化決策');

  const reader = harness('reader');
  reader.c.DecisionV5.refresh(true, { baseGrossExposure: 99 });
  const read = reader.pending('/decision/context', 'GET');
  assert.equal(read.options.body, undefined);
  await reader.complete(read, contextPayload('Reader 市場決策'));
  assert.match(reader.body(), /目前角色無法存取私人投組/);
  assert.doesNotMatch(reader.body(), /私人筆記|100000/);
  reader.c.PortfolioContext.setMode('observation_pool');
  assert(reader.requests.every(r => r.method === 'GET'));
  console.log('通過：Reader 只讀市場且不傳送持倉、觀察池或風險設定');
})().catch(error => { console.error(error); process.exitCode = 1; });

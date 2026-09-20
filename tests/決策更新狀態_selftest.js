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
    ST_PRIVATE_WEB_PROFILE: { role }, Store: { positions: { '2330': { shares: 100, entry: 1000 } } },
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
  for (const file of ['src/core/decision_data_v5.js', 'src/ui/decision_v5.js']) {
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
function track(promise) {
  const record = { done: false, value: null };
  record.promise = promise.then(value => { record.done = true; record.value = value; return value; });
  return record;
}
function idle(h) {
  assert.equal(h.button().disabled, false, '已完成或背景更新不得把人工更新按鈕鎖住');
  assert.doesNotMatch(h.button().textContent, /等待市場快照/);
}
async function finishRead(h, id) {
  await h.complete(h.pending('/pulse', 'GET'), snapshot(id));
  await h.complete(h.pending('/decision/context'), contextPayload(id));
}
async function finishManual(h, id) {
  await h.complete(h.pending('/pulse/refresh', 'POST'), { ok: true, job: job('succeeded') }, 202);
  await finishRead(h, id);
}

async function backgroundSuccess() {
  for (const role of ['owner', 'reader']) {
    const h = harness(role);
    const work = h.c.DecisionV5.refreshMarketData({ background: true });
    idle(h);
    await h.complete(h.pending('/pulse', 'GET'), snapshot('背景成功'));
    idle(h);
    await h.complete(h.pending('/decision/context', role === 'owner' ? 'POST' : 'GET'), contextPayload('背景成功'));
    await work;
    assert.match(h.body(), /決策摘要/); assert.match(h.body(), /背景成功/);
    assert(h.trace().some(row => row.event === 'market_refresh_terminal_success'));
    idle(h);
    assert(!h.requests.some(request => request.path === '/pulse/refresh'));
    // 同頁再次背景更新也不可留下等待狀態。
    await h.advance(60000);
    const second = h.c.DecisionV5.refreshMarketData({ background: true });
    await finishRead(h, '第二次背景成功'); await second; idle(h);
  }
}
async function backgroundFailure() {
  const h = harness();
  const work = h.c.DecisionV5.refreshMarketData({ background: true });
  await h.complete(h.pending('/pulse', 'GET'), { error: '測試快照不可用' }, 503); await work;
  assert.match(h.status(), /失敗|未完成/); assert.match(h.body(), /測試快照不可用/); idle(h);
  const seeded = harness(); seeded.seed('保留的舊決策');
  const failed = seeded.c.DecisionV5.refreshMarketData({ background: true });
  await seeded.complete(seeded.pending('/pulse', 'GET'), { error: '測試來源失敗' }, 503); await failed;
  assert.match(seeded.body(), /保留的舊決策/); idle(seeded);
}
async function foregroundSuccess() {
  const h = harness(); h.seed('更新前決策');
  // 使用正式 ensureMount 安裝的按鈕事件，包含完整 job 輪詢。
  const work = h.button().onclick();
  assert.equal(h.button().disabled, true);
  await h.complete(h.pending('/pulse/refresh', 'POST'), { ok: true, job: job('queued') }, 202);
  await h.advance(1000);
  await h.complete(h.pending('/pulse/update-status?jobId=' + encodeURIComponent(job('running').jobId)), { ok: true, job: job('running') });
  await h.advance(1000);
  await h.complete(h.pending('/pulse/update-status?jobId=' + encodeURIComponent(job('running').jobId)), { ok: true, job: job('succeeded') });
  await h.complete(h.pending('/pulse', 'GET'), snapshot('人工成功'));
  assert.equal(h.button().disabled, true, '個人化完成前保持同一人工工作');
  await h.complete(h.pending('/decision/context'), contextPayload('人工成功')); await work;
  assert.match(h.body(), /人工成功/); idle(h);
}
async function manualQueuedBehindBackground() {
  const h = harness();
  const background = h.c.DecisionV5.refreshMarketData({ background: true });
  await h.complete(h.pending('/pulse', 'GET'), snapshot('背景'));
  const manual = h.button().onclick(), repeated = h.button().onclick();
  assert.equal(h.requests.filter(request => request.path === '/pulse/refresh').length, 0);
  await h.complete(h.pending('/decision/context'), contextPayload('背景')); await background; await tick();
  assert.equal(h.requests.filter(request => request.path === '/pulse/refresh').length, 1, '背景完成後只排一次明確更新');
  assert.equal(h.button().disabled, true);
  await finishManual(h, '排隊人工成功'); await Promise.all([manual, repeated]);
  assert.match(h.body(), /排隊人工成功/); idle(h);
}
async function oldFinallyCannotUnlockNewRequest() {
  const h = harness();
  const old = h.c.DecisionV5.refreshMarketData();
  await h.complete(h.pending('/pulse/refresh', 'POST'), { ok: true, job: job('succeeded') }, 202);
  await h.complete(h.pending('/pulse', 'GET'), snapshot('舊工作'));
  const oldContext = h.pending('/decision/context'); oldContext.ignoreAbort = true;
  h.leave(); idle(h); h.enter();
  const current = h.c.DecisionV5.refreshMarketData();
  assert.equal(h.button().disabled, true);
  await h.complete(oldContext, contextPayload('離頁晚到')); await old;
  assert.equal(h.button().disabled, true, '舊 finally 不得解鎖新人工工作');
  assert.doesNotMatch(h.body(), /離頁晚到/);
  await finishManual(h, '重入新決策'); await current;
  assert.match(h.body(), /重入新決策/); idle(h);
}
async function manualWholeFlowDeadline() {
  const h = harness(); h.seed('逾時前決策');
  const work = track(h.c.DecisionV5.refreshMarketData());
  await h.complete(h.pending('/pulse/refresh', 'POST'), { ok: true, job: job('queued') }, 202);
  await h.advance(70000);
  await h.complete(h.pending('/pulse/update-status?jobId=' + encodeURIComponent(job('queued').jobId)), { ok: true, job: job('succeeded') });
  await h.complete(h.pending('/pulse', 'GET'), snapshot('快照已提交'));
  const request = h.pending('/decision/context');
  await h.advance(19999); assert.equal(work.done, false);
  await h.advance(1);
  assert.equal(work.done, true, '人工更新90秒上限必須包含決策個人化階段');
  await work.promise;
  assert.equal(request.options.signal.aborted, true);
  assert.match(h.status(), /逾時/); assert.match(h.body(), /逾時前決策/); idle(h);
}
async function backgroundWholeFlowDeadline() {
  for (const role of ['owner', 'reader']) {
    const h = harness(role); h.seed('背景逾時前決策');
    const work = track(h.c.DecisionV5.refreshMarketData({ background: true }));
    await h.advance(5000); await h.complete(h.pending('/pulse', 'GET'), snapshot('已提交'));
    const request = h.pending('/decision/context');
    await h.advance(6999); assert.equal(work.done, false);
    await h.advance(1);
    assert.equal(work.done, true, '背景讀取12秒上限必須包含決策個人化階段');
    await work.promise;
    assert.equal(request.options.signal.aborted, true);
    assert.match(h.status(), /逾時/); assert.match(h.body(), /背景逾時前決策/); idle(h);
    if (role === 'reader') assert(h.requests.every(item => item.method === 'GET'));
  }
}
async function contextFailureIsNotSuccess() {
  const failures = [
    ['HTTP 503', (h, request) => h.complete(request, { error: '決策服務不可用' }, 503)],
    ['空回應', (h, request) => h.completeRaw(request, '')],
    ['無效 JSON', (h, request) => h.completeRaw(request, '{invalid-json')],
    ['缺少 regime', (h, request) => h.complete(request, { ok: true })],
    ['網路失敗', (h, request) => h.fail(request)]
  ];
  for (const role of ['owner', 'reader']) {
    for (const [label, fail] of failures) {
      const h = harness(role); h.seed('保留原決策'); const originalHtml = h.body();
      const work = track(h.button().onclick());
      if (role === 'owner') await h.complete(h.pending('/pulse/refresh', 'POST'), { ok: true, job: job('succeeded') }, 202);
      await h.complete(h.pending('/pulse', 'GET'), snapshot('新市場快照'));
      await fail(h, h.pending('/decision/context', role === 'owner' ? 'POST' : 'GET'));
      assert.equal(work.done, true, role + ' ' + label + ' 必須結束等待'); await work.promise;
      assert.equal(h.body(), originalHtml, label + ' 不可替換既有決策畫面');
      assert.equal(h.c.DecisionData.get().context.regime.id, '保留原決策');
      assert.match(h.status(), /失敗|未完成/);
      assert.doesNotMatch(h.status(), /已讀取最新提交/);
      assert(!h.trace().some(row => row.event === 'market_refresh_terminal_success'), label + ' 不可宣稱更新成功');
      assert(h.trace().some(row => row.event === 'market_refresh_terminal_failure'));
      idle(h);
      const retry = h.button().onclick();
      if (role === 'owner') await finishManual(h, '重試成功');
      else await finishRead(h, '重試成功');
      await retry; assert.match(h.body(), /重試成功/); idle(h);
      if (role === 'reader') assert(h.requests.every(item => item.method === 'GET'));
    }
  }
  // 非決策頁的既有呼叫者仍可選擇讀取上次狀態，不因新增嚴格模式而改變預設契約。
  const h = harness(); h.seed('相容舊狀態'); const original = h.c.DecisionData.get();
  const legacy = h.c.DecisionData.refresh({ force: true });
  await h.complete(h.pending('/decision/context'), { error: '不可用' }, 503);
  assert.equal(await legacy, original);
}
async function readerManualDeadline() {
  const h = harness('reader'); h.seed('Reader 原決策');
  const work = track(h.button().onclick());
  await h.advance(5000); await h.complete(h.pending('/pulse', 'GET'), snapshot('Reader 已提交'));
  const request = h.pending('/decision/context', 'GET');
  await h.advance(7000);
  assert.equal(work.done, true, 'Reader 人工重新讀取也須在12秒內結束'); await work.promise;
  assert.equal(request.options.signal.aborted, true); assert(h.requests.every(item => item.method === 'GET'));
  assert.match(h.status(), /逾時/); assert.match(h.body(), /Reader 原決策/); idle(h);
}
async function lateStatusCannotOverwriteTimeout() {
  const h = harness(); h.seed('逾時保留決策');
  const work = track(h.button().onclick());
  await h.complete(h.pending('/pulse/refresh', 'POST'), { ok: true, job: job('queued') }, 202);
  await h.advance(1000);
  const late = h.pending('/pulse/update-status?jobId=' + encodeURIComponent(job('queued').jobId));
  late.ignoreAbort = true;
  await h.advance(89000);
  assert.equal(work.done, true); await work.promise;
  const timeoutMessage = h.status(); assert.match(timeoutMessage, /逾時/); idle(h);
  // 模擬已在傳輸中的晚回應；仍執行完整 refreshPulse 的 onStatus 接線。
  await h.complete(late, { ok: true, job: job('running') });
  assert.equal(h.status(), timeoutMessage, '晚到工作進度不可蓋掉已結束的逾時結果');
  assert.match(h.body(), /逾時保留決策/); idle(h);
}

(async () => {
  const cases = [
    ['背景成功與重複背景更新保留可用按鈕', backgroundSuccess],
    ['背景失敗及空狀態保留可用按鈕', backgroundFailure],
    ['人工工作輪詢與完整 render 後恢復按鈕', foregroundSuccess],
    ['背景期間人工更新只排一次 POST', manualQueuedBehindBackground],
    ['離頁晚回應與舊 finally 不干擾新工作', oldFinallyCannotUnlockNewRequest],
    ['人工完整流程90秒上限', manualWholeFlowDeadline],
    ['背景完整流程12秒上限', backgroundWholeFlowDeadline],
    ['決策回應失敗保留舊畫面並允許重試', contextFailureIsNotSuccess],
    ['Reader 人工純讀與12秒上限', readerManualDeadline],
    ['晚到工作進度不覆寫逾時結果', lateStatusCannotOverwriteTimeout]
  ];
  let failures = 0;
  for (const [label, run] of cases) {
    try { await run(); console.log('通過：' + label); }
    catch (error) { failures++; console.error('失敗：' + label + '\n' + error.stack); }
  }
  assert.equal(failures, 0, '決策更新狀態回歸不得有失敗');
  console.log('決策更新狀態：10組完整正式模組行為驗證通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

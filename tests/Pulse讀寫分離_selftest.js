'use strict';

// 執行正式資料層與面板生命週期；網路與時間受控，不連線正式服務。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const snapshot = id => ({ ok: true, id, breadthOk: true, dataCompleteness: 100,
  decisionSummary: { snapshotId: 'dc-' + id, revision: 1, regime: { id } } });
const contextPayload = id => ({ id, regime: { id }, snapshotId: 'dc-' + id });
function element() {
  return { innerHTML: '', textContent: '', disabled: false, open: false, handlers: {},
    classList: { add() {}, remove() {}, toggle() {} }, setAttribute() {}, getAttribute: () => null,
    querySelector: () => null, querySelectorAll: () => [], appendChild() {},
    addEventListener(type, fn) { this.handlers[type] = fn; } };
}
function harness(role = 'owner', panel = '') {
  const requests = [], timers = new Map(), intervals = new Map(), nodes = new Map(), rendered = [], events = [];
  let timerId = 0, now = 1000000;
  for (const id of ['pl-body', 'pl-refresh', 'pl-update-status', 'dc-refresh', 'dc-update-status',
    'dc-options-lab', 'dc-options-refresh', 'dc-options-refresh-status', 'dc-oi-lab', 'dc-oi-refresh', 'dc-oi-refresh-status']) nodes.set(id, element());
  const testBody = element(), saved = new Map();
  const c = {
    console, Promise, Math, AbortController, Date: class extends Date { static now() { return now; } },
    location: { origin: 'http://test.invalid' }, SERVER: 'http://test.invalid',
    ST_PRIVATE_WEB_PROFILE: role === 'local' ? undefined : { role },
    Store: { positions: { '2330': { shares: 100, entry: 1000 } } },
    localStorage: { getItem: k => saved.get(k) || null, setItem: (k, v) => saved.set(k, v) },
    document: { getElementById: id => nodes.get(id) || null, querySelector: () => null,
      createElement: element, head: { appendChild() {} } },
    ShellV5: { route: () => panel },
    CustomEvent: function (type, init) { this.type = type; this.detail = init.detail; },
    dispatchEvent(event) { events.push(event); }, addEventListener() {},
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, at: now + ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval(fn, ms) { const id = ++timerId; intervals.set(id, { fn, ms }); return id; },
    clearInterval(id) { intervals.delete(id); },
    testBody, testRendered: rendered,
    fetch(url, options = {}) {
      let resolve, reject;
      const promise = new Promise((a, b) => { resolve = a; reject = b; });
      const request = { path: new URL(url, 'http://test.invalid').pathname + new URL(url, 'http://test.invalid').search,
        method: options.method || 'GET', options, resolve, reject, ignoreAbort: false };
      requests.push(request);
      const abort = () => { if (!request.ignoreAbort) { const error = new Error('測試取消'); error.name = 'AbortError'; reject(error); } };
      if (options.signal) {
        if (options.signal.aborted) abort();
        else options.signal.addEventListener('abort', abort, { once: true });
      }
      return promise;
    }
  };
  c.window = c; vm.createContext(c);
  vm.runInContext(fs.readFileSync(path.join(root, 'src/core/decision_data_v5.js'), 'utf8'), c);
  if (panel) {
    const api = panel === 'pulse' ? 'PulseV5' : 'DecisionV5';
    let source = fs.readFileSync(path.join(root, 'src/ui/' + panel + '_v5.js'), 'utf8');
    const setup = 'ensureMount = function () { return window.testBody; };\n' + (panel === 'pulse'
      ? 'render = function (pack) { lastPack = pack; window.testRendered.push(pack.pulse.id); }; fetchWlQuotes = async function () { return {}; };'
      : 'render = function (ctx) { lastContext = ctx; window.testRendered.push(ctx.id); };\n' +
        'window.testBindOptions = bindOptionsLab; window.testBindResearch = bindSessionMomentumLab;');
    source = source.replace('  window.' + api + ' = ', setup + '\n  window.' + api + ' = ');
    vm.runInContext(source, c);
  }
  return { c, requests, timers, intervals, nodes, rendered, events, testBody,
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const next = [...timers].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        now = next[1].at; timers.delete(next[0]); next[1].fn(); await tick();
      }
      now = target; await tick();
    },
    async poll() { for (const timer of [...intervals.values()]) timer.fn(); await tick(); }
  };
}
function complete(request, payload, status = 200) {
  assert(request, '必須存在對應請求');
  request.resolve({ ok: status >= 200 && status < 300, status,
    json: async () => payload, text: async () => JSON.stringify(payload) });
}
const calls = h => h.requests.map(r => r.method + ' ' + r.path);
const last = h => h.requests.at(-1);
const job = (status, extra = {}) => ({ jobId: 'pulse-工作一', status, ...extra });

async function coreReadBoundary() {
  for (const role of ['local', 'owner', 'reader', 'unknown']) {
    const h = harness(role);
    const result = h.c.DecisionData.refreshPulse({ update: role === 'reader' || role === 'unknown' });
    complete(last(h), { ok: false, error: '尚未有已提交快照', updateState: { job: job('queued') } });
    assert.equal((await result).job.status, 'queued');
    assert.deepEqual(calls(h), ['GET /pulse'], '冷啟動及 Reader 手動讀取不得建立 canonical 市場資料');
    assert.equal(h.timers.size, 0);
  }
  console.log('通過：Pulse canonical 市場讀取與冷啟動不送控制 POST');
}

async function manualLifecycle() {
  const h = harness(), states = [];
  const work = h.c.DecisionData.refreshPulse({ update: true, onStatus: j => states.push(j.status) });
  assert.equal(last(h).options.body, '{}');
  complete(last(h), { ok: true, job: job('queued'), coalesced: true }, 202); await tick();
  await h.advance(1000); complete(last(h), { ok: true, job: job('running') }); await tick();
  await h.advance(1000); complete(last(h), { ok: true, job: job('succeeded', { snapshotId: 'dc-新', revision: 9 }) }); await tick();
  complete(last(h), snapshot('新')); const result = await work;
  assert.deepEqual(calls(h), ['POST /pulse/refresh', 'GET /pulse/update-status?jobId=pulse-%E5%B7%A5%E4%BD%9C%E4%B8%80',
    'GET /pulse/update-status?jobId=pulse-%E5%B7%A5%E4%BD%9C%E4%B8%80', 'GET /pulse']);
  assert.deepEqual(states, ['queued', 'running', 'succeeded']);
  assert.equal(result.pulse.id, '新'); assert.equal(result.job.revision, 9); assert.equal(result.coalesced, true);
  assert.equal(h.timers.size, 0);
  for (const terminal of ['failed', 'interrupted']) {
    const f = harness(); const failed = f.c.DecisionData.refreshPulse({ update: true });
    complete(last(f), { ok: true, job: job(terminal, { error: '測試來源失敗' }) }, 202); await tick();
    complete(last(f), snapshot('上一版')); const result = await failed;
    assert.equal(result.error, '測試來源失敗'); assert.equal(result.pulse.id, '上一版');
    assert.deepEqual(calls(f), ['POST /pulse/refresh', 'GET /pulse']);
  }
  console.log('通過：Owner 工作佇列、合併、jobId 輪詢及成功／失敗／中斷終態讀取');
}

async function cancellationAndProtocol() {
  const h = harness(), controller = new AbortController();
  const work = h.c.DecisionData.refreshPulse({ update: true, signal: controller.signal });
  const rejected = assert.rejects(work, { name: 'AbortError' });
  complete(last(h), { ok: true, job: job('queued') }, 202); await tick();
  controller.abort(); await rejected; await h.advance(100000);
  assert.deepEqual(calls(h), ['POST /pulse/refresh'], '離頁不送取消伺服器工作的請求');
  assert.equal(h.timers.size, 0);
  const t = harness(); const timeout = t.c.DecisionData.refreshPulse({ update: true });
  const timedOut = assert.rejects(timeout, { name: 'TimeoutError' });
  complete(last(t), { ok: true, job: job('running') }, 202); await tick();
  await t.advance(90000); await timedOut;
  assert.equal(t.timers.size, 0, '90 秒到期須清除輪詢與逾時計時器');
  const m = harness(); const mismatch = m.c.DecisionData.refreshPulse({ update: true });
  const mismatchFailure = assert.rejects(mismatch, /狀態不一致/);
  complete(last(m), { ok: true, job: job('queued') }, 202); await tick(); await m.advance(1000);
  complete(last(m), { ok: true, job: job('succeeded', { jobId: '別的工作' }) }); await mismatchFailure;
  assert.equal(m.requests.length, 2, '其他工作的成功不可當成目前工作完成');
  console.log('通過：離頁取消、有界等候及工作識別不一致拒收');
}

async function personalAndResearchBoundary() {
  for (const role of ['owner', 'reader']) {
    const h = harness(role);
    const work = h.c.DecisionData.refresh({ holdings: [{ sym: '2330', weight: 100 }], riskProfile: { maxExposure: 0.5 } });
    assert.equal(last(h).method, role === 'owner' ? 'POST' : 'GET');
    if (role === 'owner') assert.equal(JSON.parse(last(h).options.body).holdings[0].sym, '2330');
    complete(last(h), contextPayload('目前')); await work; await tick();
    assert.equal(last(h).path, '/research/overnight-intraday?market=all');
    complete(last(h), { ok: false, error: '研究快取待更新' }); await tick();
    assert(!calls(h).some(call => call.includes('/refresh')), '缺值不得自動建立研究或市場快照');
    const explicit = h.c.DecisionData.refreshOvernightResearch(true);
    complete(last(h), { ok: false }); await tick();
    if (role === 'owner') {
      assert.equal(last(h).method, 'POST');
      assert.match(last(h).path, /^\/research\/overnight-intraday\/refresh/);
      complete(last(h), { ok: true, status: 'ready' });
    } else assert.equal(last(h).method, 'GET');
    await explicit;
  }
  console.log('通過：Owner 個人化純計算保留、Reader 只 GET、研究缺值不自動補建');
}

async function pulsePanel() {
  const h = harness('owner', 'pulse');
  h.c.PulseV5.activate(); complete(last(h), snapshot('已提交')); await tick();
  assert.deepEqual(h.rendered, ['已提交']);
  await h.poll(); complete(last(h), { ...snapshot('待更新'), breadthOk: false }); await tick();
  assert.deepEqual(calls(h), ['GET /pulse', 'GET /pulse']); assert.equal(h.timers.size, 0);
  assert.match(h.nodes.get('pl-update-status').textContent, /資料待更新/);
  const update = h.c.PulseV5.refresh(); complete(last(h), { ok: true, job: job('queued') }, 202); await tick();
  await h.poll(); assert.equal(h.requests.length, 3, '背景讀取不可中斷手動工作');
  await h.advance(1000); complete(last(h), { ok: true, job: job('failed', { error: '來源暫停' }) }); await tick();
  complete(last(h), snapshot('待更新')); await update;
  assert.match(h.nodes.get('pl-update-status').textContent, /來源暫停.*保留/);
  assert.equal(h.rendered.at(-1), '待更新');
  await h.poll(); const old = last(h); old.ignoreAbort = true; h.c.PulseV5.deactivate();
  h.c.PulseV5.activate(); complete(last(h), snapshot('重入')); await tick();
  complete(old, snapshot('離頁舊回應')); await tick();
  assert.equal(h.rendered.at(-1), '重入'); assert(!h.rendered.includes('離頁舊回應'));
  const reader = harness('reader', 'pulse');
  const read = reader.c.PulseV5.refresh(); complete(last(reader), snapshot('Reader')); await read;
  assert.deepEqual(calls(reader), ['GET /pulse']);
  assert.match(reader.nodes.get('pl-refresh').textContent, /重新讀取/);
  console.log('通過：Pulse activate／poll 純讀、不自動暖快取、手動工作失敗保留與離頁晚回應');
}

async function decisionPanel() {
  for (const role of ['owner', 'reader']) {
    const h = harness(role, 'decision');
    h.c.DecisionV5.activate(); complete(last(h), snapshot('已提交')); await tick();
    assert.equal(last(h).path, '/decision/context');
    assert.equal(last(h).method, role === 'owner' ? 'POST' : 'GET', '背景須保留 Owner 持倉純計算');
    complete(last(h), contextPayload('決策')); await tick(); complete(last(h), { ok: false }); await tick();
    assert.equal(h.rendered.at(-1), '決策');
    assert(!calls(h).includes('POST /pulse/refresh'));
    await h.advance(60000); await h.poll(); complete(last(h), snapshot('輪詢')); await tick();
    assert.equal(last(h).path, '/decision/context'); complete(last(h), contextPayload('輪詢決策')); await tick();
    h.c.testBindOptions(); h.c.testBindResearch();
    const before = h.requests.length;
    h.nodes.get('dc-options-lab').open = true; h.nodes.get('dc-options-lab').handlers.toggle();
    assert.equal(h.requests.length, before, '展開期權面板不得自動更新');
    if (role === 'reader') {
      h.nodes.get('dc-options-refresh').onclick({ preventDefault() {}, stopPropagation() {} });
      h.nodes.get('dc-oi-refresh').onclick({ preventDefault() {}, stopPropagation() {} });
      assert.equal(h.requests.length, before); assert(calls(h).every(call => call.startsWith('GET ')));
      const read = h.c.DecisionV5.refreshMarketData(); complete(last(h), snapshot('Reader 手動')); await tick();
      complete(last(h), contextPayload('Reader 手動')); await read;
      assert(!calls(h).some(call => call.startsWith('POST ')));
    } else {
      h.nodes.get('dc-options-refresh').onclick({ preventDefault() {}, stopPropagation() {} });
      assert.equal(last(h).path, '/options/txo/refresh'); assert.equal(last(h).method, 'POST');
      complete(last(h), contextPayload('明確期權更新')); await tick();
      const refresh = h.c.DecisionV5.refreshMarketData();
      complete(last(h), { ok: true, job: job('succeeded') }, 202); await tick();
      complete(last(h), snapshot('手動')); await tick(); complete(last(h), contextPayload('手動個人化')); await refresh;
      assert.equal(h.rendered.at(-1), '手動個人化');
    }
    h.c.DecisionV5.deactivate();
  }
  const h = harness('owner', 'decision');
  const work = h.c.DecisionV5.refreshMarketData({ background: true }); complete(last(h), snapshot('舊')); await tick();
  const lateContext = last(h); lateContext.ignoreAbort = true;
  h.c.DecisionV5.deactivate(); complete(lateContext, contextPayload('離頁個人化')); await work;
  assert.equal(h.rendered.length, 0); assert.equal(h.c.DecisionData.get().context, null, '離頁回應不可發布全域個人化狀態');
  console.log('通過：Decision 背景 canonical 純讀保留個人化、Reader 控制守衛與離頁個人化拒收');
}

(async () => {
  await coreReadBoundary(); await manualLifecycle(); await cancellationAndProtocol();
  await personalAndResearchBoundary(); await pulsePanel(); await decisionPanel();
  console.log('Pulse 讀寫分離行為測試全部通過。');
})().catch(error => { console.error(error); process.exitCode = 1; });

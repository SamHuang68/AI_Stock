'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/ui/stock_health_v5.js'), 'utf8');
const kernel = fs.readFileSync(path.join(root, 'src/core/app_kernel_v5.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const calls = [], listeners = {};
  const scope = { console, Promise, WeakMap, Date, AbortController,
    location: { origin: 'http://fixture.invalid' },
    S: { sym: '2330', mkt: 'TW', tab: 'health', wl: [] },
    ShellV5: { route: () => scope.route }, route: 'chart',
    localStorage: { getItem() { return null; }, setItem() {} },
    document: { getElementById() { return {}; } },
    addEventListener(type, handler) { listeners[type] = handler; },
    AppKernel: { api: {
      getJson(url, options) {
        if (url.includes('push-config')) return Promise.resolve({});
        // 刻意讓取消後仍能收到遲到回覆，驗證目前卡片的畫面歸屬。
        return new Promise((resolve, reject) => calls.push({ url, options, resolve, reject }));
      }, postJson() { return Promise.resolve({}); }
    } }
  };
  scope.window = scope;
  vm.createContext(scope); vm.runInContext(source, scope);
  let html = '', retry;
  const el = { id: 'rpanel', isConnected: true, firstElementChild: null,
    get innerHTML() { return html; },
    set innerHTML(value) { html = value; this.firstElementChild = {}; retry = {}; },
    querySelector(selector) { return selector === '[data-sh5-retry]' ? retry : null; },
    querySelectorAll() { return []; }
  };
  scope.document.getElementById = id => id === 'rpanel' ? el : {};
  return { scope, el, calls, H: scope.StockHealthV5, listeners };
}

async function main() {
  const abort = () => Object.assign(new Error('old abort'), { name: 'AbortError' });
  for (const transition of ['tab', 'route', 'symbol', 'market', 'detached', 'replaced']) {
    const h = harness(); h.H.renderInto(h.el);
    if (transition === 'tab') h.scope.S.tab = 'stats';
    if (transition === 'route') { h.scope.route = 'settings'; h.listeners['shell:route']({ detail: { route: 'settings' } }); }
    if (transition === 'symbol') h.scope.S.sym = '2454';
    if (transition === 'market') h.scope.S.mkt = 'US';
    if (transition === 'detached') h.el.isConnected = false;
    if (transition === 'replaced') h.el.innerHTML = 'CURRENT_STATS';
    const before = h.el.innerHTML;
    h.calls[0].reject(abort()); await flush();
    assert.equal(h.el.innerHTML, before, transition + '：過期失敗不可覆寫目前畫面');
    if (transition === 'route') assert.equal(h.calls[0].options.signal.aborted, true);
  }
  for (const settle of ['success', 'failure']) {
    const h = harness(); h.H.renderInto(h.el); h.H.renderInto(h.el, true);
    assert.equal(h.calls[0].options.signal.aborted, true);
    h.calls[1].resolve({ ok: false, message: 'CURRENT_RESULT' }); await flush();
    const before = h.el.innerHTML;
    if (settle === 'success') h.calls[0].resolve({ ok: false, message: 'OLD_RESULT' });
    else h.calls[0].reject(abort());
    await flush(); assert.equal(h.el.innerHTML, before, '舊請求的 ' + settle + ' 不可替換新結果');
    h.H.renderInto(h.el); assert.match(h.el.innerHTML, /CURRENT_RESULT/, '遲到回覆不可污染快取');
  }
  for (const destination of ['health', 'new-symbol', 'stats']) {
    const h = harness(); h.H.renderInto(h.el);
    h.scope.route = 'settings'; h.listeners['shell:route']({ detail: { route: 'settings' } });
    assert.equal(h.calls[0].options.signal.aborted, true);
    h.calls[0].reject(abort()); await flush();
    h.scope.route = 'chart';
    if (destination === 'stats') h.scope.S.tab = 'stats';
    const opts = destination === 'new-symbol' ? { sym: '2454', mkt: 'TW' } : {};
    h.listeners['shell:route']({ detail: { route: 'chart', opts } });
    if (destination === 'health') {
      assert.equal(h.calls.length, 2, '離開後返回圖表的路由事件應自動恢復體檢請求');
      assert.equal(h.calls[1].options.signal.aborted, false);
      h.calls[1].resolve({ ok: false, message: 'RETURNED_RESULT' }); await flush();
      assert.match(h.el.innerHTML, /RETURNED_RESULT/, '返回後不需其他刷新就能顯示體檢結果');
    } else {
      assert.equal(h.calls.length, 1, '新選股或非體檢分頁不可先發出舊股體檢請求');
    }
  }
  {
    const h = harness(); h.H.renderInto(h.el); h.H.renderInto(h.el);
    assert.equal(h.calls.length, 1, '同一張讀取中卡片沿用既有請求');
    h.calls[0].reject(Object.assign(new Error('deadline'), { name: 'TimeoutError' })); await flush();
    assert.match(h.el.innerHTML, /體檢讀取逾時/); assert.match(h.el.innerHTML, /重試體檢/);
    h.el.querySelector('[data-sh5-retry]').onclick();
    assert.equal(h.calls.length, 2); assert.equal(h.calls[1].options.signal.aborted, false);
    h.calls[1].resolve({ ok: false, message: 'RECOVERED' }); await flush();
    assert.match(h.el.innerHTML, /RECOVERED/);
  }
  for (const method of ['getJson', 'postJson']) {
    const timers = new Map(); let next = 0, bodyStarted = false, finish;
    const scope = { AbortController, AbortSignal, location: { origin: 'http://fixture.invalid' },
      setTimeout(fn) { timers.set(++next, fn); return next; }, clearTimeout(id) { timers.delete(id); },
      fetch(url, options) { return Promise.resolve({ ok: true, json() {
        bodyStarted = true;
        return new Promise((resolve, reject) => { finish = resolve;
          options.signal.addEventListener('abort', () => reject(abort()), { once: true });
        });
      } }); }
    };
    scope.window = scope; vm.createContext(scope); vm.runInContext(kernel, scope);
    const api = scope.AppKernel.api;
    const pending = method === 'getJson' ? api.getJson('/stock-signals', { timeoutMs: 45000 }) :
      api.postJson('/fixture', {}, { timeoutMs: 45000 });
    await flush(); assert.equal(bodyStarted, true); assert.equal(timers.size, 1, method + ' 截止時間必須涵蓋 JSON 本文');
    const rejected = assert.rejects(pending, { name: 'TimeoutError' });
    [...timers.values()][0](); await rejected; assert.equal(timers.size, 0);
    const retry = scope.AppKernel.api.getJson('/stock-signals'); await flush(); finish({ ok: true });
    assert.equal((await retry).ok, true); assert.equal(timers.size, 0);
    const caller = new AbortController();
    const canceled = scope.AppKernel.api.getJson('/stock-signals', { signal: caller.signal });
    await flush(); const canceledCheck = assert.rejects(canceled, { name: 'AbortError' });
    caller.abort(); await canceledCheck; assert.equal(timers.size, 0);
  }
  for (const useSignalAny of [true, false]) {
    const bodies = [], timers = new Map(); let next = 0;
    const scope = { AbortController, AbortSignal: useSignalAny ? AbortSignal : {},
      location: { origin: 'http://fixture.invalid' },
      setTimeout(fn) { timers.set(++next, fn); return next; }, clearTimeout(id) { timers.delete(id); },
      fetch(url, options) { return Promise.resolve({ ok: true, clone() { return this; }, text() {
        return new Promise((resolve, reject) => { bodies.push({ resolve, signal: options.signal });
          options.signal.addEventListener('abort', () => reject(abort()), { once: true });
        });
      } }); }
    };
    scope.window = scope; vm.createContext(scope); vm.runInContext(kernel, scope);
    const first = new AbortController(), second = new AbortController();
    const a = await scope.AppKernel.api.request('/stream', { signal: first.signal });
    const b = await scope.AppKernel.api.request('/stream', { signal: second.signal });
    assert.equal(timers.size, 0, '原始回應取得標頭後交還串流控制權');
    const aBody = a.text(), bBody = b.text();
    const canceled = assert.rejects(aBody, { name: 'AbortError' });
    first.abort(); await canceled;
    assert.equal(bodies[1].signal.aborted, false, '獨立呼叫端不得互相取消');
    bodies[1].resolve('完整串流'); assert.equal(await bBody, '完整串流');
  }
  console.log('體檢請求驗收通過：遲到回覆、路由／分頁／市場歸屬、重試、完整 JSON 截止時間及獨立串流取消。');
}
main().catch(error => { console.error(error); process.exitCode = 1; });

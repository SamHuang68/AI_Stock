'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const tick = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
function harness() {
  const nodes = new Map(), pending = [], timers = new Map(), intervals = new Map();
  let id = 0;
  class Element {
    constructor(id = '') { this.id = id; this.style = {}; this.value = ''; this.children = []; this._text = ''; }
    set innerHTML(html) {
      this.html = html; this._text = '';
      this.children.forEach(child => child.remove()); this.children = [];
      for (const match of html.matchAll(/id="([^"]+)"/g)) {
        const el = new Element(match[1]); nodes.set(el.id, el); this.children.push(el);
      }
    }
    get innerHTML() { return this.html || ''; }
    set textContent(value) { this.innerHTML = ''; this._text = value; }
    get textContent() { return this._text; }
    appendChild(el) { nodes.set(el.id, el); this.children.push(el); }
    remove() { this.children.forEach(child => child.remove()); if (nodes.get(this.id) === this) nodes.delete(this.id); }
    querySelectorAll() { return []; }
    focus() {}
  }
  const ctx = { console, Date, TextDecoder, Uint8Array, AbortController, JSON, Math,
    Market: { of: symbol => symbol === '7203.T' ? 'JP' : symbol === 'AAPL' ? 'US' : 'TW' },
    document: { head: new Element(), body: new Element(), createElement: () => new Element(),
      getElementById: id => nodes.get(id), querySelectorAll: () => [nodes.get('cp-send')].filter(Boolean) },
    S: { sym: '2330', mkt: 'TW', data: { meta: { symbol: '2330.TW' }, candles: [{ time: '2026-09-14', close: 100 }] }, positions: {}, watches: {} },
    setTimeout(fn, ms) { timers.set(++id, { fn, ms }); return id; }, clearTimeout(id) { timers.delete(id); },
    setInterval(fn) { intervals.set(++id, fn); return id; }, clearInterval(id) { intervals.delete(id); },
    fetch(url, options) {
      if (url.endsWith('/status')) return Promise.resolve({ json: async () => ({ ok: true, modes: { fast: { available: true } } }) });
      // 刻意不響應 abort；測試 Promise 仍會結束，過期回覆不能寫入新畫面。
      return new Promise((resolve, reject) => { pending.push({ url, options, resolve, reject }); });
    }
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  for (const file of ['src/ai/ai_runtime_client.js', 'src/ai/copilot_v3.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), ctx);
  }
  return { ctx, nodes, pending, timers, intervals };
}
function response(request, { frames, raw, type = 'text/event-stream', status = 200, noReader = false, crlf = false } = {}) {
  let source = raw === undefined ? (frames || []).map(f => 'data: ' + JSON.stringify(f) + '\n\n').join('') : raw;
  if (crlf) source = source.replace(/\n/g, '\r\n');
  // 每個 UTF-8 位元組都切開，包含 CRLF 與繁體中文。
  const bytes = new TextEncoder().encode(source), chunks = [];
  for (let i = 0; i < bytes.length; i++) chunks.push(bytes.slice(i, i + 1));
  request.resolve({ ok: status === 200, status, headers: { get(name) { return name === 'Content-Type' ? type : ''; } },
    text: async () => source,
    body: noReader ? null : { getReader: () => ({ read: async () => chunks.length ? { value: chunks.shift() } : { done: true }, cancel: async () => {} }) }
  });
}
const good = text => [{ type: 'delta', text }, { type: 'done' }];
(async function () {
  const net = harness();
  const normal = net.ctx.STAI.request({ prompt: '測試' });
  response(net.pending.at(-1), { frames: good('繁體正文'), crlf: true });
  assert.equal((await normal.promise).text, '繁體正文');
  assert.equal(net.intervals.size, 0);
  assert.equal(net.timers.size, 0);
  for (const [frames, pattern] of [
    [[{ type: 'delta', text: '部分正文' }], /未收到完成確認/],
    [[{ type: 'delta', text: '部分正文' }, { type: 'error', message: '未完成' }], /未完成/],
    [[{ type: 'done' }], /未回傳可見內容/],
    [[{ type: 'delta', text: '  ' }, { type: 'done' }], /未回傳可見內容/],
    [[{ type: 'unexpected' }], /格式不符/],
  ]) {
    const req = net.ctx.STAI.request({ prompt: '測試' });
    response(net.pending.at(-1), { frames });
    await assert.rejects(req.promise, pattern);
  }
  for (const status of [401, 403, 503]) {
    const req = net.ctx.STAI.request({ prompt: '測試', requestId: 'decision-fixture' });
    assert.equal(net.pending.at(-1).options.headers['X-ST-Trace-ID'], 'decision-fixture');
    response(net.pending.at(-1), { status, raw: JSON.stringify({ error: '無法使用 ' + status }) });
    await assert.rejects(req.promise, error => error.status === status && error.requestId === 'decision-fixture' && error.detail.includes(String(status)));
  }
  const external = new AbortController();
  const delegated = net.ctx.STAI.request({ prompt: '測試', signal: external.signal });
  external.abort();
  await assert.rejects(delegated.promise, { name: 'AbortError' });
  assert.equal(net.pending.at(-1).options.signal.aborted, true);
  const timeout = net.ctx.STAI.request({ prompt: '測試', timeoutMs: 123 });
  [...net.timers.values()].find(t => t.ms === 123).fn();
  await assert.rejects(timeout.promise, /超過上限/);
  assert.equal(net.pending.at(-1).options.signal.aborted, true);
  assert.equal(net.intervals.size, 0);
  const cancelled = net.ctx.STAI.request({ prompt: '測試' });
  cancelled.cancel();
  await assert.rejects(cancelled.promise, { name: 'AbortError' });
  assert.equal(net.timers.size, 0);
  const legacy = net.ctx.STAI.request({ prompt: '測試' });
  response(net.pending.at(-1), { type: 'text/plain', raw: '半截正文\n⚠ 失敗' });
  await assert.rejects(legacy.promise, /回應格式不符/);
  const unsupported = net.ctx.STAI.request({ prompt: '測試', endpoint: '/ai-report' });
  await assert.rejects(unsupported.promise, /端點不受支援/);
  assert.match(net.ctx.STAI.context(), /2026-09-14/);
  net.ctx.S.sym = '2885';
  assert.match(net.ctx.STAI.context(), /行情載入中/);
  assert.doesNotMatch(net.ctx.STAI.context(), /收盤：100/);
  for (const [symbol, market] of [['7203.T', 'JP'], ['^TWOII', 'TW'], ['AAPL', 'US']]) {
    net.ctx.S.sym = symbol; net.ctx.S.mkt = market; net.ctx.S.data.meta.symbol = symbol;
    assert.match(net.ctx.STAI.context(), /收盤：100/);
  }
  net.ctx.S.positions = { AAPL: { shares: 0, entry: null } };
  assert.match(net.ctx.STAI.context(), /股數 0，成本 未提供/);

  const cp = harness(); cp.ctx.copilotOpen(); cp.nodes.get('cp-text').value = '測試';
  cp.nodes.get('cp-send').onclick(); cp.nodes.get('cp-send').onclick(); await tick();
  assert.equal(cp.pending.length, 1, '重複點擊只送一份');
  assert.equal(cp.nodes.get('cp-send').disabled, true);
  const oldNode = cp.nodes.get('cp-out'); cp.ctx.copilotOpen();
  assert.equal(cp.nodes.get('cp-out'), oldNode, '等待中再開面板不重建內容');
  response(cp.pending[0], { frames: good('副駕正文 <img src=x>'), noReader: true }); await tick();
  assert.match(cp.nodes.get('cp-out').innerHTML, /副駕正文 &lt;img/);
  assert.equal(cp.nodes.get('cp-send').disabled, false);
  cp.nodes.get('cp-send').onclick(); await tick();
  cp.nodes.get('cp-cancel').onclick(); await tick();
  assert.match(cp.nodes.get('cp-status').textContent, /已取消/);
  assert.equal(cp.nodes.get('cp-send').disabled, false);
  assert.equal(cp.nodes.get('cp-keep'), undefined, '未完成不得保留或寄送');
  cp.nodes.get('cp-send').onclick(); await tick();
  const stale = cp.pending.at(-1);
  cp.ctx.copilotClose(); cp.ctx.copilotOpen(); cp.nodes.get('cp-text').value = '新問題';
  cp.nodes.get('cp-send').onclick();
  response(cp.pending.at(-1), { frames: good('新結果'), noReader: true }); await tick();
  response(stale, { frames: good('過期結果'), noReader: true }); await tick();
  assert.match(cp.nodes.get('cp-out').innerHTML, /新結果/);
  assert.doesNotMatch(cp.nodes.get('cp-out').innerHTML, /過期結果/);
  assert.equal(cp.pending.filter(p => p.url === '/notify').length, 0, '測試不寄送通知');
  console.log('AI 串流驗證通過：完成契約、截斷失敗、UTF-8、取消、逾時、快照歸屬與過期回覆。');
})().catch(error => { console.error(error); process.exitCode = 1; });

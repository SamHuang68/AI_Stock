'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const tick = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function harness() {
  const nodes = new Map(), pending = [], timers = new Map(), intervals = new Map(), saved = new Map();
  let id = 0;
  class Element {
    constructor(id = '') { this.id = id; this.style = {}; this.value = ''; this.textContent = ''; this.children = []; }
    set innerHTML(html) {
      this.html = html;
      this.children.forEach(child => child.remove()); this.children = [];
      for (const match of html.matchAll(/id="([^"]+)"/g)) {
        const el = new Element(match[1]); nodes.set(el.id, el); this.children.push(el);
        if (el.id === 'ai-provider') el.value = 'local';
      }
    }
    get innerHTML() { return this.html || ''; }
    appendChild(el) { nodes.set(el.id, el); this.children.push(el); }
    remove() { this.children.forEach(child => child.remove()); if (nodes.get(this.id) === this) nodes.delete(this.id); }
    addEventListener() {}
    querySelectorAll() { return []; }
    focus() {}
  }
  const ctx = { console, Date, TextDecoder, Uint8Array, AbortController, JSON, Math,
    Market: { of: symbol => symbol === '7203.T' ? 'JP' : symbol === 'AAPL' ? 'US' : 'TW' },
    document: { head: new Element(), body: new Element(), createElement: () => new Element(),
      getElementById: id => nodes.get(id), querySelectorAll: () => [nodes.get('cp-send')].filter(Boolean) },
    localStorage: { getItem: k => saved.get(k), setItem: (k, v) => saved.set(k, v) },
    S: { sym: '2330', mkt: 'TW', data: { meta: { symbol: '2330.TW' }, candles: [{ time: '2026-09-14', close: 100 }] }, positions: {}, watches: {}, aiKeySet: false },
    setTimeout(fn, ms) { timers.set(++id, { fn, ms }); return id; }, clearTimeout(id) { timers.delete(id); },
    setInterval(fn) { intervals.set(++id, fn); return id; }, clearInterval(id) { intervals.delete(id); },
    fetch(url, options) {
      if (url.endsWith('/status')) return Promise.resolve({ json: async () => ({ ok: true, modes: { fast: { available: true } } }) });
      return new Promise((resolve, reject) => { pending.push({ url, options, resolve, reject }); });
    },
    alert(message) { throw new Error('意外提示：' + message); },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  const load = file => vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), ctx);
  load('src/ai/ai_runtime_client.js'); load('src/ai/ai_report_v3.js'); load('src/ai/copilot_v3.js');
  return { ctx, nodes, pending, timers, intervals, saved, load };
}
function response(request, { frames, raw, type = 'text/event-stream', status = 200, noReader = false } = {}) {
  const source = raw === undefined ? (frames || []).map(f => 'data: ' + JSON.stringify(f) + '\n\n').join('') : raw;
  // 刻意拆開 UTF-8 多位元組，驗證串流解碼與完成事件跨區塊。
  const bytes = new TextEncoder().encode(source), chunks = [];
  for (let i = 0; i < bytes.length; i += 7) chunks.push(bytes.slice(i, i + 7));
  request.resolve({ ok: status === 200, status, headers: { get(name) { return name === 'Content-Type' ? type : ''; } },
    text: async () => source, json: async () => JSON.parse(source),
    body: noReader ? null : { getReader: () => ({ read: async () => chunks.length ? { value: chunks.shift() } : { done: true }, cancel: async () => {} }) }
  });
}
const good = text => [{ type: 'delta', text }, { type: 'done' }];
(async function () {
  const h = harness();
  h.ctx.openAIModal();
  // 重現真實導覽橋接：舊版生成再次呼叫包裝後入口，100ms 後把面板拆掉。
  h.ctx.ShellV5 = { go() {} };
  h.load('src/ui/bridge_v5.js');
  const originalBody = h.nodes.get('ai-body');
  const work = h.ctx.generateAIReport();
  await h.ctx.generateAIReport();
  assert.equal(h.pending.length, 1, '連續生成只送一份');
  assert.equal(h.pending[0].url, '/ai/local', '無金鑰仍可用本機報告');
  assert.equal(h.nodes.get('ai-generate').disabled, true);
  assert.match(originalBody.textContent, /正在準備/);
  for (const task of h.timers.values()) if (task.ms === 100) task.fn();
  assert.equal(h.nodes.get('ai-body'), originalBody, '生成不能重建導覽面板');
  response(h.pending[0], { frames: good('研究正文 **完成** <img src=x onerror=alert(1)>') });
  await work;
  assert.match(originalBody.innerHTML, /研究正文/);
  assert.match(originalBody.innerHTML, /&lt;img/);
  assert.doesNotMatch(originalBody.innerHTML, /<img/);
  assert.equal(h.nodes.get('ai-generate').disabled, false);
  assert.equal(h.intervals.size, 0);
  const saved = h.saved.get('ai_report_last');

  let failed = h.ctx.generateAIReport();
  response(h.pending.at(-1), { frames: [{ type: 'delta', text: '不完整' }, { type: 'error', message: '模型忙碌' }] });
  await failed;
  assert.match(h.nodes.get('ai-status').textContent, /未完成.*模型忙碌/);
  assert.equal(h.saved.get('ai_report_last'), saved, '錯誤與半截正文不能存成成功');
  failed = h.ctx.generateAIReport();
  response(h.pending.at(-1), { frames: [{ type: 'delta', text: '中途斷線' }] });
  await failed;
  assert.match(h.nodes.get('ai-status').textContent, /未收到完成確認/);

  const old = h.ctx.generateAIReport(), oldRequest = h.pending.at(-1);
  h.ctx.closeAIModal(); h.ctx.createAIReportModal();
  const newWork = h.ctx.generateAIReport();
  response(h.pending.at(-1), { frames: good('新報告') }); await newWork;
  response(oldRequest, { frames: good('過期報告') }); await old;
  assert.equal(oldRequest.options.signal.aborted, true);
  assert.match(h.nodes.get('ai-body').innerHTML, /新報告/);
  assert.doesNotMatch(h.saved.get('ai_report_last'), /過期報告/);

  h.ctx.S.aiKeySet = true; h.nodes.get('ai-provider').value = 'cloud';
  const cloud = h.ctx.generateAIReport();
  assert.equal(h.pending.at(-1).url, '/ai-report');
  response(h.pending.at(-1), { type: 'application/json', raw: JSON.stringify({ ok: true, report: '模擬雲端結果', model: 'mock' }) });
  await cloud;
  assert.match(h.nodes.get('ai-body').innerHTML, /模擬雲端結果/);

  const cp = harness(); cp.ctx.copilotOpen(); cp.nodes.get('cp-text').value = '測試';
  cp.nodes.get('cp-send').onclick(); cp.nodes.get('cp-send').onclick(); await tick();
  assert.equal(cp.pending.length, 1);
  assert.match(cp.nodes.get('cp-out').textContent, /正在準備/);
  assert.equal(cp.nodes.get('cp-send').disabled, true);
  cp.ctx.copilotOpen();
  response(cp.pending[0], { frames: good('副駕正文'), noReader: true }); await tick();
  assert.match(cp.nodes.get('cp-out').innerHTML, /副駕正文/);
  assert.equal(cp.nodes.get('cp-send').disabled, false);
  cp.nodes.get('cp-send').onclick(); await tick();
  const cancelRequest = cp.pending.at(-1);
  cp.nodes.get('cp-cancel').onclick();
  response(cancelRequest, { frames: good('取消後正文') }); await tick();
  assert.match(cp.nodes.get('cp-status').textContent, /已取消/);
  assert.doesNotMatch(cp.nodes.get('cp-out').innerHTML, /取消後正文/);

  const net = harness();
  for (const status of [401, 403, 503]) {
    const req = net.ctx.STAI.request({ prompt: '測試' });
    response(net.pending.at(-1), { status, raw: JSON.stringify({ error: '無法使用 ' + status }) });
    await assert.rejects(req.promise, new RegExp(String(status)));
  }
  const timeout = net.ctx.STAI.request({ prompt: '測試', timeoutMs: 123 });
  const waiting = net.pending.at(-1);
  [...net.timers.values()].find(t => t.ms === 123).fn();
  response(waiting, { frames: good('逾時後正文') });
  await assert.rejects(timeout.promise, /超過上限/);
  assert.equal(waiting.options.signal.aborted, true);
  assert.equal(net.intervals.size, 0);
  assert.match(net.ctx.STAI.context(), /2026-09-14/);
  net.ctx.S.sym = '2885';
  assert.match(net.ctx.STAI.context(), /行情載入中/);
  assert.doesNotMatch(net.ctx.STAI.context(), /收盤：100/);
  for (const [symbol, market] of [['7203.T', 'JP'], ['^TWOII', 'TW'], ['AAPL', 'US']]) {
    net.ctx.S.sym = symbol; net.ctx.S.mkt = market; net.ctx.S.data.meta.symbol = symbol;
    assert.match(net.ctx.STAI.context(), /收盤：100/);
  }
  const legacy = net.ctx.STAI.request({ prompt: '測試' });
  response(net.pending.at(-1), { type: 'text/plain', raw: '半截正文\n⚠ 失敗' });
  await assert.rejects(legacy.promise, /回應格式不符/);
  console.log('AI 面板驗證通過：導覽重建、等待狀態、重複送出、取消、過期回覆、錯誤、UTF-8 與完成確認。');
})().catch(error => { console.error(error); process.exitCode = 1; });

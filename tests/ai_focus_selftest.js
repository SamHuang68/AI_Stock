'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// 執行完整模組，模擬網路順序與路由生命週期，不依賴真實行情或計時等待。
function harness() {
  const nodes = new Map();
  const pending = [];
  const scheduled = new Map();
  const intervals = new Map();
  const charts = [];
  let clockId = 0;
  class Element {
    constructor(id) { this.id = id; this.attributes = {}; this.textContent = ''; this.html = ''; }
    set innerHTML(value) {
      this.html = value;
      for (const match of value.matchAll(/id="([^"]+)"/g)) nodes.set(match[1], new Element(match[1]));
    }
    get innerHTML() { return this.html; }
    setAttribute(key, value) { this.attributes[key] = value; }
    getAttribute(key) { return this.attributes[key]; }
    appendChild(el) { nodes.set(el.id, el); }
    querySelector() { return null; }
    querySelectorAll(selector) {
      if (selector !== 'tr.ai5-row') return [];
      this.rows = [...this.html.matchAll(/<tr class="ai5-row" data-code="([^"]*)" data-market="([^"]*)"/g)].map(match => {
        const el = new Element('');
        el.attributes = { 'data-code': match[1], 'data-market': match[2] };
        return el;
      });
      return this.rows;
    }
  }
  for (const id of ['view-ai', 'mount-ai', 'ai5-root', 'ai5-body', 'ai5-refresh']) nodes.set(id, new Element(id));
  const document = {
    readyState: 'loading', hidden: false, head: new Element('head'),
    getElementById: id => nodes.get(id), createElement: () => new Element(''), addEventListener() {},
  };
  const window = { SERVER: '', addEventListener() {}, ShellV5: {
    route: () => 'ai', softBadge() {}, openChart: (code, market) => charts.push([code, market]),
  } };
  const context = {
    window, document, localStorage: { getItem: () => null }, AbortController, Date, console,
    loadSym() {}, ShellV5: window.ShellV5,
    setTimeout(fn, ms) { const id = ++clockId; scheduled.set(id, { fn, ms }); return id; },
    clearTimeout(id) { scheduled.delete(id); },
    setInterval(fn) { const id = ++clockId; intervals.set(id, fn); return id; },
    clearInterval(id) { intervals.delete(id); },
    fetch(url, options) {
      return new Promise((resolve, reject) => {
        pending.push({ url, options, resolve, reject });
      });
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/ui/ai_v5.js'), 'utf8'), context);
  return { api: window.AiV5, nodes, pending, scheduled, intervals, charts, document };
}

function reply(request, body, status = 200) {
  request.resolve({ ok: status >= 200 && status < 300, status, json: async () => body });
}
const data = (sym = '2330') => ({ ok: true, mkt: 'TW', scanned: 100, buy: [{ sym, name: '測試股票', score: 4 }], short: [] });

(async () => {
  const h = harness();
  let work = h.api.refresh();
  assert.equal(h.nodes.get('ai5-refresh').disabled, true);
  assert.equal(h.api.refresh({ force: true }), work);
  assert.equal(h.pending.length, 1, '連續點擊只發出一個請求');
  reply(h.pending[0], data());
  await work;
  const initial = h.nodes.get('ai5-body').innerHTML;
  assert.match(initial, /2330/);
  assert.match(h.nodes.get('ai5-status').textContent, /接收時間，非行情時間/);

  for (const status of [401, 403, 429, 503]) {
    work = h.api.refresh({ force: true });
    reply(h.pending.at(-1), {}, status);
    await work;
    assert.equal(h.nodes.get('ai5-body').innerHTML, initial, 'HTTP 失敗保留既有清單');
    assert.match(h.nodes.get('ai5-status').textContent, /保留上次成功清單/);
    assert.equal(h.nodes.get('ai5-refresh').textContent, '↻ 重試更新');
    assert.equal(h.nodes.get('ai5-refresh').disabled, false);
  }
  for (const invalid of [{}, { ok: false, buy: [], short: [] }, { buy: '錯誤格式' }, { buy: [null] }]) {
    work = h.api.refresh();
    reply(h.pending.at(-1), invalid);
    await work;
    assert.equal(h.nodes.get('ai5-body').innerHTML, initial);
    assert.match(h.nodes.get('ai5-status').textContent, /格式不完整/);
  }
  work = h.api.refresh();
  h.pending.at(-1).reject(new TypeError('網路中斷'));
  await work;
  assert.match(h.nodes.get('ai5-status').textContent, /無法連線/);

  work = h.api.refresh();
  const timed = h.pending.at(-1);
  [...h.scheduled.values()].find(item => item.ms === 120000).fn();
  assert.equal(timed.options.signal.aborted, true);
  reply(timed, data('過期回應'));
  await work;
  assert.match(h.nodes.get('ai5-status').textContent, /超過兩分鐘/);
  assert.equal(h.nodes.get('ai5-body').innerHTML, initial);

  work = h.api.refresh();
  reply(h.pending.at(-1), { ok: true, scanned: 100, buy: [], short: [] });
  await work;
  assert.doesNotMatch(h.nodes.get('ai5-body').innerHTML, /2330/);
  assert.doesNotMatch(h.nodes.get('ai5-status').textContent, /保留上次/);

  const oldWork = h.api.refresh();
  const old = h.pending.at(-1);
  h.api.deactivate();
  assert.equal(old.options.signal.aborted, true);
  work = h.api.refresh();
  reply(h.pending.at(-1), data('最新股票'));
  await work;
  reply(old, data('過期股票'));
  await oldWork;
  assert.match(h.nodes.get('ai5-body').innerHTML, /最新股票/);
  assert.doesNotMatch(h.nodes.get('ai5-body').innerHTML, /過期股票/);

  work = h.api.refresh();
  reply(h.pending.at(-1), { ok: true, mkt: 'US', buy: [{ sym: 'AAPL', name: '測試' }], short: [] });
  await work;
  h.nodes.get('ai5-body').rows[0].onclick();
  assert.deepEqual(h.charts, [['AAPL', 'US']], '開圖保留市場代碼');
  assert.match(h.nodes.get('ai5-body').innerHTML, /<button type="button" class="ai5-symbol"/);
  work = h.api.refresh();
  reply(h.pending.at(-1), data('2330" autofocus onfocus="alert(1)'));
  await work;
  assert.match(h.nodes.get('ai5-body').innerHTML, /2330&quot; autofocus/);
  assert.doesNotMatch(h.nodes.get('ai5-body').innerHTML, /data-code="2330" autofocus/);

  const empty = harness();
  work = empty.api.refresh();
  reply(empty.pending[0], {}, 503);
  await work;
  assert.match(empty.nodes.get('ai5-status').textContent, /尚無可用清單/);
  empty.api.activate();
  reply(empty.pending.at(-1), data());
  await empty.api.refresh();
  empty.document.hidden = true;
  const count = empty.pending.length;
  [...empty.intervals.values()][0]();
  assert.equal(empty.pending.length, count, '隱藏分頁不自動掃描');
  empty.api.deactivate();
  assert.equal(empty.intervals.size, 0);
  assert.equal(empty.scheduled.size, 0);
  console.log('通過：清單保留、錯誤分類、重試、逾時、請求去重、路由競態、市場開圖與屬性跳脫。');
})().catch(error => { console.error(error); process.exitCode = 1; });

'use strict';

// 正式 generate 流程搭配確定性的 DOM 幾何、網路、時間與繪圖替身；實際瀏覽器排版另行驗收。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/pdf_export_v3.js'), 'utf8');
const tick = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const pending = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const decode = value => value.replace(/&(?:amp|lt|gt|quot|#39);/g, x => ({ '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" })[x]);
class Node {
  constructor(tag, doc) { this.tagName = tag.toUpperCase(); this.ownerDocument = doc; this.childNodes = []; this.attributes = {}; this.style = {}; this.width = 300; this.height = 150; }
  get children() { return this.childNodes.filter(n => n.tagName !== '#TEXT'); }
  get textContent() { return this.tagName === '#TEXT' ? this.value : this.childNodes.map(n => n.textContent).join(''); }
  set textContent(text) { const n = new Node('#TEXT', this.ownerDocument); n.value = String(text); this.childNodes = []; this.appendChild(n); }
  get id() { return this.attributes.id || ''; }
  set id(value) { this.attributes.id = value; }
  get className() { return this.attributes.class || ''; }
  set className(value) { this.attributes.class = value; }
  appendChild(node) { node.remove(); node.parentNode = this; this.childNodes.push(node); return node; }
  remove() { if (this.parentNode) { const rows = this.parentNode.childNodes; rows.splice(rows.indexOf(this), 1); this.parentNode = null; } }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  removeAttribute(k) { delete this.attributes[k]; }
  getAttribute(k) { return this.attributes[k] || null; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const all = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    return all.filter(n => selector === '*' || (selector.startsWith('#') ? n.id === selector.slice(1) : n.tagName === selector.toUpperCase()));
  }
  cloneNode(deep) {
    const copy = new Node(this.tagName, this.ownerDocument);
    copy.attributes = { ...this.attributes }; copy.style = { ...this.style }; copy.value = this.value; copy.start = this.start;
    if (deep) this.childNodes.forEach(n => copy.appendChild(n.cloneNode(true)));
    return copy;
  }
  set innerHTML(html) {
    this.childNodes = []; const stack = [this];
    for (const token of html.match(/<[^>]*>|[^<]+/g) || []) {
      if (token.startsWith('</')) { stack.pop(); continue; }
      if (token.startsWith('<')) {
        const tag = token.match(/^<([a-z][\w-]*)/i)?.[1]; if (!tag) continue;
        const node = this.ownerDocument.createElement(tag);
        for (const match of token.matchAll(/([\w-]+)="([^"]*)"/g)) node.setAttribute(match[1], decode(match[2]));
        stack.at(-1).appendChild(node);
        if (!['BR', 'COL', 'META', 'IMG', 'INPUT'].includes(node.tagName)) stack.push(node);
      } else { const text = new Node('#TEXT', this.ownerDocument); text.value = decode(token); stack.at(-1).appendChild(text); }
    }
  }
  get rows() { return this.tagName === 'TR' ? [] : this.querySelectorAll('TR'); }
  get cells() { return this.children.filter(n => ['TD', 'TH'].includes(n.tagName)); }
  get tBodies() { return this.children.filter(n => n.tagName === 'TBODY'); }
  get tHead() { return this.children.find(n => n.tagName === 'THEAD'); }
  get clientWidth() { return 852; }
  get scrollWidth() { return 852; }
  getBoundingClientRect() {
    const vertical = this.children.reduce((sum, n) => sum + n.getBoundingClientRect().height, 0);
    let height;
    if (this.id === 'pdf-report-content' || this.className === 'pdf-export-page') height = 64 + vertical;
    else if (['COLGROUP', 'COL'].includes(this.tagName)) height = 0;
    else if (this.tagName === 'TR') height = Math.max(0, ...this.cells.map(n => n.getBoundingClientRect().height));
    else if (['TABLE', 'TBODY', 'THEAD', 'OL'].includes(this.tagName)) height = vertical;
    else if (['TD', 'TH'].includes(this.tagName)) height = 12 + Math.max(1, Math.ceil(this.textContent.trim().length / 28)) * 18;
    else {
      const blockChildren = this.children.filter(n => !['B', 'SPAN', 'BR'].includes(n.tagName));
      const text = this.childNodes.filter(n => n.tagName === '#TEXT' || ['B', 'SPAN'].includes(n.tagName)).map(n => n.textContent).join('').trim();
      height = 12 + blockChildren.reduce((sum, n) => sum + n.getBoundingClientRect().height, 0) + Math.ceil(text.length / 80) * 18;
    }
    return { width: ['TD', 'TH'].includes(this.tagName) ? 130 : 852, height, left: 0, top: 0, right: 852, bottom: height };
  }
  toDataURL() { return 'data:image/jpeg;base64,' + this.pageToken; }
}
function documentFixture(onCreate) {
  const doc = { fonts: { ready: Promise.resolve() }, createElement(tag) {
    const node = new Node(tag, doc);
    if (tag.toLowerCase() === 'iframe') node.contentDocument = documentFixture(onCreate);
    if (onCreate) onCreate(node);
    return node;
  } };
  doc.body = new Node('body', doc); doc.head = new Node('head', doc);
  doc.querySelector = selector => doc.body.querySelector(selector);
  return doc;
}
const plans = count => Object.fromEntries(Array.from({ length: count }, (_, i) => ['p' + i, {
  sym: '股票' + String(i).padStart(4, '0'), mkt: 'TW', role: '主倉',
  longCondition: '條件〈' + i + '〉', outlook: '展望〈' + i + '〉', buyZoneLow: '10.5', buyZoneHigh: '11', resistance: 12, stopLoss: 9
}]));
function harness(options = {}) {
  const alerts = [], renders = [], canvases = [], pdfs = [], requests = [], scripts = [], timers = new Map();
  let now = Date.parse('2026-09-19T18:00:00Z'), timerId = 0;
  const doc = documentFixture(node => { if (node.tagName === 'CANVAS') canvases.push(node); });
  const appendScript = doc.head.appendChild.bind(doc.head);
  doc.head.appendChild = node => { scripts.push(node); return appendScript(node); };
  class PDF {
    constructor() { this.images = []; this.pages = 1; this.internal = { pageSize: { getWidth: () => 595.28, getHeight: () => 841.89 } }; pdfs.push(this); }
    addPage() { this.pages++; }
    addImage(...args) { if (options.addImageError) throw new Error('PDF 編碼失敗'); this.images.push(args); }
    save(filename, settings) { this.saved = { filename, settings }; return options.save ? options.save(this) : Promise.resolve(); }
  }
  PDF.version = '4.2.1';
  const render = (page, config) => {
    const record = { text: page.textContent, node: page.cloneNode(true), width: config.canvas.width, height: config.canvas.height, config };
    renders.push(record); config.canvas.pageToken = String(renders.length);
    if (options.render) return options.render(page, config);
    return Promise.resolve(config.canvas);
  };
  const c = {
    console: { log() {}, error() {} }, structuredClone, AbortController, Intl,
    Date: class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } },
    document: doc, location: { origin: 'http://test.invalid' }, S: { plans: plans(options.count || 1) },
    alert: text => { assert.equal(doc.body.children.length, 0, '顯示結果前必須清除遮罩與暫存文件'); alerts.push(text); },
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, at: now + ms }); return id; }, clearTimeout(id) { timers.delete(id); },
    fetch(url, init) { requests.push({ url, init }); return options.fetch ? options.fetch(url, init) : Promise.resolve({ ok: true, json: async () => ({ trailingPE: '20.5', eps: '4.2', earningsQuarterlyGrowth: '12.5' }) }); }
  };
  if (!options.noLibs) { c.html2canvas = render; c.jspdf = { jsPDF: PDF }; }
  c.window = c; vm.createContext(c); vm.runInContext(source, c);
  return { c, api: c.PlanPdfExport, doc, scripts, alerts, renders, canvases, pdfs, requests, timers,
    install() { c.html2canvas = render; c.jspdf = { jsPDF: PDF }; },
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const next = [...timers].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break; now = next[1].at; timers.delete(next[0]); next[1].fn(); await tick();
      }
      now = target; await tick();
    }
  };
}
function clean(h) { assert.equal(h.doc.body.children.length, 0); assert(h.canvases.every(c => c.width === 0 && c.height === 0)); }

async function completeReport() {
  const save = pending(); const h = harness({ count: 100, save: () => save.promise });
  const work = h.api.generate(); assert.equal(h.api.generate(), work, '重複點擊須共用單一工作');
  h.c.S.plans.p0.outlook = '工作開始後修改'; h.c.S.plans.extra = { sym: '中途加入' };
  for (let i = 0; i < 200 && !h.pdfs[0]?.saved; i++) await tick();
  assert(h.pdfs[0]?.saved, '必須完成真正分頁與組裝後才開始儲存');
  assert.equal(h.alerts.length, 0, '儲存未完成不可回報成功');
  save.resolve(); const result = await work;
  assert.equal(result.ok, true); assert(result.pages > 11); assert.equal(result.pages, h.renders.length);
  assert.equal(h.pdfs[0].pages, result.pages); assert.equal(result.filename, '交易計畫_2026-09-20.pdf');
  assert.equal(h.pdfs[0].saved.settings.returnPromise, true);
  const text = h.renders.map(r => r.text).join('');
  for (let i = 0; i < 100; i++) {
    assert.equal(text.split('展望〈' + i + '〉').length - 1, 1, '每筆展望完整出現一次');
    assert.equal(text.split('條件〈' + i + '〉').length - 1, 3, '總表／排序／個股三處條件均保留');
  }
  assert(!text.includes('工作開始後修改')); assert(!text.includes('中途加入'));
  assert(text.includes('五、總結')); assert(text.includes('100 檔'));
  assert(text.includes('報告產生日期：2026/09/20')); assert(!text.includes('資料基準：')); assert(!text.includes('下周'));
  assert(h.renders.every(r => r.height > 150 && r.height < 2500 && r.width === 1704));
  assert(h.pdfs[0].images.every(args => args[2] === 16 && args[3] === 12 && args[5] <= 817.99), '每頁獨立畫布放在頁內，不可用負偏移重疊');
  assert(h.renders.every(r => r.node.children.at(-1).tagName !== 'H2'), '章節標題不可獨留頁尾');
  const groups = h.renders.flatMap(r => r.node.querySelectorAll('OL'));
  let index = 1;
  for (const group of groups) { assert.equal(group.start, index); index += group.children.length; }
  assert.equal(index, 101);
  for (const table of h.renders.flatMap(r => r.node.querySelectorAll('TABLE'))) assert(table.tHead, '跨頁表格保留欄頭');
  clean(h); assert.equal(h.timers.size, 0);
  console.log('通過：完整超過 11 頁、無重疊缺行、來源快照、單一工作與臺灣日期／儲存完成');
}

async function loadingAndRetry() {
  const h = harness({ noLibs: true }); const first = h.api.generate();
  assert.equal(h.api.generate(), first); assert.equal(h.scripts.length, 2);
  assert(h.scripts.every(s => s.src.startsWith('/assets/vendor/')));
  assert(h.scripts.some(s => s.src.includes('/jspdf/4.2.1/')));
  h.scripts[0].onerror(); assert.equal((await first).ok, false);
  const second = h.api.generate(); assert.equal(h.scripts.length, 3, '重試應保留另一個進行中載入');
  h.install(); h.scripts[1].onload(); h.scripts[2].onload(); assert.equal((await second).ok, true); clean(h);
  const timeout = harness({ noLibs: true }); const waiting = timeout.api.generate();
  await timeout.advance(15000); assert.equal((await waiting).ok, false); clean(timeout); assert.equal(timeout.doc.head.children.length, 0);
  const version = harness({ noLibs: true }); const wrong = version.api.generate();
  version.install(); version.c.jspdf.jsPDF.version = '2.5.1'; version.scripts[0].onload(); version.scripts[1].onload();
  assert.match((await wrong).error, /版本不符/); clean(version);
  console.log('通過：同源版本固定、並行合併、失敗重試、載入逾時與版本拒收');
}

async function optionalFundamentals() {
  const h = harness({ count: 100, fetch: () => new Promise(() => {}) }); const work = h.api.generate(); await tick();
  assert.equal(h.requests.length, 4); assert(h.requests.every(r => r.init.signal));
  await h.advance(30000); const result = await work;
  assert.equal(result.ok, true); assert(h.requests.length <= 16, '整批 deadline 不得持續啟動剩餘請求');
  assert(h.requests.every(r => r.init.signal.aborted));
  assert(h.renders.map(r => r.text).join('').includes('基本面未取得')); clean(h);
  const values = harness();
  const role = '<img src="外來角色" onerror="不應執行">';
  const html = values.api.buildReportHtml({ a: { sym: '測試', role, buyZoneLow: '10', buyZoneHigh: '11' } },
    { 測試: { shortName: 12345, earningsQuarterlyGrowth: '12.5', trailingPE: '20', eps: null } });
  assert(!html.includes(role)); assert(html.includes('&lt;img')); assert(html.includes('13%')); assert(html.includes('10.00 ~ 11.00'));
  const fullName = '這是必須完整保留超過十二個字的公司名稱';
  assert(values.api.buildReportHtml({ a: { sym: '測試' } }, { 測試: { shortName: fullName } }).includes(fullName));
  const malformed = values.api.buildReportHtml({ a: { sym: '測試', role: '__proto__' } }, { 測試: { earningsQuarterlyGrowth: {}, shortName: 42 } });
  assert(malformed.includes('__proto__ 1')); assert(malformed.includes('—'));
  console.log('通過：基本面 4 路並行／30 秒整批上限，缺值明示，numeric 與角色 HTML 安全');
}

async function failuresClean() {
  for (const option of [{ render: () => Promise.reject(new Error('渲染失敗')) }, { addImageError: true }, { save: () => Promise.reject(new Error('儲存失敗')) }]) {
    const h = harness(option); assert.equal((await h.api.generate()).ok, false); clean(h);
    assert(h.alerts.every(text => !text.includes('已交由瀏覽器')));
  }
  const render = pending(); const h = harness({ render: () => render.promise }); const work = h.api.generate(); await tick();
  assert.equal(h.renders.length, 1); await h.advance(20000); assert.equal((await work).ok, false); clean(h);
  const late = h.canvases[0]; late.width = 100; late.height = 100; render.resolve(late); await tick(); clean(h);
  const large = harness(); large.c.S.plans.p0.outlook = '完整但過長的單一段落'.repeat(10000);
  assert.equal((await large.api.generate()).ok, false); assert(!large.pdfs[0]?.saved); assert.equal(large.renders.length, 0); clean(large);
  const limit = harness({ count: 500 });
  for (const row of Object.values(limit.c.S.plans)) row.outlook += '內容'.repeat(500);
  const result = await limit.api.generate();
  assert.equal(result.ok, false); assert.match(result.error, /120 頁/); assert(!limit.pdfs[0]?.saved); clean(limit);
  console.log('通過：render／encode／save 失敗、渲染逾時晚回應、超長區塊與超頁數均不下載截斷檔且完整清理');
}

(async () => { await completeReport(); await loadingAndRetry(); await optionalFundamentals(); await failuresClean();
  console.log('PDF 匯出可靠性：全部通過。');
})().catch(error => { console.error(error); process.exitCode = 1; });

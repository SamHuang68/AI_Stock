'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const root = path.resolve(__dirname, '..'), tick = () => new Promise(resolve => setImmediate(resolve));
function harness() {
  const saved = new Map(), listeners = new Map(), downloads = [], elements = new Map();
  let dialog, reads = 0, subscriptions = 0, blocked = false;
  function node(tag) {
    return { tag, open: false, isConnected: true, style: {}, textContent: '', innerHTML: '', disabled: false,
      handlers: {}, setAttribute() {}, getAttribute() { return null; }, appendChild() {}, focus() {}, click() {}, remove() {},
      getClientRects: () => [1], contains: () => true,
      addEventListener(type, fn) { this.handlers[type] = fn; },
      querySelector(selector) { if (!elements.has(selector)) elements.set(selector, node(selector)); return elements.get(selector); },
      querySelectorAll: () => [], showModal() { this.open = true; }, close() { this.open = false; if (this.handlers.close) this.handlers.close(); } };
  }
  const storage = { get length() { reads++; if (blocked) throw new Error('禁止儲存'); return saved.size; },
    key: i => [...saved.keys()][i], getItem: k => saved.has(k) ? saved.get(k) : null, setItem: (k, v) => saved.set(k, v) };
  const context = { console, Date, Math, Promise, Map, Set, Uint8Array, TextEncoder, Blob, crypto: webcrypto, localStorage: storage,
    location: { origin: 'http://offline.test' },
    document: { head: node('head'), body: node('body'), activeElement: null, createElement(tag) { const item = node(tag); if (tag === 'dialog') dialog = item; return item; } },
    CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    addEventListener(type, callback) { if (!listeners.has(type)) listeners.set(type, new Set()); listeners.get(type).add(callback); },
    removeEventListener(type, callback) { if (listeners.has(type)) listeners.get(type).delete(callback); },
    dispatchEvent(event) { for (const callback of listeners.get(event.type) || []) callback(event); },
    fetch() { throw new Error('本機 AI 狀態禁止任何網路要求'); },
    URL: { createObjectURL(blob) { downloads.push(blob); return 'blob:離線備份'; }, revokeObjectURL() {} },
    setTimeout(fn) { fn(); },
    UpdateJobs: { subscribe(callback) { subscriptions++; callback({ capabilities: { canSubmit: false }, workers: {}, jobs: [] }); return () => { subscriptions--; }; } } };
  context.window = context; vm.createContext(context);
  for (const file of ['src/ui/更新工作中心.js']) vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, { filename: file });
  return { context, storage, saved, downloads, listeners, get: selector => dialog.querySelector(selector),
    get reads() { return reads; }, get subscriptions() { return subscriptions; }, block() { blocked = true; },
    click(attribute) { const button = { disabled: false, closest() { return this; }, hasAttribute: name => name === attribute };
      dialog.handlers.click({ target: button }); } };
}
async function until(test) { for (let i = 0; i < 1000 && !test(); i++) await tick(); assert(test(), '介面應完成核對'); }
(async () => {
  const h = harness();
  h.context.UpdateCenter.open(); await tick();
  assert.equal(h.get('[aria-labelledby="uc-local-title"]').hidden, true, '未部署研究核心時隱藏本機研究介面');
  assert.equal(h.reads, 0, '未啟用研究不讀取私人儲存');
  assert.equal(h.subscriptions, 1);
  h.context.UpdateCenter.open(); assert.equal(h.subscriptions, 1, '重複開啟不重複輪詢');
  assert.match(h.get('.uc-readonly').textContent, /唯讀模式/);
  h.context.UpdateCenter.close(); assert.equal(h.subscriptions, 0);
  assert.equal(h.reads, 0); assert.equal(h.downloads.length, 0);
  console.log('通過：更新中心不啟用研究、不讀私人儲存、唯讀提示與重複開關釋放');
})().catch(error => { console.error(error); process.exitCode = 1; });

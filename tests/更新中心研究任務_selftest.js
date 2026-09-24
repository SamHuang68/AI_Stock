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
  for (const file of ['src/core/研究任務.js', 'src/ui/更新工作中心.js']) vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, { filename: file });
  return { context, storage, saved, downloads, listeners, get: selector => dialog.querySelector(selector),
    get reads() { return reads; }, get subscriptions() { return subscriptions; }, block() { blocked = true; },
    click(attribute) { const button = { disabled: false, closest() { return this; }, hasAttribute: name => name === attribute };
      dialog.handlers.click({ target: button }); } };
}
async function until(test) { for (let i = 0; i < 1000 && !test(); i++) await tick(); assert(test(), '介面應完成核對'); }
(async () => {
  const h = harness(), store = new h.context.ResearchTaskCore.Store(h.storage);
  for (let i = 0; i < 22; i++) await store.append('離線工作-' + i, 'prepared', { packet: { label: '反方檢查', hash: '凍結包-' + i } });
  await store.append('接收工作', 'running', { packet: { label: '<script>測試工作</script>', hash: '完整摘要碼' }, route: { model: '原定模型', provider: '原定提供者', host: '本機主機' } });
  h.saved.set('st.research.task.v1.損毀', '必須保留的原始損毀字串');
  h.saved.set('st.research.pending.v1.接收工作', '必須保留的未核對原文');
  const before = new Map(h.saved); h.context.UpdateCenter.open();
  await until(() => h.get('.uc-local-count').textContent.includes('23 個工作'));
  assert(h.get('.uc-local-count').textContent.includes('損毀項目 1 個')); assert(h.get('.uc-local-count').textContent.includes('暫存 1 個'));
  let html = h.get('.uc-local-jobs').innerHTML;
  assert(html.includes('完成狀態未確認')); assert(html.includes('不能據此判定後端')); assert(html.includes('原定模型')); assert(html.includes('完整摘要碼'));
  assert(!html.includes('<script>')); assert(html.includes('&lt;script&gt;'));
  assert.equal((html.match(/class="uc-job"/g) || []).length, 20);
  h.click('data-local-next'); assert.equal((h.get('.uc-local-jobs').innerHTML.match(/class="uc-job"/g) || []).length, 3);
  h.click('data-local-prev');
  await store.append('接收工作', 'verified', { packageHash: '完整摘要碼', meta: { requestId: '完成請求' }, result: { verified: true, raw: '完整回應' } });
  await until(() => h.get('.uc-local-jobs').innerHTML.includes('已保存完整完成收據'));
  assert(h.get('.uc-local-jobs').innerHTML.includes('完成請求'));
  h.click('data-local-export'); await until(() => h.downloads.length === 1);
  const archive = JSON.parse(await h.downloads[0].text());
  assert.equal(archive.events.length, 24); assert.equal(archive.damaged[0].raw, '必須保留的原始損毀字串');
  assert.equal(archive.recovery[0].raw, '必須保留的未核對原文');
  for (const [key, value] of before) assert.equal(h.saved.get(key), value);
  h.context.UpdateCenter.close(); const priorReads = h.reads;
  assert.equal(h.subscriptions, 0); assert.equal(h.listeners.get('st:research-task-saved').size, 0); assert.equal(h.listeners.get('storage').size, 0);
  await store.append('關閉後新紀錄', 'prepared', { packet: { hash: '另一份凍結包' } }); await tick(); assert.equal(h.reads, priorReads);
  h.context.UpdateCenter.open(); await until(() => h.get('.uc-local-count').textContent.includes('24 個工作'));
  const visibleBeforeError = h.get('.uc-local-jobs').innerHTML; h.block(); h.context.dispatchEvent({ type: 'storage', key: null });
  await until(() => h.get('.uc-local-error').textContent.includes('禁止儲存'));
  assert.equal(h.get('.uc-local-jobs').innerHTML, visibleBeforeError); h.context.UpdateCenter.close();
  console.log('通過：中心唯讀本機任務、完整核對、分頁、未確認狀態、全部匯出、保存通知、關閉釋放及儲存失敗保留');
})().catch(error => { console.error(error); process.exitCode = 1; });

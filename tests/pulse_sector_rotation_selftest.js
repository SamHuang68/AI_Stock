'use strict';
// Pulse 產業輪動：/sectors 標記 industry: false 的大盤、主題、槓桿反向與合併類指數不列入；沒有標記的列照舊。
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.resolve(__dirname, '..');
const nodes = new Map(), requests = [];
function node() {
  return { textContent: '', innerHTML: '', style: {}, hidden: false, className: '', value: '',
    classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll() { return []; },
    querySelector() { return null; }, setAttribute() {}, getAttribute() { return null; } };
}
const scope = {
  console, Date, Intl, Math, Promise, AbortController,
  document: { readyState: 'loading', getElementById: id => nodes.get(id) || null,
    querySelectorAll: () => [], querySelector: () => null, addEventListener() {},
    createElement: node, head: { appendChild(el) { nodes.set(el.id, el); } } },
  localStorage: { getItem: () => null }, location: { hash: '' }, addEventListener() {},
  setTimeout() { return 1; }, clearTimeout() {}, setInterval() { return 1; }, clearInterval() {},
  fetch(url) { return new Promise((resolve, reject) => requests.push({ url, resolve, reject })); },
};
scope.window = scope;
const source = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
assert.ok(source.includes('  window.PulseV5 = {'), 'pulse_v5.js 匯出位置改變，請同步更新本測試');
vm.runInNewContext(source.replace('  window.PulseV5 = {',
  '  window.fixture = { loadSectorsMkt: loadSectorsMkt, sectorsFromPack: sectorsFromPack };\n  window.PulseV5 = {'), scope);
const T = scope.fixture;

(async () => {
  T.loadSectorsMkt('TW');
  const request = requests.find(r => String(r.url).endsWith('/sectors?mkt=TW'));
  assert.ok(request, '應向 /sectors 取台股類股');
  request.resolve({ ok: true, status: 200, json: async () => ({ sectors: [
    { name: '發行量加權股價', changePct: 1.28, close: 46887.77, industry: false },
    { name: '臺指日報酬兩倍', changePct: 2.57, close: 229142.9, industry: false },
    { name: '電子工業', changePct: 1.08, close: 2928.19, industry: false },
    { name: '塑膠', changePct: 6.52, close: 499.07, industry: true },
    { name: '光電', changePct: 3.61, close: 77.73, industry: true },
    { name: '航運', changePct: -0.24, close: 215.82 },
  ] }) });
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(T.sectorsFromPack({ sectorsRanked: [] }).map(r => r.name), ['塑膠', '光電', '航運']);
  console.log('pulse_sector_rotation_selftest 通過：產業輪動只列單一產業，沒有標記的列照舊');
})().catch(err => { console.error(err); process.exit(1); });

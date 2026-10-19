'use strict';
// 審查 PB-07：合計損益%的分子分母用同一組已載價部位，未載價部位明示且不當成 0%。僅記憶體執行。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');
const store = new Map();
const s = { console: { log() {}, warn() {}, error() {} }, S: {},
  localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)) },
  document: { getElementById: () => null, addEventListener() {}, querySelector: () => null },
  addEventListener() {}, setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {} };
s.window = s; vm.createContext(s);
vm.runInContext(read('src/core/position_v2.js'), s, { filename: 'src/core/position_v2.js' });
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

s.S.sym = '0050'; s.S.mkt = 'TW'; s.S.data = { candles: [] };
s.S.positions = {
  2330: { entry: 1000, shares: 1000, lastPrice: 1100, mkt: 'TW' },
  2317: { entry: 200, shares: 5000, lastPrice: null, mkt: 'TW' },
};
const list = text(s.renderPositionList());
assert.match(list, /合計損益 \+10\.00% \(\+100,000\)（1 檔未載價）/, list);
assert.match(list, /2,000,000 → 1,100,000（1 檔未載價）/, list);

s.S.positions = { 2317: { entry: 200, shares: 5000, lastPrice: null, mkt: 'TW' } };
assert.match(text(s.renderPositionList()), /合計損益 價格未載入/);

s.S.positions = { 2330: { entry: 1000, shares: 1000, lastPrice: 1100, mkt: 'TW' } };
const full = text(s.renderPositionList());
assert.match(full, /合計損益 \+10\.00% \(\+100,000\) /, full);
assert.doesNotMatch(full, /未載價/);

// 當前個股未載價：市值與未實現損益顯示 --，不顯示 0% 或市值等於成本
s.S.sym = '2317'; s.S.dataIdentity = null;
s.S.positions = { 2317: { entry: 200, shares: 5000, lastPrice: null, mkt: 'TW' } };
const one = text(s.renderPosition());
assert.match(one, /目前市值 -- /, one);
assert.match(one, /未實現損益 -- /, one);
assert.doesNotMatch(one, /\+0\.00%/);
console.log('position total known cost selftest ok');

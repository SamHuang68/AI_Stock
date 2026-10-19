'use strict';
// 審查 PB-04／PB-05：StratLib 遇到缺值的窗口要回 null，不可把 null 當 0 給出假值。僅記憶體執行。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');
const s = { console, S: {}, localStorage: { getItem: () => null, setItem() {} },
  document: { getElementById: () => null, addEventListener() {}, querySelector: () => null },
  addEventListener() {}, setTimeout() {}, clearTimeout() {}, stEmaSeries: () => [] };
s.window = s; vm.createContext(s);
for (const file of ['src/screener/backtest_v3.js', 'src/screener/strategy_builder_v3.js']) vm.runInContext(read(file), s, { filename: file });
const L = s.StratLib, B = s.Backtest;
const plain = v => JSON.parse(JSON.stringify(v));

// N 日高低：窗口含缺值回 null，完整窗口照常
assert.deepEqual(plain(L.highest([null, null, null], 3)), [null, null, null]);
const low = Array.from({ length: 12 }, (_, i) => 10 + i);
assert.equal(L.lowest(low, 3)[10], 18);
const lowGap = low.slice(); lowGap[9] = null;
assert.deepEqual(plain(L.lowest(lowGap, 3).slice(9, 12)), [null, null, null]);
assert.equal(L.lowest(lowGap, 3)[8], 16);

// 漲跌%：缺值不得變成 −100%
assert.deepEqual(plain(L.pctChange([100, null, 102, 51])), [null, null, null, -50]);

// KD：40 根單調上升，close[15] 缺值；缺值所在窗口回 null，之後恢復且不出現假超賣
const n = 40, close = Array.from({ length: n }, (_, i) => 100 + i);
const high = close.map(c => c + 1), lowK = close.map(c => c - 1);
const full = L.kd(high, lowK, close);
const gap = close.slice(), gapH = high.slice(), gapL = lowK.slice();
gap[15] = gapH[15] = gapL[15] = null;
const kd = L.kd(gapH, gapL, gap);
for (let i = 15; i <= 23; i++) assert.equal(kd.k[i], null, 'K[' + i + '] 窗口含缺值');
for (let i = 24; i < n; i++) assert.ok(kd.k[i] > 85, 'K[' + i + '] 不應出現假低檔 ' + kd.k[i]);
assert.ok(Math.abs(full.k[n - 1] - kd.k[n - 1]) < 0.5, "缺值後平滑狀態應收斂回完整資料");

// 布林通道：均線無定義時上下軌也是 null，且下軌與 Backtest.bbLower 同一結果
const bbClose = Array.from({ length: 25 }, (_, i) => 100 + (i % 3) - 1);
const bbGap = bbClose.slice(); bbGap[10] = null;
const band = L.bb(bbGap, 20, 2), ref = B.bbLower(bbGap, 20, 2);
for (let i = 19; i < 25; i++) {
  assert.equal(band.mid[i], null); assert.equal(band.upper[i], null); assert.equal(band.lower[i], null);
}
assert.deepEqual(plain(L.bb(bbClose, 20, 2).lower), plain(B.bbLower(bbClose, 20, 2)));
assert.deepEqual(plain(band.lower), plain(ref));
console.log('stratlib missing values selftest ok');

'use strict';
// 審查 CH-02：主圖型態「區間向上突破」的量能以當日量／前 20 日均量判定，與 WATCH 同口徑。僅記憶體執行。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');
const el = () => ({ style: {}, classList: { add() {}, remove() {}, toggle() {} }, addEventListener() {}, appendChild() {},
  setAttribute() {}, querySelector: () => null, querySelectorAll: () => [] });
const s = { console: { log() {}, warn() {}, error() {} }, S: {},
  document: { getElementById: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    createElement: el, head: el(), body: el() },
  addEventListener() {}, setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {},
  localStorage: { getItem: () => null, setItem() {} } };
s.window = s; vm.createContext(s);
vm.runInContext(read('src/chart/pattern_v3.js'), s, { filename: 'src/chart/pattern_v3.js' });
const detect = s.PatternV3.detectBreakout;

// 30 日窄幅整理（量 1000），最後一根收在上緣之上
function bars(lastVolume, priorGap) {
  const out = Array.from({ length: 30 }, (_, i) => ({ time: i + 1, open: 100, high: 101, low: 99, close: 100, volume: 1000 }));
  if (priorGap) out[25].volume = null;
  out.push({ time: 31, open: 101, high: 104, low: 100.5, close: 103, volume: lastVolume });
  return out;
}

const tripled = detect(bars(3000));
assert.equal(tripled.type, 'breakout_up');
assert.equal(tripled.reliability, '量增突破', '舊版以 5 日／20 日均量比得 1.27x，判「量不足」');
assert.match(tripled.description, /當日量為前 20 日均量 3\.0x/);

const normal = detect(bars(1200));
assert.equal(normal.reliability, '量不足');
assert.match(normal.action, /假突破風險/);

const gap = detect(bars(3000, true));
assert.equal(gap.reliability, '量能未知');
assert.match(gap.action, /量能未知/);

// 跌破分支不受影響
const down = bars(1000); down[30] = { time: 31, open: 99, high: 99.5, low: 95, close: 96, volume: 1000 };
assert.equal(detect(down).type, 'breakout_down');
console.log('pattern breakout day volume selftest ok');

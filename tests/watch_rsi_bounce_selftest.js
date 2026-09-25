// P0：前端 WATCH「RSI 超賣反彈」須為跨越事件，且 Wilder RSI 與後端 indicators.py 同值。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/core/watch_v2.js'), 'utf8');
const start = source.indexOf('function rsiWildersSeries');
const end = source.indexOf('// ── Preset combos', start);
if (start < 0 || end < 0) throw new Error('watch_v2 strategy block missing');

const sandbox = {
  num(v) { if (v == null) return null; const n = Number(v); return isFinite(n) ? n : null; },
  console,
};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end) + '\nglobalThis.__S = STRATEGIES; globalThis.__rsi = rsiWildersSeries;', sandbox);

function ok(value, message) {
  if (!value) throw new Error('FAIL: ' + message);
  console.log('OK  ', message);
}

// 與 tests/test_indicators.py 固定樣本同一數字（Wilder RSI 14）
const fixture = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
  45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64];
const series = sandbox.__rsi(fixture, 14);
ok(Math.abs(series[series.length - 1] - 57.91502067008556) < 1e-10,
  'Wilder RSI series matches server/indicators.py fixture');
ok(sandbox.__rsi([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], 14).slice(-1)[0] === 100,
  'zero average loss returns exactly 100');

const bounce = sandbox.__S.find((s) => s.key === 'rsi_oversold_bounce');
function candles(closes) { return closes.map((c) => ({ close: c, high: c * 1.01, low: c * 0.99 })); }

const path1 = [100];
for (let i = 0; i < 40; i++) path1.push(path1[path1.length - 1] * (i % 2 === 0 ? 1.012 : 0.99));
for (let j = 0; j < 5; j++) path1.push(path1[path1.length - 1] * 0.975);
const stillLow = bounce.check({}, candles(path1.concat([path1[path1.length - 1] * 1.01])), {});
ok(stillLow.status === 'wait', 'RSI still under 30 waits');
const crossed = bounce.check({}, candles(path1.concat([path1[path1.length - 1] * 1.02])), {});
ok(crossed.status === 'trigger', 'RSI crossing back above 30 triggers (same path as Python test)');

// 由高檔一路緩跌到 RSI 30~38：不是超賣反彈
const drift = [100];
for (let i = 0; i < 60; i++) drift.push(drift[drift.length - 1] * (i % 3 === 0 ? 1.006 : 0.9955));
const driftSeries = sandbox.__rsi(drift, 14);
const lastRsi = driftSeries[driftSeries.length - 1];
const res = bounce.check({}, candles(drift), {});
if (lastRsi >= 30 && lastRsi <= 38) {
  ok(res.status === 'wait' && /未曾跌破 30/.test(res.detail), 'level 30~38 without prior oversold is not a bounce');
} else {
  ok(res.status !== 'trigger', 'drift path outside band never triggers (rsi=' + lastRsi.toFixed(1) + ')');
}

console.log('\nwatch_rsi_bounce_selftest PASSED');

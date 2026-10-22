'use strict';
/**
 * K 線型態在正式頁面的狀態讀取（審查 TQ-01、交接單第 9 節 1、2 項）。
 *
 * 正式頁面的 S 是 stock_terminal.html 頂層的 `let S = {...}`，不會成為 window.S。
 * pattern_v3.js 過去用 `window.S && ...` 守衛：偵測不帶參數時回 0 個、疊圖直接 return、型態面板顯示
 * 「分析了 0 個日 K 線」；既有瀏覽器測試都先注入 window.S，所以測不到。
 *
 * 此測試執行 src/chart/pattern_v3.js 的正式程式碼，只提供瀏覽器環境。環境刻意貼近正式頁面：
 * 以另一段腳本宣告頂層 `let S`（詞法綁定，不在 globalThis 上），並斷言 window.S 始終是 undefined。
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/chart/pattern_v3.js'), 'utf8').replace(/\r\n/g, '\n');

// 明確的雙底（W 底）：兩個相近的低點中間夾一個高點，之後突破頸線。
function candles() {
  const closes = [];
  const push = (from, to, n) => { for (let i = 0; i < n; i++) closes.push(from + (to - from) * (i / n)); };
  push(120, 100, 12); push(100, 112, 8); push(112, 100.5, 8); push(100.5, 118, 10); push(118, 122, 6);
  while (closes.length < 60) closes.push(closes[closes.length - 1] + (closes.length % 2 ? 0.4 : -0.3));
  return closes.map((c, i) => ({ time: 1_700_000_000 + i * 86400, open: c - 0.3, high: c + 1.2, low: c - 1.2, close: c, volume: 1000 }));
}

function makeContext({ withWindowS }) {
  const priceLines = [], removed = [], polylines = [];
  const chartSeries = {
    createPriceLine(options) { const line = { options }; priceLines.push(line); return line; },
    removePriceLine(line) { removed.push(line); },
    setMarkers() {},
  };
  const noop = () => {};
  const windowObj = { addEventListener: noop, removeEventListener: noop, dispatchEvent: noop, SERVER: '', Colors: undefined };
  const context = {
    console: { log: noop, warn: noop, error: noop }, Date, Number, Math, isFinite, Map, Set, JSON, Array, Object, Promise,
    String, Boolean, Symbol, RegExp, Error, setTimeout: noop, clearTimeout: noop, AbortController,
    document: { getElementById: () => null, createElement: () => ({ style: {}, classList: { add: noop, remove: noop } }),
      addEventListener: noop, querySelector: () => null, querySelectorAll: () => [] },
    window: windowObj,
    LightweightCharts: { LineStyle: { Solid: 0, Dotted: 1, Dashed: 2 } },
  };
  context.globalThis = context;
  vm.createContext(context);
  context.window = Object.assign(windowObj, { document: context.document });
  // 先宣告頂層 let S（與 stock_terminal.html 相同的綁定方式），再載入被測腳本
  vm.runInContext('let S = {};', context, { filename: 'stock_terminal.html#S' });
  const state = { sym: '2330', mkt: 'TW', tab: 'chart', chart: { addLineSeries() { const series = { setData(points) { series.points = points; } }; polylines.push(series); return series; }, removeSeries: noop },
    chartSeries, data: { candles: candles() }, patternsEnabled: true };
  vm.runInContext('Object.assign(S, ' + JSON.stringify({}) + ');', context);
  Object.assign(vm.runInContext('S', context), state);
  if (withWindowS) context.window.S = vm.runInContext('S', context);
  vm.runInContext(source, context, { filename: 'src/chart/pattern_v3.js' });
  return { context, priceLines, removed, polylines };
}

function run(name, fn) {
  try { fn(); console.log('OK   ' + name); }
  catch (error) { console.error('FAIL ' + name + '\n  ' + (error && error.stack || error)); process.exitCode = 1; }
}

run('前提：正式環境沒有 window.S，但詞法 S 存在', () => {
  const { context } = makeContext({ withWindowS: false });
  assert.strictEqual(context.window.S, undefined);
  assert.strictEqual(vm.runInContext('typeof S', context), 'object');
  assert.strictEqual(vm.runInContext('typeof globalThis.S', context), 'undefined');
});

run('不帶參數的偵測讀得到目前圖表的 K 線', () => {
  const { context } = makeContext({ withWindowS: false });
  const explicit = context.window.detectPatterns(vm.runInContext('S.data.candles', context));
  assert(explicit.length > 0, '夾具必須能偵測出型態，否則此測試沒有意義');
  const implicit = context.window.detectPatterns();
  assert.strictEqual(implicit.length, explicit.length, '不帶參數時應與帶入同一份 K 線的結果相同');
});

run('型態面板不再顯示「分析了 0 個日 K 線」', () => {
  const { context } = makeContext({ withWindowS: false });
  const html = context.window.renderPatternsPanel();
  assert(!/分析了 0 個日 K 線/.test(html), html.slice(0, 160));
  assert(/共偵測到/.test(html), html.slice(0, 160));
});

run('疊圖會在圖表上畫出價位線與斜線', () => {
  const { context, priceLines, polylines } = makeContext({ withWindowS: false });
  const patterns = context.window.detectPatterns();
  context.window.PatternV3.drawPatternsOnChart(patterns);
  assert(priceLines.length + polylines.length > 0, '沒有畫出任何價位線或斜線');
});

run('window.S 存在時（其他環境或測試注入）行為相同', () => {
  const a = makeContext({ withWindowS: false });
  const b = makeContext({ withWindowS: true });
  assert.strictEqual(b.context.window.detectPatterns().length, a.context.window.detectPatterns().length);
  b.context.window.PatternV3.drawPatternsOnChart(b.context.window.detectPatterns());
  a.context.window.PatternV3.drawPatternsOnChart(a.context.window.detectPatterns());
  assert.strictEqual(b.priceLines.length, a.priceLines.length);
  assert.strictEqual(b.polylines.length, a.polylines.length);
});

run('沒有任何狀態時安全回空，不拋例外', () => {
  const context = makeContext({ withWindowS: false }).context;
  vm.runInContext('S.data = null; S.chart = null; S.chartSeries = null;', context);
  assert.deepStrictEqual(Array.from(context.window.detectPatterns()), []);
  context.window.PatternV3.drawPatternsOnChart([]);
});

if (!process.exitCode) console.log('\nAll pattern production-state checks passed.');

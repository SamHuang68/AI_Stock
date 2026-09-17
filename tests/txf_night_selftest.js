// 台指期實際前端函式回歸：報價與歷史圖分離、跨時段不可覆寫。
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/polish_v3.js'), 'utf8');
function extract(name, sourceText = source) {
  const source = sourceText;
  const start = source.indexOf('function ' + name + '(');
  assert(start >= 0, name);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error('函式未結束：' + name);
}
const header = {};
const updates = [];
const dayBar = { time: Date.parse('2026-09-17T00:00:00+08:00') / 1000, open: 100, high: 105, low: 98, close: 102, volume: 20 };
const ctx = {
  S: { sym: '__TXF__', range: '1y', data: { candles: [{ ...dayBar }], yesterdayClose: 99 },
    chartSeries: { update: value => updates.push(value) } },
  updateHeaderChg: (price, prev) => Object.assign(header, { price, prev }),
  updateHeaderHigh: () => {},
  document: { getElementById: id => id === 'ci-price' ? { set textContent(value) { header.text = value; } } : null },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(['normalizeTxfLiveQuote', 'isTxfChartSym', 'overlayTxfLiveOnLastBar', 'applyTxfLiveToChart'].map(name => extract(name)).join('\n'), ctx);
const day = { price: 104, prevClose: 99, high: 106, low: 97, session: 'day',
  asOf: '2026-09-17T12:00:00+08:00', tradeDate: '2026-09-17', stale: false };
assert.equal(ctx.overlayTxfLiveOnLastBar(dayBar, day).close, 104);
const night = { ...day, session: 'night', tradeDate: null, asOf: '2026-09-18T04:59:58+08:00' };
assert.equal(ctx.overlayTxfLiveOnLastBar(dayBar, night), null);
assert.equal(ctx.overlayTxfLiveOnLastBar(dayBar, { ...day, tradeDate: '2026-09-16' }), null);
assert.equal(ctx.overlayTxfLiveOnLastBar(dayBar, { ...day, asOf: null }), null);
assert.equal(ctx.overlayTxfLiveOnLastBar(dayBar, { ...day, stale: true }), null);
const minute = { ...dayBar, time: Date.parse(day.asOf) / 1000, high: 103, low: 101 };
const overlay = ctx.overlayTxfLiveOnLastBar(minute, day, { intraday: true });
assert.equal(overlay.high, 104);
assert.equal(overlay.low, 101);
assert.equal(ctx.overlayTxfLiveOnLastBar({ ...minute, time: minute.time - 60 }, day, { intraday: true }), null);
assert(ctx.applyTxfLiveToChart(night));
assert.equal(ctx.S.data.candles[0].close, 102);
assert.equal(updates.length, 0);
assert.equal(header.price, 104);
assert.equal(header.prev, 99);
ctx.S.sym = 'TXF';
assert(ctx.applyTxfLiveToChart(day));
assert.equal(updates.length, 1);
assert.equal(ctx.S.data.candles[0].close, 104);
assert(source.includes('setInterval(pullTxfLive, 5000)'));
const pulse = fs.readFileSync(path.join(__dirname, '../src/ui/pulse_v5.js'), 'utf8');
assert(!pulse.includes('Number(txf.price) - Number(t00.price)'));
assert(pulse.includes('turnoverDate'));
assert(pulse.includes('Z20 待足 20 日'));
Object.assign(ctx, { pct: x => String(x), esc: x => String(x), tw: () => '', renderTrendTabs: () => '', IDX_TREND_TABS: [] });
vm.runInContext(['trendQuantBits', 'trendPrimarySub', 'renderTrendCell'].map(name => extract(name, pulse)).join('\n'), ctx);
const cell = ctx.renderTrendCell({ trend: { chgPct: 1, momScore: 50, vsMa5Pct: 1 },
  observationText: '最近成交，非即時 · 09-17 04:59:58 · 日線 2026-09-16' });
assert(cell.includes('最近成交，非即時'));
assert(cell.includes('09-17 04:59:58'));
assert(cell.includes('日線 2026-09-16'));
console.log('台指期時段與歷史圖回歸：通過');

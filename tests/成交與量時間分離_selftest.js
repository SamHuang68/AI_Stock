'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
let now = Date.UTC(2026, 9, 2, 2, 30), quote, tick;
const updates = [], volumes = [], listeners = {};
const elements = new Map();
const element = () => ({textContent: '', style: {}, appendChild() {}});
elements.set('chart-wrap', element());
elements.set('rt-hb', element());
class Clock extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } }
const context = { Date: Clock, console, S: {sym: '2330', mkt: 'TW', range: '1d', tzOffset: 0,
  chartSeries: { update: value => updates.push(value) },
  volSeries: { update: value => volumes.push(value) },
  data: {candles: [{time: Date.UTC(2026, 9, 2, 2, 20) / 1000, open: 100, high: 100, low: 100, close: 100, volume: 0}]}},
  document: {hidden: false, querySelector: () => ({textContent: '1天'}),
    getElementById: id => elements.get(id), createElement: element, addEventListener() {}},
  addEventListener: (name, fn) => {listeners[name] = fn;},
  setInterval: fn => {tick = fn;}, setTimeout() {},
  fetch: async url => ({json: async () => url.startsWith('/twquote') ? quote : {ok: true}})};
context.window = context;
vm.createContext(context);
for (const file of ['intraday_volume_v3.js', 'market_data_v5.js', 'realtime_v3.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, 'src/core', file), 'utf8'), context);
}
listeners.symLoaded();
async function send(value) { quote = value; tick(); await new Promise(resolve => setImmediate(resolve)); }
(async () => {
  const priceTime = Date.UTC(2026, 9, 2, 2, 25);
  const volumeTime = Date.UTC(2026, 9, 2, 2, 30);
  const valid = {ok: true, price: 101, source: 'twse-mis', timestampMs: priceTime,
    prevClose: 100, priceRealtime: true, volumeShares: 100000, volumeRealtime: true,
    volumeSource: 'twse-mis', volumeTimestampMs: volumeTime, time: '10:25:00'};
  await send(valid);
  assert.equal(updates.at(-1).time, priceTime / 1000, '新累計量不可把舊成交搬到新的分鐘');
  assert.equal(volumes.at(-1).time, volumeTime / 1000, '累計量使用自身來源時間');
  now += 3000;
  await send({...valid, volumeShares: 101000, volumeTimestampMs: volumeTime + 3000});
  assert.equal(volumes.at(-1).value, 1000, '同來源同分鐘增量的獨立期望值為1000股');
  const before = volumes.length;
  await send({...valid, volumeTimestampMs: volumeTime - 86400000});
  assert.equal(volumes.length, before, '昨日累計量不可寫入今日圖表');
  console.log('成交與累計量時間分離：成交分鐘、量分鐘、1000股增量與舊量拒絕全部通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

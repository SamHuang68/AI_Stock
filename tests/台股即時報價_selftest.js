'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const root = path.resolve(__dirname, '..');
const chip = { textContent: '', title: '', classList: { remove() {}, add() {} } };
let response = {}, rendered = 0;
const S = { sym: '2330', wl: [{ t: '2330', m: 'TW' }], positions: { '2330': { entry: 2000, shares: 1000, lastPrice: 2380 } }, data: { candles: [{ close: 2380 }] } };
const context = { S, console, Map, Date, setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {},
  document: { body: {}, getElementById: () => chip, addEventListener() {} },
  fetch: async () => ({ ok: true, json: async () => response }),
  renderPositionPanel: () => { rendered++; }, saveWl() {}, savePositions() {} };
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'src/core/market_data_v5.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(root, 'src/core/wl_live_v3.js'), 'utf8'), context);

(async () => {
  response = { '2330': { ok: true, price: 2430, prevClose: 2380, changePct: 50 / 2380 * 100,
    timestampMs: 1789607970000, asOf: '2026-09-17T09:19:30+08:00', source: 'twse-mis' } };
  await context.pollWlPrices();
  assert.equal(S.positions['2330'].lastPrice, 2430);
  assert.equal(chip.textContent, '+2.10%');
  assert(chip.title.includes('最近成交'));
  assert.equal(S.positions['2330'].quoteTimestampMs, 1789607970000);

  // 執行正式投資組合計算，證明選中個股不再被舊 K 線收盤覆寫。
  const source = fs.readFileSync(path.join(root, 'src/core/pro_v2.js'), 'utf8');
  const start = source.indexOf('function computePortfolioMetrics()');
  const next = source.indexOf('\nfunction ', start + 1);
  vm.runInContext(source.slice(start, next), context);
  assert.equal(context.computePortfolioMetrics().items[0].ref, 2430);

  response = { '2330': { ...response['2330'], price: 2420, timestampMs: 1789607900000 } };
  await context.pollWlPrices();
  assert.equal(S.positions['2330'].lastPrice, 2430, '較晚抵達的舊成交不得覆寫新價格');

  response = { '2330.TW': { ok: false, stale: true, price: null, changePct: null } };
  await context.pollWlPrices();
  assert.equal(chip.textContent, '待更新');
  assert.equal(S.positions['2330'].dayChangePct, null);
  assert.equal(S.positions['2330'].quoteStale, true);
  assert.equal(S.positions['2330'].lastPrice, 2430);
  assert.equal(context.computePortfolioMetrics().items[0].dayChangePct, null);
  assert.equal(context.computePortfolioMetrics().items[0].ref, 2430);
  assert(rendered >= 2);
  console.log('台股即時報價：自選、持倉、過期備援與現價優先順序通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

/* 缺值不能被 JavaScript 隱式轉成零元後進入回測。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

(async () => {
  let scans = 0;
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { id, style: {}, innerHTML: '', value: '10', addEventListener() {}, querySelector: s => element(s.slice(1)), getContext: () => ({ clearRect() {} }) });
    return elements.get(id);
  };
  const candles = Array.from({ length: 80 }, (_, i) => ({ time: i, open: 100, high: 101, low: 99, close: 100, volume: 1000 }));
  candles[45].close = null;
  const context = { window: { Backtest: { scanStrategies() { scans++; return []; } } }, S: { sym: '1538', mkt: 'TW' }, document: {
    getElementById: id => elements.get(id), createElement: () => ({ style: {}, addEventListener() {}, querySelector: s => element(s.slice(1)) }), head: { appendChild() {} }, body: { appendChild() {} }
  }, fetch: async () => ({ json: async () => ({ candles }) }), console };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/screener/backtest_ui_v3.js'), 'utf8'), context);
  context.window.backtestOpen();
  element('bt3-body'); element('bt3-curve');
  await element('bt3-run').onclick();
  assert.equal(scans, 0);
  assert.match(element('bt3-body').innerHTML, /缺值或無成交/);
  console.log('日線缺值回測驗證通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

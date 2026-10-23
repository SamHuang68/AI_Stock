// Exercise the shipped overnight panel through its public render entrypoint.
// Run in Node: node tests/txf_night_selftest.js
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sourcePath = path.join(__dirname, '..', 'src', 'chart', 'overnight_v3.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const quotePaths = ['NQ=F', 'ES=F', 'YM=F', '^SOX', 'TSM'].map(sym =>
  `/yf/${encodeURIComponent(sym)}?range=5d&interval=1d`);

async function render(txf) {
  const requested = [];
  const unexpected = [];
  const window = { AppKernel: { api: { async getJson(url) {
    requested.push(url);
    if (url === '/txf') return txf;
    if (quotePaths.includes(url)) return { chart: { result: [{ meta: {},
      timestamp: [1700000000, 1700086400],
      indicators: { quote: [{ close: [100, 100.8] }] },
    }] } };
    unexpected.push(url);
    throw new Error(`Unexpected request: ${url}`);
  } } } };
  const host = {
    innerHTML: '', isConnected: true, classList: { add() {} },
    closest: () => null, querySelector: () => null, querySelectorAll: () => [],
  };
  const context = vm.createContext({
    window, AppKernel: window.AppKernel,
    document: { getElementById: id => id === 'ovn-style' ? {} : null },
    S: { positions: { '2330': { lastPrice: 100, stop: 98 } }, watches: {} },
  });
  vm.runInContext(source, context, { filename: sourcePath });
  assert.equal(typeof window.overnightRenderInto, 'function', 'production public entrypoint exists');
  await window.overnightRenderInto(host);
  assert.deepEqual(unexpected, [], 'fixture cannot silently satisfy a new data dependency');
  assert.deepEqual(requested.sort(), ['/txf', ...quotePaths].sort(), 'all production sources are exercised');
  return host.innerHTML;
}

async function main() {
  const sample = {
    ok: true,
    price: 43678,
    session: 'day',
    night: {
      price: 42650,
      prevClose: 43727,
      changePct: -2.46,
      open: 43519,
      high: 43873,
      low: 42086,
      ampRate: 4.09,
      volume: 69641,
      time: '045959',
      session: 'night',
    },
  };
  const html = await render(sample);
  assert.match(html, /42,650/, 'prefer night price over day primary');
  assert.doesNotMatch(html, /43,678/, 'day primary must not leak into the night panel');
  assert.match(html, /4\.09%/, 'ampRate comes from night');
  assert.match(html, /-2\.46%/, 'changePct comes from night');
  assert.match(html, /04:59:59/, 'night timestamp is rendered');
  assert.match(html, /97\.54 ⚠破停損/, 'TXF drives the actual position estimate and stop warning');
  assert.match(html, /依 台指期夜盤/, 'action source identifies TXF');
  assert.match(html, /\+0\.80%/, 'opposing US estimate remains visible');

  const noAmp = {
    ok: true,
    session: 'night',
    price: 42650,
    prevClose: 43727,
    high: 43873,
    low: 42086,
  };
  const fallback = await render(noAmp);
  const expectedAmp = ((43873 - 42086) / 43727 * 100).toFixed(2);
  assert.ok(fallback.includes(expectedAmp + '%'), 'missing amp is calculated from OHLC/previous close');
  assert.match(fallback, /-2\.46%/, 'missing changePct is calculated from price/previous close');
  assert.match(fallback, /97\.54 ⚠破停損/, 'primary night fallback still drives actions');

  const dayOnly = await render({ ok: true, session: 'day', price: 43000, night: null });
  assert.match(dayOnly, /暫無夜盤資料/, 'incomplete day-only data is not a night quote');
  assert.match(dayOnly, /依 美股連動預估/, 'actions identify the US fallback');
  assert.match(dayOnly, /100\.80/, 'US estimate drives the actual position estimate');
  assert.doesNotMatch(dayOnly, /⚠破停損/, 'positive US fallback must not retain the TXF warning');

  const invalid = await render({ ok: true, session: 'day', night: { price: Infinity } });
  assert.match(invalid, /暫無夜盤資料/, 'non-finite night prices are rejected by production normalization');
  const primary = await render({ ...noAmp, session: 'day', ampRate: 4.09 });
  assert.match(primary, /42,650/, 'complete OHLC primary quote remains an accepted fallback');
  assert.match(primary, /97\.54 ⚠破停損/, 'accepted primary quote uses production action priority');

  console.log('txf_night_selftest: PASS');
}

main().catch(error => { console.error(error); process.exitCode = 1; });

#!/usr/bin/env node
'use strict';

var fs = require('fs');
var path = require('path');
var vm = require('vm');

function ok(cond, msg) {
  if (!cond) throw new Error(msg);
}

var root = path.join(__dirname, '..');
var freshnessSrc = fs.readFileSync(path.join(root, 'src/core/market_freshness_v5.js'), 'utf8');

var sandbox = {
  window: {
    dispatchEvent: function () {},
    addEventListener: function () {},
    CustomEvent: function CustomEvent(type, init) {
      this.type = type;
      this.detail = init && init.detail;
    },
    SERVER: 'http://127.0.0.1:18432',
    localStorage: {
      _d: {},
      getItem: function (k) { return this._d[k] || null; },
      setItem: function (k, v) { this._d[k] = String(v); }
    },
    MarketFreshness: null,
    FeatureFlags: null
  },
  document: { readyState: 'complete', addEventListener: function () {} },
  console: console,
  Date: Date,
  Promise: Promise,
  setTimeout: setTimeout
};
sandbox.window.localStorage = sandbox.window.localStorage;
vm.createContext(sandbox);
vm.runInContext(freshnessSrc, sandbox);

var MF = sandbox.window.MarketFreshness;

ok(MF && MF.snapshotSummary, 'MarketFreshness.snapshotSummary exists');
var summary = MF.snapshotSummary({
  generatedAt: '2026-08-16T03:00:00Z',
  marketAsOf: '2026-08-15T06:00:00Z',
  session: 'mixed',
  quotes: {
    '^TWII': { market: { asOf: '2026-08-15T05:30:00+00:00', session: 'regular', source: 'twse-mis' } },
    '__TXF__': { market: { asOf: '2026-08-15T06:00:00+00:00', session: 'night', source: 'taifex-mis' } }
  }
});
ok(summary.worstAsOf === '2026-08-15T05:30:00.000Z', 'worstAsOf picks stalest quote, not generatedAt');
ok(summary.freshness === 'stale', 'mixed-age quotes classify as stale when old enough');

var health = MF.shellHealthText(summary);
ok(health.mode === 'err' && /2026-08-15/.test(health.text), 'shell health uses worst asOf');

/* 總經列標示：Pulse／總覽的美10年債過去不論新舊、是否驗證過都顯示成一般數值 */
ok(typeof MF.macroTag === 'function', 'MarketFreshness.macroTag exists');
ok(MF.macroTag({ freshness: 'fresh' }) === '', 'fresh macro row has no tag');
ok(MF.macroTag({ freshness: 'stale' }) === '（過期）', 'stale macro row is tagged');
ok(MF.macroTag({ freshness: 'invalid_future' }) === '（日期異常）', 'future-dated macro row is tagged');
ok(MF.macroTag({ freshness: 'unknown' }) === '（未驗證）', 'unverified macro row is tagged');
ok(MF.macroTag({}) === '' && MF.macroTag(null) === '' && MF.macroTag(undefined) === '',
  'rows without freshness (older server) stay untagged');

console.log('market_freshness_v5_selftest: ok');

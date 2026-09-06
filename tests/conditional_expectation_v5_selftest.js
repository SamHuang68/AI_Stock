'use strict';

var fs = require('fs');
var path = require('path');
var vm = require('vm');
var assert = require('assert');

var root = path.resolve(__dirname, '..');

function read(rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8');
}

var build = read('build_v2.py');
var postmarket = read('src/ui/postmarket_v5.js');
var decision = read('src/ui/decision_v5.js');
var hub = read('src/ui/hub_v5.js');
var ce = read('src/ui/conditional_expectation_v5.js');
var badges = read('src/core/epistemic_badges_v5.js');

assert(build.includes("'src/core/epistemic_badges_v5.js'"), 'build bundle omits epistemic badges');
assert(build.includes("'src/ui/conditional_expectation_v5.js'"), 'build bundle omits conditional expectation UI');

assert(/data-epistemic="FACT"/.test(badges), 'FACT badge contract missing');
assert(/data-epistemic="CONDITIONAL"/.test(badges), 'CONDITIONAL badge contract missing');
assert(/data-epistemic="HYPOTHESIS"/.test(badges), 'HYPOTHESIS badge contract missing');

assert(ce.includes('/research/conditional-expectation'), 'conditional card must use research API');
assert(ce.includes("FeatureFlags.isEnabled('shadowConditionalExpectation')"), 'flag gate missing');
assert(ce.includes('不適合作為預測參考'), 'expired prediction state copy missing');
assert(ce.includes('歷史條件統計 ≠ 未來保證'), 'disclaimer missing');
assert(!/DecisionData\.(publish|merge|set)/.test(ce), 'conditional UI must not write DecisionData');
assert(!/actionEnvelope/.test(ce), 'conditional UI must not touch actionEnvelope');
assert(ce.includes('symLoaded'), 'chart stats panel hook missing');
assert(ce.includes('Win'), 'horizon win rate column missing');
assert(ce.includes('MaxDD Q90'), 'horizon maxDD column missing');

assert(postmarket.includes('mountConditionalCards'), 'postmarket must mount conditional cards');
assert(postmarket.includes('shadowConditionalExpectation'), 'postmarket must respect shadow flag');
assert(postmarket.includes("EpistemicBadgesV5.badge('HYPOTHESIS'"), 'postmarket narrative uses HYPOTHESIS badge');

assert(decision.includes("EpistemicBadgesV5.badge('FACT'"), 'decision title uses FACT badge');
assert(hub.includes('shadowConditionalExpectation'), 'hub settings lists conditional expectation flag');

var sandbox = {
  window: {
    FeatureFlags: {
      isEnabled: function () { return true; }
    },
    EpistemicBadgesV5: null,
    SERVER: 'http://127.0.0.1:18432',
    S: { sym: '2330', mkt: 'TW', tab: 'stats' },
    addEventListener: function () {},
    ConditionalExpectationV5: null
  },
  document: {
    getElementById: function () { return null; },
    createElement: function () {
      return { id: '', textContent: '', appendChild: function () {} };
    },
    head: { appendChild: function () {} }
  },
  location: { origin: 'http://127.0.0.1:18432' },
  console: console,
  Promise: Promise,
  fetch: function () { return Promise.reject(new Error('no network in selftest')); }
};
vm.runInContext(badges, vm.createContext(Object.assign({}, sandbox, { window: sandbox.window })));
vm.runInContext(ce, vm.createContext(Object.assign({}, sandbox, {
  window: sandbox.window,
  FeatureFlags: sandbox.window.FeatureFlags
})));

var sample = {
  symbol: '2330',
  status: 'EXPIRED',
  binLabel: 'RSI 30-40 · 法人3日淨買 · BULL',
  epistemic: 'CONDITIONAL',
  minimumSample: 20,
  invalidIf: ['asof_gate_expired', 'n_below_minimum'],
  asOfGate: { usable: false, reasons: ['quote stale'] },
  evidenceAsOf: { quote: '2026-09-05T13:30:00+08:00', chips: '2026-09-03' },
  horizons: {
    '1': { n: 12, winRate: null, medianReturnPct: null, maxDrawdownQ90Pct: null, ratesAvailable: false },
    '5': { n: 12, winRate: null, medianReturnPct: null, maxDrawdownQ90Pct: null, ratesAvailable: false },
    '20': { n: 12, winRate: null, medianReturnPct: null, maxDrawdownQ90Pct: null, ratesAvailable: false }
  }
};
var html = sandbox.window.ConditionalExpectationV5.renderHtml(sample);
assert(/data-epistemic="CONDITIONAL"/.test(html), 'renderHtml must emit CONDITIONAL badge');
assert(/不適合作為預測參考/.test(html), 'renderHtml must show expired state');
assert(/invalidIf/.test(html), 'renderHtml must show invalidIf');
assert(/T\+1/.test(html) && /T\+5/.test(html) && /T\+20/.test(html), 'renderHtml must list horizons');

console.log('conditional_expectation_v5 self-test PASSED');

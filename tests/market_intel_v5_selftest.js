const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/core/market_intel_v5.js'), 'utf8');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const intel = sandbox.window.MarketIntelV5;

function ok(value, message) {
  if (!value) throw new Error('FAIL ' + message);
  console.log('OK  ', message);
}

const watchlist = [
  { t: 'AMD', m: 'US', name: 'AMD' },
  { t: 'MU', m: 'US', name: '美光' },
  { t: 'SNDK', m: 'US', name: 'Sandisk' },
  { t: '2408', m: 'TW', name: '南亞科' },
];
const resonance = intel.buildThemeResonance(watchlist, {
  MU: { changePct: 6.2 }, SNDK: { changePct: 5.8 }, 2408: { changePct: 6.5 }
});
ok(resonance.leaders[0].id === 'memory' && resonance.leaders[0].sameCount === 3,
  'memory names and symbols share one resonance taxonomy');

const linked = intel.linkNewsToWatchlist([
  { code: 'AMD', title: 'AMD Stock Gains As Chipmaker Eyes $5B Debt Sale Amid Surging Compute Demand', impact: { tier: 'MEDIUM', scope: ['AI_SUPPLY_CHAIN'] } },
  { code: 'MU', title: 'Micron raises DRAM and NAND guidance', impact: { tier: 'HIGH', scope: ['AI_SUPPLY_CHAIN'] } },
], watchlist);
ok(linked.byNews[0].length === 1 && linked.byNews[0][0].symbol === 'AMD',
  'capital-market news links directly without pretending broad supply-chain propagation');
ok(linked.byNews[1].some(x => x.symbol === 'SNDK') && linked.byNews[1].some(x => x.symbol === '2408'),
  'guidance news highlights same-theme watchlist members');
ok(linked.bySymbol.MU[0].tier === 'HIGH', 'highest impact metadata remains attached to linked symbols');

console.log('market_intel_v5_selftest PASSED');

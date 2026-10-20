'use strict';
// 審查 FE-03：持倉風險面板與持倉清單共用 positionTotals；未載價部位不以成本當市值。僅記憶體執行。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');
function between(source, start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, '受測原始碼界線必須存在');
  return source.slice(a, b);
}
const store = new Map();
const s = { console: { log() {}, warn() {}, error() {} }, S: {},
  localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)) },
  document: { getElementById: () => null, addEventListener() {}, querySelector: () => null },
  addEventListener() {}, setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {} };
s.window = s; vm.createContext(s);
vm.runInContext(read('src/core/position_v2.js'), s, { filename: 'src/core/position_v2.js' });
vm.runInContext(between(read('src/core/pro_v2.js'), 'function computePortfolioMetrics', '// Hook into renderPosition'), s,
  { filename: 'src/core/pro_v2.js' });
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
s.S.sym = '0050'; s.S.data = { candles: [] };

// 與 #229 相同的兩檔：一檔已載價、一檔未載價
s.S.positions = {
  2330: { entry: 1000, shares: 1000, lastPrice: 1100, mkt: 'TW' },
  2317: { entry: 200, shares: 5000, lastPrice: null, mkt: 'TW' },
};
const m = s.computePortfolioMetrics();
assert.equal(m.totalValue, 1100000);
assert.equal(m.totalCost, 2000000);
assert.ok(Math.abs(m.totalPnlPct - 10) < 1e-9, '舊版得 5%：' + m.totalPnlPct);
assert.equal(m.unknownCount, 1);
assert.equal(m.top1, null); assert.equal(m.hhi, null);
const unknown = m.items.find(x => x.code === '2317');
assert.equal(unknown.val, null); assert.equal(unknown.pnl, null);
assert.equal(m.items[m.items.length - 1].code, '2317', '未載價部位排在最後');
assert.ok(m.warnings.some(w => /1 檔未載價/.test(w.msg)));
const panel = text(s.renderPortfolioRisk());
assert.match(panel, /總市值 1,100,000（1 檔未載價）/, panel);
assert.match(panel, /合計損益 \+10\.00% \(\+100,000\)（1 檔未載價）/, panel);
assert.match(panel, /HHI 集中度 --（部分未載價）/);
assert.match(panel, /2317 .*持有 -- 未載價 市值 --（成本 \$1,000,000）/, panel);
assert.doesNotMatch(panel, /NaN/);

// 與持倉清單同一口徑
assert.equal(s.positionTotals().totalPnlPct, m.totalPnlPct);

// 全部已載價：集中度照算
s.S.positions = {
  2330: { entry: 1000, shares: 1000, lastPrice: 1100, mkt: 'TW' },
  2317: { entry: 200, shares: 5000, lastPrice: 180, mkt: 'TW' },
};
const full = s.computePortfolioMetrics();
assert.equal(full.unknownCount, 0);
assert.ok(Math.abs(full.top1 - 1100000 / 2000000 * 100) < 1e-9);
assert.ok(Math.abs(full.hhi - ((0.55 ** 2) + (0.45 ** 2))) < 1e-9);
assert.doesNotMatch(text(s.renderPortfolioRisk()), /未載價|NaN/);

// 全部未載價
s.S.positions = { 2317: { entry: 200, shares: 5000, lastPrice: null, mkt: 'TW' } };
const none = text(s.renderPortfolioRisk());
assert.match(none, /總市值 -- /); assert.match(none, /合計損益 價格未載入/); assert.doesNotMatch(none, /NaN/);
console.log('portfolio risk known cost selftest ok');

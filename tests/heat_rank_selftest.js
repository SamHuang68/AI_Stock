'use strict';
// 類股熱力圖名次：當日與前一交易日各自排序、同分依名稱、無前一日資料不顯示升降、標記轉義。
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const nodes = new Map();
function node() { return { innerHTML: '', textContent: '', style: {}, classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll() { return []; } }; }
const scope = { console, Date, Promise, AbortController, location: {}, localStorage: { getItem() { return null; } },
  addEventListener() {}, setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {},
  ShellV5: { route: () => 'heat', go() {} },
  document: { readyState: 'loading', getElementById: id => nodes.get(id) || null, createElement: node, addEventListener() {},
    head: { appendChild(el) { nodes.set(el.id, el); } } },
  fetch() { return new Promise(() => {}); } };
scope.window = scope;
const source = fs.readFileSync(path.join(root, 'src/ui/heat_v5.js'), 'utf8');
assert.ok(source.includes('  window.HeatV5 = {'), 'heat_v5.js 匯出位置改變，請同步更新本測試');
vm.runInNewContext(source.replace('  window.HeatV5 = {',
  'window.rankFixture={sectorRanks:sectorRanks,rankBadge:rankBadge,filterSectors:filterSectors,state:state}; window.HeatV5 = {'), scope);
const T = scope.rankFixture;

const rows = [
  { name: '水泥', changePct: 1.0, prevChangePct: -2.0 },
  { name: '航運', changePct: 3.0, prevChangePct: 1.0 },
  { name: '食品', changePct: 1.0, prevChangePct: 0.5 },     // 與水泥同分：依名稱排序
  { name: '電子', changePct: -1.0, prevChangePct: 2.0 },
  { name: '新類', changePct: 2.0 },                          // 無前一日資料
];
const ranks = T.sectorRanks(rows);
assert.deepEqual(JSON.parse(JSON.stringify(ranks)), {
  航運: { rank: 1, prevRank: 2 },
  新類: { rank: 2, prevRank: null },
  水泥: { rank: 3, prevRank: 4 },
  食品: { rank: 4, prevRank: 3 },
  電子: { rank: 5, prevRank: 1 },
});
assert.match(T.rankBadge(ranks['航運']), /#1▲1</);
assert.match(T.rankBadge(ranks['水泥']), /#3▲1</);
assert.match(T.rankBadge(ranks['食品']), /#4▼1</);
assert.match(T.rankBadge(ranks['電子']), /#5▼4</);
assert.match(T.rankBadge({ rank: 2, prevRank: 2 }), /#2＝</);
assert.equal(T.rankBadge(ranks['新類']), '', '無前一日名次不顯示升降');
assert.equal(T.rankBadge(undefined), '');
assert.match(T.rankBadge(ranks['航運']), /title="名次 1（前一交易日 2）"/);

// 名次只在畫面同一組類股內計算：被排除的非產業指數不佔名次。
T.state.sort = 'changePct';
const shown = T.filterSectors([{ name: '發行量加權股價指數', changePct: 9 }, ...rows], 'TW');
assert.equal(shown.some(r => r.name === '發行量加權股價指數'), false, '前提：加權指數不在熱力圖格子內');
assert.equal(T.sectorRanks(shown)['航運'].rank, 1);
console.log('heat_rank_selftest 通過：名次、前一日名次、同分排序、無資料不顯示、排除非產業指數');

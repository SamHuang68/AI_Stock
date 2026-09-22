'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/scan_v5.js'), 'utf8');
const nodes = new Map();
const node = id => {
  if (!nodes.has(id)) nodes.set(id, {
    value: '', checked: false, innerHTML: '', textContent: '', scrollTop: 0, scrollLeft: 0,
    focus() {}, querySelectorAll() { return []; }, querySelector() { return {focus() {}}; }
  });
  return nodes.get(id);
};
const window = {};
let next, calls = 0;
vm.runInNewContext(source.replace('window.ScanV5 = {', 'window.applyCandidateSort = applySort; window.ScanV5 = {'), {
  window, console, Date, setTimeout() {}, document: { getElementById: node },
  fetch: async () => { calls++; if (next instanceof Error) throw next; return {ok: true, json: async () => next}; }
});
const api = window.ScanV5;
const row = (sym, per) => ({sym, name: sym, per});
async function scan(rows, more = {}) {
  next = {results: rows, scanned: 80, techPass: 50, matched: rows.length, ...more};
  await api.scan();
}
const plain = value => JSON.parse(JSON.stringify(value));
(async () => {
  await scan([row('2330', 20), row('0050', null), row('2454', 10)]);
  assert.equal(api.comparison().previous, null);
  window.applyCandidateSort('per', 'ascending');
  await scan([row('2330', 8), row('2454', 10), row('00981A', null)], {matched: 90});
  let result = api.comparison();
  const first = result.rows.find(r => r.symbol === '2330');
  assert.equal(first.beforeRank, 2);
  assert.equal(first.afterRank, 1);
  assert.match(first.reason, /排序欄位值改變/);
  assert.deepEqual(plain(first.changes.find(c => c.field === 'PER')), {field:'PER',before:20,after:8});
  const same = result.rows.find(r => r.symbol === '2454');
  assert.equal(same.beforeRank, 1); assert.equal(same.afterRank, 2);
  assert.match(same.reason, /排序值未變/);
  assert.match(result.rows.find(r => r.symbol === '0050').reason, /不能推定/);
  assert.equal(result.rows.find(r => r.symbol === '00981A').afterRank, null, '未知不作零分或末名');
  assert.match(node('sc-results').innerHTML, /取得時間不等於行情/);
  assert.match(node('sc-results').innerHTML, /id="sc-comparison-export"/);
  assert.equal(result.current.response.matched, 90, '完整保存截斷母體');
  const beforeFailure = JSON.stringify(api.receipts());
  next = new Error('受控斷線');
  await api.scan();
  assert.equal(JSON.stringify(api.receipts()), beforeFailure);
  assert.equal(api.last()[0].per, 8);
  assert.match(node('sc-msg').textContent, /保留前次成功結果/);
  next = { results: [null] };
  await api.scan();
  assert.equal(JSON.stringify(api.receipts()), beforeFailure, '無效候選不得覆寫可用收據');
  node('sc-sector').value = '半導體';
  await scan([row('2330', 7)]);
  assert.equal(api.comparison().previous, null, '不同條件不比較');
  node('sc-sector').value = '';
  await scan([row('2330', 6), row('2454', false)]);
  result = api.comparison();
  assert.equal(result.previous.id, 2, '切回原條件找同範圍前次成功收據');
  assert.equal(result.rows.find(r => r.symbol === '2454').afterRank, null);
  const captured = api.receipts(); captured[0].response.results[0].per = 999;
  assert.equal(api.receipts()[0].response.results[0].per, 20, '對外副本不能覆寫原收據');
  await scan([row('2330', 6), row('2330', 7), row('<script>', 0)]);
  result = api.comparison();
  assert.equal(result.rows.find(r => r.symbol === '2330').afterRank, null);
  assert.match(result.rows.find(r => r.symbol === '2330').reason, /代號重複/);
  assert(!node('sc-results').innerHTML.includes('<script>'), '來源及比較文字必須跳脫');
  assert(node('sc-results').innerHTML.includes('&lt;script&gt;'));
  await scan([]);
  assert.match(node('sc-results').innerHTML, /候選位置與欄位變化/);
  assert.match(node('sc-results').innerHTML, /本次回傳未見/);
  assert.equal(api.receipts().length, 6, '空結果亦保留完整成功收據');
  assert.equal(calls, 8, '排序與比較不另觸發查詢');
  console.log('選股候選變化通過：同條件基準、真實排序差異、缺值與截斷、收據隔離、失敗保留及輸出跳脫。');
})().catch(error => { console.error(error); process.exitCode = 1; });

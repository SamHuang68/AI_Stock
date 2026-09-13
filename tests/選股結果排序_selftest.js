'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/scan_v5.js'), 'utf8');
const marker = 'window.ScanV5 = {';
assert.equal(source.split(marker).length, 2, '排序測試注入點須唯一');
const nodes = new Map();
let focus = null;
let requests = 0;
const node = id => {
  if (!nodes.has(id)) nodes.set(id, {
    value: '', innerHTML: '', scrollTop: 0, scrollLeft: 0,
    focus() { focus = id; }, querySelectorAll() { return []; },
    querySelector(selector) { return { focus() { focus = selector; } }; }
  });
  return nodes.get(id);
};
const window = { addEventListener() {} };
const sandbox = {
  window, console, document: { readyState: 'complete', getElementById: node },
  setTimeout() {}, fetch() { requests++; throw new Error('排序不得重新發出查詢'); }
};
vm.runInNewContext(source.replace(marker, `window.sortTest = {
  load: function(rows, settings) { lastResults = rows; lastResearchSettings = settings; renderResults(rows); },
  apply: applySort, cycle: cycleSort, formInput: onFormInput
}; ${marker}`), sandbox);
const api = window.ScanV5;
const test = window.sortTest;
const ids = rows => Array.from(api.sortRows(rows), row => row.sym);
const base = [
  {sym:'2330',name:'台積電',per:27.94,revYoy:53.3,trustStreak:-2},
  {sym:'5347',name:'世界',per:9,revYoy:0,trustStreak:10},
  {sym:'00631L',name:'ETF',per:null,revYoy:null,trustStreak:null},
  {sym:'2454',name:'聯發科',per:9,revYoy:-10,trustStreak:2}
];
const saved = JSON.stringify(base);
test.load(base, null);
node('sc-conditions-msg').textContent = '';
test.formInput({target:{id:'sc-sort-key',closest(){return {};}}});
assert.equal(node('sc-conditions-msg').textContent, '', '排序輸入不得標記查詢條件已變更');
test.formInput({target:{id:'sc-permax',closest(){return null;}}});
assert.match(node('sc-conditions-msg').textContent, /條件已更新/, '真正篩選條件仍須提示重新查詢');
test.cycle('per');
assert.deepEqual(ids(base), ['5347','2454','2330','00631L'], '數值升冪、同值穩定、缺值置底');
test.cycle('per');
assert.deepEqual(ids(base), ['2330','5347','2454','00631L'], '降冪仍將缺值置底');
node('sc-results').scrollTop = 120;
node('sc-results').scrollLeft = 80;
test.cycle('per');
assert.deepEqual(ids(base), base.map(r => r.sym), '第三次點擊還原本次查詢順序');
assert.equal(focus, '.sc-sort[data-sort="per"]', '還原排序後保留鍵盤焦點');
assert.equal(node('sc-results').scrollTop, 120);
assert.equal(node('sc-results').scrollLeft, 80);
assert.equal(JSON.stringify(base), saved, '排序不得改寫原始查詢資料');
node('sc-sort-key').value = 'revYoy';
node('sc-sort-key').onchange();
assert.deepEqual(ids(base), ['2454','5347','2330','00631L'], '選單支援負值與有效零值');
node('sc-sort-direction').value = 'descending';
node('sc-sort-direction').onchange();
assert.deepEqual(ids(base), ['2330','5347','2454','00631L']);
assert.equal(focus, 'sc-sort-direction');
test.apply('trustStreak', 'descending');
assert.deepEqual(ids(base), ['5347','2454','2330','00631L'], '法人觀察天數以原始數值排序');
const invalid = [{sym:'1',per:' '},{sym:'2',per:false},{sym:'3',per:Infinity},{sym:'4',per:NaN},{sym:'5',per:0}];
test.apply('per', 'ascending');
assert.deepEqual(ids(invalid), ['5','1','2','3','4'], '空白、布林、非有限數值不得當成合法零值');
const research = [
  {sym:'1',per:20,research:{drawdown100:-2,trustLatestShares:-50,trustNet5d:999,trustObservedDays:1}},
  {sym:'2',per:10,research:{drawdown100:-10,trustLatestShares:0,trustNet5d:0,trustObservedDays:5}},
  {sym:'3',per:30,research:{drawdown100:null,trustLatestShares:20,trustNet5d:30,trustObservedDays:5}},
  {sym:'4',per:null,research:{drawdown100:-5,trustLatestShares:null,trustNet5d:null,trustObservedDays:0}}
];
test.load(research, {enabled:true});
assert.deepEqual(ids(research), ['2','1','3','4'], '重新查詢或共用欄位切換模式時沿用排序');
test.apply('drawdown100', 'ascending');
assert.deepEqual(ids(research), ['2','4','1','3'], '研究模式可依巢狀回撤數值排序');
test.apply('trustNet5d', 'descending');
assert.deepEqual(ids(research), ['3','2','1','4'], '不足五日的淨買超視為缺值，不能排在完整數值前面');
assert.match(node('sc-results').innerHTML, /id="sc-sort-key"/);
assert.match(node('sc-results').innerHTML, /data-sort="drawdown100"/);
assert.match(node('sc-results').innerHTML, /投信近 5 日淨買超/);
assert.match(node('sc-results').innerHTML, /排序本次回傳的 4 檔/);
test.load(base, null);
assert.equal(api.sortState().direction, 'original', '換回一般模式時清除不適用的研究排序欄位');
node('sc-sort-reset').onclick();
assert.deepEqual(ids(base), base.map(r => r.sym));
assert.equal(requests, 0, '所有排序操作都直接使用既有結果');
console.log('選股結果排序驗證通過：兩種模式、選單與欄名、數值與缺值、還原、焦點及查詢保留。');

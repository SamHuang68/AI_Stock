'use strict';
// 一般結果排序自測：以 Node assert / vm / fs 跑實際 IIFE 及輕量 DOM mock，
// 涵蓋表頭點擊、欄位／方向下拉、重設鈕、無 refetch、缺值穩定、焦點與捲動保留。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE_PATH = path.join(__dirname, '..', 'src', 'ui', 'scan_v5.js');
const source = fs.readFileSync(SOURCE_PATH, 'utf8');

const marker = 'window.ScanV5 = {';
assert.equal(source.split(marker).length, 2, '注入點 window.ScanV5 必須唯一');

// 透過字串替換暴露內部函式給測試使用，避免污染正式 API。
const injection = [
  'window.__scanTest = {',
  '  load: function (rows) { lastResults = Array.isArray(rows) ? rows : []; renderResults(lastResults); },',
  '  cycle: cycleSort,',
  '  apply: applySort,',
  '  reset: resetSort,',
  '  scan: scan,',
  '  lastResults: function () { return lastResults; }',
  '};',
  ''
].join('\n');
const injected = source.replace(marker, injection + marker);

// -------- 輕量 DOM mock --------
let activeElement = null;
let fetchCount = 0;
const nodeMap = new Map();

function createSortButton(key) {
  let onclickFn = null;
  const btn = {
    _attrs: { 'data-sort': key },
    classList: {
      contains(name) { return name === 'sc-sort'; },
      add() {}, remove() {}
    },
    getAttribute(k) { return btn._attrs[k]; },
    setAttribute(k, v) { btn._attrs[k] = String(v); },
    focus() { activeElement = btn; }
  };
  Object.defineProperty(btn, 'onclick', {
    get() { return onclickFn; },
    set(fn) { onclickFn = fn; }
  });
  btn.click = function () { if (typeof onclickFn === 'function') onclickFn(); };
  return btn;
}

function createNode(id) {
  const self = {
    id: id,
    _attrs: {},
    _rawHtml: '',
    _sortButtons: [],
    value: '',
    textContent: '',
    scrollTop: 0,
    scrollLeft: 0,
    classList: { contains() { return false; }, add() {}, remove() {} },
    getAttribute(k) { return self._attrs[k]; },
    setAttribute(k, v) { self._attrs[k] = String(v); },
    focus() { activeElement = self; },
    appendChild() {},
    addEventListener() {},
    onclick: null,
    onchange: null,
    click() { if (typeof self.onclick === 'function') self.onclick(); },
    querySelector(selector) {
      const m = /\.sc-sort\[data-sort="([^"]+)"\]/.exec(selector);
      if (m) return self._sortButtons.find(b => b.getAttribute('data-sort') === m[1]) || null;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === '.sc-sort') return self._sortButtons.slice();
      return [];
    }
  };
  Object.defineProperty(self, 'innerHTML', {
    get() { return self._rawHtml; },
    set(v) {
      self._rawHtml = String(v);
      self._sortButtons = [];
      const re = /class="sc-sort"\s+data-sort="([^"]+)"/g;
      let m;
      while ((m = re.exec(self._rawHtml))) {
        self._sortButtons.push(createSortButton(m[1]));
      }
    }
  });
  return self;
}

function getById(id) {
  if (!nodeMap.has(id)) nodeMap.set(id, createNode(id));
  return nodeMap.get(id);
}

const documentMock = {
  readyState: 'complete',
  getElementById: getById,
  createElement: tag => createNode('__created_' + tag),
  head: { appendChild() {} },
  addEventListener() {}
};
Object.defineProperty(documentMock, 'activeElement', { get: () => activeElement });

const windowMock = { SERVER: '', addEventListener() {}, ShellV5: null };

const sandbox = {
  window: windowMock,
  document: documentMock,
  console: console,
  setTimeout: () => 0,
  clearTimeout: () => {},
  AbortController,
  fetch: () => { fetchCount++; throw new Error('排序流程不得觸發 fetch'); }
};

vm.runInNewContext(injected, sandbox);

const api = windowMock.ScanV5;
const test = windowMock.__scanTest;
assert.ok(api && typeof api.sortRows === 'function', 'window.ScanV5.sortRows 必須存在');
assert.ok(test, '測試注入 __scanTest 必須存在');

const ids = rows => Array.from(api.sortRows(rows), r => r.sym);

// 1. 初始載入維持原始順序
const base = [
  { sym: '2330', name: '台積電', per: 27.94, revYoy: 53.3, trustStreak: -2 },
  { sym: '5347', name: '世界', per: 9, revYoy: 0, trustStreak: 10 },
  { sym: '00631L', name: 'ETF', per: null, revYoy: null, trustStreak: null },
  { sym: '2454', name: '聯發科', per: 9, revYoy: -10, trustStreak: 2 }
];
const snapshot = JSON.stringify(base);
test.load(base);
assert.deepEqual(ids(base), ['2330', '5347', '00631L', '2454'], '初始沿用查詢回傳順序');
assert.equal(api.sortState().direction, 'original');

// 2. 表頭實際點擊：升冪、同值穩定、缺值永遠置底
let perBtn = getById('sc-results').querySelector('.sc-sort[data-sort="per"]');
assert.ok(perBtn, '表頭 PER 排序按鈕須渲染');
perBtn.click();
assert.deepEqual({ ...api.sortState() }, { key: 'per', direction: 'ascending' });
assert.deepEqual(ids(base), ['5347', '2454', '2330', '00631L'],
  '升冪：相同值依原順序穩定、缺值置底');

// 3. 再次點擊：降冪、缺值仍置底
perBtn = getById('sc-results').querySelector('.sc-sort[data-sort="per"]');
perBtn.click();
assert.equal(api.sortState().direction, 'descending');
assert.deepEqual(ids(base), ['2330', '5347', '2454', '00631L'], '降冪：缺值仍置底');

// 4. 第三次點擊：還原原始順序並保留捲動與鍵盤焦點
getById('sc-results').scrollTop = 120;
getById('sc-results').scrollLeft = 80;
perBtn = getById('sc-results').querySelector('.sc-sort[data-sort="per"]');
activeElement = perBtn;
perBtn.click();
assert.equal(api.sortState().direction, 'original', '第三次點擊回到原始順序');
assert.deepEqual(ids(base), base.map(r => r.sym));
assert.equal(getById('sc-results').scrollTop, 120, 'scrollTop 保留');
assert.equal(getById('sc-results').scrollLeft, 80, 'scrollLeft 保留');
assert.ok(
  activeElement && typeof activeElement.getAttribute === 'function' &&
  activeElement.getAttribute('data-sort') === 'per',
  '表頭排序後焦點保留於同欄按鈕'
);

// 5. 排序流程不得改寫 lastResults 內的原陣列
assert.equal(JSON.stringify(base), snapshot, 'lastResults 原陣列未被改寫');

// 6. 欄位下拉：負數與 0 皆保留
const keySel = getById('sc-sort-key');
keySel.value = 'revYoy';
activeElement = keySel;
keySel.onchange();
assert.deepEqual({ ...api.sortState() }, { key: 'revYoy', direction: 'ascending' });
assert.deepEqual(ids(base), ['2454', '5347', '2330', '00631L'],
  'YoY 升冪：有效負值與 0 保留、缺值置底');
assert.equal(activeElement.id, 'sc-sort-key', '欄位下拉操作後焦點保留');

// 7. 方向下拉：切換降冪
const dirSel = getById('sc-sort-direction');
dirSel.value = 'descending';
activeElement = dirSel;
dirSel.onchange();
assert.equal(api.sortState().direction, 'descending');
assert.deepEqual(ids(base), ['2330', '5347', '2454', '00631L'], 'YoY 降冪');
assert.equal(activeElement.id, 'sc-sort-direction', '方向下拉操作後焦點保留');

// 8. 程式介面 applySort：投信連買天數負值 / 缺值
test.apply('trustStreak', 'descending');
assert.deepEqual(ids(base), ['5347', '2454', '2330', '00631L'],
  '投信降冪保留負值、缺值置底');

// 9. 非數值類型：boolean / 純空白 / Infinity / NaN 皆視為缺值；有效 0 不受影響
const invalid = [
  { sym: '1', per: ' ' },
  { sym: '2', per: false },
  { sym: '3', per: Infinity },
  { sym: '4', per: NaN },
  { sym: '5', per: 0 }
];
test.apply('per', 'ascending');
assert.deepEqual(ids(invalid), ['5', '1', '2', '3', '4'],
  'bool / 純空白 / Infinity / NaN 皆不算合法數值；有效 0 仍為合法');

// 10. 重設按鈕：回到原始順序、焦點保留
test.load(base);
test.apply('per', 'descending');
assert.notEqual(api.sortState().direction, 'original');
const resetBtn = getById('sc-sort-reset');
activeElement = resetBtn;
resetBtn.onclick();
assert.equal(api.sortState().direction, 'original', '重設按鈕回到原始順序');
assert.deepEqual(ids(base), base.map(r => r.sym));
assert.equal(activeElement.id, 'sc-sort-reset', '重設按鈕操作後焦點保留');

// 11. 無障礙與工具列：aria-sort 須在 th；欄位／方向下拉與重設鈕齊備
test.apply('per', 'ascending');
const html = getById('sc-results').innerHTML;
assert.match(html, /<th aria-sort="ascending"/, 'aria-sort 必須標記在 th');
assert.match(html, /id="sc-sort-key"/, '須渲染欄位下拉');
assert.match(html, /id="sc-sort-direction"/, '須渲染方向下拉');
assert.match(html, /id="sc-sort-reset"/, '須渲染重設按鈕');
assert.match(html, /aria-live="polite"/, '排序狀態須 aria-live');
assert.match(html, /不代表全市場排序/, '須提示僅排序本次已載入資料');
assert.match(html, /class="sc-sort"\s+data-sort="per"/, '表頭排序按鈕必帶 data-sort');

// 12. 一般結果為 11 欄：代號／名稱／價／漲跌／RSI／量比／營收YoY／PER／殖利／投信／外資
const thCount = (html.match(/<th\s/g) || []).length;
assert.equal(thCount, 12, '一般結果 11 欄 + 1 欄「加入自選」共 12 個 th');

// 13. 全程零 refetch
assert.equal(fetchCount, 0, '所有排序操作皆不得呼叫 fetch');

const research = [
  {sym:'1', research:{distanceToTopPct:null, valuationDate:null}},
  {sym:'2', research:{distanceToTopPct:0, valuationDate:'2026-10-01'}},
  {sym:'3', research:{distanceToTopPct:-10, valuationDate:'2026-09-30'}},
  {sym:'4', research:{distanceToTopPct:0, valuationDate:'2026-10-01'}}
];
const frozenResearch = JSON.stringify(research);
test.load(research);
test.apply('research.distanceToTopPct', 'ascending');
assert.deepEqual(ids(research), ['3','2','4','1'], '研究巢狀欄位保留零、負值、穩定同值及缺值');
test.apply('research.distanceToTopPct', 'descending');
assert.deepEqual(ids(research), ['2','4','3','1']);
test.apply('research.valuationDate', 'ascending');
assert.deepEqual(ids(research), ['3','2','4','1'], '來源日期按實際日期排序');
assert.match(getById('sc-results').innerHTML, /估值承接/);
assert.equal(JSON.stringify(research), frozenResearch);
assert.equal(fetchCount, 0, '研究排序不重新查詢');

console.log('一般結果排序驗證通過：點擊 / 下拉 / 重設、負值零保留、缺值穩定置底、無 refetch、焦點與捲動保留。');

// 觀察下限不能畫成完整連買；來源說明必須跳脫屬性字元。
test.load([{sym:'2330',trustStreak:2,trustStreakComplete:false,foreignStreak:-3,foreignStreakComplete:false,
  fieldStatus:{trustStreak:'缺日 "範圍" <未知>'}}]);
assert.match(getById('sc-results').innerHTML, /≥\+2/);
assert.match(getById('sc-results').innerHTML, /≤-3/);
assert.match(getById('sc-results').innerHTML, /缺日 &quot;範圍&quot; &lt;未知&gt;/);

(async function () {
  const pending=[];
  sandbox.fetch=(_url,opts)=>new Promise(resolve=>pending.push({resolve,signal:opts.signal}));
  test.scan(); test.scan();
  assert(pending[0].signal.aborted, '新掃描取消前次請求');
  const reply=(sym)=>({ok:true,json:async()=>({results:[{sym}],scanned:1,techPass:1,matched:1})});
  pending[1].resolve(reply('最新'));
  await new Promise(setImmediate);
  pending[0].resolve(reply('舊結果'));
  await new Promise(setImmediate);
  assert.deepEqual(Array.from(test.lastResults(),r=>r.sym),['最新']);
  assert.match(getById('sc-results').innerHTML, /最新/);
  assert(!getById('sc-results').innerHTML.includes('舊結果'));
  console.log('籌碼觀察下限、說明跳脫與逆序請求驗證通過。');
})().catch(error=>{console.error(error);process.exitCode=1;});

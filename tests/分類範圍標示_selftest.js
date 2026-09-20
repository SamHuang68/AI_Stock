'use strict';

// 載入完整正式模組，直接驗證產業資金流 render 的範圍文字與數字。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/decision_v5.js'), 'utf8');
const marker = '  window.DecisionV5 = {';
assert.equal(source.split(marker).length, 2, '正式 render 接線必須唯一');
const state = { console, addEventListener() {} };
state.window = state;
vm.createContext(state);
vm.runInContext(source.replace(marker, 'window.renderSectorTest = sectorHtml;\n' + marker), state,
  { filename: 'src/ui/decision_v5.js' });

const label = '上市四碼證券（含存託憑證；未分類仍計入成交分母）';
function fixture(scope) {
  return { sectorFlow: {
    label: '產業資金流', marketScope: 'TW', turnoverScope: scope,
    participationPct: 63.5, turnoverCoveragePct: 99.7, top3SharePct: 52.1, hhi: 1200,
    historyStatus: { rs20Available: false, historyDates: 8 },
    rows: [
      { sector: '半導體', marketSharePct: 35.25, changePct: 1.25,
        rs20VsBenchmarkPct: 2.3, turnoverScope: scope },
      { sector: '代理籃子', marketSharePct: 10, changePct: -0.5,
        proxyBasket: true, turnoverScope: scope },
      { sector: '複合類別', marketSharePct: null, changePct: 0,
        turnoverEligible: false, turnoverScope: scope }
    ]
  } };
}
function render(data) {
  const before = JSON.stringify(data);
  const html = state.renderSectorTest(data);
  assert.equal(JSON.stringify(data), before, '範圍文字不得更動來源資料');
  assert.match(html, /上漲參與 63\.5% · 成交覆蓋 99\.7% · Top3 52\.1% · HHI 1200/);
  assert.match(html, /建置 8\/21 交易日/);
  assert.match(html, /半導體<\/td><td>1\.25%<\/td><td>35\.25%<\/td><td>\+2\.30%/);
  assert.match(html, /代理籃子<\/td><td>-0\.50%<\/td><td>10\.00%<\/td><td>—<\/td><td>proxyBasket/);
  assert.match(html, /複合類別<\/td><td>0\.00%<\/td><td>—<\/td><td>—<\/td><td>複合指數/);
  assert.doesNotMatch(html, /上市普通股/);
  return html;
}

let canonical;
for (const scope of ['TWSE_FOUR_DIGIT_SECURITIES_BY_INDUSTRY', 'TWSE_COMMON_STOCKS_BY_INDUSTRY']) {
  const html = render(fixture(scope));
  assert(html.includes('成交口徑：' + label));
  assert(html.includes('<td>' + label + '</td>'));
  assert.equal(html.split(label).length - 1, 2, '母體說明僅用於總覽與符合 scope 的列');
  assert(!html.includes(scope), '已辨認的範圍以中文呈現');
  if (canonical) assert.equal(html, canonical, '新舊代碼應呈現同一實際母體');
  canonical = html;
}
const unknown = render(fixture('UNKNOWN_PROXY_SCOPE'));
assert.match(unknown, /成交口徑：UNKNOWN_PROXY_SCOPE/);
assert.match(unknown, /<td>UNKNOWN_PROXY_SCOPE<\/td>/);
assert(!unknown.includes(label), '未知來源不得套用 TWSE 四碼證券母體');

const escaped = render(fixture('UNKNOWN<img src=x>'));
assert(escaped.includes('UNKNOWN&lt;img src=x&gt;'));
assert(!escaped.includes('<img'), '來源範圍文字必須轉義');
const missing = fixture(null);
missing.sectorFlow.rows[0].marketScope = 'US';
const missingHtml = render(missing);
assert(!missingHtml.includes('成交口徑：'));
assert.match(missingHtml, /<td>US<\/td>/);
assert(!missingHtml.includes(label));
console.log('分類範圍標示：新舊代碼、未知來源、代理籃子、複合指數與數字保留通過');

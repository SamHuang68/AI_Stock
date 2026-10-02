'use strict';
// 僅讀指定結果與 ST 既有純計算核心；不載入瀏覽器、不連線。
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');
const assert = require('assert/strict');
const root = path.resolve(__dirname, '..', '..');
const output = path.resolve(process.argv[2] || '');
const relative = path.relative(path.join(root, 'scratch'), output);
assert(relative && !relative.startsWith('..') && !path.isAbsolute(relative), '輸出必須在 scratch 子目錄。');
const read = name => JSON.parse(fs.readFileSync(path.join(output, name), 'utf8'));
const snapshot = read('輸入快照.json');
const expected = read('既有核心預期.json');
const source = fs.readFileSync(path.join(root, 'src', 'screener', 'backtest_v3.js'), 'utf8');
const hash = crypto.createHash('sha256').update(source).digest('hex');
assert.equal(hash, expected['既有核心雜湊'], '既有核心在研究後改變，必須重新產生研究。');
const context = { window: {} };
vm.runInNewContext(source, context, { timeout: 3000 });
const b = context.window.Backtest;
assert.equal(b.ENGINE_VERSION, 'st-backtest/4.0.2', '核心版本改變，需重新審查對照契約。');
const candles = snapshot['日線'].map(r => ({time:r['時間戳'], open:r['開盤'], high:r['最高'], low:r['最低'], close:r['收盤'], volume:r['成交量']}));
const fast = b.sma(candles.map(r => r.close), 20);
const slow = b.sma(candles.map(r => r.close), 60);
const buy = fast.map((v, i) => slow[i] != null && v > slow[i]);
assert.deepEqual(Array.from(buy, Number), expected['訊號'], '兩邊均線訊號不一致。');
const actual = b.runLS(candles, buy, buy.map(x => !x), {tp:0, sl:0, maxBars:0, market:'TW', ...expected['成本基點']});
assert.equal(actual.trades.length, expected['交易'].length, '交易筆數不一致。');
let maxError = 0;
for (let i = 0; i < actual.trades.length; i++) {
  for (const key of ['entryBar','exitBar','entry','exit','ret']) {
    const delta = Math.abs(actual.trades[i][key] - expected['交易'][i][key]);
    maxError = Math.max(maxError, delta);
    assert(delta < 1e-12, `第 ${i + 1} 筆交易的 ${key} 不一致。`);
  }
}
assert.equal(actual.curve.length, expected['每日權益'].length, '每日權益筆數不一致。');
for (let i=0; i<actual.curve.length; i++) {
  const delta = Math.abs(actual.curve[i].equity - expected['每日權益'][i]);
  maxError = Math.max(maxError, delta);
  assert(delta < 1e-10, `第 ${i+1} 根每日權益不一致。`);
}
assert.equal(!!actual.openPosition, expected['未平倉'], '未平倉狀態不一致。');
assert(Math.abs(actual.maxDD - expected['最大回撤百分比']) < 1e-9, '每日最大回撤不一致。');
const result = { '通過':true, '交易筆數':actual.trades.length, '最大欄位誤差':maxError,
  '既有核心雜湊':hash, '核心版本':b.ENGINE_VERSION, '每日權益筆數':actual.curve.length,
  '隔日開盤含成本累積報酬百分比':actual.totalReturn, '成本基點':expected['成本基點'],
  '說明':'研究與 ST 使用相同隔日開盤及成本模型，逐筆交易、每日權益與回撤獨立核對；年化夏普口徑不同，不比較其數值。' };
fs.writeFileSync(path.join(output, '既有核心核對.json'), JSON.stringify(result, null, 2), 'utf8');
const htmlPath = path.join(output, '研究報告.html');
const marker = '<span id="legacy-status">尚未執行獨立核對</span>';
let html = fs.readFileSync(htmlPath, 'utf8');
assert(html.includes(marker), '報告核對狀態不符，拒絕覆寫。');
html = html.replace(marker, `<span id="legacy-status">通過，共 ${actual.trades.length} 筆交易</span>`);
fs.writeFileSync(htmlPath, html, 'utf8');
console.log(JSON.stringify(result));

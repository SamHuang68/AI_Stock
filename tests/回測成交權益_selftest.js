/* 下一棒成交、逐棒權益與未知風險；固定合成行情、禁止連外。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sandbox = { window: {}, console, fetch() { throw new Error('測試禁止連外'); } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/screener/backtest_v3.js'), 'utf8'), sandbox);
const bt = sandbox.window.Backtest;
const bar = (time, open = 100, close = open) => ({ time, open, close, high: Math.max(open, close) + 1, low: Math.min(open, close) - 1, volume: 1000 });
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
let count = 0;
function test(name, body) { body(); count++; console.log('通過：' + name); }
test('收盤訊號後下一棒開盤並於退出訊號後下一棒成交', () => {
  const result = bt.runLS([bar(0), bar(1, 110, 111), bar(2, 112)], [true], [false, true]);
  assert.equal(result.trades[0].entryBar, 1); assert.equal(result.trades[0].exitBar, 2);
  near(result.trades[0].entry, 110); near(result.totalReturn, (112 / 110 - 1) * 100);
  assert.match(result.engineVersion, /next-open/);
});
test('當日收盤斷點不追溯改寫已排定的開盤成交', () => {
  const exited = bt.runLS([bar(0), bar(1), bar(2, 99, 50)], [true], [false, true]);
  assert.equal(exited.count, 1); assert.equal(exited.trades[0].exit, 99); near(exited.totalReturn, -1);
  const entered = bt.runLS([bar(0), bar(1, 100, 50)], [true], []);
  assert.equal(entered.openPosition.entry, 100); assert.equal(entered.openPosition.entryBar, 1);
  assert.equal(entered.totalReturn, null);
});
test('持有期停止成交與投組合成保留未知而非零估值', () => {
  const paused = Object.assign(bar(2), { volume: 0 });
  const result = bt.runLS([bar(0), bar(1), paused], [true], []);
  assert.equal(result.totalReturn, null); assert.equal(result.maxDD, null);
  const combined = bt.portfolio({ A: result.curve, B: [{ time: 0, equity: 1 }, { time: 2, equity: 1.2 }] });
  assert.equal(combined.finalReturn, null);
  assert.equal(bt.portfolio({ A: [] }).finalReturn, null);
  assert.throws(() => bt.portfolio({ A: [] }, { A: -1 }), /權重/);
});
test('費用賣出稅費與不利滑價按兩邊實際成交金額計算', () => {
  const result = bt.runLS([bar(0), bar(1, 110, 112), bar(2, 115)], [true], [false, true], { feeRate: .002, taxRate: .003, slippage: .01 });
  near(result.totalReturn, (115 * .99 * .995 / (110 * 1.01 * 1.002) - 1) * 100);
  assert.ok(result.trades[0].entryCosts > 0); assert.ok(result.trades[0].exitCosts > result.trades[0].entryCosts);
});
test('持有期下跌後回升仍留下逐棒回撤', () => {
  const result = bt.runLS([bar(0), bar(1, 100, 95), bar(2, 95, 85), bar(3, 85, 95), bar(4, 100)], [true], [false, false, false, true]);
  near(result.totalReturn, 0); near(result.maxDD, 15); assert.equal(result.curve.length, 5);
});
test('收盤停損後跳空按次棒開盤實現虧損', () => {
  const result = bt.run([bar(0), bar(1, 100, 90), bar(2, 85)], [true], { sl: .08, tp: 0, maxBars: 0 });
  near(result.totalReturn, -15); assert.equal(result.trades[0].reason, 'sl'); near(result.trades[0].exit, 85);
});
test('期末未平倉有估值但不冒充完成交易', () => {
  const result = bt.runLS([bar(0), bar(1, 100, 95), bar(2, 95, 96)], [true], []);
  assert.equal(result.count, 0); assert.ok(result.openPosition); near(result.totalReturn, -4);
  assert.equal(result.openPosition.pendingExit, null);
});
test('期末最後訊號只有待進場沒有虛構交易', () => {
  const result = bt.run([bar(0)], [true]); assert.equal(result.count, 0); assert.ok(result.pendingEntry); assert.equal(result.openPosition, null);
});
test('無成交進場取消且不跳到之後有效棒', () => {
  const rows = [bar(0), { ...bar(1), volume: 0 }, bar(2)];
  const result = bt.runLS(rows, [true], []); assert.equal(result.openPosition, null); assert.equal(result.rejected[0].bar, 1);
});
test('出場無法成交保留部位並在後續有效開盤完成', () => {
  const rows = [bar(0), bar(1), { time: 2, open: 99, high: 99, low: 99, close: 99, volume: 1000 }, bar(3, 98)];
  const result = bt.runLS(rows, [true], [false, true]); assert.equal(result.trades[0].exitBar, 3); near(result.totalReturn, -2);
  assert.equal(result.rejected[0].kind, 'exit');
});
test('缺估值期間令完整回撤未知而不是零', () => {
  const rows = [bar(0), bar(1), { ...bar(2), close: null }, bar(3)];
  const result = bt.runLS(rows, [true], []); assert.equal(result.maxDD, null); assert.equal(result.status, 'unknown'); assert.equal(result.curve[2].equity, null);
});
test('公司行動或無法解釋斷點後不可恢復虛構已知損益', () => {
  const rows = [bar(0), bar(1), bar(2, 25), bar(3, 26)];
  const result = bt.runLS(rows, [true], [false, true]); assert.equal(result.totalReturn, null); assert.equal(result.count, 0); assert.ok(result.openPosition.accountingUnknown);
});
test('空頭極端虧損保留負權益並停止新部位', () => {
  const result = bt.runLS([bar(0), bar(1), bar(2, 300), bar(3, 300)], [true, false, false, true], [false, false, true], { short: true, corporateActionsVerified: true });
  near(result.totalReturn, -200); near(result.maxDD, 200); assert.equal(result.bankrupt, true); assert.equal(result.pendingEntry, null);
});
test('空資料與短日內資料不假造年化有效性', () => {
  const empty = bt.runLS([], [], []); assert.equal(empty.count, 0); assert.equal(empty.sharpeAnn, null); assert.equal(empty.curve.length, 0);
  assert.equal(empty.totalReturn, null); assert.equal(empty.maxDD, null); assert.equal(empty.status, 'insufficient');
  const result = bt.runLS([bar(60), bar(120)], [true], [], { barsPerYear: 100000 });
  assert.match(result.methodology.annualization, /100000/); assert.equal(result.count, 0);
});
test('未知成本參數拒絕不偷偷改為預設', () => {
  assert.throws(() => bt.run([bar(0)], [true], { feeRate: NaN }), /參數無效/);
});
console.log(`回測成交與權益 ${count} 組驗證通過`);

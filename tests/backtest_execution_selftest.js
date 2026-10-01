const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/screener/backtest_v3.js'), 'utf8'), sandbox);
const B = sandbox.window.Backtest;
const fixtures = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/backtest_execution.json'), 'utf8'));
const zero = { entryFeeBps: 0, exitFeeBps: 0, slippageBps: 0 };
const near = (actual, expected, label) => assert.ok(Math.abs(actual - expected) < 1e-10, `${label}: ${actual} != ${expected}`);
const copy = x => JSON.parse(JSON.stringify(x));
function run(f, opts = {}) { return B.runLS(f.candles, f.buy, f.sell, { ...zero, market: f.market, ...opts }); }

// 預期值由現金／股數手算；不以舊引擎或同一函式產生期望答案。
const tw = run(fixtures.tw_drawdown);
assert.equal(tw.trades[0].signalBar, 0);
assert.equal(tw.trades[0].entryBar, 1);
assert.equal(tw.trades[0].exitBar, 3);
assert.deepEqual(Array.from(tw.curve, p => +p.equity.toFixed(10)), [1, .8, 1.2, 1.1]);
near(tw.maxDD, 20, '持倉期間最大回撤');
near(tw.totalReturn, 10, '已實現報酬');
assert.equal(tw.curve.length, 4);
const returns = [-.2, .5, -1 / 12], mean = 13 / 180;
const sd = Math.sqrt((Math.pow(-.2 - mean, 2) + Math.pow(.5 - mean, 2) + Math.pow(-1 / 12 - mean, 2)) / 2);
near(tw.sharpe, mean / sd * Math.sqrt(252), '每日年化夏普');
assert.equal(tw.sharpeAnn, tw.sharpe);
const rf = run(fixtures.tw_drawdown, { annualRiskFreeRate: .05, periodsPerYear: 250 });
near(rf.sharpe, (mean - (Math.pow(1.05, 1 / 250) - 1)) / sd * Math.sqrt(250), '一致無風險基準');

const cost = run(fixtures.us_costs, { entryFeeBps: 100, exitFeeBps: 200, slippageBps: 100 });
near(cost.trades[0].entry, 101, '進場不利滑價');
near(cost.trades[0].exit, 118.8, '出場不利滑價');
near(cost.totalReturn, (116.424 / 102.01 - 1) * 100, '雙邊實際成交金額費用');
near(cost.trades[0].ret * 100, cost.totalReturn, '逐筆與權益成本一致');
const shortFixture = copy(fixtures.us_costs);
Object.assign(shortFixture.candles[2], { open: 80, high: 80, low: 80, close: 80 });
const short = run(shortFixture, { short: true, entryFeeBps: 100, exitFeeBps: 200, slippageBps: 100 });
near(short.totalReturn, (98.01 - 82.416) / 99.99 * 100, '放空雙邊費用與不利滑價');
assert.ok(cost.totalReturn < run(fixtures.us_costs).totalReturn);

const suspended = run(fixtures.tw_etf_suspension);
assert.equal(suspended.trades[0].entryBar, 3);
assert.equal(suspended.trades[0].exitBar, 4);
near(suspended.totalReturn, 10, '停牌後以真實開盤進場');
assert.equal(suspended.curve[2].valuation, 'carried');
assert.ok(suspended.issues.some(i => i.code === 'untradable_bar'));
assert.equal(B.colsOf([{volume: null}]).volume[0], null);
assert.equal(B.colsOf([{volume: 0}]).volume[0], 0);

const range = run(fixtures.us_etf_same_bar_range, { tp: .1, sl: .1 });
assert.equal(range.trades[0].exitSignalBar, 2, '高低同根穿越不捏造停損停利先後');
assert.equal(range.trades[0].exitBar, 3);
assert.equal(range.trades[0].reason, 'tp');
near(range.totalReturn, 5, '停利訊號後跳空不保證門檻價');
const stop = copy(fixtures.tw_drawdown);
const stopResult = run(stop, { sl: .1, maxBars: 1 });
assert.equal(stopResult.trades[0].reason, 'sl', '收盤停損優先於持有期滿');
near(stopResult.trades[0].exit, 90, '收盤停損次日開盤');
const timed = run(fixtures.us_costs, { maxBars: 1 });
assert.equal(timed.trades[0].reason, 'time');
assert.equal(timed.trades[0].exitBar, 2);

const open = run({ ...fixtures.tw_drawdown, sell: [false, false, false, false] });
assert.equal(open.count, 0);
assert.equal(open.winRate, null);
assert.ok(open.openPosition);
near(open.totalReturn, 10, '未平倉估值仍入權益');
near(open.maxDD, 20, '未平倉回撤');
const last = run({ ...fixtures.us_costs, buy: [false, false, true] });
assert.equal(last.count, 0);
assert.equal(last.openPosition, null);
assert.equal(last.pendingOrder.side, 'entry');
assert.ok(last.issues.some(i => i.code === 'no_next_tradable_bar'));
const exitLast = run({ ...fixtures.us_costs, sell: [false, false, true] });
assert.equal(exitLast.openPosition.pendingExit, 'signal');
assert.equal(exitLast.count, 0);
const noTrades = run({ ...fixtures.us_costs, buy: [false, false, false] });
assert.equal(noTrades.totalReturn, 0);
assert.equal(noTrades.maxDD, 0);
assert.equal(noTrades.winRate, null);
assert.equal(noTrades.sharpe, null);
assert.equal(B.runLS([], [], []).asOf, null);

const gap = copy(fixtures.tw_drawdown);
gap.candles[2].close = null;
const carried = run(gap);
near(carried.curve[2].equity, .8, '缺收盤沿用上一估值');
assert.equal(carried.curve[2].valuation, 'carried');
assert.equal(carried.count, 0, '缺收盤不可形成出場訊號');
const haltedExit = copy(fixtures.tw_drawdown);
haltedExit.candles[3].volume = 0;
assert.equal(run(haltedExit).openPosition.pendingExit, 'signal');

for (const invalid of [{ entryFeeBps: -1 }, { slippageBps: NaN }, { exitFeeBps: null }, { maxBars: 1.2 },
  { market: 'NYSE' }, { sl: 1 }, { short: 'false' }, { periodsPerYear: 0 }]) {
  assert.throws(() => run(fixtures.us_costs, invalid));
}
for (const candles of [[fixtures.us_costs.candles[1], fixtures.us_costs.candles[0]],
  [fixtures.us_costs.candles[0], fixtures.us_costs.candles[0]],
  [{ time: '2026-02-30', close: 100 }], [{ time: '2026-01-01', open: -1 }]]) {
  assert.throws(() => B.runLS(candles, candles.map(() => false), null));
}
assert.throws(() => B.runLS(fixtures.us_costs.candles, [], null));
assert.equal(B.dateKey(Date.parse('2026-01-02T01:00:00Z') / 1000, 'TW'), '2026-01-02');
assert.equal(B.dateKey(Date.parse('2026-01-02T01:00:00Z') / 1000, 'US'), '2026-01-01');
assert.equal(B.dateKey({year: 2026, month: 1, day: 2}, 'TW'), '2026-01-02');
assert.equal(B.sma([1, null, 3], 2)[2], null);
assert.equal(B.sma([0, 2], 2)[1], 1);
assert.equal(B.rsi([1, 2, null, 3, 4, 5], 2)[3], null);
assert.equal(B.rsi([1, 2, null, 3, 4, 5], 2)[5], 100);
assert.equal(B.portfolio({empty: []}), null);
const basket = B.portfolio({TW: [{time:'2026-01-02',equity:1.1}], US: [{time:'2026-01-01',equity:1.2}]});
assert.deepEqual(Array.from(basket.curve, p => p.date), ['2026-01-01', '2026-01-02']);
near(basket.finalReturn, 15, '組合按交易日對齊');
assert.throws(() => B.portfolio({a: [{time:'2026-01-01',equity:1}]}, {a:2}));
const insolventFixture = copy(fixtures.us_costs);
Object.assign(insolventFixture.candles[1], {open:100,high:250,low:100,close:250});
const insolvent = run(insolventFixture, {short:true});
assert.ok(insolvent.issues.some(i => i.code === 'non_positive_equity'));
assert.equal(insolvent.trades[0].reason, 'insolvent');
const extendedInsolvent = copy(insolventFixture);
extendedInsolvent.candles.push({...extendedInsolvent.candles[2], time:'2026-09-24'});
extendedInsolvent.buy = [true,false,true,true]; extendedInsolvent.sell = [false,false,false,false];
const halted = run(extendedInsolvent, {short:true});
assert.equal(halted.halted, true);
assert.equal(halted.pendingOrder, null, '權益耗盡後即使跳空恢復，也不重新開倉');
assert.equal(halted.openPosition, null);
const pfBars = [100,100,150,100,90].map((open,i)=>({time:`2026-09-${21+i}`,open,
  high:Math.max(open,[100,150,150,90,90][i]),low:Math.min(open,[100,150,150,90,90][i]),close:[100,150,150,90,90][i],volume:1000}));
const pf = B.runLS(pfBars,[true,false,true,false,false],null,{...zero,maxBars:1});
near(pf.profitFactor, 10/3, '獲利因子依實際已實現金額加總');

const series = Array.from({length: 220}, (_, i) => {
  const close = 100 + 12 * Math.sin(i / 5) + i / 10;
  return { time: new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10), open: close - 1,
    high: close + 2, low: close - 2, close, volume: 1000 };
});
const splitOpts = { ...zero, trainEnd: series[139].time, testEnd: series[219].time, maxBars: 5 };
const split = B.evaluateStrategies(series, splitOpts);
assert.ok(split.selected);
assert.equal(split.test.evaluation, 'fixed-holdout');
assert.ok(split.test.trades.every(t => t.signalTime > splitOpts.trainEnd && t.time > t.signalTime));
const changedFuture = series.map((b, i) => i > 139 ? {...b, open:b.open*3, high:b.high*3, low:b.low*3, close:b.close*3} : b);
const again = B.evaluateStrategies(changedFuture, splitOpts);
assert.equal(again.selected, split.selected, '測試期不得影響策略選擇');
assert.deepEqual(Array.from(again.training, r => r.totalReturn), Array.from(split.training, r => r.totalReturn));
for (const r of split.training.concat(split.test)) {
  assert.equal(r.settings.slippageBps, 0);
  assert.equal(r.settings.entryFeeBps, 0);
}
const feeSplit = B.evaluateStrategies(series, { ...splitOpts, entryFeeBps: 25, exitFeeBps: 35, slippageBps: 15 });
assert.ok(feeSplit.training.concat(feeSplit.test).every(r => r.settings.entryFeeBps === 25 && r.settings.slippageBps === 15));
assert.throws(() => B.evaluateStrategies(series, {}));
assert.throws(() => B.evaluateStrategies(series, {trainEnd:'2026-01-01', testEnd:'2025-01-01'}));
const prefix = series.slice(0, 140);
const signal = B.STRATEGIES.sma20_pullback.fn(B.colsOf(series));
const before = B.run(series, signal, zero), prefixResult = B.run(prefix, signal.slice(0, 140), zero);
assert.deepEqual(Array.from(before.curve.slice(0, 140), p => p.equity), Array.from(prefixResult.curve, p => p.equity), '追加未來資料不得改寫既有權益');
const causal = B.STRATEGIES.sma20_pullback.fn(B.colsOf(changedFuture));
assert.deepEqual(Array.from(signal.slice(0, 140)), Array.from(causal.slice(0, 140)));
console.log('PASS 回測成交、成本、逐日回撤、夏普、缺資料、台美股／ETF、未平倉與固定樣本外契約');

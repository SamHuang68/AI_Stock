const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = { window: {}, console };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/screener/backtest_v3.js'), 'utf8'), context);
const B = context.window.Backtest;
const zero = { entryFeeBps: 0, exitFeeBps: 0, slippageBps: 0 };
const bar = (i, open = 100, close = open) => ({ time: new Date(Date.UTC(2026, 0, 1 + i)).toISOString().slice(0, 10),
  open, high: Math.max(open, close), low: Math.min(open, close), close, volume: 1000 });
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-12, `${a} != ${b}`);

// 不能由未知最高價推導突破；兩種符合已知收盤價的補值會得到相反答案。
const missing = [], warmup = [];
assert.equal(B.breakout([100, null, 300], [100, 200, 300], 2, missing)[2], false);
assert.equal(B.breakout([100, 200, 300], [100, 200, 300], 2)[2], true);
assert.equal(B.breakout([100, 400, 300], [100, 200, 300], 2)[2], false);
assert.equal(missing[2].code, 'missing_lookback_high');
assert.deepEqual(Array.from(missing[2].missingBars), [1]);
assert.match(B.describeIssue(missing[2]), /第 2 根/);
assert.deepEqual(Array.from(B.breakout([100, 101], [100, 101], 2, warmup)), [false, false]);
assert.deepEqual(Array.from(warmup, x => x.availableBars), [0, 1]);
for (const p of [20, 60]) {
  const bars = Array.from({ length: p + 5 }, (_, i) => bar(i, 100 + i));
  bars[1].high = null;
  const issues = [], signal = B.STRATEGIES['breakout' + p].fn(B.colsOf(bars), issues);
  assert.equal(signal[p], false);
  assert.equal(signal[p + 1], false);
  assert.equal(signal[p + 2], true, '缺值離開回看窗口後恢復');
  const result = B.scanStrategies(bars, { ...zero, maxBars: 1 }).find(r => r.key === 'breakout' + p);
  const gap = result.issues.filter(i => i.code === 'missing_lookback_high');
  assert.deepEqual(Array.from(gap, x => x.date), [bars[p].time, bars[p + 1].time]);
  assert.deepEqual(Array.from(gap[0].missingDates), [bars[1].time]);
  assert.equal(gap[0].windowStartDate, bars[0].time);
  assert.equal(gap[0].windowEndDate, bars[p - 1].time);
  assert.equal(result.trades[0].signalBar, p + 2);
  assert.equal(result.trades[0].entryBar, p + 3);
  assert.match(B.describe(result), /2 根突破訊號因回看最高價缺值未判定/);
  assert.ok(B.describe(result).includes(bars[1].time));
}
// 暖機讀到的缺值可追溯，但提醒所屬日期只限測試區間。
const splitBars = Array.from({ length: 130 }, (_, i) => bar(i, 100 + i));
splitBars[88].high = null;
const split = B.evaluateStrategies(splitBars, { ...zero, maxBars: 1, trainEnd: splitBars[89].time, testEnd: splitBars[129].time });
assert.equal(split.selected, 'breakout20');
assert.ok(split.test.issues.every(i => !i.date || (i.date >= splitBars[90].time && i.date <= splitBars[129].time)));
assert.ok(split.test.issues.some(i => i.missingDates?.includes(splitBars[88].time)));
assert.equal(split.test.trades[0].signalBar, 109);
const earlier = B.evaluateStrategies(splitBars, { ...zero, maxBars: 1, trainEnd: splitBars[89].time, testEnd: splitBars[100].time });
assert.ok(earlier.test.issues.every(i => !i.date || i.date <= splitBars[100].time));

// 舊數值時間戳須帶市場；日期字串、BusinessDay、原生 date 均維持兩參數相容。
const usClose = Date.parse('2026-01-02T21:00:00Z') / 1000;
const twClose = Date.parse('2026-01-02T05:30:00Z') / 1000;
const curves = { TW: [{ time: twClose, equity: 1.1 }], US: [{ time: usClose, equity: 1.2 }] };
assert.throws(() => B.portfolio(curves), /缺交易日與市場/);
assert.throws(() => B.portfolio(curves, null, { TW: 'TW' }), /US 缺交易日與市場/);
assert.throws(() => B.portfolio(curves, null, { TW: 'TW', US: 'NYSE' }), /缺交易日與市場/);
const mixed = B.portfolio(curves, null, { TW: 'TW', US: 'US' });
assert.equal(mixed.curve.length, 1);
assert.equal(mixed.curve[0].date, '2026-01-02');
near(mixed.curve[0].equity, 1.15);
near(mixed.finalReturn, 15);
assert.equal(B.portfolio({ TW: curves.TW }, null, { TW: 'TW' }).curve[0].date, '2026-01-02');
const native = B.portfolio({ US: [{ time: usClose, date: '2026-01-02', equity: 1.2 }] }, null, { US: 'TW' });
assert.equal(native.curve[0].date, '2026-01-02', '明確 date 優先，不重新解讀 timestamp');
assert.equal(B.portfolio({ US: [{ time: '2026-01-02', equity: 1.2 }] }).curve[0].date, '2026-01-02');
assert.equal(B.portfolio({ TW: [{ time: { year: 2026, month: 1, day: 2 }, equity: 1.1 }] }).curve[0].date, '2026-01-02');
assert.throws(() => B.portfolio({ US: [{ time: usClose, date: '2026-02-30', equity: 1.2 }] }), /有效的交易日/);
assert.throws(() => B.portfolio({ US: [{ time: usClose, date: '', equity: 1.2 }] }), /有效的交易日/);

// 原 Sharpe 規則不變，原因按無效日、樣本數、沒有成交、零變異依序判定。
const noBars = B.runLS([], [], null, zero);
assert.equal(noBars.sharpeReason, 'insufficient_samples');
const noTrades = B.runLS([bar(0), bar(1), bar(2)], [false, false, false], null, zero);
assert.equal(noTrades.sharpe, null);
assert.equal(noTrades.sharpeReason, 'no_trades');
assert.match(B.describe(noTrades), /沒有實際成交/);
const flatOpen = B.runLS([bar(0), bar(1), bar(2)], [true, false, false], null, zero);
assert.equal(flatOpen.count, 0);
assert.ok(flatOpen.openPosition);
assert.equal(flatOpen.sharpeReason, 'zero_variance', '有未平倉成交，不可說成沒有交易');
const valuedOpen = B.runLS([bar(0), bar(1, 100, 110), bar(2, 110, 100)], [true, false, false], null, zero);
assert.equal(valuedOpen.count, 0);
assert.ok(Number.isFinite(valuedOpen.sharpe));
assert.equal(valuedOpen.sharpeReason, null);
const zeroEnd = [bar(0), bar(1), bar(2, 100, 200)];
const finalZero = B.runLS(zeroEnd, [true, false, false], null, { ...zero, short: true });
assert.equal(finalZero.curve[2].equity, 0);
near(finalZero.sharpe, -Math.sqrt(126));
assert.equal(finalZero.sharpeReason, null);
const afterZero = B.runLS([...zeroEnd, bar(3, 180)], [true, false, false, false], null, { ...zero, short: true });
assert.equal(afterZero.dailyReturns[2], null);
assert.equal(afterZero.sharpe, null);
assert.equal(afterZero.sharpeReason, 'non_positive_prior_equity');
assert.match(B.describe(afterZero), /前期權益非正/);
const negative = B.runLS([bar(0), bar(1, 100, 250), bar(2, 180)], [true, false, false], null, { ...zero, short: true });
assert.equal(negative.curve[1].equity, -.5);
assert.equal(negative.dailyReturns[1], null);
assert.equal(negative.sharpeReason, 'non_positive_prior_equity');
assert.equal(negative.dailyReturns.length, 2, '不刪除無效日重算');
console.log('PASS 回測缺值追溯、樣本外提醒界線、台美投組日期及 Sharpe 空值原因');

#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const api = require('../src/core/估值承接核心.js');
let count = 0;
function test(name, run) { run(); count++; console.log('通過：' + name); }
function near(actual, expected) { assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} 與 ${expected} 不符`); }
const noFees = { buyFeePct: 0, sellFeePct: 0, sellTaxPct: 0, minFee: 0 };
const profile = { eps: 10, peLow: 20, peHigh: 30 };
const observation = { symbol: '2330', price: 250, officialPe: 25 };
const batches = [90, 81, 72.9].map(price => ({ price, shares: 100 }));

test('缺值與非有限值不冒充零，負零正規化為零', () => {
  [null, undefined, '', ' ', true, false, NaN, Infinity, -Infinity, {}, [], 'abc'].forEach(value => assert.equal(api.number(value), null));
  assert.equal(api.number('0'), 0); assert.equal(Object.is(api.number(-0), -0), false);
  assert.equal(api.number('-10'), -10); assert.equal(api.number(' 0.1425 '), 0.1425);
});
test('瀏覽器與 Node 共用同一純計算入口', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/core/估值承接核心.js'), 'utf8'), context);
  assert.equal(typeof context.ValuationResearch.evaluate, 'function');
  assert.equal(context.ValuationResearch.number(null), null);
});
test('預設 IP 分類、代碼尾碼及使用者覆寫', () => {
  assert.equal(api.classify('3529.TW').category, 'ip'); assert.equal(api.classify('6643').category, 'ip');
  assert.equal(api.classify('3529', 'general').category, 'general');
  assert.equal(api.classify('2330', 'ai_cycle').categoryLabel, 'AI供應鏈／題材循環');
});
test('研究範圍不設 PE 20 下限，零負缺值不列入', () => {
  [0.01, 10, 20, 30].forEach(officialPe => assert.equal(api.evaluate({ ...observation, officialPe }, profile).scope, 'in_scope'));
  [null, '', 0, -10].forEach(officialPe => assert.equal(api.evaluate({ ...observation, officialPe }, profile).scope, 'pe_unknown'));
  assert.equal(api.evaluate({ ...observation, officialPe: 30.01 }, profile).scope, 'pe_above');
});
test('IP 預設排除，AI 題材不自動提高估值上緣', () => {
  assert.equal(api.evaluate({ ...observation, symbol: '3529' }, profile).scope, 'exclude_ip');
  assert.equal(api.evaluate({ ...observation, symbol: '3529' }, profile, { excludeIp: false }).scope, 'in_scope');
  assert.equal(api.evaluate({ ...observation, officialPe: 70 }, { ...profile, category: 'ai_cycle' }).scope, 'pe_above');
  assert.equal(api.evaluate({ ...observation, officialPe: 35 }, profile, { peMax: 40 }).scope, 'in_scope');
  assert.equal(api.evaluate(observation, profile, { peMax: null }).scope, 'pe_unknown');
});
test('官方 PE 不反推假設 EPS，缺假設不提供合理價', () => {
  const result = api.evaluate(observation, {});
  assert.equal(result.low, null); assert.equal(result.high, null); assert.equal(result.hypothesisPe, null);
  assert.equal(result.valuationStatus, 'need_assumption');
});
test('估值區間、承接差距與假設 PE 使用明確輸入', () => {
  const result = api.evaluate(observation, profile);
  assert.equal(result.low, 200); assert.equal(result.high, 300); assert.equal(result.entry, 200); assert.equal(result.exit, 300);
  assert.equal(result.hypothesisPe, 25); near(result.entryGapPct, 25); assert.equal(result.valuationStatus, 'in_range');
  assert.equal(api.evaluate({ ...observation, price: 200 }, profile).valuationStatus, 'below_entry');
  assert.equal(api.evaluate({ ...observation, price: 301 }, profile).valuationStatus, 'above_range');
});
test('無效或倒置估值不以預設值遮掩', () => {
  [{ ...profile, eps: 0 }, { ...profile, eps: -1 }, { ...profile, peLow: 40 }, { ...profile, entryPrice: 0 }, { ...profile, exitPrice: -0 }].forEach(input => {
    const result = api.evaluate(observation, input); assert.equal(result.valuationStatus, 'need_assumption'); assert.ok(result.errors.length);
  });
  const custom = api.evaluate(observation, { ...profile, entryPrice: 190, exitPrice: 280 });
  assert.equal(custom.entry, 190); assert.equal(custom.exit, 280);
});
test('三批承接算例在 85 元退出合計獲利 1110 元', () => {
  const result = api.calculatePosition(batches, noFees, 72.9, 85);
  assert.equal(result.shares, 300); near(result.principal, 24390); near(result.averageCost, 81.3);
  near(result.breakEven, 81.3); near(result.currentPnl, -2520); near(result.exitPnl, 1110);
  assert.equal(result.remainingBudget, null);
});
test('反彈仍低於成本時，完整部位保持負損益', () => {
  near(api.calculatePosition(batches, noFees, 72, 72).currentPnl, -2790);
});
test('逐筆買入最低費及賣出最低費均納入', () => {
  const result = api.calculatePosition(batches, {}, 85, 85);
  near(result.buyFees, 60); near(result.totalCost, 24450); near(result.averageCost, 81.5);
  near(result.exitPnl, 937.1625);
  near(api.calculatePosition(batches, {}, result.breakEven).currentPnl, 0);
  const tiny = api.calculatePosition([{ price: 10, shares: 1 }], {}, 10, 50);
  near(tiny.totalCost, 30); near(tiny.breakEven, 50 / 0.997); near(tiny.exitPnl, -0.15);
});
test('資金含買進費，超額顯示負剩餘金額，無上限不默認零', () => {
  const result = api.calculatePosition(batches, { ...noFees, budget: 24000 }, 85);
  near(result.remainingBudget, -390); assert.ok(result.errors.some(text => text.includes('超過')));
  assert.equal(api.calculatePosition([], {}, 100).remainingBudget, null);
  assert.equal(api.calculatePosition([], { budget: 1000 }, 100).remainingBudget, 1000);
});
test('股數須為正整數，錯誤批次不計入局部持倉', () => {
  [0, -1, 1.5, null, '', true, Number.MAX_SAFE_INTEGER + 1].forEach(shares => {
    const result = api.calculatePosition([{ price: 100, shares }], noFees, 100);
    assert.equal(result.totalCost, null); assert.equal(result.shares, 0); assert.ok(result.errors.length);
  });
  [0, -0, -100, null, '', Infinity].forEach(price => assert.ok(api.calculatePosition([{ price, shares: 100 }], noFees, 100).errors.length));
});
test('明確空費率拒算，合法零費率保留', () => {
  ['buyFeePct', 'sellFeePct', 'sellTaxPct', 'minFee'].forEach(key => {
    [null, '', false, -1, Infinity].forEach(value => {
      const result = api.calculatePosition(batches, { ...noFees, [key]: value }, 85);
      assert.equal(result.totalCost, null); assert.ok(result.errors.length);
    });
  });
  assert.equal(api.calculatePosition(batches, { ...noFees, sellTaxPct: 11 }, 85).totalCost, null);
  assert.equal(api.calculatePosition(batches, noFees, 85).buyFees, 0);
});
test('空持倉與極端金額不產生 NaN 或無限值', () => {
  [api.calculatePosition([], {}, 100), api.calculatePosition([{ price: Number.MAX_VALUE, shares: 100 }], {}, 100)].forEach(result => {
    Object.values(result).forEach(value => { if (typeof value === 'number') assert.ok(Number.isFinite(value)); });
    assert.equal(result.shares, 0); assert.equal(result.breakEven, null);
  });
  const tiny = api.calculatePosition([{ price: Number.MIN_VALUE, shares: 1 }], noFees, 100);
  assert.equal(tiny.currentPnlPct, null);
  const underflow = api.evaluate(observation, { eps: Number.MIN_VALUE, peLow: 0.01, peHigh: 30 });
  assert.equal(underflow.low, null); assert.ok(underflow.errors.length);
});
test('計算不改寫使用者假設與持倉', () => {
  const input = { ...profile, tranches: batches, ...noFees }, before = JSON.stringify(input);
  api.evaluate(observation, input); assert.equal(JSON.stringify(input), before);
});
const previous = { symbol: '2330', profileRevision: '一', priceAsOf: '2026-09-09', valuationDate: '2026-09-09', scope: 'pe_above', priceState: 'above_range' };
const current = { ...previous, priceAsOf: '2026-09-10', scope: 'in_scope', priceState: 'below_entry' };
test('相同版本才比較範圍與價格狀態，改假設不冒充行情事件', () => {
  assert.deepEqual(api.compareSnapshot(null, current, '2026-09-10'), ['首次記錄']);
  assert.equal(api.compareSnapshot(previous, current, '2026-09-10').length, 2);
  assert.deepEqual(api.compareSnapshot(previous, { ...current, profileRevision: '二' }, '2026-09-10'), ['估值假設已更新']);
  assert.deepEqual(api.compareSnapshot(current, current, '2026-09-10'), []);
});
test('不同股票、日期倒退、未來或無效日期皆不新增事件', () => {
  [{ ...current, symbol: '2317' }, { ...current, priceAsOf: '2026-09-08' }, { ...current, priceAsOf: '2026-09-11' },
    { ...current, priceAsOf: null }, { ...current, priceAsOf: '2026-02-30' }, { ...current, valuationDate: '2026-09-11' },
    { ...current, valuationDate: '2026-09-08' }].forEach(snapshot => assert.deepEqual(api.compareSnapshot(previous, snapshot, '2026-09-10'), []));
});
console.log('估值承接核心：' + count + ' 組測試全部通過。');

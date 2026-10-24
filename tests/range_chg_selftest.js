#!/usr/bin/env node
/**
 * 區間漲跌口徑自測：日漲跌(昨收) vs 區間漲跌(chartPreviousClose / trim 前一根)
 * 對齊 Yahoo/iOS Stocks：現價旁同時顯示兩者。
 * 另驗證 hero 現價在 quote/rmp 與 bar close 分歧時仍取 canonical last。
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sourcePath = path.join(__dirname, '..', 'stock_terminal.html');
const source = fs.readFileSync(sourcePath, 'utf8');
const elements = Object.fromEntries(['ci-high', 'ci-chg', 'ci-range-chg'].map(id =>
  [id, { style: {}, innerHTML: '', textContent: '', classList: { remove() {} } }]));
const context = vm.createContext({
  document: { getElementById: id => elements[id] || null },
  window: {}, S: { range: '3mo', sym: '2330', data: {} },
});

function requiredSource(pattern, label) {
  const matches = [...source.matchAll(pattern)];
  if (matches.length !== 1) throw new Error(`Expected one production ${label}, found ${matches.length}`);
  return matches[0][0];
}

// Execute the actual top-level declarations. A renamed/moved declaration must
// fail this harness rather than leave a stale copy of the old implementation.
for (const name of ['calcChgFromBase', '_posPrice', 'resolveCanonicalHeroPrice',
  'patchTodayDailyBarWithLive', 'updateHeaderHigh', 'fmtChgAbsPct', 'updateHeaderChg']) {
  vm.runInContext(requiredSource(new RegExp(`^function ${name}\\([^]*?^}`, 'gm'), name),
    context, { filename: sourcePath });
}
const { calcChgFromBase, resolveCanonicalHeroPrice, patchTodayDailyBarWithLive,
  updateHeaderHigh, updateHeaderChg } = context;

// Range selection is currently inline in loadSymbol. Run its two real sections
// with fixture data; fetching/rendering between them is outside this contract.
const rangeSelection = requiredSource(
  /^  let _rangeBase = null;[^]*?(?=^  \/\/ ── Yahoo data freshness fix)/gm, 'range selection');
const rangeFallback = requiredSource(
  /^  if \(!\(_rangeBase > 0\)[^]*?(?=^  const _rangeLbl)/gm, 'range fallback');
const productionRangeBase = new Function('parsed', 'rdef', rangeSelection + rangeFallback
  + '\nreturn { rangeBase: _rangeBase, candles: parsed.candles };');
function pickRangeBase({ candles, trim, chartPreviousClose }) {
  return productionRangeBase({ candles, meta: { chartPreviousClose } }, { trim });
}

let failed = 0;
function assert(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); failed++; }
  else console.log('OK  ', msg);
}

// Case 1: YTD — chartPreviousClose = 年初前收，昨收獨立
{
  const price = 2280, yClose = 2270, cpc = 1585; // ≈ +695 YTD
  const { rangeBase } = pickRangeBase({ candles: [{ close: price }], chartPreviousClose: cpc });
  const day = calcChgFromBase(price, yClose);
  const rng = calcChgFromBase(price, rangeBase);
  assert(rangeBase === cpc, 'YTD 使用正式選取的 chartPreviousClose');
  assert(day && Math.abs(day.delta - 10) < 1e-9, '日漲跌絕對值 +10');
  assert(rng && Math.abs(rng.delta - 695) < 1e-9, 'YTD 區間漲跌 +695');
  assert(rng.pct > 40 && rng.pct < 45, 'YTD 漲幅約 43%');
}

// Case 2: 6mo — 與日漲跌分離
{
  const price = 2280, yClose = 2270, cpc = 1820; // ≈ +460 / 6mo
  const day = calcChgFromBase(price, yClose);
  const rng = calcChgFromBase(price, cpc);
  assert(day.delta === 10, '6mo 情境日漲跌仍為昨收基準');
  assert(Math.abs(rng.delta - 460) < 1e-9, '6mo 區間漲跌 +460');
}

// Case 3: trim 3周 — 用視窗前一根，而非整段 1mo 的 chartPreviousClose
{
  const candles = [];
  for (let i = 0; i < 20; i++) candles.push({ close: 100 + i }); // 100..119
  const { rangeBase, candles: shown } = pickRangeBase({
    candles, trim: 15, chartPreviousClose: 50, // CPC 是 1mo 前，不該用
  });
  assert(shown.length === 15, 'trim 後剩 15 根');
  assert(rangeBase === 104, '3周基準 = trim 前一根 close(104)，非 chartPreviousClose(50)');
  const last = shown[shown.length - 1].close;
  const rng = calcChgFromBase(last, rangeBase);
  assert(rng && Math.abs(rng.delta - 15) < 1e-9, '3周漲跌 = 119-104 = +15');
}

// Case 4: 無 CPC → 退回第一根收盤
{
  const candles = [{ close: 10 }, { close: 12 }, { close: 15 }];
  const { rangeBase } = pickRangeBase({ candles, trim: null, chartPreviousClose: null });
  assert(rangeBase === 10, '缺 CPC 時用第一根 close');
}

// Case 5: 正式 UI 更新器須隱藏 1 天的重複區間漲跌，其他區間仍顯示。
{
  context.S.range = '1d';
  updateHeaderChg(100, 98, 98, '1天', 'TW', '2330');
  assert(elements['ci-range-chg'].style.display === 'none', '1天隱藏重複區間列');
  assert(elements['ci-chg'].innerHTML.includes('+2.00'), '1天仍顯示日漲跌');
  context.S.range = '3mo';
  updateHeaderChg(100, 98, 80, '3月', 'TW', '2330');
  assert(elements['ci-range-chg'].style.display === '', '3月顯示區間列');
  assert(elements['ci-range-chg'].innerHTML.includes('+25.00%'), '3月顯示正式區間漲幅');
}

// Case 6: 2330 情境 — 3月 range 最後 bar close=2460，quote/rmp=2455 → hero 必為 2455
{
  const barClose = 2460, quotePrice = 2455, rmp = 2455;
  const t = 1700000000;
  const hero = resolveCanonicalHeroPrice({
    barClose, quotePrice, regularMarketPrice: rmp,
    regularMarketTime: t, lastBarTime: t, isDaily: true,
  });
  assert(hero === 2455, 'quote 優先於 stale bar close (2460→2455)');
  const rng = calcChgFromBase(hero, 2360);
  assert(rng && Math.abs(rng.delta - 95) < 1e-9, '區間漲跌仍用 canonical last 對 rangeBase');
}

// Case 7: 無 quote 時同日 regularMarketPrice 覆蓋 bar close
{
  const t = 1700000000;
  const hero = resolveCanonicalHeroPrice({
    barClose: 2460, quotePrice: null, regularMarketPrice: 2455,
    regularMarketTime: t, lastBarTime: t, isDaily: true,
  });
  assert(hero === 2455, '同日 RMP 覆蓋 stale bar close');
}

// Case 8: patchTodayDailyBarWithLive 同步最後一根供圖表軸
{
  const t = 1700000000;
  const candles = [{ time: t - 86400, open: 2400, high: 2420, low: 2390, close: 2410 },
    { time: t, open: 2410, high: 2460, low: 2405, close: 2460 }];
  const patched = patchTodayDailyBarWithLive(candles, { regularMarketPrice: 2455, regularMarketTime: t }, '1d');
  assert(patched === 2455, 'patch 回傳對齊後 close');
  assert(candles[1].close === 2455 && candles[1]._livePatched, '最後一根 close 已對齊 RMP');
}

// Case 9: 00631L — quote last=37.84、dayHigh=37.99；hero=收盤，今日最高可高於收盤（正常 OHLC）
{
  const t = 1700000000;
  const hero = resolveCanonicalHeroPrice({
    barClose: 37.80, quotePrice: 37.84,
    regularMarketPrice: 37.84, regularMarketTime: t, lastBarTime: t, isDaily: true,
  });
  const dayHigh = 37.99;
  const candles = [{ time: t, open: 36.70, high: 37.50, low: 36.50, close: 37.80 }];
  patchTodayDailyBarWithLive(candles, {
    regularMarketPrice: 37.84, regularMarketDayHigh: dayHigh,
    regularMarketDayLow: 36.50, regularMarketTime: t,
  }, '1d');
  const hdrHigh = updateHeaderHigh(candles, '3月', hero, dayHigh);
  assert(hero === 37.84, '00631L hero 收盤 = quote last');
  assert(hdrHigh === 37.99, '00631L 今日最高 = dayHigh（可 > 收盤）');
  assert(hdrHigh >= hero, 'dayHigh >= hero（不要求相等）');
}

// Case 10: stale bar high 低於 quote dayHigh → patch 不得把 high 壓成 close
{
  const t = 1700000000;
  const candles = [{ time: t, open: 36.70, high: 37.50, low: 36.50, close: 37.50 }];
  patchTodayDailyBarWithLive(candles, {
    regularMarketPrice: 37.84, regularMarketDayHigh: 37.99,
    regularMarketTime: t,
  }, '1d');
  assert(candles[0].close === 37.84, 'patch close 對齊 quote');
  assert(candles[0].high === 37.99, 'patch high 取 regularMarketDayHigh，非壓成 close');
}

// Case 11: 1 天行情標頭必須使用同盤快照最高，不能混入歷史最高。
{
  context.S.range = '1d';
  context.S.data.marketHeadline = { price: 42650, high: 43873, session: 'night' };
  const high = updateHeaderHigh([{ high: 50000 }], '1天', 42650, 49000);
  assert(high === 43873, '正式行情標頭最高來自同盤快照');
  assert(elements['ci-high'].innerHTML.includes('夜盤最高'), '夜盤標籤與行情一致');
  assert(context.S.data.periodHigh === 43873, '狀態與顯示使用相同最高價');
  context.S.data.marketHeadline.high = 42000;
  assert(updateHeaderHigh([{ high: 50000 }], '1天', 42650, 49000) === null,
    '低於現價的同盤最高不得回退成歷史最高');
  assert(elements['ci-high'].innerHTML.includes('未提供'), '無效最高明確顯示未提供');
}

if (failed) { console.error('\n' + failed + ' failed'); process.exit(1); }
console.log('\nAll range-chg selftests passed.');

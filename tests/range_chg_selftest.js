#!/usr/bin/env node
/**
 * 區間漲跌口徑自測：日漲跌(昨收) vs 區間漲跌(chartPreviousClose / trim 前一根)
 * 對齊 Yahoo/iOS Stocks：現價旁同時顯示兩者。
 * 另驗證 hero 現價在 quote/rmp 與 bar close 分歧時仍取 canonical last。
 */
'use strict';

function calcChgFromBase(price, base) {
  if (!(price > 0) || !(base > 0)) return null;
  const delta = price - base;
  return { delta, pct: delta / base * 100 };
}

function _posPrice(v) {
  return (v != null && isFinite(v) && v > 0) ? v : null;
}

function resolveCanonicalHeroPrice(opts) {
  const barClose = _posPrice(opts && opts.barClose);
  const quotePrice = _posPrice(opts && opts.quotePrice);
  const rmp = _posPrice(opts && opts.regularMarketPrice);
  const rmt = opts && opts.regularMarketTime;
  const lastBarTime = opts && opts.lastBarTime;
  const isDaily = !!(opts && opts.isDaily);
  if (quotePrice) return quotePrice;
  if (isDaily && rmp && rmt && lastBarTime && Math.abs(rmt - lastBarTime) <= 20 * 3600) {
    return rmp;
  }
  if (rmp && rmt && lastBarTime && (rmt - lastBarTime) > 20 * 3600) {
    return rmp;
  }
  return barClose ?? rmp ?? null;
}

function patchTodayDailyBarWithLive(candles, meta, interval) {
  if (!candles || !candles.length || !meta) return null;
  const isDaily = interval === '1d' || interval === '1wk';
  if (!isDaily) return null;
  const last = candles[candles.length - 1];
  const rmp = _posPrice(meta.regularMarketPrice);
  const rmt = meta.regularMarketTime;
  if (!rmp || !rmt || !last || !last.time) return null;
  if (Math.abs(rmt - last.time) > 20 * 3600) return null;
  if (Math.abs(last.close - rmp) < 1e-9) return rmp;
  last.close = rmp;
  if (rmp > (last.high || rmp)) last.high = rmp;
  if (rmp < (last.low || rmp)) last.low = rmp;
  last._livePatched = true;
  return rmp;
}

function pickRangeBase({ candles, trim, chartPreviousClose }) {
  let rangeBase = null;
  if (trim && candles.length > trim) {
    const preIdx = candles.length - trim - 1;
    if (preIdx >= 0 && candles[preIdx].close > 0) rangeBase = candles[preIdx].close;
    candles = candles.slice(-trim);
  } else if (chartPreviousClose != null && isFinite(chartPreviousClose) && chartPreviousClose > 0) {
    rangeBase = chartPreviousClose;
  }
  if (!(rangeBase > 0) && candles.length >= 1 && candles[0].close > 0) {
    rangeBase = candles[0].close;
  }
  return { rangeBase, candles };
}

let failed = 0;
function assert(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); failed++; }
  else console.log('OK  ', msg);
}

// Case 1: YTD — chartPreviousClose = 年初前收，昨收獨立
{
  const price = 2280, yClose = 2270, cpc = 1585; // ≈ +695 YTD
  const day = calcChgFromBase(price, yClose);
  const rng = calcChgFromBase(price, cpc);
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

// Case 5: 1天不應與日漲跌重複顯示（呼叫端隱藏；此處只驗證基準可等同昨收）
{
  const price = 100, prev = 98;
  const day = calcChgFromBase(price, prev);
  const rng = calcChgFromBase(price, prev);
  assert(day.delta === rng.delta && day.pct === rng.pct, '1天區間基準≡昨收時數值相同→UI 應隱藏區間列');
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

if (failed) { console.error('\n' + failed + ' failed'); process.exit(1); }
console.log('\nAll range-chg selftests passed.');

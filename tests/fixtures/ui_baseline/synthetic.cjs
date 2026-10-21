// UI 同條件對照用的合成資料：全部是示意數字，不是真實行情，也不含任何個人資料。
// 同一個輸入永遠產生同一份輸出（固定種子），讓兩個版本拿到完全相同的回應。
'use strict';

const SOURCE = 'ui-baseline-fixture';
const FIXED_DATE = '2026-01-15';
const FIXED_AS_OF = FIXED_DATE + 'T10:30:00+08:00';
const FIXED_EPOCH_MS = Date.parse(FIXED_AS_OF);

function seedOf(text) {
  let h = 2166136261;
  for (const ch of String(text)) { h ^= ch.codePointAt(0); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

function random(seed) {
  let t = seed >>> 0;
  return () => {
    t = (t + 0x6D2B79F5) >>> 0;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

const round = (value, digits = 2) => Number(value.toFixed(digits));

// 120 個交易日（跳過週末）的日線，最後一根是 FIXED_DATE。
function dailyBars(symbol, count = 120) {
  const rand = random(seedOf(symbol));
  const base = symbol.startsWith('^') || symbol.startsWith('__') ? 20000 : 50 + rand() * 900;
  const days = [];
  for (let d = new Date(FIXED_DATE + 'T00:00:00Z'); days.length < count; d = new Date(d.getTime() - 86400000)) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) days.unshift(d.getTime() / 1000 + 3600); // 09:00 台北
  }
  let close = base;
  return days.map(time => {
    const open = close * (1 + (rand() - 0.5) * 0.01);
    close = Math.max(1, open * (1 + (rand() - 0.48) * 0.03));
    const high = Math.max(open, close) * (1 + rand() * 0.01);
    const low = Math.min(open, close) * (1 - rand() * 0.01);
    return { time, open: round(open), high: round(high), low: round(low), close: round(close),
      volume: Math.round(1e6 + rand() * 9e6) };
  });
}

function yahooChart(symbol) {
  const bars = dailyBars(symbol);
  const last = bars[bars.length - 1], prev = bars[bars.length - 2];
  return { chart: { error: null, result: [{
    meta: { symbol, shortName: symbol + '（示意）', currency: symbol.endsWith('.TW') || symbol.startsWith('^TW') ? 'TWD' : 'USD',
      regularMarketPrice: last.close, chartPreviousClose: prev.close, previousClose: prev.close,
      regularMarketTime: Math.floor(FIXED_EPOCH_MS / 1000), dataGranularity: '1d', exchangeTimezoneName: 'Asia/Taipei' },
    timestamp: bars.map(b => b.time),
    indicators: { quote: [{ open: bars.map(b => b.open), high: bars.map(b => b.high), low: bars.map(b => b.low),
      close: bars.map(b => b.close), volume: bars.map(b => b.volume) }] },
  }] } };
}

function canonicalQuote(symbol, name, price, prevClose) {
  const change = round(price - prevClose), changePct = round((price - prevClose) / prevClose * 100, 3);
  const market = { symbol, market: 'TW', price, referencePrice: prevClose, referenceType: 'previous_close',
    displayChange: change, displayChangePct: changePct, session: 'regular', source: SOURCE, asOf: FIXED_AS_OF };
  return { price, prevClose, change, changePct, name, source: SOURCE, session: 'regular',
    open: prevClose, high: Math.max(price, prevClose), low: Math.min(price, prevClose), asOf: FIXED_AS_OF,
    tradeDate: FIXED_DATE, market, displayChange: change, displayChangePct: changePct,
    referencePrice: prevClose, referenceType: 'previous_close' };
}

function marketSnapshot() {
  return { ok: true, contractVersion: 1, updatedAt: FIXED_AS_OF, generatedAt: FIXED_AS_OF, marketAsOf: FIXED_AS_OF,
    sessionDate: FIXED_DATE, session: 'regular', sourceStatus: { [SOURCE]: 'ok' },
    quotes: {
      '^TWII': canonicalQuote('^TWII', '加權指數（示意）', 23456.78, 23321.09),
      '^TWOII': canonicalQuote('^TWOII', '櫃買指數（示意）', 256.43, 258.12),
      '__TXF__': canonicalQuote('__TXF__', '台指期（示意）', 23440.00, 23300.00),
    } };
}

const TW_SECTORS = ['水泥類指數', '食品類指數', '塑膠類指數', '紡織纖維類指數', '電機機械類指數', '電器電纜類指數',
  '半導體類指數', '電腦及週邊設備類指數', '光電類指數', '通信網路類指數', '電子零組件類指數', '航運類指數',
  '金融保險類指數', '貿易百貨類指數', '生技醫療類指數', '綠能環保類指數'];
const US_SECTORS = [['XLK', '科技'], ['XLF', '金融'], ['XLE', '能源'], ['XLV', '醫療'], ['XLY', '非必需消費'],
  ['XLP', '必需消費'], ['XLI', '工業'], ['XLB', '原物料'], ['XLU', '公用事業'], ['XLRE', '不動產'], ['XLC', '通訊']];

function sectors(mkt) {
  const rand = random(seedOf('sectors-' + mkt));
  const rows = mkt === 'US'
    ? US_SECTORS.map(([symbol, name]) => ({ symbol, name: name + '（示意）' }))
    : TW_SECTORS.map(name => ({ name }));
  // 台股另附前一交易日漲跌（對應 /sectors 的 prevChangePct／prevSession）；最後一個類股刻意不附，覆蓋「無前一日資料」。
  const prevDate = '20260114';
  return { ok: true, market: mkt, date: FIXED_DATE.replace(/-/g, ''), source: SOURCE,
    sectorFlow: { label: '示意資料：同範圍漲跌參與' },
    prevSession: mkt === 'TW' ? { date: prevDate, status: 'found', source: SOURCE } : undefined,
    sectors: rows.map((row, i) => {
      const out = { ...row, close: round(50 + rand() * 450), changePct: round((rand() - 0.45) * 6),
        marketSharePct: mkt === 'TW' ? round(rand() * 12, 1) : null, rs20VsBenchmarkPct: round((rand() - 0.5) * 10, 1) };
      const prev = round((rand() - 0.5) * 5);
      if (mkt === 'TW' && i < rows.length - 1) Object.assign(out, { prevChangePct: prev, prevSessionDate: prevDate });
      return out;
    }) };
}

// 回傳 { json } 表示有合成回應；回傳 null 表示這個端點沒有 fixture（呼叫端回 {} 並列入報告）。
function respond(method, url) {
  const p = url.pathname;
  if (method === 'GET' && p.startsWith('/yf/') && p !== '/yf/batch') {
    return { json: yahooChart(decodeURIComponent(p.slice(4))) };
  }
  if (method === 'GET' && p === '/market/snapshot') return { json: marketSnapshot() };
  if (method === 'GET' && p === '/pulse') return { json: { ok: true, indices: {}, marketSnapshot: marketSnapshot() } };
  if (method === 'GET' && p === '/sectors') return { json: sectors(url.searchParams.get('mkt') === 'US' ? 'US' : 'TW') };
  if (method === 'GET' && p === '/health') return { json: { ok: true, version: 'ui-baseline-fixture' } };
  return null;
}

module.exports = { respond, FIXED_AS_OF, FIXED_EPOCH_MS, SOURCE };

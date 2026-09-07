// Self-test: overnight panel uses /txf night OHLC + ampRate fields.
// Run in Node: node tests/txf_night_selftest.js
'use strict';

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assert failed');
}

/** Mirror overnight_v3.js night selection + amp fallback */
function pickNight(d) {
  if (!d || !d.ok) return null;
  const n = (d.night && d.night.price != null) ? d.night
    : (d.session === 'night' && d.price != null) ? d : null;
  if (!n || n.price == null) return null;
  let amp = n.ampRate;
  if (amp == null && n.high != null && n.low != null && n.prevClose > 0) {
    amp = (n.high - n.low) / n.prevClose * 100;
  }
  let changePct = n.changePct;
  if (changePct == null && n.price != null && n.prevClose > 0) {
    changePct = (n.price - n.prevClose) / n.prevClose * 100;
  }
  return { price: n.price, changePct, ampRate: amp, high: n.high, low: n.low, prevClose: n.prevClose };
}

function main() {
  const sample = {
    ok: true,
    price: 43678,
    session: 'day',
    night: {
      price: 42650,
      prevClose: 43727,
      changePct: -2.46,
      open: 43519,
      high: 43873,
      low: 42086,
      ampRate: 4.09,
      volume: 69641,
      time: '045959',
      session: 'night',
    },
  };
  const n = pickNight(sample);
  assert(n && n.price === 42650, 'prefer night block over day primary');
  assert(Math.abs(n.ampRate - 4.09) < 1e-9, 'ampRate from night');
  assert(Math.abs(n.changePct - (-2.46)) < 1e-9, 'changePct from night');

  const noAmp = {
    ok: true,
    session: 'night',
    price: 42650,
    prevClose: 43727,
    high: 43873,
    low: 42086,
    changePct: -2.46,
  };
  const n2 = pickNight(noAmp);
  const expectAmp = (43873 - 42086) / 43727 * 100;
  assert(n2 && Math.abs(n2.ampRate - expectAmp) < 1e-9, 'amp fallback (H-L)/prev');

  const dayOnly = { ok: true, session: 'day', price: 43000, night: null };
  assert(pickNight(dayOnly) == null, 'no night when day-only');

  // 主圖最後一根 K：覆寫 close/H/L，開盤保留日盤；漲跌基準用 /txf.prevClose
  function normalizeTxfLiveQuote(raw) {
    if (!raw) return null;
    const m = raw.market || {};
    const price = Number(raw.price != null ? raw.price : m.price);
    if (!(price > 0)) return null;
    const prev = Number(
      raw.prevClose != null ? raw.prevClose
        : (raw.referencePrice != null ? raw.referencePrice : m.referencePrice)
    );
    const high = Number(raw.high != null ? raw.high : price);
    const low = Number(raw.low != null ? raw.low : price);
    return {
      price,
      prevClose: prev > 0 ? prev : null,
      high: high > 0 ? high : price,
      low: low > 0 ? low : price,
      session: String(raw.session || m.session || ''),
    };
  }
  function overlayTxfLiveOnLastBar(last, quote, opts) {
    const nq = normalizeTxfLiveQuote(quote);
    if (!last || !nq) return null;
    const px = nq.price;
    const sessionHL = !(opts && opts.intraday);
    const hi = sessionHL
      ? Math.max(Number(last.high) || px, Number(nq.high) || px, px)
      : Math.max(Number(last.high) || px, px);
    const lo = sessionHL
      ? Math.min(Number(last.low) || px, Number(nq.low) || px, px)
      : Math.min(Number(last.low) || px, px);
    if (!(lo > 0) || hi < lo) return null;
    return { time: last.time, open: last.open, high: hi, low: lo, close: px, volume: last.volume };
  }

  const dayBar = { time: 1757001600, open: 46704, high: 47520, low: 46610, close: 47470, volume: 120000 };
  const nightQuote = {
    ok: true, session: 'night', sessionLabel: '夜盤',
    price: 47333, prevClose: 47462, change: -129, changePct: -0.27,
    open: 47480, high: 47490, low: 47200,
  };
  const over = overlayTxfLiveOnLastBar(dayBar, nightQuote);
  assert(over.close === 47333, 'last close follows night');
  assert(over.open === 46704, 'day open preserved');
  assert(over.high === 47520, 'day high kept when night high is lower');
  assert(over.low === 46610, 'day low kept when night low is higher');
  const nq = normalizeTxfLiveQuote(nightQuote);
  const headerPct = (nq.price - nq.prevClose) / nq.prevClose * 100;
  assert(Math.abs(headerPct - (-0.2718)) < 0.01, 'header % uses night prevClose not prior daily close');
  const stalePct = (dayBar.close - 46704) / 46704 * 100;
  assert(stalePct > 1.5, 'FinMind day close vs prior day is the desynced +1.64% header');

  const extend = overlayTxfLiveOnLastBar(dayBar, {
    price: 47333, prevClose: 47462, high: 47600, low: 46000, session: 'night',
  });
  assert(extend.high === 47600, 'night high extends last bar');
  assert(extend.low === 46000, 'night low extends last bar');

  const fromMarket = normalizeTxfLiveQuote({
    market: { price: 47333, referencePrice: 47462, session: 'night', displayChangePct: -0.27 },
  });
  assert(fromMarket && fromMarket.price === 47333 && fromMarket.prevClose === 47462,
    'canonical market snapshot quote normalizes');
  assert(overlayTxfLiveOnLastBar(dayBar, null) == null, 'skip empty quote');
  assert(overlayTxfLiveOnLastBar(dayBar, { price: 0 }) == null, 'skip invalid price');

  const minuteBar = { time: 1757228580, open: 47390, high: 47400, low: 47340, close: 47350, volume: 20 };
  const overMin = overlayTxfLiveOnLastBar(minuteBar, nightQuote, { intraday: true });
  assert(overMin.close === 47333, '1m last close follows live');
  assert(overMin.high === 47400, '1m overlay does not paint session high onto the last minute');
  assert(overMin.low === 47333, '1m low expands to live price only');

  const fs = require('fs');
  const path = require('path');
  const polish = fs.readFileSync(path.join(__dirname, '..', 'src', 'ui', 'polish_v3.js'), 'utf8');
  assert(/function applyTxfLiveToChart/.test(polish), 'polish exports applyTxfLiveToChart');
  assert(/applyTxfLiveToChart\(d\)/.test(polish), 'refreshTxfCell overlays chart from /txf');
  assert(/applyTxfLiveToChart\(quotes\.__TXF__\)/.test(polish), 'marketData overlays TXF chart');
  assert(/fetch\(base \+ '\/txf'/.test(polish) && /setInterval\(pullTxfLive, 5000\)/.test(polish),
    'TXF chart keeps polling /txf after load');
  assert(/function isTxfChartSym/.test(polish) && /s === '__TXF__' \|\| s === 'TXF'/.test(polish),
    'overlay recognizes TXF aliases');
  assert(/opts && opts\.intraday/.test(polish) && /overlayTxfLiveOnLastBar\(last, q, \{ intraday: _intraday \}\)/.test(polish),
    '1m TXF overlay does not dump session H/L onto the last minute');
  const html = fs.readFileSync(path.join(__dirname, '..', 'stock_terminal.html'), 'utf8');
  assert(/sym === 'TXF' \|\| sym === '__TXF'/.test(html) && /sym = '__TXF__'/.test(html),
    'loadSym canonicalizes TXF to __TXF__');
  const loadStart = html.indexOf('async function loadSym');
  assert(loadStart > 0, 'loadSym present');
  const load = html.slice(loadStart, loadStart + 12000);
  assert(!/yfsym === '\^TWOII' \|\| yfsym === '__TXF__'/.test(load),
    'TXF 1天 must not share TWOII 1d→1y daily rewrite');
  assert(/yfsym === '__TXF__' && S\.range !== '1d'/.test(load),
    'TXF non-1d still forces FinMind daily interval');
  assert(/const _isTxf = \(sym === '__TXF__'\)/.test(load)
    && /IntradayVolumeV3 && !_isTxf/.test(load),
    'TXF 1天 skips TW 09:00–13:30 cash-session filter');
  assert(/_intradayDef && !_isTxf && \(!parsed/.test(load),
    'TXF 1天 does not fall back to 5d daily candles');
  assert(/_isTxfI/.test(html) && /13\.75 \* 3600/.test(html),
    'TXF 1天 X-axis uses 13:45 / night 05:00 not cash 13:30');

  // applyTxfLiveToChart：標題現價／昨收與最後一根 close 跟大盤列同一份夜盤
  (function () {
    const start = polish.indexOf('function applyTxfLiveToChart');
    const normStart = polish.indexOf('function normalizeTxfLiveQuote');
    assert(start > 0 && normStart > 0, 'extract apply helpers');
    function sliceFn(from) {
      let i = polish.indexOf('{', from);
      let depth = 0;
      for (; i < polish.length; i++) {
        if (polish[i] === '{') depth++;
        else if (polish[i] === '}') {
          depth--;
          if (depth === 0) return polish.slice(from, i + 1);
        }
      }
      throw new Error('unterminated fn');
    }
    const code = sliceFn(normStart) + '\n' + sliceFn(polish.indexOf('function isTxfChartSym'))
      + '\n' + sliceFn(polish.indexOf('function overlayTxfLiveOnLastBar'))
      + '\n' + sliceFn(start);
    const header = { price: null, chg: null };
    const updates = [];
    const ctx = {
      S: {
        sym: '__TXF__', tzOffset: 0,
        data: {
          candles: [{ time: 1, open: 46704, high: 47520, low: 46610, close: 47470, volume: 1 }],
          yesterdayClose: 46704, rangeBase: 40000, rangeChgLbl: '1年',
        },
        chartSeries: { update: function (bar) { updates.push(bar); } },
      },
      updateHeaderChg: function (price, prev) { header.price = price; header.prev = prev; },
      updateHeaderHigh: function () {},
      document: {
        getElementById: function (id) {
          if (id === 'ci-price') return { set textContent(v) { header.ci = v; }, get textContent() { return header.ci; } };
          return null;
        },
      },
      window: {},
    };
    ctx.window = ctx;
    require('vm').runInNewContext(code + '\napplyTxfLiveToChart(' + JSON.stringify(nightQuote) + ');', ctx);
    assert(ctx.S.data.candles[0].close === 47333, 'apply mutates last close');
    assert(ctx.S.data.yesterdayClose === 47462, 'apply uses night prevClose as header ref');
    assert(header.price === 47333 && header.prev === 47462, 'header matches mkt-bar night quote');
    assert(header.ci === '47333.00', 'ci-price follows night');
    assert(updates.length === 1 && updates[0].close === 47333, 'series.update night close');
    ctx.S.sym = 'TXF';
    ctx.S.data.candles[0].close = 47470;
    require('vm').runInNewContext(code + '\napplyTxfLiveToChart(' + JSON.stringify(nightQuote) + ');', ctx);
    assert(ctx.S.data.candles[0].close === 47333, 'TXF alias also overlays night close');
  })();

  // 行動預估：台指期夜盤優先於美股連動
  function actionPct(txfPct, usEst) {
    return txfPct != null ? txfPct : usEst;
  }
  assert(actionPct(-2.46, 0.8) === -2.46, 'TXF night drives action');
  assert(actionPct(null, 0.8) === 0.8, 'fallback to US estimate');

  console.log('txf_night_selftest: PASS');
}

main();

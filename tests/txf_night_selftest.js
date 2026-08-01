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

  // 行動預估：台指期夜盤優先於美股連動
  function actionPct(txfPct, usEst) {
    return txfPct != null ? txfPct : usEst;
  }
  assert(actionPct(-2.46, 0.8) === -2.46, 'TXF night drives action');
  assert(actionPct(null, 0.8) === 0.8, 'fallback to US estimate');

  console.log('txf_night_selftest: PASS');
}

main();

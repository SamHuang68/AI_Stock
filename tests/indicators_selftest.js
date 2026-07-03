// ============================================================
// 統一指標庫 JS/Python 對齊 selftest
// ------------------------------------------------------------
// 跑法：node tests/indicators_selftest.js
// 與 `python server/indicators.py` 用「同一組 fixture 產生器、同一組
// 期望值常數」。fixture 用 Lehmer LCG（純整數運算),JS/Python 逐位元
// 一致,容差 1e-9。任何一邊演算法分岔 → 立刻紅燈。
// 期望值來源：server/indicators.py 的 EXPECTED（凍結後兩邊共用）。
// ============================================================
'use strict';
const path = require('path');
const Indicators = require(path.join(__dirname, '..', 'src', 'core', 'indicators_v3.js'));

const FIXTURE_N = 120;
function makeFixture(n) {
  n = n || FIXTURE_N;
  let x = 123456789;
  const rnd = () => { x = (x * 48271) % 2147483647; return x / 2147483647; };
  const close = [], high = [], low = [];
  let c = 100.0;
  for (let i = 0; i < n; i++) {
    c = c * (1 + (rnd() - 0.5) * 0.04);
    const h = c * (1 + rnd() * 0.015);
    const l = c * (1 - rnd() * 0.015);
    close.push(c); high.push(h); low.push(l);
  }
  return { high, low, close };
}

// 與 server/indicators.py EXPECTED 完全相同的常數（凍結,不得單邊修改）
const EXPECTED = {
  sma20_last:     95.3597471947273,
  ema20_last:     96.27041510701059,
  rsi14_last:     47.92438952946284,
  rsi14_at_20:    50.26179434600121,
  kd_k_last:      58.860988441280284,
  kd_d_last:      52.786881663166646,
  macd_last:      -1.1387485913740676,
  macd_sig_last:  -1.5599486772664723,
  macd_hist_last: 0.42120008589240476,
  bb_up_last:     97.49211772848977,
  bb_lo_last:     93.22737666096484,
  atr14_last:     1.889553061138027,
};
const TOL = 1e-9;

const { high: h, low: l, close: c } = makeFixture();
const last = a => a[a.length - 1];
const got = {
  sma20_last: last(Indicators.sma(c, 20)),
  ema20_last: last(Indicators.ema(c, 20)),
  rsi14_last: last(Indicators.rsi(c, 14)),
  rsi14_at_20: Indicators.rsi(c, 14)[20],
  kd_k_last: last(Indicators.kd(h, l, c).k),
  kd_d_last: last(Indicators.kd(h, l, c).d),
  macd_last: last(Indicators.macd(c).macd),
  macd_sig_last: last(Indicators.macd(c).signal),
  macd_hist_last: last(Indicators.macd(c).hist),
  bb_up_last: last(Indicators.bb(c).upper),
  bb_lo_last: last(Indicators.bb(c).lower),
  atr14_last: last(Indicators.atr(h, l, c)),
};

let passed = 0, total = 0;
function ck(name, ok, gotV, expV) {
  total++;
  if (ok) { passed++; console.log(`  PASS  ${name}`); }
  else console.error(`  FAIL  ${name}  got=${gotV}  exp=${expV}`);
}
for (const [k, exp] of Object.entries(EXPECTED)) {
  const v = got[k];
  ck('ind:' + k, v != null && Math.abs(v - exp) < TOL, v, exp);
}
// 暖身期 null 邊界
ck('ind:rsi_warmup_null', Indicators.rsi(c, 14)[13] === null, Indicators.rsi(c, 14)[13], null);
ck('ind:sma_warmup_null', Indicators.sma(c, 20)[18] === null, Indicators.sma(c, 20)[18], null);
ck('ind:atr_warmup_null', Indicators.atr(h, l, c)[13] === null, Indicators.atr(h, l, c)[13], null);
// worker 序列化路徑：INDICATORS_LIB_SRC eval 後結果須與直接引用一致
const evaled = eval(require('fs').readFileSync(path.join(__dirname, '..', 'src', 'core', 'indicators_v3.js'), 'utf8') + ';INDICATORS_LIB_SRC') // eslint-disable-line no-eval
ck('ind:lib_src_serializable', typeof evaled === 'string' && Math.abs(eval(evaled).rsi(c, 14)[c.length - 1] - EXPECTED.rsi14_last) < TOL, 'evaled', 'match');

console.log(`\n[indicators] ${passed}/${total} ${passed === total ? 'ALL PASS' : 'FAILED'}`);
process.exit(passed === total ? 0 : 1);

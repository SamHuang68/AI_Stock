// ============================================================
// 統一回測引擎 selftest — 驗證 v4.1 精準化行為
// ------------------------------------------------------------
// 跑法：node tests/backtest_selftest.js
// 驗證：
//   1. 進場 = 訊號「次一根開盤」（無前視偏差）
//   2. 台股費稅:淨報酬 = 毛報酬扣 手續費0.1425%×2 + 證交稅0.3%(賣出)
//   3. cost:false → 淨 = 毛
//   4. runLS 出場訊號成交於次根開盤
//   5. 訊號在最後一根（無次根可進場）→ 不產生交易
// ============================================================
'use strict';
const path = require('path');
const fs = require('fs');

// 建立瀏覽器環境替身,載入統一指標庫與回測引擎(IIFE 掛 window)
global.window = globalThis;
global.S = { mkt: 'TW' };
require(path.join(__dirname, '..', 'src', 'core', 'indicators_v3.js'));
eval(fs.readFileSync(path.join(__dirname, '..', 'src', 'screener', 'backtest_v3.js'), 'utf8')); // eslint-disable-line no-eval
const Backtest = window.Backtest;

let passed = 0, total = 0;
function ck(name, ok, detail) {
  total++;
  if (ok) { passed++; console.log(`  PASS  ${name}`); }
  else console.error(`  FAIL  ${name}  ${detail || ''}`);
}
const near = (a, b, tol) => Math.abs(a - b) < (tol || 1e-12);

// 固定 K 線:open=close 前根 +1 的簡單走勢,方便手算
// bar:      0    1    2    3    4    5    6
const candles = [
  { time: 100, open: 100, high: 101, low: 99, close: 100, volume: 1000 },
  { time: 200, open: 101, high: 103, low: 100, close: 102, volume: 1000 },
  { time: 300, open: 103, high: 105, low: 102, close: 104, volume: 1000 },
  { time: 400, open: 105, high: 107, low: 104, close: 106, volume: 1000 },
  { time: 500, open: 107, high: 109, low: 106, close: 108, volume: 1000 },
  { time: 600, open: 109, high: 111, low: 108, close: 110, volume: 1000 },
  { time: 700, open: 111, high: 113, low: 110, close: 112, volume: 1000 },
];

// ── 1+2. run():訊號於 bar1 → 進場 bar2 開盤 103;maxBars=2 → 出場 bar4 收盤 108
const sig = [false, true, false, false, false, false, false];
const r1 = Backtest.run(candles, sig, { tp: 9.99, sl: 9.99, maxBars: 2, market: 'TW' });
ck('run:單筆交易', r1.count === 1, `count=${r1.count}`);
const t1 = r1.trades[0];
ck('run:次根開盤進場(103)', t1.entry === 103 && t1.entryBar === 2, `entry=${t1.entry} bar=${t1.entryBar}`);
ck('run:時間出場於 bar4 收盤(108)', t1.exit === 108 && t1.exitBar === 4 && t1.reason === 'time', `exit=${t1.exit} bar=${t1.exitBar} reason=${t1.reason}`);
const gross = (108 - 103) / 103;
ck('run:毛報酬正確', near(t1.retGross, gross), `got=${t1.retGross} exp=${gross}`);
const fee = 0.001425, tax = 0.003;
const net = (108 * (1 - fee - tax)) / (103 * (1 + fee)) - 1;
ck('run:台股淨報酬=已扣0.1425%×2+0.3%', near(t1.ret, net), `got=${t1.ret} exp=${net}`);
ck('run:淨<毛', t1.ret < t1.retGross, '');
ck('run:summary 帶 cost', r1.cost && near(r1.cost.fee, fee) && near(r1.cost.tax, tax), JSON.stringify(r1.cost));
ck('run:totalReturnGross 一致', near(r1.totalReturnGross, gross * 100), `got=${r1.totalReturnGross}`);

// ── 3. cost:false → 淨=毛
const r2 = Backtest.run(candles, sig, { tp: 9.99, sl: 9.99, maxBars: 2, cost: false });
ck('run:cost=false 淨=毛', near(r2.trades[0].ret, r2.trades[0].retGross), '');

// ── 4. runLS:買訊 bar1 → 進 bar2 開盤;賣訊 bar4 → 出 bar5 開盤 109
const buy = [false, true, false, false, false, false, false];
const sell = [false, false, false, false, true, false, false];
const r3 = Backtest.runLS(candles, buy, sell, { market: 'TW' });
const t3 = r3.trades[0];
ck('runLS:賣訊次根開盤出場(109)', t3.exit === 109 && t3.exitBar === 5 && t3.reason === 'signal', `exit=${t3.exit} bar=${t3.exitBar} reason=${t3.reason}`);
ck('runLS:進場=次根開盤(103)', t3.entry === 103 && t3.entryBar === 2, `entry=${t3.entry}`);

// ── 5. 訊號在最後一根 → 無交易
const sigLast = [false, false, false, false, false, false, true];
const r4 = Backtest.run(candles, sigLast, {});
ck('run:末根訊號不進場', r4.count === 0, `count=${r4.count}`);

// ── 6. 美股市場預設零費稅
const r5 = Backtest.run(candles, sig, { tp: 9.99, sl: 9.99, maxBars: 2, market: 'US' });
ck('run:US 淨=毛(預設零費稅)', near(r5.trades[0].ret, r5.trades[0].retGross), '');

console.log(`\n[backtest] ${passed}/${total} ${passed === total ? 'ALL PASS' : 'FAILED'}`);
process.exit(passed === total ? 0 : 1);

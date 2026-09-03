// ============================================================
// Stock Terminal v3.9 Phase-2 — parseYF 異常清洗 前端單元測試
// ------------------------------------------------------------
// 用法:直接執行 `node tests/parse_selftest.js`,或在瀏覽器 Console 執行。
// Node 模式會從生成的 stock_terminal.html 載入真正的 parseYF。
// 測「日線異常驗證(孤立尖刺剔除、持續跳空/漲跌停保留)」不會回歸壞掉。
// (Python 端核心函式測試見 server.py /selftest 端點)
// ============================================================
(function () {
  'use strict';
  var host = typeof window !== 'undefined' ? window : globalThis;
  if (typeof host.parseYF !== 'function' && typeof require === 'function') {
    var fs = require('fs');
    var path = require('path');
    var html = fs.readFileSync(path.join(__dirname, '..', 'stock_terminal.html'), 'utf8');
    var start = html.indexOf('function parseYF(raw) {');
    var tail = start >= 0 ? html.slice(start) : '';
    var boundary = tail.match(/\r?\n\}\r?\n\r?\n\/\/ ── LOAD SYMBOL/);
    if (start >= 0 && boundary && boundary.index > 0) {
      var closeAt = boundary.index + boundary[0].indexOf('}') + 1;
      var source = tail.slice(0, closeAt);
      host.parseYF = Function(source + '\nreturn parseYF;')();
    }
  }
  if (typeof host.parseYF !== 'function') {
    throw new Error('[parse-selftest] 找不到生成檔中的 parseYF');
  }
  function mk(closes) {
    var n = closes.length, ts = [], q = { open: [], high: [], low: [], close: [], volume: [] };
    for (var i = 0; i < n; i++) {
      ts.push(1700000000 + i * 86400);
      q.open.push(closes[i]); q.high.push(closes[i]); q.low.push(closes[i]);
      q.close.push(closes[i]); q.volume.push(1000);
    }
    return { chart: { result: [{ timestamp: ts, indicators: { quote: [q] }, meta: { symbol: 'TEST' } }] } };
  }
  function closesOf(arr) { var p = host.parseYF(mk(arr)); return p ? p.candles.map(function (c) { return c.close; }) : null; }

  var cases = [];
  function ck(name, got, exp) {
    cases.push({ name: name, pass: JSON.stringify(got) === JSON.stringify(exp), got: got, exp: exp });
  }

  ck('正常序列全保留', closesOf([100, 101, 102]), [100, 101, 102]);
  ck('孤立尖刺剔除', closesOf([100, 200, 101]), [100, 101]);
  ck('孤立深跌剔除', closesOf([100, 50, 101]), [100, 101]);
  ck('持續性分割/跳空保留', closesOf([100, 50, 51]), [100, 50, 51]);
  ck('漲停日保留(+10%續漲)', closesOf([100, 110, 121]), [100, 110, 121]);
  ck('首尾不誤刪', closesOf([100, 101, 102, 103]), [100, 101, 102, 103]);
  ck('連續兩根尖刺保守保留', closesOf([100, 200, 201, 102]).length, 4);
  ck('開最高低為0時fallback至收盤價', (function() {
    var raw = {
      chart: {
        result: [{
          timestamp: [1700000000],
          indicators: {
            quote: [{ open: [0], high: [0], low: [0], close: [39.49], volume: [1000] }]
          },
          meta: { symbol: 'TEST_ZERO' }
        }]
      }
    };
    var p = host.parseYF(raw);
    return p && p.candles[0] && p.candles[0].open === 39.49 && p.candles[0].high === 39.49 && p.candles[0].low === 39.49;
  })(), true);

  var passed = cases.filter(function (c) { return c.pass; }).length;
  console.table(cases);
  console.log('[parse-selftest] ' + passed + '/' + cases.length + (passed === cases.length ? ' ✅ 全過' : ' ❌ 有失敗'));
  if (passed !== cases.length && typeof process !== 'undefined') process.exitCode = 1;
  return { passed: passed, total: cases.length, cases: cases };
})();

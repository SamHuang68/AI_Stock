// ============================================================
// Stock Terminal v3.9 Phase-2 — parseYF 異常清洗 前端單元測試
// ------------------------------------------------------------
// 用法:開啟 stock_terminal_v2.html 後,把本檔內容貼到瀏覽器 Console 執行,
//   或在 DevTools Snippets 存成片段。會對「真正的 window.parseYF」跑斷言。
// 測「日線異常驗證(孤立尖刺剔除、持續跳空/漲跌停保留)」不會回歸壞掉。
// (Python 端核心函式測試見 server.py /selftest 端點)
// ============================================================
(function () {
  'use strict';
  if (typeof window.parseYF !== 'function') {
    console.error('[parse-selftest] 找不到 window.parseYF — 請在 stock_terminal 頁面執行');
    return;
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
  function closesOf(arr) { var p = window.parseYF(mk(arr)); return p ? p.candles.map(function (c) { return c.close; }) : null; }

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

  var passed = cases.filter(function (c) { return c.pass; }).length;
  console.table(cases);
  console.log('[parse-selftest] ' + passed + '/' + cases.length + (passed === cases.length ? ' ✅ 全過' : ' ❌ 有失敗'));
  return { passed: passed, total: cases.length, cases: cases };
})();

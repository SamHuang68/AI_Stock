// ============================================================
// Stock Terminal v4.1 — 統一技術指標庫（單一真理來源 SSOT）
// ------------------------------------------------------------
// 鐵律：全 app 只有這一份指標數學。引用者：
//   • stock_terminal.html 指標列 Web Worker（經 INDICATORS_LIB_SRC 串進 blob）
//   • StratLib（策略組合器 / 腳本 DSL）
//   • window.Backtest（統一回測引擎）
//   • pro_v2 mockInd、wizard ATR
// Python 端對齊實作：server/indicators.py（演算法與慣例完全相同）。
// 對齊驗證：tests/indicators_selftest.js（node）與
//   `python server/indicators.py`（或 /selftest）跑「同一組 fixture、
//   同一組期望值」，任何一邊分岔立刻紅燈。
//
// 演算法慣例（與 TradingView / TA-Lib 對齊）：
//   • 序列進、序列出；暖身期（資料不足）一律 null。
//   • SMA(p)：i ≥ p-1 起有效。
//   • EMA(p)：以「前 p 根 SMA」為種子（TA-Lib 慣例），k=2/(p+1)，i ≥ p-1 起有效。
//   • RSI(p)：Wilder 平滑。首值 = 前 p 根漲跌簡單平均（於 i=p），之後遞迴
//       avg = (prev*(p-1)+cur)/p。RSI = 100*avgG/(avgG+avgL)；漲跌皆 0 → 50。
//   • KD(n,sm)：台股慣例 9,3,3。RSV=(C-LLV)/(HHV-LLV)*100（區間死平 → 50），
//       K = K'*(2/3) + RSV*(1/3)，D = D'*(2/3) + K*(1/3)，K/D 種子 50。
//   • MACD(f,s,sig)：line = EMA(f)-EMA(s)（兩者皆有效才有值）；
//       signal = 只對「有效的 line 段」做 EMA(sig)（不以 0 充填暖身期）。
//   • BB(p,k)：mid = SMA(p)，母體標準差（除以 N），上下軌 = mid ± k*std。
//   • ATR(p)：Wilder。TR 需前一收盤（自 i=1 起），首值 = 前 p 個 TR 簡單平均
//       （於 i=p），之後 atr = (prev*(p-1)+TR)/p。
//
// window.INDICATORS_LIB_SRC：本庫工廠函式的原始碼字串，Web Worker blob 直接
// 串接使用 → worker 與主執行緒共用同一份程式碼，永不分岔。
// ============================================================
(function (root) {
  'use strict';

  function __INDICATORS_FACTORY__() {
    'use strict';

    // ── SMA：滾動和（O(n)），i ≥ p-1 起有效 ──
    function sma(arr, p) {
      var n = arr.length, out = new Array(n).fill(null);
      if (!(p >= 1)) return out;
      var s = 0;
      for (var i = 0; i < n; i++) {
        s += arr[i];
        if (i >= p) s -= arr[i - p];
        if (i >= p - 1) out[i] = s / p;
      }
      return out;
    }

    // ── EMA：SMA 種子（TA-Lib 慣例），k=2/(p+1) ──
    function ema(arr, p) {
      var n = arr.length, out = new Array(n).fill(null);
      if (!(p >= 1) || n < p) return out;
      var s = 0, i;
      for (i = 0; i < p; i++) s += arr[i];
      var prev = s / p;
      out[p - 1] = prev;
      var k = 2 / (p + 1);
      for (i = p; i < n; i++) {
        prev = arr[i] * k + prev * (1 - k);
        out[i] = prev;
      }
      return out;
    }

    // ── RSI：Wilder 平滑（業界標準；非簡單平均）──
    function rsi(close, p) {
      p = p || 14;
      var n = close.length, out = new Array(n).fill(null);
      if (n <= p) return out;
      var g = 0, l = 0, i, d;
      for (i = 1; i <= p; i++) {
        d = close[i] - close[i - 1];
        if (d >= 0) g += d; else l -= d;
      }
      g /= p; l /= p;
      out[p] = (g + l === 0) ? 50 : 100 * g / (g + l);
      for (i = p + 1; i < n; i++) {
        d = close[i] - close[i - 1];
        g = (g * (p - 1) + (d > 0 ? d : 0)) / p;
        l = (l * (p - 1) + (d < 0 ? -d : 0)) / p;
        out[i] = (g + l === 0) ? 50 : 100 * g / (g + l);
      }
      return out;
    }

    // ── KD：台股慣例 9,3,3；K/D 自序列起點逐根迭代（種子 50）──
    function kd(high, low, close, n, sm) {
      n = n || 9; sm = sm || 3;
      var len = close.length;
      var k = new Array(len).fill(null), d = new Array(len).fill(null);
      var pk = 50, pd = 50;
      for (var i = 0; i < len; i++) {
        if (i < n - 1) continue;
        var hh = -Infinity, ll = Infinity;
        for (var j = i - n + 1; j <= i; j++) {
          if (high[j] > hh) hh = high[j];
          if (low[j] < ll) ll = low[j];
        }
        var rsv = (hh === ll) ? 50 : (close[i] - ll) / (hh - ll) * 100;
        pk = pk * (sm - 1) / sm + rsv / sm;
        pd = pd * (sm - 1) / sm + pk / sm;
        k[i] = pk; d[i] = pd;
      }
      return { k: k, d: d };
    }

    // ── MACD：signal 只對有效 line 段做 EMA（不以 0 充填暖身期）──
    function macd(close, f, s, sig) {
      f = f || 12; s = s || 26; sig = sig || 9;
      var n = close.length;
      var ef = ema(close, f), es = ema(close, s);
      var line = new Array(n).fill(null);
      var signal = new Array(n).fill(null);
      var hist = new Array(n).fill(null);
      var i;
      for (i = 0; i < n; i++) {
        if (ef[i] != null && es[i] != null) line[i] = ef[i] - es[i];
      }
      var start = -1;
      for (i = 0; i < n; i++) { if (line[i] != null) { start = i; break; } }
      if (start >= 0 && n - start >= sig) {
        var sum = 0;
        for (i = start; i < start + sig; i++) sum += line[i];
        var prev = sum / sig;
        signal[start + sig - 1] = prev;
        var kk = 2 / (sig + 1);
        for (i = start + sig; i < n; i++) {
          prev = line[i] * kk + prev * (1 - kk);
          signal[i] = prev;
        }
      }
      for (i = 0; i < n; i++) {
        if (line[i] != null && signal[i] != null) hist[i] = line[i] - signal[i];
      }
      return { macd: line, signal: signal, hist: hist };
    }

    // ── Bollinger：mid=SMA(p)、母體標準差（÷N，同 TradingView）──
    function bb(close, p, k) {
      p = p || 20; k = (k == null) ? 2 : k;
      var n = close.length;
      var mid = sma(close, p);
      var upper = new Array(n).fill(null), lower = new Array(n).fill(null);
      for (var i = p - 1; i < n; i++) {
        var m = mid[i], v = 0;
        for (var j = i - p + 1; j <= i; j++) { var dd = close[j] - m; v += dd * dd; }
        var sd = Math.sqrt(v / p);
        upper[i] = m + k * sd;
        lower[i] = m - k * sd;
      }
      return { mid: mid, upper: upper, lower: lower };
    }

    // ── ATR：Wilder 平滑（非 TR 簡單平均）──
    function atr(high, low, close, p) {
      p = p || 14;
      var n = close.length, out = new Array(n).fill(null);
      if (n <= p) return out;
      var trSum = 0, i, tr;
      for (i = 1; i <= p; i++) {
        tr = Math.max(high[i] - low[i], Math.abs(high[i] - close[i - 1]), Math.abs(low[i] - close[i - 1]));
        trSum += tr;
      }
      var prev = trSum / p;
      out[p] = prev;
      for (i = p + 1; i < n; i++) {
        tr = Math.max(high[i] - low[i], Math.abs(high[i] - close[i - 1]), Math.abs(low[i] - close[i - 1]));
        prev = (prev * (p - 1) + tr) / p;
        out[i] = prev;
      }
      return out;
    }

    // ── 便利函式：取序列最後一個有效值 ──
    function last(arr) {
      if (!arr || !arr.length) return null;
      var v = arr[arr.length - 1];
      return (v == null || v !== v) ? null : v;
    }

    return {
      sma: sma, ema: ema, rsi: rsi, kd: kd, macd: macd, bb: bb, atr: atr,
      last: last,
      VERSION: '1.0.0',
    };
  }

  var api = __INDICATORS_FACTORY__();
  root.Indicators = api;
  // Web Worker 無法存取主執行緒的 window → 把工廠原始碼序列化,
  // 由 runWorker 串進 blob,保證 worker 用的就是同一份程式碼。
  root.INDICATORS_LIB_SRC = '(' + __INDICATORS_FACTORY__.toString() + ')()';
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : (typeof self !== 'undefined' ? self : globalThis));

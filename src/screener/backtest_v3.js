// ============================================================
// Stock Terminal v4.1 — 統一回測引擎 (Unified Backtest Core)
// ------------------------------------------------------------
// 一個核心，三種用法：
//   1. 策略回測：WATCH 8 策略任一 → 勝率 / 賠率 / 期望值 / 權益曲線
//   2. 型態命中率：pattern_v3 19 型態 → 偵測後 N 日報酬分布
//   3. 投組回測：多檔 + 資金配置 → 投組權益曲線
// 指標一律委派統一指標庫（src/core/indicators_v3.js,SSOT）。
// v4.1 精準化：
//   • 進場 = 訊號「次一根開盤」→ 消除同根收盤進場的前視偏差
//   • 報酬 = 已扣台股費稅/滑價的淨報酬（毛報酬另存 retGross / totalReturnGross）
//     台股:手續費 0.1425%(買賣各一,可設折扣) + 證交稅 0.3%(賣出);美股預設 0
//   • TP/SL 以收盤價判斷（EOD 慣例,不模擬盤中觸價);出場訊號成交於次根開盤
// 公開 API：window.Backtest
// ============================================================
(function () {
  'use strict';

  // ---- 指標:一律走統一指標庫（不再自帶實作,永不分岔）----
  const IND = window.Indicators;
  function sma(arr, p) { return IND.sma(arr, p); }
  function rsi(closes, p) { return IND.rsi(closes, p || 14); }
  function bbLower(closes, p, k) { return IND.bb(closes, p || 20, k || 2).lower; }

  // ---- 台股費稅模型 (v4.1) ----------------------------------
  // opts.market:'TW'|'US'（未給則讀全域 S.mkt,再預設 TW）
  // opts.cost:false=不計成本;或 {fee,feeDiscount,tax,slippage} 覆寫預設
  const TW_COST = { fee: 0.001425, feeDiscount: 1.0, tax: 0.003, slippage: 0 };
  const US_COST = { fee: 0,        feeDiscount: 1.0, tax: 0,     slippage: 0 };
  function resolveCost(opts) {
    if (opts.cost === false) return { fee: 0, tax: 0, slip: 0 };
    const mkt = opts.market || ((typeof S !== 'undefined' && S.mkt) ? S.mkt : 'TW');
    const base = (mkt === 'TW') ? TW_COST : US_COST;
    const c = (opts.cost && typeof opts.cost === 'object') ? opts.cost : {};
    const disc = (c.feeDiscount != null) ? c.feeDiscount : base.feeDiscount;
    return {
      fee: ((c.fee != null) ? c.fee : base.fee) * disc,
      tax: (c.tax != null) ? c.tax : base.tax,
      slip: (c.slippage != null) ? c.slippage : base.slippage,
    };
  }
  // 淨報酬:多=買進成本 entry*(1+fee+slip) vs 賣出淨得 exit*(1-fee-tax-slip)
  //        空(融券簡化,不含借券費)=放空淨得 entry*(1-fee-tax-slip) vs 回補成本 exit*(1+fee+slip),報酬以 entry 名目計
  function netReturn(entry, exit, cost, short) {
    if (!short) {
      const buy = entry * (1 + cost.fee + cost.slip);
      const sell = exit * (1 - cost.fee - cost.tax - cost.slip);
      return sell / buy - 1;
    }
    const sellShort = entry * (1 - cost.fee - cost.tax - cost.slip);
    const cover = exit * (1 + cost.fee + cost.slip);
    return (sellShort - cover) / entry;
  }

  // ---- 策略庫：回傳 entry signal 陣列 (bool/bar) -----------
  const STRATEGIES = {
    sma20_pullback: { name: '回測 20 日均線', fn: c => crossUp(c.close, sma(c.close, 20)) },
    sma60_pullback: { name: '回測 60 日均線', fn: c => crossUp(c.close, sma(c.close, 60)) },
    breakout20: { name: '突破 20 日新高', fn: c => breakout(c.high, c.close, 20) },
    breakout60: { name: '突破 60 日新高', fn: c => breakout(c.high, c.close, 60) },
    rsi_oversold: { name: 'RSI 超賣反彈', fn: c => { const r = rsi(c.close, 14); return c.close.map((_, i) => i > 0 && r[i - 1] != null && r[i - 1] < 30 && r[i] >= 30); } },
    rsi_overheat: { name: 'RSI 過熱(空)', fn: c => { const r = rsi(c.close, 14); return c.close.map((_, i) => i > 0 && r[i - 1] != null && r[i - 1] > 70 && r[i] <= 70); }, short: true },
    bb_lower: { name: '布林下軌承接', fn: c => { const b = bbLower(c.close, 20, 2); return c.close.map((_, i) => b[i] != null && c.low[i] <= b[i] && c.close[i] > b[i]); } },
    golden_cross: { name: '黃金交叉(20/60)', fn: c => crossUp(sma(c.close, 20), sma(c.close, 60)) },
  };

  function crossUp(a, b) {
    return a.map((_, i) => i > 0 && a[i - 1] != null && b[i - 1] != null && b[i] != null && a[i - 1] <= b[i - 1] && a[i] > b[i]);
  }
  function breakout(high, close, p) {
    const out = new Array(close.length).fill(false);
    for (let i = p; i < close.length; i++) {
      let hh = -Infinity;
      for (let j = i - p; j < i; j++) hh = Math.max(hh, high[j]);
      out[i] = close[i] > hh;
    }
    return out;
  }

  // ---- 核心回測 --------------------------------------------
  // candles: [{time,open,high,low,close,volume}]
  // opts: {tp:0.15, sl:0.08, maxBars:20, short:false, market:'TW'|'US', cost:{...}|false}
  // v4.1:訊號於第 i 根收盤成立 → 於第 i+1 根「開盤」進場（無前視偏差）;
  //      TP/SL 自進場當根收盤起逐根檢查;ret=淨報酬(含費稅),retGross=毛報酬。
  function run(candles, signalArr, opts) {
    opts = Object.assign({ tp: 0.15, sl: 0.08, maxBars: 20, short: false }, opts || {});
    const cost = resolveCost(opts);
    const c = colsOf(candles);
    const trades = [];
    let equity = 1, peak = 1, maxDD = 0;
    const curve = [];
    let i = 0;
    while (i < candles.length) {
      if (signalArr[i] && i + 1 < candles.length) {
        const entryBar = i + 1;
        const entry = c.open[entryBar];
        let exit = c.close[entryBar], exitBar = entryBar, reason = 'time';
        for (let j = entryBar; j < candles.length && j <= entryBar + opts.maxBars; j++) {
          const r = opts.short ? (entry - c.close[j]) / entry : (c.close[j] - entry) / entry;
          exit = c.close[j]; exitBar = j;
          if (r >= opts.tp) { reason = 'tp'; break; }
          if (r <= -opts.sl) { reason = 'sl'; break; }
        }
        const retGross = opts.short ? (entry - exit) / entry : (exit - entry) / entry;
        const ret = netReturn(entry, exit, cost, opts.short);
        trades.push({ signalBar: i, entryBar, exitBar, entry, exit, ret, retGross, reason,
                      time: candles[entryBar].time, exitTime: candles[exitBar].time, holdBars: exitBar - entryBar });
        equity *= (1 + ret);
        peak = Math.max(peak, equity);
        maxDD = Math.max(maxDD, (peak - equity) / peak);
        curve.push({ time: candles[exitBar].time, equity });
        i = exitBar + 1;
      } else i++;
    }
    return summarize(trades, equity, maxDD, curve, cost);
  }

  function summarize(trades, equity, maxDD, curve, cost) {
    const n = trades.length;
    const wins = trades.filter(t => t.ret > 0);
    const losses = trades.filter(t => t.ret <= 0);
    // 毛報酬權益（未含費稅）— 供 UI 對照「含成本 vs 不含成本」
    let equityGross = 1;
    for (const t of trades) equityGross *= (1 + (t.retGross != null ? t.retGross : t.ret));
    const avgWin = wins.length ? wins.reduce((s, t) => s + t.ret, 0) / wins.length : 0;
    const avgLoss = losses.length ? losses.reduce((s, t) => s + t.ret, 0) / losses.length : 0;
    const winRate = n ? wins.length / n * 100 : 0;
    const expectancy = n ? trades.reduce((s, t) => s + t.ret, 0) / n : 0;
    const rets = trades.map(t => t.ret);
    const mean = expectancy;
    const sd = n > 1 ? Math.sqrt(rets.reduce((s, r) => s + (r - mean) ** 2, 0) / (n - 1)) : 0;
    const sharpe = sd ? mean / sd * Math.sqrt(n) : 0;
    const payoff = avgLoss ? Math.abs(avgWin / avgLoss) : (avgWin ? Infinity : 0);
    // v3.9 深化：獲利因子、平均持有、最大連勝/連敗、最佳/最差、年化夏普估計
    const grossWin = wins.reduce((s, t) => s + t.ret, 0);
    const grossLoss = Math.abs(losses.reduce((s, t) => s + t.ret, 0));
    const profitFactor = grossLoss ? grossWin / grossLoss : (grossWin ? Infinity : 0);
    const avgHoldBars = n ? trades.reduce((s, t) => s + (t.holdBars || 0), 0) / n : 0;
    let winStreak = 0, lossStreak = 0, curW = 0, curL = 0;
    for (const t of trades) {
      if (t.ret > 0) { curW++; curL = 0; winStreak = Math.max(winStreak, curW); }
      else { curL++; curW = 0; lossStreak = Math.max(lossStreak, curL); }
    }
    const best = n ? Math.max(...rets) : 0;
    const worst = n ? Math.min(...rets) : 0;
    // 年化夏普估計：以平均持有 bar 數換算每年交易筆數(252 交易日)
    const tradesPerYear = avgHoldBars > 0 ? 252 / avgHoldBars : n;
    const sharpeAnn = sd ? (mean / sd) * Math.sqrt(tradesPerYear) : 0;
    return {
      count: n, winRate, wins: wins.length, losses: losses.length,
      avgWin: avgWin * 100, avgLoss: avgLoss * 100, payoff,
      expectancy: expectancy * 100, totalReturn: (equity - 1) * 100,
      totalReturnGross: (equityGross - 1) * 100,
      cost: cost || null,
      maxDD: maxDD * 100, sharpe, sharpeAnn,
      profitFactor, avgHoldBars,
      maxWinStreak: winStreak, maxLossStreak: lossStreak,
      best: best * 100, worst: worst * 100,
      trades, curve,
    };
  }

  // ---- 進出場雙訊號回測 (給樂高條件器 / 腳本引擎用) -------
  // buyArr[i] 進場、sellArr[j] 出場；tp/sl/maxBars 任一先到也出場。
  // 同一時間只持有一個部位(進場後直到出場才找下一筆)。
  // v4.1:買進訊號於第 i 根收盤成立 → 第 i+1 根開盤進場;
  //      出場訊號成交於次根開盤;TP/SL/時間出場成交於觸發當根收盤;
  //      ret=淨報酬(含費稅),retGross=毛報酬。
  function runLS(candles, buyArr, sellArr, opts) {
    opts = Object.assign({ tp: 0, sl: 0, maxBars: 0, short: false }, opts || {});
    const cost = resolveCost(opts);
    const c = colsOf(candles);
    const trades = [];
    let equity = 1, peak = 1, maxDD = 0;
    const curve = [];
    let i = 0;
    while (i < candles.length) {
      if (buyArr[i] && i + 1 < candles.length) {
        const entryBar = i + 1;
        const entry = c.open[entryBar];
        let exit = c.close[entryBar], exitBar = entryBar, reason = 'end';
        for (let j = entryBar; j < candles.length; j++) {
          const r = opts.short ? (entry - c.close[j]) / entry : (c.close[j] - entry) / entry;
          exit = c.close[j]; exitBar = j;
          if (opts.tp > 0 && r >= opts.tp) { reason = 'tp'; break; }
          if (opts.sl > 0 && r <= -opts.sl) { reason = 'sl'; break; }
          if (opts.maxBars > 0 && (j - entryBar) >= opts.maxBars) { reason = 'time'; break; }
          if (sellArr && sellArr[j]) {
            // 出場訊號於 j 收盤成立 → 次根開盤成交;無次根則以 j 收盤結算
            if (j + 1 < candles.length) { exit = c.open[j + 1]; exitBar = j + 1; }
            reason = 'signal'; break;
          }
        }
        const retGross = opts.short ? (entry - exit) / entry : (exit - entry) / entry;
        const ret = netReturn(entry, exit, cost, opts.short);
        trades.push({ signalBar: i, entryBar, exitBar, entry, exit, ret, retGross, reason,
                      time: candles[entryBar].time, exitTime: candles[exitBar].time, holdBars: exitBar - entryBar });
        equity *= (1 + ret);
        peak = Math.max(peak, equity);
        maxDD = Math.max(maxDD, (peak - equity) / peak);
        curve.push({ time: candles[exitBar].time, equity });
        i = exitBar + 1;
      } else i++;
    }
    return summarize(trades, equity, maxDD, curve, cost);
  }

  function colsOf(candles) {
    return {
      open: candles.map(c => c.open), high: candles.map(c => c.high),
      low: candles.map(c => c.low), close: candles.map(c => c.close),
      volume: candles.map(c => c.volume || 0),
    };
  }

  // ---- 多策略掃描：每策略歷史勝率 -------------------------
  function scanStrategies(candles, opts) {
    const c = wrap(candles);
    const rows = [];
    for (const [key, st] of Object.entries(STRATEGIES)) {
      try {
        const sig = st.fn(c);
        const o = Object.assign({ short: !!st.short }, opts);
        const r = run(candles, sig, o);
        rows.push({ key, name: st.name, ...r });
      } catch (e) { console.warn('[bt]', key, e); }
    }
    return rows.sort((a, b) => b.expectancy - a.expectancy);
  }
  function wrap(candles) { return colsOf(candles); }

  // ---- 型態歷史命中率 -------------------------------------
  // detectFn(slice) → truthy 表示在該 slice 末端偵測到型態
  // 註:此為「偵測日收盤 → N 日後收盤」的統計量(不含費稅/滑價),
  //     非交易模擬;交易級結論請用 run/runLS。
  function patternHitRate(candles, detectFn, fwd) {
    fwd = fwd || 10;
    const hits = [];
    const minBars = 40;
    for (let i = minBars; i < candles.length - fwd; i++) {
      let det = false;
      try { det = !!detectFn(candles.slice(0, i + 1)); } catch { det = false; }
      if (det) {
        const r = (candles[i + fwd].close - candles[i].close) / candles[i].close;
        hits.push(r);
      }
    }
    if (!hits.length) return { count: 0, hitRate: null, avgRet: null };
    const wins = hits.filter(r => r > 0).length;
    return {
      count: hits.length,
      hitRate: wins / hits.length * 100,
      avgRet: hits.reduce((s, r) => s + r, 0) / hits.length * 100,
      fwd,
    };
  }

  // ---- 投組回測：等資金或自訂權重 -------------------------
  function portfolio(perSymCurves, weights) {
    // perSymCurves: {sym: [{time,equity}]}; weights: {sym: w} (預設等權)
    const syms = Object.keys(perSymCurves);
    if (!syms.length) return null;
    const w = weights || Object.fromEntries(syms.map(s => [s, 1 / syms.length]));
    const allTimes = [...new Set(syms.flatMap(s => perSymCurves[s].map(p => p.time)))].sort((a, b) => a - b);
    const last = {}; syms.forEach(s => last[s] = 1);
    const curve = allTimes.map(t => {
      syms.forEach(s => {
        const pt = perSymCurves[s].filter(p => p.time <= t).pop();
        if (pt) last[s] = pt.equity;
      });
      const eq = syms.reduce((sum, s) => sum + w[s] * last[s], 0);
      return { time: t, equity: eq };
    });
    return { curve, finalReturn: (curve[curve.length - 1].equity - 1) * 100 };
  }

  // ---- 權益曲線繪製 (canvas) ------------------------------
  function drawCurve(canvas, curve, color) {
    if (!canvas || !curve || !curve.length) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    const eqs = curve.map(p => p.equity);
    const lo = Math.min(1, ...eqs), hi = Math.max(1, ...eqs);
    const x = i => i / (curve.length - 1) * (W - 8) + 4;
    const y = v => H - 4 - (v - lo) / (hi - lo || 1) * (H - 8);
    // baseline equity=1
    ctx.strokeStyle = 'rgba(148,163,184,.3)'; ctx.beginPath();
    ctx.moveTo(4, y(1)); ctx.lineTo(W - 4, y(1)); ctx.stroke();
    ctx.strokeStyle = color || '#34d399'; ctx.lineWidth = 1.5; ctx.beginPath();
    curve.forEach((p, i) => { const px = x(i), py = y(p.equity); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke();
  }

  window.Backtest = {
    run, runLS, scanStrategies, patternHitRate, portfolio, drawCurve,
    STRATEGIES, sma, rsi, bbLower, colsOf, crossUp, breakout,
  };
})();

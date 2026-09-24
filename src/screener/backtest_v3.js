// ============================================================
// Stock Terminal v3.8 — 統一回測引擎 (Unified Backtest Core)
// ------------------------------------------------------------
// 一個核心，三種用法：
//   1. 策略回測：WATCH 8 策略任一 → 勝率 / 賠率 / 期望值 / 權益曲線
//   2. 型態命中率：pattern_v3 19 型態 → 偵測後 N 日報酬分布
//   3. 投組回測：多檔 + 資金配置 → 投組權益曲線
// 自足指標 (SMA/RSI/BB)，不依賴其他模組內部實作。
// 公開 API：window.Backtest
// ============================================================
(function () {
  'use strict';

  // ---- 指標 ------------------------------------------------
  function sma(arr, p) {
    const out = new Array(arr.length).fill(null);
    let s = 0;
    for (let i = 0; i < arr.length; i++) {
      s += arr[i];
      if (i >= p) s -= arr[i - p];
      if (i >= p - 1) out[i] = s / p;
    }
    return out;
  }
  function rsi(closes, p) {
    p = p || 14;
    const out = new Array(closes.length).fill(null);
    let g = 0, l = 0;
    for (let i = 1; i <= p; i++) {
      const d = closes[i] - closes[i - 1];
      if (d >= 0) g += d; else l -= d;
    }
    g /= p; l /= p;
    out[p] = 100 - 100 / (1 + (l === 0 ? 100 : g / l));
    for (let i = p + 1; i < closes.length; i++) {
      const d = closes[i] - closes[i - 1];
      g = (g * (p - 1) + (d > 0 ? d : 0)) / p;
      l = (l * (p - 1) + (d < 0 ? -d : 0)) / p;
      out[i] = 100 - 100 / (1 + (l === 0 ? 100 : g / l));
    }
    return out;
  }
  function bbLower(closes, p, k) {
    p = p || 20; k = k || 2;
    const m = sma(closes, p);
    const out = new Array(closes.length).fill(null);
    for (let i = p - 1; i < closes.length; i++) {
      let v = 0;
      for (let j = i - p + 1; j <= i; j++) v += (closes[j] - m[i]) ** 2;
      out[i] = m[i] - k * Math.sqrt(v / p);
    }
    return out;
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
  // opts: {tp:0.15, sl:0.08, maxBars:20, short:false}
  function run(candles, signalArr, opts) {
    return simulate(candles, signalArr, null, Object.assign({ tp: .15, sl: .08, maxBars: 20 }, opts || {}));
  }

  const ENGINE_VERSION = 'backtest-next-open/2026-09-v1';
  const positive = value => Number.isFinite(value) && value > 0;
  function executable(bar) {
    if (!bar || !['open', 'high', 'low', 'close'].every(key => positive(bar[key]))) return '價格缺值';
    if (!(bar.low <= Math.min(bar.open, bar.close) && Math.max(bar.open, bar.close) <= bar.high)) return '開高低收邊界無效';
    if (!positive(bar.volume)) return '成交量未知或無成交';
    if (bar.issues && bar.issues.length) return '來源品質尚未通過';
    if (bar.corporateAction) return '公司行動未建立持有權利計算';
    if (bar.open === bar.high && bar.high === bar.low && bar.low === bar.close) return '一價日無法證實成交';
    return null;
  }
  function simulate(candles, buyArr, sellArr, options) {
    const opts = Object.assign({ tp: 0, sl: 0, maxBars: 0, short: false,
      feeRate: 0, taxRate: 0, slippage: 0, barsPerYear: 252 }, options || {});
    for (const key of ['tp', 'sl', 'feeRate', 'taxRate', 'slippage']) {
      if (!Number.isFinite(opts[key]) || opts[key] < 0 || (['feeRate', 'taxRate', 'slippage'].includes(key) && opts[key] >= 1)) throw new Error('回測參數無效：' + key);
    }
    if (!Number.isInteger(opts.maxBars) || opts.maxBars < 0) throw new Error('最長持有棒數必須為非負整數');
    if (!positive(opts.barsPerYear)) throw new Error('年化棒數假設必須大於零');
    const trades = [], curve = [], rejected = [], valuationIssues = [];
    let cash = 1, position = null, pendingEntry = null, pendingExit = null;
    let peak = 1, maxDD = 0, lastEquity = 1, bankrupt = false;
    const sign = opts.short ? -1 : 1;
    const fill = (price, entering) => price * (1 + (entering ? sign : -sign) * opts.slippage);
    const rate = entering => opts.feeRate + ((entering ? opts.short : !opts.short) ? opts.taxRate : 0);
    for (let i = 0; i < candles.length; i++) {
      const bar = candles[i];
      let reason = executable(bar);
      const previous = i ? candles[i - 1] : null;
      const openingGap = !opts.corporateActionsVerified && previous && positive(previous.close) &&
        positive(bar.open) && Math.abs(bar.open / previous.close - 1) > .15;
      const closingGap = !opts.corporateActionsVerified && previous && positive(previous.close) &&
        positive(bar.close) && Math.abs(bar.close / previous.close - 1) > .15;
      if (openingGap) reason = '重大開盤價格斷點缺少公司行動核對';
      if (position && (bar.corporateAction || openingGap)) position.accountingUnknown = true;
      if (position && pendingExit) {
        if (reason || position.accountingUnknown) rejected.push({ kind: 'exit', bar: i, time: bar.time,
          reason: reason || '公司行動後持有權利未知', signalBar: pendingExit.bar });
        else {
          const exit = fill(bar.open, false), exitCosts = position.quantity * exit * rate(false);
          cash = position.capital - position.entryCosts + sign * position.quantity * (exit - position.entry) - exitCosts;
          trades.push({ signalBar: position.signalBar, entryBar: position.entryBar, exitBar: i,
            entry: position.entry, exit, rawEntryOpen: position.rawEntryOpen, rawExitOpen: bar.open,
            ret: cash / position.capital - 1, reason: pendingExit.reason,
            time: candles[position.entryBar].time, signalTime: candles[position.signalBar].time,
            exitTime: bar.time, holdBars: i - position.entryBar,
            entryCosts: position.entryCosts, exitCosts, quantity: position.quantity,
            exitSignalBar: pendingExit.bar });
          position = null; pendingExit = null;
        }
      }
      if (pendingEntry && !position && !bankrupt) {
        if (reason) rejected.push({ kind: 'entry', bar: i, time: bar.time, reason, signalBar: pendingEntry.bar });
        else {
          const entry = fill(bar.open, true), quantity = cash / (entry * (1 + rate(true)));
          position = { signalBar: pendingEntry.bar, entryBar: i, entry, rawEntryOpen: bar.open,
            capital: cash, quantity, entryCosts: quantity * entry * rate(true) };
        }
        // 進場只嘗試訊號後下一棒；失敗不跳至之後有價格的日期。
        pendingEntry = null;
      }
      let equity = cash;
      if (position) {
        if (closingGap) position.accountingUnknown = true;
        if (positive(bar.close) && (!reason || reason === '一價日無法證實成交') && !position.accountingUnknown) {
          equity = position.capital - position.entryCosts + sign * position.quantity * (bar.close - position.entry);
          const gross = sign * (bar.close / position.entry - 1);
          if (!pendingExit) {
            const exitReason = opts.tp > 0 && gross >= opts.tp ? 'tp' : opts.sl > 0 && gross <= -opts.sl ? 'sl' :
              opts.maxBars > 0 && i - position.entryBar + 1 >= opts.maxBars ? 'time' : sellArr && sellArr[i] ? 'signal' : null;
            if (exitReason) pendingExit = { bar: i, reason: exitReason };
          }
        } else {
          equity = null;
          valuationIssues.push({ bar: i, time: bar.time, reason: position.accountingUnknown ? '持有期間公司行動或價格斷點未知' : '持有期間無有效估值' });
        }
      }
      if (Number.isFinite(equity)) {
        peak = Math.max(peak, equity);
        maxDD = Math.max(maxDD, (peak - equity) / peak);
        bankrupt = bankrupt || equity <= 0;
      }
      lastEquity = equity;
      curve.push({ time: bar.time, equity, known: Number.isFinite(equity), position: !!position,
        drawdown: Number.isFinite(equity) ? (peak - equity) / peak * 100 : null });
      if (!position && !pendingEntry && buyArr && buyArr[i] && !bankrupt) {
        if (closingGap) reason = '重大收盤價格斷點缺少公司行動核對';
        if (reason) rejected.push({ kind: 'signal', bar: i, time: bar.time, reason });
        else pendingEntry = { bar: i };
      }
    }
    const result = summarize(trades, candles.length ? lastEquity : null, valuationIssues.length || !candles.length ? null : maxDD, curve);
    const barReturns = [];
    for (let i = 1; i < curve.length; i++) if (positive(curve[i - 1].equity) && Number.isFinite(curve[i].equity)) barReturns.push(curve[i].equity / curve[i - 1].equity - 1);
    const avg = barReturns.length ? barReturns.reduce((sum, value) => sum + value, 0) / barReturns.length : 0;
    const sd = barReturns.length > 1 ? Math.sqrt(barReturns.reduce((sum, value) => sum + (value - avg) ** 2, 0) / (barReturns.length - 1)) : 0;
    result.sharpe = valuationIssues.length ? null : sd ? avg / sd : null;
    result.sharpeAnn = result.sharpe == null ? null : result.sharpe * Math.sqrt(opts.barsPerYear);
    return Object.assign(result, { engineVersion: ENGINE_VERSION, status: !candles.length ? 'insufficient' : valuationIssues.length ? 'unknown' : 'complete',
      openPosition: position ? { ...position, markTime: candles.length ? candles[candles.length - 1].time : null,
        markEquity: lastEquity, pendingExit, unrealizedReturnPct: lastEquity == null ? null : (lastEquity / position.capital - 1) * 100 } : null,
      pendingEntry, rejected, valuationIssues, bankrupt, realizedEquity: cash,
      maxDDLowerBound: maxDD * 100,
      methodology: { version: ENGINE_VERSION, entry: '收盤訊號後下一根提供的開盤價；不可成交便取消進場',
        exit: '收盤確認停利、停損、期限或出場訊號後下一棒開盤；無法成交保留待出場部位',
        valuation: '每棒收盤按市價估值；期末未平倉不強制成交；未知估值令回撤為無值',
        costs: { feeRate: opts.feeRate, sellTaxRate: opts.taxRate, adverseSlippage: opts.slippage },
        annualization: '每年 ' + opts.barsPerYear + ' 棒的假設，須與輸入頻率相符',
        calendar: '依輸入棒序列；未另外證實完整市場交易日曆',
        dataQuality: '交易日曆、完整公司行動與流動性未全部核對，僅供探索，不能升格為有效策略證據',
        scope: '同樣本策略探索，不是樣本外證據；空方未含借券可得性與借券費' } });
  }

  function summarize(trades, equity, maxDD, curve) {
    const n = trades.length;
    const wins = trades.filter(t => t.ret > 0);
    const losses = trades.filter(t => t.ret <= 0);
    const avgWin = wins.length ? wins.reduce((s, t) => s + t.ret, 0) / wins.length : 0;
    const avgLoss = losses.length ? losses.reduce((s, t) => s + t.ret, 0) / losses.length : 0;
    const winRate = n ? wins.length / n * 100 : 0;
    const expectancy = n ? trades.reduce((s, t) => s + t.ret, 0) / n : 0;
    const rets = trades.map(t => t.ret);
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
    return {
      count: n, winRate, wins: wins.length, losses: losses.length,
      avgWin: avgWin * 100, avgLoss: avgLoss * 100, payoff,
      expectancy: expectancy * 100, totalReturn: equity == null ? null : (equity - 1) * 100,
      maxDD: maxDD == null ? null : maxDD * 100,
      profitFactor, avgHoldBars,
      maxWinStreak: winStreak, maxLossStreak: lossStreak,
      best: best * 100, worst: worst * 100,
      trades, curve,
    };
  }

  // ---- 進出場雙訊號回測 (給樂高條件器 / 腳本引擎用) -------
  // buyArr[i] 進場、sellArr[j] 出場；tp/sl/maxBars 任一先到也出場。
  // 同一時間只持有一個部位(進場後直到出場才找下一筆)。
  function runLS(candles, buyArr, sellArr, opts) {
    return simulate(candles, buyArr, sellArr, opts);
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
    if (syms.some(s => !Number.isFinite(w[s]) || w[s] < 0) || Math.abs(syms.reduce((sum, s) => sum + w[s], 0) - 1) > 1e-9) throw new Error('投組權重須為非負且合計為 1');
    const allTimes = [...new Set(syms.flatMap(s => perSymCurves[s].map(p => p.time)))].sort((a, b) => a < b ? -1 : a > b ? 1 : 0);
    const last = {}; syms.forEach(s => last[s] = 1);
    const curve = allTimes.map(t => {
      syms.forEach(s => {
        const pt = perSymCurves[s].filter(p => p.time <= t).pop();
        if (pt) last[s] = pt.equity;
      });
      const eq = syms.some(s => w[s] > 0 && !Number.isFinite(last[s])) ? null : syms.reduce((sum, s) => sum + w[s] * (last[s] || 0), 0);
      return { time: t, equity: eq };
    });
    const lastEquity = curve.length ? curve[curve.length - 1].equity : null;
    return { curve, finalReturn: Number.isFinite(lastEquity) ? (lastEquity - 1) * 100 : null,
      methodology: '既定權重的獨立資金分配合成，缺價保留未知；未共用資金池或模擬再平衡' };
  }

  // ---- 權益曲線繪製 (canvas) ------------------------------
  function drawCurve(canvas, curve, color) {
    if (!canvas || !curve || !curve.length) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    const eqs = curve.map(p => p.equity).filter(Number.isFinite);
    const lo = Math.min(1, ...eqs), hi = Math.max(1, ...eqs);
    const x = i => i / Math.max(1, curve.length - 1) * (W - 8) + 4;
    const y = v => H - 4 - (v - lo) / (hi - lo || 1) * (H - 8);
    // baseline equity=1
    ctx.strokeStyle = 'rgba(148,163,184,.3)'; ctx.beginPath();
    ctx.moveTo(4, y(1)); ctx.lineTo(W - 4, y(1)); ctx.stroke();
    ctx.strokeStyle = color || '#34d399'; ctx.lineWidth = 1.5; ctx.beginPath();
    let connected = false;
    curve.forEach((p, i) => { if (!Number.isFinite(p.equity)) { connected = false; return; }
      const px = x(i), py = y(p.equity); connected ? ctx.lineTo(px, py) : ctx.moveTo(px, py); connected = true; });
    ctx.stroke();
  }

  window.Backtest = {
    run, runLS, scanStrategies, patternHitRate, portfolio, drawCurve,
    STRATEGIES, sma, rsi, bbLower, colsOf, crossUp, breakout, ENGINE_VERSION,
  };
})();

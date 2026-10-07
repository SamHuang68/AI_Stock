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
  // sma／rsi 也是 StratLib 的實作（strategy_builder 直接引用，勿另寫一份）
  function sma(arr, p) {
    const out = new Array(arr.length).fill(null);
    let s = 0, count = 0;
    for (let i = 0; i < arr.length; i++) {
      if (Number.isFinite(arr[i])) { s += arr[i]; count++; }
      if (i >= p && Number.isFinite(arr[i - p])) { s -= arr[i - p]; count--; }
      if (i >= p - 1 && count === p) out[i] = s / p;
    }
    return out;
  }
  function rsi(closes, p) {
    p = p || 14;
    const out = new Array(closes.length).fill(null);
    let g = 0, l = 0, count = 0;
    for (let i = 1; i < closes.length; i++) {
      if (!Number.isFinite(closes[i]) || !Number.isFinite(closes[i - 1])) { g = 0; l = 0; count = 0; continue; }
      const d = closes[i] - closes[i - 1];
      if (count < p) {
        g += Math.max(d, 0); l += Math.max(-d, 0); count++;
        if (count === p) { g /= p; l /= p; }
      } else { g = (g * (p - 1) + Math.max(d, 0)) / p; l = (l * (p - 1) + Math.max(-d, 0)) / p; }
      if (count >= p) out[i] = (l === 0 ? 100 : 100 - 100 / (1 + g / l));
    }
    return out;
  }
  function bbLower(closes, p, k) {
    p = p || 20; k = k || 2;
    const m = sma(closes, p);
    const out = new Array(closes.length).fill(null);
    for (let i = p - 1; i < closes.length; i++) {
      if (m[i] == null) continue;
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
    breakout20: { name: '突破 20 日新高', fn: (c, issues) => breakout(c.high, c.close, 20, issues) },
    breakout60: { name: '突破 60 日新高', fn: (c, issues) => breakout(c.high, c.close, 60, issues) },
    rsi_oversold: { name: 'RSI 超賣反彈', fn: c => { const r = rsi(c.close, 14); return c.close.map((_, i) => i > 0 && r[i - 1] != null && r[i - 1] < 30 && r[i] >= 30); } },
    rsi_overheat: { name: 'RSI 過熱(空)', fn: c => { const r = rsi(c.close, 14); return c.close.map((_, i) => i > 0 && r[i - 1] != null && r[i - 1] > 70 && r[i] != null && r[i] <= 70); }, short: true },
    bb_lower: { name: '布林下軌承接', fn: c => { const b = bbLower(c.close, 20, 2); return c.close.map((_, i) => b[i] != null && c.low[i] != null && c.low[i] <= b[i] && c.close[i] > b[i]); } },
    golden_cross: { name: '黃金交叉(20/60)', fn: c => crossUp(sma(c.close, 20), sma(c.close, 60)) },
  };

  function crossUp(a, b) {
    return a.map((_, i) => i > 0 && a[i] != null && a[i - 1] != null && b[i - 1] != null && b[i] != null && a[i - 1] <= b[i - 1] && a[i] > b[i]);
  }
  function breakout(high, close, p, issues) {
    const out = new Array(close.length).fill(false);
    for (let i = 0; i < close.length; i++) {
      if (i < p) {
        if (issues) issues.push({ bar: i, code: 'insufficient_lookback', lookback: p, availableBars: i });
        continue;
      }
      let hh = -Infinity;
      const missingBars = [];
      for (let j = i - p; j < i; j++) {
        if (Number.isFinite(high[j])) hh = Math.max(hh, high[j]);
        else missingBars.push(j);
      }
      if (missingBars.length) {
        if (issues) issues.push({ bar: i, code: 'missing_lookback_high', lookback: p,
          windowStartBar: i - p, windowEndBar: i - 1, missingBars });
        continue; // 未知最高價不能略過，保留保守 false。
      }
      out[i] = Number.isFinite(close[i]) && close[i] > hh;
    }
    return out;
  }

  // ---- 核心回測 --------------------------------------------
  // candles: [{time,open,high,low,close,volume}]
  // opts: {tp:0.15, sl:0.08, maxBars:20, short:false}
  const ENGINE_VERSION = 'st-backtest/4.0.2';
  const DEFAULTS = Object.freeze({ tp: 0, sl: 0, maxBars: 0, short: false,
    entryFeeBps: 10, exitFeeBps: 10, slippageBps: 5, periodsPerYear: 252,
    annualRiskFreeRate: 0, market: 'TW' });
  const LIMITATIONS = Object.freeze([
    '僅模擬已提供的日線；沒有交易所日曆，缺列與休市無法自動區分。',
    '日成交量只作可成交性代理，不能證明開盤即有流動性；未提供撮合與開盤委託資料。',
    '停利／停損於收盤判斷，下次可成交開盤執行；不模擬盤中觸價、限價排隊或漲跌停成交。',
    '費用與滑價為可調情境值，非券商牌告；未含借券、融資、股息、稅務與整張限制。',
    '未驗證還原價格、點時財報與下市全集，不能宣稱已消除存活者偏差；不等同訊號成績單事件研究。',
  ]);
  const DATE_FORMATTERS = Object.create(null);
  function dateFormatter(market) {
    if (market !== 'TW' && market !== 'US') throw new TypeError('日線市場未提供日期契約');
    if (!DATE_FORMATTERS[market]) DATE_FORMATTERS[market] = new Intl.DateTimeFormat('en-CA', {
      timeZone: market === 'US' ? 'America/New_York' : 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit'
    });
    return DATE_FORMATTERS[market];
  }

  function settings(opts) {
    const out = Object.assign({}, DEFAULTS, opts || {});
    for (const key of ['tp', 'sl', 'entryFeeBps', 'exitFeeBps', 'slippageBps', 'annualRiskFreeRate']) {
      if (typeof out[key] !== 'number' || !Number.isFinite(out[key]) || out[key] < 0)
        throw new Error('回測設定無效：' + key);
    }
    if (out.sl >= 1 || out.entryFeeBps >= 10000 || out.exitFeeBps >= 10000 || out.slippageBps >= 10000)
      throw new Error('費用、滑價與停損必須小於 100%');
    if (!Number.isInteger(out.maxBars) || out.maxBars < 0 || !Number.isInteger(out.periodsPerYear) || out.periodsPerYear < 1)
      throw new Error('持有根數與年化日數必須是有效整數');
    if (typeof out.short !== 'boolean' || !['TW', 'US'].includes(out.market)) throw new Error('市場或方向設定無效');
    return out;
  }

  function dateKey(time, market) {
    if (typeof time === 'number' && Number.isFinite(time)) {
      const date = new Date(time * 1000);
      if (!Number.isFinite(date.getTime())) throw new Error('日線時間無效');
      const parts = dateFormatter(market || 'TW').formatToParts(date);
      const get = key => parts.find(p => p.type === key).value;
      return `${get('year')}-${get('month')}-${get('day')}`;
    }
    if (time && typeof time === 'object') time = `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`;
    if (typeof time !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(time)
      || !Number.isFinite(Date.parse(time)) || new Date(time).toISOString().slice(0, 10) !== time)
      throw new Error('請提供有效的交易日或秒級時間戳');
    return time;
  }
  const price = value => typeof value === 'number' && Number.isFinite(value) && value > 0;

  function validateBars(candles, opts) {
    if (!Array.isArray(candles)) throw new Error('日線資料必須是陣列');
    let previous = '';
    return candles.map((bar, i) => {
      if (!bar || typeof bar !== 'object') throw new Error('第 ' + (i + 1) + ' 根日線無效');
      const date = dateKey(bar.time, opts.market);
      if (date <= previous) throw new Error('回測僅支援依序且每日一根的日線，不接受重複／亂序／盤中線');
      previous = date;
      for (const key of ['open', 'high', 'low', 'close']) {
        if (bar[key] != null && !price(bar[key])) throw new Error('第 ' + (i + 1) + ' 根價格無效：' + key);
      }
      if (price(bar.high) && price(bar.low) && (bar.high < bar.low
        || ['open', 'close'].some(k => price(bar[k]) && (bar[k] > bar.high || bar[k] < bar.low))))
        throw new Error('第 ' + (i + 1) + ' 根 OHLC 範圍不一致');
      if (bar.volume != null && (typeof bar.volume !== 'number' || !Number.isFinite(bar.volume) || bar.volume < 0))
        throw new Error('成交量無效');
      return { ...bar, date };
    });
  }

  // 單一成交／成本核心。收盤訊號只能在較晚的可成交 bar 開盤執行。
  // TP/SL 使用收盤門檻，不從每日 high/low 猜盤中先後；期末不強制平倉。
  function simulate(candles, buyArr, sellArr, rawOpts) {
    const opts = settings(rawOpts), bars = validateBars(candles, opts);
    for (const series of [buyArr, sellArr]) {
      if (series != null && (!Array.isArray(series) || series.length !== bars.length))
        throw new Error('訊號長度須與日線一致');
    }
    if (!Array.isArray(buyArr)) throw new Error('缺少進場訊號');
    const start = opts.startDate == null ? null : dateKey(opts.startDate, opts.market);
    const end = opts.endDate == null ? null : dateKey(opts.endDate, opts.market);
    if (start && end && start > end) throw new Error('起日不得晚於截止日');
    let cash = 1, equity = 1, peak = 1, maxDD = 0, position = null, pending = null, lastMark = null, halted = false;
    const trades = [], curve = [], dailyReturns = [], issues = [];
    const sign = opts.short ? -1 : 1;
    const slip = opts.slippageBps / 10000, entryFee = opts.entryFeeBps / 10000, exitFee = opts.exitFeeBps / 10000;
    let observed = 0;
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i];
      if (start && b.date < start || end && b.date > end) continue;
      observed++;
      // 缺開盤／缺成交量／停牌時保留指令，不造出成交價。
      const tradable = price(b.open) && typeof b.volume === 'number' && b.volume > 0 && b.suspended !== true;
      if (!tradable) issues.push({ bar: i, date: b.date, code: 'untradable_bar' });
      if (pending && tradable && pending.signalBar < i) {
        if (pending.side === 'entry' && equity > 0) {
          const entry = b.open * (1 + sign * slip), before = equity;
          const quantity = before / (entry * (1 + entryFee));
          const fee = quantity * entry * entryFee;
          cash -= sign * quantity * entry + fee;
          position = { signalBar: pending.signalBar, signalTime: candles[pending.signalBar].time,
            entryBar: i, entry, quantity, before, entryFee: fee, time: b.time, direction: opts.short ? 'short' : 'long' };
          lastMark = b.open;
        } else if (pending.side === 'exit' && position) {
          const exit = b.open * (1 - sign * slip), fee = position.quantity * exit * exitFee;
          cash += sign * position.quantity * exit - fee;
          trades.push({ ...position, exit, exitBar: i, exitTime: b.time, exitFee: fee, pnl: cash - position.before,
            exitSignalBar: pending.signalBar, reason: pending.reason,
            ret: cash / position.before - 1, holdBars: i - position.entryBar });
          position = null;
        }
        pending = null;
      }
      const previousEquity = equity;
      if (price(b.close)) lastMark = b.close;
      else issues.push({ bar: i, date: b.date, code: 'missing_close_carried' });
      equity = position ? cash + sign * position.quantity * lastMark : cash;
      peak = Math.max(peak, equity);
      maxDD = Math.max(maxDD, (peak - equity) / peak);
      curve.push({ time: b.time, date: b.date, equity, valuation: price(b.close) ? 'close' : 'carried' });
      // 第一根收盤為基準，之後所有日線（包括空手）用同一報酬口徑。
      if (observed > 1) dailyReturns.push(previousEquity > 0 ? equity / previousEquity - 1 : null);
      if (equity <= 0) {
        halted = true;
        issues.push({ bar: i, date: b.date, code: 'non_positive_equity' });
        if (position && !pending) pending = { side: 'exit', signalBar: i, reason: 'insolvent' };
      }
      if (price(b.close) && !pending && equity > 0) {
        if (position) {
          const ret = sign * (b.close - position.entry) / position.entry;
          let reason = null;
          if (opts.sl > 0 && ret <= -opts.sl) reason = 'sl';
          else if (opts.tp > 0 && ret >= opts.tp) reason = 'tp';
          else if (opts.maxBars > 0 && i - position.entryBar + 1 >= opts.maxBars) reason = 'time';
          else if (sellArr && sellArr[i]) reason = 'signal';
          if (reason) pending = { side: 'exit', signalBar: i, reason };
        } else if (buyArr[i] && !halted) pending = { side: 'entry', signalBar: i, reason: 'signal' };
      }
    }
    if (pending) issues.push({ bar: pending.signalBar, code: 'no_next_tradable_bar', side: pending.side });
    const openPosition = position ? { ...position, mark: lastMark, equity,
      unrealizedReturn: equity / position.before - 1, pendingExit: pending && pending.side === 'exit' ? pending.reason : null } : null;
    return { ...summarize(trades, equity, maxDD, curve, dailyReturns, opts, !!position || trades.length > 0), openPosition, pendingOrder: pending,
      engineVersion: ENGINE_VERSION, settings: opts, issues, limitations: [...LIMITATIONS], halted,
      evaluation: 'in-sample', asOf: curve.length ? curve[curve.length - 1].date : null,
      execution: 'close-signal-next-tradable-open', equityBasis: 'daily-close-mark-to-market',
      sharpeBasis: 'daily-simple-excess-return-sample-standard-deviation' };
  }

  function run(candles, signalArr, opts) {
    return simulate(candles, signalArr, null, Object.assign({ tp: 0.15, sl: 0.08, maxBars: 20 }, opts || {}));
  }

  function runLS(candles, buyArr, sellArr, opts) {
    return simulate(candles, buyArr, sellArr, opts);
  }

  function summarize(trades, equity, maxDD, curve, dailyReturns, opts, hadEntry) {
    const n = trades.length, wins = trades.filter(t => t.ret > 0), losses = trades.filter(t => t.ret <= 0);
    const sum = a => a.reduce((s, t) => s + t.ret, 0);
    const avgWin = wins.length ? sum(wins) / wins.length : 0;
    const avgLoss = losses.length ? sum(losses) / losses.length : 0;
    const expectancy = n ? sum(trades) / n : 0;
    const rf = Math.pow(1 + opts.annualRiskFreeRate, 1 / opts.periodsPerYear) - 1;
    const excess = dailyReturns.filter(r => r != null).map(r => r - rf);
    const mean = excess.length ? excess.reduce((s, r) => s + r, 0) / excess.length : 0;
    const sd = excess.length > 1 ? Math.sqrt(excess.reduce((s, r) => s + (r - mean) ** 2, 0) / (excess.length - 1)) : 0;
    const sharpe = sd > 0 && excess.length === dailyReturns.length ? mean / sd * Math.sqrt(opts.periodsPerYear) : null;
    // 原計算規則不變；零筆「已平倉」不等於沒有成交，未平倉仍可有有效 Sharpe。
    const sharpeReason = sharpe != null ? null
      : excess.length !== dailyReturns.length ? 'non_positive_prior_equity'
        : excess.length < 2 ? 'insufficient_samples'
          : !hadEntry ? 'no_trades' : 'zero_variance';
    const payoff = avgLoss ? Math.abs(avgWin / avgLoss) : (avgWin ? Infinity : null);
    const grossWin = wins.reduce((s, t) => s + t.pnl, 0), grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));
    const profitFactor = grossLoss ? grossWin / grossLoss : (grossWin ? Infinity : null);
    let winStreak = 0, lossStreak = 0, curW = 0, curL = 0;
    for (const t of trades) {
      if (t.ret > 0) { curW++; curL = 0; winStreak = Math.max(winStreak, curW); }
      else { curL++; curW = 0; lossStreak = Math.max(lossStreak, curL); }
    }
    const rets = trades.map(t => t.ret);
    return { count: n, winRate: n ? wins.length / n * 100 : null, wins: wins.length, losses: losses.length,
      avgWin: wins.length ? avgWin * 100 : null, avgLoss: losses.length ? avgLoss * 100 : null,
      payoff: n ? payoff : null,
      expectancy: n ? expectancy * 100 : null, totalReturn: (equity - 1) * 100, maxDD: maxDD * 100,
      sharpe, sharpeAnn: sharpe, sharpeReason, profitFactor,
      avgHoldBars: n ? trades.reduce((s, t) => s + t.holdBars, 0) / n : null,
      maxWinStreak: winStreak, maxLossStreak: lossStreak,
      best: n ? Math.max(...rets) * 100 : null, worst: n ? Math.min(...rets) * 100 : null,
      trades, curve, dailyReturns };
  }

  function colsOf(candles) {
    return {
      open: candles.map(c => c.open), high: candles.map(c => c.high),
      low: candles.map(c => c.low), close: candles.map(c => c.close),
      volume: candles.map(c => c.volume == null ? null : c.volume),
    };
  }

  // ---- 多策略掃描：每策略歷史勝率 -------------------------
  function runStrategy(candles, strategy, opts) {
    const signalIssues = [];
    const sig = strategy.fn(wrap(candles), signalIssues);
    const result = run(candles, sig, { ...opts, short: !!strategy.short });
    const evaluatedDates = new Set(result.curve.map(p => p.date));
    const dateAt = i => dateKey(candles[i].time, result.settings.market);
    for (const issue of signalIssues) {
      const date = dateAt(issue.bar);
      if (!evaluatedDates.has(date)) continue; // 暖機可以讀過去，但不能混入評估區間外的提醒。
      result.issues.push({ ...issue, date, ...(issue.missingBars ? {
        windowStartDate: dateAt(issue.windowStartBar), windowEndDate: dateAt(issue.windowEndBar),
        missingDates: issue.missingBars.map(dateAt) } : {}) });
    }
    return result;
  }
  function scanStrategies(candles, opts) {
    validateBars(candles, settings(opts));
    const rows = [];
    for (const [key, st] of Object.entries(STRATEGIES)) {
      const r = runStrategy(candles, st, opts);
      rows.push({ key, name: st.name, ...r });
    }
    return rows.sort((a, b) => a.expectancy == null ? (b.expectancy == null ? 0 : 1)
      : b.expectancy == null ? -1 : b.expectancy - a.expectancy);
  }
  function wrap(candles) { return colsOf(candles); }

  // 固定日期切分：只用訓練期挑策略，測試期從空手開始；暖機只讀過去。
  // 不提供會反覆掃描測試結果的自動調參，避免把測試集變成訓練集。
  function evaluateStrategies(candles, opts) {
    if (!opts || !opts.trainEnd || !opts.testEnd) throw new Error('須先固定 trainEnd 與 testEnd');
    const config = settings(opts), bars = validateBars(candles, config);
    const trainEnd = dateKey(opts.trainEnd, config.market), testEnd = dateKey(opts.testEnd, config.market);
    if (trainEnd >= testEnd) throw new Error('訓練截止日必須早於測試截止日');
    const train = candles.filter((_, i) => bars[i].date <= trainEnd);
    const prefix = candles.filter((_, i) => bars[i].date <= testEnd);
    const testStart = bars.find(b => b.date > trainEnd && b.date <= testEnd)?.date;
    if (!train.length || !testStart) throw new Error('固定切分的訓練期或測試期沒有日線');
    const common = { ...config }; delete common.startDate; delete common.endDate;
    const ranked = scanStrategies(train, common);
    const selected = ranked.find(r => r.count > 0);
    if (!selected) return { engineVersion: ENGINE_VERSION, trainEnd, testEnd, selected: null, training: ranked,
      test: null, reason: '訓練期沒有已平倉交易，無法選定策略', limitations: [...LIMITATIONS] };
    const strategy = STRATEGIES[selected.key];
    const test = runStrategy(prefix, strategy, { ...common, startDate: testStart });
    test.evaluation = 'fixed-holdout';
    return { engineVersion: ENGINE_VERSION, trainEnd, testEnd, testStart, selected: selected.key,
      selectionMetric: 'training-net-expectancy', training: ranked, test, limitations: [...LIMITATIONS] };
  }

  const SHARPE_REASONS = Object.freeze({
    non_positive_prior_equity: '前期權益非正，部分每日報酬無法定義',
    insufficient_samples: '不足兩個每日報酬樣本',
    no_trades: '沒有實際成交，權益沒有波動',
    zero_variance: '每日報酬沒有波動',
  });
  function describeIssue(issue) {
    const prefix = issue.date ? issue.date + '：' : '';
    if (issue.code === 'missing_lookback_high') return prefix + `前 ${issue.lookback} 根最高價缺值（${(issue.missingDates || issue.missingBars.map(i => `第 ${i + 1} 根`)).join('、')}），突破訊號未判定`;
    if (issue.code === 'insufficient_lookback') return prefix + `回看需 ${issue.lookback} 根、僅有 ${issue.availableBars} 根，突破訊號未判定`;
    const labels = { untradable_bar: '缺有效開盤／成交量或停牌，不能成交', missing_close_carried: '缺收盤價，沿用上一估值',
      no_next_tradable_bar: '沒有下一可成交日，委託尚未執行', non_positive_equity: '權益非正，停止開新倉' };
    return prefix + (labels[issue.code] || issue.code);
  }
  function describeSignalIssues(result) {
    const missing = result.issues.filter(i => i.code === 'missing_lookback_high');
    const warmup = result.issues.filter(i => i.code === 'insufficient_lookback');
    return [missing.length ? `${missing.length} 根突破訊號因回看最高價缺值未判定；${describeIssue(missing[0])}` : '',
      warmup.length ? `${warmup.length} 根突破訊號因回看根數不足未判定` : ''].filter(Boolean).join('。');
  }
  function describe(result) {
    const s = result.settings;
    const sharpeNote = result.sharpeReason ? `每日夏普為 —：${SHARPE_REASONS[result.sharpeReason]}。` : '';
    const signalNote = describeSignalIssues(result);
    return `${result.engineVersion}｜${s.market} 日線｜收盤訊號→下一可成交開盤｜進／出費 ${s.entryFeeBps}/${s.exitFeeBps} bp｜滑價 ${s.slippageBps} bp／邊｜每日估值、年化 ${s.periodsPerYear} 日、無風險率 ${(s.annualRiskFreeRate * 100).toFixed(2)}%｜${result.evaluation === 'fixed-holdout' ? '固定樣本外' : '樣本內'}｜截止 ${result.asOf || '無資料'}｜已平倉 ${result.count} 筆、未平倉 ${result.openPosition ? 1 : 0} 筆、待成交 ${result.pendingOrder ? 1 : 0} 筆、資料提醒 ${result.issues.length} 項。未平倉損益計入總報酬，不列勝率。${sharpeNote}${signalNote}`;
  }

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
  function portfolio(perSymCurves, weights, markets = {}) {
    // perSymCurves: {sym: [{time,equity}]}; weights: {sym: w} (預設等權)
    if (!markets || typeof markets !== 'object' || Array.isArray(markets)) throw new Error('組合市場對照必須是每檔 TW／US 的物件');
    const syms = Object.keys(perSymCurves);
    if (!syms.length) return null;
    const w = weights || Object.fromEntries(syms.map(s => [s, 1 / syms.length]));
    if (syms.some(s => !Number.isFinite(w[s]) || w[s] < 0) || Math.abs(syms.reduce((n, s) => n + w[s], 0) - 1) > 1e-8)
      throw new Error('組合權重須為非負數且合計為 1');
    const points = Object.fromEntries(syms.map(s => [s, perSymCurves[s].map(p => {
      let date;
      if (p.date != null) {
        if (typeof p.date !== 'string') throw new Error('組合曲線 date 必須是明確交易日');
        date = dateKey(p.date);
      } else if (typeof p.time === 'number') {
        if (!['TW', 'US'].includes(markets[s])) throw new Error(`組合曲線 ${s} 缺交易日與市場，無法判定時間戳日期；請提供 date 或 markets[標的]`);
        date = dateKey(p.time, markets[s]);
      } else date = dateKey(p.time); // 日期字串／BusinessDay 本身沒有時區歧義。
      return { ...p, date };
    })]));
    const allTimes = [...new Set(syms.flatMap(s => points[s].map(p => p.date)))].sort();
    if (!allTimes.length) return null;
    const last = {}; syms.forEach(s => last[s] = 1);
    const curve = allTimes.map(t => {
      syms.forEach(s => {
        const pt = points[s].filter(p => p.date <= t).pop();
        if (pt) last[s] = pt.equity;
      });
      const eq = syms.reduce((sum, s) => sum + w[s] * last[s], 0);
      return { time: t, date: t, equity: eq };
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
    const x = i => i / Math.max(1, curve.length - 1) * (W - 8) + 4;
    const y = v => H - 4 - (v - lo) / (hi - lo || 1) * (H - 8);
    // baseline equity=1
    ctx.strokeStyle = 'rgba(148,163,184,.3)'; ctx.beginPath();
    ctx.moveTo(4, y(1)); ctx.lineTo(W - 4, y(1)); ctx.stroke();
    ctx.strokeStyle = color || '#34d399'; ctx.lineWidth = 1.5; ctx.beginPath();
    curve.forEach((p, i) => { const px = x(i), py = y(p.equity); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke();
  }

  window.Backtest = {
    run, runLS, scanStrategies, evaluateStrategies, patternHitRate, portfolio, drawCurve,
    ENGINE_VERSION, DEFAULTS, LIMITATIONS, settings, dateKey, describe, describeIssue, describeSignalIssues,
    STRATEGIES, sma, rsi, bbLower, colsOf, crossUp, breakout,
  };
})();

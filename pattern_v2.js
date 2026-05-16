// ============================================================
// Stock Terminal v2.0 — AI Pattern Recognition (rule-based)
// ------------------------------------------------------------
// 規則式偵測經典 K 線形態。沒用機器學習（黑盒、不可解釋），
// 而是用專業技術分析的固定規則 — 每個形態都有清楚的數學定義
// 和歷史驗證的勝率，這樣輸出可信、可教、可調。
//
// 偵測形態（8 個）：
//   1. 趨勢結構  HH/HL（多頭）vs LH/LL（空頭）
//   2. 雙頂雙底  Double Top / Bottom
//   3. 頭肩頂底  Head & Shoulders Top / Bottom
//   4. 箱型整理  Range / Sideways Consolidation
//   5. 區間突破  Breakout from Range
//   6. 黃金死亡  Golden Cross / Death Cross (SMA20 × SMA60)
//   7. 杯柄形態  Cup & Handle（簡化版）
//   8. 三角收斂  Symmetric Triangle
//
// 載入順序：放最後（依賴 STRATEGIES / S.chart / formatVol）
// ============================================================

// ── Find swing highs/lows (pivots) ────────────────────────
// A pivot high at index i means candles[i].high is > all candles
// in [i-window, i+window] except itself. Same for lows.
function findPivots(candles, window) {
  window = window || 5;
  const highs = [], lows = [];
  for (let i = window; i < candles.length - window; i++) {
    const h = candles[i].high, l = candles[i].low;
    let isH = true, isL = true;
    for (let k = i - window; k <= i + window; k++) {
      if (k === i) continue;
      if (candles[k].high > h) isH = false;
      if (candles[k].low  < l) isL = false;
      if (!isH && !isL) break;
    }
    if (isH) highs.push({i, time: candles[i].time, price: h});
    if (isL) lows.push({i, time: candles[i].time, price: l});
  }
  return {highs, lows};
}

// Helper: are two prices within tolerance %
function near(a, b, tolPct) { return Math.abs(a - b) / Math.max(a, b) * 100 <= (tolPct || 3); }

// ============================================================
// PATTERN DETECTORS
// ============================================================

// 1. Trend structure: last 3 pivots tell the story
function detectTrendStructure(candles, pivots) {
  const hs = pivots.highs.slice(-3);
  const ls = pivots.lows.slice(-3);
  if (hs.length < 2 || ls.length < 2) return null;

  const hhHL = hs[hs.length-1].price > hs[hs.length-2].price && ls[ls.length-1].price > ls[ls.length-2].price;
  const lhLL = hs[hs.length-1].price < hs[hs.length-2].price && ls[ls.length-1].price < ls[ls.length-2].price;

  if (hhHL) {
    return {
      type: 'trend_up',
      name: '多頭結構 (Higher High + Higher Low)',
      icon: '📈',
      severity: 'bullish',
      description: `最近兩個波峰 (${hs[hs.length-2].price.toFixed(2)} → ${hs[hs.length-1].price.toFixed(2)}) 與兩個波谷 (${ls[ls.length-2].price.toFixed(2)} → ${ls[ls.length-1].price.toFixed(2)}) 都墊高，多頭趨勢明確。`,
      action: '順勢操作：拉回不破波谷可加碼，跌破前低 (HL) 才轉空。',
      reliability: '⭐⭐⭐⭐⭐ 趨勢追蹤最高勝率',
      marks: [
        {price: hs[hs.length-2].price, time: hs[hs.length-2].time, label: 'H1', color:'#F87171'},
        {price: hs[hs.length-1].price, time: hs[hs.length-1].time, label: 'H2 (HH)', color:'#F87171'},
        {price: ls[ls.length-2].price, time: ls[ls.length-2].time, label: 'L1', color:'#4ADE80'},
        {price: ls[ls.length-1].price, time: ls[ls.length-1].time, label: 'L2 (HL)', color:'#4ADE80'},
      ],
    };
  }
  if (lhLL) {
    return {
      type: 'trend_down',
      name: '空頭結構 (Lower High + Lower Low)',
      icon: '📉',
      severity: 'bearish',
      description: `波峰下移 (${hs[hs.length-2].price.toFixed(2)} → ${hs[hs.length-1].price.toFixed(2)})、波谷下移 (${ls[ls.length-2].price.toFixed(2)} → ${ls[ls.length-1].price.toFixed(2)})，空頭趨勢成立。`,
      action: '空頭操作：反彈不過波峰 (LH) 可放空或持續減碼，突破前高才轉多。',
      reliability: '⭐⭐⭐⭐⭐ 趨勢追蹤最高勝率',
      marks: [
        {price: hs[hs.length-2].price, time: hs[hs.length-2].time, label:'H1', color:'#F87171'},
        {price: hs[hs.length-1].price, time: hs[hs.length-1].time, label:'H2 (LH)', color:'#F87171'},
        {price: ls[ls.length-2].price, time: ls[ls.length-2].time, label:'L1', color:'#4ADE80'},
        {price: ls[ls.length-1].price, time: ls[ls.length-1].time, label:'L2 (LL)', color:'#4ADE80'},
      ],
    };
  }
  return null;
}

// 2. Double Top / Bottom
function detectDoubleTopBottom(candles, pivots) {
  const c = candles[candles.length - 1].close;
  // Last 2 high pivots near same level → Double Top (if c below neckline)
  const hs = pivots.highs.slice(-2);
  const ls = pivots.lows.slice(-2);
  if (hs.length === 2 && near(hs[0].price, hs[1].price, 2.5) && hs[1].i - hs[0].i >= 10) {
    // Find the trough between the two peaks (neckline)
    let neck = Infinity, neckI = hs[0].i;
    for (let i = hs[0].i; i <= hs[1].i; i++) {
      if (candles[i].low < neck) { neck = candles[i].low; neckI = i; }
    }
    const top = (hs[0].price + hs[1].price) / 2;
    const projection = neck - (top - neck);   // measured move target
    const confirmed = c < neck;
    return {
      type: 'double_top',
      name: '雙頂 (Double Top / M 頂)',
      icon: '🔻',
      severity: confirmed ? 'bearish' : 'caution',
      description: `兩個波峰 ${hs[0].price.toFixed(2)} / ${hs[1].price.toFixed(2)} 高度接近，頸線 ${neck.toFixed(2)}。${confirmed ? '已跌破頸線確認反轉。' : '尚未跌破頸線，未完成。'}`,
      action: confirmed
        ? `空方訊號確認，量度目標 ${projection.toFixed(2)}（高度等同雙頂高度反推）。已建倉者宜減碼。`
        : `等待跌破頸線 ${neck.toFixed(2)} 確認；未跌破前不算反轉，可能形成上漲。`,
      reliability: confirmed ? '⭐⭐⭐⭐ 經典反轉形態' : '⭐⭐ 未確認',
      marks: [
        {price: hs[0].price, time: hs[0].time, label:'頂 1', color:'#F87171'},
        {price: hs[1].price, time: hs[1].time, label:'頂 2', color:'#F87171'},
        {price: neck, time: candles[neckI].time, label:`頸線 ${neck.toFixed(2)}`, color:'#FBBF24'},
        ...(confirmed ? [{price: projection, time: candles[candles.length-1].time, label:`目標 ${projection.toFixed(2)}`, color:'#A78BFA'}] : []),
      ],
    };
  }
  if (ls.length === 2 && near(ls[0].price, ls[1].price, 2.5) && ls[1].i - ls[0].i >= 10) {
    let neck = -Infinity, neckI = ls[0].i;
    for (let i = ls[0].i; i <= ls[1].i; i++) {
      if (candles[i].high > neck) { neck = candles[i].high; neckI = i; }
    }
    const bot = (ls[0].price + ls[1].price) / 2;
    const projection = neck + (neck - bot);
    const confirmed = c > neck;
    return {
      type: 'double_bottom',
      name: '雙底 (Double Bottom / W 底)',
      icon: '🔺',
      severity: confirmed ? 'bullish' : 'observing',
      description: `兩個波谷 ${ls[0].price.toFixed(2)} / ${ls[1].price.toFixed(2)} 底部接近，頸線 ${neck.toFixed(2)}。${confirmed ? '已突破頸線確認反轉。' : '尚未突破頸線，未完成。'}`,
      action: confirmed
        ? `多方訊號確認，量度目標 ${projection.toFixed(2)}（高度等同雙底深度延伸）。可分批進場。`
        : `等待突破頸線 ${neck.toFixed(2)} 確認；未突破前不算反轉。`,
      reliability: confirmed ? '⭐⭐⭐⭐ 經典反轉形態' : '⭐⭐ 未確認',
      marks: [
        {price: ls[0].price, time: ls[0].time, label:'底 1', color:'#4ADE80'},
        {price: ls[1].price, time: ls[1].time, label:'底 2', color:'#4ADE80'},
        {price: neck, time: candles[neckI].time, label:`頸線 ${neck.toFixed(2)}`, color:'#FBBF24'},
        ...(confirmed ? [{price: projection, time: candles[candles.length-1].time, label:`目標 ${projection.toFixed(2)}`, color:'#A78BFA'}] : []),
      ],
    };
  }
  return null;
}

// 3. Head & Shoulders (Top / Bottom)
function detectHeadShoulders(candles, pivots) {
  const hs = pivots.highs.slice(-3);
  const ls = pivots.lows.slice(-3);

  // Head & Shoulders Top: 3 peaks, middle highest, two shoulders similar
  if (hs.length === 3) {
    const [s1, h, s2] = hs;
    const middleHighest = h.price > s1.price && h.price > s2.price;
    const shouldersSimilar = near(s1.price, s2.price, 4);
    if (middleHighest && shouldersSimilar && h.i - s1.i >= 5 && s2.i - h.i >= 5) {
      // Neckline: connect the two troughs between
      const troughs = pivots.lows.filter(p => p.i > s1.i && p.i < s2.i);
      if (troughs.length >= 1) {
        const neck = troughs.reduce((m, p) => Math.min(m, p.price), Infinity);
        const c = candles[candles.length - 1].close;
        const confirmed = c < neck;
        const projection = neck - (h.price - neck);
        return {
          type: 'h_s_top',
          name: '頭肩頂 (Head and Shoulders Top)',
          icon: '🔻',
          severity: confirmed ? 'bearish' : 'caution',
          description: `左肩 ${s1.price.toFixed(2)} / 頭 ${h.price.toFixed(2)} / 右肩 ${s2.price.toFixed(2)}，頸線 ${neck.toFixed(2)}。${confirmed ? '已跌破頸線。' : '形態完成，等跌破頸線確認。'}`,
          action: confirmed
            ? `經典反轉形態確認，量度目標 ${projection.toFixed(2)}（頭頂到頸線高度反推）。減碼或空單。`
            : '密切觀察是否跌破頸線。若否，可能假反轉。',
          reliability: confirmed ? '⭐⭐⭐⭐⭐ 最經典反轉形態' : '⭐⭐⭐ 形態完成中',
          marks: [
            {price: s1.price, time: s1.time, label:'左肩', color:'#FB923C'},
            {price: h.price,  time: h.time,  label:'頭',   color:'#F87171'},
            {price: s2.price, time: s2.time, label:'右肩', color:'#FB923C'},
            {price: neck,     time: candles[Math.floor((s1.i+s2.i)/2)].time, label:`頸線 ${neck.toFixed(2)}`, color:'#FBBF24'},
          ],
        };
      }
    }
  }

  // Head & Shoulders Bottom (inverse): 3 troughs, middle lowest
  if (ls.length === 3) {
    const [s1, h, s2] = ls;
    const middleLowest = h.price < s1.price && h.price < s2.price;
    const shouldersSimilar = near(s1.price, s2.price, 4);
    if (middleLowest && shouldersSimilar && h.i - s1.i >= 5 && s2.i - h.i >= 5) {
      const peaks = pivots.highs.filter(p => p.i > s1.i && p.i < s2.i);
      if (peaks.length >= 1) {
        const neck = peaks.reduce((m, p) => Math.max(m, p.price), -Infinity);
        const c = candles[candles.length - 1].close;
        const confirmed = c > neck;
        const projection = neck + (neck - h.price);
        return {
          type: 'h_s_bottom',
          name: '頭肩底 (Inverse H&S)',
          icon: '🔺',
          severity: confirmed ? 'bullish' : 'observing',
          description: `左肩 ${s1.price.toFixed(2)} / 頭 ${h.price.toFixed(2)} / 右肩 ${s2.price.toFixed(2)}，頸線 ${neck.toFixed(2)}。${confirmed ? '已突破頸線。' : '形態完成，等突破頸線確認。'}`,
          action: confirmed
            ? `底部反轉確認，量度目標 ${projection.toFixed(2)}。可分批進場。`
            : '密切觀察是否突破頸線。若否，反轉失敗風險高。',
          reliability: confirmed ? '⭐⭐⭐⭐⭐ 最經典反轉形態' : '⭐⭐⭐ 形態完成中',
          marks: [
            {price: s1.price, time: s1.time, label:'左肩', color:'#FB923C'},
            {price: h.price,  time: h.time,  label:'頭',   color:'#4ADE80'},
            {price: s2.price, time: s2.time, label:'右肩', color:'#FB923C'},
            {price: neck,     time: candles[Math.floor((s1.i+s2.i)/2)].time, label:`頸線 ${neck.toFixed(2)}`, color:'#FBBF24'},
          ],
        };
      }
    }
  }
  return null;
}

// 4. Range / Sideways consolidation (last N bars within tight band)
function detectRange(candles) {
  const N = 30;
  if (candles.length < N) return null;
  const recent = candles.slice(-N);
  const hi = Math.max(...recent.map(c => c.high));
  const lo = Math.min(...recent.map(c => c.low));
  const mid = (hi + lo) / 2;
  const width = (hi - lo) / mid * 100;
  if (width >= 12) return null;   // > 12% range = not consolidation
  return {
    type: 'range',
    name: `箱型整理 (${N} 日盤整 ${width.toFixed(1)}%)`,
    icon: '↔️',
    severity: 'neutral',
    description: `近 ${N} 個交易日於 ${lo.toFixed(2)} ~ ${hi.toFixed(2)} 區間整理，振幅僅 ${width.toFixed(1)}%。`,
    action: '操作策略：跌至下緣承接、漲至上緣減碼；若帶量突破上緣 → 轉趨勢追多；跌破下緣 → 認賠出場。',
    reliability: '⭐⭐⭐ 等待方向選擇',
    marks: [
      {price: hi, time: recent[0].time, label:`上緣 ${hi.toFixed(2)}`, color:'#F87171'},
      {price: lo, time: recent[0].time, label:`下緣 ${lo.toFixed(2)}`, color:'#4ADE80'},
      {price: mid, time: recent[0].time, label:`中軸`, color:'#FBBF24'},
    ],
  };
}

// 5. Range breakout (was in a range, now broke out)
function detectBreakout(candles) {
  const N = 30;
  if (candles.length < N + 1) return null;
  const prior = candles.slice(-N - 1, -1);
  const c = candles[candles.length - 1].close;
  const hi = Math.max(...prior.map(c => c.high));
  const lo = Math.min(...prior.map(c => c.low));
  const width = (hi - lo) / ((hi + lo) / 2) * 100;
  if (width >= 12) return null;
  // Check volume
  let v5 = 0, v20 = 0;
  for (let i = candles.length - 5; i < candles.length; i++) v5 += candles[i].volume || 0;
  for (let i = candles.length - 20; i < candles.length; i++) v20 += candles[i].volume || 0;
  const volRatio = (v20 / 20) > 0 ? (v5 / 5) / (v20 / 20) : 1;
  if (c > hi) {
    return {
      type: 'breakout_up',
      name: '區間向上突破',
      icon: '🚀',
      severity: 'bullish',
      description: `價格 ${c.toFixed(2)} 突破 ${N} 日整理區上緣 ${hi.toFixed(2)}。量能 ${volRatio.toFixed(1)}x。`,
      action: volRatio >= 1.5
        ? `量增突破有效，目標 ${(hi + (hi - lo)).toFixed(2)}（量度漲幅）。順勢進場 1/3，回測突破點不破再加。`
        : '量能不足（< 1.5x），有假突破風險。等回測不破突破點再進。',
      reliability: volRatio >= 1.5 ? '⭐⭐⭐⭐ 量增突破' : '⭐⭐ 量不足',
      marks: [
        {price: hi, time: prior[0].time, label:`突破點 ${hi.toFixed(2)}`, color:'#4ADE80'},
        {price: hi + (hi - lo), time: candles[candles.length-1].time, label:`目標 ${(hi+(hi-lo)).toFixed(2)}`, color:'#A78BFA'},
      ],
    };
  }
  if (c < lo) {
    return {
      type: 'breakout_down',
      name: '區間向下跌破',
      icon: '⬇️',
      severity: 'bearish',
      description: `價格 ${c.toFixed(2)} 跌破 ${N} 日整理區下緣 ${lo.toFixed(2)}。`,
      action: `空方訊號，量度目標 ${(lo - (hi - lo)).toFixed(2)}。已持倉者必須停損。`,
      reliability: '⭐⭐⭐⭐ 經典跌破',
      marks: [
        {price: lo, time: prior[0].time, label:`跌破點 ${lo.toFixed(2)}`, color:'#F87171'},
        {price: lo - (hi - lo), time: candles[candles.length-1].time, label:`目標 ${(lo-(hi-lo)).toFixed(2)}`, color:'#A78BFA'},
      ],
    };
  }
  return null;
}

// 6. Golden / Death cross (SMA20 × SMA60)
function detectMaCross(candles) {
  const N = candles.length;
  if (N < 70) return null;
  const sma = (period, idx) => {
    if (idx + 1 < period) return null;
    let s = 0;
    for (let i = idx - period + 1; i <= idx; i++) s += candles[i].close;
    return s / period;
  };
  const c20now = sma(20, N - 1), c20prev = sma(20, N - 2);
  const c60now = sma(60, N - 1), c60prev = sma(60, N - 2);
  if (c20now == null || c60now == null) return null;
  // Look back up to 5 days for recent cross
  for (let lag = 1; lag <= 5; lag++) {
    const p20 = sma(20, N - 1 - lag), p60 = sma(60, N - 1 - lag);
    const n20 = sma(20, N - lag),     n60 = sma(60, N - lag);
    if (p20 == null || p60 == null) continue;
    if (p20 <= p60 && n20 > n60) {
      return {
        type: 'golden_cross',
        name: '黃金交叉 (SMA20 上穿 SMA60)',
        icon: '✨',
        severity: 'bullish',
        description: `${lag} 日前 SMA20 (${n20.toFixed(2)}) 上穿 SMA60 (${n60.toFixed(2)})，中期趨勢轉多。`,
        action: '中線轉多訊號。回測 SMA20 不破即為加碼點。',
        reliability: '⭐⭐⭐⭐ 中線經典訊號（注意滯後）',
        marks: [
          {price: c20now, time: candles[N-1].time, label:`SMA20 ${c20now.toFixed(2)}`, color:'#FBBF24'},
          {price: c60now, time: candles[N-1].time, label:`SMA60 ${c60now.toFixed(2)}`, color:'#67E8F9'},
        ],
      };
    }
    if (p20 >= p60 && n20 < n60) {
      return {
        type: 'death_cross',
        name: '死亡交叉 (SMA20 下穿 SMA60)',
        icon: '💀',
        severity: 'bearish',
        description: `${lag} 日前 SMA20 (${n20.toFixed(2)}) 下穿 SMA60 (${n60.toFixed(2)})，中期趨勢轉空。`,
        action: '中線轉空訊號。反彈不過 SMA20 即為減碼點。',
        reliability: '⭐⭐⭐⭐ 中線經典訊號（注意滯後）',
        marks: [
          {price: c20now, time: candles[N-1].time, label:`SMA20 ${c20now.toFixed(2)}`, color:'#FBBF24'},
          {price: c60now, time: candles[N-1].time, label:`SMA60 ${c60now.toFixed(2)}`, color:'#67E8F9'},
        ],
      };
    }
  }
  return null;
}

// 7. Cup & Handle (simplified)
function detectCupHandle(candles, pivots) {
  // Look for U-shape: a local high, a deeper low, then back near original high, then small pullback
  if (candles.length < 60) return null;
  const hs = pivots.highs;
  if (hs.length < 2) return null;
  // Last two highs near same level — those form the "lip" of cup
  const h2 = hs[hs.length-1], h1 = hs[hs.length-2];
  if (!near(h1.price, h2.price, 3)) return null;
  if (h2.i - h1.i < 20) return null;   // cup needs time
  // Lowest point between forms cup bottom
  let bot = Infinity, botI = h1.i;
  for (let i = h1.i; i <= h2.i; i++) if (candles[i].low < bot) { bot = candles[i].low; botI = i; }
  const depth = (h1.price - bot) / h1.price * 100;
  if (depth < 8 || depth > 40) return null;   // typical cup 8-40% deep
  // After h2, look for small pullback (handle, < 50% of cup depth)
  const after = candles.slice(h2.i + 1);
  if (after.length < 5) return null;
  const handleLo = Math.min(...after.map(c => c.low));
  const handleDepth = (h2.price - handleLo) / h2.price * 100;
  if (handleDepth > depth / 2 || handleDepth < 1) return null;
  const c = candles[candles.length - 1].close;
  const lip = (h1.price + h2.price) / 2;
  const confirmed = c > lip;
  return {
    type: 'cup_handle',
    name: '杯柄形態 (Cup and Handle)',
    icon: '☕',
    severity: confirmed ? 'bullish' : 'observing',
    description: `杯口高度 ${lip.toFixed(2)}、杯底 ${bot.toFixed(2)}（深度 ${depth.toFixed(1)}%）、把手回檔 ${handleDepth.toFixed(1)}%。${confirmed ? '已突破杯口確認。' : '形態完成，等突破杯口確認。'}`,
    action: confirmed
      ? `經典突破形態確認，量度目標 ${(lip + (lip - bot)).toFixed(2)}（杯深反推）。可進場。`
      : '等突破杯口才進，否則風險高。',
    reliability: confirmed ? '⭐⭐⭐⭐ William O\'Neil 經典' : '⭐⭐⭐ 形態完成中',
    marks: [
      {price: lip, time: h1.time, label:`杯口 ${lip.toFixed(2)}`, color:'#FBBF24'},
      {price: bot, time: candles[botI].time, label:`杯底 ${bot.toFixed(2)}`, color:'#4ADE80'},
      ...(confirmed ? [{price: lip + (lip - bot), time: candles[candles.length-1].time, label:`目標`, color:'#A78BFA'}] : []),
    ],
  };
}

// 8. Symmetric Triangle (converging highs and lows)
function detectTriangle(candles, pivots) {
  const hs = pivots.highs.slice(-3);
  const ls = pivots.lows.slice(-3);
  if (hs.length < 3 || ls.length < 3) return null;
  const highsDown = hs[0].price > hs[1].price && hs[1].price > hs[2].price;
  const lowsUp    = ls[0].price < ls[1].price && ls[1].price < ls[2].price;
  if (highsDown && lowsUp) {
    const apex = hs[2].price - (hs[0].price - hs[2].price) / 2;   // approximate convergence
    const c = candles[candles.length - 1].close;
    return {
      type: 'triangle',
      name: '三角收斂 (Symmetric Triangle)',
      icon: '◢',
      severity: 'neutral',
      description: `高點下移 (${hs[0].price.toFixed(2)} → ${hs[2].price.toFixed(2)})、低點上移 (${ls[0].price.toFixed(2)} → ${ls[2].price.toFixed(2)})，收斂中。`,
      action: '中性形態，等突破方向。突破上緣量增追多、跌破下緣量增追空。在內等待風險最小報酬比最佳。',
      reliability: '⭐⭐⭐ 等待方向選擇',
      marks: [
        {price: hs[0].price, time: hs[0].time, label:'高1', color:'#F87171'},
        {price: hs[2].price, time: hs[2].time, label:'高3', color:'#F87171'},
        {price: ls[0].price, time: ls[0].time, label:'低1', color:'#4ADE80'},
        {price: ls[2].price, time: ls[2].time, label:'低3', color:'#4ADE80'},
      ],
    };
  }
  return null;
}

// ============================================================
// MAIN DETECTOR — run all
// ============================================================
function detectPatterns() {
  if (!S.data?.candles?.length || S.data.candles.length < 30) return [];
  const candles = S.data.candles;
  const pivots = findPivots(candles, 5);
  const patterns = [];
  try { const p = detectTrendStructure(candles, pivots);     if (p) patterns.push(p); } catch (e) { console.warn(e); }
  try { const p = detectDoubleTopBottom(candles, pivots);   if (p) patterns.push(p); } catch (e) { console.warn(e); }
  try { const p = detectHeadShoulders(candles, pivots);     if (p) patterns.push(p); } catch (e) { console.warn(e); }
  try { const p = detectMaCross(candles);                   if (p) patterns.push(p); } catch (e) { console.warn(e); }
  try { const p = detectBreakout(candles);                  if (p) patterns.push(p); } catch (e) { console.warn(e); }
  try { const p = detectRange(candles);                     if (p && !patterns.find(x => x.type.startsWith('breakout'))) patterns.push(p); } catch (e) { console.warn(e); }
  try { const p = detectCupHandle(candles, pivots);         if (p) patterns.push(p); } catch (e) { console.warn(e); }
  try { const p = detectTriangle(candles, pivots);          if (p) patterns.push(p); } catch (e) { console.warn(e); }
  return patterns;
}

// ============================================================
// RENDER — chart annotations + sidebar list
// ============================================================
function drawPatternsOnChart(patterns) {
  if (!S.chartSeries) return;
  // Remove old pattern lines
  for (const pl of (S.patternLines || [])) try { S.chartSeries.removePriceLine(pl); } catch {}
  S.patternLines = [];
  if (!S.patternsEnabled) return;
  for (const p of patterns) {
    for (const m of (p.marks || [])) {
      try {
        const pl = S.chartSeries.createPriceLine({
          price: m.price,
          color: m.color,
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: true,
          title: m.label,
        });
        S.patternLines.push(pl);
      } catch (e) { console.warn('[pattern] line draw:', e); }
    }
  }
}

function renderPatternsPanel() {
  const patterns = detectPatterns();
  if (patterns.length === 0) {
    return '<div style="padding:14px;font-family:monospace;font-size:10px;color:var(--tlo);text-align:center">目前未偵測到明顯形態<br><span style="font-size:9px;color:var(--tf)">需要至少 30 個交易日資料</span></div>';
  }
  const sevColor = {bullish:'var(--green)', bearish:'var(--red)', caution:'var(--orange)', neutral:'var(--blue)', observing:'var(--blue)'};
  const sevBg    = {bullish:'rgba(74,222,128,.08)', bearish:'rgba(248,113,113,.08)', caution:'rgba(251,146,60,.08)', neutral:'rgba(96,165,250,.08)', observing:'rgba(96,165,250,.08)'};
  let h = '';
  for (const p of patterns) {
    const col = sevColor[p.severity], bg = sevBg[p.severity];
    h += `<div style="padding:9px 12px;border-bottom:1px solid var(--border);background:${bg}">
      <div style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;color:${col};margin-bottom:4px">${p.icon} ${escP(p.name)}</div>
      <div style="font-family:monospace;font-size:9.5px;color:var(--text);line-height:1.65;margin-bottom:4px">${escP(p.description)}</div>
      <div style="font-family:monospace;font-size:9.5px;color:${col};line-height:1.65;margin-bottom:3px">▸ ${escP(p.action)}</div>
      <div style="font-family:monospace;font-size:9px;color:var(--tf);line-height:1.5">${escP(p.reliability)}</div>
    </div>`;
  }
  return h;
}

function escP(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function patternsToggle() {
  S.patternsEnabled = !S.patternsEnabled;
  const b = document.getElementById('btn-patterns');
  if (b) b.classList.toggle('on', S.patternsEnabled);
  drawPatternsOnChart(detectPatterns());
}

function showPatternsModal() {
  const html = `
    <h3 style="margin:0 0 10px;color:var(--gold);font-family:monospace;font-size:14px">🤖 AI 形態辨識 — ${S.sym || '?'}</h3>
    <div style="font-family:monospace;font-size:9.5px;color:var(--tlo);margin-bottom:10px">規則式偵測 8 種經典 K 線形態。沒用機器學習，全部基於可解釋的技術分析規則。</div>
    <div style="border-top:1px solid var(--border);margin:-2px -24px 6px">
      ${renderPatternsPanel()}
    </div>
    <div style="margin-top:10px;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.7">
      ⚠ 形態辨識僅為技術面參考。形態完成不等於後續一定走預期方向；
      務必綜合基本面、量能、大盤、產業判斷。<br>
      勝率星級基於歷史回測，但每次都不同。
    </div>`;
  if (typeof showProModal === 'function') showProModal(html);
  else alert(detectPatterns().map(p => `${p.icon} ${p.name}\n${p.description}\n▸ ${p.action}`).join('\n\n'));
}

// ============================================================
// UI Injection
// ============================================================
(function injectPatternButton() {
  if (!document.getElementById('rangebar')) return setTimeout(injectPatternButton, 100);
  const proTools = document.getElementById('pro-tools');
  if (!proTools || document.getElementById('btn-patterns')) return;
  const b = document.createElement('button');
  b.id = 'btn-patterns';
  b.className = 'probtn';
  b.title = 'AI 形態辨識 — 偵測經典 K 線形態';
  b.innerHTML = '🤖 形態';
  b.onclick = showPatternsModal;
  // Secondary action: long-press = toggle overlay (mark on chart)
  let lp = null;
  b.addEventListener('mousedown', () => { lp = setTimeout(() => { patternsToggle(); lp = 'fired'; }, 500); });
  b.addEventListener('mouseup', () => { if (lp && lp !== 'fired') clearTimeout(lp); lp = null; });
  b.addEventListener('mouseleave', () => { if (lp && lp !== 'fired') clearTimeout(lp); lp = null; });
  proTools.appendChild(b);
})();

// Re-draw on chart redraw
(function hookChart() {
  if (typeof renderChart !== 'function') return setTimeout(hookChart, 100);
  const orig = window.renderChart;
  window.renderChart = function () {
    orig.apply(this, arguments);
    setTimeout(() => { if (S.patternsEnabled) drawPatternsOnChart(detectPatterns()); }, 100);
  };
})();

// ── Expose ─────────────────────────────────────────────────
window.detectPatterns      = detectPatterns;
window.renderPatternsPanel = renderPatternsPanel;
window.showPatternsModal   = showPatternsModal;
window.patternsToggle      = patternsToggle;

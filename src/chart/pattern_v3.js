// ============================================================
// Stock Terminal v3.0 — Advanced Chart Pattern Recognition
// ------------------------------------------------------------
// v3 = v2 (8 patterns) + 11 TradingView-grade patterns:
//   • XABCD 諧波  Gartley / Bat / Butterfly / Crab / Shark
//   • 賽福形態    Cypher
//   • ABCD 形態   AB=CD (Fib 0.618 / 0.786 retrace)
//   • 三角形態    Symmetric / Ascending / Descending Triangle
//   • 三驅形態    Three Drives (1.272 / 1.618 ext)
//   • 艾略特脈衝波 1-2-3-4-5  (with 3 hard rules)
//   • 艾略特修正浪 A-B-C       (Zigzag / Flat / Irregular)
//   • 艾略特三角波 A-B-C-D-E
//   • 艾略特雙重組合浪 W-X-Y
//   • 艾略特三重組合浪 W-X-Y-X-Z
//   • 循環分析    FFT / 自相關週期偵測
//
// 規則式偵測，無 ML，每個形態都有明確數學定義。
//
// 載入順序：放最後（依賴 STRATEGIES / S.chart / formatVol / parseYF）
// ============================================================

(function () {
'use strict';

// ============================================================
// CONSTANTS
// ============================================================
const FIB = {
  R236: 0.236, R382: 0.382, R500: 0.500, R618: 0.618, R707: 0.707,
  R786: 0.786, R886: 0.886,
  E1272: 1.272, E1414: 1.414, E1618: 1.618, E2000: 2.000, E2240: 2.240,
  E2618: 2.618, E3618: 3.618,
};

// 配色（沿用 v2）
const COL = {
  bull: '#4ADE80', bear: '#F87171', neut: '#60A5FA',
  warn: '#FBBF24', accent: '#A78BFA', muted: '#94A3B8',
  shoulder: '#FB923C', cyan: '#67E8F9', x: '#E879F9',
};

// 容差設定（百分比 — Fib 比對用）
const TOL = {
  fib_loose: 0.08,   // ±8%  寬鬆（給長時間 K 線）
  fib_tight: 0.05,   // ±5%  標準
  fib_strict: 0.03,  // ±3%  嚴格（諧波形態）
  level: 3.0,        // 兩價位「相近」的容差
};

// ============================================================
// UTILS
// ============================================================
function near(a, b, tolPct) { return Math.abs(a - b) / Math.max(Math.abs(a), Math.abs(b), 1e-9) * 100 <= (tolPct || 3); }
function inRange(v, lo, hi, tol) { tol = tol || 0; return v >= lo * (1 - tol) && v <= hi * (1 + tol); }
function fibMatch(actual, target, tol) { tol = tol || TOL.fib_tight; return Math.abs(actual - target) <= target * tol; }
function pct(a, b) { return (a - b) / Math.max(Math.abs(b), 1e-9); }
function safeNum(x) { return (typeof x === 'number' && isFinite(x)) ? x : 0; }
function fmt(n, d) { d = d == null ? 2 : d; return safeNum(n).toFixed(d); }

// ============================================================
// CORE: PIVOT / ZIGZAG ENGINE
// ============================================================
// 基本 pivot（v2 沿用，window 預設 5）
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
    if (isH) highs.push({ i, time: candles[i].time, price: h });
    if (isL) lows.push({ i, time: candles[i].time, price: l });
  }
  return { highs, lows };
}

// ZigZag 規範化 — 把 pivots 轉成交替的 swing 序列 (H, L, H, L, ...)
// 每個 swing 都帶 kind: 'H'/'L'，price, i, time
// 同類連續的 pivot 取「更極端」的那個（高的更高、低的更低）
function buildZigZag(candles, pivots) {
  const all = [];
  for (const h of pivots.highs) all.push({ kind: 'H', i: h.i, time: h.time, price: h.price });
  for (const l of pivots.lows)  all.push({ kind: 'L', i: l.i, time: l.time, price: l.price });
  all.sort((a, b) => a.i - b.i);
  if (!all.length) return [];

  const zz = [];
  for (const p of all) {
    if (!zz.length) { zz.push(p); continue; }
    const last = zz[zz.length - 1];
    if (last.kind === p.kind) {
      // 同類 — 取更極端
      if (p.kind === 'H' ? p.price > last.price : p.price < last.price) zz[zz.length - 1] = p;
    } else {
      zz.push(p);
    }
  }
  // 過濾噪音 swing — 兩個相鄰 swing 之間振幅 < 1% 視為雜訊（除非是最後一個）
  const filtered = [];
  for (let i = 0; i < zz.length; i++) {
    const s = zz[i];
    if (filtered.length < 2) { filtered.push(s); continue; }
    const prev = filtered[filtered.length - 1];
    const amp = Math.abs(s.price - prev.price) / Math.max(prev.price, 1e-9);
    if (amp < 0.012 && i < zz.length - 1) continue;  // < 1.2% 雜訊 skip
    filtered.push(s);
  }
  return filtered;
}

// 取最後 n 個 swings — 用於型態匹配
function lastSwings(zz, n) {
  if (zz.length < n) return null;
  return zz.slice(-n);
}

// 在 swing 序列中找所有「依序為 H L H L ...」或「L H L H ...」的子序列
// 回傳所有可能起點（用於 brute-force 找型態）
function enumerateSequences(zz, length, startKind) {
  const out = [];
  for (let i = 0; i + length <= zz.length; i++) {
    let ok = true;
    for (let k = 0; k < length; k++) {
      const expect = (k % 2 === 0) ? startKind : (startKind === 'H' ? 'L' : 'H');
      if (zz[i + k].kind !== expect) { ok = false; break; }
    }
    if (ok) out.push(zz.slice(i, i + length));
  }
  return out;
}

// ============================================================
// PATTERN HELPERS
// ============================================================
function legLen(a, b) { return Math.abs(b.price - a.price); }
function ratioRetrace(A, B, C) { return legLen(B, C) / Math.max(legLen(A, B), 1e-9); }
function ratioExt(A, B, C, D) { return legLen(C, D) / Math.max(legLen(A, B), 1e-9); }

// 用 swing 點生 polyline marks（連線用）— v3 新增
// 回傳 LineSeries 可吃的 [{time, value}]
function pointsToLine(points) {
  return points.map(p => ({ time: p.time, value: p.price }));
}

// ============================================================
// PATTERN: 1. TREND STRUCTURE (v2 保留)
// ============================================================
function detectTrendStructure(candles, pivots) {
  const hs = pivots.highs.slice(-3);
  const ls = pivots.lows.slice(-3);
  if (hs.length < 2 || ls.length < 2) return null;
  const hhHL = hs[hs.length - 1].price > hs[hs.length - 2].price && ls[ls.length - 1].price > ls[ls.length - 2].price;
  const lhLL = hs[hs.length - 1].price < hs[hs.length - 2].price && ls[ls.length - 1].price < ls[ls.length - 2].price;
  if (hhHL) {
    return {
      type: 'trend_up',
      name: '多頭結構 (HH + HL)',
      icon: '📈', severity: 'bullish',
      description: `波峰墊高 ${fmt(hs[hs.length-2].price)} → ${fmt(hs[hs.length-1].price)}、波谷墊高 ${fmt(ls[ls.length-2].price)} → ${fmt(ls[ls.length-1].price)}。`,
      action: '順勢操作：拉回不破波谷加碼，跌破前低 (HL) 才轉空。',
      reliability: '⭐⭐⭐⭐⭐ 趨勢追蹤最高勝率',
      marks: [
        { price: hs[hs.length-2].price, time: hs[hs.length-2].time, label:'H1', color: COL.bear },
        { price: hs[hs.length-1].price, time: hs[hs.length-1].time, label:'H2 (HH)', color: COL.bear },
        { price: ls[ls.length-2].price, time: ls[ls.length-2].time, label:'L1', color: COL.bull },
        { price: ls[ls.length-1].price, time: ls[ls.length-1].time, label:'L2 (HL)', color: COL.bull },
      ],
    };
  }
  if (lhLL) {
    return {
      type: 'trend_down',
      name: '空頭結構 (LH + LL)',
      icon: '📉', severity: 'bearish',
      description: `波峰下移 ${fmt(hs[hs.length-2].price)} → ${fmt(hs[hs.length-1].price)}、波谷下移 ${fmt(ls[ls.length-2].price)} → ${fmt(ls[ls.length-1].price)}。`,
      action: '空頭操作：反彈不過波峰 (LH) 放空或減碼，突破前高才轉多。',
      reliability: '⭐⭐⭐⭐⭐ 趨勢追蹤最高勝率',
      marks: [
        { price: hs[hs.length-2].price, time: hs[hs.length-2].time, label:'H1', color: COL.bear },
        { price: hs[hs.length-1].price, time: hs[hs.length-1].time, label:'H2 (LH)', color: COL.bear },
        { price: ls[ls.length-2].price, time: ls[ls.length-2].time, label:'L1', color: COL.bull },
        { price: ls[ls.length-1].price, time: ls[ls.length-1].time, label:'L2 (LL)', color: COL.bull },
      ],
    };
  }
  return null;
}

// ============================================================
// PATTERN: 2. DOUBLE TOP / BOTTOM (v2 保留)
// ============================================================
function detectDoubleTopBottom(candles, pivots) {
  const c = candles[candles.length - 1].close;
  const hs = pivots.highs.slice(-2);
  const ls = pivots.lows.slice(-2);
  if (hs.length === 2 && near(hs[0].price, hs[1].price, 2.5) && hs[1].i - hs[0].i >= 10) {
    let neck = Infinity, neckI = hs[0].i;
    for (let i = hs[0].i; i <= hs[1].i; i++) if (candles[i].low < neck) { neck = candles[i].low; neckI = i; }
    const top = (hs[0].price + hs[1].price) / 2;
    const projection = neck - (top - neck);
    const confirmed = c < neck;
    return {
      type: 'double_top', name: '雙頂 (M 頂)', icon: '🔻',
      severity: confirmed ? 'bearish' : 'caution',
      description: `兩個波峰 ${fmt(hs[0].price)} / ${fmt(hs[1].price)} 高度接近，頸線 ${fmt(neck)}。${confirmed ? '已跌破頸線。' : '未跌破頸線。'}`,
      action: confirmed ? `空方訊號確認，量度目標 ${fmt(projection)}。` : `等待跌破頸線 ${fmt(neck)} 確認。`,
      reliability: confirmed ? '⭐⭐⭐⭐ 經典反轉' : '⭐⭐ 未確認',
      marks: [
        { price: hs[0].price, time: hs[0].time, label:'頂 1', color: COL.bear },
        { price: hs[1].price, time: hs[1].time, label:'頂 2', color: COL.bear },
        { price: neck, time: candles[neckI].time, label: `頸線 ${fmt(neck)}`, color: COL.warn },
        ...(confirmed ? [{ price: projection, time: candles[candles.length-1].time, label: `目標 ${fmt(projection)}`, color: COL.accent }] : []),
      ],
    };
  }
  if (ls.length === 2 && near(ls[0].price, ls[1].price, 2.5) && ls[1].i - ls[0].i >= 10) {
    let neck = -Infinity, neckI = ls[0].i;
    for (let i = ls[0].i; i <= ls[1].i; i++) if (candles[i].high > neck) { neck = candles[i].high; neckI = i; }
    const bot = (ls[0].price + ls[1].price) / 2;
    const projection = neck + (neck - bot);
    const confirmed = c > neck;
    return {
      type: 'double_bottom', name: '雙底 (W 底)', icon: '🔺',
      severity: confirmed ? 'bullish' : 'observing',
      description: `兩個波谷 ${fmt(ls[0].price)} / ${fmt(ls[1].price)} 底部接近，頸線 ${fmt(neck)}。${confirmed ? '已突破頸線。' : '未突破頸線。'}`,
      action: confirmed ? `多方訊號確認，量度目標 ${fmt(projection)}。` : `等待突破頸線 ${fmt(neck)} 確認。`,
      reliability: confirmed ? '⭐⭐⭐⭐ 經典反轉' : '⭐⭐ 未確認',
      marks: [
        { price: ls[0].price, time: ls[0].time, label:'底 1', color: COL.bull },
        { price: ls[1].price, time: ls[1].time, label:'底 2', color: COL.bull },
        { price: neck, time: candles[neckI].time, label: `頸線 ${fmt(neck)}`, color: COL.warn },
        ...(confirmed ? [{ price: projection, time: candles[candles.length-1].time, label: `目標 ${fmt(projection)}`, color: COL.accent }] : []),
      ],
    };
  }
  return null;
}

// ============================================================
// PATTERN: 3. HEAD & SHOULDERS (v2 升級 — 加 polyline)
// ============================================================
function detectHeadShoulders(candles, pivots) {
  const hs = pivots.highs.slice(-3);
  const ls = pivots.lows.slice(-3);
  // 頭肩頂
  if (hs.length === 3) {
    const [s1, h, s2] = hs;
    const middleHighest = h.price > s1.price && h.price > s2.price;
    const shouldersSimilar = near(s1.price, s2.price, 4);
    if (middleHighest && shouldersSimilar && h.i - s1.i >= 5 && s2.i - h.i >= 5) {
      const troughs = pivots.lows.filter(p => p.i > s1.i && p.i < s2.i);
      if (troughs.length >= 1) {
        // 頸線：取兩個 trough 連線（v3 用真正趨勢線，不是水平線）
        const t1 = troughs[0], t2 = troughs[troughs.length - 1];
        const neckSlope = t2.i === t1.i ? 0 : (t2.price - t1.price) / (t2.i - t1.i);
        const cIdx = candles.length - 1;
        const neckAtNow = t2.price + neckSlope * (cIdx - t2.i);
        const c = candles[cIdx].close;
        const confirmed = c < neckAtNow;
        const projection = neckAtNow - (h.price - neckAtNow);
        return {
          type: 'h_s_top', name: '頭肩頂 (H&S Top)', icon: '🔻',
          severity: confirmed ? 'bearish' : 'caution',
          description: `左肩 ${fmt(s1.price)} / 頭 ${fmt(h.price)} / 右肩 ${fmt(s2.price)}，頸線 ${fmt(neckAtNow)}。${confirmed ? '已跌破頸線。' : '形態完成，等跌破。'}`,
          action: confirmed ? `量度目標 ${fmt(projection)}（頭頂到頸線高度反推）。減碼或空單。` : '密切觀察是否跌破頸線。',
          reliability: confirmed ? '⭐⭐⭐⭐⭐ 最經典反轉' : '⭐⭐⭐ 形態完成中',
          marks: [
            { price: s1.price, time: s1.time, label:'左肩', color: COL.shoulder },
            { price: h.price,  time: h.time,  label:'頭',   color: COL.bear },
            { price: s2.price, time: s2.time, label:'右肩', color: COL.shoulder },
            { price: neckAtNow, time: candles[Math.floor((s1.i+s2.i)/2)].time, label: `頸線 ${fmt(neckAtNow)}`, color: COL.warn },
          ],
          polylines: [
            { points: [s1, t1, h, t2, s2], color: COL.bear, label: 'H&S' },
            { points: [t1, t2], color: COL.warn, label: '頸線', style: 'dashed', extend: true },
          ],
        };
      }
    }
  }
  // 頭肩底
  if (ls.length === 3) {
    const [s1, h, s2] = ls;
    const middleLowest = h.price < s1.price && h.price < s2.price;
    const shouldersSimilar = near(s1.price, s2.price, 4);
    if (middleLowest && shouldersSimilar && h.i - s1.i >= 5 && s2.i - h.i >= 5) {
      const peaks = pivots.highs.filter(p => p.i > s1.i && p.i < s2.i);
      if (peaks.length >= 1) {
        const t1 = peaks[0], t2 = peaks[peaks.length - 1];
        const neckSlope = t2.i === t1.i ? 0 : (t2.price - t1.price) / (t2.i - t1.i);
        const cIdx = candles.length - 1;
        const neckAtNow = t2.price + neckSlope * (cIdx - t2.i);
        const c = candles[cIdx].close;
        const confirmed = c > neckAtNow;
        const projection = neckAtNow + (neckAtNow - h.price);
        return {
          type: 'h_s_bottom', name: '頭肩底 (Inverse H&S)', icon: '🔺',
          severity: confirmed ? 'bullish' : 'observing',
          description: `左肩 ${fmt(s1.price)} / 頭 ${fmt(h.price)} / 右肩 ${fmt(s2.price)}，頸線 ${fmt(neckAtNow)}。${confirmed ? '已突破頸線。' : '形態完成，等突破。'}`,
          action: confirmed ? `量度目標 ${fmt(projection)}。可分批進場。` : '密切觀察是否突破頸線。',
          reliability: confirmed ? '⭐⭐⭐⭐⭐ 最經典反轉' : '⭐⭐⭐ 形態完成中',
          marks: [
            { price: s1.price, time: s1.time, label:'左肩', color: COL.shoulder },
            { price: h.price,  time: h.time,  label:'頭',   color: COL.bull },
            { price: s2.price, time: s2.time, label:'右肩', color: COL.shoulder },
            { price: neckAtNow, time: candles[Math.floor((s1.i+s2.i)/2)].time, label: `頸線 ${fmt(neckAtNow)}`, color: COL.warn },
          ],
          polylines: [
            { points: [s1, t1, h, t2, s2], color: COL.bull, label: 'iH&S' },
            { points: [t1, t2], color: COL.warn, label: '頸線', style: 'dashed', extend: true },
          ],
        };
      }
    }
  }
  return null;
}

// ============================================================
// PATTERN: 4. RANGE / 5. BREAKOUT / 6. MA CROSS / 7. CUP & HANDLE
// (v2 保留 — 邏輯不變)
// ============================================================
function detectRange(candles) {
  const N = 30;
  if (candles.length < N) return null;
  const recent = candles.slice(-N);
  const hi = Math.max(...recent.map(c => c.high));
  const lo = Math.min(...recent.map(c => c.low));
  const mid = (hi + lo) / 2;
  const width = (hi - lo) / mid * 100;
  if (width >= 12) return null;
  return {
    type: 'range', name: `箱型整理 (${N}日 ${fmt(width,1)}%)`, icon: '↔️', severity: 'neutral',
    description: `近 ${N} 個交易日於 ${fmt(lo)} ~ ${fmt(hi)} 區間整理，振幅 ${fmt(width,1)}%。`,
    action: '下緣承接、上緣減碼；帶量突破/跌破則順勢。',
    reliability: '⭐⭐⭐ 等待方向選擇',
    marks: [
      { price: hi, time: recent[0].time, label: `上緣 ${fmt(hi)}`, color: COL.bear },
      { price: lo, time: recent[0].time, label: `下緣 ${fmt(lo)}`, color: COL.bull },
      { price: mid, time: recent[0].time, label: '中軸', color: COL.warn },
    ],
  };
}

function detectBreakout(candles) {
  const N = 30;
  if (candles.length < N + 1) return null;
  const prior = candles.slice(-N - 1, -1);
  const c = candles[candles.length - 1].close;
  const hi = Math.max(...prior.map(c => c.high));
  const lo = Math.min(...prior.map(c => c.low));
  const width = (hi - lo) / ((hi + lo) / 2) * 100;
  if (width >= 12) return null;
  let v5 = 0, v20 = 0;
  for (let i = candles.length - 5; i < candles.length; i++) v5 += candles[i].volume || 0;
  for (let i = candles.length - 20; i < candles.length; i++) v20 += candles[i].volume || 0;
  const volRatio = (v20 / 20) > 0 ? (v5 / 5) / (v20 / 20) : 1;
  if (c > hi) {
    return {
      type: 'breakout_up', name: '區間向上突破', icon: '🚀', severity: 'bullish',
      description: `價格 ${fmt(c)} 突破 ${N} 日整理上緣 ${fmt(hi)}。量能 ${fmt(volRatio,1)}x。`,
      action: volRatio >= 1.5 ? `量增有效，目標 ${fmt(hi+(hi-lo))}。` : '量能不足，假突破風險。',
      reliability: volRatio >= 1.5 ? '⭐⭐⭐⭐ 量增突破' : '⭐⭐ 量不足',
      marks: [
        { price: hi, time: prior[0].time, label: `突破 ${fmt(hi)}`, color: COL.bull },
        { price: hi + (hi - lo), time: candles[candles.length-1].time, label: `目標 ${fmt(hi+(hi-lo))}`, color: COL.accent },
      ],
    };
  }
  if (c < lo) {
    return {
      type: 'breakout_down', name: '區間向下跌破', icon: '⬇️', severity: 'bearish',
      description: `價格 ${fmt(c)} 跌破 ${N} 日整理下緣 ${fmt(lo)}。`,
      action: `量度目標 ${fmt(lo-(hi-lo))}。已持倉者停損。`,
      reliability: '⭐⭐⭐⭐ 經典跌破',
      marks: [
        { price: lo, time: prior[0].time, label: `跌破 ${fmt(lo)}`, color: COL.bear },
        { price: lo - (hi - lo), time: candles[candles.length-1].time, label: `目標 ${fmt(lo-(hi-lo))}`, color: COL.accent },
      ],
    };
  }
  return null;
}

function detectMaCross(candles) {
  const N = candles.length;
  if (N < 70) return null;
  const sma = (period, idx) => {
    if (idx + 1 < period) return null;
    let s = 0; for (let i = idx - period + 1; i <= idx; i++) s += candles[i].close;
    return s / period;
  };
  const c20now = sma(20, N - 1), c60now = sma(60, N - 1);
  if (c20now == null || c60now == null) return null;
  for (let lag = 1; lag <= 5; lag++) {
    const p20 = sma(20, N - 1 - lag), p60 = sma(60, N - 1 - lag);
    const n20 = sma(20, N - lag),     n60 = sma(60, N - lag);
    if (p20 == null || p60 == null) continue;
    if (p20 <= p60 && n20 > n60) {
      return {
        type: 'golden_cross', name: '黃金交叉 (SMA20×60)', icon: '✨', severity: 'bullish',
        description: `${lag} 日前 SMA20 (${fmt(n20)}) 上穿 SMA60 (${fmt(n60)})，中期轉多。`,
        action: '回測 SMA20 不破即為加碼點。',
        reliability: '⭐⭐⭐⭐ 中線經典訊號',
        marks: [
          { price: c20now, time: candles[N-1].time, label: `SMA20 ${fmt(c20now)}`, color: COL.warn },
          { price: c60now, time: candles[N-1].time, label: `SMA60 ${fmt(c60now)}`, color: COL.cyan },
        ],
      };
    }
    if (p20 >= p60 && n20 < n60) {
      return {
        type: 'death_cross', name: '死亡交叉 (SMA20×60)', icon: '💀', severity: 'bearish',
        description: `${lag} 日前 SMA20 (${fmt(n20)}) 下穿 SMA60 (${fmt(n60)})，中期轉空。`,
        action: '反彈不過 SMA20 即為減碼點。',
        reliability: '⭐⭐⭐⭐ 中線經典訊號',
        marks: [
          { price: c20now, time: candles[N-1].time, label: `SMA20 ${fmt(c20now)}`, color: COL.warn },
          { price: c60now, time: candles[N-1].time, label: `SMA60 ${fmt(c60now)}`, color: COL.cyan },
        ],
      };
    }
  }
  return null;
}

function detectCupHandle(candles, pivots) {
  if (candles.length < 60) return null;
  const hs = pivots.highs;
  if (hs.length < 2) return null;
  const h2 = hs[hs.length-1], h1 = hs[hs.length-2];
  if (!near(h1.price, h2.price, 3)) return null;
  if (h2.i - h1.i < 20) return null;
  let bot = Infinity, botI = h1.i;
  for (let i = h1.i; i <= h2.i; i++) if (candles[i].low < bot) { bot = candles[i].low; botI = i; }
  const depth = (h1.price - bot) / h1.price * 100;
  if (depth < 8 || depth > 40) return null;
  const after = candles.slice(h2.i + 1);
  if (after.length < 5) return null;
  const handleLo = Math.min(...after.map(c => c.low));
  const handleDepth = (h2.price - handleLo) / h2.price * 100;
  if (handleDepth > depth / 2 || handleDepth < 1) return null;
  const c = candles[candles.length - 1].close;
  const lip = (h1.price + h2.price) / 2;
  const confirmed = c > lip;
  return {
    type: 'cup_handle', name: '杯柄形態 (Cup & Handle)', icon: '☕',
    severity: confirmed ? 'bullish' : 'observing',
    description: `杯口 ${fmt(lip)} / 杯底 ${fmt(bot)} (深 ${fmt(depth,1)}%)、把手 ${fmt(handleDepth,1)}%。`,
    action: confirmed ? `量度目標 ${fmt(lip+(lip-bot))}。` : '等突破杯口確認。',
    reliability: confirmed ? '⭐⭐⭐⭐ O\'Neil 經典' : '⭐⭐⭐ 形態完成中',
    marks: [
      { price: lip, time: h1.time, label: `杯口 ${fmt(lip)}`, color: COL.warn },
      { price: bot, time: candles[botI].time, label: `杯底 ${fmt(bot)}`, color: COL.bull },
    ],
  };
}

// ============================================================
// PATTERN: 8. TRIANGLE — 升級到三種：對稱/上升/下降
// ============================================================
function detectTriangle(candles, pivots) {
  const hs = pivots.highs.slice(-3);
  const ls = pivots.lows.slice(-3);
  if (hs.length < 3 || ls.length < 3) return null;
  const highsDown = hs[0].price > hs[1].price && hs[1].price > hs[2].price;
  const highsFlat = near(hs[0].price, hs[2].price, 2);
  const lowsUp    = ls[0].price < ls[1].price && ls[1].price < ls[2].price;
  const lowsFlat  = near(ls[0].price, ls[2].price, 2);
  const c = candles[candles.length - 1].close;
  const last = candles[candles.length - 1];

  let kind = null, severity = 'neutral', icon = '◢', name = '', desc = '', act = '';
  if (highsFlat && lowsUp) {
    kind = 'ascending';
    name = '上升三角 (Ascending Triangle)';
    icon = '▲'; severity = 'bullish';
    desc = `頂部水平阻力 ~${fmt((hs[0].price+hs[2].price)/2)}，底部墊高 ${fmt(ls[0].price)} → ${fmt(ls[2].price)}。`;
    act = '偏多形態，突破上緣量增追多，目標 = 三角高度延伸。';
  } else if (highsDown && lowsFlat) {
    kind = 'descending';
    name = '下降三角 (Descending Triangle)';
    icon = '▼'; severity = 'bearish';
    desc = `底部水平支撐 ~${fmt((ls[0].price+ls[2].price)/2)}，頂部下移 ${fmt(hs[0].price)} → ${fmt(hs[2].price)}。`;
    act = '偏空形態，跌破下緣量增追空，目標 = 三角高度反推。';
  } else if (highsDown && lowsUp) {
    kind = 'symmetric';
    name = '對稱三角 (Symmetric Triangle)';
    icon = '◢'; severity = 'neutral';
    desc = `高點下移 ${fmt(hs[0].price)} → ${fmt(hs[2].price)}、低點上移 ${fmt(ls[0].price)} → ${fmt(ls[2].price)}。`;
    act = '中性，等突破方向。突破上緣追多、跌破下緣追空。';
  }
  if (!kind) return null;

  return {
    type: 'triangle_' + kind, name, icon, severity,
    description: desc, action: act,
    reliability: kind === 'symmetric' ? '⭐⭐⭐ 等待方向' : '⭐⭐⭐⭐ 偏向性三角',
    marks: [
      { price: hs[0].price, time: hs[0].time, label: '高1', color: COL.bear },
      { price: hs[2].price, time: hs[2].time, label: '高3', color: COL.bear },
      { price: ls[0].price, time: ls[0].time, label: '低1', color: COL.bull },
      { price: ls[2].price, time: ls[2].time, label: '低3', color: COL.bull },
    ],
    polylines: [
      { points: [hs[0], hs[2]], color: COL.bear, label: '上邊', extend: true },
      { points: [ls[0], ls[2]], color: COL.bull, label: '下邊', extend: true },
    ],
  };
}

// ============================================================
// V3 NEW PATTERNS — START HERE
// ============================================================

// ============================================================
// PATTERN 9: ABCD (AB=CD)
// ------------------------------------------------------------
// 4 個 swing 點，方向交替：
//   多頭 ABCD: A(H) → B(L) → C(H) → D(L)，B>D，C<A，AB 與 CD 接近等長
//   空頭 ABCD: A(L) → B(H) → C(L) → D(H)
//   BC 修正：0.618 ~ 0.786 (寬鬆到 0.5~0.886)
//   CD 延伸：相對於 BC = 1.272 ~ 1.618，且 |CD| ≈ |AB| (±15%)
// ============================================================
function detectABCD(candles, zz) {
  if (zz.length < 4) return null;
  const results = [];
  const seqHL = enumerateSequences(zz, 4, 'H');  // bear ABCD: A=H, B=L, C=H, D=L
  const seqLH = enumerateSequences(zz, 4, 'L');  // bull ABCD: A=L, B=H, C=L, D=H

  function tryABCD(s, bullish) {
    const [A, B, C, D] = s;
    const AB = legLen(A, B);
    const BC = legLen(B, C);
    const CD = legLen(C, D);
    if (AB <= 0 || BC <= 0 || CD <= 0) return null;
    const bc_ab = BC / AB;
    const cd_bc = CD / BC;
    const cd_ab = CD / AB;

    // BC 修正 0.382 ~ 0.886
    if (bc_ab < 0.382 || bc_ab > 0.886) return null;
    // CD 延伸 1.13 ~ 2.618
    if (cd_bc < 1.13 || cd_bc > 2.618) return null;
    // AB ≈ CD (±20%)
    if (cd_ab < 0.7 || cd_ab > 1.3) return null;
    // 方向驗證
    if (bullish) {
      if (!(A.price < B.price && B.price > C.price && C.price < D.price)) return null;
    } else {
      if (!(A.price > B.price && B.price < C.price && C.price > D.price)) return null;
    }
    return { A, B, C, D, bc_ab, cd_bc, cd_ab, bullish };
  }

  // bull = A(L) B(H) C(L) D(H)
  for (const s of seqLH) { const r = tryABCD(s, true); if (r) results.push(r); }
  for (const s of seqHL) { const r = tryABCD(s, false); if (r) results.push(r); }
  if (!results.length) return null;
  // 取最近的
  results.sort((a, b) => b.D.i - a.D.i);
  const r = results[0];

  return {
    type: r.bullish ? 'abcd_bull' : 'abcd_bear',
    name: r.bullish ? 'ABCD 多頭 (AB=CD)' : 'ABCD 空頭 (AB=CD)',
    icon: r.bullish ? '🔺' : '🔻',
    severity: r.bullish ? 'bullish' : 'bearish',
    description: `A=${fmt(r.A.price)} B=${fmt(r.B.price)} C=${fmt(r.C.price)} D=${fmt(r.D.price)}，BC 修正 ${fmt(r.bc_ab*100,1)}%、CD 延伸 ${fmt(r.cd_bc,3)}×BC、AB:CD ${fmt(r.cd_ab,3)}。`,
    action: r.bullish
      ? `D 點為潛在多頭轉折，止損下破 D 點 1%，目標 C 或更高 (Fib 0.618/1.272 from CD)。`
      : `D 點為潛在空頭轉折，止損上破 D 點 1%，目標 C 或更低。`,
    reliability: '⭐⭐⭐ AB=CD 經典諧波基礎',
    marks: [
      { price: r.A.price, time: r.A.time, label: 'A', color: COL.warn },
      { price: r.B.price, time: r.B.time, label: 'B', color: COL.warn },
      { price: r.C.price, time: r.C.time, label: 'C', color: COL.warn },
      { price: r.D.price, time: r.D.time, label: `D ${fmt(r.D.price)}`, color: r.bullish ? COL.bull : COL.bear },
    ],
    polylines: [
      { points: [r.A, r.B, r.C, r.D], color: r.bullish ? COL.bull : COL.bear, label: 'ABCD' },
      { points: [r.A, r.C], color: COL.muted, label: 'AC', style: 'dashed' },
      { points: [r.B, r.D], color: COL.muted, label: 'BD', style: 'dashed' },
    ],
  };
}

// ============================================================
// PATTERN 10: XABCD HARMONIC — Gartley / Bat / Butterfly / Crab / Shark
// ------------------------------------------------------------
// 5 個 swing 點（X-A-B-C-D），交替方向
//   多頭：X(L) A(H) B(L) C(H) D(L)
//   空頭：X(H) A(L) B(H) C(L) D(H)
// 每種型態用 Fib 比例驗證：
//   Gartley:   AB/XA=0.618, BC/AB=0.382~0.886, CD/BC=1.13~1.618, AD/XA=0.786
//   Bat:       AB/XA=0.382~0.500, BC/AB=0.382~0.886, CD/BC=1.618~2.618, AD/XA=0.886
//   Butterfly: AB/XA=0.786, BC/AB=0.382~0.886, CD/BC=1.618~2.618, AD/XA=1.272~1.618
//   Crab:      AB/XA=0.382~0.618, BC/AB=0.382~0.886, CD/BC=2.618~3.618, AD/XA=1.618
//   Shark:     AB/XA=0.382~0.618, BC/XA=1.13~1.618, CD/BC=1.618~2.24, AD/XA=0.886~1.13
// ============================================================
const HARMONICS = [
  { name: 'Gartley',   ab_xa: [0.55, 0.68], bc_ab: [0.38, 0.886], cd_bc: [1.13, 1.618], ad_xa: [0.72, 0.85] },
  { name: 'Bat',       ab_xa: [0.38, 0.50], bc_ab: [0.38, 0.886], cd_bc: [1.618, 2.618], ad_xa: [0.85, 0.92] },
  { name: 'Butterfly', ab_xa: [0.72, 0.85], bc_ab: [0.38, 0.886], cd_bc: [1.618, 2.618], ad_xa: [1.20, 1.65] },
  { name: 'Crab',      ab_xa: [0.38, 0.618], bc_ab: [0.38, 0.886], cd_bc: [2.24, 3.618], ad_xa: [1.55, 1.80] },
  { name: 'Shark',     ab_xa: [0.38, 0.618], bc_xa: [1.13, 1.618], cd_bc: [1.618, 2.24], ad_xa: [0.85, 1.13] },
];

function detectXABCD(candles, zz, includeNames) {
  if (zz.length < 5) return [];
  const results = [];
  const allowed = includeNames ? new Set(includeNames) : null;
  const seqLHLHL = enumerateSequences(zz, 5, 'L');  // bullish: X=L,A=H,B=L,C=H,D=L
  const seqHLHLH = enumerateSequences(zz, 5, 'H');  // bearish

  function tryHarmonic(s, bullish, def) {
    const [X, A, B, C, D] = s;
    const XA = legLen(X, A);
    const AB = legLen(A, B);
    const BC = legLen(B, C);
    const CD = legLen(C, D);
    const AD = legLen(A, D);
    if (XA <= 0 || AB <= 0 || BC <= 0 || CD <= 0) return null;
    const ab_xa = AB / XA;
    const bc_ab = BC / AB;
    const cd_bc = CD / BC;
    const ad_xa = AD / XA;
    const bc_xa = BC / XA;
    if (def.ab_xa && (ab_xa < def.ab_xa[0] || ab_xa > def.ab_xa[1])) return null;
    if (def.bc_ab && (bc_ab < def.bc_ab[0] || bc_ab > def.bc_ab[1])) return null;
    if (def.cd_bc && (cd_bc < def.cd_bc[0] || cd_bc > def.cd_bc[1])) return null;
    if (def.ad_xa && (ad_xa < def.ad_xa[0] || ad_xa > def.ad_xa[1])) return null;
    if (def.bc_xa && (bc_xa < def.bc_xa[0] || bc_xa > def.bc_xa[1])) return null;
    // 方向驗證 — 確保 D 落在 X 正確側
    if (bullish && !(D.price < A.price && A.price > X.price)) return null;
    if (!bullish && !(D.price > A.price && A.price < X.price)) return null;
    return { X, A, B, C, D, ab_xa, bc_ab, cd_bc, ad_xa, bc_xa, bullish, def };
  }

  for (const def of HARMONICS) {
    if (allowed && !allowed.has(def.name)) continue;
    for (const s of seqLHLHL) { const r = tryHarmonic(s, true, def); if (r) results.push(r); }
    for (const s of seqHLHLH) { const r = tryHarmonic(s, false, def); if (r) results.push(r); }
  }
  if (!results.length) return [];
  // 同樣 D 點只留最佳（用 fib 接近度）— 按 D.i 分組，每組保留一個
  const byD = new Map();
  for (const r of results) {
    const key = r.D.i + '|' + (r.bullish ? 'b' : 's');
    if (!byD.has(key)) byD.set(key, r);
  }
  const final = [...byD.values()].sort((a, b) => b.D.i - a.D.i).slice(0, 3);

  return final.map(r => ({
    type: 'harmonic_' + r.def.name.toLowerCase() + '_' + (r.bullish ? 'bull' : 'bear'),
    name: `諧波 ${r.def.name} ${r.bullish ? '多頭' : '空頭'} (XABCD)`,
    icon: r.bullish ? '🦋' : '🦂',
    severity: r.bullish ? 'bullish' : 'bearish',
    description: `X=${fmt(r.X.price)} A=${fmt(r.A.price)} B=${fmt(r.B.price)} C=${fmt(r.C.price)} D=${fmt(r.D.price)}。AB/XA=${fmt(r.ab_xa,3)}、BC/AB=${fmt(r.bc_ab,3)}、CD/BC=${fmt(r.cd_bc,3)}、AD/XA=${fmt(r.ad_xa,3)}。`,
    action: r.bullish
      ? `D 為 PRZ (潛在反轉區)，止損 X 下方 1%，目標 0.382/0.618 of CD 或 A。`
      : `D 為 PRZ，止損 X 上方 1%，目標 0.382/0.618 of CD 或 A。`,
    reliability: '⭐⭐⭐⭐ Pesavento/Gartley 學派經典',
    marks: [
      { price: r.X.price, time: r.X.time, label: 'X', color: COL.x },
      { price: r.A.price, time: r.A.time, label: 'A', color: COL.warn },
      { price: r.B.price, time: r.B.time, label: 'B', color: COL.warn },
      { price: r.C.price, time: r.C.time, label: 'C', color: COL.warn },
      { price: r.D.price, time: r.D.time, label: `D ${fmt(r.D.price)} (${r.def.name})`, color: r.bullish ? COL.bull : COL.bear },
    ],
    polylines: [
      { points: [r.X, r.A, r.B, r.C, r.D], color: r.bullish ? COL.bull : COL.bear, label: r.def.name, width: 2 },
      { points: [r.X, r.B], color: COL.muted, style: 'dashed' },
      { points: [r.A, r.C], color: COL.muted, style: 'dashed' },
      { points: [r.X, r.D], color: COL.muted, style: 'dashed' },
      { points: [r.B, r.D], color: COL.muted, style: 'dashed' },
    ],
  }));
}

// ============================================================
// PATTERN 11: CYPHER
// ------------------------------------------------------------
// 與 XABCD 規則略異：
//   AB/XA=0.382~0.618, BC/XA=1.13~1.414, CD/XC=0.786 (D 落在 XC 0.786 回測位)
// ============================================================
function detectCypher(candles, zz) {
  if (zz.length < 5) return [];
  const results = [];
  const seqLHLHL = enumerateSequences(zz, 5, 'L');
  const seqHLHLH = enumerateSequences(zz, 5, 'H');

  function tryCypher(s, bullish) {
    const [X, A, B, C, D] = s;
    const XA = legLen(X, A);
    const AB = legLen(A, B);
    const BC = legLen(B, C);
    const XC = legLen(X, C);
    const CD = legLen(C, D);
    if (!XA || !AB || !BC || !XC || !CD) return null;
    const ab_xa = AB / XA;
    const bc_xa = BC / XA;
    const cd_xc = CD / XC;
    if (ab_xa < 0.382 || ab_xa > 0.618) return null;
    if (bc_xa < 1.13  || bc_xa > 1.414) return null;
    if (cd_xc < 0.72  || cd_xc > 0.85)  return null;  // 0.786 ± 容差
    if (bullish && !(X.price < A.price && A.price > B.price && B.price < C.price && C.price > D.price && D.price > X.price)) return null;
    if (!bullish && !(X.price > A.price && A.price < B.price && B.price > C.price && C.price < D.price && D.price < X.price)) return null;
    return { X, A, B, C, D, ab_xa, bc_xa, cd_xc, bullish };
  }

  for (const s of seqLHLHL) { const r = tryCypher(s, true); if (r) results.push(r); }
  for (const s of seqHLHLH) { const r = tryCypher(s, false); if (r) results.push(r); }
  if (!results.length) return [];
  results.sort((a, b) => b.D.i - a.D.i);
  return results.slice(0, 2).map(r => ({
    type: 'cypher_' + (r.bullish ? 'bull' : 'bear'),
    name: `賽福 Cypher ${r.bullish ? '多頭' : '空頭'} (XABCD)`,
    icon: '🌀',
    severity: r.bullish ? 'bullish' : 'bearish',
    description: `X=${fmt(r.X.price)} → D=${fmt(r.D.price)}。AB/XA=${fmt(r.ab_xa,3)}、BC/XA=${fmt(r.bc_xa,3)}、CD/XC=${fmt(r.cd_xc,3)}。`,
    action: r.bullish ? `D 為買進區，止損 X 下方，目標 0.382 of CD。` : `D 為放空區，止損 X 上方，目標 0.382 of CD。`,
    reliability: '⭐⭐⭐ Darren Oglesbee 衍生諧波',
    marks: [
      { price: r.X.price, time: r.X.time, label: 'X', color: COL.x },
      { price: r.A.price, time: r.A.time, label: 'A', color: COL.warn },
      { price: r.B.price, time: r.B.time, label: 'B', color: COL.warn },
      { price: r.C.price, time: r.C.time, label: 'C', color: COL.warn },
      { price: r.D.price, time: r.D.time, label: `D ${fmt(r.D.price)}`, color: r.bullish ? COL.bull : COL.bear },
    ],
    polylines: [
      { points: [r.X, r.A, r.B, r.C, r.D], color: r.bullish ? COL.bull : COL.bear, label: 'Cypher', width: 2 },
      { points: [r.X, r.C], color: COL.muted, style: 'dashed' },
    ],
  }));
}

// ============================================================
// PATTERN 12: THREE DRIVES 三驅形態
// ------------------------------------------------------------
// 三個推進浪（D1, D2, D3）+ 兩個修正浪
// 多頭三驅（在底部，向上推進三次後反轉）— 通常實際是空頭三驅（頂部）：
//   推進 1 → 修正 1 → 推進 2 → 修正 2 → 推進 3
//   D2 = 1.272 of correction1, D3 = 1.272 of correction2
//   推進斜率與時間相似
// 用 6 個 swing 點：起點, D1, c1, D2, c2, D3
// ============================================================
function detectThreeDrives(candles, zz) {
  if (zz.length < 6) return [];
  const results = [];

  function tryThreeDrives(s, topPattern) {
    // topPattern=true: 在頂部 (空頭三驅 — 三個更高的高點)
    //   start=L, D1=H, c1=L, D2=H, c2=L, D3=H
    //   D1 < D2 < D3 (higher highs)
    const [s0, d1, c1, d2, c2, d3] = s;
    if (topPattern) {
      if (s0.kind !== 'L' || d1.kind !== 'H' || c1.kind !== 'L' || d2.kind !== 'H' || c2.kind !== 'L' || d3.kind !== 'H') return null;
      if (!(d1.price < d2.price && d2.price < d3.price)) return null;
      if (!(c1.price < d1.price && c2.price < d2.price)) return null;
    } else {
      if (s0.kind !== 'H' || d1.kind !== 'L' || c1.kind !== 'H' || d2.kind !== 'L' || c2.kind !== 'H' || d3.kind !== 'L') return null;
      if (!(d1.price > d2.price && d2.price > d3.price)) return null;
      if (!(c1.price > d1.price && c2.price > d2.price)) return null;
    }
    // 推進延伸比 D2/D1, D3/D2 應接近 1.272~1.618
    const drive1 = legLen(s0, d1);
    const corr1  = legLen(d1, c1);
    const drive2 = legLen(c1, d2);
    const corr2  = legLen(d2, c2);
    const drive3 = legLen(c2, d3);
    // corr1 修正 0.382~0.786 of drive1
    const c1_ratio = corr1 / drive1;
    if (c1_ratio < 0.382 || c1_ratio > 0.786) return null;
    // drive2 ≈ 1.272 of corr1 (寬鬆 1.0~1.8)
    const d2_ratio = drive2 / corr1;
    if (d2_ratio < 1.0 || d2_ratio > 2.0) return null;
    const c2_ratio = corr2 / drive2;
    if (c2_ratio < 0.382 || c2_ratio > 0.786) return null;
    const d3_ratio = drive3 / corr2;
    if (d3_ratio < 1.0 || d3_ratio > 2.0) return null;
    return { s0, d1, c1, d2, c2, d3, c1_ratio, d2_ratio, c2_ratio, d3_ratio, topPattern };
  }

  const seqLHLHLH = enumerateSequences(zz, 6, 'L');
  const seqHLHLHL = enumerateSequences(zz, 6, 'H');
  for (const s of seqLHLHLH) { const r = tryThreeDrives(s, true); if (r) results.push(r); }
  for (const s of seqHLHLHL) { const r = tryThreeDrives(s, false); if (r) results.push(r); }
  if (!results.length) return [];
  results.sort((a, b) => b.d3.i - a.d3.i);
  return results.slice(0, 2).map(r => ({
    type: 'three_drives_' + (r.topPattern ? 'top' : 'bottom'),
    name: r.topPattern ? '三驅頂部 (Three Drives Top)' : '三驅底部 (Three Drives Bottom)',
    icon: r.topPattern ? '🔻' : '🔺',
    severity: r.topPattern ? 'bearish' : 'bullish',
    description: `三推進 ${fmt(r.d1.price)} / ${fmt(r.d2.price)} / ${fmt(r.d3.price)}，c1=${fmt(r.c1_ratio*100,1)}%、d2=${fmt(r.d2_ratio,2)}×c1、d3=${fmt(r.d3_ratio,2)}×c2。`,
    action: r.topPattern
      ? '三推進反轉訊號，D3 為潛在頂，止損上破 D3，目標 c2 或 c1。'
      : '三推進反轉訊號，D3 為潛在底，止損下破 D3，目標 c2 或 c1。',
    reliability: '⭐⭐⭐⭐ 衰竭型反轉',
    marks: [
      { price: r.d1.price, time: r.d1.time, label: 'D1', color: COL.warn },
      { price: r.d2.price, time: r.d2.time, label: 'D2', color: COL.warn },
      { price: r.d3.price, time: r.d3.time, label: `D3 ${fmt(r.d3.price)}`, color: r.topPattern ? COL.bear : COL.bull },
    ],
    polylines: [
      { points: [r.s0, r.d1, r.c1, r.d2, r.c2, r.d3], color: r.topPattern ? COL.bear : COL.bull, label: '3-Drives', width: 2 },
      { points: [r.d1, r.d2, r.d3], color: r.topPattern ? COL.bear : COL.bull, style: 'dashed', label: '推進線' },
      { points: [r.c1, r.c2], color: COL.muted, style: 'dashed', label: '修正線' },
    ],
  }));
}

// ============================================================
// PATTERN 13: ELLIOTT IMPULSE WAVE 1-2-3-4-5
// ------------------------------------------------------------
// 五浪推進 — 6 個 swing 點（起點 + 1,2,3,4,5）
// 多頭：start(L), 1(H), 2(L), 3(H), 4(L), 5(H)
// Elliott 三大規則：
//   1. 浪 2 不超過浪 1 起點（不破 start）
//   2. 浪 3 不是最短的浪（通常最長）
//   3. 浪 4 不進入浪 1 領域（價格不重疊）
// 額外指引：
//   - 浪 3 通常 = 1.618× 浪 1
//   - 浪 5 通常 ≈ 浪 1，或 0.618× 浪 1-3
// ============================================================
function detectElliottImpulse(candles, zz) {
  if (zz.length < 6) return [];
  const results = [];

  function tryImpulse(s, bullish) {
    const [w0, w1, w2, w3, w4, w5] = s;
    if (bullish) {
      if (w0.kind !== 'L' || w1.kind !== 'H' || w2.kind !== 'L' || w3.kind !== 'H' || w4.kind !== 'L' || w5.kind !== 'H') return null;
      // Rule 1: w2 不破 w0
      if (w2.price <= w0.price) return null;
      // Rule 2: w3 不是最短的浪
      const len1 = legLen(w0, w1);
      const len3 = legLen(w2, w3);
      const len5 = legLen(w4, w5);
      if (len3 < len1 && len3 < len5) return null;
      // Rule 3: w4 不進入 w1 領域 (w4 不破 w1 高點 — 用更嚴格的價格)
      if (w4.price < w1.price) return null;
      // 多頭：w3 > w1, w5 > w3
      if (!(w3.price > w1.price && w5.price > w3.price)) return null;
      return { w0, w1, w2, w3, w4, w5, len1, len3, len5, bullish };
    } else {
      if (w0.kind !== 'H' || w1.kind !== 'L' || w2.kind !== 'H' || w3.kind !== 'L' || w4.kind !== 'H' || w5.kind !== 'L') return null;
      if (w2.price >= w0.price) return null;
      const len1 = legLen(w0, w1);
      const len3 = legLen(w2, w3);
      const len5 = legLen(w4, w5);
      if (len3 < len1 && len3 < len5) return null;
      if (w4.price > w1.price) return null;
      if (!(w3.price < w1.price && w5.price < w3.price)) return null;
      return { w0, w1, w2, w3, w4, w5, len1, len3, len5, bullish };
    }
  }

  const seqLH = enumerateSequences(zz, 6, 'L');
  const seqHL = enumerateSequences(zz, 6, 'H');
  for (const s of seqLH) { const r = tryImpulse(s, true); if (r) results.push(r); }
  for (const s of seqHL) { const r = tryImpulse(s, false); if (r) results.push(r); }
  if (!results.length) return [];
  results.sort((a, b) => b.w5.i - a.w5.i);
  const r = results[0];
  const w3_w1 = r.len3 / r.len1;
  const w5_w1 = r.len5 / r.len1;
  return [{
    type: 'elliott_impulse_' + (r.bullish ? 'bull' : 'bear'),
    name: `艾略特脈衝波 ${r.bullish ? '多頭' : '空頭'} (1-2-3-4-5)`,
    icon: r.bullish ? '🌊' : '🌊',
    severity: r.bullish ? 'bullish' : 'bearish',
    description: `五浪結構 ${fmt(r.w0.price)}→${fmt(r.w5.price)}。w3/w1=${fmt(w3_w1,2)}、w5/w1=${fmt(w5_w1,2)}。三大規則通過。`,
    action: r.bullish
      ? '五浪推進完成，預期進入 ABC 修正。w5 為潛在賣壓區，目標 w4 → 0.382~0.618 of w1-w5。'
      : '五浪推進完成，預期進入 ABC 反彈。w5 為潛在買壓區。',
    reliability: '⭐⭐⭐⭐⭐ Elliott 經典五浪',
    marks: [
      { price: r.w1.price, time: r.w1.time, label: 'w1', color: COL.bear },
      { price: r.w2.price, time: r.w2.time, label: 'w2', color: COL.bull },
      { price: r.w3.price, time: r.w3.time, label: 'w3', color: COL.bear },
      { price: r.w4.price, time: r.w4.time, label: 'w4', color: COL.bull },
      { price: r.w5.price, time: r.w5.time, label: `w5 ${fmt(r.w5.price)}`, color: COL.accent },
    ],
    polylines: [
      { points: [r.w0, r.w1, r.w2, r.w3, r.w4, r.w5], color: r.bullish ? COL.bull : COL.bear, label: 'Impulse', width: 2 },
      // 通道：浪 1 起點 + 浪 3 終點 連線 vs 浪 2 + 浪 4 連線
      { points: [r.w1, r.w3], color: COL.muted, style: 'dashed', label: '通道上' },
      { points: [r.w2, r.w4], color: COL.muted, style: 'dashed', label: '通道下' },
    ],
  }];
}

// ============================================================
// PATTERN 14: ELLIOTT CORRECTIVE WAVE A-B-C
// ------------------------------------------------------------
// 三浪修正 — 4 個 swing 點（起點 + A, B, C）
// Zigzag (5-3-5): A 大、B 修正 0.382~0.618 of A、C ≈ A 或 1.618× A
// Flat   (3-3-5): A 小、B 接近 A 起點 (>0.9 retrace)、C ≈ A
// Irregular (3-3-5): B 超越 A 起點
// ============================================================
function detectElliottCorrection(candles, zz) {
  if (zz.length < 4) return [];
  const results = [];

  function tryABC(s, bullish) {
    // bullish=true → 上漲後修正：start=H, A=L, B=H, C=L
    // bullish=false → 下跌後反彈：start=L, A=H, B=L, C=H
    const [s0, A, B, C] = s;
    if (bullish) {
      if (s0.kind !== 'H' || A.kind !== 'L' || B.kind !== 'H' || C.kind !== 'L') return null;
      if (!(A.price < s0.price && B.price > A.price && C.price < B.price)) return null;
    } else {
      if (s0.kind !== 'L' || A.kind !== 'H' || B.kind !== 'L' || C.kind !== 'H') return null;
      if (!(A.price > s0.price && B.price < A.price && C.price > B.price)) return null;
    }
    const lenA = legLen(s0, A);
    const lenB = legLen(A, B);
    const lenC = legLen(B, C);
    const b_a = lenB / lenA;
    const c_a = lenC / lenA;
    // 過濾過於不平衡的（C 太小）
    if (c_a < 0.3) return null;
    // 分類
    let subType = 'zigzag';
    if (b_a > 0.9 && b_a < 1.1) subType = 'flat';
    else if (b_a >= 1.1) subType = 'irregular';
    else if (b_a < 0.7) subType = 'zigzag';
    else subType = 'flat';
    return { s0, A, B, C, lenA, lenB, lenC, b_a, c_a, subType, bullish };
  }

  const seqHLHL = enumerateSequences(zz, 4, 'H');  // bullish correction
  const seqLHLH = enumerateSequences(zz, 4, 'L');  // bearish bounce
  for (const s of seqHLHL) { const r = tryABC(s, true); if (r) results.push(r); }
  for (const s of seqLHLH) { const r = tryABC(s, false); if (r) results.push(r); }
  if (!results.length) return [];
  results.sort((a, b) => b.C.i - a.C.i);
  const r = results[0];
  const subName = { zigzag: 'Zigzag (5-3-5)', flat: 'Flat (3-3-5)', irregular: 'Irregular (3-3-5)' }[r.subType];
  return [{
    type: 'elliott_abc_' + r.subType + '_' + (r.bullish ? 'down' : 'up'),
    name: `艾略特 ABC 修正 — ${subName}`,
    icon: '〰️',
    severity: r.bullish ? 'caution' : 'observing',
    description: `${r.bullish ? '上漲後' : '下跌後'}修正：A=${fmt(r.A.price)} B=${fmt(r.B.price)} C=${fmt(r.C.price)}。B/A=${fmt(r.b_a,2)}、C/A=${fmt(r.c_a,2)}。`,
    action: r.bullish
      ? `ABC 修正完成於 C ${fmt(r.C.price)}，可能展開新一輪上漲。若 C 破 A，反轉失敗。`
      : `ABC 反彈完成於 C ${fmt(r.C.price)}，可能展開新一輪下跌。`,
    reliability: '⭐⭐⭐⭐ Elliott 修正浪',
    marks: [
      { price: r.A.price, time: r.A.time, label: 'A', color: COL.warn },
      { price: r.B.price, time: r.B.time, label: 'B', color: COL.warn },
      { price: r.C.price, time: r.C.time, label: `C ${fmt(r.C.price)}`, color: r.bullish ? COL.bull : COL.bear },
    ],
    polylines: [
      { points: [r.s0, r.A, r.B, r.C], color: COL.accent, label: 'ABC', width: 2 },
    ],
  }];
}

// ============================================================
// PATTERN 15: ELLIOTT TRIANGLE A-B-C-D-E
// ------------------------------------------------------------
// 五浪收斂三角修正 — 6 個 swing 點（起點 + A,B,C,D,E）
// 規則：
//   每個浪都是 3-wave 結構（簡化忽略）
//   |B| < |A|, |C| < |B|, |D| < |C|, |E| < |D| （振幅遞減）
//   上下趨勢線收斂
// ============================================================
function detectElliottTriangle(candles, zz) {
  if (zz.length < 6) return [];
  const results = [];

  function tryTriangle(s, bullish) {
    const [s0, A, B, C, D, E] = s;
    if (bullish) {
      if (s0.kind !== 'H' || A.kind !== 'L' || B.kind !== 'H' || C.kind !== 'L' || D.kind !== 'H' || E.kind !== 'L') return null;
    } else {
      if (s0.kind !== 'L' || A.kind !== 'H' || B.kind !== 'L' || C.kind !== 'H' || D.kind !== 'L' || E.kind !== 'H') return null;
    }
    const lenA = legLen(s0, A);
    const lenB = legLen(A, B);
    const lenC = legLen(B, C);
    const lenD = legLen(C, D);
    const lenE = legLen(D, E);
    // 振幅遞減（容忍少數例外）
    let violations = 0;
    if (lenB >= lenA) violations++;
    if (lenC >= lenB) violations++;
    if (lenD >= lenC) violations++;
    if (lenE >= lenD) violations++;
    if (violations > 1) return null;
    return { s0, A, B, C, D, E, bullish };
  }

  const seqHLHLHL = enumerateSequences(zz, 6, 'H');
  const seqLHLHLH = enumerateSequences(zz, 6, 'L');
  for (const s of seqHLHLHL) { const r = tryTriangle(s, true); if (r) results.push(r); }
  for (const s of seqLHLHLH) { const r = tryTriangle(s, false); if (r) results.push(r); }
  if (!results.length) return [];
  results.sort((a, b) => b.E.i - a.E.i);
  const r = results[0];
  return [{
    type: 'elliott_triangle_' + (r.bullish ? 'cont' : 'cont'),
    name: '艾略特三角修正 (A-B-C-D-E)',
    icon: '▽',
    severity: 'neutral',
    description: `五浪收斂三角：A=${fmt(r.A.price)} B=${fmt(r.B.price)} C=${fmt(r.C.price)} D=${fmt(r.D.price)} E=${fmt(r.E.price)}。`,
    action: 'E 完成後預期續行原趨勢（突破方向 = 進入三角前的趨勢方向）。',
    reliability: '⭐⭐⭐⭐ Elliott 連續型三角',
    marks: [
      { price: r.A.price, time: r.A.time, label: 'A', color: COL.warn },
      { price: r.B.price, time: r.B.time, label: 'B', color: COL.warn },
      { price: r.C.price, time: r.C.time, label: 'C', color: COL.warn },
      { price: r.D.price, time: r.D.time, label: 'D', color: COL.warn },
      { price: r.E.price, time: r.E.time, label: `E ${fmt(r.E.price)}`, color: COL.accent },
    ],
    polylines: [
      { points: [r.s0, r.A, r.B, r.C, r.D, r.E], color: COL.accent, label: 'ABCDE', width: 2 },
      // 收斂趨勢線：A-C-E（一邊）和 B-D（另一邊）
      ...(r.bullish
        ? [{ points: [r.A, r.C, r.E], color: COL.bull, style: 'dashed', extend: true, label: '下緣' },
           { points: [r.B, r.D], color: COL.bear, style: 'dashed', extend: true, label: '上緣' }]
        : [{ points: [r.A, r.C, r.E], color: COL.bear, style: 'dashed', extend: true, label: '上緣' },
           { points: [r.B, r.D], color: COL.bull, style: 'dashed', extend: true, label: '下緣' }]
      ),
    ],
  }];
}

// ============================================================
// PATTERN 16: DOUBLE COMBO W-X-Y
// ------------------------------------------------------------
// 雙重組合修正浪：兩個 corrective patterns 用 X 浪連接
// 簡化：6 個 swing 點，W=完整修正 (3浪)、X=連接、Y=另一個修正
// 結構上 W 與 Y 兩段下跌（或上漲），X 是中間反彈
// 用 5 個 swing 點 概略表示：start, W_end, X_end, Y_end (4 點即可，但取 6 點驗證子結構)
// ============================================================
function detectDoubleCombo(candles, zz) {
  if (zz.length < 7) return [];
  const results = [];

  function tryWXY(s, bullish) {
    // bullish=true → 修正高點後：start=H, W_a=L, W_b=H, W_c=L, X=H, Y_a=L (簡化版用 6 點：s, Wc, X_top, Yc, ...)
    // 用 7 點：s0, W_a, W_b, W_c, X_top, Y_b, Y_c
    if (s.length < 7) return null;
    const [s0, w_a, w_b, w_c, x, y_b, y_c] = s;
    if (bullish) {
      // s0=H, w_a=L, w_b=H, w_c=L, x=H, y_b=L, y_c=H ❌
      // 修正方向：應該 W 與 Y 都往下
      // 正確：s0=H → W(三浪向下)=ABC → 結束於 w_c=L → X反彈到 x=H → Y(三浪向下)=ABC → 結束於 y_c=L
      // swing 序列：H L H L H L H — start=H, 結束=H (錯)；或 H L H L H L (6 點)
      // 重新：s0(H) → A1(L) → B1(H) → C1=W端(L) → X頂(H) → A2(L) → B2(H) → C2=Y端(L) — 8 點
      // 簡化版用 5 點：s0(H), Wend(L), Xend(H), Yend(L) — 但缺乏子結構驗證
      return null;
    }
    return null;
  }
  // 暫時用簡化版：4 點 H-L-H-L 形成 W 結束 → X 反彈 → Y 結束
  // 真正的 W-X-Y 是 3-3-3 結構，需要 7 swing points
  // 退而求其次：用 5 swing points 找下跌 → 反彈 → 再下跌 (或反向)
  function trySimple(s, bullish) {
    if (s.length !== 5) return null;
    const [s0, w_end, x_end, y_int, y_end] = s;
    if (bullish) {
      // 下行修正：s0(H)→w_end(L)→x_end(H)→y_int(L)→y_end(?) — 5 點不太對
      // 取 W=L, X=H, Y=L 三點即可
      return null;
    }
  }

  // 簡化：用 7 點 ZigZag，找 H-L-H-L-H-L-H 或反向，
  // 並驗證：W (s0→w_c) 與 Y (x→y_c) 兩個下行段長度相近
  for (let i = 0; i + 7 <= zz.length; i++) {
    const segH = zz.slice(i, i + 7);
    const segL = zz.slice(i, i + 7);
    // H-L-H-L-H-L-H — bullish correction (上方修正)
    if (segH[0].kind === 'H' && segH[1].kind === 'L' && segH[2].kind === 'H' && segH[3].kind === 'L' && segH[4].kind === 'H' && segH[5].kind === 'L' && segH[6].kind === 'H') {
      // 不對 — 7 點 H-L-H-L-H-L-H 起終都是 H — 適合 down-correction (s0=H, end=H 不對)
      // 跳過
    }
    // 改用 8 點：H L H L H L H L (start=H, end=L) — W and Y are downward, X is upward
    if (i + 8 > zz.length) continue;
    const s = zz.slice(i, i + 8);
    if (!(s[0].kind === 'H' && s[1].kind === 'L' && s[2].kind === 'H' && s[3].kind === 'L' && s[4].kind === 'H' && s[5].kind === 'L' && s[6].kind === 'H' && s[7].kind === 'L')) {
      // 嘗試反向 (bearish bounce: L H L H L H L H)
      if (!(s[0].kind === 'L' && s[1].kind === 'H' && s[2].kind === 'L' && s[3].kind === 'H' && s[4].kind === 'L' && s[5].kind === 'H' && s[6].kind === 'L' && s[7].kind === 'H')) continue;
      const bull = false;
      // W = s0→s3 (3-wave correction up), X = s3→s4 (connecting), Y = s4→s7
      const W_amp = legLen(s[0], s[3]);
      const X_amp = legLen(s[3], s[4]);
      const Y_amp = legLen(s[4], s[7]);
      const wy = Y_amp / W_amp;
      if (wy < 0.5 || wy > 2.0) continue;
      if (X_amp / W_amp < 0.3) continue;
      // 方向驗證
      if (!(s[3].price > s[0].price && s[7].price > s[4].price)) continue;
      results.push({ s, bullish: bull, W_amp, X_amp, Y_amp, wy });
      continue;
    }
    const bull = true;  // 上方修正向下
    const W_amp = legLen(s[0], s[3]);
    const X_amp = legLen(s[3], s[4]);
    const Y_amp = legLen(s[4], s[7]);
    const wy = Y_amp / W_amp;
    if (wy < 0.5 || wy > 2.0) continue;
    if (X_amp / W_amp < 0.3) continue;
    if (!(s[3].price < s[0].price && s[7].price < s[4].price)) continue;
    results.push({ s, bullish: bull, W_amp, X_amp, Y_amp, wy });
  }

  if (!results.length) return [];
  results.sort((a, b) => b.s[7].i - a.s[7].i);
  const r = results[0];
  const s = r.s;
  return [{
    type: 'elliott_combo_' + (r.bullish ? 'down' : 'up'),
    name: '艾略特雙重組合浪 (W-X-Y)',
    icon: '☯',
    severity: 'caution',
    description: `W=${fmt(r.W_amp)}, X=${fmt(r.X_amp)}, Y=${fmt(r.Y_amp)}, Y/W=${fmt(r.wy,2)}。雙修正結構。`,
    action: 'Y 結束後預期反轉回原趨勢方向。',
    reliability: '⭐⭐⭐ 複雜修正',
    marks: [
      { price: s[0].price, time: s[0].time, label: '起', color: COL.muted },
      { price: s[3].price, time: s[3].time, label: 'W', color: COL.warn },
      { price: s[4].price, time: s[4].time, label: 'X', color: COL.x },
      { price: s[7].price, time: s[7].time, label: `Y ${fmt(s[7].price)}`, color: COL.accent },
    ],
    polylines: [
      { points: s, color: COL.accent, label: 'WXY', width: 2 },
    ],
  }];
}

// ============================================================
// PATTERN 17: TRIPLE COMBO W-X-Y-X-Z
// ------------------------------------------------------------
// 11 個 swing 點：三個修正 + 兩個連接
// 簡化：用 11 swing zigzag，找 W/Y/Z 三段相似的修正、X 連接
// ============================================================
function detectTripleCombo(candles, zz) {
  if (zz.length < 12) return [];
  const results = [];

  for (let i = 0; i + 12 <= zz.length; i++) {
    const s = zz.slice(i, i + 12);
    // Bullish-side (下行修正): H L H L H L H L H L H L (start H, end L)
    const isBullDown = s[0].kind === 'H' && s.every((v, idx) => v.kind === (idx % 2 === 0 ? 'H' : 'L'));
    const isBearUp = s[0].kind === 'L' && s.every((v, idx) => v.kind === (idx % 2 === 0 ? 'L' : 'H'));
    if (!isBullDown && !isBearUp) continue;
    const bullish = isBullDown;
    // W = s[0]→s[3], X1 = s[3]→s[4], Y = s[4]→s[7], X2 = s[7]→s[8], Z = s[8]→s[11]
    const W = legLen(s[0], s[3]);
    const Y = legLen(s[4], s[7]);
    const Z = legLen(s[8], s[11]);
    const X1 = legLen(s[3], s[4]);
    const X2 = legLen(s[7], s[8]);
    // 三段修正大小相近
    if (Math.abs(W - Y) / W > 0.7 || Math.abs(Y - Z) / Y > 0.7 || Math.abs(W - Z) / W > 0.8) continue;
    // 連接段不能太小
    if (X1 / W < 0.2 || X2 / Y < 0.2) continue;
    // 方向驗證
    if (bullish && !(s[3].price < s[0].price && s[7].price < s[4].price && s[11].price < s[8].price)) continue;
    if (!bullish && !(s[3].price > s[0].price && s[7].price > s[4].price && s[11].price > s[8].price)) continue;
    results.push({ s, bullish, W, Y, Z, X1, X2 });
  }

  if (!results.length) return [];
  results.sort((a, b) => b.s[11].i - a.s[11].i);
  const r = results[0];
  const s = r.s;
  return [{
    type: 'elliott_triple_' + (r.bullish ? 'down' : 'up'),
    name: '艾略特三重組合浪 (W-X-Y-X-Z)',
    icon: '☸',
    severity: 'caution',
    description: `三修正 W=${fmt(r.W)}, Y=${fmt(r.Y)}, Z=${fmt(r.Z)}。連接 X1=${fmt(r.X1)}, X2=${fmt(r.X2)}。`,
    action: 'Z 結束後預期強烈反轉回原趨勢。三重組合通常是市場最複雜的修正之一。',
    reliability: '⭐⭐⭐ 罕見且複雜',
    marks: [
      { price: s[3].price, time: s[3].time, label: 'W', color: COL.warn },
      { price: s[4].price, time: s[4].time, label: 'X', color: COL.x },
      { price: s[7].price, time: s[7].time, label: 'Y', color: COL.warn },
      { price: s[8].price, time: s[8].time, label: 'X', color: COL.x },
      { price: s[11].price, time: s[11].time, label: `Z ${fmt(s[11].price)}`, color: COL.accent },
    ],
    polylines: [
      { points: s, color: COL.accent, label: 'WXYXZ', width: 2 },
    ],
  }];
}

// ============================================================
// PATTERN 18: CYCLE ANALYSIS — FFT 週期偵測
// ------------------------------------------------------------
// 用 close prices 算自相關 / FFT，找主要週期
// 簡化版：自相關 (autocorrelation) 找峰值
// ============================================================
function detectCycle(candles) {
  if (candles.length < 60) return null;
  const closes = candles.map(c => c.close);
  const n = closes.length;
  // 去趨勢：減去 SMA(60)
  const sma = [];
  for (let i = 0; i < n; i++) {
    if (i < 59) { sma.push(closes[i]); continue; }
    let s = 0; for (let k = i - 59; k <= i; k++) s += closes[k];
    sma.push(s / 60);
  }
  const detrended = closes.map((v, i) => v - sma[i]);
  // 自相關 — 計算 lag 5~60 的相關
  function autocorr(arr, lag) {
    const m = arr.length - lag;
    if (m <= 0) return 0;
    let mean1 = 0, mean2 = 0;
    for (let i = 0; i < m; i++) { mean1 += arr[i]; mean2 += arr[i + lag]; }
    mean1 /= m; mean2 /= m;
    let num = 0, d1 = 0, d2 = 0;
    for (let i = 0; i < m; i++) {
      const a = arr[i] - mean1, b = arr[i + lag] - mean2;
      num += a * b; d1 += a * a; d2 += b * b;
    }
    return num / Math.sqrt(Math.max(d1 * d2, 1e-12));
  }
  const corrs = [];
  for (let lag = 5; lag <= Math.min(80, Math.floor(n / 3)); lag++) corrs.push({ lag, r: autocorr(detrended, lag) });
  // 找正相關峰值（局部極大）
  const peaks = [];
  for (let i = 1; i < corrs.length - 1; i++) {
    if (corrs[i].r > 0.15 && corrs[i].r > corrs[i - 1].r && corrs[i].r > corrs[i + 1].r) {
      peaks.push(corrs[i]);
    }
  }
  if (!peaks.length) return null;
  peaks.sort((a, b) => b.r - a.r);
  const top = peaks[0];
  // 預測下一個低點：找最後一個低點，加上週期長度
  let lastLowI = 0, lastLow = Infinity;
  for (let i = n - 1; i >= Math.max(0, n - top.lag * 2); i--) {
    if (closes[i] < lastLow) { lastLow = closes[i]; lastLowI = i; }
  }
  const nextLowI = lastLowI + top.lag;
  return {
    type: 'cycle',
    name: `週期分析 (${top.lag} 日循環)`,
    icon: '🔄',
    severity: 'neutral',
    description: `偵測到 ${top.lag} 日主要週期 (自相關 ${fmt(top.r,3)})。其他候選週期: ${peaks.slice(1, 4).map(p => `${p.lag}d(${fmt(p.r,2)})`).join(', ')}。`,
    action: `若週期成立，預期下一個低點落於 K 線索引 ${nextLowI}（最後低點 ${lastLowI} + ${top.lag} 日）。`,
    reliability: top.r > 0.3 ? '⭐⭐⭐⭐ 強週期' : '⭐⭐⭐ 中等週期',
    marks: [
      { price: lastLow, time: candles[lastLowI].time, label: `週期低 ${fmt(lastLow)}`, color: COL.bull },
    ],
    cycleData: { period: top.lag, corr: top.r, peaks: peaks.slice(0, 5), lastLowI, nextLowI },
  };
}

// ============================================================
// MAIN DETECTOR
// ============================================================
function detectPatternsV3(candlesOverride) {
  const candles = candlesOverride || (window.S && window.S.data && window.S.data.candles);
  if (!candles || !candles.length || candles.length < 30) return [];
  const pivots = findPivots(candles, 5);
  const zz = buildZigZag(candles, pivots);
  const out = [];
  const wrap = (fn, ...args) => { try { const r = fn(...args); if (r) (Array.isArray(r) ? out.push(...r) : out.push(r)); } catch (e) { console.warn('[v3]', fn.name, e); } };

  // v2 patterns (升級版)
  wrap(detectTrendStructure, candles, pivots);
  wrap(detectDoubleTopBottom, candles, pivots);
  wrap(detectHeadShoulders, candles, pivots);
  wrap(detectMaCross, candles);
  wrap(detectBreakout, candles);
  const hasBreakout = out.some(p => p.type.startsWith('breakout'));
  if (!hasBreakout) wrap(detectRange, candles);
  wrap(detectCupHandle, candles, pivots);
  wrap(detectTriangle, candles, pivots);

  // v3 新增 patterns
  wrap(detectABCD, candles, zz);
  wrap(detectXABCD, candles, zz);
  wrap(detectCypher, candles, zz);
  wrap(detectThreeDrives, candles, zz);
  wrap(detectElliottImpulse, candles, zz);
  wrap(detectElliottCorrection, candles, zz);
  wrap(detectElliottTriangle, candles, zz);
  wrap(detectDoubleCombo, candles, zz);
  wrap(detectTripleCombo, candles, zz);
  wrap(detectCycle, candles);

  return out;
}

// ============================================================
// DATA LOADER (沿用 v2)
// ============================================================
const _patternDataCache = new Map();
const PATTERN_CACHE_TTL = 5 * 60_000;

async function loadPatternCandlesV3(sym, mkt) {
  if (!sym) return null;
  mkt = mkt || 'TW';
  const key = `${sym}|${mkt}`;
  const cached = _patternDataCache.get(key);
  if (cached && (Date.now() - cached.fetchedAt < PATTERN_CACHE_TTL)) return cached.candles;
  const yfsym = mkt === 'TW' ? sym + '.TW' : sym;
  const server = (typeof window !== 'undefined' && window.SERVER) || 'http://localhost:18432';
  try {
    // v3 抓 2y 給 Elliott 等長型態更多素材
    const url = `${server}/yf/${yfsym}?range=2y&interval=1d`;
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) { console.warn('[v3] data fetch HTTP', r.status); return null; }
    const raw = await r.json();
    const parsed = (typeof parseYF === 'function') ? parseYF(raw) : null;
    if (!parsed || !parsed.candles || !parsed.candles.length) {
      console.warn('[v3] parseYF returned empty for', yfsym);
      return null;
    }
    _patternDataCache.set(key, { candles: parsed.candles, fetchedAt: Date.now() });
    return parsed.candles;
  } catch (e) {
    console.warn('[v3] loadPatternCandles error:', e);
    return null;
  }
}

// ============================================================
// RENDER — chart annotations
// ------------------------------------------------------------
// v3 新增 polylines 支援：用 LightweightCharts addLineSeries 動態畫斜線
// ============================================================
function drawPatternsOnChartV3(patterns) {
  if (!window.S || !S.chart || !S.chartSeries) return;
  // 清掉舊 price lines
  for (const pl of (S.patternLines || [])) try { S.chartSeries.removePriceLine(pl); } catch {}
  S.patternLines = [];
  // 清掉舊 polyline series
  for (const ps of (S.patternPolySeries || [])) try { S.chart.removeSeries(ps); } catch {}
  S.patternPolySeries = [];
  if (!S.patternsEnabled) return;

  for (const p of patterns) {
    // 1) price line marks
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
      } catch (e) { console.warn('[v3] line draw:', e); }
    }
    // 2) polylines（斜線連接 swing points）
    for (const poly of (p.polylines || [])) {
      try {
        const ls = S.chart.addLineSeries({
          color: poly.color || COL.accent,
          lineWidth: poly.width || 1,
          lineStyle: poly.style === 'dashed' ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        let pts = poly.points.map(pt => ({ time: pt.time, value: pt.price }));
        // 時間遞增 — LightweightCharts 強制要求
        pts.sort((a, b) => a.time - b.time);
        // 去重時間
        const seen = new Set();
        pts = pts.filter(pt => { if (seen.has(pt.time)) return false; seen.add(pt.time); return true; });
        // 延伸（趨勢線到最新時間）
        if (poly.extend && pts.length >= 2) {
          const a = pts[pts.length - 2], b = pts[pts.length - 1];
          const lastT = S.data && S.data.candles ? S.data.candles[S.data.candles.length - 1].time : b.time;
          if (lastT > b.time && b.time > a.time) {
            const slope = (b.value - a.value) / (b.time - a.time);
            pts.push({ time: lastT, value: b.value + slope * (lastT - b.time) });
          }
        }
        ls.setData(pts);
        S.patternPolySeries.push(ls);
      } catch (e) { console.warn('[v3] polyline draw:', e); }
    }
  }
}

function escP(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function renderPatternsPanelV3(candlesOverride) {
  const patterns = detectPatternsV3(candlesOverride);
  if (patterns.length === 0) {
    const n = (candlesOverride || (window.S && S.data && S.data.candles))?.length || 0;
    return `<div style="padding:14px;font-family:monospace;font-size:10px;color:var(--tlo);text-align:center">目前未偵測到明顯形態<br><span style="font-size:9px;color:var(--tf)">分析了 ${n} 個日 K 線，無觸發任何形態規則</span></div>`;
  }
  const sevColor = { bullish:'var(--green)', bearish:'var(--red)', caution:'var(--orange)', neutral:'var(--blue)', observing:'var(--blue)' };
  const sevBg = { bullish:'rgba(74,222,128,.08)', bearish:'rgba(248,113,113,.08)', caution:'rgba(251,146,60,.08)', neutral:'rgba(96,165,250,.08)', observing:'rgba(96,165,250,.08)' };
  // v3：分類顯示 — 按 type prefix 分組
  const groups = {
    '經典反轉': [],
    '經典持續': [],
    '諧波 (Harmonic)': [],
    '艾略特波浪': [],
    '週期分析': [],
  };
  for (const p of patterns) {
    if (p.type.startsWith('harmonic_') || p.type.startsWith('cypher_') || p.type.startsWith('abcd_')) groups['諧波 (Harmonic)'].push(p);
    else if (p.type.startsWith('elliott_') || p.type.startsWith('three_drives')) groups['艾略特波浪'].push(p);
    else if (p.type === 'cycle') groups['週期分析'].push(p);
    else if (p.type.startsWith('triangle') || p.type === 'range' || p.type === 'cup_handle' || p.type.startsWith('breakout')) groups['經典持續'].push(p);
    else groups['經典反轉'].push(p);
  }
  // 👶 新手總結：統計多空型態，給整體傾向
  const bull = patterns.filter(p => p.severity === 'bullish').length;
  const bear = patterns.filter(p => p.severity === 'bearish').length;
  const lean = bull > bear ? '整體偏多 🟢' : bear > bull ? '整體偏空 🔴' : '多空分歧 ⚖️';
  const leanCol = (bull === bear) ? 'var(--orange)' : (window.Colors ? Colors.gain(bull - bear) : (bull > bear ? 'var(--red)' : 'var(--green)'));
  let h = `<div style="padding:10px 12px;border-bottom:1px solid var(--border);background:rgba(251,191,36,.06)">
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;color:var(--gold)">👶 新手白話總結</div>
    <div style="font-family:monospace;font-size:10px;color:var(--text);line-height:1.7;margin-top:4px">
      共偵測到 <b>${patterns.length}</b> 個型態：<b style="color:var(--green)">${bull}</b> 個看漲 / <b style="color:var(--red)">${bear}</b> 個看跌 →
      <b style="color:${leanCol}">${lean}</b>。<br>
      <span style="color:var(--tlo)">型態只是「形狀提示」、非保證。新手記住：看漲也要等站穩再進、設好停損；看跌別急著接刀。</span>
    </div></div>`;
  for (const gname of Object.keys(groups)) {
    const ps = groups[gname];
    if (!ps.length) continue;
    h += `<div style="padding:6px 12px;font-family:monospace;font-size:10px;color:var(--gold);background:rgba(251,191,36,.05);border-bottom:1px solid var(--border)">▸ ${gname} (${ps.length})</div>`;
    for (const p of ps) {
      const col = sevColor[p.severity] || 'var(--text)', bg = sevBg[p.severity] || 'transparent';
      h += `<div style="padding:9px 12px;border-bottom:1px solid var(--border);background:${bg}">
        <div style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;color:${col};margin-bottom:4px">${p.icon || ''} ${escP(p.name)}</div>
        <div style="font-family:sans-serif;font-size:10.5px;color:var(--text);line-height:1.7;margin-bottom:4px;background:rgba(255,255,255,.03);border-left:2px solid ${col};padding:4px 7px">👶 ${escP(plainTalkV3(p))}</div>
        <details style="margin-bottom:2px"><summary style="font-family:monospace;font-size:9px;color:var(--tf);cursor:pointer">技術細節</summary>
          <div style="font-family:monospace;font-size:9.5px;color:var(--text);line-height:1.65;margin:3px 0">${escP(p.description)}</div>
          <div style="font-family:monospace;font-size:9.5px;color:${col};line-height:1.65;margin-bottom:3px">▸ ${escP(p.action)}</div>
          <div style="font-family:monospace;font-size:9px;color:var(--tf);line-height:1.5">${escP(p.reliability)}</div>
        </details>
      </div>`;
    }
  }
  return h;
}

// 把型態翻成新手白話（依多空嚴重度 + 型態類型）
function plainTalkV3(p) {
  const s = p.severity;
  const isRev = (p.type || '').includes('elliott') || (p.type || '').includes('harmonic') ||
                (p.type || '').includes('abcd') || (p.type || '').includes('cypher') || (p.type || '').includes('three_drives');
  if (s === 'bullish')
    return '看漲訊號：線圖出現偏多的形狀，近期較可能往上。新手做法 → 別追高，等回檔站穩再小量試單，跌破最近低點就先離場（停損）。';
  if (s === 'bearish')
    return '看跌訊號：線圖出現偏空的形狀，近期較可能往下。新手做法 → 手上有股留意停利/停損；沒股別急著接刀，等止穩再看。';
  if (s === 'caution')
    return '變盤警示：走勢可能要轉彎或洗盤，方向還不明。新手做法 → 先觀望，等「突破壓力」或「跌破支撐」其中一邊明確了再動。';
  // neutral / observing
  return (isRev ? '轉折觀察：' : '盤整觀察：') +
    '目前方向不明、在區間整理。新手做法 → 別猜方向，等明確突破某一邊再考慮，現階段按兵不動最安全。';
}

function patternsToggleV3() {
  S.patternsEnabled = !S.patternsEnabled;
  const b = document.getElementById('btn-patterns');
  if (b) b.classList.toggle('on', S.patternsEnabled);
  drawPatternsOnChartV3(detectPatternsV3());
}

async function showPatternsModalV3() {
  const sym = S.sym; const mkt = S.mkt;
  if (!sym) {
    if (typeof showProModal === 'function') showProModal('<div style="padding:20px;text-align:center;font-family:monospace;color:var(--tlo)">請先載入個股</div>');
    return;
  }
  const loadingHtml = `
    <h3 style="margin:0 0 10px;color:var(--gold);font-family:monospace;font-size:14px">🤖 AI 形態辨識 v3 — ${sym}</h3>
    <div style="font-family:monospace;font-size:9.5px;color:var(--tlo);margin-bottom:10px">v3 = v2(8 種) + 11 種 TradingView 級型態：諧波 XABCD/Cypher、ABCD、三角(對稱/上升/下降)、三驅、艾略特五浪/修正/三角/雙重/三重組合、循環分析。</div>
    <div style="text-align:center;padding:40px 14px;font-family:monospace;font-size:11px;color:var(--gold)">⟳ 抓取 2 年日 K 線分析中...</div>`;
  if (typeof showProModal === 'function') showProModal(loadingHtml);

  const candles = await loadPatternCandlesV3(sym, mkt);
  let panelHtml;
  if (!candles) {
    panelHtml = `<div style="padding:14px;text-align:center;font-family:monospace;font-size:10px;color:var(--red);line-height:1.7">
      無法載入 ${sym} 的歷史日 K 線<br>
      <span style="font-size:9px;color:var(--tf)">請確認 server.py (:18432) 運作中</span>
    </div>`;
  } else {
    panelHtml = renderPatternsPanelV3(candles);
  }
  const html = `
    <h3 style="margin:0 0 10px;color:var(--gold);font-family:monospace;font-size:14px">🤖 AI 形態辨識 v3 — ${sym}</h3>
    <div style="font-family:monospace;font-size:9.5px;color:var(--tlo);margin-bottom:10px">v3 進階：8 經典 + 11 TradingView 級。${candles ? `<br>分析基礎：最近 <b style="color:var(--gold)">${candles.length}</b> 個日 K 線 (2y 獨立抓取)` : ''}</div>
    <div style="border-top:1px solid var(--border);margin:-2px -24px 6px">${panelHtml}</div>
    <div style="margin-top:10px;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.7">
      ⚠ 形態辨識僅為技術面參考。<br>
      v3 諧波/艾略特/週期建議搭配基本面、量能、大盤判斷。長按 🤖 按鈕可在 chart 上 toggle overlay。
    </div>`;
  if (typeof showProModal === 'function') showProModal(html);
}

// ============================================================
// UI INJECTION
// ============================================================
(function injectPatternButtonV3() {
  let tries = 0;
  function tryInject() {
    if (tries++ > 30) return;  // 給 3 秒，沒抓到就放棄（驗證頁等場景不需要按鈕）
    if (!document.getElementById('rangebar')) return setTimeout(tryInject, 100);
    const proTools = document.getElementById('pro-tools');
    if (!proTools) return setTimeout(tryInject, 100);
    const old = document.getElementById('btn-patterns');
    if (old) old.remove();
    const b = document.createElement('button');
    b.id = 'btn-patterns';
    b.className = 'probtn';
    b.title = 'AI 形態辨識 v3 — 19 種型態 (含諧波/艾略特/循環)';
    b.innerHTML = '🤖 形態³';
    b.onclick = showPatternsModalV3;
    let lp = null;
    b.addEventListener('mousedown', () => { lp = setTimeout(() => { patternsToggleV3(); lp = 'fired'; }, 500); });
    b.addEventListener('mouseup', () => { if (lp && lp !== 'fired') clearTimeout(lp); lp = null; });
    b.addEventListener('mouseleave', () => { if (lp && lp !== 'fired') clearTimeout(lp); lp = null; });
    proTools.appendChild(b);
  }
  tryInject();
})();

(function hookChartV3() {
  let tries = 0;
  function tryHook() {
    if (tries++ > 30) return;
    if (typeof renderChart !== 'function') return setTimeout(tryHook, 100);
    if (window.__patternV3Hooked) return;
    window.__patternV3Hooked = true;
    const orig = window.renderChart;
    window.renderChart = function () {
      orig.apply(this, arguments);
      setTimeout(() => { if (window.S && S.patternsEnabled) drawPatternsOnChartV3(detectPatternsV3()); }, 100);
    };
  }
  tryHook();
})();

// ============================================================
// EXPOSE
// ============================================================
window.PatternV3 = {
  // 核心
  findPivots, buildZigZag, lastSwings,
  // 偵測器
  detectTrendStructure, detectDoubleTopBottom, detectHeadShoulders,
  detectMaCross, detectBreakout, detectRange, detectCupHandle, detectTriangle,
  detectABCD, detectXABCD, detectCypher, detectThreeDrives,
  detectElliottImpulse, detectElliottCorrection, detectElliottTriangle,
  detectDoubleCombo, detectTripleCombo, detectCycle,
  detectPatterns: detectPatternsV3,
  // 資料 + 渲染
  loadPatternCandles: loadPatternCandlesV3,
  drawPatternsOnChart: drawPatternsOnChartV3,
  renderPatternsPanel: renderPatternsPanelV3,
  showPatternsModal: showPatternsModalV3,
  patternsToggle: patternsToggleV3,
  // 常數
  FIB, COL, TOL, HARMONICS,
};

// 向下相容 — 把 v3 的 API 覆寫到 v2 全域名稱上，這樣現有按鈕/hook 直接吃 v3
window.detectPatterns      = detectPatternsV3;
window.renderPatternsPanel = renderPatternsPanelV3;
window.showPatternsModal   = showPatternsModalV3;
window.patternsToggle      = patternsToggleV3;
window.loadPatternCandles  = loadPatternCandlesV3;

console.log('%c[Pattern v3.0] loaded — 19 patterns ready', 'color:#FBBF24;font-weight:bold');

})();

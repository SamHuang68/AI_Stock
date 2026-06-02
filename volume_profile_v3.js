// ============================================================
// Stock Terminal v3.8 — 成交金額 Volume Profile (主力成交金額)
// ------------------------------------------------------------
// 把每根 K 線的成交「金額」(turnover = typical price x volume)
// 分配到 Y 軸價格 bin，畫成右側橫向直方圖，並標出：
//   • POC   金額最大價區 (主力最集中成本)
//   • VAH/VAL Value Area 上下緣 (70% 金額集中區)
//   • 主力成本區 = VAL ~ VAH，判斷現價在主力成本之上/之下
//
// 模式可切換：'amt' 成交金額 (預設) / 'vol' 成交量(張數)
// 覆寫 pro_v2.js 的 computeVolumeProfile / drawVolumeProfile / vpToggle
// 必須在 pro_v2.js 之後載入。
// ============================================================
(function () {
  'use strict';

  const VP = {
    bins: 60,            // Y 軸價格切分數
    mode: 'avg',         // 'avg' = 金額與量正規化平均(預設), 'amt' = 成交金額, 'vol' = 成交量
    vaPct: 0.70,         // Value Area 佔總額比例
    enabled: false,
    canvas: null,
    ro: null,
    lastVP: null,
  };
  window.VP = VP;

  // ---- 計算量價分布 ----------------------------------------
  function computeVP(candles, bins, mode) {
    bins = bins || VP.bins;
    mode = mode || VP.mode;
    if (!candles || !candles.length) return null;
    const lo = Math.min(...candles.map(c => c.low));
    const hi = Math.max(...candles.map(c => c.high));
    const step = (hi - lo) / bins;
    if (!(step > 0)) return null;

    // 同時累積「成交量」與「成交金額」兩組分布
    const volB = new Array(bins).fill(0);
    const amtB = new Array(bins).fill(0);
    for (const c of candles) {
      const typical = (c.high + c.low + c.close) / 3;
      const vol = c.volume || 0;
      const amt = typical * vol;
      const loIdx = Math.min(bins - 1, Math.max(0, Math.floor((c.low - lo) / step)));
      const hiIdx = Math.min(bins - 1, Math.max(0, Math.floor((c.high - lo) / step)));
      const span = hiIdx - loIdx + 1;
      for (let i = loIdx; i <= hiIdx; i++) { volB[i] += vol / span; amtB[i] += amt / span; }
    }

    let buckets;
    if (mode === 'vol') buckets = volB;
    else if (mode === 'amt') buckets = amtB;
    else {
      // 'avg'：各自正規化到 [0,1] 後取平均 (量與金額同權)
      const vMax = Math.max(...volB) || 1, aMax = Math.max(...amtB) || 1;
      buckets = volB.map((v, i) => (v / vMax + amtB[i] / aMax) / 2);
    }
    const total = buckets.reduce((s, v) => s + v, 0);
    if (!(total > 0)) return null;

    // POC = 最大 bin
    let pocIdx = 0;
    for (let i = 1; i < bins; i++) if (buckets[i] > buckets[pocIdx]) pocIdx = i;
    const pocPrice = lo + (pocIdx + 0.5) * step;

    // Value Area：從 POC 往兩側擴張，直到累積達 vaPct
    let loB = pocIdx, hiB = pocIdx, acc = buckets[pocIdx];
    const target = total * VP.vaPct;
    while (acc < target && (loB > 0 || hiB < bins - 1)) {
      const downV = loB > 0 ? buckets[loB - 1] : -1;
      const upV = hiB < bins - 1 ? buckets[hiB + 1] : -1;
      if (upV >= downV) { hiB++; acc += buckets[hiB]; }
      else { loB--; acc += buckets[loB]; }
    }
    const val = lo + loB * step;          // Value Area Low
    const vah = lo + (hiB + 1) * step;    // Value Area High
    const maxB = Math.max(...buckets);

    return { lo, hi, step, bins, mode, buckets, pocIdx, pocPrice, val, vah, maxB, total };
  }

  // ---- 數字格式 (億/萬) ------------------------------------
  function fmtAmt(v) {
    if (VP.mode === 'avg') {
      // avg 為正規化分數，顯示相對強度 (POC=最大設為基準)
      const mx = VP.lastVP ? VP.lastVP.maxB : 1;
      return '強度 ' + (mx ? (v / mx * 100).toFixed(0) : 0) + '%';
    }
    if (VP.mode === 'vol') return Math.round(v).toLocaleString() + ' 張';
    if (v >= 1e8) return (v / 1e8).toFixed(2) + ' 億';
    if (v >= 1e4) return (v / 1e4).toFixed(1) + ' 萬';
    return Math.round(v).toLocaleString();
  }
  const MODE_LABEL = { avg: '量價均衡', amt: '金額', vol: '成交量' };

  // ---- 右側 canvas overlay --------------------------------
  function ensureCanvas() {
    const chartEl = document.getElementById('chart') ||
      (S.chart && S.chart.chartElement && S.chart.chartElement());
    const container = chartEl ? chartEl.parentElement || chartEl : null;
    if (!container) return null;
    if (VP.canvas && VP.canvas._host === container) return VP.canvas;
    if (VP.canvas) { try { VP.canvas.remove(); } catch {} }
    const cv = document.createElement('canvas');
    cv._host = container;
    cv.style.cssText = 'position:absolute;top:0;right:0;pointer-events:none;z-index:5;';
    if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
    container.appendChild(cv);
    VP.canvas = cv;
    return cv;
  }

  function renderHistogram(vp) {
    const cv = ensureCanvas();
    if (!cv || !S.chartSeries) return;
    const host = cv._host;
    const W = host.clientWidth, H = host.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.width = W + 'px'; cv.style.height = H + 'px';
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (!vp) return;

    const maxBarW = Math.min(W * 0.28, 220);  // 直方圖最大寬度
    const x0 = W;                              // 從右邊緣往左畫
    for (let i = 0; i < vp.bins; i++) {
      const p = vp.lo + (i + 0.5) * vp.step;
      let y = S.chartSeries.priceToCoordinate(p);
      if (y == null) continue;
      const yNext = S.chartSeries.priceToCoordinate(p + vp.step);
      const barH = yNext != null ? Math.max(1, Math.abs(y - yNext) - 0.5) : 3;
      const w = (vp.buckets[i] / vp.maxB) * maxBarW;
      const inVA = p >= vp.val && p <= vp.vah;
      const isPoc = i === vp.pocIdx;
      ctx.fillStyle = isPoc ? 'rgba(167,139,250,0.85)'
        : inVA ? 'rgba(96,165,250,0.55)'
          : 'rgba(120,140,170,0.30)';
      ctx.fillRect(x0 - w, y - barH / 2, w, barH);
    }
  }

  // ---- price lines (POC/VAH/VAL) --------------------------
  function clearLines() {
    ['_pocLine', '_vahLine', '_valLine'].forEach(k => {
      if (VP[k]) { try { S.chartSeries.removePriceLine(VP[k]); } catch {} VP[k] = null; }
    });
  }
  function drawLines(vp) {
    clearLines();
    if (!vp) return;
    VP._pocLine = S.chartSeries.createPriceLine({
      price: vp.pocPrice, color: '#A78BFA', lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Solid, axisLabelVisible: true,
      title: 'POC ' + fmtAmt(vp.buckets[vp.pocIdx]),
    });
    VP._vahLine = S.chartSeries.createPriceLine({
      price: vp.vah, color: '#60A5FA', lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'VAH',
    });
    VP._valLine = S.chartSeries.createPriceLine({
      price: vp.val, color: '#60A5FA', lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'VAL',
    });
  }

  // ---- 主繪製 ----------------------------------------------
  function draw() {
    if (!S.chart || !S.chartSeries || !S.data || !S.data.candles) return;
    if (!VP.enabled) { clearLines(); if (VP.canvas) VP.canvas.getContext('2d').clearRect(0, 0, 9999, 9999); updateInfo(null); return; }
    const vp = computeVP(S.data.candles, VP.bins, VP.mode);
    VP.lastVP = vp;
    drawLines(vp);
    renderHistogram(vp);
    updateInfo(vp);
  }

  // 重繪 hook：可視範圍 / 縮放改變時重畫直方圖
  let hooked = false;
  function hookRedraw() {
    if (hooked || !S.chart) return;
    try {
      S.chart.timeScale().subscribeVisibleLogicalRangeChange(() => { if (VP.enabled) renderHistogram(VP.lastVP); });
      hooked = true;
    } catch {}
    if (!VP.ro && window.ResizeObserver && VP.canvas && VP.canvas._host) {
      VP.ro = new ResizeObserver(() => { if (VP.enabled) renderHistogram(VP.lastVP); });
      VP.ro.observe(VP.canvas._host);
    }
  }

  // ---- 資訊面板 (主力成本判斷) -----------------------------
  function updateInfo(vp) {
    let el = document.getElementById('vp-info');
    if (!el) {
      const bar = document.getElementById('toolbar') || document.body;
      el = document.createElement('div');
      el.id = 'vp-info';
      el.style.cssText = 'display:none;font-size:11px;color:#cbd5e1;background:rgba(15,23,42,.9);' +
        'border:1px solid #334155;border-radius:6px;padding:4px 8px;margin-left:6px;white-space:nowrap';
      bar.appendChild(el);
    }
    if (!vp) { el.style.display = 'none'; return; }
    const cur = (S.data.candles[S.data.candles.length - 1] || {}).close;
    const pos = cur > vp.vah ? '<span style="color:#34d399">現價在主力成本區之上 (偏多)</span>'
      : cur < vp.val ? '<span style="color:#f87171">現價在主力成本區之下 (偏空)</span>'
        : '<span style="color:#fbbf24">現價在主力成本區內 (盤整)</span>';
    el.innerHTML = `📊 ${MODE_LABEL[VP.mode] || ''} POC <b>${vp.pocPrice.toFixed(2)}</b> ` +
      `(${fmtAmt(vp.buckets[vp.pocIdx])}) | 主力成本區 <b>${vp.val.toFixed(2)}~${vp.vah.toFixed(2)}</b> | ${pos}`;
    el.style.display = 'inline-block';
  }

  // ---- toggle / mode ---------------------------------------
  function syncBtns() {
    const b = document.getElementById('btn-vp');
    if (b) b.classList.toggle('on', VP.enabled);
    const m = document.getElementById('btn-vp-mode');
    if (m) m.textContent = MODE_LABEL[VP.mode] || '量價';
  }
  function syncState() { if (typeof S !== 'undefined') S.vpEnabled = VP.enabled; }
  function toggle() {
    VP.enabled = !VP.enabled;
    syncState();
    ensureCanvas(); hookRedraw(); draw(); syncBtns();
  }
  function setMode(m) {
    VP.mode = ['avg', 'amt', 'vol'].includes(m) ? m : 'avg';
    syncBtns();
    if (VP.enabled) draw();
  }
  function cycleMode() {
    const order = ['avg', 'amt', 'vol'];
    setMode(order[(order.indexOf(VP.mode) + 1) % order.length]);
    if (!VP.enabled) { VP.enabled = true; syncState(); ensureCanvas(); hookRedraw(); draw(); syncBtns(); }
  }
  // 切股/切區間：renderChart 後 pro_v2 會檢查 S.vpEnabled 呼叫 drawVolumeProfile(=draw)，
  // 這裡再補一個 symLoaded 監聽確保即時重繪
  window.addEventListener('symLoaded', () => { if (VP.enabled) setTimeout(draw, 60); });

  // ---- 覆寫 pro_v2 既有 API (向下相容) ----------------------
  window.computeVolumeProfile = (candles, bins) => computeVP(candles, bins, VP.mode);
  window.drawVolumeProfile = draw;
  window.vpToggle = toggle;
  window.vpSetMode = setMode;
  window.vpCycleMode = cycleMode;

  // 載入後若 chart 已存在，補 hook
  document.addEventListener('DOMContentLoaded', () => { setTimeout(() => { ensureCanvas(); hookRedraw(); }, 800); });
})();

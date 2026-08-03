// ============================================================
// Stock Terminal v3.8 — 成交金額 Volume Profile (主力成交金額)
// ------------------------------------------------------------
// 把每根 K 線的成交「金額」(turnover = typical price x volume)
// 分配到 Y 軸價格 bin，畫成右側橫向直方圖，並標出：
//   • POC   金額最大價區 (主力最集中成本)
//   • VAH/VAL Value Area 上下緣 (70% 金額集中區)
//   • 主力成本區 = VAL ~ VAH，判斷現價在主力成本之上/之下
//
// 常駐預設：量價均衡 (avg) 開啟。
// 圖上浮動鈕可切：均衡 / 只看價(金額) / 只看量。
// 覆寫 pro_v2.js 的 computeVolumeProfile / drawVolumeProfile / vpToggle
// 必須在 pro_v2.js 之後載入。
// ============================================================
(function () {
  'use strict';

  const MODE_KEY = 'st_vp_mode';
  const MODE_ORDER = ['avg', 'amt', 'vol'];
  const MODE_LABEL = { avg: '量價均衡', amt: '只看價', vol: '只看量' };
  const MODE_TITLE = {
    avg: '量與金額正規化後同權平均（預設）',
    amt: '只看成交金額（typical×量）分布',
    vol: '只看成交量（張）分布',
  };

  function loadMode() {
    try {
      const m = localStorage.getItem(MODE_KEY);
      if (MODE_ORDER.includes(m)) return m;
    } catch {}
    return 'avg';
  }
  function saveMode(m) {
    try { localStorage.setItem(MODE_KEY, m); } catch {}
  }

  const VP = {
    bins: 60,            // Y 軸價格切分數
    mode: loadMode(),    // 'avg' 均衡 / 'amt' 只看價 / 'vol' 只看量
    vaPct: 0.70,         // Value Area 佔總額比例
    enabled: true,       // 常駐預設開啟
    canvas: null,
    floatEl: null,
    ro: null,
    lastVP: null,
  };
  window.VP = VP;
  if (typeof S !== 'undefined') S.vpEnabled = true;

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

  // ---- 右側 canvas overlay --------------------------------
  function chartHost() {
    const chartEl = document.getElementById('chart') ||
      (S.chart && S.chart.chartElement && S.chart.chartElement());
    return chartEl ? (chartEl.parentElement || chartEl) : null;
  }

  function ensureCanvas() {
    const container = chartHost();
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

  // ---- 量價模式切換：固定停在 rangebar 與圖之間（不疊在 K 線上）----
  function ensureFloatStyle() {
    if (document.getElementById('vp-float-style')) return;
    const s = document.createElement('style');
    s.id = 'vp-float-style';
    s.textContent = `
    /* 專用列：插在 #rangebar 與 #chartarea 之間，永不覆蓋 K 線／新高 */
    #vp-dock{flex:0 0 28px;height:28px;display:none;align-items:center;justify-content:flex-end;
      gap:8px;padding:0 10px;background:var(--bg2,#0b1220);border-bottom:1px solid var(--border,#1e293b);
      z-index:6;box-sizing:border-box}
    #vp-dock.on{display:flex}
    #vp-dock .vp-dock-lbl{font-size:10px;color:#64748b;letter-spacing:.3px;margin-right:auto}
    #vp-float{position:static;display:flex;align-items:center;gap:0;padding:2px;border-radius:8px;
      background:rgba(15,23,42,.95);border:1px solid #334155;pointer-events:auto;user-select:none}
    #vp-float .vp-fbtn{appearance:none;border:0;background:transparent;color:#94a3b8;
      font-size:11px;font-weight:600;padding:4px 10px;border-radius:6px;cursor:pointer;
      line-height:1.2;letter-spacing:.02em}
    #vp-float .vp-fbtn:hover{color:#e2e8f0;background:rgba(51,65,85,.55)}
    #vp-float .vp-fbtn.on{color:#0f172a;background:#38bdf8}
    #vp-float .vp-fbtn.on[data-m="amt"]{background:#fbbf24}
    #vp-float .vp-fbtn.on[data-m="vol"]{background:#a78bfa;color:#0f172a}
    @media (max-width:720px){
      #vp-dock{padding:0 6px}
      #vp-float .vp-fbtn{padding:4px 7px;font-size:10px}
      #vp-dock .vp-dock-lbl{display:none}
    }`;
    document.head.appendChild(s);
  }

  /** 停靠列：插在圖表上方，不進 #chart-wrap，避免遮蔽新高 */
  function ensureDock() {
    ensureFloatStyle();
    let dock = document.getElementById('vp-dock');
    if (dock) return dock;
    const chartarea = document.getElementById('chartarea');
    const left = document.getElementById('left') || (chartarea && chartarea.parentElement);
    if (!left || !chartarea) return null;
    dock = document.createElement('div');
    dock.id = 'vp-dock';
    dock.innerHTML = '<span class="vp-dock-lbl">量價分布</span>';
    left.insertBefore(dock, chartarea);
    return dock;
  }

  function ensureFloat() {
    const dock = ensureDock();
    if (!dock) return null;
    let el = document.getElementById('vp-float');
    if (el && el._host === dock) {
      VP.floatEl = el;
      return el;
    }
    if (el) { try { el.remove(); } catch {} }
    el = document.createElement('div');
    el.id = 'vp-float';
    el._host = dock;
    el.setAttribute('role', 'group');
    el.setAttribute('aria-label', '量價模式');
    el.innerHTML = MODE_ORDER.map(m =>
      `<button type="button" class="vp-fbtn" data-m="${m}" title="${MODE_TITLE[m]}">${
        m === 'avg' ? '均衡' : (m === 'amt' ? '只看價' : '只看量')
      }</button>`
    ).join('');
    el.addEventListener('click', e => {
      const btn = e.target.closest('.vp-fbtn');
      if (!btn) return;
      const m = btn.getAttribute('data-m');
      if (!MODE_ORDER.includes(m)) return;
      if (!VP.enabled) {
        VP.enabled = true;
        syncState();
        manageOffset(true);
        ensureCanvas();
        hookRedraw();
      }
      setMode(m);
    });
    dock.appendChild(el);
    VP.floatEl = el;
    return el;
  }

  function syncFloat() {
    const dock = ensureDock();
    const el = ensureFloat();
    if (dock) dock.classList.toggle('on', !!VP.enabled);
    if (!el) return;
    el.style.display = VP.enabled ? 'flex' : 'none';
    el.querySelectorAll('.vp-fbtn').forEach(b => {
      b.classList.toggle('on', b.getAttribute('data-m') === VP.mode);
    });
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

    // 右側有價格軸（刻度+現價框，約 60px）。直方圖要止於價格軸左緣，
    // 不能畫進刻度區，否則和價格數字互相遮蔽。
    // timeScale().width() = 繪圖區寬度（已扣掉右側價格軸），最可靠
    let plotRight = W - 64;                              // fallback：保留 64px 給價格軸
    try {
      const tw = S.chart.timeScale().width();
      if (tw && tw > 40) plotRight = tw - 2;
    } catch {}
    plotRight = Math.max(40, plotRight);
    // 只在「最後一根 K 棒右側、價格軸左側」的空白區畫直方圖
    let stripLeft = plotRight * 0.72;                   // fallback
    try {
      const lastIdx = (S.data.candles.length - 1);
      const lx = S.chart.timeScale().logicalToCoordinate(lastIdx);
      if (lx != null && lx > 0) stripLeft = lx + 10;    // 最後一根 K 棒右緣再留 10px
    } catch {}
    const x0 = plotRight;                               // 從價格軸左緣往左畫
    const maxBarW = Math.max(24, Math.min(plotRight - stripLeft - 4, 180));
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

    // POC / VAH / VAL —— 只在右側空白區畫短線 + 標籤，不橫跨全圖
    const lineLeft = Math.max(0, stripLeft - 46);
    const level = (price, color, dashed, label) => {
      const y = S.chartSeries.priceToCoordinate(price);
      if (y == null) return;
      ctx.save();
      ctx.strokeStyle = color; ctx.lineWidth = 1.5;
      if (dashed) ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(lineLeft, y); ctx.lineTo(plotRight, y); ctx.stroke();
      ctx.restore();
      ctx.fillStyle = color; ctx.font = '700 10px monospace'; ctx.textBaseline = 'bottom';
      ctx.fillText(`${label} ${price.toFixed(2)}`, lineLeft + 1, y - 1);
    };
    level(vp.pocPrice, '#A78BFA', false, 'POC');
    level(vp.vah, '#60A5FA', true, 'VAH');
    level(vp.val, '#60A5FA', true, 'VAL');
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
    if (!S.chart || !S.chartSeries || !S.data || !S.data.candles) {
      syncFloat();
      return;
    }
    if (!VP.enabled) {
      clearLines();
      if (VP.canvas) {
        try { VP.canvas.getContext('2d').clearRect(0, 0, 9999, 9999); } catch {}
      }
      updateInfo(null);
      syncFloat();
      return;
    }
    const vp = computeVP(S.data.candles, VP.bins, VP.mode);
    VP.lastVP = vp;
    clearLines();              // 不再用橫跨全圖的 price line；改在 renderHistogram 畫右側短線
    renderHistogram(vp);
    updateInfo(vp);
    syncFloat();
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
    if (b) {
      b.classList.toggle('on', VP.enabled);
      b.title = VP.enabled
        ? '量價分布常駐中（點一下暫時關閉）· 圖上浮動鈕可切 均衡/只看價/只看量'
        : '開啟量價分布（預設量價均衡）';
    }
    const m = document.getElementById('btn-vp-mode');
    if (m) {
      m.textContent = MODE_LABEL[VP.mode] || '量價';
      m.title = '切換量價模式：均衡 → 只看價 → 只看量（亦可用圖上浮動鈕）';
      m.classList.toggle('on', VP.enabled);
    }
    syncFloat();
  }
  function syncState() { if (typeof S !== 'undefined') S.vpEnabled = VP.enabled; }
  // 開啟量價時把 K 線往左推，右側騰出空間給直方圖；關閉時還原
  function manageOffset(on) {
    try {
      const ts = S.chart && S.chart.timeScale();
      if (!ts) return;
      if (on) {
        if (VP._origOffset == null) VP._origOffset = ts.options().rightOffset || 0;
        ts.applyOptions({ rightOffset: Math.max(VP._origOffset, 16) });
      } else if (VP._origOffset != null) {
        ts.applyOptions({ rightOffset: VP._origOffset });
        VP._origOffset = null;
      }
    } catch {}
  }
  function toggle() {
    VP.enabled = !VP.enabled;
    syncState();
    manageOffset(VP.enabled);
    ensureCanvas();
    ensureFloat();
    hookRedraw();
    draw();
    syncBtns();
  }
  function setMode(m) {
    VP.mode = MODE_ORDER.includes(m) ? m : 'avg';
    saveMode(VP.mode);
    syncBtns();
    if (VP.enabled) draw();
    // STATS 量價面板標籤同步
    try {
      if (typeof renderStats === 'function' && document.getElementById('rpanel')) renderStats();
    } catch {}
  }
  function cycleMode() {
    const order = MODE_ORDER;
    setMode(order[(order.indexOf(VP.mode) + 1) % order.length]);
    if (!VP.enabled) {
      VP.enabled = true;
      syncState();
      manageOffset(true);
      ensureCanvas();
      ensureFloat();
      hookRedraw();
      draw();
      syncBtns();
    }
  }

  function activateDefault() {
    VP.enabled = true;
    syncState();
    manageOffset(true);
    ensureCanvas();
    ensureFloat();
    hookRedraw();
    draw();
    syncBtns();
  }

  // 切股/切區間：renderChart 後 pro_v2 會檢查 S.vpEnabled 呼叫 drawVolumeProfile(=draw)
  window.addEventListener('symLoaded', () => {
    if (!VP.enabled) return;
    setTimeout(() => {
      manageOffset(true);
      ensureCanvas();
      ensureFloat();
      hookRedraw();
      draw();
      syncBtns();
    }, 60);
  });

  // ---- 覆寫 pro_v2 既有 API (向下相容) ----------------------
  window.computeVolumeProfile = (candles, bins) => computeVP(candles, bins, VP.mode);
  window.drawVolumeProfile = draw;
  window.vpToggle = toggle;
  window.vpSetMode = setMode;
  window.vpCycleMode = cycleMode;
  window.vpActivateDefault = activateDefault;

  // 載入後常駐開啟量價均衡（或上次記住的模式）
  function boot() {
    syncState();
    ensureFloatStyle();
    activateDefault();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(boot, 700));
  } else {
    setTimeout(boot, 700);
  }
  // chart 可能較晚才建立：再補一次
  setTimeout(() => { if (VP.enabled) activateDefault(); }, 1800);
})();

// ============================================================
// Stock Terminal v3.9 — 多圖連動布局 (Multi-Chart Layouts)
// ------------------------------------------------------------
// 在主圖區 (#chartarea) 上層蓋一個 grid overlay，支援 1x1/2x1/2x2/1+3
// 多圖分割。每格各自一個 lightweight-charts instance：K線 + 量 + SMA20/60。
//   - 同步十字游標：subscribeCrosshairMove → 其他格 setCrosshairPosition
//   - 同步時間軸：subscribeVisibleLogicalRangeChange → setVisibleLogicalRange
//   - 每格可獨立換商品(敲代號 Enter)/換時框
//   - 樣板存 localStorage(mc_layouts)
// 主圖 S.chart / renderChart / 畫線 / 量價 完全不動：多圖是獨立 overlay，
//   關閉後恢復顯示主圖。資料源：/yf 單檔 (沿用 parseYF)。工具列 ▦ 多圖。
// 架構守則：狀態用裸 S；對外只掛 window.multiChart*。
// ============================================================
(function () {
  'use strict';
  const SRV = (typeof window !== 'undefined' && window.SERVER)
    ? window.SERVER
    : (typeof SERVER !== 'undefined' ? SERVER : 'http://localhost:18432');

  // 時框定義(與主程式 RANGE_DEFS 對齊的子集)
  const RANGES = [
    { key: '1d', lbl: '1天', range: '1d', interval: '5m' },
    { key: '5d', lbl: '5天', range: '5d', interval: '15m' },
    { key: '1mo', lbl: '1月', range: '1mo', interval: '1d' },
    { key: '3mo', lbl: '3月', range: '3mo', interval: '1d' },
    { key: '6mo', lbl: '6月', range: '6mo', interval: '1d' },
    { key: '1y', lbl: '1年', range: '1y', interval: '1d' },
    { key: '2y', lbl: '2年', range: '2y', interval: '1d' },
    { key: '5y', lbl: '5年', range: '5y', interval: '1d' },
    { key: '1wk', lbl: '週線', range: '5y', interval: '1wk' },
    { key: '60m', lbl: '60分', range: '1mo', interval: '60m' },
  ];

  // 版面：cols x rows，cells = 格數
  const LAYOUTS = {
    '2x1': { cols: 2, rows: 1, cells: 2, lbl: '2×1' },
    '2x2': { cols: 2, rows: 2, cells: 4, lbl: '2×2' },
    '1x3': { cols: 3, rows: 1, cells: 3, lbl: '1×3' },
  };

  // 內建樣板（開啟時可一鍵套用）
  const PRESETS = {
    mtf: { name: '同股多時框', layout: '2x2',
      panels: [{ rg: '1d' }, { rg: '60m' }, { rg: '6mo' }, { rg: '1wk' }], followMain: true },
    chain: { name: '供應鏈對比', layout: '2x2',
      panels: [
        { sym: '2330', mkt: 'TW', rg: '6mo' }, { sym: 'TSM', mkt: 'US', rg: '6mo' },
        { sym: 'SOXX', mkt: 'US', rg: '6mo' }, { sym: '^TWII', mkt: 'US', rg: '6mo' }] },
    wl: { name: '自選股前四', layout: '2x2', fromWatchlist: true },
  };

  let active = false;
  let layoutKey = '2x2';
  let syncCross = true;
  let syncTime = true;
  let panels = [];           // {idx, sym, mkt, rg, chart, cs, vs, candles, el, body, hdrSym}
  let suppressRange = false; // guard 防時間軸同步回圈

  const tzOff = () => -new Date().getTimezoneOffset() * 60;
  const isDigits = s => /^\d{3,6}[A-Z]?$/.test(s);
  const guessMkt = s => isDigits(s) ? 'TW' : 'US';
  const yf = (sym, mkt) => (mkt === 'TW' && isDigits(sym)) ? sym + '.TW' : sym;

  // ---- 資料 ----
  async function fetchPanel(sym, mkt, rgKey) {
    const r = RANGES.find(x => x.key === rgKey) || RANGES.find(x => x.key === '6mo');
    const url = `${SRV}/yf/${encodeURIComponent(yf(sym, mkt))}?range=${r.range}&interval=${r.interval}`;
    try {
      const raw = await fetch(url, { cache: 'no-store' }).then(x => x.ok ? x.json() : null);
      if (!raw) return null;
      // 沿用主程式 parseYF（全域）
      const p = (typeof parseYF === 'function') ? parseYF(raw) : null;
      return p;
    } catch (e) { console.warn('[multichart]', sym, e); return null; }
  }

  function sma(closes, n, i) {
    if (i + 1 < n) return null;
    let s = 0; for (let k = i - n + 1; k <= i; k++) s += closes[k];
    return s / n;
  }

  // ---- 單格建圖 ----
  function buildPanelChart(p, parsed) {
    if (p.chart) { try { p.chart.remove(); } catch {} p.chart = null; }
    const candles = (parsed && parsed.candles) ? parsed.candles : [];
    p.candles = candles;
    const tz = t => (t == null ? t : t + tzOff());
    const isIntraday = (RANGES.find(x => x.key === p.rg) || {}).interval !== '1d'
      && (RANGES.find(x => x.key === p.rg) || {}).interval !== '1wk';

    // ── 最後一根量回補 (對齊主程式 loadSym) ─────────────────────
    // Yahoo intraday 最後一根(含 13:30 集合競價)volume 常為 0/null。
    // 用當日總量 regularMarketVolume 減其餘各 bar 量，把缺口補回最後一根；
    // 日線最後一根量為 0/null 時直接用 regularMarketVolume 回填。
    const _meta = (parsed && parsed.meta) || {};
    const _rmv = _meta.regularMarketVolume;
    if (candles.length >= 2 && _rmv != null && isFinite(_rmv) && _rmv > 0) {
      const _li = candles.length - 1;
      if (isIntraday) {
        let _sumEx = 0;
        for (let i = 0; i < _li; i++) _sumEx += candles[i].volume || 0;
        const _rem = _rmv - _sumEx;
        if (_rem > 0 && _rem > (candles[_li].volume || 0)) candles[_li].volume = _rem;
      } else if (!(candles[_li].volume > 0)) {
        candles[_li].volume = _rmv;
      }
    }

    const chart = LightweightCharts.createChart(p.body, {
      width: p.body.clientWidth, height: p.body.clientHeight,
      layout: { background: { color: '#060A12' }, textColor: '#5A6A82' },
      grid: { vertLines: { color: '#0F1A2B' }, horzLines: { color: '#0F1A2B' } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#1A2740', scaleMargins: { top: 0.06, bottom: 0.2 } },
      timeScale: {
        borderColor: '#1A2740', timeVisible: isIntraday, secondsVisible: false,
        rightOffset: 2, barSpacing: 6, minBarSpacing: 0.5,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
    });
    p.chart = chart;

    // K 棒/量柱顏色依「該格標的本身市場」(台股紅漲綠跌/美股綠漲紅跌,同主圖 SSOT)
    // v4.1.1 修:原寫死美股色,多圖裡的台股格顏色與主圖相反。
    const _tw = window.Colors ? Colors.isTW(p.sym)
              : (/^\d/.test(String(p.sym || '')) || /^\^TW/i.test(String(p.sym || '')));
    const _UP  = _tw ? '#F87171' : '#4ADE80';
    const _DN  = _tw ? '#4ADE80' : '#F87171';
    const _UPA = _tw ? 'rgba(248,113,113,0.25)' : 'rgba(74,222,128,0.25)';
    const _DNA = _tw ? 'rgba(74,222,128,0.25)' : 'rgba(248,113,113,0.25)';
    const cs = chart.addCandlestickSeries({
      upColor: _UP, downColor: _DN,
      borderUpColor: _UP, borderDownColor: _DN,
      wickUpColor: _UP, wickDownColor: _DN,
      priceLineVisible: false,
    });
    cs.setData(candles.map(c => ({ time: tz(c.time), open: c.open, high: c.high, low: c.low, close: c.close })));
    p.cs = cs;

    const vs = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vs.setData(candles.map(c => ({ time: tz(c.time), value: c.volume, color: c.close >= c.open ? _UPA : _DNA })));
    p.vs = vs;

    if (!isIntraday && candles.length >= 20) {
      const closes = candles.map(c => c.close);
      const mk = (color, w) => chart.addLineSeries({ color, lineWidth: w, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
      const s20 = mk('#FBBF24', 1), s60 = mk('#67E8F9', 1);
      s20.setData(candles.map((c, i) => { const v = sma(closes, 20, i); return v == null ? null : { time: tz(c.time), value: v }; }).filter(Boolean));
      s60.setData(candles.map((c, i) => { const v = sma(closes, 60, i); return v == null ? null : { time: tz(c.time), value: v }; }).filter(Boolean));
    }

    chart.timeScale().fitContent();

    // 同步十字游標：把 hover time 廣播給其他格
    chart.subscribeCrosshairMove(param => {
      if (!syncCross) return;
      if (!param || !param.time) { panels.forEach(o => { if (o !== p && o.chart) try { o.chart.clearCrosshairPosition(); } catch {} }); return; }
      const t = param.time;
      panels.forEach(o => {
        if (o === p || !o.chart || !o.cs) return;
        try {
          // 取目標格在同一 time 的價，否則用來源 price
          let price = null;
          const sd = param.seriesData && param.seriesData.get(p.cs);
          if (sd) price = sd.close ?? sd.value ?? null;
          o.chart.setCrosshairPosition(price == null ? 0 : price, t, o.cs);
        } catch {}
      });
    });

    // 同步時間軸(邏輯範圍)
    chart.timeScale().subscribeVisibleLogicalRangeChange(lr => {
      if (!syncTime || suppressRange || !lr) return;
      suppressRange = true;
      panels.forEach(o => {
        if (o === p || !o.chart) return;
        try { o.chart.timeScale().setVisibleLogicalRange(lr); } catch {}
      });
      suppressRange = false;
    });
  }

  async function loadPanel(p) {
    p.body.innerHTML = '<div class="mc-load">載入中…</div>';
    if (!p.sym) { p.body.innerHTML = '<div class="mc-empty">敲代號 Enter</div>'; return; }
    const parsed = await fetchPanel(p.sym, p.mkt, p.rg);
    if (!active) return;
    p.body.innerHTML = '';
    if (!parsed || !parsed.candles.length) { p.body.innerHTML = '<div class="mc-empty">無資料: ' + p.sym + '</div>'; return; }
    if (p.nameEl) p.nameEl.textContent = parsed.name || '';
    buildPanelChart(p, parsed);
  }

  // ---- UI ----
  function style() {
    if (document.getElementById('mc-style')) return;
    const s = document.createElement('style'); s.id = 'mc-style';
    s.textContent = `
    #mc-grid{position:absolute;top:34px;left:0;right:0;bottom:0;z-index:20;background:#060A12;display:grid;gap:2px;padding:2px}
    .mc-panel{position:relative;display:flex;flex-direction:column;border:1px solid #1A2740;min-width:0;min-height:0;overflow:hidden;background:#060A12}
    .mc-hdr{display:flex;align-items:center;gap:5px;padding:3px 6px;background:#0B1220;border-bottom:1px solid #1A2740;flex:0 0 auto}
    .mc-hdr input{width:62px;background:#0f172a;border:1px solid #334155;color:#e2e8f0;border-radius:4px;padding:2px 5px;font-size:11px;font-family:inherit}
    .mc-hdr select{background:#0f172a;border:1px solid #334155;color:#cbd5e1;border-radius:4px;padding:2px 4px;font-size:10px}
    .mc-hdr .mc-nm{font-size:9px;color:#64748b;margin-left:auto;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .mc-body{flex:1;min-height:0;position:relative}
    .mc-load,.mc-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#5A6A82;font-size:11px;letter-spacing:1px}
    #mc-bar{position:absolute;top:4px;left:50%;transform:translateX(-50%);z-index:30;display:flex;gap:5px;align-items:center;background:rgba(11,18,32,.92);border:1px solid #334155;border-radius:8px;padding:3px 8px;font-size:11px;color:#cbd5e1;height:26px;box-sizing:border-box}
    #mc-bar button{background:#1e293b;border:1px solid #334155;color:#cbd5e1;border-radius:5px;padding:3px 9px;cursor:pointer;font-size:11px}
    #mc-bar button.on{background:rgba(251,191,36,.18);border-color:#fbbf24;color:#fbbf24}
    #mc-bar .sep{width:1px;height:16px;background:#334155}
    #mc-bar .mc-x{background:#7f1d1d;border-color:#991b1b;color:#fecaca}`;
    document.head.appendChild(s);
  }

  function rangeOptions(sel) {
    return RANGES.map(r => `<option value="${r.key}"${r.key === sel ? ' selected' : ''}>${r.lbl}</option>`).join('');
  }

  function buildGrid() {
    const area = document.getElementById('chartarea');
    if (!area) return;
    let grid = document.getElementById('mc-grid');
    if (grid) grid.remove();
    grid = document.createElement('div'); grid.id = 'mc-grid';
    const L = LAYOUTS[layoutKey];
    grid.style.gridTemplateColumns = `repeat(${L.cols},1fr)`;
    grid.style.gridTemplateRows = `repeat(${L.rows},1fr)`;
    area.appendChild(grid);

    // 維持/裁切 panels 數量
    panels.forEach(p => { if (p.chart) try { p.chart.remove(); } catch {} });
    const old = panels.slice();
    panels = [];
    for (let i = 0; i < L.cells; i++) {
      const prev = old[i] || {};
      const p = { idx: i, sym: prev.sym || '', mkt: prev.mkt || 'TW', rg: prev.rg || '6mo' };
      const el = document.createElement('div'); el.className = 'mc-panel';
      const hdr = document.createElement('div'); hdr.className = 'mc-hdr';
      const inp = document.createElement('input'); inp.value = p.sym; inp.placeholder = '代號';
      const selR = document.createElement('select'); selR.innerHTML = rangeOptions(p.rg);
      const nm = document.createElement('span'); nm.className = 'mc-nm';
      hdr.appendChild(inp); hdr.appendChild(selR); hdr.appendChild(nm);
      const body = document.createElement('div'); body.className = 'mc-body';
      el.appendChild(hdr); el.appendChild(body);
      grid.appendChild(el);
      p.el = el; p.body = body; p.hdrSym = inp; p.nameEl = nm;
      inp.addEventListener('keydown', e => {
        if (e.key !== 'Enter') return;
        const v = inp.value.trim().toUpperCase();
        if (!v) return;
        p.sym = v; p.mkt = guessMkt(v); loadPanel(p);
      });
      inp.addEventListener('click', () => inp.select());
      selR.addEventListener('change', () => { p.rg = selR.value; loadPanel(p); });
      panels.push(p);
    }
    // resize observer
    if (!grid._ro) {
      grid._ro = new ResizeObserver(() => resizeAll());
      grid._ro.observe(grid);
    }
    panels.forEach(p => loadPanel(p));
  }

  function resizeAll() {
    panels.forEach(p => {
      if (p.chart && p.body) try { p.chart.resize(p.body.clientWidth, p.body.clientHeight); } catch {}
    });
  }

  function buildBar() {
    let bar = document.getElementById('mc-bar');
    if (bar) bar.remove();
    bar = document.createElement('div'); bar.id = 'mc-bar';
    const layBtns = Object.keys(LAYOUTS).map(k =>
      `<button data-lay="${k}" class="${k === layoutKey ? 'on' : ''}">${LAYOUTS[k].lbl}</button>`).join('');
    const presetBtns = Object.keys(PRESETS).map(k =>
      `<button data-preset="${k}" title="套用樣板">${PRESETS[k].name}</button>`).join('');
    bar.innerHTML =
      layBtns + '<span class="sep"></span>' +
      presetBtns + '<span class="sep"></span>' +
      `<button data-sync="cross" class="${syncCross ? 'on' : ''}" title="同步十字游標">游標</button>` +
      `<button data-sync="time" class="${syncTime ? 'on' : ''}" title="同步時間軸">時間</button>` +
      '<span class="sep"></span>' +
      `<button class="mc-x" data-act="close">✕ 退出多圖</button>`;
    document.getElementById('chartarea').appendChild(bar);
    bar.querySelectorAll('[data-lay]').forEach(b => b.onclick = () => { layoutKey = b.dataset.lay; buildBar(); buildGrid(); });
    bar.querySelectorAll('[data-preset]').forEach(b => b.onclick = () => applyPreset(b.dataset.preset));
    bar.querySelectorAll('[data-sync]').forEach(b => b.onclick = () => {
      if (b.dataset.sync === 'cross') syncCross = !syncCross; else syncTime = !syncTime;
      buildBar();
    });
    bar.querySelector('[data-act="close"]').onclick = close;
  }

  function applyPreset(key) {
    const pr = PRESETS[key]; if (!pr) return;
    layoutKey = pr.layout || '2x2';
    buildBar(); buildGrid();
    let cfg = [];
    if (pr.followMain) {
      const sym = (typeof S !== 'undefined' && S.sym) ? S.sym : '2330';
      const mkt = (typeof S !== 'undefined' && S.mkt) ? S.mkt : 'TW';
      cfg = pr.panels.map(x => ({ sym, mkt, rg: x.rg }));
    } else if (pr.fromWatchlist) {
      const wl = (typeof S !== 'undefined' && Array.isArray(S.wl)) ? S.wl : [];
      cfg = wl.slice(0, LAYOUTS[layoutKey].cells).map(w => ({ sym: w.t, mkt: w.m, rg: '6mo' }));
    } else {
      cfg = pr.panels.slice();
    }
    panels.forEach((p, i) => {
      const c = cfg[i]; if (!c) return;
      p.sym = (c.sym || '').toUpperCase(); p.mkt = c.mkt || guessMkt(p.sym); p.rg = c.rg || '6mo';
      if (p.hdrSym) p.hdrSym.value = p.sym;
      // 更新 range select
      const sel = p.el && p.el.querySelector('select'); if (sel) sel.value = p.rg;
      loadPanel(p);
    });
    saveLayout();
  }

  function saveLayout() {
    try {
      const data = { layoutKey, syncCross, syncTime, panels: panels.map(p => ({ sym: p.sym, mkt: p.mkt, rg: p.rg })) };
      localStorage.setItem('mc_layouts', JSON.stringify(data));
    } catch {}
  }
  function loadSaved() {
    try {
      const d = JSON.parse(localStorage.getItem('mc_layouts') || 'null');
      if (d && LAYOUTS[d.layoutKey]) {
        layoutKey = d.layoutKey;
        if (typeof d.syncCross === 'boolean') syncCross = d.syncCross;
        if (typeof d.syncTime === 'boolean') syncTime = d.syncTime;
        return d.panels || null;
      }
    } catch {}
    return null;
  }

  function open() {
    if (active) { close(); return; }
    style();
    active = true;
    const cw = document.getElementById('chart-wrap'); if (cw) cw.style.visibility = 'hidden';
    const ci = document.getElementById('chart-info'); if (ci) ci.style.display = 'none';
    const saved = loadSaved();
    buildBar();
    buildGrid();
    // 套用儲存的商品，否則第一格放目前主商品
    if (saved && saved.length) {
      panels.forEach((p, i) => {
        const s = saved[i]; if (!s) return;
        p.sym = (s.sym || '').toUpperCase(); p.mkt = s.mkt || guessMkt(p.sym); p.rg = s.rg || '6mo';
        if (p.hdrSym) p.hdrSym.value = p.sym;
        const sel = p.el && p.el.querySelector('select'); if (sel) sel.value = p.rg;
        loadPanel(p);
      });
    } else if (panels[0] && typeof S !== 'undefined' && S.sym) {
      panels[0].sym = S.sym; panels[0].mkt = S.mkt; panels[0].rg = S.range || '6mo';
      if (panels[0].hdrSym) panels[0].hdrSym.value = S.sym;
      loadPanel(panels[0]);
    }
    const btn = document.getElementById('btn-multichart'); if (btn) btn.classList.add('on');
  }

  function close() {
    if (!active) return;
    saveLayout();
    active = false;
    panels.forEach(p => { if (p.chart) try { p.chart.remove(); } catch {} });
    panels = [];
    const grid = document.getElementById('mc-grid');
    if (grid) { if (grid._ro) try { grid._ro.disconnect(); } catch {} grid.remove(); }
    const bar = document.getElementById('mc-bar'); if (bar) bar.remove();
    const cw = document.getElementById('chart-wrap'); if (cw) cw.style.visibility = '';
    const ci = document.getElementById('chart-info'); if (ci) ci.style.display = 'block';
    const btn = document.getElementById('btn-multichart'); if (btn) btn.classList.remove('on');
  }

  window.multiChartOpen = open;
  window.multiChartClose = close;
  window.multiChartActive = () => active;
})();

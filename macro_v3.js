// ============================================================
// Stock Terminal v3.9 — 總經數據疊圖 (Macro Integration)
// ------------------------------------------------------------
// Top-Down 視角：把總經指標與個股/大盤疊圖看相關性。
//   美國：10Y/2Y 公債殖利率、10Y-2Y 利差(倒掛)、CPI、Fed Funds、失業率
//        (後端 FRED 免 key CSV)
//   台灣：CPI(FRED OECD)、景氣對策信號(國發會 best-effort)
// 多序列正規化(起點=100)疊一張圖；可疊加目前個股並算 Pearson 相關係數。
// 後端：/macro (清單) /macro/<series>?years=N。工具列 📉 總經。
// 架構守則：狀態用裸 S(S.data/S.sym)；對外 window.macro*。
// ============================================================
(function () {
  'use strict';
  const SRV = (typeof window !== 'undefined' && window.SERVER)
    ? window.SERVER
    : (typeof SERVER !== 'undefined' ? SERVER : 'http://localhost:18432');

  const COLORS = ['#FBBF24', '#67E8F9', '#F472B6', '#A3E635', '#FB923C', '#C084FC', '#E2E8F0'];
  let catalog = [];
  let years = 10;
  let normalize = true;
  let overlayStock = false;
  let chart = null;
  let series = [];   // 已加的 lightweight series

  async function loadCatalog() {
    if (catalog.length) return catalog;
    try {
      const r = await fetch(`${SRV}/macro`, { cache: 'no-store' }).then(x => x.ok ? x.json() : null);
      if (r && r.series) catalog = r.series;
    } catch {}
    return catalog;
  }
  async function fetchSeries(key) {
    try {
      const r = await fetch(`${SRV}/macro/${encodeURIComponent(key)}?years=${years}`, { cache: 'no-store' }).then(x => x.ok ? x.json() : null);
      return r;
    } catch { return null; }
  }

  function selectedKeys() {
    return [...document.querySelectorAll('.mac-ck:checked')].map(c => c.value);
  }

  function clearSeries() {
    if (!chart) return;
    series.forEach(s => { try { chart.removeSeries(s); } catch {} });
    series = [];
  }

  function pearson(a, b) {
    const n = Math.min(a.length, b.length);
    if (n < 3) return null;
    let sa = 0, sb = 0; for (let i = 0; i < n; i++) { sa += a[i]; sb += b[i]; }
    const ma = sa / n, mb = sb / n;
    let cov = 0, va = 0, vb = 0;
    for (let i = 0; i < n; i++) { const da = a[i] - ma, db = b[i] - mb; cov += da * db; va += da * da; vb += db * db; }
    if (va === 0 || vb === 0) return null;
    return cov / Math.sqrt(va * vb);
  }

  // 個股日 K → {dateStr: close}，並回排序陣列供對齊
  function stockSeries() {
    if (typeof S === 'undefined' || !S.data || !Array.isArray(S.data.candles)) return null;
    const arr = S.data.candles.map(c => {
      const d = new Date((c.time) * 1000);
      const ds = d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0') + '-' + String(d.getUTCDate()).padStart(2, '0');
      return { d: ds, c: c.close };
    });
    return arr;
  }
  function stockCloseAt(stk, dateStr) {
    // 找 <= dateStr 的最後一筆
    let best = null;
    for (const p of stk) { if (p.d <= dateStr) best = p.c; else break; }
    return best;
  }

  async function render() {
    const keys = selectedKeys();
    const msg = document.getElementById('mac-msg');
    const body = document.getElementById('mac-chart');
    if (!chart) {
      chart = LightweightCharts.createChart(body, {
        width: body.clientWidth, height: body.clientHeight,
        layout: { background: { color: '#060A12' }, textColor: '#9FB2CC' },
        grid: { vertLines: { color: '#0F1A2B' }, horzLines: { color: '#0F1A2B' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#1A2740', scaleMargins: { top: 0.08, bottom: 0.08 } },
        timeScale: { borderColor: '#1A2740', timeVisible: false, rightOffset: 8, fixLeftEdge: true },
      });
      // 圖例填入後 #mac-chart 高度會被擠小 → 圖表須跟著縮放，否則底部時間軸被裁掉
      if (!body._macRo) {
        body._macRo = new ResizeObserver(() => { if (chart) { try { chart.resize(body.clientWidth, body.clientHeight); } catch {} } });
        body._macRo.observe(body);
      }
    }
    clearSeries();
    if (!keys.length) { msg.textContent = '左側勾選總經序列'; return; }
    msg.textContent = '載入中…';

    const datasets = [];
    for (const k of keys) {
      const r = await fetchSeries(k);
      if (r && r.points && r.points.length) datasets.push({ key: k, ...r });
      else if (r) datasets.push({ key: k, label: r.label, points: [], note: r.note });
    }

    const unitOf = k => { const c = catalog.find(x => x.key === k); return c ? (c.unit || '') : ''; };
    const fmtVal = (v, u) => (v == null ? '—' : (Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2)) + (u || ''));

    let ci = 0;
    const notes = [];
    const legend = [];
    let firstMacro = null;
    for (const ds of datasets) {
      if (!ds.points.length) { notes.push(`${ds.label}：${ds.note || '無資料'}`); continue; }
      const color = COLORS[ci % COLORS.length]; ci++;
      const base = ds.points[0].value || 1;
      const data = ds.points.map(p => ({ time: p.date, value: normalize ? (p.value / base * 100) : p.value }));
      // 不顯示右側數字框(正規化值會誤導)；實際值改用下方圖例
      const ls = chart.addLineSeries({ color, lineWidth: 1.5, lastValueVisible: false, priceLineVisible: false });
      ls.setData(data);
      series.push(ls);
      if (!firstMacro) firstMacro = ds;
      const last = ds.points[ds.points.length - 1];
      legend.push({ label: ds.label, color, latest: last.value, unit: unitOf(ds.key), date: last.date });
      // 倒掛序列：標 0 軸 (僅 raw 模式有意義)
      if (ds.key === 'spread10y2y' && !normalize) {
        try { ls.createPriceLine({ price: 0, color: '#94a3b8', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: '倒掛線' }); } catch {}
      }
    }

    // 疊加個股
    let corrTxt = '';
    if (overlayStock) {
      const stk = stockSeries();
      if (stk && stk.length && firstMacro) {
        const base = stk[0].c || 1;
        const sdata = stk.map(p => ({ time: p.d, value: normalize ? (p.c / base * 100) : p.c }));
        const ls = chart.addLineSeries({ color: '#ffffff', lineWidth: 2, lastValueVisible: false, priceLineVisible: false });
        ls.setData(sdata);
        series.push(ls);
        legend.push({ label: (S.sym || '個股'), color: '#ffffff', latest: stk[stk.length - 1].c, unit: '' });
        // 相關係數：對齊 firstMacro 的日期取個股收盤
        const a = [], b = [];
        for (const p of firstMacro.points) {
          const sc = stockCloseAt(stk, p.date);
          if (sc != null && p.value != null) { a.push(sc); b.push(p.value); }
        }
        const r = pearson(a, b);
        if (r != null) corrTxt = ` ·  ${S.sym} vs ${firstMacro.label} 相關係數 r=<b style="color:${r >= 0 ? '#22c55e' : '#ef4444'}">${r.toFixed(2)}</b> (n=${a.length})`;
      }
    }

    chart.timeScale().fitContent();

    // HTML 圖例：顯示每條線的「實際最新值 + 真實單位」(正規化只影響線型，不影響此處數字)
    const legEl = document.getElementById('mac-legend');
    if (legEl) {
      legEl.innerHTML = legend.map(L =>
        `<span class="mac-li"><i style="background:${L.color}"></i>${L.label} <b>${fmtVal(L.latest, L.unit)}</b></span>`
      ).join('');
    }

    const yNote = normalize
      ? 'Y軸＝正規化指數(各序列起點=100，僅比較<b>走勢</b>，非實際值)；實際最新值見上方圖例'
      : 'Y軸＝各序列原始值(單位不同混在一起，建議改用正規化比較走勢)';
    msg.innerHTML = yNote + corrTxt + (notes.length ? '　<span style="color:#fb923c">' + notes.join('；') + '</span>' : '');

    // 圖例已填入 → 容器高度可能變小，立即校正圖表尺寸並重新貼合(讓底部時間軸顯示)
    requestAnimationFrame(() => {
      try { chart.resize(body.clientWidth, body.clientHeight); chart.timeScale().fitContent(); } catch {}
    });
  }

  function style() {
    if (document.getElementById('mac-style')) return;
    const s = document.createElement('style'); s.id = 'mac-style';
    s.textContent = `
    #mac-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #mac-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(960px,96vw);height:min(640px,92vh);display:flex;flex-direction:column;padding:14px;color:#e2e8f0;font-size:12px}
    #mac-box h3{margin:0 0 8px;font-size:15px;display:flex;align-items:center;gap:8px}
    #mac-box h3 .x{margin-left:auto;cursor:pointer;color:#94a3b8;font-size:18px}
    .mac-main{display:flex;gap:10px;flex:1;min-height:0}
    .mac-side{width:200px;flex:0 0 auto;overflow:auto;border:1px solid #1e293b;border-radius:6px;padding:8px}
    .mac-side h4{margin:6px 0 4px;font-size:10px;color:#64748b;text-transform:uppercase}
    .mac-side label{display:flex;align-items:center;gap:6px;margin:4px 0;font-size:11px;color:#cbd5e1}
    .mac-right{flex:1;min-width:0;display:flex;flex-direction:column}
    .mac-bar{display:flex;gap:10px;align-items:center;margin-bottom:6px;flex-wrap:wrap;font-size:11px}
    .mac-bar select{background:#0b1220;border:1px solid #334155;color:#cbd5e1;border-radius:5px;padding:3px}
    #mac-legend{display:flex;flex-wrap:wrap;gap:10px 16px;margin-bottom:6px;font-size:11px;color:#cbd5e1}
    .mac-li{display:inline-flex;align-items:center;gap:5px}
    .mac-li i{width:12px;height:3px;border-radius:2px;display:inline-block}
    .mac-li b{color:#e2e8f0}
    #mac-chart{flex:1;min-height:200px;border:1px solid #1A2740;border-radius:6px;overflow:hidden}
    #mac-msg{font-size:11px;color:#94a3b8;margin-top:6px;min-height:14px}`;
    document.head.appendChild(s);
  }

  async function open() {
    style();
    let m = document.getElementById('mac-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'mac-modal';
      m.innerHTML = `<div id="mac-box">
        <h3>📉 總經數據疊圖 <span style="font-size:10px;color:#475569;font-weight:400">FRED 美債/CPI/Fed · 台灣景氣</span><span class="x" onclick="window.macroClose&&macroClose()">×</span></h3>
        <div class="mac-main">
          <div class="mac-side" id="mac-side">載入序列清單…</div>
          <div class="mac-right">
            <div class="mac-bar">
              <label>區間 <select id="mac-years"><option value="3">3年</option><option value="5">5年</option><option value="10" selected>10年</option><option value="20">20年</option></select></label>
              <label><input type="checkbox" id="mac-norm" checked> 正規化(起點100)</label>
              <label><input type="checkbox" id="mac-stock"> 疊加目前個股</label>
            </div>
            <div id="mac-legend"></div>
            <div id="mac-chart"></div>
            <div id="mac-msg"></div>
          </div>
        </div>
      </div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
      m.querySelector('#mac-years').onchange = e => { years = parseInt(e.target.value, 10) || 10; render(); };
      m.querySelector('#mac-norm').onchange = e => { normalize = e.target.checked; render(); };
      m.querySelector('#mac-stock').onchange = e => { overlayStock = e.target.checked; render(); };
    }
    m.style.display = 'flex';
    const cat = await loadCatalog();
    const us = cat.filter(c => c.provider === 'fred' && c.key.startsWith('us') || ['spread10y2y', 'fedfunds', 'unrate', 'us_cpi'].includes(c.key));
    const tw = cat.filter(c => c.key.startsWith('tw'));
    const side = document.getElementById('mac-side');
    const grp = (title, arr) => arr.length ? `<h4>${title}</h4>` + arr.map(c =>
      `<label><input type="checkbox" class="mac-ck" value="${c.key}"> ${c.label}</label>`).join('') : '';
    side.innerHTML = grp('美國', us) + grp('台灣', tw) || '無序列';
    side.querySelectorAll('.mac-ck').forEach(c => c.onchange = render);
    // 預設勾 10Y 殖利率
    const def = side.querySelector('.mac-ck[value="us10y"]'); if (def) { def.checked = true; }
    setTimeout(render, 60);
  }
  function close() {
    const m = document.getElementById('mac-modal'); if (m) m.style.display = 'none';
    if (chart) { try { chart.remove(); } catch {} chart = null; series = []; }
  }

  window.macroOpen = open;
  window.macroClose = close;
})();

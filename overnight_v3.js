// ============================================================
// Stock Terminal v3.8 — 夜盤連動預警 (Overnight / 台指期夜盤 leading)
// ------------------------------------------------------------
// 台指期夜盤與台股隔日開盤主要跟著「美股期貨夜盤」走（那斯達克期/標普期/
// 道瓊期 + 費半）。本模組抓這些 24h 期貨的夜盤漲跌，算出「台股隔日預估」，
// 並連動你的『持倉停損距離』與『觀察股買區距離』，盤前先規劃進出場。
// 資料源：server /quote（Yahoo 期貨，US 盤後/夜盤持續更新）。
// 工具列 🌙 夜盤 開啟。
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';
  // 夜盤領先指標 + 對台股的權重（半導體權值高 → NQ/費半較重）
  const DRIVERS = [
    { sym: 'NQ=F', name: '那斯達克期', w: 0.35 },
    { sym: 'ES=F', name: '標普500期', w: 0.20 },
    { sym: 'YM=F', name: '道瓊期', w: 0.10 },
    { sym: '^SOX', name: '費半', w: 0.35 },
  ];

  // 用日線(5d/1d)算「現價 vs 前一交易日收盤」。期貨(=F)用 1m range 會
  // 抓到 chartPreviousClose==現價 → 0%；日線的 chartPreviousClose 才是前一結算。
  async function q(sym) {
    try {
      const r = await fetch(`${SRV}/yf/${encodeURIComponent(sym)}?range=5d&interval=1d`, { cache: 'no-store' });
      if (!r.ok) return null;
      const j = await r.json();
      const res = j && j.chart && j.chart.result && j.chart.result[0];
      if (!res) return null;
      const meta = res.meta || {};
      const closes = ((res.indicators && res.indicators.quote && res.indicators.quote[0] && res.indicators.quote[0].close) || [])
        .filter(x => x != null);
      const price = (meta.regularMarketPrice != null) ? meta.regularMarketPrice
        : (closes.length ? closes[closes.length - 1] : null);
      // 基準：優先 chartPreviousClose；若它等於現價(期貨常見) 改用倒數第二根日收
      let base = meta.chartPreviousClose != null ? meta.chartPreviousClose : null;
      if ((base == null || (price != null && Math.abs(base - price) < 1e-9)) && closes.length >= 2) {
        base = closes[closes.length - 1] === price ? closes[closes.length - 2] : closes[closes.length - 1];
      }
      const changePct = (price != null && base) ? (price - base) / base * 100 : null;
      return { price, changePct };
    } catch { return null; }
  }
  const col = p => p == null ? 'var(--tlo)' : p > 0 ? 'var(--green)' : p < 0 ? 'var(--red)' : 'var(--tlo)';
  const pct = p => p == null ? '—' : (p >= 0 ? '+' : '') + p.toFixed(2) + '%';

  function style() {
    if (document.getElementById('ovn-style')) return;
    const s = document.createElement('style'); s.id = 'ovn-style';
    s.textContent = `
    #ovn-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #ovn-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(680px,94vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #ovn-box h3{margin:0 0 8px;font-size:15px}
    #ovn-box table{width:100%;border-collapse:collapse;font-size:11px;margin:4px 0 12px}
    #ovn-box th,#ovn-box td{border-bottom:1px solid #1e293b;padding:5px 7px;text-align:right}
    #ovn-box th:first-child,#ovn-box td:first-child{text-align:left}
    #ovn-box tr{cursor:pointer}
    #ovn-box .gauge{font-size:30px;font-weight:800;text-align:center}
    #ovn-box button{background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer}`;
    document.head.appendChild(s);
  }

  async function open() {
    style();
    let m = document.getElementById('ovn-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'ovn-modal';
      m.innerHTML = `<div id="ovn-box"><h3>🌙 夜盤連動預警</h3><div id="ovn-body">載入夜盤中…</div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    m.style.display = 'flex';
    render();
  }
  function close() { const m = document.getElementById('ovn-modal'); if (m) m.style.display = 'none'; }

  async function render() {
    const body = document.getElementById('ovn-body');
    if (!body) return;
    const quotes = {};
    await Promise.all(DRIVERS.map(async d => { quotes[d.sym] = await q(d.sym); }));
    // 期貨夜盤表
    let drows = '', composite = 0, wsum = 0;
    for (const d of DRIVERS) {
      const qq = quotes[d.sym];
      const cp = qq && qq.changePct != null ? qq.changePct : null;
      if (cp != null) { composite += cp * d.w; wsum += d.w; }
      drows += `<tr data-sym="${d.sym}"><td>${d.name} <span style="color:var(--tf);font-size:9px">${d.sym}</span></td>
        <td>${qq && qq.price != null ? qq.price.toFixed(2) : '—'}</td>
        <td style="color:${col(cp)};font-weight:700">${pct(cp)}</td></tr>`;
    }
    const est = wsum > 0 ? composite / wsum : null;   // 加權台股隔日預估 %
    const estCol = col(est);
    const estTxt = est == null ? '—' : (est >= 0 ? '+' : '') + est.toFixed(2) + '%';
    const tone = est == null ? '資料不足'
      : est <= -1.5 ? '⚠ 強烈開低風險：檢視持倉停損、觀察買區'
        : est <= -0.5 ? '偏弱：開低機率高'
          : est >= 1.5 ? '🔥 強烈開高：留意追高與停利'
            : est >= 0.5 ? '偏強：開高機率高' : '中性：開盤波動有限';

    // 持倉停損預警
    let posRows = '';
    const positions = ((typeof S !== 'undefined' && S.positions)) || {};
    for (const code in positions) {
      const p = positions[code];
      const cur = p.lastPrice;
      const stop = p.stop;
      if (cur == null) continue;
      const distStop = (stop != null && stop > 0) ? (cur - stop) / cur * 100 : null;
      // 夜盤預估套到現價 → 估隔日價
      const estPx = est != null ? cur * (1 + est / 100) : null;
      const breach = (stop != null && estPx != null && estPx <= stop);
      posRows += `<tr data-load="${code}"><td>${code}</td>
        <td>${cur.toFixed(2)}</td><td>${stop != null ? stop.toFixed(2) : '—'}</td>
        <td style="color:${distStop != null && distStop < 3 ? 'var(--red)' : 'var(--tlo)'}">${distStop != null ? distStop.toFixed(1) + '%' : '—'}</td>
        <td style="color:${breach ? 'var(--red)' : 'var(--tlo)'}">${estPx != null ? estPx.toFixed(2) : '—'}${breach ? ' ⚠破停損' : ''}</td></tr>`;
    }

    // 觀察股買區（自訂買進價）機會
    let wRows = '';
    const watches = ((typeof S !== 'undefined' && S.watches)) || {};
    for (const code in watches) {
      for (const sig of (watches[code].signals || [])) {
        if (sig.strategy !== 'custom_buy') continue;
        const tgt = sig.params && sig.params.target;
        if (!tgt) continue;
        const cur = (sig.lastEval && sig.lastEval.price) || null;
        const estPx = (cur != null && est != null) ? cur * (1 + est / 100) : null;
        const reach = (estPx != null && estPx <= tgt);
        wRows += `<tr data-load="${code}"><td>${code}</td><td>${cur != null ? cur.toFixed(2) : '—'}</td>
          <td>${(+tgt).toFixed(2)}</td>
          <td style="color:${reach ? 'var(--green)' : 'var(--tlo)'}">${estPx != null ? estPx.toFixed(2) : '—'}${reach ? ' ✓可能入買區' : ''}</td></tr>`;
      }
    }

    body.innerHTML = `
      <div style="text-align:center;margin-bottom:6px">
        <div style="font-size:10px;color:var(--tlo)">美股期貨夜盤 → 台股隔日預估</div>
        <div class="gauge" style="color:${estCol}">${estTxt}</div>
        <div style="font-size:11px;color:${estCol}">${tone}</div>
      </div>
      <table><thead><tr><th>夜盤領先指標</th><th>價</th><th>夜盤漲跌</th></tr></thead><tbody>${drows}</tbody></table>
      <h3 style="font-size:12px;color:var(--red)">📉 持倉停損預警</h3>
      <table><thead><tr><th>代號</th><th>現價</th><th>停損</th><th>距停損</th><th>隔日預估價</th></tr></thead>
        <tbody>${posRows || '<tr><td colspan=5 style="text-align:center;color:var(--tf)">無持倉或未設停損</td></tr>'}</tbody></table>
      <h3 style="font-size:12px;color:var(--green)">📈 觀察股買區機會</h3>
      <table><thead><tr><th>代號</th><th>現價</th><th>買進價</th><th>隔日預估價</th></tr></thead>
        <tbody>${wRows || '<tr><td colspan=4 style="text-align:center;color:var(--tf)">觀察清單無自訂買進價訊號</td></tr>'}</tbody></table>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px">
        <span style="font-size:9px;color:var(--tf)">預估＝NQ/ES/YM/費半 夜盤加權；僅供參考非投資建議</span>
        <div><button onclick="window.overnightRefresh&&overnightRefresh()">↻ 重新整理</button> <button onclick="window.overnightClose&&overnightClose()">關閉</button></div>
      </div>`;
    // 點列載入線型
    body.querySelectorAll('[data-load]').forEach(tr => tr.onclick = () => {
      const c = tr.getAttribute('data-load');
      if (typeof loadSym === 'function') { loadSym(c, /^[0-9]/.test(c) ? 'TW' : 'US'); close(); }
    });
    body.querySelectorAll('[data-sym]').forEach(tr => tr.onclick = () => {
      const c = tr.getAttribute('data-sym');
      if (typeof loadSym === 'function') { loadSym(c, 'US'); close(); }
    });
  }

  window.overnightOpen = open;
  window.overnightClose = close;
  window.overnightRefresh = render;
})();

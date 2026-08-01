// ============================================================
// Stock Terminal v3.8 — 夜盤連動預警 (Overnight / 台指期夜盤 leading)
// ------------------------------------------------------------
// 台指期夜盤與台股隔日開盤主要跟著「美股期貨夜盤」走（那斯達克期/標普期/
// 道瓊期 + 費半）。本模組抓這些 24h 期貨的夜盤漲跌，算出「台股隔日預估」，
// 並顯示「台指期夜盤波動」(OHLC/振幅)，連動持倉停損與觀察股買區。
// 資料源：server /quote·/yf（美股期貨）、/txf（台指期夜盤，Yahoo+TAIFEX MIS）。
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

  // 與大盤列 refreshMktBar 完全相同的算法（rmt 落後判斷 + 前一交易日收盤），
  // 確保夜盤面板與大盤列數字一致（之前用 chartPreviousClose 會算出錯誤的微小%）。
  async function q(sym) {
    try {
      const r = await fetch(`${SRV}/yf/${encodeURIComponent(sym)}?range=5d&interval=1d`, { cache: 'no-store' });
      if (!r.ok) return null;
      const j = await r.json();
      const res = j && j.chart && j.chart.result && j.chart.result[0];
      if (!res) return null;
      const meta = res.meta || {};
      const ts = res.timestamp || [];
      const cl = (res.indicators && res.indicators.quote && res.indicators.quote[0] && res.indicators.quote[0].close) || [];
      const valid = [];
      for (let i = 0; i < Math.min(ts.length, cl.length); i++) {
        if (cl[i] != null && isFinite(cl[i]) && ts[i] != null) valid.push({ t: ts[i], c: cl[i] });
      }
      if (!valid.length) return null;
      const last = valid[valid.length - 1];
      const prevC = valid.length >= 2 ? valid[valid.length - 2].c : null;
      const rmt = meta.regularMarketTime, rmp = meta.regularMarketPrice;
      let cur, prev;
      if (rmt && rmp != null && isFinite(rmp) && rmp > 0 && rmt - last.t > 20 * 3600) {
        cur = rmp; prev = last.c;                 // 日線落後 → rmp 才是今天
      } else {
        cur = last.c; prev = (prevC != null) ? prevC : (meta.chartPreviousClose || meta.previousClose);
      }
      const changePct = (cur != null && prev != null && prev > 0) ? (cur - prev) / prev * 100 : null;
      return { price: cur, changePct };
    } catch { return null; }
  }

  /** /txf → 台指期夜盤波動（優先 d.night，否則 session=night 的主報價） */
  async function qTxfNight() {
    try {
      const r = await fetch(`${SRV}/txf`, { cache: 'no-store' });
      if (!r.ok) return null;
      const d = await r.json();
      if (!d || !d.ok) return null;
      const n = (d.night && d.night.price != null) ? d.night
        : (d.session === 'night' && d.price != null) ? d : null;
      if (!n || n.price == null) return null;
      let amp = n.ampRate;
      if (amp == null && n.high != null && n.low != null && n.prevClose > 0) {
        amp = (n.high - n.low) / n.prevClose * 100;
      }
      let changePct = n.changePct;
      if (changePct == null && n.price != null && n.prevClose > 0) {
        changePct = (n.price - n.prevClose) / n.prevClose * 100;
      }
      let change = n.change;
      if (change == null && n.price != null && n.prevClose != null) {
        change = n.price - n.prevClose;
      }
      return {
        price: n.price,
        prevClose: n.prevClose,
        change,
        changePct,
        open: n.open,
        high: n.high,
        low: n.low,
        ampRate: amp,
        volume: n.volume,
        time: n.time || '',
        source: n.source || d.source || '',
      };
    } catch { return null; }
  }

  const col = p => p == null ? 'var(--tlo)' : p > 0 ? 'var(--green)' : p < 0 ? 'var(--red)' : 'var(--tlo)';
  // 台股／台指期：紅漲綠跌（與 Colors.dir 一致）
  const twCol = p => {
    if (p == null) return 'var(--tlo)';
    if (window.Colors && typeof Colors.dir === 'function') return Colors.dir('__TXF__', p);
    return p > 0 ? 'var(--red)' : p < 0 ? 'var(--green)' : 'var(--tlo)';
  };
  const pct = p => p == null ? '—' : (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
  const fmtIdx = v => v == null || !isFinite(v) ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
  const fmtVol = v => v == null || !isFinite(v) ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
  const fmtTime = t => {
    if (!t || String(t).length < 4) return '';
    const s = String(t).padStart(6, '0');
    return s.slice(0, 2) + ':' + s.slice(2, 4) + ':' + s.slice(4, 6);
  };
  const ampTone = a => {
    if (a == null) return '波動資料不足';
    if (a >= 3.5) return '⚠ 高波動：夜盤區間擴大，隔日開盤易跳空';
    if (a >= 2.0) return '波動偏大：留意開盤落點與停損距離';
    if (a >= 1.0) return '波動中等';
    return '波動收斂';
  };

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
    #ovn-box .txf-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}
    #ovn-box .txf-cell{background:#111827;border:1px solid #1e293b;border-radius:6px;padding:6px 7px;text-align:center}
    #ovn-box .txf-cell .k{font-size:9px;color:#64748b}
    #ovn-box .txf-cell .v{font-size:12px;font-weight:700;margin-top:2px}
    #ovn-box button{background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer}
    @media (max-width:520px){#ovn-box .txf-grid{grid-template-columns:repeat(2,1fr)}}`;
    document.head.appendChild(s);
  }

  function renderTxfBlock(txf) {
    if (!txf) {
      return `<div style="margin:8px 0;padding:8px 10px;border:1px solid #334155;border-radius:8px;background:rgba(56,189,248,.05)">
        <div style="font-size:12px;font-weight:700;color:#38bdf8">📉 台指期夜盤波動</div>
        <div style="font-size:11px;color:var(--tf);margin-top:4px">暫無夜盤資料（MIS/Yahoo）</div></div>`;
    }
    const cp = txf.changePct;
    const cCol = twCol(cp);
    const amp = txf.ampRate;
    const rangePts = (txf.high != null && txf.low != null) ? (txf.high - txf.low) : null;
    const deltaTxt = txf.change != null
      ? ((txf.change >= 0 ? '+' : '') + Math.round(txf.change).toLocaleString('en-US'))
      : '—';
    const tTxt = fmtTime(txf.time);
    return `<div style="margin:8px 0;padding:8px 10px;border:1px solid #334155;border-radius:8px;background:rgba(56,189,248,.06)">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap">
        <div style="font-size:12px;font-weight:700;color:#38bdf8">📉 台指期夜盤波動 <span style="font-size:10px;color:#64748b;font-weight:400">TXF 近月</span></div>
        <div style="font-size:9px;color:#64748b">${tTxt ? '更新 ' + tTxt : ''} ${txf.source ? '· ' + txf.source : ''}</div>
      </div>
      <div style="display:flex;align-items:baseline;gap:10px;margin-top:6px;flex-wrap:wrap">
        <div style="font-size:22px;font-weight:800;color:${cCol}">${fmtIdx(txf.price)}</div>
        <div style="font-size:13px;font-weight:700;color:${cCol}">${deltaTxt}（${pct(cp)}）</div>
        <div style="font-size:11px;color:#94a3b8">昨收 ${fmtIdx(txf.prevClose)}</div>
      </div>
      <div class="txf-grid">
        <div class="txf-cell"><div class="k">開盤</div><div class="v">${fmtIdx(txf.open)}</div></div>
        <div class="txf-cell"><div class="k">最高</div><div class="v" style="color:var(--red)">${fmtIdx(txf.high)}</div></div>
        <div class="txf-cell"><div class="k">最低</div><div class="v" style="color:var(--green)">${fmtIdx(txf.low)}</div></div>
        <div class="txf-cell"><div class="k">振幅</div><div class="v" style="color:${amp != null && amp >= 2 ? '#fbbf24' : '#e2e8f0'}">${amp != null ? amp.toFixed(2) + '%' : '—'}${rangePts != null ? '<div style="font-size:9px;color:#64748b;font-weight:400;margin-top:2px">' + Math.round(rangePts).toLocaleString('en-US') + ' 點</div>' : ''}</div></div>
      </div>
      <div style="font-size:10px;color:#94a3b8;margin-top:6px">成交量 ${fmtVol(txf.volume)} · ${ampTone(amp)}</div>
      <div style="font-size:9px;color:#64748b;margin-top:3px;line-height:1.5">振幅＝(最高−最低)/昨收；夜盤高波動常對應隔日跳空，請對照上方美股期貨預估。</div>
    </div>`;
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
    const [, , txf] = await Promise.all([
      Promise.all(DRIVERS.map(async d => { quotes[d.sym] = await q(d.sym); })),
      q('TSM').then(v => { quotes.__TSM__ = v; }),
      qTxfNight(),
    ]);
    // TSM ADR = 2330 的隔日先行指標（核心連動）
    const tsm = quotes.__TSM__;
    const tsmPct = (tsm && tsm.changePct != null) ? tsm.changePct : null;
    const soxQ = quotes['^SOX'];
    const soxPct = (soxQ && soxQ.changePct != null) ? soxQ.changePct : null;
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
    const estCol = window.Colors ? Colors.dir('^TWII', est) : twCol(est);   // 台股隔日預估 → 台股紅漲綠跌
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
      ${renderTxfBlock(txf)}
      <table><thead><tr><th>夜盤領先指標</th><th>價</th><th>夜盤漲跌</th></tr></thead><tbody>${drows}</tbody></table>
      <div style="margin:8px 0;padding:8px 10px;border:1px solid #334155;border-radius:8px;background:rgba(251,191,36,.06)">
        <div style="font-size:12px;font-weight:700;color:#fbbf24">🔱 TSMC 核心連動（2330）</div>
        <div style="font-size:11px;margin-top:4px">TSM ADR 夜盤 <b style="color:${col(tsmPct)}">${pct(tsmPct)}</b> · 費半 <b style="color:${col(soxPct)}">${pct(soxPct)}</b>
          → <b>2330 隔日預估 ≈ <span style="color:${window.Colors?Colors.dir('2330',tsmPct):col(tsmPct)}">${pct(tsmPct)}</span></b>（主要看 TSM ADR）</div>
        <div style="font-size:9px;color:var(--tlo);line-height:1.6;margin-top:5px">
          長線結構：① TSMC＝AI 宇宙核心、先進製程獨佔，營收正比 AI 類股；② TSM/費半漲→2330 隔日多反映（除非美股收盤後重磅利空）；
          ③ INTEL 18A／Samsung SF2 即便接單，產能良率僅滿足部分；④ AI 與 AMD/INTEL 皆靠 3D 封裝（如 Panther Lake 僅 compute die，其餘 4~5 顆與封裝仍在台積）；
          ⑤ 4 大 CSP 投資集中台灣：買 TSMC 晶圓→3D 封裝→CPO 光通訊→AI 伺服器整機組裝全在台 → 台股日成交量自 2026/04 前約 8000 億／日 升至 1.2 兆＋。
        </div>
      </div>
      <h3 style="font-size:12px;color:var(--red)">📉 持倉停損預警</h3>
      <table><thead><tr><th>代號</th><th>現價</th><th>停損</th><th>距停損</th><th>隔日預估價</th></tr></thead>
        <tbody>${posRows || '<tr><td colspan=5 style="text-align:center;color:var(--tf)">無持倉或未設停損</td></tr>'}</tbody></table>
      <h3 style="font-size:12px;color:var(--green)">📈 觀察股買區機會</h3>
      <table><thead><tr><th>代號</th><th>現價</th><th>買進價</th><th>隔日預估價</th></tr></thead>
        <tbody>${wRows || '<tr><td colspan=4 style="text-align:center;color:var(--tf)">觀察清單無自訂買進價訊號</td></tr>'}</tbody></table>
      <div style="font-size:9px;color:var(--tf);line-height:1.7;margin-top:8px;border-top:1px solid #222;padding-top:6px">
        <b style="color:var(--tlo)">資料來源</b>：Yahoo Finance（美股期貨/指數）經 /yf；台指期夜盤經 /txf（Yahoo TW + TAIFEX MIS 夜盤）<br>
        夜盤指標：那斯達克期 <code>NQ=F</code>(35%) · 標普500期 <code>ES=F</code>(20%) · 道瓊期 <code>YM=F</code>(10%) · 費半 <code>^SOX</code>(35%)；核心連動 <code>TSM</code> ADR<br>
        台指期夜盤波動：近月 OHLC、振幅％、成交量（振幅＝(高−低)/昨收）<br>
        漲跌基準：各標的前一交易日收盤（遇 null 自動退最近一筆有效值，不帶入 null 計算）<br>
        更新時間：${new Date().toLocaleString('zh-TW', { hour12: false })} · 僅供參考，非投資建議
      </div>
      <div style="text-align:right;margin-top:8px">
        <button onclick="window.overnightRefresh&&overnightRefresh()">↻ 重新整理</button> <button onclick="window.overnightClose&&overnightClose()">關閉</button></div>`;
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

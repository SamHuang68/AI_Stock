// ============================================================
// Stock Terminal v3.8 — 夜盤連動預警 (Overnight / 台指期夜盤 leading)
// ------------------------------------------------------------
// 主訊號＝台指期夜盤（TXF 近月，Yahoo TW + TAIFEX MIS），直接反映台股隔夜定價。
// 輔訊號＝美股期貨夜盤（NQ/ES/YM + 費半）加權「美股連動預估」。
// 持倉停損／觀察買區以台指期夜盤%為優先（無則退美股預估）。
// 工具列 🌙 夜盤 開啟。
// ============================================================
(function () {
  'use strict';
  function srv() {
    if (window.SERVER) return window.SERVER;
    if (typeof location !== 'undefined' && location.origin && location.origin !== 'null') {
      return location.origin;
    }
    return 'http://localhost:18432';
  }
  // 美股夜盤領先指標 + 對台股的權重（半導體權值高 → NQ/費半較重）
  const DRIVERS = [
    { sym: 'NQ=F', name: '那斯達克期', w: 0.35 },
    { sym: 'ES=F', name: '標普500期', w: 0.20 },
    { sym: 'YM=F', name: '道瓊期', w: 0.10 },
    { sym: '^SOX', name: '費半', w: 0.35 },
  ];

  // 與大盤列 refreshMktBar 完全相同的算法（rmt 落後判斷 + 前一交易日收盤）
  async function q(sym) {
    try {
      const r = await fetch(`${srv()}/yf/${encodeURIComponent(sym)}?range=5d&interval=1d`, { cache: 'no-store' });
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
        cur = rmp; prev = last.c;
      } else {
        cur = last.c; prev = (prevC != null) ? prevC : (meta.chartPreviousClose || meta.previousClose);
      }
      const changePct = (cur != null && prev != null && prev > 0) ? (cur - prev) / prev * 100 : null;
      return { price: cur, changePct };
    } catch { return null; }
  }

  function normalizeTxf(n, sourceFallback) {
    if (!n || n.price == null || !isFinite(n.price)) return null;
    let amp = n.ampRate;
    if (amp == null && n.high != null && n.low != null && n.prevClose > 0) {
      amp = (n.high - n.low) / n.prevClose * 100;
    }
    let changePct = n.changePct;
    if (changePct == null && n.prevClose > 0) {
      changePct = (n.price - n.prevClose) / n.prevClose * 100;
    }
    let change = n.change;
    if (change == null && n.prevClose != null) {
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
      source: n.source || sourceFallback || '',
      sessionLabel: n.sessionLabel || '夜盤',
    };
  }

  /** /txf → 台指期夜盤（優先 night；夜盤時段/仍為 night session 的主報價亦可） */
  async function qTxfNight() {
    try {
      const r = await fetch(`${srv()}/txf`, { cache: 'no-store' });
      if (!r.ok) return null;
      const d = await r.json();
      if (!d || !d.ok) return null;
      let n = normalizeTxf(d.night, d.source);
      if (!n && d.session === 'night') n = normalizeTxf(d, d.source);
      // 日盤時段若 Yahoo/MIS 主報價仍帶齊 OHLC+振幅，且與 night 缺漏時，退主報價（盤前常見）
      if (!n && d.ampRate != null && d.high != null && d.low != null) n = normalizeTxf(d, d.source);
      return n;
    } catch { return null; }
  }

  const col = p => p == null ? 'var(--tlo)' : p > 0 ? 'var(--green)' : p < 0 ? 'var(--red)' : 'var(--tlo)';
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
  function toneOf(p, label) {
    if (p == null) return '資料不足';
    const tag = label ? `（${label}）` : '';
    if (p <= -1.5) return `⚠ 強烈開低風險${tag}：檢視持倉停損、觀察買區`;
    if (p <= -0.5) return `偏弱${tag}：開低機率高`;
    if (p >= 1.5) return `🔥 強烈開高${tag}：留意追高與停利`;
    if (p >= 0.5) return `偏強${tag}：開高機率高`;
    return `中性${tag}：開盤波動有限`;
  }

  function style() {
    if (document.getElementById('ovn-style')) return;
    const s = document.createElement('style'); s.id = 'ovn-style';
    s.textContent = `
    #ovn-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #ovn-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(720px,94vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #ovn-box h3{margin:0 0 8px;font-size:15px}
    #ovn-box table{width:100%;border-collapse:collapse;font-size:11px;margin:4px 0 12px}
    #ovn-box th,#ovn-box td{border-bottom:1px solid #1e293b;padding:5px 7px;text-align:right}
    #ovn-box th:first-child,#ovn-box td:first-child{text-align:left}
    #ovn-box tr{cursor:pointer}
    #ovn-box .gauge{font-size:30px;font-weight:800;text-align:center;line-height:1.15}
    #ovn-box .gauge-sm{font-size:20px;font-weight:800;text-align:center;line-height:1.15}
    #ovn-box .dual{display:grid;grid-template-columns:1.2fr 1fr;gap:10px;margin-bottom:8px}
    #ovn-box .dual > div{border:1px solid #1e293b;border-radius:8px;padding:8px 6px;background:#111827}
    #ovn-box .txf-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}
    #ovn-box .txf-cell{background:#0b1220;border:1px solid #1e293b;border-radius:6px;padding:6px 7px;text-align:center}
    #ovn-box .txf-cell .k{font-size:9px;color:#64748b}
    #ovn-box .txf-cell .v{font-size:12px;font-weight:700;margin-top:2px}
    #ovn-box button{background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer}
    @media (max-width:560px){
      #ovn-box .dual{grid-template-columns:1fr}
      #ovn-box .txf-grid{grid-template-columns:repeat(2,1fr)}
    }`;
    document.head.appendChild(s);
  }

  function renderTxfBlock(txf) {
    if (!txf) {
      return `<div style="margin:8px 0;padding:8px 10px;border:1px solid #334155;border-radius:8px;background:rgba(56,189,248,.05)">
        <div style="font-size:12px;font-weight:700;color:#38bdf8">📉 台指期夜盤波動</div>
        <div style="font-size:11px;color:var(--tf);margin-top:4px">暫無夜盤資料（請確認本機 /txf；MIS/Yahoo）</div></div>`;
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
        <div style="font-size:12px;font-weight:700;color:#38bdf8">📉 台指期夜盤波動 <span style="font-size:10px;color:#64748b;font-weight:400">TXF 近月 · 主訊號</span></div>
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
      <div style="font-size:9px;color:#64748b;margin-top:3px;line-height:1.5">振幅＝(最高−最低)/昨收。持倉／觀察預估價以台指期夜盤漲跌為準。</div>
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
    body.innerHTML = '<div style="padding:12px;color:#94a3b8">載入台指期夜盤與美股期貨…</div>';
    const quotes = {};
    const [, , txf] = await Promise.all([
      Promise.all(DRIVERS.map(async d => { quotes[d.sym] = await q(d.sym); })),
      q('TSM').then(v => { quotes.__TSM__ = v; }),
      qTxfNight(),
    ]);
    const tsm = quotes.__TSM__;
    const tsmPct = (tsm && tsm.changePct != null) ? tsm.changePct : null;
    const soxQ = quotes['^SOX'];
    const soxPct = (soxQ && soxQ.changePct != null) ? soxQ.changePct : null;

    let drows = '', composite = 0, wsum = 0;
    for (const d of DRIVERS) {
      const qq = quotes[d.sym];
      const cp = qq && qq.changePct != null ? qq.changePct : null;
      if (cp != null) { composite += cp * d.w; wsum += d.w; }
      drows += `<tr data-sym="${d.sym}"><td>${d.name} <span style="color:var(--tf);font-size:9px">${d.sym}</span></td>
        <td>${qq && qq.price != null ? qq.price.toFixed(2) : '—'}</td>
        <td style="color:${col(cp)};font-weight:700">${pct(cp)}</td></tr>`;
    }
    // 台指期夜盤列置頂（主訊號）
    const txfPct = (txf && txf.changePct != null) ? txf.changePct : null;
    const txfRow = `<tr data-load="__TXF__" style="background:rgba(56,189,248,.08)">
      <td>台指期夜盤 <span style="color:#38bdf8;font-size:9px">TXF · 主訊號</span></td>
      <td style="color:${twCol(txfPct)};font-weight:700">${txf && txf.price != null ? fmtIdx(txf.price) : '—'}</td>
      <td style="color:${twCol(txfPct)};font-weight:800">${pct(txfPct)}</td></tr>`;

    const usEst = wsum > 0 ? composite / wsum : null;  // 美股連動預估
    // 行動預估：有台指期夜盤→用它；否則美股連動
    const actionPct = txfPct != null ? txfPct : usEst;
    const actionSrc = txfPct != null ? '台指期夜盤' : '美股連動預估';
    const txfCol = twCol(txfPct);
    const usCol = window.Colors ? Colors.dir('^TWII', usEst) : twCol(usEst);
    const actionCol = twCol(actionPct);
    const tone = toneOf(actionPct, actionSrc);
    // 分歧提示：台指 vs 美股方向不同
    let diverge = '';
    if (txfPct != null && usEst != null && ((txfPct > 0.3 && usEst < -0.3) || (txfPct < -0.3 && usEst > 0.3))) {
      diverge = `<div style="font-size:10px;color:#fbbf24;margin-top:4px">⚠ 台指期夜盤與美股連動方向分歧：以台指期夜盤為準</div>`;
    }

    // 持倉停損預警（用 actionPct＝台指優先）
    let posRows = '';
    const positions = ((typeof S !== 'undefined' && S.positions)) || {};
    for (const code in positions) {
      const p = positions[code];
      const cur = p.lastPrice;
      const stop = p.stop;
      if (cur == null) continue;
      const distStop = (stop != null && stop > 0) ? (cur - stop) / cur * 100 : null;
      const estPx = actionPct != null ? cur * (1 + actionPct / 100) : null;
      const breach = (stop != null && estPx != null && estPx <= stop);
      posRows += `<tr data-load="${code}"><td>${code}</td>
        <td>${cur.toFixed(2)}</td><td>${stop != null ? stop.toFixed(2) : '—'}</td>
        <td style="color:${distStop != null && distStop < 3 ? 'var(--red)' : 'var(--tlo)'}">${distStop != null ? distStop.toFixed(1) + '%' : '—'}</td>
        <td style="color:${breach ? 'var(--red)' : 'var(--tlo)'}">${estPx != null ? estPx.toFixed(2) : '—'}${breach ? ' ⚠破停損' : ''}</td></tr>`;
    }

    let wRows = '';
    const watches = ((typeof S !== 'undefined' && S.watches)) || {};
    for (const code in watches) {
      for (const sig of (watches[code].signals || [])) {
        if (sig.strategy !== 'custom_buy') continue;
        const tgt = sig.params && sig.params.target;
        if (!tgt) continue;
        const cur = (sig.lastEval && sig.lastEval.price) || null;
        const estPx = (cur != null && actionPct != null) ? cur * (1 + actionPct / 100) : null;
        const reach = (estPx != null && estPx <= tgt);
        wRows += `<tr data-load="${code}"><td>${code}</td><td>${cur != null ? cur.toFixed(2) : '—'}</td>
          <td>${(+tgt).toFixed(2)}</td>
          <td style="color:${reach ? 'var(--green)' : 'var(--tlo)'}">${estPx != null ? estPx.toFixed(2) : '—'}${reach ? ' ✓可能入買區' : ''}</td></tr>`;
      }
    }

    body.innerHTML = `
      <div class="dual">
        <div>
          <div style="font-size:10px;color:#38bdf8;text-align:center">台指期夜盤（主訊號）</div>
          <div class="gauge" style="color:${txfCol}">${pct(txfPct)}</div>
          <div style="font-size:11px;text-align:center;color:#94a3b8">${txf ? fmtIdx(txf.price) + '　昨收 ' + fmtIdx(txf.prevClose) : '尚無 /txf 資料'}</div>
        </div>
        <div>
          <div style="font-size:10px;color:#94a3b8;text-align:center">美股連動預估（輔）</div>
          <div class="gauge-sm" style="color:${usCol}">${usEst == null ? '—' : pct(usEst)}</div>
          <div style="font-size:10px;text-align:center;color:#64748b">NQ/ES/YM/SOX 加權</div>
        </div>
      </div>
      <div style="text-align:center;margin:2px 0 8px">
        <div style="font-size:11px;color:${actionCol};font-weight:700">${tone}</div>
        ${diverge}
      </div>
      ${renderTxfBlock(txf)}
      <table><thead><tr><th>夜盤領先指標</th><th>價</th><th>夜盤漲跌</th></tr></thead>
        <tbody>${txfRow}${drows}</tbody></table>
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
      <h3 style="font-size:12px;color:var(--red)">📉 持倉停損預警 <span style="font-size:10px;color:#64748b;font-weight:400">依 ${actionSrc}</span></h3>
      <table><thead><tr><th>代號</th><th>現價</th><th>停損</th><th>距停損</th><th>隔日預估價</th></tr></thead>
        <tbody>${posRows || '<tr><td colspan=5 style="text-align:center;color:var(--tf)">無持倉或未設停損</td></tr>'}</tbody></table>
      <h3 style="font-size:12px;color:var(--green)">📈 觀察股買區機會 <span style="font-size:10px;color:#64748b;font-weight:400">依 ${actionSrc}</span></h3>
      <table><thead><tr><th>代號</th><th>現價</th><th>買進價</th><th>隔日預估價</th></tr></thead>
        <tbody>${wRows || '<tr><td colspan=4 style="text-align:center;color:var(--tf)">觀察清單無自訂買進價訊號</td></tr>'}</tbody></table>
      <div style="font-size:9px;color:var(--tf);line-height:1.7;margin-top:8px;border-top:1px solid #222;padding-top:6px">
        <b style="color:var(--tlo)">資料來源</b>：台指期夜盤 <code>/txf</code>（Yahoo TW WTX& + TAIFEX MIS 夜盤）；美股期貨 <code>/yf</code><br>
        <b style="color:var(--tlo)">預警口徑</b>：有台指期夜盤 → 主用其漲跌%與振幅；美股 NQ/ES/YM/SOX 僅作連動對照<br>
        美股權重：NQ(35%) · ES(20%) · YM(10%) · SOX(35%)；核心連動 TSM ADR → 2330<br>
        更新時間：${new Date().toLocaleString('zh-TW', { hour12: false })} · 僅供參考，非投資建議
      </div>
      <div style="text-align:right;margin-top:8px">
        <button onclick="window.overnightRefresh&&overnightRefresh()">↻ 重新整理</button> <button onclick="window.overnightClose&&overnightClose()">關閉</button></div>`;

    body.querySelectorAll('[data-load]').forEach(tr => tr.onclick = () => {
      const c = tr.getAttribute('data-load');
      if (c === '__TXF__') {
        if (typeof loadSym === 'function') { loadSym('__TXF__', 'TW'); close(); }
        return;
      }
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

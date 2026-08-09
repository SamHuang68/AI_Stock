// ============================================================
// Stock Terminal v3.9 — 個股期夜盤領先指標 (Single-Stock Futures)
// ------------------------------------------------------------
// 市值前十大個股期貨(含夜盤)即時報價：期貨在現股收盤後續交易，反映隔日
//   預期，是現股的領先指標。顯示 期%/現%/領先差(期%−現%)，依期%排序，
//   點列載入該股線型。資料源：/stockfut?cid=<股期代碼>（TAIFEX MIS，近月自動換約）。
// CID 由 TAIFEX MIS 實查取得(非臆測)。工具列 🔭 個股期。
// 架構守則：狀態用裸 S(loadSym)；對外只掛 window.stockFut*。台股紅漲綠跌。
// ============================================================
(function () {
  'use strict';
  const SRV = (typeof window !== 'undefined' && window.SERVER) ? window.SERVER
    : (typeof SERVER !== 'undefined' ? SERVER : 'http://localhost:18432');

  // 市值前十大(可自行增刪)。cid=TAIFEX 股票期貨代碼(MIS KindID=4 實查)
  const LIST = [
    { code: '2330', name: '台積電', cid: 'CDF' },
    { code: '2317', name: '鴻海', cid: 'DHF' },
    { code: '2454', name: '聯發科', cid: 'DVF' },
    { code: '2308', name: '台達電', cid: 'FRF' },
    { code: '2382', name: '廣達', cid: 'DKF' },
    { code: '2891', name: '中信金', cid: 'CNF' },
    { code: '2882', name: '國泰金', cid: 'CKF' },
    { code: '2881', name: '富邦金', cid: 'CEF' },
    { code: '2412', name: '中華電', cid: 'DLF' },
    { code: '3711', name: '日月光投控', cid: 'OZF' },
  ];

  function pcls(c) { return c == null ? '' : c > 0 ? 'sf-up' : c < 0 ? 'sf-dn' : ''; }
  function fmt(c) { return c == null ? '—' : (c >= 0 ? '+' : '') + c.toFixed(2) + '%'; }

  function style() {
    if (document.getElementById('sf-style')) return;
    const s = document.createElement('style'); s.id = 'sf-style';
    s.textContent = `
    #sf-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #sf-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(620px,95vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #sf-box h3{margin:0 0 4px;font-size:15px;display:flex;align-items:center;gap:8px}
    #sf-box h3 .x{margin-left:auto;cursor:pointer;color:#94a3b8;font-size:18px}
    #sf-box .sub{font-size:10px;color:#64748b;margin-bottom:8px;line-height:1.5}
    .sf-tbl{width:100%;border-collapse:collapse;font-size:11.5px}
    .sf-tbl th,.sf-tbl td{padding:6px 6px;border-bottom:1px solid #1e293b;text-align:right;white-space:nowrap}
    .sf-tbl th{color:#64748b;font-weight:600;position:sticky;top:0;background:#0f172a}
    .sf-row{cursor:pointer}.sf-row:hover{background:#162033}
    .sf-tbl .sf-c{text-align:left;font-weight:700;color:#fbbf24}
    .sf-tbl .sf-n{text-align:left;color:#cbd5e1}
    .sf-up{color:#ef4444}.sf-dn{color:#22c55e}`;
    document.head.appendChild(s);
  }

  async function render() {
    const body = document.getElementById('sf-body');
    if (!body) return;
    body.innerHTML = '<div style="padding:14px;color:#64748b">載入中…（個股期含夜盤，TAIFEX）</div>';
    // 一次批次取(server 整批快取，避免 MIS 限流)
    let byCid = {};
    try {
      const cids = LIST.map(s => s.cid).join(',');
      const d = await fetch(`${SRV}/stockfut?cids=${encodeURIComponent(cids)}`, { cache: 'no-store' }).then(r => r.json());
      (d.results || []).forEach(r => { byCid[r.cid] = r; });
    } catch (e) {}
    const results = LIST.map(s => Object.assign({}, s, byCid[s.cid] || { ok: false }));
    results.sort((a, b) => (b.changePct == null ? -999 : b.changePct) - (a.changePct == null ? -999 : a.changePct));
    const sess = results.some(r => r.session === 'night') ? 'night' : (results.some(r => r.session === 'day') ? 'day' : null);
    const sessTxt = sess === 'night' ? '🌙 夜盤(盤後)' : sess === 'day' ? '☀ 日盤' : '—';
    const V = window.Viz;
    const sessChip = V
      ? (sess === 'night' ? V.chip('夜盤', 'warn') : sess === 'day' ? V.chip('日盤', 'ok') : V.chip('—', 'mid'))
      : `<b style="color:#fbbf24">${sessTxt}</b>`;
    let maxLead = 0;
    results.forEach(r => { if (r.lead != null && isFinite(r.lead)) maxLead = Math.max(maxLead, Math.abs(r.lead)); });
    let h = `<div style="font-size:11px;color:#94a3b8;margin-bottom:6px">盤別：${sessChip}　期%、現% 皆對昨收；領先=期%−現%</div>`;
    h += `<table class="sf-tbl"><tr><th>代號</th><th>名稱</th><th>期價</th><th>期%</th><th>現%</th><th>領先</th></tr>`;
    for (const r of results) {
      const leadTxt = r.lead == null ? '—' : (r.lead >= 0 ? '+' : '') + r.lead.toFixed(2);
      const leadBar = (V && maxLead && r.lead != null) ? V.rowBar(r.lead, maxLead) : '';
      const leadChip = (V && r.lead != null)
        ? V.chip(r.lead > 0 ? '期>現' : r.lead < 0 ? '期<現' : '期=現', r.lead > 0 ? 'hot' : r.lead < 0 ? 'cold' : 'mid')
        : '';
      h += `<tr class="sf-row" data-code="${r.code}">
        <td class="sf-c">${r.code}</td><td class="sf-n">${r.name}</td>
        <td>${r.price != null ? r.price : '—'}</td>
        <td class="${pcls(r.changePct)}">${fmt(r.changePct)}</td>
        <td class="${pcls(r.spotChangePct)}">${fmt(r.spotChangePct)}</td>
        <td class="${pcls(r.lead)}" title="期%−現%；正=期貨比現股強，隔日可能續強">${leadTxt}${leadBar}${leadChip}</td></tr>`;
    }
    h += `</table>`;
    body.innerHTML = h;
    body.querySelectorAll('.sf-row').forEach(el => el.onclick = () => {
      const c = el.getAttribute('data-code');
      if (typeof loadSym === 'function') { loadSym(c, 'TW'); close(); }
    });
  }

  function open() {
    style();
    let m = document.getElementById('sf-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'sf-modal';
      m.innerHTML = `<div id="sf-box"><h3>🔭 個股期夜盤領先 <span style="font-size:10px;color:#475569;font-weight:400">市值前十大</span><span class="x" onclick="window.stockFutClose&&stockFutClose()">×</span></h3>
        <div class="sub">期貨在現股收盤後續交易→反映隔日預期。「領先」=期%−現%，正值表示期貨比現股強、隔日有望續強(夜盤量淺，當方向參考)。依期%排序，點列載入線型。台股紅漲綠跌。</div>
        <div id="sf-body">載入中…</div>
        <div style="text-align:right;margin-top:8px"><button onclick="window.stockFutRefresh&&stockFutRefresh()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer">↻ 重新整理</button>
        <button onclick="window.stockFutClose&&stockFutClose()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer;margin-left:6px">關閉</button></div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    m.style.display = 'flex';
    render();
  }
  function close() { const m = document.getElementById('sf-modal'); if (m) m.style.display = 'none'; }

  window.stockFutOpen = open;
  window.stockFutClose = close;
  window.stockFutRefresh = render;
})();

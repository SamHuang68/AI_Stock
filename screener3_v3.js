// ============================================================
// Stock Terminal v3.9 — 三合一進階選股器 (Technical + Fundamental + Chip)
// ------------------------------------------------------------
// 技術面 + 基本面 + 籌碼面 任意組合，全台股宇集掃描 (後端 /screen3)：
//   技術：站上 SMA20/60、均線多頭排列、RSI 區間、量增倍數、創20日新高
//   基本：月營收 YoY ≥、PER ≤、殖利率 ≥
//   籌碼：投信連買 ≥ N 天、外資連買 ≥ N 天
// 結果一鍵載入 / 加入自選股 (Watchlist)。結果區獨立可捲動、限高，避免被擠出視窗。
// 架構守則：狀態用裸 S(S.wl/saveWl/renderWl/loadSym)；對外 window.screener3*。
// ============================================================
(function () {
  'use strict';
  const SRV = (typeof window !== 'undefined' && window.SERVER)
    ? window.SERVER
    : (typeof SERVER !== 'undefined' ? SERVER : 'http://localhost:18432');

  let sectors = [];
  let lastResults = [];

  async function loadMeta() {
    try {
      const r = await fetch(`${SRV}/screener`, { cache: 'no-store' }).then(x => x.ok ? x.json() : null);
      if (r) { sectors = r.sectors || []; return r; }
    } catch {}
    return null;
  }

  function readForm() {
    const v = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
    const ck = id => { const el = document.getElementById(id); return el ? el.checked : false; };
    const numOrNull = s => (s === '' ? null : parseFloat(s));
    const tech = {
      aboveSma20: ck('s3-sma20'), aboveSma60: ck('s3-sma60'), bullishAlign: ck('s3-align'),
      newHigh20: ck('s3-high20'),
      rsiMin: numOrNull(v('s3-rsimin')), rsiMax: numOrNull(v('s3-rsimax')),
      volRatioMin: numOrNull(v('s3-volr')),
    };
    const fund = {
      revYoyMin: numOrNull(v('s3-revyoy')), perMax: numOrNull(v('s3-permax')), yieldMin: numOrNull(v('s3-yield')),
    };
    const chip = {
      trustBuyDays: numOrNull(v('s3-trust')), foreignBuyDays: numOrNull(v('s3-foreign')),
    };
    const sector = v('s3-sector');
    return { tech, fund, chip, sector };
  }

  async function scan() {
    const msg = document.getElementById('s3-msg');
    const body = readForm();
    msg.textContent = '掃描中…（全台股宇集，基本面/籌碼條件越多越慢，請稍候）';
    document.getElementById('s3-results').innerHTML = '';
    try {
      const r = await fetch(`${SRV}/screen3`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(x => x.ok ? x.json() : null);
      if (!r) { msg.textContent = '掃描失敗（後端無回應）'; return; }
      lastResults = r.results || [];
      msg.innerHTML = `掃描 ${r.scanned} 檔 → 技術面通過 ${r.techPass} → 三條件交集 <b style="color:#fbbf24">${r.matched}</b> 檔` +
        (r.matched > 80 ? '（顯示前 80）' : '');
      renderResults(lastResults);
    } catch (e) { msg.textContent = '掃描錯誤：' + e.message; }
  }

  function cell(v, cls) { return `<td class="${cls || ''}">${v == null ? '—' : v}</td>`; }
  function renderResults(rows) {
    const el = document.getElementById('s3-results');
    if (!rows.length) { el.innerHTML = '<div style="color:#64748b;padding:14px;text-align:center">無符合條件的個股</div>'; return; }
    let h = `<div class="s3-rtop"><button id="s3-addall">＋ 全部加入自選股</button><span style="color:#475569;font-size:10px">點代號載入線型</span></div>`;
    h += `<table class="s3-tbl"><thead><tr><th>代號</th><th>名稱</th><th>價</th><th>漲跌</th><th>RSI</th><th>量比</th><th>營收YoY</th><th>PER</th><th>殖利</th><th>投信</th><th>外資</th><th></th></tr></thead><tbody>`;
    for (const r of rows) {
      const chgCls = (r.changePct >= 0) ? 'up' : 'dn';
      const streak = v => v == null ? '—' : (v > 0 ? '+' + v : v);
      h += `<tr>
        <td class="s3-code" data-sym="${r.sym}">${r.sym}</td>
        <td class="s3-nm">${r.name || ''}</td>
        ${cell(r.close)}
        ${cell((r.changePct >= 0 ? '+' : '') + (r.changePct == null ? '—' : r.changePct + '%'), chgCls)}
        ${cell(r.rsi14)}${cell(r.volRatio)}
        ${cell(r.revYoy == null ? null : r.revYoy + '%', r.revYoy >= 0 ? 'up' : 'dn')}
        ${cell(r.per)}${cell(r['yield'] == null ? null : r['yield'] + '%')}
        ${cell(streak(r.trustStreak), r.trustStreak > 0 ? 'up' : (r.trustStreak < 0 ? 'dn' : ''))}
        ${cell(streak(r.foreignStreak), r.foreignStreak > 0 ? 'up' : (r.foreignStreak < 0 ? 'dn' : ''))}
        <td><button class="s3-add" data-sym="${r.sym}" title="加入自選">＋</button></td>
      </tr>`;
    }
    h += `</tbody></table>`;
    el.innerHTML = h;
    el.querySelectorAll('.s3-code').forEach(td => td.onclick = () => { if (typeof loadSym === 'function') { loadSym(td.dataset.sym, 'TW'); close(); } });
    el.querySelectorAll('.s3-add').forEach(b => b.onclick = () => addWl(b.dataset.sym));
    const addall = document.getElementById('s3-addall');
    if (addall) addall.onclick = () => { rows.forEach(r => addWl(r.sym, true)); if (typeof renderWl === 'function') renderWl(); };
  }

  function addWl(sym, batch) {
    if (typeof S === 'undefined' || !Array.isArray(S.wl)) return;
    if (!S.wl.find(w => w.t === sym && w.m === 'TW')) S.wl.push({ t: sym, m: 'TW' });
    if (typeof saveWl === 'function') saveWl();
    if (!batch && typeof renderWl === 'function') renderWl();
  }

  function style() {
    if (document.getElementById('s3-style')) return;
    const s = document.createElement('style'); s.id = 's3-style';
    s.textContent = `
    #s3-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #s3-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(900px,96vw);max-height:92vh;display:flex;flex-direction:column;padding:16px;color:#e2e8f0;font-size:12px}
    #s3-box h3{margin:0 0 8px;font-size:15px;display:flex;align-items:center;gap:8px}
    #s3-box h3 .x{margin-left:auto;cursor:pointer;color:#94a3b8;font-size:18px}
    .s3-cols{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
    .s3-grp{border:1px solid #1e293b;border-radius:8px;padding:8px}
    .s3-grp h4{margin:0 0 6px;font-size:12px;color:#fbbf24}
    .s3-grp label{display:flex;align-items:center;gap:5px;margin:4px 0;font-size:11px;color:#cbd5e1}
    .s3-grp input[type=number]{width:58px;background:#0b1220;border:1px solid #334155;color:#e2e8f0;border-radius:4px;padding:2px 5px}
    .s3-bar{display:flex;gap:8px;align-items:center;margin:8px 0;flex-wrap:wrap}
    .s3-bar select{background:#0b1220;border:1px solid #334155;color:#cbd5e1;border-radius:5px;padding:5px}
    #s3-scan{background:rgba(251,191,36,.18);border:1px solid #fbbf24;color:#fbbf24;border-radius:6px;padding:6px 18px;cursor:pointer;font-weight:700}
    #s3-msg{font-size:11px;color:#94a3b8;margin:4px 0;min-height:14px}
    #s3-results{overflow:auto;flex:1;min-height:120px;max-height:48vh;border:1px solid #1e293b;border-radius:6px}
    .s3-rtop{display:flex;align-items:center;gap:10px;padding:6px 8px;position:sticky;top:0;background:#0f172a;border-bottom:1px solid #1e293b}
    #s3-addall{background:#1e293b;border:1px solid #334155;color:#cbd5e1;border-radius:5px;padding:3px 10px;cursor:pointer;font-size:11px}
    .s3-tbl{width:100%;border-collapse:collapse;font-size:11px}
    .s3-tbl th,.s3-tbl td{border-bottom:1px solid #1a2740;padding:4px 6px;text-align:right;white-space:nowrap}
    .s3-tbl th{color:#64748b;font-weight:600;position:sticky;top:31px;background:#0b1220}
    .s3-tbl td.up{color:#ef4444}.s3-tbl td.dn{color:#22c55e}
    .s3-tbl .s3-code{color:#fbbf24;font-weight:700;cursor:pointer;text-align:left}
    .s3-tbl .s3-nm{color:#94a3b8;text-align:left;max-width:96px;overflow:hidden;text-overflow:ellipsis}
    .s3-add{background:#1e293b;border:1px solid #334155;color:#4ade80;border-radius:4px;cursor:pointer;padding:1px 7px}`;
    document.head.appendChild(s);
  }

  async function open() {
    style();
    let m = document.getElementById('s3-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 's3-modal';
      m.innerHTML = `<div id="s3-box">
        <h3>🔬 三合一進階選股 <span style="font-size:10px;color:#475569;font-weight:400">技術 × 基本面 × 籌碼</span><span class="x" onclick="window.screener3Close&&screener3Close()">×</span></h3>
        <div class="s3-cols">
          <div class="s3-grp"><h4>技術面</h4>
            <label><input type="checkbox" id="s3-sma20"> 站上 SMA20</label>
            <label><input type="checkbox" id="s3-sma60"> 站上 SMA60</label>
            <label><input type="checkbox" id="s3-align"> 均線多頭排列</label>
            <label><input type="checkbox" id="s3-high20"> 創 20 日新高</label>
            <label>RSI ≥ <input type="number" id="s3-rsimin"> 且 ≤ <input type="number" id="s3-rsimax"></label>
            <label>量比 ≥ <input type="number" id="s3-volr" step="0.1" placeholder="1.5"></label>
          </div>
          <div class="s3-grp"><h4>基本面</h4>
            <label>月營收 YoY ≥ <input type="number" id="s3-revyoy" placeholder="20">%</label>
            <label>PER ≤ <input type="number" id="s3-permax" placeholder="30"></label>
            <label>殖利率 ≥ <input type="number" id="s3-yield" step="0.1" placeholder="3">%</label>
            <div style="font-size:9px;color:#475569;margin-top:6px">資料源：TWSE OpenAPI 月營收 / BWIBBU 本益比，整批快取一天。ETF 無基本面。</div>
          </div>
          <div class="s3-grp"><h4>籌碼面</h4>
            <label>投信連買 ≥ <input type="number" id="s3-trust" placeholder="3"> 天</label>
            <label>外資連買 ≥ <input type="number" id="s3-foreign" placeholder="3"> 天</label>
            <div style="font-size:9px;color:#475569;margin-top:6px">連續天數來自 chip_history（需每日累積；無紀錄則顯示 0）。</div>
          </div>
        </div>
        <div class="s3-bar">
          <select id="s3-sector"><option value="">全部產業</option><option value="__TECH__">科技電子整合</option></select>
          <button id="s3-scan">🔍 開始掃描</button>
          <span style="color:#475569;font-size:10px">空白條件=不限。建議至少勾 1~2 個技術條件以加速。</span>
        </div>
        <div id="s3-msg"></div>
        <div id="s3-results"></div>
      </div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
      m.querySelector('#s3-scan').onclick = scan;
    }
    m.style.display = 'flex';
    const meta = await loadMeta();
    if (meta && meta.sectors && meta.sectors.length) {
      const sel = document.getElementById('s3-sector');
      const cur = sel.value;
      sel.innerHTML = '<option value="">全部產業</option><option value="__TECH__">科技電子整合</option>' +
        meta.sectors.map(s => `<option value="${s}">${s}</option>`).join('');
      sel.value = cur;
    }
  }
  function close() { const m = document.getElementById('s3-modal'); if (m) m.style.display = 'none'; }

  window.screener3Open = open;
  window.screener3Close = close;
})();

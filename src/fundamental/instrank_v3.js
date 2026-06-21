// ============================================================
// Stock Terminal v3.8 — 外資 / 投信買賣超排行榜
// ------------------------------------------------------------
// 跨市場掃描主力動向：T86 全表依外資/投信買超或賣超排序，
// 並標連續買賣超天數(chip_history)。點股載入線型。僅台股。
// 資料源：/inst-rank?who=foreign|trust&side=buy|sell。工具列 🏆 法人榜。
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';
  let who = 'foreign', side = 'buy';

  function style() {
    if (document.getElementById('ir-style')) return;
    const s = document.createElement('style'); s.id = 'ir-style';
    s.textContent = `
    #ir-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #ir-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(960px,96vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    .ir-cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    @media(max-width:680px){.ir-cols{grid-template-columns:1fr}}
    #ir-box h3{margin:0 0 6px;font-size:15px}
    .ir-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
    .ir-tab{padding:4px 10px;border:1px solid #334155;border-radius:14px;cursor:pointer;font-size:11px;color:#94a3b8;background:#0b1220}
    .ir-tab.on{background:#fbbf24;color:#1a1a1a;border-color:#fbbf24;font-weight:700}
    .ir-tbl{width:100%;border-collapse:collapse;font-size:11px}
    .ir-tbl th,.ir-tbl td{padding:5px 6px;border-bottom:1px solid #1e293b;text-align:right}
    .ir-tbl th:nth-child(2),.ir-tbl td:nth-child(2){text-align:left}
    .ir-row{cursor:pointer}.ir-row:hover{background:#162033}
    .ir-up{color:#ef4444}.ir-dn{color:#22c55e}
    .ir-note{font-size:9px;color:#64748b;line-height:1.6;margin-top:8px}`;
    document.head.appendChild(s);
  }

  function tabs() {
    return `<div class="ir-tabs">
      <span class="ir-tab ${who === 'foreign' ? 'on' : ''}" data-who="foreign">外資</span>
      <span class="ir-tab ${who === 'trust' ? 'on' : ''}" data-who="trust">投信</span>
      <span style="width:10px"></span>
      <span class="ir-tab ${side === 'buy' ? 'on' : ''}" data-side="buy">買超榜</span>
      <span class="ir-tab ${side === 'sell' ? 'on' : ''}" data-side="sell">賣超榜</span>
    </div>`;
  }

  async function render() {
    const body = document.getElementById('ir-body');
    if (!body) return;
    body.innerHTML = tabs() + '<div style="padding:14px;color:#64748b">載入中…</div>';
    bindTabs();
    let d = {};
    try { d = await fetch(`${SRV}/inst-rank?who=${who}&side=${side}&n=30`, { cache: 'no-store' }).then(r => r.json()); } catch (e) {}
    const list = (d && d.list) || [];
    const buy = side === 'buy';
    const cls = buy ? 'ir-up' : 'ir-dn';
    const rowHtml = (x, rank) => {
      const st = x.streak;
      const stTxt = (st == null || st === 0) ? '' :
        (st > 0 ? `<span class="ir-up">連買${st}</span>` : `<span class="ir-dn">連賣${Math.abs(st)}</span>`);
      return `<tr class="ir-row" data-code="${x.code}"><td>${rank}</td><td>${x.code} <span style="color:#64748b">${x.name || ''}</span></td>
        <td class="${cls}">${x.lots == null ? '—' : (x.lots >= 0 ? '+' : '') + x.lots.toLocaleString()}</td>
        <td>${stTxt}</td></tr>`;
    };
    const buildTbl = (slice, offset) =>
      `<table class="ir-tbl"><tr><th>#</th><th>代號</th><th>張數</th><th>連續</th></tr>${slice.map((x, i) => rowHtml(x, offset + i + 1)).join('')}</table>`;
    const hdr = `${who === 'foreign' ? '外資' : '投信'}${buy ? '買超' : '賣超'}　${d.date || ''}　（前 30 名並排）`;
    body.innerHTML = tabs() + (list.length
      ? `<div style="font-size:11px;color:#94a3b8;margin:4px 0 6px">${hdr}</div>
         <div class="ir-cols"><div>${buildTbl(list.slice(0, 15), 0)}</div><div>${buildTbl(list.slice(15, 30), 15)}</div></div>`
      : `<div style="padding:14px;color:#64748b">無資料（T86 多為盤後發布，建議收盤後查）。</div>`)
      + `<div class="ir-note">外資買超榜＝權值與 AI 供應鏈主力動向；投信買超＝中小成長股認養。連續買超天數越長代表趨勢性買盤。點列載入線型。台股紅=買超綠=賣超。</div>`;
    bindTabs();
    body.querySelectorAll('.ir-row').forEach(el => el.onclick = () => {
      const c = el.getAttribute('data-code');
      if (typeof loadSym === 'function') { loadSym(c, 'TW'); close(); }
    });
  }

  function bindTabs() {
    document.querySelectorAll('#ir-body .ir-tab').forEach(el => el.onclick = () => {
      if (el.dataset.who) who = el.dataset.who;
      if (el.dataset.side) side = el.dataset.side;
      render();
    });
  }

  function open() {
    style();
    let m = document.getElementById('ir-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'ir-modal';
      m.innerHTML = `<div id="ir-box"><h3>🏆 外資 / 投信買賣超排行榜</h3><div id="ir-body">載入中…</div>
        <div style="text-align:right;margin-top:8px"><button onclick="window.instRankRefresh&&instRankRefresh()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer">↻ 重新整理</button>
        <button onclick="window.instRankClose&&instRankClose()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer;margin-left:6px">關閉</button></div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    m.style.display = 'flex';
    render();
  }
  function close() { const m = document.getElementById('ir-modal'); if (m) m.style.display = 'none'; }

  window.instRankOpen = open;
  window.instRankClose = close;
  window.instRankRefresh = render;
})();

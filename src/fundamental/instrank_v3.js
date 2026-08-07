// ============================================================
// Stock Terminal v3.8 — 外資 / 投信 / 自營商買賣超排行榜
// ------------------------------------------------------------
// 跨市場掃描主力動向：T86 全表依外資/投信/自營商買超或賣超排序，
// 並標連續買賣超天數(chip_history)。點股載入線型。僅台股。
// 資料源：/inst-rank?who=foreign|trust|dealer&side=buy|sell。工具列 🏆 法人榜。
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';
  let who = 'foreign', side = 'buy';

  function whoLabel(w) {
    return w === 'trust' ? '投信' : w === 'dealer' ? '自營商' : '外資';
  }

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
      <span class="ir-tab ${who === 'dealer' ? 'on' : ''}" data-who="dealer">自營商</span>
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
    const V = window.Viz;
    let maxAbs = 0;
    list.forEach(x => { if (x.lots != null && isFinite(x.lots)) maxAbs = Math.max(maxAbs, Math.abs(x.lots)); });
    const rowHtml = (x, rank) => {
      const st = x.streak;
      const stTxt = V
        ? V.streakChip(st, '')
        : ((st == null || st === 0) ? '' :
          (st > 0 ? `<span class="ir-up">連買${st}</span>` : `<span class="ir-dn">連賣${Math.abs(st)}</span>`));
      const lotsTxt = x.lots == null ? '—' : (x.lots >= 0 ? '+' : '') + x.lots.toLocaleString();
      const bar = (V && maxAbs && x.lots != null) ? V.rowBar(x.lots, maxAbs) : '';
      return `<tr class="ir-row" data-code="${x.code}"><td>${rank}</td><td>${x.code} <span style="color:#64748b">${x.name || ''}</span></td>
        <td class="${cls}">${lotsTxt}${bar}</td>
        <td>${stTxt}</td></tr>`;
    };
    const buildTbl = (slice, offset) =>
      `<table class="ir-tbl"><tr><th>#</th><th>代號</th><th>張數</th><th>連續</th></tr>${slice.map((x, i) => rowHtml(x, offset + i + 1)).join('')}</table>`;
    const hdr = `${whoLabel(who)}${buy ? '買超' : '賣超'}　${d.date || ''}　（前 30 名並排）`;
    body.innerHTML = tabs() + (list.length
      ? `<div style="font-size:11px;color:#94a3b8;margin:4px 0 6px">${hdr}</div>
         <div class="ir-cols"><div>${buildTbl(list.slice(0, 15), 0)}</div><div>${buildTbl(list.slice(15, 30), 15)}</div></div>`
      : `<div style="padding:14px;color:#64748b">無資料（T86 多為盤後發布，建議收盤後查）。</div>`)
      + `<div class="ir-note">外資買超＝權值與 AI 供應鏈主力；投信買超＝中小成長股認養；自營商＝券商自營＋避險盤（常與期現套利連動）。連續買超天數越長代表趨勢性買盤。點列載入線型。台股紅=買超綠=賣超。</div>`;
    bindTabs();
    // ── Tooltip 元素創建與事件註冊 ──
    let tip = document.getElementById('ir-tooltip');
    if (!tip) {
      tip = document.createElement('div');
      tip.id = 'ir-tooltip';
      document.body.appendChild(tip);
      const ts = document.createElement('style');
      ts.textContent = `
        #ir-tooltip {
          position: fixed; pointer-events: none; z-index: 10000; display: none;
          background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(8px);
          border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 8px;
          box-shadow: 0 10px 25px rgba(0, 0, 0, 0.6); padding: 8px 12px;
          color: #e2e8f0; font-family: monospace; font-size: 11px; line-height: 1.45;
          min-width: 140px;
        }
        .ir-tip-title { font-weight: 700; color: #94a3b8; font-size: 9px; margin-bottom: 2px; }
        .ir-tip-px { font-size: 14px; font-weight: 700; color: #fff; }
        .ir-tip-chg { font-weight: 700; font-size: 11px; margin-left: 6px; }
      `;
      document.head.appendChild(ts);
    }

    let hoveredCode = null;

    body.querySelectorAll('.ir-row').forEach(el => {
      const code = el.getAttribute('data-code');
      const name = el.querySelector('span')?.textContent || '';

      el.onclick = () => {
        hoveredCode = null;
        tip.style.display = 'none';
        if (typeof loadSym === 'function') { loadSym(code, 'TW'); close(); }
      };

      el.addEventListener('mouseenter', async (e) => {
        hoveredCode = code;
        tip.style.display = 'block';
        tip.innerHTML = `<div class="ir-tip-title">${code} ${name}</div><div style="color:#64748b;font-size:10px">載入中…</div>`;

        tip.style.left = (e.clientX + 14) + 'px';
        tip.style.top = (e.clientY + 14) + 'px';

        try {
          const res = await fetch(`${SRV}/twquote?code=${encodeURIComponent(code)}`, { cache: 'no-store' });
          if (!res.ok) return;
          const q = await res.json();
          if (hoveredCode !== code) return;

          if (q && q.price > 0) {
            const px = q.price;
            let chgPct = 0;
            if (q.prevClose > 0) {
              chgPct = (px - q.prevClose) / q.prevClose * 100;
            }
            const color = chgPct > 0 ? 'var(--red)' : chgPct < 0 ? 'var(--green)' : 'var(--thi)';
            const chgTxt = (chgPct >= 0 ? '+' : '') + chgPct.toFixed(2) + '%';

            tip.innerHTML = `
              <div class="ir-tip-title">${code} ${name}</div>
              <div style="display:flex;align-items:baseline;margin-top:2px">
                <span class="ir-tip-px">${px.toFixed(2)}</span>
                <span class="ir-tip-chg" style="color:${color}">${chgTxt}</span>
              </div>
              <div style="font-size:8px;color:#64748b;margin-top:4px">昨收 ${q.prevClose ? q.prevClose.toFixed(2) : '—'}</div>
            `;
          } else {
            tip.innerHTML = `<div class="ir-tip-title">${code} ${name}</div><div style="color:#ef4444;font-size:10px">無報價</div>`;
          }
        } catch (err) {
          if (hoveredCode === code) {
            tip.innerHTML = `<div class="ir-tip-title">${code} ${name}</div><div style="color:#ef4444;font-size:10px">連線錯誤</div>`;
          }
        }
      });

      el.addEventListener('mousemove', (e) => {
        tip.style.left = (e.clientX + 14) + 'px';
        tip.style.top = (e.clientY + 14) + 'px';
      });

      el.addEventListener('mouseleave', () => {
        hoveredCode = null;
        tip.style.display = 'none';
      });
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
      m.innerHTML = `<div id="ir-box"><h3>🏆 法人買賣超排行榜</h3><div id="ir-body">載入中…</div>
        <div style="text-align:right;margin-top:8px"><button onclick="window.instRankRefresh&&instRankRefresh()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer">↻ 重新整理</button>
        <button onclick="window.instRankClose&&instRankClose()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer;margin-left:6px">關閉</button></div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    m.style.display = 'flex';
    render();
  }
  function close() {
    const m = document.getElementById('ir-modal');
    if (m) m.style.display = 'none';
    const tip = document.getElementById('ir-tooltip');
    if (tip) tip.style.display = 'none';
  }

  window.instRankOpen = open;
  window.instRankClose = close;
  window.instRankRefresh = render;
})();

// ============================================================
// Stock Terminal v3.8 — 事件行事曆 + 提醒
// ------------------------------------------------------------
// 不漏接長線關鍵事件：月營收公布(規則制，每月10日前)、除權除息預告、
// 法說會。可帶 code 看單檔。資料源：/events[?code=2330]。工具列 📅 行事曆。
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';
  let onlyCurrent = false;

  function style() {
    if (document.getElementById('cal-style')) return;
    const s = document.createElement('style'); s.id = 'cal-style';
    s.textContent = `
    #cal-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #cal-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(560px,94vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #cal-box h3{margin:0 0 6px;font-size:15px}
    .cal-card{border:1px solid #1e293b;border-radius:8px;padding:10px;margin:8px 0;background:#0b1220}
    .cal-card h4{margin:0 0 6px;font-size:12px;color:#fbbf24}
    .cal-tbl{width:100%;border-collapse:collapse;font-size:11px}
    .cal-tbl th,.cal-tbl td{padding:4px 6px;border-bottom:1px solid #1e293b;text-align:left}
    .cal-row{cursor:pointer}.cal-row:hover{background:#162033}
    .cal-soon{color:#fbbf24;font-weight:700}
    .cal-toggle{font-size:10px;color:#94a3b8;cursor:pointer;user-select:none}
    .cal-note{font-size:9px;color:#64748b;line-height:1.6;margin-top:8px}`;
    document.head.appendChild(s);
  }

  async function render() {
    const body = document.getElementById('cal-body');
    if (!body) return;
    body.innerHTML = '載入中…';
    const code = (onlyCurrent && typeof S !== 'undefined' && S.sym && S.mkt === 'TW') ? S.sym : '';
    let d = {};
    try { d = await fetch(`${SRV}/events${code ? '?code=' + encodeURIComponent(code) : ''}`, { cache: 'no-store' }).then(r => r.json()); } catch (e) { body.innerHTML = '資料載入失敗。'; return; }

    // 月營收提醒
    let revCard = '';
    if (d.revenue) {
      const r = d.revenue, soon = r.daysAway != null && r.daysAway <= 5;
      revCard = `<div class="cal-card"><h4>📈 月營收公布</h4>
        <div>下次公布截止：<span class="${soon ? 'cal-soon' : ''}">${r.nextPublishBy}</span>（${r.forMonth} 營收，約 ${r.daysAway} 天後）</div>
        <div class="cal-note">台股上市櫃每月 10 日前須公布上月營收。月營收 YoY 是 AI 供應鏈動能的最即時訊號，比季報快、最值得盯。</div></div>`;
    }

    // 除權除息
    let exCard = '';
    const ex = (d.exDividend || []);
    if (ex.length) {
      const rows = ex.slice(0, 60).map(e =>
        `<tr class="cal-row" data-code="${e.code || ''}"><td>${e.date || ''}</td><td>${e.code || ''} ${e.name || ''}</td><td>${e.type || ''}</td></tr>`).join('');
      exCard = `<div class="cal-card"><h4>💵 除權除息${code ? '（' + code + '）' : '預告'}</h4>
        <table class="cal-tbl"><tr><th>日期</th><th>標的</th><th>類型</th></tr>${rows}</table>
        <div class="cal-note">除權息日前後注意填權息行情與股利稅務；長線持有者通常參與。</div></div>`;
    } else {
      exCard = `<div class="cal-card"><h4>💵 除權除息預告</h4><div class="cal-note">目前無預告資料（TWSE 資料集可能未開放或當期無資料）。</div></div>`;
    }

    body.innerHTML = `<div style="margin-bottom:4px"><span class="cal-toggle" id="cal-tg">${onlyCurrent ? '☑' : '☐'} 只看目前個股 ${(typeof S !== 'undefined' && S.sym) ? '(' + S.sym + ')' : ''}</span></div>
      ${revCard}${exCard}
      <div class="cal-note">⚠ 僅供參考、非投資建議。資料源 TWSE OpenData。</div>`;
    const tg = document.getElementById('cal-tg');
    if (tg) tg.onclick = () => { onlyCurrent = !onlyCurrent; render(); };
    body.querySelectorAll('.cal-row').forEach(el => el.onclick = () => {
      const c = el.getAttribute('data-code');
      if (c && typeof loadSym === 'function') { loadSym(c, 'TW'); close(); }
    });
  }

  function open() {
    style();
    let m = document.getElementById('cal-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'cal-modal';
      m.innerHTML = `<div id="cal-box"><h3>📅 事件行事曆</h3><div id="cal-body">載入中…</div>
        <div style="text-align:right;margin-top:8px"><button onclick="window.calendarRefresh&&calendarRefresh()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer">↻ 重新整理</button>
        <button onclick="window.calendarClose&&calendarClose()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer;margin-left:6px">關閉</button></div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    m.style.display = 'flex';
    render();
  }
  function close() { const m = document.getElementById('cal-modal'); if (m) m.style.display = 'none'; }

  window.calendarOpen = open;
  window.calendarClose = close;
  window.calendarRefresh = render;
})();

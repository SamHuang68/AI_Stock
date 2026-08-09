// ============================================================
// Stock Terminal v3.8 — 大盤資金流儀表板
// ------------------------------------------------------------
// 量化「結構性多頭」：成交量能趨勢(FMTQIK，呼應 8000億→1.2兆)、
// 三大法人買賣金額(BFI82U)、融資融券大盤(MI_MARGN)。僅台股。
// 資料源：/marketflow。工具列 💰 資金流。
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';

  function style() {
    if (document.getElementById('mf-style')) return;
    const s = document.createElement('style'); s.id = 'mf-style';
    s.textContent = `
    #mf-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #mf-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(680px,94vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #mf-box h3{margin:0 0 6px;font-size:15px}
    .mf-card{border:1px solid #1e293b;border-radius:8px;padding:10px;margin:8px 0;background:#0b1220}
    .mf-card h4{margin:0 0 6px;font-size:12px;color:#fbbf24}
    .mf-inst{display:flex;gap:8px}
    .mf-inst>div{flex:1;text-align:center;border:1px solid #1e293b;border-radius:6px;padding:7px}
    .mf-inst .k{font-size:9px;color:#64748b}
    .mf-inst .v{font-size:16px;font-weight:800;margin-top:2px}
    .mf-up{color:#ef4444}.mf-dn{color:#22c55e}
    .mf-note{font-size:9px;color:#64748b;line-height:1.6;margin-top:6px}`;
    document.head.appendChild(s);
  }

  const yi = v => v == null ? null : v / 1e8;        // 元 → 億
  const fyi = v => v == null ? '—' : (v >= 0 ? '+' : '') + (v / 1e8).toFixed(0) + ' 億';
  const cls = v => v == null ? '' : v > 0 ? 'mf-up' : v < 0 ? 'mf-dn' : '';

  function sparkline(vals, w = 600, h = 70) {
    if (!vals.length) return '';
    const min = Math.min(...vals), max = Math.max(...vals), rng = (max - min) || 1;
    const dx = w / Math.max(1, vals.length - 1);
    const pts = vals.map((v, i) => `${(i * dx).toFixed(1)},${(h - (v - min) / rng * (h - 8) - 4).toFixed(1)}`).join(' ');
    // 8000億 / 1兆2 參考線
    const yOf = v => (h - (v - min) / rng * (h - 8) - 4);
    const refs = [[8000, '#475569', '8000億'], [12000, '#fbbf24', '1.2兆']]
      .filter(([v]) => v >= min && v <= max)
      .map(([v, c, lbl]) => `<line x1="0" y1="${yOf(v).toFixed(1)}" x2="${w}" y2="${yOf(v).toFixed(1)}" stroke="${c}" stroke-dasharray="3,3" stroke-width="1"/><text x="2" y="${(yOf(v) - 2).toFixed(1)}" fill="${c}" font-size="8">${lbl}</text>`).join('');
    return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:${h}px">${refs}<polyline points="${pts}" fill="none" stroke="#38bdf8" stroke-width="1.5"/></svg>`;
  }

  async function render() {
    const body = document.getElementById('mf-body');
    if (!body) return;
    body.innerHTML = '載入中…';
    let d = {};
    try { d = await fetch(`${SRV}/marketflow`, { cache: 'no-store' }).then(r => r.json()); } catch (e) { body.innerHTML = '資料載入失敗。'; return; }

    // 量能趨勢（成交金額，億元）
    const to = (d.turnover || []).filter(x => x.amount != null);
    const amts = to.map(x => x.amount / 1e8);
    let turnoverCard = '';
    if (amts.length) {
      const latest = amts[amts.length - 1], avg = amts.reduce((a, b) => a + b, 0) / amts.length;
      const tone = latest >= 12000 ? '<b class="mf-up">爆量(突破1.2兆)</b>' : latest >= 10000 ? '<b class="mf-up">明顯放量(兆級)</b>'
        : latest >= 8000 ? '量能健康(8000億+)' : '<b class="mf-dn">量縮(低於8000億)</b>';
      turnoverCard = `<div class="mf-card"><h4>📊 大盤量能趨勢（成交金額）</h4>
        <div style="font-size:11px">最新 <b>${latest.toFixed(0)} 億</b>　當月均量 ${avg.toFixed(0)} 億　判讀：${tone}</div>
        ${sparkline(amts)}
        <div class="mf-note">量能是市場派的結構訊號：你的核心論點——台股日均量從 ~8000億(2026/4 前)升到 1.2兆+，反映 4 大 CSP 資本支出集中台灣供應鏈，是結構偏多的底層動能。</div></div>`;
    }

    // 三大法人買賣金額（億元，正=買超）
    let instCard = '';
    if (d.inst) {
      const i = d.inst, total = (i.foreign || 0) + (i.trust || 0) + (i.dealer || 0);
      const V = window.Viz;
      const yiFmt = v => v == null || !isFinite(v) ? '—' : (v >= 0 ? '+' : '') + v.toFixed(0) + ' 億';
      const bars = V ? V.magBars([
        { label: '外資', v: yi(i.foreign), fmt: yiFmt },
        { label: '投信', v: yi(i.trust), fmt: yiFmt },
        { label: '自營', v: yi(i.dealer), fmt: yiFmt },
      ]) : '';
      instCard = `<div class="mf-card"><h4>🏦 三大法人買賣超（${i.date || ''}）</h4>
        <div class="mf-inst">
          <div><div class="k">外資</div><div class="v ${cls(i.foreign)}">${fyi(i.foreign)}</div></div>
          <div><div class="k">投信</div><div class="v ${cls(i.trust)}">${fyi(i.trust)}</div></div>
          <div><div class="k">自營商</div><div class="v ${cls(i.dealer)}">${fyi(i.dealer)}</div></div>
          <div><div class="k">合計</div><div class="v ${cls(total)}">${fyi(total)}</div></div>
        </div>
        ${bars ? `<div style="padding:4px 2px 2px">${bars}</div>` : ''}
        <div class="mf-note">外資是台股權值股(含 2330)的主要邊際買盤，方向常領先大盤；投信偏中小型成長股。台股紅=買超、綠=賣超。</div></div>`;
    }

    body.innerHTML = `<div style="font-size:11px;color:#94a3b8;margin-bottom:4px">資料日 ${d.date || '—'}</div>
      ${turnoverCard || ''}${instCard || ''}
      ${(!turnoverCard && !instCard) ? '<div class="mf-note">TWSE 盤中資料可能尚未更新，建議盤後再查（FMTQIK/BFI82U 多為收盤後發布）。</div>' : ''}
      <div class="mf-note">⚠ 僅供參考、非投資建議。資料源 TWSE OpenData。</div>`;
  }

  function open() {
    style();
    let m = document.getElementById('mf-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'mf-modal';
      m.innerHTML = `<div id="mf-box"><h3>💰 大盤資金流儀表板</h3><div id="mf-body">載入中…</div>
        <div style="text-align:right;margin-top:8px"><button onclick="window.marketFlowRefresh&&marketFlowRefresh()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer">↻ 重新整理</button>
        <button onclick="window.marketFlowClose&&marketFlowClose()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer;margin-left:6px">關閉</button></div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    m.style.display = 'flex';
    render();
  }
  function close() { const m = document.getElementById('mf-modal'); if (m) m.style.display = 'none'; }

  window.marketFlowOpen = open;
  window.marketFlowClose = close;
  window.marketFlowRefresh = render;
})();

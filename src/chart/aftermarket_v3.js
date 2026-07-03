// ============================================================
// Stock Terminal v3.8 — 盤後/盤前延伸交易 (After / Pre Market)
// ------------------------------------------------------------
// 美股有真實盤前/盤後價格 (Yahoo includePrePost)；台股個股無真實
// 盤後波動(盤後定價=收盤)故不顯示。
// 呈現：
//   1. chart-info 主價格下方 盤後/盤前 標籤
//   2. STATS 分頁 盤後/盤前 區塊
//   3. 自選股 US chip 角落小標記
// 資料源：server /quote/<sym> (含 postMarketPrice/preMarketPrice)
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';
  const _amCache = {};   // sym -> {data, ts}
  const TTL = 20000;

  async function fetchAM(sym) {
    const c = _amCache[sym];
    if (c && Date.now() - c.ts < TTL) return c.data;
    try {
      const r = await fetch(`${SRV}/quote/${sym}`, { cache: 'no-store' });
      if (!r.ok) return null;
      const d = await r.json();
      _amCache[sym] = { data: d, ts: Date.now() };
      return d;
    } catch { return null; }
  }

  // 回傳盤後/盤前資訊或 null（僅在 PRE/POST 且有 ext 價時）
  function extInfo(q) {
    if (!q) return null;
    const st = q.marketState || '';
    const reg = q.price;
    if (st === 'POST' || st === 'POSTPOST') {
      if (q.postMarketPrice == null || reg == null) return null;
      return mk('盤後', q.postMarketPrice, reg, q.postMarketChangePct);
    }
    if (st === 'PRE') {
      if (q.preMarketPrice == null || reg == null) return null;
      return mk('盤前', q.preMarketPrice, reg, q.preMarketChangePct);
    }
    return null;
  }
  function mk(label, px, reg, pctRaw) {
    // 以盤後價 vs 一般收盤價自算 %（避免 Yahoo pct 單位不一致）
    let pct = (reg ? (px - reg) / reg * 100 : null);
    if (pct == null && pctRaw != null) pct = pctRaw;
    return { label, px, pct };
  }
  const col = p => window.Colors ? Colors.dir(S.sym, p) : (p == null ? 'var(--tlo)' : p > 0 ? 'var(--green)' : p < 0 ? 'var(--red)' : 'var(--tlo)');
  const fmt = e => `${e.label} ${e.px.toFixed(2)} ${e.pct == null ? '' : (e.pct >= 0 ? '▲' : '▼') + Math.abs(e.pct).toFixed(2) + '%'}`;

  // ---- 1. chart-info 標籤 (active symbol) ------------------
  function updateChartInfoTag(e) {
    const host = document.getElementById('chart-info');
    if (!host) return;
    let tag = document.getElementById('am-tag');
    if (!e) { if (tag) tag.remove(); return; }
    if (!tag) {
      tag = document.createElement('div');
      tag.id = 'am-tag';
      tag.style.cssText = 'font-size:10px;font-weight:700;margin-top:2px';
      host.appendChild(tag);
    }
    tag.style.color = col(e.pct);
    tag.textContent = '🌙 ' + fmt(e);
  }

  // ---- 2. STATS 區塊 ---------------------------------------
  function statsHtml(e) {
    if (!e) return '';
    return `<div id="am-sect"><div class="stat-sect">${e.label}延伸交易</div>
      <div class="stat-row"><span class="stat-k">${e.label}價</span><span class="stat-v" style="color:${col(e.pct)}">${e.px.toFixed(2)}</span></div>
      <div class="stat-row"><span class="stat-k">${e.label}漲跌</span><span class="stat-v" style="color:${col(e.pct)}">${e.pct == null ? '—' : (e.pct >= 0 ? '+' : '') + e.pct.toFixed(2) + '%'}</span></div></div>`;
  }
  function refreshActive() {
    if (typeof S === 'undefined' || !S.sym || S.mkt !== 'US') { updateChartInfoTag(null); return; }
    fetchAM(S.sym).then(q => {
      const e = extInfo(q);
      updateChartInfoTag(e);
      if (S.tab === 'stats') {
        const stats = document.getElementById('rpanel');
        const ex = document.getElementById('am-sect');
        if (e && stats) { const h = statsHtml(e); if (ex) ex.outerHTML = h; else stats.insertAdjacentHTML('beforeend', h); }
        else if (ex) ex.remove();
      }
    });
  }

  // ---- 3. 自選股 US chip 角標 ------------------------------
  function refreshChips() {
    const chips = document.querySelectorAll('.wlchip[data-mkt="US"]');
    chips.forEach(chip => {
      const sym = chip.getAttribute('data-sym');
      if (!sym) return;
      fetchAM(sym).then(q => {
        const e = extInfo(q);
        let dot = chip.querySelector('.am-dot');
        if (!e) { if (dot) dot.remove(); return; }
        if (!dot) {
          dot = document.createElement('span');
          dot.className = 'am-dot';
          dot.style.cssText = 'position:absolute;top:2px;right:2px;font-size:8px;line-height:1;pointer-events:none';
          chip.appendChild(dot);
        }
        dot.title = fmt(e);
        dot.style.color = col(e.pct);
        dot.textContent = '🌙';
      });
    });
  }

  function tick() { refreshActive(); refreshChips(); }
  window.addEventListener('symLoaded', () => setTimeout(refreshActive, 150));
  setInterval(tick, 30000);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => setTimeout(tick, 1500));
  else setTimeout(tick, 1500);

  window.afterMarketRefresh = tick;
})();

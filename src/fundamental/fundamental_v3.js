// ============================================================
// Stock Terminal v3.8 — 基本面面板 (Fundamental)
// ------------------------------------------------------------
// 在 STATS 分頁加「基本面」section：
//   • 月營收 當月 / YoY / MoM / 累計YoY
//   • 損益表三率：毛利率 / 營益率 / 淨利率 + EPS
//   • 基本面評分 0~100（成長性 + 獲利性）
// 資料源：server /fundamental/<sym> (TWSE OpenAPI 全市場資料集)
// 與技術面 WATCH 共識評分並列 → 技術 x 基本面 雙軸。
// ============================================================
(function () {
  const SRV = window.SERVER || 'http://localhost:18432';
  const _fCache = {};

  async function fetchFund(sym, mkt) {
    if (!sym || mkt !== 'TW') return null;
    if (_fCache[sym]) return _fCache[sym];
    try {
      const r = await fetch(`${SRV}/fundamental/${sym}`, { cache: 'no-store' });
      if (!r.ok) return null;
      const d = await r.json();
      _fCache[sym] = d;
      return d;
    } catch (e) { console.warn('[fundamental]', e); return null; }
  }

  const fmtMoney = v => v == null ? '—' :
    (Math.abs(v) >= 1e8 ? (v / 1e8).toFixed(1) + ' 億' :
      Math.abs(v) >= 1e4 ? (v / 1e4).toFixed(0) + ' 萬' : Math.round(v).toLocaleString());
  // 方向性成長(YoY/MoM/累計)→ 顏色管理表(台股 正=紅/負=綠);水準型(三率)→ warn(偏低琥珀)
  const pctCol = v => window.Colors ? Colors.growth(S.sym, v)
    : (v == null ? 'var(--tlo)' : v > 0 ? 'var(--red)' : v < 0 ? 'var(--green)' : 'var(--tlo)');
  const pctStr = v => v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
  const marginCol = v => window.Colors ? Colors.warn(v, { lo: 8 })
    : (v == null ? 'var(--tlo)' : v < 8 ? 'var(--orange)' : 'var(--thi)');

  function scoreBadge(s) {
    if (s == null) return '';
    const col = window.Colors ? Colors.quality(s, 70, 50) : (s >= 70 ? 'var(--red)' : s >= 50 ? 'var(--orange)' : 'var(--green)');
    const lbl = s >= 70 ? '體質佳' : s >= 50 ? '中性' : '偏弱';
    return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
  }

  function render(f) {
    if (!f || (!f.revenue && !f.income)) {
      return '<div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px;line-height:1.7">無基本面資料<br><span style="font-size:9px;color:var(--tf)">TWSE OpenAPI 僅上市櫃普通股；金融/ETF 部分欄位缺</span></div>';
    }
    let h = '';
    if (f.score != null)
      h += `<div class="stat-row" style="font-weight:700"><span class="stat-k">基本面評分</span><span class="stat-v">${scoreBadge(f.score)}</span></div>`;
    const r = f.revenue;
    if (r) {
      h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">月營收 ${r.period || ''}</span><span class="stat-v">${fmtMoney(r.monthRev)}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">YoY 年增</span><span class="stat-v" style="color:${pctCol(r.yoyPct)}">${pctStr(r.yoyPct)}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">MoM 月增</span><span class="stat-v" style="color:${pctCol(r.momPct)}">${pctStr(r.momPct)}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">累計營收 YoY</span><span class="stat-v" style="color:${pctCol(r.cumYoyPct)}">${pctStr(r.cumYoyPct)}</span></div>`;
    }
    const inc = f.income;
    if (inc) {
      h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">財報 ${inc.period || ''}</span><span class="stat-v">EPS ${inc.eps != null ? inc.eps.toFixed(2) : '—'}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">毛利率</span><span class="stat-v" style="color:${marginCol(inc.grossMargin)}">${inc.grossMargin != null ? inc.grossMargin.toFixed(1) + '%' : '—'}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">營益率</span><span class="stat-v" style="color:${marginCol(inc.opMargin)}">${inc.opMargin != null ? inc.opMargin.toFixed(1) + '%' : '—'}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">淨利率</span><span class="stat-v" style="color:${marginCol(inc.netMargin)}">${inc.netMargin != null ? inc.netMargin.toFixed(1) + '%' : '—'}</span></div>`;
    }
    h += `<div style="padding:6px 12px 0;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.5">資料：TWSE OpenAPI 月營收 + 綜合損益表</div>`;
    return h;
  }

  (function patch() {
    if (typeof renderStats !== 'function') return setTimeout(patch, 120);
    if (window._fundPatched) return;
    window._fundPatched = true;
    const orig = window.renderStats;
    window.renderStats = function () {
      let h = orig.apply(this, arguments);
      if (!S.sym || S.mkt !== 'TW') return h;
      fetchFund(S.sym, S.mkt).then(f => {
        const stats = document.getElementById('rpanel');
        if (!stats || S.tab !== 'stats') return;
        const ex = document.getElementById('fund-sect');
        const html = `<div id="fund-sect"><div class="stat-sect">基本面 · ${S.sym}</div>${render(f)}</div>`;
        if (ex) ex.outerHTML = html;
        else stats.insertAdjacentHTML('beforeend', html);
      });
      return h + `<div id="fund-sect"><div class="stat-sect">基本面 · ${S.sym}</div><div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px">載入基本面中...</div></div>`;
    };
  })();

  window.fetchFund = fetchFund;
})();

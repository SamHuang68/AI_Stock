// ============================================================
// Stock Terminal v3.8 — 基本面面板 (Fundamental)
// ------------------------------------------------------------
// 在 STATS 分頁加「基本面」section：
//   • TW：月營收 當月 / YoY / MoM / 累計YoY + 三率（TWSE OpenAPI）
//   • US：營收／盈餘成長 + 三率（Yahoo keystats，與 /valuation 同源）
//   • 基本面評分 0~100（成長性 + 獲利性；台美同一公式）
// 與技術面雙軸卡並列。
// ============================================================
(function () {
  const SRV = window.SERVER || 'http://localhost:18432';
  const _fCache = {};

  async function fetchFund(sym, mkt) {
    if (!sym) return null;
    mkt = (mkt || 'TW').toUpperCase();
    const key = sym.toUpperCase() + '|' + mkt;
    if (_fCache[key]) return _fCache[key];
    try {
      const r = await fetch(`${SRV}/fundamental/${encodeURIComponent(sym)}`, { cache: 'no-store' });
      if (!r.ok) return null;
      const d = await r.json();
      _fCache[key] = d;
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
    const isUs = f && (f.market === 'US' || (S && S.mkt === 'US'));
    if (!f || (!f.revenue && !f.income)) {
      const hint = isUs
        ? 'Yahoo 成長／三率暫無資料（可檢查本機是否可連 Yahoo / 已裝 yfinance）'
        : 'TWSE OpenAPI 僅上市櫃普通股；金融/ETF 部分欄位缺';
      return `<div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px;line-height:1.7">無基本面資料<br><span style="font-size:9px;color:var(--tf)">${hint}</span></div>`;
    }
    let h = '';
    if (f.score != null)
      h += `<div class="stat-row" style="font-weight:700"><span class="stat-k">基本面評分</span><span class="stat-v">${scoreBadge(f.score)}</span></div>`;
    const r = f.revenue;
    if (r) {
      if (isUs || r.monthRev == null) {
        // 美股：無「月營收」金額，改顯示成長標題
        h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">成長 ${r.period || ''}</span><span class="stat-v">${r.label || 'Yahoo'}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">營收成長 YoY</span><span class="stat-v" style="color:${pctCol(r.yoyPct)}">${pctStr(r.yoyPct)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">盈餘成長</span><span class="stat-v" style="color:${pctCol(r.cumYoyPct)}">${pctStr(r.cumYoyPct)}</span></div>`;
      } else {
        h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">月營收 ${r.period || ''}</span><span class="stat-v">${fmtMoney(r.monthRev)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">YoY 年增</span><span class="stat-v" style="color:${pctCol(r.yoyPct)}">${pctStr(r.yoyPct)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">MoM 月增</span><span class="stat-v" style="color:${pctCol(r.momPct)}">${pctStr(r.momPct)}</span></div>`;
        h += `<div class="stat-row"><span class="stat-k">累計營收 YoY</span><span class="stat-v" style="color:${pctCol(r.cumYoyPct)}">${pctStr(r.cumYoyPct)}</span></div>`;
      }
    }
    const inc = f.income;
    if (inc) {
      h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">財報 ${inc.period || ''}</span><span class="stat-v">EPS ${inc.eps != null ? Number(inc.eps).toFixed(2) : '—'}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">毛利率</span><span class="stat-v" style="color:${marginCol(inc.grossMargin)}">${inc.grossMargin != null ? Number(inc.grossMargin).toFixed(1) + '%' : '—'}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">營益率</span><span class="stat-v" style="color:${marginCol(inc.opMargin)}">${inc.opMargin != null ? Number(inc.opMargin).toFixed(1) + '%' : '—'}</span></div>`;
      h += `<div class="stat-row"><span class="stat-k">淨利率</span><span class="stat-v" style="color:${marginCol(inc.netMargin)}">${inc.netMargin != null ? Number(inc.netMargin).toFixed(1) + '%' : '—'}</span></div>`;
      if (inc.roe != null)
        h += `<div class="stat-row"><span class="stat-k">ROE</span><span class="stat-v" style="color:${marginCol(inc.roe)}">${Number(inc.roe).toFixed(1)}%</span></div>`;
    }
    const src = isUs
      ? `資料：Yahoo Finance（${f._source || 'keystats'}）成長 + 三率`
      : '資料：TWSE OpenAPI 月營收 + 綜合損益表';
    h += `<div style="padding:6px 12px 0;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.5">${src}</div>`;
    return h;
  }

  (function patch() {
    if (typeof renderStats !== 'function') return setTimeout(patch, 120);
    if (window._fundPatched) return;
    window._fundPatched = true;
    const orig = window.renderStats;
    window.renderStats = function () {
      let h = orig.apply(this, arguments);
      if (!S.sym) return h;
      // 台／美皆顯示基本面；籌碼等仍僅台股（資料源限制）
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

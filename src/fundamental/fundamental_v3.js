// ============================================================
// Stock Terminal v3.8 — 基本面面板 (Fundamental)
// ------------------------------------------------------------
// 在 STATS 分頁加「基本面」section：
//   • TW：月營收 當月 / YoY / MoM / 累計YoY + 三率（TWSE OpenAPI）
//   • US：營收／盈餘成長 + 三率（Yahoo keystats，與 /valuation 同源）
//   • 台股大盤（^TWII/^TWOII／融資維持）：大盤體質（量能+法人+融資+估值）
//   • 美總經（美利率債／CPI金融）：市場風險白話摘要（詳細公式見主圖 ?）
//   • 基本面評分 0~100（個股：成長+獲利；大盤：四支柱平均）
// 與技術面雙軸卡並列。
// ============================================================
(function () {
  const SRV = window.SERVER || 'http://localhost:18432';
  const _fCache = {};
  const _fInflight = {};

  async function fetchFund(sym, mkt) {
    if (!sym) return null;
    mkt = (mkt || 'TW').toUpperCase();
    const key = sym.toUpperCase() + '|' + mkt;
    // 市場風險／大盤體質／融資週期可能隨視窗重算 → 優先用主圖最新 payload（須同代號）
    if (window.S && S._fundPanelPayload && String(S.sym || '').toUpperCase() === String(sym).toUpperCase()) {
      const live = S._fundPanelPayload;
      const liveSym = String((live && (live.symbol || live.code)) || (S && S._marketChartId) || '').toUpperCase();
      const want = String(sym).toUpperCase();
      if (live && (live.kind === 'market' || live.kind === 'market_risk' || live.kind === 'margin_cycle' || live.kind === 'holders') &&
          (!liveSym || liveSym === want || liveSym.replace(/^\^/, '') === want.replace(/^\^/, ''))) {
        return live;
      }
    }
    if (_fCache[key]) return _fCache[key];
    if (_fInflight[key]) return _fInflight[key];
    _fInflight[key] = (async function () {
      try {
        const traceId = 'fund-ui-' + Date.now() + '-' + String(sym).replace(/[^A-Z0-9.^_=:-]/gi, '').slice(0, 24);
        // Correlation id stays in the query string so localhost/127.0.0.1
        // deployments remain a simple CORS GET (a custom header triggers an
        // OPTIONS preflight that the lightweight local server does not need).
        const r = await fetch(`${SRV}/fundamental/${encodeURIComponent(sym)}?traceId=${encodeURIComponent(traceId)}`, {
          cache: 'no-store'
        });
        if (!r.ok) return null;
        const d = await r.json();
        _fCache[key] = d;
        return d;
      } catch (e) {
        console.warn('[fundamental]', e);
        return null;
      } finally {
        delete _fInflight[key];
      }
    })();
    return _fInflight[key];
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
  const pillarCol = s => window.Colors ? Colors.quality(s, 70, 50)
    : (s == null ? 'var(--tlo)' : s >= 70 ? 'var(--red)' : s >= 50 ? 'var(--orange)' : 'var(--green)');
  const riskCol = s => {
    if (s == null) return 'var(--tlo)';
    if (s >= 70) return '#f87171';
    if (s >= 55) return '#fb923c';
    if (s >= 45) return '#94a3b8';
    return '#4ade80';
  };

  function scoreBadge(s, kind) {
    if (s == null) return '';
    if (kind === 'market_risk') {
      const col = riskCol(s);
      const lbl = s >= 70 ? '風險偏高' : s >= 55 ? '風險中偏高' : s >= 45 ? '風險中性' : '風險偏低';
      return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
    }
    if (kind === 'margin_cycle') {
      const col = s >= 75 ? '#f87171' : s >= 55 ? '#fb923c' : s >= 30 ? '#94a3b8' : '#4ade80';
      const lbl = s >= 75 ? '擁擠高潮' : s >= 55 ? '偏熱' : s >= 30 ? '修復／中性' : '清算區';
      return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
    }
    if (kind === 'holders') {
      const col = s >= 70 ? '#f87171' : s >= 55 ? '#fb923c' : s >= 45 ? '#94a3b8' : '#4ade80';
      const lbl = s >= 70 ? '高度集中' : s >= 55 ? '集中中' : s >= 45 ? '中性' : s >= 30 ? '偏發散' : '發散';
      return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
    }
    const col = window.Colors ? Colors.quality(s, 70, 50) : (s >= 70 ? 'var(--red)' : s >= 50 ? 'var(--orange)' : 'var(--green)');
    const lbl = kind === 'market'
      ? (s >= 70 ? '偏熱／偏強' : s >= 50 ? '中性' : '偏弱／偏冷')
      : (s >= 70 ? '體質佳' : s >= 50 ? '中性' : '偏弱');
    return `<span style="display:inline-block;padding:1px 8px;border-radius:10px;background:${col};color:#0b1220;font-weight:700;font-size:11px">${s} ${lbl}</span>`;
  }

  /** STATS：只放白話摘要；完整公式在主圖「?」 */
  function renderPlainMarket(f) {
    const title = f.title || (f.kind === 'market_risk' ? '市場風險' : (f.kind === 'margin_cycle' ? '融資週期' : (f.kind === 'holders' ? '籌碼集中度' : '大盤體質')));
    const kind = f.kind === 'market_risk' ? 'market_risk' : (f.kind === 'margin_cycle' ? 'margin_cycle' : (f.kind === 'holders' ? 'holders' : 'market'));
    let h = '';
    const V = window.Viz;
    if (f.score != null) {
      h += `<div class="stat-row" style="font-weight:700"><span class="stat-k">${title}</span><span class="stat-v">${scoreBadge(f.score, kind)}</span></div>`;
      if (V) h += `<div style="padding:0 12px 4px">${V.scoreMeter(f.score)}</div>`;
    }
    const plain = f.plainSummary || f.summary || '';
    if (plain) {
      h += `<div style="padding:10px 12px;color:var(--text);font-family:monospace;font-size:10.5px;line-height:1.65">${plain}</div>`;
    }
    const rows = f.marketRows || [];
    if (rows.length) {
      h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">支柱一覽</span><span class="stat-v">點主圖 ? 看完整算法</span></div>`;
      rows.forEach(row => {
        const sc = row.score;
        const col = kind === 'market_risk' || kind === 'margin_cycle' || kind === 'holders'
          ? (sc == null ? 'var(--tlo)' : sc >= 70 ? '#f87171' : sc >= 55 ? '#fb923c' : sc >= 45 ? '#94a3b8' : '#4ade80')
          : pillarCol(sc);
        h += `<div class="stat-row"><span class="stat-k">${row.k}</span>` +
          `<span class="stat-v">${row.v}` +
          (sc != null ? ` <span style="color:${col};font-size:9px">(${Math.round(sc)})</span>` : '') +
          `</span></div>`;
        if (V && sc != null) h += `<div style="padding:0 12px 2px">${V.scoreMeter(sc, { color: col })}</div>`;
      });
    } else if (!plain) {
      h += `<div style="padding:10px 12px;color:var(--tlo);font-family:monospace;font-size:10px">資料暫缺</div>`;
    }
    h += `<div style="padding:6px 12px 0;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.5">` +
      `資料：${f._source || '—'} · 詳細公式請點主圖資訊列「?」` +
      `</div>`;
    return h;
  }

  function renderEmpty(f) {
    const note = (f && f._note) || '';
    const isIntl = f && (f.market === 'US' || f.market === 'JP' || (S && S.mkt !== 'TW'));
    const kind = f && f.kind;
    let hint;
    if (kind === 'macro' || kind === 'index')
      hint = note || (kind === 'macro' ? '總經序列無個股基本面' : '指數無公司財報評分');
    else if (isIntl)
      hint = 'Yahoo 成長／三率暫無資料（可檢查本機是否可連 Yahoo / 已裝 yfinance）';
    else
      hint = 'TWSE OpenAPI 僅上市櫃普通股；金融/ETF 部分欄位缺';
    return `<div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px;line-height:1.7">無基本面資料<br><span style="font-size:9px;color:var(--tf)">${hint}</span></div>`;
  }

  function render(f) {
    if (f && (f.kind === 'market' || f.kind === 'market_risk' || f.kind === 'margin_cycle' || f.kind === 'holders')) return renderPlainMarket(f);
    const isIntl = f && (f.market === 'US' || f.market === 'JP' || (S && S.mkt !== 'TW'));
    if (!f || (!f.revenue && !f.income)) return renderEmpty(f);
    let h = '';
    const V = window.Viz;
    if (f.score != null) {
      h += `<div class="stat-row" style="font-weight:700"><span class="stat-k">基本面評分</span><span class="stat-v">${scoreBadge(f.score)}</span></div>`;
      if (V) h += `<div style="padding:0 12px 4px">${V.scoreMeter(f.score)}</div>`;
    }
    const r = f.revenue;
    if (r) {
      if (isIntl || r.monthRev == null) {
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
    const src = isIntl
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
      // 台／美／大盤皆顯示基本面區塊；籌碼等仍僅台股（資料源限制）
      fetchFund(S.sym, S.mkt).then(f => {
        const stats = document.getElementById('rpanel');
        if (!stats || S.tab !== 'stats') return;
        const ex = document.getElementById('fund-sect');
        const sectTitle = (f && (f.kind === 'market' || f.kind === 'market_risk' || f.kind === 'margin_cycle' || f.kind === 'holders'))
          ? (f.title || (f.kind === 'market_risk' ? '市場風險' : (f.kind === 'margin_cycle' ? '融資週期' : (f.kind === 'holders' ? '籌碼集中度' : '大盤體質'))))
          : '基本面';
        const html = `<div id="fund-sect"><div class="stat-sect">${sectTitle} · ${S.sym}</div>${render(f)}</div>`;
        if (ex) ex.outerHTML = html;
        else stats.insertAdjacentHTML('beforeend', html);
      });
      return h + `<div id="fund-sect"><div class="stat-sect">基本面 · ${S.sym}</div><div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px">載入基本面中...</div></div>`;
    };
  })();

  window.fetchFund = fetchFund;
})();

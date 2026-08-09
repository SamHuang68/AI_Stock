// ============================================================
// Market Score Bar v3 — 主圖資訊列：大盤體質 / 市場風險
// ------------------------------------------------------------
// • TW（^TWII/^TWOII/融資維持/台合成）：大盤體質（越高越健康）
// • US（美利率債／CPI金融）：市場風險（越高越警戒）
// • 一行摘要 + 可展開支柱 +「?」演算法說明
// • 美圖支援 對齊／原始 模式切換（分數依視窗重算）
// ============================================================
(function MarketScoreBarV3() {
  'use strict';
  const VER = '3.4.0';
  const LOG = (...a) => console.log('%c[MarketScore ' + VER + ']', 'color:#94a3b8', ...a);
  const SRV = () => window.SERVER || (typeof location !== 'undefined' && location.origin !== 'null' ? location.origin : 'http://localhost:18432');

  const TW_FUND_SYMS = new Set([
    '^TWII', '^TWOII', 'TWII', 'TWOII', 'TAIEX', '^TAIEX',
    '__MARGIN_RATIO__', '__MARGIN__',
  ]);
  function isTwFundSym(sym) {
    const s = String(sym || '').toUpperCase();
    if (TW_FUND_SYMS.has(s)) return true;
    if (s === '__TW_MARGIN_CYCLE__' || s === '__MARGIN_CYCLE__') return false;
    return s.startsWith('__TW_') && s.endsWith('__');
  }
  function isMarginCycleSym(sym) {
    const s = String(sym || '').toUpperCase();
    return s === '__TW_MARGIN_CYCLE__' || s === '__MARGIN_CYCLE__';
  }
  function isHoldersSym(sym) {
    return /^__HOLDERS_[0-9A-Z]{4,6}__$/.test(String(sym || '').toUpperCase());
  }
  function isUsRiskSym(sym) {
    const s = String(sym || '').toUpperCase();
    return s === '__US_RATES_CREDIT__' || s === '__US_CPI_FIN__';
  }

  // ── 與 server/market_risk.py 對齊的前端重算 ────────────────
  function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
  function tanhMap(x, center, scale) {
    return clamp(50 + 50 * Math.tanh((Number(x) - center) / scale), 0, 100);
  }
  function lastVal(pts) {
    for (let i = (pts || []).length - 1; i >= 0; i--) {
      const v = pts[i] && pts[i].value;
      if (v != null && isFinite(v)) return Number(v);
    }
    return null;
  }
  function firstVal(pts) {
    for (let i = 0; i < (pts || []).length; i++) {
      const v = pts[i] && pts[i].value;
      if (v != null && isFinite(v)) return Number(v);
    }
    return null;
  }
  function windowRet(pts) {
    const a = firstVal(pts), b = lastVal(pts);
    if (a == null || b == null || a === 0) return null;
    return (b / a - 1) * 100;
  }
  function maxDd(pts) {
    let peak = null, max = 0, n = 0;
    for (const p of pts || []) {
      const v = p && p.value;
      if (v == null || !isFinite(v)) continue;
      n++;
      if (peak == null || v > peak) peak = v;
      if (peak > 0) {
        const dd = (peak - v) / peak * 100;
        if (dd > max) max = dd;
      }
    }
    return n < 2 ? null : max;
  }
  function labelRisk(s) {
    if (s == null) return '資料不足';
    if (s >= 70) return '風險偏高';
    if (s >= 55) return '風險中偏高';
    if (s >= 45) return '風險中性';
    if (s >= 30) return '風險偏低';
    return '風險偏低';
  }
  function labelHealth(s) {
    if (s == null) return '資料不足';
    if (s >= 70) return '體質偏強';
    if (s >= 55) return '體質中偏強';
    if (s >= 45) return '體質中性';
    if (s >= 30) return '體質偏弱';
    return '體質偏冷';
  }
  function labelCycle(s) {
    if (s == null) return '資料不足';
    if (s >= 75) return '擁擠高潮';
    if (s >= 55) return '偏熱';
    if (s >= 30) return '修復／中性';
    return '清算區';
  }
  function labelConcentrate(s) {
    if (s == null) return '資料不足';
    if (s >= 70) return '高度集中';
    if (s >= 55) return '集中中';
    if (s >= 45) return '中性';
    if (s >= 30) return '偏發散';
    return '發散';
  }

  function seriesMap(seriesList) {
    const m = {};
    for (const s of seriesList || []) if (s && s.key) m[s.key] = s.points || [];
    return m;
  }

  function recomputeUsRatesCredit(seriesList) {
    const sm = seriesMap(seriesList);
    const fed = lastVal(sm.fedfunds), y10 = lastVal(sm.us10y);
    const rateParts = [];
    const rateD = {};
    if (fed != null) { const sc = tanhMap(fed, 2.5, 2.0); rateParts.push(sc); rateD.fedfunds = +fed.toFixed(3); rateD.fedScore = +sc.toFixed(1); }
    if (y10 != null) { const sc = tanhMap(y10, 3.0, 1.5); rateParts.push(sc); rateD.us10y = +y10.toFixed(3); rateD.us10yScore = +sc.toFixed(1); }
    const rateSc = rateParts.length ? +(rateParts.reduce((a, b) => a + b, 0) / rateParts.length).toFixed(1) : null;
    if (rateSc != null) rateD.score = rateSc;

    const igRet = windowRet(sm.baml_ig), hyRet = windowRet(sm.baml_hy), hyDd = maxDd(sm.baml_hy);
    const credParts = [];
    const credD = {};
    if (igRet != null && hyRet != null) {
      const lag = igRet - hyRet;
      const sc = tanhMap(lag, 0, 12);
      credParts.push(sc);
      credD.igReturnPct = +igRet.toFixed(2);
      credD.hyReturnPct = +hyRet.toFixed(2);
      credD.hyLagPp = +lag.toFixed(2);
      credD.lagScore = +sc.toFixed(1);
    }
    if (hyDd != null) {
      const sc = tanhMap(hyDd, 8, 10);
      credParts.push(sc);
      credD.hyDrawdownPct = +hyDd.toFixed(2);
      credD.ddScore = +sc.toFixed(1);
    }
    const credSc = credParts.length ? +(credParts.reduce((a, b) => a + b, 0) / credParts.length).toFixed(1) : null;
    if (credSc != null) credD.score = credSc;

    const parts = [rateSc, credSc].filter(x => x != null);
    const score = parts.length ? +(parts.reduce((a, b) => a + b, 0) / parts.length).toFixed(1) : null;
    const label = labelRisk(score);
    const rows = [];
    if (rateSc != null) {
      const bits = [];
      if (rateD.fedfunds != null) bits.push('Fed ' + rateD.fedfunds + '%');
      if (rateD.us10y != null) bits.push('10Y ' + rateD.us10y + '%');
      rows.push({ k: '利率壓力', v: bits.join(' · ') || '—', score: rateSc });
    }
    if (credSc != null) {
      const bits = [];
      if (credD.hyLagPp != null) bits.push('HY落後 ' + (credD.hyLagPp >= 0 ? '+' : '') + credD.hyLagPp + 'pp');
      if (credD.hyDrawdownPct != null) bits.push('HY回撤 ' + credD.hyDrawdownPct + '%');
      rows.push({ k: '信用壓力', v: bits.join(' · ') || '—', score: credSc });
    }
    return {
      kind: 'market_risk', title: '市場風險', direction: 'alert',
      symbol: '__US_RATES_CREDIT__', code: '__US_RATES_CREDIT__',
      score, label,
      summary: score != null ? `市場風險 ${score} · ${label}` : '市場風險 —',
      plainSummary: score != null
        ? `目前市場風險約 ${score} 分（${label}）。` +
          (rateSc != null ? ` 利率壓力 ${rateSc}；` : '') +
          (credSc != null ? ` 信用壓力 ${credSc}。` : '')
        : '市場風險資料暫缺。',
      marketRows: rows,
      algo: (window.S && S._marketRiskAlgo) || null,
    };
  }

  function recomputeUsCpiFin(seriesList) {
    const sm = seriesMap(seriesList);
    const cpi = lastVal(sm.us_cpi_yoy), fed = lastVal(sm.fedfunds);
    const infSc = cpi != null ? +tanhMap(cpi, 2.0, 2.0).toFixed(1) : null;
    const rateSc = fed != null ? +tanhMap(fed, 2.5, 2.0).toFixed(1) : null;
    const ret = windowRet(sm.xlf), dd = maxDd(sm.xlf);
    const finParts = [];
    const finD = {};
    if (ret != null) {
      const sc = clamp(50 - 50 * Math.tanh(ret / 20), 0, 100);
      finParts.push(sc); finD.xlfReturnPct = +ret.toFixed(2); finD.retScore = +sc.toFixed(1);
    }
    if (dd != null) {
      const sc = tanhMap(dd, 10, 12);
      finParts.push(sc); finD.xlfDrawdownPct = +dd.toFixed(2); finD.ddScore = +sc.toFixed(1);
    }
    const finSc = finParts.length ? +(finParts.reduce((a, b) => a + b, 0) / finParts.length).toFixed(1) : null;
    const parts = [infSc, rateSc, finSc].filter(x => x != null);
    const score = parts.length ? +(parts.reduce((a, b) => a + b, 0) / parts.length).toFixed(1) : null;
    const label = labelRisk(score);
    const rows = [];
    if (infSc != null) rows.push({ k: '通膨壓力', v: 'CPI YoY ' + (+cpi).toFixed(2) + '%', score: infSc });
    if (rateSc != null) rows.push({ k: '利率壓力', v: 'Fed ' + (+fed).toFixed(2) + '%', score: rateSc });
    if (finSc != null) {
      const bits = [];
      if (finD.xlfReturnPct != null) bits.push('報酬 ' + (finD.xlfReturnPct >= 0 ? '+' : '') + finD.xlfReturnPct + '%');
      if (finD.xlfDrawdownPct != null) bits.push('回撤 ' + finD.xlfDrawdownPct + '%');
      rows.push({ k: '金融股壓力', v: bits.join(' · ') || '—', score: finSc });
    }
    return {
      kind: 'market_risk', title: '市場風險', direction: 'alert',
      symbol: '__US_CPI_FIN__', code: '__US_CPI_FIN__',
      score, label,
      summary: score != null ? `市場風險 ${score} · ${label}` : '市場風險 —',
      plainSummary: score != null
        ? `目前市場風險約 ${score} 分（${label}）。` +
          [infSc != null ? `通膨 ${infSc}` : null, rateSc != null ? `利率 ${rateSc}` : null, finSc != null ? `金融股 ${finSc}` : null]
            .filter(Boolean).join('、') + '。'
        : '市場風險資料暫缺。',
      marketRows: rows,
      algo: (window.S && S._marketRiskAlgo) || null,
    };
  }

  function recomputeFromSeries(chartId, seriesList) {
    const id = String(chartId || '').toUpperCase();
    if (id === '__US_RATES_CREDIT__') return recomputeUsRatesCredit(seriesList);
    if (id === '__US_CPI_FIN__') return recomputeUsCpiFin(seriesList);
    return null;
  }

  // ── DOM ────────────────────────────────────────────────────
  function ensureBarHost() {
    let bar = document.getElementById('market-score-bar');
    if (bar) return bar;
    const info = document.getElementById('chart-info');
    if (!info) return null;
    bar = document.createElement('div');
    bar.id = 'market-score-bar';
    info.appendChild(bar);
    return bar;
  }

  function scoreColor(score, direction) {
    if (score == null) return 'var(--tlo)';
    if (direction === 'health') {
      if (window.Colors && Colors.quality) return Colors.quality(score, 70, 50);
      return score >= 70 ? 'var(--red)' : score >= 50 ? 'var(--orange)' : 'var(--green)';
    }
    if (direction === 'cycle') {
      // 高潮偏紅警戒、清算偏綠（去槓桿）
      if (score >= 75) return '#f87171';
      if (score >= 55) return '#fb923c';
      if (score >= 30) return '#94a3b8';
      return '#4ade80';
    }
    if (direction === 'concentrate') {
      // 高度集中偏紅（台股熱）、發散偏綠
      if (score >= 70) return '#f87171';
      if (score >= 55) return '#fb923c';
      if (score >= 45) return '#94a3b8';
      return '#4ade80';
    }
    // alert：高分警戒 → 紅／橘
    if (score >= 70) return '#f87171';
    if (score >= 55) return '#fb923c';
    if (score >= 45) return '#94a3b8';
    return '#4ade80';
  }

  let _expanded = false;
  let _lastPayload = null;
  let _lastSym = null;

  function hide() {
    const bar = document.getElementById('market-score-bar');
    if (bar) { bar.style.display = 'none'; bar.innerHTML = ''; }
    const modal = document.getElementById('market-algo-modal');
    if (modal) modal.style.display = 'none';
    if (window.S) {
      // 離開大盤／美風險／融資週期圖時清掉，避免 STATS 誤用舊 payload
      if (!isTwFundSym(S.sym) && !isUsRiskSym(S.sym) && !isMarginCycleSym(S.sym) && !isHoldersSym(S.sym)) {
        S._fundPanelPayload = null;
        S._marketRisk = null;
      }
    }
  }

  function render(payload, opts) {
    opts = opts || {};
    const bar = ensureBarHost();
    if (!bar || !payload) { hide(); return; }
    _lastPayload = payload;
    _lastSym = opts.sym || (window.S && S.sym) || '';
    const direction = payload.direction
      || (payload.kind === 'market_risk' ? 'alert'
        : (payload.kind === 'margin_cycle' ? 'cycle'
          : (payload.kind === 'holders' ? 'concentrate' : 'health')));
    const title = payload.title
      || (direction === 'alert' ? '市場風險'
        : (direction === 'cycle' ? '融資週期'
          : (direction === 'concentrate' ? '籌碼集中度' : '大盤體質')));
    const score = payload.score;
    const label = payload.label
      || (direction === 'alert' ? labelRisk(score)
        : (direction === 'cycle' ? labelCycle(score)
          : (direction === 'concentrate' ? labelConcentrate(score) : labelHealth(score))));
    const summary = payload.summary || (score != null ? `${title} ${score} · ${label}` : `${title} —`);
    const rows = payload.marketRows || [];
    const viewMode = opts.viewMode || (window.S && S._marketViewMode) || null;
    const showMode = !!opts.showModeToggle;
    const col = scoreColor(score, direction);

    const info = document.getElementById('chart-info');
    if (info) {
      // 摘要列需可點；其餘仍穿透
      info.style.pointerEvents = 'none';
    }
    bar.style.cssText = [
      'display:block', 'pointer-events:auto', 'margin-top:6px', 'max-width:min(420px,78vw)',
      'font:10px/1.35 JetBrains Mono,ui-monospace,monospace',
      'color:#94a3b8',
    ].join(';');

    const modeTag = viewMode
      ? `<span class="msb-mode" title="圖表數值模式">${viewMode === 'rebase' ? '對齊' : '原始'}</span>`
      : '';

    let html =
      `<div class="msb-row" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">` +
        `<button type="button" class="msb-sum" data-msb="toggle" title="展開／收合支柱"` +
          ` style="display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border-radius:2px;cursor:pointer;` +
          `font:inherit;border:1px solid rgba(71,85,105,.7);background:rgba(10,14,20,.82);color:#cbd5e1">` +
          `<span style="color:${col};font-weight:700;font-size:11px">${summary}</span>` +
          modeTag +
          `<span style="color:#64748b;font-size:9px">${_expanded ? '▾' : '▸'}</span>` +
        `</button>` +
        `<button type="button" class="msb-q" data-msb="algo" title="演算法說明"` +
          ` style="width:20px;height:20px;border-radius:2px;cursor:pointer;font:10px/1 inherit;` +
          `border:1px solid rgba(71,85,105,.7);background:rgba(10,14,20,.82);color:#94a3b8">?</button>`;

    if (showMode) {
      html +=
        `<button type="button" data-msb="mode" title="切換對齊基準100／原始數值"` +
          ` style="padding:3px 7px;border-radius:2px;cursor:pointer;font:inherit;` +
          `border:1px solid rgba(71,85,105,.65);background:rgba(15,20,30,.85);color:#94a3b8">` +
          (viewMode === 'rebase' ? '原始' : '對齊') +
        `</button>`;
    }
    html += `</div>`;

    if (_expanded && rows.length) {
      html += `<div class="msb-pillars" style="margin-top:4px;padding:6px 8px;border-radius:2px;` +
        `background:rgba(10,14,20,.88);border:1px solid rgba(51,65,85,.65)">`;
      for (const r of rows) {
        const sc = r.score;
        const pc = scoreColor(sc, direction);
        html += `<div style="display:flex;justify-content:space-between;gap:10px;margin-top:2px">` +
          `<span style="color:#94a3b8">${r.k}</span>` +
          `<span style="color:#cbd5e1">${r.v || '—'}` +
          (sc != null ? ` <span style="color:${pc};font-weight:700">(${Math.round(sc)})</span>` : '') +
          `</span></div>`;
      }
      html += `</div>`;
    }

    bar.innerHTML = html;
    bar.onclick = function (ev) {
      const btn = ev.target && ev.target.closest && ev.target.closest('[data-msb]');
      if (!btn) return;
      const act = btn.getAttribute('data-msb');
      if (act === 'toggle') {
        _expanded = !_expanded;
        render(_lastPayload, opts);
      } else if (act === 'algo') {
        openAlgoModal(_lastPayload);
      } else if (act === 'mode') {
        if (typeof window.MarketChart !== 'undefined' && typeof MarketChart.toggleViewMode === 'function') {
          MarketChart.toggleViewMode();
        }
      }
    };

    // TW 大盤體質 → WaveDeck 宏觀覆寫（節流／去重在 bridge）
    if (direction === 'health' && score != null && window.WaveDeckBridge &&
        typeof window.WaveDeckBridge.syncFromMarket === 'function') {
      try {
        window.WaveDeckBridge.syncFromMarket({
          score: score,
          label: label,
          summary: payload.plainSummary || summary,
          source: 'market_score_bar',
          silent: true
        });
      } catch (e) { /* never block chart */ }
    }
  }

  function openAlgoModal(payload) {
    const algo = (payload && payload.algo) || null;
    let modal = document.getElementById('market-algo-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'market-algo-modal';
      document.body.appendChild(modal);
    }
    const direction = (payload && payload.direction) || (algo && algo.direction) || 'alert';
    const title = (algo && algo.title) || (payload && payload.title) || '演算法';
    const pillars = (algo && algo.pillars) || [];
    let body =
      `<div style="font-size:13px;font-weight:700;color:#e2e8f0;margin-bottom:6px">${title}</div>` +
      `<div style="color:#94a3b8;margin-bottom:10px;font-size:11px">` +
        (direction === 'health' ? '分數愈高＝體質愈健康。'
          : (direction === 'cycle' ? '分數愈高＝槓桿愈擴張／偏熱；愈低＝去槓桿／清算區。'
            : (direction === 'concentrate' ? '分數愈高＝籌碼愈集中；愈低＝愈發散／散戶化。'
              : '分數愈高＝愈需警戒。'))) +
        ' 下列公式可對非金融友人說明。' +
      `</div>`;
    if (pillars.length) {
      for (const p of pillars) {
        body +=
          `<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(51,65,85,.8)">` +
            `<div style="color:#cbd5e1;font-weight:700">${p.name}` +
              (p.weight ? ` <span style="color:#64748b;font-weight:500">· ${p.weight}</span>` : '') +
            `</div>` +
            (p.plain ? `<div style="color:#94a3b8;margin-top:4px">${p.plain}</div>` : '') +
            (p.formula ? `<div style="color:#64748b;margin-top:4px;font-size:10px;word-break:break-all">${p.formula}</div>` : '') +
          `</div>`;
      }
    } else {
      body += `<div style="color:#64748b">尚無詳細公式說明。</div>`;
    }
    if (algo && algo.aggregate) {
      body += `<div style="margin-top:12px;color:#94a3b8;font-size:11px">${algo.aggregate}</div>`;
    }
    if (algo && algo.viewNote) {
      body += `<div style="margin-top:6px;color:#64748b;font-size:10px">${algo.viewNote}</div>`;
    }
    if (payload && payload.plainSummary) {
      body += `<div style="margin-top:12px;padding:8px;border-radius:2px;background:rgba(15,23,42,.8);color:#cbd5e1;font-size:11px">${payload.plainSummary}</div>`;
    }

    modal.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:10050', 'display:flex',
      'align-items:center', 'justify-content:center',
      'background:rgba(0,0,0,.55)', 'pointer-events:auto',
    ].join(';');
    modal.innerHTML =
      `<div style="width:min(480px,92vw);max-height:80vh;overflow:auto;padding:16px 18px;` +
        `background:#0f141c;border:1px solid rgba(71,85,105,.8);border-radius:4px;` +
        `font:12px/1.5 JetBrains Mono,ui-monospace,monospace;box-shadow:0 16px 40px rgba(0,0,0,.55)">` +
        `<div style="display:flex;justify-content:flex-end">` +
          `<button type="button" data-msb-close style="cursor:pointer;border:1px solid #334155;background:#1e293b;` +
            `color:#94a3b8;border-radius:2px;padding:2px 8px;font:inherit">關閉</button>` +
        `</div>` +
        body +
      `</div>`;
    modal.onclick = function (ev) {
      if (ev.target === modal || (ev.target && ev.target.getAttribute && ev.target.getAttribute('data-msb-close') != null)) {
        modal.style.display = 'none';
      }
    };
  }

  async function fetchFund(sym) {
    try {
      const r = await fetch(`${SRV()}/fundamental/${encodeURIComponent(sym)}`, { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      LOG('fetch fund fail', e);
      return null;
    }
  }

  async function onSymLoaded(ev) {
    const d = (ev && ev.detail) || {};
    const sym = d.sym || (window.S && S.sym);
    if (!sym) { hide(); return; }
    const up = String(sym).toUpperCase();

    // 美風險圖：優先用 chart payload.risk（可能已依視窗重算）
    if (isUsRiskSym(up)) {
      let risk = (window.S && S._marketRisk) || null;
      if (!risk) {
        const f = await fetchFund(sym);
        if (f && (f.kind === 'market_risk' || f.score != null)) risk = f;
      }
      if (!risk) { hide(); return; }
      if (window.S) S._fundPanelPayload = risk;
      render(risk, {
        sym: up,
        showModeToggle: true,
        viewMode: (window.S && S._marketViewMode) || 'rebase',
      });
      return;
    }

    // 融資週期
    if (isMarginCycleSym(up)) {
      let risk = (window.S && S._marketRisk) || null;
      if (!risk || risk.kind !== 'margin_cycle') {
        const f = await fetchFund(sym);
        if (f && (f.kind === 'margin_cycle' || f.score != null)) risk = f;
      }
      if (!risk) { hide(); return; }
      if (window.S) S._fundPanelPayload = risk;
      render(risk, { sym: up, showModeToggle: false });
      return;
    }

    // 籌碼集中度
    if (isHoldersSym(up)) {
      let risk = (window.S && S._marketRisk) || null;
      if (!risk || risk.kind !== 'holders') {
        const f = await fetchFund(sym);
        if (f && (f.kind === 'holders' || f.score != null)) risk = f;
      }
      if (!risk) { hide(); return; }
      if (window.S) S._fundPanelPayload = risk;
      render(risk, { sym: up, showModeToggle: false });
      return;
    }

    if (isTwFundSym(up)) {
      const f = await fetchFund(sym);
      if (!f || (f.kind !== 'market' && f.score == null)) { hide(); return; }
      if (window.S) S._fundPanelPayload = f;
      render(f, { sym: up, showModeToggle: false });
      return;
    }

    hide();
  }

  function applyRiskUpdate(risk, opts) {
    if (!risk) return;
    if (window.S) {
      S._marketRisk = risk;
      S._fundPanelPayload = risk;
      if (risk.algo) S._marketRiskAlgo = risk.algo;
    }
    render(risk, Object.assign({
      showModeToggle: true,
      viewMode: (window.S && S._marketViewMode) || 'rebase',
    }, opts || {}));
  }

  window.addEventListener('symLoaded', onSymLoaded);

  window.MarketScoreBar = {
    ver: VER,
    render,
    hide,
    applyRiskUpdate,
    recomputeFromSeries,
    isTwFundSym,
    isUsRiskSym,
    isMarginCycleSym,
    isHoldersSym,
    openAlgoModal,
  };
  LOG('ready');
})();

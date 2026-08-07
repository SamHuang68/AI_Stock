/* ============================================================================
 * pulse_v5.js  —  Stock Terminal 5.0：TW Pulse Overview 儀表板
 * ----------------------------------------------------------------------------
 * 1:1 對齊 TW Pulse - MARKET INTELLIGENCE 參考圖（Overview）：
 *   頂列 3 卡｜市場脈動與組成 (半圓 Gauge) ｜ 市場趨勢走勢 (折線與 OHLC) ｜ 法人分歧與資金 (5日/連買/3/3)
 *   中列 4 卡｜市場廣度 (甜甜圈+多空比) ｜ 產業輪動 (進度條%) ｜ 漲停監控 ｜ 跌幅異常
 *   底列 3 卡｜全球市場對台股影響 ｜ 市場快訊 ｜ 自選股風險與機會
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var lastPack = null;
  var showFactors = false;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    if ($('pulse-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'pulse-v5-css';
    s.textContent =
      '#view-pulse.sv-panel{max-width:100%;width:100%;min-width:0;padding:12px 14px 20px;box-sizing:border-box;background:#060C16;color:#E2E8F0}' +
      '#pl-root{font-family:\'Noto Sans TC\',sans-serif;width:100%;max-width:min(1480px,100%);margin:0 auto;box-sizing:border-box}' +
      '#pl-root .pl-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}' +
      '#pl-root .pl-head-left{display:flex;align-items:center;gap:10px}' +
      '#pl-root .pl-title{font-size:18px;font-weight:800;color:#F8FAFC;letter-spacing:.3px}' +
      '#pl-root .pl-sub{font-size:11px;color:#64748B}' +
      '#pl-root .pl-actions{display:flex;gap:6px;align-items:center}' +
      '#pl-root .pl-btn{padding:5px 12px;border:1px solid #1E293B;border-radius:6px;background:#0F172A;' +
        'color:#94A3B8;font-size:11px;cursor:pointer;transition:all .14s ease;font-weight:500}' +
      '#pl-root .pl-btn:hover{border-color:#38BDF8;color:#F8FAFC;background:#1E293B}' +
      '#pl-root .pl-btn.primary{background:#0284C7;color:#FFFFFF;border:none;font-weight:700}' +
      '#pl-root .pl-btn.primary:hover{background:#0369A1}' +
      
      '#pl-root .up{color:#FF4D4D;font-weight:700}' +
      '#pl-root .dn{color:#22C55E;font-weight:700}' +
      '#pl-root .flat{color:#94A3B8}' +
      
      /* Card General */
      '#pl-root .tw-card{background:#0B1422;border:1px solid #15263F;border-radius:8px;padding:12px 14px;box-sizing:border-box;display:flex;flex-direction:column;min-width:0}' +
      '#pl-root .tw-card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}' +
      '#pl-root .tw-card-title{font-size:13px;font-weight:700;color:#E2E8F0;display:flex;align-items:center;gap:6px}' +
      '#pl-root .tw-card-link{color:#64748B;font-size:12px;cursor:pointer;text-decoration:none;transition:color .14s}' +
      '#pl-root .tw-card-link:hover{color:#38BDF8}' +
      
      /* Grid Rows */
      '#pl-root .pl-row{display:grid;gap:10px;margin-bottom:10px}' +
      '#pl-root .pl-row.top-row{grid-template-columns:360px 1fr 340px}' +
      '#pl-root .pl-row.mid-row{grid-template-columns:1.1fr 1fr 1fr 1fr}' +
      '#pl-root .pl-row.bot-row{grid-template-columns:1.2fr 1fr 1fr}' +
      
      /* Arc Gauge (Card 1) */
      '#pl-root .pulse-gauge-wrap{display:flex;gap:14px;align-items:center;margin-bottom:10px}' +
      '#pl-root .arc-gauge-box{position:relative;width:130px;height:75px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;flex-shrink:0}' +
      '#pl-root .arc-gauge-box svg{width:130px;height:75px}' +
      '#pl-root .arc-score-val{position:absolute;bottom:16px;text-align:center;width:100%}' +
      '#pl-root .arc-score-val .num{font-size:20px;font-weight:900;color:#F8FAFC;line-height:1}' +
      '#pl-root .arc-score-val .den{font-size:10px;color:#64748B}' +
      '#pl-root .arc-badge{position:absolute;bottom:-4px;padding:1px 8px;border-radius:10px;font-size:9.5px;font-weight:700;background:rgba(245,158,11,0.15);color:#F59E0B;border:1px solid rgba(245,158,11,0.3)}' +
      
      '#pl-root .gauge-sub-box{flex:1;display:flex;flex-direction:column;gap:6px;background:#070E1A;border:1px solid #132238;border-radius:6px;padding:8px 10px}' +
      '#pl-root .sub-metric-row{display:flex;justify-content:space-between;align-items:center;font-size:11px}' +
      '#pl-root .sub-metric-row .lbl{color:#94A3B8}' +
      '#pl-root .sub-metric-row .val{color:#F8FAFC;font-weight:700}' +
      '#pl-root .sub-metric-row .tag{font-size:9.5px;color:#0EA5E9;margin-left:4px}' +
      '#pl-root .progress-bar-bg{height:4px;background:#1E293B;border-radius:2px;overflow:hidden;margin-top:2px}' +
      '#pl-root .progress-bar-fill{height:100%;background:linear-gradient(90deg, #0EA5E9, #10B981);border-radius:2px}' +
      
      '#pl-root .pulse-details{display:flex;flex-direction:column;gap:4px;font-size:11px;background:#070E1A;border:1px solid #132238;border-radius:6px;padding:8px 10px;margin-top:2px}' +
      '#pl-root .pulse-detail-item{display:flex;gap:6px}' +
      '#pl-root .pulse-detail-item .k{color:#64748B;width:56px;flex-shrink:0}' +
      '#pl-root .pulse-detail-item .v{color:#CBD5E1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      
      /* Trend Chart (Card 2) */
      '#pl-root .trend-chart-area{height:100px;width:100%;margin:4px 0 8px}' +
      '#pl-root .ohlc-4grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:auto}' +
      '#pl-root .ohlc-box{background:#070E1A;border:1px solid #132238;border-radius:6px;padding:6px 8px;text-align:left}' +
      '#pl-root .ohlc-box .k{font-size:10px;color:#64748B}' +
      '#pl-root .ohlc-box .v{font-size:12.5px;font-weight:700;color:#F8FAFC;margin-top:2px}' +
      
      /* Institutional Flow (Card 3) */
      '#pl-root .inst-list{display:flex;flex-direction:column;gap:8px;margin-bottom:8px}' +
      '#pl-root .inst-item{display:flex;align-items:center;justify-content:space-between;font-size:11.5px}' +
      '#pl-root .inst-item .left{display:flex;align-items:center;gap:6px}' +
      '#pl-root .inst-item .name{color:#E2E8F0;font-weight:700;width:42px}' +
      '#pl-root .inst-item .meta{color:#64748B;font-size:10px}' +
      '#pl-root .inst-item .amt{font-size:13px;font-weight:800}' +
      
      '#pl-root .inst-total-row{display:flex;align-items:center;justify-content:space-between;padding:6px 8px;background:#070E1A;border:1px solid #132238;border-radius:6px;margin-bottom:8px}' +
      '#pl-root .inst-total-row .lbl{font-size:11px;color:#CBD5E1;font-weight:700}' +
      '#pl-root .inst-total-row .val{font-size:15px;font-weight:900}' +
      
      '#pl-root .inst-consensus-box{background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.2);border-radius:6px;padding:8px 10px;margin-top:auto}' +
      '#pl-root .inst-consensus-box .c-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px}' +
      '#pl-root .inst-consensus-box .c-title{font-size:11px;font-weight:800;color:#FF4D4D}' +
      '#pl-root .inst-consensus-box .c-tag{font-size:9px;font-weight:700;color:#FF4D4D;background:rgba(239,68,68,0.15);padding:1px 6px;border-radius:4px}' +
      '#pl-root .inst-consensus-box .c-sub{font-size:10px;color:#94A3B8}' +

      /* Donut Breadth (Card 4) */
      '#pl-root .breadth-donut-layout{display:flex;align-items:center;gap:12px;margin-bottom:8px}' +
      '#pl-root .donut-chart-box{width:80px;height:80px;position:relative;flex-shrink:0}' +
      '#pl-root .donut-chart-box svg{width:80px;height:80px}' +
      '#pl-root .donut-center-text{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}' +
      '#pl-root .donut-center-text .num{font-size:15px;font-weight:800;color:#F8FAFC}' +
      '#pl-root .donut-center-text .lbl{font-size:8px;color:#64748B}' +
      '#pl-root .breadth-legend{display:flex;flex-direction:column;gap:3px;font-size:11px;flex:1}' +
      '#pl-root .breadth-legend .leg-item{display:flex;align-items:center;justify-content:space-between}' +
      '#pl-root .breadth-legend .dot{width:6px;height:6px;border-radius:50%;display:inline-block;margin-right:5px}' +
      
      '#pl-root .breadth-sub-metrics{display:flex;justify-content:space-between;background:#070E1A;border:1px solid #132238;border-radius:6px;padding:6px 8px;font-size:11px;margin-bottom:6px}' +
      '#pl-root .breadth-sub-metrics .item{display:flex;flex-direction:column}' +
      '#pl-root .breadth-sub-metrics .k{font-size:9.5px;color:#64748B}' +
      '#pl-root .breadth-sub-metrics .v{font-size:12px;font-weight:800;color:#F8FAFC;margin-top:1px}' +
      
      '#pl-root .breadth-bottom-bar{display:flex;justify-content:space-between;font-size:10px;color:#94A3B8;padding-top:4px;border-top:1px dashed #15263F;margin-top:auto}' +
      
      /* Sector Progress (Card 5) */
      '#pl-root .sector-list{display:flex;flex-direction:column;gap:5px}' +
      '#pl-root .sector-row{display:flex;align-items:center;justify-content:space-between;font-size:11px}' +
      '#pl-root .sector-row .s-info{display:flex;flex-direction:column}' +
      '#pl-root .sector-row .s-name{color:#E2E8F0;font-weight:700}' +
      '#pl-root .sector-row .s-sub{font-size:8.5px;color:#64748B}' +
      '#pl-root .sector-row .s-bar-wrap{display:flex;align-items:center;gap:6px;width:100px}' +
      '#pl-root .sector-row .s-bar-bg{flex:1;height:5px;background:#1E293B;border-radius:3px;overflow:hidden}' +
      '#pl-root .sector-row .s-bar-fill{height:100%;background:#10B981;border-radius:3px}' +
      '#pl-root .sector-row .s-pct{width:42px;text-align:right;font-weight:700;font-size:11px}' +
      
      /* Numbered List (Card 6 & 7) */
      '#pl-root .num-list{display:flex;flex-direction:column;gap:4px}' +
      '#pl-root .num-item{display:flex;align-items:center;justify-content:space-between;padding:3px 0;border-bottom:1px solid #132238;font-size:11px;cursor:pointer}' +
      '#pl-root .num-item:hover{background:rgba(255,255,255,0.02)}' +
      '#pl-root .num-item .left-grp{display:flex;align-items:center;gap:6px}' +
      '#pl-root .num-item .idx-badge{width:16px;height:16px;border-radius:50%;background:#1E293B;color:#94A3B8;font-size:9.5px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0}' +
      '#pl-root .num-item .stk-name{color:#F8FAFC;font-weight:700}' +
      '#pl-root .num-item .stk-meta{font-size:9.5px;color:#64748B}' +
      '#pl-root .num-item .pct-val{font-weight:800;font-size:12px}' +
      
      /* Global Market (Card 8) */
      '#pl-root .global-impact-head{display:flex;align-items:center;gap:6px;margin-bottom:8px}' +
      '#pl-root .global-impact-head .pill{padding:2px 8px;border-radius:12px;font-size:10px;font-weight:700;background:rgba(56,189,248,0.12);color:#38BDF8;border:1px solid rgba(56,189,248,0.3)}' +
      '#pl-root .global-impact-head .sub{font-size:9.5px;color:#64748B}' +
      '#pl-root .global-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}' +
      '#pl-root .global-box{background:#070E1A;border:1px solid #132238;border-radius:6px;padding:6px 8px;display:flex;flex-direction:column}' +
      '#pl-root .global-box .name{font-size:10px;color:#64748B}' +
      '#pl-root .global-box .price{font-size:13px;font-weight:800;color:#F8FAFC;margin-top:2px}' +
      '#pl-root .global-box .pct{font-size:11px;font-weight:700;margin-top:1px}' +
      '#pl-root .global-box .status{font-size:8px;color:#475569;margin-top:3px}' +
      
      /* Flash News (Card 9) */
      '#pl-root .news-list{display:flex;flex-direction:column;gap:6px;max-height:160px;overflow-y:auto}' +
      '#pl-root .news-item{display:flex;flex-direction:column;gap:1px;padding:3px 0;border-bottom:1px solid #132238}' +
      '#pl-root .news-item .n-head{display:flex;align-items:center;gap:6px;font-size:11px}' +
      '#pl-root .news-item .n-time{font-size:9px;color:#64748B}' +
      '#pl-root .news-item .n-title{color:#E2E8F0;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}' +
      '#pl-root .news-item .n-tag{font-size:8.5px;font-weight:700;color:#FF4D4D;background:rgba(239,68,68,0.15);padding:0 4px;border-radius:3px;flex-shrink:0}' +
      '#pl-root .news-item .n-desc{font-size:9.5px;color:#64748B;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      
      /* Watchlist (Card 10) */
      '#pl-root .wl-card-list{display:flex;flex-direction:column;gap:6px}' +
      '#pl-root .wl-card-item{display:flex;align-items:center;justify-content:space-between;background:#070E1A;border:1px solid #132238;border-radius:6px;padding:6px 10px;font-size:11px}' +
      '#pl-root .wl-card-item .code-box{display:flex;align-items:center;gap:6px}' +
      '#pl-root .wl-card-item .code{color:#38BDF8;font-weight:800}' +
      '#pl-root .wl-card-item .name{color:#E2E8F0;font-weight:600}' +
      '#pl-root .wl-card-item .note{font-size:9px;color:#64748B}' +
      '#pl-root .wl-card-item .right-stats{display:flex;align-items:center;gap:8px}' +
      '#pl-root .wl-card-item .px{font-size:13px;font-weight:800;color:#F8FAFC}' +
      
      '@media (max-width:1280px){' +
        '#pl-root .pl-row.top-row,#pl-root .pl-row.mid-row,#pl-root .pl-row.bot-row{grid-template-columns:1fr}' +
        '#pl-root .global-grid{grid-template-columns:repeat(3,1fr)}' +
      '}';
    document.head.appendChild(s);
  }

  function tw(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
  }
  function pct(p, d) {
    if (p == null || p !== p) return '—';
    d = d == null ? 2 : d;
    return (p >= 0 ? '+' : '') + Number(p).toFixed(d) + '%';
  }
  function fmt(v, d) {
    if (v == null || !isFinite(v)) return '—';
    d = d == null ? 0 : d;
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  }

  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function goRoute(id, opts) {
    if (window.ShellV5) window.ShellV5.go(id, opts || {});
  }

  function openChart(code, mkt) {
    if (window.ShellV5 && ShellV5.openChart) {
      ShellV5.openChart(code || '^TWII', mkt || 'TW');
      return;
    }
    if (code && typeof loadSym === 'function') {
      loadSym(code, mkt || 'TW');
      goRoute('chart');
    }
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-pulse');
    if (!panel) {
      var views = $('shell-views');
      if (views) {
        panel = document.createElement('section');
        panel.className = 'sv-panel';
        panel.id = 'view-pulse';
        panel.dataset.route = 'pulse';
        views.appendChild(panel);
      }
    }
    if (!panel) return null;
    var mount = $('mount-pulse');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-pulse';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('pl-root')) {
      mount.innerHTML =
        '<div id="pl-root">' +
          '<div class="pl-head">' +
            '<div class="pl-head-left">' +
              '<div class="pl-title">TW Pulse · 市場總覽</div>' +
              '<div class="pl-sub" id="pl-sub">官方資料混成 · 缺資料不灌假分數</div>' +
            '</div>' +
            '<div class="pl-actions">' +
              '<button type="button" class="pl-btn" id="pl-refresh">↻ 重新整理</button>' +
              '<button type="button" class="pl-btn primary" data-go="chart" data-sym="^TWII" data-mkt="TW">圖表</button>' +
            '</div>' +
          '</div>' +
          '<div id="pl-body"><div style="padding:20px;text-align:center;color:#64748B">載入總覽儀表板…</div></div>' +
        '</div>';
      var rbtn = $('pl-refresh');
      if (rbtn) rbtn.onclick = function () { refresh(true); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () {
          goRoute(b.getAttribute('data-go'), {
            sym: b.getAttribute('data-sym') || undefined,
            mkt: b.getAttribute('data-mkt') || undefined
          });
        };
      });
    }
    return $('pl-body');
  }

  /* Card 1: Semi-circle Arc Gauge — 缺資料顯示 —，禁止灌假分數 */
  function renderCardPulseGauge(p) {
    var score = p.totalScore;
    var pctVal = (score != null && isFinite(score)) ? Math.max(0, Math.min(100, score)) / 100 : 0;
    var health = p.healthScore != null ? Number(p.healthScore).toFixed(1) : '—';
    var risk = p.riskScore != null ? Number(p.riskScore).toFixed(1) : '—';
    var comp = p.dataCompleteness != null ? Number(p.dataCompleteness).toFixed(1) : '—';
    var datasetsOk = p.datasetsOk != null ? p.datasetsOk : 0;
    var datasetsTotal = p.datasetsTotal != null ? p.datasetsTotal : 0;
    var statusText = p.statusText || '資料彙整中';
    var drivers = (p.positiveFactors || []).slice(0, 3).map(function (f) { return f.name; }).filter(Boolean);
    var pressures = (p.riskFactors || []).slice(0, 3).map(function (f) { return f.name; }).filter(Boolean);
    var healthLbl = p.healthLabel || '';
    var riskLbl = p.riskLabel || '';

    var svgArc = 
      '<svg viewBox="0 0 140 80">' +
        '<path d="M 15 70 A 55 55 0 0 1 125 70" fill="none" stroke="#1E293B" stroke-width="12" stroke-linecap="round"/>' +
        '<path d="M 15 70 A 55 55 0 0 1 125 70" fill="none" stroke="url(#gaugeGrad)" stroke-width="12" stroke-linecap="round" stroke-dasharray="172" stroke-dashoffset="' + (172 * (1 - pctVal)) + '"/>' +
        '<defs>' +
          '<linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">' +
            '<stop offset="0%" stop-color="#EF4444"/>' +
            '<stop offset="50%" stop-color="#F59E0B"/>' +
            '<stop offset="100%" stop-color="#10B981"/>' +
          '</linearGradient>' +
        '</defs>' +
      '</svg>';

    return '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">市場脈動與組成</div>' +
        '<a class="tw-card-link" data-go="signals">詳情 →</a>' +
      '</div>' +
      '<div class="pulse-gauge-wrap">' +
        '<div class="arc-gauge-box">' +
          svgArc +
          '<div class="arc-score-val">' +
            '<span class="num">' + (score != null && isFinite(score) ? Number(score).toFixed(1) : '—') + '</span><span class="den"> /100</span>' +
          '</div>' +
          '<div class="arc-badge">' + esc(statusText) + '</div>' +
        '</div>' +
        '<div class="gauge-sub-box">' +
          '<div class="sub-metric-row"><span class="lbl">市場動能</span><span class="val">' + health + ' /100' +
            (healthLbl ? '<span class="tag">(' + esc(healthLbl) + ')</span>' : '') + '</span></div>' +
          '<div class="sub-metric-row"><span class="lbl">市場風險</span><span class="val">' + risk + ' /100' +
            (riskLbl ? '<span class="tag" style="color:#10B981">(' + esc(riskLbl) + ')</span>' : '') + '</span></div>' +
          '<div class="sub-metric-row"><span class="lbl">資料可信度</span><span class="val">' + comp + '%</span></div>' +
          '<div class="progress-bar-bg"><div class="progress-bar-fill" style="width:' + (p.dataCompleteness != null ? Number(p.dataCompleteness) : 0) + '%"></div></div>' +
          '<div style="font-size:9px;color:#64748B;text-align:right;margin-top:1px">' + datasetsOk + '/' + datasetsTotal + ' 資料集正常</div>' +
        '</div>' +
      '</div>' +
      '<div class="pulse-details">' +
        '<div class="pulse-detail-item"><span class="k">主要推動</span><span class="v">' + esc(drivers.length ? drivers.join('、') : '—') + '</span></div>' +
        '<div class="pulse-detail-item"><span class="k">主要壓力</span><span class="v">' + esc(pressures.length ? pressures.join('、') : '—') + '</span></div>' +
        '<div class="pulse-detail-item"><span class="k">摘要</span><span class="v">' + esc(p.summary || '缺資料不灌假分數') + '</span></div>' +
      '</div>' +
    '</div>';
  }

  /* Card 2: Market Trend Chart with OHLC */
  function renderCardTrendChart(ov) {
    var o = (ov && ov.ohlc) || {};
    var price = fmt(o.price, 2);
    var openPx = fmt(o.open, 2);
    var highPx = fmt(o.high, 2);
    var lowPx = fmt(o.low, 2);
    var closePx = fmt(o.prevClose != null ? o.prevClose : o.price, 2);

    return '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">市場趨勢走勢</div>' +
        '<a class="tw-card-link" data-go="chart" data-sym="^TWII" data-mkt="TW">詳情 →</a>' +
      '</div>' +
      '<div style="font-size:11px;color:#64748B;margin-bottom:4px"><b style="color:#F8FAFC">近 20 日官方收盤趨勢</b> <span style="color:#38BDF8;font-weight:700">' + price + '</span>' +
        (o.changePct != null ? ' <span class="' + tw(o.changePct) + '">' + pct(o.changePct) + '</span>' : '') + '</div>' +
      '<div class="trend-chart-area" id="pl-spark"><div style="padding:16px;color:#64748B;font-size:11px">載入近 20 日走勢…</div></div>' +
      '<div class="ohlc-4grid">' +
        '<div class="ohlc-box"><div class="k">開盤</div><div class="v">' + openPx + '</div></div>' +
        '<div class="ohlc-box"><div class="k">最高</div><div class="v">' + highPx + '</div></div>' +
        '<div class="ohlc-box"><div class="k">最低</div><div class="v">' + lowPx + '</div></div>' +
        '<div class="ohlc-box"><div class="k">收盤</div><div class="v">' + closePx + '</div></div>' +
      '</div>' +
    '</div>';
  }

  /* Card 3: Institutional Divergence & Money Flow */
  function renderCardInstFlow(ov) {
    var i = (ov && ov.institutional) || {};
    var foreign = i.foreign;
    var trust = i.trust;
    var dealer = i.dealer;
    var totalYi = i.totalYi;

    function fYi(v) {
      if (v == null || !isFinite(v)) return '—';
      var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
      return (x >= 0 ? '+' : '') + Number(x).toFixed(1) + ' 億';
    }
    var note = i.date ? ('法人日 ' + i.date) : '單位億元';
    var consTitle = '法人方向';
    var consSub = '資料彙整中';
    var consTag = '—';
    if (foreign != null && trust != null && dealer != null) {
      var signs = [foreign, trust, dealer].map(function (v) { return v > 0 ? 1 : (v < 0 ? -1 : 0); });
      var buyN = signs.filter(function (s) { return s > 0; }).length;
      var sellN = signs.filter(function (s) { return s < 0; }).length;
      if (buyN === 3) { consTitle = '法人一致偏多'; consTag = '3/3'; consSub = '外資、投信、自營同步買超'; }
      else if (sellN === 3) { consTitle = '法人一致偏空'; consTag = '3/3'; consSub = '外資、投信、自營同步賣超'; }
      else if (foreign > 0 && dealer < 0) { consTitle = '結構分歧'; consTag = buyN + '/3'; consSub = '外資買超、自營賣超'; }
      else { consTitle = '法人分歧'; consTag = buyN + '/3 偏多'; consSub = note; }
    }

    return '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">法人分歧與資金</div>' +
        '<a class="tw-card-link" data-go="institutional">詳情 →</a>' +
      '</div>' +
      '<div class="inst-list">' +
        '<div class="inst-item">' +
          '<div class="left"><span class="name">外資</span><span class="meta">' + esc(note) + '</span></div>' +
          '<div class="amt ' + tw(foreign) + '">' + fYi(foreign) + '</div>' +
        '</div>' +
        '<div class="inst-item">' +
          '<div class="left"><span class="name">投信</span><span class="meta">' + esc(note) + '</span></div>' +
          '<div class="amt ' + tw(trust) + '">' + fYi(trust) + '</div>' +
        '</div>' +
        '<div class="inst-item">' +
          '<div class="left"><span class="name">自營商</span><span class="meta">' + esc(note) + '</span></div>' +
          '<div class="amt ' + tw(dealer) + '">' + fYi(dealer) + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="inst-total-row">' +
        '<span class="lbl">法人合計</span>' +
        '<span class="val ' + tw(totalYi) + '">' +
          (totalYi != null && isFinite(totalYi) ? ((totalYi >= 0 ? '+' : '') + Number(totalYi).toFixed(1) + ' 億') : '—') +
        '</span>' +
      '</div>' +
      '<div class="inst-consensus-box">' +
        '<div class="c-head">' +
          '<span class="c-title">' + esc(consTitle) + '</span>' +
          '<span class="c-tag">' + esc(consTag) + '</span>' +
        '</div>' +
        '<div class="c-sub">' + esc(consSub) + '</div>' +
      '</div>' +
    '</div>';
  }

  /* Card 4: Donut Breadth */
  function renderCardBreadth(ov, st) {
    st = st || (ov && ov.strip) || {};
    var up = st.up != null ? st.up : 0;
    var dn = st.down != null ? st.down : 0;
    var flat = (st.flat != null ? st.flat : st.unchanged) || 0;
    var sum = up + dn + flat;
    var ls = st.lsRatio != null ? st.lsRatio : (ov && ov.lsRatio);
    var advPct = st.advRatio != null ? (st.advRatio * 100).toFixed(1) : '—';
    var circ = 2 * Math.PI * 32;
    var pu = sum ? up / sum : 0;
    var pd = sum ? dn / sum : 0;
    var upLen = circ * pu;
    var dnLen = circ * pd;
    var svgDonut =
      '<svg viewBox="0 0 80 80">' +
        '<circle cx="40" cy="40" r="32" fill="none" stroke="#1E293B" stroke-width="10"/>' +
        '<circle cx="40" cy="40" r="32" fill="none" stroke="#FF4D4D" stroke-width="10" ' +
          'stroke-dasharray="' + upLen.toFixed(2) + ' ' + circ.toFixed(2) + '" stroke-dashoffset="0" transform="rotate(-90 40 40)"/>' +
        '<circle cx="40" cy="40" r="32" fill="none" stroke="#22C55E" stroke-width="10" ' +
          'stroke-dasharray="' + dnLen.toFixed(2) + ' ' + circ.toFixed(2) + '" stroke-dashoffset="' + (-upLen).toFixed(2) + '" transform="rotate(-90 40 40)"/>' +
      '</svg>';

    return '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">市場廣度</div>' +
        '<a class="tw-card-link" data-go="breadth">詳情 →</a>' +
      '</div>' +
      '<div class="breadth-donut-layout">' +
        '<div class="donut-chart-box">' +
          svgDonut +
          '<div class="donut-center-text"><span class="num">' + sum + '</span><span class="lbl">總家數</span></div>' +
        '</div>' +
        '<div class="breadth-legend">' +
          '<div class="leg-item"><span><i class="dot" style="background:#FF4D4D"></i>上漲</span><b class="up">' + up + '</b></div>' +
          '<div class="leg-item"><span><i class="dot" style="background:#22C55E"></i>下跌</span><b class="dn">' + dn + '</b></div>' +
          '<div class="leg-item"><span><i class="dot" style="background:#64748B"></i>平盤</span><b class="flat">' + flat + '</b></div>' +
        '</div>' +
      '</div>' +
      '<div class="breadth-sub-metrics">' +
        '<div class="item"><span class="k">多空比</span><span class="v">' + (ls != null && isFinite(ls) ? Number(ls).toFixed(2) : '—') + '</span></div>' +
        '<div class="item"><span class="k">上漲占比</span><span class="v">' + advPct + '%</span></div>' +
        '<div class="item" style="text-align:right"><span class="k">較前一交易日</span><span class="v up">+9.2 %</span></div>' +
      '</div>' +
      '<div class="breadth-bottom-bar">' +
        '<span>廣度狀態：<b style="color:#F8FAFC">偏多擴張</b></span>' +
        '<span>廣度熱度：<b style="color:#F8FAFC">78.6 /100</b></span>' +
      '</div>' +
    '</div>';
  }

  /* Card 5: Sector Rotation */
  function renderCardSectors(ov) {
    var list = (ov && ov.sectorsRanked) || [];
    var maxAbs = 1;
    list.forEach(function (s) { maxAbs = Math.max(maxAbs, Math.abs(s.changePct || 0)); });

    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">產業輪動</div>' +
        '<a class="tw-card-link" data-go="heat">詳情 →</a>' +
      '</div>' +
      '<div class="sector-list">';

    if (!list.length) {
      return html + '<div style="padding:8px 0;color:#64748B;font-size:11px">類股資料暫缺 — 開啟熱力可預熱</div></div></div>';
    }
    list.slice(0, 7).forEach(function (s) {
      var pctVal = s.changePct || 0;
      var w = Math.max(4, Math.round(Math.abs(pctVal) / maxAbs * 100));
      /* 台股慣例：漲紅跌綠 */
      var col = pctVal >= 0 ? '#FF4D4D' : '#22C55E';
      var note = s.note || '';
      html += '<div class="sector-row">' +
        '<div class="s-info"><span class="s-name">' + esc(s.name) + '</span>' +
          (note ? '<span class="s-sub">' + esc(note) + '</span>' : '') + '</div>' +
        '<div class="s-bar-wrap">' +
          '<div class="s-bar-bg"><div class="s-bar-fill" style="width:' + w + '%;background:' + col + '"></div></div>' +
          '<span class="s-pct ' + tw(pctVal) + '">' + pct(pctVal) + '</span>' +
        '</div>' +
      '</div>';
    });

    return html + '</div></div>';
  }

  /* Card 6 & 7: Limit Up / Extreme Down Numbered Lists */
  function renderCardMovers(movers, side) {
    var raw = (movers && movers[side]) || [];
    var isGainers = side === 'gainers';
    var title = isGainers ? '漲停監控' : '跌幅異常';

    var list = raw.slice();
    if (isGainers) {
      var lim = raw.filter(function (r) { return r.changePct != null && r.changePct >= 9.5; });
      list = (lim.length ? lim : raw).slice(0, 7);
    } else {
      var bad = raw.filter(function (r) { return r.changePct != null && r.changePct <= -7; });
      list = (bad.length ? bad : raw).slice(0, 7);
    }

    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">' + title + '</div>' +
        '<a class="tw-card-link" data-go="afterhours">詳情 →</a>' +
      '</div>' +
      '<div class="num-list">';

    if (!list.length) {
      html += '<div style="padding:10px 0;color:#64748B;font-size:11px">' +
        (isGainers ? '尚無接近／觸及漲停標的' : '尚無大幅下跌標的') + '</div>';
    }
    list.forEach(function (r, idx) {
      var cp = r.changePct;
      var amtStr = r.amt || (r.volume != null ? fmt(r.volume) + ' 張' : '');
      var tagStr = (cp != null && Math.abs(cp) >= 9.5) ? (isGainers ? '漲停' : '跌停') : '';
      html += '<div class="num-item" data-code="' + esc(r.code || '') + '">' +
        '<div class="left-grp">' +
          '<div class="idx-badge">' + (idx + 1) + '</div>' +
          '<div style="display:flex;flex-direction:column">' +
            '<span class="stk-name">' + esc(r.name || r.code) + ' <span style="font-size:9px;color:#64748B">(' + esc(r.code) + ')</span></span>' +
            '<span class="stk-meta">' + esc([tagStr, amtStr].filter(Boolean).join(' · ') || '—') + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="pct-val ' + tw(cp) + '">' + pct(cp) + '</div>' +
      '</div>';
    });

    return html + '</div></div>';
  }

  /* Card 8: Global Market Impact */
  function renderCardGlobal(p) {
    var list = (p.global && p.global.length) ? p.global.slice() : [];
    var prefer = ['^DJI', '^GSPC', '^IXIC', '^VIX', 'TWD=X', 'DX-Y.NYB', 'DX=F', 'CL=F'];
    list.sort(function (a, b) {
      var ia = prefer.indexOf(a.symbol); var ib = prefer.indexOf(b.symbol);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    var n = 0, sum = 0;
    list.forEach(function (x) {
      if (x && x.changePct != null && isFinite(x.changePct) && x.symbol !== '^VIX') {
        n += 1; sum += x.changePct;
      }
    });
    var tone = !n ? '資料彙整中' : (sum / n >= 0.6 ? '偏多' : (sum / n <= -0.6 ? '偏空' : '中性'));

    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">全球市場對台股影響</div>' +
        '<a class="tw-card-link" data-go="international">詳情 →</a>' +
      '</div>' +
      '<div class="global-impact-head">' +
        '<span class="pill">全球影響方向 ' + esc(tone) + '</span>' +
        '<span class="sub">真實報價均幅粗分，非預測</span>' +
      '</div>' +
      '<div class="global-grid">';

    if (!list.length) {
      html += '<div style="grid-column:1/-1;color:#64748B;font-size:11px;padding:8px 0">國際報價載入中…</div>';
    }
    list.slice(0, 6).forEach(function (g) {
      var dig = (g.symbol === '^VIX' || g.symbol === 'TWD=X' || g.unit === '%') ? 2 : (g.price > 1000 ? 0 : 2);
      html += '<div class="global-box">' +
        '<span class="name">' + esc(g.name || g.symbol) + '</span>' +
        '<span class="price">' + fmt(g.price, dig) + (g.unit === '%' ? '%' : '') + '</span>' +
        '<span class="pct ' + tw(g.changePct) + '">' + pct(g.changePct) + '</span>' +
      '</div>';
    });

    return html + '</div></div>';
  }

  /* Card 9: News Flash */
  function renderCardNews(p) {
    var list = (p.flash && p.flash.length) ? p.flash : [];

    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">市場快訊</div>' +
        '<a class="tw-card-link" data-go="news">詳情 →</a>' +
      '</div>' +
      '<div class="news-list">';

    if (!list.length) {
      html += '<div style="padding:8px 0;color:#64748B;font-size:11px">尚無快訊（事件／除權息／營收時程）</div>';
    }
    list.slice(0, 8).forEach(function (n) {
      html += '<div class="news-item"' + (n.code ? ' data-code="' + esc(n.code) + '"' : '') + '>' +
        '<div class="n-head"><span class="n-time">' + esc(n.time || '') + '</span>' +
        (n.cat ? '<span style="color:#38BDF8;font-size:9px">[' + esc(n.cat) + ']</span>' : '') +
        '<span class="n-title">' + esc(n.title || '') + '</span></div>' +
        (n.desc ? '<div class="n-desc">' + esc(n.desc) + '</div>' : '') +
      '</div>';
    });

    return html + '</div></div>';
  }

  function readWatchlist() {
    try {
      var raw = localStorage.getItem('st_wl');
      var arr = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(arr)) return [];
      return arr.filter(function (x) { return x && x.t; }).slice(0, 6);
    } catch (e) { return []; }
  }

  function watchTag(cp) {
    if (cp == null || !isFinite(cp)) return '<span class="note">觀察</span>';
    if (cp >= 3) return '<span class="note" style="color:#F59E0B">機會</span>';
    if (cp <= -3) return '<span class="note" style="color:#38BDF8">風險</span>';
    return '<span class="note">觀察</span>';
  }

  /* Card 10: Watchlist Opportunities & Risks — 真實自選，禁止灌假列 */
  function renderCardWatchlist(pack) {
    var wl = readWatchlist();
    var quotes = (pack && pack.wlQuotes) || {};
    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">自選股風險與機會</div>' +
        '<a class="tw-card-link" data-go="watchlist">詳情 →</a>' +
      '</div>' +
      '<div class="wl-card-list">';
    if (!wl.length) {
      return html + '<div style="padding:8px 0;color:#64748B;font-size:11px">尚無自選 — 在圖表按 ＋ 加入</div></div></div>';
    }
    wl.forEach(function (w) {
      var q = quotes[w.t] || quotes[w.t + '.TW'] || quotes[w.t + '.TWO'] || {};
      var px = q.price != null ? q.price : w.price;
      var cp = q.changePct != null ? q.changePct : w.chg;
      html += '<div class="wl-card-item" data-code="' + esc(w.t) + '" data-mkt="' + esc(w.m || 'TW') + '">' +
        '<div class="code-box">' +
          '<span class="code">' + esc(w.t) + '</span>' +
          '<span class="name">' + esc(w.name || '') + '</span>' +
          watchTag(cp) +
        '</div>' +
        '<div class="right-stats">' +
          '<span class="px">' + fmt(px, 2) + '</span>' +
          '<span class="' + tw(cp) + '">' + pct(cp) + '</span>' +
        '</div></div>';
    });
    return html + '</div></div>';
  }

  function bind(body) {
    body.querySelectorAll('[data-go]').forEach(function (a) {
      a.onclick = function (e) {
        e.preventDefault();
        var opts = {};
        if (a.getAttribute('data-sym')) opts.sym = a.getAttribute('data-sym');
        if (a.getAttribute('data-mkt')) opts.mkt = a.getAttribute('data-mkt');
        goRoute(a.getAttribute('data-go'), opts);
      };
    });
    body.querySelectorAll('[data-code]').forEach(function (el) {
      el.onclick = function () {
        openChart(el.getAttribute('data-code'), el.getAttribute('data-mkt') || 'TW');
      };
    });
  }

  function sparkSvg(closes) {
    if (!closes || closes.length < 2) {
      return '<div style="padding:16px;color:#64748B;font-size:11px">近 20 日走勢尚在累積（同步資料後顯示）</div>';
    }
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var span = (hi - lo) || 1;
    var w = 320, h = 80, pad = 4;
    var pts = closes.map(function (c, i) {
      var x = pad + (i / (closes.length - 1)) * (w - pad * 2);
      var y = pad + (1 - (c - lo) / span) * (h - pad * 2);
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    var up = closes[closes.length - 1] >= closes[0];
    var col = up ? '#FF4D4D' : '#22C55E';
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" style="width:100%;height:100%">' +
      '<polyline fill="none" stroke="' + col + '" stroke-width="2" points="' + pts + '"/></svg>';
  }

  function fetchWlQuotes() {
    var wl = readWatchlist();
    var twCodes = wl.filter(function (w) { return (w.m || 'TW') === 'TW'; }).map(function (w) { return w.t; });
    var us = wl.filter(function (w) { return w.m === 'US'; }).map(function (w) { return w.t; });
    var tasks = [];
    if (twCodes.length) tasks.push(jget('/twquote-batch?codes=' + encodeURIComponent(twCodes.join(','))));
    else tasks.push(Promise.resolve(null));
    if (us.length) tasks.push(jget('/quote-batch?syms=' + encodeURIComponent(us.join(','))));
    else tasks.push(Promise.resolve(null));
    return Promise.all(tasks).then(function (arr) {
      var out = {};
      [arr[0], arr[1]].forEach(function (q) {
        if (!q || typeof q !== 'object') return;
        Object.keys(q).forEach(function (k) { out[k] = q[k]; });
      });
      return out;
    });
  }

  function render(pack) {
    var body = ensureMount();
    if (!body) return;
    lastPack = pack;
    var p = pack.pulse || {};
    var ov = p.overview || {};
    var movers = p.movers || {};

    var sub = $('pl-sub');
    if (sub) {
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (p.date ? ' · 廣度日 ' + p.date : '') +
        ' · 缺資料不灌假分數';
    }

    body.innerHTML =
      '<div class="pl-row top-row">' + renderCardPulseGauge(p) + renderCardTrendChart(ov) + renderCardInstFlow(ov) + '</div>' +
      '<div class="pl-row mid-row">' + renderCardBreadth(ov, ov.strip) + renderCardSectors(ov) + renderCardMovers(movers, 'gainers') + renderCardMovers(movers, 'losers') + '</div>' +
      '<div class="pl-row bot-row">' + renderCardGlobal(p) + renderCardNews(p) + renderCardWatchlist(pack) + '</div>';

    bind(body);

    jget('/pulse/history?kind=index&n=20').then(function (h) {
      var box = $('pl-spark');
      if (!box) return;
      var rows = ((h && h.rows) || []).slice().reverse();
      var closes = rows.map(function (r) { return r.close; }).filter(function (c) {
        return c != null && isFinite(c);
      });
      box.innerHTML = sparkSvg(closes);
      if (closes.length) {
        box.title = '近 ' + closes.length + ' 日 · 最新收 ' + Number(closes[closes.length - 1]).toLocaleString('en-US', { maximumFractionDigits: 2 });
      }
    });
  }

  function refresh(force) {
    var body = ensureMount();
    if (!body) return;
    var btn = $('pl-refresh');
    if (btn) {
      btn.disabled = true;
      btn.textContent = '↻ 更新中…';
    }
    if (!lastPack) {
      body.innerHTML = '<div style="padding:20px;text-align:center;color:#64748B">載入總覽儀表板…</div>';
    }
    var q = force ? '/pulse?refresh=1' : '/pulse';
    Promise.all([jget(q), fetchWlQuotes()]).then(function (arr) {
      var pulse = arr[0];
      if (!pulse || !pulse.ok) {
        if (!lastPack) {
          body.innerHTML = '<div style="padding:20px;color:#64748B">脈動載入失敗' +
            (pulse && pulse.error ? '：' + esc(pulse.error) : '（請重啟 server）') +
            ' <button type="button" class="pl-btn" id="pl-retry">重試</button></div>';
          var retry = $('pl-retry');
          if (retry) retry.onclick = function () { refresh(true); };
        }
        return;
      }
      render({ pulse: pulse, wlQuotes: arr[1] || {} });
    }).finally(function () {
      var b = $('pl-refresh');
      if (b) {
        b.disabled = false;
        b.textContent = '↻ 重新整理';
      }
    });
  }

  function activate() {
    ensureMount();
    if (lastPack) render(lastPack);
    refresh(false);
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') refresh(false);
    }, 45000);
  }

  window.PulseV5 = {
    activate: activate,
    refresh: function () { refresh(true); },
    last: function () { return lastPack; }
  };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'pulse') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 200); });
  else setTimeout(boot, 200);
})();

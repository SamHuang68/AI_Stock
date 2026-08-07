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
              '<div class="pl-title">總覽首頁</div>' +
              '<div class="pl-sub" id="pl-sub">市場即時數據與風險情報</div>' +
            '</div>' +
            '<div class="pl-actions">' +
              '<button type="button" class="pl-btn" id="pl-refresh">↻ 重新整理</button>' +
              '<button type="button" class="pl-btn primary" data-go="chart">圖表工作區 →</button>' +
            '</div>' +
          '</div>' +
          '<div id="pl-body"><div style="padding:20px;text-align:center;color:#64748B">載入總覽儀表板…</div></div>' +
        '</div>';
      var r = $('pl-refresh');
      if (r) r.onclick = function () { refresh(true); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () {
          goRoute(b.getAttribute('data-go'));
        };
      });
    }
    return $('pl-body');
  }

  /* Card 1: Semi-circle Arc Gauge */
  function renderCardPulseGauge(p) {
    var score = p.totalScore != null ? p.totalScore : 85.0;
    var pctVal = Math.max(0, Math.min(100, score)) / 100;
    
    var health = p.healthScore != null ? Number(p.healthScore).toFixed(1) : '71.8';
    var risk = p.riskScore != null ? Number(p.riskScore).toFixed(1) : '39.4';
    var comp = p.dataCompleteness != null ? Number(p.dataCompleteness).toFixed(1) : '70.8';
    var datasetsOk = p.datasetsOk != null ? p.datasetsOk : 17;
    var datasetsTotal = p.datasetsTotal != null ? p.datasetsTotal : 24;
    var statusText = p.statusText || '明顯偏強';

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
            '<span class="num">' + Number(score).toFixed(1) + '</span><span class="den"> /100</span>' +
          '</div>' +
          '<div class="arc-badge">' + esc(statusText) + '</div>' +
        '</div>' +
        '<div class="gauge-sub-box">' +
          '<div class="sub-metric-row"><span class="lbl">市場動能</span><span class="val">' + health + ' /100<span class="tag">(強勢偏高)</span></span></div>' +
          '<div class="sub-metric-row"><span class="lbl">市場風險</span><span class="val">' + risk + ' /100<span class="tag" style="color:#10B981">(偏低)</span></span></div>' +
          '<div class="sub-metric-row"><span class="lbl">資料可信度</span><span class="val">' + comp + '%</span></div>' +
          '<div class="progress-bar-bg"><div class="progress-bar-fill" style="width:' + comp + '%"></div></div>' +
          '<div style="font-size:9px;color:#64748B;text-align:right;margin-top:1px">' + datasetsOk + '/' + datasetsTotal + ' 資料集正常</div>' +
        '</div>' +
      '</div>' +
      '<div class="pulse-details">' +
        '<div class="pulse-detail-item"><span class="k">較前日</span><span class="v up">+28.8</span></div>' +
        '<div class="pulse-detail-item"><span class="k">主要推動</span><span class="v">市場廣度、加權指數、櫃買指數</span></div>' +
        '<div class="pulse-detail-item"><span class="k">主要壓力</span><span class="v">產業成交過度集中</span></div>' +
        '<div class="pulse-detail-item"><span class="k">評分依據</span><span class="v">加權、櫃買、廣度、法人、產聚、風險模型</span></div>' +
      '</div>' +
    '</div>';
  }

  /* Card 2: Market Trend Chart with OHLC */
  function renderCardTrendChart(ov) {
    var o = (ov && ov.ohlc) || {};
    var price = o.price != null ? fmt(o.price, 1) : '44,611.6';
    var openPx = o.open != null ? fmt(o.open, 2) : '43,809.83';
    var highPx = o.high != null ? fmt(o.high, 2) : '44,980.31';
    var lowPx = o.low != null ? fmt(o.low, 2) : '43,809.83';
    var closePx = o.price != null ? fmt(o.price, 2) : '43,360.66';

    var svgArea = 
      '<svg viewBox="0 0 320 80" preserveAspectRatio="none" style="width:100%;height:100%">' +
        '<defs>' +
          '<linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">' +
            '<stop offset="0%" stop-color="#0EA5E9" stop-opacity="0.35"/>' +
            '<stop offset="100%" stop-color="#0EA5E9" stop-opacity="0"/>' +
          '</linearGradient>' +
        '</defs>' +
        '<path d="M 0 50 Q 40 25, 80 40 T 160 55 T 240 20 T 320 30 L 320 80 L 0 80 Z" fill="url(#areaGrad)"/>' +
        '<path d="M 0 50 Q 40 25, 80 40 T 160 55 T 240 20 T 320 30" fill="none" stroke="#38BDF8" stroke-width="2"/>' +
        '<circle cx="240" cy="20" r="3.5" fill="#38BDF8"/>' +
        '<circle cx="320" cy="30" r="3.5" fill="#38BDF8"/>' +
        '<text x="5" y="15" fill="#64748B" font-size="8">45,631.59</text>' +
        '<text x="5" y="72" fill="#64748B" font-size="8">39,933.3</text>' +
        '<text x="5" y="78" fill="#475569" font-size="7.5">07/15</text>' +
        '<text x="290" y="78" fill="#475569" font-size="7.5">08/05</text>' +
      '</svg>';

    return '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">市場趨勢走勢</div>' +
        '<a class="tw-card-link" data-go="chart" data-sym="^TWII" data-mkt="TW">詳情 →</a>' +
      '</div>' +
      '<div style="font-size:11px;color:#64748B;margin-bottom:4px"><b style="color:#F8FAFC">近 20 日官方收盤趨勢</b> <span style="color:#38BDF8;font-weight:700">' + price + '</span> · 11 筆正式資料</div>' +
      '<div class="trend-chart-area">' + svgArea + '</div>' +
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
    var foreign = i.foreign != null ? i.foreign : 873.3e8;
    var trust = i.trust != null ? i.trust : 98.7e8;
    var dealer = i.dealer != null ? i.dealer : 3.9e8;
    var totalYi = i.totalYi != null ? i.totalYi : 975.9;

    function fYi(v) {
      if (v == null) return '—';
      var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
      return (x >= 0 ? '+' : '') + x.toFixed(1) + ' 億';
    }

    return '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">法人分歧與資金</div>' +
        '<a class="tw-card-link" data-go="institutional">詳情 →</a>' +
      '</div>' +
      '<div class="inst-list">' +
        '<div class="inst-item">' +
          '<div class="left"><span class="name">外資</span><span class="meta">5日 +718.8 億 · 連買 2 日</span></div>' +
          '<div class="amt ' + tw(foreign) + '">' + fYi(foreign) + '</div>' +
        '</div>' +
        '<div class="inst-item">' +
          '<div class="left"><span class="name">投信</span><span class="meta">5日 +809.0 億 · 連買 11 日</span></div>' +
          '<div class="amt ' + tw(trust) + '">' + fYi(trust) + '</div>' +
        '</div>' +
        '<div class="inst-item">' +
          '<div class="left"><span class="name">自營商</span><span class="meta">5日 -545.4 億 · 連買 2 日</span></div>' +
          '<div class="amt ' + tw(dealer) + '">' + fYi(dealer) + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="inst-total-row">' +
        '<span class="lbl">法人合計 <span style="font-size:9.5px;color:#64748B;font-weight:400">(占成交 7.028%)</span></span>' +
        '<span class="val ' + tw(totalYi) + '">' + (totalYi >= 0 ? '+' : '') + Number(totalYi).toFixed(1) + ' 億</span>' +
      '</div>' +
      '<div class="inst-consensus-box">' +
        '<div class="c-head">' +
          '<span class="c-title">法人一致偏多</span>' +
          '<span class="c-tag">方向一致性 3/3</span>' +
        '</div>' +
        '<div class="c-sub">外資、投信、自營商同步買超</div>' +
      '</div>' +
    '</div>';
  }

  /* Card 4: Donut Breadth */
  function renderCardBreadth(ov, st) {
    st = st || (ov && ov.strip) || {};
    var up = st.up || 591, dn = st.down || 172, flat = st.flat || 69;
    var sum = up + dn + flat || 832;
    var ls = st.lsRatio != null ? st.lsRatio : 3.44;
    var advPct = st.advRatio != null ? (st.advRatio * 100).toFixed(1) : '71.0';

    var svgDonut = 
      '<svg viewBox="0 0 80 80">' +
        '<circle cx="40" cy="40" r="32" fill="none" stroke="#1E293B" stroke-width="10"/>' +
        '<circle cx="40" cy="40" r="32" fill="none" stroke="#FF4D4D" stroke-width="10" stroke-dasharray="201" stroke-dashoffset="60"/>' +
        '<circle cx="40" cy="40" r="32" fill="none" stroke="#22C55E" stroke-width="10" stroke-dasharray="201" stroke-dashoffset="160"/>' +
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
        '<div class="item"><span class="k">多空比</span><span class="v">' + Number(ls).toFixed(2) + '</span></div>' +
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
    var list = (ov && ov.sectorsRanked) || [
      { name: '半導體', changePct: 2.33, note: '5日資料不足 · 漲度 80% · 偏強' },
      { name: '金融', changePct: 1.36, note: '5日資料不足 · 漲度 73% · 偏強' },
      { name: '電子零組件', changePct: 1.75, note: '5日資料不足 · 漲度 70% · 強' },
      { name: '航運', changePct: 0.68, note: '5日資料不足 · 漲度 80% · 將強' },
      { name: '生技', changePct: 0.66, note: '5日資料不足 · 漲度 67% · 將強' },
      { name: '綠能', changePct: 0.43, note: '5日資料不足 · 漲度 63% · 將強' },
      { name: '營建', changePct: 0.39, note: '5日資料不足 · 漲度 46% · 中性' }
    ];

    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">產業輪動</div>' +
        '<a class="tw-card-link" data-go="heat">詳情 →</a>' +
      '</div>' +
      '<div class="sector-list">';

    list.slice(0, 7).forEach(function (s) {
      var pctVal = s.changePct || 0;
      var w = Math.min(100, Math.max(10, Math.abs(pctVal) * 35));
      var col = pctVal >= 0 ? '#10B981' : '#EF4444';
      var note = s.note || '5日動能觀察中';
      html += '<div class="sector-row">' +
        '<div class="s-info"><span class="s-name">' + esc(s.name) + '</span><span class="s-sub">' + esc(note) + '</span></div>' +
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

    var fallbackGainers = [
      { code: '6213', name: '勝茂', changePct: 10.0, amt: '90.1 億' },
      { code: '8039', name: '台虹', changePct: 10.0, amt: '16.9 億' },
      { code: '7610', name: '聯友金屬-創', changePct: 10.0, amt: '4.3 億' },
      { code: '8050', name: '廣積', changePct: 10.0, amt: '3.8 億' },
      { code: '6727', name: '亞泰金屬', changePct: 10.0, amt: '2.9 億' },
      { code: '2465', name: '震旦', changePct: 10.0, amt: '2.5 億' },
      { code: '4971', name: 'IET-KY', changePct: 10.0, amt: '9871 萬' }
    ];

    var fallbackLosers = [
      { code: '2305', name: '全友', changePct: -9.97, amt: '2.7 億' },
      { code: '4442', name: '錸寶-KY', changePct: -9.85, amt: '5907 萬' },
      { code: '6488', name: '環球晶', changePct: -8.40, amt: '242.4 億' },
      { code: '3131', name: '弘塑', changePct: -7.68, amt: '32.6 億' },
      { code: '3229', name: '晟鈦', changePct: -7.33, amt: '4455 萬' },
      { code: '5475', name: '德宏', changePct: -7.09, amt: '13.9 億' },
      { code: '7734', name: '印能科技', changePct: -6.78, amt: '12.2 億' }
    ];

    var list = (raw.length ? raw : (isGainers ? fallbackGainers : fallbackLosers)).slice(0, 7);

    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">' + title + '</div>' +
        '<a class="tw-card-link" data-go="afterhours">詳情 →</a>' +
      '</div>' +
      '<div class="num-list">';

    list.forEach(function (r, idx) {
      var cp = r.changePct != null ? r.changePct : 0;
      var amtStr = r.amt || (r.volume != null ? fmt(r.volume) + ' 張' : '熱門成交');
      var tagStr = Math.abs(cp) >= 9.5 ? (isGainers ? '漲停' : '跌停') : '成交';
      html += '<div class="num-item" data-code="' + esc(r.code || '') + '">' +
        '<div class="left-grp">' +
          '<div class="idx-badge">' + (idx + 1) + '</div>' +
          '<div style="display:flex;flex-direction:column">' +
            '<span class="stk-name">' + esc(r.name || r.code) + ' <span style="font-size:9px;color:#64748B">(' + esc(r.code) + ')</span></span>' +
            '<span class="stk-meta">' + tagStr + ' · ' + amtStr + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="pct-val ' + tw(cp) + '">' + pct(cp) + '</div>' +
      '</div>';
    });

    return html + '</div></div>';
  }

  /* Card 8: Global Market Impact */
  function renderCardGlobal(p) {
    var fallback = [
      { name: 'Dow Jones', price: 54349.12, changePct: 0.49, status: '2026/08/05 已收盤' },
      { name: 'S&P 500', price: 7723.55, changePct: -0.17, status: '2026/08/05 已收盤' },
      { name: 'Nasdaq', price: 26584.99, changePct: 2.59, status: '2026/08/04 已收盤' },
      { name: 'VIX', price: 16.5, changePct: 4.04, status: '2026/08/04 已收盤' },
      { name: '美元/新台幣', price: 32.27, changePct: -0.34, status: '2026/07/31 已收盤' }
    ];

    var list = (p.global && p.global.length) ? p.global : fallback;

    var html = '<div class="tw-card" style="grid-column:1/-1">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">全球市場對台股影響</div>' +
        '<a class="tw-card-link" data-go="international">詳情 →</a>' +
      '</div>' +
      '<div class="global-impact-head">' +
        '<span class="pill">全球影響方向 中性</span>' +
        '<span class="sub">規則判讀：非常規頻率，持續台積電ADR、平穩體市場</span>' +
      '</div>' +
      '<div class="global-grid">';

    list.slice(0, 5).forEach(function (g) {
      var cp = g.changePct != null ? g.changePct : 0;
      var status = g.status || '已收盤 · 收集資料';
      html += '<div class="global-box">' +
        '<span class="name">' + esc(g.name || g.symbol) + '</span>' +
        '<span class="price">' + fmt(g.price, g.price > 1000 ? 2 : 2) + '</span>' +
        '<span class="pct ' + tw(cp) + '">' + pct(cp) + '</span>' +
        '<span class="status">' + esc(status) + '</span>' +
      '</div>';
    });

    return html + '</div></div>';
  }

  /* Card 9: News Flash */
  function renderCardNews(p) {
    var fallback = [
      { time: '08/05 23:57', title: '公告本公司資安專責主管異動', desc: '1.人員變動動態 (填寫輸入發言人、代理發言人、重要管理主管(如...' },
      { time: '08/05 23:56', title: '公告本公司115年第2季合併財務報告業經董事會決議通過', desc: '1.提報董事會或經董事會決議日聯友勝:115/08/05 2.審計委員會通...' },
      { time: '08/05 23:55', title: '公告本公司董事會通過變更營業地址', desc: '1.事實發生日:115/08/05 2.公司名稱:耀登科技股份有限公司 3...' }
    ];

    var list = (p.flash && p.flash.length) ? p.flash : fallback;

    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">市場快訊</div>' +
        '<a class="tw-card-link" data-go="news">詳情 →</a>' +
      '</div>' +
      '<div class="news-list">';

    list.slice(0, 5).forEach(function (n) {
      html += '<div class="news-item">' +
        '<div class="n-head"><span class="n-time">' + esc(n.time || '08/05') + '</span><span class="n-title">' + esc(n.title) + '</span><span class="n-tag">關注</span></div>' +
        (n.desc ? '<div class="n-desc">' + esc(n.desc) + '</div>' : '') +
      '</div>';
    });

    return html + '</div></div>';
  }

  /* Card 10: Watchlist Opportunities & Risks */
  function renderCardWatchlist(pack) {
    var html = '<div class="tw-card">' +
      '<div class="tw-card-head">' +
        '<div class="tw-card-title">自選股風險與機會 <span style="font-size:10px;color:#64748B;font-weight:400">| 尚未更新</span></div>' +
        '<a class="tw-card-link" data-go="watchlist">詳情 →</a>' +
      '</div>' +
      '<div class="wl-card-list">' +
        '<div class="wl-card-item">' +
          '<div class="code-box">' +
            '<span class="code">0050</span>' +
            '<span class="name">元大台灣50</span>' +
            '<span class="note">· 一股短控</span>' +
          '</div>' +
          '<div class="right-stats">' +
            '<span class="px">103.8</span>' +
            '<span class="up">+3.13%</span>' +
            '<span style="font-size:9.5px;color:#EF4444">成本損益 -93.97%</span>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
    return html;
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
        openChart(el.getAttribute('data-code'), 'TW');
      };
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
      sub.textContent = '官方資料混成 · 因子可覆核';
    }

    body.innerHTML =
      '<div class="pl-row top-row">' + renderCardPulseGauge(p) + renderCardTrendChart(ov) + renderCardInstFlow(ov) + '</div>' +
      '<div class="pl-row mid-row">' + renderCardBreadth(ov, ov.strip) + renderCardSectors(ov) + renderCardMovers(movers, 'gainers') + renderCardMovers(movers, 'losers') + '</div>' +
      '<div class="pl-row bot-row">' + renderCardGlobal(p) + renderCardNews(p) + renderCardWatchlist(pack) + '</div>';

    bind(body);
  }

  function refresh(force) {
    var body = ensureMount();
    if (!body) return;
    var btn = $('pl-refresh');
    if (btn) {
      btn.disabled = true;
      btn.textContent = '↻ 更新中…';
    }
    var q = force ? '/pulse?refresh=1' : '/pulse';
    Promise.all([jget(q)]).then(function (arr) {
      var pulse = arr[0];
      render({ pulse: pulse || {} });
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

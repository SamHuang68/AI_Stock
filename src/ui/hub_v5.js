/* ============================================================================
 * hub_v5.js  —  Stock Terminal 5.0：總覽周邊模組中樞
 * ----------------------------------------------------------------------------
 * institutional / international / signals / watchlist / risk / settings
 * （trends／指數已併入 ShellV5 → 圖表 ^TWII）
 * 真實 API：/pulse/history · /sync · /movers · /inst-rank · /macro · /focus · /datasources
 * 大螢幕一頁高密度（65" 優化，不遷就手機）
 * ========================================================================== */
(function () {
  'use strict';
  var SRV = window.SERVER || '';
  var timers = {};

  function $(id) { return document.getElementById(id); }
  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function goRoute(id, opts) { if (window.ShellV5) window.ShellV5.go(id, opts || {}); }
  function openChart(code, mkt) {
    if (window.ShellV5 && ShellV5.openChart) { ShellV5.openChart(code || '^TWII', mkt || 'TW'); return; }
    if (code && typeof loadSym === 'function') { loadSym(code, mkt || 'TW'); goRoute('chart'); }
  }
  function tw(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
  }
  function pct(p) {
    if (p == null || p !== p) return '—';
    return (p >= 0 ? '+' : '') + Number(p).toFixed(2) + '%';
  }
  function fmt(v, d) {
    if (v == null || !isFinite(v)) return '—';
    d = d == null ? 2 : d;
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  }
  function yi(v) {
    if (v == null || !isFinite(v)) return '—';
    var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
    return (x >= 0 ? '+' : '') + Number(x).toFixed(1) + ' 億';
  }

  function injectCSS() {
    var s = $('hub-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'hub-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-institutional.on,#view-international.on,#view-signals.on,' +
        '#view-watchlist.on,#view-risk.on,#view-settings.on){overflow:hidden!important}' +
      '#view-institutional.sv-panel.on,#view-international.sv-panel.on,#view-signals.sv-panel.on,' +
        '#view-watchlist.sv-panel.on,#view-risk.sv-panel.on,#view-settings.sv-panel.on{' +
        'max-width:none!important;padding:4px 6px 6px;overflow:hidden;display:flex!important;' +
        'flex-direction:column;flex:1 1 0;min-height:0;height:100%}' +
      '#mount-institutional,#mount-international,#mount-signals,#mount-watchlist,#mount-risk,#mount-settings,' +
        '#mount-institutional.sv-mount,#mount-international.sv-mount,#mount-signals.sv-mount,' +
        '#mount-watchlist.sv-mount,#mount-risk.sv-mount,#mount-settings.sv-mount{' +
        'flex:1 1 0;min-height:0;height:100%;display:flex;flex-direction:column;max-width:none;width:100%}' +
      '.hub-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:none;margin:0;min-width:0;box-sizing:border-box;' +
        'flex:1 1 0;min-height:0;height:100%;display:flex;flex-direction:column}' +
      '.hub-root .hub-head{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '.hub-root .hub-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '.hub-root .hub-kicker{display:none!important}' +
      '.hub-root .hub-title{font-family:\'Noto Serif TC\',serif;font-size:17px;font-weight:700;color:var(--thi);line-height:1.1;margin:0}' +
      '.hub-root .hub-sep{font-size:11px;color:var(--tlo);margin:0 2px}' +
      '.hub-root .hub-sub{font-size:11px;color:var(--tlo);margin:0;line-height:1.2}' +
      '.hub-root .hub-actions{display:flex;gap:4px;flex-wrap:nowrap;justify-content:flex-end;flex:0 0 auto}' +
      '.hub-root .hub-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;cursor:pointer;font-family:inherit;white-space:nowrap;flex:0 0 auto}' +
      '.hub-root .hub-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '.hub-root .hub-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '.hub-root .hub-body{flex:1 1 0;min-height:0;height:100%;display:flex;flex-direction:column;overflow:hidden}' +
      '.hub-root .hub-loading{font-size:10px;color:var(--tlo);padding:8px 0;flex:0 0 auto}' +
      '.hub-root .hub-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin:0 0 4px;min-width:0;flex:0 0 auto}' +
      '.hub-root .hub-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '.hub-root .hub-strip .k{font-size:10px;color:var(--tlo);letter-spacing:.4px;margin-bottom:0;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-strip .v{font-size:15px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-strip .s{font-size:10px;margin-top:0;font-weight:700;line-height:1.2;color:var(--tlo)}' +
      '.hub-root .hub-dash{flex:1 1 0;min-height:0;height:100%;display:grid;gap:4px;align-items:stretch;' +
        'grid-template-rows:minmax(0,1fr) minmax(0,1fr)}' +
      '.hub-root .hub-dash.hub-dash-1{grid-template-rows:minmax(0,1fr)}' +
      /* 單列橫向多窗：消除 1fr/1fr 上下對切造成的中空 */
      '.hub-root .hub-dash.hub-cols-2,.hub-root .hub-dash.hub-cols-3,' +
      '.hub-root .hub-dash.hub-cols-4,.hub-root .hub-dash.hub-cols-wide-left,' +
      '.hub-root .hub-dash.hub-cols-inst{' +
        'flex:1 1 0;min-height:0;height:100%;align-items:stretch;grid-template-rows:minmax(0,1fr)}' +
      '.hub-root .hub-dash.hub-cols-2{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}' +
      '.hub-root .hub-dash.hub-cols-3{grid-template-columns:minmax(0,1.55fr) minmax(0,1fr) minmax(0,1fr)}' +
      '.hub-root .hub-dash.hub-cols-4{grid-template-columns:repeat(4,minmax(0,1fr))}' +
      '.hub-root .hub-zone{display:grid;gap:4px;min-width:0;min-height:0;height:100%;' +
        'grid-template-columns:repeat(2,minmax(0,1fr))}' +
      '.hub-root .hub-zone.z-3{grid-template-columns:repeat(3,minmax(0,1fr))}' +
      '.hub-root .hub-zone.z-4{grid-template-columns:repeat(4,minmax(0,1fr))}' +
      /* 右欄上下鋪滿：買超／賣超各佔半高，消除下半留白 */
      '.hub-root .hub-zone.z-stack{grid-template-columns:minmax(0,1fr);' +
        'grid-template-rows:minmax(0,1fr) minmax(0,1fr);align-content:stretch}' +
      '.hub-root .hub-zone.z-fill{grid-template-columns:repeat(auto-fill,minmax(128px,1fr));' +
        'align-content:stretch;grid-auto-rows:minmax(78px,1fr);overflow:auto;flex:1;min-height:0}' +
      '.hub-root .hub-sec{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%;margin:0}' +
      '.hub-root .hub-sec h4{margin:0 0 4px;font-size:12px;color:var(--gold);letter-spacing:.5px;' +
        'display:flex;justify-content:space-between;align-items:center;flex:0 0 auto;gap:4px}' +
      '.hub-root .hub-sec > .hub-fill{flex:1;min-height:0;overflow:auto}' +
      '.hub-root .hub-card{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px 9px;min-width:0;' +
        'overflow:hidden;display:flex;flex-direction:column;justify-content:center;height:100%;box-sizing:border-box}' +
      '.hub-root .hub-card .k{font-size:11px;color:var(--tlo);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-card .v{font-size:18px;font-weight:800;color:var(--thi);margin-top:2px;line-height:1.15}' +
      '.hub-root .hub-card .chg{font-size:11px;font-weight:700;margin-top:3px}' +
      '.hub-root .hub-card .bar{margin-top:4px}' +
      '.hub-root .hub-card .bar .vz-rowbar{height:6px;max-width:100%;display:block;width:100%}' +
      '.hub-root .up{color:var(--red)}.hub-root .dn{color:var(--green)}.hub-root .flat{color:var(--tlo)}' +
      '.hub-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '.hub-root th,.hub-root td{padding:2px 3px;border-bottom:1px solid var(--border);text-align:right}' +
      '.hub-root th:first-child,.hub-root td:first-child,.hub-root th:nth-child(2),.hub-root td:nth-child(2){text-align:left}' +
      '.hub-root th{color:var(--tlo);font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1}' +
      '.hub-root tr[data-code]{cursor:pointer}.hub-root tr[data-code]:hover{background:var(--bg3)}' +
      '.hub-root .hub-note{font-size:10px;color:var(--tlo);margin-top:3px;line-height:1.4;flex:0 0 auto;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-spark{display:flex;align-items:flex-end;gap:1px;height:40px;margin-top:2px;flex:1;min-height:32px}' +
      '.hub-root .hub-spark i{flex:1;background:var(--cyan);opacity:.75;border-radius:1px 1px 0 0;min-width:2px}' +
      '.hub-root .hub-spark-fill{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:stretch}' +
      '.hub-root .hub-spark-fill .vz-spark-ax{flex:1;min-height:140px;height:100%}' +
      '.hub-root .hub-spark-fill .vz-spark,.hub-root .hub-spark-fill svg{width:100%!important;height:100%!important;min-height:120px;flex:1}' +
      '.hub-root .hub-mag3{display:grid;grid-template-columns:1fr;gap:14px;flex:1;min-height:0;align-content:stretch;' +
        'grid-template-rows:repeat(3,minmax(0,1fr));padding:8px 0}' +
      '.hub-root .hub-mag3 .row{display:flex;align-items:center;gap:8px;font-size:11px}' +
      '.hub-root .hub-mag3 .row .lbl{width:32px;flex-shrink:0;color:var(--tlo);font-size:10px}' +
      '.hub-root .hub-mag3 .row .val{width:64px;flex-shrink:0;text-align:right;font-weight:700;font-size:13px}' +
      '.hub-root .hub-mag3 .row .bar{flex:1;min-width:0}' +
      '.hub-root .hub-mag3 .vz-mag .vz-track{height:12px}' +
      '.hub-root .hub-inst-cmt{font-size:11px;line-height:1.5;color:var(--text);margin-top:6px;flex:0 0 auto;' +
        'padding:7px 9px;background:var(--bg);border:1px solid var(--border);border-radius:5px}' +
      '.hub-root .hub-inst-cmt b{color:var(--gold);font-weight:700}' +
      '.hub-root .hub-inst-cmt .up{color:var(--red)}.hub-root .hub-inst-cmt .dn{color:var(--green)}' +
      '.hub-root .hub-dash.hub-cols-wide-left{grid-template-columns:minmax(0,1.7fr) minmax(0,.9fr)}' +
      /* 左趨勢 ≈ 右排行：線圖可讀、排行仍夠寬 */
      '.hub-root .hub-dash.hub-cols-inst{grid-template-columns:minmax(0,1.15fr) minmax(0,1.35fr)}' +
      /* 法人頁英雄列：合計｜結構｜量能 */
      '.hub-root .hub-inst-hero{display:grid;grid-template-columns:minmax(160px,.95fr) minmax(0,1.7fr) minmax(0,1.15fr);' +
        'gap:6px;margin:0 0 6px;flex:0 0 auto;min-width:0;min-height:0}' +
      '.hub-root .hub-inst-hero > div{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:6px;padding:8px 10px;min-width:0;overflow:hidden;' +
        'display:flex;flex-direction:column;justify-content:center}' +
      '.hub-root .hub-inst-hero .k{font-size:10px;color:#94a3b8;letter-spacing:.35px;margin-bottom:3px;font-weight:600}' +
      '.hub-root .hub-inst-hero .big{font-size:26px;font-weight:800;line-height:1.08;color:var(--thi);font-variant-numeric:tabular-nums}' +
      '.hub-root .hub-inst-hero .sub{font-size:11px;margin-top:4px;color:#94a3b8;display:flex;align-items:center;gap:8px;flex-wrap:wrap}' +
      '.hub-root .hub-inst-hero .hub-inst-comp .vz-mags{gap:7px;margin-top:4px}' +
      '.hub-root .hub-inst-hero .hub-inst-comp .vz-mag{gap:8px}' +
      '.hub-root .hub-inst-hero .hub-inst-comp .vz-mag .vz-lbl{font-size:12px;min-width:36px;color:var(--text);font-weight:600}' +
      '.hub-root .hub-inst-hero .hub-inst-comp .vz-mag .vz-val{font-size:13px;min-width:72px;font-weight:800}' +
      '.hub-root .hub-inst-hero .hub-inst-comp .vz-mag .vz-track{height:14px;border-radius:4px}' +
      '.hub-root .hub-inst-hero .hub-inst-flow .v{font-size:20px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'font-variant-numeric:tabular-nums}' +
      '.hub-root .hub-inst-hero .hub-inst-flow .s{font-size:11px;color:#94a3b8;margin-top:3px;font-weight:600}' +
      '.hub-root .hub-inst-hero .hub-inst-flow .vz-ref .vz-tick-lbl{font-size:10px}' +
      '.hub-root .hub-dash.hub-cols-inst .hub-spark-fill{flex:1;min-height:0}' +
      '.hub-root .hub-dash.hub-cols-inst .hub-spark-fill .vz-spark-ax{min-height:160px}' +
      '.hub-root .hub-dash.hub-cols-inst .hub-spark-fill .vz-spark,' +
      '.hub-root .hub-dash.hub-cols-inst .hub-spark-fill svg{min-height:120px}' +
      /* 法人頁：座標軸／峰谷刻度加大（大螢幕可讀） */
      '#view-institutional .vz-spark-ax .vz-yunit,#view-institutional .vz-spark-ax .vz-xunit,' +
      '#view-institutional .vz-spark-ax .vz-ylabs,#view-institutional .vz-spark-ax .vz-xlabs,' +
      '#view-institutional .vz-spark-ax .vz-plot .vz-pt{font-size:11px;line-height:1.25}' +
      '#view-institutional .vz-spark-ax .vz-ylabs{padding-right:6px;min-width:52px}' +
      '#view-institutional .vz-spark-ax .vz-plot .vz-pt{font-size:12px;font-weight:800}' +
      '#view-institutional .hub-title{font-size:20px;letter-spacing:.2px}' +
      '#view-institutional .hub-sub{font-size:12px;color:#94a3b8;line-height:1.35}' +
      '#view-institutional .hub-sep{font-size:12px}' +
      '#view-institutional .hub-btn{font-size:11px;padding:5px 10px}' +
      '#view-institutional .hub-sec{padding:8px 10px;border-radius:7px}' +
      '#view-institutional .hub-sec h4{font-size:13px;margin:0 0 6px;letter-spacing:.4px}' +
      '#view-institutional .hub-sec h4 .hub-h4-meta{font-size:11px!important;color:#94a3b8;font-weight:600}' +
      '#view-institutional .hub-inst-cmt{font-size:13px;line-height:1.55;padding:10px 12px;margin-top:8px}' +
      '#view-institutional .hub-note{font-size:11px;white-space:normal;line-height:1.4;color:#94a3b8}' +
      '#view-institutional .hub-seg button{font-size:12px;padding:5px 14px}' +
      '#view-institutional .hub-inst-rankhd .meta{font-size:11px;color:#94a3b8}' +
      '#view-institutional .hub-inst-rank table{font-size:12px}' +
      '#view-institutional .hub-inst-rank th,#view-institutional .hub-inst-rank td{padding:4px 5px}' +
      '#view-institutional .hub-inst-rank .lots .lots-num{font-size:13px}' +
      '#view-institutional .hub-inst-rank .lots .lots-bar{height:5px;margin-top:3px}' +
      '#view-institutional .hub-inst-rank .lots .vz-rowbar{height:5px}' +
      '#view-institutional .hub-empty{font-size:12px;padding:18px 10px}' +
      '#view-institutional .badge{font-size:10px;padding:1px 7px}' +
      '#view-institutional .hub-inst-hero .vz-chip{font-size:11px;padding:1px 8px;line-height:1.5}' +
      '.hub-root .hub-inst-rank{display:flex;flex-direction:column;min-width:0;min-height:0;height:100%;gap:4px}' +
      '.hub-root .hub-seg{display:flex;gap:0;flex:0 0 auto;border:1px solid var(--border);border-radius:5px;overflow:hidden;width:fit-content}' +
      '.hub-root .hub-seg button{padding:3px 10px;border:0;border-right:1px solid var(--border);background:var(--bg);' +
        'color:var(--tlo);font-family:inherit;font-size:10px;font-weight:600;cursor:pointer;line-height:1.3}' +
      '.hub-root .hub-seg button:last-child{border-right:0}' +
      '.hub-root .hub-seg button:hover{color:var(--thi);background:var(--bg3)}' +
      '.hub-root .hub-seg button.on{background:var(--gold);color:#060A12;font-weight:800}' +
      '.hub-root .hub-inst-rankhd{display:flex;align-items:center;justify-content:space-between;gap:8px;flex:0 0 auto}' +
      '.hub-root .hub-inst-rankhd .meta{font-size:8px;color:var(--tlo);white-space:nowrap}' +
      '.hub-root .hub-inst-rank .hub-zone{flex:1;min-height:0}' +
      '.hub-root .hub-inst-rank table{font-size:10px;table-layout:fixed;width:100%}' +
      '.hub-root .hub-inst-rank th:nth-child(1),.hub-root .hub-inst-rank td:nth-child(1){width:28px}' +
      '.hub-root .hub-inst-rank th:nth-child(2),.hub-root .hub-inst-rank td:nth-child(2){width:52px}' +
      '.hub-root .hub-inst-rank th:nth-child(3),.hub-root .hub-inst-rank td:nth-child(3){text-align:left;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-inst-rank th:nth-child(4),.hub-root .hub-inst-rank td:nth-child(4){width:88px}' +
      '.hub-root .hub-inst-rank th:nth-child(5),.hub-root .hub-inst-rank td:nth-child(5){width:72px;white-space:nowrap}' +
      '.hub-root .hub-inst-rank .lots{font-variant-numeric:tabular-nums;font-weight:700;' +
        'white-space:normal;vertical-align:middle;overflow:hidden}' +
      '.hub-root .hub-inst-rank .lots .lots-num{display:block;line-height:1.2}' +
      '.hub-root .hub-inst-rank .lots .lots-bar{display:block;margin-top:2px;height:4px;max-width:100%;overflow:hidden}' +
      '.hub-root .hub-inst-rank .lots .vz-rowbar{display:block;margin-left:0;max-width:100%;height:4px}' +
      '.hub-root .hub-inst-rank .streak{text-align:right;vertical-align:middle}' +
      '.hub-root .hub-inst-rank .streak .vz-chip{margin:0;max-width:100%;overflow:hidden;text-overflow:ellipsis}' +
      '.hub-root .badge{display:inline-block;padding:0 6px;border-radius:3px;font-size:8px;font-weight:700}' +
      '.hub-root .badge.ok{background:var(--gbg);color:var(--green);border:1px solid var(--gbdr)}' +
      '.hub-root .badge.warn{background:rgba(251,146,60,.12);color:var(--orange);border:1px solid rgba(251,146,60,.35)}' +
      '.hub-root .badge.err{background:rgba(248,113,113,.12);color:var(--red);border:1px solid rgba(248,113,113,.35)}' +
      '.hub-root .badge.mid{background:rgba(245,197,24,.12);color:var(--gold);border:1px solid var(--gold-m)}' +
      '.hub-root .hub-empty{font-size:10px;color:var(--tlo);padding:16px 8px;text-align:center}';
  }

  var instWho = 'foreign';

  function mount(route) {
    injectCSS();
    var panel = $('view-' + route);
    if (!panel) return null;
    var mid = 'mount-' + route;
    var el = $(mid);
    if (!el) {
      el = document.createElement('div');
      el.id = mid;
      el.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(el);
    }
    return el;
  }

  function head(title, sub, actionsHtml) {
    return '<div class="hub-root"><div class="hub-head"><div>' +
      '<span class="hub-title">' + title + '</span>' +
      (sub ? '<span class="hub-sep">·</span><span class="hub-sub">' + sub + '</span>' : '') +
      '</div><div class="hub-actions">' + (actionsHtml || '') + '</div></div>';
  }

  function spark(vals) {
    if (!vals || !vals.length) return '';
    var max = Math.max.apply(null, vals.map(Math.abs).concat([1]));
    var html = '<div class="hub-spark">';
    vals.forEach(function (v) {
      var h = Math.max(4, Math.round(Math.abs(v) / max * 48));
      var col = v >= 0 ? 'var(--red)' : 'var(--green)';
      html += '<i style="height:' + h + 'px;background:' + col + '"></i>';
    });
    return html + '</div>';
  }

  function yiNum(v) {
    if (v == null || !isFinite(v)) return null;
    return Math.abs(v) >= 1e6 ? v / 1e8 : v;
  }

  function fmtYiSigned(v) {
    var y = yiNum(v);
    if (y == null) return '—';
    return (y >= 0 ? '+' : '') + y.toFixed(1) + ' 億';
  }

  /** 法人資金變化評論（不重複頂列數字） */
  function buildInstComment(inst, histNewestFirst, totalYi) {
    var parts = [];
    var f = yiNum(inst.foreign), t = yiNum(inst.trust), d = yiNum(inst.dealer);
    var tot = totalYi != null && isFinite(totalYi) ? yiNum(totalYi) : (
      (f != null || t != null || d != null) ? ((f || 0) + (t || 0) + (d || 0)) : null
    );
    var rows = (histNewestFirst || []).filter(function (r) {
      return r && r.totalYi != null && isFinite(r.totalYi);
    });
    var chrono = rows.slice().reverse();
    var streak = 0;
    if (tot != null && tot !== 0 && chrono.length) {
      var sign = tot > 0 ? 1 : -1;
      for (var k = chrono.length - 1; k >= 0; k--) {
        var v = chrono[k].totalYi;
        if (v == null || v === 0 || (v > 0 ? 1 : -1) !== sign) break;
        streak += 1;
      }
    }
    if (streak >= 3) {
      parts.push(tot > 0
        ? '合計已連 <b class="up">' + streak + '</b> 日買超，資金偏進攻節奏。'
        : '合計已連 <b class="dn">' + streak + '</b> 日賣超，資金偏防衛／調節。');
    } else if (tot != null) {
      parts.push(tot > 20
        ? '當日合計明顯買超，短線籌碼偏多。'
        : tot < -20
          ? '當日合計明顯賣超，留意權值與指數壓力。'
          : '當日合計接近平衡，方向性訊號有限。');
    }
    if (chrono.length >= 2 && tot != null) {
      var prev = chrono[chrono.length - 2].totalYi;
      if (prev != null && isFinite(prev)) {
        var delta = tot - prev;
        if (Math.abs(delta) >= 50) {
          parts.push(delta > 0
            ? '較前日轉強約 <span class="up">' + fmtYiSigned(delta) + '</span>。'
            : '較前日轉弱約 <span class="dn">' + fmtYiSigned(delta) + '</span>。');
        } else if (prev > 0 && tot < 0) {
          parts.push('合計由買轉賣，資金氛圍轉向謹慎。');
        } else if (prev < 0 && tot > 0) {
          parts.push('合計由賣轉買，資金回補跡象。');
        }
      }
    }
    if (f != null && d != null) {
      if (f > 30 && d < -30) parts.push('外資偏買、自營偏賣 — 常見結構／避險分歧。');
      else if (f < -30 && d > 30) parts.push('外資偏賣、自營偏買 — 留意承接能否延續。');
    }
    if (t != null && Math.abs(t) >= 20) {
      parts.push(t > 0 ? '投信偏買，中長線資金仍有佈局。' : '投信偏賣，主動資金偏調節。');
    }
    if (!parts.length) parts.push('法人序列載入中或資料不足，暫無趨勢評論。');
    return parts.slice(0, 3).join(' ');
  }

  // ── Institutional ────────────────────────────────────────
  function whoLabel(w) {
    return w === 'trust' ? '投信' : w === 'dealer' ? '自營' : '外資';
  }
  function fmtLots(lots) {
    if (lots == null || !isFinite(lots)) return '—';
    return (lots >= 0 ? '+' : '') + Math.round(lots).toLocaleString('en-US');
  }
  function toneChip(totalYuan, V) {
    if (totalYuan == null || !isFinite(totalYuan)) return '';
    var yiVal = Math.abs(totalYuan) > 1e5 ? totalYuan / 1e8 : totalYuan;
    var kind = yiVal > 20 ? 'buy' : yiVal < -20 ? 'sell' : 'mid';
    var txt = yiVal > 20 ? '合計偏多' : yiVal < -20 ? '合計偏空' : '合計中性';
    return V ? V.chip(txt, kind) : ('<span class="badge mid">' + txt + '</span>');
  }
  function turnoverTone(latestYi) {
    if (latestYi == null || !isFinite(latestYi)) return '量能資料不足';
    if (latestYi >= 12000) return '爆量（≥1.2 兆）';
    if (latestYi >= 10000) return '明顯放量（兆級）';
    if (latestYi >= 8000) return '量能健康（≥8000 億）';
    return '量縮（低於 8000 億）';
  }

  function renderInstitutional(el, opts) {
    opts = opts || {};
    var soft = !!el.querySelector('#hub-inst-body .hub-inst-hero, #hub-inst-body .hub-strip');
    if (!soft) {
      el.innerHTML = head('法人動向', 'BFI82U 合計結構 · T86 買賣超排行 · 近月資金趨勢',
        '<button class="hub-btn" data-sync>同步資料</button>' +
        '<button class="hub-btn" data-go="afterhours">盤後</button>' +
        '<button class="hub-btn primary" data-shell-back>← 儀表板</button>') +
        '<div id="hub-inst-body" class="hub-body"><div class="hub-loading">載入法人資料…</div></div></div>';
      bindCommon(el);
    } else if (window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-institutional', true, '更新中…');
    }
    if (opts.who) instWho = opts.who;
    var who = instWho || 'foreign';
    Promise.all([
      jget('/marketflow'),
      jget('/inst-rank?who=' + encodeURIComponent(who) + '&side=buy&n=40'),
      jget('/inst-rank?who=' + encodeURIComponent(who) + '&side=sell&n=40'),
      jget('/pulse/history?kind=institutional&n=40')
    ]).then(function (arr) {
      var V = window.Viz;
      var mf = arr[0] || {};
      var inst = mf.inst || {};
      var buy = (arr[1] && arr[1].list) || [];
      var sell = (arr[2] && arr[2].list) || [];
      var buyDate = (arr[1] && arr[1].date) || '';
      var sellDate = (arr[2] && arr[2].date) || '';
      var hist = (arr[3] && arr[3].rows) || [];
      var total = null;
      if (inst.foreign != null || inst.trust != null || inst.dealer != null) {
        total = (inst.foreign || 0) + (inst.trust || 0) + (inst.dealer || 0);
      }
      var to = (mf.turnover || []).filter(function (x) { return x && x.amount != null; });
      var latestAmt = to.length ? to[to.length - 1].amount : null;
      var latestYi = latestAmt != null ? latestAmt / 1e8 : null;
      var wLab = whoLabel(who);

      function rankTbl(list, title, side) {
        var maxAbs = 0;
        list.forEach(function (r) {
          if (r.lots != null && isFinite(r.lots)) maxAbs = Math.max(maxAbs, Math.abs(r.lots));
        });
        var h = '<div class="hub-sec"><h4>' + title +
          '<span class="hub-h4-meta" style="color:var(--tlo);font-weight:600">單位：張</span></h4>' +
          '<div class="hub-fill"><table><tr><th>#</th><th>代號</th><th>名稱</th><th>張數</th><th>連續</th></tr>';
        if (!list.length) {
          h += '</table><div class="hub-empty">尚無排行（T86 多為盤後更新）</div>';
        } else {
          list.forEach(function (r, i) {
            var lots = r.lots;
            var bar = (V && lots != null && maxAbs) ? V.rowBar(lots, maxAbs) : '';
            var streak = (V && r.streak) ? V.streakChip(r.streak, '') : '';
            h += '<tr data-code="' + (r.code || '') + '">' +
              '<td>' + (i + 1) + '</td>' +
              '<td style="color:var(--gold);font-weight:700">' + (r.code || '') + '</td>' +
              '<td title="' + (r.name || '') + '">' + (r.name || '') + '</td>' +
              '<td class="lots ' + tw(side === 'buy' ? 1 : -1) + '">' +
                '<span class="lots-num">' + fmtLots(lots) + '</span>' +
                (bar ? '<span class="lots-bar">' + bar + '</span>' : '') +
              '</td>' +
              '<td class="streak">' + streak + '</td></tr>';
          });
          h += '</table>';
        }
        return h + '</div></div>';
      }

      var sparkVals = hist.slice().reverse().map(function (r) { return r.totalYi; })
        .filter(function (v) { return v != null && isFinite(v); });
      var lastSpark = sparkVals.length ? sparkVals[sparkVals.length - 1] : null;
      var sparkCol = lastSpark != null && lastSpark >= 0 ? 'var(--red)' : 'var(--green)';
      var cmtHtml = buildInstComment(inst, hist, total);
      var yiFmt = function (v) {
        if (v == null || !isFinite(v)) return '—';
        return (v >= 0 ? '+' : '') + v.toFixed(1) + ' 億';
      };
      var fYi = function (yuan) {
        if (yuan == null || !isFinite(yuan)) return null;
        return Math.abs(yuan) > 1e5 ? yuan / 1e8 : yuan;
      };
      var bars = (V && (inst.foreign != null || inst.trust != null || inst.dealer != null))
        ? V.magBars([
            { label: '外資', v: fYi(inst.foreign), fmt: yiFmt },
            { label: '投信', v: fYi(inst.trust), fmt: yiFmt },
            { label: '自營', v: fYi(inst.dealer), fmt: yiFmt }
          ])
        : '';
      /* Viz 缺席時仍顯示三大結構數字，避免結構卡空白 */
      if (!bars && (inst.foreign != null || inst.trust != null || inst.dealer != null)) {
        bars = '<div class="hub-mag3" style="grid-template-rows:repeat(3,auto);gap:8px;padding:4px 0">' +
          [['外資', inst.foreign], ['投信', inst.trust], ['自營', inst.dealer]].map(function (pair) {
            var y = fYi(pair[1]);
            return '<div class="row"><span class="lbl">' + pair[0] + '</span>' +
              '<span class="val ' + tw(y) + '">' + yiFmt(y) + '</span></div>';
          }).join('') + '</div>';
      }
      var flowMeter = (V && latestYi != null) ? V.refMeter(latestYi, [8000, 12000]) : '';
      var totalTone = toneChip(total, V);

      var hero =
        '<div class="hub-inst-hero">' +
          '<div class="hub-inst-total">' +
            '<div class="k">三大法人合計 · 買賣超</div>' +
            '<div class="big ' + tw(total) + '">' + yi(total) + '</div>' +
            '<div class="sub">' + totalTone +
              '<span>法人日 ' + ((inst && inst.date) || mf.date || '—') + '</span></div>' +
          '</div>' +
          '<div class="hub-inst-comp">' +
            '<div class="k">結構拆解（外資／投信／自營）</div>' +
            (bars || '<div class="hub-empty" style="padding:8px 0">法人金額尚未更新</div>') +
          '</div>' +
          '<div class="hub-inst-flow">' +
            '<div class="k">大盤成交金額</div>' +
            '<div class="v">' + (latestYi != null ? latestYi.toFixed(0) + ' 億' : '—') + '</div>' +
            '<div class="s">' + turnoverTone(latestYi) + '</div>' +
            flowMeter +
          '</div>' +
        '</div>';

      var trendPanel = '<div class="hub-sec"><h4>合計買賣超趨勢' +
        '<span class="hub-h4-meta">X：日 · Y：億</span></h4>' +
        '<div class="hub-spark-fill">' +
        (V && sparkVals.length >= 2
          ? V.sparkLine(sparkVals, {
              color: sparkCol, h: 220, w: 420,
              xUnit: '日', yUnit: '億', yDigits: 1, axes: true
            })
          : (sparkVals.length ? spark(sparkVals) : '<div class="hub-empty">尚無本機法人歷史 — 按「同步資料」預抓</div>')) +
        '</div>' +
        '<div class="hub-inst-cmt">' + cmtHtml + '</div>' +
        '<div class="hub-note">刻度：Y 高／中／低（億）· X 日序 · 零軸虛線 · BFI82U</div></div>';

      var seg =
        '<div class="hub-seg" id="hub-inst-who">' +
          '<button type="button" data-who="foreign"' + (who === 'foreign' ? ' class="on"' : '') + '>外資</button>' +
          '<button type="button" data-who="trust"' + (who === 'trust' ? ' class="on"' : '') + '>投信</button>' +
          '<button type="button" data-who="dealer"' + (who === 'dealer' ? ' class="on"' : '') + '>自營</button>' +
        '</div>';
      var rankDate = buyDate || sellDate || '';
      var rankPanel =
        '<div class="hub-inst-rank">' +
          '<div class="hub-inst-rankhd">' + seg +
            '<span class="meta">T86 · ' + wLab + ' · ' + (rankDate || '—') + ' · 點列載入線型</span>' +
          '</div>' +
          '<div class="hub-zone">' +
            rankTbl(buy, wLab + '買超', 'buy') +
            rankTbl(sell, wLab + '賣超', 'sell') +
          '</div>' +
        '</div>';

      var body = $('hub-inst-body');
      if (!body) return;
      body.innerHTML = hero +
        '<div class="hub-dash hub-cols-inst">' + trendPanel + rankPanel + '</div>';
      bindCommon(el);
      var whoBar = $('hub-inst-who');
      if (whoBar) {
        whoBar.querySelectorAll('button[data-who]').forEach(function (b) {
          b.onclick = function () {
            var next = b.getAttribute('data-who');
            if (!next || next === instWho) return;
            instWho = next;
            renderInstitutional(el, { who: next });
          };
        });
      }
    }).finally(function () {
      if (window.ShellV5 && window.ShellV5.softBadge) {
        window.ShellV5.softBadge('mount-institutional', false);
      }
    });
  }

  // ── International ────────────────────────────────────────
  function renderInternational(el) {
    el.innerHTML = head('國際市場', '美股指數／美元／黃金（避險）／銅（景氣循環）＋總經（Yahoo／BLS／種子備援）',
      '<button class="hub-btn" id="hub-eco-refresh">更新指標</button>' +
      '<button class="hub-btn" data-sync>同步資料</button>' +
      '<button class="hub-btn primary" data-shell-back>← 儀表板</button>') +
      '<div id="hub-intl-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    var ecoBtn = $('hub-eco-refresh');
    if (ecoBtn) ecoBtn.onclick = function () { loadInternational(el, true); };
    loadInternational(el, false);
  }

  function loadInternational(el, forceEco) {
    var body = $('hub-intl-body');
    var soft = !!(body && body.querySelector('.hub-dash, .hub-strip, .cell'));
    if (body && !soft) body.innerHTML = '<div class="hub-loading">載入國際／總經…</div>';
    if (soft && window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-international', true, '更新中…');
    }
    var ecoUrl = '/macro/economy?years=5' + (forceEco ? '&refresh=1' : '');
    Promise.all([
      jget('/pulse?refresh=0'),
      jget(ecoUrl),
      jget('/sync/status')
    ]).then(function (arr) {
      var pulse = arr[0] || {};
      var ecoPack = arr[1] || {};
      var st = arr[2] || {};
      var global = pulse.global || [];
      if (pulse.us10y && pulse.us10y.value != null) {
        global = global.concat([{
          name: '美10年債', price: pulse.us10y.value, changePct: null, unit: '%'
        }]);
      }
      var ecoItems = ecoPack.items || [];
      var V = window.Viz;
      var maxChg = 0;
      global.forEach(function (g) {
        if (g.changePct != null && isFinite(g.changePct)) maxChg = Math.max(maxChg, Math.abs(g.changePct));
      });
      if (maxChg < 0.01) maxChg = 1;
      /* 頂列 KPI：掃描／總經就緒／同步狀態（不重複下方報價卡） */
      var ecoOkPre = (ecoPack.counts && ecoPack.counts.ok) || ecoItems.filter(function (x) { return x.ok; }).length;
      var ecoTotalPre = (ecoPack.counts && ecoPack.counts.total) || ecoItems.length;
      var upN = 0, dnN = 0;
      global.forEach(function (g) {
        if (g.changePct > 0) upN++;
        else if (g.changePct < 0) dnN++;
      });
      var strip =
        '<div class="cell"><div class="k">全球報價</div><div class="v">' + global.length + '</div>' +
          '<div class="s"><span class="up">' + upN + '</span> / <span class="dn">' + dnN + '</span></div></div>' +
        '<div class="cell"><div class="k">總經指標</div><div class="v">' + ecoOkPre + '/' + ecoTotalPre + '</div>' +
          '<div class="s">' + (ecoPack.updatedAt ? String(ecoPack.updatedAt).replace('T', ' ').slice(0, 16) : '按更新指標') + '</div></div>' +
        '<div class="cell"><div class="k">同步系列</div><div class="v">' + ((st.datasets || []).length) + '</div>' +
          '<div class="s">資料來源狀態</div></div>' +
        '<div class="cell"><div class="k">美10Y</div><div class="v">' +
          (pulse.us10y && pulse.us10y.value != null ? fmt(pulse.us10y.value, 2) + '%' : '—') +
          '</div><div class="s">殖利率</div></div>';
      var cards = global.map(function (g) {
        var bar = (V && g.changePct != null) ? '<div class="bar">' + V.rowBar(g.changePct, maxChg) + '</div>' : '';
        var sym = g.symbol || g.sym || '';
        var mkt = /TWD|TWSE|台|\.TW/i.test(String(g.name || '')) ? 'TW' : 'US';
        var click = sym
          ? ' data-code="' + sym.replace(/"/g, '') + '" data-mkt="' + mkt + '" style="cursor:pointer"'
          : '';
        var dig = g.unit === '%' ? 2
          : (sym === 'HG=F' || sym === 'TWD=X' || sym === '^VIX') ? 2
          : (g.price > 1000 ? 0 : 2);
        var role = g.role
          ? '<div class="s" style="color:var(--cyan);font-weight:600;margin-top:2px">' + g.role + '</div>'
          : '';
        return '<div class="hub-card"' + click + '><div class="k">' + (g.name || g.symbol) + '</div><div class="v">' +
          fmt(g.price, dig) + (g.unit === '%' ? '%' : '') +
          '</div><div class="chg ' + tw(g.changePct) + '">' +
          (g.changePct != null ? pct(g.changePct) : '—') + '</div>' + role + bar + '</div>';
      }).join('');
      function ecoVal(it) {
        if (!it || it.value == null || !isFinite(it.value)) return '—';
        var u = it.unit || '';
        var d = (u === '%' || u === '') ? 2 : (Math.abs(it.value) >= 1000 ? 0 : 2);
        return fmt(it.value, d) + (u === '%' ? '%' : (u === 'USD' ? '' : (u ? ' ' + u : '')));
      }
      function ecoChg(it) {
        if (it == null || it.change == null || !isFinite(it.change)) return '—';
        var u = it.unit || '';
        var sign = it.change > 0 ? '+' : '';
        if (u === '%') return '<span class="' + tw(it.change) + '">' + sign + Number(it.change).toFixed(2) + '</span>';
        return '<span class="' + tw(it.change) + '">' + sign + Number(it.change).toFixed(2) + '</span>';
      }
      var ecoHtml = ecoItems.map(function (it) {
        var src = it.source ? String(it.source).replace(/^seed:/, '種子 ') : '—';
        return '<tr><td>' + (it.label || it.key) + '</td><td class="' +
          (it.ok ? '' : 'flat') + '">' + ecoVal(it) + '</td><td>' + ecoChg(it) +
          '</td><td>' + (it.date || '—') + '</td><td style="color:var(--tlo);font-size:9px">' + src + '</td></tr>';
      }).join('');
      var ecoOk = (ecoPack.counts && ecoPack.counts.ok) || ecoItems.filter(function (x) { return x.ok; }).length;
      var ecoTotal = (ecoPack.counts && ecoPack.counts.total) || ecoItems.length;
      var ds = (st.datasets || []).map(function (d) {
        var cls = d.status === '同步完成' ? 'ok' : (d.status === '同步失敗' ? 'err' : 'warn');
        return '<tr><td>' + d.dataset + '</td><td>' + (d.dataDate || '—') + '</td><td><span class="badge ' + cls + '">' +
          (d.status || '—') + '</span></td><td>' + (d.rows != null ? d.rows : '—') + '</td></tr>';
      }).join('');
      var body = $('hub-intl-body');
      if (!body) return;
      body.innerHTML =
        '<div class="hub-strip">' + strip + '</div>' +
        '<div class="hub-dash hub-cols-3">' +
          '<div class="hub-sec"><h4>全球報價 · ' + global.length +
            '<span style="color:var(--tlo);font-weight:600;font-size:8px">點卡開圖表</span></h4>' +
            '<div class="hub-fill hub-zone z-fill" style="display:grid">' +
            (cards || '<div class="hub-empty">國際報價載入中／來源暫不可用</div>') +
          '</div></div>' +
          '<div class="hub-sec"><h4>經濟指標 · ' + ecoOk + '/' + ecoTotal +
            '</h4><div class="hub-fill"><table><tr><th>項目</th><th>數值</th><th>變化</th><th>日期</th><th>來源</th></tr>' +
            (ecoHtml || '<tr><td colspan="5">總經尚未就緒 — 按「更新指標」</td></tr>') +
            '</table></div>' +
            '<div class="hub-note">' + (ecoPack.hint || 'FRED 不通時改 Yahoo／BLS／種子') +
            (ecoPack.updatedAt ? ' · ' + String(ecoPack.updatedAt).replace('T', ' ') : '') + '</div></div>' +
          '<div class="hub-sec"><h4>資料來源狀態</h4><div class="hub-fill"><table><tr><th>系列</th><th>資料日</th><th>狀態</th><th>列數</th></tr>' +
            (ds || '<tr><td colspan="4">尚無同步紀錄 — 按同步資料</td></tr>') +
            '</table></div></div>' +
        '</div>';
      bindCommon(el);
      body.querySelectorAll('.hub-card[data-code]').forEach(function (card) {
        card.onclick = function () {
          openChart(card.getAttribute('data-code'), card.getAttribute('data-mkt') || 'US');
        };
      });
      var ecoBtn = $('hub-eco-refresh');
      if (ecoBtn) ecoBtn.onclick = function () { loadInternational(el, true); };
    }).finally(function () {
      if (window.ShellV5 && window.ShellV5.softBadge) {
        window.ShellV5.softBadge('mount-international', false);
      }
    });
  }

  // ── Signals ──────────────────────────────────────────────
  function renderSignals(el) {
    el.innerHTML = head('策略訊號', '可解釋監控訊號（焦點掃描／選股結果）',
      '<button class="hub-btn" data-go="scan">選股</button>' +
      '<button class="hub-btn primary" id="hub-run-focus">執行焦點掃描</button>' +
      '<button class="hub-btn" data-shell-back>← 儀表板</button>') +
      '<div id="hub-sig-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    var run = $('hub-run-focus');
    if (run) run.onclick = function () { loadFocus(el, true); };
    loadFocus(el, false);
  }
  function loadFocus(el, force) {
    var body = $('hub-sig-body');
    var soft = !!(body && body.querySelector('.hub-strip, .hub-dash'));
    if (body && !soft) body.innerHTML = '<div class="hub-loading">掃描中…</div>';
    if (soft && window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-signals', true, '掃描中…');
    }
    jget('/focus' + (force ? '?refresh=1' : '')).then(function (d) {
      var body = $('hub-sig-body');
      if (!body) return;
      d = d || {};
      /* 契約：buy / short（與 heat_v5、ai_v5 一致）；相容舊別名 */
      var bulls = (d.buy || d.long || d.bull || d.longs || []).slice();
      var bears = (d.short || d.bear || d.shorts || []).slice();
      if (!bulls.length && !bears.length && Array.isArray(d.list)) {
        d.list.forEach(function (r) {
          var side = String(r.side || r.dir || r.bias || '');
          if (/空|short|bear|sell/i.test(side) || (r.score != null && r.score < 0)) bears.push(r);
          else bulls.push(r);
        });
      }
      var scanned = d.scanned != null ? d.scanned : (bulls.length + bears.length);
      if (!bulls.length && !bears.length) {
        body.innerHTML =
          '<div class="hub-strip">' +
            '<div class="cell"><div class="k">掃描檔數</div><div class="v">' + scanned + '</div></div>' +
            '<div class="cell"><div class="k">做多</div><div class="v up">0</div></div>' +
            '<div class="cell"><div class="k">做空</div><div class="v dn">0</div></div>' +
            '<div class="cell"><div class="k">狀態</div><div class="v">無訊號</div><div class="s">按掃描或選股</div></div>' +
          '</div>' +
          '<div class="hub-dash hub-dash-1">' +
            '<div class="hub-sec"><h4>策略訊號清單</h4>' +
            '<div class="hub-empty">目前沒有焦點訊號 — 按「執行焦點掃描」或前往選股</div></div></div>';
        bindCommon(el);
        return;
      }
      var V = window.Viz;
      function rowHtml(r, sideKind) {
        var code = r.code || r.sym || r.ticker || '';
        var name = r.name || '';
        var score = r.score != null ? r.score : (r.confidence != null ? r.confidence : null);
        var desc = '';
        if (Array.isArray(r.signals) && r.signals.length) desc = r.signals.slice(0, 3).join(' · ');
        else desc = r.reason || r.description || r.why || r.signal || '';
        var sideCell = sideKind === 'bear'
          ? (V ? V.chip('做空', 'sell') : '做空')
          : (V ? V.chip('做多', 'buy') : '做多');
        var scoreCell = '—';
        if (score != null && isFinite(score)) {
          var meterScore = Math.abs(score) <= 1 ? score * 100 : Math.max(0, Math.min(100, Math.abs(score)));
          scoreCell = (score >= 0 ? '+' : '') + Number(score).toFixed(1);
          if (V) scoreCell += V.scoreMeter(meterScore);
        }
        return '<tr data-code="' + code + '"><td style="color:var(--gold);font-weight:700">' + code +
          '</td><td>' + name + '</td><td>' + sideCell + '</td><td>' + scoreCell +
          '</td><td style="text-align:left;color:var(--tlo)">' + desc + '</td></tr>';
      }
      var bullRows = bulls.slice(0, 40).map(function (r) { return rowHtml(r, 'bull'); }).join('') ||
        '<tr><td colspan="5">目前無做多訊號</td></tr>';
      var bearRows = bears.slice(0, 40).map(function (r) { return rowHtml(r, 'bear'); }).join('') ||
        '<tr><td colspan="5">目前無做空訊號</td></tr>';
      body.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">掃描檔數</div><div class="v">' + scanned + '</div><div class="s">焦點掃描</div></div>' +
          '<div class="cell"><div class="k">做多</div><div class="v up">' + bulls.length + '</div></div>' +
          '<div class="cell"><div class="k">做空</div><div class="v dn">' + bears.length + '</div></div>' +
          '<div class="cell"><div class="k">合計</div><div class="v">' + (bulls.length + bears.length) +
            '</div><div class="s">點列開圖表</div></div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-2">' +
          '<div class="hub-sec"><h4>做多焦點 · ' + bulls.length + '</h4><div class="hub-fill"><table>' +
            '<tr><th>代號</th><th>名稱</th><th>方向</th><th>分數</th><th>訊號</th></tr>' +
            bullRows + '</table></div></div>' +
          '<div class="hub-sec"><h4>做空焦點 · ' + bears.length + '</h4><div class="hub-fill"><table>' +
            '<tr><th>代號</th><th>名稱</th><th>方向</th><th>分數</th><th>訊號</th></tr>' +
            bearRows + '</table></div></div>' +
        '</div>';
      bindCommon(el);
    }).finally(function () {
      if (window.ShellV5 && window.ShellV5.softBadge) {
        window.ShellV5.softBadge('mount-signals', false);
      }
    });
  }

  // ── Watchlist ────────────────────────────────────────────
  function readWl() {
    try {
      if (typeof S !== 'undefined' && Array.isArray(S.wl) && S.wl.length) return S.wl.slice();
    } catch (e) {}
    var keys = ['st_wl', 'wl_v2', 'watchlist'];
    for (var i = 0; i < keys.length; i++) {
      try {
        var a = JSON.parse(localStorage.getItem(keys[i]) || '[]');
        if (Array.isArray(a) && a.length) return a;
      } catch (e) {}
    }
    return [];
  }
  function renderWatchlist(el) {
    el.innerHTML = head('自選股中心', '本機瀏覽器自選＋即時報價',
      '<button class="hub-btn" data-go="chart">圖表管理</button>' +
      '<button class="hub-btn primary" id="hub-wl-refresh">重新整理</button>' +
      '<button class="hub-btn" data-shell-back>← 儀表板</button>') +
      '<div id="hub-wl-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    var btn = $('hub-wl-refresh');
    if (btn) btn.onclick = function () { fillWl(el); };
    fillWl(el);
  }
  function fillWl(el) {
    var wl = readWl();
    var body = $('hub-wl-body');
    if (!body) return;
    if (!wl.length) {
      body.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">自選總數</div><div class="v">0</div></div>' +
          '<div class="cell"><div class="k">台股</div><div class="v">0</div></div>' +
          '<div class="cell"><div class="k">美股</div><div class="v">0</div></div>' +
          '<div class="cell"><div class="k">下一步</div><div class="v" style="font-size:11px">加入自選</div></div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-2">' +
          '<div class="hub-sec"><h4>尚未加入自選</h4>' +
            '<div class="hub-empty">於圖表按 ＋ 加入，或從選股／熱力點進個股後加入</div>' +
            '<div class="hub-note"><button class="hub-btn" data-go="scan">選股</button> ' +
            '<button class="hub-btn" data-go="heat">熱力</button> ' +
            '<button class="hub-btn primary" data-go="chart">圖表</button></div></div>' +
          '<div class="hub-sec"><h4>用法</h4><div class="hub-fill" style="padding:8px;font-size:10px;color:var(--tlo);line-height:1.55">' +
            '自選存於本機瀏覽器。<br>台股走 /twquote-batch，美股走 /quote-batch。<br>點列即可載入線型。</div></div>' +
        '</div>';
      bindCommon(el);
      return;
    }
    var twc = wl.filter(function (w) { return (w.m || 'TW') === 'TW'; }).map(function (w) { return w.t; });
    var usc = wl.filter(function (w) { return w.m === 'US'; }).map(function (w) { return w.t; });
    Promise.all([
      twc.length ? jget('/twquote-batch?codes=' + encodeURIComponent(twc.join(','))) : Promise.resolve({}),
      usc.length ? jget('/quote-batch?syms=' + encodeURIComponent(usc.join(','))) : Promise.resolve({})
    ]).then(function (arr) {
      var q = Object.assign({}, arr[0] || {}, arr[1] || {});
      var V = window.Viz;
      var maxChg = 0;
      var upN = 0, dnN = 0;
      wl.forEach(function (w) {
        var qq = q[w.t] || q[w.t + '.TW'] || q[w.t + '.TWO'] || {};
        var ch = qq.changePct != null ? qq.changePct : w.chg;
        if (ch != null && isFinite(ch)) {
          maxChg = Math.max(maxChg, Math.abs(ch));
          if (ch > 0) upN++; else if (ch < 0) dnN++;
        }
      });
      if (maxChg < 0.01) maxChg = 1;
      function volOf(qq) {
        var v = qq.volume != null ? qq.volume : (qq.vol != null ? qq.vol : qq.regularMarketVolume);
        if (v == null || !isFinite(v)) return '—';
        if (v >= 1e8) return (v / 1e8).toFixed(1) + ' 億股';
        if (v >= 1e4) return (v / 1e4).toFixed(0) + ' 萬';
        return Math.round(v).toLocaleString('en-US');
      }
      function rowOf(w) {
        var qq = q[w.t] || q[w.t + '.TW'] || q[w.t + '.TWO'] || {};
        var ch = qq.changePct != null ? qq.changePct : w.chg;
        var bar = V ? V.rowBar(ch, maxChg) : '';
        var name = w.name || qq.name || qq.shortName || '';
        return '<tr data-code="' + w.t + '" data-mkt="' + (w.m || 'TW') + '"><td style="color:var(--gold);font-weight:700">' +
          w.t + '</td><td>' + name + '</td><td>' +
          fmt(qq.price != null ? qq.price : w.price) + '</td><td class="' + tw(ch) + '">' +
          pct(ch) + bar + '</td><td style="color:var(--tlo)">' + volOf(qq) + '</td></tr>';
      }
      var twRows = wl.filter(function (w) { return (w.m || 'TW') === 'TW'; }).map(rowOf).join('') ||
        '<tr><td colspan="5">尚無台股自選</td></tr>';
      var usRows = wl.filter(function (w) { return w.m === 'US'; }).map(rowOf).join('') ||
        '<tr><td colspan="5">尚無美股自選</td></tr>';
      var b = $('hub-wl-body');
      if (!b) return;
      b.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">自選總數</div><div class="v">' + wl.length + '</div></div>' +
          '<div class="cell"><div class="k">台股</div><div class="v">' + twc.length + '</div></div>' +
          '<div class="cell"><div class="k">美股</div><div class="v">' + usc.length + '</div></div>' +
          '<div class="cell"><div class="k">漲／跌</div><div class="v"><span class="up">' + upN +
            '</span> / <span class="dn">' + dnN + '</span></div></div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-2">' +
          '<div class="hub-sec"><h4>台股自選 · ' + twc.length + '</h4><div class="hub-fill"><table>' +
            '<tr><th>代號</th><th>名稱</th><th>最新價</th><th>漲跌</th><th>量</th></tr>' +
            twRows + '</table></div></div>' +
          '<div class="hub-sec"><h4>美股自選 · ' + usc.length + '</h4><div class="hub-fill"><table>' +
            '<tr><th>代號</th><th>名稱</th><th>最新價</th><th>漲跌</th><th>量</th></tr>' +
            usRows + '</table></div></div>' +
        '</div>';
      bindCommon(el);
    });
  }

  // ── Risk ─────────────────────────────────────────────────
  function renderRisk(el) {
    el.innerHTML = head('風險監控', '由脈動因子與廣度／法人規則產生的風險事件',
      '<button class="hub-btn" data-sync>同步資料</button>' +
      '<button class="hub-btn" data-go="book">投組風險</button>' +
      '<button class="hub-btn primary" data-shell-back>← 儀表板</button>') +
      '<div id="hub-risk-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    Promise.all([jget('/pulse'), jget('/pulse/history?kind=pulse&n=15')]).then(function (arr) {
      var p = arr[0] || {};
      var events = [];
      (p.riskFactors || []).forEach(function (f) {
        var sev = Math.abs(f.score) >= 10 ? '高' : '中';
        events.push({
          time: p.updatedAt || p.date || '',
          event: f.name,
          description: f.description,
          scope: '台股',
          severity: sev
        });
      });
      if ((p.snapshot && p.snapshot.inst && p.snapshot.inst.totalYi) < 0) {
        events.push({
          time: p.date || '', event: '三大法人合計偏賣',
          description: '上市櫃三大法人當日合計為賣超，權值與籌碼面可能承壓。',
          scope: '台股', severity: '中'
        });
      }
      var ar = p.snapshot && p.snapshot.stocks && p.snapshot.stocks.advRatio;
      if (ar != null && ar <= 0.35) {
        events.push({
          time: p.date || '', event: '市場廣度偏空',
          description: '上漲比偏低，短線氣氛偏防衛。',
          scope: '台股', severity: '高'
        });
      }
      var V = window.Viz;
      var riskMeter = V ? V.scoreMeter(p.riskScore, { color: 'var(--cyan)' }) : '';
      var healthMeter = V ? V.scoreMeter(p.healthScore) : '';
      var compMeter = V ? V.scoreMeter(p.dataCompleteness) : '';
      var eventsRows = '';
      if (!events.length) {
        eventsRows = '<tr><td colspan="5">目前無觸發中的風險事件</td></tr>';
      } else {
        events.forEach(function (e) {
          var cls = e.severity === '高' ? 'err' : 'mid';
          eventsRows += '<tr><td>' + (e.time || '') + '</td><td>' + e.event + '</td><td style="text-align:left">' +
            e.description + '</td><td>' + e.scope + '</td><td><span class="badge ' + cls + '">' + e.severity + '</span></td></tr>';
        });
      }
      var hist = (arr[1] && arr[1].rows) || [];
      var histPanel = '<div class="hub-sec"><h4>脈動分數歷史</h4>';
      if (hist.length) {
        var chrono = hist.slice().reverse();
        if (V) {
          var hs = chrono.map(function (r) { return r.health; });
          var rs = chrono.map(function (r) { return r.risk; });
          var hSp = hs.filter(function (v) { return v != null && isFinite(v); }).length >= 2
            ? V.sparkLine(hs, { color: 'var(--gold)', xUnit: '日', yUnit: '分', yDigits: 0 }) : '';
          var rSp = rs.filter(function (v) { return v != null && isFinite(v); }).length >= 2
            ? V.sparkLine(rs, { color: 'var(--cyan)', xUnit: '日', yUnit: '分', yDigits: 0 }) : '';
          if (hSp || rSp) {
            histPanel += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:4px;flex:0 0 auto">' +
              (hSp ? '<div><div class="hub-note">健康（X：日 · Y：分）</div>' + hSp + '</div>' : '') +
              (rSp ? '<div><div class="hub-note">風險（X：日 · Y：分）</div>' + rSp + '</div>' : '') + '</div>';
          }
        }
        histPanel += '<div class="hub-fill"><table><tr><th>日期</th><th>健康</th><th>風險</th><th>總分</th><th>狀態</th></tr>';
        hist.forEach(function (r) {
          histPanel += '<tr><td>' + r.date + '</td><td>' + fmt(r.health, 1) + '</td><td>' + fmt(r.risk, 1) +
            '</td><td>' + fmt(r.total, 1) + '</td><td>' + (r.statusText || '') + '</td></tr>';
        });
        histPanel += '</table></div>';
      } else {
        histPanel += '<div class="hub-empty">尚無歷史紀錄</div>';
      }
      histPanel += '</div>';
      var body = $('hub-risk-body');
      if (!body) return;
      body.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">市場風險度</div><div class="v">' +
            (p.riskScore != null ? Number(p.riskScore).toFixed(1) : '—') + '</div>' +
            '<div class="s">' + (p.riskLabel || '') + riskMeter + '</div></div>' +
          '<div class="cell"><div class="k">健康度</div><div class="v">' +
            (p.healthScore != null ? Number(p.healthScore).toFixed(1) : '—') + '</div>' +
            '<div class="s">' + healthMeter + '</div></div>' +
          '<div class="cell"><div class="k">風險因子數</div><div class="v">' +
            ((p.riskFactors || []).length) + '</div></div>' +
          '<div class="cell"><div class="k">完整度</div><div class="v">' +
            (p.dataCompleteness != null ? Number(p.dataCompleteness).toFixed(0) + '%' : '—') + '</div>' +
            '<div class="s">' + compMeter + '</div></div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-2">' +
          '<div class="hub-sec"><h4>風險事件清單</h4><div class="hub-fill"><table>' +
            '<tr><th>時間</th><th>事件</th><th>說明</th><th>範圍</th><th>重要</th></tr>' +
            eventsRows + '</table></div></div>' +
          histPanel +
        '</div>';
      bindCommon(el);
    });
  }

  // ── Settings ─────────────────────────────────────────────
  function renderSettings(el) {
    el.innerHTML = head('設定', '同步狀態 · 資料來源 · 本機歷史庫',
      '<button class="hub-btn" data-sync>同步資料</button>' +
      '<button class="hub-btn primary" data-shell-back>← 儀表板</button>') +
      '<div id="hub-set-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    Promise.all([jget('/sync/status'), jget('/datasources'), jget('/health')]).then(function (arr) {
      var st = arr[0] || {};
      var ds = arr[1];
      var health = arr[2] || {};
      var V = window.Viz;
      var counts = st.counts || {};
      var countChips = V
        ? (V.badge('廣度 ' + (counts.breadth || 0), 'mid') + ' ' +
           V.badge('法人 ' + (counts.institutional || 0), 'mid') + ' ' +
           V.badge('指數 ' + (counts.index || 0), 'mid') + ' ' +
           V.badge('脈動 ' + (counts.pulseScore || 0), 'mid'))
        : ('廣度 ' + (counts.breadth || 0) + ' · 法人 ' + (counts.institutional || 0) +
          ' · 指數 ' + (counts.index || 0) + ' · 脈動 ' + (counts.pulseScore || 0));
      var dsRows = '';
      (st.datasets || []).forEach(function (d) {
        var cls = d.status === '同步完成' ? 'ok' : (d.status === '同步失敗' ? 'err' : 'warn');
        dsRows += '<tr><td>' + d.dataset + '</td><td>' + (d.dataDate || '—') + '</td><td><span class="badge ' + cls + '">' +
          (d.status || '—') + '</span></td><td style="text-align:left">' + (d.note || '') + '</td><td>' +
          (d.rows != null ? d.rows : '—') + '</td></tr>';
      });
      if (!(st.datasets || []).length) dsRows = '<tr><td colspan="5">尚無紀錄 — 按「同步資料」啟動預抓</td></tr>';
      var srcPanel = '';
      if (ds && (ds.sources || ds.length)) {
        var list = ds.sources || ds;
        var srcRows = '';
        (Array.isArray(list) ? list : []).slice(0, 30).forEach(function (x) {
          srcRows += '<tr><td>' + (x.name || x.id || x.provider || '') + '</td><td>' +
            (x.status || x.reliability || '—') + '</td><td style="text-align:left">' +
            (x.note || x.lastUpdate || '') + '</td></tr>';
        });
        srcPanel = '<div class="hub-sec"><h4>系統資料源</h4><div class="hub-fill"><table>' +
          '<tr><th>來源</th><th>狀態</th><th>備註</th></tr>' + srcRows + '</table></div></div>';
      } else {
        srcPanel = '<div class="hub-sec"><h4>系統資料源</h4><div class="hub-empty">尚無資料源資訊</div></div>';
      }
      var body = $('hub-set-body');
      if (!body) return;
      body.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">自動同步</div><div class="v">' +
            (st.running ? '進行中' : '待命') + '</div>' +
            '<div class="s"><span class="badge ' + (st.running ? 'warn' : 'ok') + '">' +
            (st.lastOk ? '上次成功 ' + st.lastOk : '尚未成功') + '</span></div></div>' +
          '<div class="cell"><div class="k">歷史庫列數</div><div class="v" style="font-size:11px">' + countChips + '</div></div>' +
          '<div class="cell"><div class="k">Server</div><div class="v">' + (health.status || '—') + '</div>' +
            '<div class="s">Stock Terminal 5.0 · loopback</div></div>' +
          '<div class="cell"><div class="k">策略</div><div class="v">增量 merge</div>' +
            '<div class="s">只更新新交易日</div></div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-2">' +
          '<div class="hub-sec"><h4>資料來源狀態（pulse_history）</h4><div class="hub-fill"><table>' +
            '<tr><th>資料集</th><th>資料日</th><th>狀態</th><th>說明</th><th>列數</th></tr>' +
            dsRows + '</table></div><div class="hub-note">DB：' + (st.db || '') + '</div></div>' +
          srcPanel +
        '</div>';
      bindCommon(el);
    });
  }

  function bindCommon(root) {
    root.querySelectorAll('[data-go]').forEach(function (b) {
      b.onclick = function () {
        var opts = {};
        if (b.getAttribute('data-sym')) opts.sym = b.getAttribute('data-sym');
        if (b.getAttribute('data-mkt')) opts.mkt = b.getAttribute('data-mkt');
        goRoute(b.getAttribute('data-go'), opts);
      };
    });
    root.querySelectorAll('[data-shell-back]').forEach(function (b) {
      b.onclick = function (e) {
        e.preventDefault();
        if (window.ShellV5 && typeof window.ShellV5.goDashboard === 'function') {
          window.ShellV5.goDashboard();
        } else {
          goRoute('pulse');
        }
      };
    });
    root.querySelectorAll('[data-sync]').forEach(function (b) {
      b.onclick = function () {
        b.textContent = '同步中…';
        jget('/sync?days=40').then(function (r) {
          b.textContent = (r && r.started) ? '已啟動' : '進行中';
          if (window.ShellV5 && window.ShellV5.setSync) {
            window.ShellV5.setSync('ok', r && r.started ? 'SYNCING' : 'BUSY');
          }
          setTimeout(function () {
            var route = window.ShellV5 && window.ShellV5.route && window.ShellV5.route();
            if (route && ACTIVATORS[route]) ACTIVATORS[route]();
          }, 2500);
        });
      };
    });
    root.querySelectorAll('tr[data-code]').forEach(function (tr) {
      tr.onclick = function () { openChart(tr.getAttribute('data-code'), tr.getAttribute('data-mkt') || 'TW'); };
    });
  }

  var ACTIVATORS = {
    institutional: function () { var el = mount('institutional'); if (el) renderInstitutional(el); },
    international: function () { var el = mount('international'); if (el) renderInternational(el); },
    signals: function () { var el = mount('signals'); if (el) renderSignals(el); },
    watchlist: function () { var el = mount('watchlist'); if (el) renderWatchlist(el); },
    risk: function () { var el = mount('risk'); if (el) renderRisk(el); },
    settings: function () { var el = mount('settings'); if (el) renderSettings(el); }
  };

  function hubApi(fn) {
    return { activate: fn, deactivate: function () {}, mount: fn };
  }

  window.HubV5 = ACTIVATORS;
  window.InstitutionalV5 = hubApi(ACTIVATORS.institutional);
  window.InternationalV5 = hubApi(ACTIVATORS.international);
  window.SignalsV5 = hubApi(ACTIVATORS.signals);
  window.WatchlistV5 = hubApi(ACTIVATORS.watchlist);
  window.RiskV5 = hubApi(ACTIVATORS.risk);
  window.SettingsV5 = hubApi(ACTIVATORS.settings);
  window.TrendsV5 = {
    activate: function () {
      if (window.ShellV5 && ShellV5.openChart) ShellV5.openChart('^TWII', 'TW');
      else if (window.ShellV5) ShellV5.go('chart', { sym: '^TWII', mkt: 'TW' });
    },
    mount: function () { this.activate(); }
  };

  window.addEventListener('shell:route', function (ev) {
    var id = ev && ev.detail && ev.detail.route;
    if (id && ACTIVATORS[id]) ACTIVATORS[id]();
  });
})();

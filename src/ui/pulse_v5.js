/* ============================================================================
 * pulse_v5.js  —  Stock Terminal 5.0：市場總覽儀表板
 * ----------------------------------------------------------------------------
 * 大螢幕一頁高密度（65" 優化，不遷就手機）：
 *   頂列 KPI 細條
 *   上區 5 窗：脈動｜盤勢｜法人｜廣度｜產業
 *   下區 5 窗：漲停｜跌幅｜全球｜快訊｜自選
 *   因子／歷史預設收合（按鈕展開）
 * 產品名 Stock Terminal 5.0；資料：GET /pulse — 真實欄位，禁止 mock。
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var lastPack = null;
  var showFactors = false;
  var sectorMkt = 'TW';
  var sectorCache = { TW: null, US: null };

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    var s = $('pulse-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'pulse-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      /* 一屏鎖定：上下兩區各 5 窗，大螢幕塞滿資訊 */
      '#shell-views:has(#view-pulse.on){overflow:hidden!important}' +
      '#view-pulse.sv-panel.on{' +
        'max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-pulse,#mount-pulse.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#pl-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:none;margin:0;min-width:0;box-sizing:border-box;' +
        'flex:1;min-height:0;display:flex;flex-direction:column}' +
      /* 單列微標題 */
      '#pl-root .pl-head{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#pl-root .pl-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#pl-root .pl-kicker{font-size:9px;color:var(--gold);letter-spacing:1.2px;margin:0;font-weight:700}' +
      '#pl-root .pl-title{font-family:\'Noto Serif TC\',serif;font-size:15px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#pl-root .pl-sub{font-size:9px;color:var(--tlo);margin:0}' +
      '#pl-root .pl-tone{margin:0;font-size:10px;font-weight:700}' +
      '#pl-root .pl-actions{display:flex;gap:4px;flex-wrap:nowrap;justify-content:flex-end;flex:0 0 auto}' +
      '#pl-root .pl-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;flex:0 0 auto;white-space:nowrap}' +
      '#pl-root .pl-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#pl-root .pl-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#pl-root .pl-btn.on{border-color:var(--gold-m);color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .up{color:var(--red)}#pl-root .dn{color:var(--green)}#pl-root .flat{color:var(--tlo)}' +
      '#pl-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#pl-body.pl-expanded{overflow:auto}' +
      /* KPI 細條 */
      '#pl-root .pl-strip{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px;margin:0 0 4px;min-width:0;flex:0 0 auto}' +
      '#pl-root .pl-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-strip .k{font-size:8px;color:var(--tlo);letter-spacing:.4px;margin-bottom:0;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .v{font-size:12px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .s{font-size:8px;margin-top:0;font-weight:700;line-height:1.2;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .badge{display:inline-flex;align-items:center;gap:3px;font-size:8px;color:var(--cyan)}' +
      '#pl-root .pl-strip .dot{width:4px;height:4px;border-radius:50%;background:var(--green);box-shadow:0 0 4px var(--green);flex-shrink:0}' +
      '#pl-root .pl-strip .viz-hide,#pl-root .pl-strip .viz-meter,#pl-root .pl-strip .viz-seg,' +
        '#pl-root .pl-strip .viz-chip{display:none!important}' +
      /* 上下兩區 */
      '#pl-root .pl-dash{flex:1;min-height:0;display:grid;gap:4px;' +
        'grid-template-rows:minmax(0,1fr) minmax(0,1fr)}' +
      '#pl-root .pl-zone{display:grid;gap:4px;min-width:0;min-height:0;height:100%;' +
        'grid-template-columns:repeat(5,minmax(0,1fr))}' +
      '#pl-root .pl-sec{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%}' +
      '#pl-root .pl-sec h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px;' +
        'display:flex;justify-content:space-between;align-items:center;flex:0 0 auto;gap:4px}' +
      '#pl-root .pl-sec h4 a{color:var(--cyan);cursor:pointer;font-size:8px;font-weight:600;text-decoration:none;white-space:nowrap}' +
      '#pl-root .pl-sec h4 a:hover{color:var(--gold)}' +
      '#pl-root .pl-sec > .pl-fill{flex:1;min-height:0;overflow:auto}' +
      '#pl-root .pl-note{font-size:8px;color:var(--tlo);line-height:1.35;margin-top:3px;flex:0 0 auto}' +
      '#pl-root .pl-loading{font-size:10px;color:var(--tlo);padding:12px 0}' +
      /* gauge compact */
      '#pl-root .pl-gauge-wrap{display:flex;align-items:center;gap:8px;flex:1;min-height:0}' +
      '#pl-root .pl-gauge{width:88px;height:88px;border-radius:50%;flex-shrink:0;' +
        'background:conic-gradient(var(--gold) var(--pl-deg,0%), rgba(245,197,24,.10) 0);' +
        'display:flex;align-items:center;justify-content:center;position:relative}' +
      '#pl-root .pl-gauge::before{content:\'\';position:absolute;inset:8px;border-radius:50%;background:var(--bg2)}' +
      '#pl-root .pl-gauge-inner{position:relative;z-index:1;text-align:center}' +
      '#pl-root .pl-gauge-inner .big{font-size:20px;font-weight:800;color:var(--thi);line-height:1}' +
      '#pl-root .pl-gauge-inner .tag{display:inline-block;margin-top:2px;padding:1px 6px;border-radius:999px;' +
        'font-size:8px;font-weight:700;background:var(--gold-s);color:var(--gold);border:1px solid var(--gold-m)}' +
      '#pl-root .pl-mini{display:grid;grid-template-columns:1fr 1fr;gap:4px;flex:1;min-width:0}' +
      '#pl-root .pl-mini .m{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px}' +
      '#pl-root .pl-mini .m .k{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-mini .m .v{font-size:13px;font-weight:800;margin-top:1px;color:var(--thi)}' +
      '#pl-root .pl-mini .m .l{font-size:8px;margin-top:1px;font-weight:700}' +
      '#pl-root .pl-comp{height:4px;border-radius:2px;background:var(--bg3);overflow:hidden;margin-top:3px}' +
      '#pl-root .pl-comp > i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--gold))}' +
      '#pl-root .pl-drivers{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px;font-size:9px;flex:0 0 auto}' +
      '#pl-root .pl-drivers .box{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px}' +
      '#pl-root .pl-drivers .box .k{color:var(--tlo);margin-bottom:2px;font-size:8px}' +
      '#pl-root .pl-drivers .box li{margin:1px 0;color:var(--text);list-style:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      /* OHLC / trend */
      '#pl-root .pl-ohlc{display:grid;grid-template-columns:repeat(2,1fr);gap:4px;flex:0 0 auto}' +
      '#pl-root .pl-ohlc .box{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px}' +
      '#pl-root .pl-ohlc .box .k{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-ohlc .box .v{font-size:12px;font-weight:700;margin-top:1px;color:var(--thi)}' +
      '#pl-root .pl-trend-pair{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:4px;flex:0 0 auto}' +
      '#pl-root .pl-trend-pair .tp{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px}' +
      '#pl-root .pl-trend-pair .tp .k{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-trend-pair .tp .v{font-size:14px;font-weight:800;margin-top:1px}' +
      '#pl-root .pl-sec-tog{display:inline-flex;gap:2px;margin-left:auto}' +
      '#pl-root .pl-sec-tog button{padding:1px 6px;border:1px solid var(--border);border-radius:3px;background:transparent;' +
        'color:var(--tlo);font-size:8px;font-family:inherit;cursor:pointer}' +
      '#pl-root .pl-sec-tog button.on{border-color:var(--gold-m);color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .pl-spark{flex:1;min-height:40px;margin:3px 0;background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:2px 4px}' +
      '#pl-root .pl-spark svg{width:100%;height:100%;display:block}' +
      /* inst：上方數字、下方趨勢＋評論（不再重複量柱） */
      '#pl-root .pl-inst4{display:grid;grid-template-columns:1fr 1fr;gap:3px;flex:0 0 auto}' +
      '#pl-root .pl-inst4 .c{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px;text-align:center}' +
      '#pl-root .pl-inst4 .c .k{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-inst4 .c .v{font-size:13px;font-weight:800;margin-top:2px}' +
      '#pl-root .pl-inst-trend{flex:1;min-height:48px;margin:4px 0 2px;background:var(--bg);border:1px solid var(--border);' +
        'border-radius:5px;padding:3px 5px;display:flex;flex-direction:column;overflow:hidden}' +
      '#pl-root .pl-inst-trend .lab{font-size:8px;color:var(--tlo);flex:0 0 auto;margin-bottom:2px;' +
        'display:flex;justify-content:space-between;gap:6px}' +
      '#pl-root .pl-inst-trend .chart{flex:1;min-height:36px}' +
      '#pl-root .pl-inst-trend .chart .vz-spark,#pl-root .pl-inst-trend .chart svg{width:100%!important;height:100%!important;min-height:36px}' +
      '#pl-root .pl-inst-cmt{font-size:9px;line-height:1.45;color:var(--text);margin-top:2px;flex:0 0 auto;' +
        'max-height:4.4em;overflow:hidden}' +
      '#pl-root .pl-inst-cmt b{color:var(--gold);font-weight:700}' +
      '#pl-root .pl-inst-cmt .up{color:var(--red)}#pl-root .pl-inst-cmt .dn{color:var(--green)}' +
      '#pl-root .pl-chip{display:inline-block;margin:1px 3px 0 0;padding:0 5px;border-radius:999px;border:1px solid var(--border);font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-tag{display:inline-block;margin-left:3px;padding:0 4px;border-radius:3px;font-size:8px;font-weight:700}' +
      '#pl-root .pl-tag.hot{background:var(--gold-s);color:var(--gold);border:1px solid var(--gold-m)}' +
      '#pl-root .pl-tag.cold{background:rgba(56,189,248,.08);color:var(--cyan);border:1px solid rgba(56,189,248,.25)}' +
      '#pl-root .pl-tag.ok{background:rgba(34,197,94,.08);color:var(--green);border:1px solid rgba(34,197,94,.25)}' +
      /* donut／廣度：上方結構、下方多空比趨勢＋評論（不再只重複漲跌停） */
      '#pl-root .pl-donut-wrap{display:flex;align-items:center;gap:8px;flex:0 0 auto}' +
      '#pl-root .pl-donut{width:64px;height:64px;border-radius:50%;flex-shrink:0;position:relative;' +
        'background:conic-gradient(var(--red) 0 var(--pl-u,0%), #334155 var(--pl-u,0%) var(--pl-uf,0%), var(--green) var(--pl-uf,0%) 100%)}' +
      '#pl-root .pl-donut::before{content:\'\';position:absolute;inset:16px;border-radius:50%;background:var(--bg2)}' +
      '#pl-root .pl-donut .mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:1}' +
      '#pl-root .pl-donut .mid b{font-size:12px;color:var(--thi)}' +
      '#pl-root .pl-donut .mid span{font-size:7px;color:var(--tlo)}' +
      '#pl-root .pl-leg{font-size:9px;line-height:1.4;min-width:0;flex:1}' +
      '#pl-root .pl-leg i{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:4px}' +
      '#pl-root .pl-bd-trend{flex:1;min-height:44px;margin:4px 0 2px;background:var(--bg);border:1px solid var(--border);' +
        'border-radius:5px;padding:3px 5px;display:flex;flex-direction:column;overflow:hidden}' +
      '#pl-root .pl-bd-trend .lab{font-size:8px;color:var(--tlo);flex:0 0 auto;margin-bottom:2px;' +
        'display:flex;justify-content:space-between;gap:6px}' +
      '#pl-root .pl-bd-trend .chart{flex:1;min-height:32px}' +
      '#pl-root .pl-bd-trend .chart .vz-spark,#pl-root .pl-bd-trend .chart svg{width:100%!important;height:100%!important;min-height:32px}' +
      '#pl-root .pl-bd-cmt{font-size:9px;line-height:1.45;color:var(--text);margin-top:2px;flex:0 0 auto;' +
        'max-height:4.4em;overflow:hidden}' +
      '#pl-root .pl-bd-cmt b{color:var(--gold);font-weight:700}' +
      '#pl-root .pl-bd-cmt .up{color:var(--red)}#pl-root .pl-bd-cmt .dn{color:var(--green)}' +
      /* sectors */
      '#pl-root .pl-sbar{display:flex;align-items:center;gap:5px;margin:2px 0;font-size:10px}' +
      '#pl-root .pl-sbar .nm{width:56px;flex-shrink:0;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-sbar .track{flex:1;height:6px;background:var(--bg);border-radius:3px;overflow:hidden}' +
      '#pl-root .pl-sbar .track > i{display:block;height:100%;border-radius:3px}' +
      '#pl-root .pl-sbar .pc{width:48px;text-align:right;font-weight:700;flex-shrink:0;font-size:10px}' +
      /* lists */
      '#pl-root .pl-list{list-style:none;margin:0;padding:0;flex:1;min-height:0;overflow:auto}' +
      '#pl-root .pl-list li{display:flex;justify-content:space-between;gap:4px;padding:3px 1px;border-bottom:1px solid var(--border);cursor:pointer;font-size:10px}' +
      '#pl-root .pl-list li:hover{background:var(--bg3)}' +
      '#pl-root .pl-list .nm{color:var(--thi);font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-list .cd{color:var(--tlo);font-size:9px;margin-right:4px}' +
      /* global / flash / wl */
      '#pl-root .pl-global{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px;flex:1;align-content:start;overflow:auto;min-height:0}' +
      '#pl-root .pl-kicker{display:none!important}' +
      '#pl-root .pl-global .g{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-global .g .k{font-size:8px;color:var(--tlo);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-global .g .v{font-size:12px;font-weight:800;margin-top:1px;color:var(--thi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-flash{flex:1;min-height:0;overflow:auto;font-size:10px}' +
      '#pl-root .pl-flash .row{padding:3px 0;border-bottom:1px solid var(--border);cursor:pointer}' +
      '#pl-root .pl-flash .t{color:var(--tlo);font-size:8px;margin-right:4px}' +
      '#pl-root .pl-wl{flex:1;min-height:0;overflow:auto}' +
      '#pl-root .pl-wl table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#pl-root .pl-wl th,#pl-root .pl-wl td{padding:3px 3px;border-bottom:1px solid var(--border);text-align:right}' +
      '#pl-root .pl-wl th:first-child,#pl-root .pl-wl td:first-child{text-align:left}' +
      '#pl-root .pl-wl th{color:var(--tlo)}' +
      '#pl-root .pl-wl tr{cursor:pointer}#pl-root .pl-wl tr:hover{background:var(--bg3)}' +
      /* factors footer（展開時可捲） */
      '#pl-root .pl-extra{flex:0 0 auto;margin-top:4px}' +
      '#pl-root .pl-factors{margin-top:4px;scroll-margin-top:8px;padding:2px;border-radius:8px;transition:box-shadow .35s,background .35s}' +
      '#pl-root .pl-factors.flash{box-shadow:0 0 0 1px var(--gold-m),0 0 24px rgba(245,197,24,.18);background:rgba(245,197,24,.04)}' +
      '#pl-root .pl-factors > .pl-sec-title{font-family:\'Noto Serif TC\',serif;font-size:13px;font-weight:700;color:var(--thi);margin:0 0 6px;letter-spacing:.5px}' +
      '#pl-root .pl-three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:6px}' +
      '#pl-root .pl-fac{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:6px;margin-bottom:4px;cursor:pointer}' +
      '#pl-root .pl-fac:hover{border-color:var(--gold-m);background:var(--bg3)}' +
      '#pl-root .pl-fac.open{border-color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .pl-fac .hd{display:flex;justify-content:space-between;gap:6px;font-size:10px;font-weight:700;color:var(--thi)}' +
      '#pl-root .pl-fac .ds{font-size:9px;color:var(--tlo);line-height:1.4;margin-top:2px}' +
      '#pl-root .pl-fac .more{display:none;margin-top:4px;padding-top:4px;border-top:1px dashed var(--border);font-size:9px;color:var(--text);line-height:1.45}' +
      '#pl-root .pl-fac.open .more{display:block}' +
      '#pl-root .pl-fac .sc-pos{color:var(--red)}#pl-root .pl-fac .sc-risk{color:var(--cyan)}#pl-root .pl-fac .sc-pend{color:var(--tlo)}' +
      '#pl-root .pl-col{max-height:220px;overflow:auto}' +
      '#pl-root table.pillars{width:100%;border-collapse:collapse;font-size:10px}' +
      '#pl-root table.pillars th,#pl-root table.pillars td{padding:3px 4px;border-bottom:1px solid var(--border);text-align:right}' +
      '#pl-root table.pillars th:first-child,#pl-root table.pillars td:first-child{text-align:left}' +
      '#pl-root table.pillars th{color:var(--tlo)}';
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
  function yi(v) {
    if (v == null || !isFinite(v)) return '—';
    // accept 元 or already 億 (heuristic: |v| > 1e5 → 元)
    var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
    return (v < 0 && x > 0 ? '-' : '') + (v >= 0 && Math.abs(v) > 1e5 ? '' : (v >= 0 && x >= 0 && Math.abs(v) <= 1e5 && v !== x ? '' : '')) +
      (Math.abs(v) > 1e5 ? (v / 1e8) : v).toFixed(1).replace(/^-/, v < 0 ? '-' : '') + ' 億';
  }
  function moneyYi(v) {
    if (v == null || !isFinite(v)) return '—';
    var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
    return (x >= 0 ? '+' : '') + x.toFixed(1) + ' 億';
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
          '<div class="pl-head"><div>' +
            '<div class="pl-title">市場總覽</div>' +
            '<div class="pl-tone" id="pl-tone">—</div>' +
            '<div class="pl-sub" id="pl-sub">官方資料 · 一頁雙區</div>' +
          '</div><div class="pl-actions">' +
            '<button type="button" class="pl-btn" id="pl-refresh">↻ 重新整理</button>' +
            '<button type="button" class="pl-btn" id="pl-toggle-fac">因子帳本</button>' +
            '<button type="button" class="pl-btn" data-go="breadth">廣度</button>' +
            '<button type="button" class="pl-btn" data-go="heat">熱力</button>' +
            '<button type="button" class="pl-btn" data-go="afterhours">盤後</button>' +
            '<button type="button" class="pl-btn primary" data-go="chart">圖表</button>' +
          '</div></div>' +
          '<div id="pl-body" class="pl-loading">載入總覽儀表板…</div>' +
        '</div>';
      var r = $('pl-refresh');
      if (r) r.onclick = function () { refresh(true); };
      var tf = $('pl-toggle-fac');
      if (tf) tf.onclick = function () { focusFactors(); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () {
          goRoute(b.getAttribute('data-go'), {
            sym: b.getAttribute('data-sym') || undefined,
            mkt: b.getAttribute('data-mkt') || undefined
          });
        };
      });
    }
    syncFactorBtn();
    return $('pl-body');
  }

  function syncFactorBtn() {
    var tf = $('pl-toggle-fac');
    if (!tf) return;
    tf.classList.toggle('on', !!showFactors);
    tf.setAttribute('aria-pressed', showFactors ? 'true' : 'false');
    tf.title = showFactors ? '捲動至因子帳本（再按一次可收合）' : '顯示因子帳本';
  }

  function scrollToFactors() {
    var el = $('pl-factors');
    if (!el) return false;
    try { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    catch (e) { el.scrollIntoView(true); }
    el.classList.remove('flash');
    // reflow so animation retriggers
    void el.offsetWidth;
    el.classList.add('flash');
    setTimeout(function () { el.classList.remove('flash'); }, 1400);
    return true;
  }

  /** 因子帳本：優先「顯示並捲動」；已顯示且已在視窗內則收合 */
  function focusFactors() {
    var el = $('pl-factors');
    if (showFactors && el) {
      var rect = el.getBoundingClientRect();
      var viewH = window.innerHeight || 800;
      var inView = rect.top < viewH * 0.85 && rect.bottom > 80;
      if (inView) {
        showFactors = false;
        syncFactorBtn();
        if (lastPack) render(lastPack);
        else refresh(false);
        return;
      }
      scrollToFactors();
      syncFactorBtn();
      return;
    }
    showFactors = true;
    syncFactorBtn();
    if (lastPack) render(lastPack);
    else refresh(false);
    // render 後下一幀再捲動（DOM 已掛上 #pl-factors）
    setTimeout(function () { scrollToFactors(); }, 40);
  }

  function factorCol(title, cls, list, empty) {
    var html = '<div class="pl-sec pl-col"><h4>' + title + ' <span style="color:var(--tlo);font-weight:600">(' + (list || []).length + ')</span></h4>';
    if (!list || !list.length) return html + '<div class="pl-note">' + empty + '</div></div>';
    list.forEach(function (f) {
      var sc = f.score;
      var scTxt = cls === 'sc-pend' ? '不計分' : (cls === 'sc-pos' ? ((sc >= 0 ? '+' : '') + Number(sc).toFixed(1) + '分') : (Number(sc).toFixed(1) + '分'));
      var typ = f.type || (cls === 'sc-risk' ? 'risk' : (cls === 'sc-pend' ? 'pending' : 'positive'));
      var more = '類型 ' + typ +
        (f.score != null ? ' · 權重分 ' + Number(f.score).toFixed(2) : '') +
        ' · 點列可展開／收合細節';
      html += '<div class="pl-fac" tabindex="0" role="button" data-fac="' +
        esc(f.id || '') + '"><div class="hd"><span>' + esc(f.id || '') + '. ' + esc(f.name || '') +
        '</span><span class="' + cls + '">' + esc(scTxt) + '</span></div>' +
        '<div class="ds">' + esc(f.description || '') + '</div>' +
        '<div class="more">' + esc(more) + '</div></div>';
    });
    return html + '</div>';
  }

  function readWatchlist() {
    try {
      var raw = localStorage.getItem('st_wl');
      var arr = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(arr)) return [];
      return arr.filter(function (x) { return x && x.t; }).slice(0, 8);
    } catch (e) { return []; }
  }

  function breadthToneLabel(adv, ls) {
    if (adv == null && ls == null) return '—';
    if ((ls != null && ls >= 3) || (adv != null && adv >= 0.75)) return '極度偏多';
    if ((ls != null && ls >= 1.8) || (adv != null && adv >= 0.60)) return '偏多擴張';
    if ((ls != null && ls <= 0.35) || (adv != null && adv <= 0.30)) return '極度偏空';
    if ((ls != null && ls <= 0.55) || (adv != null && adv <= 0.40)) return '偏空收縮';
    return '廣度糾結';
  }

  function factorNames(list, n) {
    return (list || []).slice(0, n || 3).map(function (f) { return f.name; }).filter(Boolean);
  }

  function sparkSvg(closes) {
    if (!closes || closes.length < 2) {
      return '<div class="pl-note" style="padding:8px">近 20 日走勢尚在累積（同步資料後顯示）</div>';
    }
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes);
    var span = (hi - lo) || 1;
    var w = 280, h = 48, pad = 2;
    var pts = closes.map(function (c, i) {
      var x = pad + (i / (closes.length - 1)) * (w - pad * 2);
      var y = pad + (1 - (c - lo) / span) * (h - pad * 2);
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    var last = closes[closes.length - 1];
    var first = closes[0];
    var up = last >= first;
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polyline fill="none" stroke="' + (up ? 'var(--red)' : 'var(--green)') +
      '" stroke-width="2" points="' + pts + '"/></svg>';
  }

  function renderStrip(ov, p) {
    var V = window.Viz;
    var s = (ov && ov.strip) || {};
    var t00 = s.t00 || {};
    var o00 = s.o00 || {};
    var txf = p.txf || {};
    var adv = s.advRatio;
    var tone = breadthToneLabel(adv, s.lsRatio);
    var toneKind = (tone.indexOf('偏多') >= 0 || tone.indexOf('極度偏多') >= 0) ? 'buy'
      : (tone.indexOf('偏空') >= 0 || tone.indexOf('極度偏空') >= 0) ? 'sell' : 'mid';
    var udfViz = V ? V.segBar(s.up, s.flat, s.down) : '';
    var turnViz = (V && s.turnoverYi != null) ? V.refMeter(s.turnoverYi, [8000, 12000]) : '';
    var advViz = V ? (V.scoreMeter((adv || 0) * 100) + V.chip(tone, toneKind)) : '';
    var txfSess = txf.sessionLabel || (txf.session === 'night' ? '夜盤' : (txf.session === 'day' ? '日盤' : ''));
    return '<div class="pl-strip">' +
      '<div class="cell"><div class="k">加權指數 TAIEX</div><div class="v">' + fmt(t00.price, 2) + '</div>' +
        '<div class="s ' + tw(t00.changePct) + '">' + pct(t00.changePct) + '</div></div>' +
      '<div class="cell"><div class="k">櫃買指數 OTC</div><div class="v">' + fmt(o00.price, 2) + '</div>' +
        '<div class="s ' + tw(o00.changePct) + '">' + pct(o00.changePct) + '</div></div>' +
      '<div class="cell"><div class="k">台指期 TXF' + (txfSess ? ' · ' + txfSess : '') + '</div><div class="v">' +
        fmt(txf.price, 0) + '</div>' +
        '<div class="s ' + tw(txf.changePct) + '">' + pct(txf.changePct) +
        (txf.ampRate != null ? ' · 振幅 ' + Number(txf.ampRate).toFixed(2) + '%' : '') + '</div></div>' +
      '<div class="cell"><div class="k">成交金額</div><div class="v">' +
        (s.turnoverYi != null ? Number(s.turnoverYi).toFixed(1) + ' 億' : '—') + '</div>' +
        '<div class="s ' + tw(s.turnoverChgPct) + '">' +
        (s.turnoverChgPct != null ? pct(s.turnoverChgPct) + ' vs 前日' : '—') + '</div>' +
        turnViz + '</div>' +
      '<div class="cell"><div class="k">上漲 / 下跌 / 平盤</div><div class="v" style="font-size:14px">' +
        '<span class="up">' + fmt(s.up) + '</span> / <span class="dn">' + fmt(s.down) + '</span> / <span class="flat">' + fmt(s.flat) + '</span></div>' +
        '<div class="s">多空比 ' + (s.lsRatio != null ? s.lsRatio.toFixed(2) : '—') + '</div>' +
        udfViz + '</div>' +
      '<div class="cell"><div class="k">市場廣度</div><div class="v">' +
        (adv != null ? (adv * 100).toFixed(1) + '%' : '—') + '</div>' +
        '<div class="s">' + tone + '</div>' + advViz + '</div>' +
      '<div class="cell"><div class="k">漲停 / 跌停</div><div class="v" style="font-size:14px">' +
        '<span class="up">' + fmt(s.limitUp) + '</span> / <span class="dn">' + fmt(s.limitDown) + '</span></div>' +
        '<div class="s">' + (s.dataLabel || 'LOCAL') +
        (p.dataCompleteness != null ? ' · ' + Number(p.dataCompleteness).toFixed(0) + '%' : '') +
        '</div></div>' +
      '</div>';
  }

  function renderGauge(p) {
    var V = window.Viz;
    var total = p.totalScore;
    var deg = (total != null ? Math.max(0, Math.min(100, total)) : 0) * 3.6;
    var comp = p.dataCompleteness != null ? p.dataCompleteness : 0;
    var drivers = factorNames(p.positiveFactors, 3);
    var pressures = factorNames(p.riskFactors, 3);
    var healthMeter = V ? V.scoreMeter(p.healthScore) : '';
    var riskMeter = V ? V.scoreMeter(p.riskScore, { color: 'var(--cyan)' }) : '';
    return '<div class="pl-sec"><h4>市場脈動 <a data-go="pulse">因子 →</a></h4><div class="pl-gauge-wrap">' +
      '<div class="pl-gauge" style="--pl-deg:' + deg.toFixed(1) + 'deg"><div class="pl-gauge-inner">' +
        '<div class="big">' + (total != null ? Number(total).toFixed(1) : '—') + '</div>' +
        '<div class="tag">' + (p.statusText || '—') + '</div></div></div>' +
      '<div class="pl-mini">' +
        '<div class="m"><div class="k">市場動能</div><div class="v">' +
          (p.healthScore != null ? Number(p.healthScore).toFixed(1) : '—') +
          '<span style="font-size:10px;color:var(--tlo);font-weight:600"> /100</span></div>' +
          '<div class="l" style="color:var(--gold)">' + (p.healthLabel || '') + '</div>' +
          healthMeter + '</div>' +
        '<div class="m"><div class="k">市場風險</div><div class="v">' +
          (p.riskScore != null ? Number(p.riskScore).toFixed(1) : '—') +
          '<span style="font-size:10px;color:var(--tlo);font-weight:600"> /100</span></div>' +
          '<div class="l" style="color:var(--cyan)">' + (p.riskLabel || '') + '</div>' +
          riskMeter + '</div>' +
        '<div class="m"><div class="k">正面因素</div><div class="v up">' +
          (p.positiveFactorScore != null ? Number(p.positiveFactorScore).toFixed(1) : '—') + '</div>' +
          '<div class="l" style="color:var(--tlo)">' + ((p.positiveFactors || []).length) + ' 項</div></div>' +
        '<div class="m"><div class="k">資料可靠度</div><div class="v">' + Number(comp).toFixed(0) + '%</div>' +
          '<div class="l" style="color:var(--tlo)">' + (p.datasetsOk || 0) + '/' + (p.datasetsTotal || 0) + ' 資料源</div>' +
          '<div class="pl-comp"><i style="width:' + comp + '%"></i></div></div>' +
      '</div></div>' +
      '<div class="pl-drivers">' +
        '<div class="box"><div class="k">主要動能</div><ul>' +
          (drivers.length ? drivers.map(function (n) { return '<li>· ' + esc(n) + '</li>'; }).join('') : '<li style="color:var(--tlo)">—</li>') +
        '</ul></div>' +
        '<div class="box"><div class="k">主要壓力</div><ul>' +
          (pressures.length ? pressures.map(function (n) { return '<li>· ' + esc(n) + '</li>'; }).join('') : '<li style="color:var(--tlo)">—</li>') +
        '</ul></div></div>' +
      '</div>';
  }

  function renderOhlc(ov, p) {
    var o = (ov && ov.ohlc) || {};
    var txf = (p && p.txf) || {};
    var txfSess = txf.sessionLabel || (txf.session === 'night' ? '夜盤' : (txf.session === 'day' ? '日盤' : '台指期'));
    return '<div class="pl-sec"><h4>盤勢走勢 <a data-go="chart" data-sym="^TWII" data-mkt="TW">圖表 →</a></h4>' +
      '<div class="pl-trend-pair">' +
        '<div class="tp"><div class="k">加權今日漲幅</div><div class="v ' + tw(o.changePct) + '">' + pct(o.changePct) + '</div>' +
          '<div class="pl-note" style="margin:2px 0 0">現價 ' + fmt(o.price, 2) + '</div></div>' +
        '<div class="tp"><div class="k">櫃買今日漲幅</div><div class="v ' + tw(o.otcChangePct) + '">' + pct(o.otcChangePct) + '</div>' +
          '<div class="pl-note" style="margin:2px 0 0">現價 ' + fmt(o.otcPrice, 2) + '</div></div>' +
        '<div class="tp"><div class="k">台指期 · ' + esc(txfSess) + '</div><div class="v ' + tw(txf.changePct) + '">' +
          pct(txf.changePct) + '</div>' +
          '<div class="pl-note" style="margin:2px 0 0">現價 ' + fmt(txf.price, 0) +
          (txf.ampRate != null ? ' · 振幅 ' + Number(txf.ampRate).toFixed(2) + '%' : '') + '</div></div>' +
      '</div>' +
      '<div class="pl-spark" id="pl-spark"><div class="pl-note" style="padding:8px">載入近 20 日走勢…</div></div>' +
      '<div class="pl-ohlc">' +
      '<div class="box"><div class="k">開盤</div><div class="v">' + fmt(o.open, 2) + '</div></div>' +
      '<div class="box"><div class="k">最高</div><div class="v">' + fmt(o.high, 2) + '</div></div>' +
      '<div class="box"><div class="k">最低</div><div class="v">' + fmt(o.low, 2) + '</div></div>' +
      '<div class="box"><div class="k">昨收</div><div class="v">' + fmt(o.prevClose, 2) + '</div></div>' +
      '</div></div>';
  }

  function yiNum(v) {
    if (v == null || !isFinite(v)) return null;
    /* 已是億則原樣；否則當元轉億 */
    return Math.abs(v) >= 1e6 ? v / 1e8 : v;
  }

  function fmtYiSigned(v) {
    var y = yiNum(v);
    if (y == null) return '—';
    return (y >= 0 ? '+' : '') + y.toFixed(1) + ' 億';
  }

  /** 依當日法人＋歷史序列產生趨勢評論（不重複上方數字本身） */
  function buildInstComment(i, histNewestFirst) {
    var parts = [];
    var f = yiNum(i.foreign), t = yiNum(i.trust), d = yiNum(i.dealer);
    var tot = i.totalYi != null && isFinite(i.totalYi) ? Number(i.totalYi) : (
      (f != null || t != null || d != null) ? ((f || 0) + (t || 0) + (d || 0)) : null
    );
    var rows = (histNewestFirst || []).filter(function (r) {
      return r && r.totalYi != null && isFinite(r.totalYi);
    });
    var chrono = rows.slice().reverse(); /* 舊→新 */
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

  function renderInst(ov) {
    var i = (ov && ov.institutional) || {};
    var totalTxt = i.totalYi != null
      ? ((i.totalYi >= 0 ? '+' : '') + Number(i.totalYi).toFixed(1) + ' 億')
      : '—';
    return '<div class="pl-sec"><h4>法人資金 <a data-go="institutional">籌碼 →</a></h4>' +
      '<div class="pl-inst4">' +
        '<div class="c"><div class="k">外資</div><div class="v ' + tw(i.foreign) + '">' + moneyYi(i.foreign) + '</div></div>' +
        '<div class="c"><div class="k">投信</div><div class="v ' + tw(i.trust) + '">' + moneyYi(i.trust) + '</div></div>' +
        '<div class="c"><div class="k">自營</div><div class="v ' + tw(i.dealer) + '">' + moneyYi(i.dealer) + '</div></div>' +
        '<div class="c"><div class="k">合計</div><div class="v ' + tw(i.totalYi) + '">' + totalTxt + '</div></div>' +
      '</div>' +
      '<div class="pl-inst-trend" id="pl-inst-trend">' +
        '<div class="lab"><span>合計買賣超趨勢</span><span id="pl-inst-trend-meta">' +
          (i.date ? '法人日 ' + esc(i.date) : '載入…') + '</span></div>' +
        '<div class="chart" id="pl-inst-chart"><div class="pl-note" style="padding:6px 0">載入資金序列…</div></div>' +
      '</div>' +
      '<div class="pl-inst-cmt" id="pl-inst-cmt">分析資金變化中…</div></div>';
  }

  function fillInstTrend(ov) {
    var i = (ov && ov.institutional) || {};
    jget('/pulse/history?kind=institutional&n=20').then(function (h) {
      var V = window.Viz;
      var chart = $('pl-inst-chart');
      var meta = $('pl-inst-trend-meta');
      var cmt = $('pl-inst-cmt');
      var rows = (h && h.rows) || [];
      var chrono = rows.slice().reverse();
      var totals = chrono.map(function (r) { return r.totalYi; });
      if (chart) {
        if (V && totals.filter(function (v) { return v != null && isFinite(v); }).length >= 2) {
          var last = totals[totals.length - 1];
          var col = last >= 0 ? 'var(--red)' : 'var(--green)';
          chart.innerHTML = V.sparkLine(totals, { color: col, h: 56, w: 280 });
        } else if (totals.length) {
          chart.innerHTML = (V ? V.sparkBars(totals) : '<div class="pl-note">序列不足</div>');
        } else {
          chart.innerHTML = '<div class="pl-note">尚無本機法人歷史 — 可按同步資料預抓</div>';
        }
      }
      if (meta) {
        meta.textContent = (rows.length ? ('近 ' + rows.length + ' 日') : '無序列') +
          (i.date ? ' · ' + i.date : '');
      }
      if (cmt) cmt.innerHTML = buildInstComment(i, rows);
    });
  }

  /** 依當日廣度＋歷史序列產生趨勢評論（不重複頂列／圓餅數字本身） */
  function buildBreadthComment(st, histNewestFirst) {
    var parts = [];
    var up = st.up, dn = st.down, flat = st.flat != null ? st.flat : st.unchanged;
    var ls = st.lsRatio;
    if (ls == null && up != null && dn) ls = up / Math.max(dn, 1);
    var adv = st.advRatio;
    var net = st.net;
    if (net == null && up != null && dn != null) net = up - dn;
    var rows = (histNewestFirst || []).filter(function (r) {
      return r && (r.lsRatio != null || (r.up != null && r.down != null));
    });
    var chrono = rows.slice().reverse();
    function rowLs(r) {
      if (r.lsRatio != null && isFinite(r.lsRatio)) return Number(r.lsRatio);
      if (r.up != null && r.down) return r.up / Math.max(r.down, 1);
      return null;
    }
    var streak = 0;
    if (ls != null && ls !== 1 && chrono.length) {
      var bull = ls > 1;
      for (var k = chrono.length - 1; k >= 0; k--) {
        var v = rowLs(chrono[k]);
        if (v == null || v === 1 || (v > 1) !== bull) break;
        streak += 1;
      }
    }
    if (streak >= 3) {
      parts.push(ls > 1
        ? '多空比已連 <b class="up">' + streak + '</b> 日偏多，上漲面持續擴張。'
        : '多空比已連 <b class="dn">' + streak + '</b> 日偏空，上漲面持續收縮。');
    } else if (ls != null) {
      parts.push(ls >= 2
        ? '多空比明顯偏多，短線參與面寬。'
        : ls <= 0.5
          ? '多空比明顯偏空，短線承壓面廣。'
          : '多空比接近均衡，方向性訊號有限。');
    }
    if (chrono.length >= 2 && ls != null) {
      var prevLs = rowLs(chrono[chrono.length - 2]);
      if (prevLs != null && isFinite(prevLs)) {
        var dLs = ls - prevLs;
        if (Math.abs(dLs) >= 0.35) {
          parts.push(dLs > 0
            ? '較前日多空比轉強約 <span class="up">+' + dLs.toFixed(2) + '</span>。'
            : '較前日多空比轉弱約 <span class="dn">' + dLs.toFixed(2) + '</span>。');
        } else if (prevLs > 1 && ls < 1) {
          parts.push('多空比由多轉空，廣度氛圍轉向謹慎。');
        } else if (prevLs < 1 && ls > 1) {
          parts.push('多空比由空轉多，廣度回溫跡象。');
        }
      }
      var prevNet = chrono[chrono.length - 2].net;
      if (net != null && prevNet != null && isFinite(prevNet) && Math.abs(net - prevNet) >= 200) {
        parts.push(net > prevNet
          ? '淨上漲家數較前日明顯增加。'
          : '淨上漲家數較前日明顯減少。');
      }
    }
    if (adv != null) {
      if (adv >= 0.70) parts.push('上漲占比逾七成，擴散偏強。');
      else if (adv <= 0.35) parts.push('上漲占比偏低，擴散偏弱。');
    }
    /* 漲跌停僅在極端時評論，避免只複述家數 */
    var lu = st.limitUp, ld = st.limitDown;
    if (lu != null && ld != null) {
      if (lu >= 40 && ld <= 2) parts.push('漲停潮偏熱，留意短線過熱。');
      else if (ld >= 10 && lu <= 5) parts.push('跌停家數偏多，防禦情緒升溫。');
    }
    if (!parts.length) parts.push('廣度序列載入中或資料不足，暫無趨勢評論。');
    return parts.slice(0, 3).join(' ');
  }

  function renderDonut(ov, st) {
    st = st || (ov && ov.strip) || {};
    var up = st.up || 0, dn = st.down || 0, flat = st.flat || st.unchanged || 0;
    var sum = up + dn + flat;
    var pu = sum ? 100 * up / sum : 0;
    var pf = sum ? 100 * (up + flat) / sum : pu;
    var ls = ov && ov.lsRatio != null ? ov.lsRatio : st.lsRatio;
    var advTxt = st.advRatio != null ? (st.advRatio * 100).toFixed(1) + '%' : '—';
    var net = st.net;
    if (net == null && (st.up != null || st.down != null)) net = (st.up || 0) - (st.down || 0);
    var netTxt = net != null ? ((net >= 0 ? '+' : '') + net) : '—';
    return '<div class="pl-sec"><h4>市場廣度 <a data-go="breadth">詳情 →</a></h4>' +
      '<div class="pl-donut-wrap">' +
        '<div class="pl-donut" style="--pl-u:' + pu.toFixed(2) + '%;--pl-uf:' + pf.toFixed(2) + '%">' +
          '<div class="mid"><b>' + (ls != null ? Number(ls).toFixed(2) : '—') + '</b><span>多空比</span></div></div>' +
        '<div class="pl-leg">' +
          '<div><i style="background:var(--red)"></i>上漲 <b class="up">' + fmt(up) + '</b></div>' +
          '<div><i style="background:#334155"></i>平盤 <b class="flat">' + fmt(flat) + '</b></div>' +
          '<div><i style="background:var(--green)"></i>下跌 <b class="dn">' + fmt(dn) + '</b></div>' +
          '<div style="margin-top:3px;color:var(--tlo)">淨 <b class="' + tw(net) + '">' + netTxt +
            '</b> · 上漲比 ' + advTxt + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="pl-bd-trend" id="pl-bd-trend">' +
        '<div class="lab"><span>多空比趨勢</span><span id="pl-bd-trend-meta">載入…</span></div>' +
        '<div class="chart" id="pl-bd-chart"><div class="pl-note" style="padding:6px 0">載入廣度序列…</div></div>' +
      '</div>' +
      '<div class="pl-bd-cmt" id="pl-bd-cmt">分析廣度變化中…</div></div>';
  }

  function fillBreadthTrend(ov) {
    var st = Object.assign({}, (ov && ov.strip) || {});
    if (ov && ov.lsRatio != null && st.lsRatio == null) st.lsRatio = ov.lsRatio;
    jget('/pulse/history?kind=breadth&n=20').then(function (h) {
      var V = window.Viz;
      var chart = $('pl-bd-chart');
      var meta = $('pl-bd-trend-meta');
      var cmt = $('pl-bd-cmt');
      var rows = (h && h.rows) || [];
      /* 當日 strip 缺欄時，用歷史最新一筆對齊評論／meta（與詳情頁同源） */
      if (rows.length && (st.up == null || st.lsRatio == null || st.advRatio == null)) {
        var latest = rows[0];
        ['up', 'down', 'flat', 'limitUp', 'limitDown', 'advRatio', 'net', 'lsRatio'].forEach(function (k) {
          if (st[k] == null && latest[k] != null) st[k] = latest[k];
        });
      }
      var chrono = rows.slice().reverse();
      var lsSeries = chrono.map(function (r) {
        if (r.lsRatio != null && isFinite(r.lsRatio)) return Number(r.lsRatio);
        if (r.up != null && r.down) return r.up / Math.max(r.down, 1);
        return null;
      });
      var usable = lsSeries.filter(function (v) { return v != null && isFinite(v); });
      if (chart) {
        if (V && usable.length >= 2) {
          var last = usable[usable.length - 1];
          var col = last >= 1 ? 'var(--red)' : 'var(--green)';
          chart.innerHTML = V.sparkLine(usable, { color: col, h: 48, w: 280 });
        } else if (usable.length) {
          chart.innerHTML = V ? V.sparkBars(usable.map(function (v) { return v - 1; })) :
            '<div class="pl-note">序列不足</div>';
        } else {
          chart.innerHTML = '<div class="pl-note">尚無本機廣度歷史 — 可按同步資料預抓</div>';
        }
      }
      if (meta) {
        meta.textContent = (rows.length ? ('近 ' + rows.length + ' 日') : '無序列') +
          (st.lsRatio != null ? ' · 今 ' + Number(st.lsRatio).toFixed(2) : '');
      }
      if (cmt) cmt.innerHTML = buildBreadthComment(st, rows);
    });
  }

  function sectorsFromPack(ov) {
    if (sectorMkt === 'US' && sectorCache.US) return sectorCache.US;
    if (sectorMkt === 'TW' && sectorCache.TW) return sectorCache.TW;
    return (ov && ov.sectorsRanked) || [];
  }

  function renderSectors(ov) {
    var list = sectorsFromPack(ov).slice();
    list.sort(function (a, b) { return Math.abs(b.changePct || 0) - Math.abs(a.changePct || 0); });
    var maxAbs = 1;
    list.forEach(function (s) { maxAbs = Math.max(maxAbs, Math.abs(s.changePct || 0)); });
    var usOn = sectorMkt === 'US';
    var html = '<div class="pl-sec" id="pl-sectors"><h4>產業輪動' +
      '<span class="pl-sec-tog">' +
        '<button type="button" data-sec-mkt="TW" class="' + (usOn ? '' : 'on') + '">TW</button>' +
        '<button type="button" data-sec-mkt="US" class="' + (usOn ? 'on' : '') + '">US</button>' +
      '</span>' +
      ' <a data-go="heat">熱力 →</a></h4><div class="pl-fill" id="pl-sectors-body">';
    if (!list.length) {
      return html + '<div class="pl-note">' + (usOn ? '美股產業載入中…' : '類股資料暫缺 — 開啟熱力可預熱') +
        '</div></div></div>';
    }
    list.slice(0, 10).forEach(function (s) {
      var w = Math.max(4, Math.round(Math.abs(s.changePct) / maxAbs * 100));
      /* 台股紅漲綠跌；美股綠漲紅跌 */
      var upCol = usOn ? 'var(--green)' : 'var(--red)';
      var dnCol = usOn ? 'var(--red)' : 'var(--green)';
      var col = (s.changePct || 0) >= 0 ? upCol : dnCol;
      /* US：綠漲紅跌 → 借用 .dn/.up 顏色類別對調 */
      var pcCls = usOn
        ? ((s.changePct || 0) > 0 ? 'dn' : (s.changePct || 0) < 0 ? 'up' : 'flat')
        : tw(s.changePct);
      html += '<div class="pl-sbar"><div class="nm" title="' + esc(s.name) + '">' + esc(s.name) + '</div>' +
        '<div class="track"><i style="width:' + w + '%;background:' + col + '"></i></div>' +
        '<div class="pc ' + pcCls + '">' + pct(s.changePct) + '</div></div>';
    });
    return html + '</div></div>';
  }

  function loadSectorsMkt(mkt) {
    sectorMkt = mkt || 'TW';
    if (sectorCache[sectorMkt] && lastPack) {
      var body = $('pl-body');
      if (body && lastPack) render(lastPack);
      return;
    }
    jget('/sectors?mkt=' + encodeURIComponent(sectorMkt)).then(function (d) {
      var rows = (d && d.sectors) || [];
      sectorCache[sectorMkt] = rows.map(function (s) {
        return { name: s.name, changePct: s.changePct, close: s.close, symbol: s.symbol };
      });
      if (lastPack) render(lastPack);
    });
  }

  function renderMovers(movers, side) {
    var V = window.Viz;
    var raw = (movers && movers[side]) || [];
    var list = raw.slice();
    var title, empty;
    if (side === 'gainers') {
      var lim = raw.filter(function (r) { return r.changePct != null && r.changePct >= 9.5; });
      list = (lim.length ? lim : raw).slice(0, 10);
      title = '漲停監控';
      empty = '尚無接近／觸及漲停標的';
    } else {
      var bad = raw.filter(function (r) { return r.changePct != null && r.changePct <= -7; });
      list = (bad.length ? bad : raw).slice(0, 10);
      title = '跌幅異常';
      empty = '尚無大幅下跌標的';
    }
    var maxAbs = 0;
    list.forEach(function (r) {
      if (r.changePct != null && isFinite(r.changePct)) maxAbs = Math.max(maxAbs, Math.abs(r.changePct));
    });
    var html = '<div class="pl-sec"><h4>' + title +
      (movers && movers.date ? ' <span style="color:var(--tlo);font-weight:600">' + movers.date + '</span>' : '') +
      ' <a data-go="afterhours">盤後 →</a></h4><ul class="pl-list">';
    if (!list.length) return html + '<li style="cursor:default;color:var(--tlo)">' + empty + '</li></ul></div>';
    list.forEach(function (r) {
      var limChip = V ? V.limitChip(r.changePct) : '';
      var bar = V ? V.rowBar(r.changePct, maxAbs) : '';
      html += '<li data-code="' + esc(r.code || '') + '"><span class="nm"><span class="cd">' +
        esc(r.code || '') + '</span>' + esc(r.name || '') + '</span><span class="' + tw(r.changePct) + '">' +
        pct(r.changePct) + limChip + bar + '</span></li>';
    });
    return html + '</ul></div>';
  }

  function globalImpactTone(items) {
    var n = 0, sum = 0;
    items.forEach(function (x) {
      if (x && x.changePct != null && isFinite(x.changePct) && x.symbol !== '^VIX') {
        n += 1; sum += x.changePct;
      }
    });
    if (!n) return '資料彙整中';
    var avg = sum / n;
    if (avg >= 0.6) return '偏多';
    if (avg <= -0.6) return '偏空';
    return '中性';
  }

  function renderGlobal(p) {
    var g = p.global || [];
    var items = g.slice();
    if (p.us10y && p.us10y.value != null) {
      items.push({
        symbol: 'US10Y', name: '美10年債',
        price: p.us10y.value, changePct: null, unit: '%'
      });
    }
    var prefer = [
      '^DJI', '^GSPC', '^IXIC', '^SOX', '^N225', '^KS11',
      '^VIX', 'TWD=X', 'DX-Y.NYB', 'DX=F', 'US10Y', 'CL=F'
    ];
    items.sort(function (a, b) {
      var ia = prefer.indexOf(a.symbol); var ib = prefer.indexOf(b.symbol);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    var tone = globalImpactTone(items);
    var html = '<div class="pl-sec"><h4>全球影響' +
      ' <span style="color:var(--cyan);font-weight:700;font-size:9px;margin-left:4px">' + tone + '</span>' +
      ' <a data-go="international">國際 →</a></h4><div class="pl-global">';
    if (!items.length) html += '<div class="pl-note">國際報價載入中…</div>';
    items.slice(0, 10).forEach(function (x) {
      var dig = (x.unit === '%' || x.symbol === 'US10Y' || x.symbol === '^VIX' || x.symbol === 'TWD=X') ? 2
        : (x.price > 1000 ? 0 : 2);
      html += '<div class="g"><div class="k">' + esc(x.name || x.symbol) + '</div><div class="v">' +
        fmt(x.price, dig) +
        (x.unit === '%' || x.symbol === 'US10Y' ? '%' : '') + '</div>' +
        '<div class="s ' + tw(x.changePct) + '" style="font-size:9px;font-weight:700;margin-top:1px">' +
        (x.changePct != null ? pct(x.changePct) : '—') + '</div></div>';
    });
    return html + '</div></div>';
  }

  function renderEco(p) {
    var eco = p.economy || [];
    var html = '<div class="pl-sec"><h4>總經數據</h4>';
    if (!eco.length) return html + '<div class="pl-note">FRED／主計總處序列尚未就緒</div></div>';
    eco.forEach(function (e) {
      html += '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:11px">' +
        '<span style="color:var(--tlo)">' + esc(e.label || e.key) + '</span>' +
        '<span style="font-weight:700;color:var(--thi)">' + fmt(e.value, 2) + esc(e.unit || '') +
        '<span style="color:var(--tlo);font-weight:500;margin-left:6px;font-size:9px">' + esc(e.date || '') + '</span></span></div>';
    });
    return html + '</div>';
  }

  function renderFlash(p) {
    var flash = p.flash || [];
    var html = '<div class="pl-sec"><h4>市場快訊 <a data-go="news">中樞 →</a></h4><div class="pl-flash">';
    flash.slice(0, 12).forEach(function (f) {
      html += '<div class="row"' + (f.code ? ' data-code="' + esc(f.code) + '"' : '') + '>' +
        '<span class="t">' + esc(f.time || '') + '</span>' +
        '<span style="color:var(--cyan);font-size:9px;margin-right:4px">[' + esc(f.cat || '') + ']</span>' +
        esc(f.title || '') + '</div>';
    });
    return html + '</div></div>';
  }

  function watchTag(cp) {
    if (cp == null || !isFinite(cp)) return '';
    if (cp >= 3) return '<span class="pl-tag hot">機會</span>';
    if (cp <= -3) return '<span class="pl-tag cold">風險</span>';
    return '<span class="pl-tag ok">觀察</span>';
  }

  function renderWatch(quotes) {
    var wl = readWatchlist();
    var html = '<div class="pl-sec pl-wl"><h4>自選風險 <a data-go="watchlist">自選 →</a></h4>';
    if (!wl.length) return html + '<div class="pl-note">尚無自選 — 在圖表按 ＋ 加入</div></div>';
    html += '<table><tr><th>代號</th><th>現價</th><th>漲跌</th><th>標籤</th></tr>';
    wl.forEach(function (w) {
      var q = (quotes && (quotes[w.t] || quotes[w.t + '.TW'] || quotes[w.t + '.TWO'])) || {};
      var px = q.price != null ? q.price : w.price;
      var cp = q.changePct != null ? q.changePct : w.chg;
      html += '<tr data-code="' + esc(w.t) + '" data-mkt="' + esc(w.m || 'TW') + '"><td style="color:var(--gold);font-weight:700">' +
        esc(w.t) + (w.name ? ' <span style="color:var(--tlo);font-weight:500">' + esc(w.name) + '</span>' : '') +
        '</td><td>' + fmt(px, 2) + '</td><td class="' + tw(cp) + '">' + pct(cp) + '</td><td>' +
        watchTag(cp) + '</td></tr>';
    });
    return html + '</table></div>';
  }

  function renderFactors(p) {
    if (!showFactors) {
      return '<div id="pl-factors" class="pl-factors" hidden></div>';
    }
    var rows = p.marketRows || [];
    var nPos = (p.positiveFactors || []).length;
    var nRisk = (p.riskFactors || []).length;
    var nPend = (p.pendingFactors || []).length;
    var pillars = '<div class="pl-sec"><h4>體質支柱</h4>';
    if (!rows.length) pillars += '<div class="pl-note">支柱尚未就緒</div></div>';
    else {
      pillars += '<table class="pillars"><tr><th>項目</th><th>數值</th><th>評分</th></tr>';
      rows.forEach(function (r) {
        pillars += '<tr><td>' + (r.k || '') + '</td><td>' + (r.v || '—') + '</td><td>' +
          (r.score != null ? Number(r.score).toFixed(1) : '—') + '</td></tr>';
      });
      pillars += '</table></div>';
    }
    return '<div id="pl-factors" class="pl-factors">' +
      '<div class="pl-sec-title">因子帳本 · 正 ' + nPos + ' / 風險 ' + nRisk + ' / 未納入 ' + nPend + '</div>' +
      pillars +
      '<div class="pl-three">' +
        factorCol('正面因素', 'sc-pos', p.positiveFactors, '尚無') +
        factorCol('風險因素', 'sc-risk', p.riskFactors, '尚無') +
        factorCol('尚未納入', 'sc-pend', p.pendingFactors, '無') +
      '</div>' +
      '<div class="pl-note">分數來自 /pulse 因子帳本；點單列展開細節，頂列「因子帳本」可再次捲動至此。</div>' +
    '</div>';
  }

  function bind(body) {
    body.querySelectorAll('[data-go]').forEach(function (a) {
      a.onclick = function (e) {
        e.preventDefault();
        goRoute(a.getAttribute('data-go'), {
          sym: a.getAttribute('data-sym') || undefined,
          mkt: a.getAttribute('data-mkt') || undefined
        });
      };
    });
    body.querySelectorAll('[data-code]').forEach(function (el) {
      el.onclick = function () {
        openChart(el.getAttribute('data-code'), el.getAttribute('data-mkt') || 'TW');
      };
    });
    body.querySelectorAll('.pl-fac[data-fac]').forEach(function (el) {
      function toggle() { el.classList.toggle('open'); }
      el.onclick = toggle;
      el.onkeydown = function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
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
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (p.date ? ' · 廣度日 ' + p.date : '') +
        (p.updatedAt ? ' · ' + String(p.updatedAt).replace('T', ' ') : '');
    }
    var toneEl = $('pl-tone');
    if (toneEl) {
      var txf = p.txf || {};
      toneEl.className = 'pl-tone ' + tw(txf.changePct);
      toneEl.textContent = p.tone || '資料彙整中';
    }

    body.className = showFactors ? 'pl-expanded' : '';
    var extra = '';
    if (showFactors) {
      extra =
        '<div class="pl-extra">' +
          renderFactors(p) +
          '<div id="pl-hist" class="pl-loading" style="margin-top:6px">載入脈動歷史…</div>' +
        '</div>';
    }
    if (!sectorCache.TW && ov.sectorsRanked && ov.sectorsRanked.length) {
      sectorCache.TW = ov.sectorsRanked.slice();
    }

    body.innerHTML =
      renderStrip(ov, p) +
      '<div class="pl-dash">' +
        '<div class="pl-zone z-top">' +
          renderGauge(p) + renderOhlc(ov, p) + renderInst(ov) +
          renderDonut(ov, ov.strip) + renderSectors(ov) +
        '</div>' +
        '<div class="pl-zone z-bot">' +
          renderMovers(movers, 'gainers') + renderMovers(movers, 'losers') +
          renderGlobal(p) + renderFlash(p) + renderWatch(pack.wlQuotes) +
        '</div>' +
      '</div>' +
      extra;

    bind(body);
    body.querySelectorAll('[data-sec-mkt]').forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        loadSectorsMkt(b.getAttribute('data-sec-mkt'));
      };
    });
    if (sectorMkt === 'US' && !sectorCache.US) loadSectorsMkt('US');
    fillInstTrend(ov);
    fillBreadthTrend(ov);

    jget('/pulse/history?kind=index&n=20').then(function (h) {
      var box = $('pl-spark');
      if (!box) return;
      var rows = ((h && h.rows) || []).slice().reverse();
      var closes = rows.map(function (r) { return r.close; }).filter(function (c) {
        return c != null && isFinite(c);
      });
      box.innerHTML = sparkSvg(closes);
      if (closes.length) {
        var last = closes[closes.length - 1];
        box.title = '近 ' + closes.length + ' 日 · 最新收 ' + Number(last).toLocaleString('en-US', { maximumFractionDigits: 2 });
      }
    });

    jget('/pulse/history?kind=pulse&n=12').then(function (h) {
      var V = window.Viz;
      var box = $('pl-hist');
      if (!box) return;
      var rows = (h && h.rows) || [];
      if (!rows.length) {
        box.className = 'pl-note';
        box.textContent = '脈動歷史尚在累積 — 按頂列「同步資料」預抓指數／廣度／法人後，每日 /pulse 會自動 merge 分數。';
        return;
      }
      var chrono = rows.slice().reverse();
      var healthSeries = chrono.map(function (r) { return r.health; });
      var riskSeries = chrono.map(function (r) { return r.risk; });
      var sparks = '';
      if (V) {
        var hSpark = healthSeries.filter(function (v) { return v != null && isFinite(v); }).length >= 2
          ? V.sparkLine(healthSeries, { color: 'var(--gold)' }) : '';
        var rSpark = riskSeries.filter(function (v) { return v != null && isFinite(v); }).length >= 2
          ? V.sparkLine(riskSeries, { color: 'var(--cyan)' }) : '';
        if (hSpark || rSpark) {
          sparks = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">' +
            (hSpark ? '<div><div style="font-size:9px;color:var(--tlo)">動能</div>' + hSpark + '</div>' : '') +
            (rSpark ? '<div><div style="font-size:9px;color:var(--tlo)">風險</div>' + rSpark + '</div>' : '') +
            '</div>';
        }
      }
      var html = '<div class="pl-sec"><h4>市場脈搏歷史（本機庫）</h4>' + sparks +
        '<table style="width:100%;border-collapse:collapse;font-size:11px">' +
        '<tr style="color:var(--tlo)"><th style="text-align:left;padding:4px">日期</th>' +
        '<th style="padding:4px">動能</th><th style="padding:4px">風險</th><th style="padding:4px">總分</th>' +
        '<th style="padding:4px">可靠度</th><th style="padding:4px">狀態</th></tr>';
      rows.forEach(function (r) {
        html += '<tr><td style="padding:4px">' + esc(r.date) + '</td><td style="padding:4px;text-align:right">' +
          (r.health != null ? Number(r.health).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.risk != null ? Number(r.risk).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.total != null ? Number(r.total).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.completeness != null ? Number(r.completeness).toFixed(0) + '%' : '—') +
          '</td><td style="padding:4px">' + esc(r.statusText || '') + '</td></tr>';
      });
      box.className = '';
      box.innerHTML = html + '</table></div>';
    });
  }

  function warmCaches() {
    jget('/breadth');
    jget('/sectors?mkt=TW');
    jget('/marketflow');
    jget('/events');
  }

  function fetchWlQuotes() {
    var wl = readWatchlist();
    var tw = wl.filter(function (w) { return (w.m || 'TW') === 'TW'; }).map(function (w) { return w.t; });
    var us = wl.filter(function (w) { return w.m === 'US'; }).map(function (w) { return w.t; });
    var tasks = [];
    if (tw.length) tasks.push(jget('/twquote-batch?codes=' + encodeURIComponent(tw.join(','))));
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

  function refresh(force) {
    var body = ensureMount();
    if (!body) return;
    var btn = $('pl-refresh');
    if (btn) {
      btn.disabled = true;
      btn.textContent = '↻ 更新中…';
    }
    // stale-while-revalidate：已有畫面時不整頁清空（體感延遲主因）
    if (!lastPack) {
      body.innerHTML = '<div class="pl-loading">載入總覽儀表板…</div>';
    } else {
      var tone = $('pl-tone');
      if (tone && tone.textContent.indexOf('更新中') < 0) {
        tone.textContent = (tone.textContent || '—') + ' · 更新中…';
      }
    }
    // 手動刷新打穿聚合快取；子源（movers/global/macro）仍走各自 TTL，伺服器側預算 ≤8s
    var q = force ? '/pulse?refresh=1' : '/pulse';
    var t0 = Date.now();
    Promise.all([jget(q), fetchWlQuotes()]).then(function (arr) {
      var pulse = arr[0];
      if (!pulse || !pulse.ok) {
        if (!lastPack) {
          body.innerHTML = '<div class="pl-note">脈動載入失敗' +
            (pulse && pulse.error ? '：' + pulse.error : '（請重啟 server）') +
            ' <button type="button" class="pl-btn" id="pl-retry">重試</button></div>';
          var retry = $('pl-retry');
          if (retry) retry.onclick = function () { refresh(true); };
        }
        warmCaches();
        return;
      }
      render({ pulse: pulse, wlQuotes: arr[1] || {} });
      var ms = Date.now() - t0;
      var sub = $('pl-sub');
      if (sub) sub.textContent = (sub.textContent || '') + ' · ' + ms + 'ms';
      // 資料不完整：只暖快取 + soft 再取；禁止再打 refresh=1（舊邏輯會再卡 20s+）
      if ((pulse.dataCompleteness != null && pulse.dataCompleteness < 90) || !pulse.breadthOk) {
        warmCaches();
        setTimeout(function () {
          if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') {
            jget('/pulse').then(function (p2) {
              if (p2 && p2.ok) render({ pulse: p2, wlQuotes: arr[1] || {} });
            });
          }
        }, 1600);
      }
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
    }, 50000);
  }

  window.PulseV5 = {
    activate: activate,
    refresh: function () { refresh(true); },
    focusFactors: focusFactors,
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

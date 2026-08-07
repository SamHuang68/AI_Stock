/* ============================================================================
 * pulse_v5.js  —  Stock Terminal 5.0：TW Pulse Overview 儀表板
 * ----------------------------------------------------------------------------
 * 對齊 tw-pulse-terminal 參考圖（Overview）：
 *   頂列摘要｜脈動環＋OHLC＋法人｜廣度甜甜圈＋類股條＋漲跌榜｜
 *   國際列＋總經＋事件快訊＋自選｜因子帳本
 * 資料：GET /pulse（含 overview/movers/global/economy/flash）— 真實欄位，禁止 mock。
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var lastPack = null;
  var showFactors = true;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    if ($('pulse-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'pulse-v5-css';
    s.textContent =
      /* 面板必須受 shell-main 寬度約束，避免頂列 6 卡撐破水平邊界 */
      '#view-pulse.sv-panel{max-width:100%;width:100%;min-width:0;padding:8px 10px 14px;box-sizing:border-box;overflow-x:hidden}' +
      '#pl-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:min(1480px,100%);margin:0 auto;min-width:0;box-sizing:border-box}' +
      '#pl-root .pl-head{display:flex;align-items:flex-end;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px;min-width:0}' +
      '#pl-root .pl-head > div:first-child{min-width:0;flex:1 1 180px}' +
      '#pl-root .pl-kicker{font-size:9px;color:var(--gold);letter-spacing:1.5px;margin-bottom:1px}' +
      '#pl-root .pl-title{font-family:\'Noto Serif TC\',serif;font-size:clamp(16px,1.8vw,20px);font-weight:700;color:var(--thi);line-height:1.15}' +
      '#pl-root .pl-sub{font-size:10px;color:var(--tlo);margin-top:1px;overflow-wrap:anywhere;line-height:1.35}' +
      '#pl-root .pl-tone{margin-top:2px;font-size:11px;font-weight:700}' +
      '#pl-root .pl-actions{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end;flex:0 1 auto;min-width:0;max-width:100%}' +
      '#pl-root .pl-btn{padding:4px 9px;border:1px solid var(--border);border-radius:5px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;flex:0 0 auto}' +
      '#pl-root .pl-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#pl-root .pl-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#pl-root .pl-btn.on{border-color:var(--gold-m);color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .up{color:var(--red)}#pl-root .dn{color:var(--green)}#pl-root .flat{color:var(--tlo)}' +
      /* top strip：高密度 auto-fit */
      '#pl-root .pl-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:5px;margin:4px 0 8px;min-width:0}' +
      '#pl-root .pl-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:6px;padding:6px 8px;min-height:0;min-width:0;overflow:hidden}' +
      '#pl-root .pl-strip .k{font-size:8px;color:var(--tlo);letter-spacing:.5px;margin-bottom:1px;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .v{font-size:clamp(11px,1.2vw,14px);font-weight:800;color:var(--thi);line-height:1.1;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .s{font-size:9px;margin-top:1px;font-weight:700;line-height:1.25;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .badge{display:inline-flex;align-items:center;gap:4px;font-size:9px;color:var(--cyan);max-width:100%;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .dot{width:5px;height:5px;border-radius:50%;background:var(--green);box-shadow:0 0 5px var(--green);flex-shrink:0}' +
      /* cards / sections */
      '#pl-root .pl-sec{background:var(--bg2);border:1px solid var(--border);border-radius:7px;padding:7px 9px}' +
      '#pl-root .pl-sec h4{margin:0 0 5px;font-size:10px;color:var(--gold);letter-spacing:.6px;display:flex;justify-content:space-between;align-items:center}' +
      '#pl-root .pl-sec h4 a{color:var(--cyan);cursor:pointer;font-size:9px;font-weight:600;text-decoration:none}' +
      '#pl-root .pl-sec h4 a:hover{color:var(--gold)}' +
      '#pl-root .pl-row{display:grid;gap:6px;margin-bottom:6px;min-width:0}' +
      '#pl-root .pl-row > .pl-sec{min-width:0}' +
      '#pl-root .pl-row.r3{grid-template-columns:repeat(3,minmax(0,1fr))}' +
      '#pl-root .pl-row.r4{grid-template-columns:repeat(4,minmax(0,1fr))}' +
      '#pl-root .pl-row.r3b{grid-template-columns:repeat(3,minmax(0,1fr))}' +
      '#pl-root .pl-note{font-size:8px;color:var(--tlo);line-height:1.35;margin-top:3px;' +
        'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}' +
      '#pl-root .pl-loading{font-size:10px;color:var(--tlo);padding:12px 0}' +
      /* gauge */
      '#pl-root .pl-gauge-wrap{display:flex;align-items:center;gap:10px;flex-wrap:wrap}' +
      '#pl-root .pl-gauge{width:88px;height:88px;border-radius:50%;' +
        'background:conic-gradient(var(--gold) var(--pl-deg,0%), rgba(245,197,24,.10) 0);' +
        'display:flex;align-items:center;justify-content:center;flex-shrink:0;position:relative}' +
      '#pl-root .pl-gauge::before{content:\'\';position:absolute;inset:7px;border-radius:50%;background:var(--bg2)}' +
      '#pl-root .pl-gauge-inner{position:relative;z-index:1;text-align:center}' +
      '#pl-root .pl-gauge-inner .big{font-size:22px;font-weight:800;color:var(--thi);line-height:1}' +
      '#pl-root .pl-gauge-inner .tag{display:inline-block;margin-top:2px;padding:1px 6px;border-radius:999px;' +
        'font-size:8px;font-weight:700;background:var(--gold-s);color:var(--gold);border:1px solid var(--gold-m)}' +
      '#pl-root .pl-mini{display:grid;grid-template-columns:1fr 1fr;gap:4px;flex:1;min-width:160px}' +
      '#pl-root .pl-mini .m{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:5px 7px}' +
      '#pl-root .pl-mini .m .k{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-mini .m .v{font-size:13px;font-weight:800;margin-top:1px;color:var(--thi);line-height:1.15}' +
      '#pl-root .pl-mini .m .l{font-size:8px;margin-top:0;font-weight:700}' +
      '#pl-root .pl-comp{height:4px;border-radius:2px;background:var(--bg3);overflow:hidden;margin-top:3px}' +
      '#pl-root .pl-comp > i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--gold))}' +
      /* OHLC */
      '#pl-root .pl-ohlc{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}' +
      '#pl-root .pl-ohlc .box{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:5px 6px}' +
      '#pl-root .pl-ohlc .box .k{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-ohlc .box .v{font-size:12px;font-weight:700;margin-top:1px;color:var(--thi)}' +
      '#pl-root .pl-trend-pair{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:4px}' +
      '#pl-root .pl-trend-pair .tp{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:5px 7px}' +
      '#pl-root .pl-trend-pair .tp .k{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-trend-pair .tp .v{font-size:13px;font-weight:800;margin-top:1px}' +
      '#pl-root .pl-spark{height:40px;margin:4px 0 2px;background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:2px 4px}' +
      '#pl-root .pl-spark svg{width:100%;height:100%;display:block}' +
      '#pl-root .pl-drivers{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px;font-size:9px}' +
      '#pl-root .pl-drivers .box{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:5px 6px}' +
      '#pl-root .pl-drivers .box .k{color:var(--tlo);margin-bottom:2px;font-size:8px}' +
      '#pl-root .pl-drivers .box li{margin:1px 0;color:var(--text);list-style:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      /* institutional：四欄一眼掃完 */
      '#pl-root .pl-inst4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px}' +
      '#pl-root .pl-inst4 .c{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:5px 6px;text-align:center}' +
      '#pl-root .pl-inst4 .c .k{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-inst4 .c .v{font-size:12px;font-weight:800;margin-top:1px;line-height:1.15}' +
      '#pl-root .pl-chip{display:inline-block;margin:1px 3px 0 0;padding:0 5px;border-radius:999px;border:1px solid var(--border);font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-tag{display:inline-block;margin-left:3px;padding:0 4px;border-radius:3px;font-size:8px;font-weight:700}' +
      '#pl-root .pl-tag.hot{background:var(--gold-s);color:var(--gold);border:1px solid var(--gold-m)}' +
      '#pl-root .pl-tag.cold{background:rgba(56,189,248,.08);color:var(--cyan);border:1px solid rgba(56,189,248,.25)}' +
      '#pl-root .pl-tag.ok{background:rgba(34,197,94,.08);color:var(--green);border:1px solid rgba(34,197,94,.25)}' +
      /* donut */
      '#pl-root .pl-donut-wrap{display:flex;align-items:center;gap:10px;flex-wrap:wrap}' +
      '#pl-root .pl-donut{width:84px;height:84px;border-radius:50%;flex-shrink:0;position:relative;' +
        'background:conic-gradient(var(--red) 0 var(--pl-u,0%), #334155 var(--pl-u,0%) var(--pl-uf,0%), var(--green) var(--pl-uf,0%) 100%)}' +
      '#pl-root .pl-donut::before{content:\'\';position:absolute;inset:20px;border-radius:50%;background:var(--bg2)}' +
      '#pl-root .pl-donut .mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:1}' +
      '#pl-root .pl-donut .mid b{font-size:14px;color:var(--thi)}' +
      '#pl-root .pl-donut .mid span{font-size:8px;color:var(--tlo)}' +
      '#pl-root .pl-leg{font-size:10px;line-height:1.45}' +
      '#pl-root .pl-leg i{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:4px}' +
      /* sector bars */
      '#pl-root .pl-sbar{display:flex;align-items:center;gap:5px;margin:2px 0;font-size:10px}' +
      '#pl-root .pl-sbar .nm{width:64px;flex-shrink:0;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-sbar .track{flex:1;height:5px;background:var(--bg);border-radius:3px;overflow:hidden;position:relative}' +
      '#pl-root .pl-sbar .track > i{display:block;height:100%;border-radius:3px}' +
      '#pl-root .pl-sbar .pc{width:48px;text-align:right;font-weight:700;flex-shrink:0;font-size:10px}' +
      /* lists */
      '#pl-root .pl-list{list-style:none;margin:0;padding:0;max-height:200px;overflow:auto}' +
      '#pl-root .pl-list li{display:flex;justify-content:space-between;gap:6px;padding:3px 2px;border-bottom:1px solid var(--border);cursor:pointer;font-size:10px}' +
      '#pl-root .pl-list li:hover{background:var(--bg3)}' +
      '#pl-root .pl-list .nm{color:var(--thi);font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-list .cd{color:var(--tlo);font-size:9px;margin-right:4px}' +
      /* global / eco / flash / wl */
      '#pl-root .pl-global{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:4px;min-width:0}' +
      '#pl-root .pl-global .g{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:5px 7px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-global .g .k{font-size:8px;color:var(--tlo);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-global .g .v{font-size:11px;font-weight:800;margin-top:1px;color:var(--thi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-flash{max-height:140px;overflow:auto;font-size:10px}' +
      '#pl-root .pl-flash .row{padding:3px 0;border-bottom:1px solid var(--border);cursor:pointer}' +
      '#pl-root .pl-flash .t{color:var(--tlo);font-size:8px;margin-right:4px}' +
      '#pl-root .pl-wl table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#pl-root .pl-wl th,#pl-root .pl-wl td{padding:3px 3px;border-bottom:1px solid var(--border);text-align:right}' +
      '#pl-root .pl-wl th:first-child,#pl-root .pl-wl td:first-child{text-align:left}' +
      '#pl-root .pl-wl th{color:var(--tlo)}' +
      '#pl-root .pl-wl tr{cursor:pointer}#pl-root .pl-wl tr:hover{background:var(--bg3)}' +
      /* factors */
      '#pl-root .pl-factors{margin-top:6px;scroll-margin-top:8px;padding:1px;border-radius:8px;transition:box-shadow .35s,background .35s}' +
      '#pl-root .pl-factors.flash{box-shadow:0 0 0 1px var(--gold-m),0 0 16px rgba(245,197,24,.15);background:rgba(245,197,24,.04)}' +
      '#pl-root .pl-factors > .pl-sec-title{font-family:\'Noto Serif TC\',serif;font-size:13px;font-weight:700;color:var(--thi);margin:0 0 6px;letter-spacing:.5px}' +
      '#pl-root .pl-three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;margin-top:5px}' +
      '#pl-root .pl-fac{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:5px 6px;margin-bottom:3px;cursor:pointer;transition:border-color .14s,background .14s}' +
      '#pl-root .pl-fac:hover{border-color:var(--gold-m);background:var(--bg3)}' +
      '#pl-root .pl-fac.open{border-color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .pl-fac .hd{display:flex;justify-content:space-between;gap:6px;font-size:10px;font-weight:700;color:var(--thi)}' +
      '#pl-root .pl-fac .ds{font-size:9px;color:var(--tlo);line-height:1.35;margin-top:1px}' +
      '#pl-root .pl-fac .more{display:none;margin-top:4px;padding-top:4px;border-top:1px dashed var(--border);font-size:9px;color:var(--text);line-height:1.4}' +
      '#pl-root .pl-fac.open .more{display:block}' +
      '#pl-root .pl-fac .sc-pos{color:var(--red)}#pl-root .pl-fac .sc-risk{color:var(--cyan)}#pl-root .pl-fac .sc-pend{color:var(--tlo)}' +
      '#pl-root .pl-col{max-height:280px;overflow:auto}' +
      '#pl-root table.pillars{width:100%;border-collapse:collapse;font-size:10px}' +
      '#pl-root table.pillars th,#pl-root table.pillars td{padding:3px 4px;border-bottom:1px solid var(--border);text-align:right}' +
      '#pl-root table.pillars th:first-child,#pl-root table.pillars td:first-child{text-align:left}' +
      '#pl-root table.pillars th{color:var(--tlo)}' +
      '@media (max-width:1360px){' +
        '#pl-root .pl-row.r3,#pl-root .pl-row.r4,#pl-root .pl-row.r3b{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#pl-root .pl-three{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#pl-root .pl-inst4{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#pl-root .pl-ohlc{grid-template-columns:repeat(2,1fr)}' +
      '}' +
      '@media (max-width:820px){' +
        '#view-pulse.sv-panel{padding:8px 8px 12px}' +
        '#pl-root .pl-row.r3,#pl-root .pl-row.r4,#pl-root .pl-row.r3b,' +
        '#pl-root .pl-three,#pl-root .pl-inst4{grid-template-columns:1fr}' +
        '#pl-root .pl-actions{justify-content:flex-start}' +
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
  function goRoute(id) {
    if (window.ShellV5) window.ShellV5.go(id);
  }
  function openChart(code, mkt) {
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
          '<div class="pl-head"><div>' +
            '<div class="pl-kicker">TW PULSE · MARKET INTELLIGENCE</div>' +
            '<div class="pl-title">市場總覽</div>' +
            '<div class="pl-sub" id="pl-sub">官方資料混成 · 因子可覆核</div>' +
            '<div class="pl-tone" id="pl-tone">—</div>' +
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
        b.onclick = function () { goRoute(b.getAttribute('data-go')); };
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
    var adv = s.advRatio;
    var tone = breadthToneLabel(adv, s.lsRatio);
    var toneKind = (tone.indexOf('偏多') >= 0 || tone.indexOf('極度偏多') >= 0) ? 'buy'
      : (tone.indexOf('偏空') >= 0 || tone.indexOf('極度偏空') >= 0) ? 'sell' : 'mid';
    var udfViz = V ? V.segBar(s.up, s.flat, s.down) : '';
    var turnViz = (V && s.turnoverYi != null) ? V.refMeter(s.turnoverYi, [8000, 12000]) : '';
    var advViz = V ? (V.scoreMeter((adv || 0) * 100) + V.chip(tone, toneKind)) : '';
    var compViz = (V && p.dataCompleteness != null) ? V.scoreMeter(p.dataCompleteness) : '';
    return '<div class="pl-strip">' +
      '<div class="cell"><div class="k">加權指數 TAIEX</div><div class="v">' + fmt(t00.price, 2) + '</div>' +
        '<div class="s ' + tw(t00.changePct) + '">' + pct(t00.changePct) + '</div></div>' +
      '<div class="cell"><div class="k">櫃買指數 OTC</div><div class="v">' + fmt(o00.price, 2) + '</div>' +
        '<div class="s ' + tw(o00.changePct) + '">' + pct(o00.changePct) + '</div></div>' +
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
        (V ? advViz : '<div class="s">' + tone + '</div>') + '</div>' +
      '<div class="cell"><div class="k">資料可靠度</div><div class="v" style="font-size:13px">' +
        '<span class="badge"><span class="dot"></span>' +
        (p.datasetsOk || 0) + '/' + (p.datasetsTotal || 0) + '</span></div>' +
        '<div class="s">' + (s.dataLabel || 'LOCAL') +
        (p.dataCompleteness != null ? ' · ' + Number(p.dataCompleteness).toFixed(0) + '%' : '') +
        '</div>' + compViz + '</div>' +
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
    return '<div class="pl-sec"><h4>市場脈搏與組成 <a data-go="pulse">因子 →</a></h4><div class="pl-gauge-wrap">' +
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
      (p.summary ? '<div class="pl-note">' + esc(p.summary) + '</div>' : '') +
      '</div>';
  }

  function renderOhlc(ov) {
    var o = (ov && ov.ohlc) || {};
    return '<div class="pl-sec"><h4>市場盤勢走勢 <a data-go="trends">指數 →</a></h4>' +
      '<div class="pl-trend-pair">' +
        '<div class="tp"><div class="k">加權今日漲幅</div><div class="v ' + tw(o.changePct) + '">' + pct(o.changePct) + '</div>' +
          '<div class="pl-note" style="margin:2px 0 0">現價 ' + fmt(o.price, 2) + '</div></div>' +
        '<div class="tp"><div class="k">櫃買今日漲幅</div><div class="v ' + tw(o.otcChangePct) + '">' + pct(o.otcChangePct) + '</div>' +
          '<div class="pl-note" style="margin:2px 0 0">現價 ' + fmt(o.otcPrice, 2) + '</div></div>' +
      '</div>' +
      '<div class="pl-spark" id="pl-spark"><div class="pl-note" style="padding:8px">載入近 20 日走勢…</div></div>' +
      '<div class="pl-ohlc">' +
      '<div class="box"><div class="k">開盤</div><div class="v">' + fmt(o.open, 2) + '</div></div>' +
      '<div class="box"><div class="k">最高</div><div class="v">' + fmt(o.high, 2) + '</div></div>' +
      '<div class="box"><div class="k">最低</div><div class="v">' + fmt(o.low, 2) + '</div></div>' +
      '<div class="box"><div class="k">昨收</div><div class="v">' + fmt(o.prevClose, 2) + '</div></div>' +
      '</div><div class="pl-note">近 20 日收盤折線來自本機庫／同步資料；缺列不繪假曲線</div></div>';
  }

  function renderInst(ov) {
    var V = window.Viz;
    var i = (ov && ov.institutional) || {};
    var divNote = '';
    if (i.foreign != null && i.dealer != null) {
      if (i.foreign > 0 && i.dealer < 0) divNote = '外資買超、自營賣超 — 常見避險／結構分歧。';
      else if (i.foreign < 0 && i.dealer > 0) divNote = '外資賣超、自營買超 — 留意承接是否續航。';
      else if ((i.totalYi != null ? i.totalYi : 0) > 0) divNote = '法人合計偏多，資金面偏進攻。';
      else if ((i.totalYi != null ? i.totalYi : 0) < 0) divNote = '法人合計偏空，資金面偏防衛。';
      else divNote = '法人方向分歧有限。';
    }
    var bars = V ? V.magBars([
      { label: '外資', v: i.foreign, fmt: V.fmtYiFromYuan },
      { label: '投信', v: i.trust, fmt: V.fmtYiFromYuan },
      { label: '自營', v: i.dealer, fmt: V.fmtYiFromYuan }
    ]) : '';
    var divChip = (V && i.foreign > 0 && i.dealer < 0) ? V.chip('結構分歧', 'warn') : '';
    return '<div class="pl-sec"><h4>法人分歧與資金 <a data-go="institutional">籌碼 →</a></h4><div class="pl-inst4">' +
      '<div class="c"><div class="k">外資</div><div class="v ' + tw(i.foreign) + '">' + moneyYi(i.foreign) + '</div></div>' +
      '<div class="c"><div class="k">投信</div><div class="v ' + tw(i.trust) + '">' + moneyYi(i.trust) + '</div></div>' +
      '<div class="c"><div class="k">自營</div><div class="v ' + tw(i.dealer) + '">' + moneyYi(i.dealer) + '</div></div>' +
      '<div class="c"><div class="k">合計</div><div class="v ' + tw(i.totalYi) + '">' +
        (i.totalYi != null ? ((i.totalYi >= 0 ? '+' : '') + Number(i.totalYi).toFixed(1) + ' 億') : '—') +
      '</div></div></div>' +
      bars + divChip +
      '<div class="pl-note">' + (divNote || '單位億元') +
      (i.date ? ' · 法人日 ' + i.date : '') + '</div></div>';
  }

  function renderDonut(ov, st) {
    st = st || (ov && ov.strip) || {};
    var up = st.up || 0, dn = st.down || 0, flat = st.flat || st.unchanged || 0;
    var sum = up + dn + flat;
    var pu = sum ? 100 * up / sum : 0;
    var pf = sum ? 100 * (up + flat) / sum : pu;
    var ls = ov && ov.lsRatio != null ? ov.lsRatio : st.lsRatio;
    var tone = breadthToneLabel(st.advRatio, ls);
    return '<div class="pl-sec"><h4>市場廣度與多空結構 <a data-go="breadth">詳情 →</a></h4><div class="pl-donut-wrap">' +
      '<div class="pl-donut" style="--pl-u:' + pu.toFixed(2) + '%;--pl-uf:' + pf.toFixed(2) + '%">' +
        '<div class="mid"><b>' + (ls != null ? Number(ls).toFixed(2) : '—') + '</b><span>多空比</span></div></div>' +
      '<div class="pl-leg">' +
        '<div><i style="background:var(--red)"></i>上漲 <b class="up">' + fmt(up) + '</b></div>' +
        '<div><i style="background:#334155"></i>平盤 <b class="flat">' + fmt(flat) + '</b></div>' +
        '<div><i style="background:var(--green)"></i>下跌 <b class="dn">' + fmt(dn) + '</b></div>' +
        '<div style="margin-top:6px;font-weight:700;color:var(--cyan)">' + tone + '</div>' +
        '<div style="margin-top:4px">' +
          '<span class="pl-chip">漲停 ' + (st.limitUp != null ? fmt(st.limitUp) : '—') + '</span>' +
          '<span class="pl-chip">跌停 ' + (st.limitDown != null ? fmt(st.limitDown) : '—') + '</span>' +
        '</div>' +
      '</div></div></div>';
  }

  function renderSectors(ov) {
    var list = (ov && ov.sectorsRanked) || [];
    var maxAbs = 1;
    list.forEach(function (s) { maxAbs = Math.max(maxAbs, Math.abs(s.changePct || 0)); });
    var html = '<div class="pl-sec"><h4>產業輪動 <a data-go="heat">熱力 →</a></h4>';
    if (!list.length) return html + '<div class="pl-note">類股資料暫缺 — 開啟熱力可預熱</div></div>';
    list.slice(0, 8).forEach(function (s) {
      var w = Math.max(4, Math.round(Math.abs(s.changePct) / maxAbs * 100));
      var col = s.changePct >= 0 ? 'var(--red)' : 'var(--green)';
      html += '<div class="pl-sbar"><div class="nm" title="' + esc(s.name) + '">' + esc(s.name) + '</div>' +
        '<div class="track"><i style="width:' + w + '%;background:' + col + '"></i></div>' +
        '<div class="pc ' + tw(s.changePct) + '">' + pct(s.changePct) + '</div></div>';
    });
    return html + '<div class="pl-note">條長＝相對漲跌幅強度（成交熱度未接入前之誠實代理）</div></div>';
  }

  function renderMovers(movers, side) {
    var V = window.Viz;
    var raw = (movers && movers[side]) || [];
    var list = raw.slice();
    var title, empty;
    if (side === 'gainers') {
      var lim = raw.filter(function (r) { return r.changePct != null && r.changePct >= 9.5; });
      list = (lim.length ? lim : raw).slice(0, 8);
      title = '漲停監控';
      empty = '尚無接近／觸及漲停標的';
    } else {
      var bad = raw.filter(function (r) { return r.changePct != null && r.changePct <= -7; });
      list = (bad.length ? bad : raw).slice(0, 8);
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
    var prefer = ['^DJI', '^GSPC', '^IXIC', '^VIX', 'TWD=X', 'DX-Y.NYB', 'DX=F', 'US10Y', 'CL=F'];
    items.sort(function (a, b) {
      var ia = prefer.indexOf(a.symbol); var ib = prefer.indexOf(b.symbol);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    var tone = globalImpactTone(items);
    var html = '<div class="pl-sec" style="grid-column:1/-1"><h4>全球市場對台股影響' +
      ' <span style="color:var(--cyan);font-weight:700;font-size:10px;margin-left:6px">' + tone + '</span></h4>' +
      '<div class="pl-global">';
    if (!items.length) html += '<div class="pl-note">國際報價載入中…</div>';
    items.slice(0, 7).forEach(function (x) {
      var dig = (x.unit === '%' || x.symbol === 'US10Y' || x.symbol === '^VIX' || x.symbol === 'TWD=X') ? 2
        : (x.price > 1000 ? 0 : 2);
      html += '<div class="g"><div class="k">' + esc(x.name || x.symbol) + '</div><div class="v">' +
        fmt(x.price, dig) +
        (x.unit === '%' || x.symbol === 'US10Y' ? '%' : '') + '</div>' +
        '<div class="s ' + tw(x.changePct) + '" style="font-size:10px;font-weight:700;margin-top:2px">' +
        (x.changePct != null ? pct(x.changePct) : '—') + '</div></div>';
    });
    return html + '</div><div class="pl-note">含道瓊／S&P／那斯達克／VIX／美元台幣等真實報價；語氣為均幅粗分，非預測</div></div>';
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
    flash.slice(0, 10).forEach(function (f) {
      html += '<div class="row"' + (f.code ? ' data-code="' + esc(f.code) + '"' : '') + '>' +
        '<span class="t">' + esc(f.time || '') + '</span>' +
        '<span style="color:var(--cyan);font-size:9px;margin-right:4px">[' + esc(f.cat || '') + ']</span>' +
        esc(f.title || '') + '</div>';
    });
    return html + '</div><div class="pl-note">事件／除權息／營收時程（非 MOPS 全文爬蟲）</div></div>';
  }

  function watchTag(cp) {
    if (cp == null || !isFinite(cp)) return '';
    if (cp >= 3) return '<span class="pl-tag hot">機會</span>';
    if (cp <= -3) return '<span class="pl-tag cold">風險</span>';
    return '<span class="pl-tag ok">觀察</span>';
  }

  function renderWatch(quotes) {
    var wl = readWatchlist();
    var html = '<div class="pl-sec pl-wl"><h4>自選股風險與機會 <a data-go="watchlist">自選 →</a></h4>';
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
    return html + '</table><div class="pl-note">標籤依當日漲跌粗分（≥+3% 機會／≤−3% 風險），非投資建議</div></div>';
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
      a.onclick = function (e) { e.preventDefault(); goRoute(a.getAttribute('data-go')); };
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

    body.innerHTML =
      renderStrip(ov, p) +
      '<div class="pl-row r3">' + renderGauge(p) + renderOhlc(ov) + renderInst(ov) + '</div>' +
      '<div class="pl-row r4">' + renderDonut(ov, ov.strip) + renderSectors(ov) +
        renderMovers(movers, 'gainers') + renderMovers(movers, 'losers') + '</div>' +
      '<div class="pl-row r3b">' + renderEco(p) + renderFlash(p) + renderWatch(pack.wlQuotes) + '</div>' +
      renderGlobal(p) +
      renderFactors(p) +
      '<div id="pl-hist" class="pl-loading" style="margin-top:10px">載入脈動歷史…</div>' +
      '<div class="pl-note">Overview 對齊 tw-pulse-terminal 參考更新（真實端點／本機庫）；缺資料不灌假分數。⚠ 非投資建議。</div>';

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

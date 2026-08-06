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
      '#view-pulse.sv-panel{max-width:100%;width:100%;min-width:0;padding:14px 16px 28px;box-sizing:border-box;overflow-x:hidden}' +
      '#pl-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:min(1480px,100%);margin:0 auto;min-width:0;box-sizing:border-box}' +
      '#pl-root .pl-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px;min-width:0}' +
      '#pl-root .pl-head > div:first-child{min-width:0;flex:1 1 220px}' +
      '#pl-root .pl-kicker{font-size:10px;color:var(--gold);letter-spacing:2px;margin-bottom:4px}' +
      '#pl-root .pl-title{font-family:\'Noto Serif TC\',serif;font-size:clamp(20px,2.2vw,24px);font-weight:700;color:var(--thi)}' +
      '#pl-root .pl-sub{font-size:11px;color:var(--tlo);margin-top:3px;overflow-wrap:anywhere}' +
      '#pl-root .pl-tone{margin-top:5px;font-size:12px;font-weight:700}' +
      '#pl-root .pl-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;flex:0 1 auto;min-width:0;max-width:100%}' +
      '#pl-root .pl-btn{padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;flex:0 0 auto}' +
      '#pl-root .pl-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#pl-root .pl-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#pl-root .pl-btn.on{border-color:var(--gold-m);color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .up{color:var(--red)}#pl-root .dn{color:var(--green)}#pl-root .flat{color:var(--tlo)}' +
      /* top strip：auto-fit 隨內容區寬度換行，不再固定 6 欄撐破 */
      '#pl-root .pl-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:8px;margin:8px 0 12px;min-width:0}' +
      '#pl-root .pl-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:8px;padding:10px 12px;min-height:64px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-strip .k{font-size:9px;color:var(--tlo);letter-spacing:.8px;margin-bottom:4px;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .v{font-size:clamp(12px,1.35vw,16px);font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .s{font-size:10px;margin-top:3px;font-weight:700;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .badge{display:inline-flex;align-items:center;gap:5px;font-size:10px;color:var(--cyan);max-width:100%;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-strip .dot{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);flex-shrink:0}' +
      /* cards / sections */
      '#pl-root .pl-sec{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px 14px}' +
      '#pl-root .pl-sec h4{margin:0 0 8px;font-size:11px;color:var(--gold);letter-spacing:1px;display:flex;justify-content:space-between;align-items:center}' +
      '#pl-root .pl-sec h4 a{color:var(--cyan);cursor:pointer;font-size:10px;font-weight:600;text-decoration:none}' +
      '#pl-root .pl-sec h4 a:hover{color:var(--gold)}' +
      '#pl-root .pl-row{display:grid;gap:10px;margin-bottom:10px;min-width:0}' +
      '#pl-root .pl-row > .pl-sec{min-width:0}' +
      '#pl-root .pl-row.r3{grid-template-columns:repeat(3,minmax(0,1fr))}' +
      '#pl-root .pl-row.r4{grid-template-columns:repeat(4,minmax(0,1fr))}' +
      '#pl-root .pl-row.r3b{grid-template-columns:repeat(3,minmax(0,1fr))}' +
      '#pl-root .pl-note{font-size:9px;color:var(--tlo);line-height:1.65;margin-top:8px}' +
      '#pl-root .pl-loading{font-size:11px;color:var(--tlo);padding:20px 0}' +
      /* gauge */
      '#pl-root .pl-gauge-wrap{display:flex;align-items:center;gap:16px;flex-wrap:wrap}' +
      '#pl-root .pl-gauge{width:128px;height:128px;border-radius:50%;' +
        'background:conic-gradient(var(--gold) var(--pl-deg,0%), rgba(245,197,24,.10) 0);' +
        'display:flex;align-items:center;justify-content:center;flex-shrink:0;position:relative}' +
      '#pl-root .pl-gauge::before{content:\'\';position:absolute;inset:10px;border-radius:50%;background:var(--bg2)}' +
      '#pl-root .pl-gauge-inner{position:relative;z-index:1;text-align:center}' +
      '#pl-root .pl-gauge-inner .big{font-size:32px;font-weight:800;color:var(--thi);line-height:1}' +
      '#pl-root .pl-gauge-inner .tag{display:inline-block;margin-top:5px;padding:2px 8px;border-radius:999px;' +
        'font-size:10px;font-weight:700;background:var(--gold-s);color:var(--gold);border:1px solid var(--gold-m)}' +
      '#pl-root .pl-mini{display:grid;grid-template-columns:1fr 1fr;gap:7px;flex:1;min-width:180px}' +
      '#pl-root .pl-mini .m{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px 10px}' +
      '#pl-root .pl-mini .m .k{font-size:9px;color:var(--tlo)}' +
      '#pl-root .pl-mini .m .v{font-size:16px;font-weight:800;margin-top:3px;color:var(--thi)}' +
      '#pl-root .pl-mini .m .l{font-size:9px;margin-top:2px;font-weight:700}' +
      '#pl-root .pl-comp{height:7px;border-radius:4px;background:var(--bg3);overflow:hidden;margin-top:6px}' +
      '#pl-root .pl-comp > i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--gold))}' +
      /* OHLC */
      '#pl-root .pl-ohlc{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}' +
      '#pl-root .pl-ohlc .box{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px}' +
      '#pl-root .pl-ohlc .box .k{font-size:9px;color:var(--tlo)}' +
      '#pl-root .pl-ohlc .box .v{font-size:15px;font-weight:700;margin-top:4px;color:var(--thi)}' +
      /* institutional */
      '#pl-root .pl-inst4{display:grid;grid-template-columns:1fr 1fr;gap:8px}' +
      '#pl-root .pl-inst4 .c{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;text-align:center}' +
      '#pl-root .pl-inst4 .c .k{font-size:9px;color:var(--tlo)}' +
      '#pl-root .pl-inst4 .c .v{font-size:15px;font-weight:800;margin-top:4px}' +
      /* donut */
      '#pl-root .pl-donut-wrap{display:flex;align-items:center;gap:14px;flex-wrap:wrap}' +
      '#pl-root .pl-donut{width:120px;height:120px;border-radius:50%;flex-shrink:0;position:relative;' +
        'background:conic-gradient(var(--red) 0 var(--pl-u,0%), #334155 var(--pl-u,0%) var(--pl-uf,0%), var(--green) var(--pl-uf,0%) 100%)}' +
      '#pl-root .pl-donut::before{content:\'\';position:absolute;inset:28px;border-radius:50%;background:var(--bg2)}' +
      '#pl-root .pl-donut .mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:1}' +
      '#pl-root .pl-donut .mid b{font-size:18px;color:var(--thi)}' +
      '#pl-root .pl-donut .mid span{font-size:9px;color:var(--tlo)}' +
      '#pl-root .pl-leg{font-size:11px;line-height:1.7}' +
      '#pl-root .pl-leg i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px}' +
      /* sector bars */
      '#pl-root .pl-sbar{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:11px}' +
      '#pl-root .pl-sbar .nm{width:72px;flex-shrink:0;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-sbar .track{flex:1;height:8px;background:var(--bg);border-radius:4px;overflow:hidden;position:relative}' +
      '#pl-root .pl-sbar .track > i{display:block;height:100%;border-radius:4px}' +
      '#pl-root .pl-sbar .pc{width:58px;text-align:right;font-weight:700;flex-shrink:0}' +
      /* lists */
      '#pl-root .pl-list{list-style:none;margin:0;padding:0;max-height:260px;overflow:auto}' +
      '#pl-root .pl-list li{display:flex;justify-content:space-between;gap:8px;padding:6px 2px;border-bottom:1px solid var(--border);cursor:pointer;font-size:11px}' +
      '#pl-root .pl-list li:hover{background:var(--bg3)}' +
      '#pl-root .pl-list .nm{color:var(--thi);font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-list .cd{color:var(--tlo);font-size:10px;margin-right:6px}' +
      /* global / eco / flash / wl */
      '#pl-root .pl-global{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;min-width:0}' +
      '#pl-root .pl-global .g{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px 10px;min-width:0;overflow:hidden}' +
      '#pl-root .pl-global .g .k{font-size:9px;color:var(--tlo);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-global .g .v{font-size:13px;font-weight:800;margin-top:3px;color:var(--thi);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#pl-root .pl-flash{max-height:180px;overflow:auto;font-size:11px}' +
      '#pl-root .pl-flash .row{padding:6px 0;border-bottom:1px solid var(--border);cursor:pointer}' +
      '#pl-root .pl-flash .t{color:var(--tlo);font-size:9px;margin-right:6px}' +
      '#pl-root .pl-wl table{width:100%;border-collapse:collapse;font-size:11px}' +
      '#pl-root .pl-wl th,#pl-root .pl-wl td{padding:5px 4px;border-bottom:1px solid var(--border);text-align:right}' +
      '#pl-root .pl-wl th:first-child,#pl-root .pl-wl td:first-child{text-align:left}' +
      '#pl-root .pl-wl th{color:var(--tlo)}' +
      '#pl-root .pl-wl tr{cursor:pointer}#pl-root .pl-wl tr:hover{background:var(--bg3)}' +
      /* factors */
      '#pl-root .pl-factors{margin-top:12px;scroll-margin-top:12px;padding:2px;border-radius:12px;transition:box-shadow .35s,background .35s}' +
      '#pl-root .pl-factors.flash{box-shadow:0 0 0 1px var(--gold-m),0 0 24px rgba(245,197,24,.18);background:rgba(245,197,24,.04)}' +
      '#pl-root .pl-factors > .pl-sec-title{font-family:\'Noto Serif TC\',serif;font-size:16px;font-weight:700;color:var(--thi);margin:0 0 10px;letter-spacing:1px}' +
      '#pl-root .pl-three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:10px}' +
      '#pl-root .pl-fac{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:9px;margin-bottom:7px;cursor:pointer;transition:border-color .14s,background .14s}' +
      '#pl-root .pl-fac:hover{border-color:var(--gold-m);background:var(--bg3)}' +
      '#pl-root .pl-fac.open{border-color:var(--gold);background:var(--gold-s)}' +
      '#pl-root .pl-fac .hd{display:flex;justify-content:space-between;gap:8px;font-size:11px;font-weight:700;color:var(--thi)}' +
      '#pl-root .pl-fac .ds{font-size:10px;color:var(--tlo);line-height:1.5;margin-top:3px}' +
      '#pl-root .pl-fac .more{display:none;margin-top:6px;padding-top:6px;border-top:1px dashed var(--border);font-size:10px;color:var(--text);line-height:1.55}' +
      '#pl-root .pl-fac.open .more{display:block}' +
      '#pl-root .pl-fac .sc-pos{color:var(--red)}#pl-root .pl-fac .sc-risk{color:var(--cyan)}#pl-root .pl-fac .sc-pend{color:var(--tlo)}' +
      '#pl-root .pl-col{max-height:360px;overflow:auto}' +
      '#pl-root table.pillars{width:100%;border-collapse:collapse;font-size:11px}' +
      '#pl-root table.pillars th,#pl-root table.pillars td{padding:5px 6px;border-bottom:1px solid var(--border);text-align:right}' +
      '#pl-root table.pillars th:first-child,#pl-root table.pillars td:first-child{text-align:left}' +
      '#pl-root table.pillars th{color:var(--tlo)}' +
      /* 斷點以視窗為準；側欄約 58px，提早換行避免頂列被裁切 */
      '@media (max-width:1360px){' +
        '#pl-root .pl-row.r3,#pl-root .pl-row.r4,#pl-root .pl-row.r3b{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#pl-root .pl-three{grid-template-columns:repeat(2,minmax(0,1fr))}' +
      '}' +
      '@media (max-width:820px){' +
        '#view-pulse.sv-panel{padding:12px 10px 24px}' +
        '#pl-root .pl-row.r3,#pl-root .pl-row.r4,#pl-root .pl-row.r3b,' +
        '#pl-root .pl-three{grid-template-columns:1fr}' +
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

  function renderStrip(ov, p) {
    var s = (ov && ov.strip) || {};
    var t00 = s.t00 || {};
    var o00 = s.o00 || {};
    var adv = s.advRatio;
    var breadthTone = adv == null ? '—' : (adv >= 0.65 ? '偏多' : adv <= 0.35 ? '偏空' : '糾結');
    return '<div class="pl-strip">' +
      '<div class="cell"><div class="k">加權指數 TAIEX</div><div class="v">' + fmt(t00.price, 2) + '</div>' +
        '<div class="s ' + tw(t00.changePct) + '">' + pct(t00.changePct) + '</div></div>' +
      '<div class="cell"><div class="k">櫃買指數 OTC</div><div class="v">' + fmt(o00.price, 2) + '</div>' +
        '<div class="s ' + tw(o00.changePct) + '">' + pct(o00.changePct) + '</div></div>' +
      '<div class="cell"><div class="k">成交金額</div><div class="v">' +
        (s.turnoverYi != null ? Number(s.turnoverYi).toFixed(1) + ' 億' : '—') + '</div>' +
        '<div class="s ' + tw(s.turnoverChgPct) + '">' +
        (s.turnoverChgPct != null ? pct(s.turnoverChgPct) + ' vs 前日' : '—') + '</div></div>' +
      '<div class="cell"><div class="k">上漲 / 下跌 / 平盤</div><div class="v" style="font-size:14px">' +
        '<span class="up">' + fmt(s.up) + '</span> / <span class="dn">' + fmt(s.down) + '</span> / <span class="flat">' + fmt(s.flat) + '</span></div>' +
        '<div class="s">多空比 ' + (s.lsRatio != null ? s.lsRatio.toFixed(2) : '—') + '</div></div>' +
      '<div class="cell"><div class="k">市場廣度</div><div class="v">' +
        (adv != null ? (adv * 100).toFixed(1) + '%' : '—') + '</div>' +
        '<div class="s">' + breadthTone + '</div></div>' +
      '<div class="cell"><div class="k">資料狀態</div><div class="v" style="font-size:13px">' +
        '<span class="badge"><span class="dot"></span>' + (s.dataLabel || 'LOCAL') + '</span></div>' +
        '<div class="s">完整度 ' + (p.dataCompleteness != null ? Number(p.dataCompleteness).toFixed(0) + '%' : '—') +
        ' · ' + (p.datasetsOk || 0) + '/' + (p.datasetsTotal || 0) + '</div></div>' +
      '</div>';
  }

  function renderGauge(p) {
    var total = p.totalScore;
    var deg = (total != null ? Math.max(0, Math.min(100, total)) : 0) * 3.6;
    var comp = p.dataCompleteness != null ? p.dataCompleteness : 0;
    return '<div class="pl-sec"><h4>市場脈動總覽</h4><div class="pl-gauge-wrap">' +
      '<div class="pl-gauge" style="--pl-deg:' + deg.toFixed(1) + 'deg"><div class="pl-gauge-inner">' +
        '<div class="big">' + (total != null ? Number(total).toFixed(1) : '—') + '</div>' +
        '<div class="tag">' + (p.statusText || '—') + '</div></div></div>' +
      '<div class="pl-mini">' +
        '<div class="m"><div class="k">市場健康度</div><div class="v">' +
          (p.healthScore != null ? Number(p.healthScore).toFixed(1) : '—') + '</div>' +
          '<div class="l" style="color:var(--gold)">' + (p.healthLabel || '') + '</div></div>' +
        '<div class="m"><div class="k">市場風險度</div><div class="v">' +
          (p.riskScore != null ? Number(p.riskScore).toFixed(1) : '—') + '</div>' +
          '<div class="l" style="color:var(--cyan)">' + (p.riskLabel || '') + '</div></div>' +
        '<div class="m"><div class="k">正面因素</div><div class="v up">' +
          (p.positiveFactorScore != null ? Number(p.positiveFactorScore).toFixed(1) : '—') + '</div>' +
          '<div class="l" style="color:var(--tlo)">' + ((p.positiveFactors || []).length) + ' 項</div></div>' +
        '<div class="m"><div class="k">資料完整度</div><div class="v">' + Number(comp).toFixed(0) + '%</div>' +
          '<div class="pl-comp"><i style="width:' + comp + '%"></i></div></div>' +
      '</div></div>' +
      (p.summary ? '<div class="pl-note">' + p.summary + '</div>' : '') +
      '</div>';
  }

  function renderOhlc(ov) {
    var o = (ov && ov.ohlc) || {};
    return '<div class="pl-sec"><h4>加權指數 OHLC</h4><div class="pl-ohlc">' +
      '<div class="box"><div class="k">開盤</div><div class="v">' + fmt(o.open, 2) + '</div></div>' +
      '<div class="box"><div class="k">最高</div><div class="v">' + fmt(o.high, 2) + '</div></div>' +
      '<div class="box"><div class="k">最低</div><div class="v">' + fmt(o.low, 2) + '</div></div>' +
      '<div class="box"><div class="k">昨收</div><div class="v">' + fmt(o.prevClose, 2) + '</div></div>' +
      '</div><div class="pl-note">現價 ' + fmt(o.price, 2) + ' · ' + pct(o.changePct) +
      ' · 來源 MIS' + (o.source ? o.source.replace('+yahoo', '＋Yahoo') : '') + '</div></div>';
  }

  function renderInst(ov) {
    var i = (ov && ov.institutional) || {};
    return '<div class="pl-sec"><h4>三大法人 <a data-go="afterhours">盤後 →</a></h4><div class="pl-inst4">' +
      '<div class="c"><div class="k">外資</div><div class="v ' + tw(i.foreign) + '">' + moneyYi(i.foreign) + '</div></div>' +
      '<div class="c"><div class="k">投信</div><div class="v ' + tw(i.trust) + '">' + moneyYi(i.trust) + '</div></div>' +
      '<div class="c"><div class="k">自營</div><div class="v ' + tw(i.dealer) + '">' + moneyYi(i.dealer) + '</div></div>' +
      '<div class="c"><div class="k">合計</div><div class="v ' + tw(i.totalYi) + '">' +
        (i.totalYi != null ? ((i.totalYi >= 0 ? '+' : '') + Number(i.totalYi).toFixed(1) + ' 億') : '—') +
      '</div></div></div>' +
      '<div class="pl-note">單位億元' + (i.date ? ' · 法人日 ' + i.date : '') + '</div></div>';
  }

  function renderDonut(ov, st) {
    st = st || (ov && ov.strip) || {};
    var up = st.up || 0, dn = st.down || 0, flat = st.flat || st.unchanged || 0;
    var sum = up + dn + flat;
    var pu = sum ? 100 * up / sum : 0;
    var pf = sum ? 100 * (up + flat) / sum : pu;
    var ls = ov && ov.lsRatio != null ? ov.lsRatio : st.lsRatio;
    return '<div class="pl-sec"><h4>市場廣度 <a data-go="breadth">詳情 →</a></h4><div class="pl-donut-wrap">' +
      '<div class="pl-donut" style="--pl-u:' + pu.toFixed(2) + '%;--pl-uf:' + pf.toFixed(2) + '%">' +
        '<div class="mid"><b>' + (ls != null ? Number(ls).toFixed(2) : '—') + '</b><span>多空比</span></div></div>' +
      '<div class="pl-leg">' +
        '<div><i style="background:var(--red)"></i>上漲 <b class="up">' + fmt(up) + '</b></div>' +
        '<div><i style="background:#334155"></i>平盤 <b class="flat">' + fmt(flat) + '</b></div>' +
        '<div><i style="background:var(--green)"></i>下跌 <b class="dn">' + fmt(dn) + '</b></div>' +
        '<div style="margin-top:6px;color:var(--tlo)">上漲比 ' +
          (st.advRatio != null ? (st.advRatio * 100).toFixed(1) + '%' : '—') + '</div>' +
      '</div></div></div>';
  }

  function renderSectors(ov) {
    var list = (ov && ov.sectorsRanked) || [];
    var maxAbs = 1;
    list.forEach(function (s) { maxAbs = Math.max(maxAbs, Math.abs(s.changePct || 0)); });
    var html = '<div class="pl-sec"><h4>類股強弱 <a data-go="heat">熱力 →</a></h4>';
    if (!list.length) return html + '<div class="pl-note">類股資料暫缺 — 開啟熱力可預熱</div></div>';
    list.slice(0, 10).forEach(function (s) {
      var w = Math.max(4, Math.round(Math.abs(s.changePct) / maxAbs * 100));
      var col = s.changePct >= 0 ? 'var(--red)' : 'var(--green)';
      html += '<div class="pl-sbar"><div class="nm" title="' + s.name + '">' + s.name + '</div>' +
        '<div class="track"><i style="width:' + w + '%;background:' + col + '"></i></div>' +
        '<div class="pc ' + tw(s.changePct) + '">' + pct(s.changePct) + '</div></div>';
    });
    return html + '</div>';
  }

  function renderMovers(movers, side) {
    var list = (movers && movers[side]) || [];
    var title = side === 'gainers' ? '漲幅榜' : '跌幅榜';
    var html = '<div class="pl-sec"><h4>' + title +
      (movers && movers.date ? ' <span style="color:var(--tlo);font-weight:600">' + movers.date + '</span>' : '') +
      '</h4><ul class="pl-list">';
    if (!list.length) return html + '<li style="cursor:default;color:var(--tlo)">尚無日排行</li></ul></div>';
    list.forEach(function (r) {
      html += '<li data-code="' + (r.code || '') + '"><span class="nm"><span class="cd">' +
        (r.code || '') + '</span>' + (r.name || '') + '</span><span class="' + tw(r.changePct) + '">' +
        pct(r.changePct) + '</span></li>';
    });
    return html + '</ul></div>';
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
    var html = '<div class="pl-sec" style="grid-column:1/-1"><h4>國際市場</h4><div class="pl-global">';
    if (!items.length) html += '<div class="pl-note">國際報價載入中…</div>';
    items.slice(0, 6).forEach(function (x) {
      html += '<div class="g"><div class="k">' + (x.name || x.symbol) + '</div><div class="v">' +
        fmt(x.price, x.unit === '%' || (x.symbol === 'US10Y') ? 2 : (x.price > 1000 ? 0 : 2)) +
        (x.unit === '%' || x.symbol === 'US10Y' ? '%' : '') + '</div>' +
        '<div class="s ' + tw(x.changePct) + '" style="font-size:10px;font-weight:700;margin-top:2px">' +
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
        '<span style="color:var(--tlo)">' + (e.label || e.key) + '</span>' +
        '<span style="font-weight:700;color:var(--thi)">' + fmt(e.value, 2) + (e.unit || '') +
        '<span style="color:var(--tlo);font-weight:500;margin-left:6px;font-size:9px">' + (e.date || '') + '</span></span></div>';
    });
    return html + '</div>';
  }

  function renderFlash(p) {
    var flash = p.flash || [];
    var html = '<div class="pl-sec"><h4>事件快訊 <a data-go="news">中樞 →</a></h4><div class="pl-flash">';
    flash.slice(0, 10).forEach(function (f) {
      html += '<div class="row"' + (f.code ? ' data-code="' + f.code + '"' : '') + '>' +
        '<span class="t">' + (f.time || '') + '</span>' +
        '<span style="color:var(--cyan);font-size:9px;margin-right:4px">[' + (f.cat || '') + ']</span>' +
        (f.title || '') + '</div>';
    });
    return html + '</div><div class="pl-note">事件／結算中樞（非新聞爬蟲）</div></div>';
  }

  function renderWatch(quotes) {
    var wl = readWatchlist();
    var html = '<div class="pl-sec pl-wl"><h4>自選監控 <a data-go="chart">圖表 →</a></h4>';
    if (!wl.length) return html + '<div class="pl-note">尚無自選 — 在圖表按 ＋ 加入</div></div>';
    html += '<table><tr><th>代號</th><th>現價</th><th>漲跌</th></tr>';
    wl.forEach(function (w) {
      var q = (quotes && (quotes[w.t] || quotes[w.t + '.TW'] || quotes[w.t + '.TWO'])) || {};
      var px = q.price != null ? q.price : w.price;
      var cp = q.changePct != null ? q.changePct : w.chg;
      html += '<tr data-code="' + w.t + '" data-mkt="' + (w.m || 'TW') + '"><td style="color:var(--gold);font-weight:700">' +
        w.t + (w.name ? ' <span style="color:var(--tlo);font-weight:500">' + w.name + '</span>' : '') +
        '</td><td>' + fmt(px, 2) + '</td><td class="' + tw(cp) + '">' + pct(cp) + '</td></tr>';
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
      '<div class="pl-note">Overview 對齊 tw-pulse 參考儀表板；分數與排行均來自本機真實端點（/pulse · /movers · /pulse/history）。⚠ 非投資建議。</div>';

    bind(body);
    jget('/pulse/history?kind=pulse&n=12').then(function (h) {
      var box = $('pl-hist');
      if (!box) return;
      var rows = (h && h.rows) || [];
      if (!rows.length) {
        box.className = 'pl-note';
        box.textContent = '脈動歷史尚在累積 — 按頂列「同步資料」預抓指數／廣度／法人後，每日 /pulse 會自動 merge 分數。';
        return;
      }
      var html = '<div class="pl-sec"><h4>市場脈搏歷史（本機庫）</h4>' +
        '<table style="width:100%;border-collapse:collapse;font-size:11px">' +
        '<tr style="color:var(--tlo)"><th style="text-align:left;padding:4px">日期</th>' +
        '<th style="padding:4px">健康</th><th style="padding:4px">風險</th><th style="padding:4px">總分</th>' +
        '<th style="padding:4px">完整度</th><th style="padding:4px">狀態</th></tr>';
      rows.forEach(function (r) {
        html += '<tr><td style="padding:4px">' + r.date + '</td><td style="padding:4px;text-align:right">' +
          (r.health != null ? Number(r.health).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.risk != null ? Number(r.risk).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.total != null ? Number(r.total).toFixed(1) : '—') + '</td><td style="padding:4px;text-align:right">' +
          (r.completeness != null ? Number(r.completeness).toFixed(0) + '%' : '—') +
          '</td><td style="padding:4px">' + (r.statusText || '') + '</td></tr>';
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

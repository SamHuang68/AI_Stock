/* ============================================================================
 * shell_v5.js  —  Stock Terminal 5.0：側欄殼層 + 視圖路由
 * ----------------------------------------------------------------------------
 * S1：左側導覽軌 + 頂列同步；路由 = 同 HTML show/hide（預設圖表工作區）
 * S2：廣度路由改由 breadth_v5 掛載真實面板（stub:false）
 *
 * 鐵律：不破壞 #left / #pro-tools / symLoaded / Toolbar 既有行為。
 * ========================================================================== */
(function () {
  'use strict';

  var STORAGE_KEY = 'st5.shell.route';
  var VERSION = '5.0-S2';

  var ROUTES = [
    { id: 'chart',      label: '圖表',   hint: 'K 線工作區（預設）',     icon: '◈' },
    { id: 'breadth',    label: '廣度',   hint: '大盤廣度（漲跌家數）',   icon: '▣', stub: false },
    { id: 'news',       label: '快訊',   hint: '盤中快訊（後續）',       icon: '◉', stub: true },
    { id: 'afterhours', label: '盤後',   hint: '台股盤後整理（後續）',   icon: '◐', stub: true },
    { id: 'workspace',  label: '工具',   hint: '回到圖表並開啟指令盤',   icon: '⌘', action: 'cmd' }
  ];

  var state = { route: 'chart', built: false };

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    if ($('shell-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'shell-v5-css';
    s.textContent =
      '#shell-row{display:flex;flex:1;min-height:0;min-width:0}' +
      '#navrail{flex:0 0 52px;width:52px;background:linear-gradient(180deg,#0A1220 0%,#070D18 100%);' +
        'border-right:1px solid var(--border);display:flex;flex-direction:column;align-items:stretch;' +
        'padding:8px 0;gap:2px;z-index:40;flex-shrink:0}' +
      '#navrail .nr-brand{font-family:\'JetBrains Mono\',monospace;font-size:9px;font-weight:700;' +
        'color:var(--gold);letter-spacing:1px;text-align:center;padding:4px 0 10px;line-height:1.2;' +
        'border-bottom:1px solid var(--border);margin-bottom:6px;user-select:none}' +
      '#navrail .nr-brand small{display:block;color:var(--tlo);font-weight:600;letter-spacing:.5px;margin-top:2px;font-size:8px}' +
      '.nr-btn{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;' +
        'height:48px;margin:0 6px;padding:4px 2px;border:1px solid transparent;border-radius:8px;' +
        'background:transparent;color:var(--tlo);cursor:pointer;font-family:\'JetBrains Mono\',monospace;' +
        'font-size:9px;letter-spacing:.3px;transition:background .14s,color .14s,border-color .14s}' +
      '.nr-btn .nr-ico{font-size:14px;line-height:1;opacity:.85}' +
      '.nr-btn:hover{color:var(--thi);background:var(--bg3);border-color:var(--border)}' +
      '.nr-btn.on{color:var(--gold);background:var(--gold-s);border-color:var(--gold-m)}' +
      '.nr-btn.on .nr-ico{opacity:1}' +
      '.nr-spacer{flex:1}' +
      '.nr-foot{padding:8px 4px 2px;text-align:center;font-family:\'JetBrains Mono\',monospace;' +
        'font-size:8px;color:var(--tf);letter-spacing:.5px;border-top:1px solid var(--border);margin-top:6px}' +
      '#shell-main{display:flex;flex-direction:column;flex:1;min-width:0;min-height:0;position:relative}' +
      '#shell-views{display:none;flex:1;min-height:0;min-width:0;background:' +
        'radial-gradient(1200px 480px at 10% -10%,rgba(245,197,24,.06),transparent 55%),var(--bg);' +
        'overflow:auto}' +
      '#shell-views.show{display:flex;flex-direction:column}' +
      '#body.shell-hidden{display:none !important}' +
      '#wlbar.shell-hidden{display:none !important}' +
      '.sv-panel{display:none;flex:1;padding:28px 32px;max-width:720px}' +
      '.sv-panel.on{display:block}' +
      '.sv-mount{min-height:100%}' +
      '.sv-kicker{font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--gold);' +
        'letter-spacing:2px;margin-bottom:8px}' +
      '.sv-title{font-family:\'Noto Serif TC\',serif;font-size:28px;font-weight:700;color:var(--thi);' +
        'letter-spacing:1px;margin-bottom:10px}' +
      '.sv-desc{font-size:13px;line-height:1.75;color:var(--text);max-width:36em;margin-bottom:18px}' +
      '.sv-meta{font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--tlo);letter-spacing:.5px}' +
      '.sv-cta{display:inline-flex;align-items:center;gap:6px;margin-top:16px;padding:8px 14px;' +
        'background:var(--gold);color:#060A12;border:none;border-radius:6px;cursor:pointer;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:11px;font-weight:700;letter-spacing:1px}' +
      '.sv-cta:hover{background:#FBBF24}' +
      '#topbar .shell-sync{display:inline-flex;align-items:center;gap:6px;margin-left:4px;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--tlo);letter-spacing:.5px}' +
      '#topbar .shell-sync .ss-dot{width:6px;height:6px;border-radius:50%;background:var(--green);' +
        'box-shadow:0 0 6px var(--green);flex-shrink:0}' +
      '#topbar .shell-sync.warn .ss-dot{background:var(--orange);box-shadow:0 0 6px var(--orange)}' +
      '#topbar .shell-sync.err .ss-dot{background:var(--red);box-shadow:0 0 6px var(--red)}' +
      '#topbar .logo .shell-ver{margin-left:6px;font-size:9px;color:var(--tlo);letter-spacing:1px;font-weight:600}' +
      '@media (max-width:720px){' +
        '#navrail{flex-basis:44px;width:44px}' +
        '.nr-btn{height:44px;margin:0 4px;font-size:8px}' +
        '.sv-panel{padding:18px 16px}' +
        '.sv-title{font-size:22px}' +
      '}';
    document.head.appendChild(s);
  }

  function stubHTML(route) {
    return '' +
      '<div class="sv-kicker">STOCK TERMINAL · ' + VERSION + '</div>' +
      '<div class="sv-title">' + route.label + '</div>' +
      '<p class="sv-desc">' + route.hint +
        '。此頁為後續階段占位：路由與側欄已就緒，資料面板尚未接入，' +
        '不影響既有圖表工作區。</p>' +
      '<div class="sv-meta">route = ' + route.id + '</div>' +
      '<button type="button" class="sv-cta" data-shell-back>← 回到圖表工作區</button>';
  }

  function ensureStructure() {
    if (state.built) return true;
    var app = $('app');
    var body = $('body');
    if (!app || !body) return false;

    injectCSS();

    var logo = app.querySelector('#topbar .logo');
    if (logo && !logo.querySelector('.shell-ver')) {
      var ver = document.createElement('span');
      ver.className = 'shell-ver';
      ver.textContent = 'v' + VERSION;
      logo.appendChild(ver);
    } else if (logo) {
      var verEl = logo.querySelector('.shell-ver');
      if (verEl) verEl.textContent = 'v' + VERSION;
    }
    var topbar = $('topbar');
    if (topbar && !$('shell-sync')) {
      var sync = document.createElement('div');
      sync.id = 'shell-sync';
      sync.className = 'shell-sync';
      sync.innerHTML = '<span class="ss-dot" aria-hidden="true"></span><span id="shell-sync-txt">LOCAL</span>';
      var status = $('statusbar');
      if (status && status.parentElement === topbar) topbar.insertBefore(sync, status);
      else {
        var keybtn = $('keybtn');
        if (keybtn) topbar.insertBefore(sync, keybtn);
        else topbar.appendChild(sync);
      }
    }

    if (!$('shell-row')) {
      var row = document.createElement('div');
      row.id = 'shell-row';

      var rail = document.createElement('nav');
      rail.id = 'navrail';
      rail.setAttribute('aria-label', '主選單');
      rail.innerHTML =
        '<div class="nr-brand">ST<small>5.0</small></div>' +
        ROUTES.map(function (r) {
          return '<button type="button" class="nr-btn" data-route="' + r.id + '" title="' +
            r.hint.replace(/"/g, '') + '">' +
            '<span class="nr-ico" aria-hidden="true">' + r.icon + '</span>' +
            '<span>' + r.label + '</span></button>';
        }).join('') +
        '<div class="nr-spacer"></div>' +
        '<div class="nr-foot">S2</div>';

      var main = document.createElement('div');
      main.id = 'shell-main';

      var views = document.createElement('div');
      views.id = 'shell-views';
      ROUTES.forEach(function (r) {
        if (r.id === 'chart' || r.action) return;
        var p = document.createElement('section');
        p.className = 'sv-panel';
        p.id = 'view-' + r.id;
        p.dataset.route = r.id;
        if (r.stub) {
          p.innerHTML = stubHTML(r);
        } else {
          p.innerHTML = '<div class="sv-mount" id="mount-' + r.id + '"></div>';
        }
        views.appendChild(p);
      });

      body.parentElement.insertBefore(row, body);
      row.appendChild(rail);
      row.appendChild(main);
      main.appendChild(body);
      main.appendChild(views);

      rail.addEventListener('click', function (e) {
        var btn = e.target.closest('.nr-btn');
        if (!btn) return;
        go(btn.getAttribute('data-route'));
      });
      views.addEventListener('click', function (e) {
        if (e.target.closest('[data-shell-back]')) go('chart');
      });
    } else {
      // 熱重載：更新腳標 / 版本
      var foot = document.querySelector('#navrail .nr-foot');
      if (foot) foot.textContent = 'S2';
    }

    state.built = true;
    return true;
  }

  function setSync(mode, text) {
    var el = $('shell-sync');
    var txt = $('shell-sync-txt');
    if (!el || !txt) return;
    el.classList.remove('warn', 'err');
    if (mode === 'warn') el.classList.add('warn');
    if (mode === 'err') el.classList.add('err');
    txt.textContent = text || 'LOCAL';
  }

  function probeHealth() {
    if (typeof fetch !== 'function') return;
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    var t = setTimeout(function () { if (ctrl) ctrl.abort(); }, 2500);
    fetch('/health', { signal: ctrl && ctrl.signal })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function () { setSync('ok', 'SYNC OK'); })
      .catch(function () { setSync('warn', 'LOCAL'); })
      .finally(function () { clearTimeout(t); });
  }

  function emitRoute(id) {
    try {
      window.dispatchEvent(new CustomEvent('shell:route', { detail: { route: id } }));
    } catch (e) {}
    if (id === 'breadth' && window.BreadthV5 && typeof window.BreadthV5.activate === 'function') {
      try { window.BreadthV5.activate(); } catch (err) { console.warn('[shell-v5] breadth activate', err); }
    }
  }

  function applyRoute(id) {
    var route = null;
    for (var i = 0; i < ROUTES.length; i++) if (ROUTES[i].id === id) route = ROUTES[i];
    if (!route) route = ROUTES[0];

    if (route.action === 'cmd') {
      id = 'chart';
      route = ROUTES[0];
      setTimeout(function () {
        var b = $('btn-cmdp');
        if (b) b.click();
        else if (window.cmdPaletteOpen) window.cmdPaletteOpen();
      }, 0);
    }

    state.route = id;
    try { localStorage.setItem(STORAGE_KEY, id); } catch (e) {}

    var body = $('body');
    var wl = $('wlbar');
    var views = $('shell-views');
    var isChart = id === 'chart';

    if (body) body.classList.toggle('shell-hidden', !isChart);
    if (wl) wl.classList.toggle('shell-hidden', !isChart);
    if (views) views.classList.toggle('show', !isChart);

    var panels = document.querySelectorAll('.sv-panel');
    for (var p = 0; p < panels.length; p++) {
      panels[p].classList.toggle('on', panels[p].dataset.route === id);
    }

    var btns = document.querySelectorAll('#navrail .nr-btn');
    for (var b = 0; b < btns.length; b++) {
      var rid = btns[b].getAttribute('data-route');
      btns[b].classList.toggle('on', rid === id && rid !== 'workspace');
    }

    if (isChart) {
      setTimeout(function () {
        try { window.dispatchEvent(new Event('resize')); } catch (e) {}
      }, 30);
    }

    emitRoute(id);
  }

  function go(id) {
    if (!ensureStructure()) return;
    applyRoute(id || 'chart');
  }

  function boot() {
    if (!ensureStructure()) return setTimeout(boot, 120);
    var saved = 'chart';
    try { saved = localStorage.getItem(STORAGE_KEY) || 'chart'; } catch (e) {}
    if (!saved) saved = 'chart';
    applyRoute(saved);
    probeHealth();
    setInterval(probeHealth, 60000);
    console.log('[shell-v5] Stage 2 shell ready · route=' + state.route);
  }

  window.ShellV5 = {
    VERSION: VERSION,
    ROUTES: ROUTES,
    go: go,
    route: function () { return state.route; },
    setSync: setSync
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

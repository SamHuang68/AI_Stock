/* ============================================================================
 * shell_v5.js  —  Stock Terminal 5.0：側欄殼層 + 視圖路由
 * ----------------------------------------------------------------------------
 * TW Pulse 對齊：總覽／圖表／廣度／熱力／法人／國際／盤後／
 * 訊號／自選／風險／快訊／設定 + 選股／投組。
 * 「指數」已併入圖表（^TWII K 線＋總體列／indices 自選更完整）。
 * 同步：預抓歷史庫，僅 merge 最近缺漏日（/sync）。
 * 鐵律：不破壞 #left / #pro-tools / symLoaded / Toolbar 既有行為。
 * ========================================================================== */
(function () {
  'use strict';

  var STORAGE_KEY = 'st5.shell.route';
  var VERSION = '5.0';

  /* 舊 route → 更完整的目的地（圖表／熱力等） */
  var ROUTE_ALIASES = {
    trends: { to: 'chart', sym: '^TWII', mkt: 'TW' },   // 指數頁 → 圖表加權
    index:  { to: 'chart', sym: '^TWII', mkt: 'TW' }
  };

  var ROUTES = [
    { id: 'pulse',         label: '總覽', hint: '市場總覽儀表板（對齊 TW Pulse Overview）', icon: '◎' },
    { id: 'chart',         label: '圖表', hint: 'K 線工作區（含加權／櫃買指數與總體列）',   icon: '◈' },
    { id: 'breadth',       label: '廣度', hint: '大盤廣度（漲跌家數）',                     icon: '▤' },
    { id: 'heat',          label: '熱力', hint: '類股熱力圖＋焦點掃描',                     icon: '▦' },
    { id: 'institutional', label: '法人', hint: '三大法人動向與買賣超',                     icon: '🏦' },
    { id: 'international', label: '國際', hint: '美股／美元／原油與總經',                   icon: '🌐' },
    { id: 'afterhours',    label: '盤後', hint: '漲跌排行／籌碼／期貨盤後',                 icon: '◐' },
    { id: 'signals',       label: '訊號', hint: '策略訊號／焦點掃描結果',                   icon: '🎯' },
    { id: 'watchlist',     label: '自選', hint: '自選股中心（表格式；完整操作在圖表列）',   icon: '★' },
    { id: 'risk',          label: '風險', hint: '風險事件與脈動風險度',                     icon: '🛡' },
    { id: 'news',          label: '快訊', hint: '事件／結算／警報中樞',                     icon: '◉' },
    { id: 'scan',          label: '選股', hint: '三合一選股（技術×基本面×籌碼）',           icon: '🔍' },
    { id: 'book',          label: '投組', hint: '投組風險（波動／VaR／曝險）',               icon: '▣' },
    { id: 'settings',      label: '設定', hint: '同步狀態與資料來源',                       icon: '⚙' },
    { id: 'workspace',     label: '工具', hint: '回到圖表並開啟指令盤',                     icon: '⌘', action: 'cmd' }
  ];

  var state = { route: 'chart', built: false, syncing: false };

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    if ($('shell-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'shell-v5-css';
    s.textContent =
      '#shell-row{display:flex;flex:1;min-height:0;min-width:0}' +
      '#navrail{flex:0 0 58px;width:58px;background:linear-gradient(180deg,#0A1220 0%,#070D18 100%);' +
        'border-right:1px solid var(--border);display:flex;flex-direction:column;align-items:stretch;' +
        'padding:6px 0;gap:1px;z-index:40;flex-shrink:0;overflow-y:auto;overflow-x:hidden}' +
      '#navrail .nr-brand{font-family:\'JetBrains Mono\',monospace;font-size:9px;font-weight:700;' +
        'color:var(--gold);letter-spacing:1px;text-align:center;padding:4px 0 8px;line-height:1.2;' +
        'border-bottom:1px solid var(--border);margin-bottom:4px;user-select:none;flex-shrink:0}' +
      '#navrail .nr-brand small{display:block;color:var(--tlo);font-weight:600;letter-spacing:.5px;margin-top:2px;font-size:8px}' +
      '.nr-btn{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;' +
        'min-height:42px;margin:0 5px;padding:3px 2px;border:1px solid transparent;border-radius:8px;' +
        'background:transparent;color:var(--tlo);cursor:pointer;font-family:\'JetBrains Mono\',monospace;' +
        'font-size:9px;letter-spacing:.2px;transition:background .14s,color .14s,border-color .14s;flex-shrink:0}' +
      '.nr-btn .nr-ico{font-size:13px;line-height:1;opacity:.85}' +
      '.nr-btn:hover{color:var(--thi);background:var(--bg3);border-color:var(--border)}' +
      '.nr-btn.on{color:var(--gold);background:var(--gold-s);border-color:var(--gold-m)}' +
      '.nr-btn.on .nr-ico{opacity:1}' +
      '.nr-spacer{flex:1;min-height:8px}' +
      '.nr-foot{padding:6px 4px 2px;text-align:center;font-family:\'JetBrains Mono\',monospace;' +
        'font-size:8px;color:var(--tf);letter-spacing:.5px;border-top:1px solid var(--border);margin-top:4px;flex-shrink:0}' +
      '#shell-main{display:flex;flex-direction:column;flex:1;min-width:0;min-height:0;position:relative}' +
      '#shell-views{display:none;flex:1;min-height:0;min-width:0;background:' +
        'radial-gradient(1200px 480px at 10% -10%,rgba(245,197,24,.06),transparent 55%),var(--bg);' +
        'overflow:auto}' +
      '#shell-views.show{display:flex;flex-direction:column}' +
      '#body.shell-hidden{display:none !important}' +
      '#wlbar.shell-hidden{display:none !important}' +
      '.sv-panel{display:none;flex:1;padding:10px 14px 16px;max-width:min(1200px,100%);min-width:0;box-sizing:border-box}' +
      '.sv-panel.on{display:block}' +
      /* 資訊面板高密度：標題列／卡片／表格統一收緊 */
      '.sv-panel .sv-kicker{font-size:9px;letter-spacing:1.5px;margin-bottom:2px}' +
      '.sv-panel .sv-title{font-size:20px;margin:0}' +
      '.sv-panel .sv-sub{font-size:10px;margin-top:2px;line-height:1.4}' +
      /* 防 flex 子項 min-content 撑破水平；寬版面板由各模組覆寫 max-width */
      '#shell-views > .sv-panel{min-width:0}' +
      '.sv-mount{min-height:100%;min-width:0;max-width:100%;box-sizing:border-box}' +
      '.sv-kicker{font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--gold);' +
        'letter-spacing:1.5px;margin-bottom:2px}' +
      '.sv-title{font-family:\'Noto Serif TC\',serif;font-size:20px;font-weight:700;color:var(--thi);' +
        'letter-spacing:.5px;margin-bottom:4px;line-height:1.15}' +
      '.sv-desc{font-size:11px;line-height:1.5;color:var(--text);max-width:42em;margin-bottom:8px}' +
      '.sv-meta{font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--tlo);letter-spacing:.5px}' +
      '.sv-cta{display:inline-flex;align-items:center;gap:5px;margin-top:8px;padding:5px 10px;' +
        'background:var(--gold);color:#060A12;border:none;border-radius:5px;cursor:pointer;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:700;letter-spacing:.5px}' +
      '.sv-cta:hover{background:#FBBF24}' +
      '#topbar .shell-sync{display:inline-flex;align-items:center;gap:6px;margin-left:4px;' +
        'font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--tlo);letter-spacing:.5px}' +
      '#topbar .shell-sync .ss-dot{width:6px;height:6px;border-radius:50%;background:var(--green);' +
        'box-shadow:0 0 6px var(--green);flex-shrink:0}' +
      '#topbar .shell-sync.warn .ss-dot{background:var(--orange);box-shadow:0 0 6px var(--orange)}' +
      '#topbar .shell-sync.err .ss-dot{background:var(--red);box-shadow:0 0 6px var(--red)}' +
      '#topbar .shell-sync-btn{display:inline-flex;align-items:center;gap:5px;margin-left:8px;' +
        'padding:4px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--thi);font-family:\'JetBrains Mono\',monospace;font-size:10px;cursor:pointer;' +
        'letter-spacing:.3px}' +
      '#topbar .shell-sync-btn:hover{border-color:var(--gold-m);color:var(--gold)}' +
      '#topbar .shell-sync-btn:disabled{opacity:.55;cursor:wait}' +
      '#topbar .logo .shell-ver{margin-left:6px;font-size:9px;color:var(--gold);letter-spacing:1px;font-weight:700}' +
      '#topbar .logo [data-v2-banner] span,' +
      '#topbar .logo>span[style*="FBBF24"]{display:none !important}' +
      '@media (max-width:720px){' +
        '#navrail{flex-basis:48px;width:48px}' +
        '.nr-btn{min-height:38px;margin:0 3px;font-size:8px}' +
        '.sv-panel{padding:10px 12px 14px}' +
        '.sv-title{font-size:22px}' +
        '#topbar .shell-sync-btn span.lbl{display:none}' +
      '}';
    document.head.appendChild(s);
  }

  function stubHTML(route) {
    return '' +
      '<div class="sv-kicker">STOCK TERMINAL · ' + VERSION + '</div>' +
      '<div class="sv-title">' + route.label + '</div>' +
      '<p class="sv-desc">' + route.hint +
        '。面板載入中或尚未掛接資料模組。</p>' +
      '<div class="sv-meta">route = ' + route.id + '</div>' +
      '<button type="button" class="sv-cta" data-shell-back>← 回到圖表工作區</button>';
  }

  function railHTML() {
    return '<div class="nr-brand">ST<small>v' + VERSION + '</small></div>' +
      ROUTES.map(function (r) {
        return '<button type="button" class="nr-btn" data-route="' + r.id + '" title="' +
          r.hint.replace(/"/g, '') + '">' +
          '<span class="nr-ico" aria-hidden="true">' + r.icon + '</span>' +
          '<span>' + r.label + '</span></button>';
      }).join('') +
      '<div class="nr-spacer"></div>' +
      '<div class="nr-foot">INTEL</div>';
  }

  function ensurePanel(r) {
    if (r.id === 'chart' || r.action) return;
    if ($('view-' + r.id)) return;
    var views = $('shell-views');
    if (!views) return;
    var p = document.createElement('section');
    p.className = 'sv-panel';
    p.id = 'view-' + r.id;
    p.dataset.route = r.id;
    p.innerHTML = r.stub ? stubHTML(r) : '<div class="sv-mount" id="mount-' + r.id + '"></div>';
    views.appendChild(p);
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
    if (topbar && !$('shell-sync-btn')) {
      var sbtn = document.createElement('button');
      sbtn.type = 'button';
      sbtn.id = 'shell-sync-btn';
      sbtn.className = 'shell-sync-btn';
      sbtn.title = '預抓歷史庫並合併最近資料';
      sbtn.innerHTML = '⟳ <span class="lbl">同步資料</span>';
      sbtn.addEventListener('click', function () { runSync(true); });
      var syncEl = $('shell-sync');
      if (syncEl && syncEl.parentElement === topbar) {
        if (syncEl.nextSibling) topbar.insertBefore(sbtn, syncEl.nextSibling);
        else topbar.appendChild(sbtn);
      } else {
        topbar.appendChild(sbtn);
      }
    }

    if (!$('shell-row')) {
      var row = document.createElement('div');
      row.id = 'shell-row';

      var rail = document.createElement('nav');
      rail.id = 'navrail';
      rail.setAttribute('aria-label', '主選單');
      rail.innerHTML = railHTML();

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
        p.innerHTML = '<div class="sv-mount" id="mount-' + r.id + '"></div>';
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
      var rail2 = $('navrail');
      if (rail2) rail2.innerHTML = railHTML();
      ROUTES.forEach(ensurePanel);
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

  function toast(msg, ms) {
    if (window.UI && window.UI.toast) window.UI.toast(msg, ms || 2800);
    else if (typeof window.notifyToast === 'function') window.notifyToast(msg);
    else console.log('[ST5]', msg);
  }

  function pollSyncDone(tries) {
    tries = tries || 0;
    return fetch('/sync/status', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.running && tries < 90) {
          return new Promise(function (res) {
            setTimeout(function () { res(pollSyncDone(tries + 1)); }, 1000);
          });
        }
        return j;
      });
  }

  function runSync(manual) {
    if (state.syncing) return;
    state.syncing = true;
    var btn = $('shell-sync-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '⟳ <span class="lbl">同步中…</span>'; }
    setSync('warn', 'SYNCING');
    if (manual) toast('歷史庫合併同步中（僅抓最近缺漏日）…', 3500);
    fetch('/sync?days=40', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function () { return pollSyncDone(0); })
      .then(function (st) {
        if (!st || !st.ok) throw new Error((st && st.lastError) || 'sync failed');
        var c = st.counts || {};
        var msg = '同步完成 · 指數 ' + (c.index || 0) + ' · 廣度 ' + (c.breadth || 0) +
          ' · 法人 ' + (c.institutional || 0);
        setSync('ok', 'SYNC OK');
        toast(msg, 4200);
        emitRoute(state.route);
      })
      .catch(function (e) {
        setSync('err', 'SYNC ERR');
        toast('同步失敗：' + (e && e.message ? e.message : e), 4000);
      })
      .finally(function () {
        state.syncing = false;
        if (btn) { btn.disabled = false; btn.innerHTML = '⟳ <span class="lbl">同步資料</span>'; }
      });
  }

  function probeHealth() {
    if (typeof fetch !== 'function') return;
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    var t = setTimeout(function () { if (ctrl) ctrl.abort(); }, 2500);
    Promise.all([
      fetch('/health', { signal: ctrl && ctrl.signal }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
      fetch('/sync/status', { cache: 'no-store' }).then(function (r) { return r.json(); }).catch(function () { return null; })
    ]).then(function (arr) {
      var h = arr[0];
      var s = arr[1];
      if (!h) { setSync('warn', 'LOCAL'); return; }
      if (s && s.running) { setSync('warn', 'SYNCING'); return; }
      var n = s && s.counts ? (s.counts.index || 0) : 0;
      setSync('ok', n ? ('DB ' + n) : 'SYNC OK');
    }).finally(function () { clearTimeout(t); });
  }

  function emitRoute(id) {
    try {
      window.dispatchEvent(new CustomEvent('shell:route', { detail: { route: id } }));
    } catch (e) {}
    var map = {
      pulse: 'PulseV5',
      breadth: 'BreadthV5',
      heat: 'HeatV5',
      institutional: 'InstitutionalV5',
      international: 'InternationalV5',
      afterhours: 'AfterhoursV5',
      signals: 'SignalsV5',
      watchlist: 'WatchlistV5',
      risk: 'RiskV5',
      news: 'NewsV5',
      scan: 'ScanV5',
      book: 'BookV5',
      settings: 'SettingsV5'
    };
    var key = map[id];
    if (key && window[key] && typeof window[key].activate === 'function') {
      try { window[key].activate(); }
      catch (err) { console.warn('[shell-v5] ' + key + ' activate', err); }
    }
  }

  function findRoute(id) {
    for (var i = 0; i < ROUTES.length; i++) if (ROUTES[i].id === id) return ROUTES[i];
    return null;
  }

  function resolveAlias(id, opts) {
    opts = opts || {};
    var a = ROUTE_ALIASES[id];
    if (!a) return { id: id, opts: opts };
    return {
      id: a.to,
      opts: {
        sym: opts.sym || a.sym,
        mkt: opts.mkt || a.mkt
      }
    };
  }

  function applyRoute(id, opts) {
    opts = opts || {};
    var resolved = resolveAlias(id, opts);
    id = resolved.id;
    opts = resolved.opts;

    var route = findRoute(id) || findRoute('chart') || ROUTES[0];

    if (route.action === 'cmd') {
      id = 'chart';
      route = findRoute('chart') || ROUTES[0];
      setTimeout(function () {
        var b = $('btn-cmdp');
        if (b) b.click();
        else if (window.cmdPaletteOpen) window.cmdPaletteOpen();
      }, 0);
    } else {
      id = route.id;
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

    if (opts.sym && typeof loadSym === 'function') {
      var sym = opts.sym, mkt = opts.mkt || 'TW';
      setTimeout(function () {
        try { loadSym(sym, mkt); } catch (e) { console.warn('[shell-v5] loadSym', e); }
      }, isChart ? 40 : 0);
    }

    emitRoute(id);
  }

  function go(id, opts) {
    if (!ensureStructure()) return;
    applyRoute(id || 'chart', opts || {});
  }

  function boot() {
    if (!ensureStructure()) return setTimeout(boot, 120);
    /* 移除舊「指數」面板 DOM（若熱更新殘留） */
    ['trends', 'index'].forEach(function (rid) {
      var orphan = $('view-' + rid);
      if (orphan && orphan.parentNode) orphan.parentNode.removeChild(orphan);
    });
    var saved = 'chart';
    try { saved = localStorage.getItem(STORAGE_KEY) || 'chart'; } catch (e) {}
    /* 舊「指數」分頁 → 圖表 */
    if (saved === 'trends' || saved === 'index') saved = 'chart';
    if (!saved || !findRoute(saved)) saved = 'chart';
    applyRoute(saved);
    probeHealth();
    setInterval(probeHealth, 60000);
    /* 歷史庫過薄時自動背景 merge（不打擾） */
    setTimeout(function () {
      fetch('/sync/status', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j || !j.ok || j.running) return;
          if (((j.counts && j.counts.index) || 0) < 5) runSync(false);
        })
        .catch(function () {});
    }, 2800);
    console.log('[shell-v5] Stock Terminal ' + VERSION + ' · route=' + state.route);
  }

  window.ShellV5 = {
    VERSION: VERSION,
    ROUTES: ROUTES,
    ALIASES: ROUTE_ALIASES,
    go: go,
    navigate: go,
    route: function () { return state.route; },
    setSync: setSync,
    sync: function () { runSync(true); },
    /** 開圖表並載入代號（指數預設 ^TWII） */
    openChart: function (sym, mkt) {
      go('chart', { sym: sym || '^TWII', mkt: mkt || 'TW' });
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

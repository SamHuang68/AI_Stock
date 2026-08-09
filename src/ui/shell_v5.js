/* ============================================================================
 * shell_v5.js  —  Stock Terminal 5.0：側欄殼層 + 視圖路由
 * ----------------------------------------------------------------------------
 * S1：左側導覽軌 + 頂列同步；路由 = 同 HTML show/hide（預設圖表工作區）
 * S2：廣度 → breadth_v5
 * S3：盤後 → afterhours_v5；快訊 → news_v5（事件／結算中樞，非新聞爬蟲）
 * S4：脈動 → pulse_v5（TW Pulse 總覽；側欄首位，預設仍還原圖表）
 * S5：熱力 → heat_v5（類股熱力 + 焦點掃描輔區）
 * S6：投組 → book_v5（投組風險：波動／VaR／Beta／曝險）
 * S7：選股 → scan_v5（三合一 /screen3；本弧收官）
 *
 * 鐵律：不破壞 #left / #pro-tools / symLoaded / Toolbar 既有行為。
 * ========================================================================== */
(function () {
  'use strict';

  var STORAGE_KEY = 'st5.shell.route';
  var VERSION = '5.0-S7';

  var ROUTES = [
    { id: 'pulse',      label: '脈動',   hint: '市場脈動總覽（指數／廣度／籌碼）', icon: '◎', stub: false },
    { id: 'chart',      label: '圖表',   hint: 'K 線工作區（預設）',               icon: '◈' },
    { id: 'scan',       label: '選股',   hint: '三合一選股（技術×基本面×籌碼）',   icon: '🔍', stub: false },
    { id: 'heat',       label: '熱力',   hint: '類股熱力圖＋焦點掃描',             icon: '▦', stub: false },
    { id: 'book',       label: '投組',   hint: '投組風險（波動／VaR／曝險）',       icon: '▣', stub: false },
    { id: 'breadth',    label: '廣度',   hint: '大盤廣度（漲跌家數）',             icon: '▤', stub: false },
    { id: 'news',       label: '快訊',   hint: '事件／結算／警報中樞',             icon: '◉', stub: false },
    { id: 'afterhours', label: '盤後',   hint: '台指期夜盤＋個股期＋籌碼',         icon: '◐', stub: false },
    { id: 'wavedeck',   label: '執行',   hint: '開啟 WaveDeck 浪潮執行台（微觀下單艦橋）', icon: '⚡', action: 'wavedeck' },
    { id: 'workspace',  label: '工具',   hint: '回到圖表並開啟指令盤',             icon: '⌘', action: 'cmd' }
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
      sync.title = 'Stock Terminal /health';
      sync.innerHTML = '<span class="ss-dot" aria-hidden="true"></span><span id="shell-sync-txt">ST …</span>';
      var status = $('statusbar');
      if (status && status.parentElement === topbar) topbar.insertBefore(sync, status);
      else {
        var keybtn = $('keybtn');
        if (keybtn) topbar.insertBefore(sync, keybtn);
        else topbar.appendChild(sync);
      }
    }
    if (topbar && !$('shell-wd-sync')) {
      var wds = document.createElement('div');
      wds.id = 'shell-wd-sync';
      wds.className = 'shell-sync warn';
      wds.title = 'WaveDeck 連線／最近宏觀覆寫（點擊開啟）';
      wds.style.cursor = 'pointer';
      wds.innerHTML = '<span class="ss-dot" aria-hidden="true"></span><span id="shell-wd-sync-txt">WD …</span>';
      wds.onclick = function () {
        if (window.WaveDeckBridge && typeof window.WaveDeckBridge.open === 'function') {
          window.WaveDeckBridge.open();
        } else {
          window.open(window.WAVEDECK_URL || 'http://127.0.0.1:18433/', '_blank', 'noopener');
        }
      };
      var stSync = $('shell-sync');
      if (stSync && stSync.parentElement === topbar) {
        if (stSync.nextSibling) topbar.insertBefore(wds, stSync.nextSibling);
        else topbar.appendChild(wds);
      } else {
        topbar.appendChild(wds);
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
        '<div class="nr-foot">S7</div>';

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
      var rail = $('navrail');
      if (rail) {
        rail.innerHTML =
          '<div class="nr-brand">ST<small>5.0</small></div>' +
          ROUTES.map(function (r) {
            return '<button type="button" class="nr-btn" data-route="' + r.id + '" title="' +
              r.hint.replace(/"/g, '') + '">' +
              '<span class="nr-ico" aria-hidden="true">' + r.icon + '</span>' +
              '<span>' + r.label + '</span></button>';
          }).join('') +
          '<div class="nr-spacer"></div>' +
          '<div class="nr-foot">S7</div>';
      }
      // 熱更新：補上後加的路由面板（如 pulse）
      var views = $('shell-views');
      if (views) {
        ROUTES.forEach(function (r) {
          if (r.id === 'chart' || r.action) return;
          if ($('view-' + r.id)) return;
          var p = document.createElement('section');
          p.className = 'sv-panel';
          p.id = 'view-' + r.id;
          p.dataset.route = r.id;
          p.innerHTML = r.stub ? stubHTML(r) : '<div class="sv-mount" id="mount-' + r.id + '"></div>';
          views.appendChild(p);
        });
      }
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
    txt.textContent = text || 'ST';
  }

  function setWdSync(mode, text) {
    var el = $('shell-wd-sync');
    var txt = $('shell-wd-sync-txt');
    if (!el || !txt) return;
    el.classList.remove('warn', 'err');
    if (mode === 'warn') el.classList.add('warn');
    if (mode === 'err') el.classList.add('err');
    txt.textContent = text || 'WD';
  }

  function probeHealth() {
    if (typeof fetch !== 'function') return;
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    var t = setTimeout(function () { if (ctrl) ctrl.abort(); }, 2500);
    fetch('/health', { signal: ctrl && ctrl.signal })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function () { setSync('ok', 'ST OK'); })
      .catch(function () { setSync('warn', 'ST LOCAL'); })
      .finally(function () { clearTimeout(t); });
    probeWaveDeck();
  }

  function paintWdCostTip(meter) {
    var el = $('shell-wd-sync');
    if (!el) return;
    var tip = 'WaveDeck 連線／最近宏觀覆寫（點擊開啟）';
    if (meter && meter.age_sec != null) {
      tip += ' · 回報年齡 ' + meter.age_sec + 's' + (meter.fresh ? '（新鮮）' : '（偏舊）');
    }
    if (meter && meter.costs) {
      var c = meter.costs;
      tip += ' · 成本合計≈$' + (c.combined_usd_est != null ? c.combined_usd_est : '—') +
        '（ST 本機 ' + (c.st_local_calls || 0) + ' 次／雲端≈$' + (c.st_cloud_usd_est || 0) +
        ' · WD 今日 $' + (c.wd_day_usd || 0) +
        (c.wd_provider ? ' · ' + c.wd_provider : '') + '）';
    }
    if (meter && meter.report) {
      var r = meter.report;
      tip += ' · WD 回報 ' + (r.fsm || '—') + '/' + (r.mode || '—') +
        (r.ai && r.ai.action_label ? ' · ' + r.ai.action_label : '');
    }
    el.title = tip;
    // Stale reverse-bus: soften lamp when report older than 45s
    if (meter && meter.report && meter.age_sec != null && Number(meter.age_sec) > 45) {
      el.classList.remove('err');
      el.classList.add('warn');
    }
  }

  function shortWdAction(report) {
    if (!report || !report.ai) return '';
    var map = {
      HOLD: '抱', ENTER_LONG: '多', ENTER_SHORT: '空',
      REDUCE: '減', EXIT: '平'
    };
    var act = report.ai.action;
    if (act && map[act]) return map[act];
    var lab = report.ai.action_label ? String(report.ai.action_label) : '';
    return lab ? lab.slice(0, 2) : '';
  }

  function probeWaveDeck() {
    if (!window.WaveDeckBridge || typeof window.WaveDeckBridge.ping !== 'function') {
      setWdSync('warn', 'WD —');
      return;
    }
    window.WaveDeckBridge.ping().then(function (ok) {
      if (!ok) {
        setWdSync('warn', 'WD OFF');
        return;
      }
      var last = window.WaveDeckBridge.lastSync && window.WaveDeckBridge.lastSync();
      var baseTxt = (last && last.payload)
        ? ('WD ' + last.payload.style + (last.payload.delever ? '↓' : ''))
        : 'WD OK';
      setWdSync('ok', baseTxt);
      if (typeof window.WaveDeckBridge.fetchCostMeter === 'function') {
        window.WaveDeckBridge.fetchCostMeter(false).then(function (meter) {
          paintWdCostTip(meter);
          var act = shortWdAction(meter && meter.report);
          if (act) setWdSync('ok', baseTxt + ' · ' + act);
        }).catch(function () {});
      }
    }).catch(function () { setWdSync('warn', 'WD OFF'); });
  }

  function emitRoute(id) {
    try {
      window.dispatchEvent(new CustomEvent('shell:route', { detail: { route: id } }));
    } catch (e) {}
    var map = {
      pulse: 'PulseV5',
      scan: 'ScanV5',
      heat: 'HeatV5',
      book: 'BookV5',
      breadth: 'BreadthV5',
      afterhours: 'AfterhoursV5',
      news: 'NewsV5'
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

  function applyRoute(id) {
    var route = findRoute(id) || findRoute('chart') || ROUTES[0];

    if (route.action === 'wavedeck') {
      var url = (window.WAVEDECK_URL || 'http://127.0.0.1:18433/');
      if (window.WaveDeckBridge && typeof window.WaveDeckBridge.open === 'function') {
        window.WaveDeckBridge.open(url);
      } else {
        window.open(url, '_blank', 'noopener');
      }
      return;
    }

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
    try {
      window.addEventListener('wavedeck:overlay', function (ev) {
        var p = ev && ev.detail;
        if (p && p.style != null) setWdSync('ok', 'WD ' + p.style + (p.delever ? '↓' : ''));
        else probeWaveDeck();
      });
    } catch (e) {}
    console.log('[shell-v5] Stage 7 shell ready · route=' + state.route);
  }

  window.ShellV5 = {
    VERSION: VERSION,
    ROUTES: ROUTES,
    go: go,
    route: function () { return state.route; },
    setSync: setSync,
    setWdSync: setWdSync,
    probeWaveDeck: probeWaveDeck
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

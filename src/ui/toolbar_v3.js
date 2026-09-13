/* ============================================================================
 * toolbar_v3.js  —  v3.9 / v4.1 工具列模組化（一階分類 + 二階摺疊下拉）
 * ----------------------------------------------------------------------------
 * 目的：把 #pro-tools 內既有功能鈕，依「分類設定檔」收進
 *       「一階大分類 → 二階下拉」，讓版面乾淨專業、方便日後管理。
 *
 * 設計原則（重要）：
 *   1. 非侵入：不修改任何既有模組行為。只「搬移」既有的 <button> 節點，
 *      原本的 id / onclick / 事件 / 狀態(class 'on') 全部保留。
 *   2. 設定驅動：要改分組、順序、名稱、置頂，只動下方 PINNED / GROUPS。
 *   3. 時序無關：按鈕由各模組非同步 append，本檔用 MutationObserver
 *      自動把後到的按鈕歸位，不依賴載入順序。
 *   4. 可擴充：未來新功能可用 window.Toolbar.register({...}) 一行註冊。
 *
 * 2026-08 重整：
 *   - 常駐只留「⌘ 指令」（搜尋／跳轉總入口）
 *   - AI報告 / 副駕 / 焦點 → 「🤖 AI」
 *   - 代號庫 / 資料源 / 快訊 / 健檢 → 「⚙️ 系統」
 *   - 量價模式切換改由 #vp-dock，不再佔工具列
 *
 * 2026-08 下拉修復：
 *   - #pro-tools 不可 overflow-x:auto（會裁切 absolute 選單）
 *   - 選單 portal 到 document.body + position:fixed，避免被 #chartarea 蓋住
 * ========================================================================== */
(function () {
  'use strict';

  // ── 設定檔：唯一需要維護的地方 ───────────────────────────────────────────
  // 常駐置頂：高頻總入口（刻意精簡，其餘進下拉）
  var PINNED = ['btn-cmdp'];

  // 一階分類 → 二階項目（按鈕 id，順序即顯示順序）
  var GROUPS = [
    { key: 'ai', label: '🤖 AI',
      items: ['btn-ai-report', 'btn-copilot', 'btn-focus'] },
    { key: 'chart', label: '📈 圖表',
      items: ['btn-vp', 'btn-multichart', 'btn-spread', 'btn-compare',
              'btn-overnight', 'btn-drawtools', 'btn-replay'] },
    { key: 'fund', label: '🏦 籌碼基本面',
      items: ['btn-valuation', 'btn-marketflow', 'btn-instrank',
              'btn-supplychain', 'btn-stockfut', 'btn-portfolio', 'btn-chainmom'] },
    { key: 'screen', label: '🔍 選股策略',
      items: ['btn-screener3', 'btn-screener', 'btn-patterns', 'btn-kline-events',
              'btn-stratbuilder', 'btn-bt3', 'btn-wizard', 'btn-stratscript'] },
    { key: 'sys', label: '⚙️ 系統',
      items: ['btn-universe', 'btn-datasources', 'btn-calendar',
              'btn-alertpush', 'btn-toast', 'btn-live', 'btn-datahealth',
              'btn-hotkeys'] }
  ];

  // 已由 #vp-dock 取代的冗餘鈕：隱藏，不進任何分類
  var HIDDEN = { 'btn-vp-mode': 1 };

  // ── 衍生索引 ────────────────────────────────────────────────────────────
  var ID2GROUP = {};
  var ALL_KNOWN = {};
  var PINSET = {};
  var MENUS = {}; // key -> menu element（portal 後仍可靠引用）
  GROUPS.forEach(function (g) {
    g.items.forEach(function (id) { ID2GROUP[id] = g.key; ALL_KNOWN[id] = 1; });
  });
  PINNED.forEach(function (id) { PINSET[id] = 1; ALL_KNOWN[id] = 1; });
  Object.keys(HIDDEN).forEach(function (id) { ALL_KNOWN[id] = 1; });

  var mo = null;
  var openKey = null;

  function pt() { return document.getElementById('pro-tools'); }

  function menuOf(gkey) {
    return MENUS[gkey] || document.getElementById('tbg-menu-' + gkey);
  }

  // ── 樣式 ────────────────────────────────────────────────────────────────
  function injectCSS() {
    if (document.getElementById('toolbar-v3-css')) return;
    var s = document.createElement('style');
    s.id = 'toolbar-v3-css';
    s.textContent =
      /* 不可 overflow-x:auto：會裁切下拉；橫向不夠時由外層 #left 自然伸展 */
      '#pro-tools{align-items:center !important;gap:3px !important;flex-wrap:wrap;overflow:visible !important;height:auto !important}' +
      '#pro-tools .tb-sep{width:1px;height:16px;background:var(--border,#334155);margin:0 4px;flex-shrink:0;opacity:.8}' +
      '.tbg{position:relative;display:inline-flex;flex-shrink:0}' +
      '.tbg>.tbg-btn{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}' +
      '.tbg>.tbg-btn .caret{font-size:8px;opacity:.65;transition:transform .12s}' +
      '.tbg.open>.tbg-btn{color:var(--gold);border-color:var(--gold);background:var(--gold-s)}' +
      '.tbg.open>.tbg-btn .caret{transform:rotate(180deg)}' +
      '.tbg.act>.tbg-btn{border-color:var(--gold-m,#8a6d12)}' +
      /* portal 到 body：fixed，不被工具列／圖表區裁切或蓋住 */
      '.tbg-menu{position:fixed;z-index:200000;display:none;flex-direction:column;gap:3px;' +
        'background:var(--bg2,#0d1117);border:1px solid var(--border,#2a2a2a);' +
        'border-radius:7px;padding:6px;min-width:156px;max-height:min(70vh,420px);overflow-y:auto;' +
        'box-shadow:0 12px 34px rgba(0,0,0,.55)}' +
      '.tbg-menu.open{display:flex}' +
      '.tbg-menu>*{margin:0 !important}' +
      '.tbg-menu>.probtn{width:100% !important;justify-content:flex-start !important;height:28px}' +
      '.tbg-menu>span{width:100%}' +
      '.tbg-menu>span>.probtn{width:100% !important;justify-content:flex-start !important;height:28px}' +
      /* 冗餘／已整合進其他入口的按鈕 */
      '#btn-vp-mode{display:none !important}';
    document.head.appendChild(s);
  }

  function positionOpenMenu() {
    if (!openKey) return;
    var w = document.getElementById('tbg-' + openKey);
    var menu = menuOf(openKey);
    if (!w || !menu) return;
    var btn = w.querySelector('.tbg-btn');
    if (!btn) return;
    if (menu.parentElement !== document.body) document.body.appendChild(menu);
    var r = btn.getBoundingClientRect();
    menu.style.top = Math.round(r.bottom + 5) + 'px';
    menu.style.left = Math.round(r.left) + 'px';
    menu.classList.add('open');
    // 右側溢出時往左收
    var mr = menu.getBoundingClientRect();
    var maxR = window.innerWidth - 8;
    if (mr.right > maxR) {
      menu.style.left = Math.max(8, Math.round(maxR - mr.width)) + 'px';
    }
    // 下方溢出時往上開
    var maxB = window.innerHeight - 8;
    mr = menu.getBoundingClientRect();
    if (mr.bottom > maxB && r.top > mr.height + 10) {
      menu.style.top = Math.round(r.top - mr.height - 5) + 'px';
    }
  }

  // ── 開合控制 ────────────────────────────────────────────────────────────
  function closeAll() {
    openKey = null;
    var os = document.querySelectorAll('.tbg.open');
    for (var i = 0; i < os.length; i++) os[i].classList.remove('open');
    var ms = document.querySelectorAll('.tbg-menu.open');
    for (var j = 0; j < ms.length; j++) ms[j].classList.remove('open');
  }
  function toggle(w) {
    var key = (w.id || '').replace(/^tbg-/, '');
    var wasOpen = w.classList.contains('open');
    closeAll();
    if (!wasOpen && key) {
      openKey = key;
      w.classList.add('open');
      positionOpenMenu();
    }
  }

  function nodeToMove(el) {
    var n = el, root = pt();
    while (n.parentElement && n.parentElement !== root) n = n.parentElement;
    return (n.parentElement === root) ? n : el;
  }

  function place(id) {
    var el = document.getElementById(id);
    if (!el) return;
    if (HIDDEN[id]) {
      el.style.display = 'none';
      return;
    }
    if (PINSET[id]) {
      if (el.closest('.tbg-menu') && pt()) pt().appendChild(nodeToMove(el));
      return;
    }
    var gkey = ID2GROUP[id];
    if (!gkey) return;
    var menu = menuOf(gkey);
    if (!menu) return;
    if (el.closest('.tbg-menu') === menu || menu.contains(el)) return;
    menu.appendChild(nodeToMove(el));
  }

  function placeAll() { Object.keys(ALL_KNOWN).forEach(place); }

  // 未知按鈕（未列在 PINNED/GROUPS）：收進「系統」，避免散落佔版面
  function sweepOrphans() {
    var root = pt(); if (!root) return;
    var menu = menuOf('sys');
    if (!menu) return;
    var kids = Array.prototype.slice.call(root.children);
    kids.forEach(function (n) {
      if (n.classList && n.classList.contains('tbg')) return;
      if (n.classList && n.classList.contains('tb-sep')) return;
      // 量價切換列（#vp-inline）與指令列同行，不可掃進下拉
      if (n.id === 'vp-inline' || n.id === 'vp-float' || (n.getAttribute && n.getAttribute('data-tb-keep'))) return;
      var id = n.id || (n.querySelector && n.querySelector('.probtn') && n.querySelector('.probtn').id);
      if (!id || ALL_KNOWN[id] || PINSET[id]) return;
      // 後註冊但未指定分類 → 系統
      ID2GROUP[id] = 'sys';
      ALL_KNOWN[id] = 1;
      var g = GROUPS.filter(function (x) { return x.key === 'sys'; })[0];
      if (g && g.items.indexOf(id) < 0) g.items.push(id);
      menu.appendChild(nodeToMove(n.id ? n : document.getElementById(id)));
    });
  }

  function ensureSep() {
    var root = pt(); if (!root) return null;
    var sep = root.querySelector('.tb-sep');
    if (!sep) {
      sep = document.createElement('span');
      sep.className = 'tb-sep';
      sep.setAttribute('aria-hidden', 'true');
    }
    return sep;
  }

  // 排序：置頂 → 分隔線 → 五個分類入口
  function reorder() {
    var root = pt(); if (!root) return;
    var sep = ensureSep();
    for (var i = PINNED.length - 1; i >= 0; i--) {
      var el = document.getElementById(PINNED[i]);
      if (el) {
        var n = nodeToMove(el);
        if (n.parentElement !== root) root.appendChild(n);
        root.insertBefore(n, root.firstChild);
      }
    }
    if (sep) {
      var firstGroup = document.getElementById('tbg-' + GROUPS[0].key);
      if (firstGroup) root.insertBefore(sep, firstGroup);
      else root.appendChild(sep);
      // 確保分隔在 pinned 之後
      var lastPin = document.getElementById(PINNED[PINNED.length - 1]);
      if (lastPin) {
        var pinNode = nodeToMove(lastPin);
        if (pinNode.nextSibling !== sep) root.insertBefore(sep, pinNode.nextSibling);
      }
    }
    GROUPS.forEach(function (g) {
      var w = document.getElementById('tbg-' + g.key);
      if (w) root.appendChild(w);
    });
    // 量價切換永遠贴在指令列最右（同一行）
    var vp = document.getElementById('vp-inline');
    if (vp && vp.parentElement === root) root.appendChild(vp);
  }

  function updateActive() {
    GROUPS.forEach(function (g) {
      var w = document.getElementById('tbg-' + g.key); if (!w) return;
      var on = g.items.some(function (id) {
        var el = document.getElementById(id);
        return el && el.classList.contains('on') && el.style.display !== 'none';
      });
      w.classList.toggle('act', on);
    });
  }

  function run() {
    var root = pt(); if (!root) return;
    if (mo) mo.disconnect();
    placeAll();
    sweepOrphans();
    reorder();
    updateActive();
    if (openKey) positionOpenMenu();
    if (mo) mo.observe(root, { childList: true });
  }

  function build() {
    var root = pt(); if (!root) return;
    if (document.getElementById('tbg-' + GROUPS[0].key)) return;
    injectCSS();
    GROUPS.forEach(function (g) {
      var w = document.createElement('span'); w.className = 'tbg'; w.id = 'tbg-' + g.key;
      var btn = document.createElement('button'); btn.className = 'probtn tbg-btn';
      btn.type = 'button';
      btn.title = g.label.replace(/^[^\s]+\s/, '') + '（點擊展開）';
      btn.setAttribute('aria-haspopup', 'menu');
      btn.setAttribute('aria-expanded', 'false');
      btn.innerHTML = g.label + ' <span class="caret">▾</span>';
      btn.onclick = function (e) {
        e.stopPropagation();
        toggle(w);
        btn.setAttribute('aria-expanded', w.classList.contains('open') ? 'true' : 'false');
      };
      var menu = document.createElement('div');
      menu.className = 'tbg-menu';
      menu.id = 'tbg-menu-' + g.key;
      menu.setAttribute('role', 'menu');
      menu.onclick = function (e) {
        e.stopPropagation();
        setTimeout(closeAll, 0);
      };
      MENUS[g.key] = menu;
      w.appendChild(btn);
      // 初始掛在分類下，place() 會把按鈕塞進來；開啟時再 portal 到 body
      w.appendChild(menu);
      root.appendChild(w);
    });
    document.addEventListener('click', function (e) {
      if (e.target && (e.target.closest && (e.target.closest('.tbg') || e.target.closest('.tbg-menu')))) return;
      closeAll();
    });
    window.addEventListener('resize', function () { if (openKey) positionOpenMenu(); });
    window.addEventListener('scroll', function () { if (openKey) positionOpenMenu(); }, true);

    mo = new MutationObserver(function () { run(); });
    run();
    setInterval(updateActive, 1200);
    console.log('[toolbar-v3] reorg: ' + PINNED.length + ' pinned + ' + GROUPS.length + ' groups (portal menus)');
  }

  // cat: 'pin' | 'ai' | 'chart' | 'fund' | 'screen' | 'sys'
  window.Toolbar = {
    CONFIG: { PINNED: PINNED, GROUPS: GROUPS, HIDDEN: HIDDEN },
    register: function (opt) {
      if (!opt || !opt.id) return;
      var root = pt();
      if (!root) { setTimeout(function () { window.Toolbar.register(opt); }, 150); return; }
      var b = document.getElementById(opt.id);
      if (!b) {
        b = document.createElement('button'); b.id = opt.id; b.className = 'probtn';
        b.textContent = opt.label || opt.id;
        if (opt.title) b.title = opt.title;
        if (opt.onclick) b.onclick = opt.onclick;
        root.appendChild(b);
      }
      // 相容舊 cat:'pin'：除指令外，導向對應分類（避免再度撐爆常駐列）
      var cat = opt.cat;
      if (cat === 'pin' && opt.id !== 'btn-cmdp') {
        if (opt.id === 'btn-ai-report' || opt.id === 'btn-copilot' || opt.id === 'btn-focus') cat = 'ai';
        else if (opt.id === 'btn-universe' || opt.id === 'btn-datasources') cat = 'sys';
        else cat = 'sys';
      }
      if (cat === 'pin') {
        if (!PINSET[opt.id]) { PINNED.push(opt.id); PINSET[opt.id] = 1; ALL_KNOWN[opt.id] = 1; }
      } else {
        var g = null;
        for (var i = 0; i < GROUPS.length; i++) if (GROUPS[i].key === cat) g = GROUPS[i];
        if (g && g.items.indexOf(opt.id) < 0) {
          g.items.push(opt.id); ID2GROUP[opt.id] = g.key; ALL_KNOWN[opt.id] = 1;
        } else if (g) {
          ID2GROUP[opt.id] = g.key; ALL_KNOWN[opt.id] = 1;
        }
      }
      run();
    },
    reflow: run,
    closeMenus: closeAll
  };

  (function drainQueue() {
    var q = window.__tbQueue || [];
    window.__tbQueue = { push: function (o) { window.Toolbar.register(o); } };
    q.forEach(function (o) {
      try { window.Toolbar.register(o); }
      catch (e) { console.warn('[toolbar-v3] queued register failed:', o && o.id, e); }
    });
  })();

  (function boot() {
    if (!pt()) return setTimeout(boot, 150);
    build();
  })();
})();

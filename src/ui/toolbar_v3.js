/* ============================================================================
 * toolbar_v3.js  —  v3.9 工具列模組化（一階分類 + 二階摺疊下拉）
 * ----------------------------------------------------------------------------
 * 目的：把 #pro-tools 內既有的 ~29 顆功能鈕，依「分類設定檔」收進
 *       「一階大分類 → 二階下拉」，讓版面乾淨專業、方便日後管理。
 *
 * 設計原則（重要）：
 *   1. 非侵入：不修改任何既有模組。只「搬移」既有的 <button> 節點，
 *      原本的 id / onclick / 事件 / 狀態(class 'on') 全部保留。
 *   2. 設定驅動：要改分組、順序、名稱、置頂，只動下方 PINNED / GROUPS。
 *   3. 時序無關：按鈕由各模組非同步 append，本檔用 MutationObserver
 *      自動把後到的按鈕歸位，不依賴載入順序。
 *   4. 可擴充：未來新功能可用 window.Toolbar.register({...}) 一行註冊，
 *      或照舊 appendChild 到 #pro-tools，本檔會自動把它收進指定分類。
 *
 * 維護：新增一顆按鈕要進哪一類，只要把它的 id 加進對應 GROUPS.items 即可。
 * ========================================================================== */
(function () {
  'use strict';

  // ── 設定檔：唯一需要維護的地方 ───────────────────────────────────────────
  // 常駐置頂（高頻 / 代表性功能，不收進下拉）
  var PINNED = ['btn-cmdp', 'btn-ai-report', 'btn-focus'];

  // 一階分類 → 二階項目（按鈕 id，順序即顯示順序）
  var GROUPS = [
    { key: 'chart',  label: '📈 圖表',        // 📈 圖表
      items: ['btn-vp', 'btn-vp-mode', 'btn-multichart', 'btn-spread',
              'btn-compare', 'btn-overnight', 'btn-drawtools', 'btn-replay',
              'btn-hotkeys', 'btn-heatmap'] },                  // heatmap 目前停用,留位待恢復
    { key: 'fund',   label: '🏦 籌碼基本面', // 🏦 籌碼基本面
      items: ['btn-valuation', 'btn-marketflow', 'btn-instrank',
              'btn-supplychain', 'btn-stockfut'] },
    { key: 'screen', label: '🔍 選股策略',       // 🔍 選股策略
      items: ['btn-screener3', 'btn-screener', 'btn-patterns',
              'btn-stratbuilder', 'btn-bt3', 'btn-wizard', 'btn-stratscript'] },
    { key: 'alert',  label: '🔔 快訊',        // 🔔 快訊
      items: ['btn-toast', 'btn-alertpush', 'btn-live', 'btn-calendar',
              'btn-datahealth'] }
  ];

  // ── 衍生索引 ────────────────────────────────────────────────────────────
  var ID2GROUP = {};                       // 按鈕 id → 分類 key
  var ALL_KNOWN = {};                       // 所有會被歸位的 id（pinned + grouped）
  var PINSET = {};
  GROUPS.forEach(function (g) { g.items.forEach(function (id) { ID2GROUP[id] = g.key; ALL_KNOWN[id] = 1; }); });
  PINNED.forEach(function (id) { PINSET[id] = 1; ALL_KNOWN[id] = 1; });

  var mo = null;   // MutationObserver

  function pt() { return document.getElementById('pro-tools'); }

  // ── 樣式 ────────────────────────────────────────────────────────────────
  function injectCSS() {
    if (document.getElementById('toolbar-v3-css')) return;
    var s = document.createElement('style');
    s.id = 'toolbar-v3-css';
    s.textContent =
      '#pro-tools{align-items:center !important}' +
      '.tbg{position:relative;display:inline-flex}' +
      '.tbg>.tbg-btn{display:inline-flex;align-items:center;gap:5px}' +
      '.tbg>.tbg-btn .caret{font-size:8px;opacity:.65;transition:transform .12s}' +
      '.tbg.open>.tbg-btn{color:var(--gold);border-color:var(--gold);background:var(--gold-s)}' +
      '.tbg.open>.tbg-btn .caret{transform:rotate(180deg)}' +
      '.tbg.act>.tbg-btn{border-color:var(--gold-m,#8a6d12)}' +
      '.tbg-menu{position:absolute;top:calc(100% + 5px);left:0;z-index:99999;' +
        'background:var(--bg2,#0d1117);border:1px solid var(--border,#2a2a2a);' +
        'border-radius:7px;padding:6px;display:none;flex-direction:column;gap:4px;' +
        'min-width:132px;box-shadow:0 12px 34px rgba(0,0,0,.55)}' +
      '.tbg.open>.tbg-menu{display:flex}' +
      '.tbg-menu>*{margin:0 !important}' +
      '.tbg-menu>.probtn{width:100% !important;justify-content:flex-start !important;height:26px}' +
      '.tbg-menu>span{width:100%}' +
      '.tbg-menu>span>.probtn{width:100% !important;justify-content:flex-start !important;height:26px}';
    document.head.appendChild(s);
  }

  // ── 開合控制 ────────────────────────────────────────────────────────────
  function closeAll() {
    var os = document.querySelectorAll('.tbg.open');
    for (var i = 0; i < os.length; i++) os[i].classList.remove('open');
  }
  function toggle(w) {
    var wasOpen = w.classList.contains('open');
    closeAll();
    if (!wasOpen) w.classList.add('open');
  }

  // 取得「應被搬移的節點」：若按鈕被包在 wrapper(如 源/通知)，搬整個 wrapper
  function nodeToMove(el) {
    var n = el, root = pt();
    while (n.parentElement && n.parentElement !== root) n = n.parentElement;
    return (n.parentElement === root) ? n : el;
  }

  // 把單一按鈕歸位到它的分類下拉(或保持置頂)
  function place(id) {
    var el = document.getElementById(id);
    if (!el) return;
    if (PINSET[id]) {                         // 置頂：拉回 #pro-tools 直屬
      if (el.closest('.tbg-menu') && pt()) pt().appendChild(el);
      return;
    }
    var gkey = ID2GROUP[id];
    if (!gkey) return;
    var menu = document.querySelector('#tbg-' + gkey + ' > .tbg-menu');
    if (!menu) return;
    if (el.closest('#tbg-' + gkey + ' > .tbg-menu')) return;   // 已就位
    menu.appendChild(nodeToMove(el));
  }

  function placeAll() { Object.keys(ALL_KNOWN).forEach(place); }

  // 重新排序：置頂鈕在前，接著四個分類入口
  function reorder() {
    var root = pt(); if (!root) return;
    for (var i = PINNED.length - 1; i >= 0; i--) {
      var el = document.getElementById(PINNED[i]);
      if (el && el.parentElement === root) root.insertBefore(el, root.firstChild);
    }
    GROUPS.forEach(function (g) {
      var w = document.getElementById('tbg-' + g.key);
      if (w) root.appendChild(w);
    });
  }

  // 分類入口反映「內含作用中功能」狀態
  function updateActive() {
    GROUPS.forEach(function (g) {
      var w = document.getElementById('tbg-' + g.key); if (!w) return;
      var on = g.items.some(function (id) {
        var el = document.getElementById(id);
        return el && el.classList.contains('on');
      });
      w.classList.toggle('act', on);
    });
  }

  // 一次完整整理（搬移期間先停觀察以免遞迴）
  function run() {
    var root = pt(); if (!root) return;
    if (mo) mo.disconnect();
    placeAll();
    reorder();
    updateActive();
    if (mo) mo.observe(root, { childList: true });
  }

  // ── 建立分類入口 ────────────────────────────────────────────────────────
  function build() {
    var root = pt(); if (!root) return;
    if (document.getElementById('tbg-' + GROUPS[0].key)) return;  // 已建過
    injectCSS();
    GROUPS.forEach(function (g) {
      var w = document.createElement('span'); w.className = 'tbg'; w.id = 'tbg-' + g.key;
      var btn = document.createElement('button'); btn.className = 'probtn tbg-btn';
      btn.title = g.label.replace(/^[^\s]+\s/, '') + '（點擊展開）';
      btn.innerHTML = g.label + ' <span class="caret">▾</span>';
      btn.onclick = function (e) { e.stopPropagation(); toggle(w); };
      var menu = document.createElement('div'); menu.className = 'tbg-menu';
      menu.onclick = function () { setTimeout(closeAll, 0); };   // 選完即收合
      w.appendChild(btn); w.appendChild(menu);
      root.appendChild(w);
    });
    document.addEventListener('click', closeAll);

    mo = new MutationObserver(function () { run(); });
    run();
    setInterval(updateActive, 1200);   // 輕量同步作用中狀態
    console.log('[toolbar-v3] organized into ' + GROUPS.length + ' groups + ' + PINNED.length + ' pinned');
  }

  // ── 對外 API：未來模組註冊新按鈕用 ──────────────────────────────────────
  // 例：Toolbar.register({ id:'btn-foo', label:'🆕 新功能', cat:'chart', onclick:fooOpen })
  //     cat 可為 'chart' | 'fund' | 'screen' | 'alert' | 'pin'
  window.Toolbar = {
    CONFIG: { PINNED: PINNED, GROUPS: GROUPS },
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
      if (opt.cat === 'pin') {
        if (!PINSET[opt.id]) { PINNED.push(opt.id); PINSET[opt.id] = 1; ALL_KNOWN[opt.id] = 1; }
      } else {
        var g = null;
        for (var i = 0; i < GROUPS.length; i++) if (GROUPS[i].key === opt.cat) g = GROUPS[i];
        if (g && g.items.indexOf(opt.id) < 0) { g.items.push(opt.id); ID2GROUP[opt.id] = g.key; ALL_KNOWN[opt.id] = 1; }
      }
      run();
    },
    reflow: run
  };

  // 排隊式註冊：比本檔更早載入的模組，先把 spec 推進 window.__tbQueue 暫存，
  // 本檔載入後一次處理；之後再 push 的也會直接註冊。
  (function drainQueue() {
    var q = window.__tbQueue || [];
    window.__tbQueue = { push: function (o) { window.Toolbar.register(o); } };
    q.forEach(function (o) {
      try { window.Toolbar.register(o); }
      catch (e) { console.warn('[toolbar-v3] queued register failed:', o && o.id, e); }
    });
  })();

  // ── 啟動 ────────────────────────────────────────────────────────────────
  (function boot() {
    if (!pt()) return setTimeout(boot, 150);
    build();
  })();
})();

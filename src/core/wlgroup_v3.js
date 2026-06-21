// ============================================================
// Stock Terminal v3.9 Phase-1 — 自選股分組 (Watchlist Groups)
// ------------------------------------------------------------
// 給自選股加「長線/短線」標籤,可一鍵篩選只看某組。標籤存在 S.wl 各項的 .g,
// 隨 saveWl 持久化;篩選狀態存 localStorage。
// 實作:monkey-patch window.renderWl,在原渲染後 applyGroups()(加標籤鈕+篩選),
//   不改動 stock_terminal.html 核心。狀態存取用裸 S(架構守則)。
// ============================================================
(function () {
  'use strict';
  var GROUPS = ['長線', '短線'];          // 固定兩組(Sam 需求);可日後擴充
  var LS_FILTER = 'stock_wl_group_filter_v3';
  var COLOR = { '長線': ['#1f6f3f', '#3ecf6b'], '短線': ['#7a5a14', '#f1c40f'] }; // [bg, fg]

  function curFilter() { return localStorage.getItem(LS_FILTER) || 'all'; }
  function setFilter(f) { localStorage.setItem(LS_FILTER, f); rerender(); }

  function rerender() {
    if (typeof window.renderWl === 'function') window.renderWl();
  }

  function cycleGroup(sym, mkt) {
    if (typeof S === 'undefined' || !Array.isArray(S.wl)) return;
    var w = S.wl.find(function (x) { return x.t === sym && x.m === mkt; });
    if (!w) return;
    var order = [''].concat(GROUPS);            // 無 → 長線 → 短線 → 無
    var i = order.indexOf(w.g || '');
    w.g = order[(i + 1) % order.length];
    if (!w.g) delete w.g;
    if (typeof saveWl === 'function') saveWl();
    rerender();
  }
  window.cycleWlGroup = cycleGroup;

  function setPill(pill, g) {
    if (g && COLOR[g]) {
      pill.textContent = g[0];                  // 「長」/「短」
      pill.style.background = COLOR[g][0];
      pill.style.color = COLOR[g][1];
      pill.title = g + '（點擊切換分組）';
    } else {
      pill.textContent = '·';
      pill.style.background = 'transparent';
      pill.style.color = '#666';
      pill.title = '未分組（點擊設為長線/短線）';
    }
  }

  function counts() {
    var c = { all: 0, '長線': 0, '短線': 0, none: 0 };
    if (typeof S !== 'undefined' && Array.isArray(S.wl)) {
      S.wl.forEach(function (w) {
        c.all++;
        if (w.g === '長線') c['長線']++;
        else if (w.g === '短線') c['短線']++;
        else c.none++;
      });
    }
    return c;
  }

  function ensureBar() {
    var ct = document.getElementById('wlchips');
    if (!ct) return null;
    var bar = document.getElementById('wlg-bar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'wlg-bar';
      bar.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;padding:3px 0 5px;align-items:center';
      ct.parentNode.insertBefore(bar, ct);
    }
    return bar;
  }

  function renderFilterBar() {
    var bar = ensureBar();
    if (!bar) return;
    var f = curFilter(), c = counts();
    var defs = [
      ['all', '全部', c.all],
      ['長線', '長線', c['長線']],
      ['短線', '短線', c['短線']],
      ['__none__', '無', c.none],
    ];
    bar.innerHTML = defs.map(function (d) {
      var active = (f === d[0]);
      return '<button class="wlg-fbtn" data-f="' + d[0] + '" style="' +
        'font-size:10px;padding:1px 7px;border-radius:10px;cursor:pointer;border:1px solid ' +
        (active ? '#4a8' : '#333') + ';background:' + (active ? 'rgba(62,207,107,.15)' : 'transparent') +
        ';color:' + (active ? '#3ecf6b' : '#aaa') + '">' + d[1] + ' ' + d[2] + '</button>';
    }).join('');
    bar.querySelectorAll('.wlg-fbtn').forEach(function (b) {
      b.onclick = function () { setFilter(b.dataset.f); };
    });
  }

  function applyGroups() {
    var ct = document.getElementById('wlchips');
    if (!ct || typeof S === 'undefined' || !Array.isArray(S.wl)) return;
    var f = curFilter();
    ct.querySelectorAll('.wlchip').forEach(function (chip) {
      var sym = chip.dataset.sym, mkt = chip.dataset.mkt;
      var w = S.wl.find(function (x) { return x.t === sym && x.m === mkt; });
      var g = (w && w.g) || '';
      var show = (f === 'all') || (f === '__none__' ? !g : g === f);
      chip.style.display = show ? '' : 'none';
      if (!chip.querySelector('.wlg-pill')) {
        var pill = document.createElement('span');
        pill.className = 'wlg-pill';
        pill.style.cssText = 'font-size:8px;font-weight:700;padding:0 3px;margin-left:3px;' +
          'border-radius:3px;cursor:pointer;line-height:1.4;display:inline-block;min-width:8px;text-align:center';
        pill.addEventListener('click', function (e) { e.stopPropagation(); cycleGroup(sym, mkt); });
        var rm = chip.querySelector('.wlchip-rm');
        if (rm) chip.insertBefore(pill, rm); else chip.appendChild(pill);
        setPill(pill, g);
      }
    });
    renderFilterBar();
  }

  // monkey-patch renderWl:原渲染後套用分組
  (function patch() {
    if (typeof window.renderWl !== 'function') return setTimeout(patch, 150);
    if (window.__wlgPatched) return;
    var orig = window.renderWl;
    window.renderWl = function () {
      var r = orig.apply(this, arguments);
      try { applyGroups(); } catch (e) { console.warn('[wlgroup]', e); }
      return r;
    };
    window.__wlgPatched = true;
    rerender();   // 套用一次
  })();
})();

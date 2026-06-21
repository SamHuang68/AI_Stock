// ============================================================
// Stock Terminal v3.9 — 名稱搜尋自動完成 (Name Search Autocomplete)
// ------------------------------------------------------------
// 像 Yahoo 股市:在代號框打「公司名」(中文)或代號 → 即時下拉建議 → 選取載入,
// 每列可直接「＋」加自選。資料源:server /search(用 _get_tw_names 反查台股)。
// ↓↑ 選擇、Enter 選取(攔截原 go())、Esc 關閉。狀態用裸 S、全域 loadSym/saveWl/renderWl。
// ============================================================
(function () {
  'use strict';
  var box, items = [], sel = -1, timer = null, lastQ = '';

  function ensureBox() {
    if (box) return box;
    box = document.createElement('div');
    box.id = 'ns-box';
    box.style.cssText = 'position:fixed;z-index:100001;display:none;max-height:60vh;overflow-y:auto;' +
      'min-width:240px;background:#161616;border:1px solid #3a3a3a;border-radius:6px;' +
      'box-shadow:0 10px 30px rgba(0,0,0,.55);font-size:12px';
    document.body.appendChild(box);
    return box;
  }

  function hide() { if (box) box.style.display = 'none'; sel = -1; items = []; }

  function position() {
    var inp = document.getElementById('syminput');
    if (!inp || !box) return;
    var r = inp.getBoundingClientRect();
    box.style.left = r.left + 'px';
    box.style.top = (r.bottom + 3) + 'px';
    box.style.minWidth = Math.max(r.width, 240) + 'px';
  }

  function pick(it) {
    if (!it) return;
    var inp = document.getElementById('syminput');
    if (inp) inp.value = it.t;
    hide();
    if (typeof loadSym === 'function') loadSym(it.t, it.m || 'TW');
  }

  function addWatch(it) {
    if (typeof S === 'undefined' || !Array.isArray(S.wl)) return;
    if (!S.wl.find(function (w) { return w.t === it.t && w.m === (it.m || 'TW'); })) {
      S.wl.push({ t: it.t, m: it.m || 'TW', name: it.name });
      if (typeof saveWl === 'function') saveWl();
      if (typeof renderWl === 'function') renderWl();
      if (typeof setStat === 'function') setStat('已加入自選:' + it.name + ' ' + it.t);
    }
  }

  function render() {
    ensureBox();
    if (!items.length) { hide(); return; }
    box.innerHTML = items.map(function (it, i) {
      return '<div class="ns-row" data-i="' + i + '" style="display:flex;align-items:center;gap:8px;' +
        'padding:6px 10px;cursor:pointer;border-top:1px solid #242424;' + (i === sel ? 'background:rgba(62,207,107,.14)' : '') + '">' +
        '<span style="flex:1;color:#eee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' +
        String(it.name).replace(/</g, '&lt;') + '</span>' +
        '<span style="color:#888;font-family:monospace">' + it.t + '</span>' +
        '<span class="ns-add" data-i="' + i + '" title="加自選" style="color:#3ecf6b;font-weight:700;padding:0 4px;cursor:pointer">＋</span>' +
        '</div>';
    }).join('');
    box.querySelectorAll('.ns-row').forEach(function (r) {
      r.onmouseenter = function () { sel = +r.dataset.i; paint(); };
      r.onclick = function (e) {
        var i = +r.dataset.i;
        if (e.target.classList.contains('ns-add')) { addWatch(items[i]); e.stopPropagation(); }
        else pick(items[i]);
      };
    });
    position();
    box.style.display = 'block';
  }
  function paint() {
    if (!box) return;
    box.querySelectorAll('.ns-row').forEach(function (r, i) {
      r.style.background = (i === sel) ? 'rgba(62,207,107,.14)' : '';
    });
  }

  function search(q) {
    fetch('/search?q=' + encodeURIComponent(q)).then(function (r) { return r.json(); })
      .then(function (j) {
        if (q !== lastQ) return;           // 過時結果丟棄
        items = (j && j.results) || [];
        sel = items.length ? 0 : -1;
        render();
      }).catch(function () {});
  }

  function onInput() {
    var inp = document.getElementById('syminput');
    if (!inp) return;
    var q = (inp.value || '').trim();
    lastQ = q;
    if (!q) { hide(); return; }
    clearTimeout(timer);
    timer = setTimeout(function () { search(q); }, 220);
  }

  (function attach() {
    var inp = document.getElementById('syminput');
    if (!inp) return setTimeout(attach, 150);
    inp.setAttribute('autocomplete', 'off');
    inp.addEventListener('input', onInput);
    inp.addEventListener('blur', function () { setTimeout(hide, 180); });   // 留時間給點擊
    // capture 階段攔截 Enter/方向鍵:在原 inline go() 之前處理
    document.addEventListener('keydown', function (e) {
      if (document.activeElement !== inp) return;
      if (!box || box.style.display === 'none' || !items.length) return;
      if (e.key === 'ArrowDown') { sel = (sel + 1) % items.length; paint(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { sel = (sel - 1 + items.length) % items.length; paint(); e.preventDefault(); }
      else if (e.key === 'Enter') { e.preventDefault(); e.stopImmediatePropagation(); pick(items[sel] || items[0]); }
      else if (e.key === 'Escape') { hide(); }
    }, true);
    window.addEventListener('scroll', function () { if (box && box.style.display !== 'none') position(); }, true);
  })();
})();

// ============================================================
// Stock Terminal v3.9 Phase-3 — Command Palette (指令面板)
// ------------------------------------------------------------
// Ctrl/Cmd+K 叫出:打字即搜尋
//   • 自選股 / 指數(載入 K 線)
//   • 工具列所有功能鈕(自動探索 #pro-tools,點擊即執行 — 不必硬寫每個全域名)
//   • 切市場 TW/US、載入任意輸入代碼
// ↑↓ 選擇、Enter 執行、Esc 關閉。延伸既有 hotkeys,自包含低風險。
// 狀態用裸 S;載入用全域 loadSym。
// ============================================================
(function () {
  'use strict';
  var sel = 0, items = [];

  function buildBase() {
    var base = [];
    // 工具列功能鈕(自動探索,含日後新增的)
    var btns = document.querySelectorAll('#pro-tools button, #pro-tools .probtn');
    [].forEach.call(btns, function (b) {
      var label = (b.textContent || '').trim();
      if (!label) return;
      base.push({ kind: '功能', label: label, run: function () { b.click(); } });
    });
    // 自選股 / 指數
    if (typeof S !== 'undefined' && Array.isArray(S.wl)) {
      S.wl.forEach(function (w) {
        base.push({
          kind: '自選', label: (w.name ? w.name + ' ' : '') + w.t,
          hint: w.m, run: function () { if (typeof loadSym === 'function') loadSym(w.t, w.m); }
        });
      });
    }
    // 切市場
    base.push({ kind: '指令', label: '切換市場 → 台股 (TW)', run: function () { switchMkt('TW'); } });
    base.push({ kind: '指令', label: '切換市場 → 美股 (US)', run: function () { switchMkt('US'); } });
    return base;
  }

  function switchMkt(m) {
    if (typeof S !== 'undefined') S.mkt = m;
    if (typeof setMktUI === 'function') try { setMktUI(m); } catch (e) {}
  }

  function filtered(q) {
    var base = buildBase();
    q = (q || '').trim().toLowerCase();
    var out = base;
    if (q) out = base.filter(function (it) { return it.label.toLowerCase().indexOf(q) >= 0; });
    // 任意代碼載入(輸入非空且看似代碼)
    if (q && /^[0-9a-z\^=\.]{1,12}$/i.test(q)) {
      out = [{ kind: '載入', label: '載入 "' + q.toUpperCase() + '"',
        run: function () { if (typeof loadSym === 'function') loadSym(q.toUpperCase(), (typeof S !== 'undefined' ? S.mkt : 'TW')); } }].concat(out);
    }
    return out.slice(0, 50);
  }

  function render() {
    var list = document.getElementById('cmdp-list');
    if (!list) return;
    if (sel >= items.length) sel = items.length - 1;
    if (sel < 0) sel = 0;
    list.innerHTML = items.map(function (it, i) {
      return '<div class="cmdp-row' + (i === sel ? ' sel' : '') + '" data-i="' + i + '">' +
        '<span class="cmdp-kind">' + it.kind + '</span>' +
        '<span class="cmdp-label">' + String(it.label).replace(/</g, '&lt;') + '</span>' +
        (it.hint ? '<span class="cmdp-hint">' + it.hint + '</span>' : '') + '</div>';
    }).join('') || '<div class="cmdp-empty">無相符項目</div>';
    [].forEach.call(list.querySelectorAll('.cmdp-row'), function (r) {
      r.onmouseenter = function () { sel = +r.dataset.i; paintSel(); };
      r.onclick = function () { exec(+r.dataset.i); };
    });
  }
  function paintSel() {
    var rows = document.querySelectorAll('#cmdp-list .cmdp-row');
    [].forEach.call(rows, function (r, i) { r.classList.toggle('sel', i === sel); });
  }

  function refresh() {
    var inp = document.getElementById('cmdp-input');
    items = filtered(inp ? inp.value : '');
    sel = 0;
    render();
  }

  function exec(i) {
    var it = items[i];
    close();
    if (it && typeof it.run === 'function') { try { it.run(); } catch (e) { console.warn('[cmdp]', e); } }
  }

  function open() {
    var ov = document.getElementById('cmdp-ov');
    if (!ov) return;
    ov.style.display = 'flex';
    var inp = document.getElementById('cmdp-input');
    inp.value = ''; inp.focus();
    refresh();
  }
  function close() {
    var ov = document.getElementById('cmdp-ov');
    if (ov) ov.style.display = 'none';
  }
  window.openCmdPalette = open;

  function ensureDom() {
    if (document.getElementById('cmdp-ov')) return;
    var st = document.createElement('style');
    st.textContent =
      '#cmdp-ov{position:fixed;inset:0;z-index:100000;display:none;justify-content:center;align-items:flex-start;background:rgba(0,0,0,.45)}' +
      '#cmdp-box{margin-top:12vh;width:min(560px,92vw);background:#161616;border:1px solid #3a3a3a;border-radius:10px;box-shadow:0 18px 50px rgba(0,0,0,.6);overflow:hidden}' +
      '#cmdp-input{width:100%;box-sizing:border-box;padding:13px 16px;background:#111;border:0;border-bottom:1px solid #2a2a2a;color:#eee;font-size:15px;outline:none}' +
      '#cmdp-list{max-height:50vh;overflow-y:auto}' +
      '.cmdp-row{display:flex;align-items:center;gap:9px;padding:8px 14px;cursor:pointer;font-size:13px}' +
      '.cmdp-row.sel{background:rgba(62,207,107,.14)}' +
      '.cmdp-kind{font-size:9px;color:#888;border:1px solid #333;border-radius:3px;padding:0 5px;min-width:26px;text-align:center}' +
      '.cmdp-label{color:#eee;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '.cmdp-hint{font-size:10px;color:#777}' +
      '.cmdp-empty{padding:14px;color:#888;font-size:12px;text-align:center}' +
      '#cmdp-foot{padding:6px 14px;border-top:1px solid #2a2a2a;color:#777;font-size:10px}';
    document.head.appendChild(st);
    var ov = document.createElement('div');
    ov.id = 'cmdp-ov';
    ov.innerHTML = '<div id="cmdp-box">' +
      '<input id="cmdp-input" placeholder="搜尋股票 / 指數 / 功能…  (Ctrl+K)" autocomplete="off">' +
      '<div id="cmdp-list"></div>' +
      '<div id="cmdp-foot">↑↓ 選擇 · Enter 執行 · Esc 關閉</div></div>';
    document.body.appendChild(ov);
    ov.addEventListener('click', function (e) { if (e.target === ov) close(); });
    var inp = ov.querySelector('#cmdp-input');
    inp.addEventListener('input', refresh);
    inp.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { sel++; if (sel >= items.length) sel = 0; paintSel(); scrollSel(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { sel--; if (sel < 0) sel = items.length - 1; paintSel(); scrollSel(); e.preventDefault(); }
      else if (e.key === 'Enter') { exec(sel); e.preventDefault(); }
      else if (e.key === 'Escape') { close(); e.preventDefault(); }
    });
  }
  function scrollSel() {
    var r = document.querySelector('#cmdp-list .cmdp-row.sel');
    if (r && r.scrollIntoView) r.scrollIntoView({ block: 'nearest' });
  }

  // 全域熱鍵 Ctrl/Cmd+K
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      ensureDom();
      var ov = document.getElementById('cmdp-ov');
      if (ov && ov.style.display === 'flex') close(); else open();
    }
  });

  // 工具列鈕(可點亦可 Ctrl+K)
  (function inject() {
    if (!document.getElementById('pro-tools')) return setTimeout(inject, 150);
    if (document.getElementById('btn-cmdp')) return;
    ensureDom();
    var b = document.createElement('button');
    b.id = 'btn-cmdp';
    b.className = 'probtn';
    b.title = '指令面板 — 搜尋股票/功能 (Ctrl+K)';
    b.textContent = '⌘ 指令';
    b.onclick = open;
    document.getElementById('pro-tools').appendChild(b);
  })();
})();

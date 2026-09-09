// ============================================================
// Stock Terminal v3.9 Phase-3 — 可拖拉功能視窗 (Draggable Windows)
// ------------------------------------------------------------
// 讓功能 modal(資金流/供應鏈/個股期/回測…)可用標題列拖曳移動,位置記到 localStorage,
// 下次開啟還原;標題列雙擊 = 重置回置中。
// 做法:單一 mousedown 事件委派 — 只對「position:fixed 全螢幕覆蓋層裡置中的 box」
//   的 h3/h4 標題啟用,不動核心版面、不碰會重建的 renderRpanel。漏接亦不破壞原行為。
// ============================================================
(function () {
  'use strict';
  var LS = 'stock_winpos_v3';
  var store = {};
  try { store = JSON.parse(localStorage.getItem(LS) || '{}'); } catch (e) {}
  function save() { try { localStorage.setItem(LS, JSON.stringify(store)); } catch (e) {} }

  function keyOf(box) {
    return box.id || (box.querySelector('h3,h4') ? box.querySelector('h3,h4').textContent.trim().slice(0, 24) : null);
  }

  // 找「可拖曳的 box」:標題的祖先 div,其 parent 為 fixed 全螢幕覆蓋層
  function boxFrom(heading) {
    // 原生對話框自行管理版面；不可把其內容誤認為舊式覆蓋視窗。
    if (heading.closest('dialog')) return null;
    var box = heading.closest('div');
    while (box) {
      var p = box.parentElement;
      if (p) {
        var cs = getComputedStyle(p);
        if (cs.position === 'fixed') return box;   // box 的父層是全螢幕 overlay → box 即視窗
      }
      box = box.parentElement && box.parentElement.closest('div');
    }
    return null;
  }

  function makeAbsolute(box) {
    // 把原本被 flex 置中的 box 改成絕對定位(以 fixed parent 為定位基準)
    var r = box.getBoundingClientRect();
    var pr = box.parentElement.getBoundingClientRect();
    box.style.position = 'absolute';
    box.style.margin = '0';
    box.style.left = (r.left - pr.left) + 'px';
    box.style.top = (r.top - pr.top) + 'px';
  }

  function applySaved(box) {
    var k = keyOf(box);
    if (k && store[k]) {
      box.style.position = 'absolute';
      box.style.margin = '0';
      box.style.left = store[k].x + 'px';
      box.style.top = store[k].y + 'px';
    }
  }

  var drag = null;
  document.addEventListener('mousedown', function (e) {
    if (e.button !== 0) return;
    var h = e.target.closest && e.target.closest('h3,h4');
    if (!h) return;
    // 標題裡的按鈕(關閉/重整)不觸發拖曳
    if (e.target.closest('button,a,input,select')) return;
    var box = boxFrom(h);
    if (!box) return;
    if (getComputedStyle(box).position !== 'absolute') makeAbsolute(box);
    var pr = box.parentElement.getBoundingClientRect();
    drag = {
      box: box,
      dx: e.clientX - (box.getBoundingClientRect().left),
      dy: e.clientY - (box.getBoundingClientRect().top),
      pr: pr,
    };
    h.style.cursor = 'grabbing';
    e.preventDefault();
  });

  document.addEventListener('mousemove', function (e) {
    if (!drag) return;
    var x = e.clientX - drag.pr.left - drag.dx;
    var y = e.clientY - drag.pr.top - drag.dy;
    // 夾在可視範圍內(留 20px 邊)
    var bw = drag.box.offsetWidth, bh = drag.box.offsetHeight;
    x = Math.max(-bw + 60, Math.min(x, drag.pr.width - 60));
    y = Math.max(0, Math.min(y, drag.pr.height - 40));
    drag.box.style.left = x + 'px';
    drag.box.style.top = y + 'px';
  });

  document.addEventListener('mouseup', function () {
    if (!drag) return;
    var k = keyOf(drag.box);
    if (k) { store[k] = { x: parseFloat(drag.box.style.left) || 0, y: parseFloat(drag.box.style.top) || 0 }; save(); }
    var h = drag.box.querySelector('h3,h4'); if (h) h.style.cursor = '';
    drag = null;
  });

  // 標題列雙擊 → 重置回置中(清除記憶)
  document.addEventListener('dblclick', function (e) {
    var h = e.target.closest && e.target.closest('h3,h4');
    if (!h) return;
    if (e.target.closest('button,a,input,select')) return;
    var box = boxFrom(h);
    if (!box) return;
    box.style.position = ''; box.style.margin = ''; box.style.left = ''; box.style.top = '';
    var k = keyOf(box);
    if (k && store[k]) { delete store[k]; save(); }
  });

  // 視窗開啟時套用記憶位置:監看新加入/顯示的 overlay
  var mo = new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      [].forEach.call(m.addedNodes || [], function (n) {
        if (n.nodeType !== 1) return;
        var hs = n.querySelectorAll ? n.querySelectorAll('h3,h4') : [];
        [].forEach.call(hs, function (h) { var b = boxFrom(h); if (b) applySaved(b); });
      });
    });
  });
  try { mo.observe(document.body, { childList: true, subtree: true }); } catch (e) {}

  // 標題列加 grab 游標提示
  var st = document.createElement('style');
  st.textContent = '.modal h3,.modal h4,[id$="-box"] h3,[id$="-modal"] h3{cursor:grab}';
  document.head.appendChild(st);
})();

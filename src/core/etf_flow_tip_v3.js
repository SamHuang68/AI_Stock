// ============================================================
// Stock Terminal — 自選股 ETF 增減碼徽章浮動視窗
// ------------------------------------------------------------
// 自選股 chip 上的綠「+N」/紅「-N」徽章 = 有 N 檔主動 ETF 新增/移除這支股票。
// 本模組在徽章上加浮動視窗:hover(或點擊)即列出「是哪幾檔 ETF」,
// 並可點視窗內任一 ETF 直接載入其線型(兼具超連結)。
// 資料來源:S.etfDelta(/etf-delta);不修改會被 build 重生的 base html,
// 改用「包裝 renderWl + 事件委派」非侵入式掛載。
// ============================================================
(function () {
  'use strict';

  // 取某股被哪些 ETF 新增/移除/加碼/減碼(回傳含 ETF 代號與名稱)
  function getEtfFlowDetailForStock(code) {
    // S 是詞法全域(非 window.S),用裸 S 存取
    if (typeof S === 'undefined' || !S || !S.etfDelta) return null;
    var added = [], removed = [], incre = [], decre = [];
    (S.etfDelta.etfs || []).forEach(function (e) {
      var meta = { code: e.code, name: e.name };
      if ((e.new || []).some(function (s) { return s.code === code; })) added.push(meta);
      if ((e.removed || []).some(function (s) { return s.code === code; })) removed.push(meta);
      var ch = (e.changed || []).find(function (s) { return s.code === code; });
      if (ch && ch.delta != null) {
        var m2 = { code: e.code, name: e.name, delta: ch.delta };
        if (ch.delta > 0) incre.push(m2); else if (ch.delta < 0) decre.push(m2);
      }
    });
    return { added: added, removed: removed, incre: incre, decre: decre };
  }
  window.getEtfFlowDetailForStock = getEtfFlowDetailForStock;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function etfLabel(e) {
    var nm = (e.name && e.name !== e.code) ? ' ' + e.name : '';
    var dl = (e.delta != null) ? ' <span style="opacity:.7">Δ' + (e.delta > 0 ? '+' : '') + e.delta + '%</span>' : '';
    return esc(e.code) + esc(nm) + dl;
  }
  function stockName(sym) {
    if (typeof S !== 'undefined' && S && S.wl) { var w = S.wl.find(function (x) { return x.t === sym; }); if (w && w.name) return w.name; }
    return '';
  }

  // ── 浮動視窗 ──────────────────────────────────────────────
  function tipEl() {
    var t = document.getElementById('etf-flow-tip');
    if (t) return t;
    var st = document.createElement('style'); st.textContent =
      '#etf-flow-tip{position:fixed;z-index:10001;display:none;max-width:300px;background:#0d1117;border:1px solid #2f4a6e;' +
      'border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.55);padding:9px 11px;font-family:monospace;font-size:11px;color:#cbd5e1;line-height:1.6}' +
      '#etf-flow-tip .eft-h{font-weight:700;color:#e8e8e8;margin-bottom:4px;font-size:11.5px}' +
      '#etf-flow-tip .eft-sec{margin-top:4px}' +
      '#etf-flow-tip .eft-item{display:inline-block;margin:2px 4px 0 0;padding:1px 6px;background:rgba(255,255,255,.06);border-radius:3px;cursor:pointer}' +
      '#etf-flow-tip .eft-item:hover{background:rgba(96,165,250,.22)}' +
      '.etf-flow-badge{cursor:pointer;text-decoration:underline dotted transparent}' +
      '.etf-flow-badge:hover{filter:brightness(1.25)}';
    document.head.appendChild(st);
    t = document.createElement('div'); t.id = 'etf-flow-tip';
    document.body.appendChild(t);
    // 視窗內點 ETF → 載入線型
    t.addEventListener('click', function (e) {
      var it = e.target.closest('.eft-item'); if (!it) return;
      var c = it.getAttribute('data-etf');
      if (c && typeof window.loadSym === 'function') { window.loadSym(c, 'TW'); hideTip(); }
    });
    // 滑入視窗時不關閉
    t.addEventListener('mouseenter', function () { clearTimeout(_hideTimer); });
    t.addEventListener('mouseleave', hideTip);
    return t;
  }

  var _hideTimer = null;
  function hideTip() { var t = document.getElementById('etf-flow-tip'); if (t) t.style.display = 'none'; }

  function buildHtml(sym, d) {
    var nm = stockName(sym);
    var h = '<div class="eft-h">🧩 ETF 動向 · ' + esc(sym) + (nm ? ' ' + esc(nm) : '') + '</div>';
    function sec(arr, color, label) {
      if (!arr.length) return '';
      return '<div class="eft-sec"><span style="color:' + color + ';font-weight:700">' + label + ' (' + arr.length + ')</span><div>' +
        arr.map(function (e) { return '<span class="eft-item" data-etf="' + esc(e.code) + '" title="載入 ' + esc(e.code) + ' 線型">' + etfLabel(e) + '</span>'; }).join('') +
        '</div></div>';
    }
    h += sec(d.removed, '#f87171', '🔴 移除');
    h += sec(d.decre, '#fca5a5', '－減碼');
    h += sec(d.added, '#3ecf6b', '🟢 新增');
    h += sec(d.incre, '#86efac', '＋加碼');
    if (!d.removed.length && !d.added.length && !d.incre.length && !d.decre.length) h += '<div style="color:#667">本交易日無 ETF 異動</div>';
    h += '<div style="margin-top:6px;color:#5a6a82;font-size:9px">點 ETF 代號可載入其線型 · 資料:當日各主動 ETF 持股異動</div>';
    return h;
  }

  function showTip(badge, sym) {
    if (!sym) return;
    var d = getEtfFlowDetailForStock(sym); if (!d) return;
    var t = tipEl();
    t.innerHTML = buildHtml(sym, d);
    t.style.display = 'block';
    var r = badge.getBoundingClientRect();
    var tw = t.offsetWidth, th = t.offsetHeight;
    var left = Math.min(r.left, window.innerWidth - tw - 8);
    var top = r.bottom + 6;
    if (top + th > window.innerHeight - 8) top = Math.max(8, r.top - th - 6); // 空間不足往上翻
    t.style.left = Math.max(8, left) + 'px';
    t.style.top = top + 'px';
  }

  // 動態判斷:某 span 是否為「自選股 ETF 增減碼徽章」(文字 +N/-N 且在 .wlchip 內)。
  // 用純事件委派,完全不需包裝 renderWl,任何重繪/時機都穩。
  function badgeFromEvent(e) {
    var el = e.target;
    if (!el || el.nodeType !== 1 || el.tagName !== 'SPAN') return null;
    var txt = (el.textContent || '').trim();
    if (!/^[+-]\d+$/.test(txt)) return null;          // 排除帶 % 的漲跌、其他文字
    var chip = el.closest && el.closest('.wlchip'); if (!chip) return null;
    var sym = chip.getAttribute('data-sym'); if (!sym) return null;
    return { el: el, sym: sym };
  }

  document.addEventListener('mouseover', function (e) {
    var b = badgeFromEvent(e);
    if (b) { b.el.style.cursor = 'pointer'; clearTimeout(_hideTimer); showTip(b.el, b.sym); }
  });
  document.addEventListener('mouseout', function (e) {
    if (badgeFromEvent(e)) { _hideTimer = setTimeout(hideTip, 250); }
  });
  // 觸控/點擊:切換浮動視窗,並擋掉冒泡到 chip 的 loadSym(不要誤載個股)
  document.addEventListener('click', function (e) {
    var b = badgeFromEvent(e);
    if (b) {
      e.stopPropagation(); e.preventDefault();
      var t = document.getElementById('etf-flow-tip');
      if (t && t.style.display === 'block') hideTip(); else showTip(b.el, b.sym);
    }
  }, true);
  window.addEventListener('scroll', hideTip, true);

  console.log('[etf-flow-tip] 自選股 ETF 增減碼徽章浮動視窗就緒(事件委派)');
})();

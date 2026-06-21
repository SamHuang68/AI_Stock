// ============================================================
// Stock Terminal v3.9 — 焦點掃描精靈 (Focus Scanner Wizard)
// ------------------------------------------------------------
// 全台股跑「多訊號組合」自動評分,找出最強做多/做空焦點股並標方向。
// 訊號:趨勢排列/均線交叉/突破破底/帶量/RSI(後端 /focus 評分)。
// 工具列 🎯 焦點。點列載入 K 線。狀態用全域 loadSym。
// ============================================================
(function () {
  'use strict';
  var SRV = window.SERVER || 'http://localhost:18432';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }
  function mClose() { var m = document.getElementById('focus-modal'); if (m) m.style.display = 'none'; }

  function col(title, color, rows) {
    var h = '<div style="border-right:1px solid #1a1a1a">'
      + '<div style="position:sticky;top:0;background:#080c14;padding:8px 14px;font-weight:700;color:' + color + ';font-size:13px;border-bottom:1px solid #222;z-index:1">' + title + ' · ' + rows.length + '</div>';
    if (!rows.length) h += '<div style="padding:18px;color:#667;font-size:12px;text-align:center">無符合(綜合分數需 ≥ 3)</div>';
    rows.forEach(function (r) {
      var sigs = (r.signals || []).map(function (s) { return '<span style="display:inline-block;background:rgba(255,255,255,.06);color:#aab;border-radius:3px;padding:0 5px;margin:1px 2px 0 0;font-size:9px">' + esc(s) + '</span>'; }).join('');
      var up = (r.changePct >= 0);
      h += '<div data-sym="' + esc(r.sym) + '" style="padding:7px 14px;border-bottom:1px solid #161616;cursor:pointer" onmouseover="this.style.background=\'rgba(255,255,255,.04)\'" onmouseout="this.style.background=\'\'">'
        + '<div style="display:flex;align-items:center;gap:8px;font-family:monospace;font-size:12px">'
        + '<b style="color:#e8e8e8;min-width:52px">' + esc(r.sym) + '</b>'
        + '<span style="flex:1;color:#bbb;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(r.name) + '</span>'
        + '<span style="color:' + (up ? '#f87171' : '#3ecf6b') + '">' + (up ? '+' : '') + r.changePct + '%</span>'
        + '<span style="color:' + color + ';font-weight:700;min-width:34px;text-align:right">' + r.score + '★</span></div>'
        + '<div style="margin-top:2px">' + sigs + (r.rsi14 != null ? '<span style="color:#778;font-size:9px;margin-left:4px">RSI ' + r.rsi14 + '</span>' : '') + '</div></div>';
    });
    return h + '</div>';
  }

  function run() {
    var sec = (document.getElementById('fc-sector') || {}).value || '';
    var st = document.getElementById('fc-status'), body = document.getElementById('fc-body');
    st.textContent = '掃描中…(全台股跑多訊號組合,首次約 1~2 分鐘)'; body.innerHTML = '';
    fetch(SRV + '/focus' + (sec ? ('?sector=' + encodeURIComponent(sec)) : ''), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) { st.textContent = '掃描失敗'; return; }
        st.textContent = '掃描 ' + j.scanned + ' 檔 · 做多焦點 ' + j.buy.length + ' · 做空焦點 ' + j.short.length + '(點列載入 K 線)';
        body.innerHTML = col('🟢 做多焦點 (Buy)', '#3ecf6b', j.buy) + col('🔴 做空焦點 (Short)', '#f87171', j.short);
        body.querySelectorAll('[data-sym]').forEach(function (el) {
          el.onclick = function () { var c = el.getAttribute('data-sym'); if (typeof loadSym === 'function') { loadSym(c, 'TW'); mClose(); } };
        });
      }).catch(function (e) { st.textContent = '掃描失敗:' + e.message; });
  }

  function open() {
    var m = document.getElementById('focus-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'focus-modal'; m.className = 'modal';
      m.style.cssText = 'position:fixed;inset:0;background:rgba(6,10,18,.85);z-index:100;display:flex;align-items:center;justify-content:center';
      m.innerHTML = '<div id="fc-box" style="background:#0d1117;border:1px solid #8a6d12;border-radius:10px;width:min(960px,94vw);height:84vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 18px 50px rgba(0,0,0,.6)">'
        + '<div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #222;background:#080c14">'
        + '<h3 style="margin:0;font-family:monospace;color:#f5c518;font-size:14px">🎯 焦點掃描 · 訊號組合自動選股</h3>'
        + '<div><select id="fc-sector" style="background:#161616;border:1px solid #333;color:#ccc;border-radius:5px;padding:3px 7px;font-size:11px;margin-right:6px"></select>'
        + '<button id="fc-run" style="background:#2a230a;border:1px solid #8a6d12;color:#f5c518;border-radius:5px;padding:4px 12px;cursor:pointer">▶ 掃描</button> '
        + '<button id="fc-close" style="background:#334155;border:0;color:#fff;border-radius:5px;padding:4px 10px;cursor:pointer">關閉</button></div></div>'
        + '<div id="fc-status" style="padding:8px 16px;color:#8aa;font-size:11px;font-family:monospace">選產業(可全部)後按「掃描」。多訊號:多/空頭排列、均線交叉、突破破底、帶量、RSI。</div>'
        + '<div id="fc-body" style="flex:1;overflow:auto;display:grid;grid-template-columns:1fr 1fr;gap:0"></div></div>';
      document.body.appendChild(m);
      m.addEventListener('click', function (e) { if (e.target === m) mClose(); });
      document.getElementById('fc-close').onclick = mClose;
      document.getElementById('fc-run').onclick = run;
      fetch(SRV + '/screener').then(function (r) { return r.json(); }).then(function (j) {
        var sel = document.getElementById('fc-sector'); if (!sel) return;
        var opts = ['<option value="">全部</option>', '<option value="__TECH__">科技電子(整合)</option>'];
        (j.sectors || []).forEach(function (s) { opts.push('<option value="' + esc(s) + '">' + esc(s) + '</option>'); });
        sel.innerHTML = opts.join('');
      }).catch(function () {});
    }
    m.style.display = 'flex';
  }
  window.focusScanOpen = open;

  /* v3.9: 改用 Toolbar 註冊表(模組化) — 取代手寫 #pro-tools 注入樣板 */
  (function () {
    var spec = { id: 'btn-focus', label: '🎯 焦點', cat: 'pin',
                 title: '焦點掃描:多訊號組合自動找做多/做空焦點股 (v3.9)', onclick: open };
    (window.Toolbar ? window.Toolbar.register
      : function (s) { (window.__tbQueue = window.__tbQueue || []).push(s); })(spec);
  })();
})();

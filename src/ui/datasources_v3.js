// ============================================================
// Stock Terminal — 資料源管理(集中表 + 一鍵更新)
// ------------------------------------------------------------
// 工具列「🗄 資料源」開啟:列出全 app 每個資料源的 提供者 / 可靠度 / 最後更新 / 筆數,
// 可更新的提供一鍵 refresh(重抓可靠來源),確保資料來自可靠源且能即時更新。
// 來源清單與更新動作由後端 /datasources、/datasource/refresh 決定(單一真理來源)。
// ============================================================
(function () {
  'use strict';
  var SRV = window.SERVER || 'http://localhost:18432';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function ago(ts) {
    if (!ts) return '—';
    var s = Math.floor(Date.now() / 1000) - ts;
    if (s < 90) return '剛剛';
    if (s < 3600) return Math.floor(s / 60) + ' 分前';
    if (s < 86400) return Math.floor(s / 3600) + ' 小時前';
    return Math.floor(s / 86400) + ' 天前';
  }
  var RELY = {
    official: { t: '官方', c: '#4ADE80' },
    vendor: { t: '第三方', c: '#FB923C' },
    local: { t: '本地', c: '#94a3b8' },
  };
  var KIND = { file: '本地快取', db: '時序庫', daily: '每日自動', live: '即時' };

  function injectStyle() {
    if (document.getElementById('ds-style')) return;
    var s = document.createElement('style'); s.id = 'ds-style'; s.textContent =
      '#ds-modal{position:fixed;inset:0;background:rgba(6,10,18,.72);z-index:10000;display:none;align-items:center;justify-content:center}' +
      '#ds-box{background:#0d1117;border:1px solid #2f4a6e;border-radius:10px;width:min(680px,94vw);max-height:88vh;overflow:auto;padding:16px 18px;font-family:monospace;color:#cbd5e1;box-shadow:0 16px 44px rgba(0,0,0,.55)}' +
      '#ds-box h3{margin:0 0 10px;font-size:15px;color:#cfe3ff;display:flex;justify-content:space-between;align-items:center}' +
      '#ds-box h3 .x{cursor:pointer;color:#8aa;font-size:18px}' +
      '#ds-tbl{width:100%;border-collapse:collapse;font-size:11px}' +
      '#ds-tbl td{border-bottom:1px solid #1a2740;padding:8px 6px;vertical-align:top}' +
      '#ds-tbl .nm{color:#e8e8e8;font-weight:700}' +
      '#ds-tbl .pv{color:#8aa;font-size:9.5px;margin-top:2px}' +
      '#ds-tbl .ds{color:#5a6a82;font-size:9px;margin-top:3px;line-height:1.5}' +
      '.ds-badge{display:inline-block;padding:0 6px;border-radius:3px;font-size:8.5px;font-weight:700;margin-right:4px}' +
      '.ds-btn{background:#13233b;border:1px solid #2f4a6e;color:#cfe3ff;border-radius:5px;padding:4px 10px;cursor:pointer;font-family:monospace;font-size:10.5px;white-space:nowrap}' +
      '.ds-btn:disabled{opacity:.5;cursor:default}' +
      '#ds-foot{margin-top:10px;display:flex;justify-content:space-between;align-items:center;gap:8px}' +
      '#ds-st{font-size:10px;color:#8aa;min-height:14px;flex:1}';
    document.head.appendChild(s);
  }

  var _data = null;
  async function fetchList() {
    try {
      var d = await fetch(SRV + '/datasources', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; });
      _data = d; return d;
    } catch (e) { _data = null; return null; }
  }

  function rowHtml(s) {
    var rel = RELY[s.reliability] || RELY.local;
    var st = s.status || {};
    var when = (s.kind === 'live') ? '即時' : (s.kind === 'daily') ? '每日自動' : ago(st.updated);
    var cnt = (s.kind === 'live' || s.kind === 'daily') ? '' : ((st.count != null ? st.count.toLocaleString() : '0') + ' 筆');
    var btn = s.updatable
      ? '<button class="ds-btn" data-ds="' + esc(s.id) + '">↻ 更新</button>'
      : '<span style="color:#5a6a82;font-size:9px">' + (s.kind === 'live' ? '免更新' : s.kind === 'daily' ? '自動' : '手動') + '</span>';
    return '<tr><td><div class="nm">' + esc(s.name) + '</div>' +
      '<div class="pv"><span class="ds-badge" style="background:' + rel.c + '22;color:' + rel.c + '">' + rel.t + '</span>' + esc(s.provider) + '</div>' +
      '<div class="ds">' + esc(s.desc) + '</div></td>' +
      '<td style="text-align:right;white-space:nowrap"><div style="color:#cbd5e1">' + when + '</div><div style="color:#5a6a82;font-size:9px;margin-top:2px">' + cnt + ' · ' + (KIND[s.kind] || '') + '</div></td>' +
      '<td style="text-align:right">' + btn + '</td></tr>';
  }

  function render() {
    var box = document.getElementById('ds-box');
    if (!_data || !_data.sources) {
      box.querySelector('#ds-list').innerHTML = '<div style="padding:18px;color:#fca5a5;font-size:11px;line-height:1.7">無法取得資料源清單。<br>若 /datasources 回 404,代表後端尚未載入新端點 —— 請<b>重啟 server</b>(關掉黑視窗 → 跑 start_terminal_v3.bat)。</div>';
      return;
    }
    var updatable = _data.sources.filter(function (s) { return s.updatable; });
    box.querySelector('#ds-list').innerHTML = '<table id="ds-tbl"><tbody>' + _data.sources.map(rowHtml).join('') + '</tbody></table>';
    box.querySelectorAll('.ds-btn[data-ds]').forEach(function (b) { b.onclick = function () { doRefresh(b.getAttribute('data-ds'), b); }; });
    var allBtn = document.getElementById('ds-all');
    if (allBtn) allBtn.onclick = async function () { for (var i = 0; i < updatable.length; i++) { await doRefresh(updatable[i].id, null); } };
  }

  async function doRefresh(id, btn) {
    var stEl = document.getElementById('ds-st');
    if (btn) { btn.disabled = true; btn.textContent = '更新中…'; }
    if (stEl) stEl.textContent = '更新 ' + id + '…(從可靠來源重抓)';
    try {
      var r = await fetch(SRV + '/datasource/refresh', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id })
      }).then(function (x) { return x.json(); });
      if (stEl) stEl.textContent = r && r.ok
        ? (r.started ? ('✓ ' + id + ' 已在背景更新,稍後重開此視窗看結果' + (r.note ? '(' + r.note + ')' : '')) : ('✓ ' + id + ' 更新完成' + (r.count != null ? '(' + r.count.toLocaleString() + ' 筆)' : '')))
        : ('⚠ ' + id + ':' + ((r && r.error) || '失敗'));
    } catch (e) { if (stEl) stEl.textContent = '⚠ ' + e.message; }
    await fetchList(); render();
  }

  async function open() {
    injectStyle();
    var m = document.getElementById('ds-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'ds-modal';
      m.innerHTML = '<div id="ds-box"><h3>🗄 資料源管理<span class="x" onclick="document.getElementById(\'ds-modal\').style.display=\'none\'">×</span></h3>' +
        '<div style="font-size:9.5px;color:#5a6a82;margin-bottom:8px">每個資料源的提供者、可靠度與最後更新;可更新的一鍵重抓可靠來源。</div>' +
        '<div id="ds-list"><div style="padding:18px;color:#8aa">載入中…</div></div>' +
        '<div id="ds-foot"><span id="ds-st"></span><button class="ds-btn" id="ds-all">↻ 全部更新</button></div></div>';
      document.body.appendChild(m);
      m.addEventListener('click', function (e) { if (e.target === m) m.style.display = 'none'; });
    }
    m.style.display = 'flex';
    await fetchList(); render();
  }
  window.datasourcesOpen = open;

  (function () {
    var spec = { id: 'btn-datasources', label: '🗄 資料源', cat: 'pin', title: '資料源管理:來源/可靠度/最後更新 + 一鍵更新', onclick: open };
    (window.Toolbar ? window.Toolbar.register : function (s) { (window.__tbQueue = window.__tbQueue || []).push(s); })(spec);
  })();
})();

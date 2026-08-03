/* ============================================================================
 * scan_v5.js  —  Stock Terminal 5.0 Stage 7：三合一選股側欄
 * ----------------------------------------------------------------------------
 * 資料：POST /screen3（技術 × 基本面 × 籌碼，與 screener3_v3 同後端）
 * Meta：GET /screener（產業清單）
 * 掛載：#mount-scan；側欄「選股」
 * 不取代工具列模態窗；兩者可並存（表單 id 用 sc-* 避免衝突）
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var sectors = [];
  var lastResults = [];

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
    });
  }

  function injectCSS() {
    if ($('scan-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'scan-v5-css';
    s.textContent =
      '#view-scan.sv-panel{max-width:1120px;padding:18px 22px 28px}' +
      '#sc-root{font-family:\'JetBrains Mono\',monospace;color:var(--text)}' +
      '#sc-root .sc-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}' +
      '#sc-root .sc-kicker{font-size:10px;color:var(--gold);letter-spacing:2px;margin-bottom:4px}' +
      '#sc-root .sc-title{font-family:\'Noto Serif TC\',serif;font-size:26px;font-weight:700;color:var(--thi)}' +
      '#sc-root .sc-sub{font-size:11px;color:var(--tlo);margin-top:4px}' +
      '#sc-root .sc-actions{display:flex;gap:8px;flex-wrap:wrap}' +
      '#sc-root .sc-btn{padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;font-family:\'JetBrains Mono\',monospace;cursor:pointer}' +
      '#sc-root .sc-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#sc-root .sc-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#sc-root .sc-btn.primary:hover{background:#FBBF24}' +
      '#sc-root .sc-cols{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:8px 0}' +
      '#sc-root .sc-grp{border:1px solid var(--border);border-radius:8px;padding:10px 12px;background:var(--bg2)}' +
      '#sc-root .sc-grp h4{margin:0 0 8px;font-size:12px;color:var(--gold)}' +
      '#sc-root .sc-grp label{display:flex;align-items:center;gap:6px;margin:5px 0;font-size:11px;color:var(--text);flex-wrap:wrap}' +
      '#sc-root .sc-grp input[type=number]{width:58px;background:var(--bg);border:1px solid var(--border);' +
        'color:var(--thi);border-radius:4px;padding:3px 5px;font-family:inherit}' +
      '#sc-root .sc-grp .hint{font-size:9px;color:var(--tlo);margin-top:8px;line-height:1.5}' +
      '#sc-root .sc-bar{display:flex;gap:8px;align-items:center;margin:10px 0;flex-wrap:wrap}' +
      '#sc-root .sc-bar select{background:var(--bg);border:1px solid var(--border);color:var(--text);' +
        'border-radius:5px;padding:6px 8px;font-family:inherit;font-size:11px}' +
      '#sc-root #sc-msg{font-size:11px;color:var(--tlo);min-height:16px;margin:4px 0 8px}' +
      '#sc-root #sc-results{overflow:auto;max-height:min(52vh,480px);border:1px solid var(--border);border-radius:8px;background:var(--bg2)}' +
      '#sc-root .sc-rtop{display:flex;align-items:center;gap:10px;padding:8px 10px;position:sticky;top:0;' +
        'background:var(--bg2);border-bottom:1px solid var(--border);z-index:1}' +
      '#sc-root table{width:100%;border-collapse:collapse;font-size:11px}' +
      '#sc-root th,#sc-root td{padding:5px 6px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}' +
      '#sc-root th{color:var(--tlo);position:sticky;top:37px;background:var(--bg);font-weight:600}' +
      '#sc-root td.up{color:var(--red)}#sc-root td.dn{color:var(--green)}' +
      '#sc-root .sc-code{color:var(--gold);font-weight:700;cursor:pointer;text-align:left}' +
      '#sc-root .sc-nm{color:var(--tlo);text-align:left;max-width:100px;overflow:hidden;text-overflow:ellipsis}' +
      '#sc-root .sc-add{background:var(--bg3);border:1px solid var(--border);color:var(--green);border-radius:4px;cursor:pointer;padding:1px 7px}' +
      '#sc-root .sc-note{font-size:9px;color:var(--tlo);line-height:1.65;margin-top:12px}' +
      '#sc-root .sc-presets{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 4px}' +
      '#sc-root .sc-chip{padding:4px 9px;border:1px solid var(--border);border-radius:999px;background:transparent;' +
        'color:var(--tlo);font-size:10px;cursor:pointer;font-family:inherit}' +
      '#sc-root .sc-chip:hover{border-color:var(--gold-m);color:var(--gold)}' +
      '@media (max-width:900px){#sc-root .sc-cols{grid-template-columns:1fr}}';
    document.head.appendChild(s);
  }

  function loadMeta() {
    return fetch(SRV + '/screener', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (r) {
        if (r && r.sectors) sectors = r.sectors || [];
        fillSectors();
        return r;
      })
      .catch(function () { return null; });
  }

  function fillSectors() {
    var sel = $('sc-sector');
    if (!sel) return;
    var cur = sel.value;
    sel.innerHTML = '<option value="">全部產業</option><option value="__TECH__">科技電子整合</option>' +
      sectors.map(function (s) { return '<option value="' + esc(s) + '">' + esc(s) + '</option>'; }).join('');
    if (cur) sel.value = cur;
  }

  function val(id) { var el = $(id); return el ? el.value.trim() : ''; }
  function ck(id) { var el = $(id); return el ? el.checked : false; }
  function numOrNull(s) { return s === '' ? null : parseFloat(s); }

  function readForm() {
    return {
      tech: {
        aboveSma20: ck('sc-sma20'),
        aboveSma60: ck('sc-sma60'),
        bullishAlign: ck('sc-align'),
        newHigh20: ck('sc-high20'),
        rsiMin: numOrNull(val('sc-rsimin')),
        rsiMax: numOrNull(val('sc-rsimax')),
        volRatioMin: numOrNull(val('sc-volr'))
      },
      fund: {
        revYoyMin: numOrNull(val('sc-revyoy')),
        perMax: numOrNull(val('sc-permax')),
        yieldMin: numOrNull(val('sc-yield'))
      },
      chip: {
        trustBuyDays: numOrNull(val('sc-trust')),
        foreignBuyDays: numOrNull(val('sc-foreign'))
      },
      sector: val('sc-sector')
    };
  }

  function setChecked(id, on) { var el = $(id); if (el) el.checked = !!on; }
  function setVal(id, v) { var el = $(id); if (el) el.value = v == null ? '' : v; }

  function applyPreset(name) {
    ['sc-sma20', 'sc-sma60', 'sc-align', 'sc-high20'].forEach(function (id) { setChecked(id, false); });
    setVal('sc-rsimin', ''); setVal('sc-rsimax', ''); setVal('sc-volr', '');
    setVal('sc-revyoy', ''); setVal('sc-permax', ''); setVal('sc-yield', '');
    setVal('sc-trust', ''); setVal('sc-foreign', '');
    if (name === 'trend') {
      setChecked('sc-sma20', true); setChecked('sc-sma60', true); setChecked('sc-align', true);
      setVal('sc-rsimin', '45'); setVal('sc-rsimax', '75');
    } else if (name === 'breakout') {
      setChecked('sc-high20', true); setChecked('sc-sma20', true); setVal('sc-volr', '1.5');
    } else if (name === 'value') {
      setVal('sc-permax', '20'); setVal('sc-yield', '3'); setChecked('sc-sma60', true);
    } else if (name === 'chip') {
      setVal('sc-trust', '3'); setVal('sc-foreign', '3'); setChecked('sc-sma20', true);
    }
  }

  function cell(v, cls) {
    return '<td class="' + (cls || '') + '">' + (v == null || v === '' ? '—' : v) + '</td>';
  }

  function addWl(sym, batch) {
    if (typeof S === 'undefined' || !Array.isArray(S.wl)) return;
    if (!S.wl.find(function (w) { return w.t === sym && w.m === 'TW'; })) {
      S.wl.push({ t: sym, m: 'TW' });
    }
    if (typeof saveWl === 'function') saveWl();
    if (!batch && typeof renderWl === 'function') renderWl();
  }

  function openChart(sym) {
    if (typeof loadSym === 'function') {
      loadSym(sym, 'TW');
      if (window.ShellV5) window.ShellV5.go('chart');
    }
  }

  function renderResults(rows) {
    var el = $('sc-results');
    if (!el) return;
    if (!rows.length) {
      el.innerHTML = '<div style="color:var(--tlo);padding:18px;text-align:center">無符合條件的個股</div>';
      return;
    }
    var h = '<div class="sc-rtop"><button type="button" class="sc-btn" id="sc-addall">＋ 全部加入自選</button>' +
      '<span style="color:var(--tlo);font-size:10px">點代號載入線型 · 顯示前 ' + rows.length + ' 檔</span></div>';
    h += '<table><thead><tr><th>代號</th><th>名稱</th><th>價</th><th>漲跌</th><th>RSI</th><th>量比</th>' +
      '<th>營收YoY</th><th>PER</th><th>殖利</th><th>投信</th><th>外資</th><th></th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var chgCls = r.changePct >= 0 ? 'up' : 'dn';
      var streak = function (v) { return v == null ? '—' : (v > 0 ? '+' + v : v); };
      var chgAbs = r.changePct != null && Math.abs(r.changePct) < 30;
      h += '<tr>' +
        '<td class="sc-code" data-sym="' + esc(r.sym) + '">' + esc(r.sym) + '</td>' +
        '<td class="sc-nm">' + esc(r.name || '') + '</td>' +
        cell(r.close) +
        cell(chgAbs ? ((r.changePct >= 0 ? '+' : '') + r.changePct + '%') : '—', chgAbs ? chgCls : '') +
        cell(r.rsi14) + cell(r.volRatio) +
        cell(r.revYoy == null ? null : r.revYoy + '%', r.revYoy >= 0 ? 'up' : 'dn') +
        cell(r.per) +
        cell(r['yield'] == null ? null : r['yield'] + '%') +
        cell(streak(r.trustStreak), r.trustStreak > 0 ? 'up' : (r.trustStreak < 0 ? 'dn' : '')) +
        cell(streak(r.foreignStreak), r.foreignStreak > 0 ? 'up' : (r.foreignStreak < 0 ? 'dn' : '')) +
        '<td><button type="button" class="sc-add" data-sym="' + esc(r.sym) + '">＋</button></td></tr>';
    });
    h += '</tbody></table>';
    el.innerHTML = h;
    el.querySelectorAll('.sc-code').forEach(function (td) {
      td.onclick = function () { openChart(td.getAttribute('data-sym')); };
    });
    el.querySelectorAll('.sc-add').forEach(function (b) {
      b.onclick = function () { addWl(b.getAttribute('data-sym')); };
    });
    var addall = $('sc-addall');
    if (addall) {
      addall.onclick = function () {
        rows.forEach(function (r) { addWl(r.sym, true); });
        if (typeof renderWl === 'function') renderWl();
      };
    }
  }

  function scan() {
    var msg = $('sc-msg');
    var body = readForm();
    if (msg) msg.textContent = '掃描中…（全台股宇集，條件越多越慢）';
    var box = $('sc-results');
    if (box) box.innerHTML = '';
    fetch(SRV + '/screen3', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (r) {
        if (!r) { if (msg) msg.textContent = '掃描失敗（後端無回應）'; return; }
        lastResults = r.results || [];
        if (msg) {
          msg.innerHTML = '掃描 ' + r.scanned + ' 檔 → 技術通過 ' + r.techPass +
            ' → 交集 <b style="color:var(--gold)">' + r.matched + '</b> 檔' +
            (r.matched > 80 ? '（顯示前 80）' : '');
        }
        renderResults(lastResults);
      })
      .catch(function (e) {
        if (msg) msg.textContent = '掃描錯誤：' + (e.message || e);
      });
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-scan');
    if (!panel) return null;
    var mount = $('mount-scan');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-scan';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('sc-root')) {
      mount.innerHTML =
        '<div id="sc-root">' +
          '<div class="sc-head"><div>' +
            '<div class="sc-kicker">STOCK TERMINAL · 5.0-S7</div>' +
            '<div class="sc-title">三合一選股</div>' +
            '<div class="sc-sub">技術 × 基本面 × 籌碼 · 全台股宇集</div>' +
          '</div><div class="sc-actions">' +
            '<button type="button" class="sc-btn primary" id="sc-run">🔍 開始掃描</button>' +
            '<button type="button" class="sc-btn" data-shell-back>← 圖表</button>' +
          '</div></div>' +
          '<div class="sc-presets">' +
            '<button type="button" class="sc-chip" data-preset="trend">趨勢多頭</button>' +
            '<button type="button" class="sc-chip" data-preset="breakout">帶量突破</button>' +
            '<button type="button" class="sc-chip" data-preset="value">價值殖利</button>' +
            '<button type="button" class="sc-chip" data-preset="chip">法人連買</button>' +
            '<button type="button" class="sc-chip" data-preset="clear">清除條件</button>' +
          '</div>' +
          '<div class="sc-cols">' +
            '<div class="sc-grp"><h4>技術面</h4>' +
              '<label><input type="checkbox" id="sc-sma20"> 站上 SMA20</label>' +
              '<label><input type="checkbox" id="sc-sma60"> 站上 SMA60</label>' +
              '<label><input type="checkbox" id="sc-align"> 均線多頭排列</label>' +
              '<label><input type="checkbox" id="sc-high20"> 創 20 日新高</label>' +
              '<label>RSI ≥ <input type="number" id="sc-rsimin"> 且 ≤ <input type="number" id="sc-rsimax"></label>' +
              '<label>量比 ≥ <input type="number" id="sc-volr" step="0.1" placeholder="1.5"></label>' +
            '</div>' +
            '<div class="sc-grp"><h4>基本面</h4>' +
              '<label>月營收 YoY ≥ <input type="number" id="sc-revyoy" placeholder="20"> %</label>' +
              '<label>PER ≤ <input type="number" id="sc-permax" placeholder="30"></label>' +
              '<label>殖利率 ≥ <input type="number" id="sc-yield" step="0.1" placeholder="3"> %</label>' +
              '<div class="hint">TWSE 月營收／BWIBBU；ETF 通常無基本面。</div>' +
            '</div>' +
            '<div class="sc-grp"><h4>籌碼面</h4>' +
              '<label>投信連買 ≥ <input type="number" id="sc-trust" placeholder="3"> 天</label>' +
              '<label>外資連買 ≥ <input type="number" id="sc-foreign" placeholder="3"> 天</label>' +
              '<div class="hint">連續天數來自 chip_history（需每日累積）。</div>' +
            '</div>' +
          '</div>' +
          '<div class="sc-bar">' +
            '<select id="sc-sector"><option value="">全部產業</option><option value="__TECH__">科技電子整合</option></select>' +
            '<span style="color:var(--tlo);font-size:10px">空白條件=不限。建議至少勾 1～2 個技術條件。</span>' +
          '</div>' +
          '<div id="sc-msg"></div>' +
          '<div id="sc-results"></div>' +
          '<div class="sc-note">與工具列「選股策略 → 選股」同後端 /screen3。異常漲跌%（資料缺口）會顯示為 —。⚠ 非投資建議。</div>' +
        '</div>';

      var run = $('sc-run');
      if (run) run.onclick = scan;
      mount.querySelectorAll('[data-preset]').forEach(function (b) {
        b.onclick = function () {
          var p = b.getAttribute('data-preset');
          if (p === 'clear') applyPreset('');
          else applyPreset(p);
        };
      });
      // 預設帶趨勢條件，避免空白掃全庫過慢又無意義
      applyPreset('trend');
    }
    return $('sc-results');
  }

  function activate() {
    ensureMount();
    loadMeta();
    if (lastResults.length) renderResults(lastResults);
  }

  window.ScanV5 = {
    activate: activate,
    scan: scan,
    last: function () { return lastResults; }
  };

  // 工具列選股鈕：若殼層可用則導向側欄選股室
  (function hookToolbar() {
    var orig = window.screener3Open;
    window.screener3Open = function () {
      if (window.ShellV5 && typeof window.ShellV5.go === 'function') {
        window.ShellV5.go('scan');
        return;
      }
      if (typeof orig === 'function') orig();
    };
  })();

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'scan') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'scan') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 250); });
  else setTimeout(boot, 250);
})();

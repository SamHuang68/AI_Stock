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
  var sortState = { key: null, direction: 'original' };
  var SORT_COLUMNS = [
    { key: 'sym', label: '代號', type: 'text' },
    { key: 'name', label: '名稱', type: 'text' },
    { key: 'close', label: '價', type: 'number' },
    { key: 'changePct', label: '漲跌', type: 'number' },
    { key: 'rsi14', label: 'RSI', type: 'number' },
    { key: 'volRatio', label: '量比', type: 'number' },
    { key: 'revYoy', label: '營收YoY', type: 'number' },
    { key: 'per', label: 'PER', type: 'number' },
    { key: 'yield', label: '殖利', type: 'number' },
    { key: 'trustStreak', label: '投信', type: 'number' },
    { key: 'foreignStreak', label: '外資', type: 'number' }
  ];

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
    });
  }

  function injectCSS() {
    var s = $('scan-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'scan-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#view-scan.sv-panel.on{max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-scan,#mount-scan.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#sc-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);width:100%;max-width:none;margin:0;min-width:0;' +
        'box-sizing:border-box;flex:1;min-height:0;display:flex;flex-direction:column}' +
      '#sc-root .sc-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#sc-root .sc-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#sc-root .sc-kicker{display:none!important}' +
      '#sc-root .sc-title{font-family:\'Noto Serif TC\',serif;font-size:17px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#sc-root .sc-sub{font-size:11px;color:var(--tlo);margin:0}' +
      '#sc-root .sc-actions{display:flex;gap:4px;flex-wrap:nowrap;flex:0 0 auto}' +
      '#sc-root .sc-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;white-space:nowrap}' +
      '#sc-root .sc-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#sc-root .sc-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#sc-root .sc-btn.primary:hover{background:#FBBF24}' +
      '#sc-root .sc-layout{flex:1;min-height:0;display:grid;grid-template-columns:minmax(200px,22%) minmax(0,1fr);gap:4px;overflow:hidden}' +
      '#sc-root .sc-rail{min-height:0;overflow:auto;display:flex;flex-direction:column;gap:4px;padding-right:2px}' +
      '#sc-root .sc-main{min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#sc-root .sc-grp{border:1px solid var(--border);border-radius:6px;padding:5px 7px;background:var(--bg2)}' +
      '#sc-root .sc-grp h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px}' +
      '#sc-root .sc-grp label{display:flex;align-items:center;gap:4px;margin:2px 0;font-size:10px;color:var(--text);flex-wrap:wrap}' +
      '#sc-root .sc-grp input[type=number]{width:52px;background:var(--bg);border:1px solid var(--border);' +
        'color:var(--thi);border-radius:3px;padding:2px 4px;font-family:inherit;font-size:10px}' +
      '#sc-root .sc-grp .hint{font-size:10px;color:var(--tlo);margin-top:4px;line-height:1.4}' +
      '#sc-root .sc-bar{display:flex;gap:6px;align-items:center;margin:0 0 3px;flex:0 0 auto;flex-wrap:wrap}' +
      '#sc-root .sc-bar select{background:var(--bg);border:1px solid var(--border);color:var(--text);' +
        'border-radius:4px;padding:3px 6px;font-family:inherit;font-size:10px}' +
      '#sc-root #sc-msg{font-size:11px;color:var(--tlo);min-height:14px;margin:0 0 3px;flex:0 0 auto}' +
      '#sc-root #sc-results{flex:1;min-height:0;overflow:auto;border:1px solid var(--border);border-radius:6px;background:var(--bg2)}' +
      '#sc-root #sc-results .sc-empty{padding:24px 12px;text-align:center;color:var(--tlo);font-size:11px;line-height:1.5}' +
      '#sc-root #sc-results .sc-empty b{color:var(--gold);font-weight:700}' +
      '#sc-root .sc-rtop{display:flex;align-items:center;gap:8px;padding:4px 6px;position:sticky;top:0;' +
        'background:var(--bg2);border-bottom:1px solid var(--border);z-index:1}' +
      '#sc-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#sc-root th,#sc-root td{padding:3px 5px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}' +
      '#sc-root th{color:var(--tlo);position:sticky;top:28px;background:var(--bg);font-weight:600;font-size:11px}' +
      '#sc-root .sc-sort{appearance:none;border:0;background:transparent;color:inherit;font:inherit;font-weight:inherit;' +
        'padding:2px 1px;cursor:pointer;display:inline-flex;align-items:center;justify-content:flex-end;gap:3px;white-space:nowrap}' +
      '#sc-root .sc-sort:hover,#sc-root .sc-sort:focus-visible{color:var(--thi);outline:none}' +
      '#sc-root .sc-sort[aria-sort=ascending],#sc-root .sc-sort[aria-sort=descending]{color:var(--gold)}' +
      '#sc-root .sc-sort .arrow{display:inline-block;min-width:9px;color:var(--tlo);font-size:8px}' +
      '#sc-root .sc-sort[aria-sort=ascending] .arrow,#sc-root .sc-sort[aria-sort=descending] .arrow{color:var(--gold)}' +
      '#sc-root .sc-sort-state{margin-left:auto;color:var(--gold);font-size:9px;white-space:nowrap}' +
      '#sc-root td.up{color:var(--red)}#sc-root td.dn{color:var(--green)}' +
      '#sc-root .sc-code{color:var(--gold);font-weight:700;cursor:pointer;text-align:left}' +
      '#sc-root .sc-nm{color:var(--tlo);text-align:left;max-width:90px;overflow:hidden;text-overflow:ellipsis}' +
      '#sc-root .sc-add{background:var(--bg3);border:1px solid var(--border);color:var(--green);border-radius:3px;cursor:pointer;padding:0 6px;font-size:9px}' +
      '#sc-root .sc-note{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:3px;flex:0 0 auto}' +
      '#sc-root .sc-presets{display:flex;gap:3px;flex-wrap:wrap;margin:0 0 4px}' +
      '#sc-root .sc-chip{padding:2px 7px;border:1px solid var(--border);border-radius:999px;background:transparent;' +
        'color:var(--tlo);font-size:9px;cursor:pointer;font-family:inherit}' +
      '#sc-root .sc-chip:hover{border-color:var(--gold-m);color:var(--gold)}' +
      /* 手機直式：篩選條件在上、結果在下；寬表僅於自己的容器水平捲動。 */
      '@media(max-width:900px) and (orientation:portrait){' +
        'html[data-st5-route="scan"] #shell-views:has(#view-scan.on){overflow-x:hidden!important;overflow-y:auto!important}' +
        '#view-scan.sv-panel.on,#mount-scan,#mount-scan.sv-mount,#sc-root{' +
          'height:auto!important;min-height:0!important;overflow:visible!important;flex:none!important}' +
        '#sc-root .sc-head{align-items:flex-start;flex-wrap:wrap;margin-bottom:8px}' +
        '#sc-root .sc-head>div:first-child{width:100%;align-items:flex-start}' +
        '#sc-root .sc-title{font-size:19px;line-height:1.25}' +
        '#sc-root .sc-sub{font-size:11px;line-height:1.4}' +
        '#sc-root .sc-actions{width:100%;justify-content:flex-start;flex-wrap:wrap}' +
        '#sc-root .sc-btn{min-height:30px;padding:5px 9px;font-size:11px}' +
        '#sc-root .sc-layout{display:flex!important;flex-direction:column;grid-template-columns:none!important;' +
          'height:auto!important;min-height:0!important;overflow:visible!important;gap:8px}' +
        '#sc-root .sc-rail,#sc-root .sc-main{' +
          'height:auto!important;min-height:0!important;max-height:none!important;overflow:visible!important;flex:none!important}' +
        '#sc-root .sc-rail{display:grid;grid-template-columns:minmax(0,1fr);gap:7px;padding-right:0}' +
        '#sc-root .sc-grp{padding:9px 10px}' +
        '#sc-root .sc-grp h4{font-size:13px;line-height:1.35;margin-bottom:7px}' +
        '#sc-root .sc-grp label,#sc-root .sc-grp .hint{font-size:11px;line-height:1.45}' +
        '#sc-root .sc-grp input[type=number]{min-height:30px;font-size:11px}' +
        '#sc-root .sc-bar{gap:7px;margin-bottom:7px}' +
        '#sc-root .sc-bar select{min-height:30px;font-size:11px;max-width:100%}' +
        '#sc-root #sc-results{height:auto!important;min-height:180px!important;max-height:none!important;' +
          'overflow-x:auto!important;overflow-y:visible!important;flex:none!important}' +
        '#sc-root #sc-results table{min-width:760px;font-size:10px}' +
        '#sc-root .sc-rtop{position:static;min-width:760px}' +
        '#sc-root th{position:static}' +
        '#sc-root .sc-note{font-size:10px;line-height:1.5}' +
      '}';
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

  function hasSortValue(value, type) {
    if (value == null || value === '') return false;
    return type === 'number' ? isFinite(Number(value)) : String(value).trim() !== '';
  }

  function sortedResults(rows) {
    var column = SORT_COLUMNS.find(function (c) { return c.key === sortState.key; });
    if (!column || sortState.direction === 'original') return rows.slice();
    var direction = sortState.direction === 'ascending' ? 1 : -1;
    return rows.map(function (row, index) { return { row: row, index: index }; }).sort(function (a, b) {
      var av = a.row[column.key];
      var bv = b.row[column.key];
      var aHas = hasSortValue(av, column.type);
      var bHas = hasSortValue(bv, column.type);
      // 缺值永遠沉底，不因升／降冪翻到最上方。
      if (!aHas && !bHas) return a.index - b.index;
      if (!aHas) return 1;
      if (!bHas) return -1;
      var compared = column.type === 'number'
        ? Number(av) - Number(bv)
        : String(av).localeCompare(String(bv), 'zh-Hant', { numeric: true, sensitivity: 'base' });
      return compared === 0 ? a.index - b.index : compared * direction;
    }).map(function (item) { return item.row; });
  }

  function sortHeader(column) {
    var active = sortState.key === column.key && sortState.direction !== 'original';
    var aria = active ? sortState.direction : 'none';
    var arrow = aria === 'ascending' ? '▲' : (aria === 'descending' ? '▼' : '↕');
    var next = aria === 'none' ? '升冪' : (aria === 'ascending' ? '降冪' : '原始順序');
    return '<th><button type="button" class="sc-sort" data-sort="' + esc(column.key) +
      '" aria-sort="' + aria + '" title="' + esc(column.label) + '：點擊切換為' + next + '">' +
      esc(column.label) + '<span class="arrow" aria-hidden="true">' + arrow + '</span></button></th>';
  }

  function cycleSort(key) {
    if (sortState.key !== key || sortState.direction === 'original') {
      sortState = { key: key, direction: 'ascending' };
    } else if (sortState.direction === 'ascending') {
      sortState.direction = 'descending';
    } else {
      sortState = { key: null, direction: 'original' };
    }
    renderResults(lastResults);
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
    rows = sortedResults(rows);
    var V = window.Viz;
    var maxVol = 0;
    rows.forEach(function (r) {
      if (r.volRatio != null && isFinite(r.volRatio)) maxVol = Math.max(maxVol, Math.abs(r.volRatio));
    });
    var h = '<div class="sc-rtop"><button type="button" class="sc-btn" id="sc-addall">＋ 全部加入自選</button>' +
      '<span style="color:var(--tlo);font-size:10px">點代號載入線型 · 顯示前 ' + rows.length + ' 檔</span>' +
      (sortState.key ? '<span class="sc-sort-state">排序：' + esc((SORT_COLUMNS.find(function (c) { return c.key === sortState.key; }) || {}).label || '') +
        (sortState.direction === 'ascending' ? ' ▲' : ' ▼') + '</span>' : '') + '</div>';
    h += '<table class="sc-native-sort" data-st-sort="off"><thead><tr>' + SORT_COLUMNS.map(sortHeader).join('') + '<th aria-label="加入自選"></th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var chgCls = r.changePct >= 0 ? 'up' : 'dn';
      var streak = function (v) { return v == null ? '—' : (v > 0 ? '+' + v : v); };
      var chgAbs = r.changePct != null && Math.abs(r.changePct) < 30;
      var rsiCell = (V && r.rsi14 != null && isFinite(r.rsi14))
        ? '<td>' + V.heatCell(String(r.rsi14), r.rsi14 - 50, 'TW') + '</td>'
        : cell(r.rsi14);
      var volTxt = r.volRatio == null ? '—' : r.volRatio;
      var volCell = '<td>' + volTxt +
        ((V && maxVol && r.volRatio != null) ? V.rowBar(r.volRatio, maxVol) : '') + '</td>';
      var yoyTxt = r.revYoy == null ? '—' : (r.revYoy + '%');
      var yoyCol = r.revYoy == null ? '' : (window.Colors && Colors.growth
        ? Colors.growth(r.sym || 'TW', r.revYoy)
        : (r.revYoy >= 0 ? 'var(--red)' : 'var(--green)'));
      var yoyCell = r.revYoy == null
        ? cell(null)
        : '<td style="color:' + yoyCol + '">' + yoyTxt + '</td>';
      var trustCell = (V && r.trustStreak)
        ? '<td>' + V.streakChip(r.trustStreak, '') + '</td>'
        : cell(streak(r.trustStreak), r.trustStreak > 0 ? 'up' : (r.trustStreak < 0 ? 'dn' : ''));
      var foreignCell = (V && r.foreignStreak)
        ? '<td>' + V.streakChip(r.foreignStreak, '') + '</td>'
        : cell(streak(r.foreignStreak), r.foreignStreak > 0 ? 'up' : (r.foreignStreak < 0 ? 'dn' : ''));
      h += '<tr>' +
        '<td class="sc-code" data-sym="' + esc(r.sym) + '">' + esc(r.sym) + '</td>' +
        '<td class="sc-nm">' + esc(r.name || '') + '</td>' +
        cell(r.close) +
        cell(chgAbs ? ((r.changePct >= 0 ? '+' : '') + r.changePct + '%') : '—', chgAbs ? chgCls : '') +
        rsiCell + volCell +
        yoyCell +
        cell(r.per) +
        cell(r['yield'] == null ? null : r['yield'] + '%') +
        trustCell + foreignCell +
        '<td><button type="button" class="sc-add" data-sym="' + esc(r.sym) + '">＋</button></td></tr>';
    });
    h += '</tbody></table>';
    el.innerHTML = h;
    el.querySelectorAll('.sc-code').forEach(function (td) {
      td.onclick = function () { openChart(td.getAttribute('data-sym')); };
    });
    el.querySelectorAll('.sc-sort').forEach(function (button) {
      button.onclick = function () { cycleSort(button.getAttribute('data-sort')); };
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
            '<span class="sc-title">三合一選股</span>' +
            '<span class="sc-sub">技術 × 基本面 × 籌碼</span>' +
          '</div><div class="sc-actions">' +
            '<button type="button" class="sc-btn primary" id="sc-run">掃描</button>' +
            '<button type="button" class="sc-btn" data-shell-back>← 儀表板</button>' +
          '</div></div>' +
          '<div class="sc-layout">' +
            '<div class="sc-rail">' +
              '<div class="sc-presets">' +
                '<button type="button" class="sc-chip" data-preset="trend">趨勢多頭</button>' +
                '<button type="button" class="sc-chip" data-preset="breakout">帶量突破</button>' +
                '<button type="button" class="sc-chip" data-preset="value">價值殖利</button>' +
                '<button type="button" class="sc-chip" data-preset="chip">法人連買</button>' +
                '<button type="button" class="sc-chip" data-preset="clear">清除</button>' +
              '</div>' +
              '<div class="sc-grp"><h4>技術面</h4>' +
                '<label><input type="checkbox" id="sc-sma20"> SMA20</label>' +
                '<label><input type="checkbox" id="sc-sma60"> SMA60</label>' +
                '<label><input type="checkbox" id="sc-align"> 多頭排列</label>' +
                '<label><input type="checkbox" id="sc-high20"> 20日新高</label>' +
                '<label>RSI <input type="number" id="sc-rsimin">–<input type="number" id="sc-rsimax"></label>' +
                '<label>量比 ≥ <input type="number" id="sc-volr" step="0.1" placeholder="1.5"></label>' +
              '</div>' +
              '<div class="sc-grp"><h4>基本面</h4>' +
                '<label>YoY ≥ <input type="number" id="sc-revyoy" placeholder="20">%</label>' +
                '<label>PER ≤ <input type="number" id="sc-permax" placeholder="30"></label>' +
                '<label>殖利 ≥ <input type="number" id="sc-yield" step="0.1" placeholder="3">%</label>' +
                '<div class="hint">TWSE 月營收／BWIBBU</div>' +
              '</div>' +
              '<div class="sc-grp"><h4>籌碼面</h4>' +
                '<label>投信 ≥ <input type="number" id="sc-trust" placeholder="3">天</label>' +
                '<label>外資 ≥ <input type="number" id="sc-foreign" placeholder="3">天</label>' +
                '<div class="hint">chip_history 連續天數</div>' +
              '</div>' +
              '<div class="sc-bar">' +
                '<select id="sc-sector"><option value="">全部產業</option><option value="__TECH__">科技電子整合</option></select>' +
              '</div>' +
            '</div>' +
            '<div class="sc-main">' +
              '<div id="sc-msg"></div>' +
              '<div id="sc-results"><div class="sc-empty">已套用「趨勢多頭」條件<br>按 <b>掃描</b> 或稍候自動執行</div></div>' +
              '<div class="sc-note">/screen3 · 空白=不限 · 非投資建議</div>' +
            '</div>' +
          '</div>' +
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
    else {
      /* 進頁自動掃一次，避免結果區空白 */
      setTimeout(function () {
        if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'scan' && !lastResults.length) {
          scan();
        }
      }, 350);
    }
  }

  window.ScanV5 = {
    activate: activate,
    deactivate: function () {},
    scan: scan,
    last: function () { return lastResults; },
    sortState: function () { return { key: sortState.key, direction: sortState.direction }; },
    sortRows: sortedResults
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

/* ============================================================================
 * scan_v5.js  —  Stock Terminal 5.0 Stage 7：三合一選股側欄
 * ----------------------------------------------------------------------------
 * 資料：POST /screen3（技術 × 基本面 × 籌碼）
 * Meta：GET /screener（產業清單）
 * 掛載：#mount-scan；側欄「選股」
 * 工具列「🔬 選股」經 bridge_v5 導向此頁（舊模態窗已移除）
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var sectors = [];
  var lastResults = [];
  var sortState = { key: null, direction: 'original' };
  var scanGeneration = 0;
  var scanController = null;
  var lastResearchMeta = null;
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
  var RESEARCH_COLUMNS = [
    { key: 'research.rangePosition', label: '箱型位置', type: 'text' },
    { key: 'research.distanceToTopPct', label: '距箱頂%', type: 'number' },
    { key: 'research.drawdown100', label: '百日回撤%', type: 'number' },
    { key: 'research.breakoutVolumeRatio', label: '突破量比', type: 'number' },
    { key: 'research.valuationDate', label: '估值日期', type: 'text' },
    { key: 'research.priceAsOf', label: '價格日期', type: 'text' },
    { key: 'research.dataStatus', label: '資料狀態', type: 'text' }
  ];
  function columnsFor(rows) {
    return SORT_COLUMNS.concat(rows.some(function (r) { return !!r.research; }) ? RESEARCH_COLUMNS : []);
  }
  function sortValue(row, key) {
    return key.split('.').reduce(function (value, part) { return value == null ? null : value[part]; }, row);
  }

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
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
      '#shell-views:has(#view-scan.on){overflow:hidden!important}' +
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
      '#sc-root .sc-rtop{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:4px 6px;position:sticky;top:0;' +
        'background:var(--bg2);border-bottom:1px solid var(--border);z-index:1}' +
      '#sc-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#sc-root th,#sc-root td{padding:3px 5px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}' +
      '#sc-root th{color:var(--tlo);background:var(--bg);font-weight:600;font-size:11px}' +
      '#sc-root .sc-sort{appearance:none;border:0;background:transparent;color:inherit;font:inherit;font-weight:inherit;' +
        'padding:2px 1px;cursor:pointer;display:inline-flex;align-items:center;justify-content:flex-end;gap:3px;white-space:nowrap}' +
      '#sc-root .sc-sort:hover,#sc-root .sc-sort:focus-visible{color:var(--thi);outline:none}' +
      '#sc-root th[aria-sort=ascending] .sc-sort,#sc-root th[aria-sort=descending] .sc-sort{color:var(--gold)}' +
      '#sc-root .sc-sort .arrow{display:inline-block;min-width:9px;color:var(--tlo);font-size:8px}' +
      '#sc-root th[aria-sort=ascending] .arrow,#sc-root th[aria-sort=descending] .arrow{color:var(--gold)}' +
      '#sc-root .sc-sort-state{margin-left:auto;color:var(--gold);font-size:9px;white-space:nowrap}' +
      '#sc-root td.up{color:var(--red)}#sc-root td.dn{color:var(--green)}' +
      '#sc-root .sc-code{color:var(--gold);font-weight:700;cursor:pointer;text-align:left}' +
      '#sc-root .sc-nm{color:var(--tlo);text-align:left;max-width:90px;overflow:hidden;text-overflow:ellipsis}' +
      '#sc-root .sc-add{background:var(--bg3);border:1px solid var(--border);color:var(--green);border-radius:3px;cursor:pointer;padding:0 6px;font-size:9px}' +
      '#sc-root .sc-note{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:3px;flex:0 0 auto}' +
      '#sc-root .sc-presets{display:flex;gap:3px;flex-wrap:wrap;margin:0 0 4px}' +
      '#sc-root .sc-chip{padding:2px 7px;border:1px solid var(--border);border-radius:999px;background:transparent;' +
        'color:var(--tlo);font-size:9px;cursor:pointer;font-family:inherit}' +
      '#sc-root .sc-chip:hover{border-color:var(--gold-m);color:var(--gold)}';
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
      sector: val('sc-sector'),
      research: { enabled: ck('sc-research'), peMax: val('sc-research-pe') === '' ? 30 : numOrNull(val('sc-research-pe')),
        excludeIp: ck('sc-research-ip') }
    };
  }

  function setChecked(id, on) { var el = $(id); if (el) el.checked = !!on; }
  function setVal(id, v) { var el = $(id); if (el) el.value = v == null ? '' : v; }

  function applyPreset(name) {
    ['sc-sma20', 'sc-sma60', 'sc-align', 'sc-high20'].forEach(function (id) { setChecked(id, false); });
    setVal('sc-rsimin', ''); setVal('sc-rsimax', ''); setVal('sc-volr', '');
    setVal('sc-revyoy', ''); setVal('sc-permax', ''); setVal('sc-yield', '');
    setVal('sc-trust', ''); setVal('sc-foreign', '');
    setChecked('sc-research', name === 'research');
    if (name === 'trend') {
      setChecked('sc-sma20', true); setChecked('sc-sma60', true); setChecked('sc-align', true);
      setVal('sc-rsimin', '45'); setVal('sc-rsimax', '75');
    } else if (name === 'breakout') {
      setChecked('sc-high20', true); setChecked('sc-sma20', true); setVal('sc-volr', '1.5');
    } else if (name === 'value') {
      setVal('sc-permax', '20'); setVal('sc-yield', '3'); setChecked('sc-sma60', true);
    } else if (name === 'chip') {
      setVal('sc-trust', '3'); setVal('sc-foreign', '3'); setChecked('sc-sma20', true);
    } else if (name === 'research') {
      setVal('sc-research-pe', '30'); setChecked('sc-research-ip', true);
    }
  }

  function cell(v, cls) {
    return '<td class="' + (cls || '') + '">' + (v == null || v === '' ? '—' : v) + '</td>';
  }

  // 判斷排序值是否「存在且合法」：
  //   - 空值／null／undefined 不算；
  //   - 數值欄位：boolean、純空白字串、Infinity、NaN 皆視為缺值；
  //     有效的 0 與負數仍視為合法；
  //   - 文字欄位：trim 後非空才算。
  function hasSortValue(value, type) {
    if (value == null) return false;
    if (type === 'number') {
      if (typeof value === 'boolean') return false;
      if (typeof value === 'string') {
        if (value.trim() === '') return false;
        var n = Number(value);
        return isFinite(n);
      }
      return typeof value === 'number' && isFinite(value);
    }
    return String(value).trim() !== '';
  }

  function sortedResults(rows) {
    var column = columnsFor(rows).find(function (c) { return c.key === sortState.key; });
    if (!column || sortState.direction === 'original') return rows.slice();
    var direction = sortState.direction === 'ascending' ? 1 : -1;
    return rows.map(function (row, index) { return { row: row, index: index }; }).sort(function (a, b) {
      var av = sortValue(a.row, column.key);
      var bv = sortValue(b.row, column.key);
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

  // aria-sort 依 WAI-ARIA 建議掛在 th 上，而不是裡面的按鈕。
  function sortHeader(column) {
    var active = sortState.key === column.key && sortState.direction !== 'original';
    var aria = active ? sortState.direction : 'none';
    var arrow = aria === 'ascending' ? '▲' : (aria === 'descending' ? '▼' : '↕');
    var next = aria === 'none' ? '升冪' : (aria === 'ascending' ? '降冪' : '原始順序');
    return '<th aria-sort="' + aria + '" scope="col">' +
      '<button type="button" class="sc-sort" data-sort="' + esc(column.key) +
      '" aria-label="' + esc(column.label) + '：點擊切換為' + next +
      '" title="' + esc(column.label) + '：點擊切換為' + next + '">' +
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

  // 下拉切換（欄位或方向）：既不 fetch 也不改寫 lastResults。
  function applySort(key, direction) {
    if (!key || direction === 'original') {
      sortState = { key: null, direction: 'original' };
    } else {
      sortState = {
        key: key,
        direction: direction === 'descending' ? 'descending' : 'ascending'
      };
    }
    renderResults(lastResults);
  }

  // 重設鈕：清除排序狀態、回到查詢回傳的原始順序。
  function resetSort() {
    sortState = { key: null, direction: 'original' };
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
    // 排序只重繪結果區，故先快照捲動位置與鍵盤焦點，重繪後再還原，
    // 涵蓋表頭排序按鈕、欄位／方向下拉與重設鈕。
    var prevScrollTop = typeof el.scrollTop === 'number' ? el.scrollTop : 0;
    var prevScrollLeft = typeof el.scrollLeft === 'number' ? el.scrollLeft : 0;
    var activeNow = (typeof document !== 'undefined' && document.activeElement) ? document.activeElement : null;
    var focusSelector = null;
    if (activeNow) {
      if (activeNow.id === 'sc-sort-key' || activeNow.id === 'sc-sort-direction' ||
          activeNow.id === 'sc-sort-reset' || activeNow.id === 'sc-addall') {
        focusSelector = '#' + activeNow.id;
      } else if (activeNow.classList && typeof activeNow.classList.contains === 'function' &&
          activeNow.classList.contains('sc-sort')) {
        var fkey = typeof activeNow.getAttribute === 'function' ? (activeNow.getAttribute('data-sort') || '') : '';
        focusSelector = '.sc-sort[data-sort="' + fkey + '"]';
      }
    }
    if (!rows.length) {
      el.innerHTML = '<div style="color:var(--tlo);padding:18px;text-align:center">無符合條件的個股</div>';
      return;
    }
    rows = sortedResults(rows);
    var columns = columnsFor(rows);
    var researchRows = columns.length > SORT_COLUMNS.length;
    var V = window.Viz;
    var maxVol = 0;
    rows.forEach(function (r) {
      if (r.volRatio != null && isFinite(r.volRatio)) maxVol = Math.max(maxVol, Math.abs(r.volRatio));
    });
    // 排序工具列：欄位＋方向下拉、重設鈕、即時狀態（aria-live）。
    // 僅操作目前已載入的前 80 檔，不代表全市場排序。
    var activeLabel = sortState.key
      ? ((columns.find(function (c) { return c.key === sortState.key; }) || {}).label || '')
      : '';
    var sortKeyOptions = '<option value="">原始順序</option>' + columns.map(function (c) {
      return '<option value="' + esc(c.key) + '"' + (sortState.key === c.key ? ' selected' : '') +
        '>' + esc(c.label) + '</option>';
    }).join('');
    var sortDirOptions = '<option value="ascending"' +
      (sortState.direction === 'ascending' ? ' selected' : '') + '>升冪</option>' +
      '<option value="descending"' + (sortState.direction === 'descending' ? ' selected' : '') +
      '>降冪</option>';
    var sortDirDisabled = sortState.key ? '' : ' disabled';
    var stateText = sortState.key
      ? ('排序：' + esc(activeLabel) + (sortState.direction === 'ascending' ? ' ▲（升冪）' : ' ▼（降冪）'))
      : '排序：原始順序';
    var h = '<div class="sc-rtop" role="toolbar" aria-label="結果排序">' +
      '<button type="button" class="sc-btn" id="sc-addall">＋ 全部加入自選</button>' +
      '<label for="sc-sort-key" style="color:var(--tlo);font-size:10px">排序</label>' +
      '<select id="sc-sort-key" aria-label="排序欄位">' + sortKeyOptions + '</select>' +
      '<select id="sc-sort-direction" aria-label="排序方向"' + sortDirDisabled + '>' + sortDirOptions + '</select>' +
      '<button type="button" class="sc-btn" id="sc-sort-reset" aria-label="重設排序為原始順序">重設</button>' +
      '<span style="color:var(--tlo);font-size:10px">僅排序本次已載入前 ' + rows.length + ' 檔，不代表全市場排序</span>' +
      '<span class="sc-sort-state" role="status" aria-live="polite">' + stateText + '</span>' +
      '</div>';
    h += '<table class="sc-native-sort" data-st-sort="off"><thead><tr>' + columns.map(sortHeader).join('') +
      (researchRows ? '<th>承接草稿</th>' : '') + '<th aria-label="加入自選"></th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var chgCls = r.changePct >= 0 ? 'up' : 'dn';
      var streak = function (v, complete) {
        if (v == null) return '—';
        return (complete === false ? (v > 0 ? '≥' : '≤') : '') + (v > 0 ? '+' + v : v);
      };
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
      var trustCell = (V && r.trustStreak && r.trustStreakComplete !== false)
        ? '<td>' + V.streakChip(r.trustStreak, '') + '</td>'
        : cell(streak(r.trustStreak, r.trustStreakComplete), r.trustStreak > 0 ? 'up' : (r.trustStreak < 0 ? 'dn' : ''));
      var foreignCell = (V && r.foreignStreak && r.foreignStreakComplete !== false)
        ? '<td>' + V.streakChip(r.foreignStreak, '') + '</td>'
        : cell(streak(r.foreignStreak, r.foreignStreakComplete), r.foreignStreak > 0 ? 'up' : (r.foreignStreak < 0 ? 'dn' : ''));
      function explain(html, key) {
        return html.replace('<td', '<td title="' + esc((r.fieldStatus || {})[key] || '') + '"');
      }
      h += '<tr>' +
        '<td class="sc-code" data-sym="' + esc(r.sym) + '">' + esc(r.sym) + '</td>' +
        '<td class="sc-nm">' + esc(r.name || '') + '</td>' +
        cell(r.close) +
        cell(chgAbs ? ((r.changePct >= 0 ? '+' : '') + r.changePct + '%') : '—', chgAbs ? chgCls : '') +
        rsiCell + volCell +
        explain(yoyCell, 'revYoy') +
        explain(cell(r.per), 'per') +
        explain(cell(r['yield'] == null ? null : r['yield'] + '%'), 'yield') +
        explain(trustCell, 'trustStreak') + explain(foreignCell, 'foreignStreak') +
        (researchRows ? RESEARCH_COLUMNS.map(function (column) {
          var value = sortValue(r, column.key);
          if (column.key === 'research.dataStatus') value = { available: '可觀察', partial: '缺資料', not_applicable: '不適用' }[value] || value;
          return cell(value == null ? null : esc(value));
        }).join('') + '<td><button type="button" class="sc-btn sc-research-open" data-sym="' + esc(r.sym) + '">估值承接</button></td>' : '') +
        '<td><button type="button" class="sc-add" data-sym="' + esc(r.sym) + '">＋</button></td></tr>';
    });
    h += '</tbody></table>';
    el.innerHTML = h;
    el.querySelectorAll('.sc-code').forEach(function (td) {
      td.onclick = function () { openChart(td.getAttribute('data-sym')); };
    });
    el.querySelectorAll('.sc-research-open').forEach(function (button) {
      button.onclick = function () {
        var symbol = button.getAttribute('data-sym');
        var row = lastResults.find(function (r) { return r.sym === symbol; });
        if (window.ValuationResearchUI) window.ValuationResearchUI.open(symbol, row, lastResearchMeta || readForm().research);
      };
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
    // 下拉與重設鈕：三者僅調整排序狀態，不會重新發查詢。
    var sortKeySel = $('sc-sort-key');
    if (sortKeySel) {
      sortKeySel.onchange = function () {
        var dirSel = $('sc-sort-direction');
        var dir = (dirSel && dirSel.value) || 'ascending';
        if (!sortKeySel.value) applySort(null, 'original');
        else applySort(sortKeySel.value, dir);
      };
    }
    var sortDirSel = $('sc-sort-direction');
    if (sortDirSel) {
      sortDirSel.onchange = function () {
        var keySel = $('sc-sort-key');
        if (!keySel || !keySel.value) return;
        applySort(keySel.value, sortDirSel.value);
      };
    }
    var sortResetBtn = $('sc-sort-reset');
    if (sortResetBtn) sortResetBtn.onclick = function () { resetSort(); };
    // 還原捲動位置與鍵盤焦點
    if (typeof el.scrollTop === 'number') el.scrollTop = prevScrollTop;
    if (typeof el.scrollLeft === 'number') el.scrollLeft = prevScrollLeft;
    if (focusSelector) {
      var target = null;
      if (focusSelector.charAt(0) === '#') target = $(focusSelector.slice(1));
      else if (typeof el.querySelector === 'function') target = el.querySelector(focusSelector);
      if (target && typeof target.focus === 'function') target.focus({ preventScroll: true });
    }
  }

  function scan() {
    var generation = ++scanGeneration;
    if (scanController) scanController.abort();
    scanController = typeof AbortController === 'function' ? new AbortController() : null;
    var msg = $('sc-msg');
    var body = readForm();
    if (msg) msg.textContent = body.research.enabled ? '研究查詢中…（僅使用本機已存資料）' : '掃描中…（全台股宇集，條件越多越慢）';
    var box = $('sc-results');
    if (box) box.innerHTML = '';
    fetch(SRV + '/screen3', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: scanController ? scanController.signal : undefined
    })
      .then(function (r) { return r.json().then(function (data) {
        if (!r.ok) throw new Error(data.error || '後端回覆 ' + r.status);
        return data;
      }); })
      .then(function (r) {
        if (generation !== scanGeneration) return;
        if (!r) { if (msg) msg.textContent = '掃描失敗（後端無回應）'; return; }
        lastResults = r.results || [];
        lastResearchMeta = r.researchMeta || null;
        if (!columnsFor(lastResults).some(function (column) { return column.key === sortState.key; })) {
          sortState = { key: null, direction: 'original' };
        }
        if (msg) {
          msg.innerHTML = '掃描 ' + r.scanned + ' 檔 → 技術通過 ' + r.techPass +
            ' → 交集 <b style="color:var(--gold)">' + r.matched + '</b> 檔' +
            (r.matched > 80 ? '（顯示前 80）' : '') +
            (body.research.enabled ? ' · 本機快取研究；缺資料不代填，不代表策略驗證' +
              (lastResearchMeta ? '<br>' + esc(lastResearchMeta.contractVersion || '') + ' · ' +
                esc(lastResearchMeta.universeSource || '') + ' · PER 上限 ' + esc(lastResearchMeta.peMax) +
                (Array.isArray(lastResearchMeta.exclusions) && lastResearchMeta.exclusions.length ? '<br>未納入：' +
                  lastResearchMeta.exclusions.map(function (item) { return esc(item.reason) + ' ' + esc(item.count) + ' 檔'; }).join('；') : '') : '') : '');
        }
        renderResults(lastResults);
      })
      .catch(function (e) {
        if (generation !== scanGeneration || e.name === 'AbortError') return;
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
                '<button type="button" class="sc-chip" data-preset="research">估值研究</button>' +
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
              '<div class="sc-grp"><h4>估值承接研究</h4>' +
                '<label><input type="checkbox" id="sc-research">啟用本機研究篩選</label>' +
                '<label>PER ≤ <input type="number" id="sc-research-pe" value="30" min="1" max="200"></label>' +
                '<label><input type="checkbox" id="sc-research-ip" checked>3529／6643 另列研究</label>' +
                '<div class="hint">預設 30 倍，可改 40。僅既有快取；非歷史時點財報回測。</div>' +
                '<div class="hint">IP 另案：<button type="button" class="sc-btn" data-ip-research="3529">3529</button> ' +
                '<button type="button" class="sc-btn" data-ip-research="6643">6643</button></div>' +
              '</div>' +
              '<div class="sc-bar">' +
                '<select id="sc-sector"><option value="">全部產業</option><option value="__TECH__">科技電子整合</option></select>' +
              '</div>' +
            '</div>' +
            '<div class="sc-main">' +
              '<div id="sc-msg"></div>' +
              '<div id="sc-results"><div class="sc-empty">已套用「趨勢多頭」條件<br>按 <b>掃描</b> 或稍候自動執行</div></div>' +
              '<div class="sc-note">空白＝不限；—＝缺資料／不適用。≥／≤ 表示籌碼連續紀錄尚不完整。排序僅限已載入結果；研究提供箱型、量比與來源日期排序，未消除存活者偏差。</div>' +
            '</div>' +
          '</div>' +
        '</div>';

      var run = $('sc-run');
      if (run) run.onclick = scan;
      mount.querySelectorAll('[data-ip-research]').forEach(function (button) {
        button.onclick = function () {
          if (window.ValuationResearchUI) window.ValuationResearchUI.open(button.getAttribute('data-ip-research'), null, readForm().research);
        };
      });
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
    deactivate: function () { ++scanGeneration; if (scanController) scanController.abort(); },
    scan: scan,
    last: function () { return lastResults; },
    sortState: function () { return { key: sortState.key, direction: sortState.direction }; },
    sortRows: sortedResults
  };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'scan') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'scan') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 250); });
  else setTimeout(boot, 250);
})();

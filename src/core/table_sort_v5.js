/* Stock Terminal 5.0 — global, accessible three-state table sorting. */
(function () {
  'use strict';

  var states = new WeakMap();
  var queued = new Set();
  var scheduled = false;
  var SKIP_SELECTOR = '[data-st-sort="off"],.pf-hm,.bk-hm,.sc-native-sort';
  var ACTION_HEADER = /^(操作|動作|加入|新增|刪除|詳情|圖表|開啟|查看|更多|編輯)$/;
  var MISSING = /^(?:—|--|-|–|N\/A|NA|null|undefined|pending|無|尚無|未提供)$/i;

  function textOf(cell) {
    if (!cell) return '';
    var explicit = cell.getAttribute('data-sort-value');
    return String(explicit != null ? explicit : (cell.innerText || cell.textContent || '')).trim();
  }

  function isMissing(value) {
    value = String(value == null ? '' : value).trim();
    return !value || MISSING.test(value);
  }

  function numericValue(value) {
    var raw = String(value == null ? '' : value).trim();
    if (isMissing(raw)) return null;
    var negative = /^\(.*\)$/.test(raw);
    if (negative) raw = raw.slice(1, -1);
    raw = raw.replace(/[\s,，]/g, '').replace(/^(?:NT\$|TWD|USD|US\$|\$)/i, '');
    var match = raw.match(/^([+-]?(?:\d+(?:\.\d+)?|\.\d+))(?:[%％xX倍兆億万萬千kKmMbB張股口天日分筆檔家元]*)$/);
    if (!match) return null;
    var number = Number(match[1]);
    if (!isFinite(number)) return null;
    if (/兆/.test(raw)) number *= 1e12;
    else if (/億/.test(raw)) number *= 1e8;
    else if (/[万萬]/.test(raw)) number *= 1e4;
    else if (/千|[kK]/.test(raw)) number *= 1e3;
    else if (/[mM]/.test(raw)) number *= 1e6;
    else if (/[bB]/.test(raw)) number *= 1e9;
    return negative ? -number : number;
  }

  function dateValue(value) {
    var raw = String(value == null ? '' : value).trim();
    if (!/^\d{4}[-\/]\d{1,2}[-\/]\d{1,2}(?:[ T].*)?$/.test(raw)) return null;
    var stamp = Date.parse(raw.replace(/\//g, '-'));
    return isFinite(stamp) ? stamp : null;
  }

  function inferType(rows, columnIndex) {
    var values = rows.map(function (row) { return textOf(row.cells[columnIndex]); })
      .filter(function (value) { return !isMissing(value); });
    if (!values.length) return 'text';
    var need = Math.max(1, Math.ceil(values.length * 0.70));
    if (values.filter(function (value) { return dateValue(value) != null; }).length >= need) return 'date';
    if (values.filter(function (value) { return numericValue(value) != null; }).length >= need) return 'number';
    return 'text';
  }

  function shapeOf(table) {
    var headerRow = table.tHead && table.tHead.rows.length
      ? table.tHead.rows[table.tHead.rows.length - 1]
      : table.rows[0];
    if (!headerRow || !headerRow.querySelector('th')) return null;
    var headers = Array.prototype.slice.call(headerRow.cells || []);
    if (headers.length < 2 || headers.some(function (th) { return Number(th.colSpan || 1) !== 1 || Number(th.rowSpan || 1) !== 1; })) return null;
    var allRows = Array.prototype.slice.call(table.rows || []);
    var headerIndex = allRows.indexOf(headerRow);
    var rows = allRows.slice(headerIndex + 1).filter(function (row) { return !!row.querySelector('td'); });
    if (rows.length < 2) return null;
    // Correlation matrices and other row-header tables are not sortable lists.
    if (rows.some(function (row) { return row.querySelector('th') || row.cells.length !== headers.length; })) return null;
    var parent = rows[0].parentNode;
    if (!parent || rows.some(function (row) { return row.parentNode !== parent; })) return null;
    return { headerRow: headerRow, headers: headers, rows: rows, parent: parent };
  }

  function sameMembers(a, b) {
    return a.length === b.length && a.every(function (row) { return b.indexOf(row) >= 0; });
  }

  function directionLabel(direction) {
    return direction === 'ascending' ? '升冪' : (direction === 'descending' ? '降冪' : '原始順序');
  }

  function nextDirection(direction) {
    return direction === 'none' ? 'ascending' : (direction === 'ascending' ? 'descending' : 'none');
  }

  function syncHeaders(state) {
    state.headers.forEach(function (th, index) {
      var button = th.querySelector(':scope > .st-sort-button');
      if (!button) return;
      var active = state.column === index && state.direction !== 'none';
      var direction = active ? state.direction : 'none';
      th.setAttribute('aria-sort', direction);
      button.setAttribute('data-direction', direction);
      var arrow = button.querySelector('.st-sort-arrow');
      if (arrow) arrow.textContent = direction === 'ascending' ? '▲' : (direction === 'descending' ? '▼' : '↕');
      button.setAttribute('aria-label', state.labels[index] + '；目前' + directionLabel(direction) + '；點擊切換為' + directionLabel(nextDirection(direction)));
      button.title = button.getAttribute('aria-label');
    });
  }

  function desiredRows(state) {
    if (state.direction === 'none' || state.column == null) return state.originalRows.slice();
    var column = state.column;
    var type = state.types[column] || inferType(state.originalRows, column);
    state.types[column] = type;
    var sign = state.direction === 'ascending' ? 1 : -1;
    return state.originalRows.map(function (row, index) { return { row: row, index: index }; }).sort(function (a, b) {
      var av = textOf(a.row.cells[column]);
      var bv = textOf(b.row.cells[column]);
      var am = isMissing(av);
      var bm = isMissing(bv);
      // 升冪與降冪都將缺值固定沉底。
      if (am && bm) return a.index - b.index;
      if (am) return 1;
      if (bm) return -1;
      var compared;
      if (type === 'number') compared = numericValue(av) - numericValue(bv);
      else if (type === 'date') compared = dateValue(av) - dateValue(bv);
      else compared = av.localeCompare(bv, 'zh-Hant', { numeric: true, sensitivity: 'base' });
      return compared === 0 ? a.index - b.index : compared * sign;
    }).map(function (item) { return item.row; });
  }

  function applyOrder(state) {
    var wanted = desiredRows(state);
    var current = Array.prototype.slice.call(state.parent.children).filter(function (node) {
      return wanted.indexOf(node) >= 0;
    });
    if (wanted.every(function (row, index) { return current[index] === row; })) {
      syncHeaders(state);
      return;
    }
    var fragment = document.createDocumentFragment();
    wanted.forEach(function (row) { fragment.appendChild(row); });
    state.parent.appendChild(fragment);
    syncHeaders(state);
    try {
      state.table.dispatchEvent(new CustomEvent('st:table-sorted', {
        detail: { column: state.column, direction: state.direction, type: state.types[state.column] || null }
      }));
    } catch (_) {}
  }

  function cycle(state, column) {
    if (state.column !== column || state.direction === 'none') {
      state.column = column;
      state.direction = 'ascending';
    } else if (state.direction === 'ascending') {
      state.direction = 'descending';
    } else {
      state.column = null;
      state.direction = 'none';
    }
    applyOrder(state);
  }

  function isActionColumn(rows, columnIndex, label) {
    if (!label || ACTION_HEADER.test(label)) return true;
    return rows.every(function (row) {
      var cell = row.cells[columnIndex];
      return !!cell && !!cell.querySelector('button,a,input,select') && textOf(cell).length <= 4;
    });
  }

  function makeHeader(state, th, columnIndex) {
    if (th.querySelector('button,input,select,a') || th.querySelector('.sc-sort')) return;
    var label = textOf(th);
    if (isActionColumn(state.originalRows, columnIndex, label)) return;
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'st-sort-button';
    while (th.firstChild) button.appendChild(th.firstChild);
    var arrow = document.createElement('span');
    arrow.className = 'st-sort-arrow';
    arrow.setAttribute('aria-hidden', 'true');
    arrow.textContent = '↕';
    button.appendChild(arrow);
    var align = getComputedStyle(th).textAlign;
    button.style.justifyContent = align === 'left' || align === 'start' ? 'flex-start' : (align === 'center' ? 'center' : 'flex-end');
    button.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      cycle(state, columnIndex);
    });
    th.classList.add('st-sortable-head');
    th.appendChild(button);
  }

  function enhanceTable(table) {
    if (!table || !table.isConnected || table.matches(SKIP_SELECTOR) || table.querySelector('.sc-sort')) return;
    var shape = shapeOf(table);
    if (!shape) return;
    var state = states.get(table);
    if (state && state.headerRow === shape.headerRow) {
      if (!sameMembers(state.originalRows, shape.rows)) {
        var existing = state.originalRows.filter(function (row) { return shape.rows.indexOf(row) >= 0; });
        var added = shape.rows.filter(function (row) { return existing.indexOf(row) < 0; });
        state.originalRows = existing.concat(added);
        state.parent = shape.parent;
        state.types = {};
        applyOrder(state);
      }
      return;
    }
    state = {
      table: table, headerRow: shape.headerRow, headers: shape.headers,
      labels: shape.headers.map(textOf), originalRows: shape.rows.slice(), parent: shape.parent,
      column: null, direction: 'none', types: {}
    };
    states.set(table, state);
    table.setAttribute('data-st-sort', 'ready');
    shape.headers.forEach(function (th, index) { makeHeader(state, th, index); });
    syncHeaders(state);
  }

  function queueTable(table) {
    if (table && table.tagName === 'TABLE') queued.add(table);
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(function () {
      scheduled = false;
      var batch = Array.from(queued);
      queued.clear();
      batch.forEach(enhanceTable);
    });
  }

  function queueFrom(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.tagName === 'TABLE') queueTable(node);
    var parentTable = node.closest && node.closest('table');
    if (parentTable) queueTable(parentTable);
    if (node.querySelectorAll) node.querySelectorAll('table').forEach(queueTable);
  }

  function boot() {
    injectCSS();
    document.querySelectorAll('table').forEach(queueTable);
    new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        queueFrom(mutation.target);
        mutation.addedNodes.forEach(queueFrom);
      });
    }).observe(document.body, { childList: true, subtree: true });
  }

  function injectCSS() {
    if (document.getElementById('st-table-sort-v5-css')) return;
    var style = document.createElement('style');
    style.id = 'st-table-sort-v5-css';
    style.textContent =
      'th.st-sortable-head{padding:0!important}' +
      '.st-sort-button{appearance:none;width:100%;min-height:24px;border:0;background:transparent;color:inherit;' +
        'font:inherit;font-weight:inherit;padding:3px 5px;display:flex;align-items:center;gap:3px;white-space:nowrap;cursor:pointer}' +
      '.st-sort-button:hover,.st-sort-button:focus-visible{color:var(--thi,#f1f5fa);background:rgba(148,163,184,.08);outline:none}' +
      'th.st-sortable-head[aria-sort=ascending] .st-sort-button,th.st-sortable-head[aria-sort=descending] .st-sort-button{color:var(--gold,#f5c518)}' +
      '.st-sort-arrow{flex:0 0 auto;min-width:9px;font-size:8px;color:var(--tlo,#64748b);text-align:center}' +
      'th.st-sortable-head[aria-sort=ascending] .st-sort-arrow,th.st-sortable-head[aria-sort=descending] .st-sort-arrow{color:var(--gold,#f5c518)}';
    document.head.appendChild(style);
  }

  window.TableSortV5 = {
    enhance: enhanceTable,
    refresh: function (root) { (root || document).querySelectorAll('table').forEach(queueTable); },
    numericValue: numericValue,
    dateValue: dateValue
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();

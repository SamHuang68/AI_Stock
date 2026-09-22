/* 投組資料契約：共用模式、唯讀解析、完整性防護；不修改部位或抓取行情。 */
(function () {
  'use strict';
  var MODE_KEY = 'st_portfolio_mode_v1';
  var mode = 'actual';
  var revision = 0;
  var currencies = { TW: 'TWD', US: 'USD', JP: 'JPY', HK: 'HKD' };

  function validMode(value) { return value === 'actual' || value === 'observation_pool'; }
  try {
    var saved = localStorage.getItem(MODE_KEY);
    if (validMode(saved)) mode = saved;
  } catch (error) { /* 儲存不可用時仍保留本頁模式。 */ }

  function changeMode(value, reason, persist) {
    if (!validMode(value)) throw new Error('投組模式僅接受實際持倉或觀察池。');
    if (value === mode) return mode;
    var previous = mode;
    mode = value;
    revision++;
    if (persist) {
      try { localStorage.setItem(MODE_KEY, mode); } catch (error) { /* 不把私人資料當成模式備援。 */ }
    }
    window.dispatchEvent(new CustomEvent('portfolioContext', {
      detail: { contractVersion: 1, mode: mode, previousMode: previous, reason: reason, revision: revision }
    }));
    return mode;
  }

  function positive(value) {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (typeof value === 'string' && !value.trim()) return null;
    var number = Number(value);
    return isFinite(number) && number > 0 ? number : null;
  }

  function issue(code, sym, message, action) {
    return { code: code, sym: sym || null, message: message, action: action };
  }

  function readStored(keys, issues) {
    for (var i = 0; i < keys.length; i++) {
      try {
        var raw = localStorage.getItem(keys[i]);
        if (raw !== null) return { value: JSON.parse(raw), source: keys[i] };
      } catch (error) {
        issues.push(issue('storage_unavailable', null, '既有投組資料無法讀取。', '請檢查瀏覽器儲存權限與原有資料，不要清空持倉。'));
        return { value: null, source: keys[i] };
      }
    }
    return { value: null, source: 'none' };
  }

  function inputFor(kind, issues) {
    var state = typeof S !== 'undefined' && S ? S : null;
    if (kind === 'actual') {
      if (state && Object.prototype.hasOwnProperty.call(state, 'positions')) return { value: state.positions, source: 'S.positions' };
      return readStored(['stock_terminal_positions_v2'], issues);
    }
    // 已初始化的空清單具權威性，不能被舊儲存或另一種觀察清單復活。
    if (state && Array.isArray(state.wl)) return { value: state.wl, source: 'S.wl' };
    if (state && state.watches && typeof state.watches === 'object') return { value: state.watches, source: 'S.watches' };
    return readStored(['st_wl', 'wl_v2', 'watchlist', 'stock_terminal_watches_v2'], issues);
  }

  function identity(rawSym, row) {
    var raw = String(rawSym || '').trim().toUpperCase();
    var market = String(row.mkt || row.m || row.market || '').toUpperCase();
    if (!market) {
      if (/\.(TW|TWO)$/.test(raw) || /^\d{4,8}[A-Z]?$/.test(raw) || raw === '^TWII') market = 'TW';
      else if (/^[A-Z][A-Z0-9.=-]*$/.test(raw)) market = 'US';
    }
    var sym = raw.replace(/\.(TW|TWO)$/, '');
    var currency = String(row.currency || currencies[market] || '').toUpperCase();
    return { sym: sym, market: market, currency: currency,
      valid: /^[A-Z0-9^][A-Z0-9.^=_-]*$/.test(sym) && !!currencies[market] && currency === currencies[market] };
  }

  function resolve(requestedMode) {
    var kind = requestedMode == null ? mode : requestedMode;
    if (!validMode(kind)) throw new Error('投組模式僅接受實際持倉或觀察池。');
    var result = {
      contractVersion: 1, kind: kind, label: kind === 'actual' ? '實際持倉' : '觀察池（等權，非實際持倉）',
      ready: false, holdings: [], coverage: { total: 0, included: 0, excluded: 0, ratio: 0, complete: false, comparable: true },
      issues: [], source: 'none', currency: null
    };
    var profile = window.ST_PRIVATE_WEB_PROFILE;
    if (profile && profile.role !== 'owner') {
      result.issues.push(issue('private_access_blocked', null, '目前角色無法存取私人投組資料。', '請使用擁有者帳號查看持倉；一般市場研究仍可使用。'));
      return result;
    }
    var input = inputFor(kind, result.issues);
    result.source = input.source;
    var value = input.value;
    var rows = [];
    if (kind === 'actual') {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        rows = Object.keys(value).map(function (key) { return { key: key, row: value[key] }; });
      } else if (value != null) {
        result.issues.push(issue('invalid_positions', null, '持倉資料格式不完整。', '請回到原持倉頁檢查資料格式，不要以觀察池取代。'));
      }
    } else if (Array.isArray(value)) {
      rows = value.map(function (row) { return { key: typeof row === 'string' ? row : row && (row.sym || row.t || row.code), row: row }; });
    } else if (value && typeof value === 'object') {
      rows = Object.keys(value).map(function (key) { return { key: key, row: value[key] }; });
    } else if (value != null) {
      result.issues.push(issue('invalid_watchlist', null, '觀察池資料格式不完整。', '請回到自選頁檢查清單。'));
    }
    var candidates = [];
    var seen = {};
    var currencySet = {};
    rows.forEach(function (item) {
      var row = item.row && typeof item.row === 'object' ? item.row : {};
      var id = identity(item.key, row);
      var key = id.market + ':' + id.sym;
      // 觀察池只列一次同一市場標的；實際持倉重複識別碼則停止計算。
      if (kind === 'observation_pool' && seen[key]) return;
      result.coverage.total++;
      if (!id.valid || seen[key]) {
        result.issues.push(issue('invalid_identity', id.sym, '標的、市場或幣別無法確認，或持倉代號重複。', '請在原持倉／自選頁確認標的市場與幣別，排除重複資料。'));
        return;
      }
      seen[key] = true;
      var weight = 1;
      if (kind === 'actual') {
        var shares = positive(row.shares);
        var price = positive(row.lastPrice);
        if (shares === null || price === null || !isFinite(shares * price) || shares * price <= 0) {
          result.issues.push(issue('invalid_market_value', id.sym, '數量或最新價格缺漏／無效，無法計算市值。', '請確認股數大於零，並載入該標的取得有效最新價格；成本不能代替現價。'));
          return;
        }
        weight = shares * price;
      }
      candidates.push({ sym: id.sym, weight: weight, market: id.market, currency: id.currency });
      currencySet[id.currency] = true;
    });
    if (result.coverage.total > 80) {
      result.issues.push(issue('too_many_holdings', null, '投組分析目前最多支援 80 檔，原清單全部保留。', '請先在原清單明確分組，再執行分析；不會截短後假裝完整。'));
    }
    result.coverage.included = candidates.length;
    result.coverage.excluded = result.coverage.total - candidates.length;
    result.coverage.ratio = result.coverage.total ? candidates.length / result.coverage.total : 0;
    var availableCurrencies = Object.keys(currencySet);
    result.currency = availableCurrencies.length === 1 ? availableCurrencies[0] : null;
    if (kind === 'actual' && availableCurrencies.length > 1) {
      result.coverage.comparable = false;
      result.issues.push(issue('mixed_currency', null, '多市場持倉的原幣市值不可直接相加，尚無可用匯率契約。', '請先分市場檢視部位；完成明確匯率與基準幣別契約前，停止整體風險計算。'));
    }
    if (kind === 'actual' && candidates.length && !isFinite(candidates.reduce(function (sum, item) { return sum + item.weight; }, 0))) {
      result.issues.push(issue('invalid_total_value', null, '持倉總市值超出可計算範圍。', '請確認股數與價格的單位及輸入值，修正後再分析。'));
    }
    if (!result.coverage.total && !result.issues.length) {
      result.issues.push(issue('empty', null, kind === 'actual' ? '尚未建立實際持倉。' : '觀察池尚無標的。',
        kind === 'actual' ? '請在持倉頁建立部位，或明確切換至等權觀察池；不會自動混用。' : '請先加入自選標的，再執行等權觀察分析。'));
    }
    result.ready = candidates.length > 0 && !result.issues.length && result.coverage.comparable;
    result.coverage.complete = result.ready;
    // 任一缺漏都不輸出部分持倉，避免消費端誤算成完整投組。
    result.holdings = result.ready ? candidates : [];
    return result;
  }

  window.PortfolioContext = {
    getMode: function () { return mode; },
    setMode: function (value) { return changeMode(value, 'mode-change', true); },
    resolve: resolve
  };
  window.addEventListener('storage', function (event) {
    if (event && event.key === MODE_KEY) changeMode(validMode(event.newValue) ? event.newValue : 'actual', 'storage', false);
  });
}());

// ============================================================
// Stock Terminal — Market lookup(全台股/美股 代號↔市場↔名稱,單一真理來源)
// ------------------------------------------------------------
// 市場判定一律走 Market.of():① 權威表(/universe,可更新)優先 ② 代號格式兜底
// (台股=數字 / ^TW、美股=字母)。格式兜底使其對「未收錄的新上市」也永遠正確,
// 表則提供名稱、存在驗證、及「立即更新」收錄新股/ETF。
// 工具列「🗂 代號庫」可看數量、最後更新時間、一鍵更新。
// ============================================================
(function () {
  'use strict';
  var SRV = window.SERVER || 'http://localhost:18432';
  var _tw = null, _us = null, _twmeta = null, _meta = { updated: 0, counts: {} };

  function isTwFmt(c) { c = String(c || ''); return /^\d/.test(c) || /^\^TW/i.test(c); }

  var Market = {
    // 市場判定(永不失敗、對新代號也正確):US 表命中→US;TW 表/格式→TW;字母→US。
    of: function (code) {
      code = String(code || '').toUpperCase();
      // 合成指數／本地序列：台股語意（紅漲綠跌、不附 .TW）
      if (code === '__MARGIN_RATIO__' || code === '__TXF__'
          || code === '__TW_RATES__' || code === '__TW_MARGIN_MIX__'
          || code === '__US_RATES_CREDIT__' || code === '__US_CPI_FIN__') {
        // 合成序列：台股語意（利率／融資）或美股語意由 id 前綴判斷
        if (code.indexOf('__US_') === 0) return 'US';
        return 'TW';
      }
      if (_us && _us[code]) return 'US';
      if (_tw && _tw[code]) return 'TW';
      return isTwFmt(code) ? 'TW' : 'US';
    },
    isTW: function (code) { return this.of(code) === 'TW'; },
    name: function (code) {
      code = String(code || '').toUpperCase();
      return (_tw && _tw[code]) || (_us && _us[code]) || '';
    },
    known: function (code) { code = String(code || '').toUpperCase(); return !!((_tw && _tw[code]) || (_us && _us[code])); },
    meta: function (code) { code = String(code || '').toUpperCase(); return (_twmeta && _twmeta[code]) || null; },
    metaMap: function () { return _twmeta || {}; },
    counts: function () { return _meta.counts || {}; },
    updated: function () { return _meta.updated || 0; },

    load: async function () {
      try {
        var d = await fetch(SRV + '/universe', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; });
        if (d) {
          _tw = d.tw || {}; _us = d.us || {}; _twmeta = d.twmeta || {};
          _meta = { updated: d.updated || 0, counts: d.counts || { tw: Object.keys(_tw).length, us: Object.keys(_us).length } };
          console.log('[market] universe loaded · TW', Object.keys(_tw).length, '· US', Object.keys(_us).length, '· meta', Object.keys(_twmeta).length);
        }
      } catch (e) { console.warn('[market] load failed (用格式兜底):', e); }
      return this;
    },
    refresh: async function () {
      var r = await fetch(SRV + '/universe/refresh', { method: 'POST' }).then(function (x) { return x.json(); });
      await this.load();
      return r;
    },
  };
  window.Market = Market;

  // ── 「代號庫」小視窗(數量 / 最後更新 / 立即更新) ──────────
  // ── 指標格式化 ──
  function _n(v, d) { return (v === null || v === undefined || isNaN(v)) ? '–' : (+v).toFixed(d == null ? 2 : d); }
  function _cap(v) {
    if (v === null || v === undefined || isNaN(v)) return '–';
    if (v >= 1e12) return (v / 1e12).toFixed(2) + '兆';
    if (v >= 1e8) return (v / 1e8).toFixed(2) + '億';
    if (v >= 1e4) return (v / 1e4).toFixed(1) + '萬';
    return String(Math.round(v));
  }
  function _vol(v) {  // 股數 → 張
    if (v === null || v === undefined || isNaN(v)) return '–';
    var lots = v / 1000;
    return lots >= 1e4 ? (lots / 1e4).toFixed(1) + '萬張' : Math.round(lots).toLocaleString();
  }
  function _chgCell(code, v) {
    if (v === null || v === undefined || isNaN(v)) return '<td style="text-align:right">–</td>';
    var col = window.Colors ? Colors.dir(code, v) : (v > 0 ? '#ef4444' : v < 0 ? '#22c55e' : '#9aa');
    var s = (v > 0 ? '+' : '') + v.toFixed(2) + '%';
    return '<td style="text-align:right;color:' + col + ';font-weight:600">' + s + '</td>';
  }
  function _esc(s) { return String(s == null ? '' : s).replace(/[<>&"]/g, function (c) { return ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c]; }); }

  function openDlg() {
    var m = document.getElementById('uni-modal');
    if (!m) {
      var st = document.createElement('style'); st.textContent =
        '#uni-modal{position:fixed;inset:0;background:rgba(6,10,18,.7);z-index:10000;display:none;align-items:center;justify-content:center}' +
        '#uni-box{background:#0d1117;border:1px solid #2f4a6e;border-radius:10px;width:min(880px,96vw);max-height:88vh;display:flex;flex-direction:column;padding:14px 16px;font-family:monospace;color:#cbd5e1;box-shadow:0 14px 40px rgba(0,0,0,.55)}' +
        '#uni-box h3{margin:0 0 8px;font-size:14px;color:#cfe3ff;display:flex;justify-content:space-between;align-items:center}' +
        '#uni-box .x{cursor:pointer;color:#8aa}' +
        '#uni-box button{background:#13233b;border:1px solid #2f4a6e;color:#cfe3ff;border-radius:5px;padding:6px 12px;cursor:pointer;font-family:monospace;font-size:11px}' +
        '#uni-q{width:100%;box-sizing:border-box;background:#0a0f17;border:1px solid #2f4a6e;border-radius:5px;color:#e6edf3;font-family:monospace;font-size:12px;padding:7px 9px;margin:2px 0 8px}' +
        '#uni-wrap{overflow:auto;border:1px solid #1d2b40;border-radius:6px}' +
        '#uni-tbl{border-collapse:collapse;width:100%;font-size:10px;white-space:nowrap}' +
        '#uni-tbl th{position:sticky;top:0;background:#13233b;color:#9fc3ff;padding:5px 7px;text-align:right;font-weight:600;border-bottom:1px solid #2f4a6e}' +
        '#uni-tbl th:nth-child(-n+3),#uni-tbl td:nth-child(-n+3){text-align:left}' +
        '#uni-tbl td{padding:4px 7px;border-bottom:1px solid #16202f;color:#cbd5e1}' +
        '#uni-tbl tr:hover td{background:#11203a}' +
        '#uni-tbl .code{color:#fff;font-weight:700;cursor:pointer}' +
        '#uni-st{font-size:10px;color:#8aa;margin-top:8px;min-height:14px}';
      document.head.appendChild(st);
      m = document.createElement('div'); m.id = 'uni-modal';
      m.innerHTML = '<div id="uni-box">' +
        '<h3>🗂 代號庫 · 台股清單(上市/上櫃/ETF)+ 每股四大指標<span class="x" onclick="document.getElementById(\'uni-modal\').style.display=\'none\'">×</span></h3>' +
        '<div id="uni-head" style="font-size:11px;line-height:1.7"></div>' +
        '<input id="uni-q" placeholder="搜尋代號 / 中文 / 英文(例:2330、台積、TSMC)— 留空顯示前 60 檔">' +
        '<div id="uni-wrap"><table id="uni-tbl"></table></div>' +
        '<div id="uni-st"></div></div>';
      document.body.appendChild(m);
      m.addEventListener('click', function (e) { if (e.target === m) m.style.display = 'none'; });
      var q = m.querySelector('#uni-q');
      q.addEventListener('input', function () { renderList(q.value.trim()); });
    }
    renderHead();
    renderList((document.getElementById('uni-q').value || '').trim());
    m.style.display = 'flex';
  }

  function renderHead() {
    var c = Market.counts(), u = Market.updated();
    document.getElementById('uni-head').innerHTML =
      '台股 <b style="color:#fff">' + (c.tw || 0) + '</b> 檔 · 指標覆蓋 <b style="color:#fff">' + (c.twmeta || 0) + '</b> · 美股 <b style="color:#fff">' + (c.us || 0) + '</b> 檔　' +
      '<span style="color:#8aa">更新:' + (u ? new Date(u * 1000).toLocaleString('zh-TW') : '尚未') + '</span>　' +
      '<button id="uni-refresh" style="font-size:10px;padding:3px 8px">↻ 一鍵更新(名稱+指標,收錄新上市櫃)</button>';
    document.getElementById('uni-refresh').onclick = async function () {
      var stEl = document.getElementById('uni-st');
      stEl.textContent = '更新中…(抓 TWSE/TPEx 量價·估值·財報·公司名 + NASDAQ,約 20–60 秒)';
      this.disabled = true;
      try {
        var r = await Market.refresh();
        stEl.textContent = (r && r.ok) ? ('✓ 已更新 · 台股 ' + (r.counts.tw || 0) + ' · 指標 ' + (r.counts.twmeta || 0) + ' · 美股 ' + (r.counts.us || 0)) : ('⚠ ' + ((r && r.error) || '更新失敗'));
      } catch (e) { stEl.textContent = '⚠ ' + e.message; }
      renderHead();
      renderList((document.getElementById('uni-q').value || '').trim());
    };
  }

  function renderList(q) {
    var mm = Market.metaMap(), codes = Object.keys(mm);
    q = (q || '').toUpperCase();
    var rows = [];
    for (var i = 0; i < codes.length; i++) {
      var code = codes[i], d = mm[code];
      if (q) {
        var hay = (code + ' ' + (d.zh || '') + ' ' + (d.en || '')).toUpperCase();
        if (hay.indexOf(q) < 0) continue;
      }
      rows.push(code);
      if (!q && rows.length >= 60) break;
    }
    rows.sort(function (a, b) { return a < b ? -1 : 1; });
    var head = '<thead><tr>' +
      ['代號', '中文', '英文', '收盤', '漲跌%', '量(張)', 'PE', 'PB', '殖%', 'EPS', '毛%', '營%', '淨%', '市值', '板'].
        map(function (h) { return '<th>' + h + '</th>'; }).join('') + '</tr></thead>';
    var body = rows.map(function (code) {
      var d = mm[code];
      return '<tr>' +
        '<td class="code" onclick="(window.loadSym||function(){})(\'' + code + '\');document.getElementById(\'uni-modal\').style.display=\'none\'">' + code + '</td>' +
        '<td>' + _esc(d.zh) + '</td>' +
        '<td style="color:#9aa">' + _esc(d.en) + '</td>' +
        '<td style="text-align:right">' + _n(d.close, 2) + '</td>' +
        _chgCell(code, d.chg) +
        '<td style="text-align:right">' + _vol(d.vol) + '</td>' +
        '<td style="text-align:right">' + _n(d.pe, 2) + '</td>' +
        '<td style="text-align:right">' + _n(d.pb, 2) + '</td>' +
        '<td style="text-align:right">' + _n(d['yield'], 2) + '</td>' +
        '<td style="text-align:right">' + _n(d.eps, 2) + '</td>' +
        '<td style="text-align:right">' + _n(d.gross, 1) + '</td>' +
        '<td style="text-align:right">' + _n(d.op, 1) + '</td>' +
        '<td style="text-align:right">' + _n(d.net, 1) + '</td>' +
        '<td style="text-align:right">' + _cap(d.mktcap) + '</td>' +
        '<td style="color:#7a8aa0">' + _esc(d.board) + '</td>' +
        '</tr>';
    }).join('');
    var tbl = document.getElementById('uni-tbl');
    if (!codes.length) {
      tbl.innerHTML = head + '<tbody><tr><td colspan="15" style="padding:14px;color:#8aa">尚無指標資料 — 按上方「一鍵更新」抓取。</td></tr></tbody>';
    } else {
      tbl.innerHTML = head + '<tbody>' + (body || '<tr><td colspan="15" style="padding:14px;color:#8aa">查無符合</td></tr>') + '</tbody>';
    }
    document.getElementById('uni-st').textContent = q ? (rows.length + ' 筆符合') : ('共 ' + codes.length + ' 檔,顯示前 ' + rows.length + '(輸入關鍵字搜尋全部)');
  }
  window.universeOpen = openDlg;

  (function () {
    var spec = { id: 'btn-universe', label: '🗂 代號庫', cat: 'pin', title: '台股/美股 代號庫(lookup)· 可立即更新收錄新上市', onclick: openDlg };
    (window.Toolbar ? window.Toolbar.register : function (s) { (window.__tbQueue = window.__tbQueue || []).push(s); })(spec);
  })();

  Market.load();   // boot:載表(失敗不影響,格式兜底永遠可用)
})();

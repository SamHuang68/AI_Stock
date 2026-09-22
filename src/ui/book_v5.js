/* ============================================================================
 * book_v5.js  —  Stock Terminal 5.0 Stage 6：投組風險側欄
 * ----------------------------------------------------------------------------
 * 成分：共用實際持倉／等權觀察池；手動權重明列為情境模擬。
 * 資料：POST /portfolio → 波動／VaR／Beta／產業／相關性（與 portfolio_v3 同後端）
 * 掛載：#mount-book；側欄「投組」
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var lastData = null;
  var source = 'shared';
  var generation = 0;
  var controller = null;
  var active = false;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
    });
  }

  function finiteMetric(v) { return typeof v === 'number' && isFinite(v); }
  function riskValue(v, digits, suffix) { return finiteMetric(v) ? v.toFixed(digits) + (suffix || '') : '資料不足'; }
  function riskSummary(d) {
    var stocks = d.stocks || {}, codes = Object.keys(stocks), p = d.portfolio || {}, q = d.quality || {};
    var cv = Object.keys(d.corr || {}).map(function (k) { return d.corr[k]; }).filter(finiteMetric);
    var beta = 0, weight = 0;
    var betaComplete = codes.length > 0 && !(d.skipped || []).length &&
      (!finiteMetric(q.betaCoveragePct) || q.betaCoveragePct >= 99.9999);
    codes.forEach(function (c) {
      var s = stocks[c];
      if (!finiteMetric(s.beta)) { betaComplete = false; return; }
      beta += (s.weight || 0) * s.beta; weight += s.weight || 0;
    });
    var notes = [];
    if (q.available === false || !finiteMetric(p.vol) || !finiteMetric(p.var95)) notes.push('資料不足，未完成全部投組風險檢查');
    if (finiteMetric(q.holdingCoveragePct)) notes.push('持倉涵蓋率 ' + riskValue(q.holdingCoveragePct, 1, '%'));
    if (finiteMetric(q.betaCoveragePct)) notes.push('Beta 涵蓋率 ' + riskValue(q.betaCoveragePct, 1, '%'));
    if (finiteMetric(q.commonSampleDays)) notes.push('共同有效報酬 ' + q.commonSampleDays + ' 筆');
    if (Array.isArray(q.reasons) && q.reasons.length) notes.push('原因：' + q.reasons.join('、'));
    if (!betaComplete && !(q.reasons || []).length) notes.push('投組 Beta 未涵蓋全部持倉');
    return { vol: p.vol, var95: p.var95, days: p.days,
      correlation: cv.length ? cv.reduce(function (a, b) { return a + b; }, 0) / cv.length : null,
      beta: betaComplete && weight > 0 ? beta / weight : null, note: notes.join(' · ') };
  }

  function sharedContext() {
    if (window.PortfolioContext) return window.PortfolioContext.resolve();
    return { kind: 'actual', label: '實際持倉', ready: false, holdings: [],
      coverage: { total: 0, included: 0, excluded: 0, complete: false },
      issues: [{ message: '共用投組資料契約尚未載入。', action: '請重新載入完整版本；不會以舊邏輯代算。' }] };
  }
  function holdingsToText(h) {
    return (h || []).map(function (x) {
      return x.sym + ' ' + String(x.weight);
    }).join('\n');
  }
  function parseHoldings(txt) {
    var context = { kind: 'simulation', label: '情境模擬（手動權重，非實際持倉）', ready: false,
      holdings: [], coverage: { total: 0, included: 0, excluded: 0, complete: false }, issues: [] };
    var seen = {};
    (txt || '').split('\n').forEach(function (line) {
      var p = line.trim().split(/\s+/);
      if (!p[0]) return;
      context.coverage.total++;
      var sym = p[0].toUpperCase().replace(/\.(TW|TWO)$/, '');
      var w = Number(p[1]);
      if (p.length !== 2 || !/^[A-Z0-9^][A-Z0-9.^=_-]*$/.test(sym) || !isFinite(w) || w <= 0 || seen[sym]) {
        context.issues.push({ sym: sym, message: '模擬代號重複、格式錯誤或權重不是有效正數。', action: '每行輸入不重複代號與大於零的權重，例如 2330 40；權重不得省略。' });
        return;
      }
      seen[sym] = true;
      context.holdings.push({ sym: sym, weight: w, market: /^\d{4,8}[A-Z]?$/.test(sym) ? 'TW' : 'US' });
    });
    context.coverage.included = context.holdings.length;
    context.coverage.excluded = context.coverage.total - context.holdings.length;
    if (!isFinite(context.holdings.reduce(function (sum, row) { return sum + row.weight; }, 0))) {
      context.issues.push({ message: '模擬總權重超出可計算範圍。', action: '請縮小權重單位後再分析。' });
    }
    context.ready = context.holdings.length > 0 && !context.issues.length;
    context.coverage.complete = context.ready;
    if (!context.ready) context.holdings = [];
    return context;
  }

  function currentContext() {
    var shared = sharedContext();
    if ((shared.issues || []).some(function (item) { return item.code === 'private_access_blocked'; })) return shared;
    return source === 'simulation' ? parseHoldings(($('bk-edit') || {}).value) : shared;
  }

  function invalidate() {
    generation++;
    lastData = null;
    if (controller) controller.abort();
    controller = null;
  }

  function contextKey(context) {
    return JSON.stringify({ kind: context.kind, ready: context.ready, holdings: context.holdings, coverage: context.coverage });
  }

  function syncMode(context) {
    var details = $('bk-mode-details');
    if (details) details.textContent = context.label + ' · 有效 ' + context.coverage.included + '／' + context.coverage.total + ' 檔' +
      (context.ready ? '' : ' · 尚未計算；請先處理資料缺漏。');
    var mount = $('mount-book');
    if (mount) mount.querySelectorAll('[data-src]').forEach(function (button) {
      var selected = button.getAttribute('data-src') === context.kind;
      button.classList.toggle('on', selected);
      button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    var sub = $('bk-sub');
    if (sub) sub.textContent = context.label;
  }

  function showUnavailable(context) {
    var body = $('bk-body');
    if (!body) return;
    lastData = null;
    syncMode(context);
    body.innerHTML = '<div class="bk-empty"><div class="bk-empty-card">' +
      '<div class="bk-empty-icon" aria-hidden="true">▦</div><b>尚未計算投組風險</b>' +
      '<p style="font-size:11px;line-height:1.5">' + (context.issues.length ? context.issues.map(function (item) {
        return (item.sym ? esc(item.sym) + '：' : '') + esc(item.message) + '<br>' + esc(item.action);
      }).join('<br><br>') : '請輸入模擬成分與有效正權重，再執行分析。') + '</p></div></div>';
  }

  function injectCSS() {
    var s = $('book-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'book-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-book.on){overflow:hidden!important}' +
      '#view-book.sv-panel.on{max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-book,#mount-book.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#bk-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);width:100%;max-width:none;margin:0;min-width:0;' +
        'box-sizing:border-box;flex:1;min-height:0;display:flex;flex-direction:column}' +
      '#bk-root .bk-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#bk-root .bk-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#bk-root .bk-kicker{display:none!important}' +
      '#bk-root .bk-title{font-family:\'Noto Serif TC\',serif;font-size:17px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#bk-root .bk-sub{font-size:11px;color:var(--tlo);margin:0}' +
      '#bk-root .bk-actions{display:flex;gap:4px;flex-wrap:nowrap;flex:0 0 auto}' +
      '#bk-root .bk-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;white-space:nowrap}' +
      '#bk-root .bk-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#bk-root .bk-btn.on{border-color:var(--gold);color:var(--gold);background:var(--gold-s)}' +
      '#bk-root .bk-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#bk-root .bk-edit-wrap{flex:0 0 auto;margin-bottom:3px}' +
      '#bk-root .bk-edit-toggle{font-size:9px;color:var(--tlo);cursor:pointer;padding:2px 0;user-select:none}' +
      '#bk-root .bk-edit-toggle:hover{color:var(--gold)}' +
      '#bk-root #bk-edit{width:100%;box-sizing:border-box;background:var(--bg);border:1px solid var(--border);' +
        'color:var(--thi);border-radius:5px;padding:4px 6px;font-size:10px;font-family:\'JetBrains Mono\',monospace;' +
        'min-height:36px;max-height:72px;resize:vertical;margin:2px 0 0;display:none}' +
      '#bk-root #bk-edit.open{display:block}' +
      '#bk-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#bk-root .bk-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:4px;margin:0 0 4px;flex:0 0 auto;min-width:0}' +
      '#bk-root .bk-card{background:var(--bg2);border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '#bk-root .bk-card .lab{font-size:10px;color:var(--tlo);letter-spacing:.4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#bk-root .bk-card .val{font-size:12px;font-weight:800;color:var(--thi);margin-top:0;line-height:1.15}' +
      '#bk-root .bk-zone{flex:1;min-height:0;display:grid;grid-template-columns:minmax(220px,32%) minmax(0,1fr);gap:4px;overflow:hidden}' +
      '#bk-root .bk-left,#bk-root .bk-right{min-height:0;overflow:auto;display:flex;flex-direction:column;gap:4px}' +
      '#bk-root .bk-panel{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;min-width:0}' +
      '#bk-root .bk-h{font-size:10px;color:var(--gold);letter-spacing:.5px;margin:0 0 4px;font-weight:700;' +
        'border-left:2px solid var(--gold);padding-left:6px;flex:0 0 auto}' +
      '#bk-root .bk-row{display:flex;align-items:center;gap:6px;margin:2px 0;font-size:10px}' +
      '#bk-root .bk-row .nm{width:110px;flex:0 0 110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px}' +
      '#bk-root .bk-bar{flex:1;background:var(--bg);border-radius:3px;height:8px;overflow:hidden}' +
      '#bk-root .bk-bar i{display:block;height:100%;background:#60a5fa}' +
      '#bk-root .bk-row .pc{width:42px;flex:0 0 42px;text-align:right;font-size:9px}' +
      '#bk-root .bk-cn{display:flex;align-items:center;gap:6px;padding:3px 6px;border-radius:5px;' +
        'background:var(--bg);border:1px solid var(--border);opacity:.4;margin:1px 0}' +
      '#bk-root .bk-cn.on{opacity:1;border-color:var(--gold-m)}' +
      '#bk-root .bk-cn-nm{width:120px;flex:0 0 120px;font-size:9px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#bk-root .bk-cn-bar{flex:1;height:8px;background:var(--bg3);border-radius:3px;overflow:hidden}' +
      '#bk-root .bk-cn-bar i{display:block;height:100%;background:var(--gold)}' +
      '#bk-root .bk-cn-pc{width:40px;flex:0 0 40px;text-align:right;font-size:9px}' +
      '#bk-root .bk-cn-arr{text-align:center;color:var(--tf);font-size:8px;margin:0}' +
      '#bk-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#bk-root th,#bk-root td{padding:3px 5px;border-bottom:1px solid var(--border);text-align:right}' +
      '#bk-root th:first-child,#bk-root td:first-child{text-align:left}' +
      '#bk-root th{color:var(--tlo);font-size:9px}' +
      '#bk-root tr.bk-sym{cursor:pointer}#bk-root tr.bk-sym:hover{background:var(--bg3)}' +
      '#bk-root .bk-hm th.nm,#bk-root .bk-hm td.nm{text-align:left;color:var(--tlo);white-space:nowrap;font-size:8px}' +
      '#bk-root .bk-note{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:2px;flex:0 0 auto}' +
      '#bk-root .bk-loading{font-size:10px;color:var(--tlo);padding:12px 0}' +
      '#bk-root .bk-err{color:var(--orange);font-size:10px;padding:8px 0}' +
      '#bk-root .bk-empty{flex:1;min-height:0;overflow:auto;display:flex;align-items:center;justify-content:center;padding:24px}' +
      '#bk-root .bk-empty-card{width:min(520px,100%);padding:28px 30px;text-align:center;border-radius:11px;' +
        'border:1px solid rgba(125,211,252,.2);background:radial-gradient(circle at 50% 0%,rgba(56,189,248,.11),transparent 58%),' +
        'linear-gradient(145deg,rgba(17,31,50,.9),rgba(7,15,27,.96));box-shadow:0 18px 42px -28px rgba(0,0,0,.95)}' +
      '#bk-root .bk-empty-icon{width:44px;height:44px;margin:0 auto 10px;display:grid;place-items:center;border-radius:12px;' +
        'border:1px solid rgba(245,197,24,.3);background:rgba(245,197,24,.08);color:var(--gold);font-size:22px}' +
      '#bk-root .bk-empty-card b{display:block;color:var(--thi);font-size:14px;margin-bottom:6px}' +
      '#bk-root .bk-empty-card p{margin:0 auto;color:var(--tlo);font-size:10px;line-height:1.6;max-width:390px}' +
      '#bk-root .bk-empty-steps{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:16px}' +
      '#bk-root .bk-empty-steps span{padding:7px 5px;border-radius:6px;border:1px solid rgba(148,163,184,.13);' +
        'background:rgba(5,10,19,.38);color:var(--text);font-size:9px}' +
      '#bk-root .bk-wd{margin:0 0 4px;padding:6px 8px;border-radius:6px;background:var(--bg2);' +
        'border:1px solid rgba(103,232,249,.28);font-size:9px;line-height:1.45}' +
      '#bk-root .bk-wd .t{color:var(--cyan);font-weight:700;letter-spacing:1px;font-size:10px;margin-bottom:2px}' +
      '#bk-root .bk-wd b{color:var(--thi)}';
  }

  function wdStripHtml() {
    try {
      if (!window.WaveDeckBridge || typeof WaveDeckBridge.hintForSymbol !== 'function') {
        return '<div class="bk-wd" id="bk-wd-strip"><div class="t">WAVEDECK</div>橋接未載入</div>';
      }
      var stream = typeof WaveDeckBridge.streamStatus === 'function' ? WaveDeckBridge.streamStatus() : null;
      var h = WaveDeckBridge.hintForSymbol('TXF');
      var chipBit = (typeof WaveDeckBridge.chipHtml === 'function')
        ? WaveDeckBridge.chipHtml('TXF')
        : '';
      if (!h) {
        return '<div class="bk-wd" id="bk-wd-strip"><div class="t">WAVEDECK</div>' +
          (stream && stream.offline ? '串流失聯（REST 後援中）' : '執行台未連線或尚無狀態（可開 START_WAVEDECK）') +
          '</div>';
      }
      var inv = h.invalidation_price != null
        ? String(h.invalidation_price)
        : (h.invalidation ? String(h.invalidation.price) : '—');
      var conf = (h.confidence != null && isFinite(h.confidence))
        ? Math.round(Number(h.confidence) * 100) + '%' : '—';
      var spill = (h.spillover != null && isFinite(h.spillover))
        ? Math.round(Number(h.spillover) * 100) + '%' : '—';
      var rot = h.rotation || '—';
      var dir = h.direction || '—';
      return '<div class="bk-wd" id="bk-wd-strip"><div class="t">WAVEDECK · 執行狀態 ' + chipBit + '</div>' +
        '標的 <b>' + esc(h.symbol) + '</b> · 方向 <b>' + esc(dir) + '</b> · 動作 <b>' + esc(h.action) + '</b> · 信心 <b>' + conf + '</b><br>' +
        '部位 <b>' + esc(h.position_size != null ? h.position_size : (h.qty != null ? h.qty : '—')) +
        '</b> · 模式 <b>' + esc(h.wd_mode || h.mode) + '</b> · FSM <b>' + esc(h.fsm) + '</b><br>' +
        '防守／失效 <b>' + esc(inv) + '</b><br>' +
        '宏觀風格 <b>' + esc(h.style != null ? h.style : '—') + '</b> · 輪動 <b>' + esc(rot) +
        '</b> · 外溢 <b>' + esc(spill) + '</b>' +
        '</div>';
    } catch (e) {
      return '';
    }
  }

  function _bindWdChipLive() {
    if (_bindWdChipLive._on) return;
    _bindWdChipLive._on = true;
    var refresh = function () {
      var el = document.getElementById('bk-wd-strip');
      if (!el) return;
      var html = wdStripHtml();
      if (!html) return;
      var wrap = document.createElement('div');
      wrap.innerHTML = html;
      var neu = wrap.firstChild;
      if (neu && el.parentNode) el.parentNode.replaceChild(neu, el);
    };
    try {
      window.addEventListener('wavedeck:chip', refresh);
      window.addEventListener('wavedeck:full_sync', refresh);
      window.addEventListener('wavedeck:stream', refresh);
    } catch (e) {}
  }

  function bars(obj, color) {
    var entries = Object.keys(obj || {}).map(function (k) { return [k, obj[k]]; })
      .sort(function (a, b) { return b[1] - a[1]; });
    if (!entries.length) return '<div class="bk-note">無產業資料</div>';
    var max = entries[0][1] || 1;
    return entries.map(function (e) {
      var w = max > 0 ? Math.round(e[1] / max * 100) : 0;
      return '<div class="bk-row"><span class="nm">' + esc(e[0]) + '</span>' +
        '<span class="bk-bar"><i style="width:' + w + '%;background:' + (color || '#60a5fa') + '"></i></span>' +
        '<span class="pc">' + Number(e[1]).toFixed(1) + '%</span></div>';
    }).join('');
  }

  function chainDiagram(chainExp) {
    var chain = (window.SC_CHAINS && window.SC_CHAINS.TW) || null;
    if (!chain) {
      return Object.keys(chainExp).length ? bars(chainExp, 'var(--gold)') : '<div class="bk-note">無供應鏈對照</div>';
    }
    var maxExp = Math.max.apply(null, [1].concat(chain.map(function (g) { return chainExp[g.stage] || 0; })));
    return chain.map(function (g) {
      var e = chainExp[g.stage] || 0;
      var w = Math.round(e / maxExp * 100);
      return '<div class="bk-cn' + (e > 0 ? ' on' : '') + '"><span class="bk-cn-nm">' + esc(g.stage) + '</span>' +
        '<span class="bk-cn-bar"><i style="width:' + w + '%"></i></span>' +
        '<span class="bk-cn-pc">' + (e > 0 ? e.toFixed(1) + '%' : '—') + '</span></div>';
    }).join('<div class="bk-cn-arr">▼</div>') +
      (chainExp['其他'] ? '<div class="bk-note">未對應供應鏈:' + chainExp['其他'].toFixed(1) + '%</div>' : '');
  }

  function heatmap(codes, stocks, corr) {
    function val(a, b) {
      if (a === b) return 1;
      if (corr[a + '|' + b] != null) return corr[a + '|' + b];
      if (corr[b + '|' + a] != null) return corr[b + '|' + a];
      return null;
    }
    var th = '<th class="nm"></th>' + codes.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('');
    var rows = codes.map(function (a) {
      var tds = codes.map(function (b) {
        var v = val(a, b), bg = 'transparent', col = 'var(--tlo)';
        if (v != null) {
          bg = v >= 0
            ? 'rgba(245,197,24,' + Math.max(0, Math.min(1, v)).toFixed(2) + ')'
            : 'rgba(96,165,250,' + Math.min(1, -v).toFixed(2) + ')';
          if (v > 0.55) col = '#0f172a';
        }
        return '<td style="background:' + bg + ';color:' + col + '">' + (v == null ? '—' : v.toFixed(2)) + '</td>';
      }).join('');
      return '<tr><td class="nm">' + esc((stocks[a] && stocks[a].name) || a) + '</td>' + tds + '</tr>';
    }).join('');
    return '<table class="bk-hm"><thead><tr>' + th + '</tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-book');
    if (!panel) return null;
    var mount = $('mount-book');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-book';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('bk-root')) {
      var init = sharedContext();
      mount.innerHTML =
        '<div id="bk-root">' +
          '<div class="bk-head"><div>' +
            '<span class="bk-title">投組風險</span>' +
            '<span class="bk-sub" id="bk-sub">波動 · VaR · Beta · 產業曝險</span>' +
          '</div><div class="bk-actions">' +
            '<button type="button" class="bk-btn" id="bk-edit-toggle">成分 ▾</button>' +
            '<button type="button" class="bk-btn primary" id="bk-run">分析</button>' +
            '<button type="button" class="bk-btn" data-shell-back>← 儀表板</button>' +
          '</div></div>' +
          '<div class="bk-edit-wrap">' +
            '<div role="group" aria-label="投組資料模式" style="display:flex;gap:6px;flex-wrap:wrap">' +
              '<button type="button" class="bk-btn" data-src="actual">實際持倉</button>' +
              '<button type="button" class="bk-btn" data-src="observation_pool">觀察池（等權）</button>' +
              '<button type="button" class="bk-btn" data-src="simulation">情境模擬</button>' +
            '</div><div class="bk-note" id="bk-mode-details" aria-live="polite" style="font-size:11px;line-height:1.45"></div>' +
            '<textarea id="bk-edit" aria-label="情境模擬成分" placeholder="模擬專用；每行：代號 正權重（必填），例如 2330 40">' +
              esc(holdingsToText(init.holdings)) + '</textarea>' +
          '</div>' +
          '<div id="bk-body" class="bk-loading">待命</div>' +
        '</div>';
      var editToggle = $('bk-edit-toggle');
      var editTa = $('bk-edit');
      if (editToggle && editTa) {
        editToggle.onclick = function () {
          var open = editTa.classList.toggle('open');
          editToggle.textContent = open ? '成分 ▴' : '成分 ▾';
        };
        editTa.oninput = function () {
          source = 'simulation';
          invalidate();
          syncMode(currentContext());
          var body = $('bk-body');
          if (body) body.innerHTML = '<div class="bk-loading">模擬內容已變更；請按分析。先前結果已失效。</div>';
        };
      }
      mount.querySelectorAll('[data-src]').forEach(function (b) {
        b.onclick = function () {
          var next = b.getAttribute('data-src');
          if (next === 'simulation') {
            source = 'simulation';
            if ($('bk-edit')) $('bk-edit').classList.add('open');
            analyze(currentContext());
          } else {
            source = 'shared';
            var before = window.PortfolioContext && window.PortfolioContext.getMode();
            if (window.PortfolioContext) window.PortfolioContext.setMode(next);
            if (before === next || !window.PortfolioContext) activate();
          }
        };
      });
      var run = $('bk-run');
      if (run) run.onclick = function () {
        analyze(currentContext());
      };
    }
    return $('bk-body');
  }

  function render(d, context) {
    context = context || currentContext();
    var body = $('bk-body');
    if (!body) return;
    lastData = d;
    var stocks = d.stocks || {};
    var codes = Object.keys(stocks);
    var stageMap = window.SC_STAGE || {};
    var chainExp = {};
    codes.forEach(function (c) {
      var st = stageMap[c] || '其他';
      chainExp[st] = (chainExp[st] || 0) + (stocks[c].weight || 0);
    });

    var risk = riskSummary(d), avgCorr = risk.correlation, pBeta = risk.beta;

    var sub = $('bk-sub');
    if (sub) {
      sub.textContent = context.label + ' · ' + codes.length + ' 檔 · 基準 ' + (d.benchmark || '^TWII') +
        ' · 更新 ' + new Date().toLocaleTimeString('zh-TW');
    }

    var V = window.Viz;
    var var95 = risk.var95;
    var vol = risk.vol;
    // VaR：日風險 >2% 警示、>4% 危險；相關性以 0–100% 刻度，>50/70 警示
    var varMeter = V && finiteMetric(var95) ? V.ratioMeter(Math.abs(var95), 2, 4) : '';
    var corrMeter = V && finiteMetric(avgCorr) ? V.ratioMeter(Math.abs(avgCorr) * 100, 50, 70) : '';
    var betaViz = '';
    if (V && finiteMetric(pBeta)) {
      betaViz = V.magBar(pBeta - 1, 1, {
        label: 'β−1',
        fmt: function () { return pBeta.toFixed(2); }
      });
    }
    var h = wdStripHtml() + '<div class="bk-strip">' +
      '<div class="bk-card"><div class="lab">年化波動</div><div class="val">' + riskValue(vol, 1, '%') + '</div>' +
        (V && finiteMetric(vol) ? V.scoreMeter(Math.min(100, vol * 2), { hi: 40, mid: 25 }) : '') + '</div>' +
      '<div class="bk-card"><div class="lab">1日 95% VaR</div><div class="val">' + riskValue(var95, 2, '%') + '</div>' +
        varMeter + '</div>' +
      '<div class="bk-card"><div class="lab">平均相關性</div><div class="val">' + riskValue(avgCorr, 2) + '</div>' +
        corrMeter + '</div>' +
      '<div class="bk-card"><div class="lab">投組 Beta</div><div class="val">' + riskValue(pBeta, 2) + '</div>' +
        betaViz + '</div>' +
      '<div class="bk-card"><div class="lab">持倉檔數</div><div class="val">' + codes.length + '</div></div>' +
      '<div class="bk-card"><div class="lab">樣本天數</div><div class="val">' + riskValue(risk.days, 0) + '</div></div>' +
      '</div>' + (risk.note ? '<div class="bk-note">' + esc(risk.note) + '</div>' : '');

    h += '<div class="bk-zone">';
    h += '<div class="bk-left">' +
      '<div class="bk-panel"><div class="bk-h">供應鏈曝險</div>' + chainDiagram(chainExp) + '</div>' +
      '<div class="bk-panel"><div class="bk-h">產業曝險</div>' + bars(d.sector, '#60a5fa') + '</div>' +
      '</div>';

    h += '<div class="bk-right">' +
      '<div class="bk-panel"><div class="bk-h">個股（依權重）</div>' +
      '<table><thead><tr><th>個股</th><th>權重</th><th>波動</th><th>Beta</th></tr></thead><tbody>';
    codes.map(function (c) { return [c, stocks[c]]; })
      .sort(function (a, b) { return (b[1].weight || 0) - (a[1].weight || 0); })
      .forEach(function (e) {
        var s = e[1];
        h += '<tr class="bk-sym" data-code="' + esc(e[0]) + '"><td>' + esc(s.name || e[0]) +
          ' <span style="color:var(--tlo);font-size:9px">' + esc(e[0]) + '</span></td><td>' +
          (s.weight || 0).toFixed(1) + '%</td><td>' +
          (s.vol != null ? s.vol.toFixed(1) + '%' : '—') + '</td><td>' +
          (s.beta != null ? s.beta.toFixed(2) : '—') + '</td></tr>';
      });
    h += '</tbody></table></div>';

    if (codes.length >= 2) {
      var hmCodes = codes.map(function (c) { return [c, stocks[c].weight || 0]; })
        .sort(function (a, b) { return b[1] - a[1]; }).slice(0, 10).map(function (e) { return e[0]; });
      h += '<div class="bk-panel"><div class="bk-h">相關性熱力' + (codes.length > 10 ? '（前10）' : '') + '</div>' +
        heatmap(hmCodes, stocks, d.corr || {}) + '</div>';
    }
    h += '</div></div>';

    h += '<div class="bk-note">/portfolio · 5年日線 vs ' + esc(d.benchmark || '^TWII') +
      (d.skipped && d.skipped.length ? ' · 略過：' + esc(d.skipped.join('、')) : '') +
      ' · ⚠ 非投資建議</div>';

    body.innerHTML = h;
    body.querySelectorAll('tr.bk-sym').forEach(function (el) {
      el.onclick = function () {
        var c = el.getAttribute('data-code');
        if (c && typeof loadSym === 'function') {
          loadSym(c, 'TW');
          if (window.ShellV5) window.ShellV5.go('chart');
        }
      };
    });
  }

  function analyze(context) {
    var body = ensureMount();
    invalidate();
    if (!body) return;
    syncMode(context);
    if (!context.ready) {
      showUnavailable(context);
      return;
    }
    if (context.holdings.some(function (item) { return item.market !== 'TW'; })) {
      showUnavailable({ kind: context.kind, label: context.label, ready: false, holdings: [], coverage: context.coverage,
        issues: [{ message: '目前投組風險後端僅支援臺股；非臺股成分不可混入臺股基準。',
          action: '請分市場檢視標的；完成多市場資料與比較基準契約前，不執行此投組計算。' }] });
      return;
    }
    var requestGeneration = generation;
    var requestKey = contextKey(context);
    function current() {
      if (requestGeneration !== generation) return false;
      var latest = currentContext();
      if (contextKey(latest) !== requestKey) {
        invalidate();
        if (!latest.ready) showUnavailable(latest);
        else {
          syncMode(latest);
          body.innerHTML = '<div class="bk-loading">投組資料已變更；本次結果已失效，請重新分析。</div>';
        }
        return false;
      }
      return true;
    }
    controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    body.innerHTML = '<div class="bk-loading">分析中…（首次可能需回補日線）</div>';
    fetch(SRV + '/portfolio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ holdings: context.holdings, portfolioKind: context.kind }),
      signal: controller ? controller.signal : undefined
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!current()) return;
        if (!x.ok || !x.d || x.d.error) {
          body.innerHTML = '<div class="bk-err">分析失敗：' + esc((x.d && x.d.error) || '無資料') + '</div>';
          return;
        }
        var paint = function () { if (current()) render(x.d, context); };
        _bindWdChipLive();
        var stream = window.WaveDeckBridge && typeof WaveDeckBridge.streamStatus === 'function'
          ? WaveDeckBridge.streamStatus() : null;
        // 串流已有狀態時直接呈現，否則取得一次橋接狀態；兩條路徑都檢查請求代次。
        if (stream && stream.ok && stream.chips > 0) {
          paint();
        } else {
          var pull = window.WaveDeckBridge && (
            typeof WaveDeckBridge.fetchChipState === 'function'
              ? WaveDeckBridge.fetchChipState
              : WaveDeckBridge.fetchState
          );
          if (typeof pull === 'function') {
            pull.call(WaveDeckBridge, false).then(paint).catch(paint);
          } else {
            paint();
          }
        }
      })
      .catch(function (e) {
        if (!current()) return;
        lastData = null;
        body.innerHTML = '<div class="bk-err">分析失敗：' + esc(e.message || e) + '</div>';
      });
  }

  function activate() {
    active = true;
    ensureMount();
    var ta = $('bk-edit');
    var context = currentContext();
    if (source !== 'simulation' && ta) ta.value = holdingsToText(context.holdings);
    analyze(context);
  }

  window.BookV5 = {
    activate: activate,
    deactivate: function () { active = false; invalidate(); },
    refresh: activate,
    last: function () { return lastData; }
  };

  window.addEventListener('portfolioContext', function () {
    source = 'shared';
    invalidate();
    if (active) activate();
    else if ($('bk-body')) {
      syncMode(sharedContext());
      $('bk-body').innerHTML = '<div class="bk-loading">投組模式已變更；重新開啟本頁後分析。</div>';
    }
  });

  // 面板生命週期由 Shell／AppKernel 統一呼叫。
})();

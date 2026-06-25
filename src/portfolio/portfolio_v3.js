/* ============================================================================
 * portfolio_v3.js — v4.0 投組風險面板
 * ----------------------------------------------------------------------------
 * 成分股來源:持倉(市值權重) / 自選(等權重) / 自訂(可編輯代號+權重)。
 * 後端 /portfolio:相關性 / 年化波動 / 1日95%VaR / Beta / 投組Beta / 產業曝險。
 * 供應鏈曝險:沿用 window.SC_STAGE(CHAIN_TW),畫成鏈條圖(SC_CHAINS.TW 順序)。
 * 顏色:曝險用中性金/藍(非漲跌);數字一律進位。
 * ========================================================================== */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }

  function holdingsFromPositions() {
    if (typeof S !== 'undefined' && S.positions && Object.keys(S.positions).length) {
      return Object.keys(S.positions).map(function (code) {
        var p = S.positions[code] || {};
        var px = p.lastPrice || p.entry || 0;
        var val = px * (p.shares || 0);
        return { sym: code, weight: val > 0 ? val : 1 };
      });
    }
    return [];
  }
  function holdingsFromWatch() {
    if (typeof S !== 'undefined' && S.watches && Object.keys(S.watches).length) {
      return Object.keys(S.watches).map(function (code) { return { sym: code, weight: 1 }; });
    }
    return [];
  }
  function holdings() { var p = holdingsFromPositions(); return p.length ? p : holdingsFromWatch(); }

  function holdingsToText(h) {
    return h.map(function (x) { return x.sym + ' ' + (Math.round((x.weight || 1) * 100) / 100); }).join('\n');
  }
  function parseHoldings(txt) {
    return (txt || '').split('\n').map(function (line) {
      var p = line.trim().split(/\s+/);
      if (!p[0]) return null;
      var w = parseFloat(p[1]);
      return { sym: p[0].replace('.TW', '').replace('.TWO', ''), weight: (isFinite(w) && w > 0) ? w : 1 };
    }).filter(Boolean);
  }

  function injectStyle() {
    if (document.getElementById('pf-style')) return;
    var s = document.createElement('style'); s.id = 'pf-style';
    s.textContent =
      '#pf-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}' +
      '#pf-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(760px,95vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}' +
      '#pf-box h3{margin:0 0 8px;font-size:15px;display:flex;justify-content:space-between;align-items:center}' +
      '#pf-box .x{cursor:pointer;color:#64748b;font-size:18px}#pf-box .x:hover{color:#e2e8f0}' +
      '.pf-edit-bar{display:flex;align-items:center;gap:6px;margin-bottom:6px}' +
      '.pf-mini{background:#16213a;border:1px solid #28324d;color:#cbd5e1;border-radius:6px;padding:3px 8px;font-size:11px;cursor:pointer}' +
      '.pf-mini:hover{border-color:#F5C518;color:#F5C518}.pf-go{background:#F5C518;color:#0f172a;border:none;font-weight:700;margin-left:auto}' +
      '#pf-edit{width:100%;box-sizing:border-box;background:#0b1220;border:1px solid #334155;color:#e2e8f0;border-radius:8px;padding:8px;font-size:12px;font-family:monospace;min-height:54px;resize:vertical;margin-bottom:10px}' +
      '.pf-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin:6px 0 14px}' +
      '.pf-card{background:#16213a;border:1px solid #28324d;border-radius:8px;padding:8px 10px}' +
      '.pf-card .lab{font-size:10px;color:#94a3b8}.pf-card .val{font-size:18px;font-weight:700;margin-top:2px}' +
      '.pf-h{font-weight:700;margin:14px 0 6px;font-size:12px;color:#cbd5e1;border-left:3px solid #F5C518;padding-left:7px}' +
      '.pf-row{display:flex;align-items:center;gap:8px;margin:3px 0}' +
      '.pf-row .nm{width:120px;flex:0 0 120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '.pf-bar{flex:1;background:#1e293b;border-radius:4px;height:14px;overflow:hidden}.pf-bar i{display:block;height:100%;background:#F5C518}' +
      '.pf-row .pc{width:48px;flex:0 0 48px;text-align:right;font-family:monospace}' +
      '.pf-cn{display:flex;align-items:center;gap:8px;padding:4px 8px;border-radius:6px;background:#0d1526;border:1px solid #1e293b;opacity:.4}' +
      '.pf-cn.on{opacity:1;border-color:#F5C518}' +
      '.pf-cn-nm{width:135px;flex:0 0 135px;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
      '.pf-cn-bar{flex:1;height:12px;background:#1e293b;border-radius:4px;overflow:hidden}.pf-cn-bar i{display:block;height:100%;background:#F5C518}' +
      '.pf-cn-pc{width:46px;flex:0 0 46px;text-align:right;font-family:monospace;font-size:11px}' +
      '.pf-cn-arr{text-align:center;color:#475569;font-size:9px;line-height:1;margin:1px 0}' +
      '#pf-box table{width:100%;border-collapse:collapse;margin-top:4px}' +
      '#pf-box th,#pf-box td{padding:4px 6px;border-bottom:1px solid #1e293b;text-align:right;font-family:monospace}' +
      '#pf-box th:first-child,#pf-box td:first-child{text-align:left;font-family:inherit}' +
      '.pf-hm{font-size:9px;margin-top:4px;table-layout:fixed}' +
      '.pf-hm td,.pf-hm th{padding:2px 3px;border:1px solid #0f172a;text-align:center;font-family:monospace}' +
      '.pf-hm th.nm,.pf-hm td.nm{text-align:left;font-family:inherit;font-size:9px;color:#94a3b8;white-space:nowrap}' +
      '#pf-box .note{font-size:10px;color:#64748b;margin-top:8px;line-height:1.5}';
    document.head.appendChild(s);
  }

  function bars(obj, color) {
    var entries = Object.keys(obj).map(function (k) { return [k, obj[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
    var max = entries.length ? entries[0][1] : 1;
    return entries.map(function (e) {
      var w = max > 0 ? Math.round(e[1] / max * 100) : 0;
      return '<div class="pf-row"><span class="nm">' + esc(e[0]) + '</span>' +
        '<span class="pf-bar"><i style="width:' + w + '%;background:' + (color || '#F5C518') + '"></i></span>' +
        '<span class="pc">' + e[1].toFixed(1) + '%</span></div>';
    }).join('');
  }

  // 供應鏈曝險鏈條圖(按 SC_CHAINS.TW 上游→下游順序;有曝險的亮起)
  function chainDiagram(chainExp) {
    var chain = (typeof window !== 'undefined' && window.SC_CHAINS && window.SC_CHAINS.TW) || null;
    if (!chain) return Object.keys(chainExp).length ? bars(chainExp, '#F5C518') : '<div class="note">無供應鏈對照</div>';
    var maxExp = Math.max.apply(null, [1].concat(chain.map(function (g) { return chainExp[g.stage] || 0; })));
    var nodes = chain.map(function (g) {
      var e = chainExp[g.stage] || 0;
      var w = Math.round(e / maxExp * 100);
      return '<div class="pf-cn' + (e > 0 ? ' on' : '') + '"><span class="pf-cn-nm">' + esc(g.stage) + '</span>' +
        '<span class="pf-cn-bar"><i style="width:' + w + '%"></i></span>' +
        '<span class="pf-cn-pc">' + (e > 0 ? e.toFixed(1) + '%' : '—') + '</span></div>';
    }).join('<div class="pf-cn-arr">▼</div>');
    var other = chainExp['其他'];
    return nodes + (other ? '<div class="note">未對應供應鏈節點:' + other.toFixed(1) + '%</div>' : '');
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
        var v = val(a, b), bg = 'transparent', col = '#94a3b8';
        if (v != null) {
          bg = v >= 0 ? 'rgba(245,197,24,' + Math.max(0, Math.min(1, v)).toFixed(2) + ')' : 'rgba(96,165,250,' + Math.min(1, -v).toFixed(2) + ')';
          if (v > 0.55) col = '#0f172a';
        }
        return '<td style="background:' + bg + ';color:' + col + '">' + (v == null ? '—' : v.toFixed(2)) + '</td>';
      }).join('');
      return '<tr><td class="nm">' + esc((stocks[a] && stocks[a].name) || a) + '</td>' + tds + '</tr>';
    }).join('');
    return '<table class="pf-hm"><thead><tr>' + th + '</tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function card(lab, val) { return '<div class="pf-card"><div class="lab">' + lab + '</div><div class="val">' + val + '</div></div>'; }

  var _lastPD = null;
  // 把投組風險結果格式化成純文字(寄送用)
  function portfolioText(d) {
    if (!d || !d.stocks) return '';
    var stocks = d.stocks, codes = Object.keys(stocks);
    var cv = Object.keys(d.corr || {}).map(function (k) { return d.corr[k]; });
    var avgCorr = cv.length ? cv.reduce(function (a, b) { return a + b; }, 0) / cv.length : 0;
    var pBeta = 0, bw = 0;
    codes.forEach(function (c) { var s = stocks[c]; if (s.beta != null) { pBeta += (s.weight || 0) * s.beta; bw += (s.weight || 0); } });
    pBeta = bw > 0 ? pBeta / bw : 0;
    var p = d.portfolio || {};
    var lines = ['📦 投組風險分析', new Date().toLocaleString('zh-TW'), '',
      '年化波動 ' + (p.vol || 0).toFixed(1) + '%  |  1日95%VaR ' + (p.var95 || 0).toFixed(2) + '%',
      '平均相關性 ' + avgCorr.toFixed(2) + '  |  投組Beta ' + pBeta.toFixed(2) + '  |  檔數 ' + codes.length + '  |  樣本 ' + (p.days || 0) + '日',
      '', '個股(依權重):'];
    codes.map(function (c) { return [c, stocks[c]]; }).sort(function (a, b) { return (b[1].weight || 0) - (a[1].weight || 0); })
      .forEach(function (e) { var s = e[1]; lines.push('  ' + (s.name || e[0]) + '  權重' + (s.weight || 0).toFixed(1) + '%  波動' + (s.vol != null ? s.vol.toFixed(1) + '%' : '—') + '  Beta' + (s.beta != null ? s.beta.toFixed(2) : '—')); });
    lines.push(''); lines.push('基準:' + (d.benchmark || '^TWII'));
    return lines.join('\n');
  }
  function render(d) {
    _lastPD = d;
    var stocks = d.stocks || {};
    var codes = Object.keys(stocks);
    var stageMap = (typeof window !== 'undefined' && window.SC_STAGE) || {};
    var chainExp = {};
    codes.forEach(function (c) { var st = stageMap[c] || '其他'; chainExp[st] = (chainExp[st] || 0) + (stocks[c].weight || 0); });

    var cv = Object.keys(d.corr || {}).map(function (k) { return d.corr[k]; });
    var avgCorr = cv.length ? cv.reduce(function (a, b) { return a + b; }, 0) / cv.length : 0;
    var pBeta = 0, bw = 0;
    codes.forEach(function (c) { var s = stocks[c]; if (s.beta != null) { pBeta += (s.weight || 0) * s.beta; bw += (s.weight || 0); } });
    pBeta = bw > 0 ? pBeta / bw : 0;

    var p = d.portfolio || {};
    var h = '<div class="pf-cards">' +
      card('年化波動', (p.vol || 0).toFixed(1) + '%') +
      card('1日 95% VaR', (p.var95 || 0).toFixed(2) + '%') +
      card('平均相關性', avgCorr.toFixed(2)) +
      card('投組 Beta', pBeta.toFixed(2)) +
      card('持倉檔數', codes.length) +
      card('樣本天數', p.days || 0) + '</div>';

    h += '<div class="pf-h">供應鏈曝險（鏈條圖 · 你壓在哪一段）</div>' + chainDiagram(chainExp);
    h += '<div class="pf-h">產業曝險</div>' + (d.sector && Object.keys(d.sector).length ? bars(d.sector, '#60a5fa') : '<div class="note">無產業資料</div>');

    h += '<div class="pf-h">個股（依權重）</div><table><thead><tr><th>個股</th><th>權重</th><th>年化波動</th><th>Beta</th></tr></thead><tbody>';
    codes.map(function (c) { return [c, stocks[c]]; }).sort(function (a, b) { return (b[1].weight || 0) - (a[1].weight || 0); })
      .forEach(function (e) {
        var s = e[1];
        h += '<tr><td>' + esc(s.name || e[0]) + '</td><td>' + (s.weight || 0).toFixed(1) + '%</td><td>' +
          (s.vol != null ? s.vol.toFixed(1) + '%' : '—') + '</td><td>' + (s.beta != null ? s.beta.toFixed(2) : '—') + '</td></tr>';
      });
    h += '</tbody></table>';

    if (codes.length >= 2) {
      var hmCodes = codes.map(function (c) { return [c, stocks[c].weight || 0]; }).sort(function (a, b) { return b[1] - a[1]; })
        .slice(0, 12).map(function (e) { return e[0]; });
      h += '<div class="pf-h">相關性熱力圖' + (codes.length > 12 ? '（前 12 大持倉）' : '') + '</div>' + heatmap(hmCodes, stocks, d.corr || {});
    }

    h += '<div class="note">波動/VaR/Beta 取本機 DB 約 5 年日線(對 ' + esc(d.benchmark || '^TWII') + ')。平均相關性越高代表持倉越連動、分散效果越有限。' +
      (d.skipped && d.skipped.length ? '<br>無資料略過:' + esc(d.skipped.join('、')) : '') + '</div>';
    return h;
  }

  async function analyze(h) {
    var body = document.getElementById('pf-body');
    if (!body) return;
    if (!h || !h.length) { body.innerHTML = '尚無成分股。用上方「用持倉/用自選」載入,或自己輸入代號。'; return; }
    body.innerHTML = '<span style="color:#94a3b8">分析中…</span>';
    try {
      var r = await fetch('/portfolio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ holdings: h }) });
      var d = await r.json();
      if (!d || d.error) { body.innerHTML = '分析失敗:' + esc((d && d.error) || '無資料'); return; }
      body.innerHTML = render(d);
      if (window.ShareResult) ShareResult.wire('pf-send', function () { return portfolioText(_lastPD); }, '投組風險分析');
    } catch (e) { body.innerHTML = '分析失敗:' + esc(e.message); }
  }

  function loadSrc(which) {
    var h = which === 'watch' ? holdingsFromWatch() : holdingsFromPositions();
    var ta = document.getElementById('pf-edit');
    if (ta) ta.value = holdingsToText(h);
    analyze(h);
  }

  function open() {
    injectStyle();
    var modal = document.getElementById('pf-modal');
    if (!modal) { modal = document.createElement('div'); modal.id = 'pf-modal'; document.body.appendChild(modal); }
    var init = holdings();
    modal.innerHTML =
      '<div id="pf-box">' +
      '<h3>📦 投組風險 <span style="display:flex;gap:6px;align-items:center">' + (window.ShareResult ? ShareResult.buttonHTML('pf-send', '寄結果') : '') + '<span class="x" onclick="window.portfolioClose&&portfolioClose()">×</span></span></h3>' +
      '<div class="pf-edit-bar"><span style="font-size:11px;color:#94a3b8">成分股／權重</span>' +
      '<button class="pf-mini" id="pf-src-pos">用持倉</button><button class="pf-mini" id="pf-src-wat">用自選</button>' +
      '<button class="pf-mini pf-go" id="pf-reana">重新分析</button></div>' +
      '<textarea id="pf-edit" placeholder="每行一檔:代號 權重(權重可省略=1)　例:2330 30">' + esc(holdingsToText(init)) + '</textarea>' +
      '<div id="pf-body">分析中…</div></div>';
    modal.style.display = 'flex';
    modal.onclick = function (e) { if (e.target === modal) close(); };
    document.getElementById('pf-src-pos').onclick = function () { loadSrc('pos'); };
    document.getElementById('pf-src-wat').onclick = function () { loadSrc('watch'); };
    document.getElementById('pf-reana').onclick = function () { analyze(parseHoldings(document.getElementById('pf-edit').value)); };
    analyze(init);
  }

  function close() { var m = document.getElementById('pf-modal'); if (m) m.style.display = 'none'; }

  window.portfolioOpen = open;
  window.portfolioClose = close;

  (function () {
    var spec = { id: 'btn-portfolio', label: '📦 投組', cat: 'fund',
                 title: '投組風險:相關性/波動/VaR/產業·供應鏈曝險(可自訂成分股) (v4.0)', onclick: open };
    (window.Toolbar ? window.Toolbar.register
      : function (s) { (window.__tbQueue = window.__tbQueue || []).push(s); })(spec);
  })();
})();

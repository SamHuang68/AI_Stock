/* ============================================================================
 * book_v5.js  —  Stock Terminal 5.0 Stage 6：投組風險側欄
 * ----------------------------------------------------------------------------
 * 成分：持倉市值權重 → 否則自選等權；可手改 textarea。
 * 資料：POST /portfolio → 波動／VaR／Beta／產業／相關性（與 portfolio_v3 同後端）
 * 掛載：#mount-book；側欄「投組」
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var lastData = null;
  var source = 'auto'; // auto | pos | watch | custom

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
    });
  }

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
      return Object.keys(S.watches).map(function (code) {
        return { sym: code, weight: 1 };
      });
    }
    // fallback: watchlist chips in DOM / localStorage common keys
    try {
      var wl = JSON.parse(localStorage.getItem('wl_v2') || localStorage.getItem('watchlist') || '[]');
      if (Array.isArray(wl) && wl.length) {
        return wl.map(function (x) {
          var sym = typeof x === 'string' ? x : (x.sym || x.t || x.code);
          return sym ? { sym: String(sym).replace(/\.TW|\.TWO/g, ''), weight: 1 } : null;
        }).filter(Boolean);
      }
    } catch (e) {}
    return [];
  }
  function holdingsAuto() {
    var p = holdingsFromPositions();
    return p.length ? p : holdingsFromWatch();
  }
  function holdingsToText(h) {
    return (h || []).map(function (x) {
      return x.sym + ' ' + (Math.round((x.weight || 1) * 100) / 100);
    }).join('\n');
  }
  function parseHoldings(txt) {
    return (txt || '').split('\n').map(function (line) {
      var p = line.trim().split(/\s+/);
      if (!p[0]) return null;
      var w = parseFloat(p[1]);
      return {
        sym: p[0].replace('.TW', '').replace('.TWO', ''),
        weight: (isFinite(w) && w > 0) ? w : 1
      };
    }).filter(Boolean);
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
      '#bk-root .bk-title{font-family:\'Noto Serif TC\',serif;font-size:15px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#bk-root .bk-sub{font-size:9px;color:var(--tlo);margin:0}' +
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
      '#bk-root .bk-card .lab{font-size:8px;color:var(--tlo);letter-spacing:.4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
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
      '#bk-root .bk-hm{font-size:8px;margin-top:3px;table-layout:fixed}' +
      '#bk-root .bk-hm td,#bk-root .bk-hm th{padding:2px 2px;border:1px solid var(--bg);text-align:center}' +
      '#bk-root .bk-hm th.nm,#bk-root .bk-hm td.nm{text-align:left;color:var(--tlo);white-space:nowrap;font-size:8px}' +
      '#bk-root .bk-note{font-size:8px;color:var(--tlo);line-height:1.35;margin-top:2px;flex:0 0 auto}' +
      '#bk-root .bk-loading{font-size:10px;color:var(--tlo);padding:12px 0}' +
      '#bk-root .bk-err{color:var(--orange);font-size:10px;padding:8px 0}';
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
      var init = holdingsAuto();
      mount.innerHTML =
        '<div id="bk-root">' +
          '<div class="bk-head"><div>' +
            '<span class="bk-title">投組風險</span>' +
            '<span class="bk-sub" id="bk-sub">波動 · VaR · Beta · 產業曝險</span>' +
          '</div><div class="bk-actions">' +
            '<button type="button" class="bk-btn" data-src="pos">持倉</button>' +
            '<button type="button" class="bk-btn" data-src="watch">自選</button>' +
            '<button type="button" class="bk-btn" id="bk-edit-toggle">成分 ▾</button>' +
            '<button type="button" class="bk-btn primary" id="bk-run">分析</button>' +
            '<button type="button" class="bk-btn" data-shell-back>← 圖表</button>' +
          '</div></div>' +
          '<div class="bk-edit-wrap">' +
            '<textarea id="bk-edit" placeholder="每行：代號 權重（可省略=1）  例：2330 40">' +
              esc(holdingsToText(init)) + '</textarea>' +
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
      }
      mount.querySelectorAll('[data-src]').forEach(function (b) {
        b.onclick = function () {
          source = b.getAttribute('data-src');
          var h = source === 'pos' ? holdingsFromPositions() : holdingsFromWatch();
          var ta = $('bk-edit');
          if (ta) ta.value = holdingsToText(h);
          analyze(h);
        };
      });
      var run = $('bk-run');
      if (run) run.onclick = function () {
        source = 'custom';
        analyze(parseHoldings(($('bk-edit') || {}).value));
      };
    }
    return $('bk-body');
  }

  function render(d) {
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

    var cv = Object.keys(d.corr || {}).map(function (k) { return d.corr[k]; });
    var avgCorr = cv.length ? cv.reduce(function (a, b) { return a + b; }, 0) / cv.length : 0;
    var pBeta = 0, bw = 0;
    codes.forEach(function (c) {
      var s = stocks[c];
      if (s.beta != null) { pBeta += (s.weight || 0) * s.beta; bw += (s.weight || 0); }
    });
    pBeta = bw > 0 ? pBeta / bw : 0;
    var p = d.portfolio || {};

    var sub = $('bk-sub');
    if (sub) {
      sub.textContent = codes.length + ' 檔 · 基準 ' + (d.benchmark || '^TWII') +
        ' · 更新 ' + new Date().toLocaleTimeString('zh-TW');
    }

    var V = window.Viz;
    var var95 = p.var95 || 0;
    var vol = p.vol || 0;
    // VaR：日風險 >2% 警示、>4% 危險；相關性以 0–100% 刻度，>50/70 警示
    var varMeter = V ? V.ratioMeter(Math.abs(var95), 2, 4) : '';
    var corrMeter = V ? V.ratioMeter(Math.abs(avgCorr) * 100, 50, 70) : '';
    var betaViz = '';
    if (V && isFinite(pBeta)) {
      betaViz = V.magBar(pBeta - 1, 1, {
        label: 'β−1',
        fmt: function () { return pBeta.toFixed(2); }
      });
    }
    var h = '<div class="bk-strip">' +
      '<div class="bk-card"><div class="lab">年化波動</div><div class="val">' + vol.toFixed(1) + '%</div>' +
        (V ? V.scoreMeter(Math.min(100, vol * 2), { hi: 40, mid: 25 }) : '') + '</div>' +
      '<div class="bk-card"><div class="lab">1日 95% VaR</div><div class="val">' + var95.toFixed(2) + '%</div>' +
        varMeter + '</div>' +
      '<div class="bk-card"><div class="lab">平均相關性</div><div class="val">' + avgCorr.toFixed(2) + '</div>' +
        corrMeter + '</div>' +
      '<div class="bk-card"><div class="lab">投組 Beta</div><div class="val">' + pBeta.toFixed(2) + '</div>' +
        betaViz + '</div>' +
      '<div class="bk-card"><div class="lab">持倉檔數</div><div class="val">' + codes.length + '</div></div>' +
      '<div class="bk-card"><div class="lab">樣本天數</div><div class="val">' + (p.days || 0) + '</div></div>' +
      '</div>';

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

  function analyze(h) {
    var body = ensureMount();
    if (!body) return;
    if (!h || !h.length) {
      body.innerHTML = '<div class="bk-err">尚無成分股。請用「用持倉／用自選」，或在上方輸入代號權重後按重新分析。</div>';
      return;
    }
    body.innerHTML = '<div class="bk-loading">分析中…（首次可能需回補日線）</div>';
    fetch(SRV + '/portfolio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ holdings: h })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok || !x.d || x.d.error) {
          body.innerHTML = '<div class="bk-err">分析失敗：' + esc((x.d && x.d.error) || '無資料') + '</div>';
          return;
        }
        render(x.d);
      })
      .catch(function (e) {
        body.innerHTML = '<div class="bk-err">分析失敗：' + esc(e.message || e) + '</div>';
      });
  }

  function activate() {
    ensureMount();
    var ta = $('bk-edit');
    var h = parseHoldings(ta && ta.value);
    if (!h.length) {
      h = holdingsAuto();
      if (ta) ta.value = holdingsToText(h);
    }
    analyze(h);
  }

  window.BookV5 = {
    activate: activate,
    deactivate: function () {},
    refresh: activate,
    last: function () { return lastData; }
  };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'book') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'book') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 240); });
  else setTimeout(boot, 240);
})();

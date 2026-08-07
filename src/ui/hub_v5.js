/* ============================================================================
 * hub_v5.js  —  Stock Terminal 5.0：總覽周邊模組中樞
 * ----------------------------------------------------------------------------
 * institutional / international / signals / watchlist / risk / settings
 * （trends／指數已併入 ShellV5 → 圖表 ^TWII）
 * 真實 API：/pulse/history · /sync · /movers · /inst-rank · /macro · /focus · /datasources
 * 大螢幕一頁高密度（65" 優化，不遷就手機）
 * ========================================================================== */
(function () {
  'use strict';
  var SRV = window.SERVER || '';
  var timers = {};

  function $(id) { return document.getElementById(id); }
  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function goRoute(id, opts) { if (window.ShellV5) window.ShellV5.go(id, opts || {}); }
  function openChart(code, mkt) {
    if (window.ShellV5 && ShellV5.openChart) { ShellV5.openChart(code || '^TWII', mkt || 'TW'); return; }
    if (code && typeof loadSym === 'function') { loadSym(code, mkt || 'TW'); goRoute('chart'); }
  }
  function tw(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
  }
  function pct(p) {
    if (p == null || p !== p) return '—';
    return (p >= 0 ? '+' : '') + Number(p).toFixed(2) + '%';
  }
  function fmt(v, d) {
    if (v == null || !isFinite(v)) return '—';
    d = d == null ? 2 : d;
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  }
  function yi(v) {
    if (v == null || !isFinite(v)) return '—';
    var x = Math.abs(v) > 1e5 ? v / 1e8 : v;
    return (x >= 0 ? '+' : '') + Number(x).toFixed(1) + ' 億';
  }

  function injectCSS() {
    var s = $('hub-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'hub-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-institutional.on,#view-international.on,#view-signals.on,' +
        '#view-watchlist.on,#view-risk.on,#view-settings.on){overflow:hidden!important}' +
      '#view-institutional.sv-panel.on,#view-international.sv-panel.on,#view-signals.sv-panel.on,' +
        '#view-watchlist.sv-panel.on,#view-risk.sv-panel.on,#view-settings.sv-panel.on{' +
        'max-width:none!important;padding:4px 6px 6px;overflow:hidden;display:flex!important;' +
        'flex-direction:column;height:100%}' +
      '#mount-institutional,#mount-international,#mount-signals,#mount-watchlist,#mount-risk,#mount-settings,' +
        '#mount-institutional.sv-mount,#mount-international.sv-mount,#mount-signals.sv-mount,' +
        '#mount-watchlist.sv-mount,#mount-risk.sv-mount,#mount-settings.sv-mount{' +
        'flex:1;min-height:0;display:flex;flex-direction:column;max-width:none;width:100%}' +
      '.hub-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:none;margin:0;min-width:0;box-sizing:border-box;' +
        'flex:1;min-height:0;display:flex;flex-direction:column}' +
      '.hub-root .hub-head{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '.hub-root .hub-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '.hub-root .hub-kicker{font-size:9px;color:var(--gold);letter-spacing:1.2px;margin:0;font-weight:700}' +
      '.hub-root .hub-title{font-family:\'Noto Serif TC\',serif;font-size:15px;font-weight:700;color:var(--thi);line-height:1.1;margin:0}' +
      '.hub-root .hub-sep{font-size:9px;color:var(--tlo);margin:0 2px}' +
      '.hub-root .hub-sub{font-size:9px;color:var(--tlo);margin:0;line-height:1.2}' +
      '.hub-root .hub-actions{display:flex;gap:4px;flex-wrap:nowrap;justify-content:flex-end;flex:0 0 auto}' +
      '.hub-root .hub-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;cursor:pointer;font-family:inherit;white-space:nowrap;flex:0 0 auto}' +
      '.hub-root .hub-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '.hub-root .hub-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '.hub-root .hub-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '.hub-root .hub-loading{font-size:10px;color:var(--tlo);padding:8px 0;flex:0 0 auto}' +
      '.hub-root .hub-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;margin:0 0 4px;min-width:0;flex:0 0 auto}' +
      '.hub-root .hub-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '.hub-root .hub-strip .k{font-size:8px;color:var(--tlo);letter-spacing:.4px;margin-bottom:0;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-strip .v{font-size:12px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-strip .s{font-size:8px;margin-top:0;font-weight:700;line-height:1.2;color:var(--tlo)}' +
      '.hub-root .hub-dash{flex:1;min-height:0;display:grid;gap:4px;grid-template-rows:minmax(0,1fr) minmax(0,1fr)}' +
      '.hub-root .hub-dash.hub-dash-1{grid-template-rows:minmax(0,1fr)}' +
      /* 單列橫向多窗：消除 1fr/1fr 上下對切造成的中空 */
      '.hub-root .hub-dash.hub-cols-2{grid-template-rows:minmax(0,1fr);grid-template-columns:minmax(0,1fr) minmax(0,1fr)}' +
      '.hub-root .hub-dash.hub-cols-3{grid-template-rows:minmax(0,1fr);' +
        'grid-template-columns:minmax(0,1.55fr) minmax(0,1fr) minmax(0,1fr)}' +
      '.hub-root .hub-dash.hub-cols-4{grid-template-rows:minmax(0,1fr);grid-template-columns:repeat(4,minmax(0,1fr))}' +
      '.hub-root .hub-zone{display:grid;gap:4px;min-width:0;min-height:0;height:100%;' +
        'grid-template-columns:repeat(2,minmax(0,1fr))}' +
      '.hub-root .hub-zone.z-3{grid-template-columns:repeat(3,minmax(0,1fr))}' +
      '.hub-root .hub-zone.z-4{grid-template-columns:repeat(4,minmax(0,1fr))}' +
      '.hub-root .hub-zone.z-fill{grid-template-columns:repeat(auto-fill,minmax(128px,1fr));' +
        'align-content:stretch;grid-auto-rows:minmax(78px,1fr);overflow:auto;flex:1;min-height:0}' +
      '.hub-root .hub-sec{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%;margin:0}' +
      '.hub-root .hub-sec h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px;' +
        'display:flex;justify-content:space-between;align-items:center;flex:0 0 auto;gap:4px}' +
      '.hub-root .hub-sec > .hub-fill{flex:1;min-height:0;overflow:auto}' +
      '.hub-root .hub-card{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px 9px;min-width:0;' +
        'overflow:hidden;display:flex;flex-direction:column;justify-content:center;height:100%;box-sizing:border-box}' +
      '.hub-root .hub-card .k{font-size:9px;color:var(--tlo);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-card .v{font-size:18px;font-weight:800;color:var(--thi);margin-top:2px;line-height:1.15}' +
      '.hub-root .hub-card .chg{font-size:11px;font-weight:700;margin-top:3px}' +
      '.hub-root .hub-card .bar{margin-top:4px}' +
      '.hub-root .hub-card .bar .vz-rowbar{height:6px;max-width:100%;display:block;width:100%}' +
      '.hub-root .up{color:var(--red)}.hub-root .dn{color:var(--green)}.hub-root .flat{color:var(--tlo)}' +
      '.hub-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '.hub-root th,.hub-root td{padding:2px 3px;border-bottom:1px solid var(--border);text-align:right}' +
      '.hub-root th:first-child,.hub-root td:first-child,.hub-root th:nth-child(2),.hub-root td:nth-child(2){text-align:left}' +
      '.hub-root th{color:var(--tlo);font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1}' +
      '.hub-root tr[data-code]{cursor:pointer}.hub-root tr[data-code]:hover{background:var(--bg3)}' +
      '.hub-root .hub-note{font-size:8px;color:var(--tlo);margin-top:3px;line-height:1.35;flex:0 0 auto;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.hub-root .hub-spark{display:flex;align-items:flex-end;gap:1px;height:40px;margin-top:2px;flex:1;min-height:32px}' +
      '.hub-root .hub-spark i{flex:1;background:var(--cyan);opacity:.75;border-radius:1px 1px 0 0;min-width:2px}' +
      '.hub-root .hub-spark-fill{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:stretch}' +
      '.hub-root .hub-spark-fill .vz-spark,.hub-root .hub-spark-fill svg{width:100%!important;height:100%!important;min-height:140px;flex:1}' +
      '.hub-root .hub-mag3{display:grid;grid-template-columns:1fr;gap:14px;flex:1;min-height:0;align-content:stretch;' +
        'grid-template-rows:repeat(3,minmax(0,1fr));padding:8px 0}' +
      '.hub-root .hub-mag3 .row{display:flex;align-items:center;gap:8px;font-size:11px}' +
      '.hub-root .hub-mag3 .row .lbl{width:32px;flex-shrink:0;color:var(--tlo);font-size:10px}' +
      '.hub-root .hub-mag3 .row .val{width:64px;flex-shrink:0;text-align:right;font-weight:700;font-size:13px}' +
      '.hub-root .hub-mag3 .row .bar{flex:1;min-width:0}' +
      '.hub-root .hub-mag3 .vz-mag .vz-track{height:12px}' +
      '.hub-root .hub-dash.hub-cols-wide-left{grid-template-rows:minmax(0,1fr);' +
        'grid-template-columns:minmax(0,1.7fr) minmax(0,.9fr)}' +
      '.hub-root .badge{display:inline-block;padding:0 6px;border-radius:999px;font-size:8px;font-weight:700}' +
      '.hub-root .badge.ok{background:var(--gbg);color:var(--green);border:1px solid var(--gbdr)}' +
      '.hub-root .badge.warn{background:rgba(251,146,60,.12);color:var(--orange);border:1px solid rgba(251,146,60,.35)}' +
      '.hub-root .badge.err{background:rgba(248,113,113,.12);color:var(--red);border:1px solid rgba(248,113,113,.35)}' +
      '.hub-root .badge.mid{background:rgba(245,197,24,.12);color:var(--gold);border:1px solid var(--gold-m)}' +
      '.hub-root .hub-empty{font-size:10px;color:var(--tlo);padding:16px 8px;text-align:center}';
  }

  function mount(route) {
    injectCSS();
    var panel = $('view-' + route);
    if (!panel) return null;
    var mid = 'mount-' + route;
    var el = $(mid);
    if (!el) {
      el = document.createElement('div');
      el.id = mid;
      el.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(el);
    }
    return el;
  }

  function head(title, sub, actionsHtml) {
    return '<div class="hub-root"><div class="hub-head"><div>' +
      '<span class="hub-kicker">STOCK TERMINAL · 5.0</span>' +
      '<span class="hub-title">' + title + '</span>' +
      (sub ? '<span class="hub-sep">·</span><span class="hub-sub">' + sub + '</span>' : '') +
      '</div><div class="hub-actions">' + (actionsHtml || '') + '</div></div>';
  }

  function spark(vals) {
    if (!vals || !vals.length) return '';
    var max = Math.max.apply(null, vals.map(Math.abs).concat([1]));
    var html = '<div class="hub-spark">';
    vals.forEach(function (v) {
      var h = Math.max(4, Math.round(Math.abs(v) / max * 48));
      var col = v >= 0 ? 'var(--red)' : 'var(--green)';
      html += '<i style="height:' + h + 'px;background:' + col + '"></i>';
    });
    return html + '</div>';
  }

  // ── Institutional ────────────────────────────────────────
  function renderInstitutional(el) {
    el.innerHTML = head('法人動向', '三大法人合計＋買賣超排行＋歷史趨勢',
      '<button class="hub-btn" data-sync>同步資料</button><button class="hub-btn" data-go="afterhours">盤後</button>') +
      '<div id="hub-inst-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    Promise.all([
      jget('/marketflow'),
      jget('/inst-rank?who=foreign&side=buy&n=18'),
      jget('/inst-rank?who=foreign&side=sell&n=18'),
      jget('/pulse/history?kind=institutional&n=40')
    ]).then(function (arr) {
      var V = window.Viz;
      var mf = arr[0] || {};
      var inst = mf.inst || {};
      var buy = (arr[1] && arr[1].list) || [];
      var sell = (arr[2] && arr[2].list) || [];
      var hist = (arr[3] && arr[3].rows) || [];
      var total = null;
      if (inst.foreign != null || inst.trust != null || inst.dealer != null) {
        total = (inst.foreign || 0) + (inst.trust || 0) + (inst.dealer || 0);
      }
      var maxDay = Math.max(
        Math.abs(inst.foreign || 0), Math.abs(inst.trust || 0), Math.abs(inst.dealer || 0), 1
      );
      function rankTbl(list, title) {
        var maxAbs = 0;
        list.forEach(function (r) {
          var vv = r.foreign != null ? r.foreign : r.net;
          if (vv != null && isFinite(vv)) maxAbs = Math.max(maxAbs, Math.abs(vv));
        });
        var h = '<div class="hub-sec"><h4>' + title + '</h4><div class="hub-fill"><table><tr><th>#</th><th>代號</th><th>名稱</th><th>外資</th></tr>';
        list.forEach(function (r, i) {
          var v = r.foreign != null ? r.foreign : r.net;
          var bar = V ? V.rowBar(v, maxAbs) : '';
          var streak = (V && r.streak) ? V.streakChip(r.streak, '外資') : '';
          h += '<tr data-code="' + (r.code || '') + '"><td>' + (i + 1) + '</td><td style="color:var(--gold);font-weight:700">' +
            (r.code || '') + '</td><td>' + (r.name || '') + streak + '</td><td class="' + tw(v) + '">' +
            yi(v) + bar + '</td></tr>';
        });
        return h + '</table></div></div>';
      }
      var sparkVals = hist.slice().reverse().map(function (r) { return r.totalYi || 0; });
      var totalSpark = V ? V.sparkBars(sparkVals) : '';
      var fBar = V ? V.magBar(inst.foreign, maxDay, { fmt: V.fmtYiFromYuan }) : '';
      var tBar = V ? V.magBar(inst.trust, maxDay, { fmt: V.fmtYiFromYuan }) : '';
      var dBar = V ? V.magBar(inst.dealer, maxDay, { fmt: V.fmtYiFromYuan }) : '';
      var magPanel = '<div class="hub-sec"><h4>當日法人量柱</h4><div class="hub-mag3">' +
        '<div class="row"><span class="lbl">外資</span><span class="val ' + tw(inst.foreign) + '">' + yi(inst.foreign) + '</span><span class="bar">' + fBar + '</span></div>' +
        '<div class="row"><span class="lbl">投信</span><span class="val ' + tw(inst.trust) + '">' + yi(inst.trust) + '</span><span class="bar">' + tBar + '</span></div>' +
        '<div class="row"><span class="lbl">自營</span><span class="val ' + tw(inst.dealer) + '">' + yi(inst.dealer) + '</span><span class="bar">' + dBar + '</span></div>' +
        '</div></div>';
      var trendPanel = '<div class="hub-sec"><h4>法人資金趨勢</h4><div class="hub-spark-fill">' +
        (V ? V.sparkLine(sparkVals, { color: 'var(--gold)', h: 220, w: 420 }) : spark(sparkVals)) +
        '</div><div class="hub-note">日數 ' + hist.length + (inst.date ? ' · 最新法人日 ' + inst.date : '') + '</div></div>';
      var body = $('hub-inst-body');
      if (!body) return;
      body.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">外資</div><div class="v ' + tw(inst.foreign) + '">' + yi(inst.foreign) + '</div></div>' +
          '<div class="cell"><div class="k">投信</div><div class="v ' + tw(inst.trust) + '">' + yi(inst.trust) + '</div></div>' +
          '<div class="cell"><div class="k">自營</div><div class="v ' + tw(inst.dealer) + '">' + yi(inst.dealer) + '</div></div>' +
          '<div class="cell"><div class="k">合計</div><div class="v ' + tw(total) + '">' + yi(total) + '</div>' +
            (totalSpark ? '<div class="s">' + totalSpark + '</div>' : '') + '</div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-4">' +
          trendPanel + magPanel + rankTbl(buy, '外資買超') + rankTbl(sell, '外資賣超') +
        '</div>';
      bindCommon(el);
    });
  }

  // ── International ────────────────────────────────────────
  function renderInternational(el) {
    el.innerHTML = head('國際市場', '美股指數／美元／原油＋總經序列',
      '<button class="hub-btn" data-sync>同步資料</button><button class="hub-btn" data-go="pulse">總覽</button>') +
      '<div id="hub-intl-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    Promise.all([
      jget('/pulse?refresh=0'),
      jget('/macro/us10y?years=2'),
      jget('/macro/unrate?years=5'),
      jget('/macro/us_cpi_yoy?years=5'),
      jget('/sync/status')
    ]).then(function (arr) {
      var pulse = arr[0] || {};
      var global = pulse.global || [];
      if (pulse.us10y) {
        global = global.concat([{ name: '美10年債', price: pulse.us10y.value, changePct: null, unit: '%' }]);
      }
      function lastPt(d) {
        var pts = (d && d.points) || [];
        return pts.length ? pts[pts.length - 1] : null;
      }
      var eco = [
        { label: '美國失業率', pt: lastPt(arr[2]), unit: '%' },
        { label: '美國CPI年增', pt: lastPt(arr[3]), unit: '%' },
        { label: '美10年債', pt: lastPt(arr[1]), unit: '%' }
      ];
      var st = arr[4] || {};
      var V = window.Viz;
      var maxChg = 0;
      global.forEach(function (g) {
        if (g.changePct != null && isFinite(g.changePct)) maxChg = Math.max(maxChg, Math.abs(g.changePct));
      });
      if (maxChg < 0.01) maxChg = 1;
      var strip = global.slice(0, 4).map(function (g) {
        return '<div class="cell"><div class="k">' + (g.name || g.symbol) + '</div><div class="v">' +
          fmt(g.price, g.unit === '%' ? 2 : (g.price > 1000 ? 0 : 2)) + (g.unit === '%' ? '%' : '') +
          '</div><div class="s ' + tw(g.changePct) + '">' + (g.changePct != null ? pct(g.changePct) : '—') + '</div></div>';
      }).join('');
      while ((strip.match(/class="cell"/g) || []).length < 4) {
        strip += '<div class="cell"><div class="k">—</div><div class="v">—</div></div>';
      }
      var cards = global.map(function (g) {
        var bar = (V && g.changePct != null) ? '<div class="bar">' + V.rowBar(g.changePct, maxChg) + '</div>' : '';
        return '<div class="hub-card"><div class="k">' + (g.name || g.symbol) + '</div><div class="v">' +
          fmt(g.price, g.unit === '%' ? 2 : (g.price > 1000 ? 0 : 2)) + (g.unit === '%' ? '%' : '') +
          '</div><div class="chg ' + tw(g.changePct) + '">' +
          (g.changePct != null ? pct(g.changePct) : '—') + '</div>' + bar + '</div>';
      }).join('');
      var ecoHtml = eco.map(function (e) {
        return '<tr><td>' + e.label + '</td><td>' + (e.pt ? fmt(e.pt.value, 2) + e.unit : '—') +
          '</td><td>' + (e.pt ? e.pt.date : '—') + '</td></tr>';
      }).join('');
      var ds = (st.datasets || []).map(function (d) {
        var cls = d.status === '同步完成' ? 'ok' : (d.status === '同步失敗' ? 'err' : 'warn');
        return '<tr><td>' + d.dataset + '</td><td>' + (d.dataDate || '—') + '</td><td><span class="badge ' + cls + '">' +
          (d.status || '—') + '</span></td><td>' + (d.rows != null ? d.rows : '—') + '</td></tr>';
      }).join('');
      var body = $('hub-intl-body');
      if (!body) return;
      body.innerHTML =
        '<div class="hub-strip">' + strip + '</div>' +
        '<div class="hub-dash hub-cols-3">' +
          '<div class="hub-sec"><h4>全球報價</h4><div class="hub-fill hub-zone z-fill" style="display:grid">' +
            (cards || '<div class="hub-empty">國際報價載入中／來源暫不可用</div>') +
          '</div></div>' +
          '<div class="hub-sec"><h4>經濟指標</h4><div class="hub-fill"><table><tr><th>項目</th><th>數值</th><th>日期</th></tr>' +
            (ecoHtml || '<tr><td colspan="3">FRED／總經尚未就緒（可於設定同步）</td></tr>') +
            '</table></div></div>' +
          '<div class="hub-sec"><h4>資料來源狀態</h4><div class="hub-fill"><table><tr><th>系列</th><th>資料日</th><th>狀態</th><th>列數</th></tr>' +
            (ds || '<tr><td colspan="4">尚無同步紀錄 — 按同步資料</td></tr>') +
            '</table></div></div>' +
        '</div>';
      bindCommon(el);
    });
  }

  // ── Signals ──────────────────────────────────────────────
  function renderSignals(el) {
    el.innerHTML = head('策略訊號', '可解釋監控訊號（焦點掃描／選股結果）',
      '<button class="hub-btn" data-go="scan">選股</button><button class="hub-btn primary" id="hub-run-focus">執行焦點掃描</button>') +
      '<div id="hub-sig-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    var run = $('hub-run-focus');
    if (run) run.onclick = function () { loadFocus(el, true); };
    loadFocus(el, false);
  }
  function loadFocus(el, force) {
    var body = $('hub-sig-body');
    if (body) body.innerHTML = '<div class="hub-loading">掃描中…</div>';
    jget('/focus' + (force ? '?refresh=1' : '')).then(function (d) {
      var body = $('hub-sig-body');
      if (!body) return;
      var list = (d && (d.longs || d.shorts || d.results || d.list)) || [];
      if (d && d.long) list = list.concat(d.long || []);
      if (d && d.short) list = list.concat(d.short || []);
      if (d && d.bull) list = list.concat(d.bull);
      if (d && d.bear) list = list.concat(d.bear);
      if (!list.length && d && Array.isArray(d.items)) list = d.items;
      if (!list.length) {
        body.innerHTML =
          '<div class="hub-dash hub-dash-1">' +
            '<div class="hub-sec"><h4>策略訊號清單</h4>' +
            '<div class="hub-empty">目前沒有新的策略訊號 — 可按「執行焦點掃描」或前往選股</div></div></div>';
        bindCommon(el);
        return;
      }
      var V = window.Viz;
      function classify(r) {
        var side = r.side || r.dir || r.bias || (r.score != null && r.score < 0 ? '空' : '多');
        var sideStr = String(side);
        if (/空|short|bear|sell|偏空/i.test(sideStr)) return 'bear';
        if (/多|long|bull|buy|偏多/i.test(sideStr)) return 'bull';
        if (r.score != null && isFinite(r.score) && r.score < 0) return 'bear';
        return 'bull';
      }
      function rowHtml(r) {
        var code = r.code || r.sym || r.ticker || '';
        var name = r.name || '';
        var side = r.side || r.dir || r.bias || (r.score != null && r.score < 0 ? '空' : '多');
        var score = r.score != null ? r.score : (r.confidence != null ? r.confidence : '—');
        var desc = r.reason || r.description || r.why || '';
        var sideStr = String(side);
        var bull = /多|long|bull|buy|偏多/i.test(sideStr);
        var bear = /空|short|bear|sell|偏空/i.test(sideStr);
        var sideCell = sideStr;
        if (V) {
          if (bull) sideCell = V.chip('偏多', 'buy');
          else if (bear) sideCell = V.chip('偏空', 'sell');
          else sideCell = V.chip(sideStr, 'mid');
        }
        var scoreNum = typeof score === 'number' ? score : parseFloat(score);
        var scoreCell = score;
        if (V && scoreNum === scoreNum) {
          var meterScore = Math.abs(scoreNum) <= 1 ? scoreNum * 100 : Math.max(0, Math.min(100, Math.abs(scoreNum)));
          scoreCell = (scoreNum >= 0 ? '+' : '') + Number(scoreNum).toFixed(1) + V.scoreMeter(meterScore);
        }
        return '<tr data-code="' + code + '"><td style="color:var(--gold);font-weight:700">' + code +
          '</td><td>' + name + '</td><td>' + sideCell + '</td><td>' + scoreCell +
          '</td><td style="text-align:left;color:var(--tlo)">' + desc + '</td></tr>';
      }
      var bulls = [], bears = [];
      list.forEach(function (r) {
        if (classify(r) === 'bear') bears.push(r);
        else bulls.push(r);
      });
      var bullRows = bulls.slice(0, 40).map(rowHtml).join('') ||
        '<tr><td colspan="5">目前無偏多訊號</td></tr>';
      var bearRows = bears.slice(0, 40).map(rowHtml).join('') ||
        '<tr><td colspan="5">目前無偏空訊號</td></tr>';
      var dashCls = (!bears.length && bulls.length) ? 'hub-cols-wide-left'
        : (!bulls.length && bears.length) ? 'hub-cols-2'
        : 'hub-cols-2';
      body.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">訊號總數</div><div class="v">' + list.length + '</div></div>' +
          '<div class="cell"><div class="k">偏多</div><div class="v up">' + bulls.length + '</div></div>' +
          '<div class="cell"><div class="k">偏空</div><div class="v dn">' + bears.length + '</div></div>' +
          '<div class="cell"><div class="k">來源</div><div class="v">/focus</div><div class="s">點列開圖表</div></div>' +
        '</div>' +
        '<div class="hub-dash ' + dashCls + '">' +
          '<div class="hub-sec"><h4>偏多訊號 · ' + bulls.length + '</h4><div class="hub-fill"><table>' +
            '<tr><th>代號</th><th>名稱</th><th>方向</th><th>分數</th><th>說明</th></tr>' +
            bullRows + '</table></div></div>' +
          '<div class="hub-sec"><h4>偏空訊號 · ' + bears.length + '</h4><div class="hub-fill"><table>' +
            '<tr><th>代號</th><th>名稱</th><th>方向</th><th>分數</th><th>說明</th></tr>' +
            bearRows + '</table></div></div>' +
        '</div>';
      bindCommon(el);
    });
  }

  // ── Watchlist ────────────────────────────────────────────
  function readWl() {
    try {
      if (typeof S !== 'undefined' && Array.isArray(S.wl) && S.wl.length) return S.wl.slice();
    } catch (e) {}
    var keys = ['st_wl', 'wl_v2', 'watchlist'];
    for (var i = 0; i < keys.length; i++) {
      try {
        var a = JSON.parse(localStorage.getItem(keys[i]) || '[]');
        if (Array.isArray(a) && a.length) return a;
      } catch (e) {}
    }
    return [];
  }
  function renderWatchlist(el) {
    el.innerHTML = head('自選股中心', '本機瀏覽器自選＋即時報價',
      '<button class="hub-btn" data-go="chart">圖表管理</button><button class="hub-btn primary" id="hub-wl-refresh">重新整理</button>') +
      '<div id="hub-wl-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    var btn = $('hub-wl-refresh');
    if (btn) btn.onclick = function () { fillWl(el); };
    fillWl(el);
  }
  function fillWl(el) {
    var wl = readWl();
    var body = $('hub-wl-body');
    if (!body) return;
    if (!wl.length) {
      body.innerHTML =
        '<div class="hub-dash hub-dash-1">' +
          '<div class="hub-sec"><div class="hub-empty">尚無自選股 — 於圖表按 ＋ 加入</div></div></div>';
      return;
    }
    var twc = wl.filter(function (w) { return (w.m || 'TW') === 'TW'; }).map(function (w) { return w.t; });
    var usc = wl.filter(function (w) { return w.m === 'US'; }).map(function (w) { return w.t; });
    Promise.all([
      twc.length ? jget('/twquote-batch?codes=' + encodeURIComponent(twc.join(','))) : Promise.resolve({}),
      usc.length ? jget('/quote-batch?syms=' + encodeURIComponent(usc.join(','))) : Promise.resolve({})
    ]).then(function (arr) {
      var q = Object.assign({}, arr[0] || {}, arr[1] || {});
      var V = window.Viz;
      var maxChg = 0;
      wl.forEach(function (w) {
        var qq = q[w.t] || q[w.t + '.TW'] || q[w.t + '.TWO'] || {};
        var ch = qq.changePct != null ? qq.changePct : w.chg;
        if (ch != null && isFinite(ch)) maxChg = Math.max(maxChg, Math.abs(ch));
      });
      if (maxChg < 0.01) maxChg = 1;
      function rowOf(w) {
        var qq = q[w.t] || q[w.t + '.TW'] || q[w.t + '.TWO'] || {};
        var ch = qq.changePct != null ? qq.changePct : w.chg;
        var bar = V ? V.rowBar(ch, maxChg) : '';
        return '<tr data-code="' + w.t + '" data-mkt="' + (w.m || 'TW') + '"><td style="color:var(--gold);font-weight:700">' +
          w.t + '</td><td>' + (w.name || '') + '</td><td>' +
          fmt(qq.price != null ? qq.price : w.price) + '</td><td class="' + tw(ch) + '">' +
          pct(ch) + bar + '</td></tr>';
      }
      var twRows = wl.filter(function (w) { return (w.m || 'TW') === 'TW'; }).map(rowOf).join('') ||
        '<tr><td colspan="4">尚無台股自選</td></tr>';
      var usRows = wl.filter(function (w) { return w.m === 'US'; }).map(rowOf).join('') ||
        '<tr><td colspan="4">尚無美股自選</td></tr>';
      var b = $('hub-wl-body');
      if (!b) return;
      b.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">自選總數</div><div class="v">' + wl.length + '</div></div>' +
          '<div class="cell"><div class="k">台股</div><div class="v">' + twc.length + '</div></div>' +
          '<div class="cell"><div class="k">美股</div><div class="v">' + usc.length + '</div></div>' +
          '<div class="cell"><div class="k">報價</div><div class="v">' + (twc.length + usc.length ? '即時' : '—') + '</div></div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-2">' +
          '<div class="hub-sec"><h4>台股自選</h4><div class="hub-fill"><table>' +
            '<tr><th>代號</th><th>名稱</th><th>最新價</th><th>漲跌</th></tr>' +
            twRows + '</table></div></div>' +
          '<div class="hub-sec"><h4>美股自選</h4><div class="hub-fill"><table>' +
            '<tr><th>代號</th><th>名稱</th><th>最新價</th><th>漲跌</th></tr>' +
            usRows + '</table></div></div>' +
        '</div>';
      bindCommon(el);
    });
  }

  // ── Risk ─────────────────────────────────────────────────
  function renderRisk(el) {
    el.innerHTML = head('風險監控', '由脈動因子與廣度／法人規則產生的風險事件',
      '<button class="hub-btn" data-sync>同步資料</button><button class="hub-btn" data-go="book">投組風險</button>') +
      '<div id="hub-risk-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    Promise.all([jget('/pulse'), jget('/pulse/history?kind=pulse&n=15')]).then(function (arr) {
      var p = arr[0] || {};
      var events = [];
      (p.riskFactors || []).forEach(function (f) {
        var sev = Math.abs(f.score) >= 10 ? '高' : '中';
        events.push({
          time: p.updatedAt || p.date || '',
          event: f.name,
          description: f.description,
          scope: '台股',
          severity: sev
        });
      });
      if ((p.snapshot && p.snapshot.inst && p.snapshot.inst.totalYi) < 0) {
        events.push({
          time: p.date || '', event: '三大法人合計偏賣',
          description: '上市櫃三大法人當日合計為賣超，權值與籌碼面可能承壓。',
          scope: '台股', severity: '中'
        });
      }
      var ar = p.snapshot && p.snapshot.stocks && p.snapshot.stocks.advRatio;
      if (ar != null && ar <= 0.35) {
        events.push({
          time: p.date || '', event: '市場廣度偏空',
          description: '上漲比偏低，短線氣氛偏防衛。',
          scope: '台股', severity: '高'
        });
      }
      var V = window.Viz;
      var riskMeter = V ? V.scoreMeter(p.riskScore, { color: 'var(--cyan)' }) : '';
      var healthMeter = V ? V.scoreMeter(p.healthScore) : '';
      var compMeter = V ? V.scoreMeter(p.dataCompleteness) : '';
      var eventsRows = '';
      if (!events.length) {
        eventsRows = '<tr><td colspan="5">目前無觸發中的風險事件</td></tr>';
      } else {
        events.forEach(function (e) {
          var cls = e.severity === '高' ? 'err' : 'mid';
          eventsRows += '<tr><td>' + (e.time || '') + '</td><td>' + e.event + '</td><td style="text-align:left">' +
            e.description + '</td><td>' + e.scope + '</td><td><span class="badge ' + cls + '">' + e.severity + '</span></td></tr>';
        });
      }
      var hist = (arr[1] && arr[1].rows) || [];
      var histPanel = '<div class="hub-sec"><h4>脈動分數歷史</h4>';
      if (hist.length) {
        var chrono = hist.slice().reverse();
        if (V) {
          var hs = chrono.map(function (r) { return r.health; });
          var rs = chrono.map(function (r) { return r.risk; });
          var hSp = hs.filter(function (v) { return v != null && isFinite(v); }).length >= 2
            ? V.sparkLine(hs, { color: 'var(--gold)' }) : '';
          var rSp = rs.filter(function (v) { return v != null && isFinite(v); }).length >= 2
            ? V.sparkLine(rs, { color: 'var(--cyan)' }) : '';
          if (hSp || rSp) {
            histPanel += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:4px;flex:0 0 auto">' +
              (hSp ? '<div><div class="hub-note">健康</div>' + hSp + '</div>' : '') +
              (rSp ? '<div><div class="hub-note">風險</div>' + rSp + '</div>' : '') + '</div>';
          }
        }
        histPanel += '<div class="hub-fill"><table><tr><th>日期</th><th>健康</th><th>風險</th><th>總分</th><th>狀態</th></tr>';
        hist.forEach(function (r) {
          histPanel += '<tr><td>' + r.date + '</td><td>' + fmt(r.health, 1) + '</td><td>' + fmt(r.risk, 1) +
            '</td><td>' + fmt(r.total, 1) + '</td><td>' + (r.statusText || '') + '</td></tr>';
        });
        histPanel += '</table></div>';
      } else {
        histPanel += '<div class="hub-empty">尚無歷史紀錄</div>';
      }
      histPanel += '</div>';
      var body = $('hub-risk-body');
      if (!body) return;
      body.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">市場風險度</div><div class="v">' +
            (p.riskScore != null ? Number(p.riskScore).toFixed(1) : '—') + '</div>' +
            '<div class="s">' + (p.riskLabel || '') + riskMeter + '</div></div>' +
          '<div class="cell"><div class="k">健康度</div><div class="v">' +
            (p.healthScore != null ? Number(p.healthScore).toFixed(1) : '—') + '</div>' +
            '<div class="s">' + healthMeter + '</div></div>' +
          '<div class="cell"><div class="k">風險因子數</div><div class="v">' +
            ((p.riskFactors || []).length) + '</div></div>' +
          '<div class="cell"><div class="k">完整度</div><div class="v">' +
            (p.dataCompleteness != null ? Number(p.dataCompleteness).toFixed(0) + '%' : '—') + '</div>' +
            '<div class="s">' + compMeter + '</div></div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-2">' +
          '<div class="hub-sec"><h4>風險事件清單</h4><div class="hub-fill"><table>' +
            '<tr><th>時間</th><th>事件</th><th>說明</th><th>範圍</th><th>重要</th></tr>' +
            eventsRows + '</table></div></div>' +
          histPanel +
        '</div>';
      bindCommon(el);
    });
  }

  // ── Settings ─────────────────────────────────────────────
  function renderSettings(el) {
    el.innerHTML = head('設定', '同步狀態 · 資料來源 · 本機歷史庫',
      '<button class="hub-btn primary" data-sync>同步資料</button>') +
      '<div id="hub-set-body" class="hub-body"><div class="hub-loading">載入中…</div></div></div>';
    bindCommon(el);
    Promise.all([jget('/sync/status'), jget('/datasources'), jget('/health')]).then(function (arr) {
      var st = arr[0] || {};
      var ds = arr[1];
      var health = arr[2] || {};
      var V = window.Viz;
      var counts = st.counts || {};
      var countChips = V
        ? (V.badge('廣度 ' + (counts.breadth || 0), 'mid') + ' ' +
           V.badge('法人 ' + (counts.institutional || 0), 'mid') + ' ' +
           V.badge('指數 ' + (counts.index || 0), 'mid') + ' ' +
           V.badge('脈動 ' + (counts.pulseScore || 0), 'mid'))
        : ('廣度 ' + (counts.breadth || 0) + ' · 法人 ' + (counts.institutional || 0) +
          ' · 指數 ' + (counts.index || 0) + ' · 脈動 ' + (counts.pulseScore || 0));
      var dsRows = '';
      (st.datasets || []).forEach(function (d) {
        var cls = d.status === '同步完成' ? 'ok' : (d.status === '同步失敗' ? 'err' : 'warn');
        dsRows += '<tr><td>' + d.dataset + '</td><td>' + (d.dataDate || '—') + '</td><td><span class="badge ' + cls + '">' +
          (d.status || '—') + '</span></td><td style="text-align:left">' + (d.note || '') + '</td><td>' +
          (d.rows != null ? d.rows : '—') + '</td></tr>';
      });
      if (!(st.datasets || []).length) dsRows = '<tr><td colspan="5">尚無紀錄 — 按「同步資料」啟動預抓</td></tr>';
      var srcPanel = '';
      if (ds && (ds.sources || ds.length)) {
        var list = ds.sources || ds;
        var srcRows = '';
        (Array.isArray(list) ? list : []).slice(0, 30).forEach(function (x) {
          srcRows += '<tr><td>' + (x.name || x.id || x.provider || '') + '</td><td>' +
            (x.status || x.reliability || '—') + '</td><td style="text-align:left">' +
            (x.note || x.lastUpdate || '') + '</td></tr>';
        });
        srcPanel = '<div class="hub-sec"><h4>系統資料源</h4><div class="hub-fill"><table>' +
          '<tr><th>來源</th><th>狀態</th><th>備註</th></tr>' + srcRows + '</table></div></div>';
      } else {
        srcPanel = '<div class="hub-sec"><h4>系統資料源</h4><div class="hub-empty">尚無資料源資訊</div></div>';
      }
      var body = $('hub-set-body');
      if (!body) return;
      body.innerHTML =
        '<div class="hub-strip">' +
          '<div class="cell"><div class="k">自動同步</div><div class="v">' +
            (st.running ? '進行中' : '待命') + '</div>' +
            '<div class="s"><span class="badge ' + (st.running ? 'warn' : 'ok') + '">' +
            (st.lastOk ? '上次成功 ' + st.lastOk : '尚未成功') + '</span></div></div>' +
          '<div class="cell"><div class="k">歷史庫列數</div><div class="v" style="font-size:11px">' + countChips + '</div></div>' +
          '<div class="cell"><div class="k">Server</div><div class="v">' + (health.status || '—') + '</div>' +
            '<div class="s">Stock Terminal 5.0 · loopback</div></div>' +
          '<div class="cell"><div class="k">策略</div><div class="v">增量 merge</div>' +
            '<div class="s">只更新新交易日</div></div>' +
        '</div>' +
        '<div class="hub-dash hub-cols-2">' +
          '<div class="hub-sec"><h4>資料來源狀態（pulse_history）</h4><div class="hub-fill"><table>' +
            '<tr><th>資料集</th><th>資料日</th><th>狀態</th><th>說明</th><th>列數</th></tr>' +
            dsRows + '</table></div><div class="hub-note">DB：' + (st.db || '') + '</div></div>' +
          srcPanel +
        '</div>';
      bindCommon(el);
    });
  }

  function bindCommon(root) {
    root.querySelectorAll('[data-go]').forEach(function (b) {
      b.onclick = function () {
        var opts = {};
        if (b.getAttribute('data-sym')) opts.sym = b.getAttribute('data-sym');
        if (b.getAttribute('data-mkt')) opts.mkt = b.getAttribute('data-mkt');
        goRoute(b.getAttribute('data-go'), opts);
      };
    });
    root.querySelectorAll('[data-sync]').forEach(function (b) {
      b.onclick = function () {
        b.textContent = '同步中…';
        jget('/sync?days=40').then(function (r) {
          b.textContent = (r && r.started) ? '已啟動' : '進行中';
          if (window.ShellV5 && window.ShellV5.setSync) {
            window.ShellV5.setSync('ok', r && r.started ? 'SYNCING' : 'BUSY');
          }
          setTimeout(function () {
            var route = window.ShellV5 && window.ShellV5.route && window.ShellV5.route();
            if (route && ACTIVATORS[route]) ACTIVATORS[route]();
          }, 2500);
        });
      };
    });
    root.querySelectorAll('tr[data-code]').forEach(function (tr) {
      tr.onclick = function () { openChart(tr.getAttribute('data-code'), tr.getAttribute('data-mkt') || 'TW'); };
    });
  }

  var ACTIVATORS = {
    institutional: function () { var el = mount('institutional'); if (el) renderInstitutional(el); },
    international: function () { var el = mount('international'); if (el) renderInternational(el); },
    signals: function () { var el = mount('signals'); if (el) renderSignals(el); },
    watchlist: function () { var el = mount('watchlist'); if (el) renderWatchlist(el); },
    risk: function () { var el = mount('risk'); if (el) renderRisk(el); },
    settings: function () { var el = mount('settings'); if (el) renderSettings(el); }
  };

  window.HubV5 = ACTIVATORS;
  window.InstitutionalV5 = { activate: ACTIVATORS.institutional, mount: ACTIVATORS.institutional };
  window.InternationalV5 = { activate: ACTIVATORS.international, mount: ACTIVATORS.international };
  window.SignalsV5 = { activate: ACTIVATORS.signals, mount: ACTIVATORS.signals };
  window.WatchlistV5 = { activate: ACTIVATORS.watchlist, mount: ACTIVATORS.watchlist };
  window.RiskV5 = { activate: ACTIVATORS.risk, mount: ACTIVATORS.risk };
  window.SettingsV5 = { activate: ACTIVATORS.settings, mount: ACTIVATORS.settings };
  window.TrendsV5 = {
    activate: function () {
      if (window.ShellV5 && ShellV5.openChart) ShellV5.openChart('^TWII', 'TW');
      else if (window.ShellV5) ShellV5.go('chart', { sym: '^TWII', mkt: 'TW' });
    },
    mount: function () { this.activate(); }
  };

  window.addEventListener('shell:route', function (ev) {
    var id = ev && ev.detail && ev.detail.route;
    if (id && ACTIVATORS[id]) ACTIVATORS[id]();
  });
})();

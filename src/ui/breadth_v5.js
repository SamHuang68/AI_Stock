/* ============================================================================
 * breadth_v5.js  —  Stock Terminal 5.0 Stage 2：大盤廣度面板
 * ----------------------------------------------------------------------------
 * 資料：GET /breadth（TWSE MI_INDEX MS 漲跌家數 + MIS 指數 + 大盤體質）
 * 掛載：#view-breadth / #mount-breadth（由 shell_v5 路由 show/hide）
 * 不改 chart engine；切回路徑時不拆 DOM。
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var mounted = false;
  var lastData = null;
  var timer = null;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    if ($('breadth-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'breadth-v5-css';
    s.textContent =
      '#view-breadth.sv-panel{max-width:1080px;padding:20px 24px 32px}' +
      '#bd-root{font-family:\'JetBrains Mono\',monospace;color:var(--text)}' +
      '#bd-root .bd-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px}' +
      '#bd-root .bd-kicker{font-size:10px;color:var(--gold);letter-spacing:2px;margin-bottom:4px}' +
      '#bd-root .bd-title{font-family:\'Noto Serif TC\',serif;font-size:26px;font-weight:700;color:var(--thi);letter-spacing:1px}' +
      '#bd-root .bd-sub{font-size:11px;color:var(--tlo);margin-top:4px}' +
      '#bd-root .bd-actions{display:flex;gap:8px;align-items:center}' +
      '#bd-root .bd-btn{padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:10px;cursor:pointer}' +
      '#bd-root .bd-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#bd-root .bd-btn.primary{background:var(--gold);color:#060A12;border-color:transparent;font-weight:700}' +
      '#bd-root .bd-btn.primary:hover{background:#FBBF24}' +
      '#bd-root .bd-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}' +
      '#bd-root .bd-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px 14px;min-height:78px}' +
      '#bd-root .bd-card .k{font-size:9px;color:var(--tlo);letter-spacing:1px;margin-bottom:6px}' +
      '#bd-root .bd-card .v{font-size:22px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#bd-root .bd-card .s{font-size:10px;color:var(--tlo);margin-top:4px}' +
      '#bd-root .up{color:var(--red)}#bd-root .dn{color:var(--green)}#bd-root .flat{color:var(--tlo)}' +
      '#bd-root .bd-bar-wrap{margin:8px 0 16px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:14px}' +
      '#bd-root .bd-bar-lbl{display:flex;justify-content:space-between;font-size:10px;color:var(--tlo);margin-bottom:8px}' +
      '#bd-root .bd-bar{display:flex;height:18px;border-radius:4px;overflow:hidden;background:var(--bg)}' +
      '#bd-root .bd-bar .seg-up{background:var(--red)}' +
      '#bd-root .bd-bar .seg-flat{background:#334155}' +
      '#bd-root .bd-bar .seg-dn{background:var(--green)}' +
      '#bd-root .bd-section{margin-top:14px}' +
      '#bd-root .bd-section h4{font-size:11px;color:var(--gold);letter-spacing:1px;margin:0 0 8px;font-weight:700}' +
      '#bd-root .bd-rows{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 16px}' +
      '#bd-root .bd-row{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid var(--border);font-size:11px}' +
      '#bd-root .bd-row .rk{color:var(--tlo)}#bd-root .bd-row .rv{color:var(--thi);font-weight:700}' +
      '#bd-root .bd-note{font-size:9px;color:var(--tlo);line-height:1.65;margin-top:14px}' +
      '#bd-root .bd-err{color:var(--orange);font-size:11px;padding:10px 0}' +
      '#bd-root .bd-loading{color:var(--tlo);font-size:11px;padding:24px 0;letter-spacing:1px}' +
      '@media (max-width:900px){' +
        '#bd-root .bd-grid{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#bd-root .bd-rows{grid-template-columns:1fr}' +
        '#view-breadth.sv-panel{padding:16px}' +
      '}';
    document.head.appendChild(s);
  }

  function fmt(n, dig) {
    if (n == null || n !== n) return '—';
    dig = dig == null ? 0 : dig;
    return Number(n).toLocaleString('en-US', { maximumFractionDigits: dig, minimumFractionDigits: dig });
  }
  function fmtPct(n) {
    if (n == null || n !== n) return '—';
    var s = (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
    return s;
  }
  function clsChg(n) {
    if (n == null || n !== n) return 'flat';
    return n > 0 ? 'up' : n < 0 ? 'dn' : 'flat';
  }
  function yi(v) {
    if (v == null) return '—';
    return (v / 1e8).toFixed(0) + ' 億';
  }
  function fyi(v) {
    if (v == null) return '—';
    return (v >= 0 ? '+' : '') + (v / 1e8).toFixed(0) + ' 億';
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-breadth');
    if (!panel) return null;
    var mount = $('mount-breadth');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-breadth';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('bd-root')) {
      mount.innerHTML =
        '<div id="bd-root">' +
          '<div class="bd-head">' +
            '<div>' +
              '<div class="bd-kicker">STOCK TERMINAL · 5.0</div>' +
              '<div class="bd-title">大盤廣度</div>' +
              '<div class="bd-sub" id="bd-sub">載入中…</div>' +
            '</div>' +
            '<div class="bd-actions">' +
              '<button type="button" class="bd-btn" id="bd-refresh">↻ 重新整理</button>' +
              '<button type="button" class="bd-btn primary" data-shell-back>← 圖表</button>' +
            '</div>' +
          '</div>' +
          '<div id="bd-body" class="bd-loading">載入廣度資料…</div>' +
        '</div>';
      var btn = $('bd-refresh');
      if (btn) btn.onclick = function () { refresh(true); };
      mounted = true;
    }
    return $('bd-body');
  }

  function render(d) {
    var V = window.Viz;
    var body = ensureMount();
    if (!body) return;
    lastData = d;
    var sub = $('bd-sub');
    if (!d || (!d.ok && !d.indices)) {
      if (sub) sub.textContent = '資料不可用';
      body.innerHTML = '<div class="bd-err">' + ((d && d.error) || '無法載入 /breadth') + '</div>' +
        '<div class="bd-note">請確認本機 server 已重啟並可連線 TWSE。休市日會自動取最近交易日。</div>';
      return;
    }

    var st = d.stocks || {};
    var mk = d.market || {};
    var idx = d.indices || {};
    var t00 = idx.t00 || {};
    var o00 = idx.o00 || {};
    var to = d.turnover || {};
    var inst = d.inst || null;

    if (sub) {
      sub.textContent = '資料日 ' + (d.date || '—') +
        (d.source ? ' · ' + d.source : '') +
        (d.score != null ? ' · 體質 ' + d.score : '');
    }

    var up = st.up, dn = st.down, flat = st.unchanged || 0;
    var sum = (up || 0) + (dn || 0) + flat;
    var pctUp = sum ? (100 * (up || 0) / sum) : 0;
    var pctFlat = sum ? (100 * flat / sum) : 0;
    var pctDn = sum ? (100 * (dn || 0) / sum) : 0;
    var tone = (st.net == null) ? '—'
      : st.net > 200 ? '廣度偏多（上漲遠多於下跌）'
      : st.net > 50 ? '廣度溫和偏多'
      : st.net > -50 ? '廣度糾結'
      : st.net > -200 ? '廣度溫和偏空'
      : '廣度偏空（下跌家數明顯較多）';

    var seg = V ? V.segBar(up, flat, dn) : '';
    var idxCards =
      '<div class="bd-card"><div class="k">加權指數</div>' +
        '<div class="v">' + (t00.price != null ? fmt(t00.price, 2) : '—') + '</div>' +
        '<div class="s ' + clsChg(t00.changePct) + '">' + fmtPct(t00.changePct) + '</div></div>' +
      '<div class="bd-card"><div class="k">櫃買指數</div>' +
        '<div class="v">' + (o00.price != null ? fmt(o00.price, 2) : '—') + '</div>' +
        '<div class="s ' + clsChg(o00.changePct) + '">' + fmtPct(o00.changePct) + '</div></div>' +
      '<div class="bd-card"><div class="k">上漲家數（股票）</div>' +
        '<div class="v up">' + fmt(up) + '</div>' +
        '<div class="s">漲停 ' + fmt(st.limitUp) + '</div></div>' +
      '<div class="bd-card"><div class="k">下跌家數（股票）</div>' +
        '<div class="v dn">' + fmt(dn) + '</div>' +
        '<div class="s">跌停 ' + fmt(st.limitDown) + '</div></div>';

    var bar =
      '<div class="bd-bar-wrap">' +
        '<div class="bd-bar-lbl"><span>股票漲跌結構</span><span>' + tone +
          (st.advRatio != null ? ' · 上漲比 ' + (st.advRatio * 100).toFixed(1) + '%' : '') +
          (st.net != null ? ' · 淨 ' + (st.net >= 0 ? '+' : '') + st.net : '') +
        '</span></div>' +
        (seg || ('<div class="bd-bar" title="紅=上漲 灰=持平 綠=下跌">' +
          '<div class="seg-up" style="width:' + pctUp.toFixed(2) + '%"></div>' +
          '<div class="seg-flat" style="width:' + pctFlat.toFixed(2) + '%"></div>' +
          '<div class="seg-dn" style="width:' + pctDn.toFixed(2) + '%"></div>' +
        '</div>')) +
        '<div class="bd-bar-lbl" style="margin-top:8px;margin-bottom:0">' +
          '<span class="up">上漲 ' + fmt(up) + '（' + pctUp.toFixed(1) + '%）</span>' +
          '<span class="flat">持平 ' + fmt(flat) + '</span>' +
          '<span class="dn">下跌 ' + fmt(dn) + '（' + pctDn.toFixed(1) + '%）</span>' +
        '</div>' +
      '</div>';

    var rows = '';
    rows += '<div class="bd-row"><span class="rk">股票成交金額</span><span class="rv">' + yi(to.stockAmt) + '</span></div>';
    rows += '<div class="bd-row"><span class="rk">市場總成交金額</span><span class="rv">' + yi(to.totalAmt) + '</span></div>';
    rows += '<div class="bd-row"><span class="rk">股票成交筆數</span><span class="rv">' + fmt(to.stockTrades) + '</span></div>';
    rows += '<div class="bd-row"><span class="rk">整體市場上漲</span><span class="rv up">' + fmt(mk.up) +
      '（漲停 ' + fmt(mk.limitUp) + '）</span></div>';
    rows += '<div class="bd-row"><span class="rk">整體市場下跌</span><span class="rv dn">' + fmt(mk.down) +
      '（跌停 ' + fmt(mk.limitDown) + '）</span></div>';
    rows += '<div class="bd-row"><span class="rk">股票未成交 / 無比價</span><span class="rv">' +
      fmt(st.unmatched) + ' / ' + fmt(st.na) + '</span></div>';

    if (d.marketRows && d.marketRows.length) {
      d.marketRows.forEach(function (r) {
        rows += '<div class="bd-row"><span class="rk">' + (r.k || '') + '</span><span class="rv">' +
          (r.v || '—') + (r.score != null ? ' <span style="color:var(--tlo);font-weight:500">(' + r.score + ')</span>' : '') +
          '</span></div>';
      });
    }
    if (inst) {
      var total = (inst.foreign || 0) + (inst.trust || 0) + (inst.dealer || 0);
      rows += '<div class="bd-row"><span class="rk">外資（' + (inst.date || '') + '）</span><span class="rv ' +
        clsChg(inst.foreign) + '">' + fyi(inst.foreign) + '</span></div>';
      rows += '<div class="bd-row"><span class="rk">投信</span><span class="rv ' + clsChg(inst.trust) + '">' +
        fyi(inst.trust) + '</span></div>';
      rows += '<div class="bd-row"><span class="rk">自營商</span><span class="rv ' + clsChg(inst.dealer) + '">' +
        fyi(inst.dealer) + '</span></div>';
      rows += '<div class="bd-row"><span class="rk">三大法人合計</span><span class="rv ' + clsChg(total) + '">' +
        fyi(total) + '</span></div>';
      if (V) {
        rows += '<div class="bd-row" style="display:block;padding-top:6px">' + V.magBars([
          { label: '外資', v: inst.foreign, fmt: V.fmtYiFromYuan },
          { label: '投信', v: inst.trust, fmt: V.fmtYiFromYuan },
          { label: '自營', v: inst.dealer, fmt: V.fmtYiFromYuan }
        ]) + '</div>';
      }
    }

    var scoreCol = '';
    if (d.score != null && V && V.qualityColor) {
      scoreCol = ' style="color:' + V.qualityColor(d.score) + '"';
    }
    var scoreMeter = (d.score != null && V) ? V.scoreMeter(d.score) : '';
    var scoreCard = d.score != null
      ? '<div class="bd-card"><div class="k">大盤體質</div><div class="v"' + scoreCol + '>' + fmt(d.score) +
        '</div><div class="s">' + (d.summary || '量能／法人／融資／估值') + '</div>' + scoreMeter + '</div>'
      : '';

    var hist = d._hist || [];
    var histHtml = '';
    if (hist.length) {
      var ls = (up != null && dn) ? (up / Math.max(dn, 1)) : null;
      var chrono = hist.slice().reverse();
      var lsSeries = chrono.map(function (r) {
        return r.lsRatio != null ? r.lsRatio : (r.net != null ? r.net : null);
      });
      var spark = '';
      if (V && lsSeries.filter(function (v) { return v != null && isFinite(v); }).length >= 2) {
        spark = '<div style="margin-bottom:8px"><div style="font-size:9px;color:var(--tlo)">多空比／淨家數走勢</div>' +
          V.sparkLine(lsSeries) + '</div>';
      }
      histHtml = '<div class="bd-section"><h4>歷史市場廣度（本機歷史庫）</h4>' + spark +
        '<table style="width:100%;border-collapse:collapse;font-size:11px">' +
        '<tr style="color:var(--tlo)"><th style="text-align:left;padding:4px">日期</th><th style="padding:4px">上漲</th>' +
        '<th style="padding:4px">下跌</th><th style="padding:4px">平盤</th><th style="padding:4px">多空比</th></tr>';
      hist.forEach(function (r) {
        var lsTxt = r.lsRatio != null ? Number(r.lsRatio).toFixed(2) : '—';
        var lsCell = lsTxt;
        if (V && r.lsRatio != null) {
          // heat vs 1.0 (balanced): signed distance for color
          lsCell = V.heatCell(lsTxt, r.lsRatio - 1);
        }
        histHtml += '<tr><td style="padding:4px">' + r.date + '</td><td class="up" style="padding:4px;text-align:right">' +
          fmt(r.up) + '</td><td class="dn" style="padding:4px;text-align:right">' + fmt(r.down) +
          '</td><td style="padding:4px;text-align:right">' + fmt(r.flat) +
          '</td><td style="padding:4px;text-align:right">' + lsCell + '</td></tr>';
      });
      histHtml += '</table><div class="bd-note">今日多空比 ' +
        (ls != null ? ls.toFixed(2) : '—') +
        ' · 來源 pulse_history.db（同步資料僅 merge 新日）</div></div>';
    }

    body.innerHTML =
      '<div class="bd-grid">' + idxCards + scoreCard + '</div>' +
      bar +
      '<div class="bd-section"><h4>細節</h4><div class="bd-rows">' + rows + '</div></div>' +
      histHtml +
      (d.error && !d.ok ? '<div class="bd-err">' + d.error + '</div>' : '') +
      '<div class="bd-note">股票欄位為上市「股票」統計（不含權證／ETF 等）；整體市場含全部證券。' +
        '漲跌家數為 TWSE 盤後公布，盤中或休市日自動取最近交易日。台股慣例：紅漲綠跌。⚠ 非投資建議。</div>';
  }

  function refresh(force) {
    var body = ensureMount();
    if (!body) return;
    body.innerHTML = '<div class="bd-loading">載入廣度資料…</div>';
    var url = SRV + '/breadth' + (force ? '?refresh=1' : '');
    Promise.all([
      fetch(url, { cache: 'no-store' }).then(function (r) {
        return r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status));
      }),
      fetch(SRV + '/pulse/history?kind=breadth&n=20', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
    ]).then(function (arr) {
      var d = arr[0] || {};
      d._hist = (arr[1] && arr[1].rows) || [];
      render(d);
    }).catch(function (e) {
      render({ ok: false, error: '載入失敗：' + (e && e.message ? e.message : e) });
    });
  }

  function activate() {
    ensureMount();
    refresh(false);
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'breadth') {
        refresh(false);
      }
    }, 60000);
  }

  function onRoute(ev) {
    var id = ev && ev.detail && ev.detail.route;
    if (id === 'breadth') activate();
  }

  window.BreadthV5 = {
    activate: activate,
    refresh: refresh,
    last: function () { return lastData; }
  };

  window.addEventListener('shell:route', onRoute);

  // shell 可能先 boot：若當前已在 breadth，補掛一次
  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'breadth') {
      activate();
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 200); });
  else setTimeout(boot, 200);
})();

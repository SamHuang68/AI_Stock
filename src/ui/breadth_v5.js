/* ============================================================================
 * breadth_v5.js  —  Stock Terminal 5.0 Stage 2：大盤廣度面板
 * ----------------------------------------------------------------------------
 * 資料：GET /breadth（TWSE MI_INDEX MS 漲跌家數 + MIS 指數 + 大盤體質）
 * 掛載：#view-breadth / #mount-breadth（由 shell_v5 路由 show/hide）
 * 大螢幕一頁高密度（pulse 2-zone 風格）
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var mounted = false;
  var lastData = null;
  var lastMovers = null;
  var timer = null;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    var s = $('breadth-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'breadth-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-breadth.on){overflow:hidden!important}' +
      '#view-breadth.sv-panel.on{' +
        'max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-breadth,#mount-breadth.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#bd-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:none;margin:0;min-width:0;box-sizing:border-box;' +
        'flex:1;min-height:0;display:flex;flex-direction:column}' +
      '#bd-root .bd-head{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#bd-root .bd-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#bd-root .bd-kicker{display:none!important}' +
      '#bd-root .bd-title{font-family:\'Noto Serif TC\',serif;font-size:15px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#bd-root .bd-sub{font-size:9px;color:var(--tlo);margin:0}' +
      '#bd-root .bd-actions{display:flex;gap:4px;flex-wrap:nowrap;justify-content:flex-end;flex:0 0 auto}' +
      '#bd-root .bd-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:9px;cursor:pointer;flex:0 0 auto;white-space:nowrap}' +
      '#bd-root .bd-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#bd-root .bd-btn.primary{background:var(--gold);color:#060A12;border-color:transparent;font-weight:700}' +
      '#bd-root .bd-btn.primary:hover{background:#FBBF24}' +
      '#bd-root .up{color:var(--red)}#bd-root .dn{color:var(--green)}#bd-root .flat{color:var(--tlo)}' +
      '#bd-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#bd-root .bd-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:4px;margin:0 0 4px;min-width:0;flex:0 0 auto}' +
      '#bd-root .bd-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '#bd-root .bd-strip .k{font-size:8px;color:var(--tlo);letter-spacing:.4px;margin-bottom:0;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#bd-root .bd-strip .v{font-size:12px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#bd-root .bd-strip .s{font-size:8px;margin-top:0;font-weight:700;line-height:1.2;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#bd-root .bd-dash{flex:1;min-height:0;display:grid;gap:4px;' +
        'grid-template-rows:minmax(0,1fr);' +
        'grid-template-columns:minmax(0,1.15fr) minmax(0,1fr) minmax(0,1.2fr) minmax(0,.85fr)}' +
      '#bd-root .bd-zone,#bd-root .bd-zone-up,#bd-root .bd-zone-lo{display:contents}' +
      '#bd-root .bd-sec{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%}' +
      '#bd-root .bd-sec h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px;' +
        'display:flex;justify-content:space-between;align-items:center;flex:0 0 auto;gap:4px;font-weight:700}' +
      '#bd-root .bd-sec > .bd-fill{flex:1;min-height:0;overflow:auto}' +
      '#bd-root .bd-bar-lbl{display:flex;justify-content:space-between;font-size:10px;color:var(--tlo);margin-bottom:4px;flex:0 0 auto}' +
      '#bd-root .bd-bar{display:flex;height:18px;border-radius:4px;overflow:hidden;background:var(--bg);flex:0 0 auto}' +
      '#bd-root .bd-bar .seg-up{background:var(--red)}' +
      '#bd-root .bd-bar .seg-flat{background:#334155}' +
      '#bd-root .bd-bar .seg-dn{background:var(--green)}' +
      '#bd-root .bd-rows{display:grid;grid-template-columns:1fr;gap:2px;flex:1;align-content:start;overflow:auto;min-height:0}' +
      '#bd-root .bd-row{display:flex;justify-content:space-between;gap:6px;padding:4px 0;border-bottom:1px solid var(--border);font-size:11px}' +
      '#bd-root .bd-row .rk{color:var(--tlo)}#bd-root .bd-row .rv{color:var(--thi);font-weight:700;text-align:right}' +
      '#bd-root .bd-score-wrap{display:flex;align-items:center;gap:8px;flex:1;min-height:0;margin-top:6px}' +
      '#bd-root .bd-spark{flex:0 0 auto;margin-bottom:4px;background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px;min-height:56px}' +
      '#bd-root .bd-spark svg{width:100%;height:56px;display:block}' +
      '#bd-root table.bd-hist{width:100%;border-collapse:collapse;font-size:10px}' +
      '#bd-root table.bd-hist th,#bd-root table.bd-hist td{padding:2px 4px;border-bottom:1px solid var(--border);text-align:right}' +
      '#bd-root table.bd-hist th:first-child,#bd-root table.bd-hist td:first-child{text-align:left}' +
      '#bd-root table.bd-hist th{color:var(--tlo);font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1}' +
      '#bd-root .bd-note{font-size:8px;color:var(--tlo);line-height:1.35;margin-top:3px;flex:0 0 auto}' +
      '#bd-root .bd-err{color:var(--orange);font-size:10px;padding:6px 0}' +
      '#bd-root .bd-loading{color:var(--tlo);font-size:10px;padding:12px 0;letter-spacing:1px}' +
      /* 漲停／跌停 icon + 浮動清單 */
      '#bd-root .bd-lim{display:inline-flex;align-items:center;gap:4px;cursor:pointer;position:relative;' +
        'padding:1px 5px;border-radius:4px;border:1px solid transparent;user-select:none}' +
      '#bd-root .bd-lim:hover,#bd-root .bd-lim.open{border-color:var(--gold-m);background:var(--gold-s)}' +
      '#bd-root .bd-lim-ico{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;' +
        'border-radius:3px;font-size:9px;font-weight:800;line-height:1;flex:0 0 auto}' +
      '#bd-root .bd-lim-ico.up{background:rgba(248,113,113,.2);color:var(--red);border:1px solid rgba(248,113,113,.45)}' +
      '#bd-root .bd-lim-ico.dn{background:rgba(74,222,128,.18);color:var(--green);border:1px solid rgba(74,222,128,.4)}' +
      '#bd-root .bd-pop{display:none;position:absolute;top:calc(100% + 6px);left:0;z-index:80;width:280px;max-height:320px;' +
        'overflow:auto;background:#0B1220;border:1px solid var(--border);border-radius:8px;' +
        'box-shadow:0 12px 28px rgba(0,0,0,.55);padding:6px 0}' +
      '#bd-root .bd-lim.open .bd-pop{display:block}' +
      '#bd-root .bd-pop-h{padding:4px 10px 6px;font-size:10px;color:var(--gold);font-weight:700;' +
        'border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:8px}' +
      '#bd-root .bd-pop-row{display:flex;align-items:center;gap:6px;padding:4px 10px;font-size:10px;cursor:pointer}' +
      '#bd-root .bd-pop-row:hover{background:var(--bg3)}' +
      '#bd-root .bd-pop-row .cd{color:var(--gold);font-weight:700;min-width:42px}' +
      '#bd-root .bd-pop-row .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)}' +
      '#bd-root .bd-pop-row .pc{font-weight:700;min-width:58px;text-align:right}' +
      '#bd-root .bd-pop-empty{padding:12px 10px;color:var(--tlo);font-size:10px;text-align:center}' +
      '#bd-root .bd-strip .cell.has-lim{overflow:visible}' +
      '#bd-root .bd-strip{overflow:visible}';
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

  function stripCell(k, v, s, cls, extraCls) {
    return '<div class="cell' + (extraCls ? ' ' + extraCls : '') + '"><div class="k">' + k + '</div>' +
      '<div class="v' + (cls ? ' ' + cls : '') + '">' + v + '</div>' +
      (s ? '<div class="s' + (cls ? ' ' + cls : '') + '">' + s + '</div>' : '') + '</div>';
  }

  function limitPopup(side, count, list) {
    var isUp = side === 'up';
    var title = isUp ? '漲停清單' : '跌停清單';
    var ico = isUp ? '▲' : '▼';
    var rows = '';
    if (!list || !list.length) {
      rows = '<div class="bd-pop-empty">尚無' + (isUp ? '漲停' : '跌停') +
        '標的（±9.5% 近似）· 或資料載入中</div>';
    } else {
      list.slice(0, 30).forEach(function (r) {
        rows += '<div class="bd-pop-row" data-code="' + (r.code || '') + '">' +
          '<span class="cd">' + (r.code || '') + '</span>' +
          '<span class="nm">' + (r.name || '') + '</span>' +
          '<span class="pc ' + clsChg(r.changePct) + '">' + fmtPct(r.changePct) + '</span></div>';
      });
    }
    return '<span class="bd-lim" data-lim="' + side + '" title="點擊查看' + title + '">' +
      '<span class="bd-lim-ico ' + (isUp ? 'up' : 'dn') + '">' + ico + '</span>' +
      '<span>' + (isUp ? '漲停 ' : '跌停 ') + fmt(count) + '</span>' +
      '<div class="bd-pop" role="dialog">' +
        '<div class="bd-pop-h"><span>' + title + ' · ' + (list ? list.length : 0) + '</span>' +
          '<span style="color:var(--tlo);font-weight:600">±9.5% 近似</span></div>' +
        rows +
      '</div></span>';
  }

  function bindLimitPopups(root) {
    if (!root) return;
    root.querySelectorAll('.bd-lim').forEach(function (el) {
      el.onclick = function (e) {
        e.stopPropagation();
        var open = el.classList.contains('open');
        root.querySelectorAll('.bd-lim.open').forEach(function (x) { x.classList.remove('open'); });
        if (!open) el.classList.add('open');
      };
    });
    root.querySelectorAll('.bd-pop-row[data-code]').forEach(function (row) {
      row.onclick = function (e) {
        e.stopPropagation();
        var code = row.getAttribute('data-code');
        if (code && typeof loadSym === 'function') {
          loadSym(code, 'TW');
          if (window.ShellV5) window.ShellV5.go('chart');
        }
      };
    });
    if (!bindLimitPopups._doc) {
      bindLimitPopups._doc = true;
      document.addEventListener('click', function () {
        var r = $('bd-root');
        if (r) r.querySelectorAll('.bd-lim.open').forEach(function (x) { x.classList.remove('open'); });
      });
    }
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
              '<span class="bd-title">大盤廣度</span>' +
              '<span class="bd-sub" id="bd-sub">載入中…</span>' +
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

    var scoreCol = '';
    if (d.score != null && V && V.qualityColor) {
      scoreCol = ' style="color:' + V.qualityColor(d.score) + '"';
    }
    var scoreMeter = (d.score != null && V) ? V.scoreMeter(d.score) : '';

    var mv = lastMovers || d._movers || {};
    var limUpList = mv.limitUp || [];
    var limDnList = mv.limitDown || [];
    if (!limUpList.length && (mv.gainers || []).length) {
      limUpList = (mv.gainers || []).filter(function (r) { return r.changePct != null && r.changePct >= 9.5; });
    }
    if (!limDnList.length && (mv.losers || []).length) {
      limDnList = (mv.losers || []).filter(function (r) { return r.changePct != null && r.changePct <= -9.5; });
    }
    var strip =
      stripCell('加權指數', t00.price != null ? fmt(t00.price, 2) : '—', fmtPct(t00.changePct), clsChg(t00.changePct)) +
      stripCell('櫃買指數', o00.price != null ? fmt(o00.price, 2) : '—', fmtPct(o00.changePct), clsChg(o00.changePct)) +
      stripCell('上漲家數', fmt(up), limitPopup('up', st.limitUp, limUpList), null, 'has-lim') +
      stripCell('下跌家數', fmt(dn), limitPopup('dn', st.limitDown, limDnList), null, 'has-lim') +
      stripCell('淨家數', st.net != null ? ((st.net >= 0 ? '+' : '') + st.net) : '—',
        st.advRatio != null ? '上漲比 ' + (st.advRatio * 100).toFixed(1) + '%' : tone) +
      stripCell('大盤體質', d.score != null ? fmt(d.score) : '—', d.summary || '量能／法人／融資', '');

    var seg = V ? V.segBar(up, flat, dn) : '';
    var breadthBlock =
      '<div class="bd-sec"><h4>漲跌結構</h4><div class="bd-fill" style="display:flex;flex-direction:column;gap:8px;justify-content:center">' +
        '<div class="bd-bar-lbl"><span>' + tone + '</span><span>' +
          (st.net != null ? '淨 ' + (st.net >= 0 ? '+' : '') + st.net : '') +
        '</span></div>' +
        (seg || ('<div class="bd-bar" title="紅=上漲 灰=持平 綠=下跌">' +
          '<div class="seg-up" style="width:' + pctUp.toFixed(2) + '%"></div>' +
          '<div class="seg-flat" style="width:' + pctFlat.toFixed(2) + '%"></div>' +
          '<div class="seg-dn" style="width:' + pctDn.toFixed(2) + '%"></div>' +
        '</div>')) +
        '<div class="bd-bar-lbl" style="margin:0">' +
          '<span class="up">上漲 ' + fmt(up) + '（' + pctUp.toFixed(1) + '%）</span>' +
          '<span class="flat">持平 ' + fmt(flat) + '</span>' +
          '<span class="dn">下跌 ' + fmt(dn) + '（' + pctDn.toFixed(1) + '%）</span>' +
        '</div>' +
        (d.score != null
          ? '<div class="bd-score-wrap"><div class="v"' + scoreCol + ' style="font-size:28px;font-weight:800">' +
              fmt(d.score) + '</div>' + scoreMeter + '</div>'
          : '') +
      '</div></div>';

    var rows = '';
    rows += '<div class="bd-row"><span class="rk">股票成交金額</span><span class="rv">' + yi(to.stockAmt) + '</span></div>';
    rows += '<div class="bd-row"><span class="rk">市場總成交金額</span><span class="rv">' + yi(to.totalAmt) + '</span></div>';
    rows += '<div class="bd-row"><span class="rk">股票成交筆數</span><span class="rv">' + fmt(to.stockTrades) + '</span></div>';
    rows += '<div class="bd-row"><span class="rk">整體市場上漲</span><span class="rv up">' + fmt(mk.up) +
      '（' + limitPopup('up', mk.limitUp != null ? mk.limitUp : st.limitUp, limUpList) + '）</span></div>';
    rows += '<div class="bd-row"><span class="rk">整體市場下跌</span><span class="rv dn">' + fmt(mk.down) +
      '（' + limitPopup('dn', mk.limitDown != null ? mk.limitDown : st.limitDown, limDnList) + '）</span></div>';
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
        rows += '<div class="bd-row" style="display:block;padding-top:4px;grid-column:1/-1;border:none">' + V.magBars([
          { label: '外資', v: inst.foreign, fmt: V.fmtYiFromYuan },
          { label: '投信', v: inst.trust, fmt: V.fmtYiFromYuan },
          { label: '自營', v: inst.dealer, fmt: V.fmtYiFromYuan }
        ]) + '</div>';
      }
    }

    var detailBlock =
      '<div class="bd-sec"><h4>細節</h4><div class="bd-fill"><div class="bd-rows">' + rows + '</div></div></div>';

    var hist = d._hist || [];
    var histBlock = '';
    if (hist.length) {
      var ls = (up != null && dn) ? (up / Math.max(dn, 1)) : null;
      var chrono = hist.slice().reverse();
      var lsSeries = chrono.map(function (r) {
        return r.lsRatio != null ? r.lsRatio : (r.net != null ? r.net : null);
      });
      var spark = '';
      if (V && lsSeries.filter(function (v) { return v != null && isFinite(v); }).length >= 2) {
        spark = '<div class="bd-spark">' + V.sparkLine(lsSeries) + '</div>';
      }
      var tbl = '<table class="bd-hist"><tr><th>日期</th><th>上漲</th><th>下跌</th><th>平盤</th><th>多空比</th></tr>';
      hist.forEach(function (r) {
        var lsTxt = r.lsRatio != null ? Number(r.lsRatio).toFixed(2) : '—';
        var lsCell = lsTxt;
        if (V && r.lsRatio != null) {
          lsCell = V.heatCell(lsTxt, r.lsRatio - 1);
        }
        tbl += '<tr><td>' + r.date + '</td><td class="up">' + fmt(r.up) +
          '</td><td class="dn">' + fmt(r.down) +
          '</td><td>' + fmt(r.flat) +
          '</td><td>' + lsCell + '</td></tr>';
      });
      tbl += '</table>';
      histBlock =
        '<div class="bd-sec"><h4>歷史廣度</h4>' +
          '<div class="bd-fill">' + spark + tbl + '</div>' +
          '<div class="bd-note">今日多空比 ' + (ls != null ? ls.toFixed(2) : '—') +
            ' · pulse_history.db</div></div>';
    }

    var noteSec =
      '<div class="bd-sec"><h4>備註</h4><div class="bd-fill">' +
        '<div class="bd-note" style="margin:0;font-size:9px;line-height:1.5">' +
        '股票欄位為上市「股票」統計（不含權證／ETF）；整體市場含全部證券。' +
        '漲跌家數為 TWSE 盤後公布，盤中或休市日自動取最近交易日。台股慣例：紅漲綠跌。僅供參考。</div></div></div>';

    body.innerHTML =
      '<div class="bd-strip">' + strip + '</div>' +
      '<div class="bd-dash">' +
        '<div class="bd-zone bd-zone-up">' + breadthBlock + detailBlock + '</div>' +
        '<div class="bd-zone bd-zone-lo">' +
          (histBlock || '<div class="bd-sec"><h4>歷史廣度</h4><div class="bd-fill"><div class="bd-note">尚無本機歷史紀錄</div></div></div>') +
          noteSec +
        '</div>' +
      '</div>' +
      (d.error && !d.ok ? '<div class="bd-err">' + d.error + '</div>' : '');
    lastData = d;
    bindLimitPopups($('bd-root'));
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
        .catch(function () { return null; }),
      fetch(SRV + '/movers?n=30', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
    ]).then(function (arr) {
      var d = arr[0] || {};
      d._hist = (arr[1] && arr[1].rows) || [];
      lastMovers = arr[2] || null;
      d._movers = lastMovers;
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

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'breadth') {
      activate();
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 200); });
  else setTimeout(boot, 200);
})();

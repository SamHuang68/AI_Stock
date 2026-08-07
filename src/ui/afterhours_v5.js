/* ============================================================================
 * afterhours_v5.js  —  Stock Terminal 5.0 Stage 3：台股盤後整理
 * ----------------------------------------------------------------------------
 * 資料（皆既有端點，不新增 scraper）：
 *   GET /txf        — 台指期夜盤（主訊號）
 *   GET /stockfut   — 市值前十大個股期領先
 *   GET /marketflow — 量能／三大法人（盤後籌碼）
 *   GET /breadth    — 漲跌家數摘要（S2）
 * 掛載：#mount-afterhours；路由 shell:route=afterhours
 * 大螢幕一頁高密度（pulse 2-zone 風格）
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var LIST = [
    { code: '2330', name: '台積電', cid: 'CDF' },
    { code: '2317', name: '鴻海', cid: 'DHF' },
    { code: '2454', name: '聯發科', cid: 'DVF' },
    { code: '2308', name: '台達電', cid: 'FRF' },
    { code: '2382', name: '廣達', cid: 'DKF' },
    { code: '2891', name: '中信金', cid: 'CNF' },
    { code: '2882', name: '國泰金', cid: 'CKF' },
    { code: '2881', name: '富邦金', cid: 'CEF' },
    { code: '2412', name: '中華電', cid: 'DLF' },
    { code: '3711', name: '日月光投控', cid: 'OZF' }
  ];

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    var s = $('afterhours-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'afterhours-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-afterhours.on){overflow:hidden!important}' +
      '#view-afterhours.sv-panel.on{' +
        'max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-afterhours,#mount-afterhours.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#ah-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:none;margin:0;min-width:0;box-sizing:border-box;' +
        'flex:1;min-height:0;display:flex;flex-direction:column}' +
      '#ah-root .ah-head{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#ah-root .ah-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#ah-root .ah-kicker{font-size:9px;color:var(--gold);letter-spacing:1.2px;margin:0;font-weight:700}' +
      '#ah-root .ah-title{font-family:\'Noto Serif TC\',serif;font-size:15px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#ah-root .ah-sub{font-size:9px;color:var(--tlo);margin:0}' +
      '#ah-root .ah-actions{display:flex;gap:4px;flex-wrap:nowrap;justify-content:flex-end;flex:0 0 auto}' +
      '#ah-root .ah-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:9px;cursor:pointer;flex:0 0 auto;white-space:nowrap}' +
      '#ah-root .ah-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#ah-root .ah-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#ah-root .ah-btn.primary:hover{background:#FBBF24}' +
      '#ah-root .up{color:var(--red)}#ah-root .dn{color:var(--green)}#ah-root .flat{color:var(--tlo)}' +
      '#ah-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#ah-root .ah-strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:4px;margin:0 0 4px;min-width:0;flex:0 0 auto}' +
      '#ah-root .ah-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '#ah-root .ah-strip .k{font-size:8px;color:var(--tlo);letter-spacing:.4px;margin-bottom:0;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-strip .v{font-size:12px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-strip .s{font-size:8px;margin-top:0;font-weight:700;line-height:1.2;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-strip .viz-hide,#ah-root .ah-strip .viz-meter,#ah-root .ah-strip .viz-seg,' +
        '#ah-root .ah-strip .viz-chip{display:none!important}' +
      '#ah-root .ah-dash{flex:1;min-height:0;display:grid;gap:4px;' +
        'grid-template-rows:minmax(0,1fr);' +
        'grid-template-columns:minmax(0,1fr) minmax(0,1.25fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)}' +
      '#ah-root .ah-zone,#ah-root .ah-zone-up,#ah-root .ah-zone-lo{display:contents}' +
      '#ah-root .ah-sec{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%}' +
      '#ah-root .ah-sec h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px;' +
        'display:flex;justify-content:space-between;align-items:center;flex:0 0 auto;gap:4px;font-weight:700}' +
      '#ah-root .ah-sec > .ah-fill{flex:1;min-height:0;overflow:auto}' +
      '#ah-root .ah-tone{font-size:11px;margin:0 0 6px;font-weight:700;flex:0 0 auto}' +
      '#ah-root .ah-ohlc{display:grid;grid-template-columns:repeat(2,1fr);gap:5px;flex:1;align-content:stretch;' +
        'grid-auto-rows:minmax(0,1fr);min-height:0}' +
      '#ah-root .ah-ohlc .box{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px 6px;' +
        'text-align:center;display:flex;flex-direction:column;justify-content:center}' +
      '#ah-root .ah-ohlc .box .k{font-size:9px;color:var(--tlo)}' +
      '#ah-root .ah-ohlc .box .v{font-size:15px;font-weight:700;margin-top:2px;color:var(--thi)}' +
      '#ah-root table.ah-tbl{width:100%;border-collapse:collapse;font-size:10px}' +
      '#ah-root table.ah-tbl th,#ah-root table.ah-tbl td{padding:3px 4px;border-bottom:1px solid var(--border);text-align:right}' +
      '#ah-root table.ah-tbl th:first-child,#ah-root table.ah-tbl td:first-child,' +
      '#ah-root table.ah-tbl th:nth-child(2),#ah-root table.ah-tbl td:nth-child(2){text-align:left}' +
      '#ah-root table.ah-tbl th{color:var(--tlo);font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1}' +
      '#ah-root tr.ah-row{cursor:pointer}#ah-root tr.ah-row:hover{background:var(--bg3)}' +
      '#ah-root .ah-inst4{display:grid;grid-template-columns:1fr 1fr;gap:5px;flex:1;align-content:stretch;' +
        'grid-auto-rows:minmax(0,1fr);min-height:0;margin-bottom:0}' +
      '#ah-root .ah-inst4 .c{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px 6px;' +
        'text-align:center;display:flex;flex-direction:column;justify-content:center}' +
      '#ah-root .ah-inst4 .c .k{font-size:9px;color:var(--tlo)}' +
      '#ah-root .ah-inst4 .c .v{font-size:14px;font-weight:800;margin-top:2px;color:var(--thi)}' +
      '#ah-root .ah-note{font-size:8px;color:var(--tlo);line-height:1.35;margin-top:2px;flex:0 0 auto;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ah-root .ah-loading,#ah-root .ah-err{font-size:10px;color:var(--tlo);padding:10px 0}' +
      '#ah-root .ah-err{color:var(--orange)}' +
      '#ah-body.ah-loading{display:flex;align-items:center}';
  }

  function twCls(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
  }
  function pct(p) {
    if (p == null || p !== p) return '—';
    return (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
  }
  function fmtN(v, dig) {
    if (v == null || !isFinite(v)) return '—';
    dig = dig == null ? 0 : dig;
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: dig, minimumFractionDigits: dig });
  }
  function yi(v) { return v == null ? '—' : (v / 1e8).toFixed(0) + ' 億'; }
  function fyi(v) {
    if (v == null) return '—';
    return (v >= 0 ? '+' : '') + (v / 1e8).toFixed(0) + ' 億';
  }
  function fmtTime(t) {
    if (!t || String(t).length < 4) return '';
    var s = String(t).padStart(6, '0');
    return s.slice(0, 2) + ':' + s.slice(2, 4) + ':' + s.slice(4, 6);
  }
  function toneTxf(p, amp) {
    var parts = [];
    if (p == null) parts.push('夜盤%不足');
    else if (p <= -1.5) parts.push('強烈開低風險');
    else if (p <= -0.5) parts.push('偏弱・開低機率高');
    else if (p >= 1.5) parts.push('強烈開高・留意追高');
    else if (p >= 0.5) parts.push('偏強・開高機率高');
    else parts.push('中性・開盤波動有限');
    if (amp != null) {
      if (amp >= 3.5) parts.push('高振幅');
      else if (amp >= 2.0) parts.push('波動偏大');
    }
    return parts.join(' · ');
  }

  function normalizeNight(d) {
    if (!d || !d.ok) return null;
    var n = d.night;
    if (!n || n.price == null) {
      if (d.session === 'night' && d.price != null) n = d;
      else if (d.ampRate != null && d.high != null && d.low != null) n = d;
      else return null;
    }
    var changePct = n.changePct;
    if (changePct == null && n.prevClose > 0) changePct = (n.price - n.prevClose) / n.prevClose * 100;
    var amp = n.ampRate;
    if (amp == null && n.high != null && n.low != null && n.prevClose > 0) {
      amp = (n.high - n.low) / n.prevClose * 100;
    }
    return {
      price: n.price, prevClose: n.prevClose, change: n.change, changePct: changePct,
      open: n.open, high: n.high, low: n.low, ampRate: amp, volume: n.volume,
      time: n.time || '', source: n.source || d.source || '', sessionLabel: n.sessionLabel || '夜盤'
    };
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-afterhours');
    if (!panel) return null;
    var mount = $('mount-afterhours');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-afterhours';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('ah-root')) {
      mount.innerHTML =
        '<div id="ah-root">' +
          '<div class="ah-head">' +
            '<div>' +
              '<span class="ah-kicker">STOCK TERMINAL · 5.0</span>' +
              '<span class="ah-title">盤後數據</span>' +
              '<span class="ah-sub" id="ah-sub">漲跌排行 · 夜盤 · 籌碼摘要</span>' +
            '</div>' +
            '<div class="ah-actions">' +
              '<button type="button" class="ah-btn" id="ah-refresh">↻ 重新整理</button>' +
              '<button type="button" class="ah-btn" id="ah-open-ovn">夜盤詳情</button>' +
              '<button type="button" class="ah-btn primary" data-shell-back>← 圖表</button>' +
            '</div>' +
          '</div>' +
          '<div id="ah-body" class="ah-loading">載入盤後資料…</div>' +
        '</div>';
      var r = $('ah-refresh');
      if (r) r.onclick = function () { refresh(); };
      var o = $('ah-open-ovn');
      if (o) o.onclick = function () {
        if (window.overnightOpen) window.overnightOpen();
      };
    }
    return $('ah-body');
  }

  function stripCell(k, v, s, cls) {
    return '<div class="cell"><div class="k">' + k + '</div>' +
      '<div class="v' + (cls ? ' ' + cls : '') + '">' + v + '</div>' +
      (s ? '<div class="s' + (cls ? ' ' + cls : '') + '">' + s + '</div>' : '') + '</div>';
  }

  function render(pack) {
    var V = window.Viz;
    var body = ensureMount();
    if (!body) return;
    var txf = pack.txf, fut = pack.fut || [], mf = pack.mf || {}, bd = pack.bd || {};
    var sub = $('ah-sub');
    var st = (bd.stocks || {});
    if (sub) {
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (txf && txf.time ? ' · 夜盤 ' + fmtTime(txf.time) : '') +
        (bd.date ? ' · 廣度日 ' + bd.date : '');
    }

    var inst = mf.inst;
    var to = (mf.turnover || []).filter(function (x) { return x.amount != null; });
    var latestAmt = to.length ? to[to.length - 1].amount : null;
    var total = inst ? ((inst.foreign || 0) + (inst.trust || 0) + (inst.dealer || 0)) : null;

    var strip =
      stripCell('台指期夜盤', txf ? fmtN(txf.price) : '—', pct(txf && txf.changePct), twCls(txf && txf.changePct)) +
      stripCell('夜盤%', pct(txf && txf.changePct), txf ? (txf.sessionLabel || '夜盤') : '—', twCls(txf && txf.changePct)) +
      stripCell('夜盤振幅', txf && txf.ampRate != null ? txf.ampRate.toFixed(2) + '%' : '—', txf ? fmtN(txf.volume) + ' 口' : '—') +
      stripCell('漲跌家數', '<span class="up">' + fmtN(st.up) + '</span> / <span class="dn">' + fmtN(st.down) + '</span>',
        '淨 ' + (st.net != null ? ((st.net >= 0 ? '+' : '') + st.net) : '—')) +
      stripCell('大盤體質', bd.score != null ? bd.score : '—', bd.summary || '量能／法人／融資') +
      stripCell('法人合計', fyi(total), yi(latestAmt) + ' 成交');

    var txfBlock = '<div class="ah-sec"><h4>台指期夜盤</h4>';
    if (!txf) {
      txfBlock += '<div class="ah-err">暫無夜盤資料（/txf）</div></div>';
    } else {
      txfBlock +=
        '<div class="ah-tone ' + twCls(txf.changePct) + '">' + toneTxf(txf.changePct, txf.ampRate) + '</div>' +
        '<div class="ah-ohlc">' +
          '<div class="box"><div class="k">開</div><div class="v">' + fmtN(txf.open) + '</div></div>' +
          '<div class="box"><div class="k">高</div><div class="v">' + fmtN(txf.high) + '</div></div>' +
          '<div class="box"><div class="k">低</div><div class="v">' + fmtN(txf.low) + '</div></div>' +
          '<div class="box"><div class="k">昨收</div><div class="v">' + fmtN(txf.prevClose) + '</div></div>' +
        '</div>' +
        '<div class="ah-note">來源 ' + (txf.source || '—') +
          (txf.volume != null ? ' · 量 ' + fmtN(txf.volume) : '') +
          ' · 夜盤%作隔日開盤方向參考</div></div>';
    }

    var leadMax = 0;
    fut.forEach(function (r) {
      if (r.lead != null && isFinite(r.lead)) leadMax = Math.max(leadMax, Math.abs(r.lead));
    });
    var rows = fut.map(function (r) {
      var lead = r.lead == null ? '—' : ((r.lead >= 0 ? '+' : '') + r.lead.toFixed(2));
      var leadExtra = '';
      if (V && r.lead != null && isFinite(r.lead)) {
        leadExtra = V.rowBar(r.lead, leadMax || 1) +
          V.chip(r.lead >= 0 ? '期>現' : '期<現', r.lead >= 0 ? 'buy' : 'sell');
      }
      return '<tr class="ah-row" data-code="' + r.code + '">' +
        '<td style="color:var(--gold);font-weight:700">' + r.code + '</td>' +
        '<td>' + r.name + '</td>' +
        '<td>' + (r.price != null ? r.price : '—') + '</td>' +
        '<td class="' + twCls(r.changePct) + '">' + pct(r.changePct) + '</td>' +
        '<td class="' + twCls(r.spotChangePct) + '">' + pct(r.spotChangePct) + '</td>' +
        '<td class="' + twCls(r.lead) + '">' + lead + leadExtra + '</td></tr>';
    }).join('');
    var sess = fut.some(function (r) { return r.session === 'night'; }) ? '夜盤'
      : fut.some(function (r) { return r.session === 'day'; }) ? '日盤' : '—';
    var futBlock =
      '<div class="ah-sec"><h4>個股期領先 · ' + sess + '</h4>' +
      '<div class="ah-fill">' +
      (rows
        ? '<table class="ah-tbl"><tr><th>代號</th><th>名稱</th><th>期價</th><th>期%</th><th>現%</th><th>領先</th></tr>' +
          rows + '</table>'
        : '<div class="ah-err">個股期資料暫缺</div>') +
      '</div>' +
      '<div class="ah-note">領先 = 期% − 現% · 點列載入線型</div></div>';

    var instBlock = '<div class="ah-sec"><h4>盤後籌碼</h4>';
    if (!inst && latestAmt == null) {
      instBlock += '<div class="ah-err">資金流尚未更新</div></div>';
    } else {
      var instBars = '';
      var totalChip = '';
      if (V && inst) {
        instBars = V.magBars([
          { label: '外資', v: inst.foreign, fmt: V.fmtYiFromYuan },
          { label: '投信', v: inst.trust, fmt: V.fmtYiFromYuan },
          { label: '合計', v: total, fmt: V.fmtYiFromYuan }
        ]);
        if (total != null) {
          totalChip = V.chip(total > 0 ? '合計偏多' : (total < 0 ? '合計偏空' : '合計中性'),
            total > 0 ? 'buy' : (total < 0 ? 'sell' : 'mid'));
        }
      }
      instBlock += '<div class="ah-fill">' +
        '<div class="ah-inst4">' +
          '<div class="c"><div class="k">成交金額</div><div class="v">' + yi(latestAmt) + '</div></div>' +
          '<div class="c"><div class="k">外資</div><div class="v ' + twCls(inst && inst.foreign) + '">' + fyi(inst && inst.foreign) + '</div></div>' +
          '<div class="c"><div class="k">投信</div><div class="v ' + twCls(inst && inst.trust) + '">' + fyi(inst && inst.trust) + '</div></div>' +
          '<div class="c"><div class="k">合計</div><div class="v ' + twCls(total) + '">' + fyi(total) + '</div></div>' +
        '</div>' + instBars + totalChip +
        '</div>' +
        '<div class="ah-note">法人日 ' + ((inst && inst.date) || mf.date || '—') + '</div></div>';
    }

    var movers = pack.movers || {};
    var gain = movers.gainers || movers.up || [];
    var lose = movers.losers || movers.down || [];
    function mvTbl(list, title, cls) {
      var h = '<div class="ah-sec"><h4>' + title + '</h4><div class="ah-fill">';
      if (!list.length) return h + '<div class="ah-err">尚無排行</div></div></div>';
      var slice = list.slice(0, 22);
      var maxAbs = 0;
      slice.forEach(function (r) {
        if (r.changePct != null && isFinite(r.changePct)) maxAbs = Math.max(maxAbs, Math.abs(r.changePct));
      });
      h += '<table class="ah-tbl"><tr><th>#</th><th>代號</th><th>名稱</th><th>漲跌幅</th></tr>';
      slice.forEach(function (r, i) {
        var lim = V ? V.limitChip(r.changePct) : '';
        var bar = V ? V.rowBar(r.changePct, maxAbs) : '';
        h += '<tr class="ah-row" data-code="' + (r.code || '') + '"><td>' + (i + 1) +
          '</td><td style="color:var(--gold);font-weight:700">' + (r.code || '') +
          '</td><td>' + (r.name || '') + '</td><td class="' + (cls || twCls(r.changePct)) + '">' +
          pct(r.changePct) + lim + bar + '</td></tr>';
      });
      return h + '</table></div></div>';
    }

    body.classList.remove('ah-loading');
    body.innerHTML =
      '<div class="ah-strip">' + strip + '</div>' +
      '<div class="ah-dash">' +
        '<div class="ah-zone ah-zone-up">' + txfBlock + futBlock + '</div>' +
        '<div class="ah-zone ah-zone-lo">' + instBlock + mvTbl(gain, '漲幅排行', 'up') + mvTbl(lose, '跌幅排行', 'dn') + '</div>' +
      '</div>' +
      '<div class="ah-note">僅供參考 · TAIFEX MIS / TWSE OpenData</div>';

    body.querySelectorAll('tr.ah-row').forEach(function (el) {
      el.onclick = function () {
        var c = el.getAttribute('data-code');
        if (c && typeof loadSym === 'function') {
          loadSym(c, 'TW');
          if (window.ShellV5) window.ShellV5.go('chart');
        }
      };
    });
  }

  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function refresh() {
    var body = ensureMount();
    if (!body) return;
    body.innerHTML = '<div class="ah-loading">載入盤後資料…</div>';
    var cids = LIST.map(function (x) { return x.cid; }).join(',');
    Promise.all([
      jget('/txf'),
      jget('/stockfut?cids=' + encodeURIComponent(cids)),
      jget('/marketflow'),
      jget('/breadth'),
      jget('/movers?n=22')
    ]).then(function (arr) {
      var txfRaw = arr[0], sf = arr[1], mf = arr[2], bd = arr[3], mv = arr[4];
      var byCid = {};
      ((sf && sf.results) || []).forEach(function (r) { byCid[r.cid] = r; });
      var fut = LIST.map(function (s) {
        return Object.assign({}, s, byCid[s.cid] || { ok: false });
      }).sort(function (a, b) {
        return (b.changePct == null ? -999 : b.changePct) - (a.changePct == null ? -999 : a.changePct);
      });
      render({ txf: normalizeNight(txfRaw), fut: fut, mf: mf || {}, bd: bd || {}, movers: mv || {} });
    });
  }

  function activate() {
    ensureMount();
    refresh();
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'afterhours') refresh();
    }, 45000);
  }

  window.AfterhoursV5 = { activate: activate, refresh: refresh };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'afterhours') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'afterhours') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 220); });
  else setTimeout(boot, 220);
})();

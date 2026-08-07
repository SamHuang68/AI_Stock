/* ============================================================================
 * afterhours_v5.js  —  Stock Terminal 5.0 Stage 3：台股盤後整理
 * ----------------------------------------------------------------------------
 * 資料（皆既有端點，不新增 scraper）：
 *   GET /txf        — 台指期夜盤（主訊號）
 *   GET /stockfut   — 市值前十大個股期領先
 *   GET /marketflow — 量能／三大法人（盤後籌碼）
 *   GET /breadth    — 漲跌家數摘要（S2）
 * 掛載：#mount-afterhours；路由 shell:route=afterhours
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
    if ($('afterhours-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'afterhours-v5-css';
    s.textContent =
      '#view-afterhours.sv-panel{max-width:1100px;padding:20px 24px 32px}' +
      '#ah-root{font-family:\'JetBrains Mono\',monospace;color:var(--text)}' +
      '#ah-root .ah-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px}' +
      '#ah-root .ah-kicker{font-size:10px;color:var(--gold);letter-spacing:2px;margin-bottom:4px}' +
      '#ah-root .ah-title{font-family:\'Noto Serif TC\',serif;font-size:26px;font-weight:700;color:var(--thi);letter-spacing:1px}' +
      '#ah-root .ah-sub{font-size:11px;color:var(--tlo);margin-top:4px}' +
      '#ah-root .ah-actions{display:flex;gap:8px;flex-wrap:wrap}' +
      '#ah-root .ah-btn{padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:10px;cursor:pointer}' +
      '#ah-root .ah-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#ah-root .ah-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#ah-root .ah-btn.primary:hover{background:#FBBF24}' +
      '#ah-root .ah-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}' +
      '#ah-root .ah-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px 14px;min-height:78px}' +
      '#ah-root .ah-card .k{font-size:9px;color:var(--tlo);letter-spacing:1px;margin-bottom:6px}' +
      '#ah-root .ah-card .v{font-size:22px;font-weight:700;color:var(--thi);line-height:1.15}' +
      '#ah-root .ah-card .s{font-size:10px;color:var(--tlo);margin-top:4px}' +
      '#ah-root .up{color:var(--red)}#ah-root .dn{color:var(--green)}#ah-root .flat{color:var(--tlo)}' +
      '#ah-root .ah-section{margin-top:16px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px 14px}' +
      '#ah-root .ah-section h4{margin:0 0 8px;font-size:11px;color:var(--gold);letter-spacing:1px}' +
      '#ah-root .ah-txf{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}' +
      '#ah-root .ah-cell{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center}' +
      '#ah-root .ah-cell .k{font-size:9px;color:var(--tlo)}#ah-root .ah-cell .v{font-size:13px;font-weight:700;margin-top:3px;color:var(--thi)}' +
      '#ah-root table.ah-tbl{width:100%;border-collapse:collapse;font-size:11px}' +
      '#ah-root table.ah-tbl th,#ah-root table.ah-tbl td{padding:6px 6px;border-bottom:1px solid var(--border);text-align:right}' +
      '#ah-root table.ah-tbl th:first-child,#ah-root table.ah-tbl td:first-child,' +
      '#ah-root table.ah-tbl th:nth-child(2),#ah-root table.ah-tbl td:nth-child(2){text-align:left}' +
      '#ah-root table.ah-tbl th{color:var(--tlo);font-weight:600}' +
      '#ah-root tr.ah-row{cursor:pointer}#ah-root tr.ah-row:hover{background:var(--bg3)}' +
      '#ah-root .ah-note{font-size:9px;color:var(--tlo);line-height:1.65;margin-top:12px}' +
      '#ah-root .ah-loading,#ah-root .ah-err{font-size:11px;color:var(--tlo);padding:18px 0}' +
      '#ah-root .ah-err{color:var(--orange)}' +
      '#ah-root .ah-tone{font-size:12px;margin:8px 0 0;font-weight:700}' +
      '@media (max-width:900px){' +
        '#ah-root .ah-grid{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#ah-root .ah-txf{grid-template-columns:repeat(2,1fr)}' +
        '#view-afterhours.sv-panel{padding:16px}' +
      '}';
    document.head.appendChild(s);
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
          '<div class="ah-head"><div>' +
              '<div class="ah-kicker">STOCK TERMINAL · 5.0</div>' +
              '<div class="ah-title">盤後數據</div>' +
              '<div class="ah-sub" id="ah-sub">漲跌排行 · 夜盤 · 籌碼摘要</div>' +
          '</div><div class="ah-actions">' +
            '<button type="button" class="ah-btn" id="ah-refresh">↻ 重新整理</button>' +
            '<button type="button" class="ah-btn" id="ah-open-ovn">夜盤詳情</button>' +
            '<button type="button" class="ah-btn primary" data-shell-back>← 圖表</button>' +
          '</div></div>' +
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

    var flat = st.unchanged != null ? st.unchanged : (st.flat || 0);
    var breadthSeg = V ? V.segBar(st.up, flat, st.down) : '';
    var scoreMeter = (V && bd.score != null) ? V.scoreMeter(bd.score) : '';
    var cards =
      '<div class="ah-card"><div class="k">台指期夜盤</div>' +
        '<div class="v ' + twCls(txf && txf.changePct) + '">' + (txf ? fmtN(txf.price) : '—') + '</div>' +
        '<div class="s ' + twCls(txf && txf.changePct) + '">' + pct(txf && txf.changePct) + '</div></div>' +
      '<div class="ah-card"><div class="k">夜盤振幅</div>' +
        '<div class="v">' + (txf && txf.ampRate != null ? txf.ampRate.toFixed(2) + '%' : '—') + '</div>' +
        '<div class="s">' + (txf ? (txf.sessionLabel || '夜盤') : '無資料') + '</div></div>' +
      '<div class="ah-card"><div class="k">漲跌家數（股票）</div>' +
        '<div class="v"><span class="up">' + fmtN(st.up) + '</span> / <span class="dn">' + fmtN(st.down) + '</span></div>' +
        '<div class="s">淨 ' + (st.net != null ? ((st.net >= 0 ? '+' : '') + st.net) : '—') + '</div>' +
        breadthSeg + '</div>' +
      '<div class="ah-card"><div class="k">大盤體質</div>' +
        '<div class="v">' + (bd.score != null ? bd.score : '—') + '</div>' +
        '<div class="s">' + (bd.summary || '量能／法人／融資／估值') + '</div>' + scoreMeter + '</div>';

    var txfBlock = '<div class="ah-section"><h4>📉 台指期夜盤（主訊號）</h4>';
    if (!txf) {
      txfBlock += '<div class="ah-err">暫無夜盤資料（請確認 /txf）。日盤時段仍可顯示最近夜盤 OHLC。</div></div>';
    } else {
      txfBlock +=
        '<div class="ah-tone ' + twCls(txf.changePct) + '">' + toneTxf(txf.changePct, txf.ampRate) + '</div>' +
        '<div class="ah-txf" style="margin-top:10px">' +
          '<div class="ah-cell"><div class="k">開</div><div class="v">' + fmtN(txf.open) + '</div></div>' +
          '<div class="ah-cell"><div class="k">高</div><div class="v">' + fmtN(txf.high) + '</div></div>' +
          '<div class="ah-cell"><div class="k">低</div><div class="v">' + fmtN(txf.low) + '</div></div>' +
          '<div class="ah-cell"><div class="k">昨收</div><div class="v">' + fmtN(txf.prevClose) + '</div></div>' +
        '</div>' +
        '<div class="ah-note">來源 ' + (txf.source || '—') +
          (txf.volume != null ? ' · 量 ' + fmtN(txf.volume) : '') +
          '。夜盤%優先作為隔日開盤方向參考；高振幅易跳空。</div></div>';
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
      '<div class="ah-section"><h4>🔭 個股期領先（市值前十大）· ' + sess + '</h4>' +
      (rows
        ? '<table class="ah-tbl"><tr><th>代號</th><th>名稱</th><th>期價</th><th>期%</th><th>現%</th><th>領先</th></tr>' +
          rows + '</table>'
        : '<div class="ah-err">個股期資料暫缺</div>') +
      '<div class="ah-note">領先 = 期% − 現%。正值＝期貨越強、隔日可能續強（夜盤量淺，作方向參考）。點列載入線型。</div></div>';

    var inst = mf.inst;
    var to = (mf.turnover || []).filter(function (x) { return x.amount != null; });
    var latestAmt = to.length ? to[to.length - 1].amount : null;
    var instBlock = '<div class="ah-section"><h4>💰 盤後籌碼摘要</h4>';
    if (!inst && latestAmt == null) {
      instBlock += '<div class="ah-err">資金流尚未更新（FMTQIK/BFI82U 多為收盤後發布）。</div></div>';
    } else {
      var total = inst ? ((inst.foreign || 0) + (inst.trust || 0) + (inst.dealer || 0)) : null;
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
      instBlock += '<div class="ah-txf">' +
        '<div class="ah-cell"><div class="k">成交金額</div><div class="v">' + yi(latestAmt) + '</div></div>' +
        '<div class="ah-cell"><div class="k">外資</div><div class="v ' + twCls(inst && inst.foreign) + '">' + fyi(inst && inst.foreign) + '</div></div>' +
        '<div class="ah-cell"><div class="k">投信</div><div class="v ' + twCls(inst && inst.trust) + '">' + fyi(inst && inst.trust) + '</div></div>' +
        '<div class="ah-cell"><div class="k">合計</div><div class="v ' + twCls(total) + '">' + fyi(total) + '</div></div>' +
        '</div>' + instBars + totalChip +
        '<div class="ah-note">法人日 ' + ((inst && inst.date) || mf.date || '—') +
          '。完整儀表板可用工具列「籌碼基本面 → 資金流」。</div></div>';
    }

    var movers = pack.movers || {};
    var gain = movers.gainers || movers.up || [];
    var lose = movers.losers || movers.down || [];
    function mvTbl(list, title, cls) {
      var h = '<div class="ah-section" style="margin:0"><h4>' + title + '</h4>';
      if (!list.length) return h + '<div class="ah-err">尚無排行</div></div>';
      var slice = list.slice(0, 12);
      var maxAbs = 0;
      slice.forEach(function (r) {
        if (r.changePct != null && isFinite(r.changePct)) maxAbs = Math.max(maxAbs, Math.abs(r.changePct));
      });
      h += '<table class="ah-tbl"><tr><th>名次</th><th>代號</th><th>名稱</th><th>漲跌幅</th></tr>';
      slice.forEach(function (r, i) {
        var lim = V ? V.limitChip(r.changePct) : '';
        var bar = V ? V.rowBar(r.changePct, maxAbs) : '';
        h += '<tr class="ah-row" data-code="' + (r.code || '') + '"><td>' + (i + 1) +
          '</td><td style="color:var(--gold);font-weight:700">' + (r.code || '') +
          '</td><td>' + (r.name || '') + '</td><td class="' + (cls || twCls(r.changePct)) + '">' +
          pct(r.changePct) + lim + bar + '</td></tr>';
      });
      return h + '</table></div>';
    }
    var mvBlock =
      '<div class="ah-section"><h4>📈 漲跌排行（官方盤後）</h4>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">' +
        mvTbl(gain, '漲幅排行', 'up') + mvTbl(lose, '跌幅排行', 'dn') +
      '</div><div class="ah-note">來源 /movers · 點列開啟圖表。權證已過濾。</div></div>';

    body.innerHTML =
      '<div class="ah-grid">' + cards + '</div>' +
      mvBlock + txfBlock + futBlock + instBlock +
      '<div class="ah-note">⚠ 僅供參考、非投資建議。資料源：TAIFEX MIS / TWSE OpenData。</div>';

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
      jget('/movers?n=12')
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

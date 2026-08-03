/* ============================================================================
 * pulse_v5.js  —  Stock Terminal 5.0 Stage 4：TW Pulse 市場脈動總覽
 * ----------------------------------------------------------------------------
 * 5 秒掌握盤勢：指數 + 台指期 + 廣度 + 籌碼 + 法人榜 + 類股強弱。
 * 皆既有端點，client 端 Promise.all 組合（無新 scraper）。
 *   GET /twindex /txf /breadth /marketflow
 *   GET /inst-rank?who=foreign&side=buy|sell&n=5
 *   GET /sectors?mkt=TW
 * 掛載：#mount-pulse；側欄「脈動」
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    if ($('pulse-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'pulse-v5-css';
    s.textContent =
      '#view-pulse.sv-panel{max-width:1120px;padding:18px 22px 28px}' +
      '#pl-root{font-family:\'JetBrains Mono\',monospace;color:var(--text)}' +
      '#pl-root .pl-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}' +
      '#pl-root .pl-kicker{font-size:10px;color:var(--gold);letter-spacing:2px;margin-bottom:4px}' +
      '#pl-root .pl-title{font-family:\'Noto Serif TC\',serif;font-size:26px;font-weight:700;color:var(--thi)}' +
      '#pl-root .pl-sub{font-size:11px;color:var(--tlo);margin-top:4px}' +
      '#pl-root .pl-tone{margin-top:6px;font-size:13px;font-weight:700}' +
      '#pl-root .pl-actions{display:flex;gap:8px;flex-wrap:wrap}' +
      '#pl-root .pl-btn{padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;font-family:\'JetBrains Mono\',monospace;cursor:pointer}' +
      '#pl-root .pl-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#pl-root .pl-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#pl-root .pl-btn.primary:hover{background:#FBBF24}' +
      '#pl-root .pl-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}' +
      '#pl-root .pl-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px 14px;min-height:76px}' +
      '#pl-root .pl-card .k{font-size:9px;color:var(--tlo);letter-spacing:1px;margin-bottom:6px}' +
      '#pl-root .pl-card .v{font-size:20px;font-weight:700;color:var(--thi);line-height:1.15}' +
      '#pl-root .pl-card .s{font-size:10px;color:var(--tlo);margin-top:4px}' +
      '#pl-root .up{color:var(--red)}#pl-root .dn{color:var(--green)}#pl-root .flat{color:var(--tlo)}' +
      '#pl-root .pl-sec{margin-top:12px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px 14px}' +
      '#pl-root .pl-sec h4{margin:0 0 8px;font-size:11px;color:var(--gold);letter-spacing:1px;display:flex;justify-content:space-between;align-items:center}' +
      '#pl-root .pl-sec h4 a,#pl-root .pl-link{color:var(--cyan);cursor:pointer;font-size:10px;font-weight:600;text-decoration:none}' +
      '#pl-root .pl-sec h4 a:hover{color:var(--gold)}' +
      '#pl-root .pl-bar{display:flex;height:14px;border-radius:4px;overflow:hidden;background:var(--bg);margin:6px 0}' +
      '#pl-root .pl-bar .su{background:var(--red)}#pl-root .pl-bar .sf{background:#334155}#pl-root .pl-bar .sd{background:var(--green)}' +
      '#pl-root .pl-bar-lbl{display:flex;justify-content:space-between;font-size:10px;color:var(--tlo)}' +
      '#pl-root .pl-two{display:grid;grid-template-columns:1fr 1fr;gap:12px}' +
      '#pl-root table{width:100%;border-collapse:collapse;font-size:11px}' +
      '#pl-root th,#pl-root td{padding:5px 6px;border-bottom:1px solid var(--border);text-align:right}' +
      '#pl-root th:first-child,#pl-root td:first-child,#pl-root th:nth-child(2),#pl-root td:nth-child(2){text-align:left}' +
      '#pl-root th{color:var(--tlo);font-weight:600}' +
      '#pl-root tr.pl-row{cursor:pointer}#pl-root tr.pl-row:hover{background:var(--bg3)}' +
      '#pl-root .pl-chips{display:flex;flex-wrap:wrap;gap:6px}' +
      '#pl-root .pl-chip{padding:7px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg);' +
        'cursor:pointer;min-width:88px;text-align:center}' +
      '#pl-root .pl-chip:hover{border-color:var(--bhi)}' +
      '#pl-root .pl-chip .nm{font-size:10px;color:var(--thi);font-weight:700}' +
      '#pl-root .pl-chip .pc{font-size:13px;font-weight:700;margin-top:2px}' +
      '#pl-root .pl-inst{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}' +
      '#pl-root .pl-cell{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center}' +
      '#pl-root .pl-cell .k{font-size:9px;color:var(--tlo)}#pl-root .pl-cell .v{font-size:14px;font-weight:700;margin-top:3px}' +
      '#pl-root .pl-note{font-size:9px;color:var(--tlo);line-height:1.65;margin-top:12px}' +
      '#pl-root .pl-loading{font-size:11px;color:var(--tlo);padding:20px 0}' +
      '@media (max-width:900px){' +
        '#pl-root .pl-grid{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#pl-root .pl-two,#pl-root .pl-inst{grid-template-columns:1fr}' +
      '}';
    document.head.appendChild(s);
  }

  function tw(p) {
    if (p == null || p !== p) return 'flat';
    return p > 0 ? 'up' : p < 0 ? 'dn' : 'flat';
  }
  function pct(p) {
    if (p == null || p !== p) return '—';
    return (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
  }
  function fmt(v, d) {
    if (v == null || !isFinite(v)) return '—';
    d = d == null ? 0 : d;
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
  }
  function yi(v) { return v == null ? '—' : (v / 1e8).toFixed(0) + ' 億'; }
  function fyi(v) {
    if (v == null) return '—';
    return (v >= 0 ? '+' : '') + (v / 1e8).toFixed(0) + ' 億';
  }
  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }
  function goRoute(id) {
    if (window.ShellV5) window.ShellV5.go(id);
  }
  function openChart(code) {
    if (code && typeof loadSym === 'function') {
      loadSym(code, 'TW');
      goRoute('chart');
    }
  }

  function normalizeNight(d) {
    if (!d || !d.ok) return null;
    var n = d.night;
    if (!n || n.price == null) {
      if (d.price != null && (d.session === 'night' || d.ampRate != null)) n = d;
      else return null;
    }
    var cp = n.changePct;
    if (cp == null && n.prevClose > 0) cp = (n.price - n.prevClose) / n.prevClose * 100;
    return { price: n.price, changePct: cp, ampRate: n.ampRate, source: n.source || d.source };
  }

  function toneLine(txf, bd) {
    var parts = [];
    var cp = txf && txf.changePct;
    var ar = bd && bd.stocks && bd.stocks.advRatio;
    var score = bd && bd.score;
    if (cp != null) {
      if (cp <= -1.5) parts.push('夜盤偏空');
      else if (cp <= -0.5) parts.push('夜盤偏弱');
      else if (cp >= 1.5) parts.push('夜盤偏多');
      else if (cp >= 0.5) parts.push('夜盤偏強');
      else parts.push('夜盤中性');
    }
    if (ar != null) {
      if (ar >= 0.65) parts.push('廣度偏多');
      else if (ar <= 0.35) parts.push('廣度偏空');
      else parts.push('廣度糾結');
    }
    if (score != null) parts.push('體質 ' + score);
    return parts.length ? parts.join(' · ') : '資料彙整中';
  }

  function sectorPick(sectors) {
    // 排除大盤指數名，取漲跌幅極端
    var skip = /加權|櫃買|寶島|公司治理|中型|電子工業$|未含/;
    var list = (sectors || []).filter(function (s) {
      return s && s.name && s.changePct != null && !skip.test(s.name);
    });
    list.sort(function (a, b) { return b.changePct - a.changePct; });
    return { up: list.slice(0, 6), dn: list.slice(-6).reverse() };
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-pulse');
    if (!panel) return null;
    var mount = $('mount-pulse');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-pulse';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('pl-root')) {
      mount.innerHTML =
        '<div id="pl-root">' +
          '<div class="pl-head"><div>' +
            '<div class="pl-kicker">STOCK TERMINAL · 5.0-S4</div>' +
            '<div class="pl-title">市場脈動</div>' +
            '<div class="pl-sub" id="pl-sub">指數 · 夜盤 · 廣度 · 籌碼 · 類股</div>' +
            '<div class="pl-tone" id="pl-tone">—</div>' +
          '</div><div class="pl-actions">' +
            '<button type="button" class="pl-btn" id="pl-refresh">↻ 重新整理</button>' +
            '<button type="button" class="pl-btn" data-go="breadth">廣度</button>' +
            '<button type="button" class="pl-btn" data-go="afterhours">盤後</button>' +
            '<button type="button" class="pl-btn primary" data-go="chart">圖表</button>' +
          '</div></div>' +
          '<div id="pl-body" class="pl-loading">載入脈動…</div>' +
        '</div>';
      var r = $('pl-refresh');
      if (r) r.onclick = function () { refresh(); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () { goRoute(b.getAttribute('data-go')); };
      });
    }
    return $('pl-body');
  }

  function render(pack) {
    var body = ensureMount();
    if (!body) return;
    var idx = (pack.tw && pack.tw.indices) || {};
    var t00 = idx.t00 || {}, o00 = idx.o00 || {};
    var txf = pack.txf;
    var bd = pack.bd || {};
    var st = bd.stocks || {};
    var mf = pack.mf || {};
    var buy = (pack.buy && pack.buy.list) || [];
    var sell = (pack.sell && pack.sell.list) || [];
    var sec = sectorPick((pack.sec && pack.sec.sectors) || []);

    var sub = $('pl-sub');
    if (sub) {
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (bd.date ? ' · 廣度日 ' + bd.date : '') +
        (pack.buy && pack.buy.date ? ' · 法人日 ' + pack.buy.date : '');
    }
    var toneEl = $('pl-tone');
    if (toneEl) {
      toneEl.className = 'pl-tone ' + tw(txf && txf.changePct);
      toneEl.textContent = toneLine(txf, bd);
    }

    var up = st.up, dn = st.down, flat = st.unchanged || 0;
    var sum = (up || 0) + (dn || 0) + flat;
    var pu = sum ? 100 * (up || 0) / sum : 0;
    var pf = sum ? 100 * flat / sum : 0;
    var pd = sum ? 100 * (dn || 0) / sum : 0;

    var cards =
      '<div class="pl-card"><div class="k">加權指數</div><div class="v">' + fmt(t00.price, 2) + '</div>' +
        '<div class="s ' + tw(t00.changePct) + '">' + pct(t00.changePct) + '</div></div>' +
      '<div class="pl-card"><div class="k">櫃買指數</div><div class="v">' + fmt(o00.price, 2) + '</div>' +
        '<div class="s ' + tw(o00.changePct) + '">' + pct(o00.changePct) + '</div></div>' +
      '<div class="pl-card"><div class="k">台指期夜盤</div><div class="v ' + tw(txf && txf.changePct) + '">' +
        (txf ? fmt(txf.price) : '—') + '</div>' +
        '<div class="s ' + tw(txf && txf.changePct) + '">' + pct(txf && txf.changePct) +
        (txf && txf.ampRate != null ? ' · 振幅 ' + txf.ampRate.toFixed(2) + '%' : '') + '</div></div>' +
      '<div class="pl-card"><div class="k">大盤體質</div><div class="v">' + (bd.score != null ? bd.score : '—') + '</div>' +
        '<div class="s">' + (bd.summary || '量能／法人／融資／估值') + '</div></div>';

    var breadth =
      '<div class="pl-sec"><h4>廣度（股票） <a data-go="breadth">詳情 →</a></h4>' +
      '<div class="pl-bar-lbl"><span class="up">上漲 ' + fmt(up) + '</span><span class="flat">持平 ' + fmt(flat) +
        '</span><span class="dn">下跌 ' + fmt(dn) + '</span></div>' +
      '<div class="pl-bar"><div class="su" style="width:' + pu.toFixed(2) + '%"></div>' +
        '<div class="sf" style="width:' + pf.toFixed(2) + '%"></div>' +
        '<div class="sd" style="width:' + pd.toFixed(2) + '%"></div></div>' +
      '<div class="pl-bar-lbl" style="margin-top:6px"><span>上漲比 ' +
        (st.advRatio != null ? (st.advRatio * 100).toFixed(1) + '%' : '—') +
        '</span><span>淨 ' + (st.net != null ? ((st.net >= 0 ? '+' : '') + st.net) : '—') + '</span></div></div>';

    var inst = mf.inst;
    var to = (mf.turnover || []).filter(function (x) { return x.amount != null; });
    var latest = to.length ? to[to.length - 1].amount : null;
    var total = inst ? ((inst.foreign || 0) + (inst.trust || 0) + (inst.dealer || 0)) : null;
    var flow =
      '<div class="pl-sec"><h4>籌碼摘要</h4><div class="pl-inst">' +
        '<div class="pl-cell"><div class="k">成交金額</div><div class="v">' + yi(latest) + '</div></div>' +
        '<div class="pl-cell"><div class="k">外資</div><div class="v ' + tw(inst && inst.foreign) + '">' + fyi(inst && inst.foreign) + '</div></div>' +
        '<div class="pl-cell"><div class="k">投信</div><div class="v ' + tw(inst && inst.trust) + '">' + fyi(inst && inst.trust) + '</div></div>' +
        '<div class="pl-cell"><div class="k">合計</div><div class="v ' + tw(total) + '">' + fyi(total) + '</div></div>' +
      '</div></div>';

    function rankTable(list, title) {
      var rows = (list || []).slice(0, 5).map(function (r) {
        var v = r.foreign != null ? r.foreign : r.net;
        return '<tr class="pl-row" data-code="' + (r.code || '') + '">' +
          '<td style="color:var(--gold);font-weight:700">' + (r.code || '') + '</td>' +
          '<td>' + (r.name || '') + '</td>' +
          '<td class="' + tw(v) + '">' + fyi(v) + '</td>' +
          '<td>' + (r.streak ? r.streak + '天' : '—') + '</td></tr>';
      }).join('');
      return '<div class="pl-sec" style="margin:0"><h4>' + title + '</h4>' +
        (rows
          ? '<table><tr><th>代號</th><th>名稱</th><th>外資</th><th>連續</th></tr>' + rows + '</table>'
          : '<div class="pl-note">暫無排行</div>') + '</div>';
    }

    var ranks = '<div class="pl-two">' + rankTable(buy, '外資買超 Top') + rankTable(sell, '外資賣超 Top') + '</div>';

    function chips(arr, label) {
      var html = '<div class="pl-sec"><h4>' + label + '</h4><div class="pl-chips">';
      if (!arr.length) html += '<div class="pl-note">類股資料暫缺</div>';
      arr.forEach(function (s) {
        html += '<div class="pl-chip" title="' + s.name + '">' +
          '<div class="nm">' + s.name + '</div>' +
          '<div class="pc ' + tw(s.changePct) + '">' + pct(s.changePct) + '</div></div>';
      });
      html += '</div></div>';
      return html;
    }

    body.innerHTML =
      '<div class="pl-grid">' + cards + '</div>' +
      breadth + flow + ranks +
      chips(sec.up, '類股強勢') + chips(sec.dn, '類股弱勢') +
      '<div class="pl-note">脈動為總覽；細節進廣度／盤後／工具列資金流。點排行載入線型。⚠ 非投資建議。</div>';

    body.querySelectorAll('[data-go]').forEach(function (a) {
      a.onclick = function (e) { e.preventDefault(); goRoute(a.getAttribute('data-go')); };
    });
    body.querySelectorAll('tr.pl-row').forEach(function (el) {
      el.onclick = function () { openChart(el.getAttribute('data-code')); };
    });
  }

  function refresh() {
    var body = ensureMount();
    if (!body) return;
    body.innerHTML = '<div class="pl-loading">載入脈動…</div>';
    Promise.all([
      jget('/twindex'),
      jget('/txf'),
      jget('/breadth'),
      jget('/marketflow'),
      jget('/inst-rank?who=foreign&side=buy&n=5'),
      jget('/inst-rank?who=foreign&side=sell&n=5'),
      jget('/sectors?mkt=TW')
    ]).then(function (arr) {
      render({
        tw: arr[0],
        txf: normalizeNight(arr[1]),
        bd: arr[2] || {},
        mf: arr[3] || {},
        buy: arr[4],
        sell: arr[5],
        sec: arr[6]
      });
    });
  }

  function activate() {
    ensureMount();
    refresh();
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') refresh();
    }, 50000);
  }

  window.PulseV5 = { activate: activate, refresh: refresh };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'pulse') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 200); });
  else setTimeout(boot, 200);
})();

/* ============================================================================
 * pulse_v5.js  —  Stock Terminal 5.0：TW Pulse 市場脈動情報
 * ----------------------------------------------------------------------------
 * Merge：tw-pulse-terminal（Antigravity scratch）之「因子帳本 + 雙軌健康／風險 +
 * 資料完整度」UX → 綁定真實後端 GET /pulse（pulse_intel.py），禁止 mock 分數。
 *
 * 資料：
 *   GET /pulse              → total/health/risk + factors + snapshot
 *   GET /inst-rank …        → 外資買賣超 Top（附帶）
 *   背景預熱 /breadth /sectors → 提高完整度
 *
 * 掛載：#mount-pulse；側欄「脈動」
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var lastPack = null;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    if ($('pulse-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'pulse-v5-css';
    s.textContent =
      '#view-pulse.sv-panel{max-width:1180px;padding:18px 22px 32px}' +
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
      '#pl-root .pl-three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}' +
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
      /* ── Intel（tw-pulse merge）── */
      '#pl-root .pl-intel{display:grid;grid-template-columns:1.1fr 1fr;gap:12px;margin-top:4px}' +
      '#pl-root .pl-gauge-wrap{display:flex;align-items:center;gap:18px;flex-wrap:wrap}' +
      '#pl-root .pl-gauge{width:132px;height:132px;border-radius:50%;' +
        'background:conic-gradient(var(--gold) var(--pl-deg,0%), rgba(245,197,24,.12) 0);' +
        'display:flex;align-items:center;justify-content:center;flex-shrink:0;position:relative}' +
      '#pl-root .pl-gauge::before{content:\'\';position:absolute;inset:10px;border-radius:50%;background:var(--bg2)}' +
      '#pl-root .pl-gauge-inner{position:relative;z-index:1;text-align:center}' +
      '#pl-root .pl-gauge-inner .big{font-size:34px;font-weight:800;color:var(--thi);line-height:1}' +
      '#pl-root .pl-gauge-inner .tag{display:inline-block;margin-top:6px;padding:2px 8px;border-radius:999px;' +
        'font-size:10px;font-weight:700;background:var(--gold-s);color:var(--gold);border:1px solid var(--gold-m)}' +
      '#pl-root .pl-mini{display:grid;grid-template-columns:1fr 1fr;gap:8px;flex:1;min-width:200px}' +
      '#pl-root .pl-mini .m{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px}' +
      '#pl-root .pl-mini .m .k{font-size:9px;color:var(--tlo);letter-spacing:.5px}' +
      '#pl-root .pl-mini .m .v{font-size:18px;font-weight:800;margin-top:4px;color:var(--thi)}' +
      '#pl-root .pl-mini .m .l{font-size:10px;margin-top:3px;font-weight:700}' +
      '#pl-root .pl-comp{height:8px;border-radius:4px;background:var(--bg3);overflow:hidden;margin-top:8px}' +
      '#pl-root .pl-comp > i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan),var(--gold));border-radius:4px}' +
      '#pl-root .pl-fac{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:8px}' +
      '#pl-root .pl-fac .hd{display:flex;justify-content:space-between;gap:8px;font-size:11px;font-weight:700;color:var(--thi)}' +
      '#pl-root .pl-fac .ds{font-size:10px;color:var(--tlo);line-height:1.55;margin-top:4px}' +
      '#pl-root .pl-fac .sc-pos{color:var(--red)}#pl-root .pl-fac .sc-risk{color:var(--cyan)}#pl-root .pl-fac .sc-pend{color:var(--tlo)}' +
      '#pl-root .pl-col h4 .cnt{color:var(--tlo);font-weight:600}' +
      '#pl-root .pl-col{max-height:420px;overflow:auto;padding-right:2px}' +
      '@media (max-width:980px){' +
        '#pl-root .pl-grid{grid-template-columns:repeat(2,minmax(0,1fr))}' +
        '#pl-root .pl-intel,#pl-root .pl-two,#pl-root .pl-three,#pl-root .pl-inst{grid-template-columns:1fr}' +
      '}';
    document.head.appendChild(s);
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
            '<div class="pl-kicker">STOCK TERMINAL · PULSE INTEL</div>' +
            '<div class="pl-title">市場脈動</div>' +
            '<div class="pl-sub" id="pl-sub">健康度 · 風險 · 因子帳本 · 廣度籌碼</div>' +
            '<div class="pl-tone" id="pl-tone">—</div>' +
          '</div><div class="pl-actions">' +
            '<button type="button" class="pl-btn" id="pl-refresh">↻ 重新整理</button>' +
            '<button type="button" class="pl-btn" data-go="breadth">廣度</button>' +
            '<button type="button" class="pl-btn" data-go="heat">熱力</button>' +
            '<button type="button" class="pl-btn" data-go="afterhours">盤後</button>' +
            '<button type="button" class="pl-btn primary" data-go="chart">圖表</button>' +
          '</div></div>' +
          '<div id="pl-body" class="pl-loading">載入脈動情報…</div>' +
        '</div>';
      var r = $('pl-refresh');
      if (r) r.onclick = function () { refresh(true); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () { goRoute(b.getAttribute('data-go')); };
      });
    }
    return $('pl-body');
  }

  function factorCol(title, cls, list, empty) {
    var html = '<div class="pl-sec pl-col"><h4>' + title + ' <span class="cnt">(' + (list || []).length + ')</span></h4>';
    if (!list || !list.length) {
      html += '<div class="pl-note">' + empty + '</div></div>';
      return html;
    }
    list.forEach(function (f) {
      var sc = f.score;
      var scCls = cls;
      var scTxt;
      if (cls === 'sc-pos') scTxt = (sc >= 0 ? '+' : '') + Number(sc).toFixed(1) + '分';
      else if (cls === 'sc-risk') scTxt = Number(sc).toFixed(1) + '分';
      else scTxt = '不計分';
      html += '<div class="pl-fac"><div class="hd"><span>' + (f.id || '') + '. ' + (f.name || '') +
        '</span><span class="' + scCls + '">' + scTxt + '</span></div>' +
        '<div class="ds">' + (f.description || '') + '</div></div>';
    });
    html += '</div>';
    return html;
  }

  function renderIntel(p) {
    var total = p.totalScore;
    var deg = (total != null ? Math.max(0, Math.min(100, total)) : 0) * 3.6;
    var health = p.healthScore;
    var risk = p.riskScore;
    var comp = p.dataCompleteness != null ? p.dataCompleteness : 0;

    return '' +
      '<div class="pl-intel">' +
        '<div class="pl-sec" style="margin:0">' +
          '<h4>市場脈動總覽 <span class="cnt">' + (p.model || 'tw-pulse-intel') + '</span></h4>' +
          '<div class="pl-gauge-wrap">' +
            '<div class="pl-gauge" style="--pl-deg:' + deg.toFixed(1) + 'deg">' +
              '<div class="pl-gauge-inner">' +
                '<div class="big">' + (total != null ? Number(total).toFixed(1) : '—') + '</div>' +
                '<div class="tag">' + (p.statusText || '—') + '</div>' +
              '</div>' +
            '</div>' +
            '<div class="pl-mini">' +
              '<div class="m"><div class="k">市場健康度</div><div class="v">' +
                (health != null ? Number(health).toFixed(1) : '—') +
                ' <span style="font-size:10px;color:var(--tlo)">/100</span></div>' +
                '<div class="l" style="color:var(--gold)">' + (p.healthLabel || '') + '</div></div>' +
              '<div class="m"><div class="k">市場風險度</div><div class="v">' +
                (risk != null ? Number(risk).toFixed(1) : '—') +
                ' <span style="font-size:10px;color:var(--tlo)">/100</span></div>' +
                '<div class="l" style="color:var(--cyan)">' + (p.riskLabel || '') + '</div></div>' +
              '<div class="m"><div class="k">正面因素得分</div><div class="v up">' +
                (p.positiveFactorScore != null ? Number(p.positiveFactorScore).toFixed(1) : '—') +
                '</div><div class="l" style="color:var(--tlo)">已計 ' +
                ((p.positiveFactors || []).length) + ' 項</div></div>' +
              '<div class="m"><div class="k">資料完整度</div><div class="v">' +
                (comp != null ? Number(comp).toFixed(0) + '%' : '—') + '</div>' +
                '<div class="l" style="color:var(--tlo)">可用 ' +
                (p.datasetsOk != null ? p.datasetsOk : '—') + '/' +
                (p.datasetsTotal != null ? p.datasetsTotal : '—') + '</div>' +
                '<div class="pl-comp"><i style="width:' + comp + '%"></i></div></div>' +
            '</div>' +
          '</div>' +
          (p.summary ? '<div class="pl-note" style="margin-top:10px">' + p.summary + '</div>' : '') +
        '</div>' +
        '<div class="pl-sec" style="margin:0">' +
          '<h4>體質支柱（大盤評分）</h4>' +
          pillarRows(p.marketRows || []) +
          '<div class="pl-note">健康度沿用伺服器 _score_tw_market（量能／法人／融資／估值）；' +
          '風險由因子帳本推導。缺資料進「尚未納入」不灌分。</div>' +
        '</div>' +
      '</div>' +
      '<div class="pl-three">' +
        factorCol('正面因素', 'sc-pos', p.positiveFactors, '尚無正面因子（或資料不足）') +
        factorCol('風險因素', 'sc-risk', p.riskFactors, '尚未識別顯著風險因子') +
        factorCol('尚未納入評估', 'sc-pend', p.pendingFactors, '無 pending 項目') +
      '</div>';
  }

  function pillarRows(rows) {
    if (!rows.length) return '<div class="pl-note">體質支柱尚未就緒 — 開啟盤後／廣度可預熱資料。</div>';
    var html = '<table><tr><th>項目</th><th>數值</th><th>評分</th></tr>';
    rows.forEach(function (r) {
      html += '<tr><td>' + (r.k || '') + '</td><td>' + (r.v || '—') + '</td><td>' +
        (r.score != null ? Number(r.score).toFixed(1) : '—') + '</td></tr>';
    });
    html += '</table>';
    return html;
  }

  function render(pack) {
    var body = ensureMount();
    if (!body) return;
    lastPack = pack;
    var p = pack.pulse || {};
    var snap = p.snapshot || {};
    var t00 = snap.t00 || (p.indices && p.indices.t00) || {};
    var o00 = snap.o00 || (p.indices && p.indices.o00) || {};
    var txf = snap.txf || p.txf || {};
    var st = snap.stocks || p.stocks || {};
    var inst = (snap.inst) || {};
    var mfInst = (p.marketflow && p.marketflow.inst) || p.inst || {};
    var foreign = inst.foreign != null ? inst.foreign : mfInst.foreign;
    var trust = inst.trust != null ? inst.trust : mfInst.trust;
    var dealer = inst.dealer != null ? inst.dealer : mfInst.dealer;
    var totalYi = inst.totalYi;
    if (totalYi == null && (foreign != null || trust != null || dealer != null)) {
      totalYi = ((foreign || 0) + (trust || 0) + (dealer || 0)) / 1e8;
    }

    var buy = (pack.buy && pack.buy.list) || [];
    var sell = (pack.sell && pack.sell.list) || [];
    var hot = snap.sectorsHot || [];
    var cold = snap.sectorsCold || [];

    var sub = $('pl-sub');
    if (sub) {
      sub.textContent = '更新 ' + new Date().toLocaleTimeString('zh-TW') +
        (p.date ? ' · 廣度日 ' + p.date : '') +
        (pack.buy && pack.buy.date ? ' · 法人日 ' + pack.buy.date : '') +
        (p.updatedAt ? ' · ' + p.updatedAt.replace('T', ' ') : '');
    }
    var toneEl = $('pl-tone');
    if (toneEl) {
      toneEl.className = 'pl-tone ' + tw(txf && txf.changePct);
      toneEl.textContent = p.tone || '資料彙整中';
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
        (txf && txf.price != null ? fmt(txf.price) : '—') + '</div>' +
        '<div class="s ' + tw(txf && txf.changePct) + '">' + pct(txf && txf.changePct) +
        (txf && txf.ampRate != null ? ' · 振幅 ' + Number(txf.ampRate).toFixed(2) + '%' : '') + '</div></div>' +
      '<div class="pl-card"><div class="k">大盤體質</div><div class="v">' +
        (p.healthScore != null ? Number(p.healthScore).toFixed(0) : '—') + '</div>' +
        '<div class="s">' + (p.healthLabel || p.summary || '量能／法人／融資／估值') + '</div></div>';

    var breadth =
      '<div class="pl-sec"><h4>廣度（股票） <a data-go="breadth">詳情 →</a></h4>' +
      '<div class="pl-bar-lbl"><span class="up">上漲 ' + fmt(up) + '</span><span class="flat">持平 ' + fmt(flat) +
        '</span><span class="dn">下跌 ' + fmt(dn) + '</span></div>' +
      '<div class="pl-bar"><div class="su" style="width:' + pu.toFixed(2) + '%"></div>' +
        '<div class="sf" style="width:' + pf.toFixed(2) + '%"></div>' +
        '<div class="sd" style="width:' + pd.toFixed(2) + '%"></div></div>' +
      '<div class="pl-bar-lbl" style="margin-top:6px"><span>上漲比 ' +
        (st.advRatio != null ? (st.advRatio * 100).toFixed(1) + '%' : '—') +
        '</span><span>淨 ' + (st.net != null ? ((st.net >= 0 ? '+' : '') + st.net) : '—') +
        (st.limitUp != null ? ' · 漲停 ' + st.limitUp : '') +
        (st.limitDown != null ? ' · 跌停 ' + st.limitDown : '') +
        '</span></div></div>';

    var to = ((p.marketflow && p.marketflow.turnover) || []).filter(function (x) { return x && x.amount != null; });
    var latest = to.length ? to[to.length - 1].amount : null;
    var flow =
      '<div class="pl-sec"><h4>籌碼摘要</h4><div class="pl-inst">' +
        '<div class="pl-cell"><div class="k">成交金額</div><div class="v">' + yi(latest) + '</div></div>' +
        '<div class="pl-cell"><div class="k">外資</div><div class="v ' + tw(foreign) + '">' + fyi(foreign) + '</div></div>' +
        '<div class="pl-cell"><div class="k">投信</div><div class="v ' + tw(trust) + '">' + fyi(trust) + '</div></div>' +
        '<div class="pl-cell"><div class="k">合計</div><div class="v ' + tw(totalYi) + '">' +
          (totalYi != null ? ((totalYi >= 0 ? '+' : '') + totalYi.toFixed(0) + ' 億') : '—') + '</div></div>' +
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
      var html = '<div class="pl-sec"><h4>' + label + ' <a data-go="heat">熱力 →</a></h4><div class="pl-chips">';
      if (!arr.length) html += '<div class="pl-note">類股資料暫缺（開啟熱力可預熱）</div>';
      arr.forEach(function (s) {
        html += '<div class="pl-chip" title="' + s.name + '">' +
          '<div class="nm">' + s.name + '</div>' +
          '<div class="pc ' + tw(s.changePct) + '">' + pct(s.changePct) + '</div></div>';
      });
      html += '</div></div>';
      return html;
    }

    body.innerHTML =
      renderIntel(p) +
      '<div class="pl-grid">' + cards + '</div>' +
      breadth + flow + ranks +
      chips(hot, '類股強勢') + chips(cold, '類股弱勢') +
      '<div class="pl-note">脈動情報合併自 tw-pulse-terminal 因子帳本 UX，分數由本機 /pulse 依真實欄位計算。' +
      '細節進廣度／熱力／盤後。點排行載入線型。⚠ 非投資建議。</div>';

    body.querySelectorAll('[data-go]').forEach(function (a) {
      a.onclick = function (e) { e.preventDefault(); goRoute(a.getAttribute('data-go')); };
    });
    body.querySelectorAll('tr.pl-row').forEach(function (el) {
      el.onclick = function () { openChart(el.getAttribute('data-code')); };
    });
  }

  function warmCaches() {
    // 背景預熱，提升下次 /pulse 完整度（不阻塞 UI）
    jget('/breadth');
    jget('/sectors?mkt=TW');
    jget('/marketflow');
  }

  function refresh(force) {
    var body = ensureMount();
    if (!body) return;
    body.innerHTML = '<div class="pl-loading">載入脈動情報…</div>';
    var q = force ? '/pulse?refresh=1' : '/pulse';
    Promise.all([
      jget(q),
      jget('/inst-rank?who=foreign&side=buy&n=5'),
      jget('/inst-rank?who=foreign&side=sell&n=5')
    ]).then(function (arr) {
      var pulse = arr[0];
      if (!pulse || !pulse.ok) {
        body.innerHTML = '<div class="pl-note">脈動情報載入失敗' +
          (pulse && pulse.error ? '：' + pulse.error : '（請確認 server 已重啟並含 /pulse）') +
          '。<button type="button" class="pl-btn" id="pl-retry">重試</button></div>';
        var retry = $('pl-retry');
        if (retry) retry.onclick = function () { refresh(true); };
        warmCaches();
        return;
      }
      render({ pulse: pulse, buy: arr[1], sell: arr[2] });
      // 完整度不足時預熱後再補一次
      if ((pulse.dataCompleteness != null && pulse.dataCompleteness < 85) || !pulse.breadthOk) {
        warmCaches();
        setTimeout(function () {
          if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') {
            jget('/pulse?refresh=1').then(function (p2) {
              if (p2 && p2.ok) render({ pulse: p2, buy: arr[1], sell: arr[2] });
            });
          }
        }, 2500);
      }
    });
  }

  function activate() {
    ensureMount();
    refresh(false);
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') refresh(false);
    }, 50000);
  }

  window.PulseV5 = { activate: activate, refresh: function () { refresh(true); }, last: function () { return lastPack; } };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'pulse') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'pulse') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 200); });
  else setTimeout(boot, 200);
})();

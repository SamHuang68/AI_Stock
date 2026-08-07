/* ============================================================================
 * heat_v5.js  —  Stock Terminal 5.0 Stage 5：類股熱力圖
 * ----------------------------------------------------------------------------
 * 資料：GET /sectors?mkt=TW|US（官方類股／SPDR）
 * 輔區：GET /focus 做多／做空焦點（背景載入，可點進圖表）
 * 掛載：#mount-heat；側欄「熱力」
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var state = { mkt: 'TW', sort: 'chg', last: null, focus: null };

  // 台股類股名 → 代表股（點格載入 K 線）
  var TW_PROXY = [
    { key: '半導體', code: '2330' },
    { key: '電子', code: '2317' },
    { key: '電腦', code: '2382' },
    { key: '光電', code: '3008' },
    { key: '通信', code: '2345' },
    { key: '通訊', code: '2345' },
    { key: '網通', code: '2345' },
    { key: '金融', code: '2882' },
    { key: '保險', code: '2882' },
    { key: '塑膠', code: '1301' },
    { key: '化學', code: '1303' },
    { key: '鋼鐵', code: '2002' },
    { key: '航運', code: '2603' },
    { key: '汽車', code: '2207' },
    { key: '食品', code: '1216' },
    { key: '電信', code: '2412' },
    { key: '生技', code: '1707' },
    { key: '醫療', code: '1707' },
    { key: '營建', code: '2548' },
    { key: '建材', code: '2548' },
    { key: '紡織', code: '1476' },
    { key: '橡膠', code: '2105' },
    { key: '電機', code: '2308' },
    { key: '機械', code: '2308' },
    { key: '水泥', code: '1101' },
    { key: '玻璃', code: '1802' },
    { key: '造紙', code: '1904' },
    { key: '觀光', code: '2707' },
    { key: '貿易', code: '2912' },
    { key: '百貨', code: '2912' },
    { key: '油電', code: '6505' },
    { key: '燃氣', code: '6505' },
    { key: '電器', code: '2377' },
    { key: '其他電子', code: '2357' },
    { key: '資訊服務', code: '2474' },
    { key: '文化創意', code: '8446' },
    { key: '農業科技', code: '1216' },
    { key: '數位雲端', code: '2454' }
  ];

  var SKIP_TW = /加權|櫃買|寶島|公司治理|中型100|未含金融|未含電子|報酬指數|全市場/;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    var s = $('heat-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'heat-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-heat.on){overflow:hidden!important}' +
      '#view-heat.sv-panel.on{max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-heat,#mount-heat.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#ht-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);width:100%;max-width:none;margin:0;min-width:0;' +
        'box-sizing:border-box;flex:1;min-height:0;display:flex;flex-direction:column}' +
      '#ht-root .ht-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#ht-root .ht-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#ht-root .ht-kicker{font-size:9px;color:var(--gold);letter-spacing:1.2px;margin:0;font-weight:700}' +
      '#ht-root .ht-title{font-family:\'Noto Serif TC\',serif;font-size:15px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#ht-root .ht-sub{font-size:9px;color:var(--tlo);margin:0}' +
      '#ht-root .ht-actions{display:flex;gap:4px;flex-wrap:nowrap;align-items:center;flex:0 0 auto}' +
      '#ht-root .ht-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;white-space:nowrap}' +
      '#ht-root .ht-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#ht-root .ht-btn.on{border-color:var(--gold);color:var(--gold);background:var(--gold-s)}' +
      '#ht-root .ht-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#ht-body{flex:1;min-height:0;display:grid;gap:4px;overflow:hidden;' +
        'grid-template-columns:minmax(0,1.55fr) minmax(260px,1fr);grid-template-rows:minmax(0,1fr)}' +
      '#ht-body .ht-main{min-height:0;display:flex;flex-direction:column;overflow:hidden;' +
        'background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px}' +
      '#ht-root .ht-legend{display:flex;align-items:center;gap:5px;font-size:8px;color:var(--tlo);margin:0 0 3px;flex:0 0 auto}' +
      '#ht-root .ht-legend i{display:inline-block;width:12px;height:8px;border-radius:2px}' +
      '#ht-root .ht-grid-wrap{flex:1;min-height:0;overflow:auto}' +
      '#ht-root .ht-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:3px;margin:0;' +
        'align-content:stretch;grid-auto-rows:minmax(56px,1fr);min-height:100%}' +
      '#ht-root .ht-cell{min-height:48px;padding:5px 4px;border-radius:4px;border:1px solid rgba(255,255,255,.06);' +
        'cursor:pointer;text-align:center;display:flex;flex-direction:column;justify-content:center;gap:1px;' +
        'transition:transform .1s,box-shadow .1s;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.55)}' +
      '#ht-root .ht-cell:hover{transform:scale(1.02);box-shadow:0 2px 10px rgba(0,0,0,.4);z-index:2}' +
      '#ht-root .ht-cell .nm{font-size:10px;font-weight:700;line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ht-root .ht-cell .pc{font-size:14px;font-weight:700}' +
      '#ht-root .ht-cell .px{font-size:8px;opacity:.8}' +
      '#ht-root .ht-focus-zone{min-height:0;display:flex;flex-direction:column;' +
        'background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;overflow:hidden}' +
      '#ht-root .ht-focus-zone > h4{margin:0 0 3px;font-size:10px;color:var(--gold);letter-spacing:.5px;flex:0 0 auto}' +
      '#ht-root .ht-focus-zone > #ht-focus{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#ht-root .ht-two{display:grid;grid-template-rows:1fr 1fr;gap:4px;flex:1;min-height:0;overflow:hidden}' +
      '#ht-root .ht-two > div{min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#ht-root .ht-list{flex:1;min-height:0;overflow:auto}' +
      '#ht-root .ht-row{display:flex;align-items:center;gap:5px;padding:2px 3px;border-bottom:1px solid var(--border);' +
        'cursor:pointer;font-size:10px}' +
      '#ht-root .ht-row:hover{background:var(--bg3)}' +
      '#ht-root .ht-row .code{color:var(--gold);font-weight:700;min-width:42px;font-size:9px}' +
      '#ht-root .ht-row .name{flex:1;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:9px}' +
      '#ht-root .up{color:var(--red)}#ht-root .dn{color:var(--green)}' +
      '#ht-root .ht-note{font-size:8px;color:var(--tlo);line-height:1.35;margin-top:2px;flex:0 0 auto}' +
      '#ht-root .ht-loading{font-size:10px;color:var(--tlo);padding:12px 0}' +
      '#ht-body.ht-loading{display:flex;align-items:center}';
  }

  function pctColor(pct, mkt) {
    var v = Math.min(Math.abs(pct || 0), 5) / 5;
    var a = 0.22 + v * 0.58;
    var isUp = pct >= 0;
    var upR = mkt === 'TW' ? 248 : 74, upG = mkt === 'TW' ? 113 : 222, upB = mkt === 'TW' ? 113 : 128;
    var dnR = mkt === 'TW' ? 74 : 248, dnG = mkt === 'TW' ? 222 : 113, dnB = mkt === 'TW' ? 128 : 113;
    return isUp
      ? 'rgba(' + upR + ',' + upG + ',' + upB + ',' + a.toFixed(2) + ')'
      : 'rgba(' + dnR + ',' + dnG + ',' + dnB + ',' + a.toFixed(2) + ')';
  }

  function twCls(p) {
    if (p == null || p !== p) return '';
    return p > 0 ? 'up' : p < 0 ? 'dn' : '';
  }
  function pct(p) {
    if (p == null || p !== p) return '—';
    return (p >= 0 ? '+' : '') + p.toFixed(2) + '%';
  }
  function fmt(v) {
    if (v == null || !isFinite(v)) return '—';
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 });
  }

  function proxyFor(name) {
    for (var i = 0; i < TW_PROXY.length; i++) {
      if (name.indexOf(TW_PROXY[i].key) >= 0) return TW_PROXY[i].code;
    }
    return null;
  }

  function filterSectors(list, mkt) {
    var rows = (list || []).filter(function (s) {
      if (!s || s.changePct == null || !s.name) return false;
      if (mkt === 'TW' && SKIP_TW.test(s.name)) return false;
      return true;
    });
    if (state.sort === 'name') {
      rows.sort(function (a, b) { return String(a.name).localeCompare(String(b.name), 'zh-TW'); });
    } else {
      rows.sort(function (a, b) { return b.changePct - a.changePct; });
    }
    return rows;
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-heat');
    if (!panel) return null;
    var mount = $('mount-heat');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-heat';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('ht-root')) {
      mount.innerHTML =
        '<div id="ht-root">' +
          '<div class="ht-head"><div>' +
            '<span class="ht-kicker">STOCK TERMINAL · 5.0</span>' +
            '<span class="ht-title">類股熱力</span>' +
            '<span class="ht-sub" id="ht-sub">產業漲跌 · 點格載入代表股</span>' +
          '</div><div class="ht-actions">' +
            '<button type="button" class="ht-btn on" data-mkt="TW">TW</button>' +
            '<button type="button" class="ht-btn" data-mkt="US">US</button>' +
            '<button type="button" class="ht-btn on" data-sort="chg">漲跌</button>' +
            '<button type="button" class="ht-btn" data-sort="name">名稱</button>' +
            '<button type="button" class="ht-btn" id="ht-refresh">↻</button>' +
            '<button type="button" class="ht-btn primary" data-shell-back>← 圖表</button>' +
          '</div></div>' +
          '<div id="ht-body" class="ht-loading">載入類股…</div>' +
        '</div>';
      mount.querySelectorAll('[data-mkt]').forEach(function (b) {
        b.onclick = function () {
          state.mkt = b.getAttribute('data-mkt');
          mount.querySelectorAll('[data-mkt]').forEach(function (x) {
            x.classList.toggle('on', x.getAttribute('data-mkt') === state.mkt);
          });
          refresh();
        };
      });
      mount.querySelectorAll('[data-sort]').forEach(function (b) {
        b.onclick = function () {
          state.sort = b.getAttribute('data-sort');
          mount.querySelectorAll('[data-sort]').forEach(function (x) {
            x.classList.toggle('on', x.getAttribute('data-sort') === state.sort);
          });
          if (state.last) renderHeat(state.last);
        };
      });
      var r = $('ht-refresh');
      if (r) r.onclick = function () { refresh(true); };
    }
    return $('ht-body');
  }

  function openSym(code, mkt) {
    if (!code || typeof loadSym !== 'function') return;
    loadSym(code, mkt || 'TW');
    if (window.ShellV5) window.ShellV5.go('chart');
  }

  function renderFocus(j) {
    var box = $('ht-focus');
    if (!box) return;
    if (!j || !j.ok) {
      box.innerHTML = '<div class="ht-note">焦點掃描暫不可用或仍在載入。</div>';
      return;
    }
    function col(title, rows) {
      var V = window.Viz;
      var h = '<div><h4 style="margin:0 0 4px;font-size:10px;color:var(--gold);flex:0 0 auto">' + title +
        ' · ' + rows.length + '</h4><div class="ht-list">';
      if (!rows.length) h += '<div class="ht-note">無符合</div>';
      rows.slice(0, 18).forEach(function (r) {
        h += '<div class="ht-row" data-code="' + r.sym + '">' +
          '<span class="code">' + r.sym + '</span>' +
          '<span class="name">' + (r.name || '') + '</span>' +
          '<span class="' + twCls(r.changePct) + '">' + pct(r.changePct) + '</span>' +
          '<span style="color:var(--gold);font-weight:700;min-width:48px;text-align:right">' +
          (r.score != null ? r.score : '') +
          (V && r.score != null ? V.scoreMeter(r.score) : '') +
          '</span></div>';
      });
      return h + '</div></div>';
    }
    box.innerHTML = '<div class="ht-two">' +
      col('做多焦點', j.buy || []) +
      col('做空焦點', j.short || []) +
      '</div>' +
      '<div class="ht-note">掃描 ' + (j.scanned || '—') + ' 檔 · 點列載入 K 線</div>';
    box.querySelectorAll('.ht-row').forEach(function (el) {
      el.onclick = function () { openSym(el.getAttribute('data-code'), 'TW'); };
    });
  }

  function renderHeat(d) {
    var body = ensureMount();
    if (!body) return;
    state.last = d;
    var mkt = state.mkt;
    var rows = filterSectors(d && d.sectors, mkt);
    var sub = $('ht-sub');
    if (sub) {
      sub.textContent = (mkt === 'TW' ? '台股類股指數' : '美股 SPDR 產業') +
        ' · ' + rows.length + ' 格 · 資料日 ' + ((d && d.date) || '—') +
        ' · 更新 ' + new Date().toLocaleTimeString('zh-TW');
    }

    var legend = mkt === 'TW'
      ? '<div class="ht-legend"><i style="background:rgba(248,113,113,.8)"></i>漲 ' +
        '<i style="background:rgba(74,222,128,.8)"></i>跌　（台股紅漲綠跌）</div>'
      : '<div class="ht-legend"><i style="background:rgba(74,222,128,.8)"></i>漲 ' +
        '<i style="background:rgba(248,113,113,.8)"></i>跌　（美股綠漲紅跌）</div>';

    var grid = '<div class="ht-grid">';
    if (!rows.length) {
      grid += '<div class="ht-loading">無類股資料</div>';
    } else {
      rows.forEach(function (s) {
        var code = mkt === 'US' ? (s.symbol || '') : proxyFor(s.name);
        grid += '<div class="ht-cell" style="background:' + pctColor(s.changePct, mkt) + '" data-code="' +
          (code || '') + '" data-mkt="' + mkt + '" title="' + s.name + (code ? ' → ' + code : '') + '">' +
          '<div class="nm">' + s.name + '</div>' +
          '<div class="pc">' + pct(s.changePct) + '</div>' +
          '<div class="px">' + fmt(s.close) + '</div></div>';
      });
    }
    grid += '</div>';

    body.classList.remove('ht-loading');
    body.innerHTML =
      '<div class="ht-main"><h4 style="margin:0 0 3px;font-size:10px;color:var(--gold);letter-spacing:.5px;flex:0 0 auto">類股熱力圖</h4>' +
        legend + '<div class="ht-grid-wrap">' + grid + '</div>' +
        '<div class="ht-note">/sectors · 台股代表股／美股 SPDR · 非投資建議</div></div>' +
      '<div class="ht-focus-zone"><h4>焦點掃描</h4><div id="ht-focus" class="ht-loading">掃描中…</div></div>';

    body.querySelectorAll('.ht-cell').forEach(function (el) {
      el.onclick = function () {
        var c = el.getAttribute('data-code');
        var m = el.getAttribute('data-mkt') || 'TW';
        if (c) openSym(c, m);
      };
    });

    if (state.focus) renderFocus(state.focus);
  }

  function loadFocus() {
    fetch(SRV + '/focus', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        state.focus = j;
        if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'heat') {
          renderFocus(j);
        }
      })
      .catch(function () {
        state.focus = null;
        renderFocus(null);
      });
  }

  function refresh(forceFocus) {
    var body = ensureMount();
    if (!body) return;
    body.innerHTML = '<div class="ht-loading">載入類股…</div>';
    fetch(SRV + '/sectors?mkt=' + encodeURIComponent(state.mkt), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        renderHeat(d || { sectors: [] });
        if (forceFocus || !state.focus) loadFocus();
        else renderFocus(state.focus);
      })
      .catch(function () {
        var b = ensureMount();
        if (b) b.innerHTML = '<div class="ht-loading">載入失敗</div>';
      });
  }

  function activate() {
    ensureMount();
    refresh(false);
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'heat') {
        refresh(false);
      }
    }, 60000);
  }

  window.HeatV5 = { activate: activate, refresh: refresh };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'heat') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'heat') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 220); });
  else setTimeout(boot, 220);
})();

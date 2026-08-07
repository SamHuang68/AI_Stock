/* ============================================================================
 * news_v5.js  —  Stock Terminal 5.0 Stage 3：快訊中樞（事件／結算／提醒）
 * ----------------------------------------------------------------------------
 * 無新聞 scraper。此頁彙整既有「會主動打擾你」的資訊：
 *   GET /events     — 月營收截止、除權息預告
 *   結算日計算      — 每月第三個週三（與 settle_v3 同規則）
 *   GET /alert/status — 後端警報狀態（若有）
 * 掛載：#mount-news
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;

  function $(id) { return document.getElementById(id); }

  function injectCSS() {
    var s = $('news-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'news-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-news.on){overflow:hidden!important}' +
      '#view-news.sv-panel.on{max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-news,#mount-news.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none}' +
      '#nw-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);width:100%;max-width:none;margin:0;min-width:0;' +
        'box-sizing:border-box;flex:1;min-height:0;display:flex;flex-direction:column}' +
      '#nw-root .nw-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#nw-root .nw-head > div:first-child{min-width:0;flex:1 1 auto;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#nw-root .nw-kicker{font-size:9px;color:var(--gold);letter-spacing:1.2px;margin:0;font-weight:700}' +
      '#nw-root .nw-title{font-family:\'Noto Serif TC\',serif;font-size:15px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#nw-root .nw-sub{font-size:9px;color:var(--tlo);margin:0}' +
      '#nw-root .nw-actions{display:flex;gap:4px;flex-wrap:nowrap;flex:0 0 auto}' +
      '#nw-root .nw-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:9px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;white-space:nowrap}' +
      '#nw-root .nw-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#nw-root .nw-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#nw-body{flex:1;min-height:0;display:grid;grid-template-columns:minmax(220px,28%) minmax(0,1fr);gap:4px;overflow:hidden}' +
      '#nw-root .nw-left,#nw-root .nw-right{min-height:0;overflow:auto;display:flex;flex-direction:column;gap:4px}' +
      '#nw-root .nw-card{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;min-width:0}' +
      '#nw-root .nw-card h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px}' +
      '#nw-root .nw-grid{display:grid;grid-template-columns:1fr;gap:4px}' +
      '#nw-root .nw-stat{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px}' +
      '#nw-root .nw-stat .k{font-size:8px;color:var(--tlo)}#nw-root .nw-stat .v{font-size:14px;font-weight:700;color:var(--thi);margin-top:1px;line-height:1.15}' +
      '#nw-root .nw-stat .s{font-size:8px;color:var(--tlo);margin-top:1px;line-height:1.3}' +
      '#nw-root .soon{color:var(--gold);font-weight:700}' +
      '#nw-root .warn{color:var(--orange)}' +
      '#nw-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#nw-root th,#nw-root td{padding:3px 5px;border-bottom:1px solid var(--border);text-align:left}' +
      '#nw-root th{color:var(--tlo);position:sticky;top:0;background:var(--bg2);font-size:9px;z-index:1}' +
      '#nw-root tr.nw-row{cursor:pointer}#nw-root tr.nw-row:hover{background:var(--bg3)}' +
      '#nw-root .nw-table-wrap{flex:1;min-height:0;overflow:auto}' +
      '#nw-root .nw-note{font-size:8px;color:var(--tlo);line-height:1.35;margin-top:2px}' +
      '#nw-root .nw-loading{font-size:10px;color:var(--tlo);padding:12px 0}';
  }

  function thirdWednesday(y, m) {
    var first = new Date(y, m, 1);
    var dow = first.getDay();
    var firstWed = 1 + ((3 - dow + 7) % 7);
    return new Date(y, m, firstWed + 14);
  }
  function nextSettlement() {
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var t = thirdWednesday(now.getFullYear(), now.getMonth());
    if (today > t) {
      var nm = new Date(now.getFullYear(), now.getMonth() + 1, 1);
      t = thirdWednesday(nm.getFullYear(), nm.getMonth());
    }
    return t;
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-news');
    if (!panel) return null;
    var mount = $('mount-news');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-news';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('nw-root')) {
      mount.innerHTML =
        '<div id="nw-root">' +
          '<div class="nw-head"><div>' +
            '<span class="nw-kicker">STOCK TERMINAL · 5.0</span>' +
            '<span class="nw-title">快訊</span>' +
            '<span class="nw-sub">事件行事曆 · 結算日 · 警報</span>' +
          '</div><div class="nw-actions">' +
            '<button type="button" class="nw-btn" id="nw-refresh">↻</button>' +
            '<button type="button" class="nw-btn" id="nw-cal">行事曆</button>' +
            '<button type="button" class="nw-btn" id="nw-toast">通知</button>' +
            '<button type="button" class="nw-btn" id="nw-push">推播</button>' +
            '<button type="button" class="nw-btn" id="nw-ovn">夜盤</button>' +
            '<button type="button" class="nw-btn primary" data-shell-back>← 圖表</button>' +
          '</div></div>' +
          '<div id="nw-body" class="nw-loading">載入快訊…</div>' +
        '</div>';
      var r = $('nw-refresh');
      if (r) r.onclick = function () { refresh(); };
      var c = $('nw-cal');
      if (c) c.onclick = function () { if (window.calendarOpen) window.calendarOpen(); };
      var t = $('nw-toast');
      if (t) t.onclick = function () {
        var b = document.getElementById('btn-toast');
        if (b) b.click();
      };
      var p = $('nw-push');
      if (p) p.onclick = function () { if (window.alertPushOpen) window.alertPushOpen(); };
      var o = $('nw-ovn');
      if (o) o.onclick = function () { if (window.overnightOpen) window.overnightOpen(); };
    }
    return $('nw-body');
  }

  function render(ev, alertSt) {
    var body = ensureMount();
    if (!body) return;
    ev = ev || {};
    var settle = nextSettlement();
    var today = new Date();
    today = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    var days = Math.round((settle - today) / 86400000);
    var md = (settle.getMonth() + 1) + '/' + settle.getDate();
    var settleCls = days <= 3 ? 'warn' : '';
    var settleTxt = days === 0 ? '今日結算' : ('還有 ' + days + ' 天');
    var V = window.Viz;
    var settleSub = settleTxt + '（第三個週三）';
    if (V && days <= 3) {
      settleSub = V.badge(settleTxt, days <= 1 ? 'err' : 'warn') + ' <span class="' + settleCls + '">（第三個週三）</span>';
    }

    var rev = ev.revenue || {};
    var revSoon = rev.daysAway != null && rev.daysAway <= 5;
    var ex = ev.exDividend || [];

    var alertLine = '—';
    if (alertSt) {
      if (alertSt.running === true || alertSt.ok === true) alertLine = '運行中';
      else if (alertSt.error) alertLine = '異常';
      else alertLine = alertSt.status || (alertSt.enabled ? '已設定' : '未啟用');
    }

    var left =
      '<div class="nw-left">' +
        '<div class="nw-card"><h4>⏱ 時程計數</h4><div class="nw-grid">' +
          '<div class="nw-stat"><div class="k">期貨結算日</div><div class="v ' + settleCls + '">' + md + '</div>' +
            '<div class="s ' + settleCls + '">' + settleSub + '</div></div>' +
          '<div class="nw-stat"><div class="k">月營收截止</div><div class="v ' + (revSoon ? 'soon' : '') + '">' +
            (rev.nextPublishBy || '—') + '</div>' +
            '<div class="s">' + (rev.forMonth ? rev.forMonth + ' 營收' : '') +
            (rev.daysAway != null ? ' · ' + rev.daysAway + ' 天後' : '') + '</div></div>' +
          '<div class="nw-stat"><div class="k">後端警報</div><div class="v" style="font-size:12px">' + alertLine + '</div>' +
            '<div class="s">推播／規則見系統選單</div></div>' +
        '</div></div>' +
        '<div class="nw-card"><h4>📈 月營收公布</h4>' +
          (rev.nextPublishBy
            ? ('<div style="font-size:10px">下次：<span class="' + (revSoon ? 'soon' : '') + '">' + rev.nextPublishBy +
              '</span>（' + (rev.forMonth || '') + '）</div>' +
              '<div class="nw-note">上市櫃每月 10 日前須公布上月營收；YoY 是供應鏈動能的即時訊號。</div>')
            : '<div class="nw-note">無營收時程資料。</div>') +
        '</div>' +
        '<div class="nw-note">非新聞頭條源；集中「會影響部位節奏」的時程與提醒。</div>' +
      '</div>';

    var exTable = '';
    if (ex.length) {
      exTable = '<div class="nw-table-wrap"><table><tr><th>日期</th><th>標的</th><th>類型</th></tr>' +
        ex.slice(0, 60).map(function (e) {
          var typ = e.type || '';
          var typCell = typ;
          if (V && typ) {
            if (typ.indexOf('息') >= 0) typCell = V.chip('除息', 'hot');
            else if (typ.indexOf('權') >= 0) typCell = V.chip('除權', 'mid');
            else typCell = V.chip(typ, 'mid');
          }
          return '<tr class="nw-row" data-code="' + (e.code || '') + '"><td>' + (e.date || '') +
            '</td><td>' + (e.code || '') + ' ' + (e.name || '') + '</td><td>' + typCell + '</td></tr>';
        }).join('') + '</table></div>';
    } else {
      exTable = '<div class="nw-note">目前無預告（TWSE 資料集可能未開放或當期無資料）。</div>';
    }

    var right =
      '<div class="nw-right">' +
        '<div class="nw-card" style="flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden">' +
          '<h4>💵 除權除息預告 · ' + ex.length + ' 筆</h4>' + exTable +
        '</div></div>';

    body.innerHTML = left + right;

    body.querySelectorAll('tr.nw-row').forEach(function (el) {
      el.onclick = function () {
        var code = el.getAttribute('data-code');
        if (code && typeof loadSym === 'function') {
          loadSym(code, 'TW');
          if (window.ShellV5) window.ShellV5.go('chart');
        }
      };
    });
  }

  function refresh() {
    var body = ensureMount();
    if (!body) return;
    body.innerHTML = '<div class="nw-loading">載入快訊…</div>';
    Promise.all([
      fetch(SRV + '/events', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }),
      fetch(SRV + '/alert/status', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
    ]).then(function (arr) { render(arr[0], arr[1]); });
  }

  function activate() {
    ensureMount();
    refresh();
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'news') refresh();
    }, 120000);
  }

  window.NewsV5 = { activate: activate, refresh: refresh };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'news') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'news') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 240); });
  else setTimeout(boot, 240);
})();

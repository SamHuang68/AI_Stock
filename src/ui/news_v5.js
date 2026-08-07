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
    if ($('news-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'news-v5-css';
    s.textContent =
      '#view-news.sv-panel{max-width:860px;padding:8px 12px 14px}' +
      '#nw-root{font-family:\'JetBrains Mono\',monospace;color:var(--text)}' +
      '#nw-root .nw-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:6px}' +
      '#nw-root .nw-kicker{font-size:10px;color:var(--gold);letter-spacing:2px;margin-bottom:4px}' +
      '#nw-root .nw-title{font-family:\'Noto Serif TC\',serif;font-size:18px;font-weight:700;color:var(--thi);line-height:1.15}' +
      '#nw-root .nw-sub{font-size:11px;color:var(--tlo);margin-top:4px}' +
      '#nw-root .nw-actions{display:flex;gap:8px;flex-wrap:wrap}' +
      '#nw-root .nw-btn{padding:6px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;font-family:\'JetBrains Mono\',monospace;cursor:pointer}' +
      '#nw-root .nw-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#nw-root .nw-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#nw-root .nw-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin:10px 0}' +
      '#nw-root .nw-card h4{margin:0 0 8px;font-size:12px;color:var(--gold)}' +
      '#nw-root .nw-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}' +
      '#nw-root .nw-stat{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:10px}' +
      '#nw-root .nw-stat .k{font-size:9px;color:var(--tlo)}#nw-root .nw-stat .v{font-size:18px;font-weight:700;color:var(--thi);margin-top:4px}' +
      '#nw-root .nw-stat .s{font-size:10px;color:var(--tlo);margin-top:3px}' +
      '#nw-root .soon{color:var(--gold);font-weight:700}' +
      '#nw-root .warn{color:var(--orange)}' +
      '#nw-root table{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px}' +
      '#nw-root th,#nw-root td{padding:5px 6px;border-bottom:1px solid var(--border);text-align:left}' +
      '#nw-root th{color:var(--tlo)}' +
      '#nw-root tr.nw-row{cursor:pointer}#nw-root tr.nw-row:hover{background:var(--bg3)}' +
      '#nw-root .nw-note{font-size:9px;color:var(--tlo);line-height:1.65;margin-top:12px}' +
      '#nw-root .nw-loading{font-size:11px;color:var(--tlo);padding:18px 0}' +
      '@media (max-width:720px){#nw-root .nw-grid{grid-template-columns:1fr}}';
    document.head.appendChild(s);
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
            '<div class="nw-kicker">STOCK TERMINAL · 5.0-S3</div>' +
            '<div class="nw-title">快訊</div>' +
            '<div class="nw-sub">事件行事曆 · 結算日 · 警報狀態（非新聞頭條）</div>' +
          '</div><div class="nw-actions">' +
            '<button type="button" class="nw-btn" id="nw-refresh">↻ 重新整理</button>' +
            '<button type="button" class="nw-btn" id="nw-cal">行事曆</button>' +
            '<button type="button" class="nw-btn primary" data-shell-back>← 圖表</button>' +
          '</div></div>' +
          '<div id="nw-body" class="nw-loading">載入快訊…</div>' +
        '</div>';
      var r = $('nw-refresh');
      if (r) r.onclick = function () { refresh(); };
      var c = $('nw-cal');
      if (c) c.onclick = function () { if (window.calendarOpen) window.calendarOpen(); };
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

    var html =
      '<div class="nw-grid">' +
        '<div class="nw-stat"><div class="k">期貨結算日</div><div class="v ' + settleCls + '">' + md + '</div>' +
          '<div class="s ' + settleCls + '">' + settleSub + '</div></div>' +
        '<div class="nw-stat"><div class="k">月營收截止</div><div class="v ' + (revSoon ? 'soon' : '') + '">' +
          (rev.nextPublishBy || '—') + '</div>' +
          '<div class="s">' + (rev.forMonth ? rev.forMonth + ' 營收' : '') +
          (rev.daysAway != null ? ' · ' + rev.daysAway + ' 天後' : '') + '</div></div>' +
        '<div class="nw-stat"><div class="k">後端警報</div><div class="v" style="font-size:14px">' + alertLine + '</div>' +
          '<div class="s">推播／規則見系統選單</div></div>' +
      '</div>';

    html += '<div class="nw-card"><h4>📈 月營收公布</h4>' +
      (rev.nextPublishBy
        ? ('<div>下次截止：<span class="' + (revSoon ? 'soon' : '') + '">' + rev.nextPublishBy +
          '</span>（' + (rev.forMonth || '') + '）</div>' +
          '<div class="nw-note">上市櫃每月 10 日前須公布上月營收；YoY 是供應鏈動能的即時訊號。</div>')
        : '<div class="nw-note">無營收時程資料。</div>') +
      '</div>';

    html += '<div class="nw-card"><h4>💵 除權除息預告</h4>';
    if (ex.length) {
      html += '<table><tr><th>日期</th><th>標的</th><th>類型</th></tr>' +
        ex.slice(0, 40).map(function (e) {
          var typ = e.type || '';
          var typCell = typ;
          if (V && typ) {
            if (typ.indexOf('息') >= 0) typCell = V.chip('除息', 'hot');
            else if (typ.indexOf('權') >= 0) typCell = V.chip('除權', 'mid');
            else typCell = V.chip(typ, 'mid');
          }
          return '<tr class="nw-row" data-code="' + (e.code || '') + '"><td>' + (e.date || '') +
            '</td><td>' + (e.code || '') + ' ' + (e.name || '') + '</td><td>' + typCell + '</td></tr>';
        }).join('') + '</table>';
    } else {
      html += '<div class="nw-note">目前無預告（TWSE 資料集可能未開放或當期無資料）。</div>';
    }
    html += '</div>';

    html += '<div class="nw-card"><h4>🔔 快捷</h4>' +
      '<div class="nw-actions">' +
        '<button type="button" class="nw-btn" id="nw-toast">通知設定</button>' +
        '<button type="button" class="nw-btn" id="nw-push">推播設定</button>' +
        '<button type="button" class="nw-btn" id="nw-ovn">夜盤預警</button>' +
      '</div>' +
      '<div class="nw-note">此頁不是新聞頭條源；標題／外電請用外部來源。這裡集中「會影響部位節奏」的時程與提醒。</div></div>';

    body.innerHTML = html;

    body.querySelectorAll('tr.nw-row').forEach(function (el) {
      el.onclick = function () {
        var code = el.getAttribute('data-code');
        if (code && typeof loadSym === 'function') {
          loadSym(code, 'TW');
          if (window.ShellV5) window.ShellV5.go('chart');
        }
      };
    });
    var t = $('nw-toast');
    if (t) t.onclick = function () {
      var b = document.getElementById('btn-toast');
      if (b) b.click();
    };
    var p = $('nw-push');
    if (p) p.onclick = function () {
      if (window.alertPushOpen) window.alertPushOpen();
    };
    var o = $('nw-ovn');
    if (o) o.onclick = function () {
      if (window.overnightOpen) window.overnightOpen();
    };
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

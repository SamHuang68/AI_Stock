/* ============================================================================
 * news_v5.js  —  Stock Terminal 5.0 Stage 3：快訊中樞（事件／結算／提醒）
 * ----------------------------------------------------------------------------
 * 快訊中樞：
 *   GET /flash      — 台／美公司重大訊息（上市櫃重訊＋美股新聞／8-K）
 *   GET /events     — 月營收截止、除權息預告
 *   結算日計算      — 每月第三個週三（與 settle_v3 同規則）
 *   GET /alert/status — 後端警報狀態（若有）
 * 掛載：#mount-news
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var flashMkt = 'all'; /* all | TW | US */
  var flashImpact = 'all'; /* all | high | medium_up */
  var lastPack = null;

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
      '#nw-root .nw-kicker{display:none!important}' +
      '#nw-root .nw-title{font-family:\'Noto Serif TC\',serif;font-size:17px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#nw-root .nw-sub{font-size:11px;color:var(--tlo);margin:0}' +
      '#nw-root .nw-actions{display:flex;gap:4px;flex-wrap:nowrap;flex:0 0 auto}' +
      '#nw-root .nw-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;font-family:\'JetBrains Mono\',monospace;cursor:pointer;white-space:nowrap}' +
      '#nw-root .nw-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#nw-root .nw-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#nw-body{flex:1;min-height:0;display:flex;flex-direction:column;gap:4px;overflow:hidden}' +
      '#nw-root .nw-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;flex:0 0 auto}' +
      '#nw-root .nw-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '#nw-root .nw-strip .k{font-size:10px;color:var(--tlo);letter-spacing:.4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#nw-root .nw-strip .v{font-size:15px;font-weight:800;color:var(--thi);line-height:1.15;margin-top:1px}' +
      '#nw-root .nw-strip .s{font-size:10px;color:var(--tlo);margin-top:0;line-height:1.2}' +
      '#nw-root .nw-dash{flex:1;min-height:0;display:grid;grid-template-columns:minmax(220px,26%) minmax(0,1.2fr) minmax(0,1fr);gap:4px;overflow:hidden}' +
      '#nw-root .nw-left,#nw-root .nw-mid,#nw-root .nw-right{min-height:0;overflow:hidden;display:flex;flex-direction:column;gap:4px}' +
      '#nw-root .nw-card{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;min-width:0;' +
        'display:flex;flex-direction:column;flex:1;min-height:0;overflow:hidden}' +
      '#nw-root .nw-card h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px;flex:0 0 auto;' +
        'display:flex;justify-content:space-between;align-items:center;gap:6px}' +
      '#nw-root .nw-mid .nw-card h4{flex-wrap:wrap}' +
      '#nw-root .nw-grid{display:grid;grid-template-columns:1fr;gap:4px;flex:1;align-content:start}' +
      '#nw-root .nw-stat{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:4px 6px}' +
      '#nw-root .nw-stat .k{font-size:10px;color:var(--tlo)}#nw-root .nw-stat .v{font-size:16px;font-weight:700;color:var(--thi);margin-top:1px;line-height:1.15}' +
      '#nw-root .nw-stat .s{font-size:10px;color:var(--tlo);margin-top:1px;line-height:1.3}' +
      '#nw-root .soon{color:var(--gold);font-weight:700}' +
      '#nw-root .warn{color:var(--orange)}' +
      '#nw-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#nw-root th,#nw-root td{padding:3px 5px;border-bottom:1px solid var(--border);text-align:left}' +
      '#nw-root th{color:var(--tlo);position:sticky;top:0;background:var(--bg2);font-size:11px;z-index:1}' +
      '#nw-root tr.nw-row{cursor:pointer}#nw-root tr.nw-row:hover{background:var(--bg3)}' +
      '#nw-root .nw-table-wrap{flex:1;min-height:0;overflow:auto}' +
      '#nw-root .nw-flash-list{flex:1;min-height:0;overflow:auto;font-size:10px}' +
      '#nw-root .nw-flash-list .row{padding:4px 2px;border-bottom:1px solid var(--border);cursor:pointer;line-height:1.35}' +
      '#nw-root .nw-flash-list .row:hover{background:var(--bg3)}' +
      '#nw-root .nw-flash-list .t{color:var(--tlo);font-size:10px;margin-right:4px;white-space:nowrap}' +
      '#nw-root .nw-flash-list .cat{color:var(--cyan);font-size:10px;margin-right:4px}' +
      '#nw-root .nw-flash-list .cat.us{color:var(--gold)}' +
      '#nw-root .nw-flash-list .impact{display:inline-flex;padding:0 4px;margin-right:4px;border-radius:999px;' +
        'font-size:8px;border:1px solid #42516a;color:#9fb0c5;vertical-align:1px}' +
      '#nw-root .nw-flash-list .impact.high{border-color:#f87171;color:#fecaca}' +
      '#nw-root .nw-flash-list .impact.medium{border-color:#fb923c;color:#fed7aa}' +
      '#nw-root .nw-seg{display:flex;gap:0;border:1px solid var(--border);border-radius:4px;overflow:hidden}' +
      '#nw-root .nw-seg button{padding:2px 8px;border:0;border-right:1px solid var(--border);background:var(--bg);' +
        'color:var(--tlo);font-family:inherit;font-size:9px;font-weight:600;cursor:pointer}' +
      '#nw-root .nw-seg button:last-child{border-right:0}' +
      '#nw-root .nw-seg button.on{background:var(--gold);color:#060A12;font-weight:800}' +
      '#nw-root .nw-filterbar{display:flex;align-items:center;gap:4px;min-width:0;flex-wrap:wrap}' +
      '#nw-root .nw-note{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:2px;flex:0 0 auto}' +
      '#nw-root .nw-empty{flex:1;min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;' +
        'gap:6px;text-align:center;padding:18px;border:1px dashed rgba(148,163,184,.22);border-radius:8px;' +
        'background:radial-gradient(circle at 50% 18%,rgba(56,189,248,.07),transparent 54%),rgba(5,10,19,.28)}' +
      '#nw-root .nw-empty-icon{width:34px;height:34px;display:grid;place-items:center;border-radius:50%;' +
        'border:1px solid rgba(125,211,252,.25);color:var(--cyan);font-size:17px;background:rgba(56,189,248,.06)}' +
      '#nw-root .nw-empty b{font-size:11px;color:var(--thi)}' +
      '#nw-root .nw-empty span{max-width:250px;font-size:9px;line-height:1.5;color:var(--tlo)}' +
      '#nw-root .nw-loading{font-size:10px;color:var(--tlo);padding:12px 0}' +
      '#nw-body.nw-loading{display:flex;align-items:center}' +
      '@media (max-width:1100px){#nw-root .nw-dash{grid-template-columns:1fr 1fr}#nw-root .nw-left{display:none}}';
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
            '<span class="nw-title">快訊</span>' +
            '<span class="nw-sub">台美重大訊息 · 事件行事曆 · 結算日</span>' +
          '</div><div class="nw-actions">' +
            '<button type="button" class="nw-btn" id="nw-refresh">↻</button>' +
            '<button type="button" class="nw-btn" id="nw-cal">行事曆</button>' +
            '<button type="button" class="nw-btn" id="nw-toast">通知</button>' +
            '<button type="button" class="nw-btn" id="nw-push">推播</button>' +
            '<button type="button" class="nw-btn" id="nw-ovn">夜盤</button>' +
            '<button type="button" class="nw-btn primary" data-shell-back>← 儀表板</button>' +
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

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderFlashList(items) {
    items = items || [];
    if (flashMkt === 'TW') {
      items = items.filter(function (f) {
        return f.mkt !== 'US' && !(f.cat && String(f.cat).indexOf('美股') >= 0);
      });
    } else if (flashMkt === 'US') {
      items = items.filter(function (f) {
        return f.mkt === 'US' || (f.cat && String(f.cat).indexOf('美股') >= 0);
      });
    }
    if (flashImpact === 'high') {
      items = items.filter(function (f) { return String(((f.impact || {}).tier) || 'LOW').toUpperCase() === 'HIGH'; });
    } else if (flashImpact === 'medium_up') {
      items = items.filter(function (f) {
        return ['HIGH', 'MEDIUM'].indexOf(String(((f.impact || {}).tier) || 'LOW').toUpperCase()) >= 0;
      });
    }
    if (!items.length) {
      return '<div class="nw-note">此篩選尚無訊息</div>';
    }
    return '<div class="nw-flash-list">' + items.slice(0, 50).map(function (f) {
      var isUs = (f.mkt === 'US') || (f.cat && String(f.cat).indexOf('美股') >= 0);
      var impact = f.impact || {};
      var tier = String(impact.tier || 'LOW').toUpperCase();
      var impactTitle = [impact.reason, (impact.scope || []).join(' / '), impact.ruleId].filter(Boolean).join(' · ');
      return '<div class="row"' +
        (f.code ? ' data-code="' + esc(f.code) + '"' : '') +
        (f.mkt ? ' data-mkt="' + esc(f.mkt) + '"' : '') +
        (f.url ? ' data-url="' + esc(f.url) + '"' : '') + '>' +
        '<span class="t">' + esc(f.time || '') + '</span>' +
        '<span class="cat' + (isUs ? ' us' : '') + '">[' + esc(f.cat || '') + ']</span>' +
        '<span class="impact ' + tier.toLowerCase() + '" title="' + esc(impactTitle) + '">' + esc(tier) + '</span>' +
        esc(f.title || '') + '</div>';
    }).join('') + '</div>';
  }

  function render(ev, alertSt, flashPack) {
    var body = ensureMount();
    if (!body) return;
    ev = ev || {};
    flashPack = flashPack || {};
    lastPack = { ev: ev, alertSt: alertSt, flashPack: flashPack };
    var flashItems = flashPack.items || [];
    var settle = nextSettlement();
    var today = new Date();
    today = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    var days = Math.round((settle - today) / 86400000);
    var md = (settle.getMonth() + 1) + '/' + settle.getDate();
    var settleCls = days <= 3 ? 'warn' : '';
    var settleTxt = days === 0 ? '今日結算' : ('還有 ' + days + ' 天');
    var V = window.Viz;

    var rev = ev.revenue || {};
    var revSoon = rev.daysAway != null && rev.daysAway <= 5;
    var ex = ev.exDividend || [];
    var counts = flashPack.counts || {};
    var twN = counts.tw != null ? counts.tw : flashItems.filter(function (x) { return x.mkt !== 'US'; }).length;
    var usN = counts.us != null ? counts.us : flashItems.filter(function (x) { return x.mkt === 'US'; }).length;

    var alertLine = '—';
    var alertDetail = '未連線';
    if (alertSt) {
      if (alertSt.running === true || alertSt.ok === true) { alertLine = '運行中'; alertDetail = '後端警報服務正常'; }
      else if (alertSt.error) { alertLine = '異常'; alertDetail = String(alertSt.error).slice(0, 80); }
      else {
        alertLine = alertSt.status || (alertSt.enabled ? '已設定' : '未啟用');
        alertDetail = alertSt.enabled ? '規則已載入' : '可於工具列開啟通知設定';
      }
    }

    var exTable = '';
    if (ex.length) {
      exTable = '<div class="nw-table-wrap"><table><tr><th>日期</th><th>標的</th><th>類型</th></tr>' +
        ex.slice(0, 80).map(function (e) {
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
      exTable = '<div class="nw-empty"><div class="nw-empty-icon" aria-hidden="true">◇</div>' +
        '<b>目前沒有除權息事件</b><span>當期無公告，或 TWSE 資料集尚未開放；更新後會自動顯示。</span></div>';
    }

    var seg =
      '<div class="nw-seg" id="nw-mkt-seg">' +
        '<button type="button" data-mkt="all"' + (flashMkt === 'all' ? ' class="on"' : '') + '>全部</button>' +
        '<button type="button" data-mkt="TW"' + (flashMkt === 'TW' ? ' class="on"' : '') + '>台股</button>' +
        '<button type="button" data-mkt="US"' + (flashMkt === 'US' ? ' class="on"' : '') + '>美股</button>' +
      '</div>';
    var impactSeg =
      '<div class="nw-seg" id="nw-impact-seg" aria-label="影響層級篩選">' +
        '<button type="button" data-impact="all"' + (flashImpact === 'all' ? ' class="on"' : '') + '>全層級</button>' +
        '<button type="button" data-impact="medium_up"' + (flashImpact === 'medium_up' ? ' class="on"' : '') + '>中高</button>' +
        '<button type="button" data-impact="high"' + (flashImpact === 'high' ? ' class="on"' : '') + '>高影響</button>' +
      '</div>';

    body.classList.remove('nw-loading');
    body.innerHTML =
      '<div class="nw-strip">' +
        '<div class="cell"><div class="k">台股重訊</div><div class="v">' + twN + '</div>' +
          '<div class="s">上市＋櫃買精選</div></div>' +
        '<div class="cell"><div class="k">美股訊息</div><div class="v">' + usN + '</div>' +
          '<div class="s">權值／半導體＋8-K</div></div>' +
        '<div class="cell"><div class="k">期貨結算</div><div class="v ' + settleCls + '">' + md + '</div>' +
          '<div class="s ' + settleCls + '">' + settleTxt + ' · 第三週三</div></div>' +
        '<div class="cell"><div class="k">月營收截止</div><div class="v ' + (revSoon ? 'soon' : '') + '">' +
          (rev.nextPublishBy || '—') + '</div><div class="s">' +
          (rev.forMonth ? rev.forMonth + ' 營收' : '—') +
          (rev.daysAway != null ? ' · ' + rev.daysAway + ' 天' : '') +
          ' · 警報 ' + alertLine + '</div></div>' +
      '</div>' +
      '<div class="nw-dash">' +
        '<div class="nw-left">' +
          '<div class="nw-card"><h4>警報與捷徑</h4><div class="nw-grid">' +
            '<div class="nw-stat"><div class="k">警報狀態</div><div class="v" style="font-size:12px">' + esc(alertLine) +
              '</div><div class="s">' + esc(alertDetail) + '</div></div>' +
            '<div class="nw-stat"><div class="k">除權息預告</div><div class="v">' + ex.length +
              '</div><div class="s">右側完整列表</div></div>' +
            '<div class="nw-stat"><div class="k">捷徑</div><div class="s" style="margin-top:4px;display:flex;gap:4px;flex-wrap:wrap">' +
              '<button type="button" class="nw-btn" data-go="afterhours">盤後</button>' +
              '<button type="button" class="nw-btn" data-go="institutional">法人</button>' +
              '<button type="button" class="nw-btn" id="nw-open-cal">行事曆</button>' +
            '</div></div>' +
          '</div></div>' +
        '</div>' +
        '<div class="nw-mid">' +
          '<div class="nw-card"><h4><span>重大訊息</span><span class="nw-filterbar">' + seg + impactSeg + '</span>' +
            '<span style="color:var(--tlo);font-weight:600;font-size:8px">' +
            (flashPack.updatedAt ? ('更新 ' + String(flashPack.updatedAt).replace('T', ' ')) : 'TWSE／Yahoo／SEC') +
            '</span></h4>' + renderFlashList(flashItems) +
            '<div class="nw-note">點列開圖表；美股另開原文。篩選不重抓資料。</div></div>' +
        '</div>' +
        '<div class="nw-right">' +
          '<div class="nw-card"><h4>除權除息預告 · ' + ex.length + ' 筆</h4>' + exTable + '</div>' +
        '</div>' +
      '</div>';

    body.querySelectorAll('tr.nw-row').forEach(function (el) {
      el.onclick = function () {
        var code = el.getAttribute('data-code');
        if (code && typeof loadSym === 'function') {
          loadSym(code, 'TW');
          if (window.ShellV5) window.ShellV5.go('chart');
        }
      };
    });
    body.querySelectorAll('.nw-flash-list .row').forEach(function (el) {
      el.onclick = function () {
        var code = el.getAttribute('data-code');
        var mkt = el.getAttribute('data-mkt') || 'TW';
        var url = el.getAttribute('data-url');
        if (url && mkt === 'US') window.open(url, '_blank', 'noopener');
        if (code && window.ShellV5 && ShellV5.openChart) {
          ShellV5.openChart(code, mkt);
          return;
        }
        if (code && typeof loadSym === 'function') {
          loadSym(code, mkt);
          if (window.ShellV5) window.ShellV5.go('chart');
        }
      };
    });
    var segEl = $('nw-mkt-seg');
    if (segEl) {
      segEl.querySelectorAll('button[data-mkt]').forEach(function (b) {
        b.onclick = function () {
          var m = b.getAttribute('data-mkt');
          if (!m || m === flashMkt) return;
          flashMkt = m;
          if (lastPack) render(lastPack.ev, lastPack.alertSt, lastPack.flashPack);
        };
      });
    }
    var impactEl = $('nw-impact-seg');
    if (impactEl) {
      impactEl.querySelectorAll('button[data-impact]').forEach(function (b) {
        b.onclick = function () {
          var tier = b.getAttribute('data-impact');
          if (!tier || tier === flashImpact) return;
          flashImpact = tier;
          if (lastPack) render(lastPack.ev, lastPack.alertSt, lastPack.flashPack);
        };
      });
    }
    body.querySelectorAll('[data-go]').forEach(function (b) {
      b.onclick = function () {
        if (window.ShellV5) window.ShellV5.go(b.getAttribute('data-go'));
      };
    });
    var cal = $('nw-open-cal');
    if (cal) cal.onclick = function () {
      if (typeof window.calendarOpen === 'function') window.calendarOpen();
    };
  }

  function refresh(opts) {
    opts = opts || {};
    var body = ensureMount();
    if (!body) return;
    var soft = !!opts.soft || !!body.querySelector('.nw-grid, .nw-card, .nw-flash');
    if (window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-news', soft, '更新中…');
    }
    if (!soft) body.innerHTML = '<div class="nw-loading">載入快訊…</div>';
    Promise.all([
      fetch(SRV + '/events', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }),
      fetch(SRV + '/alert/status', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
      fetch(SRV + '/flash?n=36', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; })
    ]).then(function (arr) { render(arr[0], arr[1], arr[2]); })
      .finally(function () {
        if (window.ShellV5 && window.ShellV5.softBadge) {
          window.ShellV5.softBadge('mount-news', false);
        }
      });
  }

  function activate() {
    ensureMount();
    refresh({ soft: !!$('nw-body') && !$('nw-body').querySelector('.nw-loading') });
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'news') {
        refresh({ soft: true });
      }
    }, 120000);
  }

  function deactivate() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  window.NewsV5 = { activate: activate, deactivate: deactivate, refresh: refresh };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'news') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'news') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 240); });
  else setTimeout(boot, 240);
})();

/* ============================================================================
 * ai_v5.js  —  Stock Terminal 5.0：AI 中樞側欄
 * ----------------------------------------------------------------------------
 * 全站 AI 功能集中一頁：KPI strip（Claude Key／模型、本機 EVO-T1、盤後日報、權限）
 * + AI 功能目錄（用途、模型、資料去向、所在位置、就緒狀態、開啟）。
 *   GET /ai-key/status · /ai-model · /ai/local/status · /api/ai/postmarket-daily/latest
 * 焦點掃描不是 AI（規則訊號），唯一入口在「策略訊號」頁。
 * 掛載：#mount-ai；側欄「AI」
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var fetching = false;
  var status = { key: null, model: null, local: null, pmd: null };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
    });
  }
  function jget(url) {
    return fetch(SRV + url, { cache: 'no-store', credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function injectCSS() {
    var s = $('ai-v5-css');
    if (!s) {
      s = document.createElement('style');
      s.id = 'ai-v5-css';
      document.head.appendChild(s);
    }
    s.textContent =
      '#shell-views:has(#view-ai.on){overflow:hidden!important}' +
      '#view-ai.sv-panel.on{max-width:none!important;width:100%;min-width:0;padding:4px 6px 6px;box-sizing:border-box;' +
        'overflow:hidden;display:flex!important;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#mount-ai,#mount-ai.sv-mount{flex:1;min-height:0;display:flex;flex-direction:column;max-width:none;width:100%}' +
      '#ai5-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'width:100%;max-width:none;margin:0;min-width:0;box-sizing:border-box;' +
        'display:flex;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#ai5-root .ai5-head{display:flex;align-items:center;justify-content:space-between;gap:8px;' +
        'margin-bottom:3px;min-width:0;flex:0 0 auto}' +
      '#ai5-root .ai5-head > div:first-child{min-width:0;flex:1;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}' +
      '#ai5-root .ai5-title{font-family:\'Noto Serif TC\',serif;font-size:17px;font-weight:700;color:var(--thi);line-height:1.1}' +
      '#ai5-root .ai5-sub{font-size:11px;color:var(--tlo);margin:0}' +
      '#ai5-root .ai5-actions{display:flex;gap:4px;flex-wrap:nowrap;flex:0 0 auto}' +
      '#ai5-root .ai5-btn{padding:3px 7px;border:1px solid var(--border);border-radius:4px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;font-family:inherit;cursor:pointer;white-space:nowrap}' +
      '#ai5-root .ai5-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#ai5-root .ai5-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#ai5-root .ai5-btn.primary:hover{background:#FBBF24}' +
      '#ai5-body{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}' +
      '#ai5-root .ai5-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;margin:0 0 4px;flex:0 0 auto}' +
      '#ai5-root .ai5-strip .cell{background:linear-gradient(180deg,rgba(17,27,46,.95),rgba(11,18,32,.98));' +
        'border:1px solid var(--border);border-radius:5px;padding:3px 6px;min-width:0;overflow:hidden}' +
      '#ai5-root .ai5-strip .k{font-size:10px;color:var(--tlo);letter-spacing:.4px}' +
      '#ai5-root .ai5-strip .v{font-size:13px;font-weight:800;color:var(--thi);line-height:1.2;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ai5-root .ai5-strip .s{font-size:10px;color:var(--tlo);line-height:1.2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ai5-root .ai5-tools{display:flex;gap:4px;flex-wrap:wrap;margin:0 0 4px;flex:0 0 auto}' +
      '#ai5-root .ai5-dash{flex:1;min-height:0;display:grid;gap:4px;grid-template-columns:minmax(0,1fr);' +
        'grid-template-rows:minmax(0,1fr);align-items:stretch}' +
      '#ai5-root .ai5-sec{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%}' +
      '#ai5-root .ai5-sec h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px;flex:0 0 auto;' +
        'display:flex;justify-content:space-between;align-items:center;gap:6px}' +
      '#ai5-root .ai5-fill{flex:1;min-height:0;overflow:auto}' +
      '#ai5-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#ai5-root th,#ai5-root td{padding:4px 5px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}' +
      '#ai5-root td:last-child,#ai5-root th:last-child{text-align:right;white-space:nowrap}' +
      '#ai5-root th{color:var(--tlo);font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1}' +
      '#ai5-root td.nm{color:var(--thi);font-weight:700;white-space:nowrap}' +
      '#ai5-root td.what{color:var(--text);min-width:180px}' +
      '#ai5-root td.where,#ai5-root td.mdl{color:var(--tlo);white-space:nowrap}' +
      '#ai5-root .tag{display:inline-block;padding:0 5px;border-radius:3px;font-size:9px;border:1px solid var(--border)}' +
      '#ai5-root .tag.cloud{color:#fde68a;border-color:rgba(250,204,21,.45)}' +
      '#ai5-root .tag.local{color:#a7f3d0;border-color:rgba(52,211,153,.45)}' +
      '#ai5-root .tag.ext{color:#fca5a5;border-color:rgba(248,113,113,.45)}' +
      '#ai5-root .ok{color:#34d399}#ai5-root .warn{color:#fbbf24}#ai5-root .off{color:var(--tlo)}' +
      '#ai5-root .ai5-note{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:4px;flex:0 0 auto}' +
      '#ai5-root .ai5-loading{font-size:10px;color:var(--tlo);padding:12px 0}';
  }

  function role() {
    var p = window.ST_PRIVATE_WEB_PROFILE;
    return p && p.role ? String(p.role) : 'local';
  }

  function openChartTab(tab) {
    if (window.ShellV5 && typeof window.ShellV5.go === 'function') window.ShellV5.go('chart');
    setTimeout(function () {
      if (typeof window.setTab === 'function') window.setTab(tab);
    }, 200);
  }

  function openPulseAi() {
    if (window.ShellV5 && typeof window.ShellV5.go === 'function') window.ShellV5.go('pulse');
    /* 只帶到按鈕並標示；本機推論需數分鐘，由使用者自己按下開始 */
    setTimeout(function () {
      var b = $('pl-ai-sum');
      if (!b) return;
      b.scrollIntoView({ block: 'nearest' });
      b.focus();
      b.style.outline = '2px solid var(--gold)';
      setTimeout(function () { b.style.outline = ''; }, 2400);
    }, 450);
  }

  /* engine：cloud＝Claude（送 Anthropic）；local＝EVO-T1 本機；pulse＝本機快速＋外部深度 */
  var FEATURES = [
    { id: 'pmd', name: '盤後日報', engine: 'cloud', where: 'AI 中樞',
      what: '持倉＋自選逐檔敘事；數字只引用伺服器證據包，會刪除喊單字句',
      open: function () { if (window.PostmarketDaily) window.PostmarketDaily.open(); } },
    { id: 'health', name: '個股體檢白話', engine: 'cloud', where: '圖表「體檢」分頁',
      what: '燈號、訊號與歷史統計逐句引用證據翻成白話；沒 Key 時用規則模板',
      open: function () { openChartTab('health'); } },
    { id: 'copilot', name: '本機副駕', engine: 'local', where: '副駕視窗',
      what: '自然語言問盤，自動附上當前個股、持倉與自選',
      open: function () { if (typeof window.copilotOpen === 'function') window.copilotOpen(); } },
    { id: 'pulse', name: '大盤 AI 摘要', engine: 'pulse', where: '儀表板「AI 摘要」',
      what: '大盤快速摘要（本機）或支持／反方證據的深度分析（外部）',
      open: openPulseAi },
    { id: 'decision', name: '決策 AI 解釋', engine: 'local', where: '決策中心',
      what: '解釋決策情境，列出反方觀點、衝突與失效條件',
      open: function () { if (window.ShellV5) window.ShellV5.go('decision', { focusSection: 'summary', from: 'ai-hub' }); } },
    { id: 'etf', name: 'ETF 異動原因', engine: 'cloud', where: '圖表「ETF△」分頁',
      what: 'ETF 加減碼個股的一句話原因（自動補月營收與三率）',
      open: function () { openChartTab('etf'); } },
    { id: 'wizard', name: '加股精靈筆記', engine: 'cloud', where: '🧙 精靈',
      what: '加股設定精靈最後一步產生的操作筆記',
      open: function () { if (typeof window.wizardOpen === 'function') window.wizardOpen(); } }
  ];

  function engineTag(engine) {
    if (engine === 'cloud') return '<span class="tag cloud">Claude · 雲端</span>';
    if (engine === 'local') return '<span class="tag local">EVO-T1 · 本機</span>';
    return '<span class="tag local">本機</span> <span class="tag ext">深度 · 外部</span>';
  }

  function localModes() {
    var st = status.local;
    return (st && st.modes) || {};
  }

  /** 每列就緒狀態：reader 身分不能送 AI 請求（gateway POST 一律 403） */
  function readiness(f) {
    if (role() === 'reader') return '<span class="off">僅 Owner</span>';
    if (f.engine === 'cloud') {
      if (status.key == null) return '<span class="off">檢查中</span>';
      if (f.id === 'health' && !status.key.set) return '<span class="warn">規則模板</span>';
      return status.key.set ? '<span class="ok">就緒</span>' : '<span class="warn">未設 Key</span>';
    }
    if (status.local == null) return '<span class="off">檢查中</span>';
    var m = localModes();
    var fast = m.fast && m.fast.available;
    if (f.engine === 'pulse') {
      var deep = m.deep && m.deep.available;
      if (fast && deep) return '<span class="ok">就緒</span>';
      if (fast) return '<span class="ok">快速就緒</span>';
      return deep ? '<span class="warn">僅深度</span>' : '<span class="warn">離線</span>';
    }
    return fast ? '<span class="ok">就緒</span>' : '<span class="warn">離線</span>';
  }

  function ensureMount() {
    injectCSS();
    var panel = $('view-ai');
    if (!panel) return null;
    var mount = $('mount-ai');
    if (!mount) {
      mount = document.createElement('div');
      mount.id = 'mount-ai';
      mount.className = 'sv-mount';
      panel.innerHTML = '';
      panel.appendChild(mount);
    }
    if (!$('ai5-root')) {
      mount.innerHTML =
        '<div id="ai5-root">' +
          '<div class="ai5-head"><div>' +
            '<span class="ai5-title">AI 中樞</span>' +
            '<span class="ai5-sub">全站 AI 功能集中 · 模型與連線狀態</span>' +
          '</div><div class="ai5-actions">' +
            '<button type="button" class="ai5-btn" id="ai5-refresh">↻ 重新整理</button>' +
            '<button type="button" class="ai5-btn" data-go="signals" title="焦點掃描（規則訊號，非 AI）">訊號</button>' +
            '<button type="button" class="ai5-btn primary" data-shell-back>← 儀表板</button>' +
          '</div></div>' +
          '<div id="ai5-body" class="ai5-loading">載入 AI 中樞…</div>' +
        '</div>';
      var r = $('ai5-refresh');
      if (r) r.onclick = function () { refresh(); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () {
          if (window.ShellV5) window.ShellV5.go(b.getAttribute('data-go'));
        };
      });
    }
    return $('ai5-body');
  }

  function stripHtml() {
    var key = status.key;
    var keyV = key == null ? '…' : (key.set ? '已設定' : '未設定');
    var keyCls = key == null ? '' : (key.set ? 'ok' : 'warn');
    var model = status.model && status.model.model ? status.model.model : (key && key.set ? '…' : '—');
    var m = localModes();
    var fast = m.fast || {};
    var deep = m.deep || {};
    var localV = status.local == null ? '…' : (fast.available ? '快速就緒' : '離線');
    var localCls = status.local == null ? '' : (fast.available ? 'ok' : 'warn');
    var localS = (fast.model ? fast.model : 'LM Studio') + (deep.available ? ' · 深度可用' : '');
    var day = status.pmd;
    var pmdV = day && day.date ? day.date : '尚無';
    var pmdS = day && day.date ? ('當日 ' + (day.runs || 0) + ' 次 · $' + Number(day.usdToday || 0).toFixed(3)) : '收盤後手動產生';
    var r = role();
    var roleV = r === 'owner' ? 'Owner' : (r === 'reader' ? 'Reader' : '本機');
    var roleS = r === 'reader' ? 'AI 功能僅 Owner 可執行' : (r === 'owner' ? 'Private Web 遠端' : '完整權限');
    return '<div class="ai5-strip">' +
      '<div class="cell"><div class="k">Claude Key</div><div class="v ' + keyCls + '">' + esc(keyV) + '</div>' +
        '<div class="s">右上 API KEY 設定</div></div>' +
      '<div class="cell"><div class="k">Claude 模型</div><div class="v" style="font-size:11px">' + esc(model) + '</div>' +
        '<div class="s">每日自動取最新 Sonnet</div></div>' +
      '<div class="cell"><div class="k">本機 EVO-T1</div><div class="v ' + localCls + '">' + esc(localV) + '</div>' +
        '<div class="s" title="' + esc(localS) + '">' + esc(localS) + '</div></div>' +
      '<div class="cell"><div class="k">盤後日報</div><div class="v">' + esc(pmdV) + '</div>' +
        '<div class="s">' + esc(pmdS) + '</div></div>' +
      '<div class="cell"><div class="k">權限</div><div class="v">' + esc(roleV) + '</div>' +
        '<div class="s">' + esc(roleS) + '</div></div>' +
    '</div>';
  }

  function render() {
    var body = ensureMount();
    if (!body) return;
    body.className = '';

    var tools =
      '<div class="ai5-tools">' +
        '<button type="button" class="ai5-btn primary" data-ai-open="pmd">盤後日報</button>' +
        '<button type="button" class="ai5-btn" data-ai-open="copilot">本機副駕</button>' +
        '<button type="button" class="ai5-btn" data-ai-open="health">個股體檢白話</button>' +
        '<button type="button" class="ai5-btn" data-ai-open="decision">決策 AI 解釋</button>' +
      '</div>';

    var rows = FEATURES.map(function (f) {
      return '<tr>' +
        '<td class="nm">' + esc(f.name) + '</td>' +
        '<td class="what">' + esc(f.what) + '</td>' +
        '<td class="mdl">' + engineTag(f.engine) + '</td>' +
        '<td class="where">' + esc(f.where) + '</td>' +
        '<td>' + readiness(f) + '</td>' +
        '<td><button type="button" class="ai5-btn" data-ai-open="' + f.id + '">開啟</button></td>' +
      '</tr>';
    }).join('');

    body.innerHTML = tools + stripHtml() +
      '<div class="ai5-dash"><div class="ai5-sec">' +
        '<h4>AI 功能目錄<span style="color:var(--tlo);font-weight:600;font-size:8px">' + FEATURES.length + ' 項</span></h4>' +
        '<div class="ai5-fill"><table>' +
          '<tr><th>功能</th><th>做什麼</th><th>模型</th><th>位置</th><th>狀態</th><th></th></tr>' +
          rows + '</table></div>' +
        '<div class="ai5-note">雲端功能會把所列資料送到 Anthropic；本機功能只在 EVO-T1 執行；「深度」會經 Hermes 送外部模型。' +
          'AI 只整理與解釋既有資料，不構成投資建議。</div>' +
      '</div></div>';

    body.querySelectorAll('[data-ai-open]').forEach(function (b) {
      b.onclick = function () {
        var id = b.getAttribute('data-ai-open');
        for (var i = 0; i < FEATURES.length; i++) {
          if (FEATURES[i].id === id) { FEATURES[i].open(); return; }
        }
      };
    });
  }

  function refresh(opts) {
    opts = opts || {};
    var body = ensureMount();
    if (!body) return;
    if (fetching) return;
    fetching = true;
    if (window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-ai', !!opts.soft, '更新中…');
    }
    render();
    var jobs = [
      jget('/ai-key/status').then(function (d) { status.key = d || { set: false }; render(); }),
      jget('/ai/local/status').then(function (d) { status.local = d || { ok: false, modes: {} }; render(); }),
      jget('/api/ai/postmarket-daily/latest').then(function (d) {
        status.pmd = d && d.date ? d : null;
        render();
      })
    ];
    Promise.all(jobs).then(function () {
      /* /ai-model 可能要連 Anthropic 查最新模型：有 Key 才查，且不擋其他狀態 */
      if (status.key && status.key.set) {
        return jget('/ai-model').then(function (d) { status.model = d; render(); });
      }
    }).finally(function () {
      fetching = false;
      if (window.ShellV5 && window.ShellV5.softBadge) {
        window.ShellV5.softBadge('mount-ai', false);
      }
    });
  }

  function activate() {
    ensureMount();
    refresh({ soft: status.key != null });
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'ai') {
        refresh({ soft: true });
      }
    }, 300000);
  }

  function deactivate() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  window.AiV5 = { activate: activate, deactivate: deactivate, refresh: refresh, features: FEATURES };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'ai') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'ai') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 220); });
  else setTimeout(boot, 220);
})();

/* ============================================================================
 * ai_v5.js  —  Stock Terminal 5.0：AI 中樞側欄
 * ----------------------------------------------------------------------------
 * 薄層中樞：啟動既有 AI 報告／副駕／焦點掃描，不重寫推理邏輯。
 *   openAIModal / copilotOpen / focusScanOpen
 *   GET /focus（摘要）
 * 掛載：#mount-ai；側欄「AI」
 * 工具列 AI 分類鈕 → 導向本室（可再開對應模態）
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var timer = null;
  var lastFocus = null;
  var fetching = false;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
    });
  }

  function injectCSS() {
    if ($('ai-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'ai-v5-css';
    s.textContent =
      '#view-ai.sv-panel{max-width:none!important;padding:10px 12px 12px}' +
      '#ai5-root{font-family:\'JetBrains Mono\',monospace;color:var(--text);' +
        'display:flex;flex-direction:column;flex:1;min-height:0;height:100%}' +
      '#ai5-root .ai5-head{display:flex;align-items:flex-end;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px;flex-shrink:0}' +
      '#ai5-root .ai5-kicker{font-size:10px;color:var(--gold);letter-spacing:2px;margin-bottom:2px}' +
      '#ai5-root .ai5-title{font-family:\'Noto Serif TC\',serif;font-size:22px;font-weight:700;color:var(--thi)}' +
      '#ai5-root .ai5-sub{font-size:11px;color:var(--tlo);margin-top:3px}' +
      '#ai5-root .ai5-actions{display:flex;gap:6px;flex-wrap:wrap}' +
      '#ai5-root .ai5-btn{padding:5px 10px;border:1px solid var(--border);border-radius:5px;background:var(--bg3);' +
        'color:var(--text);font-size:10px;font-family:inherit;cursor:pointer}' +
      '#ai5-root .ai5-btn:hover{border-color:var(--bhi);color:var(--thi)}' +
      '#ai5-root .ai5-btn.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}' +
      '#ai5-root .ai5-btn.primary:hover{background:#FBBF24}' +
      '#ai5-root .ai5-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:8px 0;flex-shrink:0}' +
      '#ai5-root .ai5-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px 14px;' +
        'display:flex;flex-direction:column;gap:6px;min-height:120px}' +
      '#ai5-root .ai5-card h4{margin:0;font-size:12px;color:var(--gold)}' +
      '#ai5-root .ai5-card p{margin:0;font-size:10px;color:var(--tlo);line-height:1.55;flex:1}' +
      '#ai5-root .ai5-card .ai5-go{align-self:flex-start}' +
      '#ai5-root .ai5-sec{margin-top:8px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;' +
        'padding:10px 12px;flex:1;min-height:0;overflow:auto}' +
      '#ai5-root .ai5-sec h4{margin:0 0 8px;font-size:11px;color:var(--gold)}' +
      '#ai5-root .ai5-stat{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px}' +
      '#ai5-root .ai5-cell{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 10px}' +
      '#ai5-root .ai5-cell .k{font-size:9px;color:var(--tlo)}' +
      '#ai5-root .ai5-cell .v{font-size:13px;font-weight:700;color:var(--thi);margin-top:3px}' +
      '#ai5-root table{width:100%;border-collapse:collapse;font-size:11px}' +
      '#ai5-root th,#ai5-root td{padding:4px 6px;border-bottom:1px solid var(--border);text-align:left}' +
      '#ai5-root th{color:var(--tlo)}' +
      '#ai5-root tr.ai5-row{cursor:pointer}#ai5-root tr.ai5-row:hover{background:var(--bg3)}' +
      '#ai5-root .up{color:var(--red)}#ai5-root .dn{color:var(--green)}' +
      '#ai5-root .ai5-note{font-size:9px;color:var(--tlo);line-height:1.6;margin-top:8px}' +
      '#ai5-root .ai5-loading{font-size:11px;color:var(--tlo);padding:16px 0}' +
      '@media (max-width:900px){#ai5-root .ai5-grid,#ai5-root .ai5-stat{grid-template-columns:1fr}}';
    document.head.appendChild(s);
  }

  function openChart(code, mkt) {
    if (code && typeof loadSym === 'function') {
      if (window.ShellV5 && ShellV5.openChart) ShellV5.openChart(code, mkt || 'TW');
      else {
        loadSym(code, mkt || 'TW');
        if (window.ShellV5) window.ShellV5.go('chart');
      }
    }
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
            '<div class="ai5-kicker">STOCK TERMINAL · 5.0</div>' +
            '<div class="ai5-title">AI</div>' +
            '<div class="ai5-sub">報告 · 本機副駕 · 焦點掃描 — 中樞入口（邏輯仍在既有模組）</div>' +
          '</div><div class="ai5-actions">' +
            '<button type="button" class="ai5-btn" id="ai5-refresh">↻ 重新整理</button>' +
            '<button type="button" class="ai5-btn" data-go="signals">訊號</button>' +
            '<button type="button" class="ai5-btn primary" data-shell-back>← 圖表</button>' +
          '</div></div>' +
          '<div id="ai5-body" class="ai5-loading">載入 AI 中樞…</div>' +
        '</div>';
      var r = $('ai5-refresh');
      if (r) r.onclick = function () { refresh({ force: true }); };
      var sg = mount.querySelector('[data-go="signals"]');
      if (sg) sg.onclick = function () {
        if (window.ShellV5) window.ShellV5.go('signals');
      };
    }
    return $('ai5-body');
  }

  function keyStatus() {
    try {
      if (localStorage.getItem('claude_api_key') || localStorage.getItem('ai_key') ||
          localStorage.getItem('ANTHROPIC_API_KEY')) {
        return '瀏覽器已存 Key';
      }
    } catch (e) {}
    return '未偵測瀏覽器 Key（可用後端 data/ai_key.txt）';
  }

  function lastReportStamp() {
    try {
      var saved = JSON.parse(localStorage.getItem('ai_report_last') || 'null');
      return saved && saved.stamp ? saved.stamp : '尚無報告';
    } catch (e) { return '尚無報告'; }
  }

  function pickLists(focus) {
    focus = focus || {};
    var longs = (focus.long || focus.bull || focus.longs || []).slice();
    var shorts = (focus.short || focus.bear || focus.shorts || []).slice();
    if (focus.focus) {
      longs = (focus.focus.long || longs).slice();
      shorts = (focus.focus.short || shorts).slice();
    }
    if (!longs.length && !shorts.length && Array.isArray(focus.list)) {
      focus.list.forEach(function (r) {
        var side = String(r.side || r.dir || r.bias || '');
        if (/空|short|bear|sell/i.test(side) || (r.score != null && r.score < 0)) shorts.push(r);
        else longs.push(r);
      });
    }
    return { longs: longs.slice(0, 8), shorts: shorts.slice(0, 8) };
  }

  function render(focus) {
    var body = ensureMount();
    if (!body) return;
    if (focus && typeof focus === 'object') lastFocus = focus;
    var lists = pickLists(lastFocus || {});
    var longs = lists.longs;
    var shorts = lists.shorts;

    var html =
      '<div class="ai5-grid">' +
        '<div class="ai5-card"><h4>Claude AI 報告</h4>' +
          '<p>八章節盤前報告，帶入持倉／觀察／大盤。Key 只存本機。</p>' +
          '<div class="ai5-note">上次：' + esc(lastReportStamp()) + '</div>' +
          '<button type="button" class="ai5-btn primary ai5-go" id="ai5-report">開啟報告</button></div>' +
        '<div class="ai5-card"><h4>AI 副駕</h4>' +
          '<p>本機 LM Studio（OpenAI 相容 SSE）。自動附上當前個股與持倉 context。</p>' +
          '<div class="ai5-note">需另開 LM Studio 並載入模型</div>' +
          '<button type="button" class="ai5-btn primary ai5-go" id="ai5-copilot">開啟副駕</button></div>' +
        '<div class="ai5-card"><h4>焦點掃描</h4>' +
          '<p>多訊號組合自動找做多／做空焦點。完整表單開模態；摘要見下方。</p>' +
          '<div class="ai5-note">亦可從側欄「訊號」看完整表</div>' +
          '<button type="button" class="ai5-btn primary ai5-go" id="ai5-focus">開啟掃描</button></div>' +
      '</div>';

    html += '<div class="ai5-sec"><h4>狀態與焦點摘要</h4><div class="ai5-stat">' +
      '<div class="ai5-cell"><div class="k">Claude Key</div><div class="v" style="font-size:11px">' + esc(keyStatus()) + '</div></div>' +
      '<div class="ai5-cell"><div class="k">做多焦點</div><div class="v">' + longs.length + '</div></div>' +
      '<div class="ai5-cell"><div class="k">做空焦點</div><div class="v">' + shorts.length + '</div></div>' +
      '</div>';

    function tbl(list, title, cls) {
      if (!list.length) return '<div class="ai5-note">' + title + '：暫無（請開焦點掃描）</div>';
      return '<div style="margin-top:8px"><div class="ai5-note" style="margin:0 0 4px">' + title + '</div>' +
        '<table><tr><th>代號</th><th>名稱</th><th>訊號</th></tr>' +
        list.map(function (x) {
          var code = x.code || x.sym || x.ticker || '';
          var name = x.name || x.zh || '';
          var sig = x.signal || x.reason || x.score || x.tag || '—';
          return '<tr class="ai5-row" data-code="' + esc(code) + '"><td class="' + cls + '">' + esc(code) +
            '</td><td>' + esc(name) + '</td><td>' + esc(String(sig)) + '</td></tr>';
        }).join('') + '</table></div>';
    }

    html += tbl(longs, '做多焦點', 'up') + tbl(shorts, '做空焦點', 'dn');
    html += '<div class="ai5-note">AI 中樞不取代工具列 AI 分類；完整互動仍走既有模態。⚠ 模型輸出非投資建議。</div></div>';

    body.innerHTML = html;

    var br = $('ai5-report');
    if (br) br.onclick = function () {
      if (typeof window.openAIModal === 'function') window.openAIModal();
    };
    var bc = $('ai5-copilot');
    if (bc) bc.onclick = function () {
      if (typeof window.copilotOpen === 'function') window.copilotOpen();
    };
    var bf = $('ai5-focus');
    if (bf) bf.onclick = function () {
      if (typeof window.focusScanOpen === 'function') window.focusScanOpen();
    };
    body.querySelectorAll('tr.ai5-row').forEach(function (el) {
      el.onclick = function () { openChart(el.getAttribute('data-code')); };
    });
  }

  function refresh(opts) {
    opts = opts || {};
    var body = ensureMount();
    if (!body) return;
    var soft = !!opts.soft || !!body.querySelector('.ai5-grid');
    if (fetching && soft) return;
    fetching = true;
    if (window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-ai', soft, '更新中…');
    }
    if (!soft) body.innerHTML = '<div class="ai5-loading">載入 AI 中樞…</div>';

    fetch(SRV + '/focus', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; })
      .then(function (d) { render(d); })
      .finally(function () {
        fetching = false;
        if (window.ShellV5 && window.ShellV5.softBadge) {
          window.ShellV5.softBadge('mount-ai', false);
        }
      });
  }

  function activate() {
    ensureMount();
    refresh({ soft: !!lastFocus });
    if (timer) clearInterval(timer);
    timer = setInterval(function () {
      if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'ai') {
        refresh({ soft: true });
      }
    }, 120000);
  }

  function deactivate() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  /** 工具列進來：先到中樞，再開對應模態 */
  function goAndOpen(openFn) {
    if (window.ShellV5 && typeof window.ShellV5.go === 'function') {
      window.ShellV5.go('ai');
      setTimeout(function () {
        if (typeof openFn === 'function') openFn();
      }, 80);
      return true;
    }
    return false;
  }

  window.AiV5 = {
    activate: activate,
    deactivate: deactivate,
    refresh: refresh,
    goAndOpen: goAndOpen
  };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'ai') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'ai') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 280); });
  else setTimeout(boot, 280);
})();

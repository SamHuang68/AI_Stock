/* ============================================================================
 * ai_v5.js  —  Stock Terminal 5.0：AI 中樞側欄
 * ----------------------------------------------------------------------------
 * 專業終端版面：KPI strip + 做多／做空雙欄 + 緊湊工具列（開既有模態）
 *   openAIModal / copilotOpen / focusScanOpen
 *   GET /focus（欄位：buy / short / scanned）
 * 掛載：#mount-ai；側欄「AI」
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
      '#ai5-root .ai5-strip .v{font-size:15px;font-weight:800;color:var(--thi);line-height:1.15;' +
        'overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '#ai5-root .ai5-strip .s{font-size:10px;color:var(--tlo);margin-top:0;line-height:1.2}' +
      '#ai5-root .ai5-tools{display:flex;gap:4px;flex-wrap:wrap;margin:0 0 4px;flex:0 0 auto}' +
      '#ai5-root .ai5-dash{flex:1;min-height:0;display:grid;gap:4px;grid-template-columns:minmax(0,1fr) minmax(0,1fr);' +
        'grid-template-rows:minmax(0,1fr);align-items:stretch}' +
      '#ai5-root .ai5-sec{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:5px 7px;' +
        'min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;height:100%}' +
      '#ai5-root .ai5-sec h4{margin:0 0 4px;font-size:10px;color:var(--gold);letter-spacing:.5px;flex:0 0 auto;' +
        'display:flex;justify-content:space-between;align-items:center;gap:6px}' +
      '#ai5-root .ai5-fill{flex:1;min-height:0;overflow:auto}' +
      '#ai5-root table{width:100%;border-collapse:collapse;font-size:10px}' +
      '#ai5-root th,#ai5-root td{padding:3px 4px;border-bottom:1px solid var(--border);text-align:right}' +
      '#ai5-root th:first-child,#ai5-root td:first-child,#ai5-root th:nth-child(2),#ai5-root td:nth-child(2),' +
      '#ai5-root th:nth-child(4),#ai5-root td:nth-child(4){text-align:left}' +
      '#ai5-root th{color:var(--tlo);font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1}' +
      '#ai5-root tr.ai5-row{cursor:pointer}#ai5-root tr.ai5-row:hover{background:var(--bg3)}' +
      '#ai5-root .up{color:var(--red)}#ai5-root .dn{color:var(--green)}#ai5-root .flat{color:var(--tlo)}' +
      '#ai5-root .ai5-note{font-size:10px;color:var(--tlo);line-height:1.4;margin-top:2px;flex:0 0 auto}' +
      '#ai5-root .ai5-empty{font-size:10px;color:var(--tlo);padding:16px 8px;text-align:center}' +
      '#ai5-root .ai5-loading{font-size:10px;color:var(--tlo);padding:12px 0}';
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

  function keyStatus() {
    try {
      if (localStorage.getItem('claude_api_key') || localStorage.getItem('ai_key') ||
          localStorage.getItem('ANTHROPIC_API_KEY')) {
        return '本機 Key 已存';
      }
    } catch (e) {}
    return '未偵測 Key';
  }

  function lastReportStamp() {
    try {
      var saved = JSON.parse(localStorage.getItem('ai_report_last') || 'null');
      return saved && saved.stamp ? saved.stamp : '尚無報告';
    } catch (e) { return '尚無報告'; }
  }

  /** 對齊 /focus：buy / short（heat_v5 同契約）；相容舊別名 */
  function pickLists(focus) {
    focus = focus || {};
    var longs = (focus.buy || focus.long || focus.bull || focus.longs || []).slice();
    var shorts = (focus.short || focus.bear || focus.shorts || []).slice();
    if (focus.focus) {
      longs = (focus.focus.buy || focus.focus.long || longs).slice();
      shorts = (focus.focus.short || shorts).slice();
    }
    if (!longs.length && !shorts.length && Array.isArray(focus.list)) {
      focus.list.forEach(function (r) {
        var side = String(r.side || r.dir || r.bias || '');
        if (/空|short|bear|sell/i.test(side) || (r.score != null && r.score < 0)) shorts.push(r);
        else longs.push(r);
      });
    }
    return { longs: longs, shorts: shorts, scanned: focus.scanned };
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
            '<span class="ai5-title">AI</span>' +
            '<span class="ai5-sub">焦點掃描摘要 · 報告／副駕入口</span>' +
          '</div><div class="ai5-actions">' +
            '<button type="button" class="ai5-btn" id="ai5-refresh">↻ 重新整理</button>' +
            '<button type="button" class="ai5-btn" data-go="signals">訊號</button>' +
            '<button type="button" class="ai5-btn" data-go="scan">選股</button>' +
            '<button type="button" class="ai5-btn primary" data-shell-back>← 儀表板</button>' +
          '</div></div>' +
          '<div id="ai5-body" class="ai5-loading">載入 AI 中樞…</div>' +
        '</div>';
      var r = $('ai5-refresh');
      if (r) r.onclick = function () { refresh({ force: true }); };
      mount.querySelectorAll('[data-go]').forEach(function (b) {
        b.onclick = function () {
          if (window.ShellV5) window.ShellV5.go(b.getAttribute('data-go'));
        };
      });
    }
    return $('ai5-body');
  }

  function rowOf(x, cls) {
    var V = window.Viz;
    var code = x.code || x.sym || x.ticker || '';
    var name = x.name || x.zh || '';
    var score = x.score != null ? x.score : (x.confidence != null ? x.confidence : null);
    var sig = '';
    if (Array.isArray(x.signals) && x.signals.length) sig = x.signals.slice(0, 3).join(' · ');
    else sig = x.signal || x.reason || x.tag || '—';
    var scoreCell = '—';
    if (score != null && isFinite(score)) {
      var meterScore = Math.abs(score) <= 1 ? score * 100 : Math.max(0, Math.min(100, Math.abs(score)));
      scoreCell = (score >= 0 ? '+' : '') + Number(score).toFixed(1);
      if (V) scoreCell += V.scoreMeter(meterScore);
    }
    return '<tr class="ai5-row" data-code="' + esc(code) + '">' +
      '<td class="' + cls + '" style="font-weight:700">' + esc(code) + '</td>' +
      '<td>' + esc(name) + '</td>' +
      '<td>' + scoreCell + '</td>' +
      '<td style="color:var(--tlo)">' + esc(String(sig)) + '</td></tr>';
  }

  function render(focus) {
    var body = ensureMount();
    if (!body) return;
    if (focus && typeof focus === 'object') lastFocus = focus;
    var lists = pickLists(lastFocus || {});
    var longs = lists.longs || [];
    var shorts = lists.shorts || [];
    var scanned = lists.scanned != null ? lists.scanned : '—';

    var tools =
      '<div class="ai5-tools">' +
        '<button type="button" class="ai5-btn primary" id="ai5-focus">焦點掃描</button>' +
        '<button type="button" class="ai5-btn" id="ai5-report">Claude 報告</button>' +
        '<button type="button" class="ai5-btn" id="ai5-copilot">本機副駕</button>' +
      '</div>';

    var strip =
      '<div class="ai5-strip">' +
        '<div class="cell"><div class="k">Claude Key</div><div class="v" style="font-size:11px">' + esc(keyStatus()) + '</div>' +
          '<div class="s">報告：' + esc(lastReportStamp()) + '</div></div>' +
        '<div class="cell"><div class="k">掃描檔數</div><div class="v">' + esc(String(scanned)) + '</div>' +
          '<div class="s">GET /focus</div></div>' +
        '<div class="cell"><div class="k">做多焦點</div><div class="v up">' + longs.length + '</div>' +
          '<div class="s">buy</div></div>' +
        '<div class="cell"><div class="k">做空焦點</div><div class="v dn">' + shorts.length + '</div>' +
          '<div class="s">short</div></div>' +
        '<div class="cell"><div class="k">合計</div><div class="v">' + (longs.length + shorts.length) + '</div>' +
          '<div class="s">點列開圖表</div></div>' +
      '</div>';

    function tbl(list, title, cls) {
      var h = '<div class="ai5-sec"><h4>' + title + '<span style="color:var(--tlo);font-weight:600;font-size:8px">' +
        list.length + ' 檔</span></h4><div class="ai5-fill">';
      if (!list.length) {
        return h + '<div class="ai5-empty">暫無 — 按「焦點掃描」或側欄「訊號」</div></div>' +
          '<div class="ai5-note">多訊號組合 · 非投資建議</div></div>';
      }
      h += '<table><tr><th>代號</th><th>名稱</th><th>分數</th><th>訊號</th></tr>' +
        list.slice(0, 40).map(function (x) { return rowOf(x, cls); }).join('') + '</table>';
      return h + '</div><div class="ai5-note">點列載入線型</div></div>';
    }

    body.innerHTML = tools + strip +
      '<div class="ai5-dash">' +
        tbl(longs, '做多焦點', 'up') +
        tbl(shorts, '做空焦點', 'dn') +
      '</div>';

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
    var soft = !!opts.soft || !!body.querySelector('.ai5-strip, .ai5-dash');
    if (fetching && soft) return;
    fetching = true;
    if (window.ShellV5 && window.ShellV5.softBadge) {
      window.ShellV5.softBadge('mount-ai', soft, '更新中…');
    }
    if (!soft) body.innerHTML = '<div class="ai5-loading">載入 AI 中樞…</div>';

    var url = SRV + '/focus' + (opts.force ? '?refresh=1' : '');
    fetch(url, { cache: 'no-store' })
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

  window.AiV5 = { activate: activate, deactivate: deactivate, refresh: refresh };

  window.addEventListener('shell:route', function (ev) {
    if (ev && ev.detail && ev.detail.route === 'ai') activate();
  });

  function boot() {
    if (window.ShellV5 && window.ShellV5.route && window.ShellV5.route() === 'ai') activate();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 220); });
  else setTimeout(boot, 220);
})();

/* ============================================================================
 * postmarket_v5.js — 自選股盤後敘事日報（POST /api/ai/postmarket-daily）
 * ----------------------------------------------------------------------------
 * 報告產物 UI：掛在既有 AI 中樞（ai_v5「盤後日報」鈕）開啟小型 report drawer。
 * - 數字全由 server EvidencePack 算好；Claude 只整理敘事（紅線見 docs/POSTMARKET_DAILY.md）
 * - 顯示每檔結論（可展開 drivers/hypotheses/risks/watchTomorrow）與各 evidence asOf
 * - 顯示 usage.estUsd 與當日累計；複製 Markdown；server 端已存 data/reports/postmarket/
 * - 支援中止（AbortController + abortSignalClientId）
 * ========================================================================== */
(function () {
  'use strict';

  var SRV = window.SERVER || '';
  var controller = null;
  var clientId = null;
  var running = false;
  var lastReport = null;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function toast(title, body, level) {
    if (typeof window.notifyToast === 'function') {
      window.notifyToast(title, body || '', { level: level || 'info', skipDesktop: true });
    }
  }

  function injectCSS() {
    if ($('pmd-v5-css')) return;
    var s = document.createElement('style');
    s.id = 'pmd-v5-css';
    s.textContent =
      '#pmd-modal{position:fixed;inset:0;z-index:9600;background:rgba(4,8,16,.72);display:flex;' +
        'align-items:center;justify-content:center;font-family:\'JetBrains Mono\',monospace}' +
      '#pmd-box{width:min(880px,94vw);max-height:92vh;display:flex;flex-direction:column;' +
        'background:var(--bg2,#0B1220);border:1px solid var(--border,#233);border-radius:8px;' +
        'color:var(--text,#cdd6e4);box-shadow:0 18px 48px rgba(0,0,0,.55)}' +
      '#pmd-box h3{margin:0;padding:9px 12px;font-size:13px;color:var(--gold,#F5C451);' +
        'font-family:\'Noto Serif TC\',serif;border-bottom:1px solid var(--border,#233);' +
        'display:flex;justify-content:space-between;align-items:center;gap:8px}' +
      '#pmd-box .pmd-x{cursor:pointer;color:var(--tlo,#8a94a6);font-size:15px;background:none;border:none}' +
      '#pmd-ctl{padding:8px 12px;border-bottom:1px solid var(--border,#233);display:flex;' +
        'flex-wrap:wrap;gap:6px;align-items:center;font-size:11px;flex:0 0 auto}' +
      '#pmd-syms{flex:1;min-width:220px;background:var(--bg3,#111B2E);color:var(--text,#cdd6e4);' +
        'border:1px solid var(--border,#233);border-radius:4px;padding:4px 6px;font:inherit;font-size:11px}' +
      '#pmd-ctl label{display:flex;align-items:center;gap:3px;color:var(--tlo,#8a94a6);white-space:nowrap}' +
      '#pmd-ctl select{background:var(--bg3,#111B2E);color:var(--text,#cdd6e4);' +
        'border:1px solid var(--border,#233);border-radius:4px;font:inherit;font-size:11px;padding:2px 4px}' +
      '.pmd-btn{padding:4px 10px;border:1px solid var(--border,#233);border-radius:4px;' +
        'background:var(--bg3,#111B2E);color:var(--text,#cdd6e4);font:inherit;font-size:11px;cursor:pointer;white-space:nowrap}' +
      '.pmd-btn:hover{border-color:var(--bhi,#3d4c66);color:var(--thi,#f2f5fa)}' +
      '.pmd-btn.primary{background:var(--gold,#F5C451);color:#060A12;border:none;font-weight:700}' +
      '.pmd-btn.warn{color:var(--red,#ff7a76)}' +
      '.pmd-btn:disabled{opacity:.45;cursor:not-allowed}' +
      '#pmd-status{padding:4px 12px;font-size:10px;color:var(--tlo,#8a94a6);flex:0 0 auto}' +
      '#pmd-out{flex:1;min-height:120px;overflow:auto;padding:8px 12px}' +
      '.pmd-card{border:1px solid var(--border,#233);border-radius:6px;background:var(--bg3,#111B2E);' +
        'padding:8px 10px;margin-bottom:8px}' +
      '.pmd-card .pmd-sym{font-size:13px;font-weight:800;color:var(--thi,#f2f5fa)}' +
      '.pmd-card .pmd-name{font-size:11px;color:var(--tlo,#8a94a6);margin-left:6px}' +
      '.pmd-badge{display:inline-block;margin-left:8px;padding:1px 6px;border-radius:8px;font-size:9px;' +
        'border:1px solid var(--red,#ff7a76);color:var(--red,#ff7a76)}' +
      '.pmd-asof{font-size:9px;color:var(--tlo,#8a94a6);margin:3px 0 5px;line-height:1.5}' +
      '.pmd-conc{font-size:12px;line-height:1.6;color:var(--text,#cdd6e4);margin:2px 0 4px}' +
      '.pmd-card details{margin:3px 0;font-size:11px}' +
      '.pmd-card summary{cursor:pointer;color:var(--gold,#F5C451);font-size:10px;letter-spacing:.4px}' +
      '.pmd-card ul{margin:3px 0 4px;padding-left:18px}' +
      '.pmd-card li{margin:2px 0;line-height:1.55}' +
      '.pmd-err{color:var(--red,#ff7a76);font-size:11px}' +
      '.pmd-note{color:var(--tlo,#8a94a6);font-size:10px;margin-top:3px}' +
      '#pmd-foot{padding:7px 12px;border-top:1px solid var(--border,#233);display:flex;flex-wrap:wrap;' +
        'gap:8px;align-items:center;font-size:10px;color:var(--tlo,#8a94a6);flex:0 0 auto}' +
      '#pmd-usage{flex:1;min-width:180px}' +
      '.pmd-blurb{font-size:11px;color:var(--thi,#f2f5fa);border-left:2px solid var(--gold,#F5C451);' +
        'padding:4px 8px;margin-bottom:8px;background:var(--bg3,#111B2E)}';
    document.head.appendChild(s);
  }

  /** 自選股來源：st_wl（同 pulse_v5.readWatchlist 契約），僅台股、上限 20 檔 */
  function readWatchlist() {
    var out = [];
    try {
      var arr = JSON.parse(localStorage.getItem('st_wl') || '[]');
      if (Array.isArray(arr)) {
        arr.forEach(function (x) {
          if (x && x.t && (!x.m || x.m === 'TW') && out.indexOf(x.t) < 0) out.push(String(x.t));
        });
      }
    } catch (e) {}
    return out.slice(0, 20);
  }

  function parseSymbols() {
    var raw = ($('pmd-syms') && $('pmd-syms').value) || '';
    var out = [];
    raw.split(/[\s,;、，]+/).forEach(function (tok) {
      var code = tok.trim().toUpperCase();
      if (code && /^[0-9A-Z]{2,10}$/.test(code) && out.indexOf(code) < 0) out.push(code);
    });
    return out;
  }

  function fmtUsd(v) {
    return (v == null || isNaN(v)) ? '—' : ('$' + Number(v).toFixed(4));
  }

  function asOfLine(asOf) {
    var order = [['quote', '報價'], ['tech', '技術'], ['chips', '籌碼'], ['news', '新聞'], ['decision', 'Decision']];
    var parts = [];
    order.forEach(function (pair) {
      if (asOf && asOf[pair[0]]) parts.push(pair[1] + ' asOf ' + esc(String(asOf[pair[0]])));
    });
    return parts.length ? parts.join(' ｜ ') : '無 evidence asOf';
  }

  function listBlock(title, items, open) {
    if (!items || !items.length) return '';
    return '<details' + (open ? ' open' : '') + '><summary>' + esc(title) + '（' + items.length + '）</summary><ul>' +
      items.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></details>';
  }

  function render(report) {
    lastReport = report || null;
    var out = $('pmd-out');
    if (!out) return;
    if (!report || !Array.isArray(report.symbols)) {
      out.innerHTML = '<div class="pmd-note">尚無報告 — 輸入代號後按「產生日報」。</div>';
      renderUsage(null);
      return;
    }
    var html = '';
    if (report.marketBlurb) html += '<div class="pmd-blurb">大盤：' + esc(report.marketBlurb) + '</div>';
    if (report.partial) html += '<div class="pmd-err">⚠ 本次為部分結果（WaveDeck gate 先行或上游中斷）</div>';
    if (report.aborted) html += '<div class="pmd-err">⚠ 已依要求中止，僅保留已完成檔數</div>';
    report.symbols.forEach(function (row) {
      var nar = row.narrative;
      html += '<div class="pmd-card"><div><span class="pmd-sym">' + esc(row.symbol) + '</span>';
      if (row.stale) html += '<span class="pmd-badge">資料可能過期</span>';
      html += '</div><div class="pmd-asof">' + asOfLine(row.evidenceAsOf) + '</div>';
      if (row.error) {
        html += '<div class="pmd-err">✕ ' + esc(row.error) + '</div>';
      } else if (nar) {
        html += '<div class="pmd-conc">' + esc(nar.conclusion || '') + '</div>' +
          listBlock('Drivers 驅動', nar.drivers, true) +
          listBlock('Hypotheses 假說', nar.hypotheses) +
          listBlock('Risks 風險', nar.risks) +
          listBlock('明日觀察', nar.watchTomorrow);
        if (row.citations && row.citations.length) {
          html += '<div class="pmd-note">citations：' + row.citations.map(function (c) {
            return esc(c.type + ':' + c.ref);
          }).join('；') + '</div>';
        }
        if (row.guardrail && row.guardrail.length) {
          html += '<div class="pmd-note">guardrail：' + esc(row.guardrail.join('；')) + '</div>';
        }
      }
      if (row.notes && row.notes.length) {
        html += '<div class="pmd-note">' + esc(row.notes.join('；')) + '</div>';
      }
      html += '</div>';
    });
    out.innerHTML = html || '<div class="pmd-note">回應內無 symbols。</div>';
    renderUsage(report);
  }

  function renderUsage(report) {
    var el = $('pmd-usage');
    if (!el) return;
    if (!report || !report.usage) { el.textContent = ''; return; }
    var u = report.usage;
    var text = 'model ' + (report.model || '—') +
      ' ｜ tokens ' + (u.inputTokens || 0) + ' in / ' + (u.outputTokens || 0) + ' out' +
      ' ｜ 本次 ' + fmtUsd(u.estUsd);
    if (report.usageToday) {
      text += ' ｜ 今日累計 ' + fmtUsd(report.usageToday.estUsd) +
        '（' + (report.usageToday.runs || 1) + ' 次）';
    }
    if (report.savedTo) text += ' ｜ 已存 data/reports/postmarket/';
    el.textContent = text;
  }

  function toMarkdown(report) {
    if (!report) return '';
    var lines = ['# 盤後敘事日報 ' + (report.generatedAt || ''), ''];
    lines.push('- reportId: ' + (report.reportId || '—'));
    lines.push('- model: ' + (report.model || '—'));
    if (report.usage) {
      lines.push('- usage: ' + (report.usage.inputTokens || 0) + ' in / ' +
        (report.usage.outputTokens || 0) + ' out / est ' + fmtUsd(report.usage.estUsd));
    }
    if (report.marketBlurb) { lines.push('', '> 大盤：' + report.marketBlurb); }
    (report.symbols || []).forEach(function (row) {
      lines.push('', '## ' + row.symbol + (row.stale ? '（資料可能過期）' : ''));
      var asOf = row.evidenceAsOf || {};
      var asParts = [];
      Object.keys(asOf).forEach(function (k) { if (asOf[k]) asParts.push(k + '=' + asOf[k]); });
      if (asParts.length) lines.push('- evidence asOf: ' + asParts.join(', '));
      if (row.error) { lines.push('- 錯誤: ' + row.error); return; }
      var nar = row.narrative || {};
      if (nar.conclusion) lines.push('', nar.conclusion);
      [['drivers', '驅動'], ['hypotheses', '假說'], ['risks', '風險'], ['watchTomorrow', '明日觀察']]
        .forEach(function (pair) {
          var items = nar[pair[0]] || [];
          if (!items.length) return;
          lines.push('', '### ' + pair[1]);
          items.forEach(function (x) { lines.push('- ' + x); });
        });
    });
    lines.push('', '（敘事由 Claude 整理；數字均出自 Stock Terminal EvidencePack，非投資建議）');
    return lines.join('\n');
  }

  function copyText(text, done) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }).catch(function () { done(false); });
      return;
    }
    try {
      var area = document.createElement('textarea');
      area.value = text;
      document.body.appendChild(area);
      area.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(area);
      done(!!ok);
    } catch (e) { done(false); }
  }

  function setStatus(msg, isErr) {
    var el = $('pmd-status');
    if (el) {
      el.textContent = msg || '';
      el.style.color = isErr ? 'var(--red,#ff7a76)' : 'var(--tlo,#8a94a6)';
    }
  }

  function setRunning(on) {
    running = !!on;
    if ($('pmd-run')) $('pmd-run').disabled = running;
    if ($('pmd-abort')) $('pmd-abort').disabled = !running;
  }

  function run() {
    if (running) return;
    var symbols = parseSymbols();
    if (!symbols.length) { setStatus('請輸入至少一檔台股代號', true); return; }
    if (symbols.length > 20) { setStatus('最多 20 檔（v1 批次上限）', true); return; }
    clientId = 'pmd-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    controller = (typeof AbortController === 'function') ? new AbortController() : null;
    setRunning(true);
    setStatus('產生中… ' + symbols.length + ' 檔（concurrency 1，請稍候）');
    var payload = {
      asOf: new Date().toISOString(),
      symbols: symbols,
      locale: 'zh-Hant-TW',
      modelHint: ($('pmd-model') && $('pmd-model').value) || 'sonnet',
      include: {
        quotes: true,
        techSummary: true,
        chips: !!($('pmd-inc-chips') && $('pmd-inc-chips').checked),
        news: !!($('pmd-inc-news') && $('pmd-inc-news').checked),
        decisionSummary: !!($('pmd-inc-dc') && $('pmd-inc-dc').checked),
        macro: !!($('pmd-inc-macro') && $('pmd-inc-macro').checked)
      },
      maxNewsPerSymbol: 5,
      abortSignalClientId: clientId
    };
    fetch(SRV + '/api/ai/postmarket-daily', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller ? controller.signal : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        return { status: r.status, retryAfter: r.headers.get('Retry-After'), data: d };
      });
    }).then(function (res) {
      if (res.status === 503) {
        setStatus('WaveDeck 推論優先中（503）' +
          (res.retryAfter ? '，約 ' + res.retryAfter + 's 後再試' : '') +
          ' — 不會自動改打本機 deep', true);
        return;
      }
      if (res.status >= 400) {
        setStatus('失敗 HTTP ' + res.status + '：' + (res.data && res.data.error || ''), true);
        return;
      }
      render(res.data);
      setStatus('完成 ' + ((res.data.symbols || []).filter(function (s) { return s.narrative; }).length) +
        '/' + (res.data.symbols || []).length + ' 檔' +
        (res.data.savedTo ? ' ｜ 已存本機 JSON' : ''));
      toast('盤後日報完成', '本次 ' + fmtUsd((res.data.usage || {}).estUsd));
    }).catch(function (e) {
      if (e && e.name === 'AbortError') setStatus('已中止', true);
      else setStatus('連線失敗：' + (e && e.message || e), true);
    }).finally(function () {
      setRunning(false);
      controller = null;
    });
  }

  function abortRun() {
    if (!running) return;
    if (clientId) {
      fetch(SRV + '/api/ai/postmarket-daily/abort', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ abortSignalClientId: clientId })
      }).catch(function () {});
    }
    if (controller) controller.abort();
  }

  function loadLatest() {
    fetch(SRV + '/api/ai/postmarket-daily/latest', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (day) {
        if (day && day.latest) {
          render(day.latest);
          setStatus('顯示上次報告（' + (day.date || '') + '，當日累計 ' + fmtUsd(day.usdToday) + '）');
        }
      })
      .catch(function () {});
  }

  function close() {
    var m = $('pmd-modal');
    if (m) m.remove();
  }

  function open() {
    injectCSS();
    if ($('pmd-modal')) { $('pmd-modal').style.display = 'flex'; return; }
    var wrap = document.createElement('div');
    wrap.id = 'pmd-modal';
    wrap.innerHTML =
      '<div id="pmd-box">' +
        '<h3>盤後敘事日報 <span style="font-size:9px;color:var(--tlo,#8a94a6)">Claude 整理敘事 · 數字出自 ST EvidencePack · 非投資建議</span>' +
          '<button type="button" class="pmd-x" id="pmd-close">✕</button></h3>' +
        '<div id="pmd-ctl">' +
          '<input id="pmd-syms" placeholder="台股代號，逗號或空白分隔（預設帶入自選股）">' +
          '<label><input type="checkbox" id="pmd-inc-chips" checked>籌碼</label>' +
          '<label><input type="checkbox" id="pmd-inc-news" checked>新聞</label>' +
          '<label><input type="checkbox" id="pmd-inc-dc" checked>Decision</label>' +
          '<label><input type="checkbox" id="pmd-inc-macro">大盤一句話</label>' +
          '<label>model <select id="pmd-model">' +
            '<option value="sonnet" selected>sonnet（預設）</option>' +
            '<option value="opus">opus（opt-in，較燒額度）</option>' +
          '</select></label>' +
          '<button type="button" class="pmd-btn primary" id="pmd-run">產生日報</button>' +
          '<button type="button" class="pmd-btn warn" id="pmd-abort" disabled>中止</button>' +
        '</div>' +
        '<div id="pmd-status"></div>' +
        '<div id="pmd-out"><div class="pmd-note">尚無報告 — 輸入代號後按「產生日報」。</div></div>' +
        '<div id="pmd-foot">' +
          '<span id="pmd-usage"></span>' +
          '<button type="button" class="pmd-btn" id="pmd-copy">複製 Markdown</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(wrap);
    $('pmd-close').onclick = close;
    wrap.addEventListener('click', function (ev) { if (ev.target === wrap) close(); });
    $('pmd-run').onclick = run;
    $('pmd-abort').onclick = abortRun;
    $('pmd-copy').onclick = function () {
      if (!lastReport) { setStatus('尚無報告可複製', true); return; }
      copyText(toMarkdown(lastReport), function (ok) {
        setStatus(ok ? '已複製 Markdown' : '複製失敗（瀏覽器限制）', !ok);
        if (ok) toast('已複製', '盤後日報 Markdown');
      });
    };
    var wl = readWatchlist();
    if (wl.length) $('pmd-syms').value = wl.join(',');
    loadLatest();
  }

  window.PostmarketDaily = { open: open, close: close, toMarkdown: toMarkdown };
})();

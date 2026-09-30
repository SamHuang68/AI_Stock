/* 個股體檢（st-stock-signals/v1）— 圖表頁「體檢」分頁 + 策略訊號頁的自選股總表。
 *
 * 只讀後端 /stock-signals*（單一計算者）；本檔不重算任何指標。
 * 三種閱讀深度共用同一份資料：新手（燈號＋一句話＋失效價位）／進階（燈號說明＋統計）／
 * 專業（指標值、規則、方法、資料來源）。用詞沿用 DecisionContext 規範：偏多／偏空／留意，不寫買賣。
 */
(function () {
  'use strict';

  var MODE_KEY = 'st_stock_health_mode_v1';
  var MODES = [
    { key: 'beginner', label: '新手' },
    { key: 'advanced', label: '進階' },
    { key: 'pro', label: '專業' }
  ];
  var cache = {};          // sym:mkt → {at, data}
  var CACHE_MS = 60000;
  var lastWlHash = '';
  var explainCache = {};   // sym:asOf → narrative

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function num(v, d) {
    var n = Number(v);
    if (v == null || !isFinite(n)) return '—';
    return n.toLocaleString('en-US', { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d });
  }
  function pct(v, d) {
    var n = Number(v);
    if (v == null || !isFinite(n)) return '—';
    return (n * 100).toFixed(d == null ? 0 : d) + '%';
  }
  function getJson(path) {
    if (window.AppKernel && AppKernel.api) return AppKernel.api.getJson(path, { timeoutMs: 45000 });
    var base = window.SERVER || location.origin || 'http://localhost:18432';
    return fetch(base + path, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  function postJson(path, body, timeoutMs) {
    if (window.AppKernel && AppKernel.api) return AppKernel.api.postJson(path, body, { timeoutMs: timeoutMs || 15000 });
    var base = window.SERVER || location.origin || 'http://localhost:18432';
    return fetch(base + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {})
    }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }

  function getMode() {
    try {
      var m = localStorage.getItem(MODE_KEY);
      if (m === 'advanced' || m === 'pro') return m;
    } catch (e) {}
    return 'beginner';
  }
  function setMode(m) {
    try { localStorage.setItem(MODE_KEY, m); } catch (e) {}
  }

  // 顏色走 colors_v3：偏多／偏空依標的市場（台股紅漲綠跌），警示用琥珀，中性／未知用暗色
  function stateColor(sym, state) {
    var C = window.Colors;
    if (state === 'bull') return C ? C.dir(sym, 1) : 'var(--red)';
    if (state === 'bear') return C ? C.dir(sym, -1) : 'var(--green)';
    if (state === 'caution' || state === 'risk') return 'var(--orange)';
    if (state === 'neutral') return 'var(--thi)';
    return 'var(--tlo)';
  }
  var STATE_ICON = { bull: '▲', bear: '▼', caution: '!', risk: '!', neutral: '●', unknown: '○' };

  function injectCSS() {
    if (document.getElementById('stock-health-v5-css')) return;
    var style = document.createElement('style');
    style.id = 'stock-health-v5-css';
    style.textContent =
      '.sh5{padding:8px 9px 14px;color:var(--text,#cdd6e4);font-family:"Noto Sans TC",sans-serif}' +
      '.sh5-head{display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap;margin-bottom:7px}' +
      '.sh5-title{font:800 13px/1.3 "Noto Sans TC",sans-serif;color:var(--thi,#f2f5fa)}' +
      '.sh5-title small{font:600 9px "JetBrains Mono",monospace;color:var(--tlo);margin-left:6px}' +
      '.sh5-modes{display:inline-flex;border:1px solid var(--border,#22324a);border-radius:999px;overflow:hidden}' +
      '.sh5-modes button{background:transparent;border:0;color:var(--tlo);font:700 10px "Noto Sans TC",sans-serif;padding:3px 9px;cursor:pointer}' +
      '.sh5-modes button.on{background:rgba(251,191,36,.16);color:var(--gold,#fbbf24)}' +
      '.sh5-lights{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:5px;margin:6px 0 8px}' +
      '.sh5-light{border:1px solid rgba(90,106,130,.35);border-radius:8px;padding:6px 4px;text-align:center;background:rgba(10,18,30,.55)}' +
      '.sh5-light .k{font-size:10px;color:var(--tlo)}' +
      '.sh5-light .v{font-size:13px;font-weight:800;margin-top:2px;white-space:nowrap}' +
      '.sh5-light .p{font-size:10px;color:#b8c7d9;margin-top:4px;line-height:1.45;text-align:left}' +
      '.sh5-sum{font-size:13px;line-height:1.65;color:#f4f8fc;font-weight:700;padding:8px 10px;border-radius:8px;' +
        'background:rgba(56,189,248,.08);border:1px solid rgba(56,189,248,.22)}' +
      '.sh5-inval{margin-top:6px;font-size:11.5px;line-height:1.6;color:#fcd34d;padding:6px 10px;border-radius:8px;' +
        'background:rgba(251,191,36,.07);border:1px dashed rgba(251,191,36,.35)}' +
      '.sh5-sec{margin-top:10px}' +
      '.sh5-sec h4{font:800 11px "Noto Sans TC",sans-serif;color:var(--gold,#fbbf24);margin:0 0 5px;letter-spacing:.04em}' +
      '.sh5-ev{border:1px solid rgba(90,106,130,.3);border-radius:8px;padding:7px 9px;margin-bottom:6px;background:rgba(8,14,24,.6)}' +
      '.sh5-ev .t{display:flex;justify-content:space-between;gap:6px;align-items:baseline;flex-wrap:wrap}' +
      '.sh5-ev .n{font-weight:800;font-size:12px}' +
      '.sh5-ev .s{font:700 9px "JetBrains Mono",monospace;color:var(--tlo)}' +
      '.sh5-ev .d{font-size:11px;color:#cbd5e1;margin-top:3px;line-height:1.55}' +
      '.sh5-ev .pl{font-size:11px;color:#94a3b8;margin-top:2px;line-height:1.55}' +
      '.sh5-ev .iv{font-size:10.5px;color:#fcd34d;margin-top:3px}' +
      '.sh5-ev .st{font-size:10.5px;color:#a5b4fc;margin-top:3px;line-height:1.5}' +
      '.sh5-ev.off{opacity:.55}' +
      '.sh5-badge{display:inline-block;font:700 9px "JetBrains Mono",monospace;padding:1px 6px;border-radius:999px;border:1px solid currentColor;margin-left:4px}' +
      '.sh5-empty{font-size:11px;color:var(--tlo);padding:6px 2px}' +
      '.sh5-tbl{width:100%;border-collapse:collapse;font:600 10px "JetBrains Mono",monospace}' +
      '.sh5-tbl td{padding:3px 4px;border-bottom:1px solid rgba(34,50,74,.6)}' +
      '.sh5-tbl td:first-child{color:var(--tlo)}' +
      '.sh5-foot{margin-top:10px;font-size:9.5px;color:#7f93ab;line-height:1.6}' +
      '.sh5-row{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:8px;font-size:10.5px;color:var(--tlo)}' +
      '.sh5-row select,.sh5-btn{background:rgba(15,23,42,.8);color:var(--thi);border:1px solid var(--border,#22324a);border-radius:6px;font:700 10.5px "Noto Sans TC",sans-serif;padding:3px 8px;cursor:pointer}' +
      '.sh5-btn.primary{border-color:rgba(251,191,36,.5);color:var(--gold,#fbbf24)}' +
      '#sh5-schedule-save,#sh5-evidence-check,#sh5-report-more{min-height:44px;font-size:13px}.sh5-schedule-control{display:flex;align-items:center;gap:8px;min-height:44px;font-size:13px}.sh5-schedule-control input{flex-shrink:0}' +
      '.sh5-ai{margin-top:8px;font-size:12px;line-height:1.7;color:#e2e8f0;padding:8px 10px;border-radius:8px;border:1px solid rgba(165,180,252,.3);background:rgba(99,102,241,.08)}' +
      '.sh5-ai .cite{font:700 8.5px "JetBrains Mono",monospace;color:#a5b4fc;margin-left:3px}' +
      '.sh5-warn{color:#fbbf24;font-size:10.5px;margin-top:4px}' +
      '.sh5-board table{width:100%;border-collapse:collapse}' +
      '.sh5-board td,.sh5-board th{padding:5px 6px;border-bottom:1px solid rgba(34,50,74,.6);font-size:11px;text-align:left;vertical-align:top}' +
      '.sh5-board tr[data-code]{cursor:pointer}' +
      '.sh5-board tr[data-code]:hover{background:rgba(251,191,36,.06)}' +
      '.sh5-review-group{border-bottom:1px solid var(--border,#334155);padding:8px 0}.sh5-review-group>summary{cursor:pointer;color:var(--gold,#fbbf24);font-size:13px;font-weight:700}' +
      '.sh5-review-group .sh5-ev{font-size:12px;line-height:1.6;overflow-wrap:anywhere}.sh5-board .sh5-btn{min-height:32px}.sh5-comparison{overflow-x:auto}.sh5-comparison table{min-width:680px}' +
      '.sh5-table-scroll{overflow-x:auto;max-width:100%}.sh5-table-scroll .sh5-tbl{min-width:780px}' +
      '.sh5-table-scroll:focus-visible{outline:2px solid var(--gold,#fbbf24);outline-offset:2px}' +
      '.sh5-professional details{margin:8px 0;padding:8px;border:1px solid var(--border,#22324a);border-radius:7px;font-size:11px}' +
      '.sh5-professional summary{cursor:pointer;color:var(--thi,#f2f5fa);line-height:1.6}' +
      '.sh5-professional table{width:100%;border-collapse:collapse;font-size:11px}.sh5-professional th,.sh5-professional td{padding:5px;text-align:left;border-bottom:1px solid var(--border,#22324a)}' +
      '.sh5-scroll{overflow:auto;max-width:100%}.sh5-professional pre{font-size:10px;line-height:1.5}' +
      '.sh5 :focus-visible{outline:2px solid var(--gold,#fbbf24);outline-offset:2px}' +
      '.sh5-dot{display:inline-block;min-width:34px;font:800 10px "Noto Sans TC",sans-serif;margin-right:3px;white-space:nowrap}' +
      '@media(max-width:520px){.sh5-lights{grid-template-columns:repeat(3,minmax(0,1fr))}}';
    document.head.appendChild(style);
  }

  // ── 統計文字 ────────────────────────────────────────────────
  var VERDICT = {
    above: '高於基準', below: '低於基準',
    noise: '差距在誤差範圍內，無明顯差異',
    descriptive: '歷史差距，尚未驗證優勢'
  };
  function verdictText(r) {
    if (!r || !r.edgeVerdict) return '';
    return ' → ' + VERDICT[r.edgeVerdict];
  }
  function ciText(r) { return r && r.ci95Pts != null ? '±' + r.ci95Pts : ''; }

  function statsLine(ev, mode) {
    var st = ev.stats;
    if (!st || !st.horizons) return '';
    var rows = st.horizons.filter(function (r) { return mode !== 'beginner' || r.horizon === 5; });
    return rows.map(function (r) {
      if (r.gate !== 'ok') {
        if (!r.n) return '之後 ' + r.horizon + ' 日：本檔歷史尚無此訊號的完整樣本，無法統計';
        return '之後 ' + r.horizon + ' 日：本檔歷史樣本 ' + r.n + ' 次（< ' + st.minSample + '），不顯示比例';
      }
      var s = '本檔過去 ' + r.n + ' 次觸發後 ' + r.horizon + ' 日：上漲 ' + pct(r.upRatio) + ciText(r) +
        '（本檔全期間 ' + pct(r.baseUpRatio) + '）' + verdictText(r);
      if (mode !== 'beginner') {
        s += '、報酬中位數 ' + pct(r.medianRet, 1) + '、期間最大逆向中位數 ' + pct(r.medianAdverse, 1) +
          '、差距 ' + (r.edgePts > 0 ? '+' : '') + r.edgePts + ' 個百分點';
      }
      return s;
    }).join('<br>');
  }

  function pooledLine(ev, mode) {
    var p = ev.pooledStats;
    if (!p || !p.horizons) return '';
    var rows = p.horizons.filter(function (r) { return r.gate === 'ok' && (mode !== 'beginner' || r.horizon === 5); });
    if (!rows.length) return '';
    return '<span>統計資料至 ' + esc((p.window || {}).to || '未知') + '；計算於 ' + esc(p.generatedAt || '未知') + '</span><br>' + rows.map(function (r) {
      return '同市場 ' + p.symbols + ' 檔合計 ' + r.n + ' 次後 ' + r.horizon + ' 日：上漲 ' + pct(r.upRatio) + ciText(r) +
        '（基準 ' + pct(r.baseUpRatio) + '）' + verdictText(r) +
        (mode !== 'beginner' ? '、中位數 ' + pct(r.medianRet, 1) : '');
    }).join('<br>');
  }

  // ── 單檔卡片 ────────────────────────────────────────────────
  function lightsHtml(d, mode) {
    return '<div class="sh5-lights">' + d.health.lights.map(function (l) {
      var col = stateColor(d.symbol, l.state);
      return '<div class="sh5-light" data-ev="' + esc(l.evidenceId) + '"><div class="k">' + esc(l.label) + '</div>' +
        '<div class="v" style="color:' + col + '">' + (STATE_ICON[l.state] || '') + ' ' + esc(l.tag) + '</div>' +
        (mode !== 'beginner' ? '<div class="p">' + esc(l.plain) + '</div>' : '') + '</div>';
    }).join('') + '</div>';
  }

  function eventHtml(d, ev, mode) {
    var col = stateColor(d.symbol, ev.direction === 'risk' ? 'risk' : ev.direction);
    var level = ev.invalidation && ev.invalidation.level != null ? ' ' + num(ev.invalidation.level) : '';
    var off = ev.status === 'invalidated';
    var html = '<div class="sh5-ev' + (off ? ' off' : '') + '">' +
      '<div class="t"><span class="n" style="color:' + col + '">' + (STATE_ICON[ev.direction] || '•') + ' ' + esc(ev.label) +
        '<span class="sh5-badge" style="color:' + col + '">' + esc(ev.directionLabel) + '</span></span>' +
        '<span class="s">' + esc(ev.date) + ' · ' + esc(ev.statusLabel) + (ev.provisional ? ' · 盤中暫定' : '') + '</span></div>' +
      '<div class="pl">' + esc(ev.plain) + '</div>';
    if (mode !== 'beginner') html += '<div class="d">' + esc(ev.detail) + '</div>';
    html += '<div class="iv">失效條件：' + esc(ev.invalidation ? ev.invalidation.text : '—') + esc(level) + '</div>';
    var s = statsLine(ev, mode);
    var p = pooledLine(ev, mode);
    if (s || p) html += '<div class="st">' + [s, p].filter(Boolean).join('<br>') + '</div>';
    if (mode === 'pro' && ev.stats && ev.stats.method) html += '<div class="pl">方法：' + esc(ev.stats.method) + '</div>';
    return html + '</div>';
  }

  function indicatorTable(d) {
    var I = d.indicators || {};
    var rows = [
      ['收盤', num(I.close)], ['日漲跌', I.chgPct == null ? '—' : num(I.chgPct) + '%'],
      ['SMA5 / 20 / 60', num(I.sma5) + ' / ' + num(I.sma20) + ' / ' + num(I.sma60)],
      ['RSI14（Wilder）', num(I.rsi14, 1)],
      ['MACD / Signal / Hist', num(I.macd, 3) + ' / ' + num(I.macdSignal, 3) + ' / ' + num(I.macdHist, 3)],
      ['布林上 / 下軌', num(I.bbUpper) + ' / ' + num(I.bbLower)],
      ['ATR14（Wilder）', num(I.atr14)],
      ['量 / 20 日均量', num(I.volVs20d) + '×'], ['5 日 / 20 日均量', num(I.vol5vs20) + '×'],
      ['前 20 日高 / 低', num(I.high20) + ' / ' + num(I.low20)]
    ];
    return '<table class="sh5-tbl">' + rows.map(function (r) {
      return '<tr><td>' + esc(r[0]) + '</td><td>' + esc(r[1]) + '</td></tr>';
    }).join('') + '</table>';
  }

  function pushRowHtml(cfg) {
    var mode = (cfg && cfg.mode) || 'off';
    var opts = [['off', '關閉推播'], ['digest', '收盤摘要（每日一次）'], ['realtime', '即時事件＋收盤摘要']];
    var hint = cfg && cfg.channels && !cfg.channels.length && mode !== 'off'
      ? '<span class="sh5-warn">尚未啟用 Telegram／Email／Webhook，請到警報設定開啟。</span>' : '';
    var ai = '';
    if (cfg && mode !== 'off') {
      ai = '<label title="收盤摘要附 Claude 白話版：用 Message Batches 非即時處理，費用約同步呼叫一半；每句仍需通過證據驗證">' +
        '<input type="checkbox" id="sh5-aidigest"' + (cfg.aiDigest ? ' checked' : '') + (cfg.aiKeySet ? '' : ' disabled') + '> ' +
        '摘要附 AI 白話（批次）' + (cfg.aiKeySet ? '' : '（需先設定 AI Key）') + '</label>';
    }
    return '<div class="sh5-row">自選股訊號推播：<select id="sh5-push">' + opts.map(function (o) {
      return '<option value="' + o[0] + '"' + (o[0] === mode ? ' selected' : '') + '>' + o[1] + '</option>';
    }).join('') + '</select>' + (cfg ? '<span>追蹤 ' + (cfg.symbols || 0) + ' 檔</span>' : '') + ai + hint + '</div>';
  }

  function aiHtml(n) {
    if (!n) return '';
    if (n.error) return '<div class="sh5-ai"><span class="sh5-warn">' + esc(n.error) + '</span></div>';
    var parts = (n.sentences || []).map(function (s) {
      return esc(s.text) + '<span class="cite">[' + esc((s.evidenceIds || []).join(', ')) + ']</span>';
    });
    var head = n.source === 'claude'
      ? 'AI 白話解讀（' + esc(n.model || 'Claude') + '；每句都附證據編號，未通過驗證的句子已刪除）'
      : '白話解讀（規則模板）';
    var dropped = n.dropped && n.dropped.length ? '<div class="sh5-warn">已刪除 ' + n.dropped.length + ' 句無法對應證據的內容。</div>' : '';
    if (n.note) dropped += '<div class="sh5-warn">' + esc(n.note) + '</div>';
    return '<div class="sh5-ai"><div style="font-weight:800;color:#c7d2fe;margin-bottom:4px">' + esc(head) + '</div>' +
      parts.join('<br>') + dropped + '</div>';
  }

  function scoreboardHtml(p) {
    if (!p) return '<div class="sh5-empty">載入中…</div>';
    var btn = '<button class="sh5-btn" id="sh5-pool-refresh"' + (p.running ? ' disabled' : '') + '>' +
      (p.running ? '計算中…（全市場約需數分鐘）' : (p.available ? '重新計算' : '開始計算')) + '</button>';
    if (!p.available) {
      return '<div class="sh5-empty">尚未計算同市場合併統計。會用本機日線庫所有標的，逐一套用同一套規則，' +
        '算出每個訊號之後 5／20 日的表現與「隨便挑一天」的基準差距。</div><div class="sh5-row">' + btn + '</div>';
    }
    var rows = (p.scoreboard || []).map(function (r) {
      var h = r.horizons.filter(function (x) { return x.horizon === 5; })[0] || {};
      var h20 = r.horizons.filter(function (x) { return x.horizon === 20; })[0] || {};
      var st = h.stability || {};
      var rh = ((r.research || {}).horizons || []).filter(function (x) { return x.horizon === 5; })[0];
      var matched = rh && rh.all;
      var matchedText = '待重新計算';
      if (matched) {
        var ci = matched.deltaRetCI95;
        matchedText = matched.blockMeanDeltaRet == null ? '資料不足' : '季度等權差距 ' + pct(matched.blockMeanDeltaRet, 2);
        matchedText += '<br><span style="color:var(--tlo)">' + matched.n + ' 次／' + matched.quarters + ' 季';
        matchedText += ci ? '<br>季度差距區間 ' + pct(ci[0], 2) + '～' + pct(ci[1], 2) : '<br>區間資料不足';
        matchedText += '</span>';
      }
      var cell = function (x) {
        return x.gate === 'ok' ? pct(x.upRatio) + ciText(x) + '<br><span style="color:var(--tlo)">基準 ' + pct(x.baseUpRatio) + '</span>'
          : '<span style="color:var(--tlo)">樣本不足（' + (x.n || 0) + '）</span>';
      };
      return '<tr><td>' + esc(r.label) + '<br><span style="color:var(--tlo)">' + esc(r.familyLabel + '・' + r.directionLabel) + '</span></td>' +
        '<td>' + (h.n || 0) + '<br><span style="color:var(--tlo)">' + (h.symbols || 0) + ' 檔</span></td>' +
        '<td>' + cell(h) + '</td><td>' + cell(h20) + '</td>' +
        '<td>' + (h.edgeVerdict ? esc(VERDICT[h.edgeVerdict]) + '<br><span style="color:var(--tlo)">' + (h.edgePts > 0 ? '+' : '') + h.edgePts + ' pts</span>' : '—') + '</td>' +
        '<td>' + (st.olderUpRatio != null && st.recentUpRatio != null ? pct(st.olderUpRatio) + ' → ' + pct(st.recentUpRatio) : '—') + '</td>' +
        '<td>' + matchedText + '</td></tr>';
    }).join('');
    return '<div class="sh5-foot" style="margin-top:0">同市場 ' + esc(p.symbols) + ' 檔 · ' + esc((p.window || {}).from || '') + '～' +
      esc((p.window || {}).to || '') + ' · 計算於 ' + esc(p.generatedAt || '') + ' · 樣本門檻 ' + esc(p.minSample) + ' 次／' + esc(p.minSymbols) + ' 檔</div>' +
      '<div class="sh5-table-scroll" tabindex="0" role="region" aria-label="訊號成績單，可左右捲動"><table class="sh5-tbl"><tr><th scope="col">訊號</th><th scope="col">次數(5日)</th><th scope="col">5 日上漲</th><th scope="col">20 日上漲</th><th scope="col">判讀(5日)</th><th scope="col">前段→近段</th><th scope="col">情境對照(5日)</th></tr>' + rows + '</table></div>' +
      '<div class="sh5-foot">比例誤差僅為描述，不能當作優勢證明。情境對照從次日收盤起算，對照同股票、同大盤情境已成熟的歷史；季度區間屬探索結果，未校正多重比較。</div>' +
      (p.research && p.research.selection ? '<div class="sh5-foot">候選判讀：' + esc(p.research.selection.reason) + '</div>' : '') +
      (p.research && p.research.benchmarkCoverage ? '<div class="sh5-foot">大盤情境資料：' + esc(p.research.benchmarkCoverage.from || '缺少') + '～' + esc(p.research.benchmarkCoverage.to || '缺少') + '；缺少同日情境的事件不納入對照研究。</div>' : '') +
      rsiResearchHtml(p.research && p.research.rsiRebound) +
      sensitivityHtml(p.priceSensitivity) +
      rawCostHtml(p.scoreboard || []) +
      '<div class="sh5-foot">' + esc(p.method || '') + '<br>' + (p.caveats || []).map(esc).join('<br>') + '</div>' +
      '<div class="sh5-row">' + btn + '</div>';
  }

  function cardHtml(d, mode, pushCfg) {
    var head = '<div class="sh5-head"><div class="sh5-title">' + esc(d.symbol) + ' 個股體檢' +
      '<small>' + esc(d.asOf || '') + (d.session && d.session.provisional ? ' · 盤中暫定' : '') + '</small></div>' +
      '<div class="sh5-modes" role="group" aria-label="體檢閱讀深度">' + MODES.map(function (m) {
        return '<button data-sh5-mode="' + m.key + '" aria-pressed="' + (m.key === mode) + '" class="' + (m.key === mode ? 'on' : '') + '">' + m.label + '</button>';
      }).join('') + '</div></div>';
    if (!d.ok) {
      return '<div class="sh5">' + head + '<div class="sh5-empty">' + esc(d.message || '尚無資料') +
        (d.dataWarning ? '<div class="sh5-warn">' + esc(d.dataWarning) + '</div>' : '') + '</div></div>';
    }
    var warn = '';
    if (d.staleDays != null && d.staleDays > 3) warn += '<div class="sh5-warn">日線最後日期 ' + esc(d.asOf) + '，落後約 ' + d.staleDays + ' 天；請更新本機日線庫或檢查網路。</div>';
    if (d.dataWarning) warn += '<div class="sh5-warn">' + esc(d.dataWarning) + '</div>';
    var inv = d.health.invalidation;
    var events = d.events || [];
    var shown = mode === 'beginner' ? events.filter(function (e) { return e.status !== 'invalidated'; }) : events;
    var html = '<div class="sh5">' + head + warn + qualityHtml(d.dataQuality, mode) + lightsHtml(d, mode) +
      '<div class="sh5-sum">' + esc(d.health.summary.sentence) + '</div>' +
      (inv ? '<div class="sh5-inval">什麼情況代表判斷錯了：' + esc(inv.text) + '</div>' : '') +
      (mode === 'pro' ? professionalHtml(d) : '') +
      '<div class="sh5-sec"><h4>近 10 個交易日的訊號（' + shown.length + '）</h4>' +
      (shown.length ? shown.map(function (e) { return eventHtml(d, e, mode); }).join('')
        : '<div class="sh5-empty">近 10 個交易日沒有新的狀態轉換。沒有訊號也是資訊：趨勢照燈號判讀即可。</div>') + '</div>';
    html += '<div class="sh5-row"><button class="sh5-btn primary" id="sh5-explain">白話解讀（可用 AI）</button>' +
      '<span>AI 只能引用上方證據，不能改寫燈號或給買賣指令</span></div><div id="sh5-ai-out">' +
      aiHtml(explainCache[d.symbol + ':' + d.asOf]) + '</div>';
    if (mode !== 'beginner') {
      if (d.market === 'TW') html += '<details class="sh5-sec" id="sh5-research"><summary>研究維護與每日事件留存</summary><div id="sh5-research-body">展開後讀取本機狀態。</div></details>';
      html += '<div class="sh5-sec"><details id="sh5-pool"><summary style="cursor:pointer;font:800 11px \'Noto Sans TC\',sans-serif;color:var(--gold,#fbbf24)">' +
        '訊號成績單（同市場合併統計：哪些訊號真的有資訊？）</summary><div id="sh5-pool-body">' + scoreboardHtml(poolCache) + '</div></details></div>';
      if (d.market === 'TW') html += '<details class="sh5-sec" id="sh5-comparison"><summary>歷史研究與真實前瞻對照</summary><div id="sh5-comparison-body">展開後唯讀檢視每日帳本。</div></details>';
    }
    if (mode === 'pro') {
      html += '<div class="sh5-sec"><h4>指標值（' + esc(d.engine) + '）</h4>' + indicatorTable(d) + '</div>' +
        '<div class="sh5-foot">資料來源：' + esc(d.dataSource || '—') + ' · 日 K ' + esc(d.bars) + ' 根' +
        (d.chip ? ' · 籌碼至 ' + esc(d.chip.asOf) + '（' + esc(d.chip.days) + ' 日）' : '') +
        ' · 產生於 ' + esc(d.generatedAt || '') + ' · 證據 ' + Object.keys(d.evidence || {}).length + ' 項</div>';
    }
    html += pushRowHtml(pushCfg);
    html += '<div class="sh5-foot">' + esc(d.disclaimer || '') + '</div></div>';
    return html;
  }

  function rsiResearchHtml(r) {
    if (!r) return '';
    var html = '<details class="sh5-sec"><summary>RSI 獨立研究：大盤非下降、個股仍下降</summary><div class="sh5-foot">' +
      esc((r.selection || {}).reason) + '<br>此假說在看過第一輪結果後提出，歷史分段不是獨立盲測。</div>';
    (((r.signals || [])[0] || {}).horizons || []).forEach(function (h) {
      ['training', 'temporalCheck'].forEach(function (key) {
        var part = h[key] || {}, c = part.context || {}, ci = c.deltaRetCI95, inc = (part.increment || {}).ci95;
        html += '<div class="sh5-foot">' + h.horizon + ' 日／' + (key === 'training' ? '2024 年以前' : '2024 年起') +
          '：' + esc(c.n) + ' 次／' + esc(c.symbols) + ' 檔／' + esc(c.quarters) + ' 季；季度差距區間 ' +
          (ci ? pct(ci[0], 2) + '～' + pct(ci[1], 2) : '資料不足') + '；情境增量區間 ' +
          (inc ? pct(inc[0], 2) + '～' + pct(inc[1], 2) : '資料不足') + '</div>';
      });
    });
    return html + '<div class="sh5-foot">次日收盤起算；未還原、未計費用，區間未校正多重比較。</div></details>';
  }

  function professionalHtml(d) {
    var names = { close: '收盤', sma20: '20 日均線', sma60: '季線', rsi: 'Wilder RSI14',
      macd_hist: 'MACD 柱狀體', volx: '量／均量', atr: 'ATR14', trust: '投信股數', foreign: '外資股數' };
    var html = '<section class="sh5-sec sh5-professional" aria-label="專業證據檢視"><h4>專業檢視：事件、分布與證據</h4>' +
      '<div class="sh5-foot">歷史快照重建可供核對規則；實際前瞻觀察另存帳本。比例與分位數均為描述統計，不能當成獲利保證。</div>';
    var events = d.events || [];
    if (!events.length) html += '<div class="sh5-empty">近期沒有新事件；仍可核對下方燈號、失效條件與原始證據。</div>';
    events.forEach(function (e) {
      var a = e.audit || {};
      html += '<details><summary>' + esc(e.label) + '：' + esc(e.date) + ' → ' + esc(e.statusLabel) + '</summary>' +
        '<div class="sh5-foot">觸發規則：' + esc(e.rule || e.detail) + '<br>狀態更新日：' + esc(e.statusDate || e.date) +
        '；檢查至 ' + esc(a.evaluatedThrough || d.asOf) + (a.statusProvisional ? '（含盤中暫定資料）' : '') +
        '<br>確認需要 ' + esc(a.confirmationBars == null ? '—' : a.confirmationBars) + ' 根未失效日 K；歷史統計同訊號間隔至少 ' +
        esc(a.statCooldownBars == null ? '—' : a.statCooldownBars) + ' 根。<br>' + esc(a.note || '此版本未附事件快照') + '</div>';
      var vals = a.triggerValues || {};
      html += '<div class="sh5-scroll" role="region" tabindex="0" aria-label="觸發前後數值"><table class="sh5-it"><thead><tr><th>證據</th><th>觸發前一日</th><th>觸發日</th></tr></thead><tbody>';
      Object.keys(vals).forEach(function (key) {
        html += '<tr><th>' + esc(names[key] || key) + '</th><td>' + num(vals[key].before) + '</td><td>' + num(vals[key].at) + '</td></tr>';
      });
      html += '</tbody></table></div>';
      ((e.stats || {}).horizons || []).forEach(function (h) {
        html += '<div class="sh5-foot">本檔觸發後 ' + esc(h.horizon) + ' 日，n=' + esc(h.n) + '：';
        if (h.gate !== 'ok' || !h.distribution) html += '樣本不足或此版本未提供分布，不顯示分位數。';
        else html += '第 10／50／90 百分位 ' + pct(h.distribution.p10, 2) + '／' + pct(h.distribution.p50, 2) + '／' + pct(h.distribution.p90, 2) +
          '；最差 ' + pct(h.distribution.worst, 2) + '<br>成熟觸發期間：' + esc((h.window || {}).from) + '～' + esc((h.window || {}).to);
        html += '</div>';
      });
      html += '</details>';
    });
    html += '<details><summary>原始證據表（' + Object.keys(d.evidence || {}).length + ' 項）</summary>' +
      '<div class="sh5-foot">證據編號可對應白話解讀的引用；日期代表該證據的資料時間。</div>';
    Object.keys(d.evidence || {}).forEach(function (key) {
      var v = d.evidence[key];
      html += '<details><summary>' + esc(key) + ' · ' + esc(v.label || '') + ' · ' + esc(v.asOf || '未提供日期') +
        '</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(JSON.stringify(v, null, 2)) + '</pre></details>';
    });
    return html + '</details></section>';
  }

  function currentSym() {
    if (typeof S === 'undefined' || !S.sym) return null;
    return { sym: String(S.sym).toUpperCase().replace(/\.TWO?$/, ''), mkt: S.mkt === 'US' ? 'US' : 'TW' };
  }

  function load(sym, mkt, force) {
    var key = sym + ':' + mkt;
    var hit = cache[key];
    if (!force && hit && Date.now() - hit.at < CACHE_MS) return Promise.resolve(hit.data);
    return getJson('/stock-signals?sym=' + encodeURIComponent(sym) + '&market=' + mkt).then(function (d) {
      cache[key] = { at: Date.now(), data: d };
      return d;
    });
  }

  var pushCfg = null;
  var poolCache = null;
  function qualityHtml(q, mode) {
    if (!q) return '<div class="sh5-foot">資料品質尚未提供，請以各來源日期核對。</div>';
    var names = { aligned: '已對齊', stale: '待更新', missing: '缺資料', unknown: '待確認' };
    var parts = (q.items || []).map(function (r) {
      return esc(r.label) + '：' + esc(names[r.status] || '待確認') + '（' + esc(r.asOf || '無日期') + '）' +
        (r.lagSessions ? '，落後 ' + esc(r.lagSessions) + ' 個已知交易日' : '') +
        (mode !== 'beginner' ? '<br>' + esc(r.impact || '') + (r.generatedAt ? '；計算於 ' + esc(r.generatedAt) : '') : '');
    });
    return '<details class="sh5-sec"><summary>' + esc(q.label || '資料品質待確認') + ' · 基準日 ' + esc(q.referenceSession || '未知') +
      '</summary><div class="sh5-foot">' + parts.join('<br>') + '<br>' + (q.notes || []).map(esc).join('<br>') + '</div></details>';
  }

  function sensitivityHtml(p) {
    if (!p) return '<div class="sh5-foot">還原與成本研究尚未計算；原有研究結果保留。</div>';
    var partial = p.windowCount != null;
    var html = '<details class="sh5-sec"><summary>' + (partial ? '部分歷史區段：' + esc(p.windowCount) + ' 段、' + esc(p.coveredBars) + ' 根日線（' : '除權息與成本敏感度（完整覆蓋 ') + esc(p.coveredSymbols) + '／' + esc(p.totalSymbols) + ' 檔）</summary>' +
      '<div class="sh5-foot">' + esc(p.method || '') + '<br>' + (p.limitations || []).map(esc).join('<br>') + '</div>';
    var detail = '<details><summary>覆蓋日期與未接納原因</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
      esc(JSON.stringify({ covered: p.covered, missingSymbols: p.missingSymbols, missingDetails: p.missingDetails }, null, 2)) + '</pre></details>';
    if (p.snapshotSymbols != null) html += '<div class="sh5-foot">已取得來源快照 ' + esc(p.snapshotSymbols) + ' 檔；' + (partial ? '各區段與本機原價相容，分段暖機，不跨缺口計算。' : '僅完整且與本機原價相容的資料納入比較。') +
      '其中 ' + esc(p.reconciledSymbols || 0) + ' 檔經明示分割／配股事件逐日核對價格基準；原始行情與差異證據保留，轉換期間及來源可展開查閱。</div>';
    if (p.status !== 'available') return html + '<div class="sh5-warn">尚無完整且相容的還原快照。缺值不當成無除權息；缺日與價差詳見下方。</div>' + detail + '</details>' + (p.partial ? sensitivityHtml(p.partial) : '');
    html += '<div class="sh5-table-scroll" role="region" tabindex="0" aria-label="除權息與成本比較，可左右捲動"><table class="sh5-tbl"><thead><tr>' +
      '<th>訊號／天數</th><th>原價／還原事件</th><th>共同事件</th><th>共同原價中位數</th><th>共同還原中位數</th><th>還原後成本情境中位數</th></tr></thead><tbody>';
    (p.signals || []).forEach(function (s) { (s.horizons || []).forEach(function (h) {
      var med = function (v) { return v && v.gate === 'ok' ? pct(v.medianRet, 2) : '樣本不足'; };
      html += '<tr><td>' + esc(s.label) + '／' + esc(h.horizon) + ' 日</td><td>' + esc(h.rawEvents) + '／' + esc(h.adjustedEvents) + '</td><td>' +
        esc(h.commonEvents) + '</td><td>' + med(h.commonRaw) + '</td><td>' + med(h.commonAdjusted) + '</td><td>' +
        (h.costScenarios || []).map(function (c) { return esc(c.roundTripBps) + ' 基點：' + med(c); }).join('<br>') + '</td></tr>';
    }); });
    return html + '</tbody></table></div>' + detail + '</details>' + (p.partial ? sensitivityHtml(p.partial) : '');
  }

  function reportHistoryHtml(rows) {
    return (rows || []).map(function (r) {
      return '<details class="sh5-foot"><summary>' + esc(r.sessionDate + ' · ' + r.checkedAt + ' · ' +
        (r.execution === 'failed' ? '檢查失敗' : '檢查完成')) + '</summary>' +
        ((r.changes || []).length ? '<ul>' + r.changes.map(function (c) {
          return '<li>' + esc(c.label) + '：' + esc(c.before == null ? '尚無基準' : c.before) + ' → ' + esc(c.after == null ? '未知' : c.after) + '</li>';
        }).join('') + '</ul>' : '相較上次沒有量化指標變化；仍保留此次檢查紀錄。') +
        '<details><summary>當時完整報告與失敗原因</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
        esc(JSON.stringify(r, null, 2)) + '</pre></details></details>';
    }).join('');
  }

  function evidenceReportHtml(p) {
    p = p || {};
    var r = p.latest, labels = { passed: '通過', failed: '失敗', waiting: '等待證據', limited: '涵蓋有限',
      unproven: '尚未驗證優勢', observing: '持續觀察', attention: '需處理' };
    var html = '<section class="sh5-sec" aria-label="三項證據限制測試回報"><h4>三項證據限制：每日測試回報</h4>' +
      '<div class="sh5-foot">' + esc(p.note || '來源更新後檢查；每日20:40本機結報，需主機運行。') +
      '<br>檢查完成代表程序已執行，並不代表投資證據達標；不自動提升候選。</div>';
    if (!r) html += '<p class="sh5-foot">尚無驗證報告。可執行下方本機檢查，或等待每日排程。</p>';
    else {
      html += '<p role="status" class="' + (r.execution === 'failed' ? 'sh5-warn' : 'sh5-foot') + '">' +
        (r.execution === 'failed' ? '最近檢查失敗，請查看原因。' : '最近檢查已完成；證據狀態如下。') +
        '<br>最近檢查 ' + esc(p.lastCheckedAt || r.checkedAt) + '；報告日期 ' + esc(r.sessionDate) +
        '；研究至 ' + esc((r.metrics || {}).researchThrough || '未知') + '</p><ol>';
      (r.constraints || []).forEach(function (c) {
        html += '<li class="sh5-foot"><strong>' + esc(c.label + '：' + (labels[c.state] || c.state)) + '</strong><br>' +
          esc(c.summary) + '<br>下一步：' + esc(c.next) + '</li>';
      });
      html += '</ol>';
      ((r.observations || {}).horizons || []).forEach(function (h) {
        html += '<div class="sh5-foot">' + esc(h.horizon) + '日：成熟 ' + esc(h.mature) + '、待時間累積 ' +
          esc(h.waiting) + '、觀察期已到仍待結算 ' + esc(h.due) + ' 筆。</div>';
      });
      html += '<details><summary>檢查項目與判定依據（' + esc((r.checks || []).length) + '項）</summary><ul>' +
        (r.checks || []).map(function (c) { return '<li class="sh5-foot">' + esc(c.label + '：' + (labels[c.state] || c.state) + '；' + c.detail) + '</li>'; }).join('') +
        '</ul></details><details><summary>完整資料缺口與報告來源</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
        esc(JSON.stringify({ coverage: r.coverage, missingAdjustedSymbols: r.missingAdjustedSymbols, pendingSources: r.pendingSources,
          observations: r.observations, provenance: r.provenance }, null, 2)) + '</pre></details>';
    }
    html += '<details><summary>每日報告與變化紀錄（共' + esc(p.total || 0) + '份）</summary><div id="sh5-report-history">' +
      reportHistoryHtml(p.history) + '</div><button class="sh5-btn" id="sh5-report-more" data-before="' + esc(p.nextBefore || '') + '"' +
      (p.nextBefore ? '' : ' hidden') + '>載入更早報告</button><div class="sh5-foot">量化指標變化不等於投資績效改善；完整紀錄保留於本機，不截斷歷史。</div></details>';
    return html + '<button class="sh5-btn" id="sh5-evidence-check"' + (p.running ? ' disabled' : '') + '>' +
      (p.running ? '本機證據檢查執行中' : '重算並檢查三項證據（僅本機）') + '</button></section>';
  }

  function maintenanceHtml(p) {
    var j = p.job || {}, o = p.observations || {}, i = p.inventory || {};
    var names = { running: '執行中', queued: '排隊中', completed: '已完成', partial: '部分完成', failed: '失敗', interrupted: '已中斷', waiting: '等待資料', closed: '休市', disabled: '未啟用' };
    var html = evidenceReportHtml(p.evidenceReports) + '<div role="status" aria-live="polite" class="sh5-foot">' + esc(p.running ? '研究工作執行中' : (names[j.status] || '尚未執行')) +
      ' · ' + esc(j.message || '') + '<br>大盤至 ' + esc(i.benchmarkAsOf || '未知') + '；個股對齊 ' + esc(i.alignedSymbols || 0) + '／' + esc(i.symbols || 0) + ' 檔。' +
      '<br>' + esc(i.note || '') + '<br>預設只重算本機資料；不呼叫模型或傳送通知。</div>';
    if (i.calendar) html += '<div class="sh5-foot">交易日判定：' + esc(i.calendar.reason) + '</div>';
    if ((i.knownInactive || []).length) html += '<details><summary>已核對的終止交易與來源日期異常（原始資料保留）</summary><div class="sh5-foot">' +
      i.knownInactive.map(function (r) { return esc(r.symbol + '：' + r.label + '；停止交易起日 ' + r.stopDate + '；本機資料至 ' + r.localAsOf +
        (r.sourceDateConflict ? '。存在停止交易後的來源列，需留意，未納入還原比較。' : '。')) +
        ' <a href="' + esc(r.source) + '" target="_blank" rel="noopener noreferrer">公告依據</a>'; }).join('<br>') + '</div></details>';
    html += '<ol class="sh5-foot">' + (j.steps || []).map(function (s) { return '<li>' + esc(s.label) + '：' + esc(names[s.status] || s.status) +
      (s.detail && s.detail.reason ? '；' + esc(s.detail.reason) : '') + (s.error ? '（' + esc(s.error) + '）' : '') + '</li>'; }).join('') + '</ol>';
    html += '<div class="sh5-foot">每日事件留存：' + (o.enabled ? '已啟用，主機運行時收盤後檢查' : '尚未啟用') +
      '；已留存 ' + esc(o.events || 0) + ' 個事件、' + esc(o.outcomes || 0) + ' 筆成熟結果。' +
      (o.activatedAt ? '<br>啟用於 ' + esc(o.activatedAt) : '') + (o.lastRun ? '<br>最近檢查 ' + esc(o.lastRun.asOf) + '：' + esc(o.lastRun.reason) : '') +
      '<br>只記錄啟用後的當日收盤事件，缺日不回填；這些是觀察紀錄，並非通過研究的候選。</div>';
    if (o.lastRun && o.lastRun.chipChannelsExpected != null) html += '<div class="sh5-foot">首次價量輸入 ' + esc(o.lastRun.priceInputs || 0) +
      ' 檔；籌碼訊號資料到齊 ' + esc(o.lastRun.chipChannelsComplete || 0) + '／' + esc(o.lastRun.chipChannelsExpected) +
      ' 組。籌碼稍後到齊會另留證據，不改寫首次價量。</div><details><summary>尚缺資料與排除原因</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
      esc(JSON.stringify({ missingPriceSymbols: o.lastRun.missingPriceSymbols, missingChipInputs: o.lastRun.missingChipInputs,
        excludedInstruments: o.lastRun.excludedInstruments }, null, 2)) + '</pre></details>';
    if (p.sourceRevisions && p.sourceRevisions.count) html += '<div class="sh5-warn">來源修訂 ' + esc(p.sourceRevisions.count) + ' 筆、涉及 ' +
      esc(p.sourceRevisions.symbols) + ' 檔；首次日線保留，衝突另存，尚未自動採用。</div>';
    var schedule = p.schedule || {};
    html += '<div class="sh5-foot"><label class="sh5-schedule-control"><input type="checkbox" id="sh5-schedule-enable"' + (schedule.enabled ? ' checked' : '') +
      '> 持續授權盤後自動更新：TWSE／TPEx 日線及法人、Yahoo 大盤</label><br>交易日 18:30 更新，19:30／20:30 只重試未完成來源；需主機運行。僅傳日期與代號，不上傳帳本、不呼叫模型，無已知 API 費用；取消並儲存可停用。</div>' +
      '<button class="sh5-btn" id="sh5-schedule-save">儲存每日更新設定</button>';
    if (schedule.lastSources && schedule.lastSources.sources) html += '<details><summary>每日來源實際執行紀錄</summary><div class="sh5-foot">' +
      schedule.lastSources.sources.map(function (s) { return esc(s.name + '：' + (names[s.status] || s.status) + (s.reason ? '；' + s.reason : '')); }).join('<br>') +
      '</div><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(JSON.stringify(schedule.lastSources, null, 2)) + '</pre></details>';
    if ((o.recent || []).length) html += '<details><summary>最新 20 筆事件摘要（完整資料保留於本機帳本）</summary><div class="sh5-foot">' +
      o.recent.map(function (r) { return esc(r.date + ' · ' + r.symbol + ' · ' + r.signalId); }).join('<br>') + '</div></details>';
    if (!o.enabled) html += '<label class="sh5-foot"><input type="checkbox" id="sh5-daily-enable"> 同時啟用本機每日事件留存</label>';
    html += '<div class="sh5-foot"><label><input type="checkbox" id="sh5-source-consent"> 同意本次向既有 Yahoo Finance／TWSE 下載行情、還原價格與上市籌碼</label><br>僅傳送代號與日期範圍，不上傳帳本；無已知 API 費用，可能限流。未勾選則只用本機資料。</div>';
    return html + '<div class="sh5-row"><button class="sh5-btn" id="sh5-research-refresh"' + (p.running ? ' disabled' : '') + '>檢查並重算本機研究</button>' +
      '<button class="sh5-btn" id="sh5-research-status">更新狀態</button></div><div id="sh5-research-error" role="alert" class="sh5-warn"></div>';
  }

  function rawCostHtml(rows) {
    var html = '<details class="sh5-sec"><summary>原價事件研究：往返成本敏感度</summary><div class="sh5-foot">沿用原本情境研究樣本，次日收盤起算。各成本是研究假設，不代表實際券商收費；未還原價格的限制仍存在，不改變候選結果。</div>';
    rows.forEach(function (r) { ((r.research || {}).horizons || []).forEach(function (h) {
      var cases = (h.all || {}).costScenarios || [];
      html += '<div class="sh5-foot">' + esc(r.label) + '／' + esc(h.horizon) + ' 日：' +
        (cases.length ? cases.map(function (c) { return esc(c.roundTripBps) + ' 基點 → ' +
          (c.gate === 'ok' ? '中位數 ' + pct(c.medianRet, 2) + '、正報酬 ' + pct(c.upRatio) + '（n=' + esc(c.n) + '）' : '樣本不足'); }).join('；') : '尚待重算') + '</div>';
    }); });
    return html + '</details>';
  }
  function comparisonHtml(p) {
    var html = '<div class="sh5-foot">每日帳本：' + (p.enabled ? '已啟用，起始 ' + esc(p.activatedAt || '未知') : '尚未啟用') +
      ' · 實際留存 ' + esc(p.observedEvents || 0) + ' 筆事件；每個 5／20 日結果分開成熟。歷史計算時間 ' + esc(p.historicalGeneratedAt || '未知') + '。</div>';
    if (!p.historicalVerified) html += '<div class="sh5-warn">歷史研究尚未附帶相符的規則與方法指紋；此對照區暫不展示其比率。請在研究維護執行本機重算。</div>';
    function stats(row) {
      if (!row || row.gate !== 'ok' || row.n < (p.minSample || 20)) return '樣本 ' + esc(row && row.n || 0) + ' · ' + (row && row.gate === 'unverified_version' ? '版本未核實' : '等待至少 ' + esc(p.minSample || 20) + ' 筆');
      return '樣本 ' + esc(row.n) + '<br>報酬中位數 ' + pct(row.medianRet, 2) + '<br>正報酬比例 ' + pct(row.upRatio, 1) +
        '<br>不利幅度中位數 ' + pct(row.medianAdverse, 2);
    }
    function costs(row) {
      return (row && row.costScenarios || []).map(function (cost) {
        return esc(cost.roundTripBps) + ' 基點：' + (cost.gate === 'ok' && cost.n >= (p.minSample || 20) ? pct(cost.medianRet, 2) : '樣本不足');
      }).join('；') || '等待可核實且足夠的成熟樣本';
    }
    (p.groups || []).forEach(function (group) {
      html += '<details' + (group.currentRules ? ' open' : '') + '><summary>' + (group.currentRules ? '目前規則' : '既有規則（獨立計數）') + ' · ' + esc(group.rulesDigest.slice(0, 12)) + '</summary>' +
        '<div class="sh5-comparison"><table class="sh5-tbl"><thead><tr><th>訊號／期間</th><th>歷史研究<br>符合過去對照的樣本</th><th>真實前瞻<br>全部成熟結果</th><th>真實前瞻<br>符合過去對照的子集合</th></tr></thead><tbody>';
      (group.signals || []).forEach(function (signal) { (signal.horizons || []).forEach(function (h) {
        var historical = h.historical || {}, reference = h.reference || {};
        html += '<tr><td>' + esc(signal.label) + '<br>' + esc(h.horizon) + ' 交易日<br>留存 ' + esc(h.observed) + ' · 成熟 ' + esc(h.mature) +
          '<br>等待 ' + esc(h.waiting) + ' · 未核實 ' + esc(h.unverified) + '</td><td>' + stats(historical) +
          (historical.gate === 'ok' ? '<br>過去基準均值 ' + pct(historical.meanControlRet, 2) + '<br>平均差距 ' + pct(historical.meanDeltaRet, 2) : '') +
          '</td><td>' + stats(h.forward) + '</td><td>' + stats(reference) +
          (reference.gate === 'ok' ? '<br>過去基準均值 ' + pct(reference.meanControlRet, 2) + '<br>平均差距 ' + pct(reference.meanDeltaRet, 2) : '') +
          '<br>未納入對照 ' + esc(reference.missing || 0) + '</td></tr>' +
          '<tr><td colspan="4"><details><summary>' + esc(signal.label) + '／' + esc(h.horizon) + ' 日：成本假設後的報酬中位數</summary>' +
          '<div>歷史：' + costs(historical) + '</div><div>全部真實成熟結果：' + costs(h.forward) + '</div><div>具過去對照的前瞻子集合：' + costs(reference) + '</div></details></td></tr>';
      }); });
      html += '</tbody></table></div><div class="sh5-foot" style="overflow-wrap:anywhere">完整規則指紋 ' + esc(group.rulesDigest) + '</div></details>';
    });
    html += '<details><summary>比較口徑與限制</summary>' + (p.limitations || []).map(function (line) { return '<p class="sh5-foot">' + esc(line) + '</p>'; }).join('') +
      '<div class="sh5-foot" style="overflow-wrap:anywhere">方法指紋 ' + esc(p.currentMethodDigest || '未知') + '</div></details>';
    return html + '<button type="button" class="sh5-btn" data-comparison-refresh>重新讀取對照</button>';
  }
  function loadPool(market) {
    return getJson('/stock-signals/pooled?market=' + (market || 'TW')).then(function (p) { poolCache = p; return p; });
  }
  function loadPushCfg() {
    return getJson('/stock-signals/push-config').then(function (c) { pushCfg = c; return c; })
      .catch(function () { return null; });
  }

  function bindCard(el, d) {
    var comparisonBox = el.querySelector('#sh5-comparison');
    if (comparisonBox) {
      var comparisonFlight = false;
      var loadComparison = function () {
        if (comparisonFlight) return;
        comparisonFlight = true;
        var host = comparisonBox.querySelector('#sh5-comparison-body');
        var refresh = host.querySelector('[data-comparison-refresh]');
        if (refresh) refresh.disabled = true;
        return getJson('/stock-signals/research/status?comparison=1').then(function (p) {
          if (!comparisonBox.isConnected) return;
          host.innerHTML = comparisonHtml(p);
          host.querySelector('[data-comparison-refresh]').onclick = loadComparison;
        }).catch(function (e) {
          if (!comparisonBox.isConnected) return;
          var error = host.querySelector('[data-comparison-error]');
          if (!error) { error = document.createElement('div'); error.setAttribute('data-comparison-error', ''); error.className = 'sh5-warn'; host.appendChild(error); }
          error.textContent = '對照讀取失敗（需擁有者權限）：' + e.message;
          if (!host.querySelector('[data-comparison-refresh]')) {
            var retry = document.createElement('button'); retry.className = 'sh5-btn'; retry.setAttribute('data-comparison-refresh', ''); retry.textContent = '重試'; retry.onclick = loadComparison; host.appendChild(retry);
          }
        }).finally(function () { comparisonFlight = false; var button = host.querySelector('[data-comparison-refresh]'); if (button) button.disabled = false; });
      };
      comparisonBox.addEventListener('toggle', function () { if (comparisonBox.open) loadComparison(); });
    }
    var researchBox = el.querySelector('#sh5-research');
    if (researchBox) {
      var timer, lastResearchView;
      var loadResearch = function (force) {
        clearTimeout(timer);
        return getJson('/stock-signals/research/status').then(function (p) {
          if (!researchBox.isConnected || !researchBox.open) return;
          var body = el.querySelector('#sh5-research-body');
          var view = JSON.stringify(p);
          // 未變的輪詢保留已展開報告、較早分頁與鍵盤焦點。
          if (!force && view === lastResearchView && body.querySelector('#sh5-evidence-check')) {
            if (p.running || (p.evidenceReports || {}).running) timer = setTimeout(loadResearch, 3000);
            return;
          }
          lastResearchView = view;
          body.innerHTML = maintenanceHtml(p);
          body.querySelector('#sh5-research-status').onclick = loadResearch;
          body.querySelector('#sh5-evidence-check').onclick = function () {
            this.disabled = true;
            postJson('/stock-signals/research/refresh', { checkEvidence: true }).then(loadResearch).catch(function (e) {
              body.querySelector('#sh5-research-error').textContent = '證據檢查未啟動：' + e.message;
              body.querySelector('#sh5-evidence-check').disabled = false;
            });
          };
          body.querySelector('#sh5-report-more').onclick = function () {
            var button = this;
            button.disabled = true;
            getJson('/stock-signals/research/status?reportBefore=' + encodeURIComponent(button.getAttribute('data-before'))).then(function (next) {
              var reports = next.evidenceReports || {};
              body.querySelector('#sh5-report-history').insertAdjacentHTML('beforeend', reportHistoryHtml(reports.history));
              button.setAttribute('data-before', reports.nextBefore || '');
              button.hidden = !reports.nextBefore;
              button.disabled = false;
              if (button.hidden) body.querySelector('#sh5-evidence-check').focus();
            }).catch(function (e) {
              body.querySelector('#sh5-research-error').textContent = '較早報告未載入：' + e.message;
              button.disabled = false;
            });
          };
          body.querySelector('#sh5-schedule-save').onclick = function () {
            this.disabled = true;
            postJson('/stock-signals/research/refresh', { setSchedule: body.querySelector('#sh5-schedule-enable').checked }).then(loadResearch).catch(function (e) {
              body.querySelector('#sh5-research-error').textContent = '設定未儲存：' + e.message;
              body.querySelector('#sh5-schedule-save').disabled = false;
            });
          };
          body.querySelector('#sh5-research-refresh').onclick = function () {
            this.disabled = true;
            var c = body.querySelector('#sh5-daily-enable');
            var sourceConsent = body.querySelector('#sh5-source-consent');
            postJson('/stock-signals/research/refresh', { enableDaily: !!(c && c.checked), downloadSources: !!(sourceConsent && sourceConsent.checked) }).then(function () {
              cache = {}; poolCache = null; return loadResearch();
            }).catch(function (e) {
              body.querySelector('#sh5-research-error').textContent = '無法開始：' + e.message;
              body.querySelector('#sh5-research-refresh').disabled = false;
            });
          };
          if (p.running || (p.evidenceReports || {}).running) timer = setTimeout(loadResearch, 3000);
        }).catch(function (e) {
          var body = el.querySelector('#sh5-research-body');
          if (body) { body.innerHTML = '<div role="alert" class="sh5-warn">研究維護狀態無法讀取（需擁有者權限）：' + esc(e.message) + '</div><button class="sh5-btn" id="sh5-research-retry">重試</button>';
            body.querySelector('#sh5-research-retry').onclick = loadResearch; }
        });
      };
      researchBox.addEventListener('toggle', function () { if (researchBox.open) loadResearch(); else clearTimeout(timer); });
    }
    el.querySelectorAll('[data-sh5-mode]').forEach(function (b) {
      b.onclick = function () {
        var chosen = b.getAttribute('data-sh5-mode');
        setMode(chosen); paint(el, d);
        var active = el.querySelector('[data-sh5-mode="' + chosen + '"]');
        if (active) active.focus();
      };
    });
    var sel = el.querySelector('#sh5-push');
    var aiBox = el.querySelector('#sh5-aidigest');
    function savePush() {
      syncWatchlist(true);
      var body = { mode: sel.value };
      if (aiBox) body.aiDigest = !!aiBox.checked;
      postJson('/stock-signals/push-config', body).then(function (c) {
        pushCfg = c; paint(el, d);
      }).catch(function () {});
    }
    if (sel) sel.onchange = savePush;
    if (aiBox) aiBox.onchange = savePush;
    var pool = el.querySelector('#sh5-pool');
    if (pool) {
      var bindPool = function () {
        var rb = el.querySelector('#sh5-pool-refresh');
        if (rb) rb.onclick = function () {
          rb.disabled = true;
          postJson('/stock-signals/pooled/refresh', { market: d.market }).then(function () {
            return loadPool(d.market);
          }).then(function () {
            var body = el.querySelector('#sh5-pool-body');
            if (body) { body.innerHTML = scoreboardHtml(poolCache); bindPool(); }
          }).catch(function () { rb.disabled = false; });
        };
      };
      pool.addEventListener('toggle', function () {
        if (!pool.open) return;
        loadPool(d.market).then(function () {
          var body = el.querySelector('#sh5-pool-body');
          if (body) { body.innerHTML = scoreboardHtml(poolCache); bindPool(); }
        }).catch(function () {});
      });
      bindPool();
    }
    var btn = el.querySelector('#sh5-explain');
    if (btn) btn.onclick = function () {
      var out = el.querySelector('#sh5-ai-out');
      btn.disabled = true;
      if (out) out.innerHTML = '<div class="sh5-empty">解讀中…（AI 只引用本卡證據）</div>';
      postJson('/stock-signals/explain', { sym: d.symbol, market: d.market }, 90000).then(function (n) {
        explainCache[d.symbol + ':' + d.asOf] = n;
        if (out) out.innerHTML = aiHtml(n);
      }).catch(function (e) {
        if (out) out.innerHTML = aiHtml({ error: '解讀失敗：' + (e && e.message ? e.message : '連線錯誤') });
      }).finally(function () { btn.disabled = false; });
    };
  }

  function paint(el, d) {
    injectCSS();
    el.innerHTML = cardHtml(d, getMode(), pushCfg);
    bindCard(el, d);
  }

  function renderInto(el, force) {
    if (!el) return;
    injectCSS();
    var cur = currentSym();
    if (!cur) { el.innerHTML = '<div class="sh5"><div class="sh5-empty">先載入一檔股票。</div></div>'; return; }
    if (cur.sym.charAt(0) === '^' || cur.sym.indexOf('__') === 0) {
      el.innerHTML = '<div class="sh5"><div class="sh5-empty">指數與合成序列不做個股體檢；請載入個股或 ETF。</div></div>';
      return;
    }
    syncWatchlist(false);
    var hit = cache[cur.sym + ':' + cur.mkt];
    if (!force && hit && Date.now() - hit.at < CACHE_MS && pushCfg) {
      paint(el, hit.data);   // 45 秒自動刷新等重繪：直接用快取，避免閃爍
      return;
    }
    el.innerHTML = '<div class="sh5"><div class="sh5-empty">' + esc(cur.sym) + ' 體檢中…</div></div>';
    Promise.all([load(cur.sym, cur.mkt, force), pushCfg ? Promise.resolve(pushCfg) : loadPushCfg()]).then(function (res) {
      if (typeof S !== 'undefined' && S.tab !== 'health' && el.id === 'rpanel') return;
      var now = currentSym();
      if (!now || now.sym !== cur.sym) {       // 載入期間標的已切換：改畫新標的
        if (now) renderInto(el, false);
        return;
      }
      paint(el, res[0]);
    }).catch(function (e) {
      el.innerHTML = '<div class="sh5"><div class="sh5-empty">體檢載入失敗：' + esc(e && e.message ? e.message : '連線錯誤') + '</div></div>';
    });
  }

  // ── 自選股同步（供後端收盤摘要／即時推播）──────────────────
  function readWl() {
    try { if (typeof S !== 'undefined' && Array.isArray(S.wl)) return S.wl.slice(); } catch (e) {}
    return [];
  }
  function syncWatchlist(force) {
    var items = readWl().filter(function (w) {
      var t = String(w && w.t || '');
      return t && t.charAt(0) !== '^' && t.indexOf('__') !== 0;
    }).map(function (w) { return { sym: String(w.t).toUpperCase(), market: w.m === 'US' ? 'US' : 'TW' }; });
    var hash = JSON.stringify(items);
    if (!force && hash === lastWlHash) return;
    lastWlHash = hash;
    postJson('/stock-signals/watchlist', { symbols: items }).catch(function () {});
  }

  // ── 自選股總表（#signals 頁上方）────────────────────────────
  function boardHtml(payload) {
    var items = (payload && payload.items) || [];
    if (!items.length) return '<div class="hub-empty">自選股是空的：在圖表頁把股票加入自選後，這裡會列出每檔的體檢燈號。</div>';
    var rows = items.map(function (it) {
      if (!it.ok) {
        return '<tr data-code="' + esc(it.symbol) + '" data-mkt="' + esc(it.market) + '"><td style="color:var(--gold);font-weight:700">' +
          esc(it.symbol) + '</td><td colspan="3" style="color:var(--tlo)">' + esc(it.message || '尚無資料') + '</td></tr>';
      }
      var dots = it.lights.map(function (l) {
        return '<span class="sh5-dot" title="' + esc(l.label + '：' + l.tag) + '" style="color:' + stateColor(it.symbol, l.state) + '">' +
          esc(l.label) + (STATE_ICON[l.state] || '') + '</span>';
      }).join('');
      var today = (it.events || []).filter(function (e) { return e.barsAgo === 0; });
      var evs = today.length ? today.map(function (e) {
        return '<span style="color:' + stateColor(it.symbol, e.direction === 'risk' ? 'risk' : e.direction) + ';font-weight:700">' +
          esc(e.label) + (e.provisional ? '（暫定）' : '') + '</span>';
      }).join('、') : '<span style="color:var(--tlo)">—</span>';
      var chg = it.chgPct == null ? '' : ' <span style="color:' + stateColor(it.symbol, it.chgPct > 0 ? 'bull' : it.chgPct < 0 ? 'bear' : 'neutral') + '">' +
        (it.chgPct > 0 ? '+' : '') + num(it.chgPct) + '%</span>';
      return '<tr data-code="' + esc(it.symbol) + '" data-mkt="' + esc(it.market) + '"><td style="color:var(--gold);font-weight:700">' +
        esc(it.symbol) + '<br><span style="color:var(--thi);font-weight:600">' + num(it.close) + '</span>' + chg + '<br>資料日 ' + esc(it.asOf || '未知') + '</td>' +
        '<td>' + dots + '</td><td style="color:#dbeafe">' + esc(it.summary.sentence) + '</td><td>' + evs + '</td></tr>';
    }).join('');
    return '<table><tr><th>代號／資料日</th><th>燈號（趨勢／動能／量能／籌碼／風險）</th><th>一句話</th><th>最新資料日的新訊號</th></tr>' + rows + '</table>';
  }

  var boards = new WeakMap();
  function needsBoardRetry(it) {
    var quality = it && it.dataQuality || {};
    return !it || !it.ok || !!it.boardReadError || !!it.dataWarning || quality.status === 'attention' || quality.status === 'unknown' ||
      (it.lights || []).some(function (light) { return light.state === 'unknown'; });
  }
  function eventReviewHtml(items) {
    var groups = { fresh: [], active: [], invalidated: [], insufficient: [] };
    function actions(it) {
      return '<div class="sh5-row"><button type="button" class="sh5-btn" data-review-open="' + esc(it.symbol) + '" data-mkt="' + esc(it.market) + '">圖表與體檢證據</button>' +
        (it.market === 'TW' ? '<button type="button" class="sh5-btn" data-review-etf="' + esc(it.symbol) + '" data-sym="' + esc(it.symbol) + '" data-mkt="TW">ETF 明細</button>' : '') + '</div>';
    }
    items.forEach(function (it) {
      if (it.pending) return;
      var quality = it.dataQuality || {}, problems = (quality.items || []).filter(function (q) { return ['missing', 'stale', 'unknown'].indexOf(q.status) >= 0; });
      if (needsBoardRetry(it)) {
        groups.insufficient.push('<article class="sh5-ev"><b>' + esc(it.symbol) + ' · 資料日 ' + esc(it.asOf || '未知') + '</b><div>' +
          esc(it.boardReadError || it.message || it.dataWarning || quality.label || '部分條件資料不足') + '</div>' + problems.map(function (q) { return '<div>' + esc(q.label + ' · ' + (q.asOf || '未提供日期')) + '</div>'; }).join('') + actions(it) + '</article>');
      }
      (it.eventReview || []).forEach(function (event) {
        var key = event.status === 'invalidated' ? 'invalidated' : event.status === 'new' && event.barsAgo === 0 ? 'fresh' : 'active';
        var iv = event.invalidation || {}, level = iv.level;
        var audit = event.audit || {};
        groups[key].push('<article class="sh5-ev"><b>' + esc(it.symbol) + ' · ' + esc(event.label) + '</b><div>' +
          esc(event.statusLabel || (key === 'fresh' ? '新成立' : key === 'invalidated' ? '已失效' : '持續追蹤')) +
          (event.provisional || audit.statusProvisional ? ' · 盤中暫定' : '') + '</div><div>成立 ' + esc(event.date || '未知') +
          ' · 狀態日 ' + esc(event.statusDate || '未知') + ' · 證據截至 ' + esc(audit.evaluatedThrough || it.asOf || '未知') + '</div>' +
          '<div>依據：' + esc(event.detail || event.rule || event.plain || '請開啟體檢證據') + '</div>' +
          '<div>失效條件：' + esc(typeof iv === 'string' ? iv : iv.text || '未提供') + (level == null ? '' : ' · 成立日參考值 ' + num(level) + '（' + esc(event.date || '日期未知') + '）') +
          '</div>' + actions(it) + '</article>');
      });
    });
    var titles = { fresh: '新成立', active: '持續追蹤', invalidated: '已失效', insufficient: '資料不足' };
    return '<div class="sh5-foot">依每檔最新資料日分組；舊資料日不代表今天發生。事件狀態由目前歷史快照重建，首次觀測以每日帳本為準。ETF 明細沿用自身的比較日期。</div>' +
      Object.keys(groups).map(function (key) { return '<details class="sh5-review-group" data-review-group="' + key + '"' + (key === 'fresh' ? ' open' : '') + '><summary>' + titles[key] + ' · ' + groups[key].length + ' 筆</summary>' +
        (groups[key].join('') || '<div class="sh5-foot">目前已載入資料沒有此類項目。</div>') + '</details>'; }).join('');
  }
  function openBoardChart(code, market) {
    if (typeof S !== 'undefined') S.tab = 'health';
    if (window.ShellV5 && ShellV5.openChart) ShellV5.openChart(code, market);
    else if (typeof loadSym === 'function') loadSym(code, market);
  }
  function renderBoard(el) {
    if (!el) return;
    injectCSS();
    var syms = readWl().filter(function (w) {
      var t = String(w && w.t || '');
      return t && t.charAt(0) !== '^' && t.indexOf('__') !== 0;
    }).map(function (w) { return String(w.t).toUpperCase() + ':' + (w.m === 'US' ? 'US' : 'TW'); });
    syms = Array.from(new Set(syms));
    syncWatchlist(false);
    var state = { syms: syms, rows: {}, busy: false, failures: new Set(), attempted: new Set() };
    boards.set(el, state);
    el.innerHTML = '<div class="hub-sec sh5-board"><h4>自選股體檢與事件清單 · ' + syms.length + ' 檔' +
      '<span style="color:var(--tlo);font-weight:600;font-size:8px">點列開圖表 → 體檢分頁看細節</span></h4>' +
      '<div class="sh5-foot" data-board-progress role="status" aria-live="polite"></div><div class="sh5-row"><button type="button" class="sh5-btn" data-board-more>載入其餘</button><button type="button" class="sh5-btn" data-board-retry>重試失敗／資料不足項目</button></div>' +
      '<div class="hub-fill" id="sh5-board-body"></div><div data-board-message role="status" class="sh5-foot"></div></div>';
    var body = el.querySelector('#sh5-board-body');
    if (!syms.length) {
      body.innerHTML = boardHtml({ items: [] });
      el.querySelector('[data-board-progress]').textContent = '自選共 0 檔';
      el.querySelector('[data-board-more]').disabled = true;
      el.querySelector('[data-board-retry]').disabled = true;
      return;
    }
    function current() { return el.isConnected && boards.get(el) === state; }
    function paintBoard() {
      if (!current()) return;
      var open = Array.from(body.querySelectorAll('details[open]')).map(function (d) { return d.getAttribute('data-review-group') || 'legacy'; });
      var hadContent = !!body.firstChild, top = body.scrollTop, left = body.scrollLeft;
      var oldTable = body.querySelector('table'), sorting = oldTable && window.TableSortV5 ? TableSortV5.capture(oldTable) : null;
      var items = syms.map(function (s) { return state.rows[s] || { symbol: s.split(':')[0], market: s.split(':')[1], ok: false, pending: true, message: '待載入' }; });
      var pending = syms.length - state.attempted.size;
      el.querySelector('[data-board-progress]').textContent = '自選共 ' + syms.length + ' 檔 · 已完成 ' + (state.attempted.size - state.failures.size) + ' 檔 · 失敗／資料不足 ' + state.failures.size + ' 檔 · 待載入 ' + pending + ' 檔' + (state.busy ? ' · 載入中' : '') + ' · 每批最多 40 檔，僅讀本機資料';
      el.querySelector('[data-board-more]').disabled = state.busy || !pending;
      el.querySelector('[data-board-retry]').disabled = state.busy || !state.failures.size;
      body.innerHTML = eventReviewHtml(items) + '<details data-board-legacy open><summary>完整體檢總表 · ' + syms.length + ' 檔</summary><div style="overflow:auto">' + boardHtml({ items: items }) + '</div></details>';
      if (hadContent) body.querySelectorAll('details').forEach(function (d) { d.open = open.indexOf(d.getAttribute('data-review-group') || 'legacy') >= 0; });
      if (window.TableSortV5) TableSortV5.restore(body.querySelector('table'), sorting);
      body.scrollTop = top; body.scrollLeft = left;
      body.querySelectorAll('tr[data-code]').forEach(function (tr) {
        tr.onclick = function () {
          openBoardChart(tr.getAttribute('data-code'), tr.getAttribute('data-mkt') || 'TW');
        };
      });
      body.querySelectorAll('[data-review-open]').forEach(function (button) { button.onclick = function () { openBoardChart(button.getAttribute('data-review-open'), button.getAttribute('data-mkt')); }; });
      body.querySelectorAll('[data-review-etf]').forEach(function (button) { button.onclick = function () {
        if (window.EtfFlowTip) EtfFlowTip.openForChip(button, { interaction: 'click' });
        else el.querySelector('[data-board-message]').textContent = 'ETF 明細模組尚未就緒，請稍後重試。';
      }; });
    }
    async function loadBatches(list) {
      if (state.busy || !current()) return;
      state.busy = true; paintBoard();
      try {
        for (var offset = 0; offset < list.length && current(); offset += 40) {
          var batch = list.slice(offset, offset + 40), bySymbol = {};
          try {
            var payload = await getJson('/stock-signals/batch?cacheOnly=1&syms=' + encodeURIComponent(batch.join(',')));
            if (!payload || !Array.isArray(payload.items)) throw new Error('批次資料格式不完整');
            payload.items.forEach(function (row) { bySymbol[row.symbol + ':' + row.market] = row; });
          } catch (_) { /* 個別批次失敗仍保留其他批次，並列入重試清單。 */ }
          if (!current()) return;
          batch.forEach(function (s) {
            var row = bySymbol[s];
            state.attempted.add(s);
            if ((!row || !row.ok) && state.rows[s] && state.rows[s].ok) {
              row = Object.assign({}, state.rows[s], { boardReadError: '本次讀取失敗，保留最後成功資料；可再重試。' });
            }
            if (needsBoardRetry(row)) state.failures.add(s); else state.failures.delete(s);
            state.rows[s] = row || { symbol: s.split(':')[0], market: s.split(':')[1], ok: false, message: '此批次讀取失敗，請重試' };
          });
          paintBoard();
        }
      } finally { state.busy = false; paintBoard(); }
    }
    el.querySelector('[data-board-more]').onclick = function () { loadBatches(syms.filter(function (s) { return !state.attempted.has(s); })); };
    el.querySelector('[data-board-retry]').onclick = function () { loadBatches(Array.from(state.failures)); };
    loadBatches(syms.slice(0, 40));
  }

  window.StockHealthV5 = Object.freeze({
    renderInto: renderInto,
    renderBoard: renderBoard,
    syncWatchlist: syncWatchlist,
    cardHtml: cardHtml,
    boardHtml: boardHtml,
    eventReviewHtml: eventReviewHtml,
    statsLine: statsLine,
    scoreboardHtml: scoreboardHtml,
    comparisonHtml: comparisonHtml,
    qualityHtml: qualityHtml,
    sensitivityHtml: sensitivityHtml,
    maintenanceHtml: maintenanceHtml,
    evidenceReportHtml: evidenceReportHtml,
    getMode: getMode,
    setMode: setMode
  });
}());

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
    }).then(function (r) { return r.json(); });
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
      '.sh5-ai{margin-top:8px;font-size:12px;line-height:1.7;color:#e2e8f0;padding:8px 10px;border-radius:8px;border:1px solid rgba(165,180,252,.3);background:rgba(99,102,241,.08)}' +
      '.sh5-ai .cite{font:700 8.5px "JetBrains Mono",monospace;color:#a5b4fc;margin-left:3px}' +
      '.sh5-warn{color:#fbbf24;font-size:10.5px;margin-top:4px}' +
      '.sh5-board table{width:100%;border-collapse:collapse}' +
      '.sh5-board td,.sh5-board th{padding:5px 6px;border-bottom:1px solid rgba(34,50,74,.6);font-size:11px;text-align:left;vertical-align:top}' +
      '.sh5-board tr[data-code]{cursor:pointer}' +
      '.sh5-board tr[data-code]:hover{background:rgba(251,191,36,.06)}' +
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
    return rows.map(function (r) {
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
    var html = '<div class="sh5">' + head + warn + lightsHtml(d, mode) +
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
      html += '<div class="sh5-sec"><details id="sh5-pool"><summary style="cursor:pointer;font:800 11px \'Noto Sans TC\',sans-serif;color:var(--gold,#fbbf24)">' +
        '訊號成績單（同市場合併統計：哪些訊號真的有資訊？）</summary><div id="sh5-pool-body">' + scoreboardHtml(poolCache) + '</div></details></div>';
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
  function loadPool(market) {
    return getJson('/stock-signals/pooled?market=' + (market || 'TW')).then(function (p) { poolCache = p; return p; });
  }
  function loadPushCfg() {
    return getJson('/stock-signals/push-config').then(function (c) { pushCfg = c; return c; })
      .catch(function () { return null; });
  }

  function bindCard(el, d) {
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
        esc(it.symbol) + '<br><span style="color:var(--thi);font-weight:600">' + num(it.close) + '</span>' + chg + '</td>' +
        '<td>' + dots + '</td><td style="color:#dbeafe">' + esc(it.summary.sentence) + '</td><td>' + evs + '</td></tr>';
    }).join('');
    return '<table><tr><th>代號</th><th>燈號（趨勢／動能／量能／籌碼／風險）</th><th>一句話</th><th>今日新訊號</th></tr>' + rows + '</table>';
  }

  function renderBoard(el) {
    if (!el) return;
    injectCSS();
    var syms = readWl().filter(function (w) {
      var t = String(w && w.t || '');
      return t && t.charAt(0) !== '^' && t.indexOf('__') !== 0;
    }).slice(0, 40).map(function (w) { return String(w.t).toUpperCase() + ':' + (w.m === 'US' ? 'US' : 'TW'); });
    syncWatchlist(false);
    el.innerHTML = '<div class="hub-sec sh5-board"><h4>自選股體檢 · ' + syms.length + ' 檔' +
      '<span style="color:var(--tlo);font-weight:600;font-size:8px">點列開圖表 → 體檢分頁看細節</span></h4>' +
      '<div class="hub-fill" id="sh5-board-body"><div class="hub-loading">體檢中…</div></div></div>';
    var body = el.querySelector('#sh5-board-body');
    if (!syms.length) { body.innerHTML = boardHtml({ items: [] }); return; }
    getJson('/stock-signals/batch?syms=' + encodeURIComponent(syms.join(','))).then(function (p) {
      body.innerHTML = boardHtml(p);
      body.querySelectorAll('tr[data-code]').forEach(function (tr) {
        tr.onclick = function () {
          var code = tr.getAttribute('data-code');
          var mkt = tr.getAttribute('data-mkt') || 'TW';
          if (typeof S !== 'undefined') S.tab = 'health';
          if (window.ShellV5 && ShellV5.openChart) ShellV5.openChart(code, mkt);
          else if (typeof loadSym === 'function') loadSym(code, mkt);
        };
      });
    }).catch(function (e) {
      body.innerHTML = '<div class="hub-empty">自選股體檢載入失敗：' + esc(e && e.message ? e.message : '連線錯誤') + '</div>';
    });
  }

  window.StockHealthV5 = Object.freeze({
    renderInto: renderInto,
    renderBoard: renderBoard,
    syncWatchlist: syncWatchlist,
    cardHtml: cardHtml,
    boardHtml: boardHtml,
    statsLine: statsLine,
    scoreboardHtml: scoreboardHtml,
    getMode: getMode,
    setMode: setMode
  });
}());

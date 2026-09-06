/* Shadow Conditional Expectation card — GET /research/conditional-expectation (flag-gated). */
(function () {
  'use strict';

  var HORIZONS = [1, 5, 20];
  var DISCLAIMER =
    '歷史條件統計 ≠ 未來保證；非投資建議。本卡不得覆寫 Decision／Action Envelope 曝險或信心。';
  var inflight = {};

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function isEnabled() {
    return !!(window.FeatureFlags && FeatureFlags.isEnabled &&
      FeatureFlags.isEnabled('shadowConditionalExpectation'));
  }

  function epistemicBadge(tier, note) {
    if (window.EpistemicBadgesV5 && window.EpistemicBadgesV5.badge) {
      return window.EpistemicBadgesV5.badge(tier, { note: note, compact: true });
    }
    return '<span class="st-epistemic" data-epistemic="' + esc(tier) + '">' + esc(tier) + '</span>';
  }

  function injectCSS() {
    if (document.getElementById('conditional-expectation-v5-css')) return;
    var style = document.createElement('style');
    style.id = 'conditional-expectation-v5-css';
    style.textContent =
      '.st-ce-card{border:1px solid rgba(103,232,249,.28);border-radius:8px;background:linear-gradient(145deg,rgba(8,18,32,.96),rgba(6,12,22,.98));' +
        'padding:8px 10px;margin-top:8px;color:var(--text,#cdd6e4);font-family:"JetBrains Mono",monospace}' +
      '.st-ce-card.expired{border-color:rgba(148,163,184,.28);background:linear-gradient(145deg,rgba(14,18,26,.92),rgba(10,12,18,.96));' +
        'filter:saturate(.55)}' +
      '.st-ce-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px}' +
      '.st-ce-title{font:800 11px/1.35 "Noto Serif TC",serif;color:var(--thi,#f2f5fa)}' +
      '.st-ce-tags{display:flex;align-items:center;gap:5px;flex-wrap:wrap}' +
      '.st-ce-tag{display:inline-flex;padding:1px 6px;border-radius:999px;border:1px solid #36516e;color:#94a3b8;font:700 8px/1.2 "JetBrains Mono",monospace}' +
      '.st-ce-bin{font-size:10px;color:#a5b4c8;margin:2px 0 6px;line-height:1.45}' +
      '.st-ce-asof{font-size:9px;color:#7f93ab;margin-bottom:6px;line-height:1.5}' +
      '.st-ce-table{width:100%;border-collapse:collapse;font-size:9px;margin:4px 0 6px}' +
      '.st-ce-table th,.st-ce-table td{padding:4px 5px;border-bottom:1px solid rgba(38,54,79,.85);text-align:right;vertical-align:middle}' +
      '.st-ce-table th:first-child,.st-ce-table td:first-child{text-align:left;color:#8da2ba;font-weight:700}' +
      '.st-ce-table th{color:#7c8fa8;font-weight:700;background:rgba(8,16,28,.55)}' +
      '.st-ce-muted{color:#64748b}.st-ce-up{color:var(--red,#ff7a76)}.st-ce-down{color:var(--green,#43df92)}' +
      '.st-ce-expired{padding:8px 9px;border:1px dashed rgba(148,163,184,.35);border-radius:6px;color:#94a3b8;' +
        'background:rgba(15,23,42,.45);font-size:10px;line-height:1.55;margin:4px 0 6px}' +
      '.st-ce-invalid{font-size:9px;color:#fbbf24;margin:2px 0 4px;line-height:1.45}' +
      '.st-ce-foot{font-size:9px;color:#75869d;line-height:1.5;margin-top:4px}' +
      '.st-ce-loading{font-size:10px;color:#8da2ba;padding:6px 2px}' +
      '.st-ce-error{font-size:10px;color:var(--red,#ff7a76);padding:6px 2px}';
    document.head.appendChild(style);
  }

  function num(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    return n.toFixed(digits == null ? 2 : digits);
  }

  function pct(value) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    return (n * 100).toFixed(1) + '%';
  }

  function signedPct(value) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    return (n > 0 ? '+' : '') + n.toFixed(2) + '%';
  }

  function pctClass(value) {
    var n = Number(value);
    if (!isFinite(n) || n === 0) return 'st-ce-muted';
    return n > 0 ? 'st-ce-up' : 'st-ce-down';
  }

  function asOfLine(card) {
    var asOf = (card && card.evidenceAsOf) || {};
    var parts = [];
    if (asOf.quote) parts.push('報價 ' + esc(String(asOf.quote)));
    if (asOf.chips) parts.push('籌碼 ' + esc(String(asOf.chips)));
    if (asOf.regime) parts.push('regime ' + esc(String(asOf.regime)));
    return parts.length ? parts.join(' ｜ ') : 'asOf 待更新';
  }

  function isPredictionUsable(card) {
    if (!card) return false;
    var gate = card.asOfGate || {};
    if (gate.usable === false) return false;
    var invalid = card.invalidIf || [];
    if (invalid.indexOf('asof_gate_expired') >= 0) return false;
    return String(card.status || '').toUpperCase() === 'READY';
  }

  function horizonRows(card) {
    var horizons = (card && card.horizons) || {};
    return HORIZONS.map(function (h) {
      var row = horizons[String(h)] || {};
      var ready = !!row.ratesAvailable;
      return '<tr><td>T+' + h + '</td><td>' + (ready ? esc(String(row.n || 0)) : esc(String(row.n || 0)) + '*') +
        '</td><td>' + (ready ? pct(row.winRate) : '—') + '</td><td class="' + pctClass(row.medianReturnPct) + '">' +
        (ready ? signedPct(row.medianReturnPct) : '—') + '</td><td>' +
        (ready ? signedPct(row.maxDrawdownQ90Pct) : '—') + '</td></tr>';
    }).join('');
  }

  function invalidHtml(card) {
    var invalid = (card && card.invalidIf) || [];
    if (!invalid.length) return '';
    var labels = {
      asof_gate_expired: 'asOf 閘門逾期',
      n_below_minimum: '樣本未達 minimumSample',
      insufficient_bar_history: '歷史 K 線不足'
    };
    return '<div class="st-ce-invalid">invalidIf：' + invalid.map(function (key) {
      return esc(labels[key] || key);
    }).join(' · ') + '</div>';
  }

  function renderHtml(card, opts) {
    injectCSS();
    opts = opts || {};
    if (!card) {
      return '<div class="st-ce-card st-ce-loading">Conditional Expectation 無資料。</div>';
    }
    var usable = isPredictionUsable(card);
    var expired = !usable;
    var cls = expired ? ' st-ce-card expired' : ' st-ce-card';
    var status = String(card.status || '—');
    var gate = card.asOfGate || {};
    var html = '<div class="' + cls.trim() + '" data-ce-symbol="' + esc(card.symbol || opts.symbol || '') + '">' +
      '<div class="st-ce-head"><div class="st-ce-title">條件期望研究 · ' + esc(card.symbol || opts.symbol || '—') + '</div>' +
      '<div class="st-ce-tags">' + epistemicBadge('CONDITIONAL') +
      '<span class="st-ce-tag">Shadow · 研究</span><span class="st-ce-tag">' + esc(status) + '</span></div></div>' +
      '<div class="st-ce-bin">' + esc(card.binLabel || card.binId || '分箱待建立') + '</div>' +
      '<div class="st-ce-asof">asOf · ' + asOfLine(card) + '</div>';
    if (expired) {
      html += '<div class="st-ce-expired">資料過期 · 不適合作為預測參考' +
        (gate.reasons && gate.reasons.length ? '<br>' + esc(gate.reasons.join('；')) : '') + '</div>';
    }
    html += invalidHtml(card) +
      '<table class="st-ce-table" aria-label="條件期望統計"><thead><tr><th>Horizon</th><th>N</th><th>Win</th>' +
      '<th>Median</th><th>MaxDD Q90</th></tr></thead><tbody>' + horizonRows(card) + '</tbody></table>' +
      '<div class="st-ce-foot">' + esc(DISCLAIMER) +
      (card.minimumSample != null ? ' · minimumSample=' + esc(String(card.minimumSample)) : '') +
      (rowNote(card)) + '</div></div>';
    return html;
  }

  function rowNote(card) {
    var horizons = (card && card.horizons) || {};
    var withheld = HORIZONS.some(function (h) {
      var row = horizons[String(h)] || {};
      return !row.ratesAvailable && Number(row.n || 0) > 0;
    });
    return withheld ? ' · * 樣本未達門檻，勝率／中位數 withheld' : '';
  }

  function fetchCard(symbol) {
    var sym = String(symbol || '').trim().toUpperCase();
    if (!sym || !isEnabled()) return Promise.resolve(null);
    if (inflight[sym]) return inflight[sym];
    var base = window.SERVER || location.origin || 'http://localhost:18432';
    inflight[sym] = fetch(base + '/research/conditional-expectation?symbol=' + encodeURIComponent(sym), {
      cache: 'no-store'
    }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (payload) {
      delete inflight[sym];
      if (!payload || !payload.enabled) return null;
      return payload.card || null;
    }).catch(function () {
      delete inflight[sym];
      return null;
    });
    return inflight[sym];
  }

  function mountInto(container, symbol, card) {
    if (!container) return Promise.resolve(null);
    if (!isEnabled()) {
      container.innerHTML = '';
      container.hidden = true;
      return Promise.resolve(null);
    }
    container.hidden = false;
    container.innerHTML = '<div class="st-ce-loading">載入條件期望…</div>';
    var done = function (resolved) {
      if (!resolved) {
        container.innerHTML = '<div class="st-ce-error">條件期望研究不可用（旗標關閉或資料不足）。</div>';
        return resolved;
      }
      container.innerHTML = renderHtml(resolved, { symbol: symbol });
      return resolved;
    };
    if (card) return Promise.resolve(done(card));
    return fetchCard(symbol).then(done);
  }

  function statsPanelHost() {
    return document.getElementById('rpanel');
  }

  function ensureStatsSection() {
    var host = statsPanelHost();
    if (!host) return null;
    var sect = document.getElementById('st-ce-sect');
    if (sect) return sect;
    sect = document.createElement('div');
    sect.id = 'st-ce-sect';
    host.appendChild(sect);
    return sect;
  }

  function refreshStatsPanel(detail) {
    if (!isEnabled()) {
      var existing = document.getElementById('st-ce-sect');
      if (existing) existing.remove();
      return;
    }
    detail = detail || {};
    var sym = String(detail.sym || (window.S && S.sym) || '').trim().toUpperCase();
    var mkt = String(detail.mkt || (window.S && S.mkt) || 'TW').toUpperCase();
    if (!sym || mkt !== 'TW') {
      var hidden = document.getElementById('st-ce-sect');
      if (hidden) hidden.remove();
      return;
    }
    if (typeof window.S !== 'undefined' && S.tab && S.tab !== 'stats') return;
    mountInto(ensureStatsSection(), sym);
  }

  window.ConditionalExpectationV5 = {
    isEnabled: isEnabled,
    fetch: fetchCard,
    renderHtml: renderHtml,
    mountInto: mountInto,
    refreshStatsPanel: refreshStatsPanel,
    disclaimer: DISCLAIMER
  };

  window.addEventListener('symLoaded', function (event) {
    refreshStatsPanel((event && event.detail) || {});
  });
  window.addEventListener('featureFlags', function () {
    if (!isEnabled()) {
      var sect = document.getElementById('st-ce-sect');
      if (sect) sect.remove();
    } else {
      refreshStatsPanel({ sym: window.S && S.sym, mkt: window.S && S.mkt });
    }
  });
}());

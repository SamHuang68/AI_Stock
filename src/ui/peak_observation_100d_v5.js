/* st-peak-100d-v0 observation card — GET /research/peak-observation-100d (CONDITIONAL only). */
(function () {
  'use strict';

  function disclaimerFor(symbol) {
    var sym = String(symbol || '—').trim().toUpperCase();
    return sym + '：100 交易日區間高點收盤價之觀察指標，非投資建議；不得作為進場／加碼／部署依據；'
      + '不代表「歷史高點」或全期最高價。';
  }

  var inflight = {};

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function isEnabled() {
    return !!(window.FeatureFlags && FeatureFlags.isEnabled &&
      FeatureFlags.isEnabled('shadowPeak100d'));
  }

  function epistemicBadge() {
    if (window.EpistemicBadgesV5 && window.EpistemicBadgesV5.badge) {
      return window.EpistemicBadgesV5.badge('CONDITIONAL', {
        note: 'st-peak-100d-v0',
        compact: true
      });
    }
    return '<span class="st-epistemic" data-epistemic="CONDITIONAL">CONDITIONAL</span>';
  }

  function injectCSS() {
    if (document.getElementById('peak-observation-100d-v5-css')) return;
    var style = document.createElement('style');
    style.id = 'peak-observation-100d-v5-css';
    style.textContent =
      '.st-pk100-card{border:1px solid rgba(56,189,248,.28);border-radius:8px;background:linear-gradient(145deg,rgba(8,20,32,.96),rgba(6,12,22,.98));' +
        'padding:8px 10px;margin-top:8px;color:var(--text,#cdd6e4);font-family:"JetBrains Mono",monospace}' +
      '.st-pk100-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px}' +
      '.st-pk100-title{font:800 11px/1.35 "Noto Serif TC",serif;color:var(--thi,#f2f5fa)}' +
      '.st-pk100-tags{display:flex;align-items:center;gap:5px;flex-wrap:wrap}' +
      '.st-pk100-tag{display:inline-flex;padding:1px 6px;border-radius:999px;border:1px solid #0e7490;color:#38bdf8;font:700 8px/1.2 "JetBrains Mono",monospace}' +
      '.st-pk100-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:6px 0}' +
      '.st-pk100-metric{padding:5px 6px;border-radius:6px;background:rgba(8,24,40,.55);border:1px solid rgba(14,116,144,.45)}' +
      '.st-pk100-k{font-size:8px;color:#67a8c4;text-transform:uppercase;letter-spacing:.04em}' +
      '.st-pk100-v{font-size:12px;font-weight:800;color:#bae6fd;margin-top:2px}' +
      '.st-pk100-asof{font-size:9px;color:#7f93ab;margin-bottom:4px;line-height:1.5}' +
      '.st-pk100-null{font-size:10px;color:#fbbf24;padding:6px 8px;border:1px dashed rgba(251,191,36,.35);border-radius:6px;margin:4px 0}' +
      '.st-pk100-foot{font-size:9px;color:#38bdf8;line-height:1.55;margin-top:6px;padding:6px 8px;border-radius:6px;' +
        'background:rgba(8,47,73,.35);border:1px solid rgba(56,189,248,.22)}' +
      '.st-pk100-loading,.st-pk100-error{font-size:10px;padding:6px 2px}' +
      '.st-pk100-loading{color:#8da2ba}.st-pk100-error{color:var(--red,#ff7a76)}';
    document.head.appendChild(style);
  }

  function pctBelowPeak(value) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    return (n * 100).toFixed(2) + '%';
  }

  function price(value) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    return n.toFixed(2);
  }

  function renderHtml(obs, opts) {
    injectCSS();
    opts = opts || {};
    if (!obs) {
      return '<div class="st-pk100-card st-pk100-loading">100d peak observation 無資料。</div>';
    }
    var sym = obs.symbol || opts.symbol || '—';
    var html = '<div class="st-pk100-card" data-pk100-symbol="' + esc(sym) + '">' +
      '<div class="st-pk100-head"><div class="st-pk100-title">100 交易日距峰值 · ' + esc(sym) + '</div>' +
      '<div class="st-pk100-tags">' + epistemicBadge() +
      '<span class="st-pk100-tag">st-peak-100d-v0</span><span class="st-pk100-tag">peakKind A</span>' +
      '<span class="st-pk100-tag">' + esc(String(obs.windowDays || 100)) + ' sessions</span></div></div>' +
      '<div class="st-pk100-asof">asOf ' + esc(obs.asOf || '—') +
      ' · basis ' + esc(obs.priceBasis || '—') +
      ' · cutoff ' + esc(obs.knowledgeCutoff || '—') + '</div>';

    if (obs.pctBelowPeak == null) {
      html += '<div class="st-pk100-null">數值不可用：' + esc(obs.nullReason || '資料不足') + '</div>';
    } else {
      html += '<div class="st-pk100-metrics">' +
        '<div class="st-pk100-metric"><div class="st-pk100-k">pct below peak</div><div class="st-pk100-v">' +
        esc(pctBelowPeak(obs.pctBelowPeak)) + '</div></div>' +
        '<div class="st-pk100-metric"><div class="st-pk100-k">peak close</div><div class="st-pk100-v">' +
        esc(price(obs.peakClose)) + '</div></div>' +
        '<div class="st-pk100-metric"><div class="st-pk100-k">last close</div><div class="st-pk100-v">' +
        esc(price(obs.lastClose)) + '</div></div></div>' +
        '<div class="st-pk100-asof">peakDate ' + esc(obs.peakDate || '—') +
        ' · historyStart ' + esc(obs.historyStart || '—') + '</div>';
    }
    if (obs.pitLimitation) {
      html += '<div class="st-pk100-asof">PIT：' + esc(obs.pitLimitation) + '</div>';
    }
    html += '<div class="st-pk100-foot" role="note" aria-live="polite">' + esc(disclaimerFor(sym)) + '</div></div>';
    return html;
  }

  function fetchObservation(symbol) {
    var sym = String(symbol || '').trim().toUpperCase();
    if (!sym || !isEnabled()) return Promise.resolve(null);
    if (inflight[sym]) return inflight[sym];
    var base = window.SERVER || location.origin || 'http://localhost:18432';
    inflight[sym] = fetch(base + '/research/peak-observation-100d?symbol=' + encodeURIComponent(sym), {
      cache: 'no-store'
    }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (payload) {
      delete inflight[sym];
      if (!payload || !payload.enabled) return null;
      return payload.observation || null;
    }).catch(function () {
      delete inflight[sym];
      return null;
    });
    return inflight[sym];
  }

  function mountInto(container, symbol, observation) {
    if (!container) return Promise.resolve(null);
    if (!isEnabled()) {
      container.innerHTML = '';
      container.hidden = true;
      return Promise.resolve(null);
    }
    container.hidden = false;
    container.innerHTML = '<div class="st-pk100-loading">載入 100d peak observation…</div>';
    var done = function (resolved) {
      if (!resolved) {
        container.innerHTML = '<div class="st-pk100-error">100d peak observation 不可用（旗標關閉或資料不足）。</div>';
        return resolved;
      }
      container.innerHTML = renderHtml(resolved, { symbol: symbol });
      return resolved;
    };
    if (observation) return Promise.resolve(done(observation));
    return fetchObservation(symbol).then(done);
  }

  function statsPanelHost() {
    return document.getElementById('rpanel');
  }

  function ensureStatsSection() {
    var host = statsPanelHost();
    if (!host) return null;
    var sect = document.getElementById('st-pk100-sect');
    if (sect) return sect;
    sect = document.createElement('div');
    sect.id = 'st-pk100-sect';
    host.appendChild(sect);
    return sect;
  }

  function refreshStatsPanel(detail) {
    if (!isEnabled()) {
      var existing = document.getElementById('st-pk100-sect');
      if (existing) existing.remove();
      return;
    }
    detail = detail || {};
    var sym = String(detail.sym || (window.S && S.sym) || '').trim().toUpperCase();
    var mkt = String(detail.mkt || (window.S && S.mkt) || 'TW').toUpperCase();
    if (!sym || mkt !== 'TW') {
      var hidden = document.getElementById('st-pk100-sect');
      if (hidden) hidden.remove();
      return;
    }
    if (typeof window.S !== 'undefined' && S.tab && S.tab !== 'stats') return;
    mountInto(ensureStatsSection(), sym);
  }

  window.PeakObservation100dV5 = {
    isEnabled: isEnabled,
    fetch: fetchObservation,
    renderHtml: renderHtml,
    mountInto: mountInto,
    refreshStatsPanel: refreshStatsPanel,
    disclaimerFor: disclaimerFor
  };

  window.addEventListener('symLoaded', function (event) {
    refreshStatsPanel((event && event.detail) || {});
  });
  window.addEventListener('featureFlags', function () {
    if (!isEnabled()) {
      var sect = document.getElementById('st-pk100-sect');
      if (sect) sect.remove();
    } else {
      refreshStatsPanel({ sym: window.S && S.sym, mkt: window.S && S.mkt });
    }
  });
}());

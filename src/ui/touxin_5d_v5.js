/* st-touxin-5d-v0 observation card — GET /research/touxin-5d-netbuy (CONDITIONAL only). */
(function () {
  'use strict';

  function disclaimerFor(symbol) {
    var sym = String(symbol || '—').trim().toUpperCase();
    return sym + '：投信 5 日買超％／名次為歷史籌碼觀察，非投資建議；不得作為進場／加碼／部署依據；'
      + '不代表未來法人動向或買賣訊號。';
  }

  var inflight = {};

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function isEnabled() {
    return !!(window.FeatureFlags && FeatureFlags.isEnabled &&
      FeatureFlags.isEnabled('shadowTouxin5d'));
  }

  function epistemicBadge() {
    if (window.EpistemicBadgesV5 && window.EpistemicBadgesV5.badge) {
      return window.EpistemicBadgesV5.badge('CONDITIONAL', {
        note: 'st-touxin-5d-v0',
        compact: true
      });
    }
    return '<span class="st-epistemic" data-epistemic="CONDITIONAL">CONDITIONAL</span>';
  }

  function injectCSS() {
    if (document.getElementById('touxin-5d-v5-css')) return;
    var style = document.createElement('style');
    style.id = 'touxin-5d-v5-css';
    style.textContent =
      '.st-tx-card{border:1px solid rgba(56,189,248,.28);border-radius:8px;background:linear-gradient(145deg,rgba(8,18,28,.96),rgba(6,10,18,.98));' +
        'padding:8px 10px;margin-top:8px;color:var(--text,#cdd6e4);font-family:"JetBrains Mono",monospace}' +
      '.st-tx-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px}' +
      '.st-tx-title{font:800 11px/1.35 "Noto Serif TC",serif;color:var(--thi,#f2f5fa)}' +
      '.st-tx-tags{display:flex;align-items:center;gap:5px;flex-wrap:wrap}' +
      '.st-tx-tag{display:inline-flex;padding:1px 6px;border-radius:999px;border:1px solid #1e4d6b;color:#38bdf8;font:700 8px/1.2 "JetBrains Mono",monospace}' +
      '.st-tx-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:6px 0}' +
      '.st-tx-metric{padding:5px 6px;border-radius:6px;background:rgba(10,20,32,.55);border:1px solid rgba(30,77,107,.45)}' +
      '.st-tx-k{font-size:8px;color:#5b8fb8;text-transform:uppercase;letter-spacing:.04em}' +
      '.st-tx-v{font-size:12px;font-weight:800;color:#bae6fd;margin-top:2px}' +
      '.st-tx-asof{font-size:9px;color:#7f93ab;margin-bottom:4px;line-height:1.5}' +
      '.st-tx-null{font-size:10px;color:#fbbf24;padding:6px 8px;border:1px dashed rgba(251,191,36,.35);border-radius:6px;margin:4px 0}' +
      '.st-tx-foot{font-size:9px;color:#38bdf8;line-height:1.55;margin-top:6px;padding:6px 8px;border-radius:6px;' +
        'background:rgba(14,116,144,.18);border:1px solid rgba(56,189,248,.22)}' +
      '.st-tx-loading,.st-tx-error{font-size:10px;padding:6px 2px}' +
      '.st-tx-loading{color:#8da2ba}.st-tx-error{color:var(--red,#ff7a76)}';
    document.head.appendChild(style);
  }

  function fmtShares(value) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    if (Math.abs(n) >= 10000) return (n / 1000).toFixed(1) + 'k';
    return n.toFixed(0);
  }

  function fmtPct(value) {
    var n = Number(value);
    if (!isFinite(n)) return '—';
    return (n * 100).toFixed(2) + '%';
  }

  function renderHtml(obs, opts) {
    injectCSS();
    opts = opts || {};
    if (!obs) {
      return '<div class="st-tx-card st-tx-loading">投信 5 日買超觀察無資料。</div>';
    }
    var sym = obs.symbol || opts.symbol || '—';
    var html = '<div class="st-tx-card" data-tx-symbol="' + esc(sym) + '">' +
      '<div class="st-tx-head"><div class="st-tx-title">投信 5 日買超 · ' + esc(sym) + '</div>' +
      '<div class="st-tx-tags">' + epistemicBadge() +
      '<span class="st-tx-tag">st-touxin-5d-v0</span><span class="st-tx-tag">window 5</span></div></div>' +
      '<div class="st-tx-asof">asOf ' + esc(obs.asOf || '—') +
      ' · source ' + esc(obs.source || '—') +
      ' · cutoff ' + esc(obs.knowledgeCutoff || '—') + '</div>';

    if (obs.netBuyShares == null) {
      html += '<div class="st-tx-null">數值不可用：' + esc(obs.pitLimitation || '資料不足') + '</div>';
    } else {
      html += '<div class="st-tx-metrics">' +
        '<div class="st-tx-metric"><div class="st-tx-k">5d net buy</div><div class="st-tx-v">' +
        esc(fmtShares(obs.netBuyShares)) + ' 股</div></div>' +
        '<div class="st-tx-metric"><div class="st-tx-k">net buy %</div><div class="st-tx-v">' +
        esc(fmtPct(obs.netBuyPct)) + '</div></div>' +
        '<div class="st-tx-metric"><div class="st-tx-k">rank</div><div class="st-tx-v">' +
        (obs.rankAmongUniverse != null
          ? esc('#' + obs.rankAmongUniverse + ' / ' + (obs.universeSize || '—'))
          : '—') + '</div></div></div>';
    }
    if (obs.pitLimitation) {
      html += '<div class="st-tx-asof">PIT：' + esc(obs.pitLimitation) + '</div>';
    }
    html += '<div class="st-tx-foot" role="note" aria-live="polite">' + esc(disclaimerFor(sym)) + '</div></div>';
    return html;
  }

  function fetchObservation(symbol) {
    var sym = String(symbol || '').trim().toUpperCase();
    if (!sym || !isEnabled()) return Promise.resolve(null);
    if (inflight[sym]) return inflight[sym];
    var base = window.SERVER || location.origin || 'http://localhost:18432';
    inflight[sym] = fetch(base + '/research/touxin-5d-netbuy?symbol=' + encodeURIComponent(sym), {
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
    container.innerHTML = '<div class="st-tx-loading">載入投信 5 日買超觀察…</div>';
    var done = function (resolved) {
      if (!resolved) {
        container.innerHTML = '<div class="st-tx-error">投信 5 日買超觀察不可用（旗標關閉或資料不足）。</div>';
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
    var sect = document.getElementById('st-tx-sect');
    if (sect) return sect;
    sect = document.createElement('div');
    sect.id = 'st-tx-sect';
    host.appendChild(sect);
    return sect;
  }

  function refreshStatsPanel(detail) {
    if (!isEnabled()) {
      var existing = document.getElementById('st-tx-sect');
      if (existing) existing.remove();
      return;
    }
    detail = detail || {};
    var sym = String(detail.sym || (window.S && S.sym) || '').trim().toUpperCase();
    var mkt = String(detail.mkt || (window.S && S.mkt) || 'TW').toUpperCase();
    if (!sym || mkt !== 'TW') {
      var hidden = document.getElementById('st-tx-sect');
      if (hidden) hidden.remove();
      return;
    }
    if (typeof window.S !== 'undefined' && S.tab && S.tab !== 'stats') return;
    mountInto(ensureStatsSection(), sym);
  }

  window.Touxin5dV5 = {
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
      var sect = document.getElementById('st-tx-sect');
      if (sect) sect.remove();
    } else {
      refreshStatsPanel({ sym: window.S && S.sym, mkt: window.S && S.mkt });
    }
  });
}());

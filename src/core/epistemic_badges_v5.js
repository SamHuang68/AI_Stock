/* Unified epistemic tier badges — FACT | CONDITIONAL | HYPOTHESIS */
(function () {
  'use strict';

  var TIERS = {
    FACT: {
      label: 'FACT',
      title: '可重算、可稽核的確定事實；非預測機率'
    },
    CONDITIONAL: {
      label: 'CONDITIONAL',
      title: '歷史條件分箱期望；非未來保證、非買賣訊號'
    },
    HYPOTHESIS: {
      label: 'HYPOTHESIS',
      title: '假說或敘事整理；須以 EvidencePack 數字核對'
    }
  };

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function injectCSS() {
    if (document.getElementById('epistemic-badges-v5-css')) return;
    var style = document.createElement('style');
    style.id = 'epistemic-badges-v5-css';
    style.textContent =
      '.st-epistemic{display:inline-flex;align-items:center;gap:4px;padding:1px 7px;border-radius:999px;' +
        'border:1px solid currentColor;font:800 8px/1.35 "JetBrains Mono",monospace;letter-spacing:.35px;' +
        'vertical-align:middle;white-space:nowrap}' +
      '.st-epistemic[data-epistemic="FACT"]{color:#f5c451;border-color:rgba(245,196,81,.55);' +
        'background:rgba(245,196,81,.08);box-shadow:0 0 10px rgba(245,196,81,.08)}' +
      '.st-epistemic[data-epistemic="CONDITIONAL"]{color:#67e8f9;border-color:rgba(103,232,249,.45);' +
        'background:rgba(34,211,238,.08);box-shadow:0 0 10px rgba(34,211,238,.08)}' +
      '.st-epistemic[data-epistemic="HYPOTHESIS"]{color:#c4b5fd;border-color:rgba(196,181,253,.42);' +
        'background:rgba(167,139,250,.08);box-shadow:0 0 10px rgba(167,139,250,.06)}' +
      '.st-epistemic .st-epistemic-note{font:600 8px/1.2 "Noto Sans TC",sans-serif;color:inherit;opacity:.92}' +
      '.st-epistemic.compact .st-epistemic-note{display:none}';
    document.head.appendChild(style);
  }

  function badge(tier, opts) {
    injectCSS();
    var key = String(tier || '').toUpperCase();
    var meta = TIERS[key] || TIERS.FACT;
    opts = opts || {};
    var note = opts.note != null ? opts.note : '';
    var compact = opts.compact ? ' compact' : '';
    var title = opts.title || meta.title;
    if (note) title = title + ' · ' + note;
    return '<span class="st-epistemic' + compact + '" data-epistemic="' + esc(key) + '" title="' +
      esc(title) + '"><span class="st-epistemic-label">' + esc(meta.label) + '</span>' +
      (note ? '<span class="st-epistemic-note">' + esc(note) + '</span>' : '') + '</span>';
  }

  window.EpistemicBadgesV5 = {
    tiers: TIERS,
    badge: badge,
    injectCSS: injectCSS
  };
}());

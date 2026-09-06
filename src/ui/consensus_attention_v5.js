/* Consensus Radar: a bounded, deterministic view over DecisionData. */
(function () {
  'use strict';

  var ACK_KEY = 'st_consensus_ack_v1';
  var MAX_VISIBLE = 3;
  var MAX_ITEMS = 5;
  var ACTIONABLE = { WATCH: 1, ARMED: 1, CONFIRMED: 1, ACTIVE: 1, CONFLICT: 1 };
  var projection = null;
  var expanded = false;
  var open = false;

  function $(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  function ackMap() {
    try {
      var parsed = JSON.parse(localStorage.getItem(ACK_KEY) || '{}');
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (e) { return {}; }
  }
  function writeAck(map) {
    try {
      var rows = Object.keys(map).sort(function (a, b) { return String(map[b]).localeCompare(String(map[a])); });
      var bounded = {};
      rows.slice(0, 160).forEach(function (key) { bounded[key] = map[key]; });
      localStorage.setItem(ACK_KEY, JSON.stringify(bounded));
    } catch (e) {}
  }
  function isExpired(item) {
    var expires = item && item.freshness && item.freshness.expiresAt;
    var ms = expires ? Date.parse(expires) : NaN;
    return Number.isFinite(ms) && Date.now() > ms;
  }
  function isAlert(item) {
    return !!(item && ACTIONABLE[item.lifecycleState] &&
      item.freshness && item.freshness.status === 'fresh' && !isExpired(item));
  }
  function unreadItems() {
    var ack = ackMap();
    return (((projection || {}).items) || []).filter(function (item) {
      return isAlert(item) && !ack[item.eventKey];
    });
  }
  function acknowledge(item) {
    if (!item || !item.eventKey) return;
    var ack = ackMap();
    ack[item.eventKey] = new Date().toISOString();
    writeAck(ack);
    render();
    updateFab();
  }
  function acknowledgeAll() {
    var ack = ackMap();
    (((projection || {}).items) || []).forEach(function (item) {
      if (isAlert(item) && item.eventKey) ack[item.eventKey] = new Date().toISOString();
    });
    writeAck(ack);
    render();
    updateFab();
  }
  function directionMeta(item) {
    var direction = String((item || {}).direction || 'mixed');
    if (direction === 'upside') return { icon: '▲', label: '偏多', cls: 'up' };
    if (direction === 'downside') return { icon: '▼', label: '偏空', cls: 'down' };
    if (direction === 'risk') return { icon: '◆', label: '曝險', cls: 'risk' };
    return { icon: '◇', label: '分歧', cls: 'mixed' };
  }
  function stateLabel(value) {
    return {
      OBSERVATION: '觀察', WATCH: '留意', ARMED: '蓄勢', CONFIRMED: '確認',
      ACTIVE: '作用中', CONFLICT: '衝突', RECOVERY: '修復', INVALIDATED: '失效'
    }[value] || value || '觀察';
  }
  function themeLabel(value) {
    return {
      market_structure: '市場結構', headline_precursor: '方向前兆',
      ai_anchor_chain: 'AI 錨點鏈', memory_cycle: '記憶體週期', owner_exposure: '持倉曝險'
    }[value] || value || '觀察';
  }
  function freshnessLabel(item) {
    if (isExpired(item)) return '已逾時・凍結';
    var status = item && item.freshness && item.freshness.status;
    return status === 'fresh' ? '資料有效' : status === 'degraded' ? '新鮮度下降・凍結' : '資料過期・凍結';
  }
  function itemHtml(item, ack) {
    var dir = directionMeta(item);
    var read = !!ack[item.eventKey];
    var frozen = !isAlert(item) && item.lifecycleState !== 'OBSERVATION';
    var strength = Math.max(0, Math.min(100, Number(item.strength || 0)));
    var conflict = item.conflict && item.conflict.flag;
    return '<article class="ca-card sev-' + esc(item.severity) + (read ? ' read' : '') + (frozen ? ' frozen' : '') + '" data-ca-id="' + esc(item.id) + '">' +
      '<button type="button" class="ca-main" data-ca-open="' + esc(item.eventKey) + '">' +
        '<span class="ca-card-top"><span class="ca-theme">' + esc(themeLabel(item.theme)) + '</span>' +
          '<span class="ca-state">' + esc(stateLabel(item.lifecycleState)) + '</span></span>' +
        '<span class="ca-title">' + esc(item.title) + '</span>' +
        '<span class="ca-signal ' + dir.cls + '"><b>' + dir.icon + '</b> ' + esc(dir.label) +
          '<span class="ca-strength">證據 ' + Math.round(strength) + '</span></span>' +
        '<span class="ca-meter"><i style="width:' + strength.toFixed(0) + '%"></i></span>' +
        '<span class="ca-insight">' + esc(item.insight || '等待更多證據。') + '</span>' +
        '<span class="ca-meta">' + esc(freshnessLabel(item)) + ' · ' +
          esc(String(item.independentDomains || 0)) + ' 個獨立來源域' +
          (conflict ? ' · 存在反向證據' : '') + '</span>' +
      '</button>' +
      '<button type="button" class="ca-ack" data-ca-ack="' + esc(item.eventKey) + '"' +
        (read ? ' disabled' : '') + '>' + (read ? '已讀' : '標記已讀') + '</button>' +
    '</article>';
  }
  function ensureCss() {
    if ($('consensus-attention-v5-css')) return;
    var style = document.createElement('style');
    style.id = 'consensus-attention-v5-css';
    style.textContent =
      '#st-ring-fab{overflow:visible!important}' +
      '#st-ring-fab .ca-fab-icon{font-size:20px;line-height:1;text-shadow:0 0 10px rgba(56,189,248,.55)}' +
      '#st-ring-fab .ca-fab-badge{position:absolute;right:-5px;top:-5px;min-width:17px;height:17px;padding:0 4px;' +
        'box-sizing:border-box;border-radius:999px;display:flex;align-items:center;justify-content:center;' +
        'background:#f59e0b;color:#07111d;border:2px solid #07111d;font:900 9px/1 "JetBrains Mono",monospace;' +
        'box-shadow:0 0 11px rgba(245,158,11,.55)}' +
      '#st-ring-fab .ca-fab-badge:empty{display:none}' +
      '#ca-layer{position:fixed;inset:0;z-index:235;display:none;color:#e8eef8;font-family:"Noto Sans TC",sans-serif}' +
      '#ca-layer.on{display:block}' +
      '#ca-layer .ca-backdrop{position:absolute;inset:0;border:0;background:rgba(2,7,16,.58);' +
        'backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}' +
      '#ca-layer .ca-dialog{position:absolute;right:12px;top:12px;bottom:12px;width:min(460px,calc(100vw - 24px));' +
        'display:flex;flex-direction:column;overflow:hidden;background:linear-gradient(155deg,rgba(17,30,49,.98),rgba(6,14,26,.98));' +
        'border:1px solid rgba(125,211,252,.25);border-radius:16px;box-shadow:0 22px 70px rgba(0,0,0,.66),0 0 26px rgba(56,189,248,.08)}' +
      '.ca-head{display:flex;align-items:center;gap:10px;padding:14px 14px 11px;border-bottom:1px solid rgba(148,163,184,.14);' +
        'background:linear-gradient(90deg,rgba(56,189,248,.08),rgba(245,197,24,.05))}' +
      '.ca-head-mark{width:34px;height:34px;border-radius:10px;display:flex;align-items:center;justify-content:center;' +
        'font:900 22px/1 "JetBrains Mono",monospace;color:#7dd3fc;border:1px solid rgba(56,189,248,.34);' +
        'background:#091527;box-shadow:inset 0 0 12px rgba(56,189,248,.08),0 0 14px rgba(56,189,248,.12)}' +
      '.ca-head-copy{min-width:0;flex:1}.ca-head-copy h2{margin:0;color:#f8fafc;font:800 17px/1.25 "Noto Sans TC",sans-serif}' +
      '.ca-head-copy p{margin:3px 0 0;color:#8292aa;font:500 10px/1.35 "JetBrains Mono",monospace}' +
      '.ca-head button,.ca-foot button,.ca-foot a{border:1px solid rgba(148,163,184,.2);border-radius:8px;background:rgba(15,27,44,.78);' +
        'color:#cbd5e1;padding:6px 9px;font:700 10px/1.2 "Noto Sans TC",sans-serif;cursor:pointer}' +
      '.ca-head button:hover,.ca-foot button:hover,.ca-foot a:hover{border-color:rgba(125,211,252,.46);color:#7dd3fc}' +
      '.ca-body{flex:1;min-height:0;overflow:auto;padding:12px 12px 18px;overscroll-behavior:contain}' +
      '.ca-summary{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 1px 10px;color:#94a3b8;' +
        'font:600 10px/1.4 "JetBrains Mono",monospace}' +
      '.ca-summary b{color:#f5c518;font-size:12px}.ca-list{display:grid;gap:9px}' +
      '.ca-card{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;border:1px solid rgba(148,163,184,.16);' +
        'border-left:3px solid #38bdf8;border-radius:12px;background:rgba(12,24,40,.76);overflow:hidden;' +
        'box-shadow:0 8px 24px rgba(0,0,0,.22);transition:border-color .16s,transform .16s}' +
      '.ca-card:hover{border-color:rgba(125,211,252,.34);transform:translateY(-1px)}' +
      '.ca-card.sev-warning,.ca-card.sev-critical{border-left-color:#f59e0b}.ca-card.sev-watch{border-left-color:#facc15}' +
      '.ca-card.read{opacity:.70}.ca-card.frozen{filter:saturate(.65)}' +
      '.ca-main{appearance:none;border:0;background:transparent;color:inherit;text-align:left;padding:11px 8px 11px 12px;' +
        'min-width:0;display:flex;flex-direction:column;gap:5px;cursor:pointer}' +
      '.ca-card-top{display:flex;align-items:center;gap:6px}.ca-theme{color:#7dd3fc;font:700 10px/1.2 "JetBrains Mono",monospace}' +
      '.ca-state{margin-left:auto;padding:2px 6px;border:1px solid rgba(245,197,24,.24);border-radius:999px;color:#facc15;' +
        'background:rgba(245,197,24,.07);font:700 9px/1.2 "Noto Sans TC",sans-serif}' +
      '.ca-title{font-weight:800;font-size:15px;line-height:1.35;color:#f8fafc}.ca-signal{font:800 12px/1.3 "JetBrains Mono",monospace}' +
      '.ca-signal.up{color:#ff6b78}.ca-signal.down{color:#43df92}.ca-signal.risk{color:#f59e0b}.ca-signal.mixed{color:#7dd3fc}' +
      '.ca-strength{margin-left:8px;color:#b9c5d8;font-size:10px}.ca-meter{height:5px;border-radius:999px;background:#1b2b42;overflow:hidden}' +
      '.ca-meter i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#55d8ef,#f5c518,#fb923c)}' +
      '.ca-insight{color:#cbd5e1;font-size:11px;line-height:1.55}.ca-meta{color:#708199;font:500 9px/1.4 "JetBrains Mono",monospace}' +
      '.ca-ack{align-self:stretch;width:58px;border:0;border-left:1px solid rgba(148,163,184,.12);background:rgba(20,34,52,.56);' +
        'color:#8da0b8;font:700 9px/1.25 "Noto Sans TC",sans-serif;cursor:pointer;padding:6px}' +
      '.ca-ack:hover{color:#f5c518;background:rgba(245,197,24,.07)}.ca-ack:disabled{cursor:default;color:#56657a}' +
      '.ca-empty{padding:28px 18px;text-align:center;border:1px dashed rgba(148,163,184,.22);border-radius:12px;color:#94a3b8;' +
        'font-size:12px;line-height:1.7}.ca-foot{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px 12px calc(10px + env(safe-area-inset-bottom,0px));' +
        'border-top:1px solid rgba(148,163,184,.14);background:rgba(5,13,24,.88)}.ca-foot .primary{margin-left:auto;color:#08111f;' +
        'background:linear-gradient(135deg,#7dd3fc,#38bdf8);border-color:transparent}.ca-foot .ca-expand[hidden]{display:none}' +
      '.ca-foot .ca-doc-link{display:inline-flex;align-items:center;text-decoration:none;color:#8cecff;white-space:nowrap}' +
      '@media(max-width:900px) and (orientation:portrait){#ca-layer .ca-dialog{left:0;right:0;top:auto;bottom:0;width:100%;' +
        'max-height:min(72dvh,680px);border-radius:18px 18px 0 0;border-bottom:0}.ca-head{padding-top:12px}.ca-body{padding-bottom:14px}}' +
      '@media(max-width:900px) and (orientation:landscape){#ca-layer .ca-dialog{right:0;top:0;bottom:0;width:min(430px,44vw);' +
        'border-radius:14px 0 0 14px;border-right:0}.ca-body{padding-bottom:calc(14px + env(safe-area-inset-bottom,0px))}}' +
      '@media(prefers-reduced-motion:reduce){.ca-card{transition:none!important}}';
    document.head.appendChild(style);
  }
  function ensureLayer() {
    ensureCss();
    var layer = $('ca-layer');
    if (layer) return layer;
    layer = document.createElement('div');
    layer.id = 'ca-layer';
    layer.innerHTML = '<button type="button" class="ca-backdrop" aria-label="關閉共識雷達"></button>' +
      '<section class="ca-dialog" role="dialog" aria-modal="true" aria-labelledby="ca-title">' +
        '<header class="ca-head"><span class="ca-head-mark">◉</span><span class="ca-head-copy">' +
          '<h2 id="ca-title">共識雷達</h2><p id="ca-sub">DecisionContext 注意力投影</p></span>' +
          '<button type="button" data-ca-ack-all>全部已讀</button><button type="button" data-ca-close aria-label="關閉">✕</button></header>' +
        '<div class="ca-body" id="ca-body"></div>' +
        '<footer class="ca-foot"><button type="button" class="ca-expand" data-ca-expand>顯示全部</button>' +
          '<a class="ca-doc-link" href="/assets/docs/archify/st-decision-evidence-lineage.html" target="_blank" rel="noopener noreferrer" aria-label="在新分頁開啟決策證據鏈圖">資料怎麼形成？ ↗</a>' +
          '<button type="button" data-ca-ring>全部功能</button><button type="button" class="primary" data-ca-decision>決策中心</button></footer>' +
      '</section>';
    document.body.appendChild(layer);
    layer.querySelector('.ca-backdrop').onclick = closeRadar;
    layer.querySelector('[data-ca-close]').onclick = closeRadar;
    layer.querySelector('[data-ca-ack-all]').onclick = acknowledgeAll;
    layer.querySelector('[data-ca-expand]').onclick = function () { expanded = !expanded; render(); };
    layer.querySelector('[data-ca-ring]').onclick = function () {
      closeRadar();
      if (window.ShellV5 && ShellV5.openRing) ShellV5.openRing(window.innerWidth / 2, window.innerHeight / 2);
    };
    layer.querySelector('[data-ca-decision]').onclick = function () {
      closeRadar();
      if (window.ShellV5 && ShellV5.go) ShellV5.go('decision', { focusSection: 'summary', from: 'consensus-radar' });
    };
    return layer;
  }
  function render() {
    var layer = ensureLayer();
    var body = $('ca-body');
    var sub = $('ca-sub');
    var all = (((projection || {}).items) || []).slice(0, MAX_ITEMS);
    var visible = all.slice(0, expanded ? MAX_ITEMS : MAX_VISIBLE);
    var unread = unreadItems().length;
    var ack = ackMap();
    if (sub) sub.textContent = unread ? unread + ' 項新注意 · 僅提示，不具下單權限' : '沒有未讀高階訊號 · 持續觀察';
    body.innerHTML = '<div class="ca-summary"><span>先看共識，再進來源面板</span><b>' +
      esc(String(unread)) + ' 項需注意</b></div>' +
      (visible.length ? '<div class="ca-list">' + visible.map(function (item) { return itemHtml(item, ack); }).join('') + '</div>' :
       '<div class="ca-empty">DecisionContext 尚未形成共識投影。<br>請在總覽重新整理市場資料。</div>');
    var expand = layer.querySelector('[data-ca-expand]');
    if (expand) {
      expand.hidden = all.length <= MAX_VISIBLE;
      expand.textContent = expanded ? '收回重點' : '顯示全部 ' + all.length;
    }
    body.querySelectorAll('[data-ca-ack]').forEach(function (button) {
      button.onclick = function () {
        var item = all.find(function (row) { return row.eventKey === button.getAttribute('data-ca-ack'); });
        acknowledge(item);
      };
    });
    body.querySelectorAll('[data-ca-open]').forEach(function (button) {
      button.onclick = function () {
        var item = all.find(function (row) { return row.eventKey === button.getAttribute('data-ca-open'); });
        if (!item) return;
        acknowledge(item);
        closeRadar();
        var nav = item.navigation || {};
        if (window.ShellV5 && ShellV5.go) ShellV5.go(nav.route || 'decision', {
          focusSection: nav.focusSection || 'summary', highlightId: nav.highlightId || item.id,
          evidenceIds: item.evidenceIds || [], from: 'consensus-radar'
        });
      };
    });
  }
  function updateFab() {
    if (window.FeatureFlags && FeatureFlags.isEnabled && !FeatureFlags.isEnabled('shadowConsensusAttention')) {
      var hidden = $('ca-fab');
      if (hidden) hidden.style.display = 'none';
      return false;
    }
    var fab = $('st-ring-fab');
    if (!fab) return false;
    var badge = fab.querySelector('.ca-fab-badge');
    if (!badge) {
      fab.innerHTML = '<span class="ca-fab-icon" aria-hidden="true">◉</span><span class="ca-fab-badge"></span>';
      badge = fab.querySelector('.ca-fab-badge');
    }
    var count = unreadItems().length;
    badge.textContent = count ? String(Math.min(99, count)) : '';
    fab.title = count ? '共識雷達 · ' + count + ' 項新注意（雙擊返回儀表板）' : '共識雷達 · 目前沒有未讀高階訊號';
    fab.setAttribute('aria-label', count ? '開啟共識雷達，' + count + ' 項新注意' : '開啟共識雷達');
    return true;
  }
  function syncProjection() {
    var state = window.DecisionData && DecisionData.get ? DecisionData.get() : null;
    var summary = state && state.summary;
    var context = state && state.context;
    projection = (summary && summary.consensusAttention) || (context && context.consensusAttention) || projection;
    updateFab();
    if (open) render();
  }
  function openRadar() {
    if (window.FeatureFlags && FeatureFlags.isEnabled && !FeatureFlags.isEnabled('shadowConsensusAttention')) return;
    open = true;
    expanded = false;
    syncProjection();
    var layer = ensureLayer();
    layer.classList.add('on');
    render();
    var close = layer.querySelector('[data-ca-close]');
    if (close) close.focus();
  }
  function closeRadar() {
    open = false;
    var layer = $('ca-layer');
    if (layer) layer.classList.remove('on');
  }
  function mountFab(retries) {
    if (window.FeatureFlags && FeatureFlags.isEnabled && !FeatureFlags.isEnabled('shadowConsensusAttention')) return;
    if (updateFab()) return;
    if ((retries || 0) < 40) setTimeout(function () { mountFab((retries || 0) + 1); }, 100);
  }

  window.ConsensusAttentionV5 = {
    open: openRadar, close: closeRadar, sync: syncProjection,
    get: function () { return projection; }, ackKey: ACK_KEY,
    constants: { maxVisible: MAX_VISIBLE, maxItems: MAX_ITEMS }
  };
  window.addEventListener('decisionData', syncProjection);
  window.addEventListener('featureFlags', function () { mountFab(0); updateFab(); });
  window.addEventListener('keydown', function (event) { if (event.key === 'Escape' && open) closeRadar(); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { mountFab(0); });
  else mountFab(0);
}());

// Stock Terminal — watchlist ETF flow popover.
// Desktop: hover anywhere on a TW watchlist chip.  Mobile: open from the
// existing long-press action menu.  The badge is a visual signal, not the only
// interaction target.
(function (global) {
  'use strict';

  var SHOW_DELAY = 150;
  var HIDE_DELAY = 260;
  var _showTimer = null;
  var _hideTimer = null;
  var _activeChip = null;

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char];
    });
  }

  function stockName(sym) {
    if (typeof S === 'undefined' || !S || !Array.isArray(S.wl)) return '';
    var item = S.wl.find(function (row) { return row.t === sym && row.m === 'TW'; });
    return item && item.name || '';
  }

  function flowFor(sym) {
    if (global.EtfFlow && typeof global.EtfFlow.getStockFlow === 'function') {
      return global.EtfFlow.getStockFlow(sym);
    }
    return {
      sym: sym, available: false, freshness: 'missing', freshnessDetail: {},
      sourceError: null, added: [], removed: [], increased: [], decreased: [], unchanged: false,
    };
  }

  function ensureStyles() {
    if (document.getElementById('etf-flow-tip-styles')) return;
    var style = document.createElement('style');
    style.id = 'etf-flow-tip-styles';
    style.textContent =
      '#etf-flow-tip{position:fixed;z-index:10001;display:none;width:min(360px,calc(100vw - 16px));' +
      'max-height:calc(100dvh - 16px);overflow:auto;background:rgba(11,18,32,.98);border:1px solid #2f4a6e;' +
      'border-radius:10px;box-shadow:0 14px 38px rgba(0,0,0,.62);padding:10px 12px;' +
      'font-family:"JetBrains Mono",monospace;font-size:11px;color:#cbd5e1;line-height:1.55}' +
      '#etf-flow-tip .eft-head{display:flex;align-items:center;justify-content:space-between;gap:10px}' +
      '#etf-flow-tip .eft-h{font-weight:800;color:#f8fafc;margin-bottom:2px;font-size:12px}' +
      '#etf-flow-tip .eft-close{appearance:none;display:inline-grid;place-items:center;flex:0 0 28px;width:28px;height:28px;' +
      'margin:-5px -6px 0 0;border:1px solid rgba(148,163,184,.22);border-radius:7px;background:rgba(148,163,184,.08);' +
      'color:#cbd5e1;font:800 16px/1 sans-serif;cursor:pointer;touch-action:manipulation}' +
      '#etf-flow-tip .eft-close:hover,#etf-flow-tip .eft-close:focus-visible{color:#fff;border-color:rgba(96,165,250,.55);outline:none}' +
      '#etf-flow-tip .eft-meta{color:#8fa0b8;font-size:9.5px;margin-bottom:6px}' +
      '#etf-flow-tip .eft-fresh{display:inline-flex;align-items:center;gap:4px;padding:1px 6px;border-radius:999px;' +
      'border:1px solid rgba(56,189,248,.35);color:#67e8f9;background:rgba(56,189,248,.08)}' +
      '#etf-flow-tip .eft-fresh.stale{border-color:rgba(245,197,24,.45);color:#facc15;background:rgba(245,197,24,.10)}' +
      '#etf-flow-tip .eft-fresh.missing{border-color:rgba(148,163,184,.3);color:#a8b4c7;background:rgba(148,163,184,.08)}' +
      '#etf-flow-tip .eft-sec{margin-top:6px}' +
      '#etf-flow-tip .eft-item{display:inline-block;margin:3px 4px 0 0;padding:2px 7px;background:rgba(255,255,255,.06);' +
      'border:1px solid rgba(255,255,255,.07);border-radius:4px;cursor:pointer}' +
      '#etf-flow-tip .eft-item:hover{background:rgba(96,165,250,.22);border-color:rgba(96,165,250,.38)}' +
      '#etf-flow-tip .eft-empty{padding:7px 0;color:#94a3b8}' +
      '#etf-flow-tip .eft-error{margin-top:6px;color:#facc15;font-size:9.5px}' +
      '#etf-flow-tip .eft-foot{margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,.07);color:#65758d;font-size:9px}' +
      '.etf-flow-badge{display:inline-flex;align-items:center;padding:1px 4px;margin-left:2px;border-radius:3px;' +
      'font:700 7px/1.35 "JetBrains Mono",monospace;cursor:pointer;border:1px solid transparent}' +
      '.etf-flow-badge.buy{color:var(--red);background:rgba(248,113,113,.13);border-color:rgba(248,113,113,.24)}' +
      '.etf-flow-badge.sell{color:var(--green);background:rgba(74,222,128,.12);border-color:rgba(74,222,128,.22)}' +
      '.etf-flow-badge.mixed{color:var(--blue);background:rgba(96,165,250,.12);border-color:rgba(96,165,250,.22)}' +
      '.etf-flow-badge.stale{color:var(--gold);background:rgba(245,197,24,.10);border-color:rgba(245,197,24,.3)}' +
      '.wlchip[data-mkt="TW"]{--etf-hover-ring:rgba(96,165,250,.32)}' +
      '.wlchip[data-mkt="TW"][data-etf-flow-state="stale"]{--etf-hover-ring:rgba(245,197,24,.42)}' +
      '.wlchip[data-mkt="TW"]:hover{box-shadow:inset 0 -1px 0 var(--etf-hover-ring)}';
    document.head.appendChild(style);
  }

  function tipEl() {
    ensureStyles();
    var tip = document.getElementById('etf-flow-tip');
    if (tip) return tip;
    tip = document.createElement('div');
    tip.id = 'etf-flow-tip';
    tip.setAttribute('role', 'dialog');
    tip.setAttribute('aria-label', 'ETF 動向');
    tip.setAttribute('aria-live', 'polite');
    document.body.appendChild(tip);
    tip.addEventListener('click', function (event) {
      if (event.target.closest('.eft-close')) {
        event.preventDefault();
        close();
        return;
      }
      var item = event.target.closest('.eft-item');
      if (!item) return;
      var code = item.getAttribute('data-etf');
      if (code && typeof global.loadSym === 'function') {
        global.loadSym(code, 'TW');
        close();
      }
    });
    tip.addEventListener('mouseenter', function () { clearTimeout(_hideTimer); });
    tip.addEventListener('mouseleave', scheduleClose);
    return tip;
  }

  function fmtShares(value) {
    var number = Number(value);
    if (!Number.isFinite(number) || number === 0) return '';
    return ' · 股數' + (number > 0 ? '+' : '') + Math.round(number).toLocaleString('zh-TW');
  }

  function etfLabel(item) {
    var name = item.name && item.name !== item.code ? ' ' + item.name : '';
    var weight = Number(item.delta);
    var delta = Number.isFinite(weight) && weight !== 0
      ? ' · 權重' + (weight > 0 ? '+' : '') + weight.toFixed(2) + 'pp' : '';
    return esc(item.code) + esc(name) + '<span style="opacity:.72">' + esc(fmtShares(item.sharesDelta)) + esc(delta) + '</span>';
  }

  function section(items, color, label) {
    if (!items || !items.length) return '';
    return '<div class="eft-sec"><span style="color:' + color + ';font-weight:800">' +
      esc(label) + ' (' + items.length + ')</span><div>' + items.map(function (item) {
        return '<span class="eft-item" data-etf="' + esc(item.code) + '" title="載入 ' + esc(item.code) +
          ' 線型">' + etfLabel(item) + '</span>';
      }).join('') + '</div></div>';
  }

  function buildHtml(sym, flow) {
    var name = stockName(sym);
    var html = '<div class="eft-head"><div class="eft-h">ETF 動向 · ' + esc(sym) +
      (name ? ' ' + esc(name) : '') + '</div><button type="button" class="eft-close" ' +
      'aria-label="關閉 ETF 動向" title="關閉">×</button></div>';
    if (!flow.available) {
      var missingText = flow.freshness === 'error' ? 'ETF 資料取得失敗' : 'ETF 資料尚未取得';
      html += '<div class="eft-meta"><span class="eft-fresh missing">● ' + esc(missingText) + '</span></div>';
      if (flow.sourceError) html += '<div class="eft-error">' + esc(flow.sourceError) + '</div>';
      html += '<div class="eft-foot">資料可用後，桌機停留整張台股觀察卡即可查看；手機請長按並選擇「ETF 動向」。</div>';
      return html;
    }

    var stale = flow.freshness !== 'fresh';
    var dateText = flow.date ? '截至 ' + flow.date : '日期未知';
    var compareText = flow.prevDate ? ' · 比較 ' + flow.prevDate : '';
    html += '<div class="eft-meta"><span class="eft-fresh ' + (stale ? 'stale' : '') + '">' +
      (stale ? '◷ 資料過期' : '● 資料有效') + '</span>　' + esc(dateText + compareText) + '</div>';
    html += section(flow.added, '#f87171', '新增持股');
    html += section(flow.increased, '#fca5a5', '加碼');
    html += section(flow.removed, '#34d399', '移除持股');
    html += section(flow.decreased, '#86efac', '減碼');
    if (flow.unchanged) html += '<div class="eft-empty">本比較期無 ETF 持股異動。</div>';
    if (flow.freshnessDetail && flow.freshnessDetail.reason === 'history_contract_missing') {
      html += '<div class="eft-error">伺服器尚未提供 ETF 歷史健康資訊；此日期不能視為最新資料。</div>';
    }
    if (flow.sourceError) html += '<div class="eft-error">最近更新失敗；目前保留上一份有效資料。' + esc(flow.sourceError) + '</div>';
    html += '<div class="eft-foot">方向優先依持股股數變化判定；權重變化僅作輔助。點 ETF 代號可載入線型。</div>';
    return html;
  }

  function position(tip, anchor) {
    var viewport = global.visualViewport;
    var vx = viewport ? viewport.offsetLeft : 0;
    var vy = viewport ? viewport.offsetTop : 0;
    var vw = viewport ? viewport.width : global.innerWidth;
    var vh = viewport ? viewport.height : global.innerHeight;
    tip.style.maxHeight = Math.max(180, vh - 16) + 'px';
    var rect = anchor.getBoundingClientRect();
    var width = tip.offsetWidth;
    var height = tip.offsetHeight;
    var left = Math.max(vx + 8, Math.min(rect.left, vx + vw - width - 8));
    var below = rect.bottom + 6;
    var top = below + height <= vy + vh - 8 ? below : Math.max(vy + 8, rect.top - height - 6);
    tip.style.left = Math.round(left) + 'px';
    tip.style.top = Math.round(top) + 'px';
  }

  function traceOpen(sym, interaction, flow) {
    try {
      fetch((global.SERVER || location.origin) + '/diagnostics/ui-route', {
        method: 'POST', headers: {'Content-Type':'application/json'}, keepalive: true,
        body: JSON.stringify({
          ts: new Date().toISOString(), event: 'etf_flow_tip_opened',
          correlationId: 'etf-tip-' + Date.now(), from: interaction || 'hover', to: sym,
          state: flow.freshness, label: flow.date || flow.sourceError || 'no-data',
        }),
      }).catch(function () {});
    } catch {}
  }

  function openForChip(chip, options) {
    if (!chip || chip.getAttribute('data-mkt') !== 'TW') return false;
    var sym = chip.getAttribute('data-sym');
    if (!sym) return false;
    clearTimeout(_showTimer);
    clearTimeout(_hideTimer);
    _activeChip = chip;
    var flow = flowFor(sym);
    var tip = tipEl();
    tip.innerHTML = buildHtml(sym, flow);
    tip.style.display = 'block';
    position(tip, chip.querySelector('[data-etf-flow-trigger]') || chip);
    traceOpen(sym, options && options.interaction, flow);
    return true;
  }

  function close() {
    clearTimeout(_showTimer);
    clearTimeout(_hideTimer);
    var tip = document.getElementById('etf-flow-tip');
    if (tip) tip.style.display = 'none';
    _activeChip = null;
  }

  function scheduleClose() {
    clearTimeout(_hideTimer);
    _hideTimer = setTimeout(close, HIDE_DELAY);
  }

  function chipFrom(target) {
    if (!target || target.nodeType !== 1 || !target.closest) return null;
    return target.closest('.wlchip[data-mkt="TW"]');
  }

  function fineHover(event) {
    if (event && event.sourceCapabilities && event.sourceCapabilities.firesTouchEvents) return false;
    if (!global.matchMedia) return true;
    return global.matchMedia('(hover: hover) and (pointer: fine)').matches ||
      global.matchMedia('(any-hover: hover) and (any-pointer: fine)').matches;
  }

  document.addEventListener('mouseover', function (event) {
    if (!fineHover(event)) return;
    var chip = chipFrom(event.target);
    if (!chip || (event.relatedTarget && chip.contains(event.relatedTarget))) return;
    clearTimeout(_showTimer);
    clearTimeout(_hideTimer);
    _showTimer = setTimeout(function () { openForChip(chip, {interaction:'hover'}); }, SHOW_DELAY);
  });

  document.addEventListener('mouseout', function (event) {
    var chip = chipFrom(event.target);
    if (!chip) return;
    var related = event.relatedTarget;
    var tip = document.getElementById('etf-flow-tip');
    if ((related && chip.contains(related)) || (tip && related && tip.contains(related))) return;
    clearTimeout(_showTimer);
    scheduleClose();
  });

  document.addEventListener('click', function (event) {
    var trigger = event.target && event.target.closest && event.target.closest('[data-etf-flow-trigger]');
    if (!trigger) return;
    var chip = chipFrom(trigger);
    if (!chip) return;
    event.preventDefault();
    event.stopPropagation();
    var tip = document.getElementById('etf-flow-tip');
    if (_activeChip === chip && tip && tip.style.display !== 'none') close();
    else openForChip(chip, {interaction:'badge'});
  }, true);

  document.addEventListener('pointerdown', function (event) {
    var tip = document.getElementById('etf-flow-tip');
    if (!tip || tip.style.display === 'none') return;
    if (tip.contains(event.target)) return;
    var targetChip = chipFrom(event.target);
    if (targetChip && targetChip === _activeChip) return;
    close();
  }, true);

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      var tip = document.getElementById('etf-flow-tip');
      if (!tip || tip.style.display === 'none') return;
      event.preventDefault();
      if (event.stopImmediatePropagation) event.stopImmediatePropagation();
      else if (event.stopPropagation) event.stopPropagation();
      close();
      return;
    }
    if (event.key !== 'Enter' && event.key !== ' ') return;
    var trigger = event.target && event.target.closest && event.target.closest('[data-etf-flow-trigger]');
    if (!trigger) return;
    var chip = chipFrom(trigger);
    if (!chip) return;
    event.preventDefault();
    var tip = document.getElementById('etf-flow-tip');
    if (_activeChip === chip && tip && tip.style.display !== 'none') close();
    else openForChip(chip, {interaction:'keyboard'});
  }, true);

  global.addEventListener('scroll', function (event) {
    var tip = document.getElementById('etf-flow-tip');
    if (tip && event.target && (event.target === tip || tip.contains(event.target))) return;
    close();
  }, true);
  global.addEventListener('resize', close);
  if (global.visualViewport) global.visualViewport.addEventListener('resize', close);

  ensureStyles();
  global.EtfFlowTip = Object.freeze({ openForChip: openForChip, close: close });
  console.log('[etf-flow-tip] whole-chip hover and mobile ETF action ready');
})(window);

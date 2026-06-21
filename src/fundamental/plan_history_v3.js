// ============================================================
// Stock Terminal v3.4 — Plan History & Backtest Log
// ------------------------------------------------------------
// 為每檔 plan 記錄事件時間線，提供小型回測指標。
//
// 事件類型：
//   created          plan 建立
//   edited           欄位被修改
//   enter_buyzone    現價進入買區
//   cross_resistance 現價突破壓力
//   break_stoploss   現價跌破減碼線
//   break_weakbreak  現價跌破出場線
//   deleted          plan 刪除
//
// LocalStorage 結構：
//   { '2330': [ { ts, type, price, meta }, ... ] }
//
// 由 alert_v3 / plan_v3 各自呼叫 PlanHistoryV3.logEvent(...) 寫入。
// ============================================================

(function (global) {
  'use strict';

  const LS_KEY_HIST = 'stock_terminal_plan_history_v3';
  const MAX_EVENTS_PER_SYM = 200;  // 防止單檔事件無限累積

  let _history = {};

  function load() {
    try {
      const raw = localStorage.getItem(LS_KEY_HIST);
      _history = raw ? JSON.parse(raw) : {};
    } catch { _history = {}; }
    if (typeof _history !== 'object' || _history === null) _history = {};
  }
  function save() {
    try { localStorage.setItem(LS_KEY_HIST, JSON.stringify(_history)); } catch {}
  }

  function logEvent(sym, type, price, meta) {
    if (!sym || !type) return;
    if (!_history[sym]) _history[sym] = [];
    _history[sym].push({
      ts: Date.now(),
      type,
      price: (price != null && Number.isFinite(price)) ? +price : null,
      meta: meta || null,
    });
    // Trim to MAX_EVENTS_PER_SYM (keep most recent)
    if (_history[sym].length > MAX_EVENTS_PER_SYM) {
      _history[sym] = _history[sym].slice(-MAX_EVENTS_PER_SYM);
    }
    save();
  }

  function getHistory(sym) {
    return _history[sym] ? [..._history[sym]] : [];
  }

  function getAllHistory() {
    return { ..._history };
  }

  function clearHistory(sym) {
    if (sym) delete _history[sym];
    else _history = {};
    save();
  }

  // ─── Backtest stats ──────────────────────────────────────
  function getStats(sym) {
    const events = _history[sym] || [];
    if (events.length === 0) return null;
    const first = events[0].ts;
    const last  = events[events.length - 1].ts;
    const daysActive = Math.max(1, Math.round((Date.now() - first) / 86400000));
    const counts = {};
    for (const e of events) counts[e.type] = (counts[e.type] || 0) + 1;
    return {
      sym,
      total: events.length,
      firstTs: first,
      lastTs: last,
      daysActive,
      counts,
      // 統計：進買區 vs 破停損的比率，可粗略代表「進場機會 vs 風險觸發」
      hitRate: (counts.enter_buyzone || 0) + (counts.cross_resistance || 0),
      riskHit: (counts.break_stoploss || 0) + (counts.break_weakbreak || 0),
    };
  }

  // ─── Formatters ──────────────────────────────────────────
  const TYPE_LABEL = {
    created:          { label: '建立計畫',   icon: '📋', color: '#9CA3AF' },
    edited:           { label: '編輯計畫',   icon: '✎',  color: '#9CA3AF' },
    enter_buyzone:    { label: '進入買區',   icon: '●',  color: '#10B981' },
    cross_resistance: { label: '突破壓力',   icon: '✓',  color: '#10B981' },
    break_stoploss:   { label: '破減碼線',   icon: '⚠',  color: '#F97316' },
    break_weakbreak:  { label: '破出場線',   icon: '⚠⚠', color: '#EF4444' },
    deleted:          { label: '刪除計畫',   icon: '✕',  color: '#7F1D1D' },
  };

  function fmtTime(ts) {
    const d = new Date(ts);
    const mm = String(d.getMonth()+1).padStart(2,'0');
    const dd = String(d.getDate()).padStart(2,'0');
    const hh = String(d.getHours()).padStart(2,'0');
    const mi = String(d.getMinutes()).padStart(2,'0');
    return `${mm}/${dd} ${hh}:${mi}`;
  }

  // ─── UI: modal showing timeline of a sym ──────────────────
  function openHistoryModal(sym) {
    closeHistoryModal();
    const events = sym ? getHistory(sym) : Object.entries(_history).flatMap(([s, evs]) => evs.map(e => ({ ...e, _sym: s }))).sort((a,b)=>b.ts-a.ts);
    const stats = sym ? getStats(sym) : null;

    const modal = document.createElement('div');
    modal.id = 'plan-history-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;justify-content:center;align-items:center;';
    modal.innerHTML = `
      <div style="background:#111827;border:1px solid #374151;border-radius:8px;width:min(640px,90vw);max-height:80vh;display:flex;flex-direction:column;">
        <div style="padding:12px 16px;border-bottom:1px solid #374151;display:flex;justify-content:space-between;align-items:center;">
          <span style="font-weight:700;color:#F3F4F6;">📜 ${sym ? sym + ' 事件歷史' : '全部計畫歷史'}</span>
          <button id="ph-close" style="background:none;border:none;color:#9CA3AF;font-size:20px;cursor:pointer;">×</button>
        </div>
        ${stats ? renderStatsBar(stats) : ''}
        <div style="overflow-y:auto;padding:8px 14px;flex:1;">
          ${events.length === 0 ?
            '<div style="text-align:center;padding:32px;color:#6B7280;font-size:12px;">沒有歷史事件</div>' :
            renderTimeline(events, sym)}
        </div>
        <div style="padding:8px 14px;border-top:1px solid #374151;display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:10px;color:#6B7280;">共 ${events.length} 筆</span>
          <button id="ph-clear" style="background:#7F1D1D;border:1px solid #B91C1C;color:#FECACA;font-size:10px;padding:4px 10px;border-radius:4px;cursor:pointer;">清除 ${sym || '全部'}歷史</button>
        </div>
      </div>`;
    document.body.appendChild(modal);

    modal.querySelector('#ph-close').onclick = closeHistoryModal;
    modal.onclick = (e) => { if (e.target === modal) closeHistoryModal(); };
    modal.querySelector('#ph-clear').onclick = () => {
      if (!confirm(`確定清除 ${sym || '全部計畫'} 的歷史紀錄？`)) return;
      clearHistory(sym);
      closeHistoryModal();
    };
  }
  function closeHistoryModal() {
    const m = document.getElementById('plan-history-modal');
    if (m) m.remove();
  }

  function renderStatsBar(s) {
    return `
      <div style="padding:8px 16px;background:#0F172A;border-bottom:1px solid #1F2937;display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:11px;">
        <div><div style="color:#6B7280;font-size:9px;">追蹤天數</div><div style="color:#E5E7EB;font-weight:600;">${s.daysActive}d</div></div>
        <div><div style="color:#6B7280;font-size:9px;">事件總數</div><div style="color:#E5E7EB;font-weight:600;">${s.total}</div></div>
        <div><div style="color:#6B7280;font-size:9px;">正向觸發</div><div style="color:#10B981;font-weight:600;">${s.hitRate}</div></div>
        <div><div style="color:#6B7280;font-size:9px;">風控觸發</div><div style="color:#EF4444;font-weight:600;">${s.riskHit}</div></div>
      </div>`;
  }

  function renderTimeline(events, focusSym) {
    // Reverse chronological (newest first)
    const sorted = [...events].sort((a, b) => b.ts - a.ts);
    return sorted.map(e => {
      const t = TYPE_LABEL[e.type] || { label: e.type, icon: '•', color: '#9CA3AF' };
      const symLabel = focusSym ? '' : `<span style="color:#FBBF24;font-weight:600;margin-right:6px;">${e._sym}</span>`;
      const priceLabel = e.price != null ? `<span style="color:#D1D5DB;font-weight:600;">@${(+e.price).toFixed(2)}</span>` : '';
      const metaLabel = e.meta?.threshold != null ? `<span style="color:#6B7280;font-size:10px;">穿越 ${(+e.meta.threshold).toFixed(2)}</span>` : '';
      return `
        <div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px dotted #1F2937;">
          <div style="color:${t.color};font-size:14px;flex:0 0 28px;text-align:center;">${t.icon}</div>
          <div style="flex:1;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span>${symLabel}<span style="color:${t.color};font-weight:600;">${t.label}</span> ${priceLabel}</span>
              <span style="color:#6B7280;font-size:10px;">${fmtTime(e.ts)}</span>
            </div>
            ${metaLabel ? `<div style="margin-top:2px;">${metaLabel}</div>` : ''}
          </div>
        </div>`;
    }).join('');
  }

  // ─── Boot ─────────────────────────────────────────────────
  load();

  // ─── Expose ──────────────────────────────────────────────
  global.PlanHistoryV3 = {
    log: logEvent,
    get: getHistory,
    all: getAllHistory,
    clear: clearHistory,
    stats: getStats,
    open: openHistoryModal,
    close: closeHistoryModal,
  };

  console.log('[v3-history] module loaded —', Object.keys(_history).length, 'sym(s) tracked');

})(typeof window !== 'undefined' ? window : globalThis);

// ============================================================
// Stock Terminal v3.4 — Plan ↔ Position Linkage
// ------------------------------------------------------------
// 依 plan.role 推薦倉位大小：
//   主倉    60% 可用資金
//   動能倉  30%
//   攻擊倉  20%
//   觀察倉  10%
//
// 進場價用買區中位數 (或現價，取較低)。整股取整百股 (TW) / 整股 (US)。
// 「一鍵建倉」按鈕：填入 position_v2 setPosition 表單。
// ============================================================

(function (global) {
  'use strict';

  const LS_KEY_CAPITAL = 'stock_terminal_capital_v3';
  const DEFAULT_CAPITAL_TW = 1_000_000;   // 100 萬台幣
  const DEFAULT_CAPITAL_US = 50_000;       // 5 萬美元

  // Role → allocation % of available capital
  const ROLE_PCT = {
    '主倉':   0.60,
    '動能倉': 0.30,
    '攻擊倉': 0.20,
    '觀察倉': 0.10,
  };

  // ─── Settings ────────────────────────────────────────────
  function getCapital() {
    try {
      const raw = localStorage.getItem(LS_KEY_CAPITAL);
      if (raw) {
        const d = JSON.parse(raw);
        if (typeof d === 'object' && d) {
          return {
            TW: +d.TW || DEFAULT_CAPITAL_TW,
            US: +d.US || DEFAULT_CAPITAL_US,
          };
        }
      }
    } catch {}
    return { TW: DEFAULT_CAPITAL_TW, US: DEFAULT_CAPITAL_US };
  }
  function setCapital(tw, us) {
    const c = { TW: +tw, US: +us };
    try { localStorage.setItem(LS_KEY_CAPITAL, JSON.stringify(c)); } catch {}
    return c;
  }

  // ─── Suggestion calc ─────────────────────────────────────
  function suggest(plan, curPrice) {
    if (!plan) return null;
    const cap = getCapital();
    const totalCap = cap[plan.mkt] || cap.TW;
    const pct = ROLE_PCT[plan.role] ?? 0.10;
    const allocBudget = totalCap * pct;
    // Entry price = midpoint of buy zone, or current if buy zone missing
    let entry = null;
    if (Number.isFinite(plan.buyZoneLow) && Number.isFinite(plan.buyZoneHigh)) {
      entry = (plan.buyZoneLow + plan.buyZoneHigh) / 2;
    } else if (Number.isFinite(plan.buyZoneLow)) entry = plan.buyZoneLow;
    else if (curPrice != null && Number.isFinite(curPrice)) entry = curPrice;
    if (entry == null) return null;
    // Share count
    let shares;
    if (plan.mkt === 'TW') {
      // 台股一張 = 1000 股；給 < 100 萬時用零股 (整股單位)
      const lots = Math.floor(allocBudget / (entry * 1000));
      shares = lots > 0 ? lots * 1000 : Math.floor(allocBudget / entry);
      // Round odd lots to nearest 100
      if (lots === 0) shares = Math.floor(shares / 100) * 100;
    } else {
      shares = Math.floor(allocBudget / entry);
    }
    if (shares <= 0) shares = 1;
    const cost = entry * shares;
    return {
      sym: plan.sym,
      mkt: plan.mkt,
      role: plan.role,
      entry: +entry.toFixed(2),
      shares,
      cost: +cost.toFixed(0),
      pctOfCapital: cost / totalCap,
      target: Number.isFinite(plan.resistance) ? plan.resistance : null,
      stop:   Number.isFinite(plan.stopLoss)   ? plan.stopLoss   : (Number.isFinite(plan.weakBreak) ? plan.weakBreak : null),
      capital: totalCap,
      allocPct: pct,
      allocBudget: +allocBudget.toFixed(0),
    };
  }

  // ─── Apply: switch to POS tab + fill form ────────────────
  function applyToPosition(sym) {
    if (!S.plans || !S.plans[sym]) { alert('找不到計畫'); return false; }
    const plan = S.plans[sym];
    const curPrice = (S.sym === sym && S.data?.candles?.length)
      ? S.data.candles[S.data.candles.length - 1].close : null;
    const sug = suggest(plan, curPrice);
    if (!sug) { alert('無法計算建議倉位（缺買區或現價）'); return false; }
    const role = plan.role;
    const confirmMsg =
      `為 ${sym} (${role}) 建倉建議：\n` +
      `  進場 ${sug.entry}\n` +
      `  股數 ${sug.shares.toLocaleString()} (約 ${(sug.cost/10000).toFixed(1)} 萬)\n` +
      `  停損 ${sug.stop ?? '—'} / 目標 ${sug.target ?? '—'}\n` +
      `  佔資金 ${(sug.pctOfCapital*100).toFixed(1)}%\n\n` +
      `按確定 → 切到 POS 並填入表單\n按取消 → 直接套用到 S.positions`;
    const proceed = confirm(confirmMsg);
    if (proceed) {
      // Switch to POS tab + load symbol
      if (typeof loadSym === 'function' && S.sym !== sym) {
        S.mkt = plan.mkt;
        loadSym(sym);
      }
      if (typeof setTab === 'function') setTab('position');
      // Fill form via DOM (position_v2's input IDs may vary; try common ones)
      setTimeout(() => fillPositionForm(sug), 300);
    } else {
      // Direct apply to S.positions
      if (typeof setPosition === 'function') {
        // 切到該股以便 setPosition 用 S.sym
        const oldSym = S.sym;
        S.sym = sym;
        setPosition(sug.entry, sug.shares, sug.target, sug.stop, `${role} 計畫建倉`);
        S.sym = oldSym;
        alert('已直接寫入 S.positions');
      }
    }
    return true;
  }

  function fillPositionForm(sug) {
    // Try multiple common selectors for position_v2's form
    const candidates = [
      ['#pos-entry', sug.entry],
      ['#pos-shares', sug.shares],
      ['#pos-target', sug.target],
      ['#pos-stop', sug.stop],
      ['input[name="entry"]', sug.entry],
      ['input[name="shares"]', sug.shares],
      ['input[name="target"]', sug.target],
      ['input[name="stop"]', sug.stop],
    ];
    let filled = 0;
    for (const [sel, val] of candidates) {
      if (val == null) continue;
      const el = document.querySelector(sel);
      if (el && el.value !== undefined) {
        el.value = val;
        // Fire input event
        el.dispatchEvent(new Event('input', { bubbles: true }));
        filled++;
      }
    }
    console.log('[v3-pp] filled', filled, 'position form fields');
  }

  // ─── UI helpers used by plan_v3 card ────────────────────
  function renderSuggestionRow(sym) {
    const plan = S.plans?.[sym];
    if (!plan) return '';
    const curPrice = (S.sym === sym && S.data?.candles?.length)
      ? S.data.candles[S.data.candles.length - 1].close : null;
    const sug = suggest(plan, curPrice);
    if (!sug) return '';
    const cost10k = (sug.cost / 10000).toFixed(1);
    return `
      <div style="margin-top:6px;padding-top:6px;border-top:1px dashed #374151;display:flex;justify-content:space-between;align-items:center;font-size:10px;">
        <span style="color:#9CA3AF;">建議 <b style="color:#E5E7EB;">${sug.shares.toLocaleString()}</b> 股 @ ${sug.entry} <span style="color:#6B7280;">≈ ${cost10k}萬 (${(sug.pctOfCapital*100).toFixed(0)}%)</span></span>
        <button data-act="apply-position" data-sym="${sym}" style="background:#065F46;border:1px solid #10B981;color:#D1FAE5;font-size:10px;padding:2px 8px;border-radius:3px;cursor:pointer;">→ 建倉</button>
      </div>`;
  }

  // ─── Settings modal ──────────────────────────────────────
  function openCapitalModal() {
    closeCapitalModal();
    const cap = getCapital();
    const modal = document.createElement('div');
    modal.id = 'pp-capital-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;justify-content:center;align-items:center;';
    modal.innerHTML = `
      <div style="background:#111827;border:1px solid #374151;border-radius:8px;width:min(380px,90vw);">
        <div style="padding:12px 16px;border-bottom:1px solid #374151;display:flex;justify-content:space-between;align-items:center;">
          <span style="font-weight:700;color:#F3F4F6;">💰 設定可用資金</span>
          <button id="ppc-close" style="background:none;border:none;color:#9CA3AF;font-size:20px;cursor:pointer;">×</button>
        </div>
        <div style="padding:14px 16px;display:grid;grid-template-columns:80px 1fr;gap:10px;font-size:12px;align-items:center;">
          <span style="color:#9CA3AF;">台股 (TWD)</span>
          <input id="ppc-tw" type="number" step="10000" value="${cap.TW}" style="background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:6px 8px;border-radius:4px;">
          <span style="color:#9CA3AF;">美股 (USD)</span>
          <input id="ppc-us" type="number" step="1000" value="${cap.US}" style="background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:6px 8px;border-radius:4px;">
        </div>
        <div style="padding:0 16px 8px;font-size:10px;color:#6B7280;line-height:1.6;">
          倉位分配比率（依 plan.role）：<br>
          主倉 60% · 動能倉 30% · 攻擊倉 20% · 觀察倉 10%
        </div>
        <div style="padding:8px 16px 14px;display:flex;justify-content:flex-end;gap:6px;">
          <button id="ppc-cancel" style="background:#1F2937;border:1px solid #374151;color:#9CA3AF;padding:5px 12px;border-radius:4px;cursor:pointer;font-size:11px;">取消</button>
          <button id="ppc-save"   style="background:#065F46;border:1px solid #10B981;color:#D1FAE5;padding:5px 14px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:600;">儲存</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#ppc-close').onclick = closeCapitalModal;
    modal.querySelector('#ppc-cancel').onclick = closeCapitalModal;
    modal.onclick = (e) => { if (e.target === modal) closeCapitalModal(); };
    modal.querySelector('#ppc-save').onclick = () => {
      const tw = +document.getElementById('ppc-tw').value;
      const us = +document.getElementById('ppc-us').value;
      setCapital(tw, us);
      closeCapitalModal();
      if (typeof renderRpanel === 'function') renderRpanel();
    };
  }
  function closeCapitalModal() {
    const m = document.getElementById('pp-capital-modal');
    if (m) m.remove();
  }

  // ─── Expose ──────────────────────────────────────────────
  global.PlanPositionV3 = {
    suggest,
    apply: applyToPosition,
    renderSuggestionRow,
    openCapitalModal,
    closeCapitalModal,
    getCapital,
    setCapital,
    ROLE_PCT,
  };

  console.log('[v3-pp] module loaded — capital:', getCapital());

})(typeof window !== 'undefined' ? window : globalThis);

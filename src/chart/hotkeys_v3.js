// ============================================================
// Stock Terminal v3.9 — 全鍵盤快捷 (Hotkey Driven)
// ------------------------------------------------------------
// 追求 TradingView 式極速操作：
//   /            開啟快搜 (數字=台股, 字母=美股) Enter 直接 loadSym
//                ※「打字即搜尋」已移除:會與數值欄位(進場價/股數)搶鍵 → 欄位功能混用
//   Space        下一檔自選股   Shift+Space 上一檔
//   Alt+1~0      切時框 (對應 RANGE_DEFS)
//   Alt+M        多圖   Alt+D 價差圖   Alt+T 趨勢線(P3 畫線工具，存在才觸發)
//   /            開快搜    Esc 關閉浮層/快搜    ?  快捷表
// 防呆：在 input/textarea/select/contentEditable 內不攔截；Ctrl/Meta 組合不攔
//   (除我們自訂的 Alt 組合)。台股代號=純數字→TW，其餘→US。
// 架構守則：狀態用裸 S；沿用全域 loadSym / setRange / RANGE_DEFS。
// ============================================================
(function () {
  'use strict';

  function inEditable(el) {
    if (!el) return false;
    const tag = (el.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
  }

  // ---------- 快搜浮層 ----------
  function qsEl() { return document.getElementById('hk-qs'); }
  function ensureQs() {
    let q = qsEl();
    if (q) return q;
    style();
    q = document.createElement('div'); q.id = 'hk-qs';
    q.innerHTML = `<div id="hk-qs-box">
      <span id="hk-qs-ic">⌕</span>
      <input id="hk-qs-in" placeholder="代號…  (數字=台股, 字母=美股)  Enter 載入" maxlength="12" autocomplete="off" />
      <span id="hk-qs-hint"></span>
    </div>`;
    document.body.appendChild(q);
    const inp = q.querySelector('#hk-qs-in');
    inp.addEventListener('input', () => {
      const v = inp.value.trim().toUpperCase();
      const hint = q.querySelector('#hk-qs-hint');
      hint.textContent = v ? (/^\d/.test(v) ? '台股 TW' : '美股 US') : '';
    });
    inp.addEventListener('keydown', e => {
      e.stopPropagation();
      if (e.key === 'Enter') { commitQs(); }
      else if (e.key === 'Escape') { closeQs(); }
    });
    q.addEventListener('click', e => { if (e.target === q) closeQs(); });
    return q;
  }
  function openQs(initial) {
    const q = ensureQs();
    q.style.display = 'flex';
    const inp = q.querySelector('#hk-qs-in');
    inp.value = initial || '';
    inp.dispatchEvent(new Event('input'));
    setTimeout(() => { inp.focus(); const n = inp.value.length; try { inp.setSelectionRange(n, n); } catch {} }, 0);
  }
  function closeQs() { const q = qsEl(); if (q) q.style.display = 'none'; }
  function commitQs() {
    const inp = document.getElementById('hk-qs-in'); if (!inp) return;
    const v = inp.value.trim().toUpperCase(); if (!v) { closeQs(); return; }
    const mkt = /^\d/.test(v) ? 'TW' : 'US';
    closeQs();
    if (typeof loadSym === 'function') loadSym(v, mkt);
  }

  // ---------- 自選股切換 ----------
  function cycleWl(dir) {
    if (typeof S === 'undefined' || !Array.isArray(S.wl) || !S.wl.length) return;
    let idx = S.wl.findIndex(w => w.t === S.sym);
    if (idx < 0) idx = dir > 0 ? -1 : 0;
    let ni = (idx + dir + S.wl.length) % S.wl.length;
    const w = S.wl[ni];
    if (w && typeof loadSym === 'function') loadSym(w.t, w.m);
  }

  // ---------- 時框 ----------
  function setRangeByIndex(n) {
    if (typeof RANGE_DEFS === 'undefined' || typeof setRange !== 'function') return;
    const r = RANGE_DEFS[n];
    if (r) setRange(r.key);
  }

  // ---------- 關閉可見浮層 (Esc) ----------
  function closeAnyModal() {
    if (qsEl() && qsEl().style.display !== 'none') { closeQs(); return true; }
    const hk = document.getElementById('hk-help');
    if (hk && hk.style.display !== 'none') { hk.style.display = 'none'; return true; }
    // 已知模組 modal
    const ids = ['sp-modal', 'sc-modal', 'mc-bar'];
    for (const id of ids) {
      const m = document.getElementById(id);
      if (m && getComputedStyle(m).display !== 'none') {
        if (id === 'sp-modal' && window.spreadClose) { window.spreadClose(); return true; }
        if (id === 'mc-bar' && window.multiChartClose) { window.multiChartClose(); return true; }
        m.style.display = 'none'; return true;
      }
    }
    // 泛用：任何 *-modal 顯示中
    const open = [...document.querySelectorAll('[id$="-modal"]')].find(x => getComputedStyle(x).display !== 'none');
    if (open) { open.style.display = 'none'; return true; }
    return false;
  }

  // ---------- 快捷表 ----------
  const HELP = [
    ['/', '開啟快搜 (數字=台股 / 字母=美股) Enter 載入'],
    ['Space', '下一檔自選股'],
    ['Shift+Space', '上一檔自選股'],
    ['Alt+1…0', '切換時框 (1天/3周/1月/3月/6月/YTD/1年/2年/5年/10年)'],
    ['Alt+M', '多圖連動布局'],
    ['Alt+D', '價差 / 比值圖'],
    ['Alt+T', '趨勢線 (畫線工具)'],
    ['Esc', '關閉快搜 / 浮層'],
    ['?', '顯示 / 隱藏本快捷表'],
  ];
  function toggleHelp() {
    style();
    let h = document.getElementById('hk-help');
    if (!h) {
      h = document.createElement('div'); h.id = 'hk-help';
      h.innerHTML = `<div id="hk-help-box"><h3>⌨ 鍵盤快捷　<span style="float:right;cursor:pointer" onclick="document.getElementById('hk-help').style.display='none'">×</span></h3>` +
        HELP.map(([k, d]) => `<div class="hk-row"><kbd>${k}</kbd><span>${d}</span></div>`).join('') +
        `</div>`;
      document.body.appendChild(h);
      h.addEventListener('click', e => { if (e.target === h) h.style.display = 'none'; });
    }
    h.style.display = (h.style.display === 'none' || !h.style.display) ? 'flex' : 'none';
  }

  // ---------- 主鍵盤處理 ----------
  function onKey(e) {
    // 快搜開啟時，交給快搜自己的 handler (已 stopPropagation)
    if (qsEl() && qsEl().style.display !== 'none') {
      if (e.key === 'Escape') closeQs();
      return;
    }
    if (inEditable(e.target)) return;

    // Esc 關浮層
    if (e.key === 'Escape') { closeAnyModal(); return; }

    // ? 快捷表 (Shift+/)
    if (e.key === '?') { e.preventDefault(); toggleHelp(); return; }

    // / 開快搜
    if (e.key === '/') { e.preventDefault(); openQs(''); return; }

    // Space 切自選
    if (e.key === ' ' || e.code === 'Space') {
      e.preventDefault();
      cycleWl(e.shiftKey ? -1 : 1);
      return;
    }

    // Alt 組合
    if (e.altKey && !e.ctrlKey && !e.metaKey) {
      const k = e.key.toLowerCase();
      if (/^[0-9]$/.test(e.key)) {
        e.preventDefault();
        // 1→index0 … 9→index8, 0→index9
        const idx = e.key === '0' ? 9 : (parseInt(e.key, 10) - 1);
        setRangeByIndex(idx);
        return;
      }
      if (k === 'm') { e.preventDefault(); window.multiChartOpen && window.multiChartOpen(); return; }
      if (k === 'd') { e.preventDefault(); window.spreadOpen && window.spreadOpen(); return; }
      if (k === 't') { e.preventDefault(); (window.drawToolsTrend || window.drawToolsOpen) && (window.drawToolsTrend || window.drawToolsOpen)(); return; }
      if (k === 'h') { e.preventDefault(); (window.drawToolsHLine || window.drawToolsOpen) && (window.drawToolsHLine || window.drawToolsOpen)(); return; }
      return;
    }

    // 純 Ctrl/Meta 組合不攔 (留給瀏覽器)
    if (e.ctrlKey || e.metaKey) return;

    // 「打字即搜尋」已移除:會與數值欄位(進場價/股數)搶鍵,造成欄位功能混用。
    // 搜尋一律以明確動作觸發 → 按 / 或點上方代號框。數值欄位永遠是數值欄位。
  }

  function style() {
    if (document.getElementById('hk-style')) return;
    const s = document.createElement('style'); s.id = 'hk-style';
    s.textContent = `
    #hk-qs{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:10000;display:none;align-items:flex-start;justify-content:center}
    #hk-qs-box{margin-top:14vh;background:#0f172a;border:1px solid #fbbf24;border-radius:10px;box-shadow:0 10px 40px rgba(0,0,0,.6);display:flex;align-items:center;gap:8px;padding:10px 14px;width:min(420px,90vw)}
    #hk-qs-ic{color:#fbbf24;font-size:18px}
    #hk-qs-in{flex:1;background:transparent;border:0;outline:none;color:#e2e8f0;font-size:18px;font-family:'JetBrains Mono',monospace;letter-spacing:1px}
    #hk-qs-hint{font-size:10px;color:#64748b;min-width:40px;text-align:right}
    #hk-help{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:none;align-items:center;justify-content:center}
    #hk-help-box{background:#0f172a;border:1px solid #334155;border-radius:10px;padding:16px 18px;width:min(520px,92vw);color:#e2e8f0;font-size:12px}
    #hk-help-box h3{margin:0 0 10px;font-size:14px;color:#fbbf24}
    .hk-row{display:flex;align-items:center;gap:10px;padding:4px 0;border-bottom:1px solid #1a2740}
    .hk-row kbd{background:#1e293b;border:1px solid #334155;border-radius:5px;padding:2px 8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#fbbf24;min-width:78px;text-align:center}
    .hk-row span{color:#cbd5e1;font-size:11px}`;
    document.head.appendChild(s);
  }

  document.addEventListener('keydown', onKey, true);   // capture 期攔截
  window.hotkeysHelp = toggleHelp;
  window.hotkeysSearch = () => openQs('');
  console.log('[hotkeys] ready — / 開快搜 / Space 切自選 / Alt+數字 切時框 / ? 快捷表 (打字即搜尋已移除)');
})();

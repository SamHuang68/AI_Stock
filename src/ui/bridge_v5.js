/* ============================================================================
 * bridge_v5.js  —  Stock Terminal 5.0：工具列 → 側欄橋接
 * ----------------------------------------------------------------------------
 * 將 v3/v4 模態入口導向 ST5 側欄對應室（殼層可用時）。
 *   screener3Open      → scan（scan_v5 已掛；此處作備援）
 *   portfolioOpen      → book
 *   marketFlowOpen     → institutional
 *   instRankOpen       → institutional
 *   openAIModal        → ai（再開報告模態）
 *   copilotOpen        → ai（再開副駕）
 *   focusScanOpen      → ai（再開焦點；亦可 signals）
 * 須在各模組定義 window.*Open 之後、toolbar 整理前載入。
 * ========================================================================== */
(function () {
  'use strict';

  function wrap(name, route, opts) {
    opts = opts || {};
    function tryHook() {
      var cur = window[name];
      if (typeof cur !== 'function') return false;
      if (cur._st5Bridge) return true;
      var orig = cur._orig || cur;
      window[name] = function () {
        var args = arguments;
        if (window.ShellV5 && typeof window.ShellV5.go === 'function') {
          window.ShellV5.go(route);
          if (opts.openModal) {
            setTimeout(function () {
              try { orig.apply(null, args); }
              catch (e) { console.warn('[bridge-v5] open modal', name, e); }
            }, opts.delay != null ? opts.delay : 80);
          }
          return;
        }
        return orig.apply(null, args);
      };
      window[name]._st5Bridge = true;
      window[name]._orig = orig;
      return true;
    }
    if (!tryHook()) {
      setTimeout(tryHook, 400);
      setTimeout(tryHook, 1200);
      setTimeout(tryHook, 2500);
    }
  }

  /* 選股：優先 scan_v5 既有 hook；bridge 備援 */
  wrap('screener3Open', 'scan', { openModal: false });

  /* 投組 */
  wrap('portfolioOpen', 'book', { openModal: false });

  /* 資金流／法人榜 → 法人室（hub 已有完整資料） */
  wrap('marketFlowOpen', 'institutional', { openModal: false });
  wrap('instRankOpen', 'institutional', { openModal: false });

  /* AI 三鈕 → AI 中樞 + 開對應模態 */
  wrap('openAIModal', 'ai', { openModal: true, delay: 100 });
  wrap('copilotOpen', 'ai', { openModal: true, delay: 100 });
  wrap('focusScanOpen', 'ai', { openModal: true, delay: 100 });

  console.log('[bridge-v5] toolbar → shell bridges armed');
})();

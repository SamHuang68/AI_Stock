/* ============================================================================
 * bridge_v5.js  —  Stock Terminal 5.0：工具列 → 側欄橋接
 * ----------------------------------------------------------------------------
 * 將 v3/v4 入口導向 ST5 側欄對應室。
 *   screener3Open      → scan
 *   portfolioOpen      → book
 *   marketFlowOpen     → institutional（法人資金；原「法人榜」併入同頁）
 *   focusScanOpen      → signals（焦點掃描唯一入口：策略訊號頁，可選產業）
 *   stockFutOpen       → afterhours（個股期領先表在盤後頁，原浮層已併入）
 *   copilotOpen        → ai（AI 中樞 + 再開副駕）
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

  /* 舊 v3 模態窗（三合一選股／投組／資金流／法人榜／焦點掃描）已由側欄頁取代並移除；
     保留同名入口給工具列、指令盤與舊快捷鍵，一律導向對應頁。 */
  function routeOpener(name, route) {
    window[name] = function () {
      if (window.ShellV5 && typeof window.ShellV5.go === 'function') window.ShellV5.go(route);
    };
  }
  routeOpener('screener3Open', 'scan');
  routeOpener('portfolioOpen', 'book');
  routeOpener('marketFlowOpen', 'institutional');
  routeOpener('focusScanOpen', 'signals');
  routeOpener('stockFutOpen', 'afterhours');

  /* 副駕 → AI 中樞 + 開副駕視窗（AI 功能集中在 AI 中樞） */
  wrap('copilotOpen', 'ai', { openModal: true, delay: 100 });

  console.log('[bridge-v5] toolbar → shell bridges armed');
})();

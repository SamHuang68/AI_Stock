/* ============================================================================
 * wavedeck_bridge_v5.js — Stock Terminal → WaveDeck 入口與宏觀覆寫
 * ----------------------------------------------------------------------------
 * - 側欄「執行」由 shell_v5 action:wavedeck 呼叫 open()
 * - 可選：把 ST 進場風格推送到 WaveDeck /bridge/st
 * 鐵律：失敗僅 toast／console，不阻斷 ST 主流程。
 * ========================================================================== */
(function () {
  'use strict';

  var DEFAULT_URL = 'http://127.0.0.1:18433/';
  var CANDIDATES = [
    'http://127.0.0.1:18433/',
    'http://127.0.0.1:18434/',
    'http://127.0.0.1:18765/',
    'http://127.0.0.1:28765/',
    'http://127.0.0.1:38433/',
    'http://127.0.0.1:8765/'
  ];
  var BASE = (typeof window.WAVEDECK_URL === 'string' && window.WAVEDECK_URL)
    ? String(window.WAVEDECK_URL).replace(/\/?$/, '/')
    : DEFAULT_URL;

  function toast(msg) {
    if (typeof window.notifyToast === 'function') {
      try { window.notifyToast(String(msg)); return; } catch (e) {}
    }
    try { console.log('[WaveDeck]', msg); } catch (e2) {}
  }

  function open(url) {
    if (url) {
      window.open(url, '_blank', 'noopener');
      toast('已開啟 WaveDeck');
      return;
    }
    // 探測實際存活埠（Windows 可能因 excluded range 改埠）
    var list = [BASE].concat(CANDIDATES);
    var i = 0;
    function tryNext() {
      if (i >= list.length) {
        window.open(BASE, '_blank', 'noopener');
        toast('已開啟 WaveDeck（若空白請先 START_WAVEDECK）');
        return;
      }
      var u = list[i++];
      var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
      var t = setTimeout(function () { if (ctrl) ctrl.abort(); }, 600);
      fetch(u.replace(/\/?$/, '') + '/health', { signal: ctrl && ctrl.signal, cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
        .then(function () {
          clearTimeout(t);
          BASE = u.replace(/\/?$/, '/');
          window.open(BASE, '_blank', 'noopener');
          toast('已開啟 WaveDeck · ' + BASE);
        })
        .catch(function () {
          clearTimeout(t);
          tryNext();
        });
    }
    tryNext();
  }

  function pushOverlay(payload) {
    var body = payload || {};
    return fetch(BASE.replace(/\/$/, '') + '/bridge/st', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store'
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || j.ok === false) throw new Error((j && j.error) || r.statusText);
        return j;
      });
    });
  }

  async function ping() {
    try {
      var r = await fetch(BASE.replace(/\/$/, '') + '/health', { cache: 'no-store' });
      var j = await r.json();
      return !!(r.ok && j && j.ok);
    } catch (e) {
      return false;
    }
  }

  window.WaveDeckBridge = {
    VERSION: '5.0-WD',
    base: function () { return BASE; },
    open: open,
    pushOverlay: pushOverlay,
    ping: ping
  };

  try { console.log('[wavedeck-bridge] ready → ' + BASE); } catch (e) {}
})();

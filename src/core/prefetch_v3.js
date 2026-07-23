// ============================================================
// prefetch_v3.js — 自選／觀察股長歷史指標預熱（增量）
// ------------------------------------------------------------
// 開機與自選變更時，把清單 POST /prefetch：
//   - 無 bar → 回補 5y 一次
//   - 有 bar → 只抓近月增量
//   - tip 落後才重算 RSI/SMA/MACD/KD/techScore
// 之後 STATS 雙軸卡走 /indicators（秒回），不必每次打 Yahoo 1y。
// ============================================================
(function PrefetchV3() {
  'use strict';
  const SRV = window.SERVER || ((typeof location !== 'undefined' && location.origin) ? location.origin : 'http://localhost:18432');
  let _timer = null;
  let _lastKey = '';

  function wlItems() {
    const wl = (window.S && Array.isArray(S.wl)) ? S.wl : [];
    return wl.map(w => ({ t: String(w.t || w.sym || '').trim(), m: w.m || w.market || 'TW' }))
      .filter(x => x.t && !String(x.t).startsWith('__'));
  }

  function keyOf(items) {
    return items.map(x => x.t + '|' + x.m).sort().join(',');
  }

  async function runPrefetch(opts) {
    opts = opts || {};
    const items = opts.syms || wlItems();
    if (!items.length) return;
    const k = keyOf(items);
    if (!opts.force && k === _lastKey && !opts.resync) return;
    _lastKey = k;
    try {
      if (typeof setStat === 'function') setStat('預熱自選歷史指標…（增量）');
      const r = await fetch(SRV + '/prefetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          syms: items,
          depth: opts.depth || '5y',
          force: !!opts.force,
          sync: false,
        }),
        cache: 'no-store',
      });
      const j = await r.json().catch(() => ({}));
      if (typeof setStat === 'function') {
        setStat(j && j.started
          ? ('✓ 自選 ' + items.length + ' 檔背景預熱中')
          : ('預熱回應 ' + (j && j.okCount != null ? j.okCount : '?')));
      }
      console.log('%c[prefetch]', 'color:#38BDF8', items.length, 'syms →', j);
    } catch (e) {
      console.warn('[prefetch] failed', e);
    }
  }

  function schedule(delayMs) {
    if (_timer) clearTimeout(_timer);
    _timer = setTimeout(() => runPrefetch({ resync: true }), delayMs == null ? 1800 : delayMs);
  }

  // 開機稍晚預熱（等 S.wl 載入）
  function boot() {
    schedule(2500);
    // 自選變更後再預熱
    window.addEventListener('storage', (e) => {
      if (e && e.key && /wl|watch/i.test(e.key)) schedule(1200);
    });
    // 週期：每 30 分輕量重觸發（server 端 tip_fresh 會略過）
    setInterval(() => runPrefetch({ resync: true }), 30 * 60 * 1000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // 暴露：加自選後可手動叫
  window.Prefetch = {
    run: runPrefetch,
    schedule,
    warmSym: function (sym, mkt) {
      return runPrefetch({ syms: [{ t: sym, m: mkt || 'TW' }], force: false, resync: true });
    },
  };

  // 攔截 saveWl / 加自選後常見路徑
  const _hook = setInterval(() => {
    if (typeof window.saveWl === 'function' && !window.saveWl._prefetchHooked) {
      const orig = window.saveWl;
      window.saveWl = function () {
        const r = orig.apply(this, arguments);
        schedule(800);
        return r;
      };
      window.saveWl._prefetchHooked = true;
    }
  }, 500);
  setTimeout(() => clearInterval(_hook), 15000);
})();

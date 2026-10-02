/* 快取既有 worker 的完整輸入／公式版本；不另算技術分數、不觸發行情下載。 */
(function () {
  'use strict';
  const original = window.runWorker, memory = new Map(), inFlight = new Map();
  if (typeof original !== 'function') return;
  const prefix = 'st.indicators.v1.';
  const version = typeof WORKER_SRC === 'string' ? WORKER_SRC : '';
  const stats = { hits: 0, misses: 0, version: 'worker-input/1', cacheOnly: true };
  const clone = value => JSON.parse(JSON.stringify(value));
  const valid = value => value && Object.keys(value).length && Object.values(value).every(v => v === null || (typeof v === 'number' && Number.isFinite(v)));
  async function keyOf(candles) {
    if (!version || !globalThis.crypto?.subtle) return null;
    const bytes = new TextEncoder().encode(JSON.stringify([version, candles]));
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return prefix + Array.from(new Uint8Array(hash), x => x.toString(16).padStart(2, '0')).join('');
  }
  function save(key, result) {
    memory.set(key, clone(result));
    while (memory.size > 40) memory.delete(memory.keys().next().value);
    try {
      const keys = Object.keys(localStorage).filter(k => k.startsWith(prefix));
      while (keys.length >= 40) localStorage.removeItem(keys.shift());
      localStorage.setItem(key, JSON.stringify(result));
    } catch (_) { /* 儲存空間不足只略過持久快取，計算結果仍可用。 */ }
  }
  window.runWorker = async function (candles) {
    // JSON 會將 NaN 轉 null，故無效輸入不建立快取，避免不同缺值共用結果。
    if (!Array.isArray(candles) || candles.some(c => Object.values(c).some(v => typeof v === 'number' && !Number.isFinite(v)))) return original(candles);
    const key = await keyOf(candles);
    if (!key) return original(candles);
    let found = memory.get(key);
    if (!found) { try { found = JSON.parse(localStorage.getItem(key)); } catch (_) {} }
    if (valid(found)) { stats.hits++; return clone(found); }
    if (inFlight.has(key)) return clone(await inFlight.get(key));
    stats.misses++;
    const pending = original(candles);
    inFlight.set(key, pending);
    try { const result = await pending; if (valid(result)) save(key, result); return result; }
    finally { inFlight.delete(key); }
  };
  window.IndicatorCache = { stats: () => ({ ...stats, entries: memory.size }) };
})();

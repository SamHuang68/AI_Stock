// ============================================================
// Stock Terminal v3.4 — Price Alert Engine
// ------------------------------------------------------------
// 每 60 秒輪詢 S.plans + S.wl 的價格，與 plan 設定的價位比對。
// 跨越時：Browser Notification + console + UI 紅點。
//
// 警報類型：
//   ✓ 過壓力        cur 從 < resistance 上穿到 ≥
//   ● 進入買區      cur 從 buyZone 外進入區間內
//   ⚠ 破減碼        cur 從 > stopLoss 下穿到 ≤
//   ⚠⚠ 破出場       cur 從 > weakBreak 下穿到 ≤
//
// 去重：同一支股+同一閾值+同一天 只觸發 1 次（localStorage）
// ============================================================

(function (global) {
  'use strict';

  const SERVER = global.SERVER || 'http://localhost:18432';
  const POLL_MS = 60_000;          // 60s — 不太頻繁，避免警報轟炸
  const LS_KEY_FIRED = 'stock_terminal_alerts_fired_v3';
  const LS_KEY_LAST = 'stock_terminal_alerts_lastprice_v3';

  let _timer = null;
  let _inflight = false;
  let _lastPrice = {};   // sym → prev close
  let _firedToday = {};  // {YYYYMMDD: {sym_thr: true}}

  // ─── Persistence ────────────────────────────────────────────
  function loadFiredToday() {
    try {
      const raw = localStorage.getItem(LS_KEY_FIRED);
      _firedToday = raw ? JSON.parse(raw) : {};
    } catch { _firedToday = {}; }
    // Garbage-collect old days
    const today = ymd();
    const cleaned = {};
    if (_firedToday[today]) cleaned[today] = _firedToday[today];
    _firedToday = cleaned;
    saveFiredToday();
  }
  function saveFiredToday() {
    try { localStorage.setItem(LS_KEY_FIRED, JSON.stringify(_firedToday)); } catch {}
  }
  function loadLastPrice() {
    try {
      const raw = localStorage.getItem(LS_KEY_LAST);
      _lastPrice = raw ? JSON.parse(raw) : {};
    } catch { _lastPrice = {}; }
  }
  function saveLastPrice() {
    try { localStorage.setItem(LS_KEY_LAST, JSON.stringify(_lastPrice)); } catch {}
  }
  function ymd() {
    const d = new Date();
    return d.getFullYear() + String(d.getMonth()+1).padStart(2,'0') + String(d.getDate()).padStart(2,'0');
  }
  function alreadyFired(sym, thrKey) {
    const today = ymd();
    return !!_firedToday[today]?.[sym + '_' + thrKey];
  }
  function markFired(sym, thrKey) {
    const today = ymd();
    if (!_firedToday[today]) _firedToday[today] = {};
    _firedToday[today][sym + '_' + thrKey] = Date.now();
    saveFiredToday();
  }

  // ─── Notifications ──────────────────────────────────────────
  function requestNotificationPermission() {
    if (typeof Notification === 'undefined') return Promise.resolve('unavailable');
    if (Notification.permission === 'granted') return Promise.resolve('granted');
    if (Notification.permission === 'denied') return Promise.resolve('denied');
    return Notification.requestPermission();
  }

  function notify(title, body, sym) {
    console.log(`[v3-alert] 🔔 ${title} — ${body}`);
    // UI badge: tint PLAN tab button
    const planTab = document.getElementById('tab-plan');
    if (planTab) {
      planTab.style.boxShadow = '0 0 0 2px #EF4444';
      setTimeout(() => { planTab.style.boxShadow = ''; }, 5000);
    }
    // Browser Notification
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      try {
        const n = new Notification(title, {
          body,
          icon: '/favicon.ico',
          tag: 'alert-' + sym + '-' + Date.now(),
          silent: false,
        });
        n.onclick = () => {
          window.focus();
          if (sym && typeof loadSym === 'function') {
            const mkt = S.plans?.[sym]?.mkt || 'TW';
            S.mkt = mkt; loadSym(sym);
          }
        };
      } catch (e) { console.warn('[v3-alert] notif failed:', e); }
    }
  }

  // ─── Collect target symbols ────────────────────────────────
  function collectTargets() {
    const out = new Map();
    if (S.plans) {
      for (const sym of Object.keys(S.plans)) {
        out.set(sym, { sym, mkt: S.plans[sym].mkt || 'TW', plan: S.plans[sym] });
      }
    }
    // Watchlist 沒有 plan 就跳過 — 沒有閾值無法警報
    return [...out.values()];
  }

  function yfsym(it) {
    return it.mkt === 'TW' ? it.sym + '.TW' : it.sym;
  }

  // ─── Threshold check ──────────────────────────────────────
  // Returns array of alerts {sym, thrKey, title, body}
  function checkThresholds(sym, plan, prev, cur) {
    const alerts = [];
    if (cur == null || !Number.isFinite(cur)) return alerts;

    // 1. 過壓力 (cross UP)
    if (Number.isFinite(plan.resistance) && cur >= plan.resistance) {
      if (prev == null || prev < plan.resistance) {
        if (!alreadyFired(sym, 'resistance')) {
          alerts.push({ sym, thrKey: 'resistance',
            title: `✓ ${sym} 過壓力 ${plan.resistance}`,
            body: `現價 ${cur.toFixed(2)}（上穿 ${plan.resistance}）` });
        }
      }
    }

    // 2. 進入買區 (entered zone from outside)
    if (Number.isFinite(plan.buyZoneLow) && Number.isFinite(plan.buyZoneHigh)) {
      const inZone = cur >= plan.buyZoneLow && cur <= plan.buyZoneHigh;
      const wasInZone = prev != null && prev >= plan.buyZoneLow && prev <= plan.buyZoneHigh;
      if (inZone && !wasInZone) {
        if (!alreadyFired(sym, 'buyzone')) {
          alerts.push({ sym, thrKey: 'buyzone',
            title: `● ${sym} 進入買區 ${plan.buyZoneLow}~${plan.buyZoneHigh}`,
            body: `現價 ${cur.toFixed(2)}` });
        }
      }
    }

    // 3. 破減碼 (cross DOWN below stopLoss)
    if (Number.isFinite(plan.stopLoss) && cur < plan.stopLoss) {
      if (prev == null || prev >= plan.stopLoss) {
        if (!alreadyFired(sym, 'stoploss')) {
          alerts.push({ sym, thrKey: 'stoploss',
            title: `⚠ ${sym} 破減碼 ${plan.stopLoss}`,
            body: `現價 ${cur.toFixed(2)}（下穿 ${plan.stopLoss}）— 考慮減倉` });
        }
      }
    }

    // 4. 破出場 (cross DOWN below weakBreak)
    if (Number.isFinite(plan.weakBreak) && cur < plan.weakBreak) {
      if (prev == null || prev >= plan.weakBreak) {
        if (!alreadyFired(sym, 'weakbreak')) {
          alerts.push({ sym, thrKey: 'weakbreak',
            title: `⚠⚠ ${sym} 破出場 ${plan.weakBreak}`,
            body: `現價 ${cur.toFixed(2)}（下穿 ${plan.weakBreak}）— 出場` });
        }
      }
    }

    return alerts;
  }

  // ─── Batch fetch ──────────────────────────────────────────
  async function fetchBatch(syms) {
    if (!syms.length) return {};
    try {
      const url = `${SERVER}/yf/batch?syms=${encodeURIComponent(syms.join(','))}&range=1d&interval=1d&nocache=1`;
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) return {};
      return await r.json();
    } catch (e) {
      console.warn('[v3-alert] batch fail:', e);
      return {};
    }
  }

  function extractPrice(res) {
    const meta = res?.meta || {};
    let cur = meta.regularMarketPrice;
    if (cur == null || !Number.isFinite(cur)) {
      const closes = (res?.indicators?.quote?.[0]?.close || []).filter(x => x != null);
      cur = closes[closes.length - 1];
    }
    return (cur != null && Number.isFinite(cur)) ? cur : null;
  }

  // ─── Main poll ────────────────────────────────────────────
  async function pollOnce() {
    if (_inflight) return;
    const targets = collectTargets();
    if (targets.length === 0) return;
    _inflight = true;
    try {
      const symMap = new Map();
      for (const t of targets) symMap.set(yfsym(t), t);
      const data = await fetchBatch([...symMap.keys()]);

      const missedTw = [];
      for (const [ys, t] of symMap.entries()) {
        const res = data[ys]?.chart?.result?.[0];
        if (!res) {
          if (t.mkt === 'TW') missedTw.push(t);
          continue;
        }
        const cur = extractPrice(res);
        processAlert(t, cur);
      }
      // Retry TW with .TWO
      if (missedTw.length) {
        const data2 = await fetchBatch(missedTw.map(t => t.sym + '.TWO'));
        for (const t of missedTw) {
          const res = data2[t.sym + '.TWO']?.chart?.result?.[0];
          if (!res) continue;
          const cur = extractPrice(res);
          processAlert(t, cur);
        }
      }
    } finally {
      _inflight = false;
    }
  }

  function processAlert(t, cur) {
    if (cur == null) return;
    const prev = _lastPrice[t.sym];
    const alerts = checkThresholds(t.sym, t.plan, prev, cur);
    for (const a of alerts) {
      notify(a.title, a.body, a.sym);
      markFired(a.sym, a.thrKey);
      // Log to history
      if (typeof global.PlanHistoryV3?.log === 'function') {
        const typeMap = { resistance: 'cross_resistance', buyzone: 'enter_buyzone',
                          stoploss: 'break_stoploss', weakbreak: 'break_weakbreak' };
        const evType = typeMap[a.thrKey];
        if (evType) {
          const thr = ({
            resistance: t.plan.resistance,
            buyzone: t.plan.buyZoneLow,
            stoploss: t.plan.stopLoss,
            weakbreak: t.plan.weakBreak,
          })[a.thrKey];
          try { global.PlanHistoryV3.log(t.sym, evType, cur, { threshold: thr }); } catch {}
        }
      }
    }
    _lastPrice[t.sym] = cur;
    saveLastPrice();
  }

  // ─── Public controls ──────────────────────────────────────
  function start() {
    stop();
    setTimeout(pollOnce, 2000);
    _timer = setInterval(pollOnce, POLL_MS);
    console.log('[v3-alert] started (poll every', POLL_MS/1000, 's)');
  }
  function stop() {
    if (_timer) { clearInterval(_timer); _timer = null; }
  }

  function status() {
    const today = ymd();
    return {
      running: !!_timer,
      targets: collectTargets().length,
      firedToday: Object.keys(_firedToday[today] || {}).length,
      notifPermission: typeof Notification !== 'undefined' ? Notification.permission : 'unavailable',
    };
  }

  function clearFired() {
    _firedToday = {};
    saveFiredToday();
    console.log('[v3-alert] cleared all fired flags');
  }

  // ─── Boot ─────────────────────────────────────────────────
  (function boot() {
    if (typeof S === 'undefined' || !document.body) {
      return setTimeout(boot, 100);
    }
    loadFiredToday();
    loadLastPrice();
    start();
    // Pause when tab hidden
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stop(); else { start(); pollOnce(); }
    });
    // Request notification permission lazily — first time user creates a plan
    setTimeout(() => {
      if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
        // Don't auto-prompt; let user trigger via Plan UI if needed
        console.log('[v3-alert] Notification permission: default — will alert console-only unless user enables');
      }
    }, 3000);
  })();

  // ─── Expose ─────────────────────────────────────────────
  global.AlertV3 = {
    start, stop, pollOnce, status, clearFired,
    requestPermission: requestNotificationPermission,
    test: (sym='2330', price=1000) => processAlert(
      { sym, mkt:'TW', plan: { buyZoneLow:price-5, buyZoneHigh:price+5, stopLoss: price-10, weakBreak: price-20, resistance: price+10 } },
      price
    ),
  };

  console.log('[v3-alert] module loaded — AlertV3 controls available');

})(typeof window !== 'undefined' ? window : globalThis);

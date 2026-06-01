// ============================================================
// Stock Terminal v3.3 — Watchlist Live Price Polling
// ------------------------------------------------------------
// 每 30 秒批次抓 S.wl 所有自選股的最新報價，in-place 更新
// .wlchip-p 文字 + 顏色（不觸發 renderWl()，保留拖曳/active/scroll 狀態）。
//
// 為什麼用 in-place 而非 renderWl()：
//   • 避免每次 poll 都全表重畫導致閃爍
//   • 不會中斷拖曳手勢、不會 reset 水平 scroll 位置
//   • 不會閃掉 hover/×移除按鈕
//
// 端點：GET /yf/batch?syms=AAA.TW,BBB.TWO,...&range=2d&interval=1d
// TW 預設 .TW 後綴；無資料的 TW 股第二輪嘗試 .TWO（OTC 興櫃）
// ============================================================

(function (global) {
  'use strict';

  const SERVER = global.SERVER || `http://localhost:18432`;
  const POLL_MS = 30_000;          // 30 秒（伺服器負載 OK，又夠快）
  const INITIAL_DELAY = 300;       // 第一次 poll：頁面 ready 後 ~300ms 觸發
  // 註：不再用 1.5s 是因為等愈久使用者看到 localStorage 殘留的舊 % 愈久
  let _timer = null;
  let _inflight = false;

  // ─── helpers ─────────────────────────────────────────────
  function pcls(c) {
    if (c == null || !isFinite(c)) return 'flat';
    return c > 0 ? 'pos' : c < 0 ? 'neg' : 'flat';
  }

  function fmt(c) {
    if (c == null || !isFinite(c)) return '';
    return (c >= 0 ? '+' : '') + c.toFixed(2) + '%';
  }

  function applyToChip(w, chgPct, price) {
    w.chg = chgPct;
    w.price = price;
    const el = document.getElementById('wlp-' + w.t);
    if (!el) return;
    el.textContent = fmt(chgPct);
    el.classList.remove('pos', 'neg', 'flat');
    el.classList.add(pcls(chgPct));
  }

  function extractChg(res) {
    // ── Bug history ─────────────────────────────────────────
    // v1 用 range=2d：對 00631L 等槓桿 ETF 今日 close=null 時，
    //   fallback 到 meta.chartPreviousClose（在 range=2d 下指 3 天前）→
    //   算出昨天的 %。
    //
    // v2 改 range=1d：表面上 meta.chartPreviousClose === 昨天的 close。
    //   但實測 Yahoo query1/query2 雙伺服器盤後/盤前資料同步有時間差。
    //   當其中一台仍在「上一交易日視角」時，回傳的 1d response 為：
    //     regularMarketPrice = 上一交易日收盤（e.g. 5/27 close）
    //     chartPreviousClose = 上上一交易日收盤（e.g. 5/26 close）
    //   → 算出來變成「昨天的 %」（+4.02% 而非今天的 -3.42%）。
    //   表現為：00935/00981A/00947/00830 等 ETF 來回跳動。
    //
    // v3 改 range=5d + 用實際 candles 陣列交叉驗證：
    //   • 多根日 K 提供時間軸對齊參考
    //   • regularMarketTime vs 最後一根 candle.timestamp 判斷是否需 fallback 到 rmp
    //   • 完全避開 chartPreviousClose 的「3 天前 / 上上日」歧義
    // ───────────────────────────────────────────────────────
    const meta = res.meta || {};
    const ts = res.timestamp || [];
    const closes = res.indicators?.quote?.[0]?.close || [];

    // 1) 蒐集所有 (timestamp, close) 有效配對
    const valid = [];
    const n = Math.min(ts.length, closes.length);
    for (let i = 0; i < n; i++) {
      const c = closes[i];
      if (c != null && isFinite(c) && c > 0 && ts[i] != null) {
        valid.push({ t: ts[i], c });
      }
    }

    // 2) 主流程：有至少 2 根 candle → 用 candle 陣列算
    if (valid.length >= 2) {
      const last = valid[valid.length - 1];
      const prev = valid[valid.length - 2];
      const rmt = meta.regularMarketTime;
      const rmp = meta.regularMarketPrice;

      // 如果 regularMarketTime 比最後一根 K 線晚 > 20 小時，
      // 代表已進入新的一個交易日（但 K 線資料還沒更新到那一天）。
      // 此時：rmp 才是「今天」，last.c 是「昨天」。
      if (rmt && rmp != null && isFinite(rmp) && rmt - last.t > 20 * 3600) {
        return { cur: rmp, prev: last.c, chgPct: (rmp - last.c) / last.c * 100 };
      }
      // 否則 last.c 是「今天」（或盤中現值的近似），prev.c 是「昨天」
      // 盤中：若 rmp 有效，用 rmp 取代 last.c 作為 cur（更貼近 live 價）
      let cur = last.c;
      if (rmp != null && isFinite(rmp) && rmt && last.t && Math.abs(rmt - last.t) < 36 * 3600) {
        cur = rmp;
      }
      return { cur, prev: prev.c, chgPct: (cur - prev.c) / prev.c * 100 };
    }

    // 3) Fallback：candles 不夠 → 回到 meta 欄位
    let cur = meta.regularMarketPrice;
    if ((cur == null || !isFinite(cur)) && valid.length >= 1) cur = valid[valid.length - 1].c;
    const p = meta.chartPreviousClose ?? meta.previousClose;
    if (cur == null || p == null || !isFinite(p) || p <= 0) return null;
    return { cur, prev: p, chgPct: (cur - p) / p * 100 };
  }

  async function fetchBatch(syms) {
    if (!syms.length) return {};
    try {
      // range=5d (NOT 1d) — Yahoo query1/query2 雙伺服器盤前/盤後資料偶爾
      // 不同步，1d response 可能整份停在「上一交易日視角」，造成
      // %chg 顯示為「昨天的 %」。改 5d 拿多根 K 線，extractChg 用陣列
      // 對齊 regularMarketTime 來精準判斷哪根是「今天」、哪根是「昨天」。
      // nocache=1 — server 端 LRU 沒 TTL，不繞過就會一直拿到開機後第一次
      // 抓到的那份 stale data。
      const url = `${SERVER}/yf/batch?syms=${encodeURIComponent(syms.join(','))}&range=5d&interval=1d&nocache=1`;
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) { console.warn('[wl-live] batch HTTP', r.status); return {}; }
      return await r.json();
    } catch (e) {
      console.warn('[wl-live] batch error:', e);
      return {};
    }
  }

  // ─── main poll ────────────────────────────────────────────
  async function pollOnce() {
    if (_inflight) return;
    if (typeof S === 'undefined' || !S.wl || S.wl.length === 0) return;
    _inflight = true;
    try {
      // First pass — TW with .TW suffix, US raw
      const symMap = new Map();   // yfsym → wl item
      for (const w of S.wl) {
        const yfsym = w.m === 'TW' ? w.t + '.TW' : w.t;
        symMap.set(yfsym, w);
      }
      const syms = [...symMap.keys()];
      const data = await fetchBatch(syms);

      const missedTw = [];
      for (const [yfsym, w] of symMap.entries()) {
        const res = data[yfsym]?.chart?.result?.[0];
        if (!res) {
          if (w.m === 'TW') missedTw.push(w);
          continue;
        }
        const c = extractChg(res);
        if (c) applyToChip(w, c.chgPct, c.cur);
      }

      // Second pass — retry missed TW with .TWO (OTC / 興櫃)
      if (missedTw.length) {
        const twoSyms = missedTw.map(w => w.t + '.TWO');
        const data2 = await fetchBatch(twoSyms);
        for (const w of missedTw) {
          const res = data2[w.t + '.TWO']?.chart?.result?.[0];
          if (!res) continue;
          const c = extractChg(res);
          if (c) applyToChip(w, c.chgPct, c.cur);
        }
      }

      // After in-place updates: persist S.wl (so refresh shows last seen %)
      if (typeof saveWl === 'function') {
        try { saveWl(); } catch {}
      }
    } catch (e) {
      console.warn('[wl-live] poll fail:', e);
    } finally {
      _inflight = false;
    }
  }

  function start() {
    stop();
    setTimeout(pollOnce, INITIAL_DELAY);
    _timer = setInterval(pollOnce, POLL_MS);
  }
  function stop() {
    if (_timer) { clearInterval(_timer); _timer = null; }
  }

  // ─── boot ──────────────────────────────────────────────────
  (function boot() {
    if (typeof S === 'undefined' || !document.body) {
      return setTimeout(boot, 100);
    }
    // 開機清掉 localStorage 殘留的 chg/price — 這些可能是昨日或上週
    // 的最後一次 poll 結果，使用者打開瀏覽器會看到陳舊百分比一閃。
    // 清掉後第一次 render 顯示空白，~300ms 後第一次 poll 完成即補上。
    if (Array.isArray(S.wl)) {
      let dirty = false;
      for (const w of S.wl) {
        if (w.chg != null || w.price != null) {
          w.chg = null;
          w.price = null;
          dirty = true;
        }
      }
      if (dirty) {
        if (typeof saveWl === 'function') try { saveWl(); } catch {}
        // 重繪一次讓使用者立即看到空白而非昨日 %
        if (typeof renderWl === 'function') try { renderWl(); } catch {}
      }
    }
    start();
    // Re-poll when watchlist changes (chip added/removed/reordered)
    if (typeof addToWl === 'function' && !global._wlLiveHookedAdd) {
      global._wlLiveHookedAdd = true;
      const orig = global.addToWl;
      global.addToWl = function () {
        const r = orig.apply(this, arguments);
        setTimeout(pollOnce, 400);
        return r;
      };
    }
    if (typeof rmWl === 'function' && !global._wlLiveHookedRm) {
      global._wlLiveHookedRm = true;
      const orig = global.rmWl;
      global.rmWl = function () {
        const r = orig.apply(this, arguments);
        setTimeout(pollOnce, 400);
        return r;
      };
    }
    // Pause when tab not visible to save bandwidth
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stop();
      else { start(); pollOnce(); }   // immediate refresh on return
    });
  })();

  // ─── expose ────────────────────────────────────────────────
  global.pollWlPrices    = pollOnce;
  global.startWlLivePoll = start;
  global.stopWlLivePoll  = stop;

  console.log('[wl-live] watchlist live polling armed (30s interval, pauses when tab hidden)');
})(window);

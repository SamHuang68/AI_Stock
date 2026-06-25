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
  const POLL_MS = 5_000;           // v3.9 即時化:5 秒(台股 chip 走 MIS;貼近 MIS 更新節奏)
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

  // v3.9 即時化:台股批次走 TWSE MIS(真即時),回 {code:{price,prevClose,changePct}}
  async function fetchMis(codes) {
    if (!codes.length) return {};
    try {
      const url = `${SERVER}/twquote-batch?codes=${encodeURIComponent(codes.join(','))}`;
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) return {};
      return await r.json();
    } catch (e) { return {}; }
  }

  async function fetchBatch(syms) {
    if (!syms.length) return {};
    try {
      // v3.9：改用 /quote-batch（每檔 range=1d，meta.chartPreviousClose=真昨收）。
      // 原 5d 日線 batch 對「昨日 K 線 close=null 缺口」的 ETF(如 00988A)會
      // 跳過 null 抓到更舊一根當昨收→漲幅亂跳(+8% vs +0.8%)。/quote-batch 用
      // 1d meta 昨收，server 端並發 + .TW→.TWO 回退。回 {sym:{price,prevClose,changePct}}。
      const url = `${SERVER}/quote-batch?syms=${encodeURIComponent(syms.join(','))}`;
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) { console.warn('[wl-live] quote-batch HTTP', r.status); return {}; }
      return await r.json();
    } catch (e) {
      console.warn('[wl-live] batch error:', e);
      return {};
    }
  }

  // 更新某筆持倉的現價（v3.8：POS 不再只在點股時更新）
  function applyToPos(code, cur) {
    if (cur == null || !isFinite(cur)) return;
    if (typeof S !== 'undefined' && S.positions && S.positions[code]) {
      S.positions[code].lastPrice = cur;
      S.positions[code].lastUpdate = Date.now();
      _posDirty = true;
    }
  }
  let _posDirty = false;

  // ─── main poll ────────────────────────────────────────────
  async function pollOnce() {
    if (_inflight) return;
    const hasWl = (typeof S !== 'undefined' && S.wl && S.wl.length);
    const hasPos = (typeof S !== 'undefined' && S.positions && Object.keys(S.positions).length);
    if (!hasWl && !hasPos) return;
    _inflight = true;
    _posDirty = false;
    try {
      // First pass — TW with .TW suffix, US raw
      const symMap = new Map();   // yfsym → wl item（或 {_pos: code} 持倉標記）
      for (const w of (S.wl || [])) {
        // ^ 開頭=指數(如 ^TWII/^GSPC)，原樣不加 .TW
        const yfsym = (w.t && w.t[0] === '^') ? w.t : (w.m === 'TW' ? w.t + '.TW' : w.t);
        symMap.set(yfsym, w);
      }
      // 持倉代號（不在自選股的也要抓）：數字開頭視為台股 .TW，否則美股原樣
      for (const code of Object.keys(S.positions || {})) {
        const yf = /^[0-9]/.test(code) ? code + '.TW' : code;
        if (!symMap.has(yf)) symMap.set(yf, { _pos: code });
        else if (symMap.get(yf) && symMap.get(yf).t) symMap.get(yf)._posAlso = code;
      }
      const syms = [...symMap.keys()];
      // v3.9 即時化:台股(.TW/.TWO)→ MIS 即時;指數/美股 → Yahoo。MIS 漏接的台股再用 Yahoo 補。
      const twYf = syms.filter(s => s.endsWith('.TW') || s.endsWith('.TWO'));
      const otherYf = syms.filter(s => !(s.endsWith('.TW') || s.endsWith('.TWO')));
      const data = {};
      if (twYf.length) {
        const mis = await fetchMis(twYf.map(s => s.replace('.TWO', '').replace('.TW', '')));
        for (const yf of twYf) {
          const code = yf.replace('.TWO', '').replace('.TW', '');
          if (mis[code] && mis[code].changePct != null) data[yf] = mis[code];
        }
      }
      // 台股一律只用 MIS:某輪 MIS 漏接就保留 chip 上次值(不回退 Yahoo,否則 MIS即時↔Yahoo延遲 兩值亂跳)。
      // 只有美股/指數(無 MIS)走 Yahoo。
      const missing = otherYf;
      if (missing.length) Object.assign(data, await fetchBatch(missing));

      // 回傳 {sym:{price,prevClose,changePct}}（台股=MIS 即時,其餘=Yahoo）
      for (const [yfsym, w] of symMap.entries()) {
        const d = data[yfsym];
        if (!d || d.changePct == null) continue;
        if (w._pos) applyToPos(w._pos, d.price);
        else { applyToChip(w, d.changePct, d.price); if (w._posAlso) applyToPos(w._posAlso, d.price); }
      }

      // After in-place updates: persist S.wl (so refresh shows last seen %)
      if (typeof saveWl === 'function') {
        try { saveWl(); } catch {}
      }
      // v3.8：持倉價有更新 → 存檔 + 若在 POS 分頁則重繪
      if (_posDirty) {
        if (typeof savePositions === 'function') { try { savePositions(); } catch {} }
        // 重繪一律走單一守門入口:使用者正在輸入欄位時不重繪(否則每次輪詢都會
        // innerHTML 重建,清空進場價/股數、奪走焦點,下一鍵被攔走)。資料已先更新。
        if (typeof window.renderPositionPanel === 'function') window.renderPositionPanel();
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

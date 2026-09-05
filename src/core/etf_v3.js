// ============================================================
// Stock Terminal v3.2 — ETF Section (clean rewrite, self-contained)
// ------------------------------------------------------------
// 完全取代舊的 v1 renderEtfDelta / fetchEtfDelta / renderEtfHoldingsForStock
// 與 etf_v2.js 的 patch 鏈。不再 wrap 任何 v1 函式 — 全部用 window 覆蓋。
//
// 提供：
//   • fetchDelta / fetchCatalog / saveCatalog
//   • renderEtfDelta (ETF 分頁主面板)
//   • renderEtfHoldingsForStock (STATS 分頁的子區塊)
//   • openEtfMgrModal (⚙ 管理 modal — 含 catalog 編輯 + 立即跑 tracker)
//
// 設計重點：
//   1. S.etfV3 — 內部 state（catalog + 原始 delta + 過濾後 delta）
//   2. S.etfDelta / S.etfCatalog — 鏡像給 v1 的籌碼指標 / chip 用
//   3. window 覆蓋 v1 的全域函式，由 build_v2.py 的 router patch 接住
//   4. setTab(etf) 自動重抓（>60 秒陳舊）
//   5. 點 stock card 直接 loadSym 跳轉
// ============================================================

(function (global) {
  'use strict';

  const SERVER = global.SERVER || `http://localhost:18432`;

  // ─── State boot ─────────────────────────────────────────────
  function boot() {
    if (typeof S === 'undefined') return setTimeout(boot, 30);
    const defaults = {
      catalog:    null,
      deltaRaw:   null,
      delta:      null,
      lastGoodRaw:null,
      loading:    false,
      err:        null,
      freshness:  { state: 'missing', reason: 'not_loaded' },
      inflight:   null,
      catActive:  'active',
      lastFetch:  0,
      expanded:   new Set(),
      weightPage: 1,
      weightSortKey: 'delta_pp',
      weightSortDirection: 'descending',
    };
    if (!S.etfV3) S.etfV3 = defaults;
    else {
      Object.keys(defaults).forEach(key => {
        if (S.etfV3[key] == null) S.etfV3[key] = defaults[key];
      });
    }
  }
  boot();

  // ─── Helpers ────────────────────────────────────────────────
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, m => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

  // v3.7：MoneyDJ 市場碼 → Yahoo Finance symbol suffix mapping
  //   多數市場兩邊一致；只有 JP/SH 需要轉換。其他外股市場一律用
  //   uiMkt='US' 讓 loadSym 不要加 .TW 後綴（symbol 自己已帶後綴）。
  //   HK 股代號通常 4 位數，缺前 0 時補齊（例: 700.HK → 0700.HK）。
  function mapToYahoo(sym, mdjMkt) {
    const m = (mdjMkt || 'TW').toUpperCase();
    if (m === 'TW') return [sym, 'TW'];
    if (m === 'US') return [sym, 'US'];
    if (m === 'JP') return [sym + '.T',  'US'];   // Yahoo: Tokyo .T (NOT .JP)
    if (m === 'KS') return [sym + '.KS', 'US'];   // KOSPI
    if (m === 'KQ') return [sym + '.KQ', 'US'];   // KOSDAQ
    if (m === 'HK') return [sym.padStart(4, '0') + '.HK', 'US'];
    if (m === 'SH') return [sym + '.SS', 'US'];   // Yahoo: Shanghai .SS (NOT .SH)
    if (m === 'SZ') return [sym + '.SZ', 'US'];   // Shenzhen
    if (m === 'DE') return [sym + '.DE', 'US'];   // Frankfurt XETRA
    if (m === 'L')  return [sym + '.L',  'US'];   // London
    if (m === 'PA') return [sym + '.PA', 'US'];   // Paris
    if (m === 'AS') return [sym + '.AS', 'US'];   // Amsterdam
    if (m === 'TO') return [sym + '.TO', 'US'];   // Toronto
    if (m === 'AX') return [sym + '.AX', 'US'];   // ASX
    return [sym, 'US'];   // unknown market → pass-through with US UI
  }

  function ago(ts) {
    if (!ts) return '從未';
    const s = Math.round((Date.now() - ts) / 1000);
    if (s < 60)   return `${s} 秒前`;
    if (s < 3600) return `${Math.round(s/60)} 分前`;
    return `${Math.round(s/3600)} 小時前`;
  }

  function enabledSet(catalog) {
    const set = new Set();
    for (const c of (catalog?.categories || [])) {
      for (const e of (c.etfs || [])) {
        if (e.enabled) set.add((e.code || '').toUpperCase());
      }
    }
    return set;
  }

  // code -> name 對照（來自 catalog），給 delta 卡名稱缺失時回退用
  function catName(code) {
    const cat = S.etfV3 && S.etfV3.catalog;
    if (!cat) return '';
    if (!cat._nameMap) {
      const m = {};
      for (const c of (cat.categories || []))
        for (const e of (c.etfs || []))
          if (e.code && e.name) m[(e.code || '').toUpperCase()] = e.name;
      cat._nameMap = m;
    }
    return cat._nameMap[(code || '').toUpperCase()] || '';
  }
  // 解析顯示名稱：delta 名稱有效就用，否則回退 catalog 名稱
  function resolveName(code, name) {
    const c = (code || '').toUpperCase();
    if (catName(code)) return catName(code);
    if (name && name.toUpperCase() !== c) return name;
    return catName(code) || name || '';
  }

  function applyFilter() {
    if (!S.etfV3.deltaRaw) {
      S.etfV3.delta = null;
      S.etfDelta = null;
      return;
    }
    if (!S.etfV3.catalog) {
      // No catalog yet — show everything
      S.etfV3.delta = S.etfV3.deltaRaw;
      S.etfDelta = S.etfV3.delta;
      return;
    }
    const allowed = enabledSet(S.etfV3.catalog);
    S.etfV3.delta = {
      ...S.etfV3.deltaRaw,
      etfs: (S.etfV3.deltaRaw.etfs || []).filter(e => allowed.has((e.code || '').toUpperCase())),
    };
    S.etfDelta = S.etfV3.delta;   // mirror for v1 (chip indicators, watchlist badges)
  }

  function changeDirection(change) {
    const shares = Number(change && change.shares_delta);
    if (Number.isFinite(shares) && shares !== 0) return shares > 0 ? 1 : -1;
    const weight = Number(change && change.delta);
    if (Number.isFinite(weight) && weight !== 0) return weight > 0 ? 1 : -1;
    return 0;
  }

  function freshnessFor(delta, sourceError) {
    if (!delta) {
      return { state: sourceError ? 'error' : 'missing', reason: sourceError || 'not_loaded' };
    }
    const history = delta.meta && delta.meta.history;
    const serverState = history && history.state;
    if (sourceError) {
      return { state: 'stale', reason: 'refresh_failed', error: sourceError,
        latestDate: delta.date || (history && history.latestDate) || null };
    }
    if (!history || !serverState) {
      return {
        state: 'stale',
        reason: 'history_contract_missing',
        latestDate: delta.date || null,
        legacyPayload: true,
      };
    }
    return {
      state: serverState === 'ok' ? 'fresh' : 'stale',
      reason: serverState,
      latestDate: delta.date || (history && history.latestDate) || null,
      businessDayAge: history && history.businessDayAge,
    };
  }

  function stockFlow(code) {
    const sym = String(code == null ? '' : code).trim().toUpperCase();
    const delta = S.etfV3 && S.etfV3.delta;
    const freshness = (S.etfV3 && S.etfV3.freshness) || freshnessFor(delta, S.etfErr);
    const out = {
      sym, date: delta && delta.date || null, prevDate: delta && delta.prev_date || null,
      freshness: freshness.state || 'missing', freshnessDetail: freshness,
      added: [], removed: [], increased: [], decreased: [],
      addCount: 0, rmCount: 0, incCount: 0, decCount: 0,
      netWeightDelta: 0, chgSum: 0, unchanged: false, available: !!delta,
      sourceError: (S.etfV3 && S.etfV3.err) || S.etfErr || null,
    };
    if (!delta) return out;
    (delta.etfs || []).forEach(etf => {
      const meta = { code: etf.code, name: resolveName(etf.code, etf.name) };
      const added = (etf.new || []).find(item => String(item.code).toUpperCase() === sym);
      if (added) out.added.push({...meta, weight: added.weight, shares: added.shares});
      const removed = (etf.removed || []).find(item => String(item.code).toUpperCase() === sym);
      if (removed) out.removed.push({...meta, weight: removed.prev_weight, shares: removed.prev_shares});
      const changed = (etf.changed || []).find(item => String(item.code).toUpperCase() === sym);
      if (changed) {
        const detail = {...meta, delta: Number(changed.delta) || 0,
          sharesDelta: Number(changed.shares_delta) || 0};
        out.netWeightDelta += detail.delta;
        const direction = changeDirection(changed);
        if (direction > 0) out.increased.push(detail);
        else if (direction < 0) out.decreased.push(detail);
      }
    });
    out.addCount = out.added.length;
    out.rmCount = out.removed.length;
    out.incCount = out.increased.length;
    out.decCount = out.decreased.length;
    out.netWeightDelta = Math.round(out.netWeightDelta * 10000) / 10000;
    // Compatibility alias for position_v2's ETF confluence calculation.  The
    // value remains weight percentage-point change, not cash flow.
    out.chgSum = out.netWeightDelta;
    out.unchanged = !(out.addCount || out.rmCount || out.incCount || out.decCount);
    return out;
  }

  function updateEtfFlowInd() {
    const el = document.getElementById('ig-etfFlow');
    if (!el || !S.sym) return;
    const flow = stockFlow(S.sym);
    if (!flow.available) {
      el.textContent = flow.freshness === 'error' ? '資料錯誤' : '尚無資料';
      el.style.color = 'var(--tf)';
      return;
    }
    const buy = flow.addCount + flow.incCount;
    const sell = flow.rmCount + flow.decCount;
    const stale = flow.freshness !== 'fresh';
    if (buy || sell) {
      el.textContent = `${buy ? '↑' + buy : ''}${buy && sell ? ' ' : ''}${sell ? '↓' + sell : ''} ETF${stale ? ' · 舊' : ''}`;
      el.style.color = stale ? 'var(--gold)' : (buy > sell ? 'var(--red)' : sell > buy ? 'var(--green)' : 'var(--blue)');
    } else {
      el.textContent = stale ? '無異動 · 資料舊' : '本期無異動';
      el.style.color = stale ? 'var(--gold)' : 'var(--tf)';
    }
  }

  function notifyDependents() {
    try { if (typeof renderWl === 'function') renderWl(); } catch {}
    try { updateEtfFlowInd(); } catch {}
    if (typeof renderRpanel === 'function' && (S.tab === 'etf' || S.tab === 'stats')) {
      try { renderRpanel(); } catch {}
    }
  }

  // ─── Fetchers ───────────────────────────────────────────────
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

  function traceEtf(event, correlationId, detail) {
    try {
      const row = detail || {};
      fetch(`${SERVER}/diagnostics/ui-route`, {
        method: 'POST', cache: 'no-store', keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ts: new Date().toISOString(), event, correlationId,
          from: 'etf-v3', to: '/etf-delta', state: row.state || '',
          label: row.label || '', elapsedMs: row.elapsedMs || '',
        }),
      }).catch(() => {});
    } catch {}
  }

  function retryDelay(response, attempt) {
    const header = response && response.headers && response.headers.get
      ? response.headers.get('Retry-After') : null;
    if (header) {
      const seconds = Number(header);
      if (Number.isFinite(seconds)) return Math.max(500, Math.min(5000, seconds * 1000));
      const when = Date.parse(header);
      if (Number.isFinite(when)) return Math.max(500, Math.min(5000, when - Date.now()));
    }
    return Math.min(5000, 750 * Math.pow(2, attempt - 1) + Math.round(Math.random() * 180));
  }

  async function requestDelta(url, correlationId) {
    let lastError = null;
    for (let attempt = 1; attempt <= 3; attempt++) {
      const ctrl = new AbortController();
      const tid = setTimeout(() => ctrl.abort(), 12000);
      try {
        const response = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
        if (response.ok) return response;
        let message = `HTTP ${response.status}`;
        try { const body = await response.clone().json(); if (body.error) message = body.error; } catch {}
        const error = new Error(message);
        error.status = response.status;
        error.response = response;
        lastError = error;
        const retryable = [429, 500, 502, 503, 504].includes(response.status);
        if (!retryable || attempt >= 3) throw error;
        const delay = retryDelay(response, attempt);
        traceEtf('etf_delta_retry', correlationId, { state: `attempt-${attempt}`, label: `${response.status}|${delay}ms` });
        await wait(delay);
      } catch (error) {
        lastError = error;
        if (error && error.status) throw error;
        if (attempt >= 3) throw error;
        const delay = retryDelay(null, attempt);
        traceEtf('etf_delta_retry', correlationId, { state: `attempt-${attempt}`, label: `${error.name || 'network'}|${delay}ms` });
        await wait(delay);
      } finally {
        clearTimeout(tid);
      }
    }
    throw lastError || new Error('ETF delta request failed');
  }

  async function fetchCatalog() {
    try {
      const r = await fetch(`${SERVER}/etf-catalog`, { cache: 'no-store' });
      if (!r.ok) { console.warn('[etf-v3] catalog HTTP', r.status); return null; }
      S.etfV3.catalog = await r.json();
      S.etfCatalog    = S.etfV3.catalog;
      applyFilter();
      notifyDependents();
      return S.etfV3.catalog;
    } catch (e) {
      console.warn('[etf-v3] fetchCatalog error:', e);
      return null;
    }
  }

  async function saveCatalog(catalog) {
    try {
      const r = await fetch(`${SERVER}/etf-catalog`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(catalog),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({ error: 'HTTP ' + r.status }));
        throw new Error(j.error || 'save failed');
      }
      return await r.json();
    } catch (e) {
      alert('儲存失敗：' + e.message);
      return null;
    }
  }

  function fetchDelta(date) {
    if (!S.etfV3) boot();
    if (S.etfV3.inflight) return S.etfV3.inflight;
    S.etfV3.loading = true;
    S.etfV3.err = null;
    S.etfLoading = true;
    S.etfErr = null;
    if (S.tab === 'etf' && typeof renderRpanel === 'function') renderRpanel();
    const correlationId = `etf-delta-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    const started = Date.now();
    traceEtf('etf_delta_start', correlationId, { state: date ? 'historical' : 'latest', label: date || '' });
    const task = (async () => { try {
      const url = date ? `${SERVER}/etf-delta?date=${date}` : `${SERVER}/etf-delta`;
      const r = await requestDelta(url, correlationId);
      const next = await r.json();
      if (!next || !Array.isArray(next.etfs) || !next.date) throw new Error('ETF delta payload invalid');
      S.etfV3.deltaRaw = next;
      S.etfV3.lastGoodRaw = next;
      S.etfV3.lastFetch = Date.now();
      S.etfV3.err = null;
      S.etfErr = null;
      S.etfV3.freshness = freshnessFor(next, null);
      applyFilter();
      traceEtf('etf_delta_success', correlationId, {
        state: S.etfV3.freshness.state, label: next.date,
        elapsedMs: Date.now() - started,
      });
    } catch (e) {
      S.etfV3.err = e.name === 'AbortError' ? '逾時 (12s)' : (e.message || 'fetch failed');
      S.etfErr = S.etfV3.err;
      if (S.etfV3.lastGoodRaw) {
        S.etfV3.deltaRaw = S.etfV3.lastGoodRaw;
        S.etfV3.freshness = freshnessFor(S.etfV3.lastGoodRaw, S.etfV3.err);
      } else {
        S.etfV3.deltaRaw = null;
        S.etfV3.freshness = freshnessFor(null, S.etfV3.err);
      }
      applyFilter();
      traceEtf('etf_delta_failed', correlationId, {
        state: S.etfV3.freshness.state, label: S.etfV3.err,
        elapsedMs: Date.now() - started,
      });
    } finally {
      S.etfV3.loading = false;
      S.etfLoading = false;
      S.etfV3.inflight = null;
      notifyDependents();
    } })();
    S.etfV3.inflight = task;
    return task;
  }

  // ─── CSS ────────────────────────────────────────────────────
  (function injectCSS() {
    if (document.getElementById('etf-v3-styles')) return;
    const css = `
.e3-wrap { font-family: 'JetBrains Mono', monospace; }
.e3-weight-rank { margin: 10px 8px; min-width: 0; border: 1px solid var(--border); border-radius: 8px; }
.e3-weight-rank > .e3-section-hdr { font-size: 14px; padding-block: 8px; color: var(--thi); }
.e3-weight-rank .e3-meta { display: block; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.e3-weight-rank summary { padding: 10px; cursor: pointer; font-size: 12px; }
.e3-weight-scroll { overflow-x: auto; max-width: 100%; max-height: 440px; overscroll-behavior: contain; }
.e3-weight-table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }
.e3-weight-table th { position: sticky; top: 0; background: var(--bg); z-index: 1; }
.e3-weight-table th,.e3-weight-table td { padding: 9px 10px; text-align: right; border-bottom: 1px solid var(--border); }
.e3-weight-table td:nth-child(2) { text-align: left; }
.e3-weight-table .e3-actbtn { font-size: 12px; min-height: 32px; }
.e3-weight-context { padding: 8px 12px; display: grid; gap: 3px; color: var(--tlo); font-size: 12px; line-height: 1.5; border-bottom: 1px solid var(--border); }
.e3-weight-context strong { color: var(--thi); }
.e3-weight-mobile-hint { display: none; padding: 6px 12px; color: var(--blue); font-size: 12px; line-height: 1.45; border-bottom: 1px solid var(--border); }
.e3-weight-pager { min-height: 38px; padding: 6px 10px; display: flex; align-items: center; justify-content: space-between; gap: 10px; color: var(--tlo); font-size: 12px; border-bottom: 1px solid var(--border); }
.e3-weight-pager .e3-page-actions { display: flex; gap: 6px; }
.e3-weight-pager button { min-width: 68px; min-height: 30px; padding: 4px 9px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg3); color: var(--thi); font: inherit; cursor: pointer; }
.e3-weight-pager button:hover:not(:disabled),.e3-weight-pager button:focus-visible { color: var(--gold); border-color: var(--gold-m); outline: none; }
.e3-weight-pager button:disabled { opacity: .35; cursor: default; }
@media (max-width: 1000px), (pointer: coarse) {
  .e3-weight-mobile-hint { display: block; }
}
@media (max-width: 620px) {
  .e3-weight-rank { margin: 6px 4px; }
  .e3-weight-pager { align-items: flex-start; flex-direction: column; }
  .e3-weight-pager .e3-page-actions { width: 100%; }
  .e3-weight-pager button { flex: 1; }
}
.e3-tabs { display: flex; flex-wrap: wrap; gap: 3px; padding: 6px 8px; background: var(--bg); border-bottom: 1px solid var(--border); align-items: center; }
.e3-tab { padding: 4px 9px; background: transparent; border: 1px solid var(--border); border-radius: 4px; color: var(--tlo); font-family: 'JetBrains Mono', monospace; font-size: 9.5px; font-weight: 600; cursor: pointer; letter-spacing: .3px; white-space: nowrap; transition: all .12s; }
.e3-tab:hover { color: var(--gold); background: var(--gold-s); }
.e3-tab.on { background: var(--gold-s); border-color: var(--gold); color: var(--gold); }
.e3-tab .cnt { font-size: 8.5px; margin-left: 4px; opacity: .75; }
.e3-actions { display: flex; gap: 4px; margin-left: auto; }
.e3-actbtn { padding: 4px 9px; background: transparent; border: 1px solid var(--border); border-radius: 4px; color: var(--tlo); font-family: monospace; font-size: 9.5px; cursor: pointer; }
.e3-actbtn:hover { color: var(--gold); border-color: var(--gold-m); background: var(--gold-s); }
.e3-actbtn.primary { background: var(--gold-s); color: var(--gold); border-color: var(--gold-m); }
.e3-meta { padding: 4px 12px; background: var(--bg); border-bottom: 1px solid var(--border); font-family: monospace; font-size: 8.5px; color: var(--tf); letter-spacing: .3px; display: flex; justify-content: space-between; }
.e3-summary { display: flex; border-bottom: 1px solid var(--border); }
.e3-sumcell { flex: 1; padding: 9px 4px; text-align: center; border-right: 1px solid var(--border); }
.e3-sumcell:last-child { border-right: none; }
.e3-sumcell .n { font-family: monospace; font-size: 22px; font-weight: 700; line-height: 1.1; }
.e3-sumcell .l { font-family: monospace; font-size: 8.5px; color: var(--tlo); letter-spacing: 1px; margin-top: 3px; }
.e3-empty { padding: 30px 16px; text-align: center; font-family: monospace; font-size: 10.5px; color: var(--tlo); line-height: 1.8; }
.e3-empty .hint { font-size: 9px; color: var(--tf); margin-top: 6px; display: block; }
.e3-card { border-bottom: 1px solid var(--border); }
.e3-card-hdr { display: flex; align-items: center; gap: 8px; padding: 9px 12px; cursor: pointer; background: var(--bg2); transition: background .12s; }
.e3-card-hdr:hover { background: var(--bg3); }
.e3-card.open .e3-card-hdr { background: var(--gold-s); }
.e3-card-code { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; color: var(--gold); letter-spacing: .5px; min-width: 60px; }
.e3-card-name { flex: 1; font-family: monospace; font-size: 10px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.e3-card-badges { display: flex; gap: 4px; }
.e3-badge { padding: 1px 6px; border-radius: 3px; font-family: monospace; font-size: 9px; font-weight: 700; }
.e3-badge.new { background: rgba(248,113,113,.15); color: var(--red); }
.e3-badge.rm  { background: rgba(74,222,128,.15); color: var(--green); }
.e3-badge.chg { background: rgba(96,165,250,.15); color: var(--blue); }
.e3-badge.empty { background: rgba(90,106,130,.10); color: var(--tf); }
.e3-card-arrow { color: var(--tlo); font-size: 10px; transition: transform .15s; }
.e3-card.open .e3-card-arrow { transform: rotate(90deg); color: var(--gold); }
.e3-card-body { display: none; }
.e3-card.open .e3-card-body { display: block; }
.e3-section-hdr { padding: 4px 14px; background: var(--bg); font-family: monospace; font-size: 8px; color: var(--tf); letter-spacing: 1.5px; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); text-transform: uppercase; }
.e3-stock { display: flex; align-items: center; gap: 6px; padding: 5px 14px; border-bottom: 1px solid var(--bg3); cursor: pointer; transition: background .12s; }
.e3-stock:hover { background: var(--bg3); }
.e3-stock .scode { font-family: monospace; font-size: 10px; font-weight: 700; color: var(--thi); min-width: 50px; }
.e3-stock .sname { flex: 1; font-family: monospace; font-size: 9px; color: var(--tlo); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.e3-stock .swt   { font-family: monospace; font-size: 9.5px; font-weight: 700; white-space: nowrap; }
.e3-stock .swt.green { color: var(--green); }
.e3-stock .swt.red   { color: var(--red); }
.e3-stock .swt.blue  { color: var(--blue); }
.e3-consensus { padding: 7px 12px; background: rgba(245,197,24,.06); border-left: 3px solid var(--gold); cursor: pointer; transition: background .12s; border-bottom: 1px solid var(--border); }
.e3-consensus:hover { background: rgba(245,197,24,.12); }
.e3-consensus .stk { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 700; color: var(--gold); }
.e3-consensus .src { font-family: monospace; font-size: 8.5px; color: var(--tlo); margin-top: 3px; line-height: 1.5; }
.e3-loading { padding: 60px 16px; text-align: center; font-family: monospace; font-size: 11px; color: var(--gold); animation: e3pulse 1.4s ease infinite; }
@keyframes e3pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }
.e3-retry { margin-top: 12px; padding: 5px 16px; background: var(--bg3); border: 1px solid var(--border); border-radius: 4px; color: var(--tlo); font-family: monospace; font-size: 9.5px; cursor: pointer; }
.e3-retry:hover { color: var(--gold); border-color: var(--gold-m); }
/* ── Modal ── */
.e3-modal { position: fixed; inset: 0; background: rgba(6,10,18,.85); z-index: 9999; display: flex; align-items: center; justify-content: center; }
.e3-modal .panel { background: var(--bg2); border: 1px solid var(--gold-m); border-radius: 8px; width: 680px; max-width: 95vw; height: 80vh; display: flex; flex-direction: column; overflow: hidden; }
.e3-modal .head { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--border); background: var(--bg); }
.e3-modal .head h3 { font-family: 'JetBrains Mono', monospace; font-size: 13px; color: var(--gold); font-weight: 700; letter-spacing: 1px; margin: 0; }
.e3-modal .body { flex: 1; overflow-y: auto; padding: 8px 0; }
.e3-modal .foot { padding: 10px 18px; border-top: 1px solid var(--border); background: var(--bg); display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.e3-modal .x { cursor: pointer; color: var(--tlo); font-size: 20px; line-height: 1; padding: 0 4px; }
.e3-modal .x:hover { color: var(--red); }
.e3-mgrcat { margin: 8px 0; }
.e3-mgrcat-h { padding: 8px 18px; font-family: monospace; font-size: 11px; color: var(--gold); font-weight: 700; letter-spacing: .5px; background: var(--bg); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.e3-mgrcat-desc { padding: 5px 18px; font-family: monospace; font-size: 9.5px; color: var(--tf); line-height: 1.6; background: var(--bg); border-bottom: 1px solid var(--border); }
.e3-mgrlist { padding: 4px 18px; }
.e3-mgritem { display: flex; align-items: center; gap: 10px; padding: 7px 4px; border-bottom: 1px solid var(--bg3); font-family: 'JetBrains Mono', monospace; font-size: 11px; }
.e3-mgritem:last-child { border-bottom: none; }
.e3-mgritem input[type=checkbox] { accent-color: var(--gold); width: 14px; height: 14px; cursor: pointer; }
.e3-mgritem .code { color: var(--thi); font-weight: 700; letter-spacing: .5px; min-width: 60px; }
.e3-mgritem .name { flex: 1; color: var(--text); font-size: 10.5px; }
.e3-mgritem .name:hover, .e3-mgritem .code:hover { color: var(--gold); }
.e3-mkttabs { display: flex; gap: 6px; align-items: center; padding: 6px 4px 10px; position: sticky; top: 0; background: var(--bg2); z-index: 2; }
.e3-mkttab { background: var(--bg3); border: 1px solid var(--border); color: var(--tlo); border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 11px; font-weight: 700; }
.e3-mkttab.on { background: var(--gold-s); color: var(--gold); border-color: var(--gold); }
.e3-mkt-tag { font-size: 7.5px; font-weight: 700; margin-left: 3px; padding: 0 3px; border-radius: 3px; vertical-align: top; }
.e3-mkt-tag.us { background: rgba(96,165,250,.2); color: #60A5FA; }
.e3-mgritem.off { opacity: .55; }
.e3-mgritem .rm { color: var(--tf); cursor: pointer; font-size: 13px; padding: 0 4px; border-radius: 3px; }
.e3-mgritem .rm:hover { color: var(--red); background: rgba(248,113,113,.12); }
.e3-addform { padding: 10px 18px; background: var(--gold-s); border-top: 2px solid var(--gold-m); display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.e3-addform .row { display: flex; gap: 6px; align-items: center; }
.e3-addform input, .e3-addform select { background: var(--bg3); border: 1px solid var(--border); border-radius: 3px; padding: 5px 8px; color: var(--thi); font-family: monospace; font-size: 10.5px; outline: none; }
.e3-addform input { flex: 1; }
.e3-addform button { padding: 5px 12px; background: var(--gold); color: #060A12; border: none; border-radius: 3px; font-family: monospace; font-size: 10px; font-weight: 700; cursor: pointer; letter-spacing: .5px; }
.e3-addform .hint { font-size: 9px; color: var(--tlo); font-family: monospace; line-height: 1.5; }
.e3-mbtn { padding: 6px 14px; border-radius: 4px; font-family: monospace; font-size: 10px; font-weight: 700; cursor: pointer; letter-spacing: .5px; border: 1px solid var(--border); background: transparent; color: var(--tlo); }
.e3-cat-btn { padding: 2px 8px; border-radius: 3px; font-family: monospace; font-size: 9.5px; font-weight: 600; cursor: pointer; letter-spacing: .3px; border: 1px solid var(--border); background: transparent; color: var(--tlo); }
.e3-cat-btn:hover { color: var(--gold); border-color: var(--gold-m); background: var(--gold-s); }
.e3-mbtn.primary { background: var(--gold); color: #060A12; border: none; }
.e3-mbtn:hover { color: var(--gold); border-color: var(--gold-m); }
.e3-mbtn.primary:hover { background: #FBBF24; color: #060A12; }
/* ── STATS holdings section ── */
.e3-hold-row { display: flex; justify-content: space-between; padding: 4px 12px; border-bottom: 1px solid var(--bg3); font-family: monospace; font-size: 10px; }
.e3-hold-row .k { color: var(--tlo); }
.e3-hold-row .v { font-weight: 700; }
/* ── v3.1 Top 10 持股區 ── */
.e3-top10 .e3-stock { padding: 5px 14px 5px 8px; }
.e3-top10 .e3-stock .rank {
  min-width: 22px; display: inline-block; text-align: center;
  font-family: 'JetBrains Mono', monospace; font-size: 9px; font-weight: 700;
  color: var(--gold); background: var(--gold-s); border-radius: 3px;
  padding: 1px 0; letter-spacing: .3px;
}
.e3-top10 .e3-stock .bar {
  flex-shrink: 0; width: 56px; height: 8px; background: var(--bg3); border-radius: 2px;
  position: relative; overflow: hidden; margin-right: 4px;
}
.e3-top10 .e3-stock .bar > i {
  position: absolute; left: 0; top: 0; bottom: 0;
  background: linear-gradient(90deg, var(--gold), #FBBF24); display: block;
}
.e3-top10 .e3-stock .swt.gold { color: var(--gold); }
.e3-top10-foot {
  padding: 5px 14px; font-family: monospace; font-size: 9px; color: var(--tf);
  background: var(--bg); border-bottom: 1px solid var(--border); text-align: right;
}
`;
    const s = document.createElement('style');
    s.id = 'etf-v3-styles';
    s.textContent = css;
    document.head.appendChild(s);
  })();

  // ─── 🇺🇸 美股 ETF 報價區（主頁獨立分頁）──────────────────────
  function renderUsSection() {
    const cats = S.etfV3.catalog?.categories || [];
    let h = `<div class="e3-meta"><span>🇺🇸 美股 ETF · 報價（點擊載入線型）</span><span>無持股 delta（非台股）</span></div>`;
    const codes = [];
    let any = false;
    for (const c of cats) {
      const us = (c.etfs || []).filter(e => (e.market || 'TW') === 'US');
      if (!us.length) continue;
      any = true;
      h += `<div class="e3-section-hdr">${c.icon || ''} ${esc(c.name)}</div>`;
      for (const e of us) {
        const id = 'use-' + (e.code || '').replace(/[^A-Za-z0-9]/g, '');
        codes.push(e.code);
        h += `<div class="e3-stock" data-e3="goto" data-sym="${esc(e.code)}" data-mkt="US" title="載入 ${esc(e.code)} 線型">
          <span style="font-weight:700;color:var(--thi);min-width:54px">${esc(e.code)}</span>
          <span class="sname">${esc(e.name || '')}</span>
          <span class="schg" id="${id}" style="font-family:monospace;font-size:10px;color:var(--tlo);min-width:96px;text-align:right">…</span>
        </div>`;
      }
    }
    if (!any) h += `<div class="e3-empty">尚無美股 ETF<span class="hint">點 ⚙ 管理 → 選「🇺🇸 美股」新增</span></div>`;
    else setTimeout(() => fillUsQuotes(codes), 30);
    return h;
  }
  function fillUsQuotes(codes) {
    for (const code of codes) {
      fetch(`${SERVER}/quote/${code}`, { cache: 'no-store' })
        .then(r => r.ok ? r.json() : null)
        .then(q => {
          if (!q) return;
          const el = document.getElementById('use-' + (code || '').replace(/[^A-Za-z0-9]/g, ''));
          if (!el) return;
          const pct = q.changePct;
          el.textContent = (q.price != null ? q.price.toFixed(2) : '—') +
            (pct != null ? '  ' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' : '');
          el.style.color = window.Colors ? Colors.dir(code, pct) : (pct == null ? 'var(--tlo)' : pct > 0 ? 'var(--green)' : pct < 0 ? 'var(--red)' : 'var(--tlo)');
        }).catch(() => {});
    }
  }

  const WEIGHT_PAGE_SIZE = 100;
  const WEIGHT_COLUMNS = [
    { key:'etf_code', label:'ETF', type:'text' },
    { key:'code', label:'個股', type:'text' },
    { key:'market', label:'市場', type:'text' },
    { key:'prev_weight', label:'前期權重 %', type:'number' },
    { key:'weight', label:'本期權重 %', type:'number' },
    { key:'delta_pp', label:'增減百分點', type:'number' },
    { key:'status', label:'狀態', type:'text' },
    { key:'prev_date', label:'前期來源日', type:'date' },
    { key:'date', label:'本期來源日', type:'date' },
    { key:'source', label:'資料來源', type:'text' },
    { key:'snapshot_date', label:'收集檔日期', type:'date' },
  ];

  function weightDirectionLabel(direction) {
    return direction === 'ascending' ? '升冪' : direction === 'descending' ? '降冪' : '原始順序';
  }

  function weightNextDirection(key) {
    if (S.etfV3.weightSortKey !== key || S.etfV3.weightSortDirection === 'none') return 'ascending';
    return S.etfV3.weightSortDirection === 'ascending' ? 'descending' : 'none';
  }

  function weightSortHeader(column) {
    const active = S.etfV3.weightSortKey === column.key && S.etfV3.weightSortDirection !== 'none';
    const direction = active ? S.etfV3.weightSortDirection : 'none';
    const next = weightNextDirection(column.key);
    const arrow = direction === 'ascending' ? '▲' : direction === 'descending' ? '▼' : '↕';
    const label = `${column.label}；目前${weightDirectionLabel(direction)}；點擊切換為${weightDirectionLabel(next)}`;
    return `<th class="st-sortable-head" aria-sort="${direction}"><button type="button" class="st-sort-button" data-e3="weight-sort" data-key="${esc(column.key)}" data-direction="${direction}" aria-label="${esc(label)}" title="${esc(label)}">${esc(column.label)}<span class="st-sort-arrow" aria-hidden="true">${arrow}</span></button></th>`;
  }

  function weightSortValue(row, column) {
    const raw = row && row[column.key];
    if (raw == null || raw === '' || raw === '—' || raw === '-') return { missing:true, value:null };
    if (column.type === 'number') {
      const value = Number(raw);
      return Number.isFinite(value) ? { missing:false, value } : { missing:true, value:null };
    }
    if (column.type === 'date') {
      const value = Date.parse(String(raw));
      return Number.isFinite(value) ? { missing:false, value } : { missing:true, value:null };
    }
    const value = column.key === 'status'
      ? ({added:'新增持股', removed:'移除持股', increased:'增權', decreased:'減權'}[raw] || String(raw))
      : String(raw);
    return { missing:false, value };
  }

  function weightSourceLabel(source) {
    const raw = String(source || '');
    return /^moneydj(?:-|$)/i.test(raw) ? 'MoneyDJ（第三方）' : (raw || '—');
  }

  // 先對完整資料集穩定排序，再切每頁 100 筆；缺值不論升降冪都固定沉底。
  function sortWeightRows(rows) {
    const direction = S.etfV3.weightSortDirection;
    const column = WEIGHT_COLUMNS.find(item => item.key === S.etfV3.weightSortKey);
    if (!column || direction === 'none') return rows.slice();
    const sign = direction === 'ascending' ? 1 : -1;
    return rows.map((row, index) => ({ row, index })).sort((a, b) => {
      const av = weightSortValue(a.row, column);
      const bv = weightSortValue(b.row, column);
      if (av.missing && bv.missing) return a.index - b.index;
      if (av.missing) return 1;
      if (bv.missing) return -1;
      const compared = column.type === 'text'
        ? av.value.localeCompare(bv.value, 'zh-Hant', { numeric:true, sensitivity:'base' })
        : av.value - bv.value;
      return compared === 0 ? a.index - b.index : compared * sign;
    }).map(item => item.row);
  }

  function renderWeightPager(page, totalPages, totalRows) {
    const start = (page - 1) * WEIGHT_PAGE_SIZE + 1;
    const end = Math.min(totalRows, page * WEIGHT_PAGE_SIZE);
    return `<nav class="e3-weight-pager" aria-label="ETF 權重排名翻頁">
      <span>共 <strong>${totalRows.toLocaleString('zh-TW')}</strong> 筆 · 第 <strong>${page}</strong> / ${totalPages} 頁 · 顯示 ${start}–${end} · 每頁 ${WEIGHT_PAGE_SIZE} 筆</span>
      <span class="e3-page-actions">
        <button type="button" data-e3="weight-page" data-page="${page - 1}" ${page <= 1 ? 'disabled' : ''} aria-label="上一頁">← 上一頁</button>
        <button type="button" data-e3="weight-page" data-page="${page + 1}" ${page >= totalPages ? 'disabled' : ''} aria-label="下一頁">下一頁 →</button>
      </span>
    </nav>`;
  }

  // 權重是資產占比，不是成交股數或實際買賣超；保留每檔 ETF 的比較基準。
  function renderWeightRankings(delta, allowed) {
    const ranking = delta && delta.weight_rankings;
    let h = '<section class="e3-weight-rank"><div class="e3-section-hdr">ETF 增減權重・個股排名</div>';
    h += '<div class="e3-meta">點欄名依完整排名切換升冪／降冪／原始順序。增減為百分點，不等於實際買賣；價格漲跌也會改變權重。</div>';
    if (!ranking) return h + '<div class="e3-empty">目前後端尚未提供權重排名資料。</div></section>';
    const rows = (ranking.rows || []).filter(r => !allowed || allowed.has(String(r.etf_code).toUpperCase()));
    const excluded = (ranking.excluded || []).filter(r => !allowed || allowed.has(String(r.etf_code).toUpperCase()));
    const number = value => Number.isFinite(Number(value)) && value != null ? Number(value).toLocaleString('zh-TW', {maximumFractionDigits:4}) : '—';
    const sourceDates = ranking.source_dates || {};
    const dateList = value => Array.isArray(value) && value.length ? value.map(esc).join('、') : '依各 ETF 列示';
    h += `<div class="e3-weight-context">
      <span><strong>供應商資料日</strong>　前期 ${dateList(sourceDates.previous)}　→　本期 ${dateList(sourceDates.current)}</span>
      <span><strong>收集檔日期</strong>只代表本機取得快照的日期；每列會另列前後收集檔，不作為持股更新日。</span>
    </div>`;
    h += '<div class="e3-weight-mobile-hint">手機可左右滑動查看增減、日期與來源。</div>';
    if (!rows.length) h += '<div class="e3-empty">' + (ranking.status === 'ok' ? '可比較 ETF 的兩期持股權重相同，沒有增減。' : '尚無可比較持股；需同來源、不同供應商資料日的有效快照。') + '</div>';
    else {
      const sortedRows = sortWeightRows(rows);
      const totalPages = Math.max(1, Math.ceil(sortedRows.length / WEIGHT_PAGE_SIZE));
      const requestedPage = Number.parseInt(S.etfV3.weightPage, 10) || 1;
      const page = Math.min(totalPages, Math.max(1, requestedPage));
      S.etfV3.weightPage = page;
      const pageRows = sortedRows.slice((page - 1) * WEIGHT_PAGE_SIZE, page * WEIGHT_PAGE_SIZE);
      h += renderWeightPager(page, totalPages, sortedRows.length);
      h += '<div class="e3-weight-scroll" tabindex="0" aria-label="ETF 權重排名，可左右捲動"><table class="e3-weight-table" data-st-sort="off"><thead><tr>' +
        WEIGHT_COLUMNS.map(weightSortHeader).join('') + '</tr></thead><tbody>';
      for (const r of pageRows) {
        const diff = Number(r.delta_pp);
        const tw = (r.market || 'TW') === 'TW';
        const color = diff > 0 ? (tw ? 'var(--red)' : 'var(--green)') : diff < 0 ? (tw ? 'var(--green)' : 'var(--red)') : 'var(--tlo)';
        h += `<tr><td title="${esc(resolveName(r.etf_code, r.etf_name))}">${esc(r.etf_code)}</td><td><button class="e3-actbtn" data-e3="goto" data-sym="${esc(r.code)}" data-mkt="${esc(r.market || 'TW')}">${esc(r.code)} ${esc(r.name)}</button></td><td>${esc(r.market || 'TW')}</td>`;
        h += `<td data-sort-value="${esc(r.prev_weight)}">${number(r.prev_weight)}</td><td data-sort-value="${esc(r.weight)}">${number(r.weight)}</td>`;
        h += `<td data-sort-value="${esc(r.delta_pp)}" style="color:${color}">${diff > 0 ? '+' : ''}${number(r.delta_pp)}</td>`;
        const status = {added:'新增持股', removed:'移除持股', increased:'增權', decreased:'減權'}[r.status] || '待確認';
        const previousSnapshot = r.prev_snapshot_date || ranking.prev_snapshot_date || '—';
        const currentSnapshot = r.snapshot_date || ranking.snapshot_date || '—';
        h += `<td>${status}</td><td>${esc(r.prev_date || '—')}</td><td>${esc(r.date || '—')}</td><td title="原始來源碼：${esc(r.source || '—')}">${esc(weightSourceLabel(r.source))}</td><td data-sort-value="${esc(currentSnapshot)}">${esc(previousSnapshot)} → ${esc(currentSnapshot)}</td></tr>`;
      }
      h += '</tbody></table></div>';
      h += renderWeightPager(page, totalPages, sortedRows.length);
    }
    if (excluded.length) h += '<details><summary>未納入比較 '+excluded.length+' 檔 ETF（缺基準或資料不可比）</summary><div class="e3-meta">' + excluded.map(r => esc(r.etf_code)+'：'+esc(r.reason_label || '資料暫不可比較')).join('<br>') + '</div></details>';
    return h + '</section>';
  }

  // ─── ETF panel renderer ─────────────────────────────────────
  function renderEtfDelta() {
    // Lazy-fetch catalog if needed
    if (S.etfV3.catalog == null && !S.etfV3._catLoading) {
      S.etfV3._catLoading = true;
      fetchCatalog().finally(() => { S.etfV3._catLoading = false; });
    }
    // Lazy-fetch delta if no data, no error, not loading
    if (S.etfV3.deltaRaw == null && !S.etfV3.loading && !S.etfV3.err) {
      fetchDelta();
    }

    let h = '<div class="e3-wrap">';

    // Header: category tabs + actions
    h += '<div class="e3-tabs">';
    const cats = S.etfV3.catalog?.categories || [];
    const allDeltaCodes = new Set((S.etfV3.delta?.etfs || []).map(e => (e.code || '').toUpperCase()));
    for (const cat of cats) {
      const enabledList = (cat.etfs || []).filter(e => e.enabled);
      const cntEnabled = enabledList.length;
      if (cntEnabled === 0) continue;
      const cntWithData = enabledList.filter(e => allDeltaCodes.has((e.code || '').toUpperCase())).length;
      const on = cat.key === S.etfV3.catActive ? ' on' : '';
      // 顯示 "已抓到/已啟用"，相等時就顯示總數
      const cntDisplay = (cntWithData < cntEnabled && allDeltaCodes.size > 0)
        ? `${cntWithData}/${cntEnabled}` : `${cntEnabled}`;
      const tipMissing = (cntWithData < cntEnabled && allDeltaCodes.size > 0)
        ? `已啟用 ${cntEnabled} 檔，僅 ${cntWithData} 檔有 delta 資料；缺資料的 ETF 需在 etf_history 跑 tracker —— 點 ⚙ 管理 → 立即更新` : '';
      h += `<button class="e3-tab${on}" data-e3="cat" data-cat="${esc(cat.key)}" title="${esc(tipMissing)}">${cat.icon || ''} ${esc(cat.name)}<span class="cnt">${cntDisplay}</span></button>`;
    }
    h += `<button class="e3-tab${S.etfV3.catActive === '__WEIGHTS__' ? ' on' : ''}" data-e3="cat" data-cat="__WEIGHTS__">權重排名</button>`;
    // 🇺🇸 美股獨立分頁（無 MoneyDJ delta，改顯示報價清單）
    const usList = [];
    for (const c of cats) for (const e of (c.etfs || [])) if ((e.market || 'TW') === 'US') usList.push(e);
    if (usList.length) {
      const on = S.etfV3.catActive === '__US__' ? ' on' : '';
      h += `<button class="e3-tab${on}" data-e3="cat" data-cat="__US__" title="美股 ETF（報價，點擊載入）">🇺🇸 美股<span class="cnt">${usList.length}</span></button>`;
    }
    h += `<div class="e3-actions">
      <button class="e3-actbtn" data-e3="refresh" title="重新抓 /etf-delta">${S.etfV3.loading ? '⟳' : '↻'} 刷新</button>
      <button class="e3-actbtn" data-e3="report" title="跨 ETF 買賣超彙總報表：找潛在上漲/下跌標的">📋 報表</button>
      <button class="e3-actbtn primary" data-e3="mgr" title="管理觀測池">⚙ 管理</button>
    </div>`;
    h += '</div>';

    // Meta
    h += `<div class="e3-meta">
      <span>上次更新：${ago(S.etfV3.lastFetch)}</span>
      <span>切回此分頁自動重抓 (>60s)</span>
    </div>`;

    // 🇺🇸 美股分頁：跳過 TW delta，改渲染報價清單
    if (S.etfV3.catActive === '__US__') {
      h += renderUsSection();
      h += '</div>';
      return h;
    }

    // Loading
    if (S.etfV3.loading) {
      h += '<div class="e3-loading">⟳ 載入 ETF Delta...</div></div>';
      return h;
    }

    // Error
    if (S.etfV3.err) {
      const err = S.etfV3.err;
      const needHist = /history|file|need|≥2|dir=/i.test(err);
      const hint = needHist
        ? '尚無足夠歷史檔（需 ≥ 2 個交易日）<br><span style="font-size:9px;color:var(--tf)">執行 <code style="color:var(--gold)">python etf_delta_tracker.py --backfill 5</code></span>'
        : `<span style="font-size:9px;color:var(--red)">${esc(err)}</span><br><span style="font-size:9px;color:var(--tf)">請確認 server.py 跑著於 :18432</span>`;
      h += `<div class="e3-empty">${hint}<button class="e3-retry" data-e3="refresh">↻ 重試</button></div></div>`;
      return h;
    }

    // No data
    if (!S.etfV3.delta) {
      h += `<div class="e3-empty">無資料<span class="hint">點 ↻ 刷新</span></div></div>`;
      return h;
    }

    const d = S.etfV3.delta;

    // 權重排名是獨立契約，不沿用舊 delta 的摘要與快照日期列。
    if (S.etfV3.catActive === '__WEIGHTS__') {
      const rankAllowed = S.etfV3.catalog ? enabledSet(S.etfV3.catalog) : null;
      return h + renderWeightRankings(d, rankAllowed) + '</div>';
    }

    // Filter to current category
    const cat = cats.find(c => c.key === S.etfV3.catActive);
    let etfs = d.etfs || [];
    if (cat) {
      const allowed = new Set((cat.etfs || []).filter(e => e.enabled).map(e => (e.code || '').toUpperCase()));
      etfs = etfs.filter(e => allowed.has((e.code || '').toUpperCase()));
    }

    // Summary (recalculated from current category subset)
    let nN = 0, nR = 0, nC = 0;
    for (const e of etfs) {
      nN += (e.new || []).length;
      nR += (e.removed || []).length;
      nC += (e.changed || []).length;
    }
    h += `<div class="e3-summary">
      <div class="e3-sumcell"><div class="n" style="color:var(--green)">${nN}</div><div class="l">新增</div></div>
      <div class="e3-sumcell"><div class="n" style="color:var(--red)">${nR}</div><div class="l">移除</div></div>
      <div class="e3-sumcell"><div class="n" style="color:var(--blue)">${nC}</div><div class="l">加減碼</div></div>
    </div>`;

    // Date bar
    h += `<div class="e3-meta"><span>📅 ${esc(d.date)} vs ${esc(d.prev_date)}</span><span></span></div>`;

    if (etfs.length === 0) {
      h += `<div class="e3-empty">此分類無已啟用 ETF<span class="hint">點右上 ⚙ 管理 啟用更多 ETF</span></div></div>`;
      return h;
    }

    // Cross-ETF consensus
    const newMap = {};
    for (const etf of etfs) {
      for (const n of (etf.new || [])) {
        if (!newMap[n.code]) newMap[n.code] = { code: n.code, name: n.name, etfs: [] };
        newMap[n.code].etfs.push({ etf: etf.code, w: n.weight });
      }
    }
    const consensus = Object.values(newMap).filter(x => x.etfs.length >= 2);
    if (consensus.length) {
      h += '<div class="e3-section-hdr">🔥 跨 ETF 共識新增</div>';
      for (const c of consensus) {
        const srcs = c.etfs.map(e => `${e.etf}(${e.w}%)`).join(' · ');
        h += `<div class="e3-consensus" data-e3="goto" data-sym="${esc(c.code)}">
          <div class="stk">${esc(c.code)} ${esc(c.name || '')}</div>
          <div class="src">${esc(srcs)}</div>
        </div>`;
      }
    }

    // ETF cards (each ETF expandable)
    h += '<div class="e3-section-hdr">ETF 持股變動明細</div>';
    for (const e of etfs) {
      const code = (e.code || '').toUpperCase();
      const opened = S.etfV3.expanded.has(code);
      const nNew = (e.new || []).length;
      const nRm  = (e.removed || []).length;
      const nCh  = (e.changed || []).length;
      h += `<div class="e3-card${opened ? ' open' : ''}">`;
      h += `<div class="e3-card-hdr" data-e3="toggle" data-code="${esc(code)}">
        <span class="e3-card-arrow">▶</span>
        <span class="e3-card-code" data-e3="goto" data-sym="${esc(code)}" data-mkt="TW" title="載入 ${esc(code)} K線" style="cursor:pointer">${esc(code)}</span>
        <span class="e3-card-name">${esc(resolveName(code, e.name))}</span>
        <div class="e3-card-badges">
          ${nNew ? `<span class="e3-badge new">+${nNew}</span>` : ''}
          ${nRm  ? `<span class="e3-badge rm">-${nRm}</span>`   : ''}
          ${nCh  ? `<span class="e3-badge chg">~${nCh}</span>`  : ''}
          ${(!nNew && !nRm && !nCh) ? `<span class="e3-badge empty">${e.has_baseline === false ? '尚無基準' : '無變動'}</span>` : ''}
        </div>
      </div>`;
      if (opened) {
        h += '<div class="e3-card-body">';
        // ── v3.1 Top 10 當前持股（最先顯示，給使用者快速確認投資標的） ──
        const top10 = e.top10 || [];
        if (top10.length) {
          const totalW = top10.reduce((s, x) => s + (x.weight || 0), 0);
          const maxW = top10[0]?.weight || 1;
          h += '<div class="e3-section-hdr">📊 Top 10 持股（按比例）</div>';
          h += '<div class="e3-top10">';
          for (const t of top10) {
            const w = t.weight || 0;
            const barPct = Math.min(100, (w / maxW) * 100);
            h += `<div class="e3-stock" data-e3="goto" data-sym="${esc(t.code)}" data-mkt="${esc(t.market || 'TW')}" title="${esc(t.name || '')}${t.market && t.market !== 'TW' ? ' · ' + t.market : ''}">
              <span class="rank">${t.rank || ''}</span>
              <span class="scode">${esc(t.code)}${t.market && t.market !== 'TW' ? `<span style="color:var(--tlo);font-size:8px;margin-left:3px">.${esc(t.market)}</span>` : ''}</span>
              <span class="sname">${esc(t.name || '')}</span>
              <span class="bar"><i style="width:${barPct.toFixed(1)}%"></i></span>
              <span class="swt gold">${w.toFixed(2)}%</span>
            </div>`;
          }
          h += '</div>';
          h += `<div class="e3-top10-foot">Top 10 合計 <b style="color:var(--gold)">${totalW.toFixed(2)}%</b> · 總持股 ${e.total || top10.length} 檔</div>`;
        }
        if (nNew) {
          h += '<div class="e3-section-hdr">▲ 新增持股</div>';
          for (const n of e.new) {
            h += `<div class="e3-stock" data-e3="goto" data-sym="${esc(n.code)}" data-mkt="${esc(n.market || 'TW')}">
              <span class="scode">${esc(n.code)}${n.market && n.market !== 'TW' ? `<span style="color:var(--tlo);font-size:8px;margin-left:3px">.${esc(n.market)}</span>` : ''}</span>
              <span class="sname">${esc(n.name || '')}</span>
              <span class="swt green">+${(n.weight ?? 0).toFixed(2)}%</span>
            </div>`;
          }
        }
        if (nRm) {
          h += '<div class="e3-section-hdr">▼ 移除持股</div>';
          for (const r of e.removed) {
            h += `<div class="e3-stock" data-e3="goto" data-sym="${esc(r.code)}" data-mkt="${esc(r.market || 'TW')}">
              <span class="scode">${esc(r.code)}${r.market && r.market !== 'TW' ? `<span style="color:var(--tlo);font-size:8px;margin-left:3px">.${esc(r.market)}</span>` : ''}</span>
              <span class="sname">${esc(r.name || '')}</span>
              <span class="swt red">-${(r.prev_weight ?? 0).toFixed(2)}%</span>
            </div>`;
          }
        }
        if (nCh) {
          h += '<div class="e3-section-hdr">↔ 加減碼</div>';
          for (const c of e.changed) {
            const cls = c.delta >= 0 ? 'green' : 'red';
            const sign = c.delta >= 0 ? '+' : '';
            h += `<div class="e3-stock" data-e3="goto" data-sym="${esc(c.code)}" data-mkt="${esc(c.market || 'TW')}">
              <span class="scode">${esc(c.code)}${c.market && c.market !== 'TW' ? `<span style="color:var(--tlo);font-size:8px;margin-left:3px">.${esc(c.market)}</span>` : ''}</span>
              <span class="sname">${esc(c.name || '')}</span>
              <span class="swt ${cls}">${sign}${(c.delta ?? 0).toFixed(2)}%</span>
            </div>`;
          }
        }
        if (!nNew && !nRm && !nCh && !top10.length) {
          h += '<div class="e3-empty" style="padding:14px 12px;font-size:9.5px">此 ETF 在當日無持股變動</div>';
        }
        h += '</div>';
      }
      h += '</div>';
    }

    h += '</div>';
    return h;
  }

  // ─── STATS holdings sub-section ─────────────────────────────
  function renderEtfHoldingsForStock(sym) {
    if (!sym) return '';
    if (!S.etfV3.delta) return '';
    const rows = [];
    for (const etf of (S.etfV3.delta.etfs || [])) {
      const n = (etf.new || []).find(s => s.code === sym);
      if (n) { rows.push({ code: etf.code, type: 'new', val: n.weight }); continue; }
      const rm = (etf.removed || []).find(s => s.code === sym);
      if (rm) { rows.push({ code: etf.code, type: 'rm', val: rm.prev_weight }); continue; }
      const ch = (etf.changed || []).find(s => s.code === sym);
      if (ch) { rows.push({ code: etf.code, type: 'chg', val: ch.delta }); }
    }
    if (!rows.length) return '';
    let h = '<div class="stat-sect">主動 ETF 對此股動向</div>';
    for (const r of rows) {
      const lbl = r.type === 'new' ? '新進' : r.type === 'rm' ? '移除' : '加減碼';
      const col = r.type === 'rm' ? 'var(--green)' : (window.Colors ? Colors.gain(r.val) : (r.val >= 0 ? 'var(--red)' : 'var(--green)'));
      const sign = (r.type !== 'rm' && r.val >= 0) ? '+' : (r.type === 'rm' ? '-' : '');
      const num = Math.abs(r.val ?? 0).toFixed(2);
      h += `<div class="e3-hold-row"><span class="k">${esc(r.code)} ${lbl}</span><span class="v" style="color:${col}">${sign}${num}%</span></div>`;
    }
    return h;
  }

  // ─── 跨 ETF 買賣超彙總報表 ──────────────────────────────────
  function buildEtfReport() {
    const etfs = (S.etfV3.deltaRaw && S.etfV3.deltaRaw.etfs)
      || (S.etfV3.delta && S.etfV3.delta.etfs) || [];
    const agg = {};   // code -> {code,name, add:[], inc:[], rm:[], dec:[], wIn, wOut}
    const get = (code, name) => {
      const k = (code || '').toUpperCase();
      if (!agg[k]) agg[k] = { code, name: name || '', add: [], inc: [], rm: [], dec: [], wIn: 0, wOut: 0, addShares: 0 };
      if (name && !agg[k].name) agg[k].name = name;
      return agg[k];
    };
    for (const e of etfs) {
      const etf = e.code;
      for (const n of (e.new || [])) { const s = get(n.code, n.name); s.add.push(etf); s.wIn += (n.weight || 0); s.addShares += (n.shares || 0); }
      for (const c of (e.changed || [])) {
        const s = get(c.code, c.name);
        if ((c.delta || 0) >= 0) { s.inc.push(etf); s.wIn += (c.delta || 0); s.addShares += Math.max(0, c.shares_delta || 0); }
        else { s.dec.push(etf); s.wOut += Math.abs(c.delta || 0); }
      }
      for (const r of (e.removed || [])) { const s = get(r.code, r.name); s.rm.push(etf); s.wOut += (r.prev_weight || 0); }
    }
    // 權重：新增/移除 與 加碼/減碼 同權，皆 ×2
    const arr = Object.values(agg).map(s => ({
      ...s,
      bull: (s.add.length + s.inc.length) * 2,
      bear: (s.rm.length + s.dec.length) * 2,
    })).map(s => ({ ...s, net: s.bull - s.bear }));
    const up = arr.filter(s => s.bull > 0).sort((a, b) => b.bull - a.bull || b.wIn - a.wIn);
    const down = arr.filter(s => s.bear > 0).sort((a, b) => b.bear - a.bear || b.wOut - a.wOut);
    const net = arr.filter(s => s.net !== 0).sort((a, b) => b.net - a.net);
    return { up, down, net, etfCount: etfs.length };
  }

  function reportRows(list, side) {
    if (!list.length) return '<div class="e3-empty" style="padding:18px">無資料</div>';
    let h = '';
    for (const s of list.slice(0, 40)) {
      const badges = side === 'up'
        ? `${s.add.length ? `<span class="e3-badge new">▲新增 ${s.add.length}</span>` : ''}${s.inc.length ? `<span class="e3-badge chg">＋加碼 ${s.inc.length}</span>` : ''}`
        : `${s.rm.length ? `<span class="e3-badge rm">▼移除 ${s.rm.length}</span>` : ''}${s.dec.length ? `<span class="e3-badge chg">－減碼 ${s.dec.length}</span>` : ''}`;
      const etfUp = [...new Set([...s.add, ...s.inc])];
      const etfList = [...new Set([...(side === 'up' ? [...s.add, ...s.inc] : [...s.rm, ...s.dec])])].slice(0, 8).join(' · ');
      const wt = side === 'up' ? s.wIn : s.wOut;
      const wtCol = side === 'up' ? 'var(--red)' : 'var(--green)';
      // v3.9 P5：買盤側顯示「投信潛在買盤佔個股日均量%」+ AI 原因鈕
      const extra = (side === 'up' && s.addShares > 0)
        ? `<div class="e3-volpct" data-sym="${esc(s.code)}" data-shares="${s.addShares}" style="color:var(--gold);font-size:8.5px;margin-top:2px">佔量 計算中…</div>`
          + `<button class="e3-reason" data-sym="${esc(s.code)}" data-name="${esc(s.name || '')}" data-etfs="${esc(etfUp.slice(0, 6).join(','))}" data-shares="${s.addShares}" data-weight="${wt.toFixed(2)}" data-action="${s.add.length ? '新增' : '加碼'}" style="margin-top:3px;background:#1e293b;border:1px solid #334155;color:#a5b4fc;border-radius:4px;font-size:8.5px;padding:1px 6px;cursor:pointer">🤖 原因</button>`
        : '';
      h += `<div class="e3-stock" data-e3m="load" data-sym="${esc(s.code)}" data-mkt="TW" style="cursor:pointer;align-items:flex-start;padding:7px 12px">
        <span style="font-weight:700;color:var(--thi);min-width:54px">${esc(s.code)}</span>
        <span class="sname" style="flex:1">${esc(s.name || '')}<div style="color:var(--tf);font-size:8.5px;margin-top:2px">${esc(etfList)}</div><div class="e3-reason-out" data-for="${esc(s.code)}" style="color:#c7d2fe;font-size:9px;margin-top:3px"></div></span>
        <span style="text-align:right;white-space:nowrap">${badges}<div style="color:${wtCol};font-size:9px;margin-top:2px">權重 ${wt.toFixed(2)}%</div>${extra}</span>
      </div>`;
    }
    return h;
  }

  function netRows(list) {
    if (!list.length) return '<div class="e3-empty" style="padding:18px">無資料</div>';
    let h = '';
    for (const s of list.slice(0, 60)) {
      const pos = s.net > 0;
      const col = window.Colors ? Colors.gain(s.net) : (pos ? 'var(--red)' : 'var(--green)');
      const etfList = [...new Set([...s.add, ...s.inc, ...s.rm, ...s.dec])].slice(0, 8).join(' · ');
      h += `<div class="e3-stock" data-e3m="load" data-sym="${esc(s.code)}" data-mkt="TW" style="cursor:pointer;align-items:center;padding:6px 12px">
        <span style="font-weight:800;color:${col};min-width:42px;font-size:13px;text-align:center">${pos ? '+' : ''}${s.net}</span>
        <span style="font-weight:700;color:var(--thi);min-width:54px">${esc(s.code)}</span>
        <span class="sname" style="flex:1">${esc(s.name || '')}<div style="color:var(--tf);font-size:8.5px;margin-top:2px">${esc(etfList)}</div></span>
        <span style="text-align:right;white-space:nowrap;font-size:8.5px;color:var(--tlo)">▲${s.add.length}/＋${s.inc.length} ▼${s.rm.length}/－${s.dec.length}</span>
      </div>`;
    }
    return h;
  }

  function renderReportBody(rep, mode) {
    if (mode === 'net') {
      return `<div class="e3-section-hdr">📊 淨分數排序（買盤共識 − 賣盤共識，正=偏多 負=偏空）</div>${netRows(rep.net)}`;
    }
    return `<div style="display:grid;grid-template-columns:1fr 1fr;gap:0">
        <div style="border-right:1px solid var(--border)">
          <div class="e3-section-hdr" style="color:var(--green)">🟢 潛在上漲（買盤共識）</div>
          ${reportRows(rep.up, 'up')}
        </div>
        <div>
          <div class="e3-section-hdr" style="color:var(--red)">🔴 潛在下跌（賣盤共識）</div>
          ${reportRows(rep.down, 'down')}
        </div>
      </div>`;
  }

  // 把報表轉純文字（供 Email）
  function reportToText(rep, date) {
    const line = s => `${s.net >= 0 ? '+' : ''}${s.net}\t${s.code} ${s.name || ''}\t(新增${s.add.length}/加碼${s.inc.length}/移除${s.rm.length}/減碼${s.dec.length})`;
    const up = rep.net.filter(s => s.net > 0).slice(0, 20).map(line).join('\n');
    const dn = rep.net.filter(s => s.net < 0).slice(0, 20).map(line).join('\n');
    return `ETF 操盤手共識報表 ${date}\n彙總 ${rep.etfCount} 檔主動 ETF 當日新增/移除/加減碼\n\n` +
      `=== 潛在上漲（淨分數前 20）===\n${up || '無'}\n\n` +
      `=== 潛在下跌（淨分數後 20）===\n${dn || '無'}\n\n⚠ 僅反映持股異動，非投資建議。`;
  }

  async function emailReport(mode) {
    // 由伺服器自建 HTML 報表並寄出。mode: 'full'(多區塊) | 'lite'(加減碼 Top10)
    try {
      const r = await fetch(`${SERVER}/etf-report/email`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: mode || 'full' }),
      });
      const d = await r.json();
      alert(d.ok ? `已寄出 Email 報表 ✓（${mode === 'lite' ? '加減碼 Top10' : '完整多區塊'}）`
                 : ('寄送失敗：' + JSON.stringify(d.results || d) + '\n請確認 🔔 推播已設定 Email'));
    } catch (e) { alert('寄送失敗：' + e.message + '\n請確認 server 跑著且 🔔 推播已設定 Email'); }
  }

  async function openEtfReportModal() {
    if (S.etfV3.catalog == null) await fetchCatalog();
    if (S.etfV3.deltaRaw == null && S.etfV3.delta == null) { try { await fetchDelta(); } catch {} }
    closeMgrModal();
    const rep = buildEtfReport();
    S.etfV3._rep = rep;
    const mode = S.etfV3.reportMode || 'dual';
    const m = document.createElement('div');
    m.className = 'e3-modal'; m.id = 'e3-modal';
    const date = (S.etfV3.deltaRaw && S.etfV3.deltaRaw.date) || (S.etfV3.delta && S.etfV3.delta.date) || '';
    const tabBtn = (k, lbl) => `<button class="e3-mbtn${mode === k ? ' primary' : ''}" data-e3m="rep-mode" data-mode="${k}">${lbl}</button>`;
    m.innerHTML = `
      <div class="panel">
        <div class="head">
          <h3>📋 ETF 操盤手共識報表 · ${esc(date)}</h3>
          <span class="x" data-e3m="close">×</span>
        </div>
        <div style="display:flex;gap:6px;align-items:center;padding:8px 14px;border-bottom:1px solid var(--border)">
          ${tabBtn('dual', '雙榜（上漲/下跌）')}${tabBtn('net', '淨分數單榜')}
          <button class="e3-mbtn" data-e3m="email" data-mode="full" style="margin-left:auto">📧 完整報表</button>
          <button class="e3-mbtn" data-e3m="email" data-mode="lite">📧 加減碼Top10</button>
        </div>
        <div style="padding:6px 14px;font-family:monospace;font-size:9px;color:var(--tlo);border-bottom:1px solid var(--border)">
          彙總 ${rep.etfCount} 檔主動 ETF；評分 新增/移除/加碼/減碼 皆 ×2。多檔同步買進→潛在上漲，同步賣出→潛在下跌。點列載入線型。
        </div>
        <div class="body" id="e3-rep-body" style="padding:0">${renderReportBody(rep, mode)}</div>
        <div class="foot">
          <span style="font-family:monospace;font-size:9px;color:var(--tf)">⚠ 僅反映主動 ETF 當日持股異動，非投資建議</span>
          <button class="e3-mbtn" data-e3m="close">關閉</button>
        </div>
      </div>`;
    document.body.appendChild(m);
    m.addEventListener('click', ev => { if (ev.target === m) closeMgrModal(); });
    enhanceConsensus(rep);
  }

  // ─── v3.9 P5: 佔量% + AI 原因推導 ───────────────────────────
  const _SRV = () => (typeof window !== 'undefined' && window.SERVER) ? window.SERVER : 'http://localhost:18432';

  async function enhanceConsensus(rep) {
    // 1) AI 原因鈕（事件委派，阻止冒泡避免觸發整列載入）
    document.querySelectorAll('#e3-modal .e3-reason').forEach(btn => {
      btn.onclick = async (ev) => {
        ev.stopPropagation();
        const out = document.querySelector(`#e3-modal .e3-reason-out[data-for="${CSS.escape(btn.dataset.sym)}"]`);
        if (!(typeof S !== 'undefined' && S.aiKeySet)) { if (out) out.textContent = '⚠ 請先在右上角設定 API KEY'; return; }
        btn.disabled = true; btn.textContent = '🤖 推導中…';
        try {
          const r = await fetch(_SRV() + '/etf-reason', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              apiKey: '', code: btn.dataset.sym, name: btn.dataset.name,
              etfs: (btn.dataset.etfs || '').split(',').filter(Boolean),
              action: btn.dataset.action, sharesDelta: btn.dataset.shares, weightDelta: btn.dataset.weight,
            }),
          }).then(x => x.json());
          if (out) out.textContent = r.reason ? ('🤖 ' + r.reason) : ('⚠ ' + (r.error || '無回應'));
        } catch (e) { if (out) out.textContent = '⚠ ' + e.message; }
        btn.textContent = '🤖 原因'; btn.disabled = false;
      };
    });
    // 2) 佔量%：批次抓買盤側個股 20 日均量，算 投信加碼張數 ÷ 日均量
    const cells = [...document.querySelectorAll('#e3-modal .e3-volpct')];
    if (!cells.length) return;
    const codes = [...new Set(cells.map(c => c.dataset.sym))];
    try {
      const url = `${_SRV()}/yf/batch?syms=${codes.map(c => c + '.TW').join(',')}&range=1mo&interval=1d`;
      const data = await fetch(url, { cache: 'no-store' }).then(x => x.ok ? x.json() : {});
      const avgVol = {};
      for (const c of codes) {
        const res = data[c + '.TW'] && data[c + '.TW'].chart && data[c + '.TW'].chart.result && data[c + '.TW'].chart.result[0];
        const vols = (res && res.indicators && res.indicators.quote && res.indicators.quote[0] && res.indicators.quote[0].volume) || [];
        const valid = vols.filter(v => v != null && isFinite(v) && v > 0).slice(-20);
        avgVol[c] = valid.length ? valid.reduce((a, b) => a + b, 0) / valid.length : null;
      }
      cells.forEach(cell => {
        const sym = cell.dataset.sym, sh = parseFloat(cell.dataset.shares) || 0;
        const av = avgVol[sym];
        if (!av) { cell.textContent = '佔量 —（均量無資料）'; return; }
        const pct = sh / av * 100;
        const lots = Math.round(sh / 1000);
        cell.textContent = `投信買盤 ≈ ${lots.toLocaleString()} 張 ≈ 20日均量 ${pct.toFixed(1)}%`;
        cell.style.color = pct >= 30 ? 'var(--red)' : pct >= 10 ? 'var(--gold)' : 'var(--tf)';
      });
    } catch (e) {
      cells.forEach(cell => { cell.textContent = '佔量 計算失敗'; });
    }
  }

  // ─── Manager modal ──────────────────────────────────────────
  async function openEtfMgrModal() {
    if (S.etfV3.catalog == null) await fetchCatalog();
    closeMgrModal();
    const m = document.createElement('div');
    m.className = 'e3-modal';
    m.id = 'e3-modal';
    m.innerHTML = `
      <div class="panel">
        <div class="head">
          <h3>⚙ ETF 觀測池管理</h3>
          <span class="x" data-e3m="close">×</span>
        </div>
        <div class="body" id="e3-mgr-body">${renderMgrBody()}</div>
        <div class="foot">
          <span style="font-family:monospace;font-size:9.5px;color:var(--tlo)" id="e3-foot-msg">勾選 = 加入每日追蹤池 · 點 × 移除自訂 ETF</span>
          <div style="display:flex;gap:6px">
            <button class="e3-mbtn" data-e3m="close">關閉</button>
            <button class="e3-mbtn" data-e3m="save">💾 只儲存</button>
            <button class="e3-mbtn primary" data-e3m="save-run">💾 儲存並立即更新</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(m);
    m.addEventListener('click', ev => { if (ev.target === m) closeMgrModal(); });
  }

  function closeMgrModal() {
    document.getElementById('e3-modal')?.remove();
  }

  function renderMgrBody() {
    if (!S.etfV3.catalog?.categories) {
      return '<div style="padding:30px;text-align:center;color:var(--tlo);font-family:monospace">載入 catalog 中...</div>';
    }
    const mkt = S.etfV3.mgrMkt || 'all';   // 'all' | 'TW' | 'US'
    const matchMkt = e => mkt === 'all' || (e.market || 'TW') === mkt;
    const tab = (k, lbl) => `<button class="e3-mkttab${mkt === k ? ' on' : ''}" data-e3m="mgr-mkt" data-mkt="${k}">${lbl}</button>`;
    let h = `<div class="e3-mkttabs">${tab('all', '全部')}${tab('TW', '🇹🇼 台股')}${tab('US', '🇺🇸 美股')}
      <span style="margin-left:auto;font-size:9px;color:var(--tlo)">點代號可載入線型 · 美股以 US 市場開啟</span></div>`;
    const cats = S.etfV3.catalog.categories;
    for (let ci = 0; ci < cats.length; ci++) {
      const cat = cats[ci];
      const visible = (cat.etfs || []).map((e, ei) => ({ e, ei })).filter(o => matchMkt(o.e));
      if (!visible.length) continue;   // 此市場篩選下該分類無項目 → 跳過
      const enabledCnt = (cat.etfs || []).filter(e => e.enabled).length;
      const totalEtfs = (cat.etfs || []).length;
      h += `<div class="e3-mgrcat">
        <div class="e3-mgrcat-h">
          <span>${cat.icon || ''} ${esc(cat.name)}</span>
          <span style="display:flex;gap:5px;align-items:center;">
            <button class="e3-cat-btn" data-e3m="cat-all" data-ci="${ci}" data-mode="on"  title="全選此分類">☑ 全選</button>
            <button class="e3-cat-btn" data-e3m="cat-all" data-ci="${ci}" data-mode="off" title="全不選">☐ 清空</button>
            <span style="font-size:9.5px;color:var(--tlo);font-weight:400;min-width:42px;text-align:right;">${enabledCnt} / ${totalEtfs}</span>
          </span>
        </div>
        <div class="e3-mgrcat-desc">${esc(cat.desc || '')}</div>
        <div class="e3-mgrlist">`;
      for (const { e, ei } of visible) {
        const isCustom = cat.key === 'custom';
        const em = e.market || 'TW';
        const tag = em === 'US' ? '<span class="e3-mkt-tag us">US</span>' : '';
        h += `<div class="e3-mgritem${e.enabled ? '' : ' off'}">
          <input type="checkbox" data-e3m="toggle" data-ci="${ci}" data-ei="${ei}" ${e.enabled ? 'checked' : ''}>
          <span class="code" data-e3m="load" data-sym="${esc(e.code)}" data-mkt="${esc(em)}" title="載入 ${esc(e.code)} 線型" style="cursor:pointer">${esc(e.code)}${tag}</span>
          <span class="name" data-e3m="load" data-sym="${esc(e.code)}" data-mkt="${esc(em)}" style="cursor:pointer">${esc(e.name || '')}</span>
          ${isCustom ? `<span class="rm" data-e3m="remove" data-ci="${ci}" data-ei="${ei}" title="移除">×</span>` : ''}
        </div>`;
      }
      h += `</div>`;
      if (cat.key === 'custom') {
        h += `<div class="e3-addform">
          <div style="font-family:monospace;font-size:10px;color:var(--gold);font-weight:700;letter-spacing:.5px">+ 新增自訂 ETF</div>
          <div class="row">
            <input id="e3-add-code" type="text" placeholder="代號（台股 00935A / 美股 TQQQ）" maxlength="8" style="text-transform:uppercase">
            <input id="e3-add-name" type="text" placeholder="名稱" maxlength="20">
            <select id="e3-add-mkt" title="市場">
              <option value="TW">🇹🇼 台股</option>
              <option value="US">🇺🇸 美股</option>
            </select>
            <select id="e3-add-cat">
              ${cats.map(c => `<option value="${esc(c.key)}" ${c.key === 'custom' ? 'selected' : ''}>${c.icon || ''} ${esc(c.name)}</option>`).join('')}
            </select>
            <button data-e3m="add">＋ 加入</button>
          </div>
          <div class="hint">代號需可在 MoneyDJ <code>basic0007.xdjhtm?etfid=CODE.TW</code> 查到才能抓持股</div>
        </div>`;
      }
      h += `</div>`;
    }
    return h;
  }

  function setFootMsg(msg, color) {
    const m = document.getElementById('e3-foot-msg');
    if (m) { m.textContent = msg; m.style.color = color || 'var(--tlo)'; }
  }

  // ─── Click delegation (panel + modal) ───────────────────────
  document.addEventListener('click', ev => {
    // Panel actions
    const pa = ev.target.closest('[data-e3]');
    if (pa) {
      const act = pa.dataset.e3;
      if (act === 'cat') {
        ev.preventDefault();
        S.etfV3.catActive = pa.dataset.cat;
        if (S.etfV3.catActive === '__WEIGHTS__') S.etfV3.weightPage = 1;
        if (typeof renderRpanel === 'function') renderRpanel();
      }
      if (act === 'weight-sort') {
        ev.preventDefault();
        const key = pa.dataset.key;
        if (!WEIGHT_COLUMNS.some(column => column.key === key)) return;
        if (S.etfV3.weightSortKey !== key || S.etfV3.weightSortDirection === 'none') {
          S.etfV3.weightSortKey = key;
          S.etfV3.weightSortDirection = 'ascending';
        } else if (S.etfV3.weightSortDirection === 'ascending') {
          S.etfV3.weightSortDirection = 'descending';
        } else {
          S.etfV3.weightSortKey = null;
          S.etfV3.weightSortDirection = 'none';
        }
        S.etfV3.weightPage = 1;
        if (typeof renderRpanel === 'function') renderRpanel();
      }
      if (act === 'weight-page') {
        ev.preventDefault();
        if (pa.disabled) return;
        const page = Number.parseInt(pa.dataset.page, 10);
        if (Number.isFinite(page)) S.etfV3.weightPage = Math.max(1, page);
        if (typeof renderRpanel === 'function') renderRpanel();
      }
      if (act === 'refresh') { ev.preventDefault(); fetchDelta(); }
      if (act === 'report') { ev.preventDefault(); openEtfReportModal(); }
      if (act === 'mgr') { ev.preventDefault(); openEtfMgrModal(); }
      if (act === 'toggle') {
        ev.preventDefault();
        const code = pa.dataset.code;
        if (S.etfV3.expanded.has(code)) S.etfV3.expanded.delete(code);
        else S.etfV3.expanded.add(code);
        if (typeof renderRpanel === 'function') renderRpanel();
      }
      if (act === 'goto') {
        ev.preventDefault();
        const sym = pa.dataset.sym;
        const mkt = pa.dataset.mkt || 'TW';
        if (sym && typeof loadSym === 'function') {
          const [yfSym, uiMkt] = mapToYahoo(sym, mkt);
          loadSym(yfSym, uiMkt);
        }
      }
      return;
    }
    // Modal actions
    const ma = ev.target.closest('[data-e3m]');
    if (!ma) return;
    const act = ma.dataset.e3m;
    if (act === 'close') { ev.preventDefault(); closeMgrModal(); return; }
    if (act === 'rep-mode') {
      ev.preventDefault();
      S.etfV3.reportMode = ma.dataset.mode;
      const body = document.getElementById('e3-rep-body');
      if (body && S.etfV3._rep) body.innerHTML = renderReportBody(S.etfV3._rep, S.etfV3.reportMode);
      document.querySelectorAll('[data-e3m="rep-mode"]').forEach(b =>
        b.classList.toggle('primary', b.dataset.mode === S.etfV3.reportMode));
      return;
    }
    if (act === 'email') { ev.preventDefault(); emailReport(ma.dataset.mode || 'full'); return; }
    if (act === 'mgr-mkt') {
      ev.preventDefault();
      S.etfV3.mgrMkt = ma.dataset.mkt;
      const body = document.getElementById('e3-mgr-body');
      if (body) body.innerHTML = renderMgrBody();
      return;
    }
    if (act === 'load') {
      ev.preventDefault();
      const sym = ma.dataset.sym, mk = ma.dataset.mkt || 'TW';
      closeMgrModal();
      if (typeof loadSym === 'function') loadSym(sym, mk);
      return;
    }
    if (act === 'toggle') {
      const ci = +ma.dataset.ci, ei = +ma.dataset.ei;
      const e = S.etfV3.catalog?.categories[ci]?.etfs[ei];
      if (e) e.enabled = ma.checked;
      const row = ma.closest('.e3-mgritem');
      if (row) row.classList.toggle('off', !ma.checked);
      const grp = ma.closest('.e3-mgrcat');
      if (grp) {
        const meta = grp.querySelector('.e3-mgrcat-h span:last-child');
        const total = S.etfV3.catalog.categories[ci].etfs.length;
        const enabled = S.etfV3.catalog.categories[ci].etfs.filter(x => x.enabled).length;
        if (meta) meta.textContent = `${enabled} / ${total}`;
      }
      return;
    }
    if (act === 'remove') {
      ev.preventDefault();
      const ci = +ma.dataset.ci, ei = +ma.dataset.ei;
      const code = S.etfV3.catalog?.categories[ci]?.etfs[ei]?.code;
      if (!code) return;
      if (confirm(`移除 ${code}？`)) {
        S.etfV3.catalog.categories[ci].etfs.splice(ei, 1);
        const body = document.getElementById('e3-mgr-body');
        if (body) body.innerHTML = renderMgrBody();
      }
      return;
    }
    if (act === 'cat-all') {
      ev.preventDefault();
      const ci = +ma.dataset.ci;
      const mode = ma.dataset.mode;   // 'on' | 'off'
      const cat = S.etfV3.catalog?.categories[ci];
      if (!cat) return;
      const enable = (mode === 'on');
      let changed = 0;
      for (const e of (cat.etfs || [])) {
        if (e.enabled !== enable) { e.enabled = enable; changed++; }
      }
      // Re-render modal body to reflect new states
      const body = document.getElementById('e3-mgr-body');
      if (body) body.innerHTML = renderMgrBody();
      setFootMsg(`${cat.icon || ''} ${cat.name}：${enable ? '全選' : '全不選'} (${changed} 檔變更)`, enable ? 'var(--green)' : 'var(--tlo)');
      return;
    }
    if (act === 'add') {
      ev.preventDefault();
      const code = document.getElementById('e3-add-code').value.trim().toUpperCase();
      const name = document.getElementById('e3-add-name').value.trim();
      const catKey = document.getElementById('e3-add-cat').value;
      const mkt = (document.getElementById('e3-add-mkt') || {}).value || 'TW';
      if (!code || !name) { alert('請填代號與名稱'); return; }
      const okTw = /^[0-9]{4,6}[A-Z]?$/.test(code);
      const okUs = /^[A-Z][A-Z0-9.]{0,7}$/.test(code);
      if (mkt === 'TW' ? !okTw : !okUs) {
        alert(mkt === 'TW' ? '台股代號格式不正確（例：00935A、0050）' : '美股代號格式不正確（例：TQQQ、SOXL）'); return;
      }
      const cat = S.etfV3.catalog.categories.find(c => c.key === catKey);
      if (!cat) return;
      if (cat.etfs.find(e => e.code === code && (e.market || 'TW') === mkt)) { alert('該 ETF 已存在此分類'); return; }
      // 美股無 MoneyDJ 持股 delta，預設不進台股追蹤（enabled:false）
      cat.etfs.push({ code, name, market: mkt, enabled: mkt === 'TW' });
      const body = document.getElementById('e3-mgr-body');
      if (body) body.innerHTML = renderMgrBody();
      return;
    }
    if (act === 'save') {
      ev.preventDefault();
      ma.disabled = true; ma.textContent = '儲存中...';
      saveCatalog(S.etfV3.catalog).then(r => {
        ma.disabled = false;
        if (r?.ok) {
          ma.textContent = `✓ 已存 (${r.enabledCount} 檔)`;
          setFootMsg(`✓ Catalog 已存，${r.enabledCount} 檔啟用`, 'var(--green)');
          applyFilter();
          notifyDependents();
          setTimeout(() => { ma.textContent = '💾 只儲存'; }, 2000);
        } else {
          ma.textContent = '💾 只儲存';
        }
      });
      return;
    }
    if (act === 'save-run') {
      ev.preventDefault();
      ma.disabled = true; ma.textContent = '儲存中...';
      saveCatalog(S.etfV3.catalog).then(async r => {
        if (!r?.ok) { ma.disabled = false; ma.textContent = '💾 儲存並立即更新'; return; }
        ma.textContent = '▶ 啟動 tracker...';
        setFootMsg(`✓ Catalog 已存 (${r.enabledCount} 檔)，正在抓 MoneyDJ 持股...`, 'var(--gold)');
        try {
          const rr = await fetch(`${SERVER}/etf-tracker/run`, { method: 'POST' });
          if (!rr.ok) {
            const j = await rr.json().catch(() => ({ error: 'HTTP ' + rr.status }));
            alert('啟動 tracker 失敗：' + (j.error || rr.status));
            ma.disabled = false; ma.textContent = '💾 儲存並立即更新';
            return;
          }
        } catch (e) {
          alert('啟動失敗：' + e.message);
          ma.disabled = false; ma.textContent = '💾 儲存並立即更新';
          return;
        }
        // Poll status
        let attempts = 0;
        const maxAttempts = 150;
        const startTs = Date.now();
        const poll = async () => {
          attempts++;
          try {
            const sr = await fetch(`${SERVER}/etf-tracker/status`, { cache: 'no-store' });
            const st = await sr.json();
            const elapsed = Math.round((Date.now() - startTs) / 1000);
            if (st.running) {
              ma.textContent = `▶ 抓取中 ${elapsed}s...`;
              setFootMsg(`抓取中 ${elapsed} 秒（首次跑全部 ETF 可能需 30~60 秒）...`, 'var(--gold)');
              if (attempts < maxAttempts) return setTimeout(poll, 2000);
              setFootMsg('⚠ tracker 還在跑但等待超時', 'var(--red)');
              ma.disabled = false; ma.textContent = '💾 儲存並立即更新';
              return;
            }
            if (st.lastReturnCode === 0) {
              ma.textContent = `✓ 完成 (${st.lastDuration}s)`;
              setFootMsg(`✓ 抓取完成，耗時 ${st.lastDuration} 秒`, 'var(--green)');
              await fetchDelta();
              setTimeout(() => {
                closeMgrModal();
                if (typeof renderRpanel === 'function') renderRpanel();
              }, 1200);
            } else {
              ma.textContent = '⚠ 失敗';
              const tail = (st.lastOutput || '').split('\n').slice(-3).join('\n');
              setFootMsg(`⚠ tracker 失敗 (code ${st.lastReturnCode})：${tail}`, 'var(--red)');
              ma.disabled = false;
              setTimeout(() => { ma.textContent = '💾 儲存並立即更新'; }, 4000);
            }
          } catch (e) {
            console.warn('[etf-v3] poll error:', e);
            if (attempts < maxAttempts) return setTimeout(poll, 2000);
            setFootMsg('⚠ 輪詢失敗：' + e.message, 'var(--red)');
            ma.disabled = false; ma.textContent = '💾 儲存並立即更新';
          }
        };
        setTimeout(poll, 1500);
      });
    }
  });

  // ─── setTab hook (auto-refresh on tab open if stale) ────────
  (function hookSetTab() {
    if (typeof setTab !== 'function') return setTimeout(hookSetTab, 100);
    if (global._etfV3HookedSetTab) return;
    global._etfV3HookedSetTab = true;
    const orig = global.setTab;
    global.setTab = function (tab) {
      orig.apply(this, arguments);
      if (tab === 'etf') {
        const age = Date.now() - (S.etfV3.lastFetch || 0);
        if (age > 60_000 && !S.etfV3.loading) fetchDelta();
      }
    };
  })();

  // ─── Public v3 owner + narrow compatibility aliases ─────────
  global.renderEtfDelta            = renderEtfDelta;
  global.renderEtfHoldingsForStock = renderEtfHoldingsForStock;
  global.openEtfMgrModal           = openEtfMgrModal;
  // Also expose v3-prefixed names for direct calls
  global.renderEtfV3               = renderEtfDelta;
  global.renderEtfHoldingsV3       = renderEtfHoldingsForStock;
  global.etfV3FetchCatalog         = fetchCatalog;
  global.etfV3FetchDelta           = fetchDelta;
  global.updateEtfFlowIndV3        = updateEtfFlowInd;
  global.getEtfFlowForStock        = stockFlow;
  global.EtfFlow = Object.freeze({
    getStockFlow: stockFlow,
    changeDirection,
  });

  // Boot: load catalog immediately, delta will lazy-load on first ETF tab open
  fetchCatalog();

  console.log('[etf-v3] clean ETF module loaded (replaces v1 + v2 ETF code)');
})(window);

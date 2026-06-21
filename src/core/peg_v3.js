// ============================================================
// Stock Terminal v3.4 — PE / EPS / PEG Comparison Table
// ------------------------------------------------------------
// 抓 PLAN + WATCH 所有股票的 /keystats/<sym>.TW，列成比較表。
//
// PEG 計算：
//   PEG = PE / EPS_year_growth_%
//   來源：/keystats 只有 trailingPE + eps（TTM），沒有 forwardEPS
//   策略：使用者可在 plan_v3 的 outlook 欄填「預期成長 X%」字串，
//         此處 regex 抓出 X 來算 PEG；若沒填則只顯示 PE
//
// PE 顏色：<15 綠｜15~30 黃｜>30 紅 (粗略估值區間)
// PEG 顏色：<1 綠｜1~2 黃｜>2 紅
// ============================================================

(function (global) {
  'use strict';

  const SERVER = global.SERVER || 'http://localhost:18432';
  const CACHE_TTL = 60 * 60 * 1000;   // 1h client cache (server cache is also 1h)
  const _ksCache = {};   // sym → { data, ts }

  // ─── Fetch one stock's keystats ─────────────────────────────
  async function fetchKeystats(sym) {
    const cached = _ksCache[sym];
    if (cached && (Date.now() - cached.ts) < CACHE_TTL) return cached.data;
    try {
      const r = await fetch(`${SERVER}/keystats/${encodeURIComponent(sym)}`, { cache: 'no-store' });
      if (!r.ok) return { _error: 'HTTP ' + r.status };
      const data = await r.json();
      _ksCache[sym] = { data, ts: Date.now() };
      return data;
    } catch (e) {
      return { _error: e.message };
    }
  }

  // ─── Extract growth rate from outlook text ──────────────────
  // Matches "成長 X%" "年增 X%" "增 X%" "X% 成長" "EPS 成長 X%"
  function extractGrowthRate(text) {
    if (!text) return null;
    const m = text.match(/(?:成長|年增|增)\s*(\d+(?:\.\d+)?)\s*%/);
    if (m) return parseFloat(m[1]);
    const m2 = text.match(/(\d+(?:\.\d+)?)\s*%\s*(?:成長|年增)/);
    if (m2) return parseFloat(m2[1]);
    return null;
  }

  // ─── Collect target symbols from PLAN + WATCH ───────────────
  function collectSymbols() {
    const out = new Map();   // sym → { sym, mkt, source[], growth }
    if (S.plans) {
      for (const sym of Object.keys(S.plans)) {
        const p = S.plans[sym];
        out.set(sym, {
          sym, mkt: p.mkt || 'TW',
          source: ['plan'],
          growth: extractGrowthRate(p.outlook),
        });
      }
    }
    if (Array.isArray(S.wl)) {
      for (const w of S.wl) {
        const sym = w.t;
        const existing = out.get(sym);
        if (existing) existing.source.push('watch');
        else out.set(sym, { sym, mkt: w.m || 'TW', source: ['watch'], growth: null });
      }
    }
    return [...out.values()];
  }

  // ─── Convert local sym → Yahoo sym ──────────────────────────
  function yfsym(item) {
    if (item.mkt === 'TW') return item.sym + '.TW';
    return item.sym;
  }

  // ─── Fetch all in parallel ───────────────────────────────────
  async function fetchAll(items) {
    const promises = items.map(async (it) => {
      const k = await fetchKeystats(yfsym(it));
      // Retry with .TWO if TW failed
      if (it.mkt === 'TW' && (k._error || (k.trailingPE == null && k.eps == null))) {
        const k2 = await fetchKeystats(it.sym + '.TWO');
        if (!k2._error && (k2.trailingPE != null || k2.eps != null)) {
          return { ...it, ks: k2 };
        }
      }
      return { ...it, ks: k };
    });
    return Promise.all(promises);
  }

  // ─── Color helpers ───────────────────────────────────────────
  function peColor(pe) {
    if (pe == null || !Number.isFinite(pe)) return '#6B7280';
    if (pe < 15) return '#10B981';
    if (pe < 30) return '#FBBF24';
    return '#EF4444';
  }
  function pegColor(peg) {
    if (peg == null || !Number.isFinite(peg)) return '#6B7280';
    if (peg < 1)  return '#10B981';
    if (peg < 2)  return '#FBBF24';
    return '#EF4444';
  }
  function fmt(v, dec = 2) {
    if (v == null || !Number.isFinite(v)) return '—';
    return (+v).toFixed(dec);
  }
  function fmtCap(v) {
    if (v == null || !Number.isFinite(v)) return '—';
    if (v >= 1e12) return (v/1e12).toFixed(1) + 'T';
    if (v >= 1e9)  return (v/1e9).toFixed(1) + 'B';
    if (v >= 1e6)  return (v/1e6).toFixed(1) + 'M';
    return v.toFixed(0);
  }

  // ─── Render initial skeleton (data fills in async) ──────────
  function renderPegSection() {
    const items = collectSymbols();
    if (items.length === 0) {
      return '';
    }
    return `
      <div class="stat-sect" style="margin-top:12px;display:flex;justify-content:space-between;align-items:center;">
        <span>📊 基本面比較 (${items.length} 檔)</span>
        <button id="peg-refresh" style="background:#1F2937;border:1px solid #374151;color:#9CA3AF;font-size:10px;padding:2px 8px;border-radius:3px;cursor:pointer;">↻ 重抓</button>
      </div>
      <div id="peg-table-wrap" style="margin:4px 6px 10px;">
        <div style="font-size:10px;color:#9CA3AF;padding:6px;text-align:center;">載入中...</div>
      </div>
      <div style="font-size:9px;color:#4B5563;padding:0 8px 8px;line-height:1.5;">
        PE 區間：<span style="color:#10B981;">&lt;15 便宜</span> · <span style="color:#FBBF24;">15~30 中等</span> · <span style="color:#EF4444;">&gt;30 偏貴</span><br>
        PEG 區間：<span style="color:#10B981;">&lt;1 划算</span> · <span style="color:#FBBF24;">1~2 合理</span> · <span style="color:#EF4444;">&gt;2 偏貴</span>（在計畫展望填「成長 X%」自動算）
      </div>`;
  }

  // ─── Render filled table from data ──────────────────────────
  function renderTable(rows) {
    if (rows.length === 0) return '<div style="text-align:center;padding:16px;color:#6B7280;font-size:11px;">沒有資料</div>';

    // Compute effective growth for each row (combine multiple sources)
    rows.forEach(r => { r._effectiveGrowth = effectiveGrowth(r); r._peg = computePeg(r); });

    // Sort: have-data first, then by PEG (lower = better)
    const sorted = [...rows].sort((a, b) => {
      const hasA = a.ks?.trailingPE != null || a.ks?.eps != null;
      const hasB = b.ks?.trailingPE != null || b.ks?.eps != null;
      if (hasA !== hasB) return hasA ? -1 : 1;
      const ap = a._peg, bp = b._peg;
      if (ap != null && bp != null) return ap - bp;
      if (ap != null) return -1;
      if (bp != null) return 1;
      const apE = a.ks?.trailingPE, bpE = b.ks?.trailingPE;
      if (apE != null && bpE != null) return apE - bpE;
      return 0;
    });

    const header = `
      <thead style="background:#0F172A;">
        <tr style="font-size:10px;color:#9CA3AF;text-align:right;">
          <th style="text-align:left;padding:4px 6px;">代號</th>
          <th style="padding:4px 4px;">PE</th>
          <th style="padding:4px 4px;">EPS</th>
          <th style="padding:4px 4px;">成長%</th>
          <th style="padding:4px 4px;">PEG</th>
          <th style="padding:4px 4px;">市值</th>
        </tr>
      </thead>`;

    const body = sorted.map(r => {
      const pe = r.ks?.trailingPE;
      const eps = r.ks?.eps;
      const peg = r._peg;
      const growth = r._effectiveGrowth;
      const hasAnyData = (pe != null || eps != null || r.ks?.marketCap != null);
      const nameText = r.ks?.shortName ? escapeHtml(r.ks.shortName.slice(0, 14)) : '';
      const errorHint = (r.ks?._error && !hasAnyData) ? '<br><span style="color:#7F1D1D;font-size:9px;">無資料</span>' : '';
      const sourceTag = sourceBadge(r.ks);
      return `
        <tr style="font-size:11px;text-align:right;border-top:1px solid #1F2937;${!hasAnyData ? 'opacity:0.45;' : ''}">
          <td style="text-align:left;padding:4px 6px;">
            <span style="cursor:pointer;color:#E5E7EB;font-weight:600;" data-peg-goto="${r.sym}" data-peg-mkt="${r.mkt}">${r.sym}</span>
            ${r.source.includes('plan') ? '<span style="color:#FBBF24;font-size:9px;margin-left:3px;">📋</span>' : ''}
            ${sourceTag}
            ${nameText ? `<br><span style="color:#6B7280;font-size:9px;">${nameText}</span>` : ''}
            ${errorHint}
          </td>
          <td style="padding:4px 4px;color:${peColor(pe)};font-weight:600;">${fmt(pe, 1)}</td>
          <td style="padding:4px 4px;color:#D1D5DB;">${fmt(eps, 2)}</td>
          <td style="padding:4px 4px;color:#9CA3AF;">${growth != null ? growth.toFixed(0) + '%' : '—'}</td>
          <td style="padding:4px 4px;color:${pegColor(peg)};font-weight:600;">${fmt(peg, 2)}</td>
          <td style="padding:4px 4px;color:#9CA3AF;">${fmtCap(r.ks?.marketCap)}</td>
        </tr>`;
    }).join('');

    return `<table style="width:100%;border-collapse:collapse;background:#0F172A;border:1px solid #374151;border-radius:4px;">${header}<tbody>${body}</tbody></table>`;
  }

  // 來源徽章：📡 = quoteSummary v10 (最準); 📄 = HTML scrape (備援)
  function sourceBadge(ks) {
    if (!ks) return '';
    if (ks._source?.includes('v10')) return '<span title="Yahoo v10" style="color:#10B981;font-size:9px;margin-left:3px;">📡</span>';
    if (ks._source?.includes('html')) return '<span title="HTML scrape" style="color:#F59E0B;font-size:9px;margin-left:3px;">📄</span>';
    return '';
  }

  // 有效成長率：優先序
  //   1. plan.outlook 文字明確寫 X% (使用者寫的)
  //   2. Yahoo earningsQuarterlyGrowth (季 EPS 年增)
  //   3. Yahoo revenueGrowth (營收成長)
  function effectiveGrowth(r) {
    if (r.growth != null && Number.isFinite(r.growth)) return r.growth;
    const k = r.ks;
    if (!k) return null;
    if (k.earningsQuarterlyGrowth != null && Number.isFinite(k.earningsQuarterlyGrowth)) return k.earningsQuarterlyGrowth;
    if (k.revenueGrowth != null && Number.isFinite(k.revenueGrowth)) return k.revenueGrowth;
    return null;
  }

  // PEG 計算優先序：
  //   1. Yahoo pegRatio 直接給 (5-yr expected EPS growth based)
  //   2. PE / effectiveGrowth (自算)
  function computePeg(r) {
    const k = r.ks;
    if (k?.pegRatio != null && Number.isFinite(k.pegRatio) && k.pegRatio > 0) return k.pegRatio;
    const pe = k?.trailingPE;
    const g = effectiveGrowth(r);
    if (pe == null || !Number.isFinite(pe) || g == null || !Number.isFinite(g) || g <= 0) return null;
    return pe / g;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // ─── Fetch + render (called after DOM is inserted) ──────────
  async function fillTable(force = false) {
    const wrap = document.getElementById('peg-table-wrap');
    if (!wrap) return;
    if (force) for (const k of Object.keys(_ksCache)) delete _ksCache[k];

    const items = collectSymbols();
    if (items.length === 0) {
      wrap.innerHTML = '<div style="text-align:center;padding:16px;color:#6B7280;font-size:11px;">沒有 PLAN / WATCH 股票</div>';
      return;
    }
    const rows = await fetchAll(items);
    wrap.innerHTML = renderTable(rows);
    // bind goto
    wrap.querySelectorAll('[data-peg-goto]').forEach(el => {
      el.onclick = () => {
        const s = el.dataset.pegGoto;
        const m = el.dataset.pegMkt || 'TW';
        if (typeof loadSym === 'function') {
          S.mkt = m;
          loadSym(s);
        }
      };
    });
  }

  function attachPegSection() {
    const refresh = document.getElementById('peg-refresh');
    if (refresh) refresh.onclick = () => fillTable(true);
    // Auto-fill on attach
    setTimeout(() => fillTable(false), 50);
  }

  // ─── Expose ────────────────────────────────────────────────
  global.renderPegSection = renderPegSection;
  global.attachPegSection = attachPegSection;
  global.PegV3 = {
    fetchKeystats,
    collectSymbols,
    fillTable,
    extractGrowthRate,
    _cache: _ksCache,
  };

  console.log('[v3-peg] module loaded — exposes renderPegSection/attachPegSection/PegV3');

})(typeof window !== 'undefined' ? window : globalThis);

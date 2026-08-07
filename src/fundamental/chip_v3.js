// ============================================================
// Stock Terminal v3.0 — 法人籌碼面板 (Institutional Chip Panel)
// ------------------------------------------------------------
// 在 STATS 分頁底部加「籌碼」section，顯示：
//   • 三大法人買賣超（外資 / 投信 / 自營商）
//   • 融資餘額 / 融券餘額（券資比）
// 資料源：TWSE T86 / MI_MARGN，每日盤後更新
// ============================================================

const SERVER_C = window.SERVER || `http://localhost:18432`;
const _chipCache = {};   // sym → result

async function fetchChip(sym, mkt) {
  if (!sym || mkt !== 'TW') return null;
  // 指數／總經／合成序列：後端也會短路，前端先擋避免無謂請求
  if (sym[0] === '^' || (sym.startsWith('__') && sym.endsWith('__'))) return null;
  if (_chipCache[sym]) return _chipCache[sym];
  try {
    const r = await fetch(`${SERVER_C}/chip/${sym}`, {cache:'no-store'});
    if (!r.ok) return null;
    const data = await r.json();
    _chipCache[sym] = data;
    return data;
  } catch (e) { console.warn('[chip] fetch error:', e); return null; }
}

function fmtShares(n) {
  if (n == null) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e7) return (n/1e7).toFixed(2) + ' 千萬股';
  if (abs >= 1e4) return (n/1e4).toFixed(1) + ' 萬股';
  return Math.round(n).toLocaleString() + ' 股';
}
function colorN(n) { return window.Colors ? Colors.gain(n) : (n > 0 ? 'var(--green)' : n < 0 ? 'var(--red)' : 'var(--tlo)'); }
function signN(n)  { return (n != null && n >= 0 ? '+' : '') + (n == null ? '—' : fmtShares(n)); }

function renderChipSection(chip) {
  if (!chip || (!chip.inst && !chip.margin && !(chip.holders && chip.holders.ok))) {
    return '<div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px;line-height:1.7">無籌碼資料<br><span style="font-size:9px;color:var(--tf)">TWSE 資料盤後 17:30 後更新；ETF / 興櫃股無資料</span></div>';
  }
  let h = '';
  if (chip.inst) {
    const tot = (chip.inst.foreign||0) + (chip.inst.trust||0) + (chip.inst.dealer||0);
    const tc  = colorN(tot);
    h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">三大法人合計</span><span class="stat-v" style="color:${tc}">${signN(tot)}</span></div>`;
    h += `<div class="stat-row"><span class="stat-k">外資</span><span class="stat-v" style="color:${colorN(chip.inst.foreign)}">${signN(chip.inst.foreign)}</span></div>`;
    h += `<div class="stat-row"><span class="stat-k">投信</span><span class="stat-v" style="color:${colorN(chip.inst.trust)}">${signN(chip.inst.trust)}</span></div>`;
    h += `<div class="stat-row"><span class="stat-k">自營商</span><span class="stat-v" style="color:${colorN(chip.inst.dealer)}">${signN(chip.inst.dealer)}</span></div>`;
  }
  if (chip.margin) {
    h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px"><span class="stat-k">融資餘額</span><span class="stat-v">${chip.margin.marginBalance != null ? Math.round(chip.margin.marginBalance/1000).toLocaleString() + ' 張' : '—'}</span></div>`;
    h += `<div class="stat-row"><span class="stat-k">融券餘額</span><span class="stat-v">${chip.margin.shortBalance != null ? Math.round(chip.margin.shortBalance/1000).toLocaleString() + ' 張' : '—'}</span></div>`;
    if (chip.margin.marginBalance && chip.margin.shortBalance != null) {
      const ratio = chip.margin.shortBalance / chip.margin.marginBalance * 100;
      h += `<div class="stat-row"><span class="stat-k">券資比</span><span class="stat-v" style="color:${ratio > 30 ? 'var(--red)' : ratio > 10 ? 'var(--orange)' : 'var(--green)'}">${ratio.toFixed(1)}%</span></div>`;
    }
  }
  // v3.8: 借券賣出
  if (chip.shortLend && (chip.shortLend.balance != null || chip.shortLend.sellVolume != null)) {
    h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px"><span class="stat-k">借券賣出餘額</span><span class="stat-v" style="color:var(--red)">${chip.shortLend.balance != null ? Math.round(chip.shortLend.balance/1000).toLocaleString() + ' 張' : '—'}</span></div>`;
    if (chip.shortLend.sellVolume != null)
      h += `<div class="stat-row"><span class="stat-k">當日借券賣出</span><span class="stat-v">${Math.round(chip.shortLend.sellVolume/1000).toLocaleString()} 張</span></div>`;
  }
  // v3.8: 當沖比（無比率時改顯示當沖量，避免 TWTB4U 無 per-stock % 時整列消失）
  if (chip.dayTrade && (chip.dayTrade.ratioPct != null || chip.dayTrade.volume != null)) {
    const dr = chip.dayTrade.ratioPct;
    if (dr != null) {
      const dc = dr > 30 ? 'var(--red)' : dr > 15 ? 'var(--orange)' : 'var(--tlo)';
      h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px"><span class="stat-k">當沖比${dr>30?' 🚩':''}</span><span class="stat-v" style="color:${dc}">${dr.toFixed(1)}%</span></div>`;
    } else if (chip.dayTrade.volume != null) {
      h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px"><span class="stat-k">當沖量</span><span class="stat-v">${Math.round(chip.dayTrade.volume/1000).toLocaleString()} 張</span></div>`;
    }
  }
  // v3.8: 法人連續買賣超天數
  if (chip.streak && (chip.streak.foreign || chip.streak.trust || chip.streak.dealer)) {
    const badge = (n, who) => {
      if (!n) return '';
      const buy = n > 0;
      return `<span style="display:inline-block;margin:2px 4px 0 0;padding:1px 6px;border-radius:8px;font-size:9px;background:${buy?'rgba(239,68,68,.18)':'rgba(34,197,94,.18)'};color:${buy?'var(--red)':'var(--green)'}">${who}連${buy?'買':'賣'}${Math.abs(n)}日</span>`;
    };
    h += `<div style="padding:6px 12px 0">${badge(chip.streak.foreign,'外資')}${badge(chip.streak.trust,'投信')}${badge(chip.streak.dealer,'自營')}</div>`;
  }
  // 籌碼集中度（TDCC 週）
  const hold = chip.holders;
  if (hold && hold.risk) {
    const r = hold.risk;
    const last = hold.last || {};
    const sc = r.score;
    const col = sc == null ? 'var(--tlo)' : sc >= 70 ? '#f87171' : sc >= 55 ? '#fb923c' : sc >= 45 ? '#94a3b8' : '#4ade80';
    const chartId = hold.chartId || (`__HOLDERS_${(S && S.sym) || ''}__`);
    h += `<div class="stat-row" style="border-top:1px solid var(--border);padding-top:8px;font-weight:700"><span class="stat-k">籌碼集中度</span>` +
      `<span class="stat-v" style="color:${col}">${sc != null ? sc + ' · ' + (r.label || '') : '—'}</span></div>`;
    if (last.holders != null)
      h += `<div class="stat-row"><span class="stat-k">總股東人數</span><span class="stat-v">${Number(last.holders).toLocaleString()}</span></div>`;
    if (last.major_pct != null)
      h += `<div class="stat-row"><span class="stat-k">大股東持有率</span><span class="stat-v">${Number(last.major_pct).toFixed(2)}%（≥400張）</span></div>`;
    if (r.plainSummary)
      h += `<div style="padding:6px 12px;color:var(--text);font-family:monospace;font-size:10px;line-height:1.55">${r.plainSummary}</div>`;
    h += `<div style="padding:4px 12px 8px">` +
      `<button type="button" data-open-holders="${chartId}" style="cursor:pointer;padding:4px 10px;border-radius:2px;font:10px JetBrains Mono,monospace;` +
      `border:1px solid rgba(71,85,105,.7);background:rgba(15,20,30,.85);color:#94a3b8">主圖看集中度</button></div>`;
  }
  h += `<div style="padding:6px 12px 0;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.5">資料：TWSE 三大法人 + 信用 + 借券 + 當沖` +
    (hold && hold.ok ? ' + TDCC 集保週報' : '') +
    `（${chip.date.slice(0,4)}/${chip.date.slice(4,6)}/${chip.date.slice(6,8)}）</div>`;
  return h;
}

// Patch renderStats to append chip section
(function patchStats() {
  if (typeof renderStats !== 'function') return setTimeout(patchStats, 100);
  if (window._origRenderStats) return;
  window._origRenderStats = window.renderStats;
  window.renderStats = function () {
    let h = window._origRenderStats.apply(this, arguments);
    if (!S.sym || S.mkt !== 'TW') return h;
    // Async fetch and inject when ready
    fetchChip(S.sym, S.mkt).then(chip => {
      const stats = document.getElementById('rpanel');
      if (!stats || S.tab !== 'stats') return;
      const ex = document.getElementById('chip-sect');
      const newHtml = `<div id="chip-sect"><div class="stat-sect">籌碼面 · ${S.sym}</div>${renderChipSection(chip)}</div>`;
      if (ex) ex.outerHTML = newHtml;
      else stats.insertAdjacentHTML('beforeend', newHtml);
      const btn = document.querySelector('#chip-sect [data-open-holders]');
      if (btn && !btn._bound) {
        btn._bound = true;
        btn.addEventListener('click', function () {
          const id = btn.getAttribute('data-open-holders');
          if (!id) return;
          if (window.MarketChart && typeof MarketChart.load === 'function') {
            MarketChart.load(id);
          } else if (typeof loadSym === 'function') {
            loadSym(id, 'TW');
          }
        });
      }
    });
    return h + '<div id="chip-sect"><div class="stat-sect">籌碼面 · '+S.sym+'</div><div style="padding:14px 12px;text-align:center;color:var(--tlo);font-family:monospace;font-size:10px">載入籌碼中...</div></div>';
  };
})();

// Invalidate cache on sym change so we re-fetch
window.addEventListener('symLoaded', () => {
  // Keep cache per-sym (today's data won't change), but re-render
  if (S.tab === 'stats' && typeof renderRpanel === 'function') renderRpanel();
});

window.fetchChip = fetchChip;

// ============================================================
// Stock Terminal v3.8 — STATS 強化 (4 合 1)
// ------------------------------------------------------------
// 1. 技術 x 基本面 雙軸總結卡 (STATS 頂端)
// 2. 量價數值面板 (POC / 主力成本區 / 現價相對位置)
// 3. 右側面板可收合 (40% <-> 0 全螢幕線型)
// 4. 分頁記憶 (切股票後保留上次看的分頁)
// 須在 fundamental_v3.js / volume_profile_v3.js 之後載入。
// ============================================================
(function () {
  'use strict';

  // ---- 樣式 ------------------------------------------------
  function style() {
    if (document.getElementById('enh3-style')) return;
    const s = document.createElement('style'); s.id = 'enh3-style';
    s.textContent = `
    .dual-card{display:flex;gap:8px;padding:10px 12px;border-bottom:1px solid var(--border)}
    .dual-half{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px;text-align:center}
    .dual-half .lbl{font-size:9px;color:var(--tlo);letter-spacing:.5px}
    .dual-half .score{font-size:26px;font-weight:800;line-height:1.1;font-family:'JetBrains Mono',monospace}
    .dual-half .tag{font-size:9px;font-weight:700}
    .vp-panel .stat-k{color:var(--tlo)}
    #right-collapse{position:absolute;top:50%;transform:translateY(-50%);z-index:60;
      width:18px;height:54px;background:var(--bg2);border:1px solid var(--border);border-right:none;
      border-radius:6px 0 0 6px;cursor:pointer;color:var(--tlo);font-size:11px;
      display:flex;align-items:center;justify-content:center;transition:right .15s}
    #right-collapse:hover{color:var(--thi)}
    body.right-collapsed #right{flex:0 0 0!important;width:0!important;overflow:hidden;border:none}
    `;
    document.head.appendChild(s);
  }

  // ---- 技術面分數 0~100 ------------------------------------
  function techScore() {
    const ind = window.S && S.ind;
    if (!ind) return null;
    const cur = (S.data && S.data.candles && S.data.candles.length)
      ? S.data.candles[S.data.candles.length - 1].close : null;
    let score = 50, parts = 0;
    const add = v => { score += v; parts++; };
    if (ind.rsi14 != null) add(Math.max(-20, Math.min(20, (ind.rsi14 - 50) * 0.8)));
    if (ind.macd != null && ind.macdSig != null) add(ind.macd > ind.macdSig ? 12 : -12);
    if (ind.K != null && ind.D != null) add(ind.K > ind.D ? 8 : -8);
    if (cur != null && ind.sma20 != null) add(cur > ind.sma20 ? 10 : -10);
    if (ind.sma20 != null && ind.sma60 != null) add(ind.sma20 > ind.sma60 ? 10 : -10);
    if (!parts) return null;
    return Math.max(0, Math.min(100, Math.round(score)));
  }
  const scoreCol = s => s == null ? 'var(--tlo)' : s >= 65 ? 'var(--green)' : s >= 45 ? 'var(--orange)' : 'var(--red)';
  const techTag = s => s == null ? '—' : s >= 65 ? '🟢 偏多' : s >= 45 ? '⚖️ 中性' : '🔴 偏空';
  const fundTag = s => s == null ? '—' : s >= 70 ? '🟢 體質佳' : s >= 50 ? '🟡 中性' : '🔴 偏弱';

  function dualCardHtml(fundScore) {
    const t = techScore();
    return `<div class="dual-card">
      <div class="dual-half"><div class="lbl">技術面</div>
        <div class="score" style="color:${scoreCol(t)}">${t == null ? '—' : t}</div>
        <div class="tag" style="color:${scoreCol(t)}">${techTag(t)}</div></div>
      <div class="dual-half"><div class="lbl">基本面</div>
        <div class="score" style="color:${scoreCol(fundScore)}">${fundScore == null ? '—' : fundScore}</div>
        <div class="tag" style="color:${scoreCol(fundScore)}">${fundTag(fundScore)}</div></div>
    </div>`;
  }

  // ---- 量價數值面板 ----------------------------------------
  function vpPanelHtml() {
    const vp = window.VP && VP.enabled && VP.lastVP;
    if (!vp) return '';
    const cur = (S.data && S.data.candles && S.data.candles.length)
      ? S.data.candles[S.data.candles.length - 1].close : null;
    const pos = cur == null ? '—'
      : cur > vp.vah ? '<span style="color:var(--green)">主力成本之上 (偏多)</span>'
        : cur < vp.val ? '<span style="color:var(--red)">主力成本之下 (偏空)</span>'
          : '<span style="color:var(--orange)">主力成本區內 (盤整)</span>';
    const modeLbl = { avg: '量價均衡', amt: '金額', vol: '成交量' }[VP.mode] || '';
    return `<div class="vp-panel"><div class="stat-sect">量價分布 · ${modeLbl}</div>
      <div class="stat-row"><span class="stat-k">POC 主力成本</span><span class="stat-v" style="color:#A78BFA">${vp.pocPrice.toFixed(2)}</span></div>
      <div class="stat-row"><span class="stat-k">成本區上緣 VAH</span><span class="stat-v">${vp.vah.toFixed(2)}</span></div>
      <div class="stat-row"><span class="stat-k">成本區下緣 VAL</span><span class="stat-v">${vp.val.toFixed(2)}</span></div>
      <div class="stat-row"><span class="stat-k">現價位置</span><span class="stat-v">${pos}</span></div></div>`;
  }

  // ---- patch renderStats：頂端插雙軸卡 + 量價面板 ----------
  (function patch() {
    if (typeof renderStats !== 'function') return setTimeout(patch, 120);
    if (window._enhStatsPatched) return;
    window._enhStatsPatched = true;
    const orig = window.renderStats;
    window.renderStats = function () {
      const base = orig.apply(this, arguments);
      const head = dualCardHtml(null) + vpPanelHtml();
      // 非同步補基本面分數
      if (window.fetchFund && S.sym && S.mkt === 'TW') {
        fetchFund(S.sym, S.mkt).then(f => {
          if (S.tab !== 'stats') return;
          const card = document.querySelector('#rpanel .dual-card');
          if (card) card.outerHTML = dualCardHtml(f && f.score != null ? f.score : null);
        });
      }
      return head + base;
    };
  })();

  // ---- 右側收合按鈕 ----------------------------------------
  function injectCollapse() {
    const right = document.getElementById('right');
    if (!right) return setTimeout(injectCollapse, 200);
    if (document.getElementById('right-collapse')) return;
    const btn = document.createElement('div');
    btn.id = 'right-collapse';
    btn.title = '收合 / 展開功能分析區';
    btn.textContent = '⟩';
    document.body.appendChild(btn);
    const place = () => {
      const collapsed = document.body.classList.contains('right-collapsed');
      btn.style.right = collapsed ? '0px' : (right.getBoundingClientRect().width + 'px');
      btn.textContent = collapsed ? '⟨' : '⟩';
    };
    btn.onclick = () => {
      document.body.classList.toggle('right-collapsed');
      try { localStorage.setItem('stockTerminal.rightCollapsed', document.body.classList.contains('right-collapsed') ? '1' : '0'); } catch {}
      setTimeout(() => { place(); try { window.dispatchEvent(new Event('resize')); } catch {}
        if (window.VP && VP.enabled && window.drawVolumeProfile) drawVolumeProfile(); }, 180);
    };
    if (localStorage.getItem('stockTerminal.rightCollapsed') === '1')
      document.body.classList.add('right-collapsed');
    place();
    window.addEventListener('resize', place);
  }

  // ---- 分頁記憶 --------------------------------------------
  (function tabMemory() {
    if (typeof setTab !== 'function') return setTimeout(tabMemory, 150);
    if (window._enhTabPatched) return;
    window._enhTabPatched = true;
    const orig = window.setTab;
    window.setTab = function (tab) {
      try { localStorage.setItem('stockTerminal.lastTab', tab); } catch {}
      return orig.apply(this, arguments);
    };
    const saved = localStorage.getItem('stockTerminal.lastTab');
    if (saved && saved !== 'stats') setTimeout(() => { try { setTab(saved); } catch {} }, 900);
  })();

  style();
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', () => { style(); injectCollapse(); });
  else injectCollapse();
})();

// ============================================================
// Stock Terminal v3.8 — STATS 強化 (4 合 1)
// ------------------------------------------------------------
// 1. 基本面分數卡 (STATS 頂端；技術面燈號統一在「體檢」分頁，這裡只放入口)
// 2. 量價數值面板 (POC / 主力成本區 / 現價相對位置)
// 3. 右側面板可收合 (40% <-> 0 全螢幕線型)
// 4. 分頁記憶 (切股票後保留上次看的分頁)
// 須在 fundamental_v3.js / volume_profile_v3.js 之後載入。
//
// v3.8.5 (2026-07-23): 美股基本面評分（Yahoo 成長+三率，與台股同一 _fundamental_score）
//   雙軸卡／STATS 基本面不再鎖 TW；tag tech·385。
// v3.8.7 (2026-07-23): 台股大盤體質評分（^TWII/^TWOII/融資維持）；合成序列略過 canon yf。
// v3.8.9: 移除技術面分數（與「體檢」趨勢／動能燈號重疊、口徑不同易矛盾），改為體檢入口。
// ============================================================
(function () {
  'use strict';
  const ENH_VER = '389';  // 分數卡版本戳（data-enh-ver，確認不是瀏覽器舊快取）
  try { console.info('[enhance] stats score card ·' + ENH_VER); } catch (_) {}

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
    .dual-link{cursor:pointer;font:inherit;color:var(--tlo)}
    .dual-link:hover{border-color:var(--gold-m);color:var(--thi)}
    .dual-link-ico{font-size:24px;line-height:58px;margin:1px 0 3px}
    .dual-link .tag{color:var(--gold)}
    .vp-panel .stat-k{color:var(--tlo)}
    /* position:fixed — 不受 ST5 shell 包一層 #shell-main 影響；z-index 高於 topbar/navrail */
    #right-collapse{position:fixed;top:50%;transform:translateY(-50%);z-index:200;
      width:20px;height:64px;background:var(--bg2);border:1px solid var(--border);
      border-radius:8px 0 0 8px;cursor:pointer;color:var(--tlo);font-size:14px;font-weight:700;
      display:flex;align-items:center;justify-content:center;transition:right .15s,background .15s,color .15s,box-shadow .15s;
      box-shadow:-2px 0 8px rgba(0,0,0,.35);user-select:none;-webkit-user-select:none;
      padding:0;line-height:1;font-family:'JetBrains Mono',monospace}
    #right-collapse:hover{color:var(--thi);background:var(--bg3);border-color:var(--bhi)}
    #right-collapse.chart-hidden{display:none!important}
    /* 收合後按鈕貼右緣：加寬＋金色邊，避免「找不到展開鈕 → 以為壞掉」 */
    body.right-collapsed #right-collapse{
      width:28px;height:72px;right:0!important;color:var(--gold);
      background:var(--gold-s);border-color:var(--gold-m);
      box-shadow:-3px 0 14px rgba(245,197,24,.28)}
    body.right-collapsed #right-collapse:hover{background:var(--gold-m);color:var(--thi)}
    body.right-collapsed #right{
      flex:0 0 0!important;width:0!important;min-width:0!important;max-width:0!important;
      overflow:hidden!important;border:none!important;padding:0!important;opacity:0!important;
      pointer-events:none!important}
    `;
    document.head.appendChild(s);
  }

  const scoreCol = s => window.Colors ? Colors.quality(s, 65, 45) : (s == null ? 'var(--tlo)' : s >= 65 ? 'var(--red)' : s >= 45 ? 'var(--orange)' : 'var(--green)');
  const fundTag = (s, kind) => {
    if (s == null) return '—';
    if (kind === 'market') return s >= 70 ? '🟢 偏熱／偏強' : s >= 50 ? '🟡 中性' : '🔴 偏弱／偏冷';
    return s >= 70 ? '🟢 體質佳' : s >= 50 ? '🟡 中性' : '🔴 偏弱';
  };

  // 技術面分數已移除：趨勢／動能燈號與訊號歷史勝率統一看「體檢」分頁（同一套 Wilder 指標），
  // 這裡只留基本面／大盤體質分數，另一格改成前往體檢的入口，避免兩個技術面結論互相矛盾。
  function dualCardHtml(fundScore, fundPayload) {
    const isMarket = fundPayload && fundPayload.kind === 'market';
    const fundLbl = isMarket ? '大盤體質' : '基本面';
    const fundColor = scoreCol(fundScore);
    return `<div class="dual-card" data-enh-ver="${ENH_VER}">
      <div class="dual-half" data-score-kind="fundamental" style="--score-color:${fundColor}"><div class="lbl">${fundLbl}</div>
        <div class="score-ring" style="--score:${fundScore == null ? 0 : fundScore};--score-color:${fundColor}"><div class="score" style="color:${fundColor}">${fundScore == null ? '—' : fundScore}</div></div>
        <div class="tag" style="color:${fundColor}">${fundTag(fundScore, isMarket ? 'market' : null)}</div></div>
      <button type="button" class="dual-half dual-link" data-score-kind="health" onclick="setTab('health')" title="技術面燈號（趨勢／動能／量能）與訊號歷史勝率在「體檢」分頁">
        <div class="lbl">技術面</div><div class="dual-link-ico">🩺</div>
        <div class="tag">看「體檢」燈號 ›</div></button>
    </div>`;
  }

  // ---- 量價數值面板 ----------------------------------------
  function vpPanelHtml() {
    if (!window.VP || !VP.enabled) return '';
    const candles = (S.data && S.data.candles) || [];
    if (!candles.length) return '';
    // 重要：用「目前股票的 candles」即時重算，不可讀全域 VP.lastVP
    // （切股票時 STATS 會比圖表量價重繪先跑，lastVP 還是上一檔的殘值 → 數值對不到股票）
    const vp = (typeof window.computeVolumeProfile === 'function')
      ? window.computeVolumeProfile(candles) : VP.lastVP;
    if (!vp) return '';
    const cur = candles[candles.length - 1].close;
    const pos = cur == null ? '—'
      : cur > vp.vah ? '<span class="vp-state above">主力成本之上 (偏多)</span>'
        : cur < vp.val ? '<span class="vp-state below">主力成本之下 (偏空)</span>'
          : '<span class="vp-state inside">主力成本區內 (盤整)</span>';
    const modeLbl = { avg: '量價均衡', amt: '只看價', vol: '只看量' }[VP.mode] || '';
    return `<div class="vp-panel"><div class="stat-sect">量價分布 · ${modeLbl}</div>
      <div class="stat-row vp-poc"><span class="stat-k">POC 主力成本</span><span class="stat-v" style="color:#A78BFA">${vp.pocPrice.toFixed(2)}</span></div>
      <div class="stat-row vp-vah"><span class="stat-k">成本區上緣 VAH</span><span class="stat-v">${vp.vah.toFixed(2)}</span></div>
      <div class="stat-row vp-val"><span class="stat-k">成本區下緣 VAL</span><span class="stat-v">${vp.val.toFixed(2)}</span></div>
      <div class="stat-row vp-position"><span class="stat-k">現價位置</span><span class="stat-v">${pos}</span></div></div>`;
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
      if (window.fetchFund && S.sym) {
        fetchFund(S.sym, S.mkt).then(f => {
          if (S.tab !== 'stats') return;
          const card = document.querySelector('#rpanel .dual-card');
          if (card) card.outerHTML = dualCardHtml(f && f.score != null ? f.score : null, f);
        });
      }
      return head + base;
    };
  })();

  // ---- 右側收合按鈕 ----------------------------------------
  // ST5 shell 會把 #body 包進 #shell-main；按鈕改 fixed 掛在 viewport，
  // 並在 shell:route / resize 後重算位置。收合態加寬金色邊，避免找不到展開鈕。
  function injectCollapse() {
    const right = document.getElementById('right');
    if (!right) return setTimeout(injectCollapse, 200);
    if (document.getElementById('right-collapse')) return;

    const btn = document.createElement('button');
    btn.id = 'right-collapse';
    btn.type = 'button';
    btn.title = '收合 / 展開功能分析區（快捷鍵 ]）';
    btn.setAttribute('aria-label', '收合 / 展開功能分析區');
    btn.textContent = '⟩';
    document.body.appendChild(btn);

    function onChartRoute() {
      try {
        if (window.ShellV5 && typeof window.ShellV5.route === 'function') {
          return window.ShellV5.route() === 'chart';
        }
      } catch (_) {}
      const body = document.getElementById('body');
      return !(body && body.classList.contains('shell-hidden'));
    }

    function place() {
      const chart = onChartRoute();
      btn.classList.toggle('chart-hidden', !chart);
      if (!chart) return;
      const collapsed = document.body.classList.contains('right-collapsed');
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      btn.textContent = collapsed ? '⟨' : '⟩';
      btn.title = (collapsed ? '展開功能分析區' : '收合功能分析區') + '（快捷鍵 ]）';
      if (collapsed) {
        btn.style.right = '0px';
        return;
      }
      // #right 尚未 layout（寬度 0）時先貼右緣，下一幀 / resize 再對齊分隔線
      const w = right.getBoundingClientRect().width;
      btn.style.right = (w > 8 ? w : 0) + 'px';
    }

    function afterToggle() {
      place();
      try { window.dispatchEvent(new Event('resize')); } catch (_) {}
      if (window.VP && VP.enabled && window.drawVolumeProfile) {
        try { drawVolumeProfile(); } catch (_) {}
      }
    }

    function toggle() {
      if (!onChartRoute()) return;
      document.body.classList.toggle('right-collapsed');
      const collapsed = document.body.classList.contains('right-collapsed');
      try { localStorage.setItem('stockTerminal.rightCollapsed', collapsed ? '1' : '0'); } catch (_) {}
      // 雙 rAF：等 flex 收合／展開完成再量寬
      requestAnimationFrame(function () {
        requestAnimationFrame(function () { afterToggle(); });
      });
      setTimeout(afterToggle, 200);
    }

    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggle();
    });

    if (localStorage.getItem('stockTerminal.rightCollapsed') === '1') {
      document.body.classList.add('right-collapsed');
    }

    place();
    window.addEventListener('resize', place);
    window.addEventListener('shell:route', function () {
      setTimeout(place, 40);
    });
    // shell_v5 較晚 boot：延遲再對齊一次，避免按鈕停在錯誤 right
    setTimeout(place, 120);
    setTimeout(place, 600);

    // 快捷鍵 ]：圖表工作區收合／展開右側分析區（不搶 input/textarea）
    document.addEventListener('keydown', function (e) {
      if (e.key !== ']' || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      const tag = (t && t.tagName) ? t.tagName.toUpperCase() : '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
      if (!onChartRoute()) return;
      e.preventDefault();
      toggle();
    });

    window.toggleRightPanel = toggle;
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
    // 只還原仍存在的分頁（RESEARCH/PLAN 已移除，舊記憶會落到空白面板）
    const exists = saved && document.querySelector('.rtab[data-tab="' + saved.replace(/[^a-z]/g, '') + '"]');
    if (saved && saved !== 'stats' && exists) setTimeout(() => { try { setTab(saved); } catch {} }, 900);
  })();

  style();
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', () => { style(); injectCollapse(); });
  else injectCollapse();
})();

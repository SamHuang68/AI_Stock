// ============================================================
// Stock Terminal v3.8 — STATS 強化 (4 合 1)
// ------------------------------------------------------------
// 1. 技術 x 基本面 雙軸總結卡 (STATS 頂端)
// 2. 量價數值面板 (POC / 主力成本區 / 現價相對位置)
// 3. 右側面板可收合 (40% <-> 0 全螢幕線型)
// 4. 分頁記憶 (切股票後保留上次看的分頁)
// 須在 fundamental_v3.js / volume_profile_v3.js 之後載入。
//
// v3.8.3 (2026-07-23): 修正 techScore 字串比較 / Wilder RSI / 正確 KD
//   → 雙軸卡「技術面」分數下方 tag 必顯示「tech·383」。
//   若仍見技術面=0 且無 tech·383 → 本機未 pull 此分支，或瀏覽器舊快取。
// ============================================================
(function () {
  'use strict';
  const ENH_VER = '383';  // 雙軸卡可見版本戳（確認不是瀏覽器舊快取）
  try { console.info('[enhance] dual-score engine tech·' + ENH_VER); } catch (_) {}

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

  // 槓桿/反向 ETF → 本體（正2 跟本體同向、反1 反向）。槓桿單日%被放大，
  // 自身指標會失真(00631L 顯 38 偏空，但本體 0050 是 61 中性) → 改依本體判斷。
  const LEVERAGE_MAP = {
    '00631L': { base: '0050', inverse: false },   // 元大台灣50正2
    '00675L': { base: '0050', inverse: false },   // 富邦臺灣加權正2(近似)
    '00632R': { base: '0050', inverse: true },    // 元大台灣50反1
    '00676R': { base: '0050', inverse: true },    // 富邦臺灣加權反1
    '00663L': { base: '^DJI', inverse: false },   // 國泰美國道瓊正2
    '00670L': { base: '^IXIC', inverse: false },  // 富邦NASDAQ正2
  };
  // v3.8.1: 技術面分數一律用「1y 日線」標準基底算（與畫面顯示區間脫鉤）。
  // 修 bug：本尊(0050)用「目前顯示區間 candles」算、槓桿(00631L)用本體 1y 日線算，
  // 同一本體兩個分數(26 vs 65)互相矛盾。現統一走 canonical 路徑。
  const _canonTech = {};   // 'SYM|MKT' -> 1y日線技術面分數(槓桿已映射本體)
  const _canonFail = {};   // 'SYM|MKT' -> true(抓不到，fallback 用畫面指標)

  // ---- 技術面分數 0~100（可傳入指定 ind/candles，否則用目前載入個股）----
  // 公式（基底 50，最後 clamp 0~100）：
  //   RSI14 Wilder：±20（(rsi-50)*0.8）
  //   MACD vs Signal：+12 / −12
  //   KD K vs D：+8 / −8
  //   收盤 vs SMA20：+10 / −10
  //   SMA20 vs SMA60：+10 / −10
  // 注意：ind 各欄必須是 number；字串比較會讓負 MACD 誤判（2308 曾因此變 0）。
  function _n(v) {
    if (v == null || v === '' || v === '-') return null;
    const x = typeof v === 'number' ? v : parseFloat(v);
    return Number.isFinite(x) ? x : null;
  }
  function techScore(ind, candles) {
    ind = ind || ((typeof S !== 'undefined') && S.ind);
    candles = candles || (S.data && S.data.candles) || [];
    if (!ind) return null;
    const cur = candles.length ? candles[candles.length - 1].close : null;
    let score = 50, parts = 0;
    const add = v => { score += v; parts++; };
    const rsi = _n(ind.rsi14);
    const macd = _n(ind.macd), macdSig = _n(ind.macdSig);
    const K = _n(ind.K), D = _n(ind.D);
    const sma20 = _n(ind.sma20), sma60 = _n(ind.sma60);
    if (rsi != null) add(Math.max(-20, Math.min(20, (rsi - 50) * 0.8)));
    if (macd != null && macdSig != null) add(macd > macdSig ? 12 : -12);
    if (K != null && D != null) add(K > D ? 8 : -8);
    if (cur != null && sma20 != null) add(cur > sma20 ? 10 : -10);
    if (sma20 != null && sma60 != null) add(sma20 > sma60 ? 10 : -10);
    if (!parts) return null;
    return Math.max(0, Math.min(100, Math.round(score)));
  }

  // 取得「該檔應顯示的技術面分數」：canonical 快取優先；抓失敗才退回畫面指標
  function techScoreResolved() {
    const sym = (typeof S !== 'undefined' && S.sym) ? S.sym.toUpperCase() : '';
    const key = sym + '|' + ((typeof S !== 'undefined' && S.mkt) || 'TW');
    if (_canonTech[key] != null) return _canonTech[key];
    if (_canonFail[key]) return techScore();   // canonical 失敗 → 降級用畫面指標
    return null;                               // 計算中 → 顯示 —，算好後重繪
  }

  // 抓「標準基底」1y 日線算技術面分數：槓桿/反向取本體（反向翻轉），
  // 一般股票取自身。存快取後重繪雙軸卡。
  async function computeCanonTech(sym, mkt) {
    const key = sym + '|' + (mkt || 'TW');
    try {
      const SRV = window.SERVER || 'http://localhost:18432';
      const lev = LEVERAGE_MAP[sym];
      const target = lev ? lev.base : sym;
      let yf;
      if (/^\^/.test(target)) yf = target;
      else if (lev) yf = /^[0-9]/.test(target) ? target + '.TW' : target;
      else yf = (mkt === 'TW') ? target + '.TW' : target;
      const r = await fetch(`${SRV}/yf/${encodeURIComponent(yf)}?range=1y&interval=1d`, { cache: 'no-store' });
      if (!r.ok) { _canonFail[key] = true; return; }
      const raw = await r.json();
      const parsed = (typeof parseYF === 'function') ? parseYF(raw) : null;
      if (!parsed || !parsed.candles || parsed.candles.length < 20) { _canonFail[key] = true; return; }
      const ind = (typeof runWorker === 'function') ? await runWorker(parsed.candles) : null;
      if (!ind) { _canonFail[key] = true; return; }
      let sc = techScore(ind, parsed.candles);
      if (sc == null) { _canonFail[key] = true; return; }
      if (lev && lev.inverse) sc = 100 - sc;   // 反向 ETF 與本體相反
      _canonTech[key] = sc;
      if (typeof S !== 'undefined' && S.tab === 'stats' && (S.sym || '').toUpperCase() === sym) {
        const card = document.querySelector('#rpanel .dual-card');
        if (card) {
          // 保留目前基本面分數（從畫面讀回）後重繪
          card.outerHTML = dualCardHtml(null);
          if (window.fetchFund) fetchFund(S.sym, S.mkt).then(f => {
            const c2 = document.querySelector('#rpanel .dual-card');
            if (c2 && S.tab === 'stats') c2.outerHTML = dualCardHtml(f && f.score != null ? f.score : null);
          });
        }
      }
    } catch (e) { _canonFail[key] = true; }
  }
  const scoreCol = s => window.Colors ? Colors.quality(s, 65, 45) : (s == null ? 'var(--tlo)' : s >= 65 ? 'var(--red)' : s >= 45 ? 'var(--orange)' : 'var(--green)');
  const techTag = s => {
    const base = s == null ? '—' : s >= 65 ? '🟢 偏多' : s >= 45 ? '⚖️ 中性' : '🔴 偏空';
    return `${base} · tech·${ENH_VER}`;
  };
  const fundTag = s => s == null ? '—' : s >= 70 ? '🟢 體質佳' : s >= 50 ? '🟡 中性' : '🔴 偏弱';

  function dualCardHtml(fundScore) {
    const t = techScoreResolved();
    const sym = (typeof S !== 'undefined' && S.sym) ? S.sym.toUpperCase() : '';
    const lev = LEVERAGE_MAP[sym];
    const techLbl = lev
      ? `技術面 <span style="font-size:8px;color:var(--tf)">(依本體 ${lev.base} · 1Y日線)</span>`
      : `技術面 <span style="font-size:8px;color:var(--tf)">(1Y日線)</span>`;
    return `<div class="dual-card" data-enh-ver="${ENH_VER}">
      <div class="dual-half"><div class="lbl">${techLbl}</div>
        <div class="score" style="color:${scoreCol(t)}">${t == null ? '—' : t}</div>
        <div class="tag" style="color:${scoreCol(t)}">${techTag(t)}</div></div>
      <div class="dual-half"><div class="lbl">基本面</div>
        <div class="score" style="color:${scoreCol(fundScore)}">${fundScore == null ? '—' : fundScore}</div>
        <div class="tag" style="color:${scoreCol(fundScore)}">${fundTag(fundScore)}</div></div>
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
      // 非同步補基本面分數 + canonical(1y日線) 技術面（槓桿/反向自動映射本體）
      const symU = (S.sym || '').toUpperCase();
      const mktU = S.mkt || 'TW';
      if (symU && _canonTech[symU + '|' + mktU] == null && !_canonFail[symU + '|' + mktU])
        computeCanonTech(symU, mktU);
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

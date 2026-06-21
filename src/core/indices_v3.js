// ============================================================
// Stock Terminal v3.9 — 大盤指數加入自選股 (Index Watch)
// ------------------------------------------------------------
// 一鍵把台股加權/櫃買 + 美股四大(道瓊/標普/那斯達克/費半)加入自選股，
// 即可點 chip 看即時 K 線。指數代碼以 ^ 開頭(Yahoo)，loadSym/wl_live 已加
// ^ 守衛不附 .TW；自選股 chip 顯示友善名稱(w.name)。工具列 📈 指數。
// 架構守則：狀態用裸 S(S.wl/saveWl/renderWl)；對外 window.addIndices。
// ============================================================
(function () {
  'use strict';
  const INDICES = [
    { t: '^TWII', m: 'TW', name: '加權' },
    // 櫃買 ^TWOII 已移除：Yahoo 該指數各端點互斥(日線/quote/live 給 419/269/105 不一)，皆不可信。
    //   實際櫃買約 419~430(2026-06 TPEx 官方/財報狗),只有 TWSE MIS otc_o00 正確;見底部大盤列。
    { t: '^DJI', m: 'US', name: '道瓊' },
    { t: '^GSPC', m: 'US', name: 'S&P500' },
    { t: '^IXIC', m: 'US', name: '那斯達克' },
    { t: '^SOX', m: 'US', name: '費半' },
  ];

  function addIndices() {
    if (typeof S === 'undefined' || !Array.isArray(S.wl)) return;
    let added = 0;
    for (const ix of INDICES) {
      const ex = S.wl.find(w => w.t === ix.t);
      if (!ex) { S.wl.push({ t: ix.t, m: ix.m, name: ix.name }); added++; }
      else if (!ex.name) ex.name = ix.name;   // 補上友善名稱
    }
    if (typeof saveWl === 'function') saveWl();
    if (typeof renderWl === 'function') renderWl();
    if (typeof pollWlPrices === 'function') setTimeout(pollWlPrices, 300);
    if (typeof setStat === 'function') setStat(added ? `已加入 ${added} 個指數到自選股` : '指數已在自選股中');
  }

  window.addIndices = addIndices;

  // 自動清除先前一鍵加入的櫃買 ^TWOII(Yahoo 該指數資料壞:chart 419/quote 269/live 105 三種值、
  //   會顯示 +56% 假漲幅亂跳)。櫃買即時值請看底部大盤列(TWSE MIS otc_o00 才正確)。
  (function cleanupBadIndex() {
    if (typeof S === 'undefined' || !Array.isArray(S.wl)) return setTimeout(cleanupBadIndex, 200);
    const i = S.wl.findIndex(w => w && w.t === '^TWOII');
    if (i >= 0) {
      S.wl.splice(i, 1);
      if (typeof saveWl === 'function') saveWl();
      if (typeof renderWl === 'function') renderWl();
      console.log('[indices] removed broken ^TWOII (Yahoo data unreliable)');
    }
  })();

  // v3.9: 📈指數 按鈕已停用 — 改成直接點下方大盤列 cell 帶出 K 線(polish_v3),不需再把指數加進自選股。
  //   window.addIndices 仍保留(可手動呼叫);cleanupBadIndex 安全機制續行。
  // (function inject() {
  //   if (!document.getElementById('pro-tools')) return setTimeout(inject, 150);
  //   if (document.getElementById('btn-indices')) return;
  //   const b = document.createElement('button');
  //   b.id = 'btn-indices';
  //   b.className = 'probtn';
  //   b.title = '一鍵把指數加入自選股';
  //   b.textContent = '📈 指數';
  //   b.onclick = addIndices;
  //   document.getElementById('pro-tools').appendChild(b);
  // })();
})();

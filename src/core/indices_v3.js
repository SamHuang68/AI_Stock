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
    { t: '^TWOII', m: 'TW', name: '櫃買' },  // 日線改走 TPEx st41（server tw_index_charts）
    { t: '__TXF__', m: 'TW', name: '台指期' },
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

  // v3.9: 📈指數 按鈕已停用 — 改成直接點下方大盤列 cell 帶出 K 線(polish_v3)。
  //   櫃買／台指期日線已由 server/tw_index_charts 覆寫，不再自動清除 ^TWOII。
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

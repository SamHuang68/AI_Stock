// ============================================================
// Stock Terminal v3.9 — 當日盤中自動刷新 (Live Intraday Refresh)
// ------------------------------------------------------------
// 停在「1天」(分鐘盤中)時,每 INTERVAL 靜默重載當前個股 → 動態看盤、看得到當日漲跌。
// 靜默(loadSym 第三參數 silent=true)不閃「載入中」遮罩;切到日線/週線等不刷新(免擾)。
// 分頁隱藏時暫停,回到前景立即刷一次。狀態用裸 S、全域 loadSym。
// ============================================================
(function () {
  'use strict';
  var INTERVAL = 90000;   // 90s(台股即時走 realtime_v3 的 MIS;此處只負責 Yahoo 歷史回補,放慢以免干擾即時棒)

  function isIntradayActive() {
    var el = document.querySelector('#rangebar .active, #rangebar .on');
    if (!el || (el.textContent || '').trim() !== '1天') return false;   // 1天=唯一分鐘盤中視圖
    // 台股盤中由 realtime_v3(MIS 即時)逐分鐘累積,不在此全圖重載(否則會清掉累積的即時棒);
    // 美股盤中無 MIS → 仍用 Yahoo liverefresh。
    if (typeof S !== 'undefined' && S && S.mkt === 'TW') return false;
    return true;
  }

  function tick() {
    if (document.hidden) return;
    if (!isIntradayActive()) return;
    if (typeof S === 'undefined' || !S || !S.sym) return;
    if (typeof loadSym !== 'function') return;
    try { loadSym(S.sym, S.mkt, true); } catch (e) { console.warn('[liverefresh]', e); }
  }

  setInterval(tick, INTERVAL);
  // 切回前景時,若在盤中視圖立即刷一次
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) setTimeout(tick, 300);
  });
})();

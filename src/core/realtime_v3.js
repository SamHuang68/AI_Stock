// ============================================================
// Stock Terminal v3.9 — 台股盤中『真即時』(Realtime via TWSE MIS)
// ------------------------------------------------------------
// 問題:Yahoo 免費台股 1 分K 延遲約 20 分鐘(實測 10:24 vs 10:44),不適合即時看盤。
// 解法:停在「1天」且為台股、盤中時段時,每 10 秒抓 TWSE MIS 即時個股價,
//   用 series.update 即時更新「當前分鐘 K 棒」+ 右側現價/漲跌,達成近即時。
//   (Yahoo 歷史分K 仍由 liverefresh 補,故圖左側歷史可能落後;這是免費源天花板。)
// 狀態用裸 S;依賴 S.chartSeries / S.tzOffset / S.sym / S.mkt。
// ============================================================
(function () {
  'use strict';
  var MS = 3000;   // v3.9 即時化:3 秒(貼近 MIS ~5s 更新節奏的安全極限;更低只會重複+觸發 520)
  var curBucket = null, curBar = null, lastSym = null;
  var lastCumVol = null, bucketBaseVol = null;   // MIS 累積成交量(算每分鐘量增量用)

  function activeIntradayTW() {
    var el = document.querySelector('#rangebar .active, #rangebar .on');
    return !!el && (el.textContent || '').trim() === '1天' &&
      typeof S !== 'undefined' && S && S.mkt === 'TW' && S.sym && S.chartSeries;
  }

  function inTradingHours() {
    var d = new Date();                       // 假設機器在台北時區
    var hm = d.getHours() * 60 + d.getMinutes();
    return hm >= 535 && hm <= 820;            // 08:55–13:40 寬限
  }

  function tick() {
    if (document.hidden || !activeIntradayTW() || !inTradingHours()) return;
    var sym = S.sym;
    if (sym !== lastSym) { lastSym = sym; curBucket = null; curBar = null; lastCumVol = null; bucketBaseVol = null; }   // 切股重置
    fetch('/twquote?code=' + encodeURIComponent(sym)).then(function (r) { return r.json(); })
      .then(function (q) {
        if (!q || !q.ok || !(q.price > 0)) return;
        if (S.sym !== sym || !activeIntradayTW()) return;     // 切股/離開保護
        var off = S.tzOffset || 0;
        var bucket = Math.floor(Date.now() / 1000 / 60) * 60 + off;   // 當前分鐘(tz 平移)
        var cumVol = (q.volume > 0 ? q.volume : 0) * 1000;            // MIS 累積成交量:張→股(對齊 Yahoo 量柱)
        if (bucket !== curBucket) {
          curBucket = bucket;
          bucketBaseVol = (lastCumVol != null) ? lastCumVol : cumVol;  // 本分鐘起始累積量
          curBar = { time: bucket, open: q.price, high: q.price, low: q.price, close: q.price };
        } else {
          curBar.close = q.price;
          if (q.price > curBar.high) curBar.high = q.price;
          if (q.price < curBar.low) curBar.low = q.price;
        }
        lastCumVol = cumVol;
        try { S.chartSeries.update(curBar); } catch (e) { /* 圖剛重建時忽略 */ }
        if (S.dotSeries) { try { S.dotSeries.update({ time: bucket, value: q.price }); } catch (e) {} }   // 十字圓點線同步
        // 量柱同步:本分鐘量 = 累積量 − 本分鐘起始累積量(漲綠跌紅,同主圖)
        if (S.volSeries) {
          var bv = Math.max(0, cumVol - (bucketBaseVol || 0));
          var up = curBar.close >= curBar.open;
          try { S.volSeries.update({ time: bucket, value: bv, color: up ? 'rgba(74,222,128,0.25)' : 'rgba(248,113,113,0.25)' }); } catch (e) {}
        }
        // 即時心跳標(右上角):讓使用者一眼確認 realtime 在跳 + 最後更新時間(等同 Yahoo「HH:MM 更新」)
        var hb = document.getElementById('rt-hb');
        if (!hb) {
          var cw = document.getElementById('chart-wrap');
          if (cw) {
            hb = document.createElement('div');
            hb.id = 'rt-hb';
            hb.style.cssText = 'position:absolute;top:4px;right:10px;z-index:8;font-size:9px;' +
              'font-family:monospace;color:#3ecf6b;pointer-events:none;text-shadow:0 0 3px #000';
            cw.appendChild(hb);
          }
        }
        if (hb) hb.textContent = '● 即時 ' + new Date().toLocaleTimeString('zh-TW', { hour12: false }) + ' · MIS';
        // 右側現價/漲跌即時(台股紅漲綠跌) — 日漲跌 + 區間漲跌同步
        var cip = document.getElementById('ci-price');
        if (cip) cip.textContent = q.price.toFixed(2);
        if (q.prevClose > 0) {
          if (typeof updateHeaderChg === 'function') {
            updateHeaderChg(q.price, q.prevClose,
              (S.data && S.data.rangeBase) || null,
              (S.data && S.data.rangeChgLbl) || null,
              S.mkt, S.sym);
          } else {
            var pc = (q.price - q.prevClose) / q.prevClose * 100;
            var el = document.getElementById('ci-chg');
            if (el) { el.textContent = (pc >= 0 ? '+' : '') + pc.toFixed(2) + '%'; el.style.color = pc >= 0 ? 'var(--red)' : 'var(--green)'; }
          }
        }
        // 區間最高：即時價創新高時左欄同步刷新（避開右側量價浮動鈕遮蔽）
        if (typeof updateHeaderHigh === 'function' && S.data && S.data.candles) {
          updateHeaderHigh(S.data.candles, S.data.rangeChgLbl, q.price);
        }
        // 右側 STATS 面板即時(在 STATS 分頁才有這些 id;否則 guard 跳過)— 解「右側顯示 Yahoo 延遲值」
        function setRp(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
        var curUnit = (S.mkt === 'TW') ? 'TWD' : 'USD';
        setRp('rp-PRICE', q.price.toFixed(2) + ' ' + curUnit);
        if (q.prevClose > 0) {
          var dd = q.price - q.prevClose, ddp = dd / q.prevClose * 100;
          setRp('rp-CHANGE', (dd >= 0 ? '+' : '') + dd.toFixed(2) + ' (' + (ddp >= 0 ? '+' : '') + ddp.toFixed(2) + '%)');
        }
        if (S.data && S.data.rangeBase > 0 && S.range !== '1d') {
          var rd = q.price - S.data.rangeBase, rp = rd / S.data.rangeBase * 100;
          var rl = S.data.rangeChgLbl || '';
          setRp('rp-RANGE', (rd >= 0 ? '+' : '') + rd.toFixed(2) + ' (' + (rp >= 0 ? '+' : '') + rp.toFixed(2) + '%)' + (rl ? ' · ' + rl : ''));
        }
        if (q.open > 0) setRp('rp-OPEN', q.open.toFixed(2));
        if (q.high > 0) setRp('rp-HIGH', q.high.toFixed(2));
        if (q.low > 0) setRp('rp-LOW', q.low.toFixed(2));
        if (q.volume > 0) { var vsh = q.volume * 1000; setRp('rp-VOLUME', vsh > 1e6 ? (vsh / 1e6).toFixed(1) + 'M' : vsh.toLocaleString()); }
      }).catch(function () {});
  }

  setInterval(tick, MS);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) setTimeout(tick, 200); });
})();

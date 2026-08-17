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
  var volumeTracker = window.IntradayVolumeV3 && window.IntradayVolumeV3.createTracker
    ? window.IntradayVolumeV3.createTracker({ maxContinuityMs: 15000 }) : null;
  var requestSeq = 0, lastAppliedSeq = 0, generation = 0, chartReady = false;
  var lastTraceKey = null;

  function traceVolume(reason, q, extra) {
    var key = [reason, S && S.sym, q && q.volumeSource, curBucket].join('|');
    if (key === lastTraceKey) return;
    lastTraceKey = key;
    try {
      fetch('/diagnostics/ui-route', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true,
        body: JSON.stringify({
          ts: new Date().toISOString(), event: 'intraday_volume_rebase',
          correlationId: 'volume-' + Date.now(), from: 'realtime_v3', to: 'volumeSeries',
          state: reason, currentSource: q && q.volumeSource,
          label: JSON.stringify(extra || {}).slice(0, 110)
        })
      }).catch(function () {});
    } catch (e) {}
  }

  function resetFromChart(reason) {
    generation += 1;
    lastAppliedSeq = requestSeq;
    lastSym = (typeof S !== 'undefined' && S) ? S.sym : null;
    curBucket = null;
    curBar = null;
    var seed = null;
    if (S && S.data && S.data.candles && S.data.candles.length) {
      var last = S.data.candles[S.data.candles.length - 1];
      if (last && isFinite(Number(last.time))) {
        seed = { bucket: Number(last.time) + (S.tzOffset || 0), volume: Number(last.volume) || 0 };
        curBucket = seed.bucket;
        curBar = { time: seed.bucket, open: last.open, high: last.high, low: last.low, close: last.close };
      }
    }
    if (volumeTracker) volumeTracker.reset(lastSym, reason, seed);
  }

  function activeIntradayTW() {
    var el = document.querySelector('#rangebar .active, #rangebar .on');
    return !!el && (el.textContent || '').trim() === '1天' &&
      typeof S !== 'undefined' && S && S.mkt === 'TW' && /^\d{4,6}[A-Z]?$/.test(S.sym || '') &&
      S.chartSeries && chartReady;
  }

  function inTradingHours() {
    var d = new Date();                       // 假設機器在台北時區
    var hm = d.getHours() * 60 + d.getMinutes();
    return hm >= 535 && hm <= 820;            // 08:55–13:40 寬限
  }

  function tick() {
    if (document.hidden || !activeIntradayTW() || !inTradingHours()) return;
    var sym = S.sym;
    if (sym !== lastSym) resetFromChart('symbol_change');
    var seq = ++requestSeq;
    var requestGeneration = generation;
    fetch('/twquote?code=' + encodeURIComponent(sym)).then(function (r) { return r.json(); })
      .then(function (q) {
        if (!q || !q.ok || !(q.price > 0)) return;
        if (requestGeneration !== generation || S.sym !== sym || !activeIntradayTW()) return;
        if (seq <= lastAppliedSeq) {
          traceVolume('out_of_order_response', q, { requestSeq: seq, lastAppliedSeq: lastAppliedSeq });
          return;
        }
        lastAppliedSeq = seq;
        var off = S.tzOffset || 0;
        var bucket = Math.floor(Date.now() / 1000 / 60) * 60 + off;   // 當前分鐘(tz 平移)
        var cumVol = window.IntradayVolumeV3
          ? window.IntradayVolumeV3.canonicalShares(q) : null;
        var volumeResult = volumeTracker && cumVol != null ? volumeTracker.observe({
          context: sym,
          source: q.volumeSource || q.source || 'unknown',
          bucket: bucket,
          cumulative: cumVol,
          sampleTimestampMs: q.volumeTimestampMs || q.timestampMs,
          receivedAtMs: Date.now(),
          requestSeq: seq,
          realtime: q.volumeRealtime !== false,
        }) : null;
        if (volumeResult && volumeResult.action === 'baseline' &&
            volumeResult.reason !== 'initial' && volumeResult.reason !== 'sym_loaded') {
          traceVolume(volumeResult.reason, q, {
            requestSeq: seq, bucket: bucket, volume: volumeResult.volume,
            sampleTimestampMs: q.volumeTimestampMs || null
          });
        }

        var priceRealtime = q.source === 'twse-mis';
        if (bucket !== curBucket) {
          curBucket = bucket;
          curBar = { time: bucket, open: q.price, high: q.price, low: q.price, close: q.price };
        } else if (curBar && priceRealtime) {
          curBar.close = q.price;
          if (q.price > curBar.high) curBar.high = q.price;
          if (q.price < curBar.low) curBar.low = q.price;
        }
        // Yahoo 價格備援可能延遲數十分鐘；不可用抵達時間偽裝成本分鐘成交。
        if (priceRealtime && curBar) {
          try { S.chartSeries.update(curBar); } catch (e) {
            traceVolume('price_series_update_failed', q, { message: String(e).slice(0, 80), bucket: bucket });
          }
          if (S.dotSeries) { try { S.dotSeries.update({ time: bucket, value: q.price }); } catch (e) {} }
        }
        // 量柱同步：只採用來源／序列連續且單位已正規化的累積量差。
        if (S.volSeries && curBar && volumeResult) {
          var bv = volumeResult.volume;
          var up = curBar.close >= curBar.open;
          try { S.volSeries.update({ time: bucket, value: bv, color: up ? 'rgba(74,222,128,0.25)' : 'rgba(248,113,113,0.25)' }); } catch (e) {
            traceVolume('volume_series_update_failed', q, { message: String(e).slice(0, 80), bucket: bucket });
          }
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
        if (hb) {
          var isMisPrice = q.source === 'twse-mis';
          var volLabel = q.volumeSource === 'twse-mis' && !isMisPrice ? '/MIS量' : '';
          hb.style.color = isMisPrice ? '#3ecf6b' : '#f59e0b';
          hb.textContent = '● ' + (isMisPrice ? '即時 ' : '備援 ') +
            (isMisPrice ? new Date().toLocaleTimeString('zh-TW', { hour12: false }) : (q.time || '時間未知')) +
            ' · ' + (isMisPrice ? 'MIS' : 'Yahoo價' + volLabel);
        }
        // 右側現價/漲跌即時(台股紅漲綠跌) — 日漲跌 + 區間漲跌同步
        var cip = document.getElementById('ci-price');
        if (priceRealtime && cip) cip.textContent = q.price.toFixed(2);
        if (priceRealtime && q.prevClose > 0) {
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
        if (priceRealtime && typeof updateHeaderHigh === 'function' && S.data && S.data.candles) {
          updateHeaderHigh(S.data.candles, S.data.rangeChgLbl, q.price);
        }
        // 右側 STATS 面板即時(在 STATS 分頁才有這些 id;否則 guard 跳過)— 解「右側顯示 Yahoo 延遲值」
        function setRp(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
        var curUnit = (S.mkt === 'TW') ? 'TWD' : ((S.mkt === 'JP') ? 'JPY' : 'USD');
        if (priceRealtime) setRp('rp-PRICE', q.price.toFixed(2) + ' ' + curUnit);
        if (priceRealtime && q.prevClose > 0) {
          var dd = q.price - q.prevClose, ddp = dd / q.prevClose * 100;
          setRp('rp-CHANGE', (dd >= 0 ? '+' : '') + dd.toFixed(2) + ' (' + (ddp >= 0 ? '+' : '') + ddp.toFixed(2) + '%)');
        }
        if (priceRealtime && S.data && S.data.rangeBase > 0 && S.range !== '1d') {
          var rd = q.price - S.data.rangeBase, rp = rd / S.data.rangeBase * 100;
          var rl = S.data.rangeChgLbl || '';
          setRp('rp-RANGE', (rd >= 0 ? '+' : '') + rd.toFixed(2) + ' (' + (rp >= 0 ? '+' : '') + rp.toFixed(2) + '%)' + (rl ? ' · ' + rl : ''));
        }
        if (priceRealtime && q.open > 0) setRp('rp-OPEN', q.open.toFixed(2));
        if (priceRealtime && q.high > 0) setRp('rp-HIGH', q.high.toFixed(2));
        if (priceRealtime && q.low > 0) setRp('rp-LOW', q.low.toFixed(2));
        if (cumVol != null) setRp('rp-VOLUME', cumVol > 1e6 ? (cumVol / 1e6).toFixed(1) + 'M' : cumVol.toLocaleString());
      }).catch(function () {});
  }

  setInterval(tick, MS);
  window.addEventListener('symLoading', function () { chartReady = false; resetFromChart('sym_loading'); });
  window.addEventListener('symLoaded', function () { chartReady = true; resetFromChart('sym_loaded'); setTimeout(tick, 100); });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (volumeTracker) volumeTracker.rebaseNext('visibility_resume');
      return;
    }
    if (volumeTracker) volumeTracker.rebaseNext('visibility_resume');
    setTimeout(tick, 200);
  });
  window.addEventListener('offline', function () { if (volumeTracker) volumeTracker.rebaseNext('network_resume'); });
  window.addEventListener('online', function () {
    if (volumeTracker) volumeTracker.rebaseNext('network_resume');
    setTimeout(tick, 200);
  });
})();

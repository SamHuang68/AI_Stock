// ============================================================
// Stock Terminal v3.9 Phase-0 — 資料源健檢燈 (Data Source Health)
// ------------------------------------------------------------
// 工具列 📡 源 指示燈,每 30s 輪詢 /health 的 sources 區塊,顯示各對外源
// (yahoo / twse-mis / taifex-mis) 的 綠/黃/紅 狀態 + 成功率 + 最後成功幾秒前。
//   綠 = 健康且近期有成功;  黃 = 熔斷開啟或資料偏舊;  紅 = 連續失敗。
// 這是 TrustedDataLayer 的「源健檢」旁路視圖(非請求路徑)。
// 架構守則:IIFE,對外不汙染;工具列注入同 indices_v3.js 模式。
// ============================================================
(function () {
  'use strict';

  var POLL_MS = 30000;
  var SRC_LABEL = { 'yahoo': 'Yahoo', 'twse-mis': '證交所MIS', 'taifex-mis': '期交所MIS' };

  function dotColor(s) {
    if (!s) return '#666';
    if (s.breakerOpen || s.failStreak >= 4) return '#e74c3c';        // 紅:熔斷/連敗
    if ((s.okRate != null && s.okRate < 80) ||
        (s.lastOkAgo != null && s.lastOkAgo > 180)) return '#f1c40f'; // 黃:成功率低/偏舊
    if (!s.healthy) return '#f1c40f';
    return '#2ecc71';                                                 // 綠:健康
  }

  function worst(sources) {
    var keys = Object.keys(sources || {});
    if (!keys.length) return '#666';                 // 無紀錄:灰
    var cols = keys.map(function (k) { return dotColor(sources[k]); });
    if (cols.indexOf('#e74c3c') >= 0) return '#e74c3c';  // 任一紅 → 紅
    if (cols.indexOf('#f1c40f') >= 0) return '#f1c40f';  // 任一黃 → 黃
    if (cols.indexOf('#666') >= 0) return '#666';        // 任一灰 → 灰
    return '#2ecc71';                                     // 全綠 → 綠
  }

  function fmtAgo(sec) {
    if (sec == null) return '—';
    if (sec < 60) return Math.round(sec) + 's前';
    if (sec < 3600) return Math.round(sec / 60) + 'm前';
    return Math.round(sec / 3600) + 'h前';
  }

  var _prevColor = {};   // 偵測源轉紅 → 推 toast
  function checkTransitions(sources) {
    Object.keys(sources || {}).forEach(function (k) {
      var c = dotColor(sources[k]);
      if (c === '#e74c3c' && _prevColor[k] && _prevColor[k] !== '#e74c3c') {
        if (typeof window.notifyToast === 'function') {
          var s = sources[k] || {};
          window.notifyToast('資料源異常：' + (SRC_LABEL[k] || k),
            (s.breakerOpen ? '熔斷開啟' : '連續失敗 ' + (s.failStreak || 0) + ' 次') +
            (s.lastError ? '・' + s.lastError : ''), { level: 'error' });
        }
      }
      _prevColor[k] = c;
    });
  }

  function render(sources) {
    var pill = document.getElementById('dh-pill');
    var panel = document.getElementById('dh-panel');
    checkTransitions(sources);
    if (!pill || !panel) return;
    var keys = Object.keys(sources || {});
    pill.style.background = worst(sources);
    if (!keys.length) {
      panel.innerHTML = '<div style="padding:8px 10px;color:#888;font-size:11px">尚無對外請求紀錄</div>';
      return;
    }
    var rows = keys.sort().map(function (k) {
      var s = sources[k] || {};
      var name = SRC_LABEL[k] || k;
      var rate = (s.okRate != null) ? s.okRate + '%' : '—';
      var err = s.breakerOpen ? ' · 熔斷中' : (s.failStreak ? ' · 連敗' + s.failStreak : '');
      var errLine = (s.lastError && (s.breakerOpen || s.failStreak))
        ? '<div style="color:#c0392b;font-size:10px;margin-top:2px">' +
          String(s.lastError).replace(/</g, '&lt;') + '</div>' : '';
      return '<div style="padding:6px 10px;border-top:1px solid #2a2a2a">' +
        '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' +
        dotColor(s) + ';margin-right:6px"></span>' +
        '<b style="font-size:11px">' + name + '</b>' +
        '<span style="float:right;font-size:10px;color:#999">' +
        rate + ' · ' + fmtAgo(s.lastOkAgo) + (s.lastMs != null ? ' · ' + s.lastMs + 'ms' : '') +
        '</span>' +
        '<span style="font-size:10px;color:#e67e22">' + err + '</span>' +
        errLine + '</div>';
    }).join('');
    panel.innerHTML = '<div style="padding:6px 10px;font-size:10px;color:#888">資料源健檢 (30s)</div>' + rows;
  }

  function poll() {
    fetch('/health').then(function (r) { return r.json(); })
      .then(function (j) { render(j && j.sources ? j.sources : {}); })
      .catch(function () {
        var pill = document.getElementById('dh-pill');
        if (pill) pill.style.background = '#e74c3c';
      });
  }

  (function inject() {
    if (!document.getElementById('pro-tools')) return setTimeout(inject, 150);
    if (document.getElementById('btn-datahealth')) return;

    var wrap = document.createElement('span');
    wrap.style.position = 'relative';
    wrap.style.display = 'inline-block';

    var b = document.createElement('button');
    b.id = 'btn-datahealth';
    b.className = 'probtn';
    b.title = '資料源健檢:各對外源成功率/延遲/熔斷狀態 (v3.9 Phase-0)';
    b.innerHTML = '<span id="dh-pill" style="display:inline-block;width:8px;height:8px;' +
      'border-radius:50%;background:#666;margin-right:5px;vertical-align:middle"></span>📡 源';

    var panel = document.createElement('div');
    panel.id = 'dh-panel';
    panel.style.cssText = 'display:none;position:absolute;top:100%;right:0;z-index:9999;' +
      'min-width:230px;background:#161616;border:1px solid #333;border-radius:6px;' +
      'box-shadow:0 6px 20px rgba(0,0,0,.5);margin-top:4px';
    panel.innerHTML = '<div style="padding:8px 10px;color:#888;font-size:11px">載入中…</div>';

    b.onclick = function (e) {
      e.stopPropagation();
      panel.style.display = (panel.style.display === 'none') ? 'block' : 'none';
      if (panel.style.display === 'block') poll();
    };
    document.addEventListener('click', function () { panel.style.display = 'none'; });

    wrap.appendChild(b);
    wrap.appendChild(panel);
    document.getElementById('pro-tools').appendChild(wrap);

    poll();
    setInterval(poll, POLL_MS);
  })();
})();

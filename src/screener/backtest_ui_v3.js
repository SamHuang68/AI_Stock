// ============================================================
// Stock Terminal v3.8 — 回測引擎 UI
// ------------------------------------------------------------
// 浮動面板：對當前股票 S.data.candles 跑
//   • 8 策略歷史勝率/期望值掃描 (Backtest.scanStrategies)
//   • 選定策略的權益曲線 (Backtest.drawCurve)
//   • 19 型態歷史命中率 (Backtest.patternHitRate，若 PatternV3 存在)
// 依賴 backtest_v3.js (window.Backtest)。
// ============================================================
(function () {
  'use strict';

  function style() {
    if (document.getElementById('bt3-style')) return;
    const s = document.createElement('style'); s.id = 'bt3-style';
    s.textContent = `
    #bt3-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #bt3-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(720px,94vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #bt3-box h3{margin:0 0 8px;font-size:15px}
    #bt3-box .ctrl{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
    #bt3-box input{width:64px;background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:5px;padding:3px 5px}
    #bt3-box button{background:#2563eb;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer}
    #bt3-box button.sec{background:#334155}
    #bt3-box table{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px}
    #bt3-box th,#bt3-box td{border-bottom:1px solid #1e293b;padding:4px 5px;text-align:right}
    #bt3-box th:first-child,#bt3-box td:first-child{text-align:left}
    #bt3-box tr{cursor:pointer}
    #bt3-box tr:hover td{background:#1e293b}
    .bt3-pos{color:#34d399}.bt3-neg{color:#f87171}`;
    document.head.appendChild(s);
  }

  function cur(v, p) { return (v >= 0 ? '+' : '') + v.toFixed(p == null ? 1 : p) + '%'; }
  function cls(v) { return v >= 0 ? 'bt3-pos' : 'bt3-neg'; }

  function open() {
    style();
    let m = document.getElementById('bt3-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'bt3-modal';
      m.innerHTML = `<div id="bt3-box">
        <h3>📈 回測引擎 v3.8</h3>
        <div class="ctrl">
          停利% <input id="bt3-tp" value="15">
          停損% <input id="bt3-sl" value="8">
          最長持有(日) <input id="bt3-mb" value="20">
          <button id="bt3-run">執行掃描</button>
          <button class="sec" id="bt3-close">關閉</button>
        </div>
        <canvas id="bt3-curve" width="680" height="120" style="background:#0b1220;border:1px solid #1e293b;border-radius:6px;width:100%"></canvas>
        <div id="bt3-body" style="margin-top:8px;color:#64748b">按「執行掃描」開始（使用目前線型資料）。</div>
      </div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
      m.querySelector('#bt3-close').onclick = close;
      m.querySelector('#bt3-run').onclick = runScan;
    }
    m.style.display = 'flex';
  }
  function close() {
    const m = document.getElementById('bt3-modal');
    if (m) m.style.display = 'none';
    // 清除上一支股票的回測結果，避免下次開啟殘留
    lastRows = [];
    const body = document.getElementById('bt3-body');
    if (body) body.innerHTML = '按「執行掃描」開始（使用目前線型資料）。';
    const cv = document.getElementById('bt3-curve');
    if (cv) { const ctx = cv.getContext('2d'); ctx && ctx.clearRect(0, 0, cv.width, cv.height); }
  }

  let lastRows = [];

  async function runScan() {
    const body = document.getElementById('bt3-body');
    if (body) body.innerHTML = '載入本機深度歷史中…';
    // v4.0:優先用本機 DB 的深度歷史(5年)跑回測,不再只靠畫面載入的區間
    let candles = [];
    try {
      const sym = (typeof S !== 'undefined' && S.sym) ? S.sym : '';
      const mkt = (typeof S !== 'undefined' && S.mkt) ? S.mkt : 'TW';
      if (sym) {
        const r = await fetch('/bars?sym=' + encodeURIComponent(sym) + '&market=' + encodeURIComponent(mkt));
        const j = await r.json();
        if (j && j.candles && j.candles.length >= 80) candles = j.candles;
      }
    } catch (e) {}
    // 後援:深度歷史抓不到 → 用畫面載入的線型資料
    if (candles.length < 80) candles = ((typeof S !== 'undefined') && S.data && S.data.candles) || [];
    if (candles.length < 80) { body.innerHTML = '<span class="bt3-neg">資料太少（需 ≥ 80 根 K）。</span>'; return; }
    const opts = {
      tp: (+document.getElementById('bt3-tp').value || 15) / 100,
      sl: (+document.getElementById('bt3-sl').value || 8) / 100,
      maxBars: +document.getElementById('bt3-mb').value || 20,
    };
    const rows = window.Backtest.scanStrategies(candles, opts);
    lastRows = rows;
    let h = `<table><thead><tr><th>策略</th><th>次數</th><th>勝率</th><th>賠率</th><th>期望值</th><th>總報酬(淨)</th><th>總報酬(毛)</th><th>最大回撤</th><th>夏普</th></tr></thead><tbody>`;
    rows.forEach((r, i) => {
      h += `<tr data-i="${i}"><td>${r.name}</td><td>${r.count}</td>
        <td>${r.winRate.toFixed(0)}%</td>
        <td>${isFinite(r.payoff) ? r.payoff.toFixed(2) : '∞'}</td>
        <td class="${cls(r.expectancy)}">${cur(r.expectancy)}</td>
        <td class="${cls(r.totalReturn)}">${cur(r.totalReturn)}</td>
        <td class="${cls(r.totalReturnGross != null ? r.totalReturnGross : r.totalReturn)}">${cur(r.totalReturnGross != null ? r.totalReturnGross : r.totalReturn)}</td>
        <td class="bt3-neg">-${r.maxDD.toFixed(0)}%</td>
        <td>${r.sharpe.toFixed(2)}</td></tr>`;
    });
    h += `</tbody></table>`;
    const c0 = rows.length && rows[0].cost ? rows[0].cost : null;
    h += `<div style="font-size:10px;color:#64748b;margin-top:4px">進場=訊號次根開盤(無前視);淨=已扣` +
      (c0 ? `手續費 ${(c0.fee * 100).toFixed(4)}%×2 + 證交稅 ${(c0.tax * 100).toFixed(2)}%(賣出)` : '費稅') +
      `;TP/SL 以收盤判斷,未模擬盤中觸價與滑價</div>`;

    // 型態命中率（若 PatternV3 可用）
    if (window.PatternV3 && typeof PatternV3.detectPatterns === 'function') {
      h += `<div style="margin-top:10px;font-weight:700">型態歷史命中率 (10 日後)</div>`;
      h += patternRates(candles);
    }
    body.innerHTML = h;
    body.querySelectorAll('tr[data-i]').forEach(tr => tr.onclick = () => {
      const r = lastRows[+tr.dataset.i];
      window.Backtest.drawCurve(document.getElementById('bt3-curve'), r.curve, '#34d399');
    });
    if (rows[0]) window.Backtest.drawCurve(document.getElementById('bt3-curve'), rows[0].curve, '#34d399');
  }

  function patternRates(candles) {
    // 用 PatternV3 對 slice 偵測；逐型態用 detectPatterns 是否含該型
    const sampleTypes = ['雙底', '雙頂', '頭肩底', '頭肩頂', '黃金交叉', '杯柄', '上升三角', '突破'];
    let h = '<table><thead><tr><th>型態(關鍵字)</th><th>樣本</th><th>命中率</th><th>平均報酬</th></tr></thead><tbody>';
    for (const kw of sampleTypes) {
      const res = window.Backtest.patternHitRate(candles, slice => {
        try {
          const r = PatternV3.detectPatterns(slice);
          const list = Array.isArray(r) ? r : (r && r.patterns) || [];
          return list.some(p => (p.name || p.type || '').includes(kw));
        } catch { return false; }
      }, 10);
      if (res.count > 0)
        h += `<tr><td>${kw}</td><td>${res.count}</td><td>${res.hitRate.toFixed(0)}%</td><td class="${cls(res.avgRet)}">${cur(res.avgRet)}</td></tr>`;
    }
    h += '</tbody></table>';
    return h;
  }

  window.backtestOpen = open;
  window.backtestClose = close;
})();

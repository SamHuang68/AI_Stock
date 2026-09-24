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

  function cur(v, p) { return Number.isFinite(v) ? (v >= 0 ? '+' : '') + v.toFixed(p == null ? 1 : p) + '%' : '—'; }
  function cls(v) { return Number.isFinite(v) ? v >= 0 ? 'bt3-pos' : 'bt3-neg' : ''; }

  function open() {
    style();
    let m = document.getElementById('bt3-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'bt3-modal';
      m.innerHTML = `<div id="bt3-box">
        <h3>📈 下一棒開盤回測研究</h3>
        <div class="ctrl">
          停利% <input id="bt3-tp" value="15">
          停損% <input id="bt3-sl" value="8">
          最長持有(棒) <input id="bt3-mb" value="20">
          單邊費用情境% <input id="bt3-fee" value="0.25">
          賣出稅費情境% <input id="bt3-tax" value="0">
          不利滑價% <input id="bt3-slip" value="0">
          <button id="bt3-run">執行掃描</button>
          <button class="sec" id="bt3-close">關閉</button>
        </div>
        <div style="line-height:1.6">收盤訊號及出場條件均於下一棒開盤執行；每棒收盤估值，期末部位保留未平倉。成本為自訂情境，非實際券商費率。資料與交易日曆未完整核對，僅供同樣本探索，不能升格策略。</div>
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
    scanSequence++;
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
  let scanSequence = 0;

  async function runScan() {
    const sequence = ++scanSequence;
    const symbol = (typeof S !== 'undefined' && S.sym) ? S.sym : '';
    const market = (typeof S !== 'undefined' && S.mkt) ? S.mkt : 'TW';
    const body = document.getElementById('bt3-body');
    if (body) body.innerHTML = '載入本機深度歷史中…';
    // v4.0:優先用本機 DB 的深度歷史(5年)跑回測,不再只靠畫面載入的區間
    let candles = [];
    try {
      const sym = symbol;
      const mkt = market;
      if (sym) {
        const r = await fetch('/bars?sym=' + encodeURIComponent(sym) + '&market=' + encodeURIComponent(mkt));
        const j = await r.json();
        if (j && j.candles && j.candles.length >= 80) candles = j.candles;
      }
    } catch (e) {}
    if (sequence !== scanSequence || (typeof S !== 'undefined' && (S.sym !== symbol || (S.mkt || 'TW') !== market))) return;
    // 後援:深度歷史抓不到 → 用畫面載入的線型資料
    if (candles.length < 80) candles = ((typeof S !== 'undefined') && S.data && S.data.candles) || [];
    if (candles.length < 80) { body.innerHTML = '<span class="bt3-neg">資料太少（需 ≥ 80 根 K）。</span>'; return; }
    if (candles.some(c => !['open', 'high', 'low', 'close'].every(k => Number.isFinite(c[k]) && c[k] > 0))) {
      lastRows = [];
      body.innerHTML = '<span class="bt3-neg">歷史區間含缺值或無成交日，無法判定回測；請改用已完整核對的區間。</span>';
      const cv = document.getElementById('bt3-curve');
      const ctx = cv && cv.getContext('2d'); if (ctx) ctx.clearRect(0, 0, cv.width, cv.height);
      return;
    }
    const opts = {
      tp: Number(document.getElementById('bt3-tp').value) / 100,
      sl: Number(document.getElementById('bt3-sl').value) / 100,
      maxBars: Number(document.getElementById('bt3-mb').value),
      feeRate: Number(document.getElementById('bt3-fee').value) / 100,
      taxRate: Number(document.getElementById('bt3-tax').value) / 100,
      slippage: Number(document.getElementById('bt3-slip').value) / 100,
    };
    if (![opts.feeRate, opts.taxRate, opts.slippage].every(value => Number.isFinite(value) && value >= 0 && value < 1)) {
      body.textContent = '成本情境須為 0 至小於 100% 的有限數值。'; return;
    }
    if (![opts.tp, opts.sl].every(value => Number.isFinite(value) && value >= 0) || !Number.isInteger(opts.maxBars) || opts.maxBars < 0) {
      body.textContent = '停利停損須為非負數，持有棒數須為非負整數；0 代表停用該條件。'; return;
    }
    const rows = window.Backtest.scanStrategies(candles, opts);
    lastRows = rows;
    let h = `<div>版本：${window.Backtest.ENGINE_VERSION || '未提供'}。排序使用同一開發樣本；總報酬含期末按市價部位，勝率僅計已平倉交易。</div><div style="max-width:100%;overflow:auto"><table><thead><tr><th>策略</th><th>已平倉</th><th>勝率</th><th>賠率</th><th>期望值</th><th>總報酬</th><th>收盤回撤</th><th>每棒夏普</th><th>待確認</th></tr></thead><tbody>`;
    rows.forEach((r, i) => {
      h += `<tr data-i="${i}"><td>${r.name}</td><td>${r.count}</td>
        <td>${r.count ? r.winRate.toFixed(0) + '%' : '—'}</td>
        <td>${isFinite(r.payoff) ? r.payoff.toFixed(2) : '∞'}</td>
        <td class="${cls(r.expectancy)}">${cur(r.expectancy)}</td>
        <td class="${cls(r.totalReturn)}">${cur(r.totalReturn)}</td>
        <td class="bt3-neg">${Number.isFinite(r.maxDD) ? '-' + r.maxDD.toFixed(1) + '%' : '未知'}</td>
        <td>${Number.isFinite(r.sharpe) ? r.sharpe.toFixed(2) : '—'}</td>
        <td>${r.openPosition ? '未平倉' : r.pendingEntry ? '待進場' : '—'}${r.rejected && r.rejected.length ? '／未成交 ' + r.rejected.length : ''}${r.status === 'unknown' ? '／估值未知' : ''}</td></tr>`;
    });
    h += `</tbody></table></div>`;

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

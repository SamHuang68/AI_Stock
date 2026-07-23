// ============================================================
// Stock Terminal v3.8 — 長線估值錨（本益比河流）
// ------------------------------------------------------------
// 給長線市場派判斷「現在貴不貴」：抓當前 PER/PBR/殖利率(/valuation)，
// 再用 5 年週線股價 ÷ EPS_ttm 還原歷史本益比分布，標出現在落在
// 便宜↔昂貴的百分位，並列出 EPS×各倍數對應股價（河流帶）。
// 資料源：/valuation/<sym> + /yf?range=5y&interval=1wk。工具列 ⚓ 估值。
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';

  function pcls(c) { return c == null ? '' : c > 0 ? 'val-up' : c < 0 ? 'val-dn' : ''; }
  function pct(p) { return (typeof percentile === 'undefined') ? p : p; }

  function style() {
    if (document.getElementById('val-style')) return;
    const s = document.createElement('style'); s.id = 'val-style';
    s.textContent = `
    #val-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #val-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(640px,94vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #val-box h3{margin:0 0 6px;font-size:15px}
    .val-kpi{display:flex;gap:8px;margin:8px 0}
    .val-kpi>div{flex:1;border:1px solid #1e293b;border-radius:8px;padding:8px;text-align:center;background:#0b1220}
    .val-kpi .k{font-size:9px;color:#64748b}
    .val-kpi .v{font-size:18px;font-weight:800;margin-top:2px}
    .val-gauge{height:14px;border-radius:7px;background:linear-gradient(90deg,#16a34a,#eab308,#ef4444);position:relative;margin:6px 0 2px}
    .val-gauge .mk{position:absolute;top:-3px;width:3px;height:20px;background:#fff;border-radius:2px;box-shadow:0 0 4px #000}
    .val-lbl{display:flex;justify-content:space-between;font-size:9px;color:#64748b}
    .val-up{color:#ef4444}.val-dn{color:#22c55e}
    .val-tbl{width:100%;border-collapse:collapse;margin-top:8px;font-size:11px}
    .val-tbl th,.val-tbl td{padding:4px 6px;border-bottom:1px solid #1e293b;text-align:right}
    .val-tbl th:first-child,.val-tbl td:first-child{text-align:left}
    .val-now{background:rgba(251,191,36,.12);font-weight:800}
    .val-note{font-size:9px;color:#64748b;line-height:1.6;margin-top:8px}`;
    document.head.appendChild(s);
  }

  function quantile(sorted, q) {
    if (!sorted.length) return null;
    const pos = (sorted.length - 1) * q, base = Math.floor(pos), rest = pos - base;
    return sorted[base + 1] !== undefined ? sorted[base] + rest * (sorted[base + 1] - sorted[base]) : sorted[base];
  }

  async function render() {
    const body = document.getElementById('val-body');
    if (!body) return;
    const sym = (typeof S !== 'undefined' && S.sym) ? S.sym : null;
    // 市場一律依「代號本身」判(台股代號數字開頭/^TW;美股為字母),不靠 S.mkt 或 server 猜測,
    // 避免 00631L 之類被標成美股、或用無 .TW 代號抓錯標的。
    const isTw = window.Colors ? Colors.isTW(sym) : (/^\d/.test(String(sym || '')) || /^\^TW/i.test(String(sym || '')));
    const mkt = isTw ? 'TW' : 'US';
    if (!sym) { body.innerHTML = '請先載入一檔股票。'; return; }
    body.innerHTML = '載入中…';
    const yfSym = (mkt === 'TW' && !/^\^/.test(String(sym)) && !(String(sym).startsWith('__') && String(sym).endsWith('__')))
      ? (sym.includes('.') ? sym : sym + '.TW')
      : sym;

    let v = {}, hist = [];
    try { v = await fetch(`${SRV}/valuation/${encodeURIComponent(sym)}`, { cache: 'no-store' }).then(r => r.json()); } catch (e) {}
    try {
      const j = await fetch(`${SRV}/yf/${encodeURIComponent(yfSym)}?range=5y&interval=1wk`, { cache: 'no-store' }).then(r => r.json());
      const res = j.chart && j.chart.result && j.chart.result[0];
      const cl = res && res.indicators && res.indicators.quote && res.indicators.quote[0] && res.indicators.quote[0].close;
      hist = (cl || []).filter(x => x != null && isFinite(x) && x > 0);
    } catch (e) {}

    const eps = v.epsTtm;
    let price = v.price || (hist.length ? hist[hist.length - 1] : null);
    // v3.9 Data Integrity:BWIBBU_ALL 的 price 是 EOD 收盤(慢一天)→ 用最新成交價覆蓋,現價/PER 才是最新。
    //   台股取 MIS /twquote(真即時/收盤);否則用目前載入的 K 線最後收盤。
    let _live = null;
    const _code = sym.replace('.TWO', '').replace('.TW', '');
    if (mkt === 'TW') {
      try { const _q = await fetch(`${SRV}/twquote?code=${encodeURIComponent(_code)}`, { cache: 'no-store' }).then(r => r.json()); if (_q && _q.ok && _q.price > 0) _live = _q.price; } catch (e) {}
    }
    if (!_live && typeof S !== 'undefined' && S.sym === sym && S.data && S.data.candles && S.data.candles.length) {
      const _lc = S.data.candles[S.data.candles.length - 1]; if (_lc && _lc.close > 0) _live = _lc.close;
    }
    if (_live) price = _live;
    const curPer = (price && eps) ? (price / eps) : v.per;   // 用最新價重算 PER(原 v.per 基於 EOD 收盤)
    const fmt = (x, d = 2) => x == null ? '—' : (+x).toFixed(d);

    let kpi = `<div class="val-kpi">
      <div><div class="k">本益比 PER</div><div class="v">${fmt(curPer, 1)}</div></div>
      <div><div class="k">股價淨值比 PBR</div><div class="v">${fmt(v.pbr, 2)}</div></div>
      <div><div class="k">殖利率</div><div class="v">${v.yieldPct == null ? '—' : fmt(v.yieldPct, 2) + '%'}</div></div>
    </div>`;

    // 歷史本益比分布（5年週線 ÷ 當前 EPS_ttm，近似河流）
    let gauge = '', river = '', verdict = '';
    if (eps && eps > 0 && hist.length > 20) {
      const peSeries = hist.map(p => p / eps).sort((a, b) => a - b);
      const lo = quantile(peSeries, 0.05), q1 = quantile(peSeries, 0.25),
        med = quantile(peSeries, 0.5), q3 = quantile(peSeries, 0.75), hi = quantile(peSeries, 0.95);
      const useP = curPer || (price && eps ? price / eps : med);
      // 百分位：現值在歷史序列的位置
      let below = peSeries.filter(x => x <= useP).length;
      const pctile = Math.round(below / peSeries.length * 100);
      const pos = Math.max(2, Math.min(98, pctile));
      gauge = `<div style="font-size:9px;color:#64748b;margin-top:6px">5 年本益比區間定位（現值 PER ${fmt(useP, 1)} ≈ 第 ${pctile} 百分位）</div>
        <div class="val-gauge"><div class="mk" style="left:${pos}%"></div></div>
        <div class="val-lbl"><span>便宜 ${fmt(lo, 1)}x</span><span>中位 ${fmt(med, 1)}x</span><span>昂貴 ${fmt(hi, 1)}x</span></div>`;
      verdict = pctile <= 25 ? '<b class="val-dn">相對便宜</b>（接近歷史低本益比區）'
        : pctile >= 75 ? '<b class="val-up">相對昂貴</b>（接近歷史高本益比區）'
          : '<b>合理區間</b>（歷史本益比中段）';
      // 河流帶：各分位 PER × EPS = 對應股價
      const bands = [['便宜 5%', lo], ['偏低 25%', q1], ['中位 50%', med], ['偏高 75%', q3], ['昂貴 95%', hi]];
      let rows = bands.map(([lbl, p]) => {
        const target = p * eps;
        const gap = price ? (target - price) / price * 100 : null;
        return `<tr><td>${lbl}</td><td>${fmt(p, 1)}x</td><td>${fmt(target, 1)}</td><td class="${pcls(gap)}">${gap == null ? '—' : (gap >= 0 ? '+' : '') + gap.toFixed(1) + '%'}</td></tr>`;
      }).join('');
      river = `<table class="val-tbl"><tr><th>估值帶</th><th>PER</th><th>對應股價</th><th>距現價</th></tr>
        ${rows}<tr class="val-now"><td>現價</td><td>${fmt(useP, 1)}x</td><td>${fmt(price, 1)}</td><td>—</td></tr></table>`;
    } else {
      gauge = `<div class="val-note">缺 EPS_ttm 或歷史股價不足，無法繪製本益比河流。${mkt === 'TW' ? '（TWSE 本益比資料集可能當日尚未更新，盤後較完整）' : '（美股源 Yahoo：若持續缺值，請確認 server 已安裝 yfinance — pip install yfinance）'}</div>`;
    }

    const mktTag = !isTw
      ? '<span style="background:#1e3a5f;color:#7dd3fc;border-radius:4px;padding:1px 6px;font-size:9px">美股</span>'
      : '<span style="background:#3f1e2e;color:#fda4af;border-radius:4px;padding:1px 6px;font-size:9px">台股</span>';
    body.innerHTML = `<div style="font-size:11px;color:#94a3b8;margin-bottom:2px">${mktTag} ${v.code || sym}　EPS(近12月) ${fmt(eps, 2)}　現價 ${fmt(price, 1)}${v._source ? `　<span style="color:#475569;font-size:9px">源:${v._source}</span>` : ''}</div>
      ${kpi}
      ${verdict ? `<div style="font-size:12px;margin:4px 0">估值判讀：${verdict}</div>` : ''}
      ${gauge}${river}
      <div class="val-note">長線市場派視角：本益比河流回答「現在貴不貴」，但成長股的合理倍數會隨 AI 需求擴張上移——TSMC/台灣 AI 供應鏈在結構性擴張期，落在歷史高位不必然是賣點，需搭配營收動能與產業循環判讀。本表用「當前 EPS×歷史股價」近似，EPS 變動時河流會整體位移。⚠ 僅供參考、非投資建議。</div>`;
  }

  function open() {
    style();
    let m = document.getElementById('val-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'val-modal';
      m.innerHTML = `<div id="val-box"><h3>⚓ 長線估值錨 · 本益比河流</h3><div id="val-body">載入中…</div>
        <div style="text-align:right;margin-top:8px"><button onclick="window.valuationRefresh&&valuationRefresh()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer">↻ 重新整理</button>
        <button onclick="window.valuationClose&&valuationClose()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer;margin-left:6px">關閉</button></div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    m.style.display = 'flex';
    render();
  }
  function close() { const m = document.getElementById('val-modal'); if (m) m.style.display = 'none'; }

  window.valuationOpen = open;
  window.valuationClose = close;
  window.valuationRefresh = render;
})();

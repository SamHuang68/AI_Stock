// ============================================================
// Stock Terminal v3.0 — UI/UX Polish (per pro feedback)
// ------------------------------------------------------------
//   1. 移除底部指標列（資訊重複），改為市場總覽跑馬燈
//   2. 紅綠色慣例：TW（紅漲綠跌）/ US（綠漲紅跌）動態切換
//   3. K 線圖加入 SMA / 布林通道圖例
//   4. 成交量柱依當日方向 + 市場慣例上色（更強烈）
//   5. 在 K 線圖上畫昨收水平虛線
//   6. STATS 補 MKT CAP / P/E / P/B / Yield（從 /keystats 取）
// ============================================================

const SERVER_P = window.SERVER || `http://localhost:18432`;

// ============================================================
// CSS injection
// ============================================================
(function injectPolishCSS() {
  const css = `
/* (1) 隱藏底部指標列 — 改為大盤總覽 */
#indbar { display: none !important; }

/* 大盤總覽跑馬燈 — v3.1 觀察清單 chip 風格
   排版：行 1 = 名稱(灰小) 加權值(大白)；行 2 = ▲值 ▲% (小，紅漲綠跌台股慣例)
   配色：固定台股慣例 — 紅漲綠跌（不依 body.market-* class 切換）
*/
#mkt-bar {
  min-height: 76px; max-height: 92px;
  background: var(--bg2); border-top: 1px solid var(--border);
  flex-shrink: 0; overflow: hidden;
  font-family: 'JetBrains Mono', monospace; font-size: 10px;
}
/* v3.8: 大盤改 2 列 grid (column flow，8 指數 → 4 欄 x 2 列) */
#mkt-bar-inner {
  display: grid; grid-template-rows: repeat(2, 1fr);
  grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr);
  gap: 0; padding: 0;
}
.mkt-cell {
  display: flex; flex-direction: column; justify-content: center; align-items: flex-start;
  padding: 3px 12px; border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border); min-height: 36px;
  white-space: nowrap; min-width: 0; gap: 1px; overflow: hidden;
}
.mkt-cell .row1 {
  display: flex; align-items: baseline; gap: 6px;
}
.mkt-cell .nm {
  color: var(--tlo); font-size: 9px; letter-spacing: .5px; font-weight: 600;
  line-height: 1.1;
}
.mkt-cell .px {
  color: var(--thi); font-weight: 700; font-size: 12px; line-height: 1.1;
  letter-spacing: .2px;
}
.mkt-cell .row2 {
  display: flex; align-items: baseline; gap: 5px;
}
.mkt-cell .delta { font-weight: 600; font-size: 9px; line-height: 1.1; }
.mkt-cell .ch { font-weight: 700; font-size: 9.5px; line-height: 1.1; }
.mkt-cell.loading .px,
.mkt-cell.loading .delta,
.mkt-cell.loading .ch { color: var(--tf); }
/* 紅漲綠跌 — 大盤一律台股慣例 */
.mkt-cell .up   { color: var(--red); }
.mkt-cell .down { color: var(--green); }
.mkt-cell .flat { color: var(--tlo); }

/* (#3) 自選股 chip — 直立排版（代號上、漲跌下小字）
       讓單個 chip 從 ~80px 縮到 ~52px，可塞下 2 倍數量 */
.wlchip {
  flex-direction: row !important;
  gap: 4px !important;
  padding: 0 7px !important;
  min-width: 0 !important;
}
.wlchip-grip { flex-shrink: 0; }
.wlchip-t {
  display: block !important;
  font-size: 11px !important;
  line-height: 1.1 !important;
  letter-spacing: .3px !important;
}
.wlchip-p {
  display: block !important;
  font-size: 8.5px !important;
  line-height: 1 !important;
  margin-top: 1px !important;
}
.wlchip > .wlchip-t,
.wlchip > .wlchip-p {
  /* let them stack via a virtual column trick using flex-direction column on a wrapper.
     We render them in renderWl-wrapper instead — see JS below. */
}
.wlchip-stack {
  display: flex; flex-direction: column; align-items: flex-start;
  justify-content: center; line-height: 1; min-width: 0; flex-shrink: 1;
}
.wlchip-rm { flex-shrink: 0; }

/* (#2) 線型視窗上限 — 不超過 viewport 62%，下方留空給未來面板/可增大 wlbar */
#chartarea {
  max-height: 62vh;
}

/* (2) TW/US 顏色慣例 — 預設美股 (.up=green .down=red)，台股反過來 */
body.market-tw .price-up,   body.market-tw .pos { color: var(--red) !important; }
body.market-tw .price-down, body.market-tw .neg { color: var(--green) !important; }
body.market-us .price-up,   body.market-us .pos { color: var(--green) !important; }
body.market-us .price-down, body.market-us .neg { color: var(--red) !important; }

/* (3) Chart legend — 左下角，水平排版，避免擋到右側價格軸 + 上方 chart-info */
#chart-legend {
  position: absolute; bottom: 28px; left: 10px; z-index: 6;
  background: rgba(11, 18, 32, .75); border: 1px solid var(--border);
  border-radius: 4px; padding: 4px 9px;
  font-family: 'JetBrains Mono', monospace; font-size: 9px;
  color: var(--tlo); pointer-events: none;
  display: flex; flex-direction: row; flex-wrap: wrap; align-items: center;
  gap: 4px 10px; backdrop-filter: blur(4px); max-width: calc(100% - 80px);
}
#chart-legend .lg-row { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
#chart-legend .lg-line {
  display: inline-block; width: 12px; height: 2px; border-radius: 1px;
}
#chart-legend .lg-dash { background-image: linear-gradient(to right, currentColor 50%, transparent 50%); background-size: 4px 2px; background-repeat: repeat-x; height: 2px; }
#chart-legend.collapsed { padding: 3px 7px; opacity: .55; }
#chart-legend.collapsed .lg-row { display: none; }
#chart-legend.collapsed::before { content: 'i'; font-style: italic; color: var(--gold); font-weight: 700; }

/* (6) STATS keystats — emphasize the new rows */
.keystat-row { display: flex; justify-content: space-between; padding: 6px 12px; border-bottom: 1px solid var(--border); font-family: monospace; font-size: 10.5px; }
.keystat-row .k { color: var(--tlo); }
.keystat-row .v { color: var(--thi); font-weight: 700; }
.keystat-loading { padding: 8px 12px; color: var(--tf); font-family: monospace; font-size: 9.5px; font-style: italic; }
`;
  const s = document.createElement('style'); s.id = 'polish-v3-styles'; s.textContent = css;
  document.head.appendChild(s);
})();

// ============================================================
// (1) Market overview ticker bar — replaces removed indbar
// ============================================================
const MKT_INDICES = [
  {sym:'^TWII', name:'加權'},
  {sym:'__TXF__', name:'台指期'},   // TAIFEX 即時(含夜盤)，特例來源 /txf
  {sym:'^TWOII', name:'櫃買'},
  {sym:'^SOX',  name:'費半'},
  {sym:'^GSPC', name:'S&P500'},
  {sym:'^IXIC', name:'NASDAQ'},
  {sym:'^DJI',  name:'道瓊'},
  {sym:'^N225', name:'日經'},
  {sym:'^HSI',  name:'恆生'},
  {sym:'^KS11', name:'韓國'},      // KOSPI
  {sym:'GC=F',  name:'黃金'},      // COMEX 黃金期貨
  {sym:'SI=F',  name:'白銀'},      // COMEX 白銀期貨
  {sym:'CL=F',  name:'原油'},      // WTI 原油期貨
];

(function injectMktBar() {
  if (!document.getElementById('left')) return setTimeout(injectMktBar, 100);
  if (document.getElementById('mkt-bar')) return;
  const bar = document.createElement('div');
  bar.id = 'mkt-bar';
  bar.innerHTML = '<div id="mkt-bar-inner">' +
    MKT_INDICES.map(m =>
      // v3.1 觀察清單風格雙列：
      //   行 1：指數名（小灰）+ 加權值（大字）
      //   行 2：▲漲跌值 ▲漲跌% （小字、台股紅漲綠跌）
      `<div class="mkt-cell loading" data-mkt-sym="${m.sym}">
        <div class="row1">
          <span class="nm">${m.name}</span>
          <span class="px">--</span>
        </div>
        <div class="row2">
          <span class="delta">--</span>
          <span class="ch">--</span>
        </div>
      </div>`
    ).join('') + '</div>';
  const left = document.getElementById('left');
  const indbar = document.getElementById('indbar');
  if (indbar) left.insertBefore(bar, indbar.nextSibling);
  else left.appendChild(bar);
  refreshMktBar();
  setInterval(refreshMktBar, 60_000);
})();

// 數字格式：千分位 + 小數位（指數通常 2 位，但點數 < 100 顯示 3 位）
function fmtIdx(v) {
  if (v == null || !isFinite(v)) return '--';
  const dp = Math.abs(v) >= 100 ? 2 : 3;
  return v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

async function refreshMktBar() {
  try {
    const syms = MKT_INDICES.filter(m => m.sym !== '__TXF__').map(m => m.sym).join(',');
    // v3.3 改 range=5d：原 range=2d 只有兩根 K，遇到 Yahoo 日線資料落後
    //   於 regularMarketPrice 時無法做時間軸交叉驗證，會直接用「昨日的
    //   昨日 vs 前日」算出昨日的 % 變化（櫃買/日經顯示 0.00% 即此 bug）。
    //   5d 給 5 根 K，搭配下方 rmt vs lastTs 比對能精準判斷哪根才是「今天」。
    const r = await fetch(`${SERVER_P}/yf/batch?syms=${encodeURIComponent(syms)}&range=5d&interval=1d`, {cache:'no-store'});
    if (!r.ok) return;
    const data = await r.json();
    for (const m of MKT_INDICES) {
      const d = data[m.sym];
      if (!d) continue;
      const res = d?.chart?.result?.[0];
      if (!res) continue;
      const meta = res.meta || {};
      const tsArr = res.timestamp || [];
      const rawCloses = res.indicators?.quote?.[0]?.close || [];
      const valid = [];
      for (let i = 0; i < Math.min(tsArr.length, rawCloses.length); i++) {
        if (rawCloses[i] != null && isFinite(rawCloses[i]) && tsArr[i] != null) {
          valid.push({ t: tsArr[i], c: rawCloses[i] });
        }
      }
      if (valid.length < 1) continue;
      const last = valid[valid.length - 1];
      const prevC = valid.length >= 2 ? valid[valid.length - 2].c : null;
      const rmt = meta.regularMarketTime;
      const rmp = meta.regularMarketPrice;
      // ── Yahoo 日線落後修正 ──
      // 若 rmt 比最後一根 K 線晚 > 20h，rmp 才是「今天」，last.c 是「昨天」
      let cur, prev;
      if (rmt && rmp != null && isFinite(rmp) && rmp > 0 && rmt - last.t > 20 * 3600) {
        cur = rmp; prev = last.c;
      } else {
        cur = last.c;
        prev = prevC != null ? prevC : (meta.chartPreviousClose || meta.previousClose);
      }
      if (cur == null || prev == null || !isFinite(prev) || prev <= 0) continue;
      const delta = cur - prev;
      const chgPct = delta / prev * 100;
      const cell = document.querySelector(`[data-mkt-sym="${m.sym}"]`);
      if (!cell) continue;
      cell.classList.remove('loading');
      cell.querySelector('.px').textContent = fmtIdx(cur);

      // ── 漲跌色：固定台股紅漲綠跌（與大盤 bar 慣例一致）──
      const dir = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
      const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';
      const dEl = cell.querySelector('.delta');
      dEl.className = 'delta ' + dir;
      dEl.textContent = sign + Math.abs(delta).toFixed(Math.abs(delta) >= 100 ? 0 : 2);
      const ch = cell.querySelector('.ch');
      ch.className = 'ch ' + dir;
      const arrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '－';
      ch.textContent = arrow + Math.abs(chgPct).toFixed(2) + '%';
    }
  } catch (e) { console.warn('[polish-v3] mktbar refresh failed:', e); }
  // 台指期(含夜盤) — TAIFEX 特例來源
  try { await refreshTxfCell(); } catch (e) { console.warn('[polish-v3] txf failed:', e); }
}

async function refreshTxfCell() {
  const cell = document.querySelector('[data-mkt-sym="__TXF__"]');
  if (!cell) return;
  const r = await fetch(`${SERVER_P}/txf`, { cache: 'no-store' });
  if (!r.ok) return;
  const d = await r.json();
  if (!d || !d.ok || d.price == null) return;
  cell.classList.remove('loading');
  cell.querySelector('.px').textContent = fmtIdx(d.price);
  const chg = d.changePct;
  const dir = chg > 0 ? 'up' : chg < 0 ? 'down' : 'flat';
  const sign = chg > 0 ? '+' : chg < 0 ? '−' : '';
  const delta = (d.prevClose != null) ? (d.price - d.prevClose) : null;
  const dEl = cell.querySelector('.delta');
  dEl.className = 'delta ' + dir;
  dEl.textContent = delta != null ? sign + Math.abs(delta).toFixed(0) : '';
  const ch = cell.querySelector('.ch');
  ch.className = 'ch ' + dir;
  const arrow = chg > 0 ? '▲' : chg < 0 ? '▼' : '－';
  ch.textContent = (chg != null) ? arrow + Math.abs(chg).toFixed(2) + '%' : '';
}

// ============================================================
// (2) TW/US color convention — auto switch on market change
// ============================================================
function applyMarketColorClass(mkt) {
  document.body.classList.remove('market-tw', 'market-us');
  document.body.classList.add(mkt === 'TW' ? 'market-tw' : 'market-us');
}
// Initial + on market change
(function bootMktColor() {
  applyMarketColorClass(S.mkt || 'TW');
  // Hook setMkt to also apply color class
  if (typeof setMkt === 'function') {
    const orig = window.setMkt;
    window.setMkt = function (mkt) {
      orig.apply(this, arguments);
      applyMarketColorClass(mkt);
      // 重繪線型（candle 色要重套）
      if (S.data?.candles && typeof renderChart === 'function') {
        setTimeout(() => renderChart(S.data.candles), 50);
      }
    };
  }
})();
// Patch ci-chg color update (loadSym sets .style.color directly) to use class
(function patchCiChg() {
  // After symLoaded, fix the ci-chg color via class instead of inline
  // 與 loadSym 同步邏輯：intraday 用 yesterdayClose（= chartPreviousClose），
  // daily 用 prev candle close；避免 5min K 倒數第二根當作昨收的色彩誤判。
  window.addEventListener('symLoaded', () => {
    const el = document.getElementById('ci-chg');
    if (!el || !S.data?.candles?.length) return;
    const last = S.data.candles[S.data.candles.length - 1];
    const prev = S.data.candles[S.data.candles.length - 2];
    const ref = (S.data.yesterdayClose != null && S.data.yesterdayClose > 0)
      ? S.data.yesterdayClose
      : (prev ? prev.close : null);
    if (ref == null) return;
    const up = last.close >= ref;
    el.classList.remove('price-up', 'price-down');
    el.classList.add(up ? 'price-up' : 'price-down');
    el.style.color = '';   // clear inline; let class win
  });
})();

// ============================================================
// (3) Chart legend + (4) volume color + (5) prev close line
// All applied by patching renderChart
// ============================================================
(function patchRenderChartPolish() {
  if (typeof renderChart !== 'function') return setTimeout(patchRenderChartPolish, 100);
  if (window._polishChartPatched) return;
  window._polishChartPatched = true;
  const orig = window.renderChart;
  window.renderChart = function (candles) {
    // TW/US: swap candle up/down colors before original render reads them
    const tw = (S.mkt || 'TW') === 'TW';
    const UP = tw ? '#F87171' : '#4ADE80';   // TW red-up / US green-up
    const DN = tw ? '#4ADE80' : '#F87171';
    // Temporarily override CSS vars for the chart series creation
    document.documentElement.style.setProperty('--chart-up', UP);
    document.documentElement.style.setProperty('--chart-down', DN);

    orig.apply(this, arguments);

    // After orig renders, post-process:
    setTimeout(() => {
      try {
        // (a) Candle re-color via series.applyOptions
        if (S.chartSeries) {
          S.chartSeries.applyOptions({
            upColor: UP, downColor: DN,
            borderUpColor: UP, borderDownColor: DN,
            wickUpColor: UP, wickDownColor: DN,
          });
        }
        // (b) Volume bars: re-set with stronger colors + market convention
        // 套用同一份 tz 平移（與 renderChart 一致），避免 volume 軸跟 candle 軸錯位
        if (S.volSeries && S.data?.candles) {
          const upAlpha = 'rgba(' + (tw ? '248,113,113' : '74,222,128') + ',0.55)';
          const dnAlpha = 'rgba(' + (tw ? '74,222,128' : '248,113,113') + ',0.55)';
          const _tz = (S.tzOffset && isFinite(S.tzOffset)) ? S.tzOffset : 0;
          S.volSeries.setData(S.data.candles.map(c => ({
            time: c.time + _tz, value: c.volume,
            color: c.close >= c.open ? upAlpha : dnAlpha,
          })));
        }
        // (c) Previous close line
        // For daily K: prev candle = yesterday's close
        // For intraday (1天 / 5m): use S.data.yesterdayClose set by loadSym
        //   (= meta.chartPreviousClose). The second-to-last 5min K is NOT
        //   yesterday's close — it's the previous 5min bar (~4345 vs real 4640).
        if (S.chartSeries && S.data?.candles?.length >= 1) {
          if (S._prevLine) try { S.chartSeries.removePriceLine(S._prevLine); } catch {}
          const cands = S.data.candles;
          const last = cands[cands.length - 1];
          const prev = cands.length >= 2 ? cands[cands.length - 2] : null;
          const yPrice = (S.data.yesterdayClose != null && S.data.yesterdayClose > 0)
            ? S.data.yesterdayClose
            : (prev ? prev.close : null);
          if (yPrice != null && yPrice > 0) {
            S._prevLine = S.chartSeries.createPriceLine({
              price: yPrice,
              color: 'rgba(200, 200, 200, .35)',
              lineWidth: 1,
              lineStyle: LightweightCharts.LineStyle.Dashed,
              axisLabelVisible: false,           // 不顯示浮動大框，改用右下小字讀數
              title: '',
            });
          }
          renderCloseReadout(last ? last.close : null, yPrice);
        }
        // (d) Legend overlay
        renderChartLegend();
      } catch (e) { console.warn('[polish-v3] post-render error:', e); }
    }, 60);
  };
})();

// 在右側價格軸「對應價位高度」放昨收/今收小標籤（不橫跨、不蓋 K 線）
// 像原生現價標一樣貼在軸上，今收=漲跌色、昨收=灰。
function renderCloseReadout(close, prevClose) {
  const wrap = document.getElementById('chart-wrap');
  if (!wrap || !S.chartSeries) return;
  // 清掉舊版底部框 + 舊標籤
  ['close-readout', 'ctag-now', 'ctag-prev'].forEach(id => {
    const e = document.getElementById(id); if (e) e.remove();
  });
  const tw = document.body.classList.contains('market-tw') || S.mkt === 'TW';
  // 半字級小標籤，貼在 Y 軸刻度數字右邊（不蓋刻度），對應價位高度
  const mk = (id, price, prefix, color) => {
    if (price == null || price <= 0) return;
    let y; try { y = S.chartSeries.priceToCoordinate(price); } catch { y = null; }
    if (y == null) return;
    const el = document.createElement('div');
    el.id = id;
    el.textContent = `${prefix}${price.toFixed(2)}`;
    el.style.cssText = `position:absolute;right:1px;top:${y}px;transform:translateY(-50%);` +
      `z-index:7;pointer-events:none;font-family:'JetBrains Mono',monospace;font-size:6.5px;` +
      `font-weight:700;color:${color};text-shadow:0 0 3px #000,0 0 3px #000;white-space:nowrap`;
    wrap.appendChild(el);
  };
  // 今收：依漲跌上色（台股紅漲綠跌）；昨收：灰
  let nowCol = 'var(--tlo)';
  if (prevClose != null && prevClose > 0) {
    const up = close >= prevClose;
    nowCol = up ? (tw ? '#f87171' : '#4ade80') : (tw ? '#4ade80' : '#f87171');
  }
  mk('ctag-now', close, '今', nowCol);
  mk('ctag-prev', prevClose, '昨', 'rgba(190,195,205,.9)');
}

function renderChartLegend() {
  const wrap = document.getElementById('chart-wrap');
  if (!wrap) return;
  let lg = document.getElementById('chart-legend');
  if (!lg) {
    lg = document.createElement('div');
    lg.id = 'chart-legend';
    lg.title = '點擊可摺疊';
    lg.style.cursor = 'pointer';
    lg.style.pointerEvents = 'auto';
    lg.addEventListener('click', e => { e.stopPropagation(); lg.classList.toggle('collapsed'); });
    wrap.appendChild(lg);
  }
  // 不顯示 K 線紅/綠（一眼可見不必標註），只標均線/BB/昨收這些「需要解碼」的線
  lg.innerHTML = `
    <div class="lg-row"><span class="lg-line" style="background:#FBBF24"></span>SMA 20</div>
    <div class="lg-row"><span class="lg-line" style="background:#67E8F9"></span>SMA 60</div>
    <div class="lg-row" style="color:rgba(96,165,250,.85)"><span class="lg-dash" style="width:12px;color:rgba(96,165,250,.85)"></span>BB</div>
    <div class="lg-row" style="color:rgba(200,200,200,.55)"><span class="lg-dash" style="width:12px;color:rgba(200,200,200,.55)"></span>昨收</div>
  `;
}

// ============================================================
// (6) Key Stats — fetch MKT CAP / P/E / P/B / Yield from /keystats
// ============================================================
const _keystatsCache = {};
async function fetchKeyStats(sym, mkt) {
  if (!sym) return null;
  const key = sym + '|' + (mkt || 'TW');
  if (_keystatsCache[key]) return _keystatsCache[key];
  const yfsym = mkt === 'TW' ? sym + '.TW' : sym;
  try {
    const r = await fetch(`${SERVER_P}/keystats/${yfsym}`, {cache:'no-store'});
    if (!r.ok) return null;
    const data = await r.json();
    _keystatsCache[key] = data;
    return data;
  } catch (e) { console.warn('[keystats] fetch error:', e); return null; }
}

function fmtBig(n, unit) {
  if (n == null || !isFinite(n)) return '--';
  if (Math.abs(n) >= 1e12) return (n/1e12).toFixed(2) + ' 兆';
  if (Math.abs(n) >= 1e8)  return (n/1e8).toFixed(2) + ' 億';
  if (Math.abs(n) >= 1e4)  return (n/1e4).toFixed(1) + ' 萬';
  return n.toLocaleString();
}

// Patch renderStats to inject key stats inline (replace MKT CAP placeholder)
(function patchStatsKeystats() {
  if (typeof renderStats !== 'function') return setTimeout(patchStatsKeystats, 100);
  // Need to wrap whatever's currently there (chip_v3.js also wraps it)
  const prev = window.renderStats;
  window.renderStats = function () {
    let h = prev.apply(this, arguments);
    if (!S.sym) return h;
    // Async fetch and inject — find element and update after render
    fetchKeyStats(S.sym, S.mkt).then(ks => {
      if (!ks) return;
      // Update existing MKT CAP cell (if v1 stats has one)
      const sect = document.getElementById('keystats-sect');
      const html = renderKeystatsSection(ks);
      if (sect) sect.outerHTML = html;
      else {
        const rp = document.getElementById('rpanel');
        if (!rp || S.tab !== 'stats') return;
        // Insert before chip-sect if exists, else append
        const chipSect = document.getElementById('chip-sect');
        if (chipSect) chipSect.insertAdjacentHTML('beforebegin', html);
        else rp.insertAdjacentHTML('beforeend', html);
      }
    });
    // Add loading placeholder
    return h + `<div id="keystats-sect"><div class="stat-sect">關鍵估值</div><div class="keystat-loading">載入中...</div></div>`;
  };
})();

function renderKeystatsSection(ks) {
  const mc = ks.marketCap;
  const pe = ks.trailingPE;
  const pb = ks.priceToBook;
  const yld = ks.dividendYield;
  const eps = ks.eps;
  const epsCurrency = ks.currency || (S.mkt === 'TW' ? 'TWD' : 'USD');
  let h = '<div id="keystats-sect"><div class="stat-sect">關鍵估值 · ' + S.sym + '</div>';
  h += `<div class="keystat-row"><span class="k">市值 MKT CAP</span><span class="v">${fmtBig(mc)}${mc != null ? ' ' + epsCurrency : ''}</span></div>`;
  h += `<div class="keystat-row"><span class="k">本益比 P/E</span><span class="v" style="color:${pe != null ? (pe < 15 ? 'var(--green)' : pe > 30 ? 'var(--red)' : 'var(--thi)') : 'var(--tlo)'}">${pe != null ? pe.toFixed(2) : '--'}</span></div>`;
  h += `<div class="keystat-row"><span class="k">股價淨值比 P/B</span><span class="v" style="color:${pb != null ? (pb < 1.5 ? 'var(--green)' : pb > 5 ? 'var(--red)' : 'var(--thi)') : 'var(--tlo)'}">${pb != null ? pb.toFixed(2) : '--'}</span></div>`;
  h += `<div class="keystat-row"><span class="k">殖利率 Yield</span><span class="v" style="color:${yld != null ? (yld > 4 ? 'var(--green)' : 'var(--thi)') : 'var(--tlo)'}">${yld != null ? yld.toFixed(2) + '%' : '--'}</span></div>`;
  if (eps != null) h += `<div class="keystat-row"><span class="k">EPS</span><span class="v">${eps.toFixed(2)} ${epsCurrency}</span></div>`;
  if (ks._source) h += `<div style="padding:4px 12px;font-family:monospace;font-size:8px;color:var(--tf)">資料源：${ks._source}</div>`;
  h += '</div>';
  return h;
}

// ============================================================
// (#3) Patch renderWl to wrap code + pct in vertical stack
// 這樣每個 chip 從橫向 ~80px 縮到 ~52px，可放 2 倍數量
// ============================================================
(function patchRenderWl() {
  if (typeof renderWl !== 'function') return setTimeout(patchRenderWl, 100);
  if (window._polishWlPatched) return;
  window._polishWlPatched = true;
  const orig = window.renderWl;
  window.renderWl = function () {
    orig.apply(this, arguments);
    // After v1 renders chips, restructure: wrap .wlchip-t + .wlchip-p in a .wlchip-stack
    const ct = document.getElementById('wlchips');
    if (!ct) return;
    ct.querySelectorAll('.wlchip').forEach(chip => {
      if (chip.dataset._stacked) return;
      const t = chip.querySelector('.wlchip-t');
      const p = chip.querySelector('.wlchip-p');
      if (!t || !p || t.parentElement !== chip) return;
      const stack = document.createElement('div');
      stack.className = 'wlchip-stack';
      chip.insertBefore(stack, t);
      stack.appendChild(t);
      stack.appendChild(p);
      chip.dataset._stacked = '1';
    });
  };
  // Trigger once if already rendered
  if (document.getElementById('wlchips')?.children.length) {
    try { window.renderWl(); } catch {}
  }
})();

// Expose
window.refreshMktBar  = refreshMktBar;
window.fetchKeyStats  = fetchKeyStats;
window.applyMarketColorClass = applyMarketColorClass;

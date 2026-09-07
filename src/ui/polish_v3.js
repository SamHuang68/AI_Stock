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

const SERVER_P = window.SERVER || ((typeof location !== 'undefined' && location.origin) ? location.origin : 'http://localhost:18432');

// 台股代號判定(數字開頭如 2308/00685L,或 ^TW 指數)。台股紅綠慣例應依「標的本身」,
// 不受 TW/US 市場鈕(S.mkt)影響 —— 否則在 US 鈕時看台股/台股指數會套成美股慣例。
function _isTwSym(s) { return window.Colors ? Colors.isTW(s) : (/^\d/.test(String(s || '')) || /^\^TW/i.test(String(s || ''))); }
function _isRedUpSym(s) {
  if (window.Colors && Colors.isRedUp) return Colors.isRedUp(s);
  return _isTwSym(s) || /^\d{4}\.T$/i.test(String(s || '')) || String(s || '').toUpperCase() === '^N225';
}

// ============================================================
// CSS injection
// ============================================================
(function injectPolishCSS() {
  const css = `
/* (1) 隱藏底部指標列 — 改為大盤總覽 */
#indbar { display: none !important; }

/* 大盤總覽 — 兩個 tab（大盤／市場）避免一列塞滿混淆
   左側垂直 tab，右側單一 panel 顯示對應格
*/
#mkt-bar {
  display: flex; align-items: stretch;
  min-height: 72px; max-height: 88px;
  background: var(--bg2); border-top: 1px solid var(--border);
  flex-shrink: 0; overflow: hidden;
  font-family: 'JetBrains Mono', monospace; font-size: 10px;
}
#mkt-bar-tabs {
  display: flex; flex-direction: column; flex-shrink: 0;
  width: 40px; border-right: 1px solid var(--border); background: var(--bg);
}
.mkt-tab {
  flex: 1; display: flex; align-items: center; justify-content: center;
  writing-mode: vertical-rl; text-orientation: mixed;
  letter-spacing: 2px; font-size: 11px; font-weight: 700;
  color: var(--tlo); background: transparent; border: none;
  border-bottom: 1px solid var(--border); cursor: pointer;
  padding: 0; font-family: inherit;
}
.mkt-tab:last-child { border-bottom: none; }
.mkt-tab:hover { color: var(--thi); background: rgba(255,255,255,.04); }
.mkt-tab.on {
  color: var(--thi); background: var(--bg2);
  box-shadow: inset 2px 0 0 var(--gold, #F5C518);
}
#mkt-bar-panels { flex: 1; min-width: 0; position: relative; }
.mkt-panel { display: none; height: 100%; }
.mkt-panel.on { display: block; }
#mkt-bar-inner, .mkt-bar-inner {
  display: grid; grid-template-rows: repeat(2, 1fr);
  grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr);
  gap: 0; padding: 0; height: 100%;
}
.mkt-cell {
  display: flex; flex-direction: column; justify-content: center; align-items: flex-start;
  padding: 3px 12px; border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border); min-height: 36px;
  white-space: nowrap; min-width: 0; gap: 1px; overflow: hidden;
  cursor: pointer; transition: background .12s;
}
.mkt-cell:hover { background: rgba(255,255,255,.06); }
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
/* 紅漲綠跌 — 大盤一律台股慣例（美股格由 JS 依 redUp 覆寫） */
.mkt-cell .up   { color: var(--red); }
.mkt-cell .down { color: var(--green); }
.mkt-cell .flat { color: var(--tlo); }

/* (#3) 自選股 chip — 台股使用 2×2：名稱｜漲跌、代號｜ETF＋−。 */
.wlchip {
  flex-direction: row !important;
  gap: 4px !important;
  padding: 0 7px !important;
  min-width: 0 !important;
}
.wlchip-grip { flex-shrink: 0; }
.wlchip-t {
  display: block !important;
  font-size: 10px !important;
  line-height: 1.05 !important;
  letter-spacing: .2px !important;
  min-width: 0 !important;
  max-width: 48px !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  white-space: nowrap !important;
}
.wlchip-c {
  display: inline-block !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 7px !important;
  color: var(--tlo) !important;
  line-height: .95 !important;
  margin: 0 !important;
}
.wlchip-p {
  display: inline-block !important;
  font-size: 8px !important;
  line-height: 1 !important;
  margin: 0 !important;
}
.wlchip > .wlchip-t,
.wlchip > .wlchip-p {
  /* let them stack via a virtual column trick using flex-direction column on a wrapper.
     We render them in renderWl-wrapper instead — see JS below. */
}
.wlchip-stack {
  display: flex; flex-direction: column; align-items: flex-start;
  justify-content: center; gap: 1px; line-height: 1; min-width: 0; max-width: 52px;
  flex-shrink: 1; padding: 1px 0 !important;
}
.wlchip[data-mkt="TW"] .wlchip-stack {
  width: 76px; max-width: 76px; flex: 0 0 76px;
}
.wlchip-primary,
.wlchip-meta {
  display: grid; grid-template-columns: minmax(0, 1fr) max-content;
  align-items: baseline; column-gap: 2px; width: 100%; min-width: 0;
  min-height: 8px; line-height: 1;
}
.wlchip-primary { min-height: 10px; }
.wlchip-primary .wlchip-t { max-width: none !important; }
.wlchip-primary .wlchip-p,
.wlchip-meta .etf-flow-badge { justify-self: end; }
.wlchip-meta .wlchip-c { justify-self: start; }
.wlchip[data-mkt="US"] .wlchip-meta {
  display: flex; align-items: baseline; justify-content: flex-start; gap: 2px;
}
/* (#2) 線型視窗上限 — 不超過 viewport 62%，下方留空給未來面板/可增大 wlbar */
#chartarea {
  max-height: 62vh;
}

/* (2) TW/US 顏色慣例 — 預設美股 (.up=green .down=red)，台股反過來 */
body.market-tw .price-up   { color: var(--red) !important; }
body.market-tw .price-down { color: var(--green) !important; }
body.market-jp .price-up   { color: var(--red) !important; }
body.market-jp .price-down { color: var(--green) !important; }
body.market-us .price-up   { color: var(--green) !important; }
body.market-us .price-down { color: var(--red) !important; }

/* (3) Chart legend — v3.8.1 整合進大浮動視窗右下角；
       chart-info 改兩欄：左=價格/漲跌/名稱(窄欄)，右=OHLC視窗緊貼股價後 + 圖例。
       視窗縮小約一半(字級/間距減)、半透明，避免遮到 K 線。 */
#ci-row { display: flex; align-items: flex-start; gap: 8px; }
#ci-row .ci-left { min-width: 0; max-width: 220px; }
#ci-row .ci-left #ci-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#ci-row .ci-left .ci-high { font-size: 12px; font-weight: 700; margin-top: 3px; color: var(--gold); line-height: 1.3; }
#ci-row .ci-left .ci-high b { color: var(--thi); font-size: 13px; }
#ci-row .ci-left .ci-range-chg { font-size: 10px; line-height: 1.35; }
#ci-east { display: flex; flex-direction: column; align-items: flex-end; }
#ci-east #ci-ohlc {
  margin-top: 0; font-size: 8px; line-height: 1.5; letter-spacing: .2px;
  padding: 2px 6px; max-width: 330px;
}
#ci-east #ci-ohlc .ohlc-d { margin-right: 5px; }
#ci-east #ci-ohlc .ohlc-v { margin-right: 5px; }
#ci-east #ci-ohlc .ma-row { font-size: 7.5px; margin-top: 1px; }
#ci-east #ci-ohlc .ma-row span { margin-right: 6px; }
#chart-legend {
  margin-top: 2px;
  background: rgba(11, 18, 32, .75); border: 1px solid var(--border);
  border-radius: 4px; padding: 2px 6px;
  font-family: 'JetBrains Mono', monospace; font-size: 7.5px;
  color: var(--tlo); pointer-events: auto;
  display: flex; flex-direction: row; flex-wrap: wrap; align-items: center;
  gap: 3px 7px; backdrop-filter: blur(4px);
}
#chart-legend .lg-row { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
#chart-legend .lg-line {
  display: inline-block; width: 9px; height: 2px; border-radius: 1px;
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
// (1) Market overview ticker bar — 大盤 / 市場 雙 tab
// ------------------------------------------------------------
// 大盤：台股現貨／期／融資／台總經
// 市場：美總經／全球指數／商品
// ============================================================
const MKT_TABS = {
  tw: {
    id: 'tw',
    label: '大盤',
    title: '台股大盤（加權／期／櫃買／融資／融資週期／台利率）',
    items: [
      {sym:'^TWII', name:'加權'},
      {sym:'__TXF__', name:'台指期'},
      {sym:'^TWOII', name:'櫃買'},
      {sym:'__MARGIN_RATIO__', name:'融資維持'},
      {sym:'__TW_MARGIN_CYCLE__', name:'融資週期'},
      {sym:'__TW_RATES__', name:'台利率'},
      {sym:'__TW_MARGIN_MIX__', name:'融資比YoY'},
    ],
  },
  mkt: {
    id: 'mkt',
    label: '市場',
    title: '全球市場（美總經／指數／商品）',
    items: [
      {sym:'__US_RATES_CREDIT__', name:'美利率債'},
      {sym:'__US_CPI_FIN__', name:'CPI金融'},
      {sym:'^SOX',  name:'費半',  redUp:false},
      {sym:'^GSPC', name:'S&P500',redUp:false},
      {sym:'^IXIC', name:'NASDAQ',redUp:false},
      {sym:'^DJI',  name:'道瓊',  redUp:false},
      {sym:'^N225', name:'日經'},
      {sym:'^HSI',  name:'恆生'},
      {sym:'^KS11', name:'韓國'},
      {sym:'GC=F',  name:'黃金'},
      {sym:'SI=F',  name:'白銀'},
      {sym:'CL=F',  name:'原油'},
    ],
  },
};
// 扁平清單（refresh 迴圈仍用）
const MKT_INDICES = [].concat(MKT_TABS.tw.items, MKT_TABS.mkt.items);

function _mktCellHtml(m) {
  return `<div class="mkt-cell loading" data-mkt-sym="${m.sym}" title="點擊載入 ${m.name}">
    <div class="row1">
      <span class="nm">${m.name}</span>
      <span class="px">--</span>
    </div>
    <div class="row2">
      <span class="delta">--</span>
      <span class="ch">--</span>
    </div>
  </div>`;
}

function setMktBarTab(tabId, persist) {
  const id = (tabId === 'mkt') ? 'mkt' : 'tw';
  const bar = document.getElementById('mkt-bar');
  if (!bar) return;
  bar.querySelectorAll('.mkt-tab').forEach(btn => {
    btn.classList.toggle('on', btn.getAttribute('data-mkt-tab') === id);
  });
  bar.querySelectorAll('.mkt-panel').forEach(p => {
    p.classList.toggle('on', p.getAttribute('data-mkt-panel') === id);
  });
  if (persist !== false) {
    try { localStorage.setItem('stockTerminal.mktBarTab', id); } catch (_) {}
  }
}

(function injectMktBar() {
  if (!document.getElementById('left')) return setTimeout(injectMktBar, 100);
  if (document.getElementById('mkt-bar')) return;

  let saved = 'tw';
  try {
    const v = localStorage.getItem('stockTerminal.mktBarTab');
    if (v === 'mkt' || v === 'tw') saved = v;
  } catch (_) {}

  const bar = document.createElement('div');
  bar.id = 'mkt-bar';
  bar.innerHTML =
    `<div id="mkt-bar-tabs" role="tablist" aria-label="大盤與市場">` +
      Object.values(MKT_TABS).map(t =>
        `<button type="button" class="mkt-tab${t.id === saved ? ' on' : ''}" role="tab"` +
        ` data-mkt-tab="${t.id}" title="${t.title}" aria-selected="${t.id === saved}">${t.label}</button>`
      ).join('') +
    `</div>` +
    `<div id="mkt-bar-panels">` +
      Object.values(MKT_TABS).map(t =>
        `<div class="mkt-panel${t.id === saved ? ' on' : ''}" data-mkt-panel="${t.id}" role="tabpanel">` +
          `<div class="mkt-bar-inner">${t.items.map(_mktCellHtml).join('')}</div>` +
        `</div>`
      ).join('') +
    `</div>`;

  const left = document.getElementById('left');
  const indbar = document.getElementById('indbar');
  if (indbar) left.insertBefore(bar, indbar.nextSibling);
  else left.appendChild(bar);

  bar.addEventListener('click', function (e) {
    const tabBtn = e.target.closest && e.target.closest('.mkt-tab');
    if (tabBtn) {
      setMktBarTab(tabBtn.getAttribute('data-mkt-tab'));
      return;
    }
    const cell = e.target.closest && e.target.closest('.mkt-cell');
    if (!cell) return;
    const sym = cell.getAttribute('data-mkt-sym');
    if (!sym) return;
    if (typeof loadSym === 'function') {
      const mkt = (typeof Market !== 'undefined' && Market.of) ? Market.of(sym) : 'US';
      loadSym(sym, mkt);
    }
  });

  window.setMktBarTab = setMktBarTab;
  refreshMktBar();
  setInterval(refreshMktBar, 60_000);
})();

// 數字格式：千分位 + 小數位（指數通常 2 位，但點數 < 100 顯示 3 位）
function fmtIdx(v) {
  if (v == null || !isFinite(v)) return '--';
  const dp = Math.abs(v) >= 100 ? 2 : 3;
  return v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

/**
 * 市場總覽列的唯一漲跌上色入口。
 * 每次資料源覆寫都同時更新 class 與 inline color，避免 Yahoo 先畫的舊色
 * 殘留到 TWSE／TAIFEX 最新值；redUp=true 為台股／東亞，false 為美股／商品。
 */
function applyMktCellTone(cell, value, redUp) {
  if (!cell) return 'flat';
  const dir = value > 0 ? 'up' : value < 0 ? 'down' : 'flat';
  const col = window.Colors && Colors.dirRU
    ? Colors.dirRU(redUp !== false, value)
    : (value > 0 ? (redUp !== false ? 'var(--red)' : 'var(--green)')
      : value < 0 ? (redUp !== false ? 'var(--green)' : 'var(--red)') : 'var(--tlo)');
  ['.delta', '.ch'].forEach(sel => {
    const el = cell.querySelector(sel);
    if (!el) return;
    el.className = sel.slice(1) + ' ' + dir;
    el.style.color = col; // overwrite stale inline color from every prior source
  });
  return dir;
}

function renderCanonicalMarketQuote(sym, quote) {
  const cell = document.querySelector(`[data-mkt-sym="${sym}"]`);
  const m = quote && (quote.market || quote);
  if (!cell || !m || m.price == null) return;
  const delta = m.displayChange != null ? Number(m.displayChange) : (Number(m.price) - Number(m.referencePrice));
  const pct = m.displayChangePct != null ? Number(m.displayChangePct) : null;
  cell.classList.remove('loading');
  cell.querySelector('.px').textContent = fmtIdx(m.price);
  applyMktCellTone(cell, delta, true);
  const dEl = cell.querySelector('.delta');
  const ch = cell.querySelector('.ch');
  if (dEl) dEl.textContent = isFinite(delta) ? (delta > 0 ? '+' : '') + delta.toFixed(Math.abs(delta) >= 100 ? 0 : 2) : '--';
  if (ch) ch.textContent = pct != null && isFinite(pct) ? (pct > 0 ? '▲' : pct < 0 ? '▼' : '—') + Math.abs(pct).toFixed(2) + '%' : '--';
  cell.title = `${m.source || 'unknown'} · ${m.session || 'regular'} · ${m.referenceType || 'previous_close'} · ${m.asOf || ''}`;
}

/**
 * 台指期主圖與大盤列必須吃同一份 /txf（TAIFEX MIS）。
 * FinMind 日線只保留歷史日盤；日盤收盤後把最後一根 K 的 H/L/C 覆寫成當前盤
 * （夜盤優先），標題漲跌基準改用 /txf.prevClose（日盤結算），避免 K 停在
 * 日收而下方已在走夜盤。
 */
function normalizeTxfLiveQuote(raw) {
  if (!raw) return null;
  const m = raw.market || {};
  const price = Number(raw.price != null ? raw.price : m.price);
  if (!(price > 0)) return null;
  const prev = Number(
    raw.prevClose != null ? raw.prevClose
      : (raw.referencePrice != null ? raw.referencePrice : m.referencePrice)
  );
  const high = Number(raw.high != null ? raw.high : price);
  const low = Number(raw.low != null ? raw.low : price);
  const opn = Number(raw.open != null ? raw.open : NaN);
  const session = String(raw.session || m.session || '');
  let changePct = raw.changePct != null ? Number(raw.changePct)
    : (raw.displayChangePct != null ? Number(raw.displayChangePct)
      : (m.displayChangePct != null ? Number(m.displayChangePct) : NaN));
  if (!isFinite(changePct) && prev > 0) changePct = (price - prev) / prev * 100;
  return {
    price,
    prevClose: prev > 0 ? prev : null,
    high: high > 0 ? high : price,
    low: low > 0 ? low : price,
    open: opn > 0 ? opn : null,
    session,
    sessionLabel: raw.sessionLabel || (session === 'night' ? '夜盤' : session === 'day' ? '日盤' : ''),
    changePct: isFinite(changePct) ? changePct : null,
  };
}

function overlayTxfLiveOnLastBar(last, quote) {
  const nq = normalizeTxfLiveQuote(quote) || (quote && Number(quote.price) > 0 ? quote : null);
  if (!last || !nq) return null;
  const px = nq.price;
  const hi = Math.max(Number(last.high) || px, Number(nq.high) || px, px);
  const lo = Math.min(Number(last.low) || px, Number(nq.low) || px, px);
  if (!(lo > 0) || hi < lo) return null;
  return {
    time: last.time,
    open: last.open,
    high: hi,
    low: lo,
    close: px,
    volume: last.volume,
  };
}

function applyTxfLiveToChart(raw) {
  if (typeof S === 'undefined' || !S || S.sym !== '__TXF__') return false;
  const q = normalizeTxfLiveQuote(raw);
  if (!q) return false;
  const cs = S.data && S.data.candles;
  if (!cs || !cs.length) return false;
  const last = cs[cs.length - 1];
  const bar = overlayTxfLiveOnLastBar(last, q);
  if (!bar) return false;
  last.open = bar.open;
  last.high = bar.high;
  last.low = bar.low;
  last.close = bar.close;
  if (q.prevClose > 0) S.data.yesterdayClose = q.prevClose;
  const off = (S.tzOffset && isFinite(S.tzOffset)) ? S.tzOffset : 0;
  const col = (function () {
    const delta = (q.prevClose > 0) ? (q.price - q.prevClose) : 0;
    const pal = (window.Colors && typeof Colors.candle === 'function')
      ? Colors.candle('__TXF__') : { up: '#F87171', down: '#4ADE80' };
    if (delta > 0) return pal.up;
    if (delta < 0) return pal.down;
    return '#9ca3af';
  })();
  if (S.chartSeries && typeof S.chartSeries.update === 'function') {
    try {
      S.chartSeries.update({
        time: bar.time + off,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        color: col,
        borderColor: col,
        wickColor: col,
      });
    } catch (e) { /* LightweightCharts 拒絕未知 time 時保留 FinMind 棒 */ }
  }
  const pEl = document.getElementById('ci-price');
  if (pEl) pEl.textContent = q.price.toFixed(2);
  if (typeof updateHeaderChg === 'function') {
    updateHeaderChg(
      q.price,
      q.prevClose > 0 ? q.prevClose : (S.data.yesterdayClose || null),
      S.data.rangeBase,
      S.data.rangeChgLbl,
      'TW',
      '__TXF__'
    );
  }
  if (typeof updateHeaderHigh === 'function') {
    updateHeaderHigh(cs, S.data.rangeChgLbl, q.price);
  }
  if (typeof updateWlPrice === 'function' && q.prevClose > 0) {
    const pct = (q.price - q.prevClose) / q.prevClose * 100;
    try { updateWlPrice('__TXF__', q.price, pct); } catch (e) {}
  }
  if (S.chartSeries && q.prevClose > 0) {
    try {
      if (S._prevLine) S.chartSeries.removePriceLine(S._prevLine);
      S._prevLine = S.chartSeries.createPriceLine({
        price: q.prevClose,
        color: 'rgba(200, 200, 200, .35)',
        lineWidth: 1,
        lineStyle: (typeof LightweightCharts !== 'undefined')
          ? LightweightCharts.LineStyle.Dashed : 2,
        axisLabelVisible: false,
        title: '',
      });
    } catch (e) {}
  }
  if (typeof renderCloseReadout === 'function') {
    try { renderCloseReadout(q.price, q.prevClose); } catch (e) {}
  }
  let hb = document.getElementById('rt-hb');
  if (!hb) {
    const cw = document.getElementById('chart-wrap');
    if (cw) {
      hb = document.createElement('div');
      hb.id = 'rt-hb';
      hb.style.cssText = 'position:absolute;top:4px;right:10px;z-index:8;font-size:9px;' +
        'font-family:monospace;pointer-events:none;text-shadow:0 0 3px #000';
      cw.appendChild(hb);
    }
  }
  if (hb) {
    const night = q.session === 'night';
    hb.style.color = night ? '#38bdf8' : '#3ecf6b';
    hb.textContent = '● ' + (q.sessionLabel || (night ? '夜盤' : '日盤')) + ' · MIS';
  }
  return true;
}

window.normalizeTxfLiveQuote = normalizeTxfLiveQuote;
window.overlayTxfLiveOnLastBar = overlayTxfLiveOnLastBar;
window.applyTxfLiveToChart = applyTxfLiveToChart;

window.addEventListener('marketData', function (ev) {
  const quotes = ev && ev.detail && ev.detail.snapshot && ev.detail.snapshot.quotes;
  if (!quotes) return;
  ['^TWII', '^TWOII', '__TXF__'].forEach(sym => renderCanonicalMarketQuote(sym, quotes[sym]));
  const active = window.S && S.sym;
  if (active === '__TXF__') {
    applyTxfLiveToChart(quotes.__TXF__);
    return;
  }
  const q = active && quotes[active];
  const m = q && q.market;
  if (m && typeof updateHeaderChg === 'function' && m.price != null && m.referencePrice != null) {
    updateHeaderChg(m.price, m.referencePrice,
      S.data && S.data.rangeBase, S.data && S.data.rangeChgLbl, 'TW', active);
  }
});

async function refreshMktBar() {
  try {
    const syms = MKT_INDICES.filter(m => m.sym !== '__TXF__' && !(m.sym.startsWith('__') && m.sym.endsWith('__'))).map(m => m.sym).join(',');
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
      // 漲跌基準一律用 Yahoo 官方昨收 regularMarketPreviousClose(與主圖一致)。
      // 原本用日線陣列推算(prevC),外資指數(^KS11/^SOX)遇 Yahoo 落後/壞 tick 會算出
      // -8% 等離譜值且與主圖不一致 → 改吃官方昨收,只在缺時才退回陣列。
      // 後端 pulse 全球影響 (_yf_mktbar_day_change) 必須與此公式完全一致。
      const _rmpc = meta.regularMarketPreviousClose;
      const cur = (rmp != null && isFinite(rmp) && rmp > 0) ? rmp : last.c;
      const prev = (_rmpc != null && isFinite(_rmpc) && _rmpc > 0) ? _rmpc
                 : (prevC != null ? prevC : (meta.chartPreviousClose || meta.previousClose));
      if (cur == null || prev == null || !isFinite(prev) || prev <= 0) continue;
      const delta = cur - prev;
      const chgPct = delta / prev * 100;
      const cell = document.querySelector(`[data-mkt-sym="${m.sym}"]`);
      if (!cell) continue;
      cell.classList.remove('loading');
      cell.querySelector('.px').textContent = fmtIdx(cur);

      // ── 漲跌色:依各標的市場慣例(台股/東亞 紅漲;美股指數 綠漲)走中央 Colors ──
      const dir = applyMktCellTone(cell, delta, m.redUp !== false);
      const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';
      const dEl = cell.querySelector('.delta');
      dEl.textContent = sign + Math.abs(delta).toFixed(Math.abs(delta) >= 100 ? 0 : 2);
      const ch = cell.querySelector('.ch');
      const arrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '－';
      ch.textContent = arrow + Math.abs(chgPct).toFixed(2) + '%';
    }
  } catch (e) { console.warn('[polish-v3] mktbar refresh failed:', e); }
  // 加權/櫃買 — TWSE 即時指數覆寫(修 Yahoo ^TWII 早盤落後一日)
  try { if (window.MarketData) await MarketData.refresh(); } catch (e) { console.warn('[polish-v3] market snapshot failed:', e); }
  // 台指期(含夜盤) — 與主圖共用 /txf，收盤後最後一根 K 繼續跟夜盤
  try { await refreshTxfCell(); } catch (e) { console.warn('[polish-v3] txf cell failed:', e); }
  // 大盤融資維持率 — 本地特例數據
  try { await refreshMarginRatioCell(); } catch (e) { console.warn('[polish-v3] margin ratio cell failed:', e); }
  // MacroMicro 追蹤圖格（台利率／融資比／美利率債／CPI金融）
  try { await refreshMacroTrackCells(); } catch (e) { console.warn('[polish-v3] macro track cells failed:', e); }
}

async function refreshMacroTrackCells() {
  const ids = (window.ChartRegistry && ChartRegistry.MACRO_TRACK_IDS)
    ? ChartRegistry.MACRO_TRACK_IDS.slice()
    : [
      '__TW_RATES__', '__TW_MARGIN_MIX__', '__TW_MARGIN_CYCLE__',
      '__US_RATES_CREDIT__', '__US_CPI_FIN__',
    ];
  await Promise.all(ids.map(async (id) => {
    const cell = document.querySelector(`[data-mkt-sym="${id}"]`);
    if (!cell) return;
    try {
      const r = await fetch(`${SERVER_P}/macro/chart/${encodeURIComponent(id)}?years=5`, { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      const series = (d && d.series) || [];
      const primary = (window.ChartRegistry && ChartRegistry.pickPrimarySeries)
        ? ChartRegistry.pickPrimarySeries(series, id)
        : series.find(s => s.scale === 'left' && s.points && s.points.length);
      // 絕不退回右軸加權／指數，避免格上出現 43654 這種指數價
      if (!primary || !primary.points || !primary.points.length) return;
      const pts = primary.points;
      const cur = pts[pts.length - 1].value;
      const prev = pts.length >= 2 ? pts[pts.length - 2].value : cur;
      const delta = cur - prev;
      const unit = primary.unit || '';
      cell.classList.remove('loading');
      const px = cell.querySelector('.px');
      if (px) {
        px.textContent = (Math.abs(cur) >= 100 ? cur.toFixed(1) : cur.toFixed(2)) + (unit === '%' ? '%' : '');
      }
      const tw = !(id.indexOf('__US_') === 0);
      applyMktCellTone(cell, delta, tw);
      const dEl = cell.querySelector('.delta');
      if (dEl) {
        dEl.textContent = (delta >= 0 ? '+' : '') + delta.toFixed(2) + (unit === '%' ? 'pp' : '');
      }
      const ch = cell.querySelector('.ch');
      if (ch) {
        const pct = prev ? (delta / prev * 100) : 0;
        ch.textContent = (delta >= 0 ? '▲' : '▼') + Math.abs(pct).toFixed(2) + '%';
      }
      cell.title = (d.name || id) + ' · 點擊載入追蹤圖';
    } catch (e) { /* ignore per-cell */ }
  }));
}

async function refreshMarginRatioCell() {
  try {
    const r = await fetch(`${SERVER_P}/yf/__MARGIN_RATIO__?range=5d`, {cache:'no-store'});
    if (!r.ok) return;
    const d = await r.json();
    const res = d?.chart?.result?.[0];
    if (!res) return;
    const meta = res.meta || {};
    const tsArr = res.timestamp || [];
    const rawCloses = res.indicators?.quote?.[0]?.close || [];
    const valid = [];
    for (let i = 0; i < Math.min(tsArr.length, rawCloses.length); i++) {
      if (rawCloses[i] != null && isFinite(rawCloses[i])) {
        valid.push(rawCloses[i]);
      }
    }
    if (valid.length < 1) return;
    // 優先用 meta 即時／權威值（與主圖一致）
    const cur = (meta.regularMarketPrice != null && isFinite(meta.regularMarketPrice))
      ? meta.regularMarketPrice : valid[valid.length - 1];
    const prev = (meta.regularMarketPreviousClose != null && isFinite(meta.regularMarketPreviousClose))
      ? meta.regularMarketPreviousClose
      : (meta.previousClose != null && isFinite(meta.previousClose))
        ? meta.previousClose
        : (valid.length >= 2 ? valid[valid.length - 2] : cur);
    const delta = cur - prev;           // 百分點 (pp)
    const cell = document.querySelector(`[data-mkt-sym="__MARGIN_RATIO__"]`);
    if (!cell) return;

    cell.classList.remove('loading');
    cell.querySelector('.px').textContent = cur.toFixed(2) + '%';

    // 風險色：≤140 偏警戒底色（不覆蓋漲跌色）
    if (cur <= 140) cell.style.boxShadow = 'inset 0 0 0 1px rgba(239,68,68,.45)';
    else if (cur <= 150) cell.style.boxShadow = 'inset 0 0 0 1px rgba(249,115,22,.35)';
    else cell.style.boxShadow = '';

    const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';
    applyMktCellTone(cell, delta, true); // 增加為紅、減少為綠

    const dEl = cell.querySelector('.delta');
    // 日變化以百分點顯示（與維持率單位一致）
    dEl.textContent = sign + Math.abs(delta).toFixed(2) + 'pp';

    const ch = cell.querySelector('.ch');
    const arrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '－';
    ch.textContent = arrow + (prev > 0 ? (delta / prev * 100).toFixed(2) : '0.00') + '%';
    cell.title = '大盤融資維持率 ' + cur.toFixed(2) + '%（點擊載入歷史圖 · TWSE／MacroMicro 對齊公式）';
  } catch (e) { console.warn('[polish-v3] margin ratio cell refresh failed:', e); }
}

// ============================================================
// 大盤融資維持率 — 圖表風險區間 + 歷史資訊列（MacroMicro 對齊）
// ============================================================
(function marginRatioChartEnhance() {
  const ZONE_DEFAULTS = [
    { level: 130, label: '危險 130', color: '#ef4444' },
    { level: 140, label: '警戒 140', color: '#f97316' },
    { level: 150, label: '偏弱 150', color: '#eab308' },
    { level: 166, label: '門檻 166', color: '#38bdf8' },
  ];
  let _lines = [];
  let _metaCache = null;

  function clearLines() {
    if (!S.chartSeries) { _lines = []; return; }
    for (const pl of _lines) {
      try { S.chartSeries.removePriceLine(pl); } catch (e) {}
    }
    _lines = [];
  }

  function ensureBanner() {
    let el = document.getElementById('margin-ratio-banner');
    if (el) return el;
    const host = document.getElementById('chart-info') || document.getElementById('left');
    if (!host) return null;
    el = document.createElement('div');
    el.id = 'margin-ratio-banner';
    el.style.cssText = [
      'display:none', 'margin:4px 8px 0', 'padding:6px 10px',
      'font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
      'color:#cbd5e1', 'background:linear-gradient(90deg,rgba(56,189,248,.08),rgba(15,23,42,.2))',
      'border:1px solid rgba(56,189,248,.25)', 'border-radius:4px',
    ].join(';');
    host.parentNode.insertBefore(el, host.nextSibling);
    return el;
  }

  function hideBanner() {
    const el = document.getElementById('margin-ratio-banner');
    if (el) el.style.display = 'none';
  }

  function renderBanner(m) {
    const el = ensureBanner();
    if (!el || !m) return;
    const zone = m.riskZone;
    const zoneHtml = zone
      ? `<span style="color:${zone.color || '#f97316'};font-weight:700">◎ ${zone.label || ''}</span>`
      : `<span style="color:#4ade80">◎ 正常區（&gt;166%）</span>`;
    const bf = m.backfill || {};
    const bfNote = bf.running
      ? ` · 回補中 ${bf.done || 0}/${bf.total || '?'} (${bf.phase || ''})`
      : '';
    el.innerHTML =
      `<b style="color:#7dd3fc">大盤融資維持率</b> ` +
      `<b style="color:#f8fafc;font-size:13px">${(m.current != null ? m.current.toFixed(2) : '--')}%</b> ` +
      zoneHtml +
      `<span style="color:#94a3b8"> · 雙軸折線（維持率L／加權R）· 歷史 ${m.firstDate || '—'} → ${m.lastDate || '—'}（${m.count || 0} 日）` +
      ` · 區間 ${m.min != null ? m.min.toFixed(1) : '—'}–${m.max != null ? m.max.toFixed(1) : '—'}%` +
      ` · 均 ${m.avg != null ? m.avg.toFixed(1) : '—'}%</span>` +
      `<div style="color:#64748b;margin-top:2px">公式：${m.formula || 'Σ(融資市值,不含ETF)/融資金額×100'} · 來源 ${m.source || 'TWSE'}${bfNote}` +
      ` · <a href="${m.reference || 'https://www.macromicro.me/charts/53117/taiwan-taiex-maintenance-margin'}" target="_blank" rel="noopener" style="color:#38bdf8">MacroMicro 對照</a>` +
      ` · <button type="button" id="margin-bf-btn" style="cursor:pointer;background:#0f172a;color:#7dd3fc;border:1px solid #334155;border-radius:3px;padding:1px 6px;font:inherit">回補全歷史</button></div>`;
    el.style.display = 'block';
    const btn = document.getElementById('margin-bf-btn');
    if (btn) {
      btn.onclick = async () => {
        btn.disabled = true;
        btn.textContent = '啟動中…';
        try {
          await fetch(`${SERVER_P}/margin_ratio/backfill`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ full: true }), cache: 'no-store'
          });
          btn.textContent = '已背景回補';
          setTimeout(() => applyMarginEnhance(true), 2500);
        } catch (e) {
          btn.textContent = '失敗';
          btn.disabled = false;
        }
      };
    }
  }

  function applyZones(zones) {
    clearLines();
    // MarketChart 已畫風險虛線且用浮動窗標註 → 勿再疊軸上標籤
    if (window.MarketChart && window.S && (S._marketChartId || MarketChart.resolve(S.sym))) {
      return;
    }
    if (!S.chartSeries || typeof S.chartSeries.createPriceLine !== 'function') return;
    const list = (zones && zones.length) ? zones : ZONE_DEFAULTS;
    const LS = (window.LightweightCharts && LightweightCharts.LineStyle)
      ? LightweightCharts.LineStyle.Dashed : 2;
    for (const z of list) {
      try {
        const pl = S.chartSeries.createPriceLine({
          price: z.level,
          color: z.color || '#64748b',
          lineWidth: 1,
          lineStyle: LS,
          axisLabelVisible: false,
          title: '',
        });
        _lines.push(pl);
      } catch (e) {}
    }
  }

  async function applyMarginEnhance(forceMeta) {
    if (S.sym !== '__MARGIN_RATIO__') {
      clearLines();
      hideBanner();
      return;
    }
    // 價格顯示加 %
    const pEl = document.getElementById('ci-price');
    if (pEl && pEl.textContent && !pEl.textContent.includes('%')) {
      pEl.textContent = pEl.textContent.trim() + '%';
    }
    const nEl = document.getElementById('ci-name');
    if (nEl) nEl.textContent = '大盤融資維持率';
    try {
      if (forceMeta || !_metaCache) {
        const r = await fetch(`${SERVER_P}/margin_ratio`, { cache: 'no-store' });
        if (r.ok) _metaCache = await r.json();
      }
    } catch (e) {}
    applyZones(_metaCache && _metaCache.riskZones);
    renderBanner(_metaCache || {
      current: S.data && S.data.candles && S.data.candles.length
        ? S.data.candles[S.data.candles.length - 1].close : null,
      formula: 'Σ(融資市值,不含ETF)/融資金額×100',
      source: 'TWSE',
    });
  }

  window.addEventListener('symLoaded', () => {
    setTimeout(() => applyMarginEnhance(true), 80);
  });
})();

// TWSE MIS 即時：加權(t00)→^TWII、櫃買(o00)→^TWOII。
// 有有效 price 才覆寫 Yahoo 值；盤前無成交(price=null)則保留 Yahoo。
async function refreshTwIndexCells() {
  const r = await fetch(`${SERVER_P}/twindex`, { cache: 'no-store' });
  if (!r.ok) return;
  const d = await r.json();
  if (!d || !d.ok || !d.indices) return;
  const map = { 't00': '^TWII', 'o00': '^TWOII' };
  for (const [code, sym] of Object.entries(map)) {
    const ix = d.indices[code];
    if (!ix || ix.price == null) continue;          // 無即時成交 → 不覆寫
    const cell = document.querySelector(`[data-mkt-sym="${sym}"]`);
    if (!cell) continue;
    const prev = ix.prevClose;
    const cur = ix.price;
    const delta = (prev != null) ? (cur - prev) : null;
    const chgPct = (ix.changePct != null) ? ix.changePct
      : (delta != null && prev ? delta / prev * 100 : null);
    cell.classList.remove('loading');
    cell.querySelector('.px').textContent = fmtIdx(cur);
    if (delta == null || chgPct == null) continue;
    applyMktCellTone(cell, delta, true);
    const sign = delta > 0 ? '+' : delta < 0 ? '−' : '';
    const dEl = cell.querySelector('.delta');
    dEl.textContent = sign + Math.abs(delta).toFixed(Math.abs(delta) >= 100 ? 0 : 2);
    const ch = cell.querySelector('.ch');
    const arrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '－';
    ch.textContent = arrow + Math.abs(chgPct).toFixed(2) + '%';
  }
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
  applyMktCellTone(cell, chg, true);
  const sign = chg > 0 ? '+' : chg < 0 ? '−' : '';
  const delta = (d.prevClose != null) ? (d.price - d.prevClose) : null;
  const dEl = cell.querySelector('.delta');
  dEl.textContent = delta != null ? sign + Math.abs(delta).toFixed(0) : '';
  const ch = cell.querySelector('.ch');
  const arrow = chg > 0 ? '▲' : chg < 0 ? '▼' : '－';
  ch.textContent = (chg != null) ? arrow + Math.abs(chg).toFixed(2) + '%' : '';
  applyTxfLiveToChart(d);
}

// ============================================================
// (2) TW/US color convention — auto switch on market change
// ============================================================
function applyMarketColorClass(mkt) {
  document.body.classList.remove('market-tw', 'market-us', 'market-jp');
  document.body.classList.add(mkt === 'TW' ? 'market-tw' : (mkt === 'JP' ? 'market-jp' : 'market-us'));
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
// Patch ci-chg / ci-range-chg：symLoaded 後再對齊顏色與區間漲跌（避免 race）
(function patchCiChg() {
  // After symLoaded, 重跑 updateHeaderChg：日漲跌(昨收) + 區間漲跌(rangeBase)
  // 與 loadSym 同步：intraday 用 yesterdayClose（= chartPreviousClose），
  // daily 用權威昨收；區間用 chartPreviousClose / trim 前一根。
  window.addEventListener('symLoaded', () => {
    if (!S.data?.candles?.length) return;
    const last = S.data.candles[S.data.candles.length - 1];
    const prev = S.data.candles[S.data.candles.length - 2];
    const ref = (S.data.yesterdayClose != null && S.data.yesterdayClose > 0)
      ? S.data.yesterdayClose
      : (prev ? prev.close : null);
    if (S.sym === '__TXF__') {
      const store = window.MarketData && MarketData.get && MarketData.get();
      const live = store && store.quotes && store.quotes.__TXF__;
      if (live && applyTxfLiveToChart(live)) return;
    }
    if (typeof updateHeaderChg === 'function') {
      updateHeaderChg(last.close, ref, S.data.rangeBase, S.data.rangeChgLbl, S.mkt, S.sym);
      if (typeof updateHeaderHigh === 'function') {
        updateHeaderHigh(S.data.candles, S.data.rangeChgLbl, last.close);
      }
      return;
    }
    // fallback：舊版無 updateHeaderChg 時只修日漲跌色
    const el = document.getElementById('ci-chg');
    if (!el || ref == null) return;
    el.classList.remove('price-up', 'price-down');
    el.style.color = (last.close === ref) ? ''
      : (window.Colors ? Colors.dir(S.sym, last.close - ref)
        : ((_isTwSym(S.sym) || (S.mkt || 'TW') === 'TW')
            ? (last.close > ref ? 'var(--red)' : 'var(--green)')
            : (last.close > ref ? 'var(--green)' : 'var(--red)')));
  });
})();

// ============================================================
// (3) Chart legend + (4) volume color + (5) prev close line
// All applied by patching renderChart
// ============================================================
// ── 台股指數(^TWII/^TWOII)早盤 Yahoo 日線落後一日 → 用 TWSE 即時校正頂部數字 ──
// Yahoo ^TWII 早盤最後一根日 K 還停在昨天 → 頂部現價/% 與底部總體列(用 TWSE 即時)不一致。
// 只在「偵測到落後(最後一根 K 收盤≈昨收)」時,用同一個 /twindex 源校正頂部現價/漲跌%/昨收。
// 正常盤(主圖已是今天)完全不介入,保留 Yahoo。
(function patchTwIndexHeader() {
  const TW_IDX = { '^TWII': 't00', '^TWOII': 'o00' };
  window.addEventListener('symLoaded', async () => {
    const sym = S.sym;
    const code = TW_IDX[sym]; if (!code) return;
    try {
      const d = await fetch(`${SERVER_P}/twindex`, { cache: 'no-store' }).then(r => r.ok ? r.json() : null);
      const ix = d && d.indices && d.indices[code];
      if (!ix || ix.price == null || ix.prevClose == null) return;   // 盤後/假日無即時 → 不動
      if (S.sym !== sym) return;                                     // race:已切股
      const cs = S.data && S.data.candles; if (!cs || !cs.length) return;
      const lb = cs[cs.length - 1];
      const lagging = Math.abs(lb.close - ix.prevClose) < Math.max(1, ix.prevClose * 1e-5);
      if (!lagging) return;   // 主圖最後一根已是今天 → Yahoo 已正確,不介入
      const price = ix.price, prev = ix.prevClose, pct = (price - prev) / prev * 100;
      if (S.data) S.data.yesterdayClose = prev;
      const pEl = document.getElementById('ci-price'); if (pEl) pEl.textContent = price.toFixed(2);
      // 日漲跌 + 區間漲跌一併更新（區間基準不變，只刷新現價差額）
      if (typeof updateHeaderChg === 'function') {
        updateHeaderChg(price, prev, S.data && S.data.rangeBase, S.data && S.data.rangeChgLbl, 'TW', sym);
      } else {
        const cEl = document.getElementById('ci-chg');
        if (cEl) {
          cEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
          cEl.classList.remove('price-up', 'price-down');
          cEl.style.color = window.Colors ? Colors.dir(sym, pct) : (pct > 0 ? 'var(--red)' : pct < 0 ? 'var(--green)' : '');
        }
      }
      console.log('[polish-v3] ^TW index header corrected via TWSE (early-session lag):', sym, price, pct.toFixed(2) + '%');
    } catch (e) { /* keep Yahoo on failure */ }
  });
})();

// 台指期：symLoaded 後拉 /txf 覆寫最後一根；夜盤時段持續輪詢，與下方大盤列同步。
(function patchTxfLiveChart() {
  let inflight = false;
  async function pullTxfLive() {
    if (typeof S === 'undefined' || !S || S.sym !== '__TXF__') return;
    if (document.hidden) return;
    if (inflight) return;
    inflight = true;
    try {
      const store = window.MarketData && MarketData.get && MarketData.get();
      const cached = store && store.quotes && store.quotes.__TXF__;
      if (cached) applyTxfLiveToChart(cached);
      const base = (typeof SERVER_P !== 'undefined' && SERVER_P) ? SERVER_P : '';
      const r = await fetch(base + '/txf', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      applyTxfLiveToChart(d);
    } catch (e) { /* 保留 FinMind 日線 */ }
    finally { inflight = false; }
  }
  window.addEventListener('symLoaded', () => {
    if (S && S.sym === '__TXF__') pullTxfLive();
  });
  setInterval(pullTxfLive, 5000);
})();

// ============================================================
// 大盤融資維持率 — 已迁至 src/chart/market_chart_v3.js（MarketChart）
// polish 僅保留 shim：MarketChart 優先，未載入才走本地後備。
// ============================================================
function renderMarginRatioMacroChart(candles) {
  if (window.MarketChart && typeof MarketChart.render === 'function') {
    const def = MarketChart.resolve('__MARGIN_RATIO__');
    const pts = (candles && candles.length)
      ? candles.map(c => ({ time: c.time, value: c.close }))
      : ((window.S && S.data && S.data.candles) || []).map(c => ({ time: c.time, value: c.close }));
    if (def && pts.length) {
      MarketChart.render(def, pts);
      return;
    }
  }
  _renderMarginRatioMacroChartFallback(candles);
}

function _renderMarginRatioMacroChartFallback(candles) {
  const wrap = document.getElementById('chart-wrap');
  if (!wrap || typeof LightweightCharts === 'undefined') {
    console.warn('[margin-chart] chart-wrap / LightweightCharts missing');
    return;
  }
  if (!candles || !candles.length) {
    console.warn('[margin-chart] no candles');
    return;
  }

  if (S.chart) {
    try { S.chart.remove(); } catch (e) {}
    S.chart = null;
  }

  const userTzOffset = -new Date().getTimezoneOffset() * 60;
  S.tzOffset = userTzOffset;
  const tz = (t) => (t == null ? t : t + userTzOffset);
  const _marginLoadId = window.__loadSeq;

  const chart = LightweightCharts.createChart(wrap, {
    width: wrap.clientWidth,
    height: wrap.clientHeight,
    layout: { background: { color: '#060A12' }, textColor: '#5A6A82' },
    grid: { vertLines: { color: '#0F1A2B' }, horzLines: { color: '#0F1A2B' } },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Magnet,
      vertLine: { color: 'rgba(245,197,24,.55)', width: 1, style: 2, labelVisible: true, labelBackgroundColor: '#B8860B' },
      horzLine: { color: 'rgba(245,197,24,.55)', width: 1, style: 2, labelVisible: true, labelBackgroundColor: '#B8860B' },
    },
    leftPriceScale: {
      visible: true,
      borderColor: '#1A2740',
      scaleMargins: { top: 0.08, bottom: 0.10 },
    },
    rightPriceScale: {
      visible: true,
      borderColor: '#1A2740',
      scaleMargins: { top: 0.08, bottom: 0.10 },
    },
    timeScale: {
      borderColor: '#1A2740',
      timeVisible: false,
      secondsVisible: false,
      rightOffset: 2,
      barSpacing: 2,
      minBarSpacing: 0.5,
      fixLeftEdge: true,
      fixRightEdge: true,
      lockVisibleTimeRangeOnResize: true,
    },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
  });
  S.chart = chart;

  const lineData = candles.map(c => ({ time: tz(c.time), value: c.close }));
  const area = chart.addAreaSeries({
    priceScaleId: 'left',
    lineColor: '#38BDF8',
    topColor: 'rgba(56,189,248,0.22)',
    bottomColor: 'rgba(56,189,248,0.02)',
    lineWidth: 2,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: true,
    crosshairMarkerRadius: 5,
    crosshairMarkerBorderColor: '#7DD3FC',
    crosshairMarkerBackgroundColor: '#0EA5E9',
    priceFormat: {
      type: 'custom',
      formatter: v => (v != null && isFinite(v) ? v.toFixed(2) + '%' : ''),
    },
  });
  area.setData(lineData);
  S.chartSeries = area;
  S.dotSeries = area;
  S.volSeries = null;
  S.overlaySeries = {};
  S.wsSeries = null;
  S.wsLeftSeries = null;
  S.twiiSeries = null;
  S._prevLine = null;
  S._marginMacroChart = true; // 偵測標記：確認已走折線路徑

  const _prevCloseByTime = new Map();
  for (let i = 0; i < candles.length; i++) {
    _prevCloseByTime.set(tz(candles[i].time), i > 0 ? candles[i - 1].close : null);
  }
  const _twiiByTime = new Map();

  chart.subscribeCrosshairMove(param => {
    const ohlcEl = document.getElementById('ci-ohlc');
    if (!ohlcEl) return;
    if (!param || !param.point || !param.time || !param.seriesData) {
      ohlcEl.style.display = 'none';
      return;
    }
    const pt = param.seriesData.get(area);
    if (!pt || pt.value == null) { ohlcEl.style.display = 'none'; return; }
    const d = new Date(typeof param.time === 'number' ? param.time * 1000 : Date.parse(param.time));
    const ds = `${d.getUTCFullYear()}/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`;
    const prev = _prevCloseByTime.get(param.time);
    const delta = (prev != null && prev > 0) ? (pt.value - prev) : null;
    const chgPct = (delta != null && prev > 0) ? (delta / prev * 100) : null;
    const up = delta != null && delta > 0;
    const dn = delta != null && delta < 0;
    const col = up ? 'var(--red)' : (dn ? 'var(--green)' : 'var(--tlo)');
    const twii = _twiiByTime.get(param.time);
    const twiiHtml = (twii != null && isFinite(twii))
      ? `<span class="ohlc-k" style="margin-left:10px">加權(R)</span><span class="ohlc-v" style="color:#F59E0B">${twii.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>`
      : '';
    ohlcEl.style.display = 'block';
    ohlcEl.innerHTML =
      `<span class="ohlc-d">${ds}</span>` +
      `<span class="ohlc-k">維持率(L)</span><span class="ohlc-v" style="color:${col}">${pt.value.toFixed(2)}%</span>` +
      (delta != null
        ? `<span style="color:${col};margin-left:6px">${up ? '+' : ''}${delta.toFixed(2)}pp` +
          (chgPct != null ? ` (${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%)` : '') + `</span>`
        : '') +
      twiiHtml;
  });

  // 右軸加權指數
  (async () => {
    try {
      if (typeof fetchYF !== 'function' || typeof parseYF !== 'function') return;
      const rdef = (typeof currentRangeDef === 'function') ? currentRangeDef() : { range: 'max', interval: '1d' };
      const raw = await fetchYF('^TWII', { range: (rdef && rdef.range) || 'max', interval: '1d' });
      if (_marginLoadId !== window.__loadSeq || S.sym !== '__MARGIN_RATIO__' || S.chart !== chart) return;
      const parsed = parseYF(raw);
      if (!parsed || !parsed.candles || !parsed.candles.length) return;
      const twiiData = parsed.candles.map(c => ({ time: tz(c.time), value: c.close }));
      _twiiByTime.clear();
      for (const p of twiiData) _twiiByTime.set(p.time, p.value);
      const twiiLine = chart.addLineSeries({
        priceScaleId: 'right',
        color: '#F59E0B',
        lineWidth: 1.5,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 4,
        crosshairMarkerBorderColor: '#FCD34D',
        crosshairMarkerBackgroundColor: '#F59E0B',
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      });
      twiiLine.setData(twiiData);
      S.twiiSeries = twiiLine;
      S.overlaySeries = Object.assign({}, S.overlaySeries, { twii: twiiLine });
      try { if (typeof renderChartLegend === 'function') renderChartLegend(); } catch (e) {}
    } catch (e) {
      console.warn('[margin-chart] TWII overlay failed:', e);
    }
  })();

  // Header 強制顯示正確名稱／%
  try {
    const last = candles[candles.length - 1];
    const pEl = document.getElementById('ci-price');
    if (pEl && last) pEl.textContent = Number(last.close).toFixed(2) + '%';
    const nEl = document.getElementById('ci-name');
    if (nEl) nEl.textContent = '大盤融資維持率';
    const info = document.getElementById('chart-info');
    if (info) info.style.display = '';
    const loading = document.getElementById('chart-loading');
    if (loading) loading.style.display = 'none';
  } catch (e) {}

  requestAnimationFrame(() => {
    try { chart.timeScale().fitContent(); } catch (e) {}
  });
  if (!wrap._marginRo) {
    wrap._marginRo = new ResizeObserver(() => {
      if (!S.chart || S.sym !== '__MARGIN_RATIO__') return;
      try {
        S.chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
        S.chart.timeScale().fitContent();
      } catch (e) {}
    });
    wrap._marginRo.observe(wrap);
  }
  console.log('[margin-chart] MacroMicro dual-axis area rendered', candles.length, 'pts');
}

// 融資維持率 load/render 改由 MarketChart 模組攔截；此處不再重複 wrap loadSym。
// 若 MarketChart 尚未載入，仍擋掉 K 線重色路徑。
(function patchRenderChartPolish() {
  if (typeof renderChart !== 'function') return setTimeout(patchRenderChartPolish, 100);
  if (window._polishChartPatched) return;
  window._polishChartPatched = true;
  const orig = window.renderChart;
  window.renderChart = function (candles) {
    // MarketChart 優先；否則本地後備折線（絕不走下方 K 線重色）
    if (S.sym === '__MARGIN_RATIO__' || (window.MarketChart && MarketChart.resolve(S.sym))) {
      try {
        if (window.MarketChart && MarketChart.resolve(S.sym)) {
          const def = MarketChart.resolve(S.sym);
          const pts = (candles && candles.length)
            ? candles.map(c => ({ time: c.time, value: c.close }))
            : ((S.data && S.data.candles) || []).map(c => ({ time: c.time, value: c.close }));
          MarketChart.render(def, pts);
        } else {
          renderMarginRatioMacroChart(candles || (S.data && S.data.candles) || []);
        }
      } catch (e) {
        console.error('[margin-chart] render failed:', e);
      }
      setTimeout(() => {
        try { if (typeof renderChartLegend === 'function') renderChartLegend(); } catch (e) {}
        try {
          window.dispatchEvent(new CustomEvent('symLoaded', { detail: { sym: S.sym, mkt: S.mkt } }));
        } catch (e) {}
      }, 40);
      return;
    }

    S._marginMacroChart = false;

    // TW/US: swap candle up/down colors before original render reads them
    const _cvTheme = (window.ChartVisualV5 && typeof window.ChartVisualV5.themeFor === 'function')
      ? window.ChartVisualV5.themeFor(S.sym, S.mkt) : null;
    const tw = _cvTheme ? _cvTheme.redUp : _isRedUpSym(S.sym);
    const UP = _cvTheme ? _cvTheme.candleUp : (tw ? '#F87171' : '#4ADE80');
    const DN = _cvTheme ? _cvTheme.candleDown : (tw ? '#4ADE80' : '#F87171');
    const FLAT = _cvTheme ? _cvTheme.candleFlat : '#9CA3AF';
    // Temporarily override CSS vars for the chart series creation
    document.documentElement.style.setProperty('--chart-up', UP);
    document.documentElement.style.setProperty('--chart-down', DN);

    orig.apply(this, arguments);

    // After orig renders, post-process:
    setTimeout(() => {
      try {
        const _tz = (S.tzOffset && isFinite(S.tzOffset)) ? S.tzOffset : 0;
        
        // 建立昨收 Map 供昨收比對使用
        const _prevMap = new Map();
        const _cs = S.data?.candles || [];
        for (let i = 0; i < _cs.length; i++) {
          _prevMap.set(_cs[i].time, i > 0 ? _cs[i - 1].close : null);
        }

        // (a) Candle re-color: 依據台股昨收比對或美股開收比對，為每根 K 線單獨賦色
        if (S.chartSeries && S.data?.candles) {
          S.chartSeries.setData(_cs.map(c => {
            const _pc = _prevMap.get(c.time);
            const _base = (_pc != null && _pc > 0) ? _pc : c.open;
            let cCol;
            if (tw) {
              // 台股昨收比對：收>昨收=紅(漲)；收<昨收=綠(跌)；持平=灰
              cCol = (c.close > _base) ? UP : (c.close < _base ? DN : FLAT);
            } else {
              // 美股開盤比對：收>開=綠(陽)；收<開=紅(陰)；持平=灰
              cCol = (c.close > c.open) ? UP : (c.close < c.open ? DN : FLAT);
            }
            return {
              time: c.time + _tz,
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
              color: cCol,
              borderColor: cCol,
              wickColor: cCol
            };
          }));
        }

        // (b) Volume bars: 重新依市場習慣(台股昨收比對/美股開開比對)進行量柱著色
        if (S.volSeries && S.data?.candles) {
          const upAlpha = _cvTheme ? _cvTheme.volumeUp : ('rgba(' + (tw ? '248,113,113' : '74,222,128') + ',0.42)');
          const dnAlpha = _cvTheme ? _cvTheme.volumeDown : ('rgba(' + (tw ? '74,222,128' : '248,113,113') + ',0.42)');
          const flatAlpha = _cvTheme ? _cvTheme.volumeFlat : 'rgba(156,163,175,0.30)';

          S.volSeries.setData(_cs.map(c => {
            const _pc = _prevMap.get(c.time);
            const _base = (_pc != null && _pc > 0) ? _pc : c.open;
            let col;
            if (tw) {
              col = (c.close > _base) ? upAlpha : (c.close < _base ? dnAlpha : flatAlpha);
            } else {
              col = (c.close > c.open) ? upAlpha : (c.close < c.open ? dnAlpha : flatAlpha);
            }
            return {
              time: c.time + _tz,
              value: c.volume,
              color: col
            };
          }));
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

// MarketChart 模組會維持最外層 hook；此處不再延遲重掛，避免與 MarketChart 搶 renderChart。
// （舊 ensureMarginChartOutermost 已移除）

// 在右側價格軸「對應價位高度」放昨收/今收小標籤（不橫跨、不蓋 K 線）
// 像原生現價標一樣貼在軸上，今收=漲跌色、昨收=灰。
function renderCloseReadout(close, prevClose) {
  const wrap = document.getElementById('chart-wrap');
  if (!wrap || !S.chartSeries) return;
  // 清掉舊版底部框 + 舊標籤
  ['close-readout', 'ctag-now', 'ctag-prev'].forEach(id => {
    const e = document.getElementById(id); if (e) e.remove();
  });
  const _cvTheme = (window.ChartVisualV5 && typeof window.ChartVisualV5.themeFor === 'function')
    ? window.ChartVisualV5.themeFor(S.sym, S.mkt) : null;
  const tw = _cvTheme ? _cvTheme.redUp : _isRedUpSym(S.sym);
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
    nowCol = up
      ? (_cvTheme ? _cvTheme.candleUp : (tw ? '#f87171' : '#4ade80'))
      : (_cvTheme ? _cvTheme.candleDown : (tw ? '#4ade80' : '#f87171'));
  }
  mk('ctag-now', close, '今', nowCol);
  mk('ctag-prev', prevClose, '昨', 'rgba(190,195,205,.9)');
}

function renderChartLegend() {
  const ci = document.getElementById('chart-info');
  if (!ci) return;
  // v3.8.1 一次性重排 chart-info：左欄(價/漲跌/名稱) + 右欄(ci-ohlc + 圖例)
  let east = document.getElementById('ci-east');
  if (!east) {
    const row = document.createElement('div'); row.id = 'ci-row';
    const left = document.createElement('div'); left.className = 'ci-left';
    ['ci-price', 'ci-high', 'ci-chg', 'ci-range-chg', 'ci-name', 'market-score-bar'].forEach(id => {
      const el = document.getElementById(id); if (el) left.appendChild(el);
    });
    east = document.createElement('div'); east.id = 'ci-east';
    const ohlc = document.getElementById('ci-ohlc');
    if (ohlc) east.appendChild(ohlc);
    row.appendChild(left); row.appendChild(east);
    ci.appendChild(row);
  }
  let lg = document.getElementById('chart-legend');
  if (lg && lg.parentElement !== east) { lg.remove(); lg = null; }   // 舊版掛在 chart-wrap → 重建
  if (!lg) {
    lg = document.createElement('div');
    lg.id = 'chart-legend';
    lg.title = '點擊可摺疊';
    lg.style.cursor = 'pointer';
    lg.addEventListener('click', e => { e.stopPropagation(); lg.classList.toggle('collapsed'); });
    east.appendChild(lg);
  }
  // 融資維持率：雙軸折線圖例（MacroMicro：維持率L + 加權R）
  if (S.sym === '__MARGIN_RATIO__') {
    lg.innerHTML =
      `<div class="lg-row" style="color:#38BDF8"><span class="lg-swatch" style="background:#38BDF8"></span>融資維持率 (L)</div>` +
      `<div class="lg-row" style="color:#F59E0B"><span class="lg-swatch" style="background:#F59E0B"></span>加權指數 (R)</div>` +
      `<div class="lg-row" style="color:#38bdf8"><span class="lg-dash" style="width:9px;border-color:#38bdf8"></span>門檻 166%</div>` +
      `<div class="lg-row" style="color:#eab308"><span class="lg-dash" style="width:9px;border-color:#eab308"></span>偏弱 150%</div>` +
      `<div class="lg-row" style="color:#f97316"><span class="lg-dash" style="width:9px;border-color:#f97316"></span>警戒 140%</div>` +
      `<div class="lg-row" style="color:#ef4444"><span class="lg-dash" style="width:9px;border-color:#ef4444"></span>危險 130%</div>`;
    return;
  }
  // 不顯示 K 線紅/綠（一眼可見不必標註），只標均線/BB/昨收這些「需要解碼」的線
  // v3.9 去重:SMA20/SMA60/BB 已在 OHLC 資訊行用對應顏色+數值標示,色塊圖例只留「昨收」(虛線較不易辨識)
  lg.innerHTML = `<div class="lg-row" style="color:rgba(200,200,200,.55)"><span class="lg-dash" style="width:9px;color:rgba(200,200,200,.55)"></span>昨收</div>`;
}

// ============================================================
// (6) Key Stats — fetch MKT CAP / P/E / P/B / Yield from /keystats
// ============================================================
const _keystatsCache = {};
const _keystatsInflight = {};
async function fetchKeyStats(sym, mkt) {
  if (!sym) return null;
  const key = sym + '|' + (mkt || 'TW');
  if (_keystatsCache[key]) return _keystatsCache[key];
  if (_keystatsInflight[key]) return _keystatsInflight[key];
  // 指數(^…)／合成序列(__…__) 不加 .TW（避免 ^TWII.TW 404）
  const s = String(sym);
  const yfsym = (s[0] === '^' || (s.startsWith('__') && s.endsWith('__')))
    ? sym
    : (mkt === 'TW' ? sym + '.TW' : sym);
  _keystatsInflight[key] = (async function () {
    try {
      const traceId = 'ks-ui-' + Date.now() + '-' + String(yfsym).replace(/[^A-Z0-9.^_=:-]/gi, '').slice(0, 24);
      const r = await fetch(`${SERVER_P}/keystats/${encodeURIComponent(yfsym)}?traceId=${encodeURIComponent(traceId)}`, {
        cache:'no-store'
      });
      if (!r.ok) return null;
      const data = await r.json();
      _keystatsCache[key] = data;
      return data;
    } catch (e) {
      console.warn('[keystats] fetch error:', e);
      return null;
    } finally {
      delete _keystatsInflight[key];
    }
  })();
  return _keystatsInflight[key];
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
      // 回填 STATS 上方「MKT CAP」列（Yahoo chart meta 沒有市值，先前永遠 --）
      if (ks && ks.marketCap != null) {
        const el = document.getElementById('rp-MKTCAP');
        if (el) {
          const cur = ks.currency || (S.mkt === 'TW' ? 'TWD' : (S.mkt === 'JP' ? 'JPY' : 'USD'));
          el.textContent = fmtBig(ks.marketCap) + ' ' + cur;
        }
        // 同步進 S.data.meta，後續重繪／PDF 也能用
        try {
          if (S.data && S.data.meta) S.data.meta.marketCap = ks.marketCap;
        } catch (_) {}
      }
      const sect = document.getElementById('keystats-sect');
      const html = ks
        ? renderKeystatsSection(ks)
        : `<div id="keystats-sect"><div class="stat-sect">關鍵估值 · ${S.sym}</div>` +
          `<div style="padding:12px;font-family:monospace;font-size:10px;color:var(--tlo);text-align:center">關鍵估值暫無資料<br><span style="font-size:9px;color:var(--tf)">Yahoo／官方估值皆未回傳</span></div></div>`;
      if (sect) sect.outerHTML = html;
      else {
        const rp = document.getElementById('rpanel');
        if (!rp || S.tab !== 'stats') return;
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
  if (!ks) {
    return `<div id="keystats-sect"><div class="stat-sect">關鍵估值</div>` +
      `<div style="padding:12px;font-family:monospace;font-size:10px;color:var(--tlo);text-align:center">無資料</div></div>`;
  }
  // 大盤融資維持率：顯示歷史／風險區，而非本益比
  if (S.sym === '__MARGIN_RATIO__' || (ks && ks.marginMeta)) {
    const m = (ks && ks.marginMeta) || {};
    const cur = ks.regularMarketPrice != null ? ks.regularMarketPrice : m.current;
    const zone = m.riskZone;
    const V = window.Viz;
    let h = '<div id="keystats-sect"><div class="stat-sect">融資維持率 · 總覽</div>';
    h += `<div class="keystat-row"><span class="k">最新</span><span class="v">${cur != null ? cur.toFixed(2) + '%' : '--'}</span></div>`;
    if (V && cur != null && isFinite(cur)) {
      h += `<div style="padding:0 12px 4px">${V.zoneMark(cur, 120, 200)}</div>`;
    }
    h += `<div class="keystat-row"><span class="k">日變化</span><span class="v">${m.delta != null ? ((m.delta >= 0 ? '+' : '') + m.delta.toFixed(2) + 'pp') : '--'}</span></div>`;
    h += `<div class="keystat-row"><span class="k">歷史高低</span><span class="v">${m.min != null ? m.min.toFixed(2) : '--'}% ～ ${m.max != null ? m.max.toFixed(2) : '--'}%</span></div>`;
    h += `<div class="keystat-row"><span class="k">歷史均値</span><span class="v">${m.avg != null ? m.avg.toFixed(2) + '%' : '--'}</span></div>`;
    h += `<div class="keystat-row"><span class="k">樣本數</span><span class="v">${m.count != null ? m.count : '--'} 日（${m.firstDate || '—'} → ${m.lastDate || '—'}）</span></div>`;
    h += `<div class="keystat-row"><span class="k">風險區</span><span class="v" style="color:${zone && zone.color ? zone.color : 'var(--thi)'}">${zone ? (zone.label || '') : '正常（>166%）'}</span></div>`;
    if (m.formula) h += `<div style="padding:4px 12px;font-family:monospace;font-size:8px;color:var(--tf)">${m.formula}</div>`;
    if (m.source) h += `<div style="padding:0 12px 6px;font-family:monospace;font-size:8px;color:var(--tf)">來源：${m.source}</div>`;
    h += '</div>';
    return h;
  }
  // 台股大盤指數：市場摘要（中位本益比＋體質支柱）
  if (ks.kind === 'market' || (ks.marketMeta && ks.marketMeta.rows)) {
    const mm = ks.marketMeta || {};
    let h = '<div id="keystats-sect"><div class="stat-sect">大盤摘要 · ' + S.sym + '</div>';
    if (mm.score != null)
      h += `<div class="keystat-row"><span class="k">體質評分</span><span class="v">${mm.score}</span></div>`;
    (mm.rows || []).forEach(row => {
      h += `<div class="keystat-row"><span class="k">${row.k}</span><span class="v">${row.v}` +
        (row.score != null ? ` <span style="font-size:9px;color:var(--tlo)">(${Math.round(row.score)})</span>` : '') +
        `</span></div>`;
    });
    if (ks.trailingPE != null)
      h += `<div class="keystat-row"><span class="k">全市場本益比中位</span><span class="v">${Number(ks.trailingPE).toFixed(1)}</span></div>`;
    if (ks._source) h += `<div style="padding:4px 12px;font-family:monospace;font-size:8px;color:var(--tf)">資料源：${ks._source}</div>`;
    h += '</div>';
    return h;
  }
  // 指數／總經：明確說明無個股估值
  if (ks.kind === 'index' || ks.kind === 'macro' || ks._note) {
    return `<div id="keystats-sect"><div class="stat-sect">關鍵估值 · ${S.sym}</div>` +
      `<div style="padding:12px;font-family:monospace;font-size:10px;color:var(--tlo);text-align:center">${ks._note || '指數／總經無個股估值'}</div></div>`;
  }
  const mc = ks.marketCap;
  const pe = ks.trailingPE;
  const pb = ks.priceToBook;
  const yld = ks.dividendYield;
  const eps = ks.eps;
  const epsCurrency = ks.currency || (S.mkt === 'TW' ? 'TWD' : (S.mkt === 'JP' ? 'JPY' : 'USD'));
  let h = '<div id="keystats-sect"><div class="stat-sect">關鍵估值 · ' + S.sym + '</div>';
  h += `<div class="keystat-row"><span class="k">市值 MKT CAP</span><span class="v">${fmtBig(mc)}${mc != null ? ' ' + epsCurrency : ''}</span></div>`;
  h += `<div class="keystat-row"><span class="k">本益比 P/E</span><span class="v" style="color:${pe != null ? (window.Colors ? Colors.warn(pe, {hi:30}) : (pe > 30 ? 'var(--orange)' : 'var(--thi)')) : 'var(--tlo)'}">${pe != null ? pe.toFixed(2) : '--'}</span></div>`;
  h += `<div class="keystat-row"><span class="k">股價淨值比 P/B</span><span class="v" style="color:${pb != null ? (window.Colors ? Colors.warn(pb, {hi:5}) : (pb > 5 ? 'var(--orange)' : 'var(--thi)')) : 'var(--tlo)'}">${pb != null ? pb.toFixed(2) : '--'}</span></div>`;
  h += `<div class="keystat-row"><span class="k">殖利率 Yield</span><span class="v" style="color:${yld != null ? (window.Colors ? Colors.warn(yld, {hi:15}) : (yld > 15 ? 'var(--orange)' : 'var(--thi)')) : 'var(--tlo)'}">${yld != null ? yld.toFixed(2) + '%' : '--'}</span></div>`;
  if (eps != null) h += `<div class="keystat-row"><span class="k">EPS</span><span class="v">${eps.toFixed(2)} ${epsCurrency}</span></div>`;
  const rg = ks.revenueGrowth, eg = ks.earningsGrowth != null ? ks.earningsGrowth : ks.earningsQuarterlyGrowth;
  if (rg != null || eg != null) {
    const gCol = v => window.Colors ? Colors.growth(S.sym, v) : 'var(--thi)';
    const gStr = v => v == null ? '--' : ((v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%');
    if (rg != null) h += `<div class="keystat-row"><span class="k">營收成長</span><span class="v" style="color:${gCol(rg)}">${gStr(rg)}</span></div>`;
    if (eg != null) h += `<div class="keystat-row"><span class="k">盈餘成長</span><span class="v" style="color:${gCol(eg)}">${gStr(eg)}</span></div>`;
  }
  if (ks.grossMargin != null || ks.opMargin != null || ks.netMargin != null) {
    const mCol = v => window.Colors ? Colors.warn(v, { lo: 8 }) : 'var(--thi)';
    const mStr = v => v == null ? '--' : Number(v).toFixed(1) + '%';
    if (ks.grossMargin != null) h += `<div class="keystat-row"><span class="k">毛利率</span><span class="v" style="color:${mCol(ks.grossMargin)}">${mStr(ks.grossMargin)}</span></div>`;
    if (ks.opMargin != null) h += `<div class="keystat-row"><span class="k">營益率</span><span class="v" style="color:${mCol(ks.opMargin)}">${mStr(ks.opMargin)}</span></div>`;
    if (ks.netMargin != null) h += `<div class="keystat-row"><span class="k">淨利率</span><span class="v" style="color:${mCol(ks.netMargin)}">${mStr(ks.netMargin)}</span></div>`;
  }
  if (ks._source) h += `<div style="padding:4px 12px;font-family:monospace;font-size:8px;color:var(--tf)">資料源：${ks._source}</div>`;
  h += '</div>';
  return h;
}

// ============================================================
// (#3) Patch renderWl into compact two-row market-aware layouts.
// TW: name | change, then code | ETF +−. US keeps the existing two-row layout.
// ============================================================
(function patchRenderWl() {
  if (typeof renderWl !== 'function') return setTimeout(patchRenderWl, 100);
  if (window._polishWlPatched) return;
  window._polishWlPatched = true;
  const orig = window.renderWl;
  window.renderWl = function () {
    orig.apply(this, arguments);
    // After v1 renders chips, restructure into two rows without changing
    // the live-price element or ETF trigger ownership.
    const ct = document.getElementById('wlchips');
    if (!ct) return;
    ct.querySelectorAll('.wlchip').forEach(chip => {
      const sym = chip.dataset.sym;
      const mkt = chip.dataset.mkt;
      const w = (typeof S !== 'undefined' && S.wl) ? S.wl.find(x => x.t === sym && x.m === mkt) : null;
      const hasName = w && w.name && w.name !== w.t;

      if (chip.dataset._stacked) return;

      const t = chip.querySelector('.wlchip-t');
      const p = chip.querySelector('.wlchip-p');
      const etfBadge = chip.querySelector('[data-etf-flow-trigger]');
      if (!t || !p || t.parentElement !== chip) return;

      const stack = document.createElement('div');
      stack.className = 'wlchip-stack';
      chip.insertBefore(stack, t);
      const meta = document.createElement('div');
      meta.className = 'wlchip-meta';

      if (mkt === 'TW') {
        const primary = document.createElement('div');
        primary.className = 'wlchip-primary';
        t.textContent = hasName ? w.name : sym;
        primary.appendChild(t);
        primary.appendChild(p);
        stack.appendChild(primary);

        const codeSpan = document.createElement('span');
        codeSpan.className = 'wlchip-c';
        codeSpan.textContent = sym;
        meta.appendChild(codeSpan);
        if (etfBadge) meta.appendChild(etfBadge);
        stack.appendChild(meta);
      } else {
        if (hasName) {
          t.textContent = w.name;
          stack.appendChild(t);
          const codeSpan = document.createElement('span');
          codeSpan.className = 'wlchip-c';
          codeSpan.textContent = w.t;
          meta.appendChild(codeSpan);
        } else {
          t.textContent = sym;
          stack.appendChild(t);
        }
        meta.appendChild(p);
        stack.appendChild(meta);
      }
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

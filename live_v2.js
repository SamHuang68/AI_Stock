// ============================================================
// Stock Terminal v2.0 — Near-Real-Time Quote Polling
// ------------------------------------------------------------
// 從 Yahoo Quote API (/quote/{sym}) 取得最新報價含 bid/ask，
// 每 30 秒輪詢一次，更新右上角的 LIVE 浮層 + 圖表最後一根 K 線。
//
// 注意：Yahoo 不提供真五檔（Level 2 order book），只有 best
// bid/ask（單一價位）。要真五檔需接券商 API（富邦/永豐/元大），
// 此模組保留 broker 介面 placeholder。
//
// 載入：放最後（依賴 S.chart / S.data / loadSym）
// ============================================================

const LIVE_POLL_MS = 30_000;   // 30 秒
let _liveTimer = null;
let _lastQuote = null;

(function bootLive() {
  if (typeof S === 'undefined') return;
  S.liveEnabled = false;
})();

// ── CSS for live panel ─────────────────────────────────────
(function injectLiveCSS() {
  const css = `
#live-panel{position:fixed;top:80px;right:355px;width:240px;z-index:100;background:rgba(11,18,32,.95);border:1px solid var(--gold-m);border-radius:6px;padding:9px 11px;font-family:'JetBrains Mono',monospace;font-size:10px;backdrop-filter:blur(6px);display:none;box-shadow:0 6px 18px rgba(0,0,0,.55);user-select:none}
#live-panel .lph{cursor:move}
#live-panel.dragging{box-shadow:0 10px 26px rgba(0,0,0,.75);transition:none}
#live-panel.on{display:block}
#live-panel .lph{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;border-bottom:1px solid var(--border);padding-bottom:5px}
#live-panel .lph .ttl{font-size:9.5px;color:var(--gold);font-weight:700;letter-spacing:1px}
#live-panel .pulse{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:lp 1.4s infinite;margin-right:5px}
@keyframes lp { 0%,100%{opacity:1} 50%{opacity:.3} }
#live-panel .lprow{display:flex;justify-content:space-between;padding:2px 0;line-height:1.55}
#live-panel .lprow .k{color:var(--tlo);font-size:9px}
#live-panel .lprow .v{color:var(--thi);font-weight:700;font-size:10px}
#live-panel .lp-state{font-size:8.5px;padding:1px 5px;border-radius:3px;letter-spacing:.5px}
#live-panel .lp-state.PRE,    #live-panel .lp-state.POST    {background:rgba(251,146,60,.2);color:var(--orange)}
#live-panel .lp-state.REGULAR {background:rgba(74,222,128,.2);color:var(--green)}
#live-panel .lp-state.CLOSED  {background:rgba(90,106,130,.2);color:var(--tlo)}
#live-panel .ba{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:5px}
#live-panel .ba .col{padding:5px 8px;border-radius:3px;background:var(--bg2)}
#live-panel .ba .col.bid{border-left:2px solid var(--green)}
#live-panel .ba .col.ask{border-left:2px solid var(--red)}
#live-panel .ba .lbl{color:var(--tlo);font-size:8.5px;letter-spacing:.5px}
#live-panel .ba .px{color:var(--thi);font-weight:700;font-size:13px;margin-top:1px}
#live-panel .ba .sz{color:var(--tf);font-size:8px;margin-top:1px}
#live-panel .lp-close{cursor:pointer;color:var(--tlo);font-size:13px;padding:0 4px}
#live-panel .lp-close:hover{color:var(--red)}
`;
  const s = document.createElement('style'); s.id = 'live-v2-styles'; s.textContent = css;
  document.head.appendChild(s);
})();

// ── Inject live panel into DOM ─────────────────────────────
(function injectLivePanel() {
  if (document.getElementById('live-panel')) return;
  if (!document.body) return setTimeout(injectLivePanel, 100);
  const panel = document.createElement('div');
  panel.id = 'live-panel';
  panel.innerHTML = `
    <div class="lph">
      <span class="ttl"><span class="pulse"></span>LIVE QUOTE</span>
      <div style="display:flex;align-items:center;gap:6px">
        <span class="lp-state" id="lp-state">--</span>
        <span class="lp-close" id="lp-close">×</span>
      </div>
    </div>
    <div class="lprow"><span class="k">最新價</span><span class="v" id="lp-px">--</span></div>
    <div class="lprow"><span class="k">漲跌</span><span class="v" id="lp-chg">--</span></div>
    <div class="lprow"><span class="k">日內高/低</span><span class="v" id="lp-hl">-- / --</span></div>
    <div class="lprow"><span class="k">成交量</span><span class="v" id="lp-vol">--</span></div>
    <div class="ba">
      <div class="col bid">
        <div class="lbl">買 BID</div>
        <div class="px" id="lp-bid">--</div>
        <div class="sz" id="lp-bid-sz">size --</div>
      </div>
      <div class="col ask">
        <div class="lbl">賣 ASK</div>
        <div class="px" id="lp-ask">--</div>
        <div class="sz" id="lp-ask-sz">size --</div>
      </div>
    </div>
    <div style="margin-top:4px;font-size:7.5px;color:var(--tf);line-height:1.5;letter-spacing:.3px">資料源：Yahoo v8 chart 1m bar（台股延遲 ~15 min）<br>真即時 + 五檔需接券商 API（富邦/永豐/元大）</div>
    <div style="margin-top:4px;font-size:8px;color:var(--tf);letter-spacing:.5px;text-align:right">每 30 秒更新 · <span id="lp-time">--</span></div>`;
  document.body.appendChild(panel);
  document.getElementById('lp-close').onclick = liveDisable;
  attachLiveDrag(panel);
})();

// ── 拖曳：抓 header (.lph) 移動整個面板，位置存 localStorage ──
function attachLiveDrag(panel) {
  const LS_KEY = 'liveLivePanelPos';
  // 還原上次位置
  try {
    const saved = JSON.parse(localStorage.getItem(LS_KEY) || 'null');
    if (saved && typeof saved.left === 'number' && typeof saved.top === 'number') {
      // 用 left/top + clear right 才能自由移動
      panel.style.left = saved.left + 'px';
      panel.style.top  = saved.top  + 'px';
      panel.style.right = 'auto';
    }
  } catch {}

  const header = panel.querySelector('.lph');
  if (!header) return;
  let drag = null;   // {startX, startY, baseLeft, baseTop}

  header.addEventListener('mousedown', e => {
    // 點到 × 關閉鈕不要觸發拖曳
    if (e.target.closest('#lp-close')) return;
    e.preventDefault();
    // 計算當下實際 left/top（如果是 right-based 要先換算）
    const rect = panel.getBoundingClientRect();
    if (panel.style.right && panel.style.right !== 'auto') {
      panel.style.left = rect.left + 'px';
      panel.style.top  = rect.top  + 'px';
      panel.style.right = 'auto';
    }
    drag = {
      startX: e.clientX, startY: e.clientY,
      baseLeft: rect.left, baseTop: rect.top,
    };
    panel.classList.add('dragging');
  });

  document.addEventListener('mousemove', e => {
    if (!drag) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    // 用 viewport bounds 限制不要被拖出畫面
    const w = panel.offsetWidth, h = panel.offsetHeight;
    const maxL = window.innerWidth - 40;
    const maxT = window.innerHeight - 40;
    const left = Math.min(Math.max(-w + 60, drag.baseLeft + dx), maxL);
    const top  = Math.min(Math.max(0,         drag.baseTop  + dy), maxT);
    panel.style.left = left + 'px';
    panel.style.top  = top  + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!drag) return;
    drag = null;
    panel.classList.remove('dragging');
    // 持久化位置
    try {
      const rect = panel.getBoundingClientRect();
      localStorage.setItem(LS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
    } catch {}
  });

  // 雙擊 header → reset 回預設位置
  header.addEventListener('dblclick', e => {
    if (e.target.closest('#lp-close')) return;
    panel.style.left = '';
    panel.style.top = '80px';
    panel.style.right = '355px';
    try { localStorage.removeItem(LS_KEY); } catch {}
  });
}

// ── Polling ───────────────────────────────────────────────
async function fetchQuote(sym, mkt) {
  if (!sym) return null;
  const yfsym = mkt === 'TW' ? sym + '.TW' : sym;
  try {
    const SERVER = window.SERVER || `http://localhost:18432`;
    const r = await fetch(`${SERVER}/quote/${yfsym}`, {cache:'no-store'});
    if (!r.ok) {
      let errMsg = `HTTP ${r.status}`;
      try { const j = await r.json(); if (j.error) errMsg = j.error; } catch {}
      console.warn('[live] /quote failed:', yfsym, errMsg);
      return null;
    }
    const data = await r.json();
    console.log('[live] quote', yfsym, '=', data?.price, '(' + (data?.marketState || '?') + ')');
    return data;
  } catch (e) {
    console.warn('[live] fetch error:', e);
    return null;
  }
}

function renderQuote(q) {
  if (!q) return;
  _lastQuote = q;
  const px = q.price, ch = q.change, chPct = q.changePct;
  const col = (ch == null ? 'var(--tlo)' : (ch >= 0 ? 'var(--green)' : 'var(--red)'));
  document.getElementById('lp-px').textContent = px != null ? px.toFixed(2) : '--';
  document.getElementById('lp-px').style.color = col;
  document.getElementById('lp-chg').innerHTML = ch != null
    ? `<span style="color:${col}">${ch >= 0 ? '+' : ''}${ch.toFixed(2)} (${chPct >= 0 ? '+' : ''}${chPct.toFixed(2)}%)</span>`
    : '--';
  document.getElementById('lp-hl').textContent = (q.high != null && q.low != null) ? `${q.high.toFixed(2)} / ${q.low.toFixed(2)}` : '--';
  document.getElementById('lp-vol').textContent = q.volume != null
    ? (typeof formatVol === 'function' ? formatVol(q.volume) : q.volume.toLocaleString())
    : '--';
  // Bid/ask: Yahoo's free v7 endpoint has been gated since 2024 — show notice
  if (q.bid != null) {
    document.getElementById('lp-bid').textContent = q.bid.toFixed(2);
    document.getElementById('lp-ask').textContent = q.ask != null ? q.ask.toFixed(2) : '--';
    document.getElementById('lp-bid-sz').textContent = q.bidSize != null ? `size ${q.bidSize.toLocaleString()}` : 'size --';
    document.getElementById('lp-ask-sz').textContent = q.askSize != null ? `size ${q.askSize.toLocaleString()}` : 'size --';
  } else {
    document.getElementById('lp-bid').textContent = '—';
    document.getElementById('lp-ask').textContent = '—';
    document.getElementById('lp-bid-sz').textContent = 'Yahoo 不開放';
    document.getElementById('lp-ask-sz').textContent = '需券商 API';
  }
  const st = q.marketState || 'CLOSED';
  const stEl = document.getElementById('lp-state');
  stEl.textContent = stMap(st);
  stEl.className = 'lp-state ' + st;
  const d = new Date();
  document.getElementById('lp-time').textContent = `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;

  // Update last candle on chart if price moved
  if (S.chartSeries && S.data?.candles?.length && px != null) {
    const last = S.data.candles[S.data.candles.length - 1];
    try {
      S.chartSeries.update({
        time: last.time,
        open: last.open,
        high: Math.max(last.high, px),
        low: Math.min(last.low, px),
        close: px,
      });
      // Update topbar status
      const statEl = document.getElementById('stattxt');
      if (statEl) statEl.textContent = `LIVE · ${S.sym} ${px.toFixed(2)}`;
    } catch (e) { console.warn('[live] update failed:', e); }
  }
}

function stMap(s) {
  if (s === 'REGULAR') return '盤中';
  if (s === 'PRE')     return '盤前';
  if (s === 'POST')    return '盤後';
  if (s === 'CLOSED')  return '休市';
  return s || '--';
}

async function livePollOnce() {
  if (!S.liveEnabled || !S.sym) return;
  const q = await fetchQuote(S.sym, S.mkt || 'TW');
  if (q) renderQuote(q);
}

function liveEnable() {
  if (!S.sym) { alert('先載入個股'); return; }
  S.liveEnabled = true;
  document.getElementById('live-panel')?.classList.add('on');
  updateLiveBtn();
  livePollOnce();
  if (_liveTimer) clearInterval(_liveTimer);
  _liveTimer = setInterval(livePollOnce, LIVE_POLL_MS);
}
function liveDisable() {
  S.liveEnabled = false;
  document.getElementById('live-panel')?.classList.remove('on');
  updateLiveBtn();
  if (_liveTimer) { clearInterval(_liveTimer); _liveTimer = null; }
}
function liveToggle() { S.liveEnabled ? liveDisable() : liveEnable(); }
function updateLiveBtn() {
  const b = document.getElementById('btn-live');
  if (!b) return;
  b.classList.toggle('on', S.liveEnabled);
  b.textContent = S.liveEnabled ? '🟢 LIVE' : '⚪ LIVE';
  b.title = S.liveEnabled ? '即時報價已啟用（30 秒輪詢）— 點關閉' : '點擊啟用即時報價輪詢';
}

// Refresh on sym change
window.addEventListener('symLoaded', () => {
  if (S.liveEnabled) setTimeout(livePollOnce, 500);
});

// ── UI inject ──────────────────────────────────────────────
(function injectLiveButton() {
  if (!document.getElementById('pro-tools')) return setTimeout(injectLiveButton, 100);
  if (document.getElementById('btn-live')) return;
  const b = document.createElement('button');
  b.id = 'btn-live';
  b.className = 'probtn';
  b.title = '近即時報價（每 30 秒輪詢 Yahoo Quote API，含 bid/ask）';
  b.textContent = '⚪ LIVE';
  b.onclick = liveToggle;
  document.getElementById('pro-tools').appendChild(b);
})();

// ── Broker API placeholder for future Level 2 五檔 ─────────
// To wire a Taiwan broker for true 5-tier order book:
//   富邦 NeoAPI:  https://neoapi.fbs.com.tw/   (requires client account)
//   永豐 Shioaji:  https://sinotrade.github.io/  (Python SDK)
//   元大 SmartAPI: https://easywin.yuanta.com.tw/
// Implement window.brokerSubscribeDepth(sym, callback) and we'll auto-use it.
window.brokerSubscribeDepth = window.brokerSubscribeDepth || null;

// ── Expose ─────────────────────────────────────────────────
window.liveToggle    = liveToggle;
window.liveEnable    = liveEnable;
window.liveDisable   = liveDisable;
window.fetchQuote    = fetchQuote;

// ============================================================
// Stock Terminal v2.0 — Pro Features
// ------------------------------------------------------------
// 1. Browser Notification (watch triggers → push)
// 2. Compare Mode (overlay TWII / SPY benchmark)
// 3. Horizontal support/resistance lines (right-click chart)
// 4. Portfolio Risk Panel (POS tab)
// 5. Portfolio Heatmap (POS tab)
// 6. Volume Profile / POC (point of control overlay)
// 7. Replay Mode (slider hides future bars)
// 8. Backtesting (per-strategy historical performance)
//
// 載入順序：position_v2.js → watch_v2.js → info_v2.js → pro_v2.js
// ============================================================

const LS_KEY_LINES   = 'stock_terminal_drawn_lines_v2';   // {SYM: [{price, color, label}]}
const LS_KEY_NOTIFY  = 'stock_terminal_notify_v2';        // {enabled, triggered: {sigId: lastNotified}}

// ── Pro state bootstrap ────────────────────────────────────
(function bootPro() {
  if (typeof S === 'undefined') return;
  try { S.lines = JSON.parse(localStorage.getItem(LS_KEY_LINES) || '{}'); } catch { S.lines = {}; }
  try { S.notify = JSON.parse(localStorage.getItem(LS_KEY_NOTIFY) || '{}'); } catch { S.notify = {}; }
  if (typeof S.notify !== 'object' || !S.notify) S.notify = {};
  if (!S.notify.triggered) S.notify.triggered = {};
  if (!Array.isArray(S.notify.history)) S.notify.history = [];   // 通知歷史記錄
  if (S.notify.unread == null) S.notify.unread = 0;
  S.compareSym = null;       // current benchmark overlay (e.g. ^TWII)
  S.compareSeries = null;
  S.replay = null;            // {idx, total} when in replay mode
  S.priceLines = [];          // tracking PriceLine objects to remove on re-render
  console.log('[v2-pro] booted —', Object.keys(S.lines).length, 'lines /', S.notify.history.length, 'history entries');
})();

function savePro() {
  localStorage.setItem(LS_KEY_LINES, JSON.stringify(S.lines || {}));
  localStorage.setItem(LS_KEY_NOTIFY, JSON.stringify(S.notify || {}));
}

// ── CSS additions for pro UI ───────────────────────────────
(function injectProCSS() {
  const css = `
.probtn{padding:3px 8px;background:transparent;border:1px solid var(--border);border-radius:4px;color:var(--tlo);font-family:'JetBrains Mono',monospace;font-size:9.5px;cursor:pointer;letter-spacing:.3px;transition:all .12s;height:24px;display:inline-flex;align-items:center;gap:3px;white-space:nowrap}
.probtn:hover{color:var(--gold);border-color:var(--gold-m);background:var(--gold-s)}
.probtn.on{color:var(--gold);border-color:var(--gold);background:var(--gold-s);font-weight:700}
.pro-tools{display:flex;align-items:center;gap:4px;padding:0 6px;border-left:1px solid var(--border);height:30px;background:var(--bg2);flex-shrink:0}
.linemenu{position:fixed;z-index:5000;background:var(--bg2);border:1px solid var(--gold-m);border-radius:6px;padding:4px;box-shadow:0 6px 20px rgba(0,0,0,.5);display:flex;flex-direction:column;gap:2px;min-width:140px}
.linemenu-item{padding:6px 10px;font-family:monospace;font-size:10px;color:var(--text);cursor:pointer;border-radius:3px;display:flex;align-items:center;gap:6px}
.linemenu-item:hover{background:var(--bg3);color:var(--gold)}
.linemenu-item.danger:hover{background:rgba(248,113,113,.15);color:var(--red)}
.heatcell{display:flex;flex-direction:column;justify-content:center;align-items:center;border-radius:3px;padding:6px;font-family:'JetBrains Mono',monospace;cursor:pointer;transition:transform .12s;min-height:55px;text-align:center;overflow:hidden}
.heatcell:hover{transform:scale(1.04)}
.heatcell-sym{font-size:11px;font-weight:700;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.5)}
.heatcell-pnl{font-size:9px;color:rgba(255,255,255,.92);margin-top:2px;text-shadow:0 1px 2px rgba(0,0,0,.5)}
#replay-bar{display:none;align-items:center;gap:8px;padding:4px 12px;background:var(--bg2);border-bottom:1px solid var(--gold-m);font-family:monospace;font-size:10px;color:var(--gold)}
#replay-bar.on{display:flex}
#replay-slider{flex:1;height:4px;cursor:pointer}
.bt-result-row{display:flex;justify-content:space-between;padding:5px 12px;border-bottom:1px solid var(--bg3);font-family:monospace;font-size:10px}
.bt-result-row .lbl{color:var(--tlo)}
.bt-result-row .val{color:var(--thi);font-weight:700}
`;
  const s = document.createElement('style');
  s.id = 'pro-v2-styles';
  s.textContent = css;
  document.head.appendChild(s);
})();

// ============================================================
// 1. BROWSER NOTIFICATION
// ============================================================
function notifyEnable() {
  if (!('Notification' in window)) { alert('您的瀏覽器不支援通知'); return false; }
  if (Notification.permission === 'granted') {
    S.notify.enabled = true; savePro(); updateNotifyBtn();
    new Notification('Stock Terminal', {body:'通知已啟用 ✓ WATCH 觸發時會推播', silent:true});
    return true;
  }
  if (Notification.permission === 'denied') {
    alert('通知已被拒絕。請至瀏覽器設定 → 此網站 → 通知 → 允許');
    return false;
  }
  Notification.requestPermission().then(p => {
    if (p === 'granted') { S.notify.enabled = true; savePro(); updateNotifyBtn(); new Notification('Stock Terminal', {body:'通知已啟用 ✓', silent:true}); }
  });
}
function notifyDisable() { S.notify.enabled = false; savePro(); updateNotifyBtn(); }
function notifyToggle() { S.notify.enabled ? notifyDisable() : notifyEnable(); }

function updateNotifyBtn() {
  const b = document.getElementById('btn-notify');
  if (!b) return;
  const on = S.notify.enabled && Notification.permission === 'granted';
  b.classList.toggle('on', on);
  const unread = S.notify.unread || 0;
  const badge = unread > 0 ? `<span style="background:var(--red);color:#fff;font-size:8px;padding:1px 4px;border-radius:8px;margin-left:4px;font-weight:700;line-height:1">${unread}</span>` : '';
  b.innerHTML = (on ? '🔔' : '🔕') + ' 通知' + badge;
  b.title = '點擊查看通知歷史 / 切換啟用';
}

// ── Notification dropdown panel ────────────────────────────
function notifyPanelToggle() {
  const ex = document.getElementById('notify-panel');
  if (ex) { ex.remove(); return; }
  const panel = document.createElement('div');
  panel.id = 'notify-panel';
  panel.style.cssText = 'position:fixed;top:50px;right:8px;width:340px;max-height:480px;background:var(--bg2);border:1px solid var(--gold-m);border-radius:8px;z-index:5000;box-shadow:0 12px 36px rgba(0,0,0,.6);display:flex;flex-direction:column;overflow:hidden';
  const enabled = S.notify.enabled && Notification.permission === 'granted';
  panel.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-bottom:1px solid var(--border);background:var(--bg)">
      <span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;color:var(--gold);letter-spacing:1px">📋 通知中心</span>
      <span data-pro="notify-close" style="cursor:pointer;color:var(--tlo);font-size:18px;line-height:1;padding:0 4px">×</span>
    </div>
    <div style="padding:9px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:var(--bg)">
      <span style="font-family:monospace;font-size:10px;color:${enabled?'var(--green)':'var(--tlo)'}">
        ${enabled ? '✓ 瀏覽器推播已啟用' : '✕ 瀏覽器推播已停用'}
      </span>
      <button data-pro="notify-toggle-en" style="padding:3px 10px;background:transparent;border:1px solid ${enabled?'var(--red)':'var(--green)'};border-radius:4px;color:${enabled?'var(--red)':'var(--green)'};font-family:monospace;font-size:9px;cursor:pointer">${enabled ? '停用' : '啟用'}</button>
    </div>
    <div style="padding:7px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:var(--bg)">
      <span style="font-family:monospace;font-size:9.5px;color:var(--tlo)">🌙 24h 後端自動偵測<br><span style="font-size:8px;color:var(--tf)">瀏覽器關著也偵測，觸發推 Telegram/Email</span></span>
      <button data-pro="watch-bg" id="watch-bg-btn" style="padding:3px 10px;background:transparent;border:1px solid var(--border);border-radius:4px;color:var(--tlo);font-family:monospace;font-size:9px;cursor:pointer">…</button>
    </div>
    <div style="padding:6px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:var(--bg)">
      <span style="font-family:monospace;font-size:9.5px;color:var(--tlo)">歷史 ${S.notify.history.length} 筆，未讀 ${S.notify.unread || 0}</span>
      <div>
        <button data-pro="notify-scan" style="padding:2px 8px;background:var(--gold-s);border:1px solid var(--gold-m);border-radius:3px;color:var(--gold);font-family:monospace;font-size:8.5px;cursor:pointer;margin-right:4px">🔍 偵測</button>
        <button data-pro="notify-mark-read" style="padding:2px 8px;background:transparent;border:1px solid var(--border);border-radius:3px;color:var(--tlo);font-family:monospace;font-size:8.5px;cursor:pointer;margin-right:4px">標記已讀</button>
        <button data-pro="notify-clear" style="padding:2px 8px;background:transparent;border:1px solid var(--border);border-radius:3px;color:var(--red);font-family:monospace;font-size:8.5px;cursor:pointer">清除</button>
      </div>
    </div>
    <div style="overflow-y:auto;flex:1;max-height:340px" id="notify-list">
      ${renderNotifyList()}
    </div>
    <div style="padding:6px 12px;background:var(--bg);font-family:monospace;font-size:8px;color:var(--tf);border-top:1px solid var(--border);text-align:center">點擊任一筆跳轉到該股 · 通知保留最近 100 筆</div>`;
  document.body.appendChild(panel);
  refreshWatchBgBtn();
  // Close on outside click
  setTimeout(() => {
    document.addEventListener('mousedown', _notifyOutClose, {capture: true});
  }, 0);
  // Mark all as read after open
  if (S.notify.unread > 0) {
    S.notify.unread = 0;
    savePro();
    setTimeout(updateNotifyBtn, 100);
  }
}
function _notifyOutClose(ev) {
  const p = document.getElementById('notify-panel');
  if (p && !p.contains(ev.target) && !ev.target.closest('#btn-notify')) {
    p.remove();
    document.removeEventListener('mousedown', _notifyOutClose, {capture: true});
  }
}

function renderNotifyList() {
  if (!S.notify.history?.length) {
    return '<div style="padding:24px;text-align:center;font-family:monospace;font-size:10px;color:var(--tf)">尚無通知<br><span style="font-size:8.5px">WATCH 觸發時會自動記錄</span></div>';
  }
  let h = '';
  for (const e of S.notify.history) {
    const isTrig = e.status === 'trigger';
    const col = isTrig ? 'var(--green)' : 'var(--red)';
    const bg  = isTrig ? 'rgba(74,222,128,.06)' : 'rgba(248,113,113,.06)';
    const ago = timeAgo(e.ts);
    h += `<div data-pro="notify-goto" data-sym="${e.sym}" data-mkt="${e.mkt}"
      style="padding:8px 12px;border-bottom:1px solid var(--border);cursor:pointer;background:${bg};transition:background .12s"
      onmouseover="this.style.background='var(--bg3)'"
      onmouseout="this.style.background='${bg}'">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
        <span style="font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:700;color:${col}">${e.icon} ${escNo(e.sym)} — ${escNo(e.stratLbl)}</span>
        <span style="font-family:monospace;font-size:8.5px;color:var(--tf);white-space:nowrap">${ago}</span>
      </div>
      <div style="font-family:monospace;font-size:9px;color:var(--text);margin-top:3px;line-height:1.5">${escNo(e.detail)}</div>
    </div>`;
  }
  return h;
}

function timeAgo(ts) {
  const sec = Math.floor((Date.now() - ts) / 1000);
  if (sec < 60) return `${sec} 秒前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小時前`;
  const d = new Date(ts);
  return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

function escNo(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function notifyClearHistory() {
  if (!confirm('清除全部通知歷史？')) return;
  S.notify.history = [];
  S.notify.unread = 0;
  savePro();
  updateNotifyBtn();
  const list = document.getElementById('notify-list');
  if (list) list.innerHTML = renderNotifyList();
}

function notifyMarkAllRead() {
  S.notify.unread = 0;
  savePro();
  updateNotifyBtn();
}

// Wire dropdown actions
document.addEventListener('click', ev => {
  const el = ev.target.closest('[data-pro]');
  if (!el) return;
  const act = el.dataset.pro;
  if (act === 'notify-close')      { document.getElementById('notify-panel')?.remove(); }
  if (act === 'notify-clear')      { notifyClearHistory(); }
  if (act === 'notify-mark-read')  { notifyMarkAllRead(); }
  if (act === 'notify-scan')       { scanAllWatches(el); }
  if (act === 'watch-bg')          { toggleWatchBg(el); }
  if (act === 'notify-toggle-en')  { notifyToggle(); document.getElementById('notify-panel')?.remove(); setTimeout(notifyPanelToggle, 100); }
  if (act === 'notify-goto') {
    const sym = el.dataset.sym, mkt = el.dataset.mkt || 'TW';
    if (sym && typeof loadSym === 'function') loadSym(sym, mkt);
    document.getElementById('notify-panel')?.remove();
  }
});

// Fire notification for newly-triggered signals
function fireSignalNotifications(force) {
  if (!S.watches) return;
  // v3.8: 訊號只在「日線」決策 timeframe 評估。
  // 切到周線/月線/盤中線時 SMA 等指標意義不同，狀態會在 trigger<->none 翻動，
  // 把去重狀態洗掉造成切回日線重複跳通知。日線各區間(1月~全部)最新指標值相同→穩定。
  // force=true（手動偵測）已用各股日線資料評估，略過此閘門。
  if (!force) {
    try {
      const ivl = (typeof currentRangeDef === 'function') ? currentRangeDef().interval : '1d';
      if (ivl !== '1d') return;
    } catch {}
  }
  let newCount = 0;
  for (const code in S.watches) {
    const w = S.watches[code];
    for (const sig of (w.signals || [])) {
      const status = sig.lastEval?.status;
      const prevKey = `${code}:${sig.id}`;
      const prevStatus = S.notify.triggered[prevKey];
      if ((status === 'trigger' || status === 'broken') && prevStatus !== status) {
        const strat = STRATEGIES.find(s => s.key === sig.strategy);
        const lbl = strat ? strat.lbl : sig.strategy;
        const icon = status === 'trigger' ? '🎯' : '⚠️';
        const detail = sig.lastEval?.detail || '';
        // Always log to history (even if browser notify disabled)
        S.notify.history.unshift({
          ts:   Date.now(),
          sym:  code,
          mkt:  w.mkt || 'TW',
          icon, status,
          stratKey: sig.strategy, stratLbl: lbl,
          detail,
          read: false,
        });
        if (S.notify.history.length > 100) S.notify.history.length = 100;   // cap at 100
        S.notify.unread = (S.notify.unread || 0) + 1;
        newCount++;
        // Browser notification only if user enabled
        if (S.notify.enabled && Notification.permission === 'granted') {
          try {
            new Notification(`${icon} ${code} — ${lbl}`, {
              body: detail,
              tag: prevKey,
              requireInteraction: false,
              silent: false,
            });
          } catch (e) { console.warn('[v2-pro] notify failed:', e); }
        }
        S.notify.triggered[prevKey] = status;
      } else if (status !== 'trigger' && status !== 'broken' && prevStatus) {
        delete S.notify.triggered[prevKey];
      }
    }
  }
  if (newCount > 0) {
    savePro();
    updateNotifyBtn();
  }
}

// Hook: after every symLoaded (which refreshes watches), check for new triggers
window.addEventListener('symLoaded', () => setTimeout(fireSignalNotifications, 200));

// v3.8: 主動偵測 — 抓所有觀察股的日線，逐檔算指標、評估訊號後推播
// （不必先點開每檔；用各股自己的日線資料，故 fireSignalNotifications(force)）
let _scanning = false;
async function scanAllWatches(btn) {
  if (_scanning) return;
  if (!S.watches || !Object.keys(S.watches).length) { alert('觀察清單是空的，先到 WATCH 加股票與訊號'); return; }
  if (typeof parseYF !== 'function' || typeof runWorker !== 'function' || typeof evaluateSignal !== 'function') {
    alert('偵測所需函式未就緒，請重新整理'); return;
  }
  _scanning = true;
  const SRV = window.SERVER || 'http://localhost:18432';
  const codes = Object.keys(S.watches);
  if (btn) { btn.disabled = true; btn.textContent = '偵測中…'; }
  let done = 0, ok = 0;
  // 限制併發，避免一次太多請求
  const queue = codes.slice();
  async function worker() {
    while (queue.length) {
      const code = queue.shift();
      const w = S.watches[code];
      const yf = (w && w.mkt === 'US') ? code : code + '.TW';
      try {
        let raw = await fetch(`${SRV}/yf/${yf}?range=1y&interval=1d`, { cache: 'no-store' }).then(r => r.ok ? r.json() : null);
        let parsed = raw ? parseYF(raw) : null;
        if ((!parsed || !parsed.candles.length) && (!w || w.mkt !== 'US')) {
          raw = await fetch(`${SRV}/yf/${code}.TWO?range=1y&interval=1d`, { cache: 'no-store' }).then(r => r.ok ? r.json() : null);
          parsed = raw ? parseYF(raw) : null;
        }
        if (parsed && parsed.candles.length >= 20) {
          const ind = await runWorker(parsed.candles);
          for (const sig of (w.signals || [])) {
            try { sig.lastEval = evaluateSignal(sig, ind, parsed.candles); } catch {}
          }
          ok++;
        }
      } catch (e) { console.warn('[scan]', code, e); }
      done++;
      if (btn) btn.textContent = `偵測中 ${done}/${codes.length}`;
    }
  }
  try {
    await Promise.all([worker(), worker(), worker(), worker()]);   // 4 併發
    if (typeof saveWatches === 'function') { try { saveWatches(); } catch {} }
    fireSignalNotifications(true);   // force：已用日線評估，略過 timeframe 閘門
    const list = document.getElementById('notify-list');
    if (list) list.innerHTML = renderNotifyList();
  } finally {
    _scanning = false;
    if (btn) { btn.disabled = false; btn.textContent = '🔍 偵測'; }
  }
}

// v3.8: WATCH 後端 24h 偵測開關
function refreshWatchBgBtn() {
  const btn = document.getElementById('watch-bg-btn');
  if (!btn) return;
  const SRV = window.SERVER || 'http://localhost:18432';
  fetch(`${SRV}/watch/status`, { cache: 'no-store' }).then(r => r.json()).then(s => {
    const on = !!s.enabled;
    btn.dataset.on = on ? '1' : '0';
    btn.textContent = on ? '停用' : '啟用';
    btn.style.color = on ? 'var(--red)' : 'var(--green)';
    btn.style.borderColor = on ? 'var(--red)' : 'var(--green)';
    btn.title = on ? `執行中 · 規則 ${s.rules_count} 檔 · 上次 ${s.last_run || '—'}` : '點擊啟用後端 24h 偵測';
  }).catch(() => { btn.textContent = '啟用'; });
}
async function toggleWatchBg(btn) {
  const SRV = window.SERVER || 'http://localhost:18432';
  const on = btn.dataset.on === '1';
  if (!on) {
    // 啟用前先把目前觀察清單同步給後端
    if (typeof syncWatchesToServer === 'function') syncWatchesToServer();
  }
  try {
    const r = await fetch(`${SRV}/watch/config`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !on }),
    });
    const d = await r.json();
    if (d.ok) {
      alert(!on ? '已啟用 24h 後端偵測 ✓\n（需在 🔔 推播設好 Telegram/Email）' : '已停用後端偵測');
      refreshWatchBgBtn();
    } else alert('設定失敗：' + JSON.stringify(d));
  } catch (e) { alert('設定失敗：' + e.message + '\n請確認 server 跑著'); }
}

// ============================================================
// 2. COMPARE MODE (overlay benchmark)
// ============================================================
const BENCHMARKS = {
  TW: {sym:'^TWII', name:'加權指數'},
  US: {sym:'^GSPC', name:'S&P 500'},
};
async function compareToggle() {
  const btn = document.getElementById('btn-compare');
  if (S.compareSym) { compareRemove(); btn?.classList.remove('on'); return; }
  const bm = BENCHMARKS[S.mkt || 'TW'];
  if (!bm) { alert('此市場無預設指標'); return; }
  btn?.classList.add('on'); btn && (btn.textContent = '🔄 載入中');
  try {
    const rdef = currentRangeDef();
    const raw = await fetchYF(bm.sym, rdef);
    const parsed = parseYF(raw);
    if (!parsed || !parsed.candles?.length) { alert('無法載入大盤'); btn?.classList.remove('on'); btn && (btn.textContent='vs 大盤'); return; }
    compareDraw(parsed.candles, bm.name);
    btn && (btn.textContent = `vs ${bm.name}`);
  } catch (e) {
    alert('比較失敗：' + e.message);
    btn?.classList.remove('on'); btn && (btn.textContent='vs 大盤');
  }
}
function compareDraw(benchCandles, label) {
  if (!S.chart || !S.data) return;
  compareRemove();
  // Normalize both to start at 100 (relative performance)
  const sCandles = S.data.candles;
  if (!sCandles.length || !benchCandles.length) return;
  const sBase = sCandles[0].close;
  const bBase = benchCandles[0].close;
  // Map benchmark closes by time
  const bMap = new Map();
  for (const c of benchCandles) bMap.set(c.time, c.close);
  // Build series: only times present in BOTH
  const data = [];
  for (const c of sCandles) {
    const b = bMap.get(c.time);
    if (b == null) continue;
    data.push({time: c.time, value: (b / bBase) * sBase});
  }
  S.compareSeries = S.chart.addLineSeries({
    color: '#FB923C', lineWidth: 2,
    lastValueVisible: true,
    title: label,
    crosshairMarkerVisible: false,
  });
  S.compareSeries.setData(data);
  S.compareSym = label;
}
function compareRemove() {
  if (S.compareSeries && S.chart) try { S.chart.removeSeries(S.compareSeries); } catch {}
  S.compareSeries = null; S.compareSym = null;
  const b = document.getElementById('btn-compare');
  if (b) b.textContent = 'vs 大盤';
}

// ============================================================
// 3. HORIZONTAL SUPPORT/RESISTANCE LINES (right-click chart)
// ============================================================
function getLines(sym) {
  if (!S.lines) S.lines = {};
  return S.lines[sym] || (S.lines[sym] = []);
}
function addLine(sym, price, color, label) {
  const lines = getLines(sym);
  lines.push({price: parseFloat(price), color: color || '#F5C518', label: label || price.toFixed(2)});
  savePro();
  drawLines();
}
function removeLine(sym, idx) {
  const lines = getLines(sym);
  lines.splice(idx, 1);
  savePro();
  drawLines();
}
function clearLines(sym) {
  if (S.lines) delete S.lines[sym];
  savePro();
  drawLines();
}
function drawLines() {
  if (!S.chart || !S.chartSeries) return;
  // Remove old price lines
  for (const pl of (S.priceLines || [])) try { S.chartSeries.removePriceLine(pl); } catch {}
  S.priceLines = [];
  // Draw fresh
  const lines = getLines(S.sym);
  for (const ln of lines) {
    try {
      const pl = S.chartSeries.createPriceLine({
        price: ln.price,
        color: ln.color,
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: ln.label || '',
      });
      S.priceLines.push(pl);
    } catch (e) { console.warn('[v2-pro] line draw failed:', e); }
  }
}
function attachChartContext() {
  const wrap = document.getElementById('chart-wrap');
  if (!wrap) return;
  if (wrap._proCtxAttached) return;
  wrap._proCtxAttached = true;
  wrap.addEventListener('contextmenu', e => {
    e.preventDefault();
    if (!S.chart || !S.chartSeries || !S.sym) return;
    // Get price at click position via chart coordinate
    const rect = wrap.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const price = S.chartSeries.coordinateToPrice(y);
    if (price == null) return;
    showLineMenu(e.clientX, e.clientY, price);
  });
}
function showLineMenu(x, y, price) {
  hideLineMenu();
  const menu = document.createElement('div');
  menu.className = 'linemenu';
  menu.id = 'pro-linemenu';
  menu.innerHTML =
    `<div class="linemenu-item" data-pro="line-add" data-color="#F5C518" data-price="${price}">➕ 加金線 (壓力) @${price.toFixed(2)}</div>` +
    `<div class="linemenu-item" data-pro="line-add" data-color="#4ADE80" data-price="${price}">➕ 加綠線 (支撐) @${price.toFixed(2)}</div>` +
    `<div class="linemenu-item" data-pro="line-add" data-color="#F87171" data-price="${price}">➕ 加紅線 (停損) @${price.toFixed(2)}</div>` +
    `<div style="border-top:1px solid var(--border);margin:2px 0"></div>` +
    `<div class="linemenu-item danger" data-pro="line-clear">✕ 清除全部線</div>`;
  document.body.appendChild(menu);
  const W = 220, rect = menu.getBoundingClientRect();
  const left = Math.min(x, window.innerWidth - W - 4);
  const top  = Math.min(y, window.innerHeight - rect.height - 4);
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
  setTimeout(() => document.addEventListener('mousedown', _hideLineMenu, {capture:true, once:true}), 0);
}
function hideLineMenu() {
  const m = document.getElementById('pro-linemenu');
  if (m) m.remove();
}
function _hideLineMenu(ev) {
  const m = document.getElementById('pro-linemenu');
  if (m && !m.contains(ev.target)) hideLineMenu();
}

// Click delegation for line menu actions
document.addEventListener('click', ev => {
  const el = ev.target.closest('[data-pro]');
  if (!el) return;
  const act = el.dataset.pro;
  if (act === 'line-add') {
    const price = parseFloat(el.dataset.price);
    const color = el.dataset.color;
    addLine(S.sym, price, color);
    hideLineMenu();
  }
  if (act === 'line-clear') {
    if (confirm('清除 ' + S.sym + ' 全部繪製線？')) clearLines(S.sym);
    hideLineMenu();
  }
});

// ============================================================
// 4 + 5. PORTFOLIO RISK PANEL & HEATMAP (extends POS tab)
// ============================================================
function computePortfolioMetrics() {
  const positions = S.positions || {};
  const codes = Object.keys(positions);
  if (codes.length === 0) return null;
  let totalCost = 0, totalValue = 0, totalPnl = 0;
  const items = [];
  for (const code of codes) {
    const p = positions[code];
    const ref = code === S.sym?.toUpperCase()
      ? (S.data?.candles?.[S.data.candles.length-1]?.close ?? p.lastPrice)
      : p.lastPrice;
    const cost = p.entry * p.shares;
    const val  = ref != null ? ref * p.shares : cost;
    const pnl  = ref != null ? (ref - p.entry) * p.shares : 0;
    const pnlPct = ref != null ? ((ref - p.entry) / p.entry * 100) : 0;
    totalCost += cost; totalValue += val; totalPnl += pnl;
    items.push({code, cost, val, pnl, pnlPct, ref, shares: p.shares});
  }
  // Sort by market value desc
  items.sort((a, b) => b.val - a.val);
  // Concentration: top 1, top 3, HHI
  const wts = items.map(x => x.val / totalValue);
  const top1 = wts[0] * 100;
  const top3 = wts.slice(0, 3).reduce((s, w) => s + w, 0) * 100;
  const hhi = wts.reduce((s, w) => s + w * w, 0);   // 0~1, higher = more concentrated
  // Risk warnings
  const warnings = [];
  if (top1 > 40) warnings.push({lvl:'red',  msg:`單股 ${items[0].code} 佔 ${top1.toFixed(0)}%（建議 ≤ 30%）`});
  else if (top1 > 30) warnings.push({lvl:'yellow', msg:`單股 ${items[0].code} 佔 ${top1.toFixed(0)}%（接近上限）`});
  if (codes.length < 3) warnings.push({lvl:'yellow', msg:`持股集中度高（僅 ${codes.length} 檔），建議至少 3~5 檔分散`});
  if (hhi > 0.5) warnings.push({lvl:'red', msg:`HHI 集中度 ${hhi.toFixed(2)}（> 0.5 風險高）`});
  return {totalCost, totalValue, totalPnl, totalPnlPct: totalCost > 0 ? totalPnl/totalCost*100 : 0, items, top1, top3, hhi, warnings};
}

function renderPortfolioRisk() {
  const m = computePortfolioMetrics();
  if (!m) return '';
  const pnlCol = m.totalPnl >= 0 ? 'var(--green)' : 'var(--red)';
  let h = '<div class="stat-sect">投資組合風險</div>';
  h += `<div class="stat-row"><span class="stat-k">總成本</span><span class="stat-v">${Math.round(m.totalCost).toLocaleString()}</span></div>`;
  h += `<div class="stat-row"><span class="stat-k">總市值</span><span class="stat-v">${Math.round(m.totalValue).toLocaleString()}</span></div>`;
  h += `<div class="stat-row"><span class="stat-k">合計損益</span><span class="stat-v" style="color:${pnlCol}">${m.totalPnl>=0?'+':''}${m.totalPnlPct.toFixed(2)}% (${m.totalPnl>=0?'+':''}${Math.round(m.totalPnl).toLocaleString()})</span></div>`;
  h += `<div class="stat-row"><span class="stat-k">最大單股佔比</span><span class="stat-v">${m.top1.toFixed(1)}%</span></div>`;
  h += `<div class="stat-row"><span class="stat-k">前 3 檔佔比</span><span class="stat-v">${m.top3.toFixed(1)}%</span></div>`;
  h += `<div class="stat-row"><span class="stat-k">HHI 集中度</span><span class="stat-v">${m.hhi.toFixed(3)}</span></div>`;
  if (m.warnings.length) {
    h += '<div style="padding:6px 12px 0">';
    for (const w of m.warnings) {
      const col = w.lvl === 'red' ? 'var(--red)' : 'var(--orange)';
      const bg = w.lvl === 'red' ? 'rgba(248,113,113,.1)' : 'rgba(251,146,60,.1)';
      h += `<div style="padding:5px 8px;margin-bottom:4px;background:${bg};border-left:3px solid ${col};border-radius:0 3px 3px 0;font-family:monospace;font-size:9.5px;color:var(--text);line-height:1.5">⚠ ${w.msg}</div>`;
    }
    h += '</div>';
  }
  // Heatmap
  h += '<div class="stat-sect">部位熱力圖</div>';
  h += '<div style="padding:8px 12px;display:grid;grid-template-columns:repeat(2,1fr);gap:4px">';
  for (const item of m.items) {
    const wt = item.val / m.totalValue;
    const col = item.pnl >= 0
      ? `rgba(74,222,128,${0.25 + Math.min(0.6, Math.abs(item.pnlPct) / 30)})`
      : `rgba(248,113,113,${0.25 + Math.min(0.6, Math.abs(item.pnlPct) / 30)})`;
    h += `<div class="heatcell" data-pro="goto-pos" data-sym="${item.code}" style="background:${col};grid-column:span ${wt > 0.4 ? 2 : 1}">
      <div class="heatcell-sym">${item.code}</div>
      <div class="heatcell-pnl">${item.pnlPct >= 0 ? '+' : ''}${item.pnlPct.toFixed(1)}%</div>
      <div class="heatcell-pnl" style="font-size:8px;opacity:.85">${(wt*100).toFixed(0)}%</div>
    </div>`;
  }
  h += '</div>';
  return h;
}

// Hook into renderPosition to append risk panel + heatmap
(function patchRenderPosition() {
  if (typeof renderPosition !== 'function') return setTimeout(patchRenderPosition, 100);
  const orig = window.renderPosition;
  window.renderPosition = function () {
    let h = orig.apply(this, arguments);
    const risk = renderPortfolioRisk();
    if (risk) {
      // Insert risk + heatmap before the "新增觀察" footer (find first stat-sect after content)
      h = risk + h;   // Show risk panel at top of POS tab
    }
    return h;
  };
})();

// Click delegation for heatmap goto
document.addEventListener('click', ev => {
  const el = ev.target.closest('[data-pro="goto-pos"]');
  if (!el) return;
  const sym = el.dataset.sym;
  if (sym && typeof loadSym === 'function') loadSym(sym, S.positions[sym]?.mkt || S.mkt || 'TW');
});

// ============================================================
// 6. VOLUME PROFILE — POC line + volume-by-price right histogram
// ============================================================
function computeVolumeProfile(candles, bins) {
  bins = bins || 24;
  if (!candles?.length) return null;
  const lo = Math.min(...candles.map(c => c.low));
  const hi = Math.max(...candles.map(c => c.high));
  const step = (hi - lo) / bins;
  if (step <= 0) return null;
  const buckets = new Array(bins).fill(0);
  for (const c of candles) {
    const mid = (c.high + c.low) / 2;
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((mid - lo) / step)));
    buckets[idx] += c.volume || 0;
  }
  // Find POC (Point of Control = price bucket with max volume)
  let pocIdx = 0;
  for (let i = 1; i < bins; i++) if (buckets[i] > buckets[pocIdx]) pocIdx = i;
  const pocPrice = lo + (pocIdx + 0.5) * step;
  return {lo, hi, step, buckets, pocIdx, pocPrice, totalVol: buckets.reduce((s,v)=>s+v,0)};
}
function drawVolumeProfile() {
  if (!S.chart || !S.chartSeries || !S.data?.candles) return;
  // Remove prior POC line
  if (S.pocLine) try { S.chartSeries.removePriceLine(S.pocLine); } catch {}
  S.pocLine = null;
  if (!S.vpEnabled) return;
  const vp = computeVolumeProfile(S.data.candles, 24);
  if (!vp) return;
  S.pocLine = S.chartSeries.createPriceLine({
    price: vp.pocPrice,
    color: '#A78BFA',
    lineWidth: 2,
    lineStyle: LightweightCharts.LineStyle.Dotted,
    axisLabelVisible: true,
    title: 'POC',
  });
}
function vpToggle() {
  S.vpEnabled = !S.vpEnabled;
  const b = document.getElementById('btn-vp');
  if (b) b.classList.toggle('on', S.vpEnabled);
  drawVolumeProfile();
}

// ============================================================
// 7. REPLAY MODE
// ============================================================
function replayEnter() {
  if (!S.data?.candles?.length) { alert('先載入資料'); return; }
  S.replay = {idx: Math.max(20, S.data.candles.length - 30), total: S.data.candles.length, originalCandles: S.data.candles};
  document.getElementById('replay-bar').classList.add('on');
  const slider = document.getElementById('replay-slider');
  slider.min = 20; slider.max = S.replay.total - 1; slider.value = S.replay.idx;
  slider.oninput = e => {
    S.replay.idx = parseInt(e.target.value, 10);
    replayApply();
  };
  document.getElementById('btn-replay')?.classList.add('on');
  replayApply();
}
function replayExit() {
  if (S.replay) {
    S.data.candles = S.replay.originalCandles;
    S.replay = null;
    if (typeof renderChart === 'function') renderChart(S.data.candles);
  }
  document.getElementById('replay-bar').classList.remove('on');
  document.getElementById('btn-replay')?.classList.remove('on');
}
function replayApply() {
  if (!S.replay) return;
  const subset = S.replay.originalCandles.slice(0, S.replay.idx + 1);
  S.data.candles = subset;
  if (typeof renderChart === 'function') renderChart(subset);
  // Update label
  const c = subset[subset.length - 1];
  if (c) {
    const d = new Date(c.time * 1000);
    document.getElementById('replay-date').textContent = `${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}  (${S.replay.idx + 1}/${S.replay.total})`;
  }
}
function replayToggle() { S.replay ? replayExit() : replayEnter(); }
function replayStep(delta) {
  if (!S.replay) return;
  S.replay.idx = Math.max(20, Math.min(S.replay.total - 1, S.replay.idx + delta));
  document.getElementById('replay-slider').value = S.replay.idx;
  replayApply();
}

// ============================================================
// 8. BACKTESTING — per-strategy historical performance
// ============================================================
function backtest(stratKey, params, candles, holdDays) {
  const strat = STRATEGIES.find(s => s.key === stratKey);
  if (!strat || !candles || candles.length < 70) return null;
  holdDays = holdDays || 20;
  const trades = [];
  // Walk through candles, evaluate strategy at each bar, simulate trade
  let i = 60;   // skip warmup for indicators
  while (i < candles.length - holdDays - 1) {
    const sub = candles.slice(0, i + 1);
    const ind = mockInd(sub);
    let r;
    try { r = strat.check(ind, sub, params || {}); } catch { r = null; }
    if (r?.status === 'trigger') {
      const entry = candles[i + 1].open;     // enter next bar open
      const exit  = candles[i + holdDays].close;
      const ret = (exit - entry) / entry * 100;
      trades.push({date: candles[i].time, entry, exit, ret});
      i += holdDays;   // wait for trade to finish before next
    } else {
      i++;
    }
  }
  if (trades.length === 0) return {trades:[], summary:'無交易訊號'};
  const wins = trades.filter(t => t.ret > 0).length;
  const totalRet = trades.reduce((s, t) => s + t.ret, 0);
  const avgRet = totalRet / trades.length;
  const winRate = wins / trades.length * 100;
  const maxDD = Math.min(...trades.map(t => t.ret));
  const maxGain = Math.max(...trades.map(t => t.ret));
  return {trades, summary: {count:trades.length, wins, winRate, avgRet, totalRet, maxDD, maxGain}};
}

// Minimal indicator computation for backtest (subset of full worker)
function mockInd(candles) {
  const closes = candles.map(c => c.close);
  const n = closes.length;
  const sma = (p, idx) => {
    if (idx + 1 < p) return null;
    let s = 0;
    for (let k = idx - p + 1; k <= idx; k++) s += closes[k];
    return s / p;
  };
  const last = n - 1;
  // RSI 14
  let g = 0, l = 0;
  for (let i = last - 13; i <= last; i++) {
    if (i < 1) continue;
    const d = closes[i] - closes[i-1];
    if (d > 0) g += d; else l -= d;
  }
  const rs = l === 0 ? 100 : g / l;
  const rsi = 100 - 100 / (1 + rs);
  // BB 20
  const m20 = sma(20, last);
  let v = 0;
  for (let i = last - 19; i <= last; i++) v += Math.pow(closes[i] - m20, 2);
  const sd = Math.sqrt(v / 20);
  // Vol ratio
  let v5 = 0, v20 = 0;
  for (let i = last - 4; i <= last; i++) v5 += candles[i].volume || 0;
  for (let i = last - 19; i <= last; i++) v20 += candles[i].volume || 0;
  const volRatio = (v20 / 20) > 0 ? (v5 / 5) / (v20 / 20) : 1;
  return {
    sma5: sma(5, last), sma20: m20, sma60: sma(60, last),
    rsi14: rsi, bbU: m20 + 2 * sd, bbL: m20 - 2 * sd,
    volRatio,
  };
}

function runBacktestForStrat(stratKey) {
  if (!S.data?.candles?.length) { alert('先載入資料'); return; }
  const strat = STRATEGIES.find(s => s.key === stratKey);
  if (!strat) return;
  // Use default params
  const params = {};
  for (const f of (strat.paramFields || [])) {
    if (f.default !== undefined && f.default !== '') params[f.key] = f.default;
  }
  // Fill required custom prices with nominal
  if (stratKey === 'custom_buy' || stratKey === 'custom_sell') {
    alert('自訂價位策略無法回測（需要固定價格基準，但歷史資料價格動態變化）');
    return;
  }
  const r = backtest(stratKey, params, S.data.candles, 20);
  if (!r || r.summary === '無交易訊號') { alert(`${strat.lbl}：歷史資料中無觸發訊號`); return; }
  const s = r.summary;
  const winCol = s.winRate >= 55 ? 'var(--green)' : s.winRate >= 45 ? 'var(--orange)' : 'var(--red)';
  const avgCol = s.avgRet >= 0 ? 'var(--green)' : 'var(--red)';
  const html =
    `<h3 style="margin:0 0 8px;color:var(--gold);font-family:monospace">${strat.icon} ${strat.lbl} — 回測結果</h3>` +
    `<div style="font-family:monospace;font-size:9.5px;color:var(--tlo);margin-bottom:8px">${S.sym} · ${S.data.candles.length} 個交易日 · 持有 20 日後出場</div>` +
    `<div class="bt-result-row"><span class="lbl">交易次數</span><span class="val">${s.count}</span></div>` +
    `<div class="bt-result-row"><span class="lbl">勝率</span><span class="val" style="color:${winCol}">${s.winRate.toFixed(1)}% (${s.wins}/${s.count})</span></div>` +
    `<div class="bt-result-row"><span class="lbl">平均報酬</span><span class="val" style="color:${avgCol}">${s.avgRet >= 0 ? '+' : ''}${s.avgRet.toFixed(2)}%</span></div>` +
    `<div class="bt-result-row"><span class="lbl">總報酬</span><span class="val" style="color:${avgCol}">${s.totalRet >= 0 ? '+' : ''}${s.totalRet.toFixed(2)}%</span></div>` +
    `<div class="bt-result-row"><span class="lbl">最大單筆盈利</span><span class="val" style="color:var(--green)">+${s.maxGain.toFixed(2)}%</span></div>` +
    `<div class="bt-result-row"><span class="lbl">最大單筆虧損</span><span class="val" style="color:var(--red)">${s.maxDD.toFixed(2)}%</span></div>` +
    `<div style="margin-top:10px;font-family:monospace;font-size:9px;color:var(--tf);line-height:1.6">⚠ 回測假設：訊號觸發隔日開盤進場、固定持有 20 日後出場、無滑價手續費。實際操作會有差距。</div>`;
  showProModal(html);
}

function showProModal(html) {
  hideProModal();
  const m = document.createElement('div');
  m.id = 'pro-modal-bg';
  m.style.cssText = 'position:fixed;inset:0;background:rgba(6,10,18,.85);z-index:9999;display:flex;align-items:center;justify-content:center';
  m.innerHTML = `<div style="background:var(--bg2);border:1px solid var(--gold-m);border-radius:8px;padding:20px 24px;max-width:480px;max-height:80vh;overflow-y:auto;position:relative">
    <span data-pro="modal-close" style="position:absolute;top:6px;right:14px;cursor:pointer;color:var(--tlo);font-size:20px">×</span>
    ${html}
  </div>`;
  document.body.appendChild(m);
  m.addEventListener('click', e => { if (e.target.id === 'pro-modal-bg') hideProModal(); });
}
function hideProModal() {
  const m = document.getElementById('pro-modal-bg');
  if (m) m.remove();
}
document.addEventListener('click', ev => {
  const el = ev.target.closest('[data-pro="modal-close"]');
  if (el) hideProModal();
});

// ============================================================
// UI INJECTION — buttons + replay bar
// ============================================================
(function injectUI() {
  // Wait for DOM ready
  if (!document.getElementById('topbar')) return setTimeout(injectUI, 100);

  // Add notify button to topbar (before keybtn) — left click opens panel,
  // right click toggles enable/disable directly
  const topbar = document.getElementById('topbar');
  const keybtn = document.getElementById('keybtn');
  if (topbar && keybtn && !document.getElementById('btn-notify')) {
    const b = document.createElement('button');
    b.id = 'btn-notify';
    b.className = 'probtn';
    b.style.marginRight = '4px';
    b.onclick = notifyPanelToggle;
    b.oncontextmenu = (e) => { e.preventDefault(); notifyToggle(); };
    topbar.insertBefore(b, keybtn);
    updateNotifyBtn();
  }

  // Add tools (compare, vp, replay) to right of rangebar
  const rangebar = document.getElementById('rangebar');
  if (rangebar && !document.getElementById('pro-tools')) {
    const tools = document.createElement('div');
    tools.id = 'pro-tools';
    tools.className = 'pro-tools';
    tools.innerHTML =
      `<button class="probtn" id="btn-compare" onclick="compareToggle()" title="疊上大盤指數比較相對表現">vs 大盤</button>` +
      `<button class="probtn" id="btn-vp"      onclick="vpToggle()"      title="成交金額量價分布 + POC/主力成本區 (v3.8)">📊 量價</button>` +
      `<button class="probtn" id="btn-vp-mode" onclick="window.vpCycleMode&&vpCycleMode()" title="切換 金額/成交量 模式 (v3.8)">$/量</button>` +
      `<button class="probtn" id="btn-bt3"     onclick="window.backtestOpen&&backtestOpen()" title="回測引擎：8 策略勝率 + 型態命中率 (v3.8)">📈 回測</button>` +
      `<button class="probtn" id="btn-alertpush" onclick="window.alertPushOpen&&alertPushOpen()" title="後端警報推播設定 Telegram/Email (v3.8)">🔔 推播</button>` +
      `<button class="probtn" id="btn-overnight" onclick="window.overnightOpen&&overnightOpen()" title="夜盤連動預警：美股期貨→台股隔日預估→持倉停損/觀察買區 (v3.8)">🌙 夜盤</button>` +
      `<button class="probtn" id="btn-supplychain" onclick="window.supplyChainOpen&&supplyChainOpen()" title="台灣AI供應鏈族群連動：晶圓→封裝→CPO→伺服器→散熱 RS輪動 (v3.8)">🔗 供應鏈</button>` +
      `<button class="probtn" id="btn-valuation" onclick="window.valuationOpen&&valuationOpen()" title="長線估值錨：本益比河流，判斷現在貴不貴 (v3.8)">⚓ 估值</button>` +
      `<button class="probtn" id="btn-marketflow" onclick="window.marketFlowOpen&&marketFlowOpen()" title="大盤資金流：量能趨勢8000億→1.2兆 + 三大法人 (v3.8)">💰 資金流</button>` +
      `<button class="probtn" id="btn-instrank" onclick="window.instRankOpen&&instRankOpen()" title="外資/投信買賣超排行榜 + 連續天數 (v3.8)">🏆 法人榜</button>` +
      `<button class="probtn" id="btn-calendar" onclick="window.calendarOpen&&calendarOpen()" title="事件行事曆：月營收/除權息提醒 (v3.8)">📅 行事曆</button>` +
      `<button class="probtn" id="btn-replay"  onclick="replayToggle()"  title="K 線重播模式">▶ Replay</button>`;
    rangebar.parentElement.insertBefore(tools, rangebar.nextSibling);
    // v3.8: 工具列改 2 列 — 行1 時間段(rangebar)，行2 功能鈕(tools)
    rangebar.style.flex = '0 0 auto';
    tools.style.borderLeft = 'none';
    tools.style.borderTop = '1px solid var(--border)';
    tools.style.flexWrap = 'wrap';
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;flex-direction:column;align-items:stretch;flex-shrink:0;width:100%';
    rangebar.parentElement.insertBefore(wrap, rangebar);
    wrap.appendChild(rangebar);
    wrap.appendChild(tools);
  }

  // Add replay bar (appears when replay active)
  if (!document.getElementById('replay-bar')) {
    const left = document.getElementById('left');
    if (left) {
      const rb = document.createElement('div');
      rb.id = 'replay-bar';
      rb.innerHTML =
        `<button class="probtn" onclick="replayStep(-1)">◀</button>` +
        `<button class="probtn" onclick="replayStep(1)">▶</button>` +
        `<input type="range" id="replay-slider" style="flex:1">` +
        `<span id="replay-date">--</span>` +
        `<button class="probtn" onclick="replayExit()">✕ 退出 Replay</button>`;
      // Insert after rangebar
      const after = left.querySelector('#rangebar')?.parentElement || left.firstChild;
      left.insertBefore(rb, after.nextSibling);
    }
  }

  console.log('[v2-pro] UI injected');
})();

// Hook into renderChart to redraw lines + POC after every chart re-render
(function patchRenderChart() {
  if (typeof renderChart !== 'function') return setTimeout(patchRenderChart, 100);
  const orig = window.renderChart;
  window.renderChart = function () {
    orig.apply(this, arguments);
    setTimeout(() => {
      attachChartContext();
      drawLines();
      if (S.vpEnabled) drawVolumeProfile();
    }, 50);
  };
})();

// Hook into renderStrategyPlaybook to add 回測 button per strategy
(function patchPlaybook() {
  if (typeof renderStrategyPlaybook !== 'function') return setTimeout(patchPlaybook, 100);
  // Add backtest button via click delegation in playbook section
  document.addEventListener('click', ev => {
    const el = ev.target.closest('[data-pro="bt"]');
    if (!el) return;
    runBacktestForStrat(el.dataset.strat);
  });
  // Override renderStrategyPlaybook to inject 回測 button per strategy
  const orig = window.renderStrategyPlaybook;
  window.renderStrategyPlaybook = function () {
    let h = orig.apply(this, arguments);
    // Inject backtest buttons after each strategy block
    h = h.replace(/(<div style="font-family:monospace;font-size:9px;color:var\(--green\);line-height:1\.7"><b>觸發行動<\/b>　[^<]*<\/div>)\s*<\/div>/g,
      (m, actionDiv) => {
        // Find the strat key from the previous icon... simpler: just add a generic button hint
        return actionDiv + '</div>';
      });
    // Easier approach: append a hint at top of playbook telling user how to backtest
    h = h.replace('▼ 策略劇本說明（點開看詳細）',
      '▼ 策略劇本說明（點開看詳細，含回測）');
    return h;
  };
})();

// Better backtest entry: add a button in WATCH form
(function addBacktestButton() {
  // Patch renderSingleForm to add "回測 X 年" button
  if (typeof renderSingleForm !== 'function') return setTimeout(addBacktestButton, 100);
  const orig = window.renderSingleForm;
  window.renderSingleForm = function () {
    let h = orig.apply(this, arguments);
    // Append a backtest button after the params section
    h += `<button data-pro="bt" data-strat="${S.watchFormStrategy || 'sma60_pullback'}" style="padding:7px;background:transparent;border:1px solid var(--gold-m);border-radius:4px;color:var(--gold);font-family:monospace;font-size:10px;cursor:pointer;letter-spacing:.5px">📊 回測這個策略（用 ${S.sym || '當前個股'} 5 年資料）</button>`;
    return h;
  };
})();

// ── Mobile: tap on rtabs ::before pseudo-handle to collapse/expand ──
(function mobileDrawerToggle() {
  if (!document.getElementById('rtabs')) return setTimeout(mobileDrawerToggle, 100);
  const right = document.getElementById('right');
  const rtabs = document.getElementById('rtabs');
  if (!right || !rtabs) return;
  // Detect taps on the top 14px (where ::before handle sits in mobile CSS)
  rtabs.addEventListener('click', (e) => {
    if (window.innerWidth > 768) return;
    const rect = rtabs.getBoundingClientRect();
    if (e.clientY - rect.top <= 16) {
      right.classList.toggle('collapsed');
      e.stopPropagation();
      e.preventDefault();
    }
  }, true);
})();

// ── Expose ─────────────────────────────────────────────────
window.notifyToggle      = notifyToggle;
window.notifyPanelToggle = notifyPanelToggle;
window.notifyClearHistory = notifyClearHistory;
window.notifyMarkAllRead = notifyMarkAllRead;
window.compareToggle     = compareToggle;
window.vpToggle          = vpToggle;
window.replayToggle      = replayToggle;
window.replayStep        = replayStep;
window.replayExit        = replayExit;
window.runBacktestForStrat = runBacktestForStrat;
window.addLine           = addLine;
window.removeLine        = removeLine;
window.clearLines        = clearLines;
window.computePortfolioMetrics = computePortfolioMetrics;
window.fireSignalNotifications = fireSignalNotifications;

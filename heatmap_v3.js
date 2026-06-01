// ============================================================
// Stock Terminal v3.2 — 產業熱力圖（砍掉重寫，全前端）
// ------------------------------------------------------------
// 完全不靠 TWSE / /sectors endpoint。直接打 server 的 /yf/batch
// proxy（已驗證穩定），所有 sector 分組與平均都在前端做。
//
// 邏輯：
//   • US 模式 → 11 個 SPDR Select Sector ETFs（XLE/XLF/XLK/XLV/XLY/
//     XLP/XLI/XLB/XLU/XLRE/XLC），每個 ETF 就是一個產業
//   • TW 模式 → 17 大類股，每類用 1~3 檔台股龍頭代理，等權平均算漲跌
//
// 為何不再用 TWSE：MI_INDEX endpoint 對盤中 / 盤前 / 假日表現不穩，
// Yahoo /yf/batch 經 LRU 快取後 0.5 秒回應，整體可靠度遠高於 TWSE。
//
// 配色：TW 紅漲綠跌、US 綠漲紅跌（依使用者市場慣例）
// 快取：5 分鐘 TTL，按 TW/US 分開
// ============================================================

(function () {
'use strict';

const SERVER_H = window.SERVER || 'http://localhost:18432';
const TTL_MS = 5 * 60 * 1000;   // 5 分鐘
const _cache = { TW: null, US: null };
const _cacheT = { TW: 0, US: 0 };

// ── US：SPDR Select Sector ETFs ──────────────────────────────
const SPDR = [
  { sym: 'XLE',  name: '能源 Energy' },
  { sym: 'XLF',  name: '金融 Financials' },
  { sym: 'XLK',  name: '科技 Technology' },
  { sym: 'XLV',  name: '醫療 Healthcare' },
  { sym: 'XLY',  name: '非必需消費' },
  { sym: 'XLP',  name: '必需消費' },
  { sym: 'XLI',  name: '工業 Industrials' },
  { sym: 'XLB',  name: '原物料 Materials' },
  { sym: 'XLU',  name: '公用事業 Utilities' },
  { sym: 'XLRE', name: '不動產 Real Estate' },
  { sym: 'XLC',  name: '通訊 Communication' },
];

// ── TW：17 類股，每類 1~3 檔龍頭代理股 ────────────────────────
// 選股原則：在該類股市值或代表性最高的個股，能反映類股大方向
const TW_SECTORS = [
  { name: '半導體',       proxies: ['2330', '2454', '2303'] },   // 台積電 / 聯發科 / 聯電
  { name: '電子代工',     proxies: ['2317', '2382'] },           // 鴻海 / 廣達
  { name: '被動元件 / IC', proxies: ['2308', '3037'] },           // 台達電 / 欣興
  { name: 'PCB / 載板',    proxies: ['3034', '2383'] },           // 聯詠 / 台光電
  { name: '網通設備',     proxies: ['2345', '2059'] },           // 智邦 / 川湖
  { name: '金融',         proxies: ['2882', '2891', '2884'] },   // 國泰金 / 中信金 / 玉山金
  { name: '塑膠化纖',     proxies: ['1301', '1303', '1326'] },   // 台塑 / 南亞 / 台化
  { name: '鋼鐵',         proxies: ['2002', '2027'] },           // 中鋼 / 大成鋼
  { name: '航運',         proxies: ['2603', '2609', '2615'] },   // 長榮 / 陽明 / 萬海
  { name: '汽車',         proxies: ['2207', '2204'] },           // 和泰車 / 中華
  { name: '食品',         proxies: ['1216', '1227'] },           // 統一 / 佳格
  { name: '電信',         proxies: ['2412', '3045'] },           // 中華電 / 台灣大
  { name: '生技醫療',     proxies: ['1707', '4904'] },           // 葡萄王 / 遠傳 (替代)
  { name: '營建',         proxies: ['2548', '2545'] },           // 華固 / 皇翔
  { name: '紡織',         proxies: ['1402', '1476'] },           // 遠東新 / 儒鴻
  { name: '橡膠',         proxies: ['2105', '2104'] },           // 正新 / 中橡
  { name: '貿易百貨',     proxies: ['2912', '2915'] },           // 統一超 / 潤泰全
];

// ── CSS ──────────────────────────────────────────────────────
(function injectCss() {
  if (document.getElementById('heatmap-v3-styles')) return;
  const css = `
.heatmap-modal{position:fixed;inset:0;background:rgba(6,10,18,.9);z-index:9998;display:flex;align-items:center;justify-content:center}
.heatmap-modal .panel{background:var(--bg2);border:1px solid var(--gold-m);border-radius:8px;width:90vw;max-width:980px;height:80vh;display:flex;flex-direction:column;overflow:hidden}
.heatmap-modal .head{display:flex;justify-content:space-between;align-items:center;padding:12px 18px;border-bottom:1px solid var(--border);background:var(--bg)}
.heatmap-modal .head h3{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--gold);font-weight:700;letter-spacing:1px;margin:0;display:flex;align-items:center;gap:8px}
.heatmap-modal .head h3 .sub{color:var(--tlo);font-size:10px;font-weight:400;letter-spacing:0}
.heatmap-modal .head .ctrls{display:flex;align-items:center;gap:8px}
.heatmap-modal .body{flex:1;overflow-y:auto;padding:14px;background:var(--bg)}
.hm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px}
.hm-cell{padding:14px 10px;border-radius:6px;cursor:pointer;text-align:center;transition:transform .12s, box-shadow .12s;font-family:'JetBrains Mono',monospace;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.7);min-height:88px;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:4px;position:relative}
.hm-cell:hover{transform:scale(1.04);box-shadow:0 4px 16px rgba(0,0,0,.45);z-index:5}
.hm-cell .nm{font-size:12px;font-weight:700;letter-spacing:.5px;line-height:1.2}
.hm-cell .pct{font-size:18px;font-weight:700;letter-spacing:.5px;line-height:1}
.hm-cell .px{font-size:9.5px;opacity:.78;line-height:1}
.hm-cell .sub{position:absolute;bottom:4px;right:6px;font-size:8px;opacity:.55;letter-spacing:.3px}
.hm-foot{padding:8px 18px;background:var(--bg2);border-top:1px solid var(--border);font-family:monospace;font-size:9.5px;color:var(--tlo);display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.hm-legend{display:flex;align-items:center;gap:4px;font-size:9px}
.hm-legend .swatch{display:inline-block;width:14px;height:14px;border-radius:2px;vertical-align:middle;margin:0 3px}
.hm-refresh{background:transparent;border:1px solid var(--border);color:var(--tlo);padding:5px 11px;border-radius:3px;font-family:monospace;font-size:10px;cursor:pointer;letter-spacing:.5px}
.hm-refresh:hover{color:var(--gold);background:var(--gold-s);border-color:var(--gold-m)}
.hm-close{cursor:pointer;color:var(--tlo);font-size:22px;line-height:1;padding:2px 8px}
.hm-close:hover{color:var(--red)}
.hm-loading{display:flex;align-items:center;justify-content:center;flex-direction:column;height:100%;color:var(--gold);font-family:monospace;font-size:11px;gap:6px}
.hm-loading .dot{animation:hm-pulse 1.4s ease infinite}
@keyframes hm-pulse{0%,100%{opacity:1}50%{opacity:.35}}
.hm-empty{padding:50px 20px;text-align:center;color:var(--tlo);font-family:monospace;line-height:1.9}
.hm-empty .reasons{font-size:9.5px;color:var(--tf);line-height:1.7;margin:8px 0 14px}
.hm-empty .retry{padding:6px 14px;background:var(--gold-s);border:1px solid var(--gold-m);border-radius:3px;color:var(--gold);font-family:monospace;font-size:10.5px;cursor:pointer;font-weight:600}
.hm-empty .retry:hover{background:var(--gold);color:#060A12}
#btn-heatmap{padding:3px 10px;background:transparent;border:1px solid var(--border);border-radius:3px;color:var(--tlo);font-family:monospace;font-size:9.5px;cursor:pointer;letter-spacing:.5px}
#btn-heatmap:hover{color:var(--gold);background:var(--gold-s);border-color:var(--gold-m)}
`;
  const s = document.createElement('style');
  s.id = 'heatmap-v3-styles';
  s.textContent = css;
  document.head.appendChild(s);
})();

// ── 配色：依市場慣例 ────────────────────────────────────────
function pctColor(pct, mkt) {
  const v = Math.min(Math.abs(pct), 5) / 5;
  const a = 0.25 + v * 0.55;
  const isUp = pct >= 0;
  // TW 紅漲綠跌 / US 綠漲紅跌
  const upR = mkt === 'TW' ? 248 : 74,  upG = mkt === 'TW' ? 113 : 222, upB = mkt === 'TW' ? 113 : 128;
  const dnR = mkt === 'TW' ? 74  : 248, dnG = mkt === 'TW' ? 222 : 113, dnB = mkt === 'TW' ? 128 : 113;
  return isUp
    ? `rgba(${upR},${upG},${upB},${a.toFixed(2)})`
    : `rgba(${dnR},${dnG},${dnB},${a.toFixed(2)})`;
}

function escH(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

// ── 從 Yahoo chart response 抓 (cur, prev, chgPct) ────────────
// v3.3 改用 5d candles + rmt 對齊，與 wl_live_v3.js / loadSym / screener
// 全部共用同一套「Yahoo 日線落後修正」邏輯。原本 range=1d + chartPreviousClose
// 在 Yahoo 雙伺服器資料不同步時會把昨日值當今日。
function extractChg(res) {
  const meta = res?.meta || {};
  const ts = res?.timestamp || [];
  const rawCloses = res?.indicators?.quote?.[0]?.close || [];
  const valid = [];
  for (let i = 0; i < Math.min(ts.length, rawCloses.length); i++) {
    if (rawCloses[i] != null && isFinite(rawCloses[i]) && rawCloses[i] > 0 && ts[i] != null) {
      valid.push({ t: ts[i], c: rawCloses[i] });
    }
  }
  if (valid.length >= 2) {
    const last = valid[valid.length - 1];
    const prevC = valid[valid.length - 2].c;
    const rmt = meta.regularMarketTime;
    const rmp = meta.regularMarketPrice;
    if (rmt && rmp != null && isFinite(rmp) && rmp > 0 && rmt - last.t > 20 * 3600) {
      return { cur: rmp, prev: last.c, chgPct: (rmp - last.c) / last.c * 100 };
    }
    let cur = last.c;
    if (rmp != null && isFinite(rmp) && rmt && Math.abs(rmt - last.t) < 36 * 3600) cur = rmp;
    return { cur, prev: prevC, chgPct: (cur - prevC) / prevC * 100 };
  }
  // Fallback：candles 不夠 → 回到 meta
  let cur = meta.regularMarketPrice;
  if ((cur == null || !isFinite(cur)) && valid.length >= 1) cur = valid[valid.length - 1].c;
  const p = meta.chartPreviousClose ?? meta.previousClose;
  if (cur == null || p == null || !isFinite(p) || p <= 0) return null;
  return { cur: +cur, prev: +p, chgPct: (cur - p) / p * 100 };
}

// ── 批次抓 N 個 symbol ────────────────────────────────────────
async function batchFetch(syms) {
  if (!syms.length) return {};
  // v3.3 改 range=5d 拿多根 K，搭配 extractChg 內的 rmt 對齊修正。
  // 不加 nocache=1，讓 LRU 自然快取，跟個股 chart 共用，不會擋線
  const url = `${SERVER_H}/yf/batch?syms=${encodeURIComponent(syms.join(','))}&range=5d&interval=1d`;
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return await r.json();
}

// ── 抓 US 11 SPDR ETFs，每個就是一類 ─────────────────────────
async function fetchUS() {
  const syms = SPDR.map(s => s.sym);
  const data = await batchFetch(syms);
  const sectors = [];
  for (const s of SPDR) {
    const res = data[s.sym]?.chart?.result?.[0];
    if (!res) continue;
    const x = extractChg(res);
    if (!x) continue;
    sectors.push({
      name: s.name,
      close: x.cur,
      changePct: x.chgPct,
      sub: s.sym,    // 顯示 ETF 代碼
    });
  }
  return sectors;
}

// ── 抓 TW：17 類股 × 1-3 代理，等權平均 ──────────────────────
async function fetchTW() {
  // 先把所有代理股 flatten 成單一 batch
  const allCodes = [...new Set(TW_SECTORS.flatMap(s => s.proxies))];
  const allSyms = allCodes.map(c => c + '.TW');
  const data = await batchFetch(allSyms);

  // 嘗試找不到 .TW 的，第二輪試 .TWO
  const missed = [];
  const priceMap = new Map();   // code → {cur, prev, chgPct}
  for (const c of allCodes) {
    const ts = c + '.TW';
    const res = data[ts]?.chart?.result?.[0];
    if (res) {
      const x = extractChg(res);
      if (x) { priceMap.set(c, x); continue; }
    }
    missed.push(c);
  }
  if (missed.length) {
    const twoSyms = missed.map(c => c + '.TWO');
    try {
      const data2 = await batchFetch(twoSyms);
      for (const c of missed) {
        const res = data2[c + '.TWO']?.chart?.result?.[0];
        if (!res) continue;
        const x = extractChg(res);
        if (x) priceMap.set(c, x);
      }
    } catch (e) { /* 忽略，跳過缺資料的 */ }
  }

  // 各類股算等權平均
  const sectors = [];
  for (const s of TW_SECTORS) {
    const hits = s.proxies.map(c => priceMap.get(c)).filter(Boolean);
    if (!hits.length) continue;
    const avgPct = hits.reduce((a, b) => a + b.chgPct, 0) / hits.length;
    const avgPx  = hits.reduce((a, b) => a + b.cur,    0) / hits.length;
    sectors.push({
      name: s.name,
      close: avgPx,
      changePct: avgPct,
      sub: s.proxies.join('·'),   // 顯示代理股代碼
      n: hits.length,             // 該類股有幾檔代理拿到資料
    });
  }
  return sectors;
}

// ── 主取資料：mkt 決定哪個 ────────────────────────────────────
async function fetchSectors(mkt, force) {
  mkt = mkt === 'US' ? 'US' : 'TW';
  const now = Date.now();
  if (!force && _cache[mkt] && _cache[mkt].length && (now - _cacheT[mkt] < TTL_MS)) {
    return { sectors: _cache[mkt], fromCache: true, age: now - _cacheT[mkt] };
  }
  const fetcher = mkt === 'US' ? fetchUS : fetchTW;
  try {
    const sectors = await fetcher();
    if (sectors.length) {
      _cache[mkt] = sectors;
      _cacheT[mkt] = now;
    }
    return { sectors, fromCache: false };
  } catch (e) {
    console.warn('[heatmap] fetch error:', e);
    return { sectors: [], error: String(e) };
  }
}

// ── UI ────────────────────────────────────────────────────────
let _modalOpen = false;

function closeHeatmap() {
  const m = document.getElementById('heatmap-modal');
  if (m) m.remove();
  _modalOpen = false;
}

// v3.2 新增：可指定 mktOverride，讓 modal 內的 TW/US 切換按鈕能繞過 S.mkt
async function openHeatmap(force, mktOverride) {
  if (_modalOpen) closeHeatmap();
  _modalOpen = true;

  const mkt = (mktOverride || (window.S && S.mkt) || 'TW') === 'US' ? 'US' : 'TW';
  const mktName = mkt === 'US' ? '美股 SPDR Select Sectors' : '台股 17 大類股 (Yahoo 代理)';
  const colorNote = mkt === 'US' ? '綠漲紅跌（美股慣例）' : '紅漲綠跌（台股慣例）';
  const symCount = mkt === 'US' ? 11 : new Set(TW_SECTORS.flatMap(s => s.proxies)).size;
  const sectorCount = mkt === 'US' ? SPDR.length : TW_SECTORS.length;

  const m = document.createElement('div');
  m.className = 'heatmap-modal';
  m.id = 'heatmap-modal';
  m.innerHTML = `
    <div class="panel">
      <div class="head">
        <h3>📊 產業熱力圖 <span class="sub">— ${escH(mktName)}</span></h3>
        <div class="ctrls">
          <div class="hm-mkt-toggle" style="display:inline-flex;border:1px solid var(--border);border-radius:4px;overflow:hidden;margin-right:6px">
            <button class="hm-mkt-btn ${mkt === 'TW' ? 'on' : ''}" data-mkt="TW" style="padding:5px 10px;background:${mkt === 'TW' ? 'var(--gold-s)' : 'transparent'};color:${mkt === 'TW' ? 'var(--gold)' : 'var(--tlo)'};border:none;font-family:monospace;font-size:10px;cursor:pointer;letter-spacing:.5px">🇹🇼 TW</button>
            <button class="hm-mkt-btn ${mkt === 'US' ? 'on' : ''}" data-mkt="US" style="padding:5px 10px;background:${mkt === 'US' ? 'var(--gold-s)' : 'transparent'};color:${mkt === 'US' ? 'var(--gold)' : 'var(--tlo)'};border:none;border-left:1px solid var(--border);font-family:monospace;font-size:10px;cursor:pointer;letter-spacing:.5px">🇺🇸 US</button>
          </div>
          <button class="hm-refresh" id="hm-refresh">↻ 重抓</button>
          <span class="hm-close" id="hm-close">×</span>
        </div>
      </div>
      <div class="body" id="hm-body">
        <div class="hm-loading"><div class="dot">⟳</div><div class="dot">抓 ${symCount} 個 ${mkt === 'US' ? 'SPDR ETF' : '台股龍頭'} (${sectorCount} 類)...</div></div>
      </div>
      <div class="hm-foot">
        <span id="hm-foot-msg">資料：Yahoo Finance · ${escH(colorNote)}</span>
        <div class="hm-legend">
          ${mkt === 'US'
            ? '<span class="swatch" style="background:rgba(248,113,113,.85)"></span>≤-3% <span class="swatch" style="background:rgba(248,113,113,.4)"></span>-1% <span class="swatch" style="background:rgba(255,255,255,.1)"></span>0 <span class="swatch" style="background:rgba(74,222,128,.4)"></span>+1% <span class="swatch" style="background:rgba(74,222,128,.85)"></span>≥+3%'
            : '<span class="swatch" style="background:rgba(74,222,128,.85)"></span>≤-3% <span class="swatch" style="background:rgba(74,222,128,.4)"></span>-1% <span class="swatch" style="background:rgba(255,255,255,.1)"></span>0 <span class="swatch" style="background:rgba(248,113,113,.4)"></span>+1% <span class="swatch" style="background:rgba(248,113,113,.85)"></span>≥+3%'}
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(m);
  m.addEventListener('click', e => { if (e.target === m) closeHeatmap(); });
  document.getElementById('hm-close').onclick = closeHeatmap;
  document.getElementById('hm-refresh').onclick = () => openHeatmap(true, mkt);
  // TW/US 切換 — 不影響主終端機的 S.mkt，只切熱力圖視窗
  m.querySelectorAll('.hm-mkt-btn').forEach(btn => {
    btn.onclick = (e) => {
      const newMkt = e.currentTarget.dataset.mkt;
      if (newMkt !== mkt) openHeatmap(false, newMkt);
    };
  });

  const { sectors, error, fromCache, age } = await fetchSectors(mkt, force);
  const body = document.getElementById('hm-body');
  const foot = document.getElementById('hm-foot-msg');
  if (!body) return;
  if (!sectors.length) {
    body.innerHTML = `
      <div class="hm-empty">
        <div style="color:var(--gold);font-size:14px;margin-bottom:6px">❌ 無法載入${mkt === 'US' ? '美股' : '台股'}類股資料</div>
        <div class="reasons">
          ${error ? '錯誤：' + escH(error.slice(0, 200)) + '<br>' : ''}
          可能原因：<br>
          • Server.py 未啟動，請確認 :18432 在跑<br>
          • Yahoo Finance 暫時不通 (極少見)<br>
          • 防火牆 / Antivirus 擋住 Node port
        </div>
        <button class="retry" onclick="openHeatmap(true)">↻ 重新嘗試</button>
      </div>
    `;
    if (foot) foot.textContent = '⚠ 載入失敗 — 點「重抓」或檢查 server.py';
    return;
  }
  if (foot) {
    const cacheTag = fromCache ? ` · 快取 ${Math.round(age / 1000)}s` : '';
    foot.textContent = `資料：Yahoo Finance · ${sectors.length} 類${cacheTag} · ${colorNote}`;
  }

  // 按 |%| 降冪排序，視覺強烈先放前面
  const sorted = sectors.slice().sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct));
  let h = '<div class="hm-grid">';
  for (const s of sorted) {
    const col = pctColor(s.changePct, mkt);
    const text = Math.abs(s.changePct) > 3 ? '#fff' : 'rgba(255,255,255,.92)';
    const sign = s.changePct >= 0 ? '+' : '';
    h += `<div class="hm-cell" style="background:${col};color:${text}" title="${escH(s.sub || '')}">
      <div class="nm">${escH(s.name)}</div>
      <div class="pct">${sign}${s.changePct.toFixed(2)}%</div>
      <div class="px">${(s.close || 0).toFixed(2)}</div>
      ${s.sub ? `<div class="sub">${escH(s.sub.length > 16 ? s.sub.slice(0, 14) + '…' : s.sub)}</div>` : ''}
    </div>`;
  }
  h += '</div>';
  body.innerHTML = h;
}

// ── 注入按鈕到 pro-tools 工具列 ───────────────────────────────
(function injectBtn() {
  let tries = 0;
  function tryInject() {
    if (tries++ > 30) return;
    const tools = document.getElementById('pro-tools');
    if (!tools) return setTimeout(tryInject, 100);
    if (document.getElementById('btn-heatmap')) return;
    const b = document.createElement('button');
    b.id = 'btn-heatmap';
    b.className = 'probtn';
    b.title = '產業熱力圖（TW 17 類股 / US 11 SPDR ETF）';
    b.innerHTML = '📊 類股';
    b.onclick = () => openHeatmap(false);
    tools.appendChild(b);
  }
  tryInject();
})();

// ── 對外 expose ───────────────────────────────────────────────
window.openHeatmap = openHeatmap;
window.closeHeatmap = closeHeatmap;
window.HeatmapV3 = { fetchSectors, fetchUS, fetchTW, SPDR, TW_SECTORS };

console.log('%c[Heatmap v3.2] loaded — pure /yf/batch, no TWSE', 'color:#FBBF24;font-weight:bold');

})();

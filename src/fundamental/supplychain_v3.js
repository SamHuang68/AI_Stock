// ============================================================
// Stock Terminal v3.8 — 台灣 AI 供應鏈族群連動
// ------------------------------------------------------------
// 把台股 AI 供應鏈視覺化成鏈條：晶圓 → IC設計/IP → 記憶體 → 封測(CoWoS)
//   → 載板/PCB/CCL → 被動元件 → CPO光通訊 → 整機 → 機構 → 散熱 → 電源。
//   每段顯示族群相對強弱
//   (成分股當日%平均)與資金流向，看「輪動到哪一段」。點個股載入線型。
// 資料源：/yf/batch（與大盤列同套 rmt 落後修正算 %）。工具列 🔗 供應鏈。
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';

  // 鏈條(由上游到下游)。代號為代表性成分，可自行增刪。
  // v3.8.1 全面重排：新增 記憶體/儲存、被動元件(2327國巨)、機構/連接器、
  //   拆分 散熱 與 電源/電力基建；封測補 京元電/欣銓、PCB 補 台光電(CCL)、
  //   整機補 鴻海。上櫃股 server fetch_one 會自動 .TW→.TWO 回退。
  // v3.8.2：分 台股/美股 兩個 tab，美股鏈 設備/EDA→代工→晶片→記憶體→
  //   網通光通訊→伺服器→電力散熱→CSP平台。
  let scMkt = 'TW';   // 目前 tab
  const CHAIN_TW = [
    { stage: '晶圓 / 先進製程', icon: '🔬', stocks: [['2330', '台積電'], ['2303', '聯電'], ['6770', '力積電'], ['5347', '世界先進']] },
    { stage: 'IC 設計 / 矽智財 IP', icon: '🧠', stocks: [['2454', '聯發科'], ['3443', '創意'], ['3661', '世芯-KY'], ['5274', '信驊'], ['3529', '力旺'], ['6533', '晶心科']] },
    { stage: '記憶體 / 儲存', icon: '💾', stocks: [['2344', '華邦電'], ['2408', '南亞科'], ['8299', '群聯'], ['3260', '威剛']] },
    { stage: '先進封裝 / 測試 (CoWoS)', icon: '📦', stocks: [['3711', '日月光投控'], ['6147', '頎邦'], ['2449', '京元電子'], ['3264', '欣銓'], ['6515', '穎崴'], ['3680', '家登']] },
    { stage: '載板 / PCB / CCL', icon: '🧩', stocks: [['3037', '欣興'], ['8046', '南電'], ['3189', '景碩'], ['2368', '金像電'], ['2383', '台光電']] },
    { stage: '被動元件', icon: '⚡', stocks: [['2327', '國巨'], ['2492', '華新科'], ['3026', '禾伸堂'], ['6173', '信昌電']] },
    { stage: 'CPO / 光通訊 / 網通', icon: '💡', stocks: [['2345', '智邦'], ['4979', '華星光'], ['3450', '聯鈞'], ['4977', '眾達-KY'], ['3163', '波若威'], ['3081', '聯亞']] },
    { stage: 'AI 伺服器 / 整機', icon: '🖥️', stocks: [['2317', '鴻海'], ['2382', '廣達'], ['3231', '緯創'], ['6669', '緯穎'], ['2376', '技嘉'], ['2356', '英業達'], ['4938', '和碩']] },
    { stage: '機構 / 連接器 / 滑軌', icon: '🔩', stocks: [['3533', '嘉澤'], ['2059', '川湖'], ['8210', '勤誠']] },
    { stage: '散熱', icon: '❄️', stocks: [['3017', '奇鋐'], ['3324', '雙鴻'], ['2421', '建準'], ['6230', '超眾']] },
    { stage: '電源 / 電力基建', icon: '🔌', stocks: [['2308', '台達電'], ['2301', '光寶科'], ['1519', '華城'], ['1503', '士電'], ['1513', '中興電']] },
  ];

  const CHAIN_US = [
    { stage: '半導體設備 / EDA', icon: '🛠️', stocks: [['ASML', '艾司摩爾'], ['AMAT', '應用材料'], ['LRCX', '科林研發'], ['KLAC', '科磊'], ['SNPS', '新思'], ['CDNS', '益華']] },
    { stage: '晶圓代工 / IDM', icon: '🔬', stocks: [['TSM', '台積電ADR'], ['INTC', '英特爾'], ['GFS', '格芯'], ['UMC', '聯電ADR']] },
    { stage: 'AI 晶片 GPU / ASIC', icon: '🧠', stocks: [['NVDA', '輝達'], ['AMD', '超微'], ['AVGO', '博通'], ['MRVL', '邁威爾'], ['QCOM', '高通']] },
    { stage: '記憶體 / 儲存', icon: '💾', stocks: [['MU', '美光'], ['SNDK', 'Sandisk'], ['WDC', '威騰'], ['STX', '希捷']] },
    { stage: 'AI 電源 / 電源管理 IC', icon: '⚡', stocks: [['MPWR', 'MPS 芯源'], ['VICR', 'Vicor'], ['ON', '安森美'], ['ADI', '亞德諾'], ['TXN', '德儀']] },
    { stage: '網通 / 光通訊 / 互連', icon: '💡', stocks: [['ANET', 'Arista'], ['CSCO', '思科'], ['COHR', 'Coherent'], ['LITE', 'Lumentum'], ['CRDO', 'Credo'], ['ALAB', 'Astera Labs']] },
    { stage: 'AI 伺服器 / 整機', icon: '🖥️', stocks: [['SMCI', '美超微'], ['DELL', '戴爾'], ['HPE', '慧與']] },
    { stage: '電力 / 散熱基建', icon: '🔌', stocks: [['VRT', 'Vertiv'], ['ETN', '伊頓'], ['GEV', 'GE Vernova'], ['CEG', '星座能源']] },
    { stage: 'CSP / AI 平台', icon: '☁️', stocks: [['MSFT', '微軟'], ['GOOGL', 'Alphabet'], ['AMZN', '亞馬遜'], ['META', 'Meta'], ['ORCL', '甲骨文']] },
  ];
  const CHAINS = { TW: CHAIN_TW, US: CHAIN_US };

  function pcls(c) { return c == null ? '' : c > 0 ? 'sc-up' : c < 0 ? 'sc-dn' : ''; }
  function fmt(c) { return c == null ? '—' : (c >= 0 ? '+' : '') + c.toFixed(2) + '%'; }

  function style() {
    if (document.getElementById('sc-style')) return;
    const s = document.createElement('style'); s.id = 'sc-style';
    // 台股紅漲綠跌
    s.textContent = `
    #sc-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #sc-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(720px,94vw);max-height:90vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #sc-box h3{margin:0 0 4px;font-size:15px}
    .sc-stage{border:1px solid #1e293b;border-radius:8px;margin:6px 0;overflow:hidden}
    .sc-stage-h{display:flex;align-items:center;gap:8px;padding:6px 10px;background:#111827;font-weight:700;font-size:12px}
    .sc-rs{margin-left:auto;font-weight:800}
    .sc-stocks{display:flex;flex-wrap:wrap;gap:4px;padding:7px 10px}
    .sc-chip{display:flex;flex-direction:column;align-items:flex-start;border:1px solid #334155;border-radius:6px;padding:4px 8px;cursor:pointer;min-width:78px;background:#0b1220}
    .sc-chip:hover{border-color:#fbbf24}
    .sc-chip .c{font-size:11px;font-weight:700;color:#e2e8f0}
    .sc-chip .n{font-size:8.5px;color:#64748b}
    .sc-up{color:#ef4444}.sc-dn{color:#22c55e}
    .sc-usmkt .sc-up{color:#4ade80}.sc-usmkt .sc-dn{color:#f87171}
    .sc-flow{text-align:center;color:#475569;font-size:14px;line-height:1}
    .sc-tabs{display:flex;gap:6px;margin:2px 0 8px}
    .sc-tab{background:#1e293b;border:1px solid #334155;color:#94a3b8;border-radius:6px;padding:4px 14px;cursor:pointer;font-size:11px;font-weight:700}
    .sc-tab.on{background:rgba(251,191,36,.15);border-color:#fbbf24;color:#fbbf24}
    .sc-ov-hd{font-size:10px;color:#64748b;margin:2px 0 4px;letter-spacing:1px}
    .sc-ov{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #1e293b}
    .sc-ov-chip{display:flex;align-items:center;gap:4px;border:1px solid #1e293b;border-radius:6px;padding:3px 8px;font-size:10.5px;cursor:pointer;background:#0b1220}
    .sc-ov-chip:hover{border-color:#fbbf24}
    .sc-ov-chip b{font-weight:800}`;
    document.head.appendChild(s);
  }

  // 與大盤列同套：/yf/batch range=5d，rmt 落後修正算 %
  async function fetchPctMap(syms) {
    const out = {};
    try {
      const url = `${SRV}/yf/batch?syms=${encodeURIComponent(syms.join(','))}&range=5d&interval=1d`;
      const data = await fetch(url, { cache: 'no-store' }).then(r => r.ok ? r.json() : {});
      for (const sym of syms) {
        const res = data[sym] && data[sym].chart && data[sym].chart.result && data[sym].chart.result[0];
        if (!res) continue;
        const meta = res.meta || {};
        const ts = res.timestamp || [];
        const cl = (res.indicators && res.indicators.quote && res.indicators.quote[0] && res.indicators.quote[0].close) || [];
        const valid = [];
        for (let i = 0; i < Math.min(ts.length, cl.length); i++) if (cl[i] != null && isFinite(cl[i]) && ts[i] != null) valid.push({ t: ts[i], c: cl[i] });
        if (!valid.length) continue;
        const last = valid[valid.length - 1], prevC = valid.length >= 2 ? valid[valid.length - 2].c : null;
        const rmt = meta.regularMarketTime, rmp = meta.regularMarketPrice;
        let cur, prev;
        if (rmt && rmp != null && isFinite(rmp) && rmp > 0 && rmt - last.t > 20 * 3600) { cur = rmp; prev = last.c; }
        else { cur = last.c; prev = prevC != null ? prevC : (meta.chartPreviousClose || meta.previousClose); }
        if (cur != null && prev != null && prev > 0) out[sym] = (cur - prev) / prev * 100;
      }
    } catch (e) { console.warn('[supplychain]', e); }
    return out;
  }

  async function render() {
    const body = document.getElementById('sc-body');
    if (!body) return;
    body.innerHTML = '載入中…';
    const isUS = scMkt === 'US';
    const chain = CHAINS[scMkt] || CHAIN_TW;
    // tab 高亮 + 美股綠漲紅跌 class
    const box = document.getElementById('sc-box');
    if (box) box.classList.toggle('sc-usmkt', isUS);
    document.querySelectorAll('.sc-tab').forEach(b =>
      b.classList.toggle('on', b.dataset.mkt === scMkt));
    const allCodes = [...new Set(chain.flatMap(g => g.stocks.map(s => s[0])))];
    const pmap = await fetchPctMap(allCodes.map(c => isUS ? c : c + '.TW'));
    if (scMkt !== (isUS ? 'US' : 'TW')) return;   // 載入期間被切走 → 丟棄
    const getp = code => pmap[isUS ? code : code + '.TW'];

    let h = '';
    const stageRS = [];
    chain.forEach((g, gi) => {
      const vals = g.stocks.map(s => getp(s[0])).filter(v => v != null);
      const rs = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
      stageRS.push({ name: g.stage, rs, gi, icon: g.icon });
      let chips = '';
      // 族群內依強弱排序
      const sorted = [...g.stocks].sort((a, b) => (getp(b[0]) ?? -999) - (getp(a[0]) ?? -999));
      for (const [code, name] of sorted) {
        const p = getp(code);
        chips += `<div class="sc-chip" data-load="${code}"><span class="c">${code}</span><span class="n">${name}</span><span class="${pcls(p)}" style="font-size:10px;font-weight:700">${fmt(p)}</span></div>`;
      }
      h += `<div class="sc-stage" id="sc-stage-${gi}">
        <div class="sc-stage-h">${g.icon} ${g.stage}<span class="sc-rs ${pcls(rs)}">${fmt(rs)}</span></div>
        <div class="sc-stocks">${chips}</div></div>`;
      if (gi < chain.length - 1) h += `<div class="sc-flow">▼</div>`;
    });

    // 輪動結論：最強/最弱段
    const ranked = stageRS.filter(s => s.rs != null).sort((a, b) => b.rs - a.rs);
    let summary = '';
    if (ranked.length) {
      const top = ranked[0], bot = ranked[ranked.length - 1];
      const flowNote = isUS
        ? '鏈條由上游(設備/EDA)到下游(電力基建/CSP)；看資金輪動到哪一段。美股綠漲紅跌。'
        : '鏈條由上游(晶圓)到下游(整機/機構/散熱/電源)；看資金輪動到哪一段。台股紅漲綠跌。';
      summary = `<div style="font-size:11px;color:var(--tlo);margin-bottom:8px">今日最強段：<b class="${pcls(top.rs)}">${top.name} ${fmt(top.rs)}</b>　最弱段：<b class="${pcls(bot.rs)}">${bot.name} ${fmt(bot.rs)}</b><br><span style="font-size:9px;color:var(--tf)">${flowNote}</span></div>`;
    }
    // 段別漲跌總覽(依強弱排序，點跳到該段)：上方一目了然不必往下捲
    let overview = '';
    if (ranked.length) {
      const chips = ranked.map(s =>
        `<div class="sc-ov-chip ${pcls(s.rs)}" data-jump="${s.gi}" title="點擊跳到該段">${s.icon} ${s.name} <b>${fmt(s.rs)}</b></div>`).join('');
      overview = `<div class="sc-ov-hd">段別漲跌總覽（強→弱）</div><div class="sc-ov">${chips}</div>`;
    }
    body.innerHTML = summary + overview + h;
    body.querySelectorAll('[data-load]').forEach(el => el.onclick = () => {
      const c = el.getAttribute('data-load');
      if (typeof loadSym === 'function') { loadSym(c, scMkt); close(); }
    });
    body.querySelectorAll('[data-jump]').forEach(el => el.onclick = () => {
      const t = document.getElementById('sc-stage-' + el.getAttribute('data-jump'));
      if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  function open() {
    style();
    let m = document.getElementById('sc-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'sc-modal';
      m.innerHTML = `<div id="sc-box"><h3>🔗 AI 供應鏈族群連動</h3>
        <div class="sc-tabs">
          <button class="sc-tab on" data-mkt="TW">台股</button>
          <button class="sc-tab" data-mkt="US">美股</button>
        </div>
        <div id="sc-body">載入中…</div>
        <div style="text-align:right;margin-top:8px"><button onclick="window.supplyChainRefresh&&supplyChainRefresh()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer">↻ 重新整理</button>
        <button onclick="window.supplyChainClose&&supplyChainClose()" style="background:#334155;border:0;color:#fff;border-radius:6px;padding:5px 11px;cursor:pointer;margin-left:6px">關閉</button></div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
      m.querySelectorAll('.sc-tab').forEach(b => b.onclick = () => {
        if (scMkt === b.dataset.mkt) return;
        scMkt = b.dataset.mkt;
        render();
      });
    }
    // 開啟時跟隨目前終端機市場
    if (typeof S !== 'undefined' && S.mkt) scMkt = (S.mkt === 'US') ? 'US' : 'TW';
    m.style.display = 'flex';
    render();
  }
  function close() { const m = document.getElementById('sc-modal'); if (m) m.style.display = 'none'; }

  window.supplyChainOpen = open;
  window.supplyChainClose = close;
  window.supplyChainRefresh = render;
})();

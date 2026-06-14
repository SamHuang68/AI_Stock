// ============================================================
// Stock Terminal v3.9 — 加股設定精靈 (Setup Wizard)
// ------------------------------------------------------------
// 加入/載入一支股票時，用 4 題問答(用途/週期/風險/資金)＋一套「專業分析
//   Skill 引擎」自動把 觀察訊號 / 警報 / 持倉計畫 / 畫線 / 研判結論 一次設好。
//   引擎全用既有資料：S.data.candles + StratLib + Backtest.scanStrategies
//   + /fundamental /valuation /chip(best-effort)；停損 ATR 自適應或固定%可選；
//   結論規則即時或 Claude 口語版(/ai-note)可選。建議預設全套用、可逐項取消。
// 寫入既有子系統：S.watches+saveWatches、/alert/rules、setPosition、
//   window.drawToolsAdd、localStorage wizard_notes。皆標 source:'wizard' 冪等。
// 架構守則：狀態用裸 S；對外 window.wizardOpen(sym,mkt)/wizardClose。
// ============================================================
(function () {
  'use strict';
  const SRV = (typeof window !== 'undefined' && window.SERVER) ? window.SERVER
    : (typeof SERVER !== 'undefined' ? SERVER : 'http://localhost:18432');

  // ---- 答案狀態 ----
  let wz = null;   // {sym,mkt,use,period,risk,capital,entry,shares,slMode,conclMode,diag,sug}

  const DEFAULTS = { use: 'watch', period: 'swing', risk: 'mid', capital: 0, slMode: 'atr', conclMode: 'rule' };
  const RISK_SL = { low: 5, mid: 8, high: 12 };          // 固定停損%
  const RISK_ATRK = { low: 1.2, mid: 1.5, high: 2.0 };   // ATR 倍數
  const RISK_BUDGET = { low: 0.01, mid: 0.015, high: 0.02 }; // 風險預算佔資金%
  const PERIOD_TOL = { long: 3, swing: 2, short: 1.2 };  // 買區/容差%

  // ---- 小工具 ----
  const last = a => { for (let i = a.length - 1; i >= 0; i--) if (a[i] != null) return a[i]; return null; };
  const avg = a => a.length ? a.reduce((s, x) => s + (x || 0), 0) / a.length : 0;
  const tzoff = () => (typeof S !== 'undefined' && typeof S.tzOffset === 'number') ? S.tzOffset : 0;
  const isTw = () => (wz && wz.mkt === 'TW');
  const lots = sh => Math.max(0, Math.floor(sh / 1000) * 1000); // 台股取整張

  function atr14(h, l, c) {
    let s = 0, k = 0;
    for (let i = Math.max(1, c.length - 14); i < c.length; i++) {
      s += Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])); k++;
    }
    return k ? s / k : 0;
  }

  // 近 winBar 內的擺動高低 → 最近的上方壓力 / 下方支撐
  function levels(c, price) {
    const w = 4, lookback = Math.min(90, c.length - 1);
    const start = c.length - lookback;
    const sH = [], sL = [];
    for (let i = start + w; i < c.length - w; i++) {
      let hi = true, lo = true;
      for (let j = i - w; j <= i + w; j++) {
        if (c[j].high > c[i].high) hi = false;
        if (c[j].low < c[i].low) lo = false;
      }
      if (hi) sH.push(c[i].high);
      if (lo) sL.push(c[i].low);
    }
    const below = sL.filter(v => v < price * 0.998).sort((a, b) => b - a);
    const above = sH.filter(v => v > price * 1.002).sort((a, b) => a - b);
    const support = below[0] || Math.min(...c.slice(start).map(x => x.low));
    const resistance = above[0] || Math.max(...c.slice(start).map(x => x.high));
    return { support, resistance };
  }

  // 近 winBar 波段最高/最低 + 時間 (給 Fib)
  function swing(c) {
    const lookback = Math.min(120, c.length);
    const seg = c.slice(c.length - lookback);
    let hi = seg[0], lo = seg[0];
    for (const x of seg) { if (x.high > hi.high) hi = x; if (x.low < lo.low) lo = x; }
    return { swHigh: hi.high, swLow: lo.low, swHighT: hi.time, swLowT: lo.time };
  }

  // ---- 體檢引擎 ----
  function compute() {
    const c = (typeof S !== 'undefined' && S.data && S.data.candles) ? S.data.candles : null;
    if (!c || c.length < 60 || !window.StratLib) return null;
    const L = window.StratLib;
    const closes = c.map(x => x.close), highs = c.map(x => x.high), lows = c.map(x => x.low), vols = c.map(x => x.volume || 0);
    const n = closes.length, price = closes[n - 1];
    const sma20 = last(L.sma(closes, 20)), sma60 = last(L.sma(closes, 60));
    const sma200 = n >= 200 ? last(L.sma(closes, 200)) : null;
    const rsi = last(L.rsi(closes, 14));
    const atr = atr14(highs, lows, closes), atrPct = price ? atr / price * 100 : 0;
    const volRatio = avg(vols.slice(-20)) ? avg(vols.slice(-5)) / avg(vols.slice(-20)) : 0;
    let tb = 50;
    if (sma20 && sma60) { if (price > sma20) tb += 8; if (sma20 > sma60) tb += 10; if (price < sma20) tb -= 8; if (sma20 < sma60) tb -= 10; }
    if (rsi != null) { if (rsi > 55) tb += 6; if (rsi < 45) tb -= 6; if (rsi > 75) tb -= 4; if (rsi < 25) tb += 4; }
    tb = Math.max(0, Math.min(100, tb));
    const { support, resistance } = levels(c, price);
    const sw = swing(c);
    // 歷史策略勝率 (best-effort)
    let scan = [];
    try { if (window.Backtest && window.Backtest.scanStrategies) scan = window.Backtest.scanStrategies(c) || []; } catch {}
    const scanMap = {}; scan.forEach(r => { scanMap[r.key] = r; });
    return { price, sma20, sma60, sma200, rsi, atr, atrPct, volRatio, techBias: tb, support, resistance, sw, scanMap };
  }

  async function fetchContext(sym) {
    const out = { fund: null, val: null, chip: null };
    const code = sym;
    await Promise.all([
      fetch(`${SRV}/fundamental/${encodeURIComponent(code)}`).then(r => r.ok ? r.json() : null).then(j => out.fund = j).catch(() => { }),
      fetch(`${SRV}/valuation/${encodeURIComponent(code)}`).then(r => r.ok ? r.json() : null).then(j => out.val = j).catch(() => { }),
      fetch(`${SRV}/chip/${encodeURIComponent(code)}`).then(r => r.ok ? r.json() : null).then(j => out.chip = j).catch(() => { }),
    ]);
    return out;
  }

  // ---- 由答案 + 體檢 產生建議 ----
  function buildSuggestions() {
    const d = wz.diag; if (!d) return null;
    const price = d.price;
    const tol = PERIOD_TOL[wz.period] || 2;
    // 停損
    let slPct;
    if (wz.slMode === 'fixed') slPct = RISK_SL[wz.risk];
    else slPct = Math.max(3, +(RISK_ATRK[wz.risk] * d.atrPct).toFixed(1));
    const entryRef = (wz.use === 'hold' && wz.entry > 0) ? wz.entry : price;
    const stopPrice = +(entryRef * (1 - slPct / 100)).toFixed(2);
    // 停利：壓力位，否則 2:1 風報
    const target = +(d.resistance > entryRef ? d.resistance : entryRef * (1 + slPct / 100 * 2)).toFixed(2);
    // 買區(支撐帶)
    const buyLo = +(d.support).toFixed(2), buyHi = +(d.support * (1 + tol / 100)).toFixed(2);
    // 建議股數
    const cap = wz.capital || 0;
    const fullShares = cap > 0 ? (isTw() ? lots(cap / price) : Math.floor(cap / price)) : 0;
    const riskPerSh = Math.max(0.01, entryRef - stopPrice);
    const riskShares = cap > 0 ? (isTw() ? lots(cap * RISK_BUDGET[wz.risk] / riskPerSh) : Math.floor(cap * RISK_BUDGET[wz.risk] / riskPerSh)) : 0;

    // 觀察訊號 (依週期)
    const SIG = {
      long: [{ strategy: 'sma60_pullback', params: { tolerance: 2 } }, { strategy: 'rsi_oversold_bounce', params: {} }],
      swing: [{ strategy: 'sma20_pullback', params: { tolerance: 1.5 } }, { strategy: 'sma60_pullback', params: { tolerance: 2 } }, { strategy: 'bb_lower_touch', params: {} }],
      short: [{ strategy: 'breakout_n_high', params: { days: 20, volMult: 1.5 } }, { strategy: 'rsi_oversold_bounce', params: {} }],
    };
    const sigs = (SIG[wz.period] || SIG.swing).slice();
    if (wz.use === 'buy') sigs.push({ strategy: 'custom_buy', params: { target: buyHi } });
    if (wz.use !== 'watch') sigs.push({ strategy: 'rsi_overheat', params: { threshold: 75 } });

    // 警報
    const alerts = [
      { type: 'cross_down', price: buyLo, note: '跌破支撐' },
      { type: 'cross_up', price: target, note: '突破壓力/接近停利' },
    ];
    let composite = null;
    if (wz.use !== 'hold') {
      composite = {
        combine: 'AND', note: '買區',
        conditions: [{ left: 'close', op: 'lte', right: String(buyHi) }, { left: 'rsi14', op: 'lt', right: '45' }],
      };
    }
    // 畫線：支撐/壓力(預設) 與 斐波那契(獨立、預設關，避免一堆橫條)
    const draws = [
      { type: 'hline', p: buyLo, color: '#22c55e', source: 'wizard', label: '支撐 ' + buyLo },
      { type: 'hline', p: target, color: '#ef4444', source: 'wizard', label: '壓力 ' + target },
    ];
    let fib = null;
    if (d.sw && d.sw.swHigh > d.sw.swLow) {
      const tz = tzoff();
      fib = { type: 'fib', a: { t: d.sw.swHighT + tz, p: d.sw.swHigh }, b: { t: d.sw.swLowT + tz, p: d.sw.swLow }, color: '#fbbf24', source: 'wizard' };
    }
    return { slPct, stopPrice, target, buyLo, buyHi, fullShares, riskShares, entryRef, sigs, alerts, composite, draws, fib };
  }

  // ---- 規則式結論 ----
  function ruleConclusion() {
    const d = wz.diag, ctx = wz._ctx || {};
    const parts = [];
    parts.push(`技術面${d.techBias >= 60 ? '偏多' : d.techBias <= 40 ? '偏空' : '中性'}(${d.techBias})、RSI ${d.rsi != null ? d.rsi.toFixed(0) : '—'}、波動 ATR ${d.atrPct.toFixed(1)}%`);
    if (ctx.fund && ctx.fund.revenue && ctx.fund.revenue.yoyPct != null)
      parts.push(`月營收 YoY ${ctx.fund.revenue.yoyPct}%`);
    if (ctx.fund && ctx.fund.income && ctx.fund.income.netMargin != null)
      parts.push(`淨利率 ${ctx.fund.income.netMargin}%`);
    if (ctx.val && ctx.val.per != null) parts.push(`PER ${ctx.val.per}`);
    if (ctx.chip && ctx.chip.inst) {
      const t = ctx.chip.inst.trust_streak ?? ctx.chip.inst.trustStreak;
      const f = ctx.chip.inst.foreign_streak ?? ctx.chip.inst.foreignStreak;
      if (t) parts.push(`投信連${t > 0 ? '買' : '賣'}${Math.abs(t)}天`);
      else if (f) parts.push(`外資連${f > 0 ? '買' : '賣'}${Math.abs(f)}天`);
    }
    // 市場派/供應鏈
    const core = isCoreChain(wz.sym);
    let view = d.techBias >= 60 ? '順勢偏多，回檔分批' : d.techBias <= 40 ? '弱勢，待轉強再進' : '區間整理，等買區';
    if (core) view += '；屬台灣 AI 供應鏈核心，結構偏多但留意短線過熱風險';
    return parts.join('、') + '。研判：' + view + '。';
  }
  function isCoreChain(sym) {
    try {
      const names = (window.__CHAIN_CODES__ || []);
      if (names.length) return names.includes(sym);
    } catch {}
    return ['2330', '2317', '2454', '3711', '2308', '3037', '3017', '2382', '6669', '2345'].includes(sym);
  }

  // ---- UI ----
  function style() {
    if (document.getElementById('wz-style')) return;
    const s = document.createElement('style'); s.id = 'wz-style';
    s.textContent = `
    #wz-modal{position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:9999;display:none;align-items:center;justify-content:center}
    #wz-box{background:#0f172a;border:1px solid #334155;border-radius:12px;width:min(720px,96vw);max-height:92vh;overflow:auto;padding:18px;color:#e2e8f0;font-size:12px}
    #wz-box h3{margin:0 0 4px;font-size:16px;display:flex;align-items:center;gap:8px}
    #wz-box h3 .x{margin-left:auto;cursor:pointer;color:#94a3b8;font-size:20px}
    #wz-box .sub{color:#64748b;font-size:11px;margin-bottom:10px}
    .wz-q{margin:12px 0}
    .wz-q .ql{font-weight:700;margin-bottom:6px}
    .wz-opts{display:flex;gap:8px;flex-wrap:wrap}
    .wz-opt{flex:1;min-width:120px;background:#0b1220;border:1px solid #334155;border-radius:8px;padding:9px 10px;cursor:pointer;text-align:left}
    .wz-opt.on{border-color:#fbbf24;background:rgba(251,191,36,.12)}
    .wz-opt b{font-size:12px}.wz-opt span{display:block;color:#64748b;font-size:9.5px;margin-top:2px}
    .wz-row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
    .wz-row input{background:#0b1220;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:6px 9px;width:120px}
    .wz-row label{color:#94a3b8;font-size:11px}
    .wz-toggle{display:inline-flex;border:1px solid #334155;border-radius:6px;overflow:hidden}
    .wz-toggle button{background:#0b1220;border:0;color:#94a3b8;padding:5px 10px;cursor:pointer;font-size:11px}
    .wz-toggle button.on{background:rgba(251,191,36,.18);color:#fbbf24;font-weight:700}
    #wz-go{background:rgba(251,191,36,.18);border:1px solid #fbbf24;color:#fbbf24;border-radius:8px;padding:9px 22px;cursor:pointer;font-weight:700;font-size:13px}
    .wz-card{border:1px solid #1e293b;border-radius:8px;padding:10px;margin:8px 0;background:#0b1220}
    .wz-card h4{margin:0 0 6px;font-size:12px;color:#fbbf24;display:flex;align-items:center;gap:6px}
    .wz-card label{display:flex;align-items:center;gap:6px;margin:3px 0;font-size:11px;color:#cbd5e1}
    .wz-stat{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:8px 0}
    .wz-stat div{background:#0b1220;border:1px solid #1e293b;border-radius:6px;padding:6px}
    .wz-stat .l{font-size:9px;color:#64748b}.wz-stat .v{font-size:13px;font-weight:800;margin-top:2px}
    .wz-concl{background:#0b1220;border:1px solid #1e293b;border-radius:8px;padding:10px;font-size:11.5px;line-height:1.6;color:#c7d2fe;margin:8px 0}
    #wz-msg{font-size:11px;color:#94a3b8;min-height:14px;margin:6px 0}
    .wz-foot{display:flex;gap:8px;justify-content:flex-end;margin-top:10px}
    .wz-foot button{border-radius:8px;padding:8px 16px;cursor:pointer;font-size:12px;border:1px solid #334155;background:#1e293b;color:#cbd5e1}
    .wz-foot .pri{background:rgba(34,197,94,.18);border-color:#22c55e;color:#86efac;font-weight:700}`;
    document.head.appendChild(s);
  }

  function optBtn(group, val, title, desc) {
    const on = wz[group] === val;
    return `<div class="wz-opt${on ? ' on' : ''}" data-grp="${group}" data-val="${val}"><b>${title}</b><span>${desc}</span></div>`;
  }

  function renderQuestions() {
    const box = document.getElementById('wz-body');
    box.innerHTML = `
      <div class="wz-q"><div class="ql">1. 這檔對你是？</div><div class="wz-opts">
        ${optBtn('use', 'watch', '🔭 觀察中', '還沒買，等買點')}
        ${optBtn('use', 'hold', '💰 已持有', '管理停利停損')}
        ${optBtn('use', 'buy', '🎯 想建倉', '評估＋給買區')}
      </div></div>
      <div class="wz-q"><div class="ql">2. 操作週期？</div><div class="wz-opts">
        ${optBtn('period', 'long', '📅 長線', '季～年')}
        ${optBtn('period', 'swing', '〰️ 波段', '數週～數月')}
        ${optBtn('period', 'short', '⚡ 短線', '數日')}
      </div></div>
      <div class="wz-q"><div class="ql">3. 風險承受？</div><div class="wz-opts">
        ${optBtn('risk', 'low', '🛡️ 保守', '停損緊')}
        ${optBtn('risk', 'mid', '⚖️ 穩健', '預設')}
        ${optBtn('risk', 'high', '🔥 積極', '容許追勢')}
      </div></div>
      <div class="wz-q"><div class="ql">4. 可投入資金（算建議股數，可留空）</div>
        <div class="wz-row"><label>金額</label><input id="wz-cap" type="number" placeholder="例 300000" value="${wz.capital || ''}">${isTw() ? '<span style="color:#64748b">台股以「張」估</span>' : ''}</div>
      </div>
      ${wz.use === 'hold' ? `<div class="wz-q"><div class="ql">你的持倉（已持有才需填）</div>
        <div class="wz-row"><label>進場價</label><input id="wz-entry" type="number" value="${wz.entry || ''}">
        <label>股數</label><input id="wz-shares" type="number" value="${wz.shares || ''}"></div></div>` : ''}
      <div class="wz-q"><div class="wz-row">
        <label>停損方式</label>
        <span class="wz-toggle"><button data-tg="slMode" data-v="atr" class="${wz.slMode === 'atr' ? 'on' : ''}">ATR 自適應</button><button data-tg="slMode" data-v="fixed" class="${wz.slMode === 'fixed' ? 'on' : ''}">固定 %</button></span>
        <label>結論</label>
        <span class="wz-toggle"><button data-tg="conclMode" data-v="rule" class="${wz.conclMode === 'rule' ? 'on' : ''}">規則即時</button><button data-tg="conclMode" data-v="ai" class="${wz.conclMode === 'ai' ? 'on' : ''}">Claude 口語</button></span>
      </div></div>
      <div id="wz-msg"></div>
      <div class="wz-foot"><button class="x2" id="wz-cancel">取消</button><button id="wz-go">分析並產生建議 →</button></div>`;
    box.querySelectorAll('.wz-opt').forEach(el => el.onclick = () => { wz[el.dataset.grp] = el.dataset.val; renderQuestions(); });
    box.querySelectorAll('[data-tg]').forEach(b => b.onclick = () => { wz[b.dataset.tg] = b.dataset.v; syncInputs(); renderQuestions(); });
    box.querySelector('#wz-go').onclick = onAnalyze;
    box.querySelector('#wz-cancel').onclick = close;
  }
  function syncInputs() {
    const cap = document.getElementById('wz-cap'); if (cap) wz.capital = parseFloat(cap.value) || 0;
    const en = document.getElementById('wz-entry'); if (en) wz.entry = parseFloat(en.value) || 0;
    const sh = document.getElementById('wz-shares'); if (sh) wz.shares = parseFloat(sh.value) || 0;
  }

  async function onAnalyze() {
    syncInputs();
    const msg = document.getElementById('wz-msg');
    wz.diag = compute();
    if (!wz.diag) { msg.innerHTML = '<span style="color:#f87171">資料不足，請先載入個股(建議 1 年日線)</span>'; return; }
    msg.textContent = '體檢中…抓基本面/估值/籌碼';
    try { wz._ctx = await fetchContext(wz.sym); } catch { wz._ctx = {}; }
    wz.sug = buildSuggestions();
    // 結論
    if (wz.conclMode === 'ai') {
      wz.conclusion = '產生中…';
      renderSummary();
      wz.conclusion = await aiConclusion();
      renderSummary();
    } else {
      wz.conclusion = ruleConclusion();
      renderSummary();
    }
  }

  async function aiConclusion() {
    const key = (typeof S !== 'undefined' && S.apiKey) ? S.apiKey : '';
    if (!key) return ruleConclusion() + '（未設 API KEY，改用規則結論）';
    const d = wz.diag, ctx = wz._ctx || {};
    const prompt = `你是專業台股分析師。用 2~3 句繁體中文，為個股 ${wz.sym} 寫操作研判。`
      + `數據：技術分數 ${d.techBias}/100、RSI ${d.rsi != null ? d.rsi.toFixed(0) : '—'}、ATR ${d.atrPct.toFixed(1)}%、`
      + `支撐 ${wz.sug.buyLo}、壓力 ${wz.sug.target}`
      + (ctx.fund && ctx.fund.revenue ? `、月營收YoY ${ctx.fund.revenue.yoyPct}%` : '')
      + (ctx.val && ctx.val.per != null ? `、PER ${ctx.val.per}` : '')
      + `。使用者：${({ watch: '觀察中', hold: '已持有', buy: '想建倉' }[wz.use])}、${({ long: '長線', swing: '波段', short: '短線' }[wz.period])}、風險${({ low: '保守', mid: '穩健', high: '積極' }[wz.risk])}。`
      + `以代號為準不臆測公司名；若屬台灣 AI 供應鏈核心納入結構偏多視角但點出短線風險；只回研判本文不要前綴。`;
    try {
      const r = await fetch(`${SRV}/ai-note`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ apiKey: key, prompt, max_tokens: 320 }) }).then(x => x.json());
      return r.text ? r.text : ruleConclusion();
    } catch { return ruleConclusion(); }
  }

  const SIG_LBL = {
    sma60_pullback: '回測60日線', sma20_pullback: '回測20日線', breakout_n_high: '突破N日新高',
    rsi_oversold_bounce: 'RSI超賣反彈', bb_lower_touch: '布林下軌承接', rsi_overheat: 'RSI過熱(賣)',
    custom_buy: '自訂買進價', custom_sell: '自訂賣出價',
  };

  function renderSummary() {
    const d = wz.diag, s = wz.sug;
    const box = document.getElementById('wz-body');
    const chk = (id, on) => `<input type="checkbox" id="${id}" ${on ? 'checked' : ''}>`;
    const sigList = s.sigs.map(sig => {
      const sc = d.scanMap[sig.strategy];
      const wr = sc && sc.winRate != null ? ` <span style="color:#64748b">(歷史勝率 ${sc.winRate.toFixed(0)}%)</span>` : '';
      return `<label>${chk('wz-sig-' + sig.strategy + '-' + (sig.params.target || sig.params.days || ''), true)} ${SIG_LBL[sig.strategy] || sig.strategy}${sig.params.target ? ' @' + sig.params.target : ''}${wr}</label>`;
    }).join('');
    box.innerHTML = `
      <div class="wz-stat">
        <div><div class="l">現價</div><div class="v">${d.price.toFixed(2)}</div></div>
        <div><div class="l">技術分數</div><div class="v" style="color:${d.techBias >= 60 ? '#22c55e' : d.techBias <= 40 ? '#ef4444' : '#fbbf24'}">${d.techBias}</div></div>
        <div><div class="l">支撐</div><div class="v" style="color:#22c55e">${s.buyLo}</div></div>
        <div><div class="l">壓力</div><div class="v" style="color:#ef4444">${s.target}</div></div>
      </div>
      <div class="wz-concl">🧠 ${wz.conclusion || ''}</div>

      <div class="wz-card"><h4>${chk('wz-ap-watch', true)} 觀察訊號（WATCH 後端 24h 偵測）</h4>${sigList}</div>

      <div class="wz-card"><h4>${chk('wz-ap-alert', true)} 警報（🔔 後端推播）</h4>
        <label>跌破支撐 ${s.buyLo}　|　突破壓力 ${s.target}</label>
        ${s.composite ? `<label>買區複合警示：收盤 ≤ ${s.buyHi} 且 RSI &lt; 45</label>` : ''}
      </div>

      ${wz.use === 'hold'
        ? `<div class="wz-card"><h4>${chk('wz-ap-pos', true)} 持倉計畫（PLAN）</h4>
            <label>進場 ${wz.entry || d.price.toFixed(2)}・股數 ${wz.shares || '—'}・停損 ${s.stopPrice}（-${s.slPct}%）・停利 ${s.target}</label></div>`
        : `<div class="wz-card"><h4>${chk('wz-ap-pos', true)} 買進計畫</h4>
            <label>買區 ${s.buyLo}~${s.buyHi}・停損 ${s.stopPrice}（-${s.slPct}%）・停利 ${s.target}</label>
            ${wz.capital > 0 ? `<label>建議股數：全額 ${s.fullShares.toLocaleString()}　|　風險控管 ${s.riskShares.toLocaleString()}（${isTw() ? '股' : '股'}）</label>` : ''}</div>`}

      <div class="wz-card"><h4>${chk('wz-ap-draw', true)} 畫線：支撐/壓力水平線</h4>
        ${s.fib ? `<label>${chk('wz-ap-fib', false)} 加畫斐波那契回撤（7 條，預設不畫避免太雜）</label>` : ''}</div>

      <div id="wz-msg"></div>
      <div class="wz-foot"><button id="wz-back">← 改答案</button><button class="pri" id="wz-apply">✅ 套用勾選項目</button></div>`;
    box.querySelector('#wz-back').onclick = renderQuestions;
    box.querySelector('#wz-apply').onclick = apply;
  }

  // ---- 套用 ----
  async function apply() {
    const msg = document.getElementById('wz-msg'); msg.textContent = '套用中…';
    const sym = wz.sym, mkt = wz.mkt, s = wz.sug;
    const done = [];
    try {
      // WATCH
      if (document.getElementById('wz-ap-watch')?.checked) {
        if (typeof S !== 'undefined') {
          if (!S.watches) S.watches = {};
          const prevW = S.watches[sym] || {};
          const keep = (prevW.signals || []).filter(x => x.source !== 'wizard');
          const add = s.sigs.map((sig, i) => ({ id: 'wz' + Date.now() + i, strategy: sig.strategy, params: sig.params, source: 'wizard', addedAt: Date.now(), updatedAt: Date.now(), lastEval: null }));
          // 保留既有欄位(sym/notes/addedAt) — 漏 sym 會讓 WATCH 標題顯示 undefined
          S.watches[sym] = Object.assign({}, prevW, { sym: sym, mkt: mkt, notes: prevW.notes || '', addedAt: prevW.addedAt || Date.now(), signals: [...keep, ...add] });
          if (typeof saveWatches === 'function') saveWatches();
          if (typeof renderRpanel === 'function' && S.tab === 'watch') { try { renderRpanel(); } catch {} }
          done.push('觀察訊號');
        }
      }
      // 警報
      if (document.getElementById('wz-ap-alert')?.checked) {
        let rules = [];
        try { rules = await fetch(`${SRV}/alert/rules`).then(r => r.ok ? r.json() : []); } catch {}
        if (!Array.isArray(rules)) rules = [];
        rules = rules.filter(r => !(r.source === 'wizard' && r.sym === sym));
        s.alerts.forEach((a, i) => rules.push({ id: Date.now() + i, sym, market: mkt, type: a.type, price: a.price, note: a.note, enabled: true, source: 'wizard' }));
        if (s.composite) rules.push({ id: Date.now() + 99, type: 'composite', sym, market: mkt, combine: s.composite.combine, conditions: s.composite.conditions, note: s.composite.note, enabled: true, source: 'wizard' });
        try { await fetch(`${SRV}/alert/rules`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rules) }); done.push('警報'); } catch {}
      }
      // 持倉/計畫
      if (document.getElementById('wz-ap-pos')?.checked) {
        if (wz.use === 'hold' && typeof setPosition === 'function' && typeof S !== 'undefined' && S.sym === sym) {
          setPosition(wz.entry || wz.diag.price, wz.shares || 0, s.target, s.stopPrice, '精靈建議: ' + (wz.conclusion || ''));
          done.push('持倉');
        } else {
          // 想建倉/觀察：存買進計畫到 localStorage
          try { const k = 'wizard_plans'; const o = JSON.parse(localStorage.getItem(k) || '{}'); o[sym] = { buyLo: s.buyLo, buyHi: s.buyHi, stop: s.stopPrice, target: s.target, fullShares: s.fullShares, riskShares: s.riskShares, ts: Date.now() }; localStorage.setItem(k, JSON.stringify(o)); done.push('買進計畫'); } catch {}
        }
      }
      // 畫線（支撐/壓力，斐波那契選配）
      if (document.getElementById('wz-ap-draw')?.checked && typeof window.drawToolsAdd === 'function') {
        const arr = s.draws.slice();
        if (s.fib && document.getElementById('wz-ap-fib')?.checked) arr.push(s.fib);
        window.drawToolsAdd(sym, arr, { replaceSource: 'wizard' });
        done.push('畫線');
      }
      // 結論備註
      try { const k = 'wizard_notes'; const o = JSON.parse(localStorage.getItem(k) || '{}'); o[sym] = { note: wz.conclusion, ts: Date.now() }; localStorage.setItem(k, JSON.stringify(o)); } catch {}
    } catch (e) {
      msg.innerHTML = '<span style="color:#f87171">套用部分失敗：' + e.message + '</span>'; return;
    }
    msg.innerHTML = `<span style="color:#86efac">✅ 已套用：${done.join('、') || '（無）'}</span>`;
    setTimeout(close, 900);
  }

  function open(sym, mkt) {
    style();
    sym = (sym || (typeof S !== 'undefined' && S.sym) || '').toUpperCase();
    mkt = mkt || (typeof S !== 'undefined' && S.mkt) || 'TW';
    if (!sym) { alert('請先載入一支股票'); return; }
    wz = Object.assign({ sym, mkt, entry: 0, shares: 0, conclusion: '' }, DEFAULTS);
    // 已持有自動帶入既有持倉
    try { if (typeof S !== 'undefined' && S.positions && S.positions[sym]) { wz.use = 'hold'; wz.entry = S.positions[sym].entry || 0; wz.shares = S.positions[sym].shares || 0; } } catch {}
    let m = document.getElementById('wz-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'wz-modal';
      m.innerHTML = `<div id="wz-box"><h3>🧙 加股設定精靈 <span style="font-size:11px;color:#64748b" id="wz-sym"></span><span class="x" onclick="window.wizardClose&&wizardClose()">×</span></h3><div class="sub">回答 4 題 → 自動體檢並建議 觀察訊號/警報/計畫/畫線，可逐項取消後套用。</div><div id="wz-body"></div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    document.getElementById('wz-sym').textContent = sym + ' · ' + mkt;
    m.style.display = 'flex';
    renderQuestions();
  }
  function close() { const m = document.getElementById('wz-modal'); if (m) m.style.display = 'none'; }

  window.wizardOpen = open;
  window.wizardClose = close;
})();

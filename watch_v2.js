// ============================================================
// Stock Terminal v2.0 — Watch List & Strategy Playbook (multi-signal)
// ------------------------------------------------------------
// 一檔股票可掛多個訊號 + 共識評分 (Confluence) + 預設劇本組合。
//
// 資料結構：
//   S.watches = {
//     '2330': {
//       sym, mkt, notes, addedAt,
//       signals: [
//         { id, strategy, params, addedAt, lastEval },
//         ...
//       ]
//     }
//   }
//
// 載入順序：在 position_v2.js 之後（共用 num/fx）。
// ============================================================

const LS_KEY_WATCH = 'stock_terminal_watches_v2';

// ── State bootstrap (with migration from old single-signal format) ──
(function bootWatches() {
  if (typeof S === 'undefined') { console.error('[v2-watch] S missing'); return; }
  try {
    const stored = localStorage.getItem(LS_KEY_WATCH);
    S.watches = stored ? JSON.parse(stored) : {};
  } catch { S.watches = {}; }
  if (typeof S.watches !== 'object' || S.watches === null || Array.isArray(S.watches)) {
    S.watches = {};
  }
  // Migrate old flat format ({sym, strategy, params, ...}) → new ({sym, signals: [...]})
  let migrated = 0;
  for (const code in S.watches) {
    const w = S.watches[code];
    // 自我修復：舊版/精靈曾漏寫 sym → 標題 undefined、刪不掉。用 key 回填。
    if (w && typeof w === 'object' && !w.sym) { w.sym = code; migrated++; }
    if (Array.isArray(w?.signals)) continue;
    if (w?.strategy) {
      S.watches[code] = {
        sym: code,
        mkt: w.mkt || 'TW',
        notes: w.notes || '',
        addedAt: w.addedAt || Date.now(),
        signals: [{
          id: genSigId(),
          strategy: w.strategy,
          params: w.params || {},
          addedAt: w.addedAt || Date.now(),
          updatedAt: w.updatedAt || Date.now(),
          lastEval: w.lastEval || null,
        }],
      };
      migrated++;
    }
  }
  if (migrated > 0) {
    saveWatches();
    console.log('[v2-watch] migrated', migrated, 'old single-signal entries to new format');
  }
  S.watchFormMode = 'preset';     // 'preset' | 'single'
  S.watchFormPreset = 'classic_pullback';
  S.watchFormStrategy = 'sma60_pullback';
  console.log('[v2-watch] booted —', Object.keys(S.watches).length, 'stock(s) loaded');
})();

function genSigId() {
  return 's' + Math.random().toString(36).slice(2, 9) + Date.now().toString(36).slice(-3);
}

function saveWatches() {
  if (!S.watches) S.watches = {};
  localStorage.setItem(LS_KEY_WATCH, JSON.stringify(S.watches));
  syncWatchesToServer();   // v3.8: 同步給後端 24h 偵測
}

// 同步觀察清單到 server（debounce），供 watch_daemon 後端評估
let _watchSyncTimer = null;
function syncWatchesToServer() {
  clearTimeout(_watchSyncTimer);
  _watchSyncTimer = setTimeout(() => {
    try {
      const SRV = window.SERVER || 'http://localhost:18432';
      // 精簡：只送後端需要的欄位
      const out = {};
      for (const code in (S.watches || {})) {
        const w = S.watches[code];
        out[code] = { mkt: w.mkt || 'TW', signals: (w.signals || []).map(s => ({ id: s.id, strategy: s.strategy, params: s.params || {} })) };
      }
      fetch(`${SRV}/watch/rules`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(out) }).catch(() => {});
    } catch {}
  }, 800);
}

// ── Strategy Playbook ──────────────────────────────────────
const STRATEGIES = [
  {
    key: 'sma60_pullback',
    lbl: '回測 60 日均線進場',
    icon: '📉',
    type: 'trend',
    direction: 'buy',
    difficulty: '★☆☆ 簡單',
    desc: '價格回到 60 日均線附近，找多頭趨勢中的低風險進場點。',
    why: '60 日均線代表中期趨勢。多頭結構下，價格回檔到 SMA60 通常是中線買盤接手點，' +
         '法人也常在此分批承接。專業稱「Pullback to MA」。',
    when: '✓ 適合：強勢上漲後的回檔、SMA60 朝上、最近 6 個月有上漲\n' +
          '✗ 不適合：明顯下跌趨勢、SMA60 朝下',
    action: '分 3 批：到 SMA60 進 1/3 → 再跌 2% 進 1/3 → 跌破 SMA60 -3% 進最後 1/3。停損 SMA60 -5%。',
    paramFields: [{key:'tolerance', lbl:'容差 %', default:1.5, hint:'價距 SMA60 多少 % 算「附近」', type:'number', min:0.5, max:5, step:0.5}],
    check(ind, candles, params) {
      const c = candles[candles.length-1].close;
      const sma60 = num(ind.sma60);
      if (sma60 == null) return {status:'no-data', detail:'SMA60 尚無資料'};
      const tol = (params?.tolerance ?? 1.5) / 100;
      const upper = sma60 * (1+tol), lower = sma60 * (1-tol);
      if (c >= lower && c <= upper) return {status:'trigger', detail:`進入容差區 ${lower.toFixed(2)}~${upper.toFixed(2)}`, triggerPrice: sma60};
      if (c < lower) return {status:'broken', detail:`跌破容差下緣 ${lower.toFixed(2)}，趨勢可能轉弱`, triggerPrice: sma60};
      return {status:'wait', detail:`距 SMA60 上緣 ${upper.toFixed(2)} 還 ${((c-upper)/c*100).toFixed(2)}%`, triggerPrice: sma60};
    },
  },
  {
    key: 'sma20_pullback',
    lbl: '回測 20 日均線進場',
    icon: '📊',
    type: 'trend',
    direction: 'buy',
    difficulty: '★☆☆ 簡單',
    desc: '價格短線回到 20 日均線，強勢股「不破 SMA20」的順勢加碼。',
    why: 'SMA20 是短期趨勢線。強勢股回檔常停在 SMA20 不破，是加碼的甜蜜點。',
    when: '✓ 適合：剛突破壓力、SMA20 朝上、過去 1~2 個月一路漲\n✗ 不適合：盤整或下跌、SMA20 朝下',
    action: '進場 1/3~1/2，停損 SMA20 -3%。',
    paramFields: [{key:'tolerance', lbl:'容差 %', default:1.0, hint:'價距 SMA20 多少 % 算「附近」', type:'number', min:0.3, max:3, step:0.3}],
    check(ind, candles, params) {
      const c = candles[candles.length-1].close;
      const sma20 = num(ind.sma20);
      if (sma20 == null) return {status:'no-data', detail:'SMA20 尚無資料'};
      const tol = (params?.tolerance ?? 1) / 100;
      const upper = sma20*(1+tol), lower = sma20*(1-tol);
      if (c >= lower && c <= upper) return {status:'trigger', detail:`進入容差區 ${lower.toFixed(2)}~${upper.toFixed(2)}`, triggerPrice: sma20};
      if (c < lower) return {status:'broken', detail:`跌破容差下緣 ${lower.toFixed(2)}，等下波或改 SMA60`, triggerPrice: sma20};
      return {status:'wait', detail:`距 SMA20 上緣 ${upper.toFixed(2)} 還 ${((c-upper)/c*100).toFixed(2)}%`, triggerPrice: sma20};
    },
  },
  {
    key: 'breakout_n_high',
    lbl: '突破 N 日新高',
    icon: '🚀',
    type: 'momentum',
    direction: 'buy',
    difficulty: '★★☆ 中等',
    desc: '價格站上最近 N 個交易日的最高點 + 量增，動能進場訊號。',
    why: '突破近期高點代表買盤強勢；配合量能 > 1.5x 通常是法人或主力進場。專業稱「Breakout」。',
    when: '✓ 適合：盤整後突破、明顯壓力區突破、量能配合\n✗ 不適合：高位追高、量能不足（假突破）',
    action: '突破當下進 1/3，3~5 日內回測突破點不破再加 1/3。停損突破點 -3~5%。',
    paramFields: [
      {key:'days', lbl:'回看天數', default:20, hint:'20/60/252', type:'number', min:5, max:252, step:1},
      {key:'volMult', lbl:'量能倍數', default:1.5, hint:'大於 20 日均量幾倍', type:'number', min:1, max:5, step:0.5},
    ],
    check(ind, candles, params) {
      const days = Math.floor(params?.days ?? 20);
      const volMult = params?.volMult ?? 1.5;
      const c = candles[candles.length-1].close;
      if (candles.length < days+1) return {status:'no-data', detail:`需要 ${days+1} 個交易日`};
      const recent = candles.slice(-(days+1), -1);
      const maxHigh = Math.max(...recent.map(x => x.high));
      const volRatio = num(ind.volRatio);
      if (c > maxHigh) {
        if (volRatio != null && volRatio >= volMult) {
          return {status:'trigger', detail:`突破 ${days} 日新高 ${maxHigh.toFixed(2)} + 量 ${volRatio.toFixed(1)}x`, triggerPrice: maxHigh};
        }
        return {status:'partial', detail:`價突破但量不足 (${volRatio==null?'?':volRatio.toFixed(1)}x，需 ${volMult}x)`, triggerPrice: maxHigh};
      }
      return {status:'wait', detail:`距 ${days} 日高 ${maxHigh.toFixed(2)} 還 +${((maxHigh-c)/c*100).toFixed(2)}%`, triggerPrice: maxHigh};
    },
  },
  {
    key: 'rsi_oversold_bounce',
    lbl: 'RSI 超賣反彈',
    icon: '🔄',
    type: 'momentum',
    direction: 'buy',
    difficulty: '★★☆ 中等',
    desc: 'RSI 從 30 以下回升突破 30，短線超賣反彈進場。',
    why: 'RSI < 30 是技術超賣區。回升突破 30 意味賣壓減緩。常用「捕底」訊號。',
    when: '✓ 適合：個股有基本面支撐、整體盤整、短線急跌後\n✗ 不適合：明顯下跌趨勢',
    action: '進場 1/3 試單，停損近期低 -3%。短線目標 5~10%。',
    paramFields: [],
    check(ind, candles, params) {
      const rsi = num(ind.rsi14);
      if (rsi == null) return {status:'no-data', detail:'RSI 尚無資料'};
      if (rsi >= 30 && rsi <= 38) return {status:'trigger', detail:`RSI ${rsi.toFixed(1)} 在反彈區 (30~38)`};
      if (rsi < 30) return {status:'wait', detail:`RSI ${rsi.toFixed(1)} 仍超賣，等回升突破 30`};
      if (rsi > 38 && rsi < 50) return {status:'expired', detail:`RSI ${rsi.toFixed(1)} 已過反彈區，訊號失效`};
      return {status:'wait', detail:`RSI ${rsi.toFixed(1)}（非觀察區）`};
    },
  },
  {
    key: 'bb_lower_touch',
    lbl: '布林下軌承接',
    icon: '📍',
    type: 'volatility',
    direction: 'buy',
    difficulty: '★☆☆ 簡單',
    desc: '價格觸碰或跌破布林通道下軌，短線超賣反彈機會。',
    why: 'BB 下軌 = SMA20 -2σ。統計上只有 2.5% 機率落在下軌外，反彈到中軌機率高。',
    when: '✓ 適合：盤整、上漲趨勢中的回檔\n✗ 不適合：強勢下跌 (walk the band)',
    action: '進場 1/3，停損下軌 -3%。目標：回到 SMA20。',
    paramFields: [],
    check(ind, candles, params) {
      const c = candles[candles.length-1].close;
      const bbL = num(ind.bbL);
      const sma20 = num(ind.sma20);
      if (bbL == null) return {status:'no-data', detail:'BB 尚無資料'};
      if (c <= bbL) {
        const tgt = sma20 != null ? `，目標 SMA20 ${sma20.toFixed(2)}` : '';
        return {status:'trigger', detail:`觸下軌 ${bbL.toFixed(2)}${tgt}`, triggerPrice: bbL};
      }
      return {status:'wait', detail:`距下軌 ${bbL.toFixed(2)} 還 +${((c-bbL)/bbL*100).toFixed(2)}%`, triggerPrice: bbL};
    },
  },
  {
    key: 'rsi_overheat',
    lbl: 'RSI 過熱警示',
    icon: '🔥',
    type: 'momentum',
    direction: 'sell',
    difficulty: '★☆☆ 簡單',
    desc: 'RSI > 75 進入超買區，動能過熱提示分批停利。',
    why: 'RSI > 75 代表短線買盤過度，回檔機率上升。專業稱「Overbought」。',
    when: '✓ 適合：已建倉部位的停利提示、短線出貨\n✗ 不適合：強趨勢中 RSI 可長期 > 70',
    action: '減碼 1/3 鎖利，或上調移動停損；若沒持倉就放棄追高。',
    paramFields: [{key:'threshold', lbl:'門檻 RSI', default:75, hint:'RSI 大於多少算過熱', type:'number', min:65, max:90, step:1}],
    check(ind, candles, params) {
      const rsi = num(ind.rsi14);
      const thr = params?.threshold ?? 75;
      if (rsi == null) return {status:'no-data', detail:'RSI 尚無資料'};
      if (rsi >= thr) return {status:'trigger', detail:`RSI ${rsi.toFixed(1)} ≥ ${thr}，過熱`};
      if (rsi >= thr - 5) return {status:'wait', detail:`RSI ${rsi.toFixed(1)} 接近過熱 (${thr})`};
      return {status:'wait', detail:`RSI ${rsi.toFixed(1)}（離過熱還 ${(thr-rsi).toFixed(1)} 點）`};
    },
  },
  {
    key: 'custom_buy',
    lbl: '自訂價位買進',
    icon: '🎯',
    type: 'price',
    direction: 'buy',
    difficulty: '★☆☆ 簡單',
    desc: '價格跌到設定值（或更低）就提醒進場。',
    why: '最簡單也最常用：你已研究好「這個價格我願意買」，價到提醒。',
    when: '配合基本面分析的合理買進區、技術支撐、歷史低點等',
    action: '依個人計畫進場。建議到價先進 1/2，觀察走勢再決定加碼。',
    paramFields: [{key:'target', lbl:'買進價', default:'', hint:'價 ≤ 此值即觸發', type:'number', min:0, step:0.01}],
    check(ind, candles, params) {
      const c = candles[candles.length-1].close;
      const tgt = num(params?.target);
      if (tgt == null) return {status:'no-data', detail:'未設定買進價'};
      if (c <= tgt) return {status:'trigger', detail:`已達買進價 ${tgt.toFixed(2)}`, triggerPrice: tgt};
      return {status:'wait', detail:`距買進價 ${tgt.toFixed(2)} 還 -${((c-tgt)/c*100).toFixed(2)}%`, triggerPrice: tgt};
    },
  },
  {
    key: 'custom_sell',
    lbl: '自訂價位賣出',
    icon: '💰',
    type: 'price',
    direction: 'sell',
    difficulty: '★☆☆ 簡單',
    desc: '價格漲到設定值（或更高）就提醒減碼/停利。',
    why: '預設停利提示。漲到目標就提醒，避免「賺了不賣 → 跌回又虧」。',
    when: '已建倉部位的停利計畫、波段操作目標價',
    action: '依計畫減碼。建議到價先賣 1/2，再漲再加碼出。',
    paramFields: [{key:'target', lbl:'賣出價', default:'', hint:'價 ≥ 此值即觸發', type:'number', min:0, step:0.01}],
    check(ind, candles, params) {
      const c = candles[candles.length-1].close;
      const tgt = num(params?.target);
      if (tgt == null) return {status:'no-data', detail:'未設定賣出價'};
      if (c >= tgt) return {status:'trigger', detail:`已達賣出價 ${tgt.toFixed(2)}`, triggerPrice: tgt};
      return {status:'wait', detail:`距賣出價 ${tgt.toFixed(2)} 還 +${((tgt-c)/c*100).toFixed(2)}%`, triggerPrice: tgt};
    },
  },
];

// ── Preset combos: pro-curated multi-signal bundles ────────
const PRESETS = [
  {
    key: 'classic_pullback',
    lbl: '經典回檔買進',
    icon: '📉',
    desc: '多頭趨勢中等價格回測重要均線 + 動能未過熱，最穩健的進場組合。',
    when: '個股長期向上、近期短線回檔，想等更好價位時',
    customPriceLbl: null,
    signals: [
      {strategy:'sma60_pullback', params:{tolerance:2}},
      {strategy:'sma20_pullback', params:{tolerance:1}},
      {strategy:'rsi_oversold_bounce', params:{}},
    ],
  },
  {
    key: 'momentum_breakout',
    lbl: '強勢突破追勢',
    icon: '🚀',
    desc: '突破近期 20 日與 60 日高點 + 量增，動能進場標準組合。',
    when: '盤整後想抓突破時機、追強勢股',
    customPriceLbl: null,
    signals: [
      {strategy:'breakout_n_high', params:{days:20, volMult:1.5}},
      {strategy:'breakout_n_high', params:{days:60, volMult:2}},
      {strategy:'sma20_pullback', params:{tolerance:1.5}},   // 突破後若回測 SMA20 不破也是好點
    ],
  },
  {
    key: 'oversold_bounce',
    lbl: '超賣反彈短線',
    icon: '🔄',
    desc: 'RSI + 布林下軌雙重超賣訊號，短線反彈勝率高。',
    when: '短線急殺後想抓反彈、配合基本面尚可的個股',
    customPriceLbl: null,
    signals: [
      {strategy:'rsi_oversold_bounce', params:{}},
      {strategy:'bb_lower_touch', params:{}},
    ],
  },
  {
    key: 'swing_take_profit',
    lbl: '波段停利',
    icon: '💰',
    desc: '到設定目標 + RSI 過熱 雙重訊號，避免「賺了不賣 → 跌回又虧」。',
    when: '已建倉部位的停利規劃',
    customPriceLbl: '停利目標價',
    customPriceMode: 'sell',
    signals: [
      {strategy:'custom_sell', params:{target:null}},    // ← filled by user
      {strategy:'rsi_overheat', params:{threshold:75}},
    ],
  },
  {
    key: 'support_resistance',
    lbl: '雙價位警示',
    icon: '🎯',
    desc: '設定買進價（下方）+ 賣出價（上方）。最自由的純價格組合。',
    when: '基本面分析後得出的合理買區 + 停利目標',
    customPriceLbl: '買進價（下）',
    customPriceLbl2: '賣出價（上）',
    customPriceMode: 'both',
    signals: [
      {strategy:'custom_buy', params:{target:null}},
      {strategy:'custom_sell', params:{target:null}},
    ],
  },
];

// ── Watch operations (multi-signal) ────────────────────────
function ensureStockWatch(sym, mkt) {
  const code = sym.toUpperCase().trim();
  if (!S.watches[code]) {
    S.watches[code] = {
      sym: code,
      mkt: mkt || S.mkt || 'TW',
      notes: '',
      addedAt: Date.now(),
      signals: [],
    };
  }
  return S.watches[code];
}

function addSignal(sym, strategyKey, params, mkt) {
  const strat = STRATEGIES.find(s => s.key === strategyKey);
  if (!strat) { alert('未知策略：' + strategyKey); return false; }
  // Validate required params (custom_buy/sell need a target)
  if ((strategyKey === 'custom_buy' || strategyKey === 'custom_sell')) {
    const t = num(params?.target);
    if (t == null || t <= 0) { alert(`「${strat.lbl}」必須填正數的價格`); return false; }
  }
  const w = ensureStockWatch(sym, mkt);
  w.signals.push({
    id: genSigId(),
    strategy: strategyKey,
    params: params || {},
    addedAt: Date.now(),
    lastEval: null,
  });
  saveWatches();
  return true;
}

function removeSignal(sym, sigId) {
  const code = sym.toUpperCase().trim();
  const w = S.watches[code];
  if (!w) return;
  w.signals = w.signals.filter(s => s.id !== sigId);
  if (w.signals.length === 0) delete S.watches[code];
  saveWatches();
  if (S.tab === 'watch') renderRpanel();
}

function removeStockWatch(sym) {
  const code = sym.toUpperCase().trim();
  delete S.watches[code];
  saveWatches();
  if (S.tab === 'watch') renderRpanel();
}

function applyPreset(sym, presetKey, customPrice, customPrice2, mkt) {
  const preset = PRESETS.find(p => p.key === presetKey);
  if (!preset) { alert('未知劇本'); return false; }
  // Validate custom price requirements
  if (preset.customPriceMode === 'sell' || preset.customPriceMode === 'both') {
    const t = num(customPrice ?? customPrice2);
    if (t == null || t <= 0) { alert(`劇本「${preset.lbl}」需要填${preset.customPriceLbl || '價格'}`); return false; }
  }
  if (preset.customPriceMode === 'both') {
    if (num(customPrice) == null || num(customPrice2) == null) { alert(`需要填兩個價格`); return false; }
  }
  const w = ensureStockWatch(sym, mkt);
  let added = 0;
  for (const sig of preset.signals) {
    const params = { ...sig.params };
    if (sig.strategy === 'custom_buy') params.target = num(customPrice);
    if (sig.strategy === 'custom_sell') {
      params.target = preset.customPriceMode === 'both' ? num(customPrice2) : num(customPrice);
    }
    w.signals.push({
      id: genSigId(),
      strategy: sig.strategy,
      params,
      addedAt: Date.now(),
      lastEval: null,
    });
    added++;
  }
  saveWatches();
  console.log('[v2-watch] applied preset', presetKey, 'to', sym, '→ added', added, 'signal(s)');
  return true;
}

function evaluateSignal(sig, ind, candles) {
  const strat = STRATEGIES.find(s => s.key === sig.strategy);
  if (!strat) return {status:'error', detail:'未知策略 '+sig.strategy};
  if (!ind || !candles || candles.length < 2) return {status:'no-data', detail:'尚未載入'};
  try { return strat.check(ind, candles, sig.params || {}); }
  catch (e) { console.error('[v2-watch] strategy threw:', e); return {status:'error', detail: e.message}; }
}

function refreshSignalsForStock(stockWatch) {
  if (!stockWatch || stockWatch.sym !== S.sym?.toUpperCase().trim()) return;
  if (!S.ind || !S.data?.candles) return;
  const price = S.data.candles[S.data.candles.length-1].close;
  for (const sig of stockWatch.signals) {
    sig.lastEval = {
      ...evaluateSignal(sig, S.ind, S.data.candles),
      evaluatedAt: Date.now(),
      price,
    };
  }
  saveWatches();
}

// ── Confluence: aggregate multi-signal score per stock ──────
function signalDirection(sig) {
  const strat = STRATEGIES.find(s => s.key === sig.strategy);
  if (!strat) return 'neutral';
  const status = sig.lastEval?.status;
  if (status === 'trigger') return strat.direction || 'neutral';
  if (status === 'broken') return strat.direction === 'buy' ? 'sell' : 'buy'; // pullback broken → bearish
  return 'neutral';
}

function computeConfluence(stockWatch) {
  let buy = 0, sell = 0, triggered = 0, total = 0, broken = 0, waiting = 0, partial = 0, expired = 0;
  for (const sig of (stockWatch.signals || [])) {
    total++;
    const status = sig.lastEval?.status;
    if (status === 'trigger')       { triggered++; const d = signalDirection(sig); if (d==='buy') buy++; if (d==='sell') sell++; }
    else if (status === 'partial')  { partial++; }
    else if (status === 'broken')   { broken++; sell++; }
    else if (status === 'expired')  { expired++; }
    else                            { waiting++; }
  }
  const score = buy - sell;
  let bias, biasIcon, biasLbl;
  if (total === 0)                     { bias='empty'; biasIcon='—'; biasLbl='無訊號'; }
  else if (triggered === 0 && broken === 0) { bias='observing'; biasIcon='👀'; biasLbl='觀察中'; }
  else if (buy > 0 && sell > 0)        { bias='conflict'; biasIcon='⚠️'; biasLbl='多空分歧'; }
  else if (score >= 2)                 { bias='strong-bull'; biasIcon='🟢'; biasLbl='強多 +'+score; }
  else if (score === 1)                { bias='bull';        biasIcon='🟢'; biasLbl='偏多 +1'; }
  else if (score === -1)               { bias='bear';        biasIcon='🔴'; biasLbl='偏空 -1'; }
  else if (score <= -2)                { bias='strong-bear'; biasIcon='🔴'; biasLbl='強空 '+score; }
  else                                 { bias='neutral';     biasIcon='⚖️'; biasLbl='中性'; }
  return { buy, sell, triggered, total, broken, waiting, partial, expired, score, bias, biasIcon, biasLbl };
}

// ── Status visualisation ──────────────────────────────────
const STATUS_META = {
  trigger:   {icon:'🎯', lbl:'觸發',   col:'var(--green)',  bg:'rgba(74,222,128,.15)'},
  partial:   {icon:'⚠️', lbl:'部分',   col:'var(--orange)', bg:'rgba(251,146,60,.12)'},
  broken:    {icon:'⚠️', lbl:'破位',   col:'var(--red)',    bg:'rgba(248,113,113,.12)'},
  expired:   {icon:'❌', lbl:'失效',   col:'var(--tlo)',    bg:'rgba(90,106,130,.10)'},
  wait:      {icon:'⏳', lbl:'等待',   col:'var(--blue)',   bg:'rgba(96,165,250,.08)'},
  'no-data': {icon:'…',  lbl:'待載',   col:'var(--tf)',     bg:'rgba(45,58,82,.30)'},
  error:     {icon:'⚠',  lbl:'錯誤',   col:'var(--red)',    bg:'rgba(248,113,113,.18)'},
};
const BIAS_META = {
  'strong-bull': {col:'var(--green)', bg:'rgba(74,222,128,.18)'},
  'bull':        {col:'var(--green)', bg:'rgba(74,222,128,.10)'},
  'observing':   {col:'var(--blue)',  bg:'rgba(96,165,250,.08)'},
  'neutral':     {col:'var(--tlo)',   bg:'rgba(90,106,130,.10)'},
  'conflict':    {col:'var(--orange)',bg:'rgba(251,146,60,.12)'},
  'bear':        {col:'var(--red)',   bg:'rgba(248,113,113,.10)'},
  'strong-bear': {col:'var(--red)',   bg:'rgba(248,113,113,.18)'},
  'caution':     {col:'var(--orange)',bg:'rgba(251,146,60,.15)'},
  'empty':       {col:'var(--tf)',    bg:'transparent'},
};

// ── Render: WATCH tab ──────────────────────────────────────
function renderWatch() {
  // Auto-refresh signals for the current symbol's watch
  const code = S.sym?.toUpperCase().trim();
  if (code && S.watches[code]) refreshSignalsForStock(S.watches[code]);

  let h = `<div class="stat-hdr">價位觀察清單 · ${Object.keys(S.watches || {}).length} 檔</div>`;
  h += renderWatchListBody();
  h += renderWatchForm();
  h += renderStrategyPlaybook();
  h += '<div style="padding:14px 12px 18px;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.7">⚠ 訊號僅供參考。多訊號共振只提升勝率，不保證獲利。資金管理 > 選股。</div>';
  return h;
}

function renderWatchListBody() {
  const codes = Object.keys(S.watches || {});
  if (codes.length === 0) {
    return '<div style="padding:18px 14px;font-family:monospace;font-size:10px;color:var(--tlo);text-align:center;line-height:1.8">尚無觀察股<br><span style="font-size:9px;color:var(--tf)">↓ 在下方表單套用劇本或加單一訊號</span></div>';
  }
  let h = '';
  for (const code of codes) h += renderStockCard(S.watches[code]);
  return h;
}

function renderStockCard(w) {
  const isActive = w.sym === S.sym?.toUpperCase().trim();
  const conf = computeConfluence(w);
  const biasM = BIAS_META[conf.bias] || BIAS_META.neutral;
  const lastPrice = isActive ? S.data?.candles?.[S.data.candles.length-1]?.close
                              : (w.signals[0]?.lastEval?.price);

  let h = `<div style="border-bottom:2px solid var(--border);background:${isActive?'var(--gold-s)':'transparent'}">`;

  // ── Card header (clickable to load) ──
  h += `<div data-act="goto-watch" data-sym="${w.sym}" data-mkt="${w.mkt || 'TW'}"
       style="display:flex;justify-content:space-between;align-items:center;padding:9px 12px;cursor:pointer;gap:6px"
       title="點擊載入 ${w.sym} 圖表">
    <div style="display:flex;align-items:baseline;gap:8px;min-width:0;flex:1">
      <span style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:${isActive?'var(--gold)':'var(--thi)'};letter-spacing:.5px">${w.sym}</span>
      <span style="font-family:monospace;font-size:9.5px;color:var(--tlo)">${lastPrice != null ? lastPrice.toFixed(2) : '—'}</span>
    </div>
    <div style="display:flex;align-items:center;gap:5px">
      <span style="font-family:monospace;font-size:9.5px;font-weight:700;padding:2px 7px;border-radius:3px;background:${biasM.bg};color:${biasM.col};white-space:nowrap">${conf.biasIcon} ${conf.biasLbl}</span>
      <span data-act="remove-stock" data-sym="${w.sym}" title="移除整檔" style="color:var(--tf);font-size:13px;padding:0 4px;cursor:pointer;border-radius:3px;font-weight:700">×</span>
    </div>
  </div>`;

  // ── Signal rows ──
  for (const sig of w.signals) {
    h += renderSignalRow(w, sig);
  }

  // ── Per-stock notes ──
  if (w.notes) {
    h += `<div style="padding:6px 14px;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.5;font-style:italic;background:var(--bg)">📝 ${esc(w.notes)}</div>`;
  }

  // ── Add-signal-to-this-stock button ──
  h += `<div style="padding:6px 12px 10px;background:var(--bg)">
    <button data-act="quick-add" data-sym="${w.sym}" style="width:100%;padding:5px;background:transparent;border:1px dashed var(--border);border-radius:4px;color:var(--tlo);font-family:monospace;font-size:9px;cursor:pointer;letter-spacing:.5px">+ 為 ${w.sym} 加訊號</button>
  </div>`;

  h += `</div>`;
  return h;
}

function renderSignalRow(stockWatch, sig) {
  const strat = STRATEGIES.find(s => s.key === sig.strategy);
  if (!strat) return '';
  const e = sig.lastEval || {status:'no-data', detail:'點該股載入'};
  const meta = STATUS_META[e.status] || STATUS_META['no-data'];
  // Show param summary for clarity (e.g., "回測 SMA60 ±2%" or "自訂買進 2000")
  let paramHint = '';
  if (sig.strategy === 'custom_buy' || sig.strategy === 'custom_sell') {
    paramHint = ` @ ${num(sig.params?.target)?.toFixed(2) || '?'}`;
  } else if (sig.params?.tolerance) {
    paramHint = ` ±${sig.params.tolerance}%`;
  } else if (sig.params?.days) {
    paramHint = ` ${sig.params.days}日`;
  }

  return `<div style="padding:7px 14px 7px 18px;border-top:1px solid var(--bg3);background:${meta.bg}">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
      <span style="font-family:monospace;font-size:10px;font-weight:600;color:var(--thi)">${strat.icon} ${esc(strat.lbl)}${paramHint}<span class="info-i" data-info="strat:${strat.key}" title="此策略說明">i</span></span>
      <div style="display:flex;align-items:center;gap:6px">
        <span style="font-family:monospace;font-size:9px;font-weight:700;color:${meta.col};white-space:nowrap">${meta.icon} ${meta.lbl}</span>
        <span data-act="remove-signal" data-sym="${stockWatch.sym}" data-sigid="${sig.id}" title="移除此訊號" style="color:var(--tf);font-size:11px;padding:0 3px;cursor:pointer;border-radius:3px">×</span>
      </div>
    </div>
    <div style="font-family:monospace;font-size:8.5px;color:var(--tlo);margin-top:2px;line-height:1.5">${esc(e.detail)}</div>
  </div>`;
}

// ── Form: add new watch (preset or single) ─────────────────
function renderWatchForm() {
  const mode = S.watchFormMode || 'preset';

  let h = '<div class="stat-sect">新增觀察 / 加訊號</div>';

  // Mode tabs
  h += `<div style="display:flex;padding:6px 12px 0;gap:4px">
    <button data-act="set-mode-preset" style="flex:1;padding:5px;background:${mode==='preset'?'var(--gold-s)':'transparent'};border:1px solid ${mode==='preset'?'var(--gold-m)':'var(--border)'};border-radius:4px;color:${mode==='preset'?'var(--gold)':'var(--tlo)'};font-family:monospace;font-size:9.5px;font-weight:${mode==='preset'?'700':'400'};cursor:pointer">📋 套用劇本（推薦）</button>
    <button data-act="set-mode-single" style="flex:1;padding:5px;background:${mode==='single'?'var(--gold-s)':'transparent'};border:1px solid ${mode==='single'?'var(--gold-m)':'var(--border)'};border-radius:4px;color:${mode==='single'?'var(--gold)':'var(--tlo)'};font-family:monospace;font-size:9.5px;font-weight:${mode==='single'?'700':'400'};cursor:pointer">🔧 單一策略</button>
  </div>`;

  h += `<div style="padding:8px 12px;display:flex;flex-direction:column;gap:6px">
    <input id="watch-sym" type="text" placeholder="股票代號（如 2330 / AAPL）" value="${S.sym || ''}" style="${inp()};text-transform:uppercase">`;

  if (mode === 'preset') {
    h += renderPresetForm();
  } else {
    h += renderSingleForm();
  }

  h += `<textarea id="watch-notes" placeholder="筆記（為何看上、預期目標…，可空）" style="${inp()};resize:vertical;min-height:42px;line-height:1.5"></textarea>
    <button data-act="${mode==='preset'?'apply-preset':'add-single'}" style="padding:9px;background:var(--gold);border:none;border-radius:4px;color:#060A12;font-family:monospace;font-size:11px;font-weight:700;cursor:pointer;letter-spacing:1px;margin-top:4px">${mode==='preset'?'＋ 套用劇本':'＋ 加入訊號'}</button>
    <div id="watch-toast" style="display:none;padding:6px;background:rgba(74,222,128,.12);border:1px solid var(--gbdr);border-radius:4px;color:var(--green);font-family:monospace;font-size:9.5px;text-align:center;letter-spacing:.5px"></div>
  </div>`;
  return h;
}

function renderPresetForm() {
  const key = S.watchFormPreset || 'classic_pullback';
  const preset = PRESETS.find(p => p.key === key) || PRESETS[0];
  let h = `<div style="display:flex;align-items:center;gap:6px">
    <select id="watch-preset" onchange="onWatchPresetChange()" style="${inp()};cursor:pointer;flex:1">
      ${PRESETS.map(p => `<option value="${p.key}" ${p.key===key?'selected':''}>${p.icon} ${p.lbl}</option>`).join('')}
    </select>
    <span class="info-i-lg" data-info="preset:${preset.key}" title="點看詳細劇本說明">i</span>
  </div>`;

  h += `<div style="padding:8px 9px;background:var(--bg);border-radius:4px;line-height:1.7">
    <div style="font-family:monospace;font-size:9.5px;color:var(--text)">${esc(preset.desc)}</div>
    <div style="font-family:monospace;font-size:9px;color:var(--tlo);margin-top:4px">適用：${esc(preset.when)}</div>
    <div style="font-family:monospace;font-size:9px;color:var(--blue);margin-top:5px">包含 ${preset.signals.length} 個訊號：${preset.signals.map(s => {
      const st = STRATEGIES.find(x=>x.key===s.strategy);
      return st ? `<span data-info="strat:${st.key}" style="cursor:pointer" title="點看 ${st.lbl} 說明">${st.icon}</span>` : '';
    }).join(' ')}</div>
  </div>`;

  // Custom price inputs if preset needs them
  if (preset.customPriceMode === 'sell') {
    h += `<input id="watch-preset-price" type="number" step="0.01" placeholder="${esc(preset.customPriceLbl)}" style="${inp('var(--green)')}">`;
  } else if (preset.customPriceMode === 'both') {
    h += `<input id="watch-preset-price"  type="number" step="0.01" placeholder="${esc(preset.customPriceLbl)}"  style="${inp('var(--green)')}">`;
    h += `<input id="watch-preset-price2" type="number" step="0.01" placeholder="${esc(preset.customPriceLbl2)}" style="${inp('var(--red)')}">`;
  }
  return h;
}

function renderSingleForm() {
  const stratKey = S.watchFormStrategy || 'sma60_pullback';
  const strat = STRATEGIES.find(s => s.key === stratKey) || STRATEGIES[0];
  let h = `<div style="display:flex;align-items:center;gap:6px">
    <select id="watch-strat" onchange="onWatchStratChange()" style="${inp()};cursor:pointer;flex:1">
      ${STRATEGIES.map(s => `<option value="${s.key}" ${s.key===stratKey?'selected':''}>${s.icon} ${s.lbl}　${s.difficulty}</option>`).join('')}
    </select>
    <span class="info-i-lg" id="watch-strat-info" data-info="strat:${strat.key}" title="點看策略詳細">i</span>
  </div>`;
  h += `<div id="watch-strat-desc" style="padding:6px 8px;background:var(--bg);border-radius:4px;font-family:monospace;font-size:9.5px;color:var(--text);line-height:1.7">${esc(strat.desc)}</div>`;
  h += `<div id="watch-strat-params" style="display:flex;flex-direction:column;gap:5px">${renderParamFields(strat)}</div>`;
  return h;
}

function renderParamFields(strat) {
  if (!strat.paramFields?.length) {
    return '<div style="padding:4px;font-family:monospace;font-size:9px;color:var(--tlo);font-style:italic">（此策略無需設定參數）</div>';
  }
  return strat.paramFields.map(f =>
    `<div style="display:flex;flex-direction:column;gap:2px">
      <label style="font-family:monospace;font-size:8.5px;color:var(--tlo);letter-spacing:.5px">${esc(f.lbl)} <span style="color:var(--tf);font-weight:400">— ${esc(f.hint)}</span></label>
      <input id="watch-param-${f.key}" type="${f.type || 'text'}" value="${f.default !== '' ? f.default : ''}"
        ${f.min != null ? `min="${f.min}"` : ''} ${f.max != null ? `max="${f.max}"` : ''} ${f.step != null ? `step="${f.step}"` : ''}
        style="${inp()}">
    </div>`).join('');
}

function renderStrategyPlaybook() {
  let h = `<div class="stat-sect" id="play-hdr" data-act="toggle-play" style="cursor:pointer;user-select:none">▼ 策略劇本說明（點開看詳細）</div>`;
  h += '<div id="play-body" style="display:none">';
  // Group by type for cleaner reading
  const groups = [
    {key:'trend',      lbl:'📈 趨勢類'},
    {key:'momentum',   lbl:'⚡ 動能類'},
    {key:'volatility', lbl:'📊 波動類'},
    {key:'price',      lbl:'🎯 價格類'},
  ];
  for (const g of groups) {
    const items = STRATEGIES.filter(s => s.type === g.key);
    if (items.length === 0) continue;
    h += `<div style="padding:7px 12px 4px;background:var(--bg);font-family:monospace;font-size:9px;color:var(--gold);letter-spacing:1px">${g.lbl}</div>`;
    for (const s of items) {
      h += `<div style="padding:9px 12px;border-bottom:1px solid var(--border)">
        <div style="font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:700;color:var(--gold);margin-bottom:4px">${s.icon} ${esc(s.lbl)}　<span style="color:var(--tlo);font-size:9px;font-weight:400">${esc(s.difficulty)}</span></div>
        <div style="font-family:monospace;font-size:9.5px;color:var(--text);margin-bottom:5px;line-height:1.7">${esc(s.desc)}</div>
        <div style="font-family:monospace;font-size:9px;color:var(--blue);margin-bottom:4px;line-height:1.7"><b>原理</b>　${esc(s.why)}</div>
        <div style="font-family:monospace;font-size:9px;color:var(--tlo);margin-bottom:4px;line-height:1.7;white-space:pre-line"><b>適用</b>　${esc(s.when)}</div>
        <div style="font-family:monospace;font-size:9px;color:var(--green);line-height:1.7"><b>觸發行動</b>　${esc(s.action)}</div>
      </div>`;
    }
  }
  h += '</div>';
  return h;
}

// ── Helpers ─────────────────────────────────────────────────
function inp(borderC) {
  return `background:var(--bg3);border:1px solid ${borderC || 'var(--border)'};border-radius:4px;padding:6px 9px;color:${borderC || 'var(--thi)'};font-family:monospace;font-size:11px;outline:none`;
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

// ── Wire up clicks & form ──────────────────────────────────
function attachWatch() {
  const panel = document.getElementById('rpanel');
  if (!panel) return;
  if (panel._watchListenerAttached) return;
  panel._watchListenerAttached = true;

  panel.addEventListener('click', function (ev) {
    const btn = ev.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;

    if (act === 'apply-preset')   { ev.preventDefault(); submitPreset(); }
    if (act === 'add-single')     { ev.preventDefault(); submitSingleSignal(); }
    if (act === 'set-mode-preset'){ ev.preventDefault(); S.watchFormMode='preset'; renderRpanel(); }
    if (act === 'set-mode-single'){ ev.preventDefault(); S.watchFormMode='single'; renderRpanel(); }
    if (act === 'remove-signal')  {
      ev.preventDefault(); ev.stopPropagation();
      const sym = btn.dataset.sym, sigId = btn.dataset.sigid;
      if (sym && sigId && confirm(`移除這個訊號？`)) removeSignal(sym, sigId);
    }
    if (act === 'remove-stock')   {
      ev.preventDefault(); ev.stopPropagation();
      const sym = btn.dataset.sym;
      if (sym && confirm(`移除 ${sym} 全部訊號？`)) removeStockWatch(sym);
    }
    if (act === 'goto-watch')     {
      ev.preventDefault();
      const sym = btn.dataset.sym, mkt = btn.dataset.mkt || S.mkt || 'TW';
      if (sym && sym !== S.sym && typeof loadSym === 'function') loadSym(sym, mkt);
    }
    if (act === 'quick-add')      {
      ev.preventDefault();
      // Pre-fill the form with this sym, then focus
      const symInput = document.getElementById('watch-sym');
      if (symInput) { symInput.value = btn.dataset.sym; symInput.focus(); }
    }
    if (act === 'toggle-play')    {
      ev.preventDefault();
      const body = document.getElementById('play-body'), hdr = document.getElementById('play-hdr');
      if (body) {
        const open = body.style.display !== 'none';
        body.style.display = open ? 'none' : 'block';
        if (hdr) hdr.textContent = (open ? '▼' : '▲') + hdr.textContent.slice(1);
      }
    }
  });
}

function onWatchPresetChange() {
  S.watchFormPreset = document.getElementById('watch-preset').value;
  renderRpanel();
}
function onWatchStratChange() {
  S.watchFormStrategy = document.getElementById('watch-strat').value;
  const strat = STRATEGIES.find(s => s.key === S.watchFormStrategy);
  if (!strat) return;
  document.getElementById('watch-strat-desc').textContent = strat.desc;
  document.getElementById('watch-strat-params').innerHTML = renderParamFields(strat);
  const info = document.getElementById('watch-strat-info');
  if (info) info.dataset.info = 'strat:' + strat.key;
}

function submitPreset() {
  const sym = document.getElementById('watch-sym').value.trim().toUpperCase();
  if (!sym) { alert('請填股票代號'); return; }
  const presetKey = document.getElementById('watch-preset').value;
  const preset = PRESETS.find(p => p.key === presetKey);
  const notes = document.getElementById('watch-notes').value;
  const p1 = document.getElementById('watch-preset-price')?.value;
  const p2 = document.getElementById('watch-preset-price2')?.value;
  const ok = applyPreset(sym, presetKey, p1 ? parseFloat(p1) : null, p2 ? parseFloat(p2) : null, S.mkt || 'TW');
  if (!ok) return;
  if (notes && S.watches[sym]) {
    S.watches[sym].notes = (S.watches[sym].notes ? S.watches[sym].notes + ' / ' : '') + notes;
    saveWatches();
  }
  showWatchToast(`✓ ${sym} 已套用「${preset.lbl}」`);
  if (S.tab === 'watch') renderRpanel();
}

function submitSingleSignal() {
  const sym = document.getElementById('watch-sym').value.trim().toUpperCase();
  if (!sym) { alert('請填股票代號'); return; }
  const stratKey = document.getElementById('watch-strat').value;
  const strat = STRATEGIES.find(s => s.key === stratKey);
  const notes = document.getElementById('watch-notes').value;
  const params = {};
  for (const f of strat.paramFields) {
    const el = document.getElementById(`watch-param-${f.key}`);
    if (!el) continue;
    const raw = el.value;
    if (raw === '' || raw == null) continue;
    params[f.key] = f.type === 'number' ? parseFloat(raw) : raw;
  }
  const ok = addSignal(sym, stratKey, params, S.mkt || 'TW');
  if (!ok) return;
  if (notes && S.watches[sym]) {
    S.watches[sym].notes = (S.watches[sym].notes ? S.watches[sym].notes + ' / ' : '') + notes;
    saveWatches();
  }
  showWatchToast(`✓ ${sym} 已加入「${strat.lbl}」`);
  if (S.tab === 'watch') renderRpanel();
}

function showWatchToast(msg) {
  const t = document.getElementById('watch-toast');
  if (!t) return;
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(() => { if (t) t.style.display = 'none'; }, 2200);
}

// ── Sym-loaded hook: refresh current symbol's signals ──────
window.addEventListener('symLoaded', function () {
  try {
    const code = S.sym?.toUpperCase().trim();
    if (code && S.watches[code]) refreshSignalsForStock(S.watches[code]);
    if (S.tab === 'watch') {
      const el = document.getElementById('rpanel');
      if (el) { el.innerHTML = renderWatch(); attachWatch(); }
    }
  } catch (e) { console.error('[v2-watch] symLoaded handler:', e); }
});

// Polling fallback
(function pollWatchTab() {
  let _last = null;
  setInterval(() => {
    if (S.tab !== 'watch') return;
    if (S.sym !== _last) {
      _last = S.sym;
      const el = document.getElementById('rpanel');
      if (el) {
        try { el.innerHTML = renderWatch(); attachWatch(); }
        catch (e) { console.error('[v2-watch] poll re-render:', e); }
      }
    }
  }, 600);
})();

// ── Expose to window ───────────────────────────────────────
window.STRATEGIES         = STRATEGIES;
window.PRESETS            = PRESETS;
window.addSignal          = addSignal;
window.applyPreset        = applyPreset;
window.removeSignal       = removeSignal;
window.removeStockWatch   = removeStockWatch;
window.evaluateSignal     = evaluateSignal;
window.computeConfluence  = computeConfluence;
window.renderWatch        = renderWatch;
window.attachWatch        = attachWatch;
window.onWatchStratChange = onWatchStratChange;
window.onWatchPresetChange = onWatchPresetChange;
window.submitPreset       = submitPreset;
window.submitSingleSignal = submitSingleSignal;

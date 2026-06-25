// ============================================================
// Stock Terminal v2.0 — Position Management & Signal Engine
// ------------------------------------------------------------
// Persists per-symbol position to localStorage and runs a rule-
// based technical-signal engine each time you load a symbol.
//
// Loaded by stock_terminal_v2.html.  Depends on v1's S state.
// ============================================================

const LS_KEY_POS = 'stock_terminal_positions_v2';

// ── State bootstrap ─────────────────────────────────────────
// Note: v1 declares `let S = {...}` — top-level `let` is script-scope global
// (accessible by reference) but NOT attached to `window`. So we test by ref.
(function bootPositions() {
  if (typeof S === 'undefined') {
    console.error('[v2] global S (state object) missing — v1 not loaded?');
    return;
  }
  try {
    const stored = localStorage.getItem(LS_KEY_POS);
    S.positions = stored ? JSON.parse(stored) : {};
  } catch { S.positions = {}; }
  // Defensive: ensure positions is a plain object
  if (typeof S.positions !== 'object' || S.positions === null || Array.isArray(S.positions)) {
    S.positions = {};
  }
  S.prevInd = null;
  console.log('[v2] bootPositions OK — loaded', Object.keys(S.positions).length, 'position(s)');
})();

function savePositions() {
  if (!S.positions) S.positions = {};
  localStorage.setItem(LS_KEY_POS, JSON.stringify(S.positions));
}
function getPosition(sym) {
  if (!S.positions) S.positions = {};
  return S.positions[sym || S.sym] || null;
}
function setPosition(entry, shares, target, stop, notes) {
  if (typeof S === 'undefined') { alert('v2 未正確載入，請 Ctrl+Shift+R 重新整理'); return false; }
  if (!S.positions) S.positions = {};   // defensive — bootPositions may have bailed
  if (!S.sym) { alert('尚未選擇股票'); return false; }
  const e = parseFloat(entry), s = parseInt(shares, 10);
  if (!isFinite(e) || e <= 0) { alert('進場價必須是正數'); return false; }
  if (!isFinite(s) || s <= 0) { alert('股數必須是正整數'); return false; }
  const lastClose = S.data?.candles?.[S.data.candles.length - 1]?.close ?? null;
  S.positions[S.sym] = {
    entry:  e,
    shares: s,
    target: parseFloat(target) || null,
    stop:   parseFloat(stop)   || null,
    notes:  notes || '',
    mkt:    S.mkt || 'TW',                     // remember market so we can re-load later
    lastPrice: lastClose,                      // snapshot current price
    lastUpdate: lastClose != null ? Date.now() : null,
    addedAt: S.positions[S.sym]?.addedAt || Date.now(),
    updatedAt: Date.now(),
  };
  savePositions();
  console.log('[v2] saved position:', S.sym, S.positions[S.sym]);
  // Re-render after a tick so the toast is visible briefly before the form refreshes
  setTimeout(() => {
    if (S.tab === 'position') renderRpanel();
    if (S.tab === 'stats')    renderRpanel();
  }, 1800);
  return true;
}
function clearPosition() {
  if (!S.sym) return;
  if (!S.positions) S.positions = {};
  delete S.positions[S.sym];
  savePositions();
  if (S.tab === 'position') renderRpanel();
}

// Number coercion helpers — v1's worker stringifies all indicator values via .toFixed(),
// so S.ind.rsi14 is "76.3" (string), comparisons work via coercion but .toFixed() throws.
function num(v) { if (v == null || v === '-' || v === '--') return null; const n = Number(v); return isFinite(n) ? n : null; }
function fx(v, d) { const n = num(v); return n == null ? '--' : n.toFixed(d == null ? 2 : d); }

// ── Signal engine: rule-based technical recommendations ─────
function generateSignals() {
  const signals = [];
  if (!S.ind || !S.data || !S.data.candles || S.data.candles.length < 2) return signals;

  const candles = S.data.candles;
  const last = candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  const c = last.close;
  const pc = prev.close;
  // Numericize indicator values up-front — every check below uses numbers.
  const raw = S.ind;
  const ind = {
    rsi14:    num(raw.rsi14),
    K:        num(raw.K),
    D:        num(raw.D),
    macd:     num(raw.macd),
    signal:   num(raw.macdSig),   // v1's worker key is macdSig, not signal
    macdHist: num(raw.macdHist),
    sma5:     num(raw.sma5),
    sma20:    num(raw.sma20),
    sma60:    num(raw.sma60),
    bbU:      num(raw.bbU),
    bbL:      num(raw.bbL),
    atr14:    num(raw.atr14),
    volRatio: num(raw.volRatio),
    d2SMA20:  num(raw.d2SMA20),
  };
  const pos = getPosition();

  const push = (level, txt, detail, action) => signals.push({level, txt, detail, action});

  // ─── A. Moving-average crosses (trend signals) ───
  if (ind.sma60 != null) {
    if (pc >= ind.sma60 && c < ind.sma60) {
      push('sell', '破 60 日均線',
        `價 ${c.toFixed(2)} 跌破 SMA60 ${ind.sma60.toFixed(2)}，中線趨勢轉空`,
        '建議減碼 1/2 或全部出場，待重新站回再評估');
    } else if (pc <= ind.sma60 && c > ind.sma60) {
      push('buy', '站上 60 日均線',
        `價 ${c.toFixed(2)} 突破 SMA60 ${ind.sma60.toFixed(2)}，中線轉多`,
        '建議分批進場 1/3 → 1/3 → 1/3，量增確認再加碼');
    } else if (c < ind.sma60 * 0.97) {
      push('caution', '價低於 SMA60 超過 3%',
        `當前 ${c.toFixed(2)} 低於 SMA60 ${ind.sma60.toFixed(2)} 約 ${((1-c/ind.sma60)*100).toFixed(1)}%`,
        '中線弱勢，反彈不過 SMA60 維持空方');
    }
  }
  if (ind.sma20 != null) {
    if (pc >= ind.sma20 && c < ind.sma20) {
      push('caution', '破 20 日均線',
        `短線轉弱，價 ${c.toFixed(2)} 跌破 SMA20 ${ind.sma20.toFixed(2)}`,
        '若帶量需警覺，可先減碼 1/3 觀察 SMA60 是否守住');
    } else if (pc <= ind.sma20 && c > ind.sma20) {
      push('info', '站上 20 日均線',
        `短線轉強，價 ${c.toFixed(2)} 突破 SMA20 ${ind.sma20.toFixed(2)}`,
        '可小量試單，配合 SMA60 同向再加碼');
    }
  }
  // 黃金/死亡排列
  if (ind.sma5 != null && ind.sma20 != null && ind.sma60 != null) {
    if (ind.sma5 > ind.sma20 && ind.sma20 > ind.sma60) {
      push('buy', '均線多頭排列',
        `SMA5(${ind.sma5.toFixed(2)}) > SMA20(${ind.sma20.toFixed(2)}) > SMA60(${ind.sma60.toFixed(2)})`,
        '強勢多頭結構，可持有或拉回 SMA20 加碼');
    } else if (ind.sma5 < ind.sma20 && ind.sma20 < ind.sma60) {
      push('sell', '均線空頭排列',
        `SMA5(${ind.sma5.toFixed(2)}) < SMA20(${ind.sma20.toFixed(2)}) < SMA60(${ind.sma60.toFixed(2)})`,
        '空方結構，反彈不破 SMA20 維持減碼');
    }
  }

  // ─── B. RSI extremes ───
  if (ind.rsi14 != null) {
    if (ind.rsi14 > 75) {
      push('caution', `RSI 過熱 ${ind.rsi14.toFixed(0)}`,
        '14 日 RSI 高於 75，短線超買區',
        '考慮分批停利 1/3，或上調移動停損');
    } else if (ind.rsi14 < 25) {
      push('buy', `RSI 超賣 ${ind.rsi14.toFixed(0)}`,
        '14 日 RSI 低於 25，短線超賣區',
        '可分批承接 1/3，配合 KD/MACD 翻多再加碼');
    }
  }

  // ─── C. KD cross ───
  if (ind.K != null && ind.D != null) {
    if (ind.K > ind.D && ind.K < 25 && ind.D < 25) {
      push('buy', 'KD 低檔黃金交叉',
        `K(${ind.K.toFixed(0)}) > D(${ind.D.toFixed(0)})，雙線在 25 以下`,
        '短線反彈機會高，可加碼 1/3');
    } else if (ind.K < ind.D && ind.K > 75 && ind.D > 75) {
      push('sell', 'KD 高檔死亡交叉',
        `K(${ind.K.toFixed(0)}) < D(${ind.D.toFixed(0)})，雙線在 75 以上`,
        '短線回檔風險高，建議減碼 1/3');
    }
  }

  // ─── D. MACD Histogram ───
  if (ind.macdHist != null && ind.macd != null && ind.signal != null) {
    if (ind.macdHist > 0 && ind.macd > 0 && ind.macd > ind.signal) {
      // bullish momentum confirmed
      if (S.prevInd && S.prevInd.macdHist != null && S.prevInd.macdHist < 0) {
        push('buy', 'MACD 動能由空轉多',
          `Hist ${ind.macdHist.toFixed(2)} 由負轉正，MACD ${ind.macd.toFixed(2)} > Signal ${ind.signal.toFixed(2)}`,
          '動能訊號確認，可順勢加碼');
      }
    } else if (ind.macdHist < 0 && ind.macd < 0 && ind.macd < ind.signal) {
      if (S.prevInd && S.prevInd.macdHist != null && S.prevInd.macdHist > 0) {
        push('sell', 'MACD 動能由多轉空',
          `Hist ${ind.macdHist.toFixed(2)} 由正轉負`,
          '動能轉弱，減碼以待趨勢明朗');
      }
    }
  }

  // ─── E. Bollinger Bands ───
  if (ind.bbU != null && ind.bbL != null) {
    if (c > ind.bbU && ind.rsi14 != null && ind.rsi14 > 70) {
      push('caution', '觸 BB 上軌 + RSI 過熱',
        `價 ${c.toFixed(2)} 突破布林上軌 ${ind.bbU.toFixed(2)}，RSI ${ind.rsi14.toFixed(0)}`,
        '雙重超買訊號，建議分批停利');
    } else if (c < ind.bbL && ind.rsi14 != null && ind.rsi14 < 30) {
      push('buy', '觸 BB 下軌 + RSI 超賣',
        `價 ${c.toFixed(2)} 跌破布林下軌 ${ind.bbL.toFixed(2)}，RSI ${ind.rsi14.toFixed(0)}`,
        '雙重超賣訊號，反彈機率高');
    }
  }

  // ─── F. Volume confirmation ───
  if (ind.volRatio != null && ind.volRatio > 2) {
    const dirHint = c > pc ? '量增價漲' : '量增價跌';
    const lvl = c > pc ? 'info' : 'caution';
    push(lvl, `量能 ${ind.volRatio.toFixed(1)}x 放大`,
      `${dirHint}，今日量為 20 日均量 ${ind.volRatio.toFixed(1)} 倍`,
      c > pc ? '突破訊號可信度高' : '量增收黑警示出貨可能');
  }

  // ─── G. Position-based signals (need an open position) ───
  if (pos && pos.entry) {
    const pnl = (c - pos.entry) / pos.entry * 100;
    const dollarPnl = (c - pos.entry) * pos.shares;

    if (pos.target && c >= pos.target) {
      push('sell', `達成停利 ${pos.target.toFixed(2)}`,
        `當前 ${c.toFixed(2)} 已達/超過設定停利`,
        '紀律出場 1/2，剩餘以移動停損保護');
    }
    if (pos.stop && c <= pos.stop) {
      push('sell', `觸發停損 ${pos.stop.toFixed(2)}`,
        `當前 ${c.toFixed(2)} 已破停損`,
        '紀律出場全部部位，不檢討、不留戀');
    }
    if (pos.stop && c > pos.stop) {
      const dist = (c - pos.stop) / c * 100;
      if (dist < 3) {
        push('caution', `距停損僅 ${dist.toFixed(1)}%`,
          `當前 ${c.toFixed(2)} 接近停損 ${pos.stop.toFixed(2)}`,
          '心理準備出場，避免凹單');
      }
    }
    if (!pos.target && pnl >= 20) {
      push('info', `浮盈 ${pnl.toFixed(1)}% (${dollarPnl >= 0 ? '+' : ''}${Math.round(dollarPnl).toLocaleString()})`,
        '已超過 20% 報酬',
        '可考慮減碼 1/3 鎖利，或設移動停損');
    }
    if (pnl <= -10) {
      push('caution', `浮虧 ${pnl.toFixed(1)}%`,
        `成本 ${pos.entry.toFixed(2)} → 現價 ${c.toFixed(2)}`,
        '重新檢視進場邏輯，破壞則停損；理由仍在可加碼攤平但要設新停損');
    }
  }

  // ─── H. ETF Flow confluence (TW only) ───
  if (S.etfDelta && S.mkt === 'TW' && typeof getEtfFlowForStock === 'function') {
    const flow = getEtfFlowForStock(S.sym);
    if (flow && flow.addCount >= 3) {
      push('buy', `${flow.addCount} 檔主動 ETF 同步買進`,
        '主動 ETF 經理人共識偏多',
        '法人籌碼背書，可提高加碼信心');
    } else if (flow && flow.rmCount >= 3) {
      push('sell', `${flow.rmCount} 檔主動 ETF 同步賣出`,
        '主動 ETF 經理人共識偏空',
        '法人籌碼鬆動，建議謹慎或減碼');
    }
    if (flow && flow.chgSum && Math.abs(flow.chgSum) >= 3) {
      const lvl = flow.chgSum > 0 ? 'info' : 'caution';
      const dir = flow.chgSum > 0 ? '加碼' : '減碼';
      push(lvl, `ETF 整體權重${dir} ${Math.abs(flow.chgSum).toFixed(1)}%`,
        `主動 ETF 對該股權重變化合計 ${flow.chgSum > 0 ? '+' : ''}${flow.chgSum.toFixed(2)}%`,
        '權重變化幅度大，留意籌碼動向');
    }
  }

  // Sort: buy first, then sell, then caution, then info
  const order = {buy:0, sell:1, caution:2, info:3};
  signals.sort((a,b) => order[a.level] - order[b.level]);

  // Store this snapshot for cross detection next time
  S.prevInd = { ...ind };

  return signals;
}

// ── Render: position list (all held positions, jump on click) ──
function renderPositionList() {
  const codes = Object.keys(S.positions || {});
  if (codes.length === 0) return '';

  // Aggregate portfolio totals
  let totalCost = 0, totalValue = 0, totalPnl = 0, knownCount = 0;
  for (const code of codes) {
    const p = S.positions[code];
    const ref = code === S.sym
      ? (S.data?.candles?.[S.data.candles.length - 1]?.close ?? p.lastPrice)
      : p.lastPrice;
    totalCost += p.entry * p.shares;
    if (ref != null) {
      totalValue += ref * p.shares;
      totalPnl   += (ref - p.entry) * p.shares;
      knownCount++;
    }
  }
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost * 100) : 0;
  const pnlCol = totalPnl >= 0 ? 'var(--green)' : 'var(--red)';

  let h = `<div class="stat-sect">持倉清單 · ${codes.length} 檔</div>`;

  // Portfolio summary row
  h += `<div style="padding:7px 12px;background:var(--bg);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px">
    <span style="color:var(--tlo)">總成本 / 市值</span>
    <span style="color:var(--thi)">${Math.round(totalCost).toLocaleString()} → ${knownCount ? Math.round(totalValue).toLocaleString() : '--'}</span>
  </div>
  <div style="padding:5px 12px 8px;background:var(--bg);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:10px">
    <span style="color:var(--tlo)">合計損益</span>
    <span style="color:${pnlCol};font-weight:700">${knownCount ? `${totalPnl >= 0 ? '+' : ''}${totalPnlPct.toFixed(2)}% (${totalPnl >= 0 ? '+' : ''}${Math.round(totalPnl).toLocaleString()})` : '部分價格未載入'}</span>
  </div>`;

  // Individual rows
  for (const code of codes) {
    const p = S.positions[code];
    const isActive = code === S.sym;
    const ref = isActive
      ? (S.data?.candles?.[S.data.candles.length - 1]?.close ?? p.lastPrice)
      : p.lastPrice;
    const pnlPct = ref != null ? ((ref - p.entry) / p.entry * 100) : null;
    const pnlCol = pnlPct == null ? 'var(--tlo)' : (pnlPct >= 0 ? 'var(--green)' : 'var(--red)');
    const lotsTxt = (p.shares % 1000 === 0) ? `${p.shares / 1000}張` : `${p.shares}股`;
    h += `<div data-act="goto-pos" data-sym="${code}" data-mkt="${p.mkt || 'TW'}"
       style="display:flex;justify-content:space-between;align-items:center;padding:7px 12px;border-bottom:1px solid var(--border);cursor:pointer;background:${isActive ? 'var(--gold-s)' : 'transparent'};transition:background .12s"
       onmouseover="if(!this.dataset.active)this.style.background='var(--bg3)'"
       onmouseout="this.style.background='${isActive ? 'var(--gold-s)' : 'transparent'}'"
       ${isActive ? 'data-active="1"' : ''}>
      <div style="display:flex;flex-direction:column;gap:2px;min-width:0">
        <span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;color:${isActive ? 'var(--gold)' : 'var(--thi)'};letter-spacing:.5px">${code}</span>
        <span style="font-family:'JetBrains Mono',monospace;font-size:8.5px;color:var(--tlo)">${lotsTxt} @ ${p.entry.toFixed(2)}</span>
      </div>
      <div style="text-align:right">
        <div style="font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:700;color:${pnlCol}">${pnlPct == null ? '—' : (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(1) + '%'}</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--tlo);margin-top:1px">${ref != null ? ref.toFixed(2) : '未載入'}</div>
      </div>
    </div>`;
  }
  return h;
}

// ── Render: POSITION tab ────────────────────────────────────
function renderPosition() {
  if (!S.sym) {
    // Even without a current symbol, still show the position list if any
    const listOnly = renderPositionList();
    if (listOnly) {
      return listOnly + '<div style="padding:14px;font-family:JetBrains Mono,monospace;font-size:10px;color:var(--tlo);text-align:center">點任一檔進入該股</div>';
    }
    return '<div style="padding:16px;font-family:JetBrains Mono,monospace;font-size:10px;color:var(--tlo)">尚未選擇個股</div>';
  }
  const pos = getPosition();
  const last = S.data && S.data.candles ? S.data.candles[S.data.candles.length - 1] : null;
  const c = last ? last.close : null;

  let h = renderPositionList();
  h += `<div class="stat-hdr">倉位管理 · ${S.sym}</div>`;

  // ── Current position block ──
  if (pos) {
    const pnl = c ? (c - pos.entry) / pos.entry * 100 : 0;
    const dPnl = c ? (c - pos.entry) * pos.shares : 0;
    const cost = pos.entry * pos.shares;
    const val  = c ? c * pos.shares : cost;
    const col  = pnl >= 0 ? 'var(--green)' : 'var(--red)';

    h += '<div class="stat-sect">當前持倉</div>';
    h += row('成本價', pos.entry.toFixed(2));
    h += row('持有股數', pos.shares.toLocaleString());
    h += row('現價', c ? c.toFixed(2) : '--');
    h += row('總成本', cost.toLocaleString(undefined, {maximumFractionDigits: 0}));
    h += row('目前市值', val.toLocaleString(undefined, {maximumFractionDigits: 0}));
    h += row('未實現損益',
      `<span style="color:${col}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}% (${dPnl >= 0 ? '+' : ''}${Math.round(dPnl).toLocaleString()})</span>`,
      true);
    if (pos.target) {
      const tpct = (pos.target - pos.entry) / pos.entry * 100;
      h += row('停利目標', `<span style="color:var(--green)">${pos.target.toFixed(2)} (${tpct >= 0 ? '+' : ''}${tpct.toFixed(1)}%)</span>`, true);
    }
    if (pos.stop) {
      const spct = (pos.stop - pos.entry) / pos.entry * 100;
      h += row('停損價', `<span style="color:var(--red)">${pos.stop.toFixed(2)} (${spct.toFixed(1)}%)</span>`, true);
    }
    if (pos.notes) {
      h += `<div class="stat-row" style="flex-direction:column;align-items:flex-start;gap:4px"><span class="stat-k">筆記</span><span style="font-size:9px;color:var(--text);line-height:1.5">${escapeHtml(pos.notes)}</span></div>`;
    }
    if (pos.addedAt) {
      const d = new Date(pos.addedAt);
      h += row('建倉日', `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`);
    }
    h += `<div style="padding:10px 12px"><button data-act="clear-pos" style="width:100%;padding:7px;background:transparent;border:1px solid var(--border);border-radius:4px;color:var(--red);font-family:monospace;font-size:10px;cursor:pointer">清除倉位</button></div>`;
  }

  // ── Position input form ──
  // 台股「1 張 = 1000 股」是慣用單位；美股直接以股為單位
  const isTW = S.mkt === 'TW';
  const unitLot = isTW;   // default to lots for TW
  const lotMult = unitLot ? 1000 : 1;
  const sharesDisplay = pos?.shares != null
    ? (unitLot ? pos.shares / lotMult : pos.shares)
    : '';

  h += `<div class="stat-sect">${pos ? '更新倉位' : '建立倉位'}</div>`;
  h += `<div style="padding:8px 12px;display:flex;flex-direction:column;gap:6px">
    <input id="pos-entry"  type="text" inputmode="decimal" autocomplete="off" placeholder="進場價" value="${pos?.entry ?? ''}"  style="${inpStyle()}">
    <div style="display:flex;gap:4px">
      <input id="pos-shares" type="text" inputmode="numeric" autocomplete="off" placeholder="${unitLot ? '張數' : '股數'}" value="${sharesDisplay}" style="${inpStyle()};flex:1">
      <select id="pos-unit" style="${inpStyle()};width:64px;cursor:pointer">
        <option value="lot" ${unitLot ? 'selected' : ''}>張</option>
        <option value="share" ${!unitLot ? 'selected' : ''}>股</option>
      </select>
    </div>
    <input id="pos-target" type="text" inputmode="decimal" autocomplete="off" placeholder="停利價（可空）" value="${pos?.target ?? ''}" style="${inpStyle('var(--green)')}">
    <input id="pos-stop"   type="text" inputmode="decimal" autocomplete="off" placeholder="停損價（可空）" value="${pos?.stop ?? ''}"   style="${inpStyle('var(--red)')}">
    <textarea id="pos-notes" placeholder="進場理由 / 筆記" style="${inpStyle()};resize:vertical;min-height:50px;line-height:1.5">${escapeHtml(pos?.notes || '')}</textarea>
    <button id="pos-save-btn" data-act="save-pos" style="padding:9px;background:var(--gold);border:none;border-radius:4px;color:#060A12;font-family:monospace;font-size:11px;font-weight:700;cursor:pointer;letter-spacing:1px;margin-top:4px">${pos ? '✓ 更新倉位' : '＋ 儲存倉位'}</button>
    <div id="pos-toast" style="display:none;padding:6px;background:rgba(74,222,128,.12);border:1px solid var(--gbdr);border-radius:4px;color:var(--green);font-family:monospace;font-size:9.5px;text-align:center;letter-spacing:.5px"></div>
  </div>`;

  // ── Signals ──
  const signals = generateSignals();
  h += `<div class="stat-sect">訊號建議${signals.length ? ` · ${signals.length}` : ''}</div>`;
  if (signals.length === 0) {
    h += '<div style="padding:14px;font-family:monospace;font-size:10px;color:var(--tlo);text-align:center">目前無重大訊號</div>';
  } else {
    const colorMap = {buy: 'var(--green)', sell: 'var(--red)', caution: 'var(--orange)', info: 'var(--blue)'};
    const bgMap    = {buy: 'rgba(74,222,128,0.08)', sell: 'rgba(248,113,113,0.08)', caution: 'rgba(251,146,60,0.08)', info: 'rgba(96,165,250,0.08)'};
    const tagMap   = {buy: '多', sell: '空', caution: '警', info: '訊'};
    h += '<div style="padding:8px 10px;display:flex;flex-direction:column;gap:6px">';
    for (const s of signals) {
      h += `<div style="background:${bgMap[s.level]};border-left:3px solid ${colorMap[s.level]};padding:7px 10px;border-radius:0 4px 4px 0">
        <div style="font-family:monospace;font-size:10.5px;font-weight:700;color:${colorMap[s.level]};letter-spacing:.5px">[${tagMap[s.level]}] ${escapeHtml(s.txt)}</div>
        <div style="font-family:monospace;font-size:9.5px;color:var(--text);margin-top:3px;line-height:1.55">${escapeHtml(s.detail)}</div>
        ${s.action ? `<div style="font-family:monospace;font-size:9px;color:${colorMap[s.level]};margin-top:3px;line-height:1.5;opacity:.85">▸ ${escapeHtml(s.action)}</div>` : ''}
      </div>`;
    }
    h += '</div>';
  }

  h += '<div style="padding:12px 12px 18px;font-family:monospace;font-size:8.5px;color:var(--tf);line-height:1.7">⚠ 訊號為規則化技術面提示，並未涵蓋基本面與總體環境。實際進出請綜合判斷並嚴守紀律。</div>';

  return h;

  // helpers
  function row(k, v, raw) {
    return `<div class="stat-row"><span class="stat-k">${k}</span><span class="stat-v">${raw ? v : v}</span></div>`;
  }
  function inpStyle(borderC) {
    return `background:var(--bg3);border:1px solid ${borderC || 'var(--border)'};border-radius:4px;padding:6px 9px;color:${borderC || 'var(--thi)'};font-family:monospace;font-size:11px;outline:none`;
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  }
}

function attachPosition() {
  const panel = document.getElementById('rpanel');
  if (!panel) return;

  // ── One-time: panel-level click delegation ──
  // The panel element itself isn't replaced on re-render, so the delegated
  // click handler survives. We MUST guard against re-registering on each call
  // or listeners accumulate (single click → N stacked confirm() dialogs).
  if (!panel._posListenerAttached) {
    panel._posListenerAttached = true;
    panel.addEventListener('click', function (ev) {
      const btn = ev.target.closest('[data-act]');
      if (!btn) return;
      const act = btn.dataset.act;
      if (act === 'save-pos')  { ev.preventDefault(); submitPosition(); }
      if (act === 'clear-pos') {
        ev.preventDefault();
        if (confirm(`清除 ${S.sym} 倉位？`)) clearPosition();
      }
      if (act === 'goto-pos') {
        ev.preventDefault();
        const sym = btn.dataset.sym;
        const mkt = btn.dataset.mkt || S.mkt || 'TW';
        if (sym && sym !== S.sym && typeof loadSym === 'function') {
          loadSym(sym, mkt);
        }
      }
    });
  }

  // ── 數值欄位維持「純資料輸入」:不在輸入框上掛任何鍵盤行為 ──
  // 原本「Enter → 送出存倉」已移除:輸入框不混用其他功能。
  // 儲存一律用「儲存倉位」按鈕(panel 上的 data-act="save-pos" 委派)。
}

// ── Re-render hook: triggered by `symLoaded` CustomEvent fired in v1's loadSym ──
// build_v2.py patches v1 to dispatch this event after every load. We use it to:
//   1. Snapshot the current price into the position's lastPrice field
//   2. Force re-render the POS panel (defensive — v1's local renderRpanel
//      might have thrown, never reaching the panel update)
window.addEventListener('symLoaded', function (e) {
  try {
    const sym = e.detail && e.detail.sym;
    const code = (sym || S.sym || '').toUpperCase().trim();
    if (S.positions && S.positions[code] && S.data?.candles?.length) {
      S.positions[code].lastPrice  = S.data.candles[S.data.candles.length - 1].close;
      S.positions[code].lastUpdate = Date.now();
      savePositions();
    }
    // 重繪一律走單一守門入口(編輯中自動跳過,不清空輸入框/不奪焦點)
    renderPositionPanel();
    console.log('[v2] symLoaded handler fired for', code, '— S.tab=', S.tab);
  } catch (err) {
    console.error('[v2] symLoaded handler error:', err);
  }
});

// Polling fallback: if symLoaded event isn't reached (e.g., user on a v2.html
// built before the build_v2 patch), poll every 600ms for S.sym changes.
(function pollSymChange() {
  let _last = null;
  setInterval(() => {
    if (S.tab !== 'position') return;
    if (S.sym && S.sym !== _last) {
      _last = S.sym;
      renderPositionPanel();
    }
  }, 600);
})();

// ── 單一守門渲染入口 ─────────────────────────────────────────
// 所有「重繪 POS 面板」的路徑都必須走這裡,集中唯一一道焦點守門:
// 只要使用者正在任一 pos-* 欄位輸入,就完全不重繪(innerHTML 重建會清空
// 輸入框、奪走焦點)。資料(S.positions)在背景照常更新,等失焦後的下一次
// 輪詢才反映到畫面。原則:打字時永不動 DOM。任何模組要刷新 POS 面板,
// 一律呼叫 window.renderPositionPanel(),不可自行 innerHTML = renderPosition()。
function renderPositionPanel() {
  if (typeof S === 'undefined' || S.tab !== 'position') return;
  const el = document.getElementById('rpanel');
  if (!el) return;
  // 單一標準:使用者正在 el 內任一欄位打字 → 不重繪(避免清空輸入/奪焦點)
  const editing = (window.Field && Field.editing) ? Field.editing(el)
    : (() => { const a = document.activeElement; return a && /^pos-(entry|shares|target|stop|notes)$/.test(a.id || ''); })();
  if (editing) return;
  try { el.innerHTML = renderPosition(); attachPosition(); }
  catch (err) {
    console.error('[v2] renderPositionPanel threw:', err);
    el.innerHTML = `<div style="padding:14px;color:var(--red);font-family:monospace;font-size:10px">render error: ${err.message}</div>`;
  }
}
window.renderPositionPanel = renderPositionPanel;

function submitPosition() {
  console.log('[v2] submitPosition called for', S.sym);
  const entryEl = document.getElementById('pos-entry');
  const sharesEl = document.getElementById('pos-shares');
  const unitEl = document.getElementById('pos-unit');
  if (!entryEl || !sharesEl) {
    alert('表單元件未找到（可能 v2 未正確載入，請重新整理）');
    console.error('[v2] form elements missing');
    return;
  }
  const e = entryEl.value;
  let s = sharesEl.value;
  const t = document.getElementById('pos-target')?.value || '';
  const p = document.getElementById('pos-stop')?.value || '';
  const n = document.getElementById('pos-notes')?.value || '';

  // Lot → share conversion for TW market (1 張 = 1000 股)
  const unit = unitEl?.value || 'share';
  if (unit === 'lot' && s) {
    s = String(parseFloat(s) * 1000);
  }

  const ok = setPosition(e, s, t, p, n);
  if (ok) showPosToast(`✓ ${S.sym} 倉位已儲存`);
}

function showPosToast(msg) {
  const t = document.getElementById('pos-toast');
  if (!t) return;
  t.textContent = msg;
  t.style.display = 'block';
  clearTimeout(showPosToast._tm);
  showPosToast._tm = setTimeout(() => { if (t) t.style.display = 'none'; }, 2200);
}

// Expose to window explicitly (defensive — function decls *should* already be global)
window.submitPosition = submitPosition;
window.clearPosition  = clearPosition;
window.setPosition    = setPosition;
window.getPosition    = getPosition;
window.renderPosition = renderPosition;
window.attachPosition = attachPosition;

// ── Hook into v1's tab system ───────────────────────────────
(function patchTabs() {
  if (!window.setTab || !window.renderRpanel) {
    console.warn('[v2] setTab/renderRpanel not found; deferring patch');
    return setTimeout(patchTabs, 100);
  }
  // Read each button's onclick attr to derive the actual DOM tab order
  // (build_v2.py injects POS *before* ETF, so order is: stats/research/batch/history/pos/etf)
  window.setTab = function (tab) {
    S.tab = tab;
    // 切換分頁屬明確操作:先讓目前 rpanel 內聚焦的欄位失焦,確保新分頁一定重繪
    // (否則守門會把「上一頁殘留的焦點」誤判成編輯中而跳過,造成切頁後面板沒更新)
    const _ae = document.activeElement;
    const _rp = document.getElementById('rpanel');
    if (_ae && _rp && _rp.contains(_ae) && typeof _ae.blur === 'function') _ae.blur();
    document.querySelectorAll('.rtab').forEach(b => {
      const oc = b.getAttribute('onclick') || '';
      const m = oc.match(/setTab\(['"](\w+)['"]\)/);
      const btab = m ? m[1] : null;
      b.classList.toggle('on', btab === tab);
    });
    renderRpanel();
  };

  const origRender = window.renderRpanel;
  window.renderRpanel = function () {
    if (S.tab === 'position') {
      renderPositionPanel();   // 單一守門入口(編輯中自動跳過)
      return;
    }
    // 其他右panel分頁(自選等):使用者正在欄位打字時不重繪(避免清空輸入/奪焦點)。
    // 用 Field.editing → 只擋「文字/數值輸入中」,select 變更等仍正常重繪。
    const rp = document.getElementById('rpanel');
    if (rp && window.Field && Field.editing(rp)) return;
    return origRender.apply(this, arguments);
  };

  console.log('[v2] position tab patched (setTab + renderRpanel wrapped)');
})();

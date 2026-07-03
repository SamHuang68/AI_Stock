// ============================================================
// Stock Terminal v3.9 — 樂高式策略條件組合器 (Visual Strategy Builder)
// ------------------------------------------------------------
// 不寫程式，用下拉選單組進出場條件：
//   [指標A] [比較] [指標B/數值]，多條以 AND / OR 串。
//   例：SMA20 交叉向上 SMA60　AND　RSI14 > 50  → 進場
//       SMA20 交叉向下 SMA60　                  → 出場
// 編譯成 buyArr/sellArr 餵 window.Backtest.runLS，輸出深化績效 +
//   可在主圖標示 buy/sell marker。條件組存 localStorage(strat_builder)。
// 同時對外提供共用指標庫 window.StratLib(腳本引擎 strategy_script 共用)。
// 架構守則：狀態用裸 S(讀 S.data.candles / S.chartSeries)；對外 window.stratBuilder*。
// ============================================================
(function () {
  'use strict';

  // ---------- 共用指標庫 StratLib ----------
  // 全部接受/回傳「與 K 線等長、不足期數為 null」的陣列。
  // v4.1:指標數學一律委派統一指標庫（src/core/indicators_v3.js,SSOT）,
  // 本模組不再自帶實作 → 與指標列 / 回測 / Python 後端永遠同一份數學。
  // (修正舊版 MACD signal 以 0 充填暖身期、EMA 無 SMA 種子的偏差)
  const IND = window.Indicators;
  function sma(arr, p) { return IND.sma(arr, p); }
  function ema(arr, p) { return IND.ema(arr, p); }
  function rsi(close, p) { return IND.rsi(close, p || 14); }
  // 隨機指標 KD (n=9, 平滑3) — 台股慣例 9,3,3
  function kd(high, low, close, n, sm) { return IND.kd(high, low, close, n || 9, sm || 3); }
  function macd(close, f, s, sig) { return IND.macd(close, f || 12, s || 26, sig || 9); }
  function bb(close, p, k) { return IND.bb(close, p || 20, k || 2); }
  function atr(high, low, close, p) { return IND.atr(high, low, close, p || 14); }
  function crossover(a, b) {
    return a.map((_, i) => i > 0 && a[i - 1] != null && b[i - 1] != null && a[i] != null && b[i] != null && a[i - 1] <= b[i - 1] && a[i] > b[i]);
  }
  function crossunder(a, b) {
    return a.map((_, i) => i > 0 && a[i - 1] != null && b[i - 1] != null && a[i] != null && b[i] != null && a[i - 1] >= b[i - 1] && a[i] < b[i]);
  }
  function highest(arr, n) {
    return arr.map((_, i) => { if (i < n - 1) return null; let h = -Infinity; for (let j = i - n + 1; j <= i; j++) h = Math.max(h, arr[j]); return h; });
  }
  function lowest(arr, n) {
    return arr.map((_, i) => { if (i < n - 1) return null; let l = Infinity; for (let j = i - n + 1; j <= i; j++) l = Math.min(l, arr[j]); return l; });
  }
  function pctChange(close) {
    return close.map((v, i) => i === 0 ? null : (close[i - 1] ? (v - close[i - 1]) / close[i - 1] * 100 : null));
  }
  window.StratLib = { sma, ema, rsi, kd, macd, bb, atr, crossover, crossunder, highest, lowest, pctChange };

  // ---------- 指標清單 (UI 下拉) ----------
  // type: 'price'(無參數) | 'n'(需期數) | 'sub'(子序列 macd/kd/bb)
  const INDICATORS = {
    close: { lbl: '收盤價', kind: 'price' },
    open: { lbl: '開盤價', kind: 'price' },
    high: { lbl: '最高價', kind: 'price' },
    low: { lbl: '最低價', kind: 'price' },
    volume: { lbl: '成交量', kind: 'price' },
    sma: { lbl: 'SMA', kind: 'n', dflt: 20 },
    ema: { lbl: 'EMA', kind: 'n', dflt: 20 },
    rsi: { lbl: 'RSI', kind: 'n', dflt: 14 },
    volsma: { lbl: '量均', kind: 'n', dflt: 20 },
    k: { lbl: 'KD的K', kind: 'fixed' },
    d: { lbl: 'KD的D', kind: 'fixed' },
    macd: { lbl: 'MACD線', kind: 'fixed' },
    macdsig: { lbl: 'MACD訊號', kind: 'fixed' },
    macdhist: { lbl: 'MACD柱', kind: 'fixed' },
    bbu: { lbl: '布林上軌', kind: 'fixed' },
    bbm: { lbl: '布林中軌', kind: 'fixed' },
    bbl: { lbl: '布林下軌', kind: 'fixed' },
    pct: { lbl: '漲跌%', kind: 'fixed' },
  };
  const COMPARATORS = {
    gt: '>', lt: '<', gte: '>=', lte: '<=', xup: '交叉向上', xdn: '交叉向下',
  };

  // ---------- 把 spec 解析成序列 ----------
  function buildSeries(spec, cols) {
    const { open, high, low, close, volume } = cols;
    const n = spec.n || INDICATORS[spec.ind]?.dflt || 20;
    switch (spec.ind) {
      case 'close': return close;
      case 'open': return open;
      case 'high': return high;
      case 'low': return low;
      case 'volume': return volume;
      case 'sma': return sma(close, n);
      case 'ema': return ema(close, n);
      case 'rsi': return rsi(close, n);
      case 'volsma': return sma(volume, n);
      case 'k': return kd(high, low, close).k;
      case 'd': return kd(high, low, close).d;
      case 'macd': return macd(close).macd;
      case 'macdsig': return macd(close).signal;
      case 'macdhist': return macd(close).hist;
      case 'bbu': return bb(close).upper;
      case 'bbm': return bb(close).mid;
      case 'bbl': return bb(close).lower;
      case 'pct': return pctChange(close);
      default: return close;
    }
  }

  // ---------- 評估一組條件 → bool 陣列 ----------
  function evalConditions(conds, combine, cols) {
    const len = cols.close.length;
    if (!conds.length) return new Array(len).fill(false);
    const series = conds.map(cd => {
      const L = buildSeries(cd.left, cols);
      const R = (cd.rightMode === 'num')
        ? new Array(len).fill(parseFloat(cd.rightNum))
        : buildSeries(cd.right, cols);
      const out = new Array(len).fill(false);
      for (let i = 0; i < len; i++) {
        const a = L[i], b = R[i];
        if (a == null || b == null) continue;
        switch (cd.cmp) {
          case 'gt': out[i] = a > b; break;
          case 'lt': out[i] = a < b; break;
          case 'gte': out[i] = a >= b; break;
          case 'lte': out[i] = a <= b; break;
          case 'xup': out[i] = i > 0 && L[i - 1] != null && R[i - 1] != null && L[i - 1] <= R[i - 1] && a > b; break;
          case 'xdn': out[i] = i > 0 && L[i - 1] != null && R[i - 1] != null && L[i - 1] >= R[i - 1] && a < b; break;
        }
      }
      return out;
    });
    const res = new Array(len).fill(false);
    for (let i = 0; i < len; i++) {
      res[i] = combine === 'OR' ? series.some(s => s[i]) : series.every(s => s[i]);
    }
    return res;
  }

  // ---------- 狀態 ----------
  let model = null;   // {entry:[],entryCombine,exit:[],exitCombine,tp,sl,maxBars}
  function blankCond() { return { left: { ind: 'sma', n: 20 }, cmp: 'xup', rightMode: 'ind', right: { ind: 'sma', n: 60 }, rightNum: 0 }; }
  function defModel() {
    return {
      entry: [{ left: { ind: 'sma', n: 20 }, cmp: 'xup', rightMode: 'ind', right: { ind: 'sma', n: 60 }, rightNum: 0 },
      { left: { ind: 'rsi', n: 14 }, cmp: 'gt', rightMode: 'num', right: { ind: 'sma', n: 20 }, rightNum: 50 }],
      entryCombine: 'AND',
      exit: [{ left: { ind: 'sma', n: 20 }, cmp: 'xdn', rightMode: 'ind', right: { ind: 'sma', n: 60 }, rightNum: 0 }],
      exitCombine: 'OR',
      tp: 0, sl: 8, maxBars: 0,
    };
  }

  // ---------- UI ----------
  function indSelect(spec, onChange) {
    const opts = Object.entries(INDICATORS).map(([k, v]) => `<option value="${k}"${k === spec.ind ? ' selected' : ''}>${v.lbl}</option>`).join('');
    const needN = INDICATORS[spec.ind] && INDICATORS[spec.ind].kind === 'n';
    return `<select class="sb-ind">${opts}</select>` +
      `<input class="sb-n" type="number" value="${spec.n || ''}" style="width:46px;display:${needN ? 'inline-block' : 'none'}" />`;
  }

  function condRow(cd, group, idx) {
    return `<div class="sb-cond" data-group="${group}" data-idx="${idx}">
      <span class="sb-left">${indSelect(cd.left)}</span>
      <select class="sb-cmp">${Object.entries(COMPARATORS).map(([k, v]) => `<option value="${k}"${k === cd.cmp ? ' selected' : ''}>${v}</option>`).join('')}</select>
      <select class="sb-rmode"><option value="ind"${cd.rightMode === 'ind' ? ' selected' : ''}>指標</option><option value="num"${cd.rightMode === 'num' ? ' selected' : ''}>數值</option></select>
      <span class="sb-right" style="display:${cd.rightMode === 'ind' ? 'inline' : 'none'}">${indSelect(cd.right)}</span>
      <input class="sb-rnum" type="number" value="${cd.rightNum}" style="width:60px;display:${cd.rightMode === 'num' ? 'inline-block' : 'none'}" />
      <button class="sb-del" title="刪除">✕</button>
    </div>`;
  }

  function groupHtml(title, group, conds, combine) {
    return `<div class="sb-group">
      <div class="sb-ghdr">${title}
        <select class="sb-combine" data-group="${group}">
          <option value="AND"${combine === 'AND' ? ' selected' : ''}>全部成立 (AND)</option>
          <option value="OR"${combine === 'OR' ? ' selected' : ''}>任一成立 (OR)</option>
        </select>
        <button class="sb-add" data-group="${group}">+ 條件</button>
      </div>
      <div class="sb-conds" data-group="${group}">${conds.map((c, i) => condRow(c, group, i)).join('')}</div>
    </div>`;
  }

  function readUI() {
    // 從 DOM 把目前選擇讀回 model
    ['entry', 'exit'].forEach(group => {
      const wrap = document.querySelector(`.sb-conds[data-group="${group}"]`);
      if (!wrap) return;
      const rows = [...wrap.querySelectorAll('.sb-cond')];
      model[group] = rows.map(r => {
        const inds = r.querySelectorAll('.sb-ind');
        const ns = r.querySelectorAll('.sb-n');
        const left = { ind: inds[0].value, n: parseFloat(ns[0].value) || INDICATORS[inds[0].value]?.dflt };
        const rmode = r.querySelector('.sb-rmode').value;
        const right = inds[1] ? { ind: inds[1].value, n: parseFloat(ns[1].value) || INDICATORS[inds[1].value]?.dflt } : { ind: 'sma', n: 60 };
        return { left, cmp: r.querySelector('.sb-cmp').value, rightMode: rmode, right, rightNum: parseFloat(r.querySelector('.sb-rnum').value) || 0 };
      });
      const cb = document.querySelector(`.sb-combine[data-group="${group}"]`);
      if (cb) model[group + 'Combine'] = cb.value;
    });
    model.tp = parseFloat(document.getElementById('sb-tp').value) || 0;
    model.sl = parseFloat(document.getElementById('sb-sl').value) || 0;
    model.maxBars = parseFloat(document.getElementById('sb-maxbars').value) || 0;
  }

  function renderGroups() {
    document.getElementById('sb-entry').innerHTML = groupHtml('進場條件', 'entry', model.entry, model.entryCombine);
    document.getElementById('sb-exit').innerHTML = groupHtml('出場條件', 'exit', model.exit, model.exitCombine);
    bindGroupEvents();
  }

  function bindGroupEvents() {
    document.querySelectorAll('.sb-add').forEach(b => b.onclick = () => { readUI(); model[b.dataset.group].push(blankCond()); renderGroups(); });
    document.querySelectorAll('.sb-del').forEach(b => b.onclick = () => {
      const row = b.closest('.sb-cond'); const g = row.dataset.group;
      readUI(); model[g].splice(parseInt(row.dataset.idx, 10), 1);
      if (!model[g].length) model[g].push(blankCond());
      renderGroups();
    });
    // 指標選擇變更 → 顯示/隱藏期數欄
    document.querySelectorAll('.sb-ind').forEach(sel => sel.onchange = () => {
      const needN = INDICATORS[sel.value] && INDICATORS[sel.value].kind === 'n';
      const nIn = sel.parentElement.querySelector('.sb-n');
      if (nIn) { nIn.style.display = needN ? 'inline-block' : 'none'; if (needN && !nIn.value) nIn.value = INDICATORS[sel.value].dflt; }
    });
    document.querySelectorAll('.sb-rmode').forEach(sel => sel.onchange = () => {
      const row = sel.closest('.sb-cond');
      row.querySelector('.sb-right').style.display = sel.value === 'ind' ? 'inline' : 'none';
      row.querySelector('.sb-rnum').style.display = sel.value === 'num' ? 'inline-block' : 'none';
    });
  }

  // ---------- 執行回測 ----------
  function getCandles() {
    if (typeof S !== 'undefined' && S.data && Array.isArray(S.data.candles)) return S.data.candles;
    return null;
  }
  function run() {
    readUI();
    const candles = getCandles();
    const msg = document.getElementById('sb-msg');
    if (!candles || candles.length < 60) { msg.innerHTML = '<span style="color:#f87171">資料不足，請先載入個股(建議 1 年以上日線)</span>'; return; }
    if (!window.Backtest || !window.Backtest.runLS) { msg.innerHTML = '<span style="color:#f87171">回測核心未載入</span>'; return; }
    const cols = window.Backtest.colsOf(candles);
    const buy = evalConditions(model.entry, model.entryCombine, cols);
    const sell = evalConditions(model.exit, model.exitCombine, cols);
    const opts = { tp: model.tp > 0 ? model.tp / 100 : 0, sl: model.sl > 0 ? model.sl / 100 : 0, maxBars: model.maxBars || 0 };
    const r = window.Backtest.runLS(candles, buy, sell, opts);
    window._sbLast = { r, candles, buy, sell };
    renderResult(r);
  }

  function fmtPF(v) { return v === Infinity ? '∞' : v.toFixed(2); }
  function renderResult(r) {
    const sym = (typeof S !== 'undefined' && S.sym) ? S.sym : '';
    const cell = (lbl, val, cls) => `<div class="sb-stat"><div class="sb-sl">${lbl}</div><div class="sb-sv ${cls || ''}">${val}</div></div>`;
    const pos = v => v >= 0 ? 'up' : 'dn';
    let h = `<div class="sb-stats">` +
      cell('總報酬(淨)', (r.totalReturn >= 0 ? '+' : '') + r.totalReturn.toFixed(1) + '%', pos(r.totalReturn)) +
      cell('總報酬(毛)', r.totalReturnGross != null ? (r.totalReturnGross >= 0 ? '+' : '') + r.totalReturnGross.toFixed(1) + '%' : '—') +
      cell('交易筆數', r.count) +
      cell('勝率', r.winRate.toFixed(1) + '%', r.winRate >= 50 ? 'up' : 'dn') +
      cell('獲利因子', fmtPF(r.profitFactor), r.profitFactor >= 1 ? 'up' : 'dn') +
      cell('最大回撤', '-' + r.maxDD.toFixed(1) + '%', 'dn') +
      cell('夏普(年化)', r.sharpeAnn.toFixed(2), r.sharpeAnn >= 1 ? 'up' : '') +
      cell('期望值/筆', (r.expectancy >= 0 ? '+' : '') + r.expectancy.toFixed(2) + '%', pos(r.expectancy)) +
      cell('平均持有', r.avgHoldBars.toFixed(1) + ' 根') +
      cell('最大連勝', r.maxWinStreak, 'up') +
      cell('最大連敗', r.maxLossStreak, 'dn') +
      cell('最佳/最差', '+' + r.best.toFixed(1) + '% / ' + r.worst.toFixed(1) + '%') +
      `</div>` +
      `<div style="font-size:10px;color:#64748b;margin:4px 0">進場=訊號次根開盤(無前視);淨=已扣` +
      (r.cost ? `手續費 ${(r.cost.fee * 100).toFixed(4)}%×2 + 證交稅 ${(r.cost.tax * 100).toFixed(2)}%(賣出)` : '費稅') +
      `;出場訊號成交於次根開盤,TP/SL 以收盤判斷</div>`;
    h += `<div class="sb-actions"><button id="sb-mark">📍 在主圖標示買賣點</button><canvas id="sb-curve" width="540" height="90"></canvas></div>`;
    // 交易明細
    if (r.trades.length) {
      h += `<details class="sb-trades"><summary>逐筆交易明細 (${r.trades.length})</summary><table><thead><tr><th>#</th><th>進場日</th><th>進</th><th>出場日</th><th>出</th><th>報酬</th><th>持有</th><th>出場因</th></tr></thead><tbody>`;
      const fmtD = t => { const d = new Date(t * 1000); return (d.getMonth() + 1) + '/' + d.getDate() + '/' + String(d.getFullYear()).slice(2); };
      const rsn = { tp: '停利', sl: '停損', time: '時間', signal: '訊號', end: '到底' };
      r.trades.forEach((t, i) => {
        h += `<tr><td>${i + 1}</td><td>${fmtD(t.time)}</td><td>${t.entry.toFixed(2)}</td><td>${fmtD(t.exitTime)}</td><td>${t.exit.toFixed(2)}</td><td class="${t.ret >= 0 ? 'up' : 'dn'}">${(t.ret * 100).toFixed(2)}%</td><td>${t.holdBars}</td><td>${rsn[t.reason] || t.reason}</td></tr>`;
      });
      h += `</tbody></table></details>`;
    }
    document.getElementById('sb-result').innerHTML = h;
    document.getElementById('sb-msg').textContent = sym ? `回測標的：${sym}（目前圖表區間）` : '';
    if (window.Backtest.drawCurve) window.Backtest.drawCurve(document.getElementById('sb-curve'), r.curve, '#fbbf24');
    const mk = document.getElementById('sb-mark'); if (mk) mk.onclick = markChart;
  }

  function markChart() {
    const d = window._sbLast; if (!d) return;
    if (typeof S === 'undefined' || !S.chartSeries) { alert('主圖未就緒'); return; }
    const tz = (typeof S.tzOffset === 'number') ? S.tzOffset : 0;
    const markers = [];
    d.r.trades.forEach(t => {
      markers.push({ time: t.time + tz, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: 'B' });
      markers.push({ time: t.exitTime + tz, position: 'aboveBar', color: '#ef4444', shape: 'arrowDown', text: t.ret >= 0 ? '+' + (t.ret * 100).toFixed(0) + '%' : (t.ret * 100).toFixed(0) + '%' });
    });
    markers.sort((a, b) => a.time - b.time);
    try { S.chartSeries.setMarkers(markers); } catch (e) { console.warn(e); }
  }

  // ---------- 儲存/載入條件組 ----------
  function savedStore() { try { return JSON.parse(localStorage.getItem('strat_builder') || '{}'); } catch { return {}; } }
  function saveModel() {
    readUI();
    const name = prompt('條件組命名：', 'my_strategy'); if (!name) return;
    const all = savedStore(); all[name] = model; localStorage.setItem('strat_builder', JSON.stringify(all));
    refreshSavedList();
  }
  function refreshSavedList() {
    const sel = document.getElementById('sb-saved'); if (!sel) return;
    const all = savedStore();
    sel.innerHTML = '<option value="">— 載入條件組 —</option>' + Object.keys(all).map(k => `<option value="${k}">${k}</option>`).join('');
  }
  function loadModel(name) {
    const all = savedStore(); if (!all[name]) return;
    model = JSON.parse(JSON.stringify(all[name]));
    document.getElementById('sb-tp').value = model.tp || 0;
    document.getElementById('sb-sl').value = model.sl || 0;
    document.getElementById('sb-maxbars').value = model.maxBars || 0;
    renderGroups();
  }

  // ---------- modal ----------
  function style() {
    if (document.getElementById('sb-style')) return;
    const s = document.createElement('style'); s.id = 'sb-style';
    s.textContent = `
    #sb-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #sb-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(820px,96vw);max-height:92vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #sb-box h3{margin:0 0 8px;font-size:15px;display:flex;align-items:center;gap:8px}
    #sb-box h3 .x{margin-left:auto;cursor:pointer;color:#94a3b8;font-size:18px}
    .sb-group{border:1px solid #1e293b;border-radius:8px;margin:8px 0;padding:8px}
    .sb-ghdr{display:flex;align-items:center;gap:8px;font-weight:700;margin-bottom:6px}
    .sb-ghdr .sb-add{margin-left:auto}
    .sb-cond{display:flex;align-items:center;gap:5px;flex-wrap:wrap;padding:4px 0;border-bottom:1px solid #131c2e}
    .sb-cond select,.sb-cond input{background:#0b1220;border:1px solid #334155;color:#e2e8f0;border-radius:5px;padding:3px 5px;font-size:11px}
    .sb-add,.sb-del,#sb-run,#sb-save,.sb-actions button{background:#1e293b;border:1px solid #334155;color:#cbd5e1;border-radius:5px;padding:3px 9px;cursor:pointer;font-size:11px}
    #sb-run{background:rgba(251,191,36,.18);border-color:#fbbf24;color:#fbbf24;font-weight:700;padding:6px 16px}
    .sb-del{color:#f87171;border-color:#7f1d1d;padding:2px 7px}
    .sb-opts{display:flex;gap:12px;align-items:center;margin:8px 0;flex-wrap:wrap}
    .sb-opts input{width:60px;background:#0b1220;border:1px solid #334155;color:#e2e8f0;border-radius:5px;padding:4px}
    .sb-opts label{font-size:11px;color:#94a3b8}
    #sb-msg{font-size:11px;color:#94a3b8;margin:6px 0;min-height:14px}
    .sb-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:8px 0}
    .sb-stat{background:#0b1220;border:1px solid #1e293b;border-radius:6px;padding:6px 8px}
    .sb-sl{font-size:9px;color:#64748b}.sb-sv{font-size:14px;font-weight:800;margin-top:2px}
    .sb-sv.up{color:#22c55e}.sb-sv.dn{color:#ef4444}
    .sb-actions{display:flex;gap:10px;align-items:center;margin:8px 0;flex-wrap:wrap}
    #sb-curve{border:1px solid #1e293b;border-radius:6px;background:#060A12}
    .sb-trades{margin-top:8px}.sb-trades summary{cursor:pointer;color:#94a3b8;font-size:11px;margin-bottom:6px}
    .sb-trades table{width:100%;border-collapse:collapse;font-size:10px}
    .sb-trades th,.sb-trades td{border-bottom:1px solid #1a2740;padding:3px 5px;text-align:right}
    .sb-trades th{color:#64748b;font-weight:600}
    .sb-trades td.up{color:#22c55e}.sb-trades td.dn{color:#ef4444}
    .sb-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
    .sb-toolbar select{background:#0b1220;border:1px solid #334155;color:#cbd5e1;border-radius:5px;padding:4px}`;
    document.head.appendChild(s);
  }

  function open() {
    style();
    if (!model) model = defModel();
    let m = document.getElementById('sb-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'sb-modal';
      m.innerHTML = `<div id="sb-box">
        <h3>🧱 策略條件組合器 <span class="x" onclick="window.stratBuilderClose&&stratBuilderClose()">×</span></h3>
        <div class="sb-toolbar">
          <select id="sb-saved"><option value="">— 載入條件組 —</option></select>
          <button id="sb-save">💾 另存</button>
          <span style="color:#475569;font-size:10px">不寫程式，下拉組條件 → 回測。標的=目前載入的個股與圖表區間。</span>
        </div>
        <div id="sb-entry"></div>
        <div id="sb-exit"></div>
        <div class="sb-opts">
          <label>停利% <input id="sb-tp" type="number" value="${model.tp}" /></label>
          <label>停損% <input id="sb-sl" type="number" value="${model.sl}" /></label>
          <label>最長持有(根) <input id="sb-maxbars" type="number" value="${model.maxBars}" /></label>
          <button id="sb-run">▶ 回測</button>
        </div>
        <div id="sb-msg"></div>
        <div id="sb-result"></div>
      </div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
      m.querySelector('#sb-run').onclick = run;
      m.querySelector('#sb-save').onclick = saveModel;
      m.querySelector('#sb-saved').onchange = e => { if (e.target.value) loadModel(e.target.value); };
    }
    m.style.display = 'flex';
    renderGroups();
    refreshSavedList();
  }
  function close() { const m = document.getElementById('sb-modal'); if (m) m.style.display = 'none'; }

  window.stratBuilderOpen = open;
  window.stratBuilderClose = close;
})();

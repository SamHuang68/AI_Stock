// ============================================================
// Stock Terminal v3.9 — 迷你策略腳本引擎 (Pine-like Safe DSL)
// ------------------------------------------------------------
// 類 Pine 語法，但「不是 eval 任意 JS」：自寫 tokenizer + 遞迴下降
//   直譯器，函式白名單，逐行算成「序列」。範例：
//     fast = sma(close, 20)
//     slow = sma(close, 60)
//     buy  = crossover(fast, slow) and rsi(close,14) > 50
//     sell = crossunder(fast, slow)
//     plot fast, slow
// buy/sell → window.Backtest.runLS；plot → 主圖疊線；交易 → buy/sell marker。
// 指標庫共用 window.StratLib(strategy_builder 提供)。
// 架構守則：狀態用裸 S；對外 window.stratScript*。
// ============================================================
(function () {
  'use strict';

  const PRICE = { close: 1, open: 1, high: 1, low: 1, volume: 1 };

  // ---------- Tokenizer ----------
  function tokenize(src) {
    const toks = [];
    let i = 0;
    const isId = c => /[A-Za-z_]/.test(c);
    const isIdN = c => /[A-Za-z0-9_]/.test(c);
    const isNum = c => /[0-9.]/.test(c);
    while (i < src.length) {
      const c = src[i];
      if (c === '#') { while (i < src.length && src[i] !== '\n') i++; continue; }
      if (c === '\n') { toks.push({ t: 'nl' }); i++; continue; }
      if (c === ' ' || c === '\t' || c === '\r') { i++; continue; }
      if (isNum(c)) { let b = ''; while (i < src.length && isNum(src[i])) b += src[i++]; toks.push({ t: 'num', v: parseFloat(b) }); continue; }
      if (isId(c)) {
        let b = ''; while (i < src.length && isIdN(src[i])) b += src[i++];
        const low = b.toLowerCase();
        if (low === 'and' || low === 'or' || low === 'not') toks.push({ t: 'kw', v: low });
        else toks.push({ t: 'id', v: b });
        continue;
      }
      // 多字元運算
      const two = src.substr(i, 2);
      if (['>=', '<=', '==', '!='].includes(two)) { toks.push({ t: 'op', v: two }); i += 2; continue; }
      if ('+-*/()<>=,'.includes(c)) { toks.push({ t: 'op', v: c }); i++; continue; }
      throw new Error('無法解析: ' + c);
    }
    toks.push({ t: 'nl' });
    return toks;
  }

  // ---------- 解析 + 直譯 ----------
  // 值 = number 或 array(number|bool|null)。執行需 cols(等長價格陣列)。
  function interp(src, cols) {
    const L = window.StratLib;
    const clen = cols.close.length;
    const env = {};
    const plots = [];

    const arrOf = x => Array.isArray(x) ? x : new Array(clen).fill(x);
    const num = x => Array.isArray(x) ? (x.length ? x[x.length - 1] : 0) : x;
    function broadcast(a, b, fn) {
      if (!Array.isArray(a) && !Array.isArray(b)) return fn(a, b);
      const A = arrOf(a), B = arrOf(b);
      const out = new Array(clen).fill(null);
      for (let i = 0; i < clen; i++) { const av = A[i], bv = B[i]; if (av == null || bv == null) { out[i] = null; continue; } out[i] = fn(av, bv); }
      return out;
    }

    const FUNCS = {
      sma: (s, n) => L.sma(arrOf(s), num(n)),
      ema: (s, n) => L.ema(arrOf(s), num(n)),
      rsi: (s, n) => L.rsi(arrOf(s), num(n)),
      highest: (s, n) => L.highest(arrOf(s), num(n)),
      lowest: (s, n) => L.lowest(arrOf(s), num(n)),
      crossover: (a, b) => L.crossover(arrOf(a), arrOf(b)),
      crossunder: (a, b) => L.crossunder(arrOf(a), arrOf(b)),
      k: () => L.kd(cols.high, cols.low, cols.close).k,
      d: () => L.kd(cols.high, cols.low, cols.close).d,
      macd: () => L.macd(cols.close).macd,
      macdsig: () => L.macd(cols.close).signal,
      macdhist: () => L.macd(cols.close).hist,
      bbupper: (n, k) => L.bb(cols.close, n ? num(n) : 20, k ? num(k) : 2).upper,
      bbmid: (n, k) => L.bb(cols.close, n ? num(n) : 20, k ? num(k) : 2).mid,
      bblower: (n, k) => L.bb(cols.close, n ? num(n) : 20, k ? num(k) : 2).lower,
      abs: (s) => Array.isArray(s) ? s.map(v => v == null ? null : Math.abs(v)) : Math.abs(s),
    };

    // 解析狀態
    let toks, pos;
    const peek = () => toks[pos];
    const eat = () => toks[pos++];

    // 表達式 (遞迴下降，含優先序)
    function parseExpr() { return parseOr(); }
    function parseOr() { let n = parseAnd(); while (peek() && peek().t === 'kw' && peek().v === 'or') { eat(); const r = parseAnd(); const l = n; n = () => broadcast(l(), r(), (a, b) => (!!a) || (!!b)); } return n; }
    function parseAnd() { let n = parseNot(); while (peek() && peek().t === 'kw' && peek().v === 'and') { eat(); const r = parseNot(); const l = n; n = () => broadcast(l(), r(), (a, b) => (!!a) && (!!b)); } return n; }
    function parseNot() { if (peek() && peek().t === 'kw' && peek().v === 'not') { eat(); const r = parseNot(); return () => { const v = r(); return Array.isArray(v) ? v.map(x => x == null ? null : !x) : !v; }; } return parseCmp(); }
    function parseCmp() {
      let n = parseAdd();
      while (peek() && peek().t === 'op' && ['>', '<', '>=', '<=', '==', '!='].includes(peek().v)) {
        const op = eat().v; const r = parseAdd(); const l = n;
        n = () => broadcast(l(), r(), (a, b) => {
          switch (op) { case '>': return a > b; case '<': return a < b; case '>=': return a >= b; case '<=': return a <= b; case '==': return a === b; case '!=': return a !== b; }
        });
      }
      return n;
    }
    function parseAdd() { let n = parseMul(); while (peek() && peek().t === 'op' && (peek().v === '+' || peek().v === '-')) { const op = eat().v; const r = parseMul(); const l = n; n = () => broadcast(l(), r(), (a, b) => op === '+' ? a + b : a - b); } return n; }
    function parseMul() { let n = parseUnary(); while (peek() && peek().t === 'op' && (peek().v === '*' || peek().v === '/')) { const op = eat().v; const r = parseUnary(); const l = n; n = () => broadcast(l(), r(), (a, b) => op === '*' ? a * b : (b === 0 ? null : a / b)); } return n; }
    function parseUnary() { if (peek() && peek().t === 'op' && peek().v === '-') { eat(); const r = parseUnary(); return () => { const v = r(); return Array.isArray(v) ? v.map(x => x == null ? null : -x) : -v; }; } return parsePrimary(); }
    function parsePrimary() {
      const tk = peek();
      if (!tk) throw new Error('語法不完整');
      if (tk.t === 'num') { eat(); return () => tk.v; }
      if (tk.t === 'op' && tk.v === '(') { eat(); const e = parseExpr(); if (!peek() || peek().v !== ')') throw new Error('缺少 )'); eat(); return e; }
      if (tk.t === 'id') {
        eat();
        const name = tk.v;
        // 函式呼叫
        if (peek() && peek().t === 'op' && peek().v === '(') {
          eat();
          const args = [];
          if (!(peek() && peek().t === 'op' && peek().v === ')')) {
            args.push(parseExpr());
            while (peek() && peek().t === 'op' && peek().v === ',') { eat(); args.push(parseExpr()); }
          }
          if (!peek() || peek().v !== ')') throw new Error('缺少 )');
          eat();
          const fn = FUNCS[name.toLowerCase()];
          if (!fn) throw new Error('未知函式: ' + name);
          return () => fn(...args.map(a => a()));
        }
        // 變數 / 價格
        const lname = name.toLowerCase();
        return () => {
          if (PRICE[lname]) return cols[lname];
          if (lname in env) return env[lname];
          throw new Error('未定義變數: ' + name);
        };
      }
      throw new Error('非預期符號: ' + (tk.v != null ? tk.v : tk.t));
    }

    // 逐行
    const lines = src.split('\n');
    for (let ln = 0; ln < lines.length; ln++) {
      const line = lines[ln];
      if (!line.trim() || line.trim().startsWith('#')) continue;
      toks = tokenize(line); pos = 0;
      // 過濾尾端 nl
      const first = peek();
      if (!first) continue;
      if (first.t === 'id' && first.v.toLowerCase() === 'plot') {
        eat();
        do {
          const startTokName = peek();
          const e = parseExpr();
          const label = (startTokName && startTokName.t === 'id') ? startTokName.v : 'plot';
          try { const val = e(); plots.push({ label, series: arrOf(val) }); } catch (err) { throw new Error('第 ' + (ln + 1) + ' 行 plot: ' + err.message); }
          if (peek() && peek().t === 'op' && peek().v === ',') { eat(); continue; }
          break;
        } while (true);
        continue;
      }
      // 賦值: id = expr
      if (first.t === 'id' && toks[1] && toks[1].t === 'op' && toks[1].v === '=') {
        const vname = eat().v.toLowerCase(); eat(); // name, '='
        const e = parseExpr();
        try { env[vname] = e(); } catch (err) { throw new Error('第 ' + (ln + 1) + ' 行: ' + err.message); }
        continue;
      }
      throw new Error('第 ' + (ln + 1) + ' 行語法錯誤(需 name = expr 或 plot ...)');
    }

    return { env, plots };
  }

  // ---------- 範例腳本 ----------
  const EXAMPLES = {
    'golden': `# 均線黃金交叉 + RSI 濾網\nfast = sma(close, 20)\nslow = sma(close, 60)\nbuy  = crossover(fast, slow) and rsi(close, 14) > 50\nsell = crossunder(fast, slow)\nplot fast, slow`,
    'rsi': `# RSI 超賣進場 / 超買出場\nr = rsi(close, 14)\nbuy  = crossover(r, 30)\nsell = crossover(r, 70)\nplot r`,
    'bb': `# 布林通道：跌破下軌進、突破中軌出\nlowerb = bblower(20, 2)\nmidb   = bbmid(20, 2)\nbuy  = crossover(close, lowerb)\nsell = crossover(close, midb)\nplot lowerb, midb`,
  };

  let plotSeries = [];
  function clearPlots() {
    if (typeof S === 'undefined' || !S.chart) { plotSeries = []; return; }
    plotSeries.forEach(s => { try { S.chart.removeSeries(s); } catch {} });
    plotSeries = [];
  }

  function getCandles() {
    if (typeof S !== 'undefined' && S.data && Array.isArray(S.data.candles)) return S.data.candles;
    return null;
  }

  function run() {
    const ta = document.getElementById('ss-code');
    const msg = document.getElementById('ss-msg');
    const candles = getCandles();
    if (!candles || candles.length < 60) { msg.innerHTML = '<span style="color:#f87171">資料不足，請先載入個股(1 年以上日線)</span>'; return; }
    if (!window.StratLib || !window.Backtest || !window.Backtest.runLS) { msg.innerHTML = '<span style="color:#f87171">核心未載入</span>'; return; }
    const cols = window.Backtest.colsOf(candles);
    let res;
    try { res = interp(ta.value, cols); }
    catch (e) { msg.innerHTML = '<span style="color:#f87171">腳本錯誤：' + e.message + '</span>'; return; }
    const buy = res.env.buy, sell = res.env.sell;
    if (!Array.isArray(buy)) { msg.innerHTML = '<span style="color:#f87171">需定義 buy = ... (布林序列)</span>'; return; }
    const sellArr = Array.isArray(sell) ? sell : null;
    const r = window.Backtest.runLS(candles, buy, sellArr, { sl: 0, tp: 0, maxBars: 0 });
    window._ssLast = { r, candles, plots: res.plots };
    msg.textContent = `OK · 進場訊號 ${buy.filter(Boolean).length} 次 · ${res.plots.length} 條 plot`;
    renderResult(r);
    drawPlots(res.plots, candles);
    markTrades(r);
  }

  function drawPlots(plots, candles) {
    clearPlots();
    if (typeof S === 'undefined' || !S.chart) return;
    const tz = (typeof S.tzOffset === 'number') ? S.tzOffset : 0;
    const colors = ['#fbbf24', '#67e8f9', '#f472b6', '#a3e635', '#fb923c'];
    plots.forEach((p, idx) => {
      try {
        const ls = S.chart.addLineSeries({ color: colors[idx % colors.length], lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
        const data = [];
        for (let i = 0; i < candles.length; i++) { const v = p.series[i]; if (v != null && isFinite(v)) data.push({ time: candles[i].time + tz, value: v }); }
        ls.setData(data);
        plotSeries.push(ls);
      } catch (e) { console.warn('[script plot]', e); }
    });
  }

  function markTrades(r) {
    if (typeof S === 'undefined' || !S.chartSeries) return;
    const tz = (typeof S.tzOffset === 'number') ? S.tzOffset : 0;
    const markers = [];
    r.trades.forEach(t => {
      markers.push({ time: t.time + tz, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: 'B' });
      markers.push({ time: t.exitTime + tz, position: 'aboveBar', color: '#ef4444', shape: 'arrowDown', text: 'S' });
    });
    markers.sort((a, b) => a.time - b.time);
    try { S.chartSeries.setMarkers(markers); } catch {}
  }

  function fmtPF(v) { return v === Infinity ? '∞' : v.toFixed(2); }
  function renderResult(r) {
    const cell = (lbl, val, cls) => `<div class="ss-stat"><div class="ss-sl">${lbl}</div><div class="ss-sv ${cls || ''}">${val}</div></div>`;
    const pos = v => v >= 0 ? 'up' : 'dn';
    let h = `<div class="ss-stats">` +
      cell('總報酬', (r.totalReturn >= 0 ? '+' : '') + r.totalReturn.toFixed(1) + '%', pos(r.totalReturn)) +
      cell('筆數', r.count) +
      cell('勝率', r.winRate.toFixed(1) + '%', r.winRate >= 50 ? 'up' : 'dn') +
      cell('獲利因子', fmtPF(r.profitFactor), r.profitFactor >= 1 ? 'up' : 'dn') +
      cell('最大回撤', '-' + r.maxDD.toFixed(1) + '%', 'dn') +
      cell('夏普(年化)', r.sharpeAnn.toFixed(2), r.sharpeAnn >= 1 ? 'up' : '') +
      `</div><canvas id="ss-curve" width="540" height="80"></canvas>`;
    document.getElementById('ss-result').innerHTML = h;
    if (window.Backtest.drawCurve) window.Backtest.drawCurve(document.getElementById('ss-curve'), r.curve, '#fbbf24');
  }

  function style() {
    if (document.getElementById('ss-style')) return;
    const s = document.createElement('style'); s.id = 'ss-style';
    s.textContent = `
    #ss-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #ss-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(760px,96vw);max-height:92vh;overflow:auto;padding:16px;color:#e2e8f0;font-size:12px}
    #ss-box h3{margin:0 0 8px;font-size:15px;display:flex;align-items:center;gap:8px}
    #ss-box h3 .x{margin-left:auto;cursor:pointer;color:#94a3b8;font-size:18px}
    .ss-bar{display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap}
    .ss-bar select,.ss-bar button{background:#1e293b;border:1px solid #334155;color:#cbd5e1;border-radius:5px;padding:5px 10px;cursor:pointer;font-size:11px}
    #ss-run{background:rgba(251,191,36,.18);border-color:#fbbf24;color:#fbbf24;font-weight:700}
    #ss-clear{border-color:#7f1d1d;color:#fca5a5}
    #ss-code{width:100%;box-sizing:border-box;height:150px;background:#060A12;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:10px;font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.5;resize:vertical}
    #ss-msg{font-size:11px;color:#94a3b8;margin:6px 0;min-height:14px}
    .ss-help{font-size:10px;color:#64748b;background:#0b1220;border:1px solid #1e293b;border-radius:6px;padding:7px 9px;margin:6px 0;line-height:1.6}
    .ss-help code{color:#fbbf24}
    .ss-stats{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin:8px 0}
    .ss-stat{background:#0b1220;border:1px solid #1e293b;border-radius:6px;padding:6px}
    .ss-sl{font-size:9px;color:#64748b}.ss-sv{font-size:13px;font-weight:800;margin-top:2px}
    .ss-sv.up{color:#22c55e}.ss-sv.dn{color:#ef4444}
    #ss-curve{border:1px solid #1e293b;border-radius:6px;background:#060A12;margin-top:6px}`;
    document.head.appendChild(s);
  }

  function open() {
    style();
    let m = document.getElementById('ss-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'ss-modal';
      m.innerHTML = `<div id="ss-box">
        <h3>📝 策略腳本 (DSL) <span class="x" onclick="window.stratScriptClose&&stratScriptClose()">×</span></h3>
        <div class="ss-bar">
          <select id="ss-ex"><option value="">— 載入範例 —</option><option value="golden">均線黃金交叉+RSI</option><option value="rsi">RSI 超賣超買</option><option value="bb">布林通道</option></select>
          <button id="ss-run">▶ 執行回測</button>
          <button id="ss-clear">清除主圖標記</button>
          <span style="color:#475569;font-size:10px">標的=目前個股與圖表區間</span>
        </div>
        <textarea id="ss-code" spellcheck="false"></textarea>
        <div class="ss-help">函式：<code>sma/ema/rsi/highest/lowest(來源,期數)</code>、<code>crossover/crossunder(a,b)</code>、<code>k() d() macd() macdsig() macdhist()</code>、<code>bbupper/bbmid/bblower(期數,標準差)</code>、<code>abs()</code>。<br>變數：<code>close open high low volume</code>。運算：<code>+ - * / &gt; &lt; &gt;= &lt;= == != and or not</code>。必須定義 <code>buy = ...</code>(可選 <code>sell = ...</code>)；<code>plot a, b</code> 疊到主圖。不用 sell 時，部位持有到資料末端(可純看 plot)。</div>
        <div id="ss-msg"></div>
        <div id="ss-result"></div>
      </div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
      m.querySelector('#ss-run').onclick = run;
      m.querySelector('#ss-clear').onclick = () => { clearPlots(); if (typeof S !== 'undefined' && S.chartSeries) try { S.chartSeries.setMarkers([]); } catch {} };
      m.querySelector('#ss-ex').onchange = e => { if (e.target.value && EXAMPLES[e.target.value]) document.getElementById('ss-code').value = EXAMPLES[e.target.value]; };
    }
    if (!document.getElementById('ss-code').value.trim()) document.getElementById('ss-code').value = EXAMPLES.golden;
    m.style.display = 'flex';
  }
  function close() { const m = document.getElementById('ss-modal'); if (m) m.style.display = 'none'; }

  window.stratScriptOpen = open;
  window.stratScriptClose = close;
})();

// ============================================================
// Stock Terminal v3.9 — 價差 / 比值圖 (Spread / Ratio Charts)
// ------------------------------------------------------------
// 輸入數學式繪製合成序列，看相對強弱 / 溢價差：
//   2330/2303        台積電 ÷ 聯電 (相對強弱)
//   2330-TSM*TWD=X   台積電 - (TSM ADR × 美元匯率) 溢價差
//   ^TWII/^SOX       台股加權 ÷ 費半
// 解析法：自寫 tokenizer + 遞迴下降解析器（不用 eval），抓出代號 →
//   /yf/batch 取各檔收盤、對齊共同時間軸 → 逐點套公式 → line series。
// 合成商品僅供分析，不可下單 / 不進自選。工具列 📊 價差。
// 架構守則：狀態用裸 S（僅讀 S.mkt 推測市場）；對外只掛 window.spread*。
// ============================================================
(function () {
  'use strict';
  const SRV = (typeof window !== 'undefined' && window.SERVER)
    ? window.SERVER
    : (typeof SERVER !== 'undefined' ? SERVER : 'http://localhost:18432');

  const RANGES = [
    { key: '1mo', lbl: '1月', range: '1mo', interval: '1d' },
    { key: '3mo', lbl: '3月', range: '3mo', interval: '1d' },
    { key: '6mo', lbl: '6月', range: '6mo', interval: '1d' },
    { key: '1y', lbl: '1年', range: '1y', interval: '1d' },
    { key: '2y', lbl: '2年', range: '2y', interval: '1d' },
    { key: '5y', lbl: '5年', range: '5y', interval: '1d' },
  ];
  let rgKey = '6mo';
  let chart = null, lineS = null;
  const tzOff = () => -new Date().getTimezoneOffset() * 60;

  const isTwCode = s => /^\d{3,6}[A-Z]?$/.test(s);
  // 代號 → yf ticker（4~6 碼純數字 → .TW；其餘原樣，如 TSM / ^TWII / TWD=X）
  function toYf(tok) {
    if (isTwCode(tok)) return tok + '.TW';
    return tok;
  }

  // ---------- Tokenizer ----------
  // 數字：含小數的純數字(且非 3~6 碼台股代號) 視為常數；其餘字母/^/=/. 視為代號
  function tokenize(expr) {
    const out = [];
    let i = 0;
    const symRe = /[A-Za-z0-9_^.=]/;
    while (i < expr.length) {
      const ch = expr[i];
      if (ch === ' ' || ch === '\t') { i++; continue; }
      if ('+-*/()'.includes(ch)) { out.push({ t: 'op', v: ch }); i++; continue; }
      if (symRe.test(ch)) {
        let j = i; let buf = '';
        while (j < expr.length && symRe.test(expr[j])) { buf += expr[j]; j++; }
        i = j;
        // 判斷常數 vs 代號
        if (/^\d+(\.\d+)?$/.test(buf) && !isTwCode(buf)) {
          out.push({ t: 'num', v: parseFloat(buf) });
        } else if (/^\d+\.\d+$/.test(buf)) {
          out.push({ t: 'num', v: parseFloat(buf) });
        } else {
          out.push({ t: 'sym', v: buf.toUpperCase() });
        }
        continue;
      }
      throw new Error('無法解析字元: ' + ch);
    }
    return out;
  }

  // ---------- 遞迴下降解析 → AST function(ctx) ----------
  // ctx = { vals: {SYM: number} }；回傳數值或 null(缺值)
  function parse(tokens) {
    let pos = 0;
    const peek = () => tokens[pos];
    const eat = () => tokens[pos++];
    const syms = new Set();

    function expr() {
      let node = term();
      while (peek() && peek().t === 'op' && (peek().v === '+' || peek().v === '-')) {
        const op = eat().v; const rhs = term();
        const l = node, r = rhs;
        node = ctx => { const a = l(ctx), b = r(ctx); if (a == null || b == null) return null; return op === '+' ? a + b : a - b; };
      }
      return node;
    }
    function term() {
      let node = factor();
      while (peek() && peek().t === 'op' && (peek().v === '*' || peek().v === '/')) {
        const op = eat().v; const rhs = factor();
        const l = node, r = rhs;
        node = ctx => { const a = l(ctx), b = r(ctx); if (a == null || b == null) return null; if (op === '/') return b === 0 ? null : a / b; return a * b; };
      }
      return node;
    }
    function factor() {
      const tk = peek();
      if (!tk) throw new Error('公式不完整');
      if (tk.t === 'op' && tk.v === '-') { eat(); const f = factor(); return ctx => { const v = f(ctx); return v == null ? null : -v; }; }
      if (tk.t === 'op' && tk.v === '(') {
        eat(); const e = expr();
        if (!peek() || peek().v !== ')') throw new Error('缺少 )');
        eat(); return e;
      }
      if (tk.t === 'num') { eat(); const n = tk.v; return () => n; }
      if (tk.t === 'sym') { eat(); const s = tk.v; syms.add(s); return ctx => { const v = ctx.vals[s]; return (v == null || !isFinite(v)) ? null : v; }; }
      throw new Error('非預期符號: ' + tk.v);
    }
    const fn = expr();
    if (pos < tokens.length) throw new Error('多餘符號: ' + tokens[pos].v);
    return { fn, syms: [...syms] };
  }

  // ---------- 抓資料並對齊 ----------
  async function fetchSeries(syms) {
    const r = RANGES.find(x => x.key === rgKey) || RANGES.find(x => x.key === '6mo');
    const yfMap = {}; syms.forEach(s => yfMap[s] = toYf(s));
    const url = `${SRV}/yf/batch?syms=${encodeURIComponent(Object.values(yfMap).join(','))}&range=${r.range}&interval=${r.interval}`;
    const data = await fetch(url, { cache: 'no-store' }).then(x => x.ok ? x.json() : {});
    // 每個代號 → Map<time, close>
    const perSym = {};
    for (const s of syms) {
      const key = yfMap[s];
      const res = data[key] && data[key].chart && data[key].chart.result && data[key].chart.result[0];
      const m = new Map();
      if (res) {
        const ts = res.timestamp || [];
        const cl = (res.indicators && res.indicators.quote && res.indicators.quote[0] && res.indicators.quote[0].close) || [];
        for (let i = 0; i < Math.min(ts.length, cl.length); i++) if (cl[i] != null && isFinite(cl[i]) && ts[i] != null) m.set(ts[i], cl[i]);
      }
      perSym[s] = m;
    }
    return perSym;
  }

  async function run() {
    const inp = document.getElementById('sp-input');
    const msg = document.getElementById('sp-msg');
    const body = document.getElementById('sp-chart');
    if (!inp || !body) return;
    const raw = inp.value.trim();
    if (!raw) { msg.textContent = '請輸入公式，例如 2330/2303'; return; }
    let ast;
    try { ast = parse(tokenize(raw)); }
    catch (e) { msg.textContent = '公式錯誤：' + e.message; return; }
    if (!ast.syms.length) { msg.textContent = '公式需至少含一個代號'; return; }
    msg.textContent = '載入中… (' + ast.syms.join(', ') + ')';
    let perSym;
    try { perSym = await fetchSeries(ast.syms); }
    catch (e) { msg.textContent = '抓取失敗：' + e.message; return; }

    // 共同時間軸 = 第一個代號的時間 ∩ 其他代號
    const base = perSym[ast.syms[0]];
    if (!base || !base.size) { msg.textContent = '查無資料：' + ast.syms[0]; return; }
    const times = [...base.keys()].sort((a, b) => a - b);
    const out = [];
    for (const t of times) {
      const vals = {};
      let ok = true;
      for (const s of ast.syms) { const v = perSym[s].get(t); if (v == null) { ok = false; break; } vals[s] = v; }
      if (!ok) continue;
      const val = ast.fn({ vals });
      if (val == null || !isFinite(val)) continue;
      out.push({ time: t + tzOff(), value: val });
    }
    if (!out.length) { msg.textContent = '無重疊時間點可計算（不同市場交易日可能不一致）'; return; }

    // 繪圖
    if (chart) { try { chart.remove(); } catch {} chart = null; }
    chart = LightweightCharts.createChart(body, {
      width: body.clientWidth, height: body.clientHeight,
      layout: { background: { color: '#060A12' }, textColor: '#5A6A82' },
      grid: { vertLines: { color: '#0F1A2B' }, horzLines: { color: '#0F1A2B' } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#1A2740' },
      timeScale: { borderColor: '#1A2740', timeVisible: false, rightOffset: 2 },
    });
    lineS = chart.addLineSeries({ color: '#FBBF24', lineWidth: 2, priceLineVisible: true, lastValueVisible: true });
    lineS.setData(out);
    chart.timeScale().fitContent();

    const first = out[0].value, last = out[out.length - 1].value;
    const chg = first ? ((last - first) / Math.abs(first) * 100) : 0;
    const hi = Math.max(...out.map(o => o.value)), lo = Math.min(...out.map(o => o.value));
    msg.innerHTML = `<b style="color:#fbbf24">${raw}</b> &nbsp; 現值 <b>${last.toFixed(4)}</b> &nbsp; ` +
      `區間 <span class="${chg >= 0 ? 'sp-up' : 'sp-dn'}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span> &nbsp; ` +
      `高 ${hi.toFixed(3)} / 低 ${lo.toFixed(3)} &nbsp; <span style="color:#475569">(${out.length} 點 · 合成商品，僅供分析)</span>`;
  }

  function style() {
    if (document.getElementById('sp-style')) return;
    const s = document.createElement('style'); s.id = 'sp-style';
    s.textContent = `
    #sp-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #sp-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(860px,95vw);height:min(620px,92vh);display:flex;flex-direction:column;padding:14px;color:#e2e8f0;font-size:12px}
    #sp-box h3{margin:0 0 8px;font-size:15px;display:flex;align-items:center;gap:8px}
    #sp-box h3 .x{margin-left:auto;cursor:pointer;color:#94a3b8;font-size:18px}
    .sp-row{display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap}
    #sp-input{flex:1;min-width:220px;background:#0b1220;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:6px 9px;font-size:13px;font-family:'JetBrains Mono',monospace}
    .sp-row select{background:#0b1220;border:1px solid #334155;color:#cbd5e1;border-radius:6px;padding:5px}
    .sp-row button{background:rgba(251,191,36,.15);border:1px solid #fbbf24;color:#fbbf24;border-radius:6px;padding:6px 14px;cursor:pointer;font-weight:700}
    .sp-quick{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:6px}
    .sp-quick span{background:#1e293b;border:1px solid #334155;color:#94a3b8;border-radius:5px;padding:3px 8px;cursor:pointer;font-size:10px;font-family:monospace}
    .sp-quick span:hover{border-color:#fbbf24;color:#fbbf24}
    #sp-msg{font-size:11px;color:#94a3b8;min-height:16px;margin-bottom:6px}
    #sp-chart{flex:1;min-height:0;border:1px solid #1A2740;border-radius:6px;overflow:hidden}
    .sp-up{color:#ef4444}.sp-dn{color:#22c55e}`;
    document.head.appendChild(s);
  }

  const QUICK = ['2330/2303', '2330/^TWII', '^TWII/^SOX', '2454/2330', 'TSM/2330', 'NVDA/AMD'];

  function open() {
    style();
    let m = document.getElementById('sp-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'sp-modal';
      m.innerHTML = `<div id="sp-box">
        <h3>📊 價差 / 比值圖 <span class="x" onclick="window.spreadClose&&spreadClose()">×</span></h3>
        <div class="sp-row">
          <input id="sp-input" placeholder="輸入公式：2330/2303、^TWII/^SOX、2330-TSM*TWD=X" />
          <select id="sp-range">${RANGES.map(r => `<option value="${r.key}"${r.key === rgKey ? ' selected' : ''}>${r.lbl}</option>`).join('')}</select>
          <button onclick="window.spreadRun&&spreadRun()">繪製</button>
        </div>
        <div class="sp-quick">${QUICK.map(q => `<span data-q="${q}">${q}</span>`).join('')}</div>
        <div id="sp-msg">支援 + - * / 與括號；4~6 碼純數字視為台股(自動加 .TW)，TSM/^TWII/TWD=X 等原樣。</div>
        <div id="sp-chart"></div>
      </div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
      m.querySelector('#sp-range').addEventListener('change', e => { rgKey = e.target.value; if (document.getElementById('sp-input').value.trim()) run(); });
      m.querySelector('#sp-input').addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
      m.querySelectorAll('.sp-quick span').forEach(el => el.onclick = () => { document.getElementById('sp-input').value = el.dataset.q; run(); });
    }
    m.style.display = 'flex';
    setTimeout(() => { const i = document.getElementById('sp-input'); if (i) i.focus(); }, 50);
  }
  function close() {
    const m = document.getElementById('sp-modal'); if (m) m.style.display = 'none';
    if (chart) { try { chart.remove(); } catch {} chart = null; }
  }

  window.spreadOpen = open;
  window.spreadClose = close;
  window.spreadRun = run;
})();

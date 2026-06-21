// ============================================================
// Stock Terminal v3.9 — 進階畫線工具 + 雲端記憶 (Drawing Tools)
// ------------------------------------------------------------
// lightweight-charts 原生不支援任意斜線，故在圖上疊一層 <canvas> 自繪：
//   趨勢線 / 水平線 / 垂直線 / 斐波那契回撤 / 矩形 / 平行通道 / 文字標記。
//   錨點存「time + price」(非像素) → 換區間/裝置可還原。
//   座標換算：timeScale().timeToCoordinate / series.priceToCoordinate。
//   存 localStorage(draw_v3) 為主，並 best-effort 同步 server /draw/<sym>
//   (沒端點也能完整運作)。工具列 ✏ 畫線。
// 架構守則：狀態用裸 S(S.chart/S.chartSeries/S.sym/S.tzOffset)；對外 window.drawTools*。
// ============================================================
(function () {
  'use strict';
  const SRV = (typeof window !== 'undefined' && window.SERVER)
    ? window.SERVER
    : (typeof SERVER !== 'undefined' ? SERVER : 'http://localhost:18432');

  const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  const COLORS = ['#FBBF24', '#67E8F9', '#F472B6', '#A3E635', '#FB923C', '#E2E8F0'];
  // 各工具所需點擊數
  const NEED = { trend: 2, hline: 1, vline: 1, fib: 2, rect: 2, channel: 3, text: 1 };
  const TOOL_LBL = { select: '🖱 選取', trend: '╱ 趨勢線', hline: '― 水平', vline: '│ 垂直', fib: '𝑭 斐波', rect: '▭ 矩形', channel: '▥ 通道', text: '🏷 文字' };

  let store = {};          // {sym: [obj,...]}
  try { store = JSON.parse(localStorage.getItem('draw_v3') || '{}'); } catch { store = {}; }

  let mode = 'off';        // 'off' | 'select' | 工具名
  let color = COLORS[0];
  let pending = null;      // 建立中的物件 {type, pts:[{t,p}]}
  let mouse = null;        // 目前滑鼠 {x,y} (預覽用)
  let sel = null;          // 選取中 {obj, anchor} anchor: 'a'|'b'|'c'|null
  let drag = null;         // 拖曳中 {obj, anchor}
  let rafPending = false;

  function curSym() { return (typeof S !== 'undefined' && S.sym) ? S.sym : ''; }
  function objs() { const s = curSym(); if (!s) return []; return store[s] || (store[s] = []); }
  function saveLocal() { try { localStorage.setItem('draw_v3', JSON.stringify(store)); } catch {} }
  function saveAll() { saveLocal(); cloudSave(); }

  // ---- 雲端 best-effort ----
  async function cloudSave() {
    const s = curSym(); if (!s) return;
    try {
      await fetch(`${SRV}/draw/${encodeURIComponent(s)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ objects: store[s] || [] }),
      });
    } catch {}
  }
  async function cloudLoad(sym) {
    try {
      const r = await fetch(`${SRV}/draw/${encodeURIComponent(sym)}`, { cache: 'no-store' });
      if (!r.ok) return null;
      const j = await r.json();
      return Array.isArray(j.objects) ? j.objects : null;
    } catch { return null; }
  }

  // ---- 座標換算 ----
  function ts() { return (typeof S !== 'undefined' && S.chart) ? S.chart.timeScale() : null; }
  function X(t) { const s = ts(); if (!s) return null; const x = s.timeToCoordinate(t); return x == null ? null : x; }
  function Y(p) { if (typeof S === 'undefined' || !S.chartSeries) return null; const y = S.chartSeries.priceToCoordinate(p); return y == null ? null : y; }
  function tAt(x) { const s = ts(); if (!s) return null; const t = s.coordinateToTime(x); return t == null ? null : t; }
  function pAt(y) { if (typeof S === 'undefined' || !S.chartSeries) return null; const p = S.chartSeries.coordinateToPrice(y); return p == null ? null : p; }

  // ---- canvas ----
  function cv() { return document.getElementById('dt-canvas'); }
  function ensureCanvas() {
    const area = document.getElementById('chartarea');
    const wrap = document.getElementById('chart-wrap');
    if (!area || !wrap) return null;
    let c = cv();
    if (!c) {
      c = document.createElement('canvas'); c.id = 'dt-canvas';
      c.style.cssText = 'position:absolute;top:0;left:0;z-index:4;pointer-events:none';
      area.appendChild(c);
      c.addEventListener('mousedown', onDown);
      c.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
      if (!area._dtRo) { area._dtRo = new ResizeObserver(() => { sizeCanvas(); scheduleRedraw(); }); area._dtRo.observe(wrap); }
    }
    sizeCanvas();
    return c;
  }
  function sizeCanvas() {
    const c = cv(); const wrap = document.getElementById('chart-wrap'); if (!c || !wrap) return;
    const w = wrap.clientWidth, h = wrap.clientHeight, dpr = window.devicePixelRatio || 1;
    c.style.width = w + 'px'; c.style.height = h + 'px';
    c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    const ctx = c.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function scheduleRedraw() { if (rafPending) return; rafPending = true; requestAnimationFrame(() => { rafPending = false; redraw(); }); }

  // ---- 繪製 ----
  function redraw() {
    const c = cv(); if (!c) return;
    const ctx = c.getContext('2d');
    const w = c.clientWidth, h = c.clientHeight;
    ctx.clearRect(0, 0, w, h);
    ctx.font = '10px JetBrains Mono, monospace';
    const list = objs();
    for (const o of list) drawObj(ctx, o, w, h, o === (sel && sel.obj));
    if (pending) drawPending(ctx, w, h);
  }

  function drawObj(ctx, o, w, h, selected) {
    ctx.lineWidth = selected ? 2 : 1.2;
    ctx.strokeStyle = o.color || color;
    ctx.fillStyle = o.color || color;
    if (o.type === 'hline') {
      const y = Y(o.p); if (y == null) return;
      dash(ctx, true); line(ctx, 0, y, w, y); dash(ctx, false);
      label(ctx, w - 4, y, o.p.toFixed(2), 'right', 'bottom');
    } else if (o.type === 'vline') {
      const x = X(o.t); if (x == null) return;
      dash(ctx, true); line(ctx, x, 0, x, h); dash(ctx, false);
    } else if (o.type === 'trend') {
      const x1 = X(o.a.t), y1 = Y(o.a.p), x2 = X(o.b.t), y2 = Y(o.b.p);
      if (x1 == null || y1 == null || x2 == null || y2 == null) return;
      line(ctx, x1, y1, x2, y2);
      if (selected) { handle(ctx, x1, y1); handle(ctx, x2, y2); }
    } else if (o.type === 'rect') {
      const x1 = X(o.a.t), y1 = Y(o.a.p), x2 = X(o.b.t), y2 = Y(o.b.p);
      if (x1 == null || y1 == null || x2 == null || y2 == null) return;
      ctx.globalAlpha = 0.08; ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)); ctx.globalAlpha = 1;
      ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
      if (selected) { handle(ctx, x1, y1); handle(ctx, x2, y2); }
    } else if (o.type === 'fib') {
      const x1 = X(o.a.t), x2 = X(o.b.t);
      const xa = (x1 == null ? 0 : x1), xb = (x2 == null ? w : x2);
      const left = Math.min(xa, xb), right = Math.max(xa, xb);
      for (const lv of FIB) {
        const price = o.a.p + (o.b.p - o.a.p) * lv;
        const y = Y(price); if (y == null) continue;
        ctx.globalAlpha = 0.9;
        line(ctx, left, y, right, y);
        label(ctx, left + 2, y, (lv * 100).toFixed(1) + '%  ' + price.toFixed(2), 'left', 'bottom');
      }
      ctx.globalAlpha = 1;
      if (selected) { const ya = Y(o.a.p), yb = Y(o.b.p); if (ya != null) handle(ctx, left, ya); if (yb != null) handle(ctx, right, yb); }
    } else if (o.type === 'channel') {
      const x1 = X(o.a.t), y1 = Y(o.a.p), x2 = X(o.b.t), y2 = Y(o.b.p);
      if (x1 == null || y1 == null || x2 == null || y2 == null) return;
      line(ctx, x1, y1, x2, y2);
      // 平行：用第三點的價差平移
      const span = (o.b.t - o.a.t) || 1;
      const lineP = o.a.p + (o.b.p - o.a.p) * ((o.c.t - o.a.t) / span);
      const dp = o.c.p - lineP;
      const y1b = Y(o.a.p + dp), y2b = Y(o.b.p + dp);
      if (y1b != null && y2b != null) {
        dash(ctx, true); line(ctx, x1, y1b, x2, y2b); dash(ctx, false);
        ctx.globalAlpha = 0.05; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.lineTo(x2, y2b); ctx.lineTo(x1, y1b); ctx.closePath(); ctx.fill(); ctx.globalAlpha = 1;
      }
      if (selected) { handle(ctx, x1, y1); handle(ctx, x2, y2); }
    } else if (o.type === 'text') {
      const x = X(o.a.t), y = Y(o.a.p); if (x == null || y == null) return;
      ctx.font = '12px JetBrains Mono, monospace';
      const tw = ctx.measureText(o.text).width;
      ctx.globalAlpha = 0.85; ctx.fillStyle = '#0b1220'; ctx.fillRect(x - 2, y - 13, tw + 6, 16); ctx.globalAlpha = 1;
      ctx.fillStyle = o.color || color; ctx.fillText(o.text, x + 1, y);
      if (selected) handle(ctx, x, y);
      ctx.font = '10px JetBrains Mono, monospace';
    }
  }

  function drawPending(ctx, w, h) {
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1.2;
    const pts = pending.pts;
    const cur = mouse ? { x: mouse.x, y: mouse.y } : null;
    const P = i => { const p = pts[i]; return { x: X(p.t), y: Y(p.p) }; };
    if (pending.type === 'trend' || pending.type === 'channel' || pending.type === 'rect' || pending.type === 'fib') {
      if (pts.length >= 1 && cur) {
        const a = P(0);
        if (a.x != null) {
          if (pending.type === 'rect') { dash(ctx, true); ctx.strokeRect(Math.min(a.x, cur.x), Math.min(a.y, cur.y), Math.abs(cur.x - a.x), Math.abs(cur.y - a.y)); dash(ctx, false); }
          else { dash(ctx, true); line(ctx, a.x, a.y, cur.x, cur.y); dash(ctx, false); }
        }
      }
    }
    pts.forEach((_, i) => { const p = P(i); if (p.x != null) handle(ctx, p.x, p.y); });
  }

  function line(ctx, x1, y1, x2, y2) { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); }
  function handle(ctx, x, y) { ctx.fillRect(x - 3, y - 3, 6, 6); }
  function dash(ctx, on) { ctx.setLineDash(on ? [5, 4] : []); }
  function label(ctx, x, y, txt, ha, va) {
    ctx.save();
    const tw = ctx.measureText(txt).width;
    let bx = x; if (ha === 'right') bx = x - tw;
    ctx.globalAlpha = 0.75; ctx.fillStyle = '#0b1220'; ctx.fillRect(bx - 2, y - 11, tw + 4, 12); ctx.globalAlpha = 1;
    ctx.fillStyle = '#cbd5e1'; ctx.textAlign = ha === 'right' ? 'right' : 'left'; ctx.textBaseline = 'alphabetic';
    ctx.fillText(txt, x, y - 1); ctx.restore();
  }

  // ---- 互動 ----
  function evtXY(e) { const c = cv(); const r = c.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }

  function onDown(e) {
    if (mode === 'off') return;
    const { x, y } = evtXY(e);
    if (mode === 'select') {
      const hit = hitTest(x, y);
      sel = hit;
      if (hit && hit.anchor) drag = hit;
      scheduleRedraw();
      return;
    }
    // 建立工具
    const t = tAt(x), p = pAt(y);
    if (t == null || p == null) return;
    if (mode === 'text') {
      const txt = prompt('文字標記內容：', '頭肩頂');
      if (txt) { objs().push({ type: 'text', a: { t, p }, text: txt, color }); saveAll(); }
      scheduleRedraw(); return;
    }
    if (!pending) pending = { type: mode, pts: [] };
    pending.pts.push({ t, p });
    if (pending.pts.length >= NEED[mode]) finalizePending();
    scheduleRedraw();
  }

  function onMove(e) {
    mouse = evtXY(e);
    if (drag) {
      const t = tAt(mouse.x), p = pAt(mouse.y);
      const o = drag.obj;
      if (drag.anchor === 'p') { if (p != null) o.p = p; }
      else if (drag.anchor === 't') { if (t != null) o.t = t; }
      else { const a = o[drag.anchor]; if (a) { if (t != null) a.t = t; if (p != null) a.p = p; } }
      scheduleRedraw();
      return;
    }
    if (mode !== 'off' && mode !== 'select') scheduleRedraw();
  }
  function onUp() { if (drag) { drag = null; saveAll(); } }

  function finalizePending() {
    const pts = pending.pts, type = pending.type;
    let o = null;
    if (type === 'hline') o = { type, p: pts[0].p, color };
    else if (type === 'vline') o = { type, t: pts[0].t, color };
    else if (type === 'trend' || type === 'fib' || type === 'rect') o = { type, a: pts[0], b: pts[1], color };
    else if (type === 'channel') o = { type, a: pts[0], b: pts[1], c: pts[2], color };
    if (o) { objs().push(o); saveAll(); }
    pending = null;
  }

  // 命中測試
  function hitTest(x, y) {
    const list = objs();
    const near = 7;
    for (let k = list.length - 1; k >= 0; k--) {
      const o = list[k];
      if (o.type === 'hline') { const yy = Y(o.p); if (yy != null && Math.abs(y - yy) < near) return { obj: o, anchor: 'p' }; }
      else if (o.type === 'vline') { const xx = X(o.t); if (xx != null && Math.abs(x - xx) < near) return { obj: o, anchor: 't' }; }
      else if (o.type === 'text') { const xx = X(o.a.t), yy = Y(o.a.p); if (xx != null && yy != null && Math.abs(x - xx) < 40 && Math.abs(y - yy) < 12) return { obj: o, anchor: 'a' }; }
      else if (o.type === 'trend' || o.type === 'channel' || o.type === 'rect' || o.type === 'fib') {
        const xa = X(o.a.t), ya = Y(o.a.p), xb = X(o.b.t), yb = Y(o.b.p);
        if (xa != null && ya != null && Math.hypot(x - xa, y - ya) < near) return { obj: o, anchor: 'a' };
        if (xb != null && yb != null && Math.hypot(x - xb, y - yb) < near) return { obj: o, anchor: 'b' };
        if (o.type === 'channel' && o.c) { const xc = X(o.c.t), yc = Y(o.c.p); if (xc != null && yc != null && Math.hypot(x - xc, y - yc) < near) return { obj: o, anchor: 'c' }; }
        if ((o.type === 'trend' || o.type === 'channel') && xa != null && xb != null && distSeg(x, y, xa, ya, xb, yb) < near) return { obj: o, anchor: null };
        if (o.type === 'rect' && xa != null && xb != null) {
          const L = Math.min(xa, xb), R = Math.max(xa, xb), T = Math.min(ya, yb), B = Math.max(ya, yb);
          if ((Math.abs(x - L) < near || Math.abs(x - R) < near) && y > T - near && y < B + near) return { obj: o, anchor: null };
          if ((Math.abs(y - T) < near || Math.abs(y - B) < near) && x > L - near && x < R + near) return { obj: o, anchor: null };
        }
        if (o.type === 'fib') { for (const lv of FIB) { const yy = Y(o.a.p + (o.b.p - o.a.p) * lv); if (yy != null && Math.abs(y - yy) < near) return { obj: o, anchor: null }; } }
      }
    }
    return null;
  }
  function distSeg(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1; const l2 = dx * dx + dy * dy;
    let t = l2 ? ((px - x1) * dx + (py - y1) * dy) / l2 : 0; t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }

  function deleteSel() {
    if (!sel) return;
    const list = objs(); const i = list.indexOf(sel.obj);
    if (i >= 0) { list.splice(i, 1); sel = null; saveAll(); scheduleRedraw(); }
  }
  function clearSym() { const s = curSym(); if (!s) return; if (!confirm('清除 ' + s + ' 的所有畫線？')) return; store[s] = []; sel = null; saveAll(); scheduleRedraw(); }

  // ---- 模式 / canvas pointer-events ----
  function setMode(m) {
    mode = m; pending = null;
    const c = cv(); if (c) c.style.pointerEvents = (m === 'off') ? 'none' : 'auto';
    updateBar();
    scheduleRedraw();
  }

  // ---- 工具列 ----
  function bar() { return document.getElementById('dt-bar'); }
  function updateBar() {
    const b = bar(); if (!b) return;
    b.querySelectorAll('[data-tool]').forEach(x => x.classList.toggle('on', x.dataset.tool === mode));
    b.querySelectorAll('[data-color]').forEach(x => x.classList.toggle('on', x.dataset.color === color));
  }
  function buildBar() {
    let b = bar(); if (b) { b.style.display = 'flex'; return; }
    style();
    b = document.createElement('div'); b.id = 'dt-bar';
    const tools = ['select', 'trend', 'hline', 'vline', 'fib', 'rect', 'channel', 'text'];
    b.innerHTML =
      tools.map(t => `<button data-tool="${t}" title="${TOOL_LBL[t]}">${TOOL_LBL[t]}</button>`).join('') +
      '<span class="dt-sep"></span>' +
      COLORS.map(c => `<button class="dt-sw" data-color="${c}" style="background:${c}" title="${c}"></button>`).join('') +
      '<span class="dt-sep"></span>' +
      `<button data-act="del" title="刪除選取 (Del)">🗑</button>` +
      `<button data-act="clear" title="清除本商品全部">清除</button>` +
      `<button class="dt-x" data-act="close">✕ 關閉</button>`;
    document.getElementById('chartarea').appendChild(b);
    b.querySelectorAll('[data-tool]').forEach(x => x.onclick = () => setMode(x.dataset.tool));
    b.querySelectorAll('[data-color]').forEach(x => x.onclick = () => { color = x.dataset.color; if (sel && sel.obj) { sel.obj.color = color; saveAll(); } updateBar(); scheduleRedraw(); });
    b.querySelector('[data-act="del"]').onclick = deleteSel;
    b.querySelector('[data-act="clear"]').onclick = clearSym;
    b.querySelector('[data-act="close"]').onclick = close;
    updateBar();
  }

  function style() {
    if (document.getElementById('dt-style')) return;
    const s = document.createElement('style'); s.id = 'dt-style';
    s.textContent = `
    #dt-bar{position:absolute;top:6px;left:50%;transform:translateX(-50%);z-index:31;display:flex;gap:4px;align-items:center;background:rgba(11,18,32,.94);border:1px solid #334155;border-radius:8px;padding:4px 7px;flex-wrap:wrap;max-width:94%}
    #dt-bar button{background:#1e293b;border:1px solid #334155;color:#cbd5e1;border-radius:5px;padding:3px 8px;cursor:pointer;font-size:11px}
    #dt-bar button.on{background:rgba(251,191,36,.2);border-color:#fbbf24;color:#fbbf24}
    #dt-bar .dt-sw{width:18px;height:18px;padding:0;border-radius:4px}
    #dt-bar .dt-sw.on{outline:2px solid #fff;outline-offset:1px}
    #dt-bar .dt-sep{width:1px;height:18px;background:#334155;margin:0 2px}
    #dt-bar .dt-x{background:#7f1d1d;border-color:#991b1b;color:#fecaca}`;
    document.head.appendChild(s);
  }

  // ---- 與主圖整合 ----
  function attach() {
    ensureCanvas();
    const s = ts();
    if (s && !s._dtSub) {
      s._dtSub = true;
      s.subscribeVisibleLogicalRangeChange(scheduleRedraw);
      s.subscribeVisibleTimeRangeChange && s.subscribeVisibleTimeRangeChange(scheduleRedraw);
    }
    scheduleRedraw();
  }

  // 每次 renderChart 後重新 attach (S.chart 會被重建)
  (function patch() {
    if (typeof window.renderChart !== 'function') return setTimeout(patch, 120);
    const orig = window.renderChart;
    window.renderChart = function () {
      const r = orig.apply(this, arguments);
      setTimeout(attach, 70);
      return r;
    };
  })();

  // 切股 → 載入該股雲端畫線(若本機沒有)
  window.addEventListener('symLoaded', async (e) => {
    const sym = e && e.detail && e.detail.sym; if (!sym) return;
    setTimeout(attach, 80);
    if (!store[sym] || !store[sym].length) {
      const cloud = await cloudLoad(sym);
      if (cloud && cloud.length) { store[sym] = cloud; saveLocal(); scheduleRedraw(); }
    }
  });

  // Del 鍵刪除選取 (僅畫線開啟且非輸入框)
  document.addEventListener('keydown', e => {
    if (mode === 'off') return;
    const tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target.isContentEditable) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { if (sel) { e.preventDefault(); deleteSel(); } }
    else if (e.key === 'Escape') { if (pending) { pending = null; scheduleRedraw(); } }
  });

  function open() {
    ensureCanvas();
    buildBar();
    if (mode === 'off') setMode('select');
    else updateBar();
    attach();
  }
  function close() {
    setMode('off');
    const b = bar(); if (b) b.style.display = 'none';
  }

  window.drawToolsOpen = open;
  window.drawToolsClose = close;
  window.drawToolsTrend = () => { open(); setMode('trend'); };
  window.drawToolsHLine = () => { open(); setMode('hline'); };

  // 程式化新增畫線物件 (供 Wizard 等模組用)。opts.replaceSource 會先清掉同 source 的舊物件(冪等)。
  window.drawToolsAdd = function (sym, arr, opts) {
    if (!sym || !Array.isArray(arr) || !arr.length) return;
    sym = String(sym).toUpperCase();
    if (!store[sym]) store[sym] = [];
    if (opts && opts.replaceSource) store[sym] = store[sym].filter(o => o.source !== opts.replaceSource);
    arr.forEach(o => store[sym].push(o));
    saveLocal();
    try {
      fetch(`${SRV}/draw/${encodeURIComponent(sym)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ objects: store[sym] }),
      });
    } catch {}
    if (curSym() === sym) { ensureCanvas(); scheduleRedraw(); }
  };
})();

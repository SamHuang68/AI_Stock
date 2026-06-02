// ============================================================
// Stock Terminal v3.8 — 版面：可拖拉左右分隔 (線型 vs 功能分析)
// ------------------------------------------------------------
// #splitter 在 #left(線型) 與 #right(功能分析) 之間，拖曳調整寬度。
// 寬度存 localStorage，重開沿用。拖曳後觸發 chart resize + 量價重繪。
// #splitter div + CSS 已寫在 stock_terminal.html (v1 base)。
// ============================================================
(function () {
  'use strict';
  const LS_KEY = 'stockTerminal.rightWidth';
  const MIN = 280;

  function applyWidth(px) {
    const body = document.getElementById('body');
    if (!body) return;
    const max = Math.max(MIN, body.clientWidth * 0.75);
    px = Math.min(max, Math.max(MIN, px));
    document.documentElement.style.setProperty('--right-w', px + 'px');
    try { localStorage.setItem(LS_KEY, String(Math.round(px))); } catch {}
    afterResize();
  }

  let _raf = 0;
  function afterResize() {
    if (_raf) return;
    _raf = requestAnimationFrame(() => {
      _raf = 0;
      try {
        if (typeof S !== 'undefined' && S.chart) {
          const w = document.getElementById('chart-wrap') || document.getElementById('chartarea');
          if (w && S.chart.resize) S.chart.resize(w.clientWidth, w.clientHeight);
        }
      } catch {}
      try { window.dispatchEvent(new Event('resize')); } catch {}
      try { if (window.VP && VP.enabled && window.drawVolumeProfile) drawVolumeProfile(); } catch {}
    });
  }

  function initSplitter() {
    const sp = document.getElementById('splitter');
    const body = document.getElementById('body');
    if (!sp || !body) return setTimeout(initSplitter, 300);

    // 還原儲存寬度
    let saved = parseInt(localStorage.getItem(LS_KEY) || '', 10);
    if (saved > 0) applyWidth(saved);

    let dragging = false;
    const onMove = e => {
      if (!dragging) return;
      const rect = body.getBoundingClientRect();
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      applyWidth(rect.right - clientX);
      e.preventDefault();
    };
    const onUp = () => {
      dragging = false;
      sp.classList.remove('dragging');
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      afterResize();
    };
    const onDown = e => {
      dragging = true;
      sp.classList.add('dragging');
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'col-resize';
      e.preventDefault();
    };
    sp.addEventListener('mousedown', onDown);
    sp.addEventListener('touchstart', onDown, { passive: false });
    window.addEventListener('mousemove', onMove);
    window.addEventListener('touchmove', onMove, { passive: false });
    window.addEventListener('mouseup', onUp);
    window.addEventListener('touchend', onUp);

    // 雙擊分隔條 → 重置成預設 340
    sp.addEventListener('dblclick', () => applyWidth(340));
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', initSplitter);
  else initSplitter();
})();

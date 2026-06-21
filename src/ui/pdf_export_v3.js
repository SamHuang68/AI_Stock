// ============================================================
// Stock Terminal v3.4 — Reverse PDF Generator (Plan → PDF)
// ------------------------------------------------------------
// 從 S.plans + Yahoo keystats 反向生成下周執行 PDF，
// 結構對齊原始輸入格式（總表 / 排序 / EPS-PE-PEG / 個股展望 / 總結）。
//
// 技術：html2canvas (HTML→canvas) + jsPDF (canvas→PDF)
//   ✓ 中文字型用瀏覽器原生 (繁中字無需嵌入)
//   ✓ A4 縱向，多頁切割
// ============================================================

(function (global) {
  'use strict';

  const HTML2CANVAS_URL = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
  const JSPDF_URL = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';

  // ─── Lazy CDN loaders ────────────────────────────────────
  let _libsPromise = null;
  function loadLibs() {
    if (_libsPromise) return _libsPromise;
    _libsPromise = Promise.all([loadScript(HTML2CANVAS_URL), loadScript(JSPDF_URL)]);
    return _libsPromise;
  }
  function loadScript(url) {
    return new Promise((resolve, reject) => {
      // Check if already loaded
      if (url.includes('html2canvas') && global.html2canvas) return resolve();
      if (url.includes('jspdf') && global.jspdf?.jsPDF) return resolve();
      const s = document.createElement('script');
      s.src = url;
      s.onload = resolve;
      s.onerror = () => reject(new Error('載入失敗: ' + url));
      document.head.appendChild(s);
    });
  }

  // ─── Format helpers ──────────────────────────────────────
  function fmtNum(v, dec=2) {
    if (v == null || !Number.isFinite(v)) return '—';
    return (+v).toFixed(dec);
  }
  function fmtZone(lo, hi) {
    if (Number.isFinite(lo) && Number.isFinite(hi)) return `${lo.toFixed(2)} ~ ${hi.toFixed(2)}`;
    if (Number.isFinite(lo)) return lo.toFixed(2);
    if (Number.isFinite(hi)) return hi.toFixed(2);
    return '—';
  }
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`;
  }
  function nextWeekStartStr() {
    const d = new Date();
    // 找下週一
    const day = d.getDay();
    const add = (day === 0) ? 1 : (8 - day);
    d.setDate(d.getDate() + add);
    return `${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`;
  }

  // ─── Build the HTML report ──────────────────────────────
  function buildReportHtml(plans, keystats) {
    const planList = Object.values(plans);
    if (planList.length === 0) return null;

    // Sort by role priority (主倉 > 動能 > 攻擊 > 觀察)
    const rolePriority = { '主倉': 0, '動能倉': 1, '攻擊倉': 2, '觀察倉': 3 };
    const sorted = [...planList].sort((a, b) =>
      (rolePriority[a.role] ?? 9) - (rolePriority[b.role] ?? 9));

    const reportDate = todayStr();
    const tradeDate = nextWeekStartStr();
    const symList = sorted.map(p => `${p.sym}`).join('、');

    // === Section 1: 下周執行總表 ===
    const totalsRows = sorted.map(p => `
      <tr>
        <td><b>${esc(p.sym)}</b></td>
        <td>${esc(p.role || '—')}</td>
        <td>${esc(p.longCondition || '—')}</td>
        <td>${fmtZone(p.buyZoneLow, p.buyZoneHigh)}</td>
        <td>${fmtNum(p.resistance)}</td>
        <td>${fmtNum(p.stopLoss)}${Number.isFinite(p.weakBreak) ? ` / ${fmtNum(p.weakBreak)}` : ''}</td>
      </tr>`).join('');

    // === Section 2: 操作排序 ===
    const orderHtml = sorted.map((p, i) => {
      const k = keystats[p.sym] || {};
      const reason = k.shortName ? ` (${esc(k.shortName)})` : '';
      return `<li><b>${esc(p.sym)}</b>${reason} — ${esc(p.role || '')}${p.longCondition ? '：' + esc(p.longCondition) : ''}</li>`;
    }).join('');

    // === Section 3: EPS/PE/PEG ===
    const pegRows = sorted.map(p => {
      const k = keystats[p.sym] || {};
      const pe = k.trailingPE;
      const eps = k.eps;
      const growth = k.earningsQuarterlyGrowth ?? k.revenueGrowth;
      const peg = k.pegRatio ?? (pe && growth > 0 ? pe / growth : null);
      return `
        <tr>
          <td><b>${esc(p.sym)}</b></td>
          <td>${k.shortName ? esc(k.shortName.slice(0,12)) : '—'}</td>
          <td style="text-align:right;">${fmtNum(pe, 1)}</td>
          <td style="text-align:right;">${fmtNum(eps, 2)}</td>
          <td style="text-align:right;">${growth != null ? growth.toFixed(0)+'%' : '—'}</td>
          <td style="text-align:right;">${fmtNum(peg, 2)}</td>
        </tr>`;
    }).join('');

    // === Section 4: 個股展望與執行細節 ===
    const detailHtml = sorted.map(p => `
      <div style="margin-bottom:14px;">
        <div style="font-size:14px;font-weight:700;color:#111;margin-bottom:4px;">${esc(p.sym)} <span style="font-size:11px;color:#555;font-weight:400;">— ${esc(p.role || '')}</span></div>
        ${p.outlook ? `<div style="font-size:11px;color:#444;margin-bottom:6px;line-height:1.7;"><b>展望：</b>${esc(p.outlook)}</div>` : ''}
        <div style="font-size:11px;color:#444;line-height:1.7;">
          <div><b>多方條件：</b>${esc(p.longCondition || '—')}</div>
          <div><b>可買區：</b>${fmtZone(p.buyZoneLow, p.buyZoneHigh)}</div>
          ${Number.isFinite(p.resistance) ? `<div><b>壓力：</b>${fmtNum(p.resistance)}（突破即追）</div>` : ''}
          ${Number.isFinite(p.stopLoss)   ? `<div><b>減碼：</b>${fmtNum(p.stopLoss)}</div>` : ''}
          ${Number.isFinite(p.weakBreak)  ? `<div><b>出場：</b>${fmtNum(p.weakBreak)}</div>` : ''}
        </div>
      </div>`).join('');

    return `
<div id="pdf-report-content" style="background:#fff;color:#1a1a1a;padding:32px 36px;width:780px;font-family:'PingFang TC','Microsoft JhengHei','PingFang SC',sans-serif;font-size:12px;line-height:1.6;">
  <h1 style="font-size:20px;margin:0 0 4px;color:#111;">${esc(symList)}：下周執行與基本面</h1>
  <div style="font-size:10px;color:#666;margin-bottom:20px;">
    交易日：${tradeDate} 起｜資料基準：${reportDate} (Stock Terminal v3.4 自動生成)<br>
    本文件是交易計畫與估值整理，不是投資建議。下周若開盤跳空或大盤轉弱，先等前 15~30 分鐘確認量價，再照表執行。
  </div>

  <h2 style="font-size:14px;border-bottom:1px solid #999;padding-bottom:4px;margin:18px 0 10px;">一、下周執行總表</h2>
  <table style="width:100%;border-collapse:collapse;font-size:11px;">
    <thead style="background:#f0f0f0;">
      <tr>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">股票</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">定位</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">多方條件</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">可買區</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">壓力</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">減碼/出場</th>
      </tr>
    </thead>
    <tbody>
      ${totalsRows.replace(/<td>/g, '<td style="border:1px solid #ccc;padding:6px;">')}
    </tbody>
  </table>

  <h2 style="font-size:14px;border-bottom:1px solid #999;padding-bottom:4px;margin:18px 0 10px;">二、操作排序（依角色優先）</h2>
  <ol style="margin:0 0 10px 24px;font-size:11px;line-height:1.8;">${orderHtml}</ol>

  <h2 style="font-size:14px;border-bottom:1px solid #999;padding-bottom:4px;margin:18px 0 10px;">三、EPS / PE / PEG 整理</h2>
  <table style="width:100%;border-collapse:collapse;font-size:11px;">
    <thead style="background:#f0f0f0;">
      <tr>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">代號</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">名稱</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:right;">PE</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:right;">EPS</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:right;">成長%</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:right;">PEG</th>
      </tr>
    </thead>
    <tbody>${pegRows.replace(/<td>/g, '<td style="border:1px solid #ccc;padding:6px;">')}</tbody>
  </table>
  <div style="font-size:9px;color:#888;margin-top:4px;">PE / EPS 來源：Yahoo Finance quoteSummary API。成長% 為 earningsQuarterlyGrowth 或 revenueGrowth。盤中需重新確認。</div>

  <h2 style="font-size:14px;border-bottom:1px solid #999;padding-bottom:4px;margin:18px 0 10px;">四、個股展望與執行細節</h2>
  ${detailHtml}

  <h2 style="font-size:14px;border-bottom:1px solid #999;padding-bottom:4px;margin:18px 0 10px;">五、總結</h2>
  <div style="font-size:11px;line-height:1.8;">
    <div><b>本期執行檔數：</b>${planList.length} 檔</div>
    <div><b>角色分佈：</b>${Object.entries(planList.reduce((a,p)=>{a[p.role||'未分']=(a[p.role||'未分']||0)+1;return a;},{})).map(([k,v])=>`${k} ${v}`).join('、')}</div>
    <div style="margin-top:8px;color:#666;font-size:10px;">風控口訣：支撐有守才買，壓力爆量過不了就先收。</div>
  </div>

  <div style="margin-top:24px;padding-top:8px;border-top:1px dotted #999;font-size:9px;color:#999;text-align:center;">
    Stock Terminal v3.4 · ${reportDate} 自動生成
  </div>
</div>`;
  }

  // ─── Fetch keystats for all plan symbols ────────────────
  async function fetchKeystatsForPlans(plans) {
    const out = {};
    const syms = Object.values(plans);
    const promises = syms.map(async (p) => {
      const yfsym = p.mkt === 'TW' ? p.sym + '.TW' : p.sym;
      try {
        const r = await fetch(`${global.SERVER || 'http://localhost:18432'}/keystats/${encodeURIComponent(yfsym)}`);
        if (!r.ok) return;
        out[p.sym] = await r.json();
      } catch {}
    });
    await Promise.all(promises);
    return out;
  }

  // ─── Main: generate PDF ─────────────────────────────────
  async function generate() {
    const plans = global.S?.plans;
    if (!plans || Object.keys(plans).length === 0) {
      alert('沒有計畫可匯出 — 請先建立計畫');
      return;
    }
    // Show progress
    const progress = createProgressOverlay();
    progress.update('載入 PDF 函式庫...');

    try {
      await loadLibs();
      progress.update('抓取基本面資料 (PE/EPS)...');
      const keystats = await fetchKeystatsForPlans(plans);

      progress.update('渲染報告...');
      const html = buildReportHtml(plans, keystats);
      if (!html) throw new Error('報告生成失敗');

      // Mount offscreen
      const container = document.createElement('div');
      container.style.cssText = 'position:fixed;left:-9999px;top:0;';
      container.innerHTML = html;
      document.body.appendChild(container);
      const content = container.querySelector('#pdf-report-content');

      progress.update('截圖中 (可能需要 3~5 秒)...');
      // Render to canvas
      const canvas = await global.html2canvas(content, {
        scale: 2,
        backgroundColor: '#ffffff',
        logging: false,
      });
      document.body.removeChild(container);

      progress.update('組裝 PDF...');
      const { jsPDF } = global.jspdf;
      const pdf = new jsPDF({ unit: 'pt', format: 'a4', orientation: 'portrait' });
      const pdfW = pdf.internal.pageSize.getWidth();
      const pdfH = pdf.internal.pageSize.getHeight();
      const imgW = pdfW - 32;   // 16pt margins
      const imgH = canvas.height * (imgW / canvas.width);

      // Multi-page slicing
      const imgData = canvas.toDataURL('image/jpeg', 0.95);
      let yOffset = 0;
      let pageIndex = 0;
      const pageContentH = pdfH - 24;   // 12pt top/bottom margin
      while (yOffset < imgH) {
        if (pageIndex > 0) pdf.addPage();
        pdf.addImage(imgData, 'JPEG', 16, 12 - yOffset, imgW, imgH);
        // Mask everything below pageContentH (we draw the whole image, just clipped to page)
        // For simplicity: overlap-free multi-page
        yOffset += pageContentH;
        pageIndex++;
        if (pageIndex > 10) break;   // safety
      }

      const fname = `Plan_${new Date().toISOString().slice(0,10)}.pdf`;
      pdf.save(fname);
      progress.close();
      alert(`PDF 已下載：${fname}`);
    } catch (e) {
      console.error('[v3-pdf-export]', e);
      progress.close();
      alert('PDF 生成失敗：' + e.message);
    }
  }

  // ─── Progress overlay ────────────────────────────────────
  function createProgressOverlay() {
    const o = document.createElement('div');
    o.id = 'pdf-export-progress';
    o.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:99999;display:flex;justify-content:center;align-items:center;';
    o.innerHTML = `
      <div style="background:#1F2937;border:1px solid #374151;border-radius:8px;padding:24px 32px;min-width:280px;text-align:center;">
        <div style="font-size:32px;margin-bottom:8px;">📥</div>
        <div id="pe-msg" style="color:#E5E7EB;font-size:13px;">準備中...</div>
        <div style="margin-top:12px;width:100%;height:3px;background:#374151;border-radius:2px;overflow:hidden;">
          <div style="width:30%;height:100%;background:#10B981;animation:pdfprog 1.5s ease-in-out infinite;"></div>
        </div>
      </div>
      <style>@keyframes pdfprog{0%{transform:translateX(-100%);}100%{transform:translateX(400%);}}</style>`;
    document.body.appendChild(o);
    return {
      update(msg) { document.getElementById('pe-msg').textContent = msg; },
      close() { try { o.remove(); } catch {} },
    };
  }

  // ─── Expose ──────────────────────────────────────────────
  global.PlanPdfExport = {
    generate,
    buildReportHtml,
    fetchKeystatsForPlans,
  };

  console.log('[v3-pdf-export] module loaded — PlanPdfExport.generate() available');

})(typeof window !== 'undefined' ? window : globalThis);

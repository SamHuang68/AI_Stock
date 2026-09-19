// ============================================================
// Stock Terminal v3.4 — Reverse PDF Generator (Plan → PDF)
// ------------------------------------------------------------
// 從 S.plans + Yahoo keystats 反向生成下週執行 PDF，
// 結構對齊原始輸入格式（總表 / 排序 / EPS-PE-PEG / 個股展望 / 總結）。
//
// 技術：html2canvas (HTML→canvas) + jsPDF (canvas→PDF)
//   ✓ 中文字型用瀏覽器原生 (繁中字無需嵌入)
//   ✓ A4 縱向，多頁切割
// ============================================================

(function (global) {
  'use strict';

  const HTML2CANVAS_URL = '/assets/vendor/html2canvas/1.4.1/html2canvas.min.js';
  const JSPDF_URL = '/assets/vendor/jspdf/4.2.1/jspdf.umd.min.js';
  const JSPDF_VERSION = '4.2.1';
  const MAX_PAGES = 120;

  // 同源依賴只合併進行中的載入；失敗或逾時後可重試。
  let _libsPromise = null;
  let _generatePromise = null;
  const scriptLoads = new Map();
  function bounded(promise, ms, message, onTimeout) {
    let timer;
    return Promise.race([Promise.resolve(promise), new Promise((resolve, reject) => {
      timer = setTimeout(() => { if (onTimeout) onTimeout(); reject(new Error(message)); }, ms);
    })]).finally(() => clearTimeout(timer));
  }
  function loadLibs() {
    if (_libsPromise) return _libsPromise;
    _libsPromise = Promise.all([
      loadScript(HTML2CANVAS_URL, () => typeof global.html2canvas === 'function'),
      loadScript(JSPDF_URL, () => typeof global.jspdf?.jsPDF === 'function' && global.jspdf.jsPDF.version === JSPDF_VERSION)
    ]).finally(() => { _libsPromise = null; });
    return _libsPromise;
  }
  function loadScript(url, valid) {
    if (valid()) return Promise.resolve();
    if (scriptLoads.has(url)) return scriptLoads.get(url);
    const promise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      const timer = setTimeout(() => finish(new Error('載入逾時：' + url)), 15000);
      function finish(error) {
        clearTimeout(timer); s.onload = null; s.onerror = null; s.remove();
        if (error) reject(error); else resolve();
      }
      s.src = url;
      s.onload = () => finish(valid() ? null : new Error('PDF 函式庫 API 或版本不符：' + url));
      s.onerror = () => finish(new Error('載入失敗：' + url));
      document.head.appendChild(s);
    }).finally(() => { scriptLoads.delete(url); });
    scriptLoads.set(url, promise);
    return promise;
  }

  // ─── Format helpers ──────────────────────────────────────
  function numeric(v) {
    if (typeof v !== 'number' && (typeof v !== 'string' || !v.trim())) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  function fmtNum(v, dec=2) {
    const n = numeric(v);
    return n == null ? '—' : n.toFixed(dec);
  }
  function fmtZone(lo, hi) {
    lo = numeric(lo); hi = numeric(hi);
    if (Number.isFinite(lo) && Number.isFinite(hi)) return `${lo.toFixed(2)} ~ ${hi.toFixed(2)}`;
    if (Number.isFinite(lo)) return lo.toFixed(2);
    if (Number.isFinite(hi)) return hi.toFixed(2);
    return '—';
  }
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function taiwanDate(now = new Date()) {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
    const values = Object.fromEntries(parts.map(p => [p.type, p.value]));
    return `${values.year}-${values.month}-${values.day}`;
  }
  function nextWeekStartStr(date) {
    const d = new Date(date + 'T00:00:00Z');
    // 找下週一
    const day = d.getUTCDay();
    const add = (day === 0) ? 1 : (8 - day);
    d.setUTCDate(d.getUTCDate() + add);
    return d.toISOString().slice(0, 10).replace(/-/g, '/');
  }

  // ─── Build the HTML report ──────────────────────────────
  function buildReportHtml(plans, keystats = {}, date = taiwanDate()) {
    const planList = Object.values(plans);
    if (planList.length === 0) return null;

    // Sort by role priority (主倉 > 動能 > 攻擊 > 觀察)
    const rolePriority = { '主倉': 0, '動能倉': 1, '攻擊倉': 2, '觀察倉': 3 };
    const sorted = [...planList].sort((a, b) =>
      (rolePriority[a.role] ?? 9) - (rolePriority[b.role] ?? 9));

    const reportDate = date.replace(/-/g, '/');
    const tradeDate = nextWeekStartStr(date);
    const symList = sorted.map(p => `${p.sym}`).join('、');

    // === Section 1: 下週執行總表 ===
    const totalsRows = sorted.map(p => `
      <tr>
        <td><b>${esc(p.sym)}</b></td>
        <td>${esc(p.role || '—')}</td>
        <td>${esc(p.longCondition || '—')}</td>
        <td>${fmtZone(p.buyZoneLow, p.buyZoneHigh)}</td>
        <td>${fmtNum(p.resistance)}</td>
        <td>${fmtNum(p.stopLoss)}${numeric(p.weakBreak) != null ? ` / ${fmtNum(p.weakBreak)}` : ''}</td>
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
      const pe = numeric(k.trailingPE);
      const eps = numeric(k.eps);
      const growth = numeric(k.earningsQuarterlyGrowth ?? k.revenueGrowth);
      const peg = numeric(k.pegRatio) ?? (pe && growth > 0 ? pe / growth : null);
      return `
        <tr>
          <td><b>${esc(p.sym)}</b></td>
          <td>${k.shortName ? esc(k.shortName) : '—'}</td>
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
          ${numeric(p.resistance) != null ? `<div><b>壓力：</b>${fmtNum(p.resistance)}（突破即追）</div>` : ''}
          ${numeric(p.stopLoss) != null ? `<div><b>減碼：</b>${fmtNum(p.stopLoss)}</div>` : ''}
          ${numeric(p.weakBreak) != null ? `<div><b>出場：</b>${fmtNum(p.weakBreak)}</div>` : ''}
        </div>
      </div>`).join('');

    return `
<div id="pdf-report-content" style="background:#fff;color:#1a1a1a;padding:32px 36px;width:780px;overflow-wrap:anywhere;font-family:'PingFang TC','Microsoft JhengHei',sans-serif;font-size:12px;line-height:1.6;">
  <h1 style="font-size:20px;margin:0 0 4px;color:#111;">${esc(symList)}：下週執行與基本面</h1>
  <div style="font-size:10px;color:#666;margin-bottom:20px;">
    交易日：${tradeDate} 起｜報告產生日期：${reportDate} (Stock Terminal v3.4 自動生成)<br>
    本文件是交易計畫與估值整理，不是投資建議。下週若開盤跳空或大盤轉弱，先等前 15~30 分鐘確認量價，再照表執行。
  </div>

  <h2 style="font-size:14px;border-bottom:1px solid #999;padding-bottom:4px;margin:18px 0 10px;">一、下週執行總表</h2>
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
  ${Object.values(plans).filter(p => keystats[p.sym]?._exportError).map(p => `<div style="font-size:9px;color:#888;">${esc(p.sym)} 基本面未取得：${esc(keystats[p.sym]._exportError)}；保留計畫內容，缺值以 — 顯示。</div>`).join('')}

  <h2 style="font-size:14px;border-bottom:1px solid #999;padding-bottom:4px;margin:18px 0 10px;">四、個股展望與執行細節</h2>
  ${detailHtml}

  <h2 style="font-size:14px;border-bottom:1px solid #999;padding-bottom:4px;margin:18px 0 10px;">五、總結</h2>
  <div style="font-size:11px;line-height:1.8;">
    <div><b>本期執行檔數：</b>${planList.length} 檔</div>
    <div><b>角色分佈：</b>${Object.entries(planList.reduce((a,p)=>{a[p.role||'未分']=(a[p.role||'未分']||0)+1;return a;},Object.create(null))).map(([k,v])=>`${esc(k)} ${v}`).join('、')}</div>
    <div style="margin-top:8px;color:#666;font-size:10px;">風控口訣：支撐有守才買，壓力爆量過不了就先收。</div>
  </div>

  <div style="margin-top:24px;padding-top:8px;border-top:1px dotted #999;font-size:9px;color:#999;text-align:center;">
    Stock Terminal v3.4 · ${reportDate} 自動生成
  </div>
</div>`;
  }

  // ─── Fetch keystats for all plan symbols ────────────────
  async function fetchKeystatsForPlans(plans) {
    const out = Object.create(null);
    const rows = Object.values(plans);
    const deadline = Date.now() + 30000;
    let cursor = 0;
    async function worker() {
      while (cursor < rows.length) {
        const p = rows[cursor++];
        const remaining = deadline - Date.now();
        if (remaining <= 0) { out[p.sym] = { _exportError: '整批讀取逾時' }; continue; }
        const controller = new AbortController();
        const yfsym = p.mkt === 'TW' ? p.sym + '.TW' : p.sym;
        try {
          const data = await bounded((async () => {
            const r = await fetch(`${global.SERVER || global.location?.origin || 'http://localhost:18432'}/keystats/${encodeURIComponent(yfsym)}`, { signal: controller.signal });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const value = await r.json();
            if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('回應格式無效');
            return value;
          })(), Math.min(8000, remaining), '基本面讀取逾時', () => controller.abort());
          out[p.sym] = data;
        } catch (error) { out[p.sym] = { _exportError: String(error?.message || error) }; }
        finally { controller.abort(); }
      }
    }
    await Promise.all(Array.from({ length: Math.min(4, rows.length) }, worker));
    return out;
  }

  // 先以實際 DOM 高度分頁，再逐頁渲染；不使用整張長圖位移或裁切文字。
  function paginate(content, maxHeight) {
    const doc = content.ownerDocument;
    const pages = [];
    let page, heading = null;
    function nextPage() {
      if (pages.length >= MAX_PAGES) throw new Error(`報告超過 ${MAX_PAGES} 頁的匯出能力；未下載任何截斷內容，請分批匯出完整計畫。`);
      page = content.cloneNode(false);
      page.removeAttribute('id'); page.className = 'pdf-export-page';
      doc.body.appendChild(page); pages.push(page);
    }
    function fits() {
      return Math.ceil(page.getBoundingClientRect().height) <= maxHeight && page.scrollWidth <= page.clientWidth + 1;
    }
    function tooLarge() { throw new Error('單一表格列、清單項或報告區塊超過一頁，無法完整呈現；未下載 PDF，請將過長內容分段後重試。'); }
    function breakWithHeading() {
      const title = heading && heading.parentNode === page ? heading : null;
      if (title) title.remove();
      if (page.children.length) nextPage();
      if (title) page.appendChild(title);
      heading = null;
    }
    function appendBlock(node) {
      let copy = node.cloneNode(true);
      page.appendChild(copy);
      if (fits()) { heading = null; return; }
      copy.remove();
      breakWithHeading();
      page.appendChild(copy);
      if (!fits()) tooLarge();
    }
    function appendCollection(items, makeContainer) {
      let group = null, target = null;
      items.forEach((item, index) => {
        if (!group) { ({ group, target } = makeContainer(index)); page.appendChild(group); }
        let copy = item.cloneNode(true);
        target.appendChild(copy);
        if (fits()) { heading = null; return; }
        copy.remove();
        if (!target.children.length) group.remove();
        breakWithHeading();
        ({ group, target } = makeContainer(index)); page.appendChild(group); target.appendChild(copy);
        if (!fits()) tooLarge();
      });
    }
    nextPage();
    for (const node of Array.from(content.children)) {
      if (node.tagName === 'TABLE' && node.tBodies.length) {
        const widths = Array.from(node.rows[0]?.cells || []).map(cell => cell.getBoundingClientRect().width);
        const rows = Array.from(node.tBodies).flatMap(body => Array.from(body.rows));
        appendCollection(rows, () => {
          const group = node.cloneNode(false), cols = doc.createElement('colgroup');
          group.style.tableLayout = 'fixed';
          widths.forEach(width => { const col = doc.createElement('col'); col.style.width = width + 'px'; cols.appendChild(col); });
          group.appendChild(cols);
          if (node.tHead) group.appendChild(node.tHead.cloneNode(true));
          const target = doc.createElement('tbody'); group.appendChild(target);
          return { group, target };
        });
      } else if (node.tagName === 'OL') {
        appendCollection(Array.from(node.children), index => {
          const group = node.cloneNode(false); group.start = (node.start || 1) + index;
          return { group, target: group };
        });
      } else {
        appendBlock(node);
        if (node.tagName === 'H2') heading = page.children[page.children.length - 1];
      }
    }
    if (!pages.length || !pages[0].children.length) throw new Error('報告沒有可匯出的內容');
    return pages;
  }

  // generate 可接受非同步儲存介面，供應用程式改接其他儲存目的地。
  function generate(options = {}) {
    if (_generatePromise) return _generatePromise;
    _generatePromise = generateReport(options).then(result => {
      alert(result.ok ? `完整 PDF 已交由瀏覽器下載：${result.filename}（${result.pages} 頁）` : 'PDF 生成失敗：' + result.error);
      return result;
    }).finally(() => { _generatePromise = null; });
    return _generatePromise;
  }
  async function generateReport(options) {
    let progress = null, mount = null, canvas = null;
    function releaseCanvas(value) { if (value) { value.width = 0; value.height = 0; value.remove(); } }
    try {
      const original = global.S?.plans;
      if (!original || Object.keys(original).length === 0) return { ok: false, error: '沒有計畫可匯出 — 請先建立計畫' };
      const plans = typeof structuredClone === 'function' ? structuredClone(original) : JSON.parse(JSON.stringify(original));
      if (Object.values(plans).some(p => !p || typeof p !== 'object' || !p.sym)) throw new Error('計畫格式無效，請先確認每筆計畫的股票代號。');
      const date = taiwanDate();
      progress = createProgressOverlay();
      progress.update('載入 PDF 函式庫…');
      await loadLibs();
      progress.update('抓取基本面資料（PE／EPS，最長 30 秒）…');
      const keystats = await fetchKeystatsForPlans(plans);
      progress.update('準備完整報告與分頁…');
      const html = buildReportHtml(plans, keystats, date);
      if (!html) throw new Error('報告生成失敗');
      // 獨立文件擁有所有 html2canvas 複製容器；失敗或逾時亦可完整移除。
      mount = document.createElement('iframe');
      mount.id = 'pdf-export-mount'; mount.title = 'PDF 匯出暫存報告'; mount.setAttribute('aria-hidden', 'true');
      mount.style.cssText = 'position:fixed;left:-10000px;top:0;width:920px;height:1400px;border:0;';
      document.body.appendChild(mount);
      const doc = mount.contentDocument;
      if (!doc?.body) throw new Error('無法建立 PDF 暫存文件');
      doc.body.style.margin = '0'; doc.body.innerHTML = html;
      const content = doc.querySelector('#pdf-report-content');
      if (doc.fonts?.ready) await bounded(doc.fonts.ready, 10000, '等待報告字型逾時');
      const { jsPDF } = global.jspdf;
      const pdf = new jsPDF({ unit: 'pt', format: 'a4', orientation: 'portrait' });
      const pdfW = pdf.internal.pageSize.getWidth();
      const pdfH = pdf.internal.pageSize.getHeight();
      const imgW = pdfW - 32, maxHeight = Math.floor((pdfH - 24) * content.getBoundingClientRect().width / imgW) - 2;
      if (!Number.isFinite(maxHeight) || maxHeight <= 64) throw new Error('PDF 分頁尺寸無效');
      const pages = paginate(content, maxHeight);
      content.remove();
      const renderDeadline = Date.now() + 120000;
      for (let index = 0; index < pages.length; index++) {
        const remaining = renderDeadline - Date.now();
        if (remaining <= 0) throw new Error('完整報告渲染逾時；未下載截斷 PDF，請分批匯出。');
        progress.update(`渲染第 ${index + 1}／${pages.length} 頁…`);
        canvas = doc.createElement('canvas');
        const bounds = pages[index].getBoundingClientRect();
        canvas.width = Math.ceil(bounds.width) * 2; canvas.height = Math.ceil(bounds.height) * 2;
        const rendering = Promise.resolve().then(() => global.html2canvas(pages[index], {
          canvas, scale: 2, backgroundColor: '#ffffff', logging: false, removeContainer: true, imageTimeout: 8000
        }));
        let rendered;
        try { rendered = await bounded(rendering, Math.min(20000, remaining), 'PDF 單頁渲染逾時'); }
        catch (error) { rendering.then(releaseCanvas, () => {}); throw error; }
        if (rendered !== canvas) { releaseCanvas(canvas); canvas = rendered; }
        if (!canvas?.width || !canvas?.height) throw new Error('PDF 畫布內容為空');
        const imgH = canvas.height * imgW / canvas.width;
        if (imgH > pdfH - 24 + 0.1) throw new Error('分頁渲染高度超出紙張；未下載可能截斷的 PDF。');
        if (index) pdf.addPage();
        pdf.addImage(canvas.toDataURL('image/jpeg', 0.95), 'JPEG', 16, 12, imgW, imgH);
        releaseCanvas(canvas); canvas = null; pages[index].remove();
      }
      const fname = `交易計畫_${date}.pdf`;
      progress.update('儲存完整 PDF…');
      const saving = options.save ? options.save(pdf, fname) : pdf.save(fname, { returnPromise: true });
      if (!saving || typeof saving.then !== 'function') throw new Error('PDF 儲存介面未提供完成狀態');
      await bounded(saving, 20000, 'PDF 儲存逾時，尚未確認完成');
      return { ok: true, filename: fname, pages: pages.length };
    } catch (e) {
      console.error('[v3-pdf-export]', e);
      const message = String(e?.message || e);
      return { ok: false, error: message };
    } finally {
      releaseCanvas(canvas);
      if (mount) mount.remove();
      if (progress) progress.close();
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
      update(msg) { o.querySelector('#pe-msg').textContent = msg; },
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

/* 使用者明示選擇標的及期間；開啟畫面不下載、不回補整份清單。 */
(function () {
  'use strict';
  let dialog, timer, jobId, opener, openerFallback, rejectedSelection = '';
  const $ = id => document.getElementById(id);
  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function describeResult(value) {
    const x = value || {}, q = x.quality;
    const count = v => Number.isInteger(v) && v >= 0 ? String(v) : '未提供';
    if (q && typeof q === 'object') {
      return '來源觀測 ' + count(q.observed) + '，品質通過 ' + count(q.accepted) +
        '，來源衝突 ' + count(q.conflicts) + '，缺日 ' + count(q.missing) +
        '，無效 ' + count(q.invalid) + '；來源核對完成不代表每筆行情可用';
    }
    if (x.reused) return '已沿用快取；品質仍依來源收據核對';
    if (Number.isInteger(x.inserted)) return '新增 ' + count(x.inserted) + '，來源差異 ' + count(x.conflicts);
    return '來源資料 ' + count(x.rows) + ' 筆；未提供分欄品質結果';
  }
  async function api(path, body) {
    const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
    const result = await r.json();
    if (!r.ok) {
      const error = Error(result.error || '讀取失敗（HTTP ' + r.status + '）');
      error.status = r.status; throw error;
    }
    return result;
  }
  async function poll() {
    if (!dialog?.open) return;
    try {
      const r = await api('/daily-cache/status'); jobId = r.jobId;
      const labels = { idle: '尚未啟動更新', queued: '等待共用工作佇列', running: '更新中', cancelling: '取消中', completed: '已完成', failed: '未完成', cancelled: '已取消' };
      $('dc-status').textContent = (rejectedSelection ? rejectedSelection + '｜' : '') + (labels[r.status] || r.status) + (r.range ? '｜' + r.range + '｜完成 ' + r.completed + '/' + r.symbols.length : '') + (r.error ? '｜' + r.error : '') + (r.results?.length ? '｜' + r.results.map(describeResult).join('；') : '');
      const evidence = $('dc-evidence');
      if (evidence) { evidence.hidden = !r.results?.length; evidence.querySelector('pre').textContent = JSON.stringify(r.results || [], null, 2); }
      const busy = ['queued', 'running', 'cancelling'].includes(r.status);
      $('dc-start').disabled = busy; $('dc-cancel').disabled = !['queued', 'running'].includes(r.status);
      if (busy) timer = setTimeout(poll, 1200);
    } catch (e) { $('dc-status').textContent = e.message + '；私有服務更新需要擁有者存取權。'; }
  }
  function selected() {
    return Array.from(dialog.querySelectorAll('[data-dc-symbol]:checked'), el => ({ symbol: el.dataset.dcSymbol, market: el.dataset.dcMarket }));
  }
  async function start() {
    const symbols = selected();
    if (!symbols.length || symbols.length > 5) { $('dc-status').textContent = '請選擇 1 至 5 個標的。'; return; }
    $('dc-start').disabled = true;
    rejectedSelection = '';
    try { await api('/daily-cache/refresh', { symbols, range: $('dc-range').value, kind: $('dc-source').value }); await poll(); }
    catch (e) {
      if (e.status === 409) { rejectedSelection = '本次選擇未被接受：' + e.message; await poll(); return; }
      $('dc-status').textContent = e.message; $('dc-start').disabled = false;
    }
  }
  async function warm() {
    const rows = selected();
    if (!rows.length || rows.length > 5) { $('dc-status').textContent = '請選擇 1 至 5 個標的。'; return; }
    $('dc-warm').disabled = true;
    try {
      let count = 0;
      for (const row of rows) {
        if (!dialog.open) break;
        const r = await api('/bars?' + new URLSearchParams({ sym: row.symbol, market: row.market }));
        if (r.candles.length && r.candles.every(c => ['open', 'high', 'low', 'close', 'volume'].every(k => Number.isFinite(c[k])))) { await runWorker(r.candles); count++; }
      }
      $('dc-status').textContent = '已預算 ' + count + ' 個本機標的；使用原指標公式，未連線資料來源。技術分數仍使用原本 1 年標準基底。';
    } catch (e) { $('dc-status').textContent = e.message; }
    finally { $('dc-warm').disabled = false; }
  }
  function close() {
    clearTimeout(timer);
    if (dialog?.open) dialog.close();
    const visible = el => el?.isConnected && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
    // 選單項目此刻可能仍可見，但 toolbar 已排程收合；優先回到持續可見的分類入口。
    const target = visible(openerFallback) ? openerFallback : (visible(opener) ? opener : null);
    target?.focus({ preventScroll: true });
    opener = openerFallback = null;
  }
  function open(event) {
    close();
    rejectedSelection = '';
    opener = event?.currentTarget instanceof HTMLElement ? event.currentTarget :
      (document.activeElement !== document.body ? document.activeElement : $('btn-daily-cache'));
    // 工具列選單會在點擊後收合；關閉時應回到仍可見的分類入口。
    const menuId = opener?.closest('.tbg-menu')?.id || '';
    openerFallback = menuId.startsWith('tbg-menu-') ? $('tbg-' + menuId.slice(9))?.querySelector('.tbg-btn') : null;
    if (!dialog) { dialog = document.createElement('dialog'); dialog.id = 'dc-dialog'; document.body.appendChild(dialog); }
    dialog.style.cssText = 'width:min(620px,94vw);max-height:90vh;overflow:auto;background:#101827;color:#e2e8f0;border:1px solid #64748b;border-radius:10px;padding:20px;font:15px/1.7 system-ui';
    const current = { symbol: String(S.sym || ''), market: S.mkt === 'US' ? 'US' : 'TW' };
    const watches = Object.entries(S.watches || {}).map(([symbol, x]) => ({ symbol, market: x.market || x.mkt || 'TW' }));
    const rows = [current, ...watches].filter((r, i, all) => r.symbol && all.findIndex(x => x.symbol === r.symbol && x.market === r.market) === i).slice(0, 50);
    dialog.innerHTML = '<h2>日線與指標快取</h2><p>只處理勾選標的，每次最多 5 個。開啟此畫面不下載資料。來源修訂另存，保留首次價格。</p><div style="display:flex;gap:12px;flex-wrap:wrap">' + rows.map((r, i) => '<label><input type="checkbox" data-dc-symbol="' + esc(r.symbol) + '" data-dc-market="' + esc(r.market) + '"' + (!i ? ' checked' : '') + '>' + esc(r.symbol + ' · ' + r.market) + '</label>').join('') + '</div><p><label>範圍 <select id="dc-range"><option value="1mo">1 個月</option><option value="3mo">3 個月</option><option value="1y" selected>1 年</option><option value="3y">3 年</option><option value="5y">5 年</option></select></label> <label>來源 <select id="dc-source"><option value="history">既有 Yahoo 日線</option><option value="official">TWSE 官方研究核對</option></select></label></p><p>官方核對僅支援單一上市四碼標的與 1／3／5 年；含交易日曆及公司行動核對。上櫃等未支援範圍會明示失敗。每次至多十分鐘，請求間隔至少 1.2 秒，已完成月份可重用。</p><div style="display:flex;gap:8px;flex-wrap:wrap"><button id="dc-warm">僅預算本機快取</button><button id="dc-start">更新選定標的</button><button id="dc-cancel" disabled>取消更新</button><button id="dc-close">關閉</button></div><p id="dc-status" role="status">尚未下載</p>';
    const details = document.createElement('details');
    details.id = 'dc-evidence'; details.hidden = true;
    details.innerHTML = '<summary>查看來源、衝突與缺日核對</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:40vh;overflow:auto"></pre>';
    dialog.appendChild(details);
    $('dc-start').onclick = start; $('dc-warm').onclick = warm; $('dc-close').onclick = close;
    $('dc-cancel').onclick = async () => { try { const r = await api('/daily-cache/cancel', { jobId }); $('dc-status').textContent = r.message; } catch (e) { $('dc-status').textContent = e.message; } };
    dialog.oncancel = event => { event.preventDefault(); close(); }; dialog.showModal(); poll();
  }
  function mount() { const p = $('pro-tools'); if (!p) return false; if (!$('btn-daily-cache')) { const b = document.createElement('button'); b.id = 'btn-daily-cache'; b.className = 'btn'; b.textContent = '日線快取'; b.onclick = open; p.appendChild(b); } return true; }
  if (!mount()) { let tries = 0; const t = setInterval(() => { if (mount() || ++tries > 30) clearInterval(t); }, 300); }
  window.DailyCacheUI = { open, close, describeResult };
})();

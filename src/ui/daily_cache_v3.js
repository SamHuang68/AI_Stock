/* 使用者明示選擇標的及期間；開啟畫面不下載、不回補整份清單。 */
(function () {
  'use strict';
  let dialog, timer, jobId;
  const $ = id => document.getElementById(id);
  const esc = s => String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  async function api(path, body) {
    const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
    const result = await r.json();
    if (!r.ok) throw Error(result.error || '讀取失敗（HTTP ' + r.status + '）');
    return result;
  }
  async function poll() {
    if (!dialog?.open) return;
    try {
      const r = await api('/daily-cache/status'); jobId = r.jobId;
      const labels = { idle: '尚未啟動更新', queued: '等待共用工作佇列', running: '更新中', completed: '已完成', failed: '未完成', cancelled: '已取消' };
      $('dc-status').textContent = (labels[r.status] || r.status) + (r.range ? '｜' + r.range + '｜完成 ' + r.completed + '/' + r.symbols.length : '') + (r.error ? '｜' + r.error : '') + (r.results?.length ? '｜' + r.results.map(x => x.reused ? '已沿用快取' : ('新增 ' + (x.inserted ?? x.rows ?? 0) + '，來源差異 ' + (x.conflicts ?? '見研究品質'))).join('；') : '');
      const busy = ['queued', 'running'].includes(r.status);
      $('dc-start').disabled = busy; $('dc-cancel').disabled = !busy;
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
    try { await api('/daily-cache/refresh', { symbols, range: $('dc-range').value, kind: $('dc-source').value }); await poll(); }
    catch (e) { $('dc-status').textContent = e.message; $('dc-start').disabled = false; }
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
  function close() { clearTimeout(timer); if (dialog?.open) dialog.close(); }
  function open() {
    close();
    if (!dialog) { dialog = document.createElement('dialog'); dialog.id = 'dc-dialog'; document.body.appendChild(dialog); }
    dialog.style.cssText = 'width:min(620px,94vw);max-height:90vh;overflow:auto;background:#101827;color:#e2e8f0;border:1px solid #64748b;border-radius:10px;padding:20px;font:15px/1.7 system-ui';
    const current = { symbol: String(S.sym || ''), market: S.mkt === 'US' ? 'US' : 'TW' };
    const watches = Object.entries(S.watches || {}).map(([symbol, x]) => ({ symbol, market: x.market || x.mkt || 'TW' }));
    const rows = [current, ...watches].filter((r, i, all) => r.symbol && all.findIndex(x => x.symbol === r.symbol && x.market === r.market) === i).slice(0, 50);
    dialog.innerHTML = '<h2>日線與指標快取</h2><p>只處理勾選標的，每次最多 5 個。開啟此畫面不下載資料。來源修訂另存，保留首次價格。</p><div style="display:flex;gap:12px;flex-wrap:wrap">' + rows.map((r, i) => '<label><input type="checkbox" data-dc-symbol="' + esc(r.symbol) + '" data-dc-market="' + esc(r.market) + '"' + (!i ? ' checked' : '') + '>' + esc(r.symbol + ' · ' + r.market) + '</label>').join('') + '</div><p><label>範圍 <select id="dc-range"><option value="1mo">1 個月</option><option value="3mo">3 個月</option><option value="1y" selected>1 年</option><option value="3y">3 年</option><option value="5y">5 年</option></select></label> <label>來源 <select id="dc-source"><option value="history">既有 Yahoo 日線</option><option value="official">TWSE 官方研究核對</option></select></label></p><p>官方核對僅支援單一上市四碼標的與 1／3／5 年；含交易日曆及公司行動核對。上櫃等未支援範圍會明示失敗。每次至多十分鐘，請求間隔至少 1.2 秒，已完成月份可重用。</p><div style="display:flex;gap:8px;flex-wrap:wrap"><button id="dc-warm">僅預算本機快取</button><button id="dc-start">更新選定標的</button><button id="dc-cancel" disabled>取消更新</button><button id="dc-close">關閉</button></div><p id="dc-status" role="status">尚未下載</p>';
    $('dc-start').onclick = start; $('dc-warm').onclick = warm; $('dc-close').onclick = close;
    $('dc-cancel').onclick = async () => { try { const r = await api('/daily-cache/cancel', { jobId }); $('dc-status').textContent = r.message; } catch (e) { $('dc-status').textContent = e.message; } };
    dialog.oncancel = close; dialog.showModal(); poll();
  }
  function mount() { const p = $('pro-tools'); if (!p) return false; if (!$('btn-daily-cache')) { const b = document.createElement('button'); b.id = 'btn-daily-cache'; b.className = 'btn'; b.textContent = '日線快取'; b.onclick = open; p.appendChild(b); } return true; }
  if (!mount()) { let tries = 0; const t = setInterval(() => { if (mount() || ++tries > 30) clearInterval(t); }, 300); }
  window.DailyCacheUI = { open, close };
})();

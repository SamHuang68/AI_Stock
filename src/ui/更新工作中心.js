/* 統一更新工作中心；市場成功以原發布者的已提交快照為準。 */
(function () {
  'use strict';
  var dialog = null, unsubscribe = null, priorFocus = null, lastState = null;
  var localListening = false, localGeneration = 0, localReading = false, localPending = false;
  var localArchive = null, localTasks = [], localPage = 0, localPageSize = 20;
  var labels = { pulse: '市場快照', options: '選擇權研究', research: '日夜盤研究' };
  var statusLabels = { queued: '等待', running: '執行中', succeeded: '完成', failed: '失敗', interrupted: '中斷', timed_out: '逾時後結束' };
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function time(value) {
    if (!value) return '尚未提供';
    var date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false }) : '時間格式不正確';
  }
  function title(job) { return labels[job.type] || ('背景工作：' + String(job.type || '').replace(/^legacy:/, '')); }
  function stopLocal() {
    localListening = false; localGeneration++;
    window.removeEventListener('st:research-task-saved', readLocal);
    window.removeEventListener('storage', storageChanged);
  }
  function storageChanged(event) {
    if (!event.key || event.key.indexOf('st.research.task.v1.') === 0 || event.key.indexOf('st.research.pending.v1.') === 0) readLocal();
  }
  function renderLocal() {
    var names = { prepared: '證據已凍結；尚未執行', running: '已保存送出前狀態', verified: '引文已核對',
      quarantined: '回應已隔離', failed: '瀏覽器執行失敗', cancelled: '瀏覽器已停止接收', stop_requested: '已要求停止接收' };
    var count = localTasks.length, pages = Math.max(1, Math.ceil(count / localPageSize));
    localPage = Math.min(localPage, pages - 1);
    dialog.querySelector('.uc-local-count').textContent = '已核對 ' + localArchive.events.length + ' 個事件、' + count + ' 個工作；損毀項目 ' + localArchive.damaged.length + ' 個（原字串保留於完整匯出）；未核對復原暫存 ' + (localArchive.recovery || []).length + ' 個（不列入已完成狀態）。第 ' + (localPage + 1) + '／' + pages + ' 頁，每頁最多 ' + localPageSize + ' 個工作。';
    dialog.querySelector('.uc-local-jobs').innerHTML = localTasks.slice(localPage * localPageSize, (localPage + 1) * localPageSize).map(function (job) {
      var state = names[job.status] || '狀態未識別';
      var completion = job.hasCompletionReceipt ? '已保存完整完成收據；研究推論仍須人工覆核。' :
        (job.status === 'prepared' ? '此紀錄只保存離線整理，不表示已呼叫模型。' : '尚無完成收據，完成狀態未確認；不能據此判定後端已停止或中斷。');
      return '<article class="uc-job"><div class="uc-job-head"><strong>' + esc(job.label) + '</strong><span>' + esc(state) + '</span></div>' +
        '<p>' + esc(completion) + '</p><dl><dt>工作識別</dt><dd>' + esc(job.taskId) + '</dd><dt>最近紀錄</dt><dd>' + esc(time(job.recordedAt)) + '</dd>' +
        '<dt>模型／提供者</dt><dd>' + esc(job.model || '尚未保存模型') + '／' + esc(job.provider || '未提供') + '</dd>' +
        '<dt>主機</dt><dd>' + esc(job.host || '未提供') + '</dd><dt>資料包摘要</dt><dd>' + esc(job.packageHash || '未提供') + '</dd>' +
        '<dt>請求識別</dt><dd>' + esc(job.requestId || '尚未保存') + '</dd><dt>狀態事件</dt><dd>' + job.eventCount + ' 個</dd></dl>' +
        (job.error ? '<p class="uc-job-error">' + esc(job.error) + '</p>' : '') + '</article>';
    }).join('') || '<p>本瀏覽器尚無已保存的研究任務。</p>';
    dialog.querySelector('[data-local-prev]').disabled = localPage === 0;
    dialog.querySelector('[data-local-next]').disabled = localPage + 1 >= pages;
    dialog.querySelector('[data-local-export]').disabled = false;
  }
  async function readLocal() {
    if (!localListening || !dialog || !dialog.open) return;
    if (localReading) { localPending = true; return; }
    localReading = true; var generation = localGeneration;
    try {
      if (!window.ResearchTaskCore) throw new Error('研究任務元件尚未載入');
      var archive = await new window.ResearchTaskCore.Store(window.localStorage).all();
      if (generation !== localGeneration || !localListening) return;
      localArchive = archive; localTasks = window.ResearchTaskCore.summarize(archive);
      dialog.querySelector('.uc-local-error').textContent = ''; renderLocal();
    } catch (error) {
      if (generation === localGeneration && localListening) dialog.querySelector('.uc-local-error').textContent = '本機研究紀錄無法核對：' + error.message + '。先前已顯示的內容保留，不能據此判定目前狀態。';
    } finally {
      localReading = false;
      if (localPending) { localPending = false; readLocal(); }
    }
  }
  async function exportLocal() {
    try {
      // 重新核對全部紀錄，匯出不受畫面頁數限制，也不傳送伺服器。
      var archive = await new window.ResearchTaskCore.Store(window.localStorage).all();
      var url = URL.createObjectURL(new Blob([JSON.stringify(archive, null, 2)], { type: 'application/json;charset=utf-8' }));
      var link = document.createElement('a'); link.href = url; link.download = '本瀏覽器研究工作完整紀錄.json';
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
    } catch (error) { dialog.querySelector('.uc-local-error').textContent = '完整匯出失敗：' + error.message + '；原紀錄保留。'; }
  }
  function close() {
    stopLocal();
    if (unsubscribe) { unsubscribe(); unsubscribe = null; }
    if (dialog && dialog.open) dialog.close();
    if (priorFocus && priorFocus.isConnected && priorFocus.getClientRects().length) priorFocus.focus();
  }
  function render(state) {
    lastState = state;
    if (!dialog) return;
    var active = document.activeElement, focusKey = active && dialog.contains(active) ? active.getAttribute('data-key') : null;
    dialog.querySelector('.uc-error').textContent = state.error || '';
    dialog.querySelector('.uc-readonly').textContent = state.capabilities.canSubmit ? '手動更新會建立伺服器工作；關閉視窗只停止瀏覽器輪詢。' : '唯讀模式：可查看進度，不能提交或重試。';
    dialog.querySelector('.uc-note').textContent = state.note || '';
    dialog.querySelectorAll('[data-submit]').forEach(function (button) { button.disabled = !state.capabilities.canSubmit || state.writing; });
    dialog.querySelector('[data-read]').disabled = state.loading;
    var workers = Object.keys(state.workers || {}).filter(function (name) { return state.workers[name].error; });
    dialog.querySelector('.uc-workers').textContent = workers.map(function (name) { return (name === 'pulse' ? '市場工作者' : '研究工作者') + '：' + state.workers[name].error; }).join('；');
    var jobs = state.jobs || [];
    dialog.querySelector('.uc-jobs').innerHTML = jobs.length ? jobs.map(function (job) {
      var result = job.result || {};
      return '<article class="uc-job"><div class="uc-job-head"><strong>' + esc(title(job)) + '</strong><span>' + esc(statusLabels[job.status] || job.status) + (job.overdue ? ' · 已超時仍在等待底層結束' : '') + '</span></div>' +
        '<div>' + esc(job.stage || '階段尚未提供') + '</div><dl><dt>工作識別</dt><dd>' + esc(job.jobId) + '</dd>' +
        '<dt>排隊時間</dt><dd>' + esc(time(job.queuedAt)) + '</dd><dt>開始／結束</dt><dd>' + esc(time(job.startedAt)) + '／' + esc(time(job.finishedAt)) + '</dd>' +
        '<dt>觸發原因</dt><dd>' + esc(job.reason || '未提供') + '</dd><dt>執行次數</dt><dd>' + esc(job.attempt || 1) + (job.lineageComplete === false ? '（較早沿革已超過保存範圍）' : '') + '</dd>' +
        (job.parentJobId ? '<dt>上次工作</dt><dd>' + esc(job.parentJobId) + '</dd>' : '') +
        (result.marketJobId ? '<dt>正式快照工作</dt><dd>' + esc(result.marketJobId) + '</dd>' : '') +
        (result.snapshotId ? '<dt>已提交快照</dt><dd>' + esc(result.snapshotId) + '／修訂 ' + esc(result.revision) + '</dd>' : '') +
        '</dl>' + (job.error ? '<p class="uc-job-error">' + esc(job.error) + '</p>' : '') +
        (result.note ? '<p>' + esc(result.note) + '</p>' : '') +
        (job.canRetry && state.capabilities.canRetry ? '<button type="button" data-key="retry-' + esc(job.jobId) + '" data-retry="' + esc(job.jobId) + '"' + (state.writing ? ' disabled' : '') + '>重試此工作</button>' : '') + '</article>';
    }).join('') : '<p>尚無已保存的更新工作。</p>';
    if (focusKey) {
      var next = Array.from(dialog.querySelectorAll('[data-key]')).find(function (node) { return node.getAttribute('data-key') === focusKey; });
      if (next && !next.disabled) next.focus({ preventScroll: true });
    }
  }
  function ensure() {
    if (dialog) return;
    var style = document.createElement('style');
    style.textContent = '#st-update-center{box-sizing:border-box;width:min(1050px,96%);max-width:96%;max-height:92%;inset:0;margin:auto;padding:0;border:1px solid #526179;border-radius:10px;background:#101827;color:#e2e8f0;font:13px/1.55 system-ui,"Microsoft JhengHei UI",sans-serif;overflow:auto}#st-update-center::backdrop{background:#0009}#st-update-center *{box-sizing:border-box;min-width:0}#st-update-center button{font:inherit;color:inherit;border:1px solid #64748b;border-radius:5px;background:#1e293b;padding:7px 10px;cursor:pointer;white-space:normal}#st-update-center button:disabled{opacity:.5;cursor:default}#st-update-center button:focus-visible{outline:2px solid #60a5fa;outline-offset:2px}#st-update-center .uc-header{position:sticky;top:0;background:#101827;z-index:1;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:8px;border-bottom:1px solid #334155}#st-update-center h2{font-size:17px;margin:0}#st-update-center .uc-content{padding:12px 16px}#st-update-center .uc-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}#st-update-center .uc-jobs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}#st-update-center .uc-job{padding:12px;border:1px solid #334155;border-radius:7px;overflow-wrap:anywhere}#st-update-center .uc-job-head{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}#st-update-center dl{display:grid;grid-template-columns:90px minmax(0,1fr);gap:5px;margin:8px 0}#st-update-center dd{margin:0}#st-update-center dt{color:#aab9ce}#st-update-center .uc-error,#st-update-center .uc-workers,#st-update-center .uc-job-error{color:#fda4af;white-space:pre-wrap;overflow-wrap:anywhere}#st-update-center p{margin:8px 0;overflow-wrap:anywhere}#st-update-center .uc-note{color:#aab9ce}@media(max-width:620px){#st-update-center .uc-jobs{grid-template-columns:minmax(0,1fr)}#st-update-center{font-size:12px}#st-update-center .uc-content{padding:10px}#st-update-center dl{grid-template-columns:76px minmax(0,1fr)}}';
    document.head.appendChild(style);
    dialog = document.createElement('dialog'); dialog.id = 'st-update-center'; dialog.setAttribute('aria-labelledby', 'uc-title');
    dialog.innerHTML = '<div class="uc-header"><h2 id="uc-title">更新工作中心</h2><button type="button" data-close data-key="close">關閉</button></div>' +
      '<div class="uc-content"><p class="uc-readonly"></p><div class="uc-actions"><button type="button" data-submit="pulse" data-key="pulse">更新市場</button><button type="button" data-submit="options" data-key="options">更新選擇權</button><button type="button" data-submit="research" data-key="research">更新日夜盤研究</button><button type="button" data-read data-key="read">重新讀取</button></div><p class="uc-error" role="alert"></p><p class="uc-workers" role="status"></p><p class="uc-note"></p><div class="uc-jobs"></div>' +
      '<section aria-labelledby="uc-local-title"><h3 id="uc-local-title">本瀏覽器 AI 研究任務</h3><p>只讀取此瀏覽器保存的完整狀態事件；不傳送私人任務、不呼叫或取消模型。其他裝置的任務不在此範圍。</p>' +
      '<p class="uc-local-error uc-error" role="alert"></p><p class="uc-local-count">正在核對本機紀錄</p><div class="uc-local-jobs uc-jobs"></div>' +
      '<div class="uc-actions"><button type="button" data-local-prev disabled>上一頁研究工作</button><button type="button" data-local-next disabled>下一頁研究工作</button>' +
      '<button type="button" data-local-export disabled>匯出全部本機研究紀錄</button></div><p>完整原文、凍結資料包及全部較早事件，可在研究工作台的「讀取本機工作紀錄」查看，或使用上方完整匯出。</p></section></div>';
    document.body.appendChild(dialog);
    var archive = document.createElement('a');
    archive.href = (window.SERVER || location.origin) + '/updates/archive';
    archive.download = '更新工作沿革.json'; archive.textContent = '匯出完整研究工作沿革';
    archive.style.cssText = 'display:inline-block;color:#93c5fd;padding:7px;overflow-wrap:anywhere';
    dialog.querySelector('.uc-actions').appendChild(archive);
    dialog.addEventListener('cancel', function (event) { event.preventDefault(); close(); });
    dialog.addEventListener('close', function () { stopLocal(); if (unsubscribe) { unsubscribe(); unsubscribe = null; } });
    dialog.addEventListener('click', function (event) {
      var button = event.target.closest('button');
      if (!button || !dialog.contains(button) || button.disabled) return;
      if (button.hasAttribute('data-close')) { close(); return; }
      if (button.hasAttribute('data-local-prev')) { localPage--; renderLocal(); return; }
      if (button.hasAttribute('data-local-next')) { localPage++; renderLocal(); return; }
      if (button.hasAttribute('data-local-export')) { exportLocal(); return; }
      var request;
      if (button.hasAttribute('data-read')) { readLocal(); request = window.UpdateJobs.refresh(); }
      else if (button.hasAttribute('data-submit')) request = window.UpdateJobs.submit(button.getAttribute('data-submit'));
      else if (button.hasAttribute('data-retry')) request = window.UpdateJobs.retry(button.getAttribute('data-retry'));
      if (request) request.catch(function () { /* 共用 store 已保留錯誤。 */ });
    });
  }
  window.UpdateCenter = { open: function (trigger) {
    ensure();
    if (dialog.open) return;
    priorFocus = trigger && typeof trigger.focus === 'function' ? trigger : document.activeElement;
    dialog.showModal();
    localListening = true; localGeneration++; localPage = 0;
    window.addEventListener('st:research-task-saved', readLocal);
    window.addEventListener('storage', storageChanged); readLocal();
    if (!window.UpdateJobs) { dialog.querySelector('.uc-error').textContent = '更新工作模組尚未載入'; return; }
    unsubscribe = window.UpdateJobs.subscribe(render);
    dialog.querySelector('[data-close]').focus();
  }, close: close };
}());

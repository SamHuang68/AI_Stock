/* 研究任務面板：先凍結、再查路由、逐次確認；不在掛載時呼叫模型。 */
(function () {
  'use strict';
  var mountNode, inputReader, runner, packet, selectedRoute, routeController, generation = 0;
  function $(id) { return mountNode && mountNode.querySelector('#' + id); }
  function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  }); }
  function owner() { return !window.ST_PRIVATE_WEB_PROFILE || window.ST_PRIVATE_WEB_PROFILE.role === 'owner'; }
  function status(value) { if ($('rt-status')) $('rt-status').textContent = value; }
  function json(value) { return JSON.stringify(value, null, 2); }
  function details(title, text) { return '<details><summary>' + esc(title) + '</summary><pre>' + esc(text) + '</pre></details>'; }
  function download(name, value) {
    var url = URL.createObjectURL(new Blob([typeof value === 'string' ? value : json(value)], { type: 'application/json;charset=utf-8' }));
    var link = document.createElement('a'); link.href = url; link.download = name; link.hidden = true;
    mountNode.appendChild(link); link.click(); link.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
  }
  function sync() {
    if (!$('rt-run')) return;
    var busy = !!(runner && runner.active);
    $('rt-run').disabled = !owner() || !packet || !selectedRoute || !$('rt-consent').checked || busy;
    $('rt-route-read').disabled = !owner() || !packet || busy;
    $('rt-freeze').disabled = busy; $('rt-mode').disabled = busy; $('rt-type').disabled = busy;
    $('rt-copy').disabled = !packet; $('rt-download').disabled = !packet;
    $('rt-stop').disabled = !busy;
  }
  function clearRoute() {
    selectedRoute = null;
    if ($('rt-consent')) $('rt-consent').checked = false;
    if ($('rt-route')) $('rt-route').textContent = '尚未讀取本次模型路由。';
    sync();
  }
  function presentPacket() {
    var core = window.ResearchTaskCore, frozen = core.deterministic(packet);
    var state = packet.type === 'review' ? '歷史回顧：明列當時與事後資料，不聲稱即時' : core.freshness(packet.snapshots.current, Date.now()).reason;
    $('rt-package').innerHTML = '<p><b>' + esc(packet.label) + '</b> · ' + packet.evidence.length + ' 項完整證據 · ' + esc(state) + '</p>' +
      '<p>資料包摘要碼：<code>' + esc(packet.hash) + '</code><br>' + esc(packet.boundary) + '</p>' +
      details('規則式證據整理（完整）', json(frozen)) + details('凍結資料包（實際模型輸入完整內容）', json(packet));
  }
  async function freeze() {
    var seq = ++generation; clearRoute(); packet = null; sync(); status('正在凍結完整公開研究資料');
    try {
      var core = window.ResearchTaskCore, result = await core.freeze(inputReader(), $('rt-type').value);
      if (seq !== generation) return;
      packet = result; presentPacket();
      try { await runner.store.append(packet.hash, 'prepared', { packet: packet, deterministic: core.deterministic(packet) }); }
      catch (error) { status(error.message + '；完整資料包仍可複製或下載'); sync(); return; }
      if (seq === generation) { status('已凍結完整公開資料；尚未呼叫模型。請先查看資料包，再選擇是否查詢既有路由。'); sync(); }
    } catch (error) { if (seq === generation) { status(error.message); sync(); } }
  }
  async function readRoute() {
    if (!owner() || !packet) return;
    var seq = ++generation, mode = $('rt-mode').value;
    if (routeController) routeController.abort(); routeController = new AbortController();
    var currentController = routeController, timeout = setTimeout(function () { currentController.abort(); }, 12000);
    clearRoute(); status('正在讀取既有模型路由；沒有傳送研究資料或要求推理');
    try {
      var response = await fetch((window.SERVER || '') + '/ai/local/status', { cache: 'no-store', signal: currentController.signal });
      if (!response.ok) throw new Error('無法讀取模型路由（HTTP ' + response.status + '）');
      var data = await response.json(), route = await window.ResearchTaskCore.route(data.modes && data.modes[mode], mode);
      if (seq !== generation || currentController.signal.aborted) return;
      selectedRoute = route;
      $('rt-route').innerHTML = '<p>本次目的地：<b>' + esc(route.host) + '</b> · ' + esc(route.provider) + '<br>模型：<b>' + esc(route.model) + '</b>' +
        '<br>實際模型目的地：<code>' + esc(route.destination) + '</code><br>目的地設定摘要：<code>' + esc(route.destinationId) + '</code>' +
        '<br>伺服器通道：<code>' + esc(route.endpoint) + '</code> · 資料邊界：<b>' + esc(route.dataBoundary) + '</b>' +
        (route.probeDeferred ? '<br>外部連線與模型可用性尚未探測；目的地核對不代表模型已就緒。' : '') +
        '<br>' + esc(route.cost) + '<br>路由確認有效一分鐘；設定不一致時停止，不自動換模型。</p>';
      status('請核對目的地、模型、資料包與未知費用，勾選後按確認執行。'); sync();
    } catch (error) { if (seq === generation) { status(error.name === 'AbortError' ? '路由讀取已停止或逾時，請重試' : error.message); sync(); } }
    finally { clearTimeout(timeout); if (routeController === currentController) routeController = null; }
  }
  function renderResult(value) {
    var result = value.result;
    $('rt-result').innerHTML = '<p><b>' + (result.verified ? '引文核對通過；以下仍是研究推論' : '回應不可驗證；已隔離，不列入研究摘要') + '</b></p>' +
      '<p>請求識別：<code>' + esc(value.meta.requestId || '未提供') + '</code> · 資料包：<code>' + esc(value.packageHash) + '</code></p>' +
      (result.verified ? result.claims.map(function (claim) {
        return '<article><p><b>研究推論 · ' + esc(claim.phase) + '</b><br>' + esc(claim.interpretation) + '</p>' +
          '<p>證據：<code>' + esc(claim.evidenceId) + '</code></p>' + details('精確匹配的完整引文', claim.quote) +
          '<p>限制：' + esc(claim.limitations.join('；')) + '<br>後續查證：' + esc(claim.nextChecks.join('；')) + '</p></article>';
      }).join('') + '<p>整體限制：' + esc(result.limitations.join('；')) + '<br>後續查證：' + esc(result.nextChecks.join('；')) + '</p>' :
        '<p>' + result.issues.map(esc).join('<br>') + '</p>') +
      details('完整原始回應（未當成已證實事實）', result.raw) + details('完整執行與核對收據', json(value));
  }
  async function run() {
    if (!owner() || !packet || !selectedRoute || !$('rt-consent').checked) return;
    var seq = ++generation, ownRunner = runner;
    var consent = { packageHash: packet.hash, routeHash: selectedRoute.hash };
    $('rt-consent').checked = false;
    $('rt-result').textContent = '模型回應在完整結束並通過引用檢查前，只屬待核對原文。';
    try {
      var promise = ownRunner.run(packet, selectedRoute, consent, function (event) {
        if (seq !== generation) return;
        if (event.status === 'receiving') {
          if (event.value.text !== undefined) $('rt-result').textContent = '待核對原文（未列入摘要）\n' + event.value.text;
          status('接收中 · ' + (event.value.requestId || event.taskId) + '；可停止接收，不保證後端立即停止' +
            (event.value.storageError ? '。' + event.value.storageError : ''));
        } else if (event.status === 'running') status('本次確認已送出；不會自動改用其他模型');
      });
      sync(); var result = await promise;
      if (seq !== generation) return;
      renderResult(result); status(result.result.verified ? '已保存原文及引用核對；推論仍需人工查證' : '原文與隔離原因已保存；規則式證據整理不受影響');
    } catch (error) { if (seq === generation) {
      status('研究未完成：' + error.message);
      $('rt-result').innerHTML = '<p>本次不列入研究摘要；若儲存失敗，請立即複製下方完整原文及收據。</p>' +
        details('未完成或未保存的完整原文', error.partial || '') +
        (error.researchReceipt ? details('未保存的完整核對收據', json(error.researchReceipt)) : '');
    } }
    finally { if (runner === ownRunner) sync(); }
  }
  async function history() {
    var seq = generation;
    try {
      var all = await runner.store.all(); if (seq !== generation) return;
      $('rt-history').innerHTML = '<p>已保存 ' + all.events.length + ' 個不可覆寫狀態事件；損毀項目 ' + all.damaged.length + ' 個，原字串仍保留。</p>' +
        '<p>若最後狀態為接收中，代表沒有保存完成收據；重新開頁不會自動續跑或重送。</p>' +
        all.events.map(function (event) { return details(event.recordedAt + ' · ' + event.status + ' · ' + event.taskId, json(event)); }).join('') +
        ((all.recovery || []).length ? '<p>另有 ' + all.recovery.length + ' 個同步復原暫存；內容可變、未核對，不表示完成，不會自動重送。若含 receiptEventId，請以對應正式收據為準。</p>' + details('完整未核對復原原文（含已被正式收據取代者）', json(all.recovery)) : '') +
        (all.damaged.length ? details('無法驗證的原始紀錄', json(all.damaged)) : '');
    } catch (error) { status(error.message); }
  }
  function mount(container, getInput) {
    stop(); mountNode = container; inputReader = getInput;
    if (!container) return;
    if (!window.ResearchTaskCore || !window.STAI) { container.textContent = '研究任務元件尚未完整載入'; return; }
    try { runner = new window.ResearchTaskCore.Runner(localStorage, window.STAI); }
    catch (_) { container.textContent = '瀏覽器禁止研究紀錄儲存，研究任務暫不可用；其他市場研究仍可讀取。'; return; }
    packet = null; selectedRoute = null;
    container.innerHTML = '<div class="rt-root"><p>先產生完整公開資料包與規則式整理，再逐次確認模型。私人筆記、假說、持倉與風險設定不會送出。</p>' +
      '<div class="rw-row"><label>研究任務<select id="rt-type">' + Object.keys(window.ResearchTaskCore.types).map(function (key) {
        return '<option value="' + key + '">' + esc(window.ResearchTaskCore.types[key]) + '</option>';
      }).join('') + '</select></label><button id="rt-freeze">凍結資料與整理證據</button><button id="rt-copy" disabled>複製完整資料包</button>' +
      '<button id="rt-download" disabled>下載完整資料包</button></div><p id="rt-status" role="status" aria-live="polite">尚未凍結資料；不會自動呼叫模型</p><div id="rt-package"></div>' +
      '<div class="rw-row"><label>既有模型通道<select id="rt-mode"><option value="fast">快速通道</option><option value="deep">深度通道</option></select></label>' +
      '<button id="rt-route-read" disabled>讀取路由與模型資訊</button></div><p class="rw-small">此按鈕只查同源 /ai/local/status，會探測主機既有模型列表，不傳研究內容也不要求推理；探測費用未確認。</p>' +
      '<div id="rt-route">尚未讀取本次模型路由。</div><label><span><input type="checkbox" id="rt-consent">我已核對目的地、模型、完整資料內容及未知費用，同意本次傳送與推理</span></label>' +
      '<div class="rw-row"><button id="rt-run" disabled>確認本次資料與路由並執行</button><button id="rt-stop" disabled>停止接收</button></div>' +
      '<p class="rw-small">停止接收不保證後端立即停止。過期快照僅可用明確區分當時／事後的歷史回顧。引文核對不是模型推論正確性的認證。</p>' +
      (owner() ? '' : '<p>Reader 只可整理、複製及下載公開證據；模型執行禁止。</p>') +
      '<div id="rt-result"></div><div class="rw-row"><button id="rt-history-read">讀取本機工作紀錄</button><button id="rt-history-export">下載全部工作紀錄</button></div><div id="rt-history"></div></div>';
    $('rt-freeze').onclick = freeze;
    $('rt-type').onchange = function () { ++generation; packet = null; clearRoute(); $('rt-package').textContent = '任務已變更，請重新凍結資料；已保存紀錄仍保留。'; sync(); };
    $('rt-mode').onchange = function () { ++generation; clearRoute(); };
    $('rt-consent').onchange = sync; $('rt-route-read').onclick = readRoute; $('rt-run').onclick = run;
    $('rt-download').onclick = function () { if (packet) download('研究資料包-' + packet.type + '-' + packet.hash + '.json', packet); };
    $('rt-copy').onclick = async function () {
      try { await navigator.clipboard.writeText(json(packet)); status('已複製完整凍結資料包'); }
      catch (_) { status('剪貼簿不可用；可下載完整資料包或從展開內容複製'); }
    };
    $('rt-stop').onclick = function () {
      if (runner) runner.stop().catch(function (error) { status(error.message + '；停止接收已要求，但紀錄未保存'); });
      status('已要求停止接收；不保證後端立即停止，晚到結果不列入摘要');
    };
    $('rt-history-read').onclick = history;
    $('rt-history-export').onclick = async function () {
      try { download('研究工作紀錄-' + new Date().toISOString().slice(0, 10) + '.json', await runner.store.all()); }
      catch (error) { status(error.message); }
    };
    sync();
  }
  function stop() { ++generation; if (routeController) routeController.abort(); routeController = null; if (runner) runner.stop().catch(function (error) { status(error.message + '；停止接收紀錄未保存'); }); }
  window.ResearchTasks = { mount: mount, stop: stop };
})();

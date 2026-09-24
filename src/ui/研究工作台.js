/* 已提交快照 → 證據 → 個股關聯 → 不可覆寫筆記 → 事後回顧。 */
(function () {
  'use strict';
  var active = false, generation = 0, controller, data, subject, selectedRecord, store, draftTimer;
  var history = [], records = [], draftKey;
  var verifiedRecord = null, recordSequence = 0, moreController = null;
  var studyControllers = {}, observationRows = [], observationCursor = null;
  function $(id) { return document.getElementById(id); }
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  }); }
  function pretty(v) { return typeof v === 'string' ? v : JSON.stringify(v, null, 2); }
  function shortTime(value) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return value.slice(5).replace('-', '/');
    var parsed = new Date(value || '');
    if (!Number.isFinite(parsed.getTime())) return '日期未知';
    return parsed.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function message(text) { if ($('rw-status')) $('rw-status').textContent = text; }
  function portfolioAllowed() { return !window.ST_PRIVATE_WEB_PROFILE || window.ST_PRIVATE_WEB_PROFILE.role === 'owner'; }
  function portfolio() {
    if (!portfolioAllowed()) return null;
    return window.PortfolioContext ? window.PortfolioContext.resolve() : null;
  }
  function renderPortfolioSource() {
    if (!$('rw-portfolio-mode')) return;
    var allowed = portfolioAllowed(), api = window.PortfolioContext;
    $('rw-portfolio-mode').disabled = !allowed || !api;
    $('rw-simulation-edit').disabled = !allowed || !api || !window.ShellV5;
    if (!allowed) {
      $('rw-portfolio-mode').value = '';
      $('rw-portfolio-source').textContent = 'Reader：不讀取實際持倉、觀察池或模擬情境；公開標的研究仍可使用。'; return;
    }
    if (!api) { $('rw-portfolio-source').textContent = '共用投組模式尚未載入，關聯來源未知。'; return; }
    try {
      $('rw-portfolio-mode').value = api.getMode();
      var context = portfolio();
      $('rw-portfolio-source').textContent = '目前研究關聯：' + context.label + ' · 來源 ' + (context.sourceLabel || context.source || '未知') +
        (context.inputVersion ? ' · 輸入版本 ' + context.inputVersion : '') +
        ' · ' + (context.ready ? '輸入已完整核對' : '輸入不足，直接關聯未知') +
        '。切換只改本次研究前提，已保存紀錄維持原來源；模擬情境不代表實際持倉。';
    } catch (error) { $('rw-portfolio-source').textContent = '關聯來源無法讀取：' + error.message + '；不改用其他模式。'; }
  }
  function details(title, value) { return '<details><summary>' + esc(title) + '</summary><pre>' + esc(pretty(value)) + '</pre></details>'; }
  function css() {
    if ($('rw-css')) return;
    var el = document.createElement('style'); el.id = 'rw-css';
    el.textContent = '#rw-root{box-sizing:border-box;max-width:1400px;margin:auto;padding:12px;color:var(--txt,#e2e8f0);font:13px/1.6 sans-serif;overflow-wrap:anywhere}' +
      '#rw-root *{box-sizing:border-box;min-width:0}#rw-root h2{margin:0;font-size:20px}#rw-root h3{margin:4px 0 10px;font-size:16px}' +
      '#rw-root section{border:1px solid var(--border,#334155);background:var(--panel,#101d30);border-radius:8px;padding:12px;margin:12px 0}' +
      '#rw-root .rw-row{display:flex;gap:8px;flex-wrap:wrap;align-items:end}#rw-root label{display:flex;flex-direction:column;gap:4px;flex:1 1 150px}' +
      '#rw-root button,#rw-root input,#rw-root select,#rw-root textarea{font:inherit;color:inherit;background:var(--bg,#071322);border:1px solid #60758d;border-radius:5px;padding:7px;max-width:100%}' +
      '#rw-root button{cursor:pointer;min-height:36px}#rw-root button:disabled{opacity:.55;cursor:default}#rw-root :focus-visible{outline:2px solid #facc15;outline-offset:3px}' +
      '#rw-root textarea{width:100%;min-height:90px;resize:vertical}#rw-root .rw-small{font-size:12px;color:#b6c5d8}' +
      '#rw-root pre{white-space:pre-wrap;font:12px/1.6 monospace;overflow-wrap:anywhere;max-width:100%}#rw-root summary{cursor:pointer;padding:8px 0}' +
      '#rw-root .rw-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}#rw-root .rw-change{border-left:3px solid #38bdf8;padding:8px 10px;margin:8px 0;background:#122238}' +
      '#rw-root a{color:#7dd3fc}#rw-root .rw-note{white-space:pre-wrap}#rw-root .rw-warning{color:#fcd34d}#rw-root [hidden]{display:none!important}' +
      '@media(max-width:760px){#rw-root{padding:8px;font-size:12px}#rw-root .rw-grid{grid-template-columns:1fr}#rw-root button{min-height:40px}}';
    document.head.appendChild(el);
  }
  function draft() {
    return { title: $('rw-title').value, note: $('rw-note').value,
      hypothesis: $('rw-hypothesis').value, invalidation: $('rw-invalidation').value };
  }
  function preserveDraft() {
    if (!$('rw-title')) return;
    try { localStorage.setItem(draftKey, JSON.stringify(draft())); }
    catch (_) { message('草稿無法寫入瀏覽器；請先複製筆記或匯出，不要關閉頁面'); }
  }
  function fillDraft(value) {
    ['title', 'note', 'hypothesis', 'invalidation'].forEach(function (name) { $('rw-' + name).value = value[name] || ''; });
  }
  function mount() {
    if ($('rw-root')) return;
    css();
    var target = $('mount-research'); if (!target) return;
    var storageError = null;
    try { store = new window.ResearchWorkflow.Store(localStorage); }
    catch (_) { storageError = '瀏覽器禁止儲存，仍可讀取市場研究；筆記請先自行複製保存'; }
    var tabId = Date.now().toString(36) + Math.random().toString(36).slice(2);
    try {
      tabId = sessionStorage.getItem('st.research.draftTab') || tabId;
      sessionStorage.setItem('st.research.draftTab', tabId);
    } catch (_) { storageError = '瀏覽器禁止分頁儲存，草稿無法在重新開啟後自動還原；請匯出研究備份'; }
    draftKey = 'st.research.draft.v1.' + tabId;
    target.innerHTML = '<main id="rw-root"><div class="rw-row"><h2>每日研究工作台</h2><button id="rw-refresh">讀取最新快照</button>' +
      '<button id="rw-updates">更新工作中心</button></div><p id="rw-status" role="status" aria-live="polite">正在讀取已提交快照</p>' +
      '<p class="rw-small">市場快照唯讀；私人筆記與持倉關聯只存於此瀏覽器。重新讀取不會抓行情，也不會改寫已保存研究。</p>' +
      '<section aria-labelledby="rw-today"><h3 id="rw-today">今日變化與證據</h3><div class="rw-row">' +
      '<label>目前快照<select id="rw-current"></select></label><label>比較快照<select id="rw-previous"></select></label>' +
      '<button id="rw-compare">比較</button><button id="rw-more">載入更早快照</button></div><div id="rw-changes"></div><div id="rw-evidence"></div></section>' +
      '<section aria-labelledby="rw-subject-title"><h3 id="rw-subject-title">標的研究與持倉關聯</h3>' +
      '<div class="rw-row"><label>研究關聯模式<select id="rw-portfolio-mode"><option value="">來源尚未核對</option><option value="actual">實際持倉</option><option value="observation_pool">觀察池（等權）</option><option value="simulation">模擬情境</option></select></label>' +
      '<button id="rw-simulation-edit">前往投組頁編輯模擬情境</button></div><p id="rw-portfolio-source" class="rw-small" role="status">關聯來源尚未核對</p><div class="rw-row">' +
      '<label>台股／ETF 代號<input id="rw-symbol" value="2330" maxlength="10" autocomplete="off"></label>' +
      '<button id="rw-subject-load">讀取已保存標的研究</button><button id="rw-chart">開啟圖表</button></div><div id="rw-subject">尚未選取標的研究</div></section>' +
      '<section aria-labelledby="rw-journal-title"><h3 id="rw-journal-title">保存研究與回顧</h3>' +
      '<div class="rw-row"><label>研究標題<input id="rw-title" maxlength="240"></label></div>' +
      '<div class="rw-grid"><label>當時假說<textarea id="rw-hypothesis" maxlength="10000"></textarea></label>' +
      '<label>推翻條件與缺漏證據<textarea id="rw-invalidation" maxlength="10000"></textarea></label></div>' +
      '<label>研究筆記／事後回顧<textarea id="rw-note" maxlength="20000"></textarea></label>' +
      '<div class="rw-row"><button id="rw-save">保存目前快照與研究</button><button id="rw-save-review" disabled>新增所選紀錄的事後回顧</button>' +
      '<button id="rw-export">匯出全部研究備份</button><label>匯入研究備份<input type="file" id="rw-import" accept="application/json,.json"></label></div>' +
      '<p class="rw-small">每次保存都新增紀錄，原文及當時快照保留。匯出檔可能含私人筆記與持倉資訊。</p>' +
      '<label>已保存研究<select id="rw-records"></select></label><div id="rw-record"></div></section>' +
      '<section aria-labelledby="rw-ai-title"><h3 id="rw-ai-title">有證據的研究任務</h3><div id="rw-ai"></div></section>' +
      '<section aria-labelledby="rw-validation-title"><h3 id="rw-validation-title">預警前向驗證</h3>' +
      '<p class="rw-small">依規則版本分開統計已觸發、未觸發、未知與未成熟觀測；未來樣本須逐日累積，不能由歷史資料補造。</p>' +
      '<div class="rw-row"><button id="rw-validation-load">讀取已保存驗證</button><button id="rw-validation-more" disabled>更多觀測</button>' +
      '<label>原始觀測<select id="rw-observation"><option value="">尚未讀取</option></select></label><button id="rw-replay">核對凍結規則輸出</button></div>' +
      '<div id="rw-validation"></div><div id="rw-replay-result"></div></section>' +
      '<section aria-labelledby="rw-portfolio-title"><h3 id="rw-portfolio-title">突破、VIDYA 與資金限制研究</h3>' +
      '<p class="rw-small">2330／0050 近五年公開資料的工程假設。固定規則、共用現金、持股上限與成本情境分開比較；公司行動權利無法計價時保留未知，不宣稱已證實策略有效。</p>' +
      '<button id="rw-portfolio-load">以已保存資料計算組合研究</button><div id="rw-portfolio-result"></div></section></main>';
    $('rw-refresh').onclick = function () { load(); };
    $('rw-updates').onclick = function () { if (window.UpdateCenter) window.UpdateCenter.open(); };
    $('rw-compare').onclick = function () { load($('rw-current').value, $('rw-previous').value); };
    $('rw-more').onclick = more;
    $('rw-validation-load').onclick = function () { loadValidation(false); };
    $('rw-validation-more').onclick = function () { loadValidation(true); };
    $('rw-portfolio-load').onclick = loadPortfolioStudy;
    $('rw-replay').onclick = replayObservation;
    $('rw-subject-load').onclick = loadSubject;
    $('rw-portfolio-mode').onchange = function () {
      if (!portfolioAllowed() || !window.PortfolioContext) return;
      try { window.PortfolioContext.setMode(this.value); renderPortfolioSource(); renderSubject(); }
      catch (error) { message(error.message); renderPortfolioSource(); }
    };
    $('rw-simulation-edit').onclick = function () {
      if (!portfolioAllowed() || !window.PortfolioContext || !window.ShellV5) return;
      try { window.PortfolioContext.setMode('simulation'); window.ShellV5.go('book'); }
      catch (error) { message(error.message); }
    };
    $('rw-chart').onclick = function () {
      try { var sym = window.ResearchWorkflow.normalizeSymbol($('rw-symbol').value); window.ShellV5.go('chart', { sym: sym, mkt: 'TW' }); }
      catch (error) { message(error.message); }
    };
    $('rw-save').onclick = function () { save(false); };
    $('rw-save-review').onclick = function () { save(true); };
    $('rw-export').onclick = function () { download('研究備份-' + new Date().toISOString().slice(0, 10) + '.json', store.exportAll()); };
    $('rw-import').onchange = async function () {
      var file = this.files[0]; if (!file) return;
      try {
        if (file.size > 30 * 1024 * 1024) throw new Error('備份超過 30 MB，請在本機檢查檔案後再匯入');
        var n = await store.importAll(JSON.parse(await file.text())); listRecords(); message('已匯入 ' + n + ' 筆，原有紀錄保留');
      } catch (error) { message(error.message); } finally { this.value = ''; }
    };
    $('rw-records').onchange = showRecord;
    ['title', 'note', 'hypothesis', 'invalidation'].forEach(function (name) {
      $('rw-' + name).oninput = function () { clearTimeout(draftTimer); draftTimer = setTimeout(preserveDraft, 200); };
    });
    try { fillDraft(JSON.parse(localStorage.getItem(draftKey) || '{}')); }
    catch (_) { message('既有草稿格式無法讀取，原始內容仍保留於瀏覽器'); }
    listRecords();
    if (!store) ['rw-save', 'rw-save-review', 'rw-export', 'rw-import'].forEach(function (key) { $(key).disabled = true; });
    if (storageError) message(storageError);
    renderPortfolioSource();
  }
  function options() {
    [data && data.current, data && data.previous].filter(Boolean).forEach(function (r) {
      if (!history.some(function (h) { return h.snapshotId === r.snapshotId; })) history.push(r);
    });
    ['current', 'previous'].forEach(function (name) {
      var el = $('rw-' + name), selection = data && data[name] && data[name].snapshotId;
      el.innerHTML = (name === 'previous' ? '<option value="">自動選擇前一份</option>' : '') + history.map(function (row) {
        return '<option value="' + esc(row.snapshotId) + '" title="' + esc((row.asOf || '日期未知') + ' · 修訂 ' + row.revision) + '">' +
          esc(shortTime(row.asOf)) + ' · #' + esc(row.revision) + '</option>';
      }).join('');
      if (selection) el.value = selection;
    });
    $('rw-more').disabled = !(data && data.nextBefore);
  }
  function render() {
    if (!data || !data.current) { $('rw-changes').textContent = '尚無已提交快照，請由更新工作中心建立。'; $('rw-evidence').textContent = ''; return; }
    var current = data.current, previous = data.previous;
    var significant = data.changes.filter(function (x) { return x.kind !== 'source_time'; });
    var html = '<p>資料時間 ' + esc(current.asOf || '未知') + ' · 修訂 ' + esc(current.revision) + ' · ' + esc(current.snapshotId) + '</p>' +
      '<p>比較 ' + esc(previous ? (previous.asOf + '／修訂 ' + previous.revision) : '尚無前一份快照') + '</p>';
    if (!significant.length) html += '<p>沒有可確認的新狀態變化；不將重新建置時間視為新市場事件。</p>';
    significant.slice(0, 3).forEach(function (row) {
      html += '<article class="rw-change"><strong>' + esc(row.title) + '</strong>' + details('查看前後證據', row) + '</article>';
    });
    html += details('全部差異（' + data.changes.length + ' 項，含僅來源時間變動）', data.changes);
    html += details('資料品質與使用前提', current.dataQuality || { note: '資料品質資訊不足，不能當成即時行情' });
    $('rw-changes').innerHTML = html;
    $('rw-evidence').innerHTML = '<h4>完整證據清單（' + current.evidence.length + ' 項）</h4>' + current.evidence.map(function (row) {
      return '<details id="rw-e-' + esc(row.id.replace(/[^a-zA-Z0-9_-]/g, '-')) + '"><summary>' + esc(row.metric || row.id) + ' · ' +
        esc(row.quality || '品質未知') + ' · ' + esc(row.asOf || '日期未知') + '</summary><pre>' + esc(pretty(row)) + '</pre></details>';
    }).join('') + details('快照完整研究內容', current);
    options(); renderSubject();
  }
  async function request(path, signal) {
    var response = await fetch((window.SERVER || '') + path, { signal: signal, cache: 'no-store' });
    var result = await response.json(); if (!response.ok || result.ok === false) throw new Error(result.error || '研究讀取失敗'); return result;
  }
  async function studyRequest(key, path) {
    if (studyControllers[key]) studyControllers[key].abort();
    var own = new AbortController(); studyControllers[key] = own;
    var timer = setTimeout(function () { own.abort(); }, key === 'portfolio' ? 45000 : 15000);
    try {
      var result = await request(path, own.signal);
      if (!active || studyControllers[key] !== own) return null;
      return result;
    } catch (error) {
      if (active && studyControllers[key] === own) message(error.name === 'AbortError' ? '研究讀取逾時或已停止，原結果保留' : error.message);
      return null;
    } finally { clearTimeout(timer); if (studyControllers[key] === own) delete studyControllers[key]; }
  }
  async function loadValidation(moreRows) {
    if (moreRows && !observationCursor) return;
    var result = await studyRequest('validation', '/research/validation' + (moreRows ? '?before=' + observationCursor : ''));
    if (!result) return;
    observationRows = moreRows ? observationRows.concat(result.observations || []) : (result.observations || []);
    observationCursor = result.nextBefore;
    $('rw-validation-more').disabled = !observationCursor;
    $('rw-observation').innerHTML = '<option value="">選擇原始觀測</option>' + observationRows.map(function (row, index) {
      return '<option value="' + esc(row.observationId) + '" title="' + esc(row.originSession + ' · ' + row.signalId) + '">' +
        esc(String(row.originSession || '').slice(5) + ' · 第 ' + (index + 1) + ' 筆') + '</option>';
    }).join('');
    var v = result.validation || {};
    $('rw-validation').innerHTML = '<p>已保存觀測 ' + esc(v.observations || 0) + ' 筆 · 依版本與訊號分層 ' + esc((v.strata || []).length) + ' 組</p>' +
      (v.strata || []).map(function (row) { return details(row.signalId + ' · ' + row.direction + ' · ' + row.observations + ' 筆', row); }).join('') +
      details('驗證口徑、未知與母體限制', { status: v.status, version: v.version, notes: v.notes, retrospectiveBackfill: v.retrospectiveBackfill }) +
      details('已載入原始觀測完整內容（' + observationRows.length + ' 筆）', observationRows);
  }
  async function replayObservation() {
    var id = $('rw-observation').value;
    if (!id) { message('請先選擇已保存的原始觀測'); return; }
    var result = await studyRequest('replay', '/research/validation?replay=' + encodeURIComponent(id));
    if (result) $('rw-replay-result').innerHTML = '<p>凍結輸入與目前相同版本規則：核對一致</p>' + details('完整重播證據與範圍', result);
  }
  async function loadPortfolioStudy() {
    $('rw-portfolio-load').disabled = true;
    try {
      var result = await studyRequest('portfolio', '/research/portfolio');
      if (!result) return;
      function metric(value) { return Number.isFinite(value) ? value.toFixed(2) + '%' : '未知／資料不足'; }
      var labels = { complete: '計算完成（仍屬研究）', limited: '部分資料或持有權利未知', unavailable: '資料不足，尚不能計算', unknown: '未知', insufficient: '樣本不足' };
      var html = '<p>研究狀態：' + esc(labels[result.status] || result.status || '未知') + '</p>' +
        (result.reason ? '<p class="rw-warning">' + esc(result.reason) + '</p>' : '') +
        details('工程假設、資料範圍與限制', { version: result.version, config: result.config, range: result.range, sourceStatus: result.sourceStatus, inputDigest: result.inputDigest, notes: result.notes });
      function renderSizing(report, heading) {
        var part = '<h3>' + esc(heading) + '</h3>';
        (report.rules || []).forEach(function (rule) {
          part += '<h4>' + esc(rule.label || rule.key) + '</h4>';
          Object.keys(rule.scenarios || {}).forEach(function (key) {
            var scenario = rule.scenarios[key], label = { gross: '未扣成本', baseNet: '單邊成本 0.25%', stressNet: '單邊成本 0.50%' }[key] || key;
            part += details(label + ' · 報酬 ' + metric(scenario.totalReturnPct) + ' · 最大回撤 ' + metric(scenario.maxDrawdownPct), scenario);
          });
        });
        return part;
      }
      html += renderSizing(result, '依初始本金配置');
      if (result.equitySizing) {
        html += '<p>複利比較依前一個交易日已知收盤權益配置；權益未知時停止新配置。兩種配置各自計算，未共用現金。</p>';
        html += renderSizing(result.equitySizing, '依前日權益配置（複利比較）');
        html += details('複利比較的完整前提與基準', { config: result.equitySizing.config, inputDigest: result.equitySizing.inputDigest,
          range: result.equitySizing.range, notes: result.equitySizing.notes, benchmark: result.equitySizing.benchmark });
      }
      html += details('同期間 0050 基準及完整資料品質', { benchmark: result.benchmark, assets: result.assets });
      $('rw-portfolio-result').innerHTML = html;
    } finally { if (active) $('rw-portfolio-load').disabled = false; }
  }
  async function load(current, previous) {
    if (moreController) { moreController.abort(); moreController = null; }
    var seq = ++generation; if (controller) controller.abort(); controller = new AbortController();
    var own = controller, deadline = setTimeout(function () { own.abort(); }, 15000); message('正在讀取已提交研究快照');
    try {
      var query = '?current=' + encodeURIComponent(current || '') + '&previous=' + encodeURIComponent(previous || '');
      var result = await request('/research/workflow' + query, own.signal);
      if (!active || seq !== generation) return;
      data = result; history = result.history; render(); message('已讀取已提交快照；行情來源沒有因讀取而更新');
    } catch (error) { if (active && seq === generation) message(error.name === 'AbortError' ? '讀取已停止或逾時，前次內容保留，可重試' : error.message); }
    finally { clearTimeout(deadline); }
  }
  async function more() {
    if (!data || !data.nextBefore || moreController) return;
    var seq = generation, cursor = data.nextBefore;
    var own = new AbortController(); moreController = own;
    var timeout = setTimeout(function () { own.abort(); }, 15000);
    $('rw-more').disabled = true;
    try {
      var result = await request('/research/workflow?before=' + cursor, own.signal);
      if (!active || seq !== generation) return;
      var ids = new Set(history.map(function (r) { return r.snapshotId; }));
      result.history.forEach(function (r) { if (!ids.has(r.snapshotId)) history.push(r); });
      data.nextBefore = result.nextBefore; options();
    } catch (error) { if (active && seq === generation) message(error.name === 'AbortError' ? '歷史讀取逾時或已停止；原快照保留，可重試' : error.message); }
    finally { clearTimeout(timeout); if (moreController === own) { moreController = null; if (active) options(); } }
  }
  var subjectGeneration = 0, subjectController;
  async function loadSubject() {
    var sym;
    try { sym = window.ResearchWorkflow.normalizeSymbol($('rw-symbol').value); }
    catch (error) { message(error.message); return; }
    var seq = ++subjectGeneration; if (subjectController) subjectController.abort(); subjectController = new AbortController();
    var own = subjectController, timer = setTimeout(function () { own.abort(); }, 25000); message('讀取已保存日線及各領域公開研究；原內容保留至讀取完成');
    try {
      var result = await Promise.allSettled([
        /^\d{4,6}$/.test(sym) ? request('/kline-events?sym=' + encodeURIComponent(sym) + '&range=1y', own.signal) : Promise.resolve(null),
        request('/research/subject?symbol=' + encodeURIComponent(sym), own.signal)
      ]);
      if (!active || seq !== subjectGeneration) return;
      if (result[1].status !== 'fulfilled') throw result[1].reason;
      var daily = result[0].status === 'fulfilled' ? result[0].value : null;
      var technicalReason = result[0].status === 'rejected' ? String(result[0].reason.message || '日線讀取失敗') : null;
      var nextSubject = await window.ResearchWorkflow.freezeSubject(sym, daily, result[1].value, window.SC_CHAINS && window.SC_CHAINS.TW, technicalReason);
      if (!active || seq !== subjectGeneration) return;
      subject = nextSubject;
      renderSubject(); message('標的整合研究已載入；各領域來源日期分開保留，未知不當成即時資料');
    } catch (error) { if (active && seq === subjectGeneration) message(error.name === 'AbortError' ? '個股研究等待已停止，原內容保留' : error.message + '；原標的研究完整保留，可重試'); }
    finally { clearTimeout(timer); }
  }
  function subjectTools() {
    var shell = window.ShellV5 && typeof window.ShellV5.go === 'function';
    return {
      fundamentals: { label: '開啟此股估值承接研究', available: /^\d{4}$/.test(subject.symbol) && window.ValuationResearchUI && typeof window.ValuationResearchUI.open === 'function', run: function () { window.ValuationResearchUI.open(subject.symbol); } },
      flows: { label: '開啟三大法人頁', available: shell, run: function () { window.ShellV5.go('institutional', { sym: subject.symbol, mkt: 'TW' }); } },
      supplyChainNews: { label: '開啟市場快訊頁', available: shell, run: function () { window.ShellV5.go('news', { sym: subject.symbol, mkt: 'TW' }); } },
      peersThemes: { label: '開啟台股類股熱力頁', available: shell, run: function () { window.ShellV5.go('heat', { mkt: 'TW' }); } },
      etfResearch: { label: '開啟 ETF 觀測池', available: typeof window.openEtfMgrModal === 'function', run: function () { window.openEtfMgrModal(); } },
      supplyChainClassification: { label: '開啟既有供應鏈工具', available: typeof window.supplyChainOpen === 'function', run: function () { window.supplyChainOpen(); } }
    };
  }
  function renderSubject() {
    renderPortfolioSource();
    if (!$('rw-subject') || !subject) return;
    var relation = window.ResearchWorkflow.relevance(subject.symbol, portfolio());
    var saved = subject.savedResearch || {}, report = saved.report || {}, tools = subjectTools();
    var labels = { fundamentals: '基本面與估值資料', flows: '法人與籌碼', supplyChainNews: '已保存公開新聞與事件', peersThemes: '同業與主題比較', etfResearch: 'ETF 研究', supplyChainClassification: '供應鏈研究分類' };
    var availability = { available: '已有保存證據', partial: '部分資料／前提受限', unknown: '未知／尚無保存證據', not_applicable: '已核對為不適用' };
    var domains = Object.assign({}, report.domains || {}, { supplyChainClassification: saved.supplyChainClassification });
    var content = Object.keys(labels).map(function (key) {
      var domain = domains[key] || { availability: 'unknown', evidence: [], source: [], asOf: null, reason: '尚無保存資料' }, tool = tools[key];
      return '<article class="rw-change"><h4>' + esc(labels[key]) + '</h4><p><b>' + esc(availability[domain.availability] || '狀態未知') + '</b> · 來源資料日 ' + esc(domain.asOf || '未知') + '</p>' +
        '<p>來源：' + esc((domain.source || []).join('；') || '未知') + '</p><p>' + esc(domain.reason || '各筆證據日期及適用前提請分別核對') + '</p>' +
        (domain.evidence || []).map(function (row) { return details('證據 ' + row.evidenceId + ' · ' + (row.asOf || '資料日期未知'), row); }).join('') +
        details('完整領域資料與限制', domain) + '<button type="button" data-rw-tool="' + key + '"' + (tool.available ? '' : ' disabled') + '>' + esc(tool.label) + '</button>' +
        (tool.available ? '' : '<p class="rw-small">既有工具尚未載入或不支援此代號；上方保存證據仍可檢視。</p>') + '</article>';
    }).join('');
    $('rw-subject').innerHTML = '<p>' + esc(subject.symbol) + ' · 個股資料日 ' + esc(subject.asOf || '未知') + ' · ' + esc(relation.label) + '</p>' +
      '<p>' + esc(subject.premise) + '</p><p class="rw-small">' + esc(relation.note || '') + '</p>' +
      '<p class="rw-small">下列工具沿用既有功能；法人、快訊、ETF 池為整體頁面，供應鏈工具沿終端機目前市場，不代表已自動篩選本標的。開啟工具可能沿其既有流程讀取資料；本次整合讀取本身不更新來源。</p>' +
      '<div class="rw-grid">' + content + '</div>' + details('原始與參考價比較、各領域完整凍結研究', subject) + details('直接持倉關聯', relation);
    $('rw-subject').querySelectorAll('[data-rw-tool]').forEach(function (button) {
      button.onclick = function () { var tool = tools[button.getAttribute('data-rw-tool')]; if (tool && tool.available) tool.run(); };
    });
  }
  function listRecords() {
    var result;
    try { result = store ? store.list() : { records: [], damagedKeys: [] }; }
    catch (_) { message('瀏覽器研究清單無法讀取，原資料保留'); return; }
    records = result.records;
    $('rw-records').innerHTML = '<option value="">選取紀錄（' + records.length + ' 筆）</option>' + records.map(function (r, index) {
      return '<option value="' + r.id + '" title="' + esc(r.createdAt + ' · ' + r.title) + '">' +
        esc(shortTime(r.createdAt)) + ' · #' + (index + 1) + '</option>';
    }).join('');
    if (result.damagedKeys.length) message('有 ' + result.damagedKeys.length + ' 筆紀錄無法解析，原始資料保留且會包含於備份');
  }
  async function showRecord() {
    var sequence = ++recordSequence; verifiedRecord = null;
    var selected = $('rw-records').value; selectedRecord = records.find(function (r) { return r.id === selected; }) || null;
    $('rw-save-review').disabled = true;
    if (!selectedRecord) { $('rw-record').textContent = ''; return; }
    var record = selectedRecord, valid = false;
    try { valid = await store.verify(record); } catch (_) { valid = false; }
    if (selectedRecord !== record || !active || sequence !== recordSequence) return;
    verifiedRecord = valid ? record : null;
    $('rw-record').innerHTML = '<p class="' + (valid ? '' : 'rw-warning') + '">' + (valid ? '內容摘要核對通過' : '內容摘要不符，不可作為原始研究證據') + '</p>' +
      '<h4>' + esc(record.title) + '</h4>' +
      '<p>當時快照 ' + esc(record.snapshot.snapshotId) + ' · ' + esc(record.snapshot.asOf) + '</p>' +
      '<p class="rw-note">' + esc(record.note) + '</p>' + details('當時假說、證據與完整紀錄', record);
    $('rw-save-review').disabled = !valid;
  }
  async function save(review) {
    if (!data || !data.current) { message('尚無可保存的已提交快照'); return; }
    if (review && !verifiedRecord) return;
    preserveDraft(); var input = draft();
    try {
      var prior = review ? selectedRecord : null;
      if (prior && !await store.verify(prior)) throw new Error('原研究摘要不符，停止建立回顧');
      if (prior && data.current.revision <= prior.snapshot.revision) throw new Error('請先讀取晚於原研究的市場快照，再新增事後回顧');
      var r = await store.save(Object.assign(input, { snapshot: prior ? prior.snapshot : data.current,
        comparison: prior ? prior.comparison : data.previous, subject: prior ? prior.subject : subject, symbol: prior ? prior.symbol : subject && subject.symbol,
        portfolio: prior ? prior.portfolio : portfolio(), reviewOf: prior && prior.id,
        outcome: prior ? { observedAt: new Date().toISOString(), snapshot: data.current,
          subject: subject && subject.symbol === prior.symbol ? subject : null,
          note: '這是事後取得的結果，不回寫當時假說；與原紀錄的日期及標的需分別核對。' } : null }));
      listRecords(); $('rw-records').value = r.id; await showRecord();
      message('研究紀錄已保存，原紀錄不變。草稿保留，可繼續補充。');
    } catch (error) { message(error.message); }
  }
  function download(name, value) {
    var url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' }));
    var a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }
  function activate() {
    active = true; mount();
    // 面板也供決策中心使用；每次回到工作台必須重新綁定容器與已核對紀錄。
    if (window.ResearchTasks) window.ResearchTasks.mount($('rw-ai'), function () {
      return { data: data, subject: subject, record: verifiedRecord };
    });
    renderPortfolioSource(); if (data) render(); else load();
  }
  function deactivate() {
    Object.keys(studyControllers).forEach(function (key) { studyControllers[key].abort(); }); studyControllers = {};
    if (moreController) { moreController.abort(); moreController = null; }
    active = false; generation++; subjectGeneration++; if (controller) controller.abort(); if (subjectController) subjectController.abort();
    clearTimeout(draftTimer); preserveDraft(); if (window.ResearchTasks) window.ResearchTasks.stop();
  }
  window.addEventListener('storage', function (e) { if (active && e.key && e.key.indexOf('st.research.record.v1.') === 0) listRecords(); });
  window.addEventListener('portfolioContext', function () { if (active) renderSubject(); });
  window.addEventListener('pagehide', function () { clearTimeout(draftTimer); preserveDraft(); });
  window.ResearchDesk = { activate: activate, deactivate: deactivate };
})();

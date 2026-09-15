/* ============================================================================
 * copilot_v3.js — v4.0 本機 AI 副駕面板
 * ----------------------------------------------------------------------------
 * 自然語言問盤。自動把「當前個股 + 持倉 + 自選」整理成 context 餵給本機 LLM
 * (LM Studio,經 /ai/local)。只送真實資料(data integrity);顏色中性。
 * 模型由 ST 後端固定；瀏覽器不可改端點或任意指定模型。
 * ========================================================================== */
(function () {
  'use strict';

  var _lastReply = '', _lastQ = '', activeTask = null;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }

  function mdLite(t) {
    // 極簡 markdown:跳脫 → **粗體** → 換行
    var h = esc(t);
    h = h.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    h = h.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
    return h;
  }

  function injectStyle() {
    if (document.getElementById('cp-style')) return;
    var s = document.createElement('style'); s.id = 'cp-style';
    s.textContent =
      '#cp-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}' +
      '#cp-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(720px,95vw);max-height:90vh;display:flex;flex-direction:column;color:#e2e8f0;font-size:12px}' +
      '#cp-box h3{margin:0;padding:12px 16px;font-size:15px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #1e293b}' +
      '#cp-box .x{cursor:pointer;color:#64748b;font-size:18px}#cp-box .x:hover{color:#e2e8f0}' +
      '#cp-out{flex:1;overflow:auto;padding:14px 16px;line-height:1.7;min-height:120px}' +
      '.cp-q{display:flex;flex-wrap:wrap;gap:6px;padding:0 16px 8px}' +
      '.cp-q button{background:#16213a;border:1px solid #28324d;color:#cbd5e1;border-radius:14px;padding:4px 10px;font-size:11px;cursor:pointer}' +
      '.cp-q button:hover{border-color:#F5C518;color:#F5C518}' +
      '.cp-in{display:flex;gap:8px;padding:10px 16px;border-top:1px solid #1e293b;align-items:flex-end}' +
      '#cp-text{flex:1;background:#0b1220;border:1px solid #334155;color:#e2e8f0;border-radius:8px;padding:8px;font-size:12px;resize:vertical;min-height:38px;font-family:inherit}' +
      '#cp-send{background:#F5C518;color:#0f172a;border:none;border-radius:8px;padding:8px 14px;font-weight:700;cursor:pointer;white-space:nowrap}' +
      '#cp-model{background:#0b1220;border:1px solid #334155;color:#cbd5e1;border-radius:6px;padding:4px 6px;font-size:10px;max-width:180px}' +
      '.cp-meta{font-size:10px;color:#64748b;margin-top:10px}' +
      '.cp-keep{background:#16213a;border:1px solid #28324d;color:#cbd5e1;border-radius:12px;padding:2px 10px;font-size:10px;cursor:pointer;margin-left:6px}' +
      '.cp-keep:hover{border-color:#F5C518;color:#F5C518}.cp-keep-st{font-size:10px;color:#94a3b8;margin-left:4px}' +
      '#cp-box button:disabled{opacity:.45;cursor:wait}#cp-status{overflow-wrap:anywhere}#cp-box .cp-hint{font-size:10px;color:#64748b;padding:0 16px 8px}';
    document.head.appendChild(s);
  }

  var QUICK = [
    '我的持倉整體風險如何?最該注意哪一檔?',
    '我的持倉是不是太集中在某一段供應鏈?',
    '當前這檔的多空判斷與關鍵價位?',
    '今天台股盤面結構偏多還偏空?'
  ];

  async function loadModels() {
    var sel = document.getElementById('cp-model');
    if (!sel) return;
    try {
      var r = await fetch('/ai/local/status');
      var d = await r.json();
      var fast = d && d.modes && d.modes.fast;
      if (d.ok && fast && fast.available) {
        sel.innerHTML = '<option value="">' + esc((fast.host || 'EVO-T1') + ' · ' +
          (fast.provider || 'LM Studio') + ' · ' + (fast.model || '固定模型')) + '</option>';
      } else {
        sel.innerHTML = '<option value="">(EVO-T1 快速模型未就緒)</option>';
      }
    } catch (e) {
      sel.innerHTML = '<option value="">(無法連線)</option>';
    }
  }

  function busy(value) {
    document.querySelectorAll('#cp-send, .cp-q button').forEach(function (el) { el.disabled = value; });
    var cancel = document.getElementById('cp-cancel'); if (cancel) cancel.hidden = !value;
  }
  async function send(preset) {
    if (activeTask) return;
    var text = String(preset || (document.getElementById('cp-text') || {}).value || '').trim();
    if (!text) return;
    var out = document.getElementById('cp-out'), status = document.getElementById('cp-status');
    _lastReply = ''; _lastQ = '';
    busy(true);
    out.textContent = '正在準備本機模型；載入與推理可能需要數分鐘，收到正文後會逐步顯示。';
    var task = window.STAI.request({ prompt: text, context: window.STAI.context(),
      onText: function (reply) { if (activeTask === task) out.innerHTML = mdLite(reply); },
      onStatus: function (info) { status.textContent = '已等候 ' + info.elapsedSeconds + ' 秒 · ' +
        (info.hasText ? '接收正文中' : '模型準備／推理中') + ' · ' + info.requestId; }
    });
    activeTask = task;
    try {
      var result = await task.promise;
      if (activeTask !== task) return;
      _lastReply = result.text; _lastQ = text;
      status.textContent = '完成 · ' + result.elapsedSeconds + ' 秒 · ' +
        [result.meta.host, result.meta.provider, result.meta.model].filter(Boolean).join(' · ');
      out.innerHTML = mdLite(result.text) + '<div class="cp-meta">本機資料邊界 <button class="cp-keep" id="cp-keep">📨 寄到 Telegram/Email</button><span id="cp-keep-st" class="cp-keep-st"></span></div>';
      var keep = document.getElementById('cp-keep'); if (keep) keep.onclick = notifyReply;
    } catch (err) {
      if (activeTask === task) {
        status.textContent = '未完成：' + err.message;
        out.textContent = '本次分析未完成，可稍後重試。';
      }
    } finally {
      if (activeTask === task) { activeTask = null; busy(false); }
    }
  }

  function open() {
    injectStyle();
    if (activeTask) { var shown = document.getElementById('cp-modal'); if (shown) shown.style.display = 'flex'; return; }
    var modal = document.getElementById('cp-modal');
    if (!modal) { modal = document.createElement('div'); modal.id = 'cp-modal'; document.body.appendChild(modal); }
    modal.innerHTML =
      '<div id="cp-box">' +
      '<h3>🤖 AI 副駕 <span style="display:flex;gap:8px;align-items:center"><select id="cp-model"><option>載入中…</option></select><span class="x" onclick="window.copilotClose&&copilotClose()">×</span></span></h3>' +
      '<div class="cp-hint">EVO-T1 主機端 LM Studio · 固定本機模型 · 手機不執行推理 · 會附上當前個股與持倉資料</div>' +
      '<div id="cp-out">問我關於你的持倉、當前個股、或台股盤面結構的問題。</div>' +
      '<div id="cp-status" role="status" class="cp-hint"></div><button id="cp-cancel" hidden>取消接收</button><div class="cp-q">' + QUICK.map(function (q, i) { return '<button data-q="' + i + '">' + esc(q) + '</button>'; }).join('') + '</div>' +
      '<div class="cp-in"><textarea id="cp-text" placeholder="用自然語言問…(Enter 送出,Shift+Enter 換行)"></textarea><button id="cp-send">送出</button></div>' +
      '</div>';
    modal.style.display = 'flex';
    modal.onclick = function (e) { if (e.target === modal) close(); };
    loadModels();
    document.getElementById('cp-cancel').onclick = function () { if (activeTask) activeTask.cancel(); };
    document.getElementById('cp-send').onclick = function () { send(); };
    document.getElementById('cp-text').onkeydown = function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    };
    modal.querySelectorAll('.cp-q button').forEach(function (b) {
      b.onclick = function () { send(QUICK[+b.dataset.q]); };
    });
    setTimeout(function () { var t = document.getElementById('cp-text'); if (t) t.focus(); }, 50);
  }

  function close() { if (activeTask) activeTask.cancel(); activeTask = null; var m = document.getElementById('cp-modal'); if (m) m.style.display = 'none'; }

  async function notifyReply() {
    if (!_lastReply) return;
    var st = document.getElementById('cp-keep-st');
    if (st) st.textContent = ' 寄送中…';
    var msg = (_lastQ ? '【問】' + _lastQ + '\n\n' : '') + '【AI 副駕】\n' + _lastReply;
    try {
      var r = await fetch('/notify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: msg, subject: 'Stock Terminal AI 副駕分析' })
      });
      var d = await r.json();
      if (d && d.ok) { if (st) st.textContent = ' ✓ 已寄送'; return; }
      var why = d && d.results ? Object.keys(d.results).map(function (k) { return k + ':' + d.results[k]; }).join(' / ') : ((d && d.error) || '失敗');
      if (st) st.textContent = ' ⚠ 未寄出(請先在 🔔 通知設定 Telegram/Email) — ' + esc(why);
    } catch (e) { if (st) st.textContent = ' ⚠ ' + esc(e.message); }
  }

  window.copilotOpen = open;
  window.copilotClose = close;

  (function () {
    var spec = { id: 'btn-copilot', label: '🤖 副駕', cat: 'ai',
                 title: 'AI 副駕:本機 LLM 自然語言問盤(附帶你的持倉/個股) (v4.0)', onclick: open };
    (window.Toolbar ? window.Toolbar.register
      : function (s) { (window.__tbQueue = window.__tbQueue || []).push(s); })(spec);
  })();
})();

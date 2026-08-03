/* ============================================================================
 * copilot_v3.js — v4.0 本機 AI 副駕面板
 * ----------------------------------------------------------------------------
 * 自然語言問盤。自動把「當前個股 + 持倉 + 自選」整理成 context 餵給本機 LLM
 * (LM Studio,經 /ai/local)。只送真實資料(data integrity);顏色中性。
 * 模型下拉(讀 /ai/local/status):快問選小模型、深度分析選大模型。
 * ========================================================================== */
(function () {
  'use strict';

  var _lastReply = '', _lastQ = '';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }

  function mdLite(t) {
    // 極簡 markdown:跳脫 → **粗體** → 換行
    var h = esc(t);
    h = h.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
    h = h.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
    return h;
  }

  // 把畫面上有的真實資料整理成 context(只送有的,不編造)
  function buildContext() {
    var parts = [];
    if (typeof S === 'undefined') return '';
    if (S.sym && S.data) {
      var cs = S.data.candles || [];
      var last = cs.length ? cs[cs.length - 1] : null;
      var nm = S.data.name || S.sym;
      if (last && last.close != null) {
        var line = '當前個股:' + S.sym + ' ' + nm + ',最新收盤 ' + last.close;
        if (S.data.yesterdayClose) {
          var chg = ((last.close - S.data.yesterdayClose) / S.data.yesterdayClose * 100);
          line += ',昨收 ' + S.data.yesterdayClose + ',漲跌 ' + (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
        }
        parts.push(line);
      }
    }
    if (S.positions && Object.keys(S.positions).length) {
      var ph = Object.keys(S.positions).map(function (code) {
        var p = S.positions[code] || {};
        var pnl = (p.lastPrice && p.entry) ? ((p.lastPrice - p.entry) / p.entry * 100).toFixed(1) + '%' : '';
        return code + '(' + (p.shares || 0) + '股,進場 ' + p.entry + (pnl ? ',損益 ' + pnl : '') + ')';
      });
      parts.push('我的持倉:' + ph.join('; '));
    }
    if (S.watches && Object.keys(S.watches).length) {
      parts.push('自選股:' + Object.keys(S.watches).join('、'));
    }
    return parts.join('\n');
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
      '#cp-box .cp-hint{font-size:10px;color:#64748b;padding:0 16px 8px}';
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
      if (d.ok && d.models && d.models.length) {
        sel.innerHTML = d.models.map(function (m) { return '<option value="' + esc(m) + '">' + esc(m) + '</option>'; }).join('');
      } else {
        sel.innerHTML = '<option value="">(LM Studio 未啟動)</option>';
      }
    } catch (e) {
      sel.innerHTML = '<option value="">(無法連線)</option>';
    }
  }

  async function send(preset) {
    var text = preset || (document.getElementById('cp-text') || {}).value || '';
    text = text.trim();
    if (!text) return;
    var out = document.getElementById('cp-out');
    var model = (document.getElementById('cp-model') || {}).value || '';
    out.innerHTML = '<span style="color:#94a3b8">思考中…(本機模型,首次載入可能較久)</span>';
    var ctx = buildContext();
    try {
      var r = await fetch('/ai/local', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text, context: ctx, model: model || undefined })
      });
      if (!r.body || !r.body.getReader) { out.innerHTML = mdLite(await r.text()); return; }   // 後援
      var reader = r.body.getReader();
      var dec = new TextDecoder();
      var acc = '';
      out.innerHTML = '';
      while (true) {
        var res = await reader.read();
        if (res.done) break;
        acc += dec.decode(res.value, { stream: true });
        out.innerHTML = mdLite(acc);
        out.scrollTop = out.scrollHeight;
      }
      _lastReply = acc; _lastQ = text;
      out.innerHTML = mdLite(acc) + '<div class="cp-meta">模型:' + esc(model || '') + (ctx ? ' · 已附帶持倉/個股' : '') +
        ' <button class="cp-keep" id="cp-keep">📨 寄到 Telegram/Email</button><span id="cp-keep-st" class="cp-keep-st"></span></div>';
      var _kb = document.getElementById('cp-keep'); if (_kb) _kb.onclick = notifyReply;
    } catch (e) {
      out.innerHTML = '<span style="color:#f87171">⚠ ' + esc(e.message) + '</span>';
    }
  }

  function open() {
    injectStyle();
    var modal = document.getElementById('cp-modal');
    if (!modal) { modal = document.createElement('div'); modal.id = 'cp-modal'; document.body.appendChild(modal); }
    modal.innerHTML =
      '<div id="cp-box">' +
      '<h3>🤖 AI 副駕 <span style="display:flex;gap:8px;align-items:center"><select id="cp-model"><option>載入中…</option></select><span class="x" onclick="window.copilotClose&&copilotClose()">×</span></span></h3>' +
      '<div class="cp-hint">本機 LM Studio · 完全離線 · 會自動附上你當前個股與持倉資料</div>' +
      '<div id="cp-out">問我關於你的持倉、當前個股、或台股盤面結構的問題。</div>' +
      '<div class="cp-q">' + QUICK.map(function (q, i) { return '<button data-q="' + i + '">' + esc(q) + '</button>'; }).join('') + '</div>' +
      '<div class="cp-in"><textarea id="cp-text" placeholder="用自然語言問…(Enter 送出,Shift+Enter 換行)"></textarea><button id="cp-send">送出</button></div>' +
      '</div>';
    modal.style.display = 'flex';
    modal.onclick = function (e) { if (e.target === modal) close(); };
    loadModels();
    document.getElementById('cp-send').onclick = function () { send(); };
    document.getElementById('cp-text').onkeydown = function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    };
    modal.querySelectorAll('.cp-q button').forEach(function (b) {
      b.onclick = function () { send(QUICK[+b.dataset.q]); };
    });
    setTimeout(function () { var t = document.getElementById('cp-text'); if (t) t.focus(); }, 50);
  }

  function close() { var m = document.getElementById('cp-modal'); if (m) m.style.display = 'none'; }

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

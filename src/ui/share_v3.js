// ============================================================
// Stock Terminal — 分析結果寄送(Telegram/Email)共用模組  [單一真理來源]
// ------------------------------------------------------------
// 任何「跑資料分析的地方」都用同一顆按鈕把結果寄到使用者已設定的
// Telegram/Email(沿用後端 /notify;管道在 🔔 通知設定)。
//
// 用法(三步):
//   1. 在面板標題列插入按鈕:  ... + ShareResult.buttonHTML('fc-send') + ...
//   2. 渲染完成後綁定:        ShareResult.wire('fc-send', getTextFn, '主旨')
//      getTextFn: () => string  回傳要寄出的純文字(通常是格式化後的結果)
//   3. (可選) 直接寄:         await ShareResult.send(text, subject)
//
// Email 聯絡人（AI 分析全文／設定頁）:
//   ShareResult.openMailer(getTextFn, '主旨')
//   ShareResult.openContacts()
//   通訊錄 GET/POST /notify/contacts；寄信 POST /report-email（沿用 SMTP）。
//
// 安全:寄送只在使用者「點按鈕」時觸發,絕不自動發送。
// ============================================================
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function apiUrl(path) {
    return (window.SERVER || '') + path;
  }

  function parseJson(r) {
    return r.text().then(function (raw) {
      var d = {};
      try { d = raw ? JSON.parse(raw) : {}; } catch (e) { d = { error: raw.slice(0, 180) }; }
      return { ok: r.ok, status: r.status, data: d };
    });
  }

  const ShareResult = {};
  var mailerState = { contacts: [], selected: {}, editId: '', getText: null, subject: '', manageOnly: false };

  // 實際送出:POST /notify { text, subject } → { ok, results, error }
  ShareResult.send = async function (text, subject) {
    try {
      const r = await fetch(apiUrl('/notify'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: String(text || ''), subject: subject || 'Stock Terminal 分析結果' })
      });
      const d = await r.json();
      if (d && d.ok) return { ok: true };
      const why = d && d.results
        ? Object.keys(d.results).map(function (k) { return k + ':' + d.results[k]; }).join(' / ')
        : ((d && d.error) || '失敗');
      return { ok: false, why: why };
    } catch (e) {
      return { ok: false, why: e.message };
    }
  };

  ShareResult.listContacts = async function () {
    try {
      const r = await fetch(apiUrl('/notify/contacts'), { cache: 'no-store' });
      const parsed = await parseJson(r);
      if (!parsed.ok) {
        return { ok: false, contacts: [], why: (parsed.data && parsed.data.error) || ('HTTP ' + parsed.status) };
      }
      return { ok: true, contacts: (parsed.data && parsed.data.contacts) || [] };
    } catch (e) {
      return { ok: false, contacts: [], why: e.message };
    }
  };

  ShareResult.saveContacts = async function (contacts) {
    try {
      const r = await fetch(apiUrl('/notify/contacts'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contacts: contacts || [] }),
        cache: 'no-store'
      });
      const parsed = await parseJson(r);
      if (!parsed.ok) {
        return { ok: false, contacts: [], why: (parsed.data && parsed.data.error) || ('HTTP ' + parsed.status) };
      }
      return { ok: true, contacts: (parsed.data && parsed.data.contacts) || [] };
    } catch (e) {
      return { ok: false, contacts: [], why: e.message };
    }
  };

  ShareResult.sendToEmails = async function (text, subject, emails) {
    try {
      const r = await fetch(apiUrl('/report-email'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          to: emails || [],
          subject: subject || 'Stock Terminal AI 分析',
          text: String(text || '')
        })
      });
      const parsed = await parseJson(r);
      if (parsed.ok && parsed.data && parsed.data.ok) {
        return { ok: true, to: parsed.data.to };
      }
      return { ok: false, why: (parsed.data && parsed.data.error) || ('HTTP ' + parsed.status) };
    } catch (e) {
      return { ok: false, why: e.message };
    }
  };

  // 產生按鈕 + 狀態 span 的 HTML(狀態 span id = <id>-st)
  ShareResult.buttonHTML = function (id, label) {
    return '<button id="' + esc(id) + '" type="button" title="把這份分析結果寄到你設定的 Telegram/Email(在 🔔 通知設定)" ' +
      'style="background:#13233b;border:1px solid #2f4a6e;color:#cfe3ff;border-radius:5px;padding:4px 10px;cursor:pointer;font-size:11px;font-family:monospace">📨 ' +
      esc(label || '寄到 Telegram/Email') + '</button>' +
      '<span id="' + esc(id) + '-st" style="font-size:10px;color:#8aa;margin-left:6px;font-family:monospace"></span>';
  };

  // 綁定按鈕點擊 → 取文字 → 寄送 → 更新狀態。重複呼叫安全(只綁一次)。
  ShareResult.wire = function (id, getText, subject) {
    const btn = document.getElementById(id);
    if (!btn || btn._srWired) return;
    btn._srWired = true;
    const stId = id + '-st';
    btn.addEventListener('click', async function () {
      const st = document.getElementById(stId);
      let text = '';
      try { text = (typeof getText === 'function') ? getText() : String(getText || ''); } catch (e) { text = ''; }
      if (!text || !text.trim()) { if (st) st.textContent = ' 無內容可寄(先跑分析)'; return; }
      if (st) st.textContent = ' 寄送中…';
      btn.disabled = true;
      const res = await ShareResult.send(text, subject);
      btn.disabled = false;
      if (st) st.textContent = res.ok
        ? ' ✓ 已寄送'
        : ' ⚠ 未寄出(請先在 🔔 通知設定 Telegram/Email) — ' + res.why;
    });
  };

  function ensureMailerStyle() {
    if (document.getElementById('sr-mail-css')) return;
    var css = document.createElement('style');
    css.id = 'sr-mail-css';
    css.textContent =
      '#sr-mail-overlay{position:fixed;inset:0;z-index:10040;background:rgba(3,8,16,.62);display:flex;' +
        'align-items:center;justify-content:center;padding:12px}' +
      '#sr-mail-box{width:min(440px,100%);max-height:min(86vh,640px);overflow:auto;background:#0b1524;' +
        'border:1px solid #33557a;border-radius:10px;color:#dbeafe;box-shadow:0 18px 48px rgba(0,0,0,.45);' +
        'font:13px/1.5 "Noto Sans TC",sans-serif;padding:14px 14px 12px}' +
      '#sr-mail-box h3{margin:0 0 6px;font:700 15px/1.3 "Noto Sans TC",sans-serif;color:#f8fafc}' +
      '#sr-mail-box .sr-note{color:#94a3b8;font-size:11px;margin:0 0 10px}' +
      '#sr-mail-list{display:flex;flex-direction:column;gap:6px;margin:0 0 10px}' +
      '#sr-mail-list label{display:flex;align-items:flex-start;gap:8px;padding:7px 8px;border:1px solid #24374f;' +
        'border-radius:7px;background:#0a1422}' +
      '#sr-mail-list .sr-meta{flex:1 1 auto;min-width:0}' +
      '#sr-mail-list .sr-name{font-weight:700;color:#e2e8f0}' +
      '#sr-mail-list .sr-email{font-size:11px;color:#7dd3fc;word-break:break-all}' +
      '#sr-mail-list .sr-row-act{display:flex;gap:4px;flex:0 0 auto}' +
      '#sr-mail-list button,#sr-mail-form button,#sr-mail-actions button{appearance:none;cursor:pointer;' +
        'border-radius:6px;font:700 11px/1.2 "Noto Sans TC",sans-serif}' +
      '#sr-mail-list .sr-edit,#sr-mail-list .sr-del{border:1px solid #33557a;background:#102033;color:#cbd5e1;padding:3px 7px}' +
      '#sr-mail-form{display:grid;grid-template-columns:1fr 1.4fr auto;gap:6px;margin:0 0 10px}' +
      '#sr-mail-form input{min-width:0;background:#07111d;border:1px solid #33557a;border-radius:6px;color:#e2e8f0;' +
        'padding:6px 8px;font:12px/1.3 "Noto Sans TC",sans-serif}' +
      '#sr-mail-form button{border:1px solid #38bdf8;background:rgba(14,165,233,.12);color:#bae6fd;padding:6px 10px}' +
      '#sr-mail-actions{display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap}' +
      '#sr-mail-actions .sr-send{border:none;background:#d4a017;color:#060a12;padding:7px 12px}' +
      '#sr-mail-actions .sr-close{border:1px solid #43536a;background:#0a1423;color:#9fb0c5;padding:7px 12px}' +
      '#sr-mail-st{min-height:16px;margin:8px 0 0;font-size:11px;color:#93c5fd}' +
      '#sr-mail-empty{color:#64748b;font-size:12px;padding:8px;border:1px dashed #334155;border-radius:7px}' +
      '@media (max-width:520px){#sr-mail-form{grid-template-columns:1fr}#sr-mail-box{max-height:92vh}}';
    document.head.appendChild(css);
  }

  function setStatus(msg) {
    var el = document.getElementById('sr-mail-st');
    if (el) el.textContent = msg || '';
  }

  function selectedEmails() {
    return mailerState.contacts.filter(function (c) { return mailerState.selected[c.id]; })
      .map(function (c) { return c.email; });
  }

  function renderMailerList() {
    var list = document.getElementById('sr-mail-list');
    if (!list) return;
    if (!mailerState.contacts.length) {
      list.innerHTML = '<div id="sr-mail-empty">尚無聯絡人。先在下方新增姓名與 Email。</div>';
      return;
    }
    list.innerHTML = mailerState.contacts.map(function (c) {
      var checked = mailerState.selected[c.id] ? ' checked' : '';
      var pick = mailerState.manageOnly
        ? ''
        : '<input type="checkbox" data-cid="' + esc(c.id) + '"' + checked + '>';
      return '<label>' + pick +
        '<span class="sr-meta"><span class="sr-name">' + esc(c.name) + '</span>' +
        '<div class="sr-email">' + esc(c.email) + '</div></span>' +
        '<span class="sr-row-act">' +
        '<button type="button" class="sr-edit" data-edit="' + esc(c.id) + '">編輯</button>' +
        '<button type="button" class="sr-del" data-del="' + esc(c.id) + '">刪除</button>' +
        '</span></label>';
    }).join('');
    list.querySelectorAll('input[type="checkbox"][data-cid]').forEach(function (box) {
      box.onchange = function () {
        mailerState.selected[box.getAttribute('data-cid')] = box.checked;
      };
    });
    list.querySelectorAll('[data-edit]').forEach(function (btn) {
      btn.onclick = function () { startEdit(btn.getAttribute('data-edit')); };
    });
    list.querySelectorAll('[data-del]').forEach(function (btn) {
      btn.onclick = function () { removeContact(btn.getAttribute('data-del')); };
    });
  }

  function startEdit(id) {
    var row = mailerState.contacts.filter(function (c) { return c.id === id; })[0];
    if (!row) return;
    mailerState.editId = id;
    var nameEl = document.getElementById('sr-mail-name');
    var emailEl = document.getElementById('sr-mail-email');
    var saveBtn = document.getElementById('sr-mail-save');
    if (nameEl) nameEl.value = row.name;
    if (emailEl) emailEl.value = row.email;
    if (saveBtn) saveBtn.textContent = '儲存';
    setStatus('正在編輯 ' + row.name);
  }

  function resetForm() {
    mailerState.editId = '';
    var nameEl = document.getElementById('sr-mail-name');
    var emailEl = document.getElementById('sr-mail-email');
    var saveBtn = document.getElementById('sr-mail-save');
    if (nameEl) nameEl.value = '';
    if (emailEl) emailEl.value = '';
    if (saveBtn) saveBtn.textContent = '新增';
  }

  async function persist(next, msg) {
    setStatus('儲存中…');
    var res = await ShareResult.saveContacts(next);
    if (!res.ok) {
      setStatus('儲存失敗：' + (res.why || ''));
      return false;
    }
    var keep = {};
    (res.contacts || []).forEach(function (c) {
      keep[c.id] = mailerState.selected[c.id] !== false;
      if (mailerState.selected[c.id] == null && !mailerState.manageOnly) keep[c.id] = true;
    });
    mailerState.contacts = res.contacts || [];
    mailerState.selected = keep;
    renderMailerList();
    resetForm();
    setStatus(msg || '已更新聯絡人');
    return true;
  }

  async function removeContact(id) {
    var next = mailerState.contacts.filter(function (c) { return c.id !== id; });
    await persist(next, '已刪除聯絡人');
  }

  async function saveForm(ev) {
    if (ev) ev.preventDefault();
    var nameEl = document.getElementById('sr-mail-name');
    var emailEl = document.getElementById('sr-mail-email');
    var name = nameEl ? String(nameEl.value || '').trim() : '';
    var email = emailEl ? String(emailEl.value || '').trim() : '';
    if (!email || email.indexOf('@') < 0) {
      setStatus('請輸入有效 Email');
      return;
    }
    var next = mailerState.contacts.slice();
    if (mailerState.editId) {
      next = next.map(function (c) {
        if (c.id !== mailerState.editId) return c;
        return { id: c.id, name: name || c.name, email: email };
      });
    } else {
      next.push({ name: name, email: email });
    }
    await persist(next, mailerState.editId ? '已更新聯絡人' : '已新增聯絡人');
  }

  async function sendSelected() {
    var emails = selectedEmails();
    if (!emails.length) {
      setStatus('請先勾選至少一位聯絡人');
      return;
    }
    var text = '';
    try {
      text = mailerState.getText ? String(mailerState.getText() || '') : '';
    } catch (e) { text = ''; }
    if (!text.trim()) {
      setStatus('沒有可寄出的分析內容');
      return;
    }
    var sendBtn = document.getElementById('sr-mail-send');
    if (sendBtn) sendBtn.disabled = true;
    setStatus('寄送中…');
    var res = await ShareResult.sendToEmails(text, mailerState.subject, emails);
    if (sendBtn) sendBtn.disabled = false;
    setStatus(res.ok
      ? '已寄出至 ' + emails.join('、')
      : '未寄出：' + (res.why || '') + '（請先在通知設定填寄件帳號／應用程式密碼）');
  }

  function closeMailer() {
    var overlay = document.getElementById('sr-mail-overlay');
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    document.removeEventListener('keydown', onMailerKey);
  }

  function onMailerKey(ev) {
    if (ev.key === 'Escape') closeMailer();
  }

  function mountMailer() {
    ensureMailerStyle();
    closeMailer();
    var overlay = document.createElement('div');
    overlay.id = 'sr-mail-overlay';
    overlay.innerHTML =
      '<div id="sr-mail-box" role="dialog" aria-modal="true" aria-labelledby="sr-mail-title">' +
        '<h3 id="sr-mail-title">' + (mailerState.manageOnly ? '管理 Email 聯絡人' : 'Email 通知') + '</h3>' +
        '<p class="sr-note">' + (mailerState.manageOnly
          ? '聯絡人只存在本機通訊錄，不含 SMTP 密鑰。寄信用通知設定裡的寄件帳號。'
          : '點選後把目前分析全文寄到勾選的聯絡人。可在此新增、編輯、刪除聯絡人。') + '</p>' +
        '<div id="sr-mail-list"></div>' +
        '<form id="sr-mail-form">' +
          '<input id="sr-mail-name" type="text" maxlength="40" placeholder="姓名" autocomplete="name">' +
          '<input id="sr-mail-email" type="email" maxlength="254" placeholder="Email" autocomplete="email">' +
          '<button type="submit" id="sr-mail-save">新增</button>' +
        '</form>' +
        '<div id="sr-mail-actions">' +
          (mailerState.manageOnly ? '' : '<button type="button" class="sr-send" id="sr-mail-send">寄出通知</button>') +
          '<button type="button" class="sr-close" id="sr-mail-close">關閉</button>' +
        '</div>' +
        '<div id="sr-mail-st"></div>' +
      '</div>';
    overlay.addEventListener('click', function (ev) {
      if (ev.target === overlay) closeMailer();
    });
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onMailerKey);
    var form = document.getElementById('sr-mail-form');
    if (form) form.addEventListener('submit', saveForm);
    var closeBtn = document.getElementById('sr-mail-close');
    if (closeBtn) closeBtn.onclick = closeMailer;
    var sendBtn = document.getElementById('sr-mail-send');
    if (sendBtn) sendBtn.onclick = sendSelected;
    renderMailerList();
  }

  async function openMailerPanel(opts) {
    mailerState.getText = opts.getText || null;
    mailerState.subject = opts.subject || 'Stock Terminal AI 分析';
    mailerState.manageOnly = !!opts.manageOnly;
    mailerState.editId = '';
    mountMailer();
    setStatus('載入聯絡人…');
    var res = await ShareResult.listContacts();
    if (!res.ok) {
      mailerState.contacts = [];
      mailerState.selected = {};
      renderMailerList();
      setStatus('無法讀取聯絡人：' + (res.why || ''));
      return;
    }
    mailerState.contacts = res.contacts || [];
    var selected = {};
    mailerState.contacts.forEach(function (c) { selected[c.id] = !mailerState.manageOnly; });
    mailerState.selected = selected;
    renderMailerList();
    setStatus(mailerState.contacts.length ? '' : '通訊錄是空的，請先新增聯絡人');
  }

  ShareResult.openMailer = function (getText, subject) {
    return openMailerPanel({ getText: getText, subject: subject, manageOnly: false });
  };

  ShareResult.openContacts = function () {
    return openMailerPanel({ manageOnly: true, subject: 'Stock Terminal AI 分析' });
  };

  window.ShareResult = ShareResult;
  console.log('[share] 分析結果寄送模組就緒 — ShareResult.buttonHTML / wire / send / openMailer');
})();

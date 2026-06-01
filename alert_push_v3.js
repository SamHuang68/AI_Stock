// ============================================================
// Stock Terminal v3.8 — Alert Push 設定 UI (前端)
// ------------------------------------------------------------
// 與 server.py 後端警報 daemon 對接：
//   GET  /alert/status   /alert/rules   /alert/config
//   POST /alert/rules    /alert/config  /alert/test
// 提供浮動面板：開關後端警報、Telegram/Email 設定、規則表、測試推播。
// 不影響既有 alert_v3.js (前端 60s 瀏覽器通知) — 兩者可並存。
// ============================================================
(function () {
  'use strict';
  const SRV = window.SERVER || 'http://localhost:18432';

  async function api(path, method, body) {
    const opt = { method: method || 'GET' };
    if (body !== undefined) { opt.headers = { 'Content-Type': 'application/json' }; opt.body = JSON.stringify(body); }
    const r = await fetch(SRV + path, opt);
    return r.json();
  }

  function injectStyle() {
    if (document.getElementById('alert-push-style')) return;
    const s = document.createElement('style');
    s.id = 'alert-push-style';
    s.textContent = `
    #ap-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:none;align-items:center;justify-content:center}
    #ap-box{background:#0f172a;border:1px solid #334155;border-radius:10px;width:min(560px,92vw);max-height:88vh;overflow:auto;padding:18px;color:#e2e8f0;font-size:13px}
    #ap-box h3{margin:0 0 10px;font-size:15px}
    #ap-box section{border:1px solid #1e293b;border-radius:8px;padding:10px;margin:8px 0}
    #ap-box label{display:block;margin:6px 0 2px;color:#94a3b8;font-size:11px}
    #ap-box input,#ap-box select{width:100%;box-sizing:border-box;background:#1e293b;border:1px solid #334155;color:#e2e8f0;border-radius:6px;padding:5px 7px;font-size:12px}
    #ap-box .row{display:flex;gap:8px}
    #ap-box .row>div{flex:1;min-width:0}
    #ap-box button{background:#2563eb;border:0;color:#fff;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px}
    #ap-box button.sec{background:#334155}
    #ap-box table{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px}
    #ap-box th,#ap-box td{border-bottom:1px solid #1e293b;padding:4px;text-align:left}
    .ap-toggle{display:flex;align-items:center;gap:6px}
    #ap-status{font-size:11px;color:#64748b;margin-top:8px}`;
    document.head.appendChild(s);
  }

  let cfg = null, rules = [];

  async function refresh() {
    try { cfg = await api('/alert/config'); } catch { cfg = null; }
    try { rules = await api('/alert/rules'); } catch { rules = []; }
    render();
  }

  function render() {
    const box = document.getElementById('ap-body');
    if (!box || !cfg) return;
    const tg = cfg.telegram || {}, em = cfg.email || {};
    box.innerHTML = `
    <section>
      <div class="ap-toggle"><input type="checkbox" id="ap-enabled" ${cfg.enabled ? 'checked' : ''}>
      <b>啟用後端警報 daemon</b>（瀏覽器關著也會推播）</div>
      <label>輪詢秒數</label><input id="ap-poll" type="number" value="${cfg.poll_seconds || 60}" min="15">
    </section>
    <section>
      <div class="ap-toggle"><input type="checkbox" id="ap-tg-en" ${tg.enabled ? 'checked' : ''}><b>Telegram</b>
      <span style="color:#64748b">（@BotFather 建 bot 取 token，傳訊息給 bot 後用 getUpdates 拿 chat_id）</span></div>
      <label>Bot Token</label><input id="ap-tg-token" placeholder="${tg.bot_token ? '已設定 (留空不改)' : '123456:ABC...'}">
      <label>Chat ID</label><input id="ap-tg-chat" value="${tg.chat_id || ''}">
    </section>
    <section>
      <div class="ap-toggle"><input type="checkbox" id="ap-em-en" ${em.enabled ? 'checked' : ''}><b>Email (SMTP)</b>
      <span style="color:#64748b">（Gmail 用應用程式密碼）</span></div>
      <div class="row"><div><label>SMTP Host</label><input id="ap-em-host" value="${em.smtp_host || 'smtp.gmail.com'}"></div>
      <div><label>Port</label><input id="ap-em-port" type="number" value="${em.smtp_port || 587}"></div></div>
      <label>帳號</label><input id="ap-em-user" value="${em.user || ''}">
      <label>應用程式密碼</label><input id="ap-em-pw" type="password" placeholder="${em.app_password ? '已設定 (留空不改)' : ''}">
      <label>收件者</label><input id="ap-em-to" value="${em.to || ''}">
    </section>
    <section>
      <b>警報規則</b>
      <table><thead><tr><th>代號</th><th>市場</th><th>類型</th><th>價位</th><th>備註</th><th></th></tr></thead>
      <tbody id="ap-rules">${rules.map((r, i) => `<tr>
        <td>${r.sym || ''}</td><td>${r.market || 'TW'}</td>
        <td>${r.type === 'cross_down' ? '破支撐↓' : '過壓力↑'}</td>
        <td>${r.price}</td><td>${r.note || ''}</td>
        <td><button class="sec" data-del="${i}" style="padding:2px 6px">✕</button></td></tr>`).join('')}</tbody></table>
      <div class="row" style="margin-top:6px">
        <div><input id="ap-r-sym" placeholder="代號 2330"></div>
        <div><select id="ap-r-mkt"><option>TW</option><option>US</option></select></div>
        <div><select id="ap-r-type"><option value="cross_up">過壓力↑</option><option value="cross_down">破支撐↓</option></select></div>
        <div><input id="ap-r-price" type="number" placeholder="價位"></div>
        <div><button id="ap-r-add">＋加規則</button></div>
      </div>
    </section>
    <div class="row">
      <button id="ap-save">儲存設定</button>
      <button class="sec" id="ap-test">測試推播</button>
      <button class="sec" id="ap-close2">關閉</button>
    </div>
    <div id="ap-status">${cfg.running ? '🟢 daemon 執行中' : '⚪ daemon 未啟動'} · 規則 ${rules.length} 條</div>`;

    box.querySelectorAll('[data-del]').forEach(b => b.onclick = () => { rules.splice(+b.dataset.del, 1); pushRules(); });
    box.querySelector('#ap-r-add').onclick = addRule;
    box.querySelector('#ap-save').onclick = saveCfg;
    box.querySelector('#ap-test').onclick = testPush;
    box.querySelector('#ap-close2').onclick = close;
  }

  async function pushRules() { await api('/alert/rules', 'POST', rules); refresh(); }

  function addRule() {
    const sym = document.getElementById('ap-r-sym').value.trim();
    const price = parseFloat(document.getElementById('ap-r-price').value);
    if (!sym || !(price > 0)) { alert('請填代號與價位'); return; }
    rules.push({
      id: Date.now(), sym, market: document.getElementById('ap-r-mkt').value,
      type: document.getElementById('ap-r-type').value, price, note: '', enabled: true,
    });
    pushRules();
  }

  async function saveCfg() {
    const body = {
      enabled: document.getElementById('ap-enabled').checked,
      poll_seconds: parseInt(document.getElementById('ap-poll').value, 10) || 60,
      telegram: {
        enabled: document.getElementById('ap-tg-en').checked,
        chat_id: document.getElementById('ap-tg-chat').value.trim(),
      },
      email: {
        enabled: document.getElementById('ap-em-en').checked,
        smtp_host: document.getElementById('ap-em-host').value.trim(),
        smtp_port: parseInt(document.getElementById('ap-em-port').value, 10) || 587,
        user: document.getElementById('ap-em-user').value.trim(),
        to: document.getElementById('ap-em-to').value.trim(),
      },
    };
    const tok = document.getElementById('ap-tg-token').value.trim();
    if (tok) body.telegram.bot_token = tok;
    const pw = document.getElementById('ap-em-pw').value;
    if (pw) body.email.app_password = pw;
    const r = await api('/alert/config', 'POST', body);
    if (r.ok) { alert('已儲存'); refresh(); } else alert('儲存失敗: ' + JSON.stringify(r));
  }

  async function testPush() {
    const r = await api('/alert/test', 'POST', {});
    alert('測試結果：' + JSON.stringify(r.results || r, null, 1));
  }

  function open() {
    injectStyle();
    let m = document.getElementById('ap-modal');
    if (!m) {
      m = document.createElement('div'); m.id = 'ap-modal';
      m.innerHTML = `<div id="ap-box"><h3>🔔 後端警報推播設定 (v3.8)</h3><div id="ap-body">載入中…</div></div>`;
      document.body.appendChild(m);
      m.addEventListener('click', e => { if (e.target === m) close(); });
    }
    m.style.display = 'flex';
    refresh();
  }
  function close() { const m = document.getElementById('ap-modal'); if (m) m.style.display = 'none'; }

  window.alertPushOpen = open;
  window.alertPushClose = close;
})();

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
    if (!r.ok) {
      const error = new Error('HTTP ' + r.status);
      error.status = r.status;
      throw error;
    }
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

  let cfg = null, rules = [], readError = null, refreshId = 0, ruleWritePending = false;

  const COMP_INDS = [['close', '收盤'], ['sma20', 'SMA20'], ['sma60', 'SMA60'], ['rsi14', 'RSI'],
  ['bbL', '布林下軌'], ['bbU', '布林上軌'], ['volRatio', '量比'], ['high20', '20日高']];
  function compCondRow(idx) {
    const opts = COMP_INDS.map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
    return `<div class="row ap-cc" style="margin-top:4px">
      <div><select class="ap-cc-l">${opts}</select></div>
      <div><select class="ap-cc-op"><option value="lt">&lt;</option><option value="gt">&gt;</option><option value="lte">≤</option><option value="gte">≥</option></select></div>
      <div><input class="ap-cc-r" placeholder="數值或指標(如 50 / sma60)"></div>
    </div>`;
  }
  function addComposite() {
    const sym = document.getElementById('ap-c-sym').value.trim();
    if (!sym) { alert('請填代號'); return; }
    const conds = [];
    document.querySelectorAll('#ap-c-conds .ap-cc').forEach(row => {
      const left = row.querySelector('.ap-cc-l').value;
      const op = row.querySelector('.ap-cc-op').value;
      const right = row.querySelector('.ap-cc-r').value.trim();
      if (right !== '') conds.push({ left, op, right });
    });
    if (!conds.length) { alert('請至少填一個條件'); return; }
    const candidate = [...rules, {
      id: Date.now(), type: 'composite', sym,
      market: document.getElementById('ap-c-mkt').value,
      combine: document.getElementById('ap-c-combine').value,
      conditions: conds, enabled: true,
    }];
    pushRules(candidate);
  }

  async function refresh() {
    const id = ++refreshId;
    cfg = null; rules = []; readError = null;
    render();
    try {
      const nextCfg = await api('/alert/config');
      if (id !== refreshId) return;
      const nextRules = await api('/alert/rules');
      if (id !== refreshId) return;
      cfg = nextCfg; rules = nextRules;
    } catch (error) {
      if (id !== refreshId) return;
      readError = error;
    }
    render();
  }

  // 價位規則與盤中條件（漲跌幅相對前一日收盤；預估量為線性估算，開盤 15 分鐘後才判斷）。
  const RULE_INPUT = {
    cross_up: { field: 'price', placeholder: '價位', min: 1e-9, max: Infinity, error: '請填代號與價位' },
    cross_down: { field: 'price', placeholder: '價位', min: 1e-9, max: Infinity, error: '請填代號與價位' },
    pct_up: { field: 'threshold', placeholder: '漲幅 %（0.1–50）', min: 0.1, max: 50, error: '請填代號與 0.1 到 50 的漲幅 %' },
    pct_down: { field: 'threshold', placeholder: '跌幅 %（0.1–50）', min: 0.1, max: 50, error: '請填代號與 0.1 到 50 的跌幅 %' },
    volume_ratio: { field: 'threshold', placeholder: '倍數（1–20）', min: 1, max: 20, error: '請填代號與 1 到 20 的倍數' },
  };
  const RULE_HINT = {
    cross_up: '價格由下往上穿越價位時提醒；跌回價位 1% 以下才會再次提醒。',
    cross_down: '價格由上往下穿越價位時提醒；漲回價位 1% 以上才會再次提醒。',
    pct_up: '相對前一日收盤的漲幅達門檻時提醒；回落到門檻以下才會再次提醒。台股使用證交所即時成交。',
    pct_down: '相對前一日收盤的跌幅達門檻時提醒；回升到門檻以內才會再次提醒。台股使用證交所即時成交。',
    volume_ratio: '預估全日量 ÷ 前一交易日量；以已交易時間線性換算，早盤偏高，開盤 15 分鐘內不判斷。',
  };
  function ruleTypeLabel(r) {
    const label = { cross_down: '破支撐↓', cross_up: '過壓力↑', pct_up: '漲幅達↑', pct_down: '跌幅達↓',
      volume_ratio: '預估量比' }[r.type] || '過壓力↑';
    const once = r.once ? (r._last_once_done ? '（只提醒一次・已提醒）' : '（只提醒一次）') : '';
    return label + once;
  }
  function ruleTarget(r) {
    if (r.type === 'pct_up' || r.type === 'pct_down') return r.threshold + '%';
    if (r.type === 'volume_ratio') return r.threshold + ' 倍昨量';
    return r.price;
  }

  function render() {
    const box = document.getElementById('ap-body');
    if (!box) return;
    if (!cfg) {
      box.innerHTML = '<div id="ap-status" role="status"></div><button class="sec" id="ap-close2">關閉</button>';
      box.querySelector('#ap-status').textContent = readError
        ? (readError.status === 403 ? '僅擁有者可見'
          : '讀取失敗，無法確認 daemon 狀態' + (readError.status ? '（HTTP ' + readError.status + '）' : ''))
        : '載入中…';
      box.querySelector('#ap-close2').onclick = close;
      return;
    }
    const tg = cfg.telegram || {}, em = cfg.email || {};
    box.innerHTML = `
    <section>
      <div class="ap-toggle"><input type="checkbox" id="ap-enabled" ${cfg.enabled ? 'checked' : ''}>
      <b>啟用後端警報 daemon</b>（瀏覽器關著也會推播）</div>
      <div class="ap-toggle" style="margin-top:8px"><input type="checkbox" id="ap-market-signal" ${cfg.market_signal_enabled ? 'checked' : ''}>
      <b>推送跨市場前兆雷達的狀態轉換</b></div>
      <div style="color:#64748b;font-size:10px;margin:3px 0 7px">僅推送戒備／確認／生效／衝突等邊緣事件；目前為 Shadow observation，不是買賣或槓桿指令。</div>
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
      <div class="ap-toggle"><input type="checkbox" id="ap-wh-en" ${(cfg.webhook || {}).enabled ? 'checked' : ''}><b>Webhook</b>
      <span style="color:#64748b">（Discord/Slack/自架；POST JSON {text,content}）</span></div>
      <label>Webhook URL</label><input id="ap-wh-url" value="${(cfg.webhook || {}).url || ''}" placeholder="https://discord.com/api/webhooks/...">
    </section>
    <section>
      <b>複合警示</b> <span style="color:#64748b;font-size:10px">多條件 AND/OR，後端日線評估</span>
      <table><thead><tr><th>代號</th><th>邏輯</th><th>條件</th><th></th></tr></thead>
      <tbody>${rules.map((r, i) => r.type === 'composite' ? `<tr>
        <td>${r.sym}</td><td>${(r.combine || 'AND')}</td>
        <td style="font-size:10px">${(r.conditions || []).map(c => `${c.left}${({ gt: '>', lt: '<', gte: '≥', lte: '≤' }[c.op] || c.op)}${c.right}`).join(' · ')}</td>
        <td><button class="sec" data-del="${i}" style="padding:2px 6px">✕</button></td></tr>` : '').join('')}</tbody></table>
      <div class="row" style="margin-top:6px">
        <div><input id="ap-c-sym" placeholder="代號 2330"></div>
        <div><select id="ap-c-mkt"><option>TW</option><option>US</option></select></div>
        <div><select id="ap-c-combine"><option value="AND">AND 全部</option><option value="OR">OR 任一</option></select></div>
      </div>
      <div id="ap-c-conds">${compCondRow(0)}${compCondRow(1)}</div>
      <button id="ap-c-add" style="margin-top:4px">＋加複合警示</button>
    </section>
    <section>
      <b>價格警報規則</b>
      <table><thead><tr><th>代號</th><th>市場</th><th>類型</th><th>價位／門檻</th><th>備註</th><th></th></tr></thead>
      <tbody id="ap-rules">${rules.map((r, i) => r.type === 'composite' ? '' : `<tr>
        <td>${r.sym || ''}</td><td>${r.market || 'TW'}</td>
        <td>${ruleTypeLabel(r)}</td>
        <td>${ruleTarget(r)}</td><td>${r.note || ''}</td>
        <td><button class="sec" data-del="${i}" style="padding:2px 6px">✕</button></td></tr>`).join('')}</tbody></table>
      <div class="row" style="margin-top:6px">
        <div><input id="ap-r-sym" placeholder="代號 2330"></div>
        <div><select id="ap-r-mkt"><option>TW</option><option>US</option></select></div>
        <div><select id="ap-r-type"><option value="cross_up">過壓力↑</option><option value="cross_down">破支撐↓</option>
          <option value="pct_up">漲幅達 %</option><option value="pct_down">跌幅達 %</option>
          <option value="volume_ratio">預估量達昨量倍數</option></select></div>
        <div><input id="ap-r-price" type="number" step="any" placeholder="價位"></div>
        <div><button id="ap-r-add">＋加規則</button></div>
      </div>
      <div style="display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-top:4px;font-size:10px">
        <label style="white-space:nowrap;display:inline-flex;align-items:center;gap:4px"><input type="checkbox" id="ap-r-once" style="width:auto;margin:0">只提醒一次</label>
        <span id="ap-r-hint" style="color:#64748b">${RULE_HINT.cross_up}</span>
      </div>
    </section>
    <div class="row">
      <button id="ap-save">儲存設定</button>
      <button class="sec" id="ap-test">測試推播</button>
      <button class="sec" id="ap-close2">關閉</button>
    </div>
    <div id="ap-status">${cfg.running ? '🟢 daemon 執行中' : '⚪ daemon 未啟動'} · 規則 ${rules.length} 條</div>`;

    box.querySelectorAll('[data-del]').forEach(b => b.onclick = () => {
      pushRules(rules.filter((_, index) => index !== +b.dataset.del));
    });
    box.querySelector('#ap-r-add').onclick = addRule;
    const typeSelect = box.querySelector('#ap-r-type');
    typeSelect.onchange = () => {
      const meta = RULE_INPUT[typeSelect.value] || RULE_INPUT.cross_up;
      box.querySelector('#ap-r-price').placeholder = meta.placeholder;
      box.querySelector('#ap-r-hint').textContent = RULE_HINT[typeSelect.value] || '';
    };
    const cAdd = box.querySelector('#ap-c-add'); if (cAdd) cAdd.onclick = addComposite;
    box.querySelector('#ap-save').onclick = saveCfg;
    box.querySelector('#ap-test').onclick = testPush;
    box.querySelector('#ap-close2').onclick = close;
  }

  function reportWriteError(action, error) {
    const message = action + '失敗' + (error && error.status
      ? '（HTTP ' + error.status + '）' : '，連線或回應異常，請稍後再試');
    const status = document.getElementById('ap-status');
    if (status) status.textContent = message;
    alert(message);
  }

  async function pushRules(candidate) {
    if (ruleWritePending) {
      const message = '規則儲存中，請稍候再操作';
      const status = document.getElementById('ap-status');
      if (status) status.textContent = message;
      alert(message); return;
    }
    ruleWritePending = true;
    try { await api('/alert/rules', 'POST', candidate); await refresh(); }
    catch (error) { reportWriteError('儲存規則', error); }
    finally { ruleWritePending = false; }
  }

  function addRule() {
    const sym = document.getElementById('ap-r-sym').value.trim();
    const type = document.getElementById('ap-r-type').value;
    const value = parseFloat(document.getElementById('ap-r-price').value);
    const meta = RULE_INPUT[type] || RULE_INPUT.cross_up;
    if (!sym || !(value >= meta.min && value <= meta.max)) { alert(meta.error); return; }
    const rule = { id: Date.now(), sym, market: document.getElementById('ap-r-mkt').value, type, note: '', enabled: true };
    if (meta.field === 'price') rule.price = value; else rule.threshold = value;
    if (document.getElementById('ap-r-once').checked) rule.once = true;
    pushRules([...rules, rule]);
  }

  async function saveCfg() {
    const body = {
      enabled: document.getElementById('ap-enabled').checked,
      market_signal_enabled: document.getElementById('ap-market-signal').checked,
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
      webhook: {
        enabled: document.getElementById('ap-wh-en').checked,
        url: document.getElementById('ap-wh-url').value.trim(),
      },
    };
    const tok = document.getElementById('ap-tg-token').value.trim();
    if (tok) body.telegram.bot_token = tok;
    const pw = document.getElementById('ap-em-pw').value;
    if (pw) body.email.app_password = pw;
    try {
      const r = await api('/alert/config', 'POST', body);
      if (r.ok) { alert('已儲存'); await refresh(); } else alert('儲存失敗: ' + JSON.stringify(r));
    } catch (error) { reportWriteError('儲存設定', error); }
  }

  async function testPush() {
    try {
      const r = await api('/alert/test', 'POST', {});
      alert('測試結果：' + JSON.stringify(r.results || r, null, 1));
    } catch (error) { reportWriteError('測試推播', error); }
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

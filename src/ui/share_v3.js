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
// 安全:寄送只在使用者「點按鈕」時觸發,絕不自動發送。
// ============================================================
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  const ShareResult = {};

  // 實際送出:POST /notify { text, subject } → { ok, results, error }
  ShareResult.send = async function (text, subject) {
    try {
      const r = await fetch('/notify', {
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

  window.ShareResult = ShareResult;
  console.log('[share] 分析結果寄送模組就緒 — ShareResult.buttonHTML / wire / send');
})();

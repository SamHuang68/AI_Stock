// AI 研究報告：預設使用既有本機模型；雲端模式須主動選取。
let aiReportTask = null;

(function injectAICSS() {
  const css = `
.ai-modal{position:fixed;inset:0;background:rgba(6,10,18,.92);z-index:9998;display:flex;align-items:center;justify-content:center}
.ai-modal .panel{background:var(--bg2);border:1px solid var(--gold-m);border-radius:8px;width:90vw;max-width:780px;height:88vh;display:flex;flex-direction:column;overflow:hidden}
.ai-modal .head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border);background:var(--bg)}
.ai-modal .head h3{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--gold);font-weight:700;letter-spacing:1px;margin:0}
.ai-body{flex:1;overflow-y:auto;padding:18px 24px;font-family:'Noto Serif TC','PingFang TC',sans-serif;font-size:13px;line-height:1.9;color:var(--text)}
.ai-body h1,.ai-body h2,.ai-body h3{color:var(--gold);font-family:'JetBrains Mono',monospace;margin:18px 0 8px;letter-spacing:.5px}
.ai-body h1{font-size:18px}.ai-body h2{font-size:15px}.ai-body h3{font-size:13px}
.ai-body p{margin:6px 0}
.ai-body code{background:var(--bg);color:var(--gold);padding:1px 5px;border-radius:3px;font-size:11.5px}
.ai-body table{width:100%;border-collapse:collapse;margin:10px 0;font-size:12px}
.ai-body th,.ai-body td{padding:6px 10px;border:1px solid var(--border);text-align:left}
.ai-body th{background:var(--bg3);color:var(--gold)}
.ai-body strong{color:var(--gold)}
.ai-body ul,.ai-body ol{margin:6px 0 6px 24px}
.ai-body li{margin:3px 0}
.ai-foot{padding:10px 18px;border-top:1px solid var(--border);background:var(--bg);display:flex;justify-content:space-between;align-items:center}
.ai-foot button{padding:6px 14px;background:transparent;border:1px solid var(--border);border-radius:3px;color:var(--tlo);font-family:monospace;font-size:10px;cursor:pointer;letter-spacing:.5px}
.ai-foot button.primary{background:var(--gold);color:#060A12;border:none;font-weight:700}
.ai-foot button:hover{color:var(--gold);border-color:var(--gold-m)}
.ai-foot button.primary:hover{background:#FBBF24;color:#060A12}
#btn-ai-report{padding:3px 10px;background:transparent;border:1px solid var(--border);border-radius:3px;color:var(--tlo);font-family:monospace;font-size:9.5px;cursor:pointer;letter-spacing:.5px}
#btn-ai-report:hover{color:var(--gold);background:var(--gold-s);border-color:var(--gold-m)}
.ai-loading{text-align:center;padding:80px 30px;color:var(--gold);font-family:monospace;font-size:12px;line-height:2}
.ai-loading .spin{display:inline-block;animation:airot 1.4s linear infinite;font-size:24px;margin-right:10px}
.ai-foot{flex-wrap:wrap;gap:8px}.ai-foot>div{flex-wrap:wrap}.ai-foot select{max-width:100%;background:var(--bg);color:var(--text)}.ai-foot button:disabled{opacity:.45;cursor:wait}
@keyframes airot{from{transform:rotate(0)}to{transform:rotate(360deg)}}
`;
  const s = document.createElement('style'); s.id='ai-v3-styles'; s.textContent=css;
  document.head.appendChild(s);
})();

// Minimal Markdown → HTML (no external lib)
function mdToHtml(md) {
  let h = escA(md);
  // Headers
  h = h.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
  h = h.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
  h = h.replace(/^# (.*?)$/gm, '<h1>$1</h1>');
  // Bold
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Inline code
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Markdown tables
  h = h.replace(/^(\|.+\|)\n(\|[-:\s|]+\|)\n((?:\|.+\|\n?)+)/gm, (m, hdr, sep, body) => {
    const hcells = hdr.split('|').slice(1, -1).map(c => `<th>${c.trim()}</th>`).join('');
    const rows = body.trim().split('\n').map(line => {
      const cells = line.split('|').slice(1, -1).map(c => `<td>${c.trim()}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    return `<table><thead><tr>${hcells}</tr></thead><tbody>${rows}</tbody></table>`;
  });
  // Lists
  h = h.replace(/^([\-\*]) (.+)$/gm, '<li>$2</li>');
  h = h.replace(/((?:<li>.+<\/li>\n?)+)/g, '<ul>$1</ul>');
  h = h.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');
  // Paragraphs (anything left)
  h = h.split('\n\n').map(block => {
    if (/^<(h[1-6]|ul|ol|table|p|li)/.test(block.trim())) return block;
    return '<p>' + block.replace(/\n/g, '<br>') + '</p>';
  }).join('\n');
  return h;
}

function syncAIReportControls(busy) {
  ['ai-generate', 'ai-last', 'ai-provider'].forEach(id => {
    const el = document.getElementById(id); if (el) el.disabled = busy;
  });
  const cancel = document.getElementById('ai-cancel'); if (cancel) cancel.hidden = !busy;
}
async function generateAIReport() {
  if (aiReportTask) return;
  // 不再呼叫會被導覽橋接包裝的全域入口，以免延遲重建面板。
  if (!document.getElementById('ai-body')) createAIReportModal();
  const body = document.getElementById('ai-body');
  const status = document.getElementById('ai-status');
  const cloud = document.getElementById('ai-provider').value === 'cloud';
  if (cloud && !S.aiKeySet) { status.textContent = '雲端模式尚未設定金鑰，可改用本機報告。'; return; }
  const context = window.STAI.context();
  syncAIReportControls(true);
  body.textContent = '正在準備報告，請保留此面板；本機模型載入與推理可能需要數分鐘。';
  const task = window.STAI.request({
    endpoint: cloud ? '/ai-report' : '/ai/local',
    body: cloud ? { positions: S.positions || {}, watches: S.watches || {},
      marketSym: S.mkt === 'US' ? '^GSPC' : '^TWII', context } : undefined,
    prompt: '請依提供的畫面快照，寫一份約 300 字繁體中文研究報告，依序列出資料日期、已知觀察、持倉風險、反方證據與待補資料。缺少大盤行情或新聞時直接說未提供，不可推測昨日表現、即時行情或買賣價位。',
    context,
    onText: text => { if (aiReportTask === task) body.innerHTML = mdToHtml(text); },
    onStatus: info => { status.textContent = (cloud ? '既有雲端報告' : '本機報告') +
      ' · 已等候 ' + info.elapsedSeconds + ' 秒 · ' + (info.hasText ? '接收正文中' : '模型準備／推理中') +
      ' · ' + info.requestId; }
  });
  aiReportTask = task;
  try {
    const result = await task.promise;
    if (aiReportTask !== task) return;
    const stamp = new Date().toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
    status.textContent = '完成 · ' + result.elapsedSeconds + ' 秒 · ' +
      [result.meta.host, result.meta.provider, result.meta.model].filter(Boolean).join(' · ');
    try { localStorage.setItem('ai_report_last', JSON.stringify({ stamp, md: result.text, meta: result.meta })); } catch (_) {}
  } catch (e) {
    if (aiReportTask === task) { status.textContent = '未完成：' + e.message; body.textContent = '本次報告未完成，未覆寫上次成功報告。'; }
  } finally {
    if (aiReportTask === task) { aiReportTask = null; syncAIReportControls(false); }
  }
}
function cancelAIReport() {
  if (aiReportTask) aiReportTask.cancel();
}

function escA(s) { return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

function createAIReportModal() {
  if (document.getElementById('ai-modal')) return;
  const m = document.createElement('div');
  m.className = 'ai-modal';
  m.id = 'ai-modal';
  m.innerHTML = `
    <div class="panel">
      <div class="head">
        <h3>🤖 AI 研究報告</h3>
        <span style="cursor:pointer;color:var(--tlo);font-size:20px" onclick="closeAIModal()">×</span>
      </div>
      <div class="ai-body" id="ai-body"><div style="color:var(--tlo);font-family:monospace;font-size:11px;line-height:1.8;padding:14px;text-align:center">點下方 <b style="color:var(--gold)">🔄 重新生成</b> 開始分析（預設本機模型，僅整理已提供的個股、持倉與觀察資料）<br>或 <b>📂 上次報告</b> 看上次結果。</div></div>
      <div id="ai-status" role="status" style="padding:8px 18px;overflow-wrap:anywhere;font-size:11px">本機模型不需要雲端金鑰。</div><div class="ai-foot">
        <span style="font-family:monospace;font-size:9.5px;color:var(--tf)">資料：目前畫面快照 · 未提供資料不推測</span>
        <div style="display:flex;gap:6px">
          <select id="ai-provider" aria-label="報告模型路徑"><option value="local">本機報告</option><option value="cloud">既有 Claude 雲端（傳送快照）</option></select><button id="ai-cancel" hidden onclick="cancelAIReport()">取消</button><button id="ai-last" onclick="loadLastAIReport()">📂 上次報告</button>
          <button id="ai-generate" onclick="generateAIReport()" class="primary">🔄 重新生成</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(m);
  m.addEventListener('click', e => { if (e.target === m) closeAIModal(); });
}
function openAIModal() { createAIReportModal(); }
function closeAIModal() { cancelAIReport(); aiReportTask = null; document.getElementById('ai-modal')?.remove(); }

function loadLastAIReport() {
  if (aiReportTask) return;
  try {
    const saved = JSON.parse(localStorage.getItem('ai_report_last') || 'null');
    if (!saved) { alert('還沒有上次報告'); return; }
    const body = document.getElementById('ai-body');
    if (body) body.innerHTML = `<div style="color:var(--tlo);font-family:monospace;font-size:9.5px;margin-bottom:10px">上次生成：${escA(saved.stamp)}</div>` + mdToHtml(saved.md);
  } catch (e) { alert('讀取失敗：' + e.message); }
}

/* v3.9: 改用 Toolbar 註冊表(模組化) — 取代手寫 #pro-tools 注入樣板 */
(function () {
  var spec = { id: 'btn-ai-report', label: '🤖 AI報告', cat: 'ai',
               title: 'AI 研究報告（預設本機模型，可選既有雲端）',
               onclick: openAIModal };   // 先開面板,由使用者點「重新生成」才分析
  (window.Toolbar ? window.Toolbar.register
    : function (s) { (window.__tbQueue = window.__tbQueue || []).push(s); })(spec);
})();

window.generateAIReport = generateAIReport;
window.openAIModal = openAIModal;
window.closeAIModal = closeAIModal;
window.loadLastAIReport = loadLastAIReport;

window.cancelAIReport = cancelAIReport;

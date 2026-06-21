// ============================================================
// Stock Terminal v3.0 — Claude AI 每日盤前報告
// ------------------------------------------------------------
// 收集你的持倉 + 觀察清單，呼叫 Claude API 產出 Markdown 報告。
// 需要在右上角 API KEY 設過 sk-ant-* 才能用。
// ============================================================

const SERVER_A = window.SERVER || `http://localhost:18432`;

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
@keyframes airot{from{transform:rotate(0)}to{transform:rotate(360deg)}}
`;
  const s = document.createElement('style'); s.id='ai-v3-styles'; s.textContent=css;
  document.head.appendChild(s);
})();

// Minimal Markdown → HTML (no external lib)
function mdToHtml(md) {
  // 安全(v3.9 review):中和潛在注入(AI 回應理論上可含 HTML)。移除 script/iframe/事件處理器/js: 協定。
  let h = String(md || '')
    .replace(/<\s*\/?\s*(script|iframe|object|embed|link|meta)\b/gi, '&lt;$1')
    .replace(/\son\w+\s*=/gi, ' data-x=')
    .replace(/javascript:/gi, 'js:');
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

async function generateAIReport() {
  if (!S.aiKeySet) { alert('請先在右上角設定 Claude API Key (sk-ant-...)'); return; }
  openAIModal();
  const body = document.getElementById('ai-body');
  body.innerHTML = '<div class="ai-loading"><span class="spin">⚙</span>Claude 撰寫中...<br><span style="font-size:10px;color:var(--tlo);margin-top:10px;display:inline-block">分析您的持倉與觀察清單</span></div>';
  // Collect data
  const positions = {};
  for (const code in (S.positions || {})) {
    const p = S.positions[code];
    positions[code] = {
      entry: p.entry, shares: p.shares,
      target: p.target, stop: p.stop,
      lastPrice: p.lastPrice,
      notes: p.notes,
    };
  }
  const watches = {};
  for (const code in (S.watches || {})) {
    watches[code] = S.watches[code];
  }
  try {
    const r = await fetch(`${SERVER_A}/ai-report`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        apiKey: S.apiKey,
        positions,
        watches,
        marketSym: S.mkt === 'US' ? '^GSPC' : '^TWII',
      }),
    });
    if (!r.ok) {
      const j = await r.json().catch(()=>({error:'HTTP '+r.status}));
      body.innerHTML = `<div style="padding:30px;color:var(--red);font-family:monospace;font-size:11px;line-height:2">⚠ 報告生成失敗<br><br>${escA(j.error || ('HTTP '+r.status))}</div>`;
      return;
    }
    const data = await r.json();
    body.innerHTML = mdToHtml(data.report || '無內容回傳');
    // Save to localStorage for re-open
    const stamp = new Date().toISOString().slice(0,16).replace('T', ' ');
    try { localStorage.setItem('ai_report_last', JSON.stringify({stamp, md: data.report})); } catch {}
  } catch (e) {
    body.innerHTML = `<div style="padding:30px;color:var(--red);font-family:monospace;font-size:11px;line-height:2">⚠ 網路錯誤：${escA(e.message)}</div>`;
  }
}

function escA(s) { return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

function openAIModal() {
  closeAIModal();
  const m = document.createElement('div');
  m.className = 'ai-modal';
  m.id = 'ai-modal';
  m.innerHTML = `
    <div class="panel">
      <div class="head">
        <h3>🤖 Claude AI 每日盤前報告</h3>
        <span style="cursor:pointer;color:var(--tlo);font-size:20px" onclick="closeAIModal()">×</span>
      </div>
      <div class="ai-body" id="ai-body"><div style="color:var(--tlo);font-family:monospace;font-size:11px;line-height:1.8;padding:14px;text-align:center">點下方 <b style="color:var(--gold)">🔄 重新生成</b> 開始分析(會用 Claude 跑你的持倉+觀察+大盤)<br>或 <b>📂 上次報告</b> 看上次結果。</div></div>
      <div class="ai-foot">
        <span style="font-family:monospace;font-size:9.5px;color:var(--tf)">資料：你的持倉 + 觀察 + 大盤 · 模型：Claude</span>
        <div style="display:flex;gap:6px">
          <button onclick="loadLastAIReport()">📂 上次報告</button>
          <button onclick="generateAIReport()" class="primary">🔄 重新生成</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(m);
  m.addEventListener('click', e => { if (e.target === m) closeAIModal(); });
}
function closeAIModal() { document.getElementById('ai-modal')?.remove(); }

function loadLastAIReport() {
  try {
    const saved = JSON.parse(localStorage.getItem('ai_report_last') || 'null');
    if (!saved) { alert('還沒有上次報告'); return; }
    const body = document.getElementById('ai-body');
    if (body) body.innerHTML = `<div style="color:var(--tlo);font-family:monospace;font-size:9.5px;margin-bottom:10px">上次生成：${saved.stamp}</div>` + mdToHtml(saved.md);
  } catch (e) { alert('讀取失敗：' + e.message); }
}

/* v3.9: 改用 Toolbar 註冊表(模組化) — 取代手寫 #pro-tools 注入樣板 */
(function () {
  var spec = { id: 'btn-ai-report', label: '🤖 AI報告', cat: 'pin',
               title: 'Claude AI 每日報告（需先設 API Key）',
               onclick: openAIModal };   // 先開面板,由使用者點「重新生成」才分析
  (window.Toolbar ? window.Toolbar.register
    : function (s) { (window.__tbQueue = window.__tbQueue || []).push(s); })(spec);
})();

window.generateAIReport = generateAIReport;
window.openAIModal = openAIModal;
window.closeAIModal = closeAIModal;
window.loadLastAIReport = loadLastAIReport;

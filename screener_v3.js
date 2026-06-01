// ============================================================
// Stock Terminal v3.0 — 全市場 Screener
// ------------------------------------------------------------
// 從 hardcoded 台股 Top 200+ 池中掃描符合條件的股票。
// 5 個預設策略一鍵掃，結果可直接加入觀察清單 / 載入線型。
// ============================================================

const SERVER_S = window.SERVER || `http://localhost:18432`;
let _screenerPresets = null;

(function injectScreenerCSS() {
  const css = `
.screener-modal{position:fixed;inset:0;background:rgba(6,10,18,.9);z-index:9998;display:flex;align-items:center;justify-content:center}
.screener-modal .panel{background:var(--bg2);border:1px solid var(--gold-m);border-radius:8px;width:90vw;max-width:780px;height:80vh;display:flex;flex-direction:column;overflow:hidden}
.screener-modal .head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border);background:var(--bg)}
.screener-modal .head h3{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--gold);font-weight:700;letter-spacing:1px;margin:0}
.scr-presets{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:6px;padding:14px;background:var(--bg);border-bottom:1px solid var(--border)}
.scr-preset{padding:10px 12px;background:var(--bg2);border:1px solid var(--border);border-radius:5px;cursor:pointer;transition:all .12s;font-family:monospace}
.scr-preset:hover{border-color:var(--gold-m);background:var(--gold-s)}
.scr-preset .ttl{font-size:11px;color:var(--gold);font-weight:700;letter-spacing:.5px}
.scr-preset .desc{font-size:9.5px;color:var(--tlo);margin-top:3px;line-height:1.5}
.scr-results{flex:1;overflow-y:auto;padding:0}
.scr-status{padding:10px 18px;background:var(--bg);color:var(--tlo);font-family:monospace;font-size:10px;border-bottom:1px solid var(--border)}
.scr-row{display:grid;grid-template-columns:90px 1fr 80px 70px 70px;align-items:center;gap:8px;padding:8px 14px;border-bottom:1px solid var(--bg3);font-family:monospace;font-size:10.5px;cursor:pointer;transition:background .12s}
.scr-row:hover{background:var(--gold-s)}
.scr-row .sym{font-weight:700;color:var(--thi);letter-spacing:.5px}
.scr-row .nm{color:var(--text);font-size:9.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.scr-row .px{text-align:right;color:var(--thi)}
.scr-row .ch{text-align:right;font-weight:700}
.scr-row .add{text-align:right;color:var(--gold);font-size:9px}
.scr-h{display:grid;grid-template-columns:90px 1fr 80px 70px 70px;gap:8px;padding:6px 14px;background:var(--bg);font-family:monospace;font-size:9px;color:var(--tlo);letter-spacing:.5px;border-bottom:1px solid var(--border)}
.scr-h div:nth-child(3),.scr-h div:nth-child(4),.scr-h div:nth-child(5){text-align:right}
#btn-screener{padding:3px 10px;background:transparent;border:1px solid var(--border);border-radius:3px;color:var(--tlo);font-family:monospace;font-size:9.5px;cursor:pointer;letter-spacing:.5px}
#btn-screener:hover{color:var(--gold);background:var(--gold-s);border-color:var(--gold-m)}
`;
  const s = document.createElement('style'); s.id='screener-v3-styles'; s.textContent=css;
  document.head.appendChild(s);
})();

async function loadScreenerPresets() {
  if (_screenerPresets) return _screenerPresets;
  try {
    const r = await fetch(`${SERVER_S}/screener`, {cache:'no-store'});
    if (!r.ok) return null;
    const data = await r.json();
    _screenerPresets = data;
    return data;
  } catch (e) { return null; }
}

async function openScreener() {
  closeScreener();
  const presets = await loadScreenerPresets();
  const m = document.createElement('div');
  m.className = 'screener-modal';
  m.id = 'screener-modal';
  let presetCards = '';
  if (presets?.presets) {
    for (const p of presets.presets) {
      presetCards += `<div class="scr-preset" data-scr-preset="${p.key}">
        <div class="ttl">🔍 ${escS(p.name)}</div>
        <div class="desc">${escS(p.desc)}</div>
      </div>`;
    }
  }
  m.innerHTML = `
    <div class="panel">
      <div class="head">
        <h3>🔍 全市場 Screener — 掃描 ${presets?.symbolCount || '?'} 檔台股</h3>
        <span style="cursor:pointer;color:var(--tlo);font-size:20px" onclick="closeScreener()">×</span>
      </div>
      <div class="scr-presets">${presetCards}</div>
      <div class="scr-h">
        <div>代號</div><div>名稱</div><div>現價</div><div>漲跌%</div><div>RSI/量比</div>
      </div>
      <div class="scr-results" id="scr-results">
        <div style="padding:30px;text-align:center;color:var(--tlo);font-family:monospace;font-size:11px">點上方策略開始掃描</div>
      </div>
    </div>
  `;
  document.body.appendChild(m);
  m.addEventListener('click', e => {
    if (e.target === m) closeScreener();
    const preset = e.target.closest('[data-scr-preset]');
    if (preset) runScreener(preset.dataset.scrPreset, preset.querySelector('.ttl').textContent);
    const row = e.target.closest('[data-scr-sym]');
    if (row) {
      const sym = row.dataset.scrSym;
      if (typeof loadSym === 'function') loadSym(sym, 'TW');
      closeScreener();
    }
  });
}
function closeScreener() { document.getElementById('screener-modal')?.remove(); }

async function runScreener(preset, label) {
  const list = document.getElementById('scr-results');
  if (!list) return;
  list.innerHTML = `<div style="padding:30px;text-align:center;color:var(--gold);font-family:monospace;font-size:11px">▶ 掃描中（${escS(label)}）...<br><span style="font-size:9px;color:var(--tlo);margin-top:6px;display:inline-block">200+ 檔同時抓資料約 20~40 秒</span></div>`;
  const t0 = Date.now();
  try {
    const r = await fetch(`${SERVER_S}/screener`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({preset}),
    });
    const data = await r.json();
    const dt = Math.round((Date.now() - t0) / 1000);
    if (!data.results?.length) {
      list.innerHTML = `<div style="padding:30px;text-align:center;color:var(--tlo);font-family:monospace;font-size:11px">無符合條件的股票<br><span style="font-size:9px;color:var(--tf)">掃了 ${data.scanned} 檔，耗時 ${dt}s</span></div>`;
      return;
    }
    let h = `<div style="padding:8px 14px;background:var(--gbg);color:var(--green);font-family:monospace;font-size:10px;border-bottom:1px solid var(--border)">✓ 找到 <b>${data.matched}</b> 檔（掃 ${data.scanned} 檔，耗時 ${dt}s） · 點擊載入</div>`;
    for (const x of data.results) {
      const chC = x.changePct >= 0 ? 'var(--green)' : 'var(--red)';
      h += `<div class="scr-row" data-scr-sym="${x.sym}">
        <span class="sym">${escS(x.sym)}</span>
        <span class="nm">${escS(x.name || '')}</span>
        <span class="px">${x.close?.toFixed(2) || '--'}</span>
        <span class="ch" style="color:${chC}">${x.changePct >= 0 ? '+' : ''}${x.changePct?.toFixed(2) || '0'}%</span>
        <span class="add">RSI ${x.rsi14 || '--'} · V ${x.volRatio || '--'}x</span>
      </div>`;
    }
    list.innerHTML = h;
  } catch (e) {
    list.innerHTML = `<div style="padding:30px;text-align:center;color:var(--red);font-family:monospace;font-size:11px">掃描失敗：${escS(e.message)}</div>`;
  }
}

function escS(s) { return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

(function injectScreenerBtn() {
  if (!document.getElementById('pro-tools')) return setTimeout(injectScreenerBtn, 100);
  if (document.getElementById('btn-screener')) return;
  const b = document.createElement('button');
  b.id = 'btn-screener';
  b.className = 'probtn';
  b.title = '全市場 Screener — 掃描符合策略的股票';
  b.innerHTML = '🔍 掃描';
  b.onclick = openScreener;
  document.getElementById('pro-tools').appendChild(b);
})();

window.openScreener = openScreener;
window.closeScreener = closeScreener;

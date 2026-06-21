// ============================================================
// Stock Terminal v3.0 — 全市場 Screener
// ------------------------------------------------------------
// 從 hardcoded 台股 Top 200+ 池中掃描符合條件的股票。
// 5 個預設策略一鍵掃，結果可直接加入觀察清單 / 載入線型。
// ============================================================

const SERVER_S = window.SERVER || `http://localhost:18432`;
let _screenerPresets = null;
let _scrLastHTML = null, _scrLastSector = '全部';   // v3.9: 結果快取，關了再開不必重掃

(function injectScreenerCSS() {
  const css = `
/* v3.9: 右側常駐 dock，不蓋 K 線(圖在左)，點股載入後面板保留 */
.screener-modal{position:fixed;top:52px;right:0;bottom:0;z-index:9998;pointer-events:none}
.screener-modal .panel{pointer-events:auto;position:absolute;top:0;right:0;bottom:0;width:min(460px,44vw);max-width:none;height:auto;background:var(--bg2);border-left:2px solid var(--gold-m);border-radius:0;display:flex;flex-direction:column;overflow:hidden;box-shadow:-10px 0 34px rgba(0,0,0,.55)}
.scr-row.active{background:var(--gold-s);border-left:3px solid var(--gold)}
/* v3.9: 收合成右緣細條，露出右側 STATS 看漲跌原因 */
.screener-modal .panel.scr-collapsed{width:28px}
#right.scr-docked #rpanel{padding-right:36px}  /* 收合時右側面板讓出細條寬度,STATS 數值不被遮 */
.screener-modal .panel.scr-collapsed > *{display:none}
.screener-modal .panel.scr-collapsed .scr-handle{display:flex}
.scr-handle{display:none;position:absolute;inset:0;align-items:center;justify-content:center;writing-mode:vertical-rl;cursor:pointer;color:var(--gold);font-family:'JetBrains Mono',monospace;font-size:12px;letter-spacing:3px;background:var(--bg2)}
.scr-handle:hover{background:var(--gold-s)}
.screener-modal .head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border);background:var(--bg)}
.screener-modal .head h3{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--gold);font-weight:700;letter-spacing:1px;margin:0}
.scr-presets{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:4px;padding:6px 8px;background:var(--bg);border-bottom:1px solid var(--border);max-height:24vh;overflow-y:auto;flex-shrink:0}
.scr-preset{padding:3px 8px!important}
.scr-preset .ttl{font-size:10.5px}
.scr-preset .desc{margin-top:0;font-size:8.5px;line-height:1.3}
.scr-results{flex:1;overflow-y:auto;min-height:56vh}
.scr-row{padding:5px 14px!important}
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
      const isShort = p.side === 'short';
      const tag = isShort
        ? '<span style="color:var(--red);font-weight:700">▼空</span> '
        : '<span style="color:var(--green);font-weight:700">▲多</span> ';
      presetCards += `<div class="scr-preset" data-scr-preset="${p.key}" style="border-left:3px solid ${isShort ? 'var(--red)' : 'var(--green)'}">
        <div class="ttl">${tag}${escS(p.name)}</div>
        <div class="desc">${escS(p.desc)}</div>
      </div>`;
    }
  }
  m.innerHTML = `
    <div class="panel">
      <div class="scr-handle" onclick="screenerExpand()">🔍 掃描結果 ⟨</div>
      <div class="head">
        <h3>🔍 全市場 Screener — 掃描 ${presets?.symbolCount || '?'} 檔台股</h3>
        <span style="display:flex;align-items:center;gap:10px">
          <span style="cursor:pointer;color:var(--tlo);font-size:15px" onclick="screenerCollapse()" title="收合(看右側 STATS 找原因)">⟩</span>
          <span style="cursor:pointer;color:var(--tlo);font-size:20px" onclick="closeScreener()">×</span>
        </span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;padding:8px 14px;border-bottom:1px solid var(--border);font-family:monospace;font-size:11px;color:var(--tlo)">
        類股篩選
        <select id="scr-sector" style="background:var(--bg2);border:1px solid var(--border);color:var(--text);border-radius:5px;padding:4px 8px;font-size:11px;max-width:260px">
          <option value="全部">全部（全市場）</option>
          <option value="__TECH__">🔌 科技電子（整合）</option>
          ${(presets?.sectors || []).map(s => `<option value="${escS(s)}">${escS(s)}</option>`).join('')}
        </select>
        <span style="color:var(--tf);font-size:9px">選定後只掃該類股，結果更聚焦</span>
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
  // 還原上次掃描結果與類股，免重掃
  const secEl = document.getElementById('scr-sector');
  if (secEl && _scrLastSector) secEl.value = _scrLastSector;
  if (_scrLastHTML) { const list = document.getElementById('scr-results'); if (list) list.innerHTML = _scrLastHTML; }
  m.addEventListener('click', e => {
    const preset = e.target.closest('[data-scr-preset]');
    if (preset) { runScreener(preset.dataset.scrPreset, preset.querySelector('.ttl').textContent); return; }
    const row = e.target.closest('[data-scr-sym]');
    if (row) {
      const sym = row.dataset.scrSym;
      if (typeof loadSym === 'function') loadSym(sym, 'TW');
      // 常駐右側：點股載入左側 K 線，高亮選中，不關閉、不重掃；
      // 自動收合成右緣細條 → 右側 STATS 露出來看漲跌原因；點細條再展開挑下一檔
      m.querySelectorAll('.scr-row.active').forEach(r => r.classList.remove('active'));
      row.classList.add('active');
      screenerCollapse();
    }
  });
}
function closeScreener() { document.getElementById('screener-modal')?.remove(); document.getElementById('right')?.classList.remove('scr-docked'); }
function screenerCollapse() {
  document.querySelector('#screener-modal .panel')?.classList.add('scr-collapsed');
  document.getElementById('right')?.classList.add('scr-docked');   // 收合→右側面板讓出細條寬度
}
function screenerExpand() {
  document.querySelector('#screener-modal .panel')?.classList.remove('scr-collapsed');
  document.getElementById('right')?.classList.remove('scr-docked'); // 展開時 dock 覆蓋右側,不需讓位
}

async function runScreener(preset, label) {
  const list = document.getElementById('scr-results');
  if (!list) return;
  list.innerHTML = `<div style="padding:30px;text-align:center;color:var(--gold);font-family:monospace;font-size:11px">▶ 掃描中（${escS(label)}）...<br><span style="font-size:9px;color:var(--tlo);margin-top:6px;display:inline-block">全台股上市+上櫃約 1800 檔，首次掃描約 1~2 分鐘（已快取後更快）</span></div>`;
  const t0 = Date.now();
  try {
    const sectorEl = document.getElementById('scr-sector');
    const sector = sectorEl ? sectorEl.value : '全部';
    const r = await fetch(`${SERVER_S}/screener`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({preset, sector}),
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
    _scrLastHTML = h; _scrLastSector = sector;   // 快取結果
  } catch (e) {
    list.innerHTML = `<div style="padding:30px;text-align:center;color:var(--red);font-family:monospace;font-size:11px">掃描失敗：${escS(e.message)}</div>`;
  }
}

function escS(s) { return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

/* v3.9: 改用 Toolbar 註冊表(模組化) — 取代手寫 #pro-tools 注入樣板 */
(function () {
  var spec = { id: 'btn-screener', label: '🔍 掃描', cat: 'screen',
               title: '全市場 Screener — 掃描符合策略的股票', onclick: openScreener };
  (window.Toolbar ? window.Toolbar.register
    : function (s) { (window.__tbQueue = window.__tbQueue || []).push(s); })(spec);
})();

window.openScreener = openScreener;
window.closeScreener = closeScreener;

// ============================================================
// Stock Terminal v2.0 — ETF Catalog & Category Browser
// ------------------------------------------------------------
// 將 ETF△ 分頁從「平鋪 10 檔」升級為「依分類分頁 + ⚙ 管理 modal」。
// 後端：/etf-catalog (GET/POST) — 讀寫 etf_catalog.json
//
// 載入：建議放最後（依賴 renderEtfDelta、S.etfDelta）
// ============================================================

(function bootEtfV2() {
  if (typeof S === 'undefined') return;
  S.etfCatalog = null;
  S.etfCatActive = 'active';   // 當前 active 分類 key
})();

const SERVER_E = window.SERVER || `http://localhost:18432`;

// ── Fetch & save catalog ────────────────────────────────────
async function fetchEtfCatalog() {
  try {
    const r = await fetch(`${SERVER_E}/etf-catalog`, {cache:'no-store'});
    if (!r.ok) { console.warn('[etf-v2] catalog fetch failed:', r.status); return null; }
    const data = await r.json();
    S.etfCatalog = data;
    return data;
  } catch (e) { console.warn('[etf-v2] fetch error:', e); return null; }
}

async function saveEtfCatalog(catalog) {
  try {
    const r = await fetch(`${SERVER_E}/etf-catalog`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(catalog),
    });
    if (!r.ok) { const j = await r.json().catch(()=>({error: 'HTTP '+r.status})); throw new Error(j.error || 'save failed'); }
    const j = await r.json();
    return j;
  } catch (e) { alert('儲存失敗：' + e.message); return null; }
}

// ── CSS for ETF v2 ─────────────────────────────────────────
(function injectEtfCSS() {
  const css = `
.etf-cattabs{display:flex;flex-wrap:wrap;gap:2px;padding:6px 8px;background:var(--bg);border-bottom:1px solid var(--border)}
.etf-cattab{padding:4px 8px;background:transparent;border:1px solid var(--border);border-radius:3px;color:var(--tlo);font-family:monospace;font-size:9.5px;cursor:pointer;letter-spacing:.3px;transition:all .12s;white-space:nowrap}
.etf-cattab:hover{color:var(--gold);background:var(--gold-s)}
.etf-cattab.on{background:var(--gold-s);border-color:var(--gold);color:var(--gold);font-weight:700}
.etf-cattab .cnt{font-size:8.5px;color:var(--tf);margin-left:4px;font-weight:400}
.etf-cattab.on .cnt{color:var(--gold)}
#etf-mgr-btn{padding:3px 10px;background:transparent;border:1px solid var(--border);border-radius:3px;color:var(--tlo);font-family:monospace;font-size:9.5px;cursor:pointer;letter-spacing:.5px;margin-left:auto}
#etf-mgr-btn:hover{color:var(--gold);background:var(--gold-s);border-color:var(--gold-m)}
.etf-modal{position:fixed;inset:0;background:rgba(6,10,18,.85);z-index:9999;display:flex;align-items:center;justify-content:center}
.etf-modal .panel{background:var(--bg2);border:1px solid var(--gold-m);border-radius:8px;width:680px;max-width:95vw;height:80vh;display:flex;flex-direction:column;overflow:hidden}
.etf-modal .head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border);background:var(--bg)}
.etf-modal .head h3{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--gold);font-weight:700;letter-spacing:1px;margin:0}
.etf-modal .body{flex:1;overflow-y:auto;padding:8px 0}
.etf-modal .foot{padding:10px 18px;border-top:1px solid var(--border);background:var(--bg);display:flex;justify-content:space-between;align-items:center;gap:8px}
.etf-cat-grp{margin:8px 0}
.etf-cat-h{padding:8px 18px;font-family:monospace;font-size:11px;color:var(--gold);font-weight:700;letter-spacing:.5px;background:var(--bg);border-top:1px solid var(--border);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;cursor:pointer;user-select:none}
.etf-cat-h .icon{font-size:13px}
.etf-cat-h .meta{font-size:9.5px;color:var(--tlo);font-weight:400}
.etf-cat-desc{padding:5px 18px;font-family:monospace;font-size:9.5px;color:var(--tf);line-height:1.6;background:var(--bg);border-bottom:1px solid var(--border)}
.etf-list{padding:4px 18px}
.etf-item{display:flex;align-items:center;gap:10px;padding:7px 4px;border-bottom:1px solid var(--bg3);font-family:'JetBrains Mono',monospace;font-size:11px}
.etf-item:last-child{border-bottom:none}
.etf-item input[type=checkbox]{accent-color:var(--gold);width:14px;height:14px;cursor:pointer}
.etf-item .code{color:var(--thi);font-weight:700;letter-spacing:.5px;min-width:60px}
.etf-item .name{flex:1;color:var(--text);font-size:10.5px}
.etf-item.disabled{opacity:.55}
.etf-item .rm{color:var(--tf);cursor:pointer;font-size:13px;padding:0 4px;border-radius:3px}
.etf-item .rm:hover{color:var(--red);background:rgba(248,113,113,.12)}
.etf-add-form{padding:10px 18px;background:var(--gold-s);border-top:2px solid var(--gold-m);display:flex;flex-direction:column;gap:6px;margin-top:8px}
.etf-add-form .row{display:flex;gap:6px;align-items:center}
.etf-add-form input,.etf-add-form select{background:var(--bg3);border:1px solid var(--border);border-radius:3px;padding:5px 8px;color:var(--thi);font-family:monospace;font-size:10.5px;outline:none}
.etf-add-form input{flex:1}
.etf-add-form button{padding:5px 12px;background:var(--gold);color:#060A12;border:none;border-radius:3px;font-family:monospace;font-size:10px;font-weight:700;cursor:pointer;letter-spacing:.5px}
.etf-add-form .hint{font-size:9px;color:var(--tlo);font-family:monospace;line-height:1.5}
.etf-mod-x{cursor:pointer;color:var(--tlo);font-size:20px;line-height:1;padding:0 4px}
.etf-mod-x:hover{color:var(--red)}
.etf-action-btn{padding:6px 14px;border-radius:4px;font-family:monospace;font-size:10px;font-weight:700;cursor:pointer;letter-spacing:.5px;border:1px solid var(--border);background:transparent;color:var(--tlo)}
.etf-action-btn.primary{background:var(--gold);color:#060A12;border:none}
.etf-action-btn:hover{color:var(--gold);border-color:var(--gold-m)}
.etf-action-btn.primary:hover{background:#FBBF24;color:#060A12}
`;
  const s = document.createElement('style'); s.id='etf-v2-styles'; s.textContent=css;
  document.head.appendChild(s);
})();

// ── Override renderEtfDelta to add category tabs + filter ──
// CRITICAL: save the v1 renderEtfDelta BEFORE we patch it, otherwise
// _origRenderEtfDelta would point to our patched version → infinite recursion
// and filter becomes a no-op.
(function patchEtfRender() {
  if (typeof renderEtfDelta !== 'function') return setTimeout(patchEtfRender, 100);
  if (window._origRenderEtfDelta) return;   // already patched
  window._origRenderEtfDelta = window.renderEtfDelta;
  const orig = window._origRenderEtfDelta;

  window.renderEtfDelta = function () {
    // Lazy-load catalog
    if (S.etfCatalog == null) {
      fetchEtfCatalog().then(() => {
        if (S.tab === 'etf' && typeof renderRpanel === 'function') renderRpanel();
      });
    }

    // ── Header: category tabs + ⚙ manage button ──
    const cats = S.etfCatalog?.categories || [];
    let header = '<div class="etf-cattabs">';
    if (cats.length) {
      for (const cat of cats) {
        const enabledCount = (cat.etfs || []).filter(e => e.enabled).length;
        if (enabledCount === 0 && cat.key !== S.etfCatActive) continue;
        const on = cat.key === S.etfCatActive;
        header += `<button class="etf-cattab${on?' on':''}" data-etfact="cat-tab" data-cat="${cat.key}">${cat.icon||''} ${escE(cat.name)}<span class="cnt">${enabledCount}</span></button>`;
      }
    }
    header += `<button id="etf-mgr-btn" data-etfact="mgr-open">⚙ 管理 ETF</button>`;
    header += '</div>';

    // ── Body: filter S.etfDelta by current category, then call orig ──
    // If no catalog loaded yet → just render orig (no filtering)
    if (!S.etfCatalog || !S.etfDelta?.etfs?.length) {
      return header + orig.apply(this, arguments);
    }
    const cat = S.etfCatalog.categories.find(c => c.key === S.etfCatActive);
    if (!cat) return header + orig.apply(this, arguments);
    const allowedCodes = new Set((cat.etfs || []).filter(e => e.enabled).map(e => e.code.toUpperCase()));
    if (allowedCodes.size === 0) {
      return header + `<div style="padding:30px 14px;text-align:center;font-family:monospace;font-size:10.5px;color:var(--tlo);line-height:1.9">此分類無已啟用的 ETF<br><span style="font-size:9px;color:var(--tf)">點右上 ⚙ 管理 ETF 開啟追蹤</span></div>`;
    }

    // Temporarily swap S.etfDelta to filtered subset
    const realDelta = S.etfDelta;
    const filteredEtfs = realDelta.etfs.filter(e => allowedCodes.has((e.code || '').toUpperCase()));
    if (filteredEtfs.length === 0) {
      // Allowed codes exist but none are in current history snapshot
      const allowedList = [...allowedCodes].join(', ');
      const inHistory = realDelta.etfs.map(e => e.code).join(', ');
      return header + `<div style="padding:24px 14px;text-align:center;font-family:monospace;font-size:10px;color:var(--tlo);line-height:1.9">此分類已啟用 ${allowedCodes.size} 檔 (${escE(allowedList)})<br>但歷史快照只含 ${realDelta.etfs.length} 檔 (${escE(inHistory)})<br><span style="font-size:9px;color:var(--orange);margin-top:6px;display:inline-block">⚠ 需手動跑 <code style="color:var(--gold)">run_tracker.bat</code><br>或等明天排程，才會抓新加入的 ETF 持股</span></div>`;
    }
    S.etfDelta = {...realDelta, etfs: filteredEtfs};
    let body;
    try { body = orig.apply(this, arguments); }
    catch (e) { console.error('[etf-v2] orig render failed:', e); body = ''; }
    S.etfDelta = realDelta;   // ALWAYS restore
    return header + body;
  };
  console.log('[etf-v2] patched renderEtfDelta — filter active');
})();

// ── Catalog manager modal ──────────────────────────────────
async function openEtfMgrModal() {
  if (S.etfCatalog == null) {
    await fetchEtfCatalog();
  }
  closeEtfMgrModal();
  const m = document.createElement('div');
  m.className = 'etf-modal';
  m.id = 'etf-modal';
  m.innerHTML = `
    <div class="panel">
      <div class="head">
        <h3>⚙ ETF 觀測池管理</h3>
        <span class="etf-mod-x" data-etfact="mgr-close">×</span>
      </div>
      <div class="body" id="etf-mgr-body">${renderEtfMgrBody()}</div>
      <div class="foot">
        <span style="font-family:monospace;font-size:9.5px;color:var(--tlo)" id="etf-foot-msg">勾選 = 加入每日追蹤池 · 點 × 移除自訂 ETF</span>
        <div style="display:flex;gap:6px">
          <button class="etf-action-btn" data-etfact="mgr-close">關閉</button>
          <button class="etf-action-btn" data-etfact="mgr-save">💾 只儲存</button>
          <button class="etf-action-btn primary" data-etfact="mgr-save-run">💾 儲存並立即更新</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(m);
  m.addEventListener('click', e => { if (e.target === m) closeEtfMgrModal(); });
}
function closeEtfMgrModal() {
  document.getElementById('etf-modal')?.remove();
}

function renderEtfMgrBody() {
  if (!S.etfCatalog?.categories) {
    return '<div style="padding:30px;text-align:center;color:var(--tlo);font-family:monospace">載入 catalog 中...</div>';
  }
  let h = '';
  for (let ci = 0; ci < S.etfCatalog.categories.length; ci++) {
    const cat = S.etfCatalog.categories[ci];
    const enabledCnt = (cat.etfs || []).filter(e => e.enabled).length;
    h += `<div class="etf-cat-grp">
      <div class="etf-cat-h">
        <span><span class="icon">${cat.icon||''}</span> ${escE(cat.name)}</span>
        <span class="meta">${enabledCnt} / ${(cat.etfs||[]).length}</span>
      </div>
      <div class="etf-cat-desc">${escE(cat.desc || '')}</div>
      <div class="etf-list">`;
    for (let ei = 0; ei < (cat.etfs || []).length; ei++) {
      const e = cat.etfs[ei];
      const isCustom = cat.key === 'custom';
      h += `<div class="etf-item${e.enabled?'':' disabled'}">
        <input type="checkbox" data-etfact="toggle" data-ci="${ci}" data-ei="${ei}" ${e.enabled?'checked':''}>
        <span class="code">${escE(e.code)}</span>
        <span class="name">${escE(e.name||'')}</span>
        ${isCustom ? `<span class="rm" data-etfact="remove" data-ci="${ci}" data-ei="${ei}" title="移除">×</span>` : ''}
      </div>`;
    }
    h += `</div>`;
    // Custom category 加新增表單
    if (cat.key === 'custom') {
      h += `<div class="etf-add-form">
        <div style="font-family:monospace;font-size:10px;color:var(--gold);font-weight:700;letter-spacing:.5px">+ 新增自訂 ETF</div>
        <div class="row">
          <input id="etf-add-code"  type="text" placeholder="代號（如 00935A）" maxlength="8" style="text-transform:uppercase">
          <input id="etf-add-name"  type="text" placeholder="名稱（顯示用）" maxlength="20">
          <select id="etf-add-cat">
            ${S.etfCatalog.categories.map(c => `<option value="${c.key}" ${c.key==='custom'?'selected':''}>${c.icon||''} ${escE(c.name)}</option>`).join('')}
          </select>
          <button data-etfact="add">＋ 加入</button>
        </div>
        <div class="hint">ETF 代號需可在 MoneyDJ 的 <code>basic0007.xdjhtm?etfid=CODE.TW</code> 查到才能抓持股</div>
      </div>`;
    }
    h += `</div>`;
  }
  return h;
}

// Modal interactions
document.addEventListener('click', ev => {
  const el = ev.target.closest('[data-etfact]');
  if (!el) return;
  const act = el.dataset.etfact;

  if (act === 'cat-tab') {
    ev.preventDefault();
    S.etfCatActive = el.dataset.cat;
    if (typeof renderRpanel === 'function') renderRpanel();
  }
  if (act === 'mgr-open') {
    ev.preventDefault();
    openEtfMgrModal();
  }
  if (act === 'mgr-close') {
    ev.preventDefault();
    closeEtfMgrModal();
  }
  if (act === 'toggle') {
    const ci = +el.dataset.ci, ei = +el.dataset.ei;
    const e = S.etfCatalog.categories[ci]?.etfs[ei];
    if (e) e.enabled = el.checked;
    // Update visual state of row
    const row = el.closest('.etf-item');
    if (row) row.classList.toggle('disabled', !el.checked);
    // Update header count
    const grp = el.closest('.etf-cat-grp');
    if (grp) {
      const meta = grp.querySelector('.etf-cat-h .meta');
      const enabled = S.etfCatalog.categories[ci].etfs.filter(x => x.enabled).length;
      const total = S.etfCatalog.categories[ci].etfs.length;
      if (meta) meta.textContent = `${enabled} / ${total}`;
    }
  }
  if (act === 'remove') {
    ev.preventDefault();
    const ci = +el.dataset.ci, ei = +el.dataset.ei;
    if (confirm(`移除 ${S.etfCatalog.categories[ci]?.etfs[ei]?.code}？`)) {
      S.etfCatalog.categories[ci].etfs.splice(ei, 1);
      const body = document.getElementById('etf-mgr-body');
      if (body) body.innerHTML = renderEtfMgrBody();
    }
  }
  if (act === 'add') {
    ev.preventDefault();
    const code = document.getElementById('etf-add-code').value.trim().toUpperCase();
    const name = document.getElementById('etf-add-name').value.trim();
    const catKey = document.getElementById('etf-add-cat').value;
    if (!code || !name) { alert('請填代號與名稱'); return; }
    if (!/^[0-9]{4,6}[A-Z]?$/.test(code)) { alert('代號格式不正確（例：00935A、0050、006208）'); return; }
    const cat = S.etfCatalog.categories.find(c => c.key === catKey);
    if (!cat) return;
    if (cat.etfs.find(e => e.code === code)) { alert('該 ETF 已存在此分類'); return; }
    cat.etfs.push({code, name, enabled: true});
    const body = document.getElementById('etf-mgr-body');
    if (body) body.innerHTML = renderEtfMgrBody();
  }
  if (act === 'mgr-save') {
    ev.preventDefault();
    el.disabled = true; el.textContent = '儲存中...';
    saveEtfCatalog(S.etfCatalog).then(r => {
      el.disabled = false;
      if (r?.ok) {
        el.textContent = `✓ 已存 (${r.enabledCount} 檔)`;
        setEtfFootMsg(`✓ Catalog 已存，${r.enabledCount} 檔啟用。下次排程或手動跑 tracker 後生效。`, 'var(--green)');
        setTimeout(() => { el.textContent = '💾 只儲存'; }, 2000);
      } else {
        el.textContent = '💾 只儲存';
      }
    });
  }
  if (act === 'mgr-save-run') {
    ev.preventDefault();
    el.disabled = true; el.textContent = '儲存中...';
    saveEtfCatalog(S.etfCatalog).then(async r => {
      if (!r?.ok) { el.disabled = false; el.textContent = '💾 儲存並立即更新'; return; }
      el.textContent = '▶ 啟動 tracker...';
      setEtfFootMsg(`✓ Catalog 已存 (${r.enabledCount} 檔)，正在抓 MoneyDJ 持股資料...`, 'var(--gold)');
      // Fire tracker run
      try {
        const rr = await fetch(`${SERVER_E}/etf-tracker/run`, {method: 'POST'});
        if (!rr.ok) {
          const j = await rr.json().catch(()=>({error: 'HTTP '+rr.status}));
          alert('啟動 tracker 失敗：' + (j.error || rr.status));
          el.disabled = false; el.textContent = '💾 儲存並立即更新';
          return;
        }
      } catch (e) {
        alert('啟動失敗：' + e.message);
        el.disabled = false; el.textContent = '💾 儲存並立即更新';
        return;
      }
      // Poll status every 2s up to 5 min
      let attempts = 0;
      const maxAttempts = 150;
      const startTs = Date.now();
      const poll = async () => {
        attempts++;
        try {
          const sr = await fetch(`${SERVER_E}/etf-tracker/status`, {cache:'no-store'});
          const st = await sr.json();
          const elapsed = Math.round((Date.now() - startTs) / 1000);
          if (st.running) {
            el.textContent = `▶ 抓取中 ${elapsed}s...`;
            setEtfFootMsg(`抓取中 ${elapsed} 秒（首次跑全部 ETF 可能需 30~60 秒）...`, 'var(--gold)');
            if (attempts < maxAttempts) return setTimeout(poll, 2000);
            else { setEtfFootMsg('⚠ tracker 還在跑但等待超時，請稍後手動刷新', 'var(--red)'); el.disabled = false; el.textContent = '💾 儲存並立即更新'; return; }
          }
          // Finished
          if (st.lastReturnCode === 0) {
            el.textContent = `✓ 完成 (${st.lastDuration}s)`;
            setEtfFootMsg(`✓ 抓取完成，耗時 ${st.lastDuration} 秒`, 'var(--green)');
            // Reload /etf-delta + close modal + refresh panel
            if (typeof fetchEtfDelta === 'function') await fetchEtfDelta();
            setTimeout(() => {
              closeEtfMgrModal();
              if (typeof renderRpanel === 'function') renderRpanel();
            }, 1200);
          } else {
            el.textContent = '⚠ 失敗';
            const tail = (st.lastOutput || '').split('\n').slice(-3).join('\n');
            setEtfFootMsg(`⚠ tracker 失敗 (code ${st.lastReturnCode})：${tail}`, 'var(--red)');
            el.disabled = false;
            setTimeout(() => { el.textContent = '💾 儲存並立即更新'; }, 4000);
          }
        } catch (e) {
          console.warn('[etf-v2] poll error:', e);
          if (attempts < maxAttempts) return setTimeout(poll, 2000);
          setEtfFootMsg('⚠ 輪詢失敗：' + e.message, 'var(--red)');
          el.disabled = false; el.textContent = '💾 儲存並立即更新';
        }
      };
      setTimeout(poll, 1500);
    });
  }
});

function setEtfFootMsg(msg, color) {
  const m = document.getElementById('etf-foot-msg');
  if (m) { m.textContent = msg; m.style.color = color || 'var(--tlo)'; }
}

function escE(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

// ── Expose ─────────────────────────────────────────────────
window.fetchEtfCatalog = fetchEtfCatalog;
window.saveEtfCatalog  = saveEtfCatalog;
window.openEtfMgrModal = openEtfMgrModal;

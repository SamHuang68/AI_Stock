// ============================================================
// Stock Terminal v3.4 — Plan Card (下周執行計畫)
// ------------------------------------------------------------
// 對標 PDF「下周執行總表」格式 — 每檔可輸入：
//   role         主倉 / 動能倉 / 攻擊倉 / 觀察倉
//   buyZoneLow/H 可買區下緣 / 上緣 (例: 270 ~ 275)
//   resistance   壓力位 (突破即追)
//   stopLoss     減碼線
//   weakBreak    出場線 (跌破即砍)
//   longCondition 多方條件文字
//   outlook      基本面/題材展望
//
// 切到該股時自動在主圖畫水平線：綠買區、黃壓力、橙減碼、紅出場
// 資料用 localStorage（跨會話保留）；alert_v3.js 監聽 S.plans 做警報
// ============================================================

(function (global) {
  'use strict';

  const LS_KEY_PLAN = 'stock_terminal_plans_v3';
  const ROLES = ['主倉', '動能倉', '攻擊倉', '觀察倉'];

  // ── CSS injection: prevent form inputs from overflowing right panel ──
  // 右面板固定 340px，扣掉 padding 後 1fr 欄只剩 ~220px。買區下/上兩個
  // type=number input 用 flex:1 但 spinner arrow 撐住 intrinsic min-width
  // 導致溢出。修法：box-sizing:border-box + min-width:0 強制 shrink + 隱藏
  // spinner arrow（節省 ~16px，也讓觸控更乾淨）。
  (function injectPlanFormCss() {
    if (document.getElementById('plan-v3-form-css')) return;
    const css = `
.plan-edit input, .plan-edit select, .plan-edit textarea {
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
}
.plan-edit input[type="number"]::-webkit-outer-spin-button,
.plan-edit input[type="number"]::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.plan-edit input[type="number"] {
  -moz-appearance: textfield;
  appearance: textfield;
}
.plan-edit > div[style*="grid"] {
  min-width: 0;
}
.plan-edit > div[style*="grid"] > span[style*="flex"] {
  min-width: 0;
  overflow: hidden;
}
`;
    const style = document.createElement('style');
    style.id = 'plan-v3-form-css';
    style.textContent = css;
    document.head.appendChild(style);
  })();

  // ── State bootstrap ──
  function bootPlans() {
    if (typeof S === 'undefined') {
      console.error('[v3-plan] global S missing — v1 not loaded?');
      return;
    }
    try {
      const stored = localStorage.getItem(LS_KEY_PLAN);
      S.plans = stored ? JSON.parse(stored) : {};
    } catch { S.plans = {}; }
    if (typeof S.plans !== 'object' || S.plans === null || Array.isArray(S.plans)) {
      S.plans = {};
    }
    S.planEditing = null;     // sym currently being edited
    S.planPriceLines = [];    // tracked PriceLine objects for cleanup
    console.log('[v3-plan] booted —', Object.keys(S.plans).length, 'plan(s) loaded');
  }

  function savePlans() {
    if (!S.plans) S.plans = {};
    try { localStorage.setItem(LS_KEY_PLAN, JSON.stringify(S.plans)); } catch {}
  }

  // ── Public API ──────────────────────────────────────────────
  function getPlan(sym) {
    if (!S.plans) S.plans = {};
    return S.plans[sym || S.sym] || null;
  }

  function setPlan(sym, mkt, fields) {
    if (!sym) return false;
    if (!S.plans) S.plans = {};
    const existing = S.plans[sym] || {};
    const isNew = !existing.addedAt;
    S.plans[sym] = {
      sym, mkt: mkt || existing.mkt || 'TW',
      role:          fields.role          ?? existing.role          ?? '觀察倉',
      buyZoneLow:    n(fields.buyZoneLow,    existing.buyZoneLow),
      buyZoneHigh:   n(fields.buyZoneHigh,   existing.buyZoneHigh),
      resistance:    n(fields.resistance,    existing.resistance),
      stopLoss:      n(fields.stopLoss,      existing.stopLoss),
      weakBreak:     n(fields.weakBreak,     existing.weakBreak),
      longCondition: fields.longCondition ?? existing.longCondition ?? '',
      outlook:       fields.outlook       ?? existing.outlook       ?? '',
      addedAt:       existing.addedAt || Date.now(),
      updatedAt:     Date.now(),
    };
    savePlans();
    if (sym === S.sym) drawPlanLines();
    // Log history event
    if (typeof global.PlanHistoryV3?.log === 'function') {
      try { global.PlanHistoryV3.log(sym, isNew ? 'created' : 'edited', null, null); } catch {}
    }
    return true;
  }

  function n(v, fallback) {
    if (v === '' || v == null) return fallback ?? null;
    const f = parseFloat(v);
    return Number.isFinite(f) ? f : (fallback ?? null);
  }

  function deletePlan(sym) {
    if (!S.plans || !S.plans[sym]) return false;
    delete S.plans[sym];
    savePlans();
    if (sym === S.sym) drawPlanLines();
    if (typeof global.PlanHistoryV3?.log === 'function') {
      try { global.PlanHistoryV3.log(sym, 'deleted', null, null); } catch {}
    }
    return true;
  }

  // ── Chart price line rendering ──────────────────────────────
  function clearPlanLines() {
    if (!S.chart || !S.chartSeries) return;
    for (const pl of (S.planPriceLines || [])) {
      try { S.chartSeries.removePriceLine(pl); } catch {}
    }
    S.planPriceLines = [];
  }

  function drawPlanLines() {
    clearPlanLines();
    if (!S.chart || !S.chartSeries) return;
    const p = getPlan(S.sym);
    if (!p) return;
    const LS = (typeof LightweightCharts !== 'undefined') ? LightweightCharts.LineStyle : { Dashed: 2, Dotted: 1, Solid: 0 };
    const lines = [];
    if (Number.isFinite(p.buyZoneLow))  lines.push({ price: p.buyZoneLow,  color: '#10B981', title: `買區下 ${p.buyZoneLow}`,    style: LS.Solid });
    if (Number.isFinite(p.buyZoneHigh)) lines.push({ price: p.buyZoneHigh, color: '#10B981', title: `買區上 ${p.buyZoneHigh}`,   style: LS.Solid });
    if (Number.isFinite(p.resistance))  lines.push({ price: p.resistance,  color: '#FBBF24', title: `壓力 ${p.resistance}`,      style: LS.Dashed });
    if (Number.isFinite(p.stopLoss))    lines.push({ price: p.stopLoss,    color: '#F97316', title: `減碼 ${p.stopLoss}`,        style: LS.Dashed });
    if (Number.isFinite(p.weakBreak))   lines.push({ price: p.weakBreak,   color: '#EF4444', title: `出場 ${p.weakBreak}`,       style: LS.Solid });
    for (const ln of lines) {
      try {
        const pl = S.chartSeries.createPriceLine({
          price: ln.price,
          color: ln.color,
          lineWidth: 2,
          lineStyle: ln.style,
          axisLabelVisible: true,
          title: ln.title,
        });
        S.planPriceLines.push(pl);
      } catch (e) { console.warn('[v3-plan] line draw failed:', e); }
    }
  }

  // ── PLAN tab UI ─────────────────────────────────────────────
  function renderPlan() {
    try { return _renderPlanInner(); }
    catch (e) {
      console.error('[v3-plan] renderPlan threw:', e);
      return `<div style="padding:20px;color:#FCA5A5;font-size:11px;">
        <b>PLAN 渲染錯誤：</b>${String(e.message || e).replace(/[<>]/g, '')}<br>
        <span style="color:#9CA3AF;font-size:10px;">F12 Console 看完整 stack；或執行 <code>localStorage.removeItem('stock_terminal_plans_v3')</code> 重置計畫</span>
      </div>`;
    }
  }
  function _renderPlanInner() {
    if (!S.plans) S.plans = {};
    const keys = Object.keys(S.plans).sort((a, b) => (S.plans[b].updatedAt || 0) - (S.plans[a].updatedAt || 0));
    const editing = S.planEditing;

    const btnStyle = 'padding:3px 6px;font-size:10px;border-radius:4px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;';
    const header = `
      <div class="stat-sect" style="padding-bottom:4px;">下周執行計畫 (${keys.length} 檔)</div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;padding:0 6px 6px;">
        <button id="plan-add-current" class="rtab" title="加入當前股票"
                style="${btnStyle}background:#1F2937;border:1px solid #374151;color:#E5E7EB;">＋ 加入</button>
        <button id="plan-import-pdf" class="rtab" title="從 PDF 匯入計畫"
                style="${btnStyle}background:#7C2D12;border:1px solid #C2410C;color:#FED7AA;">📄 匯入</button>
        <button id="plan-export-pdf" class="rtab" title="匯出 PDF 報告"
                style="${btnStyle}background:#3730A3;border:1px solid #4F46E5;color:#C7D2FE;">📥 出 PDF</button>
        <button id="plan-capital" class="rtab" title="設定可用資金"
                style="${btnStyle}background:#064E3B;border:1px solid #047857;color:#A7F3D0;">💰 資金</button>
        <button id="plan-enable-alert" class="rtab" title="啟用價位穿越警報"
                style="${btnStyle}background:#1E3A8A;border:1px solid #2563EB;color:#BFDBFE;">🔔 警報</button>
        <button id="plan-history-all" class="rtab" title="查看事件歷史"
                style="${btnStyle}background:#374151;border:1px solid #4B5563;color:#D1D5DB;">📜 歷史</button>
        <button id="plan-clear-all" class="rtab" title="清空所有計畫"
                style="${btnStyle}background:#7F1D1D;border:1px solid #B91C1C;color:#FECACA;">🗑 清空</button>
      </div>
      <input type="file" id="plan-pdf-file" accept="application/pdf" style="display:none;">
      <div style="font-size:10px;color:#9CA3AF;padding:4px 6px 8px;line-height:1.5;display:flex;gap:8px;flex-wrap:wrap;">
        <span><span style="color:#10B981;">━</span> 買區</span>
        <span><span style="color:#FBBF24;">┄</span> 壓力</span>
        <span><span style="color:#F97316;">┄</span> 減碼</span>
        <span><span style="color:#EF4444;">━</span> 出場</span>
      </div>
    `;

    if (keys.length === 0) {
      return header + `
        <div style="text-align:center;padding:32px 12px;color:#6B7280;font-size:12px;line-height:1.8;">
          目前沒有計畫。<br>
          可點上方 <b style="color:#E5E7EB;">＋ 加入 ${S.sym || '當前'}</b> 手動輸入<br>
          或點 <b style="color:#FED7AA;">📄 匯入 PDF</b> 拖入週計畫文件自動解析<br>
          <div style="margin-top:14px;font-size:10px;color:#4B5563;">支援格式：含「下周執行總表」表格的 PDF</div>
        </div>`;
    }

    const cards = keys.map(sym => renderPlanCard(sym, sym === editing)).join('');
    const peg = (typeof global.renderPegSection === 'function') ? global.renderPegSection() : '';
    return header + cards + peg;
  }

  function renderPlanCard(sym, isEditing) {
    const p = S.plans[sym];
    if (!p) return '';
    const cur = (sym === S.sym && S.data?.candles?.length)
      ? S.data.candles[S.data.candles.length - 1].close
      : null;
    const status = computeStatus(p, cur);

    if (isEditing) return renderPlanEditForm(sym);

    const roleColor = {
      '主倉':   '#10B981',
      '動能倉': '#F59E0B',
      '攻擊倉': '#EF4444',
      '觀察倉': '#6B7280',
    }[p.role] || '#6B7280';

    return `
      <div class="plan-card" data-sym="${sym}" style="margin:6px 6px 10px;border:1px solid #374151;border-radius:6px;background:#0F172A;padding:8px 10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;">
          <span style="display:flex;align-items:center;gap:6px;">
            <span style="font-weight:700;color:#F3F4F6;font-size:13px;cursor:pointer;text-decoration:underline;" data-act="goto" data-sym="${sym}">${sym}</span>
            <span style="background:${roleColor};color:#0F172A;font-size:10px;padding:1px 5px;border-radius:3px;font-weight:700;">${p.role}</span>
            <span style="font-size:10px;color:#9CA3AF;">${p.mkt}</span>
          </span>
          <span style="display:flex;gap:4px;">
            <button data-act="history" data-sym="${sym}" title="事件歷史" style="background:#1F2937;border:1px solid #374151;color:#9CA3AF;font-size:10px;padding:2px 7px;border-radius:3px;cursor:pointer;">📜</button>
            <button data-act="edit" data-sym="${sym}" title="編輯" style="background:#1F2937;border:1px solid #374151;color:#9CA3AF;font-size:10px;padding:2px 7px;border-radius:3px;cursor:pointer;">✎</button>
            <button data-act="delete" data-sym="${sym}" title="刪除" style="background:#1F2937;border:1px solid #7F1D1D;color:#FCA5A5;font-size:10px;padding:2px 7px;border-radius:3px;cursor:pointer;">✕</button>
          </span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:4px 8px;font-size:11px;color:#D1D5DB;">
          ${rowKV('買區', fmtZone(p.buyZoneLow, p.buyZoneHigh), '#10B981')}
          ${rowKV('壓力', fmtNum(p.resistance), '#FBBF24')}
          ${rowKV('減碼', fmtNum(p.stopLoss),   '#F97316')}
          ${rowKV('出場', fmtNum(p.weakBreak),  '#EF4444')}
        </div>
        ${cur != null ? `
          <div style="margin-top:6px;padding-top:6px;border-top:1px dashed #374151;font-size:10px;color:#9CA3AF;display:flex;justify-content:space-between;">
            <span>現價 <b style="color:#F3F4F6;font-size:11px;">${cur.toFixed(2)}</b></span>
            <span style="color:${status.color};font-weight:600;">${status.label}</span>
          </div>` : ''}
        ${p.longCondition ? `<div style="margin-top:5px;font-size:10px;color:#9CA3AF;line-height:1.5;">📋 ${escapeHtml(p.longCondition)}</div>` : ''}
        ${p.outlook ? `<div style="margin-top:3px;font-size:10px;color:#6B7280;line-height:1.5;">${escapeHtml(p.outlook)}</div>` : ''}
        ${(typeof global.PlanPositionV3?.renderSuggestionRow === 'function') ? global.PlanPositionV3.renderSuggestionRow(sym) : ''}
      </div>`;
  }

  function rowKV(k, v, color) {
    return `<span style="display:flex;justify-content:space-between;"><span style="color:#6B7280;">${k}</span><span style="color:${color};font-weight:600;">${v}</span></span>`;
  }
  function fmtNum(n) { return (n != null && Number.isFinite(n)) ? n.toFixed(2) : '—'; }
  function fmtZone(lo, hi) {
    if (!Number.isFinite(lo) && !Number.isFinite(hi)) return '—';
    if (Number.isFinite(lo) && Number.isFinite(hi)) return `${lo.toFixed(2)} ~ ${hi.toFixed(2)}`;
    return fmtNum(lo) + (Number.isFinite(hi) ? ` ↑` : '');
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function computeStatus(p, cur) {
    if (cur == null || !Number.isFinite(cur)) return { label: '無報價', color: '#6B7280' };
    if (Number.isFinite(p.weakBreak) && cur < p.weakBreak)
      return { label: `⚠ 破出場 ${p.weakBreak}`, color: '#EF4444' };
    if (Number.isFinite(p.stopLoss) && cur < p.stopLoss)
      return { label: `⚠ 破減碼 ${p.stopLoss}`, color: '#F97316' };
    if (Number.isFinite(p.resistance) && cur >= p.resistance)
      return { label: `✓ 過壓力 ${p.resistance}`, color: '#10B981' };
    if (Number.isFinite(p.buyZoneLow) && Number.isFinite(p.buyZoneHigh) && cur >= p.buyZoneLow && cur <= p.buyZoneHigh)
      return { label: `● 在買區`, color: '#10B981' };
    if (Number.isFinite(p.buyZoneHigh) && cur > p.buyZoneHigh)
      return { label: `↑ 高於買區`, color: '#9CA3AF' };
    if (Number.isFinite(p.buyZoneLow) && cur < p.buyZoneLow)
      return { label: `↓ 低於買區`, color: '#9CA3AF' };
    return { label: '觀察中', color: '#9CA3AF' };
  }

  function renderPlanEditForm(sym) {
    const p = S.plans[sym] || { sym, mkt: 'TW', role: '觀察倉' };
    const roleOpts = ROLES.map(r => `<option value="${r}" ${r === p.role ? 'selected' : ''}>${r}</option>`).join('');
    return `
      <div class="plan-edit" data-sym="${sym}" style="margin:6px 6px 10px;border:2px solid #3B82F6;border-radius:6px;background:#0F172A;padding:10px 10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-weight:700;color:#60A5FA;font-size:13px;">編輯 ${sym}</span>
          <span style="display:flex;gap:5px;">
            <button data-act="save" data-sym="${sym}" style="background:#065F46;border:1px solid #10B981;color:#D1FAE5;font-size:10px;padding:3px 10px;border-radius:3px;cursor:pointer;font-weight:600;">儲存</button>
            <button data-act="cancel" data-sym="${sym}" style="background:#1F2937;border:1px solid #374151;color:#9CA3AF;font-size:10px;padding:3px 10px;border-radius:3px;cursor:pointer;">取消</button>
          </span>
        </div>
        <div style="display:grid;grid-template-columns:80px 1fr;gap:5px 8px;font-size:11px;align-items:center;">
          <span style="color:#9CA3AF;">定位</span>
          <select data-fld="role" style="background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:3px 5px;border-radius:3px;font-size:11px;">${roleOpts}</select>
          <span style="color:#10B981;">買區 下~上</span>
          <span style="display:flex;gap:4px;">
            <input data-fld="buyZoneLow" type="number" step="0.01" placeholder="低" value="${p.buyZoneLow ?? ''}" style="flex:1;background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:3px 5px;border-radius:3px;font-size:11px;">
            <span style="color:#6B7280;align-self:center;">~</span>
            <input data-fld="buyZoneHigh" type="number" step="0.01" placeholder="高" value="${p.buyZoneHigh ?? ''}" style="flex:1;background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:3px 5px;border-radius:3px;font-size:11px;">
          </span>
          <span style="color:#FBBF24;">壓力</span>
          <input data-fld="resistance" type="number" step="0.01" placeholder="突破即追" value="${p.resistance ?? ''}" style="background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:3px 5px;border-radius:3px;font-size:11px;">
          <span style="color:#F97316;">減碼</span>
          <input data-fld="stopLoss" type="number" step="0.01" placeholder="跌破減倉" value="${p.stopLoss ?? ''}" style="background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:3px 5px;border-radius:3px;font-size:11px;">
          <span style="color:#EF4444;">出場</span>
          <input data-fld="weakBreak" type="number" step="0.01" placeholder="跌破出場" value="${p.weakBreak ?? ''}" style="background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:3px 5px;border-radius:3px;font-size:11px;">
          <span style="color:#9CA3AF;">條件</span>
          <input data-fld="longCondition" type="text" placeholder="例: 站穩 283 放量過 290" value="${escapeHtml(p.longCondition || '')}" style="background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:3px 5px;border-radius:3px;font-size:11px;">
          <span style="color:#9CA3AF;">展望</span>
          <textarea data-fld="outlook" rows="2" placeholder="基本面/題材" style="background:#1F2937;border:1px solid #374151;color:#E5E7EB;padding:3px 5px;border-radius:3px;font-size:11px;resize:vertical;font-family:inherit;">${escapeHtml(p.outlook || '')}</textarea>
        </div>
      </div>`;
  }

  // ── Event wiring ────────────────────────────────────────────
  function attachPlan() {
    try { return _attachPlanInner(); }
    catch (e) { console.error('[v3-plan] attachPlan threw:', e); }
  }
  function _attachPlanInner() {
    const root = document.getElementById('rpanel') || document;

    const addBtn = root.querySelector('#plan-add-current');
    if (addBtn) addBtn.onclick = () => {
      if (!S.sym) { alert('尚未選擇股票'); return; }
      if (!S.plans[S.sym]) setPlan(S.sym, S.mkt, {});
      S.planEditing = S.sym;
      if (typeof renderRpanel === 'function') renderRpanel();
    };

    const importBtn = root.querySelector('#plan-import-pdf');
    const fileInput = root.querySelector('#plan-pdf-file');
    if (importBtn && fileInput) {
      importBtn.onclick = () => fileInput.click();
      fileInput.onchange = async (e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        if (typeof global.PlanPdfImport?.parseFile === 'function') {
          try {
            const result = await global.PlanPdfImport.parseFile(f);
            if (result?.imported > 0) {
              alert(`成功匯入 ${result.imported} 檔計畫\n${result.symbols.join(', ')}`);
              if (typeof renderRpanel === 'function') renderRpanel();
              drawPlanLines();
            } else {
              alert('無法從 PDF 解析出計畫資料\n請確認 PDF 含有「下周執行總表」格式表格');
            }
          } catch (err) {
            console.error('[v3-plan] PDF import error:', err);
            alert('PDF 解析失敗：' + err.message);
          }
        } else {
          alert('PDF 解析模組尚未載入');
        }
        e.target.value = '';
      };
    }

    const alertBtn = root.querySelector('#plan-enable-alert');
    if (alertBtn) {
      // Update button style based on current state
      const updateAlertBtn = () => {
        const st = (typeof global.AlertV3?.status === 'function') ? global.AlertV3.status() : null;
        if (!st) { alertBtn.textContent = '🔔 警報'; return; }
        const perm = st.notifPermission;
        if (perm === 'granted') {
          // 短化：「🔔 監控 3·今 1」(fits within button width)
          alertBtn.textContent = `🔔 ${st.targets}·${st.firedToday}`;
          alertBtn.title = `警報啟用中：監控 ${st.targets} 檔，今天已觸發 ${st.firedToday} 次`;
          alertBtn.style.background = '#065F46';
          alertBtn.style.borderColor = '#10B981';
          alertBtn.style.color = '#D1FAE5';
        } else if (perm === 'denied') {
          alertBtn.textContent = '🔕 封鎖';
          alertBtn.title = '警報已被瀏覽器封鎖 — 請到網站設定允許通知';
          alertBtn.style.background = '#7F1D1D';
          alertBtn.style.borderColor = '#B91C1C';
          alertBtn.style.color = '#FECACA';
        } else {
          alertBtn.textContent = '🔔 警報';
          alertBtn.title = '啟用價位穿越警報';
        }
      };
      updateAlertBtn();
      alertBtn.onclick = async () => {
        if (typeof global.AlertV3?.requestPermission === 'function') {
          const result = await global.AlertV3.requestPermission();
          if (result === 'granted') {
            new Notification('Stock Terminal v3.0', { body: '價位警報已啟用，將監控 ' + Object.keys(S.plans||{}).length + ' 檔計畫' });
          }
          updateAlertBtn();
        }
      };
    }

    const capitalBtn = root.querySelector('#plan-capital');
    if (capitalBtn) capitalBtn.onclick = () => {
      if (typeof global.PlanPositionV3?.openCapitalModal === 'function') {
        global.PlanPositionV3.openCapitalModal();
      }
    };

    const exportBtn = root.querySelector('#plan-export-pdf');
    if (exportBtn) exportBtn.onclick = () => {
      if (typeof global.PlanPdfExport?.generate === 'function') {
        global.PlanPdfExport.generate();
      } else {
        alert('PDF 匯出模組未載入');
      }
    };

    const histBtn = root.querySelector('#plan-history-all');
    if (histBtn) histBtn.onclick = () => {
      if (typeof global.PlanHistoryV3?.open === 'function') {
        global.PlanHistoryV3.open(null);   // null = all
      }
    };

    const clearBtn = root.querySelector('#plan-clear-all');
    if (clearBtn) clearBtn.onclick = () => {
      if (Object.keys(S.plans).length === 0) return;
      if (!confirm(`確定要清空全部 ${Object.keys(S.plans).length} 檔計畫？`)) return;
      S.plans = {};
      savePlans();
      drawPlanLines();
      if (typeof renderRpanel === 'function') renderRpanel();
    };

    root.querySelectorAll('[data-act]').forEach(el => {
      const act = el.dataset.act;
      const sym = el.dataset.sym;
      if (act === 'goto') {
        el.onclick = () => {
          if (typeof loadSym === 'function') {
            const mkt = S.plans[sym]?.mkt || 'TW';
            S.mkt = mkt;
            loadSym(sym);
          }
        };
      } else if (act === 'history') {
        el.onclick = () => {
          if (typeof global.PlanHistoryV3?.open === 'function') {
            global.PlanHistoryV3.open(sym);
          }
        };
      } else if (act === 'edit') {
        el.onclick = () => {
          S.planEditing = sym;
          if (typeof renderRpanel === 'function') renderRpanel();
        };
      } else if (act === 'delete') {
        el.onclick = () => {
          if (!confirm(`刪除 ${sym} 的計畫？`)) return;
          deletePlan(sym);
          if (typeof renderRpanel === 'function') renderRpanel();
        };
      } else if (act === 'save') {
        el.onclick = () => {
          const form = root.querySelector(`.plan-edit[data-sym="${sym}"]`);
          if (!form) return;
          const fields = {};
          form.querySelectorAll('[data-fld]').forEach(inp => {
            fields[inp.dataset.fld] = inp.value;
          });
          setPlan(sym, S.plans[sym]?.mkt || S.mkt, fields);
          S.planEditing = null;
          if (typeof renderRpanel === 'function') renderRpanel();
        };
      } else if (act === 'apply-position') {
        el.onclick = () => {
          if (typeof global.PlanPositionV3?.apply === 'function') {
            global.PlanPositionV3.apply(sym);
          }
        };
      } else if (act === 'cancel') {
        el.onclick = () => {
          // If this is a brand-new empty plan, drop it
          const p = S.plans[sym];
          if (p && !Number.isFinite(p.buyZoneLow) && !Number.isFinite(p.buyZoneHigh) &&
              !Number.isFinite(p.resistance) && !Number.isFinite(p.stopLoss) && !Number.isFinite(p.weakBreak) &&
              !p.longCondition && !p.outlook) {
            deletePlan(sym);
          }
          S.planEditing = null;
          if (typeof renderRpanel === 'function') renderRpanel();
        };
      }
    });

    // Attach PEG comparison section if available
    if (typeof global.attachPegSection === 'function') {
      try { global.attachPegSection(); } catch (e) { console.warn('[v3-plan] peg attach failed:', e); }
    }
  }

  // ── Hooks ──────────────────────────────────────────────────
  // Redraw plan price lines after every symbol load
  window.addEventListener('symLoaded', () => {
    setTimeout(drawPlanLines, 200);    // give chart time to render
  });

  // ── Boot ───────────────────────────────────────────────────
  (function boot() {
    if (typeof S === 'undefined' || !document.body) {
      return setTimeout(boot, 100);
    }
    bootPlans();
  })();

  // ── Expose ─────────────────────────────────────────────────
  global.renderPlan      = renderPlan;
  global.attachPlan      = attachPlan;
  global.drawPlanLines   = drawPlanLines;
  global.getPlan         = getPlan;
  global.setPlan         = setPlan;
  global.deletePlan      = deletePlan;
  global.PlanV3 = {
    getAll: () => S.plans || {},
    set: setPlan,
    get: getPlan,
    delete: deletePlan,
    redraw: drawPlanLines,
    save: savePlans,
  };

  console.log('[v3-plan] module loaded — exposes renderPlan/attachPlan/PlanV3');

})(typeof window !== 'undefined' ? window : globalThis);

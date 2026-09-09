/* 估值承接研究：官方觀察、使用者假設及分批情境各自保留來源。 */
(function () {
  'use strict';
  const KEY = 'st.valuation-research.v1';
  let dialog, active, priorFocus, controller, generation = 0;
  const $ = id => document.getElementById(id);
  const core = () => window.ValuationResearch;
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g,
    char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const fmt = (value, places = 2) => core().number(value) == null ? '未提供' : Number(value).toLocaleString('zh-TW', { maximumFractionDigits: places });
  const percent = value => core().number(value) == null ? '未提供' : fmt(value) + '%';
  const labels = { exclude_ip: '另案估值，排除於本次範圍', pe_unknown: '官方本益比未提供或非正值', pe_above: '超出本次本益比上限', in_scope: '符合本次本益比範圍' };
  const states = { need_assumption: '待設定估值假設', below_entry: '已到承接價以下', in_range: '尚未達承接價', above_range: '高於假設估值上緣' };

  function readStore() {
    try {
      const data = JSON.parse(localStorage.getItem(KEY) || '{}');
      return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
    } catch (_) { return {}; }
  }
  function style() {
    if ($('vr-style')) return;
    const node = document.createElement('style'); node.id = 'vr-style';
    node.textContent = `
      #vr-dialog{width:min(1080px,94vw);max-height:92vh;margin:auto;inset:0;box-sizing:border-box;padding:0;border:1px solid #475569;border-radius:12px;background:#101827;color:#e2e8f0;font:14px/1.55 system-ui,sans-serif;overflow:auto}
      #vr-dialog::backdrop{background:rgba(2,6,23,.78)}
      #vr-dialog *{box-sizing:border-box}#vr-dialog h2{font-size:22px;margin:0}#vr-dialog h3{font-size:16px;margin:0 0 10px;color:#fbbf24}
      #vr-dialog .vr-head{position:sticky;top:0;z-index:2;background:#101827;border-bottom:1px solid #334155;padding:16px 20px;display:flex;justify-content:space-between;align-items:center;gap:12px}
      #vr-dialog .vr-content{padding:18px 20px}#vr-dialog .vr-muted{color:#aebcce;font-size:12px}#vr-dialog .vr-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
      #vr-dialog section{min-width:0;background:#152033;border:1px solid #334155;border-radius:8px;padding:14px;margin-bottom:14px}
      #vr-dialog .vr-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}#vr-dialog label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:#cbd5e1;min-width:0}
      #vr-dialog input,#vr-dialog select,#vr-dialog textarea{font:inherit;color:#f1f5f9;background:#0b1220;border:1px solid #526179;border-radius:5px;padding:8px;width:100%;min-width:0}#vr-dialog textarea{resize:vertical}
      #vr-dialog .vr-wide{grid-column:1/-1}#vr-dialog button{font:inherit;font-size:13px;min-height:36px;border:1px solid #526179;background:#23314a;color:#f1f5f9;border-radius:5px;padding:6px 12px;cursor:pointer}
      #vr-dialog button:focus-visible,#vr-dialog input:focus-visible,#vr-dialog select:focus-visible,#vr-dialog textarea:focus-visible{outline:2px solid #fbbf24;outline-offset:2px}#vr-dialog .vr-primary{background:#fbbf24;color:#101827;font-weight:700;border-color:#fbbf24}
      #vr-dialog .vr-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}#vr-dialog .vr-facts{display:grid;grid-template-columns:minmax(100px,1fr) 1.5fr;gap:6px 12px;margin:0}#vr-dialog dt{color:#aebcce}#vr-dialog dd{margin:0;overflow-wrap:anywhere}
      #vr-dialog .vr-status{padding:10px 12px;border-left:3px solid #fbbf24;background:#202c3e;margin-bottom:12px}#vr-dialog .vr-error{color:#fda4af}#vr-dialog .vr-tranche{display:grid;grid-template-columns:1fr 1fr 40px;align-items:end;gap:8px;margin-bottom:8px}
      #vr-dialog .vr-tranche button{padding:4px}#vr-dialog details>summary{cursor:pointer;color:#cbd5e1;margin-bottom:10px}#vr-dialog ul{padding-left:20px;margin:6px 0}#vr-dialog .vr-history{border-top:1px solid #334155;padding:8px 0}#vr-dialog .vr-kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:10px 0}#vr-dialog .vr-kpi{padding:10px;background:#0b1220;border-radius:6px;overflow-wrap:anywhere}#vr-dialog .vr-kpi strong{display:block;font-size:20px;color:#f8fafc}
      @media(max-width:700px){#vr-dialog{width:96vw;max-height:94vh}#vr-dialog .vr-grid{grid-template-columns:1fr;gap:0}#vr-dialog .vr-head,#vr-dialog .vr-content{padding:12px}#vr-dialog h2{font-size:18px}#vr-dialog .vr-fields{gap:8px}#vr-dialog .vr-facts{grid-template-columns:1fr 1.35fr}#vr-dialog section{padding:12px}}
    `;
    document.head.appendChild(node);
  }
  function field(id, label, value, attrs = '') {
    return '<label>' + label + '<input id="vr-' + id + '" value="' + esc(value) + '" ' + attrs + '></label>';
  }
  function defaults(symbol) {
    return { category: core().classify(symbol).category, eps: '', epsPeriod: '', reason: '', peLow: 20, peHigh: 30,
      entryPrice: '', exitPrice: '', budget: '', tranches: [], buyFeePct: 0.1425, sellFeePct: 0.1425, sellTaxPct: 0.3, minFee: 20 };
  }
  function renderForm(profile) {
    const numeric = 'type="number" min="0" step="any"';
    $('vr-form').innerHTML = '<h3>估值假設</h3><p class="vr-muted">EPS 與倍數由你依獲利品質、循環位置設定。20～30 倍是可修改的起始值，沒有套用所有產業的合理倍數。</p>' +
      '<div class="vr-fields"><label>研究分類<select id="vr-category"><option value="general">一般獲利企業</option><option value="ai_cycle">AI 供應鏈／景氣循環</option><option value="ip">IP／另案估值</option></select></label>' +
      field('eps', '可持續每股盈餘假設（元）', profile.eps, numeric) +
      field('epsPeriod', '假設適用期間', profile.epsPeriod, 'type="text" maxlength="80" placeholder="例如：未來一個完整年度"') +
      '<label>估值理由<textarea id="vr-reason" rows="2" maxlength="1500" placeholder="記錄獲利依據、循環風險與失效條件">' + esc(profile.reason) + '</textarea></label>' +
      field('peLow', '假設倍數下緣', profile.peLow, numeric) + field('peHigh', '假設倍數上緣', profile.peHigh, numeric) +
      field('entryPrice', '承接價（空白採估值下緣）', profile.entryPrice, numeric) + field('exitPrice', '退出價（空白採估值上緣）', profile.exitPrice, numeric) +
      '</div><div class="vr-actions"><button type="button" class="vr-primary" id="vr-save">儲存假設與觀察</button><button type="button" id="vr-discard">還原已儲存假設</button><span class="vr-muted" id="vr-save-state"></span></div><div id="vr-errors" role="status" class="vr-error"></div>';
    $('vr-category').value = profile.category;
    $('vr-scenario').innerHTML = '<h3>分批承接情境</h3><p class="vr-muted">這是研究試算，未寫入持倉。先決定估值與承接價，再填各批價格、股數；每跌 10% 只是一種間距。</p>' +
      field('budget', '總投入上限（元，含買進費用）', profile.budget, numeric) +
      '<div id="vr-tranches" style="margin-top:10px"></div><div class="vr-actions"><button type="button" id="vr-add">新增一批</button><button type="button" id="vr-next">依前批下跌 10% 新增價格</button></div>' +
      '<details style="margin-top:12px"><summary>交易成本假設</summary><p class="vr-muted">預設費率僅供試算，請依券商與交易類型修改。最低費用以每批計算。</p><div class="vr-fields">' +
      field('buyFeePct', '買進手續費（%）', profile.buyFeePct, numeric) + field('sellFeePct', '賣出手續費（%）', profile.sellFeePct, numeric) +
      field('sellTaxPct', '賣出交易稅（%）', profile.sellTaxPct, numeric) + field('minFee', '每筆最低手續費（元）', profile.minFee, numeric) +
      '</div></details><div id="vr-position"></div>';
    (Array.isArray(profile.tranches) && profile.tranches.length ? profile.tranches : [{ price: '', shares: '' }]).forEach(addTranche);
    $('vr-save').onclick = save;
    $('vr-discard').onclick = () => {
      try { localStorage.removeItem(KEY + '.draft.' + active.symbol); } catch (_) {}
      renderForm({ ...defaults(active.symbol), ...(active.saved.profile || {}) });
      active.dirty = false; $('vr-save-state').textContent = active.saved.profile ? '已還原儲存的假設' : '已還原空白假設'; recalculate();
    };
    $('vr-add').onclick = () => { addTranche({ price: '', shares: '' }); changed(); };
    $('vr-next').onclick = () => {
      const rows = readTranches();
      const last = rows.length ? core().number(rows[rows.length - 1].price) : null;
      const evaluation = evaluate();
      const base = last > 0 ? last : evaluation.entry;
      if (!(base > 0)) { $('vr-errors').textContent = '請先設定承接價或上一批價格。'; return; }
      const empty = $('vr-tranches').children.length === 1 && !rows.length;
      if (empty) $('vr-tranches').innerHTML = '';
      addTranche({ price: empty ? base : Math.round(base * 0.9 * 10000) / 10000, shares: '' }); changed();
    };
    ['vr-form', 'vr-scenario'].forEach(id => { $(id).oninput = changed; });
  }
  function addTranche(row) {
    const line = document.createElement('div'); line.className = 'vr-tranche';
    line.innerHTML = '<label>買進價格<input type="number" min="0" step="any" class="vr-price" value="' + esc(row.price) + '"></label>' +
      '<label>股數<input type="number" min="1" step="1" class="vr-shares" value="' + esc(row.shares) + '"></label><button type="button" aria-label="移除這一批">×</button>';
    line.querySelector('button').onclick = () => { line.remove(); changed(); };
    $('vr-tranches').appendChild(line);
  }
  function readTranches() {
    return Array.from($('vr-tranches').children).map(line => ({ price: line.querySelector('.vr-price').value, shares: line.querySelector('.vr-shares').value }))
      .filter(row => row.price !== '' || row.shares !== '');
  }
  function readProfile() {
    const profile = {};
    ['category', 'eps', 'epsPeriod', 'reason', 'peLow', 'peHigh', 'entryPrice', 'exitPrice', 'budget', 'buyFeePct', 'sellFeePct', 'sellTaxPct', 'minFee'].forEach(key => { profile[key] = $('vr-' + key).value.trim(); });
    profile.tranches = readTranches();
    return profile;
  }
  function observation() {
    const row = active.row || {}, research = row.research || {};
    return { symbol: active.symbol, price: row.close, officialPe: row.per, priceAsOf: research.priceAsOf, valuationDate: research.valuationDate };
  }
  function evaluate() { return core().evaluate(observation(), readProfile(), active.settings); }
  function pair(label, value) { return '<dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd>'; }
  function facts() {
    const row = active.row || {}, research = row.research || {};
    $('vr-facts').innerHTML = '<dl class="vr-facts">' +
      pair('收盤價／交易日', fmt(row.close) + '／' + (research.priceAsOf || '未提供')) +
      pair('官方本益比／資料日', fmt(row.per) + ' 倍／' + (research.valuationDate || '未提供')) +
      pair('本益比來源', research.valuationSource || '未提供') +
      pair('月營收年增／期別', percent(row.revYoy) + '／' + (research.revenuePeriod || '未提供')) +
      pair('月增／累計年增', percent(research.revenueMom) + '／' + percent(research.revenueCumYoy)) +
      pair('100 日高點回撤', percent(research.drawdown100)) +
      pair('前 20 日區間', fmt(research.rangeBottom) + ' ～ ' + fmt(research.rangeTop)) +
      pair('區間位置／距上緣', (research.rangePosition || '未提供') + '／' + percent(research.distanceToTopPct)) +
      pair('當日量／前 20 日均量', fmt(research.breakoutVolumeRatio) + ' 倍') +
      pair('投信最近淨買股數', fmt(research.trustLatestShares, 0) + '／' + (research.trustAsOf || '未提供')) +
      pair('投信 5 日淨買股數', fmt(research.trustNet5d, 0) + '（觀測 ' + fmt(research.trustObservedDays, 0) + '/5 日）') + '</dl>' +
      '<p class="vr-muted">營收為最近公告的單一期別，不能單憑一個月判定獲利趨勢。區間位置比較前 20 個交易日，不代表已確認的整理型態。</p>' +
      (Array.isArray(research.missing) && research.missing.length ? '<p class="vr-muted">資料限制：' + research.missing.map(esc).join('；') + '</p>' : '');
  }
  function recalculate() {
    const result = evaluate();
    $('vr-verdict').innerHTML = '<div class="vr-status"><strong>' + esc(labels[result.scope] || result.scope) + '</strong><br>' +
      esc(states[result.valuationStatus] || result.valuationStatus) + ' · 篩選上限 ' + esc(active.settings.peMax) + ' 倍</div>' +
      '<div class="vr-kpis"><div class="vr-kpi"><span class="vr-muted">假設估值區間</span><strong>' + fmt(result.low) + ' ～ ' + fmt(result.high) + '</strong></div>' +
      '<div class="vr-kpi"><span class="vr-muted">距承接價</span><strong>' + percent(result.entryGapPct) + '</strong></div></div>' +
      '<p class="vr-muted">承接價 ' + fmt(result.entry) + ' · 退出價 ' + fmt(result.exit) + ' · 依假設 EPS 計算的本益比 ' + fmt(result.hypothesisPe) + ' 倍。此值與官方本益比分開。</p>';
    const position = result.position || {};
    $('vr-position').innerHTML = '<div class="vr-kpis"><div class="vr-kpi"><span class="vr-muted">累計成本／股數</span><strong>' + fmt(position.totalCost) + '／' + fmt(position.shares, 0) + '</strong></div>' +
      '<div class="vr-kpi"><span class="vr-muted">含賣出成本損益兩平價</span><strong>' + fmt(position.breakEven) + '</strong></div></div><dl class="vr-facts">' +
      pair('含買費均價', fmt(position.averageCost)) + pair('剩餘可投入額', fmt(position.remainingBudget)) +
      pair('以目前價格退出損益', fmt(position.currentPnl) + '（' + percent(position.currentPnlPct) + '）') +
      pair('以假設退出價退出損益', fmt(position.exitPnl) + '（' + percent(position.exitPnlPct) + '）') + '</dl>';
    $('vr-errors').textContent = (result.errors || []).join('；');
    return result;
  }
  function changed() {
    active.dirty = true; $('vr-save-state').textContent = '草稿已保留，尚未儲存為假設'; recalculate();
    try { localStorage.setItem(KEY + '.draft.' + active.symbol, JSON.stringify({ profile: readProfile(), baseRevision: active.saved.revision || null })); }
    catch (_) { $('vr-save-state').textContent = '草稿儲存失敗，請保留本頁輸入。'; }
  }
  function renderHistory() {
    const saved = active.saved || {};
    const revisions = Array.isArray(saved.profiles) ? saved.profiles : [];
    const snapshots = Array.isArray(saved.snapshots) ? saved.snapshots : [];
    $('vr-history').innerHTML = '<h3>假設修訂與狀態紀錄</h3><p class="vr-muted">僅記錄你儲存或重新整理時的觀察。假設修改會重新起算狀態，避免把改價誤認為市場變化。</p>' +
      (revisions.length ? revisions.slice(-5).reverse().map(item => '<div class="vr-history"><strong>' + esc(item.at) + '</strong>　EPS 假設 ' + fmt(item.eps) +
        ' · 倍數 ' + fmt(item.peLow) + '～' + fmt(item.peHigh) + '<br><span class="vr-muted">' + esc(item.period || '') + ' · ' + esc(item.reason || '') + '</span></div>').join('') : '<p class="vr-muted">尚無已儲存的假設。</p>') +
      (snapshots.length ? '<details><summary>最近的觀察與變化</summary>' + snapshots.slice(-10).reverse().map(item => '<div class="vr-history">' + esc(item.priceAsOf || '日期未提供') + ' · ' +
        esc((item.events || []).join('；') || '狀態維持') + '<br><span class="vr-muted">收盤 ' + fmt(item.price) + ' · ' + esc(states[item.priceState] || item.priceState) + '</span></div>').join('') + '</details>' : '');
  }
  function appendSnapshot(saved, result) {
    const obs = observation();
    const validDay = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
      Number.isFinite(new Date(value + 'T00:00:00Z').getTime()) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
    if (!validDay(obs.priceAsOf) || !(core().number(obs.price) > 0)) return;
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei' }).format(new Date());
    if (obs.priceAsOf > today) return;
    if (obs.valuationDate && (!validDay(obs.valuationDate) || obs.valuationDate > today)) return;
    const snapshots = Array.isArray(saved.snapshots) ? saved.snapshots.slice() : [];
    const current = { ...obs, profileRevision: saved.revision + ':' + active.settings.peMax + ':' + active.settings.excludeIp, scope: result.scope, priceState: result.valuationStatus };
    const previous = snapshots[snapshots.length - 1];
    if (previous && previous.priceAsOf > current.priceAsOf) return;
    if (previous && previous.valuationDate && current.valuationDate && previous.valuationDate > current.valuationDate) return;
    if (previous && previous.profileRevision === current.profileRevision && previous.priceAsOf === current.priceAsOf && previous.price === current.price && previous.scope === current.scope && previous.priceState === current.priceState) return;
    current.events = core().compareSnapshot(previous, current);
    snapshots.push(current); saved.snapshots = snapshots.slice(-40);
  }
  function persist(saved) {
    try {
      const store = readStore(), latest = store[active.symbol];
      if ((latest && latest.revision || null) !== (active.saved && active.saved.revision || null)) {
        $('vr-save-state').textContent = '另一分頁已更新此股票假設；請重新開啟研究視窗再儲存。'; return false;
      }
      store[active.symbol] = saved; localStorage.setItem(KEY, JSON.stringify(store)); active.saved = saved; return true;
    } catch (_) { $('vr-save-state').textContent = '瀏覽器儲存失敗，請保留本頁輸入後再試。'; return false; }
  }
  function save() {
    const result = recalculate(), profile = readProfile();
    if (result.errors.length || !(core().number(profile.eps) > 0) || !profile.epsPeriod || !profile.reason) {
      $('vr-errors').textContent = result.errors.join('；') || '請填正值的可持續 EPS、適用期間與估值理由。'; return;
    }
    const saved = { ...(active.saved || {}) };
    const different = JSON.stringify(saved.profile) !== JSON.stringify(profile);
    if (different) {
      saved.revision = String(Date.now()); saved.profile = profile;
      saved.profiles = (Array.isArray(saved.profiles) ? saved.profiles : []).concat({ at: new Date().toLocaleString('zh-TW', { timeZone: 'Asia/Taipei' }), eps: profile.eps, peLow: profile.peLow, peHigh: profile.peHigh, period: profile.epsPeriod, reason: profile.reason }).slice(-20);
    }
    appendSnapshot(saved, result);
    if (persist(saved)) {
      active.dirty = false; $('vr-save-state').textContent = '已儲存在此瀏覽器'; renderHistory();
      try { localStorage.removeItem(KEY + '.draft.' + active.symbol); } catch (_) {}
    }
  }
  async function refresh() {
    const serial = ++generation;
    if (controller) controller.abort(); controller = new AbortController();
    $('vr-refresh').disabled = true; $('vr-load-state').textContent = '正在取得最新可用資料…';
    const timer = setTimeout(() => controller && serial === generation && controller.abort(), 45000);
    try {
      const query = '?peMax=' + encodeURIComponent(active.settings.peMax) + '&excludeIp=' + (active.settings.excludeIp ? '1' : '0');
      const response = await fetch((window.SERVER || '') + '/valuation-research/' + encodeURIComponent(active.symbol) + query, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('資料服務回應 ' + response.status);
      const json = await response.json();
      if (serial !== generation) return;
      const row = json.row || json;
      if (String(row.sym) !== active.symbol) throw new Error('資料代號不一致');
      active.row = row; facts(); const result = recalculate();
      $('vr-load-state').textContent = '資料已更新；交易日與公告期別如下。';
      if (!active.dirty && active.saved && active.saved.profile && !result.errors.length) {
        const saved = { ...active.saved }; appendSnapshot(saved, result); persist(saved); renderHistory();
      }
    } catch (error) {
      if (serial !== generation) return;
      $('vr-load-state').textContent = (error.name === 'AbortError' ? '取得資料逾時' : '取得資料失敗：' + error.message) + (active.row ? '；保留先前資料，請核對資料日。' : '；估值假設仍可編輯。');
    } finally { clearTimeout(timer); if (serial === generation) $('vr-refresh').disabled = false; }
  }
  function close() {
    generation++; if (controller) controller.abort();
    if (dialog.open) dialog.close();
    if (priorFocus && priorFocus.isConnected) priorFocus.focus();
  }
  function open(symbol, row, settings) {
    if (!core()) return;
    symbol = String(symbol || '').replace(/\.(TW|TWO)$/i, '');
    if (!/^\d{4}$/.test(symbol)) return;
    style(); priorFocus = document.activeElement;
    if (dialog) close();
    dialog = $('vr-dialog');
    if (!dialog) { dialog = document.createElement('dialog'); dialog.id = 'vr-dialog'; document.body.appendChild(dialog); }
    const stored = readStore()[symbol];
    const saved = stored && typeof stored === 'object' ? stored : {};
    active = { symbol, row: row || null, saved, dirty: false, settings: { peMax: 30, excludeIp: true, ...(settings || {}) } };
    dialog.innerHTML = '<div class="vr-head"><div><h2 id="vr-title">' + esc(symbol) + ' 估值承接研究</h2><div class="vr-muted">先確認獲利基礎，再觀察承接與反彈空間</div></div><button type="button" id="vr-close">關閉</button></div>' +
      '<div class="vr-content"><p class="vr-muted">假設與情境儲存在此瀏覽器。本機與私有網站的瀏覽器儲存各自獨立。</p><div class="vr-grid"><div><section><h3>已公布資料與價格結構</h3><div class="vr-actions"><button type="button" id="vr-refresh">重新整理資料</button><span id="vr-load-state" class="vr-muted" role="status"></span></div><div id="vr-facts" style="margin-top:12px"></div></section><section id="vr-verdict" aria-live="polite"></section><section id="vr-history"></section></div><div><section id="vr-form"></section><section id="vr-scenario"></section></div></div>' +
      '<p class="vr-muted">AI 需求成長需要以可持續獲利驗證，不能單憑題材提高倍數。高本益比、IP 授權模式與一般企業的循環高峰需要分開研究；價格調整的時點與幅度尚未確定。</p></div>';
    dialog.setAttribute('aria-labelledby', 'vr-title');
    $('vr-close').onclick = close;
    dialog.oncancel = event => { event.preventDefault(); close(); };
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(KEY + '.draft.' + symbol) || 'null'); } catch (_) {}
    const restoreDraft = draft && draft.profile && (draft.baseRevision || null) === (saved.revision || null);
    renderForm({ ...defaults(symbol), ...(restoreDraft ? draft.profile : saved.profile || {}) });
    active.dirty = !!restoreDraft;
    $('vr-save-state').textContent = restoreDraft ? '已還原草稿，尚未儲存為假設' : (saved.profile ? '已載入此瀏覽器的假設' : '尚未儲存');
    $('vr-refresh').onclick = refresh; facts(); recalculate(); renderHistory();
    dialog.showModal(); $('vr-close').focus(); refresh();
  }
  window.ValuationResearchUI = { open, close };
})();

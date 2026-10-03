/* 官方日線事件研究：圖表、品質及統計使用同一份資料。 */
(function () {
  'use strict';
  let dialog, controller, priorFocus, data, generation = 0, viewStart = 0, viewSize = 30, eventPage = 0;
  const EVENT_PAGE_SIZE = 50;
  let longController, longData, longParams;
  const $ = id => document.getElementById(id);
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const number = v => typeof v === 'number' && Number.isFinite(v);
  const fmt = (v, n = 2) => number(v) ? v.toLocaleString('zh-TW', { maximumFractionDigits: n }) : '未提供';
  const pct = (v, n = 2) => number(v) ? (v > 0 ? '+' : '') + fmt(v, n) + '%' : '資料不足';
  const label = key => (data.rules.find(r => r.key === key) || {}).label || key;
  const CSS = `
    #ke-dialog{width:min(1180px,96vw);max-height:94vh;max-height:94dvh;margin:auto;inset:0;padding:0;border:1px solid #526179;border-radius:10px;background:#101827;color:#e2e8f0;font:15px/1.65 system-ui,"Microsoft JhengHei UI",sans-serif;overflow:auto}
    #ke-dialog::backdrop{background:rgba(2,6,23,.78)}#ke-dialog *{box-sizing:border-box}#ke-dialog h2{font-size:23px;line-height:1.35;margin:0;font-weight:600}#ke-dialog h3{font-size:18px;margin:0 0 10px;font-weight:600}
    #ke-dialog .ke-head{position:sticky;top:0;z-index:2;background:#101827;border-bottom:1px solid #334155;padding:16px 20px;display:flex;justify-content:space-between;align-items:center;gap:12px}#ke-dialog .ke-content{padding:18px 20px;min-width:0}
    #ke-dialog .ke-muted{color:#b0bfd2;font-size:13px}#ke-dialog section{border-top:1px solid #334155;padding:18px 0}#ke-dialog .ke-fields{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-bottom:16px}#ke-dialog label{display:flex;flex-direction:column;gap:4px;min-width:0}
    #ke-dialog input,#ke-dialog select,#ke-dialog button{font:inherit;color:#f1f5f9;background:#23314a;border:1px solid #64748b;border-radius:5px;padding:7px 11px;min-height:40px}#ke-dialog input{width:164px;background:#0b1220}#ke-dialog button{cursor:pointer}#ke-dialog button:disabled{opacity:.55;cursor:default}#ke-dialog :focus-visible{outline:2px solid #fbd45a;outline-offset:3px}
    #ke-dialog .ke-state{padding:10px 14px;background:#19283b;border-left:3px solid #71ece3;margin-bottom:14px;overflow-wrap:anywhere}#ke-dialog .ke-warn{border-left-color:#fbd45a;background:#302a1c}#ke-dialog .ke-kpis{display:flex;flex-wrap:wrap;gap:12px 36px;margin:14px 0}#ke-dialog .ke-kpis strong{display:block;font-size:24px;font-weight:600;color:#f8fafc}
    #ke-dialog .ke-scroll{max-width:100%;overflow:auto;border:1px solid #334155;border-radius:7px;background:#111d2f}#ke-dialog svg{display:block;width:100%;min-width:740px}#ke-dialog svg text{font-family:inherit;font-size:13px;fill:#b0bfd2}#ke-dialog [data-ke-day]{cursor:pointer}#ke-dialog svg [data-ke-day]:focus{outline:none}#ke-dialog svg [data-ke-day]:focus .ke-hit{stroke:#fbd45a;stroke-width:2}
    #ke-dialog table{border-collapse:collapse;width:100%;font-size:14px;min-width:780px}#ke-dialog th,#ke-dialog td{text-align:right;padding:11px 12px;border-bottom:1px solid #334155;vertical-align:top;white-space:nowrap}#ke-dialog th{color:#b0bfd2;font-weight:500}#ke-dialog td:first-child,#ke-dialog th:first-child{text-align:left}#ke-dialog td.ke-wrap{white-space:normal;min-width:190px;text-align:left}#ke-dialog td small{display:block;color:#b0bfd2}#ke-dialog .ke-pos{color:#ff858c}#ke-dialog .ke-neg{color:#55dcc4}
    #ke-dialog .ke-detail{background:#19283b;padding:14px 16px;margin:12px 0;border-radius:6px;scroll-margin-top:88px}#ke-dialog .ke-detail:empty{display:none}#ke-dialog details{margin-top:14px}#ke-dialog summary{cursor:pointer;color:#dce6f4}#ke-dialog ul{padding-left:22px}#ke-dialog li{margin:7px 0}#ke-dialog .ke-inline{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px}
    #ke-dialog [hidden]{display:none!important}#ke-dialog .ke-nav{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}#ke-dialog .ke-nav label{margin-right:6px}#ke-dialog .ke-timeline{width:100%;margin:10px 0}#ke-dialog .ke-timeline input{width:100%;padding:0;accent-color:#fbd45a}#ke-dialog .ke-scope{overflow-wrap:anywhere}#ke-dialog .ke-selected .ke-hit{stroke:#fbd45a;stroke-width:1.5}
    @media(max-width:600px){#ke-dialog .ke-head,#ke-dialog .ke-content{padding:12px}#ke-dialog h2{font-size:20px}#ke-dialog .ke-kpis{gap:10px 22px}#ke-dialog .ke-fields>label{flex:1 1 130px}#ke-dialog input{width:100%}#ke-dialog section{padding:14px 0}}
  `;
  function cell(v, title) {
    const value = title && title.includes('百分點') && number(v) ? (v > 0 ? '+' : '') + fmt(v) + ' 百分點' : pct(v);
    return '<td class="' + (number(v) && v !== 0 ? v > 0 ? 'ke-pos' : 'ke-neg' : '') + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + value + '</td>';
  }
  function chart(rows) {
    const good = rows.filter(r => [r.open, r.high, r.low, r.close].every(number));
    if (!good.length) return '<p>沒有可繪製的完整日線。請查看下方資料品質。</p>';
    const low = Math.min(...good.map(r => r.low)), high = Math.max(...good.map(r => r.high));
    const span = Math.max(high - low, high * .01), min = low - span * .08, max = high + span * .15;
    const y = v => 32 + (max - v) / (max - min) * 265, step = 900 / rows.length;
    const x = i => 70 + step * (i + .5), width = Math.min(19, step * .64);
    const volMax = Math.max(1, ...good.map(r => number(r.volume) ? r.volume : 0));
    let svg = '<svg viewBox="0 0 1000 440" aria-label="' + esc(rows[0].date + ' 至 ' + rows[rows.length - 1].date) + ' K 線與成交量"><title>紅色為收盤高於開盤，綠色為收盤低於開盤；黃色點為特殊事件</title>';
    for (let i = 0; i < 5; i++) { const v = min + (max - min) * i / 4, yy = y(v); svg += '<line x1="68" x2="970" y1="' + yy + '" y2="' + yy + '" stroke="#334155"/><text x="58" y="' + (yy + 4) + '" text-anchor="end">' + fmt(v, 0) + '</text>'; }
    svg += '<text x="70" y="324">成交量（股）</text>';
    rows.forEach((r, i) => {
      const cx = x(i), color = r.close >= r.open ? '#ff6b72' : '#33d2bd';
      const title = r.date + '｜' + (r.signals.length ? r.signals.map(label).join('、') : r.reason);
      svg += '<g data-ke-day="' + esc(r.date) + '" tabindex="0" role="button" aria-label="' + esc(title) + '"><title>' + esc(title) + '</title><rect class="ke-hit" x="' + (cx - step / 2 + 1) + '" y="16" width="' + (step - 2) + '" height="393" fill="transparent"/>';
      if ([r.open, r.high, r.low, r.close].every(number)) {
        svg += '<line x1="' + cx + '" x2="' + cx + '" y1="' + y(r.high) + '" y2="' + y(r.low) + '" stroke="' + color + '" stroke-width="1.6"/><rect x="' + (cx - width / 2) + '" y="' + Math.min(y(r.open), y(r.close)) + '" width="' + width + '" height="' + Math.max(1.5, Math.abs(y(r.open) - y(r.close))) + '" fill="' + color + '"/>';
        if (r.signals.length) svg += '<circle cx="' + cx + '" cy="' + (y(r.high) - 12) + '" r="5" fill="#fbd45a"/>';
      } else svg += '<text x="' + cx + '" y="165" text-anchor="middle">×</text>';
      if (number(r.volume)) { const h = r.volume / volMax * 66; svg += '<rect x="' + (cx - width / 2) + '" y="' + (400 - h) + '" width="' + width + '" height="' + h + '" fill="' + color + '" opacity=".65"/>'; }
      svg += '</g>';
      if (i % Math.max(1, Math.ceil(rows.length / 6)) === 0) svg += '<text x="' + cx + '" y="427" text-anchor="middle">' + esc(r.date) + '</text>';
    });
    return svg + '</svg>';
  }
  function selectDay(day) {
    const index = data.candles.findIndex(item => item.date === day), r = data.candles[index]; if (!r) return;
    if (index < viewStart || index >= viewStart + viewSize) { viewStart = index - Math.floor(viewSize / 2); renderChart(); }
    $('ke-chart').querySelectorAll('[data-ke-day]').forEach(el => el.classList.toggle('ke-selected', el.dataset.keDay === day));
    $('ke-detail').innerHTML = '<strong>' + esc(r.date) + '｜' + esc(r.signals.map(label).join('、') || r.reason) + '</strong><div>' + esc(r.reason) + '</div><div class="ke-muted">開 ' + fmt(r.open) + '・高 ' + fmt(r.high) + '・低 ' + fmt(r.low) + '・收 ' + fmt(r.close) + '・成交 ' + fmt(r.volume, 0) + ' 股</div>' +
      (r.metrics ? '<div>實體 ' + pct(r.metrics.bodyPct, 4) + '・量比 ' + fmt(r.metrics.volumeRatio, 3) + ' 倍・前 20 日高／低 ' + fmt(r.metrics.priorHigh) + '／' + fmt(r.metrics.priorLow) + '</div>' : '') +
      '<div class="ke-muted">' + [1, 3, 5, 10].map(h => h + ' 日後：' + (number(r.returns[h].value) ? pct(r.returns[h].value) : esc(r.returns[h].reason))).join('；') + '</div>';
  }
  function renderChart() {
    const maxStart = Math.max(0, data.candles.length - viewSize);
    viewStart = Math.max(0, Math.min(maxStart, viewStart));
    const rows = data.candles.slice(viewStart, viewStart + viewSize);
    $('ke-chart').innerHTML = chart(rows);
    $('ke-visible').textContent = rows.length ? '目前顯示 ' + rows[0].date + '～' + rows[rows.length - 1].date + '（第 ' + (viewStart + 1) + '～' + (viewStart + rows.length) + ' 日，共 ' + data.candles.length + ' 日）' : '所選期間沒有日線資料。';
    $('ke-position').max = maxStart; $('ke-position').value = viewStart; $('ke-position').disabled = !maxStart;
    $('ke-position').setAttribute('aria-valuetext', $('ke-visible').textContent);
    ['ke-first', 'ke-prev'].forEach(id => { $(id).disabled = viewStart === 0; });
    ['ke-next', 'ke-last'].forEach(id => { $(id).disabled = viewStart === maxStart; });
    $('ke-detail').innerHTML = '';
  }
  function eventTable(rows) {
    return '<table><thead><tr><th>日期</th><th>事件</th><th>收盤</th><th>1 日後</th><th>3 日後</th><th>5 日後</th><th>10 日後</th></tr></thead><tbody>' + (rows.length ? rows.map(r => '<tr><td><button data-ke-day="' + esc(r.date) + '">' + esc(r.date) + '</button></td><td class="ke-wrap">' + esc(r.signals.map(label).join('、')) + '</td><td>' + fmt(r.close) + '</td>' + [1, 3, 5, 10].map(h => cell(r.returns[h].value, r.returns[h].reason)).join('') + '</tr>').join('') : '<tr><td colspan="7">此區間沒有可判定的特殊事件。請查看資料品質。</td></tr>') + '</tbody></table>';
  }
  function renderEvents() {
    const pages = Math.max(1, Math.ceil(data.events.length / EVENT_PAGE_SIZE));
    eventPage = Math.max(0, Math.min(pages - 1, eventPage));
    $('ke-events').innerHTML = eventTable(data.events.slice(eventPage * EVENT_PAGE_SIZE, (eventPage + 1) * EVENT_PAGE_SIZE));
    $('ke-event-page').textContent = '第 ' + (eventPage + 1) + '／' + pages + ' 頁，共 ' + data.events.length + ' 個事件日（由新到舊）';
    $('ke-event-prev').disabled = eventPage === 0; $('ke-event-next').disabled = eventPage === pages - 1;
  }
  function renderStats() {
    const h = $('ke-horizon').value;
    $('ke-stats').innerHTML = '<table><thead><tr><th>型態</th><th>成熟樣本</th><th>平均</th><th>中位數</th><th>上漲比例</th><th>中間 50% 報酬</th><th>基準平均</th><th>平均差</th><th>非重疊平均</th></tr></thead><tbody>' + data.stats.map(row => {
      const s = row.horizons[h];
      return '<tr><td>' + esc(row.label) + '<small>事件總數 ' + row.cases + '</small></td><td>' + s.raw.n + (s.raw.smallSample ? '<small>小樣本</small>' : '') + '</td>' + cell(s.raw.mean) + cell(s.raw.median) + '<td>' + (number(s.raw.positivePct) ? fmt(s.raw.positivePct) + '%' : '資料不足') + '</td><td>' + pct(s.raw.q25) + '～' + pct(s.raw.q75) + '</td><td>' + pct(s.baseline.mean) + '<small>n=' + s.baseline.n + '</small></td>' + cell(s.difference, '事件平均減去同期間基準平均，單位為百分點') + '<td>' + pct(s.nonOverlapping.mean) + '<small>n=' + s.nonOverlapping.n + '</small></td></tr>';
    }).join('') + '</tbody></table>';
  }
  function canUseShadow() {
    const profile = window.ST_PRIVATE_WEB_PROFILE;
    return !profile || profile.role === 'owner';
  }
  function syncShadowAccess() {
    const allowed = canUseShadow(), note = $('ke-long-access');
    if (note) note.textContent = allowed ? '影子紀錄保留首次證據與實際觀測時間。' : '唯讀模式：可載入突破研究；保存與私人影子紀錄僅供擁有者使用。';
    if (!allowed) {
      ['ke-long-save', 'ke-long-history'].forEach(id => { if ($(id)) $(id).disabled = true; });
      if ($('ke-long-shadow')) $('ke-long-shadow').innerHTML = '';
    }
    return allowed;
  }
  function renderLong() {
    syncShadowAccess();
    const host = $('ke-long-result'); if (!host || !longData) return;
    const research = longData.research;
    if (!research) { host.innerHTML = '<p>' + esc((longData.missingData || []).join('；') || '研究資料尚未建立。') + '</p>'; return; }
    const adjusted = $('ke-long-basis').value === 'official_reference';
    const selected = adjusted ? research.adjusted : research;
    const latest = selected && selected.latest;
    const horizon = $('ke-long-horizon').value;
    const assumptions = selected && selected.execution && selected.execution.assumptions;
    const rows = selected && selected.execution ? selected.execution.rules : [];
    host.innerHTML = '<p><strong>' + (adjusted ? '官方參考價比較' : '原始價格') + '・持有 ' + esc(horizon) + ' 日</strong><br>研究期間 ' + esc(longData.historyStart || '無資料') + '～' + esc(longData.historyEnd || '無資料') + '。' + esc((longData.missingData || []).join('；')) + '</p>' +
      (adjusted ? '<p class="ke-state ke-warn">官方參考價僅調整訊號比較窗口，成交一律採原始價格。' + esc(longData.comparisonStatus === 'missing' ? longData.comparisonReason : '需要完整來源收據；不是股數比率或總報酬。') + '</p>' : '') +
      '<ul>' + (selected ? selected.rules : []).map(rule => '<li><strong>' + esc(rule.label) + '</strong>：' + esc(latest ? latest.reason[rule.key] : '尚無資料') + '</li>').join('') + '</ul>' +
      '<p class="ke-muted">' + esc(assumptions ? assumptions.entry + '；' + assumptions.exit + '。' + assumptions.costNote : '尚無成交資料。') + '</p>' +
      '<div class="ke-scroll"><table><thead><tr><th>規則</th><th>成熟／訊號</th><th>未平倉／未進場</th><th>排除</th><th>原價毛報酬</th><th>每邊 0.25%</th><th>每邊 0.50%</th><th>0050 配對差</th><th>同年隨機中位數</th></tr></thead><tbody>' + rows.map(rule => {
        const h = rule.horizons[horizon], trades = h.trades;
        return '<tr><td class="ke-wrap">' + esc(rule.label) + '</td><td>' + h.counts.mature + '／' + h.counts.signals + '</td><td>' + trades.filter(t => t.positionStatus === 'open').length + '／' + trades.filter(t => t.positionStatus === 'not_entered').length + '</td><td>' + h.counts.excluded + '</td>' + cell(h.raw.gross.mean) + cell(h.raw.baseNet.mean) + cell(h.raw.stressNet.mean) + '<td>' + pct(h.benchmark.excess.baseNet.mean) + '<small>相同交易 n=' + h.benchmark.pairedCount + '，百分點</small></td><td>' + pct(h.random.metrics.baseNet.median) + '<small>' + esc(h.random.status) + '</small></td></tr>';
      }).join('') + '</tbody></table></div><details><summary>成交日期、排除原因與固定切分</summary>' + rows.map(rule => {
        const h = rule.horizons[horizon], split = h.fixedSplit;
        return '<h4>' + esc(rule.label) + '</h4><p>訓練截至 ' + esc(split.trainEnd) + '：n=' + split.train.n + '；測試自 ' + esc(split.testStart) + '：n=' + split.test.n + '。不以測試結果調參。</p><ul>' + h.trades.map(t => '<li>' + esc(t.signalDate + ' 訊號 → ' + (t.entryDate || '待定') + ' 開盤 → ' + (t.exitDate || '尚未到期') + ' 收盤；' + (t.reason || '成熟')) + '；淨報酬 ' + pct(t.baseNet) + '</li>').join('') + '</ul>';
      }).join('') + '</details><details><summary>方法、官方證據與限制</summary><ul>' + (selected ? selected.notes : []).concat(longData.limitations || []).map(n => '<li>' + esc(n) + '</li>').join('') + '</ul>' + (adjusted ? '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(JSON.stringify(selected.adjustmentEvidence, null, 2)) + '</pre>' : '') + '</details>';
    $('ke-long-save').disabled = !(canUseShadow() && longData.freshness && longData.freshness.fresh && latest && latest.date === longData.asOf && latest.date === longData.freshness.expectedSession);
  }
  async function loadLong() {
    if (!data || !longParams) return;
    const serial = generation;
    if (longController) longController.abort();
    const request = longController = new AbortController();
    $('ke-long-load').disabled = true; $('ke-long-status').textContent = '正在讀取本機長期研究…';
    const timer = setTimeout(() => request.abort(), 30000);
    try {
      const response = await fetch('/breakout-research?' + longParams, { signal: request.signal });
      if (!response.ok) throw new Error('長期研究讀取失敗，請確認日線與官方核對資料已建立。');
      const result = await response.json();
      if (serial !== generation || !dialog.open) return;
      longData = result; renderLong();
      $('ke-long-status').textContent = '已讀取本機研究；保存按鈕只凍結最新完整交易日的首次觀察。';
    } catch (error) { if (serial === generation && dialog.open) $('ke-long-status').textContent = error.name === 'AbortError' ? '研究讀取逾時，請重新載入。' : error.message; }
    finally { clearTimeout(timer); if (serial === generation && $('ke-long-load')) $('ke-long-load').disabled = false; }
  }
  async function saveLong() {
    if (!syncShadowAccess()) return;
    if (!longData || !longParams) return;
    const serial = generation, button = $('ke-long-save'); button.disabled = true;
    const request = new AbortController(), timer = setTimeout(() => request.abort(), 20000);
    try {
      const payload = Object.fromEntries(longParams); payload.priceBasis = $('ke-long-basis').value;
      const response = await fetch('/breakout-shadow', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: request.signal });
      if (!response.ok) throw new Error('保存未完成，請確認資料是最新完整交易日。');
      const result = await response.json();
      if (serial === generation && dialog.open) $('ke-long-status').textContent = result.status + '；' + (result.note || result.reason || '首次觀察保留，資料修訂另列。');
    } catch (error) { if (serial === generation && dialog.open) $('ke-long-status').textContent = error.name === 'AbortError' ? '保存回應逾時；請查閱影子紀錄確認狀態，重試不會覆寫首次紀錄。' : error.message; }
    finally { clearTimeout(timer); if (serial === generation) { button.disabled = !canUseShadow(); syncShadowAccess(); } }
  }
  async function showShadow() {
    if (!syncShadowAccess()) return;
    if (!longParams) return;
    const serial = generation, button = $('ke-long-history'); button.disabled = true;
    const request = new AbortController(), timer = setTimeout(() => request.abort(), 20000);
    try {
      const response = await fetch('/breakout-shadow?' + new URLSearchParams({ sym: longParams.get('sym') }), { signal: request.signal });
      if (!response.ok) throw new Error('影子紀錄讀取失敗；請使用具備研究紀錄權限的帳號。');
      const result = await response.json();
      if (serial !== generation || !dialog.open) return;
      $('ke-long-shadow').innerHTML = '<p>' + esc(result.status) + '</p><ul>' + (result.records || []).map(r => '<li>' + esc(r.date + '｜' + r.version + '｜首次觀測 ' + r.observedAt) + '；修訂 ' + r.revisionCount + ' 次<small style="display:block;overflow-wrap:anywhere">輸入摘要 ' + esc(r.inputDigest) + '</small></li>').join('') + '</ul><p class="ke-muted">' + esc(result.note) + '</p>';
    } catch (error) { if (serial === generation && dialog.open) $('ke-long-status').textContent = error.name === 'AbortError' ? '影子紀錄讀取逾時，請重新載入。' : error.message; }
    finally { clearTimeout(timer); if (serial === generation) { button.disabled = !canUseShadow(); syncShadowAccess(); } }
  }
  function render() {
    const f = data.freshness;
    $('ke-status').className = 'ke-state' + (f.fresh ? '' : ' ke-warn');
    $('ke-status').textContent = f.status + '｜應有 ' + (f.expectedSession || '待核對') + '；資料最新 ' + (f.latestSession || '無資料') + '。本次研究截至 ' + data.asOf + '。';
    $('ke-result').innerHTML = '<p class="ke-scope"><strong>' + esc(data.range.label) + '：' + esc(data.historyStart || '無資料') + '～' + esc(data.historyEnd || '無資料') + '</strong><br><span class="ke-muted">資料庫現存日線 ' + esc(data.availableStart || '無資料') + '～' + esc(data.availableEnd || '無資料') + '；完整歷史依現有資料範圍提供，尚未核對的日期不納入事件統計。</span></p><div class="ke-kpis"><div><span class="ke-muted">研究標的</span><strong>' + esc(data.sym + ' ' + data.name) + '</strong></div><div><span class="ke-muted">期間事件天數</span><strong>' + data.events.length + '</strong></div><div><span class="ke-muted">期間可判定交易日</span><strong>' + data.eligibleDays + '</strong></div><div><span class="ke-muted">時間軸日數</span><strong>' + data.timelineDays + '</strong></div></div>' +
      '<section><h3>長期突破與隔日開盤研究</h3><p>120／252 日首次突破、同年隨機及同日 0050 對照；僅使用本機已核對資料。</p><div class="ke-nav" data-ke-interactive><button id="ke-long-load">載入長期研究</button><label>訊號比較基準<select id="ke-long-basis"><option value="raw">原始價格</option><option value="official_reference">官方參考價比較</option></select></label><label>持有日數<select id="ke-long-horizon"><option value="1">1 日</option><option value="3">3 日</option><option value="5" selected>5 日</option><option value="10">10 日</option></select></label><button id="ke-long-save" disabled>保存首次影子觀察</button><button id="ke-long-history">查看影子紀錄</button></div><p id="ke-long-access" class="ke-muted"></p><p id="ke-long-status" role="status">尚未載入；先完成 253 日暖機及官方公司行動核對。</p><div id="ke-long-result"></div><div id="ke-long-shadow"></div></section>' +
      '<section><h3>歷史 K 線與成交量</h3><p class="ke-muted">點選 K 線或黃色點可查看當日依據。紅漲綠跌；缺值以 × 標示。圖表分段瀏覽，統計維持整個所選期間。</p><div class="ke-nav" data-ke-interactive><label>每段日數<select id="ke-size"><option value="30">30 日</option><option value="60">60 日</option><option value="120">120 日</option></select></label><button id="ke-first">最早</button><button id="ke-prev">上一段</button><button id="ke-next">下一段</button><button id="ke-last">最新</button><label>跳至日期<input id="ke-jump" type="date"></label><button id="ke-jump-go">前往日期</button></div><label class="ke-timeline" data-ke-interactive>歷史時間軸<input id="ke-position" type="range" min="0" step="1" value="0"></label><p id="ke-visible" class="ke-muted" aria-live="polite"></p><div id="ke-chart" class="ke-scroll"></div><div id="ke-detail" class="ke-detail" aria-live="polite"></div></section>' +
      '<section><h3>特殊事件與後續表現</h3><div class="ke-nav" data-ke-interactive><button id="ke-event-prev">上一頁事件</button><span id="ke-event-page" aria-live="polite"></span><button id="ke-event-next">下一頁事件</button></div><div id="ke-events" class="ke-scroll"></div><p class="ke-muted">資料不足的原因可點選該日查看；缺值與未成熟報酬皆不補零。下載報告包含所選期間全部事件。</p></section>' +
      '<section><div class="ke-inline"><h3>歷史同型態統計</h3><label>後續交易日<select id="ke-horizon"><option value="1">1 日</option><option value="3">3 日</option><option value="5" selected>5 日</option><option value="10">10 日</option></select></label></div><p class="ke-muted">研究區間 ' + esc(data.historyStart || '尚未建立') + '～' + esc(data.historyEnd || '尚未建立') + '。各期只使用成熟樣本；平均差單位為百分點。</p><div id="ke-stats" class="ke-scroll"></div></section>' +
      '<details><summary>資料品質與不可判定日期</summary><p>官方來源：TWSE／TPEx；成交量統一為股。歷史中尚未官方核對 ' + data.unverifiedRows + ' 筆。</p><p>' + (data.companyActionCoverage ? '公司行動已核對：' + esc(data.companyActionCoverage.start + '～' + data.companyActionCoverage.end + '；' + data.companyActionCoverage.source) : '公司行動尚未完成核對。目前已提供台積電三年研究回補；其他標的需建立完整核對區間後才會產生統計。') + '</p><ul>' + data.candles.filter(r => !r.eligible).map(r => '<li>' + esc(r.date + '：' + r.reason) + '</li>').join('') + '</ul></details>' +
      '<details><summary>六種規則與統計口徑</summary><ul>' + data.rules.map(r => '<li>' + esc(r.label + '：' + r.formula) + '</li>').join('') + '</ul><ul>' + data.notes.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul></details>';
    viewStart = Math.max(0, data.candles.length - viewSize); eventPage = 0;
    $('ke-size').value = String(viewSize);
    $('ke-size').onchange = () => { const end = viewStart + viewSize; viewSize = Number($('ke-size').value); viewStart = end - viewSize; renderChart(); };
    $('ke-position').oninput = () => { viewStart = Number($('ke-position').value); renderChart(); };
    $('ke-first').onclick = () => { viewStart = 0; renderChart(); };
    $('ke-prev').onclick = () => { viewStart -= viewSize; renderChart(); };
    $('ke-next').onclick = () => { viewStart += viewSize; renderChart(); };
    $('ke-last').onclick = () => { viewStart = data.candles.length; renderChart(); };
    $('ke-jump').min = data.historyStart || ''; $('ke-jump').max = data.historyEnd || '';
    $('ke-jump-go').onclick = () => {
      const day = $('ke-jump').value;
      if (!day || !$('ke-jump').reportValidity()) return;
      const row = data.candles.find(r => r.date >= day);
      if (row) { viewStart = data.candles.indexOf(row); renderChart(); selectDay(row.date); }
    };
    $('ke-event-prev').onclick = () => { eventPage--; renderEvents(); };
    $('ke-event-next').onclick = () => { eventPage++; renderEvents(); };
    $('ke-horizon').onchange = renderStats; renderStats(); renderChart(); renderEvents();
    $('ke-long-load').onclick = loadLong; $('ke-long-save').onclick = saveLong;
    $('ke-long-history').onclick = showShadow;
    syncShadowAccess();
    $('ke-long-basis').onchange = renderLong; $('ke-long-horizon').onchange = renderLong;
    $('ke-result').onclick = event => { const el = event.target.closest('[data-ke-day]'); if (el) selectDay(el.dataset.keDay); };
    $('ke-result').onkeydown = event => { const el = event.target.closest('g[data-ke-day]'); if (el && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); selectDay(el.dataset.keDay); } };
    if (data.candles.length) selectDay(data.candles[data.candles.length - 1].date);
    $('ke-export').disabled = false;
  }
  async function load() {
    const sym = $('ke-sym').value.trim().toUpperCase();
    if (!/^[0-9A-Z]{4,7}$/.test(sym)) { $('ke-status').textContent = '請輸入有效台股代號。'; return; }
    const params = new URLSearchParams({ sym, range: $('ke-range').value });
    if ($('ke-date').value) params.set('asOf', $('ke-date').value);
    if ($('ke-range').value === 'custom') {
      if (!$('ke-start').value) { $('ke-status').textContent = '自訂期間請填寫開始日期。'; return; }
      if ($('ke-date').value && $('ke-start').value > $('ke-date').value) { $('ke-status').textContent = '開始日期不得晚於截至日期。'; return; }
      params.set('start', $('ke-start').value);
    }
    const serial = ++generation;
    if (longController) longController.abort(); longData = null;
    if (controller) controller.abort(); const request = controller = new AbortController();
    $('ke-load').disabled = true; $('ke-export').disabled = true; $('ke-result').innerHTML = ''; $('ke-status').textContent = '正在讀取已核對日線與事件統計…';
    const timer = setTimeout(() => request.abort(), 20000);
    try {
      const response = await fetch('/kline-events?' + params, { signal: request.signal });
      if (!response.ok) throw new Error(response.status === 400 ? '期間或日期無效，請確認開始日不晚於截至日，且不超過最新已完成交易日。' : '事件資料尚未完整建立，請檢查日線更新狀態。');
      const result = await response.json();
      if (serial !== generation || !dialog.open) return;
      data = result; longParams = new URLSearchParams(params); render();
    } catch (error) {
      if (serial === generation && dialog.open) { $('ke-status').className = 'ke-state ke-warn'; $('ke-status').textContent = error.name === 'AbortError' ? '讀取逾時，請重新載入。' : error.message; }
    } finally { clearTimeout(timer); if (serial === generation) $('ke-load').disabled = false; }
  }
  function download() {
    if (!data) return;
    const copy = $('ke-result').cloneNode(true);
    copy.querySelector('#ke-events').innerHTML = eventTable(data.events);
    const charts = [];
    for (let i = 0; i < data.candles.length; i += 120) {
      const rows = data.candles.slice(i, i + 120);
      charts.push('<p>' + esc(rows[0].date + '～' + rows[rows.length - 1].date) + '</p>' + chart(rows));
    }
    copy.querySelector('#ke-chart').innerHTML = charts.join('') || chart([]);
    copy.querySelector('#ke-visible').textContent = '以下分段列出所選期間全部 ' + data.candles.length + ' 日。';
    copy.querySelectorAll('[data-ke-interactive]').forEach(el => el.remove());
    copy.querySelectorAll('details').forEach(el => { el.open = true; });
    copy.querySelectorAll('select').forEach(el => { el.value = $(el.id).value; el.replaceWith(document.createTextNode(el.options[el.selectedIndex].text)); });
    copy.querySelectorAll('button').forEach(el => el.replaceWith(document.createTextNode(el.textContent)));
    const html = '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(data.sym) + ' K 線事件研究</title><style>body{margin:20px;background:#0b1220}' + CSS + '#ke-dialog{max-height:none;width:100%;max-width:1180px;margin:auto;overflow:visible}</style><main id="ke-dialog"><div class="ke-content"><h2>' + esc(data.sym) + ' K 線事件研究</h2><p>' + esc($('ke-status').textContent) + '</p>' + copy.innerHTML + '</div></main></html>';
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = data.sym + '_K線事件研究_' + (data.historyStart || '無資料') + '_' + data.asOf + '.html'; a.hidden = true;
    dialog.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  function close() {
    generation++; if (controller) controller.abort();
    if (longController) longController.abort();
    if (dialog && dialog.open) dialog.close();
    if (priorFocus && priorFocus.isConnected) priorFocus.focus();
  }
  function open(symbol) {
    if (dialog && dialog.open) close(); priorFocus = document.activeElement;
    if (!$('ke-style')) { const style = document.createElement('style'); style.id = 'ke-style'; style.textContent = CSS; document.head.appendChild(style); }
    if (!dialog) { dialog = document.createElement('dialog'); dialog.id = 'ke-dialog'; dialog.setAttribute('aria-labelledby', 'ke-title'); document.body.appendChild(dialog); }
    const current = String(symbol || ((typeof S !== 'undefined' && S.mkt === 'TW') ? S.sym : '') || '2330').replace(/\.(TW|TWO)$/i, '');
    dialog.innerHTML = '<div class="ke-head"><div><h2 id="ke-title">K 線事件研究</h2><div class="ke-muted">找出值得觀察的日期，查看歷史後續表現</div></div><button id="ke-close">關閉</button></div><div class="ke-content"><div class="ke-fields"><label>台股代號<input id="ke-sym" value="' + esc(/^[0-9A-Z]{4,7}$/.test(current) ? current : '2330') + '" maxlength="7"></label><label>研究期間<select id="ke-range"><option value="30d">近 30 個交易日</option><option value="3m">近 3 個月</option><option value="6m">近 6 個月</option><option value="1y">近 1 年</option><option value="3y" selected>近 3 年</option><option value="5y">近 5 年</option><option value="10y">近 10 年</option><option value="all">完整歷史</option><option value="custom">自訂期間</option></select></label><label id="ke-start-field" hidden>開始日期<input id="ke-start" type="date"></label><label>截至日期（留空為最新）<input id="ke-date" type="date"></label><button id="ke-load">載入研究</button><button id="ke-export" disabled>下載 HTML 報告</button></div><div id="ke-status" class="ke-state" role="status"></div><div id="ke-result"></div></div>';
    $('ke-close').onclick = close; dialog.oncancel = event => { event.preventDefault(); close(); };
    $('ke-load').onclick = load; $('ke-export').onclick = download;
    $('ke-range').onchange = () => { $('ke-start-field').hidden = $('ke-range').value !== 'custom'; };
    dialog.showModal(); $('ke-close').focus(); load();
  }
  function mount() {
    const parent = $('pro-tools'); if (!parent) return false;
    if (!$('btn-kline-events')) { const b = document.createElement('button'); b.id = 'btn-kline-events'; b.className = 'btn'; b.textContent = 'K 線事件'; b.onclick = () => open(); parent.appendChild(b); }
    return true;
  }
  if (!mount()) { let attempts = 0; const timer = setInterval(() => { if (mount() || ++attempts > 30) clearInterval(timer); }, 300); }
  window.addEventListener('hashchange', () => { if (dialog && dialog.open) close(); });
  window.KlineEventsUI = { open, close };
})();

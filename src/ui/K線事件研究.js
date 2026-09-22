/* 官方日線事件研究：圖表、品質及統計使用同一份資料。 */
(function () {
  'use strict';
  let dialog, controller, priorFocus, data, generation = 0, viewStart = 0, viewSize = 30, eventPage = 0;
  const EVENT_PAGE_SIZE = 50;
  const $ = id => document.getElementById(id);
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const number = v => typeof v === 'number' && Number.isFinite(v);
  const fmt = (v, n = 2) => number(v) ? v.toLocaleString('zh-TW', { maximumFractionDigits: n }) : '未提供';
  const pct = (v, n = 2) => number(v) ? (v > 0 ? '+' : '') + fmt(v, n) + '%' : '資料不足';
  const researchRules = () => data.research && Array.isArray(data.research.rules) ? data.research.rules : [];
  const label = key => ([...(data.rules || []), ...researchRules()].find(r => r.key === key) || {}).label || key;
  const researchSignals = row => row.research && Array.isArray(row.research.signals) ? row.research.signals : [];
  const eventSignals = row => [...(row.signals || []), ...researchSignals(row)];
  const eventRows = () => data.candles.filter(row => eventSignals(row).length).slice().reverse();
  const METRICS = [
    ['priorHigh20', '前 20 日高點', false], ['priorHigh120', '前 120 日高點', false],
    ['priorHigh252', '前 252 日高點', false], ['maxDrawdown100Pct', '前 100 日最大回撤幅度', true],
    ['distance252HighPct', '距前 252 日高點', true]
  ];
  const researchCondition = (row, key) => row.conditions && row.conditions[key] === true ? '符合' : row.conditions && row.conditions[key] === false ? '未符合' : '不可判定';
  const researchEvidence = row => METRICS.map(([key, name, percentage]) => {
    const value = (row.metrics || {})[key];
    return name + ' ' + (key === 'maxDrawdown100Pct' ? number(value) ? fmt(value) + '%' : '資料不足' : percentage ? pct(value) : fmt(value));
  }).join('；');
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
    #ke-dialog .ke-research-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}#ke-dialog .ke-research-card{min-width:0;padding:12px;border:1px solid #475569;border-radius:6px;background:#19283b;overflow-wrap:anywhere}#ke-dialog .ke-research-card h4{font-size:14px;line-height:1.5;margin:0 0 8px}#ke-dialog .ke-research-card p{margin:5px 0;font-size:13px}#ke-dialog .ke-evidence{font-size:13px;overflow-wrap:anywhere}#ke-dialog .ke-detail{overflow-wrap:anywhere}#ke-dialog .ke-head>div{min-width:0}#ke-dialog .ke-head>button{flex-shrink:0}#ke-dialog .ke-fields select{max-width:100%}#ke-dialog .ke-research-table td.ke-wrap{min-width:210px;max-width:420px;overflow-wrap:anywhere}#ke-dialog a{color:#93c5fd;text-underline-offset:3px}
    @media(max-width:800px){#ke-dialog .ke-research-grid{grid-template-columns:minmax(0,1fr)}#ke-dialog .ke-research-card{padding:10px}}
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
      const events = eventSignals(r);
      const title = r.date + '｜' + (events.length ? events.map(label).join('、') : r.reason);
      svg += '<g data-ke-day="' + esc(r.date) + '" tabindex="0" role="button" aria-label="' + esc(title) + '"><title>' + esc(title) + '</title><rect class="ke-hit" x="' + (cx - step / 2 + 1) + '" y="16" width="' + (step - 2) + '" height="393" fill="transparent"/>';
      if ([r.open, r.high, r.low, r.close].every(number)) {
        svg += '<line x1="' + cx + '" x2="' + cx + '" y1="' + y(r.high) + '" y2="' + y(r.low) + '" stroke="' + color + '" stroke-width="1.6"/><rect x="' + (cx - width / 2) + '" y="' + Math.min(y(r.open), y(r.close)) + '" width="' + width + '" height="' + Math.max(1.5, Math.abs(y(r.open) - y(r.close))) + '" fill="' + color + '"/>';
        if (events.length) svg += '<circle cx="' + cx + '" cy="' + (y(r.high) - 12) + '" r="5" fill="#fbd45a"/>';
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
    $('ke-detail').innerHTML = '<strong>' + esc(r.date) + '｜' + esc(eventSignals(r).map(label).join('、') || r.reason) + '</strong><div>' + esc(r.reason) + '</div><div class="ke-muted">開 ' + fmt(r.open) + '・高 ' + fmt(r.high) + '・低 ' + fmt(r.low) + '・收 ' + fmt(r.close) + '・成交 ' + fmt(r.volume, 0) + ' 股</div>' +
      (r.metrics ? '<div>實體 ' + pct(r.metrics.bodyPct, 4) + '・量比 ' + fmt(r.metrics.volumeRatio, 3) + ' 倍・前 20 日高／低 ' + fmt(r.metrics.priorHigh) + '／' + fmt(r.metrics.priorLow) + '</div>' : '') +
      (r.research ? '<div class="ke-evidence"><strong>突破位置研究</strong><ul>' + researchRules().map(rule => '<li>' + esc(rule.label + '：當日條件' + researchCondition(r.research, rule.key) + '；' + (researchSignals(r).includes(rule.key) ? '本日新增觀察事件' : '本日未新增觀察事件') + '。' + ((r.research.reason || {})[rule.key] || '')) + '</li>').join('') + '</ul><p>' + esc(researchEvidence(r.research)) + '</p></div>' : '') +
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
    return '<table><thead><tr><th>日期</th><th>事件</th><th>收盤</th><th>1 日後</th><th>3 日後</th><th>5 日後</th><th>10 日後</th></tr></thead><tbody>' + (rows.length ? rows.map(r => '<tr><td><button data-ke-day="' + esc(r.date) + '">' + esc(r.date) + '</button></td><td class="ke-wrap">' + esc(eventSignals(r).map(label).join('、')) + (researchSignals(r).length ? '<small>含研究觀察事件，不是買進建議</small>' : '') + '</td><td>' + fmt(r.close) + '</td>' + [1, 3, 5, 10].map(h => cell(r.returns[h].value, r.returns[h].reason)).join('') + '</tr>').join('') : '<tr><td colspan="7">此區間沒有可判定的特殊事件。請查看資料品質。</td></tr>') + '</tbody></table>';
  }
  function renderEvents() {
    const events = eventRows(), pages = Math.max(1, Math.ceil(events.length / EVENT_PAGE_SIZE));
    eventPage = Math.max(0, Math.min(pages - 1, eventPage));
    $('ke-events').innerHTML = eventTable(events.slice(eventPage * EVENT_PAGE_SIZE, (eventPage + 1) * EVENT_PAGE_SIZE));
    $('ke-event-page').textContent = '第 ' + (eventPage + 1) + '／' + pages + ' 頁，共 ' + events.length + ' 個事件日（由新到舊）';
    $('ke-event-prev').disabled = eventPage === 0; $('ke-event-next').disabled = eventPage === pages - 1;
  }
  function statsTable(rows, h) {
    return '<table><thead><tr><th>型態</th><th>成熟樣本</th><th>平均</th><th>中位數</th><th>上漲比例</th><th>中間 50% 報酬</th><th>基準平均</th><th>平均差</th><th>非重疊平均</th></tr></thead><tbody>' + rows.map(row => {
      const s = row.horizons[h];
      return '<tr><td>' + esc(row.label) + '<small>事件總數 ' + row.cases + '</small>' + (number(row.eligibleDays) ? '<small>可判定日數 ' + row.eligibleDays + '</small>' : '') + '</td><td>' + s.raw.n + (s.raw.smallSample ? '<small>小樣本</small>' : '') + '</td>' + cell(s.raw.mean) + cell(s.raw.median) + '<td>' + (number(s.raw.positivePct) ? fmt(s.raw.positivePct) + '%' : '資料不足') + '</td><td>' + pct(s.raw.q25) + '～' + pct(s.raw.q75) + '</td><td>' + pct(s.baseline.mean) + '<small>n=' + s.baseline.n + '</small></td>' + cell(s.difference, '事件平均減去同期間基準平均，單位為百分點') + '<td>' + pct(s.nonOverlapping.mean) + '<small>n=' + s.nonOverlapping.n + '</small></td></tr>';
    }).join('') + '</tbody></table>';
  }
  function renderStats() {
    const h = $('ke-horizon').value;
    $('ke-stats').innerHTML = statsTable(data.stats, h);
    if ($('ke-research-stats')) $('ke-research-stats').innerHTML = statsTable(data.research.stats || [], h);
  }
  function researchSection() {
    if (!researchRules().length) return '';
    const research = data.research, latest = research.latest || {}, signals = latest.signals || [];
    const shadow = research.shadow, writer = shadow && shadow.writer;
    return '<section id="ke-research"><h3>突破位置與修復風險觀察</h3><p class="ke-muted">研究標籤與影子紀錄，不加入買進分數、不自動下單。正報酬不等於進場優勢；目前未完成文章策略、配對隨機或 0050 比較驗證。</p>' +
      '<div class="ke-state' + (!latest.date || researchRules().some(rule => !(latest.eligible || {})[rule.key]) ? ' ke-warn' : '') + '">資料基準：' + esc(latest.date || '無可用交易日') + '；最近已完成交易日：' + esc(data.freshness.expectedSession || '待核對') + '。以本次截至日期以前的已完成日線分析；休市沿用最近已完成交易日，歷史查詢保留當時日期前提。</div>' +
      '<div class="ke-research-grid">' + researchRules().map(rule => '<article class="ke-research-card"><h4>' + esc(rule.label) + '</h4><p><strong>當日條件：' + researchCondition(latest, rule.key) + '</strong></p><p>' + (signals.includes(rule.key) ? '本日新增觀察事件' : '本日未新增觀察事件') + '；首次事件判定：' + ((latest.eligible || {})[rule.key] ? '可判定' : '不可判定') + '</p><p class="ke-muted">' + esc((latest.reason || {})[rule.key] || '請查看規則與判定依據。') + '</p></article>').join('') + '</div>' +
      '<p class="ke-evidence">' + esc(researchEvidence(latest)) + '</p>' +
      '<details><summary>研究規則、來源與判定前提</summary><ul>' + researchRules().map(rule => '<li><strong>' + esc(rule.label) + '</strong>：' + esc(rule.formula) + '</li>').join('') + '</ul><p>首次事件只在已能判定的前一交易日未符合、當日符合時成立；連續符合不重複記錄，無法核對前日時不補造事件。</p><p>本階段「修復風險」為工程版：20 日突破、前 100 日最大回撤至少 20%、距前 252 日高點至少低 15%；不是文章 15 日箱型策略的重現。VIDYA 尚未納入。</p><p class="ke-evidence">規則版本：' + esc(research.version || '未提供') + '；資料來源：' + esc(latest.source || '依官方日線品質紀錄') + '；輸入摘要：' + esc(latest.inputDigest || '未提供') + '</p><ul>' + (research.notes || []).map(note => '<li>' + esc(note) + '</li>').join('') + '</ul></details>' +
      '<p class="ke-muted">研究來源（2026 年 9 月 20 日）：<a href="https://blog.fantasymaya.org/posts/right-side-breakout-regime-note/" target="_blank" rel="noopener noreferrer">右側突破的出場回測</a>、<a href="https://blog.fantasymaya.org/posts/entry-signal-cross-validation/" target="_blank" rel="noopener noreferrer">進場策略與隨機比較</a>。本頁為工程觀察規則，不代表已重現文章策略或績效。</p>' +
      '<p class="ke-evidence">影子紀錄：' + (shadow ? esc(shadow.status || '已提供') + '；最近已記錄交易日 ' + esc(shadow.asOf || '尚無紀錄') + '；首次觀測 ' + esc(shadow.observedAt || '尚無紀錄') + '；目前版本觀察日數 ' + fmt(shadow.count, 0) + '（不是訊號數或績效樣本）。' + esc(shadow.note || '') : '尚未提供帳本狀態；歷史事件不視為當時已觀測的前瞻紀錄。') + '</p>' +
      (writer ? '<p class="ke-evidence">最近帳本寫入工作：' + esc(writer.status || '狀態未提供') + '；檢查標的 ' + fmt(writer.checked, 0) + '；新增觀察 ' + fmt(writer.added, 0) + '；失敗 ' + fmt(Array.isArray(writer.failures) ? writer.failures.length : writer.failures, 0) + '；執行時間 ' + esc(writer.observedAt || '未提供') + '。' + esc(writer.reason || '') + '</p>' : '') +
      (shadow && shadow.revised ? '<div class="ke-state ke-warn">目前資料與該日首次觀測不同；影子帳本保留首次證據，未覆寫或回填歷史。</div>' : '') +
      (shadow && shadow.evidence ? '<details><summary>首次觀測證據</summary><p class="ke-evidence">' + esc((shadow.evidence.date || shadow.asOf || '未提供日期') + '；' + researchEvidence(shadow.evidence)) + '</p><ul>' + researchRules().map(rule => '<li>' + esc(rule.label + '：當日條件' + researchCondition(shadow.evidence, rule.key) + '；' + ((shadow.evidence.signals || []).includes(rule.key) ? '新增觀察事件' : '未新增觀察事件') + '。' + ((shadow.evidence.reason || {})[rule.key] || '')) + '</li>').join('') + '</ul><p class="ke-evidence">首次輸入摘要：' + esc(shadow.evidence.inputDigest || '未提供') + '</p></details>' : '') +
      '<h3>研究事件後續表現</h3><p class="ke-muted">期數跟隨下方「後續交易日」選單。事件日收盤至後續收盤的描述統計，非隔日開盤交易回測；基準為同期合格日期，非配對隨機進場或 0050。</p><div id="ke-research-stats" class="ke-scroll" tabindex="0" aria-label="研究事件後續表現，可水平捲動"></div>' +
      '<details><summary>研究不可判定日期與原因</summary><ul>' + data.candles.filter(row => row.research && researchRules().some(rule => !(row.research.eligible || {})[rule.key])).map(row => '<li>' + esc(row.date + '：' + researchRules().filter(rule => !(row.research.eligible || {})[rule.key]).map(rule => rule.label + '／' + ((row.research.reason || {})[rule.key] || '不可判定')).join('；')) + '</li>').join('') + '</ul></details></section>';
  }
  function render() {
    const f = data.freshness;
    $('ke-status').className = 'ke-state' + (f.fresh ? '' : ' ke-warn');
    $('ke-status').textContent = f.status + '｜應有 ' + (f.expectedSession || '待核對') + '；資料最新 ' + (f.latestSession || '無資料') + '。本次研究截至 ' + data.asOf + '。';
    $('ke-result').innerHTML = '<p class="ke-scope"><strong>' + esc(data.range.label) + '：' + esc(data.historyStart || '無資料') + '～' + esc(data.historyEnd || '無資料') + '</strong><br><span class="ke-muted">資料庫現存日線 ' + esc(data.availableStart || '無資料') + '～' + esc(data.availableEnd || '無資料') + '；完整歷史依現有資料範圍提供，尚未核對的日期不納入事件統計。</span></p><div class="ke-kpis"><div><span class="ke-muted">研究標的</span><strong>' + esc(data.sym + ' ' + data.name) + '</strong></div><div><span class="ke-muted">期間事件天數（含研究）</span><strong>' + eventRows().length + '</strong></div><div><span class="ke-muted">原六種規則可判定日數</span><strong>' + data.eligibleDays + '</strong></div><div><span class="ke-muted">時間軸日數</span><strong>' + data.timelineDays + '</strong></div></div>' + researchSection() +
      '<section><h3>歷史 K 線與成交量</h3><p class="ke-muted">點選 K 線或黃色點可查看當日依據。紅漲綠跌；缺值以 × 標示。圖表分段瀏覽，統計維持整個所選期間。</p><div class="ke-nav" data-ke-interactive><label>每段日數<select id="ke-size"><option value="30">30 日</option><option value="60">60 日</option><option value="120">120 日</option></select></label><button id="ke-first">最早</button><button id="ke-prev">上一段</button><button id="ke-next">下一段</button><button id="ke-last">最新</button><label>跳至日期<input id="ke-jump" type="date"></label><button id="ke-jump-go">前往日期</button></div><label class="ke-timeline" data-ke-interactive>歷史時間軸<input id="ke-position" type="range" min="0" step="1" value="0"></label><p id="ke-visible" class="ke-muted" aria-live="polite"></p><div id="ke-chart" class="ke-scroll"></div><div id="ke-detail" class="ke-detail" aria-live="polite"></div></section>' +
      '<section><h3>特殊事件與後續表現</h3><div class="ke-nav" data-ke-interactive><button id="ke-event-prev">上一頁事件</button><span id="ke-event-page" aria-live="polite"></span><button id="ke-event-next">下一頁事件</button></div><div id="ke-events" class="ke-scroll"></div><p class="ke-muted">包含原六種規則與研究首次觀察事件。資料不足的原因可點選該日查看；缺值與未成熟報酬皆不補零。下載報告包含所選期間全部事件與研究證據。</p></section>' +
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
    if (controller) controller.abort(); const request = controller = new AbortController();
    $('ke-load').disabled = true; $('ke-export').disabled = true; $('ke-result').innerHTML = ''; $('ke-status').textContent = '正在讀取已核對日線與事件統計…';
    const timer = setTimeout(() => request.abort(), 20000);
    try {
      const response = await fetch('/kline-events?' + params, { signal: request.signal });
      if (!response.ok) throw new Error(response.status === 400 ? '期間或日期無效，請確認開始日不晚於截至日，且不超過最新已完成交易日。' : '事件資料尚未完整建立，請檢查日線更新狀態。');
      const result = await response.json();
      if (serial !== generation || !dialog.open) return;
      data = result; render();
    } catch (error) {
      if (serial === generation && dialog.open) { $('ke-status').className = 'ke-state ke-warn'; $('ke-status').textContent = error.name === 'AbortError' ? '讀取逾時，請重新載入。' : error.message; }
    } finally { clearTimeout(timer); if (serial === generation) $('ke-load').disabled = false; }
  }
  function download() {
    if (!data) return;
    const copy = $('ke-result').cloneNode(true);
    copy.querySelector('#ke-events').innerHTML = eventTable(eventRows());
    if (researchRules().length) {
      const evidence = document.createElement('section');
      evidence.innerHTML = '<h3>研究期間完整每日證據</h3><p class="ke-muted">每日條件與首次事件分開列出；不可判定不等於條件未符合。價格為原始日線口徑，所有高點區間排除當日。</p><div class="ke-scroll"><table class="ke-research-table"><thead><tr><th>日期</th><th>規則判定</th><th>首次事件</th><th>數值依據</th></tr></thead><tbody>' + data.candles.map(row => '<tr><td>' + esc(row.date) + '</td><td class="ke-wrap">' + researchRules().map(rule => esc(rule.label + '：' + researchCondition(row.research || {}, rule.key) + '；' + (((row.research || {}).reason || {})[rule.key] || ''))).join('<br>') + '</td><td class="ke-wrap">' + esc(researchSignals(row).map(label).join('、') || '無新增觀察事件') + '</td><td class="ke-wrap">' + esc(researchEvidence(row.research || {})) + '</td></tr>').join('') + '</tbody></table></div>';
      copy.appendChild(evidence);
    }
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

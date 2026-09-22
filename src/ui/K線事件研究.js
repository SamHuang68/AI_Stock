/* 官方日線事件研究：圖表、品質及統計使用同一份資料。 */
(function () {
  'use strict';
  let dialog, controller, priorFocus, data, generation = 0, viewStart = 0, viewSize = 30, eventPage = 0, executionPage = 0, priceBasis = 'adjusted', selectedDay = null;
  const EVENT_PAGE_SIZE = 50;
  const $ = id => document.getElementById(id);
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const number = v => typeof v === 'number' && Number.isFinite(v);
  const fmt = (v, n = 2) => number(v) ? v.toLocaleString('zh-TW', { maximumFractionDigits: n }) : '未提供';
  const pct = (v, n = 2) => number(v) ? (v > 0 ? '+' : '') + fmt(v, n) + '%' : '資料不足';
  const hasAdjusted = () => Boolean(data.research && data.research.adjusted);
  const activeBasis = () => priceBasis === 'adjusted' && hasAdjusted() ? 'adjusted' : 'raw';
  const basisLabel = basis => basis === 'adjusted' ? '官方參考價調整比較' : '原始價格（保守排除）';
  const selectedResearch = () => activeBasis() === 'adjusted' ? data.research.adjusted : data.research;
  const rowResearch = row => activeBasis() === 'adjusted' ? row.adjustedResearch : row.research;
  const researchRules = () => selectedResearch() && Array.isArray(selectedResearch().rules) ? selectedResearch().rules : [];
  const label = key => ([...(data.rules || []), ...researchRules()].find(r => r.key === key) || {}).label || key;
  const researchSignals = row => rowResearch(row) && Array.isArray(rowResearch(row).signals) ? rowResearch(row).signals : [];
  const eventSignals = row => [...(row.signals || []), ...researchSignals(row)];
  const eventRows = () => data.candles.filter(row => eventSignals(row).length).slice().reverse();
  const METRICS = [
    ['priorHigh20', '前 20 日高點', false], ['priorHigh120', '前 120 日高點', false],
    ['priorHigh252', '前 252 日高點', false], ['maxDrawdown100Pct', '前 100 日最大回撤幅度', true],
    ['distance252HighPct', '距前 252 日高點', true]
  ];
  const researchCondition = (row, key) => row.conditions && row.conditions[key] === true ? '符合' : row.conditions && row.conditions[key] === false ? '未符合' : '不可判定';
  const evidenceText = value => value == null ? '未提供' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const researchEvidence = row => {
    const metrics = row.metrics || {}, anchor = row.anchorDate || (row.comparisonEvidence || {}).anchorDate;
    const rawHighs = row.rawPriorHighs || metrics.rawPriorHighs || Object.fromEntries([20, 120, 252].filter(h => metrics['rawPriorHigh' + h] !== undefined).map(h => ['前 ' + h + ' 日原始高點', metrics['rawPriorHigh' + h]]));
    return METRICS.map(([key, name, percentage]) => {
      const value = metrics[key];
      return name + ' ' + (key === 'maxDrawdown100Pct' ? number(value) ? fmt(value) + '%' : '資料不足' : percentage ? pct(value) : fmt(value));
    }).join('；') + (anchor ? '；價格比較基準日 ' + anchor : '') + (row.priceBasis ? '；價格口徑 ' + row.priceBasis : '') +
      (Object.keys(rawHighs).length ? '；對照原始高點 ' + evidenceText(rawHighs) : '');
  };
  const CSS = `
    #ke-dialog{width:min(1180px,96vw);max-height:94vh;max-height:94dvh;margin:auto;inset:0;padding:0;border:1px solid #526179;border-radius:10px;background:#101827;color:#e2e8f0;font:15px/1.65 system-ui,"Microsoft JhengHei UI",sans-serif;overflow:auto;scroll-padding-top:110px;scroll-padding-bottom:16px}
    #ke-dialog::backdrop{background:rgba(2,6,23,.78)}#ke-dialog *{box-sizing:border-box}#ke-dialog h2{font-size:23px;line-height:1.35;margin:0;font-weight:600}#ke-dialog h3{font-size:18px;margin:0 0 10px;font-weight:600}
    #ke-dialog .ke-head{position:sticky;top:0;z-index:2;background:#101827;border-bottom:1px solid #334155;padding:16px 20px;display:flex;justify-content:space-between;align-items:center;gap:12px}#ke-dialog .ke-content{padding:18px 20px;min-width:0}
    #ke-dialog .ke-muted{color:#b0bfd2;font-size:13px}#ke-dialog section{border-top:1px solid #334155;padding:18px 0}#ke-dialog .ke-fields{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-bottom:16px}#ke-dialog label{display:flex;flex-direction:column;gap:4px;min-width:0}
    #ke-dialog input,#ke-dialog select,#ke-dialog button{font:inherit;color:#f1f5f9;background:#23314a;border:1px solid #64748b;border-radius:5px;padding:7px 11px;min-height:40px;scroll-margin-block:8px}#ke-dialog input{width:164px;background:#0b1220}#ke-dialog button{cursor:pointer}#ke-dialog button:disabled{opacity:.55;cursor:default}#ke-dialog :focus-visible{outline:2px solid #fbd45a;outline-offset:3px}
    #ke-dialog .ke-state{padding:10px 14px;background:#19283b;border-left:3px solid #71ece3;margin-bottom:14px;overflow-wrap:anywhere}#ke-dialog .ke-warn{border-left-color:#fbd45a;background:#302a1c}#ke-dialog .ke-kpis{display:flex;flex-wrap:wrap;gap:12px 36px;margin:14px 0}#ke-dialog .ke-kpis strong{display:block;font-size:24px;font-weight:600;color:#f8fafc}
    #ke-dialog .ke-scroll{max-width:100%;overflow:auto;border:1px solid #334155;border-radius:7px;background:#111d2f}#ke-dialog svg{display:block;width:100%;min-width:740px}#ke-dialog svg text{font-family:inherit;font-size:13px;fill:#b0bfd2}#ke-dialog [data-ke-day]{cursor:pointer}#ke-dialog svg [data-ke-day]:focus{outline:none}#ke-dialog svg [data-ke-day]:focus .ke-hit{stroke:#fbd45a;stroke-width:2}
    #ke-dialog table{border-collapse:collapse;width:100%;font-size:14px;min-width:780px}#ke-dialog th,#ke-dialog td{text-align:right;padding:11px 12px;border-bottom:1px solid #334155;vertical-align:top;white-space:nowrap}#ke-dialog th{color:#b0bfd2;font-weight:500}#ke-dialog td:first-child,#ke-dialog th:first-child{text-align:left}#ke-dialog td.ke-wrap{white-space:normal;min-width:190px;text-align:left}#ke-dialog td small{display:block;color:#b0bfd2}#ke-dialog .ke-pos{color:#ff858c}#ke-dialog .ke-neg{color:#55dcc4}
    #ke-dialog .ke-detail{background:#19283b;padding:14px 16px;margin:12px 0;border-radius:6px;scroll-margin-top:88px}#ke-dialog .ke-detail:empty{display:none}#ke-dialog details{margin-top:14px}#ke-dialog summary{cursor:pointer;color:#dce6f4}#ke-dialog ul{padding-left:22px}#ke-dialog li{margin:7px 0}#ke-dialog .ke-inline{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px}
    #ke-dialog [hidden]{display:none!important}#ke-dialog .ke-nav{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}#ke-dialog .ke-nav label{margin-right:6px}#ke-dialog .ke-timeline{width:100%;margin:10px 0}#ke-dialog .ke-timeline input{width:100%;padding:0;accent-color:#fbd45a}#ke-dialog .ke-scope{overflow-wrap:anywhere}#ke-dialog .ke-selected .ke-hit{stroke:#fbd45a;stroke-width:1.5}
    #ke-dialog .ke-research-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}#ke-dialog .ke-research-card{min-width:0;padding:12px;border:1px solid #475569;border-radius:6px;background:#19283b;overflow-wrap:anywhere}#ke-dialog .ke-research-card h4{font-size:14px;line-height:1.5;margin:0 0 8px}#ke-dialog .ke-research-card p{margin:5px 0;font-size:13px}#ke-dialog .ke-evidence{font-size:13px;overflow-wrap:anywhere}#ke-dialog .ke-detail{overflow-wrap:anywhere}#ke-dialog .ke-head>div{min-width:0}#ke-dialog .ke-head>button{flex-shrink:0}#ke-dialog .ke-fields select{max-width:100%}#ke-dialog .ke-research-table td.ke-wrap{min-width:210px;max-width:420px;overflow-wrap:anywhere}#ke-dialog a{color:#93c5fd;text-underline-offset:3px}
    #ke-dialog .ke-execution{min-width:0;overflow-wrap:anywhere}#ke-dialog .ke-execution h4{font-size:15px;margin:16px 0 8px}#ke-dialog .ke-execution .ke-nav{align-items:end}#ke-dialog .ke-execution .ke-nav>label{flex:0 1 240px;max-width:100%}#ke-dialog .ke-execution select{max-width:100%;font-size:13px}#ke-dialog .ke-execution table{font-size:13px}#ke-dialog .ke-execution th,#ke-dialog .ke-execution td{padding:9px 10px}#ke-dialog .ke-execution td.ke-wrap{min-width:170px;max-width:320px;overflow-wrap:anywhere}#ke-dialog .ke-execution summary{line-height:1.6}#ke-dialog .ke-execution .ke-state p{margin:4px 0}#ke-dialog .ke-execution .ke-scroll{margin:8px 0 12px}
    #ke-dialog .ke-basis{min-width:0;overflow-wrap:anywhere}#ke-dialog .ke-basis select{width:100%;max-width:100%;font-size:13px}#ke-dialog .ke-basis label{width:min(100%,330px)}#ke-dialog .ke-payload{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.7 ui-monospace,monospace;margin:8px 0;padding:10px;background:#0b1220;border-radius:5px}#ke-dialog .ke-adjustment{min-width:0;overflow-wrap:anywhere}#ke-dialog .ke-adjustment details{padding:8px 10px;border:1px solid #334155;border-radius:5px}#ke-dialog .ke-adjustment p{margin:6px 0}
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
    const research = rowResearch(r);
    if (index < viewStart || index >= viewStart + viewSize) { viewStart = index - Math.floor(viewSize / 2); renderChart(); }
    selectedDay = day;
    $('ke-chart').querySelectorAll('[data-ke-day]').forEach(el => el.classList.toggle('ke-selected', el.dataset.keDay === day));
    $('ke-detail').innerHTML = '<strong>' + esc(r.date) + '｜' + esc(eventSignals(r).map(label).join('、') || r.reason) + '</strong><div>' + esc(r.reason) + '</div><div class="ke-muted">開 ' + fmt(r.open) + '・高 ' + fmt(r.high) + '・低 ' + fmt(r.low) + '・收 ' + fmt(r.close) + '・成交 ' + fmt(r.volume, 0) + ' 股</div>' +
      (r.metrics ? '<div>實體 ' + pct(r.metrics.bodyPct, 4) + '・量比 ' + fmt(r.metrics.volumeRatio, 3) + ' 倍・前 20 日高／低 ' + fmt(r.metrics.priorHigh) + '／' + fmt(r.metrics.priorLow) + '</div>' : '') +
      (research ? '<div class="ke-evidence"><strong>突破位置研究・' + esc(basisLabel(activeBasis())) + '</strong><ul>' + researchRules().map(rule => '<li>' + esc(rule.label + '：當日條件' + researchCondition(research, rule.key) + '；' + (researchSignals(r).includes(rule.key) ? '本日新增觀察事件' : '本日未新增觀察事件') + '。' + ((research.reason || {})[rule.key] || '')) + '</li>').join('') + '</ul><p>' + esc(researchEvidence(research)) + '</p>' + rowAdjustmentEvidence(research) + '</div>' : '') +
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
    selectedDay = null;
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
    if ($('ke-research-stats')) $('ke-research-stats').innerHTML = statsTable(selectedResearch().stats || [], h);
  }
  function evidenceLink(value) {
    try {
      const url = new URL(String(value));
      if (url.protocol === 'https:' || url.protocol === 'http:') return '<a href="' + esc(url.href) + '" target="_blank" rel="noopener noreferrer">' + esc(value) + '</a>';
    } catch (_) { /* 未核對網址只顯示文字。 */ }
    return esc(evidenceText(value));
  }
  function rowAdjustmentEvidence(row) {
    const evidence = row.comparisonEvidence || row.adjustmentEvidence;
    return evidence ? '<details><summary>本日比較窗口的完整調整證據</summary><pre class="ke-payload">' + esc(evidenceText(evidence)) + '</pre></details>' : '';
  }
  function adjustmentEvidence() {
    if (activeBasis() !== 'adjusted') return '<p class="ke-muted">本模式直接使用原始價格比較，跨公司行動的觀察窗口保守排除。原始價格研究及影子紀錄維持原版本。</p>';
    const research = selectedResearch(), evidence = research.adjustmentEvidence || {}, coverage = evidence.coverage || {};
    return '<div class="ke-adjustment"><p class="ke-state ke-warn">調整僅用於突破位置與高點比較；K 線、成交開盤與收盤價格仍為原始日線。這不是含息總報酬，也不是官方發布的還原日線；跨公司行動的持有期仍排除。歷史結果採目前已核對版本，不能視為事件當時已取得的證據。</p><details><summary>官方參考價基準、涵蓋與全部來源事件</summary><p class="ke-evidence">比較口徑：' + esc(research.priceBasis || 'twse-reference-comparison') + '；規則版本：' + esc(research.version || '未提供') + '。各觀察日只使用當日以前已生效的因子。</p><p class="ke-evidence">來源涵蓋：' + esc(coverage.start || '尚未建立') + '～' + esc(coverage.end || '尚未建立') + '；涵蓋版本：' + esc(coverage.version || '未提供') + '</p><pre class="ke-payload">' + esc(evidenceText(coverage.sources)) + '</pre><ul>' + (evidence.notes || []).map(note => '<li>' + esc(note) + '</li>').join('') + '</ul>' + (Array.isArray(evidence.events) && evidence.events.length ? evidence.events.map(event => '<details><summary>' + esc((event.date || '日期未提供') + '｜' + (event.kind || '事件類型未提供') + '｜' + (event.status || '狀態未提供')) + '</summary><p>本機價格核對：' + (event.verified === true ? '已核對通過' : event.verified === false ? '核對未通過' : '尚未核對') + '。' + esc(event.verificationReason || (event.verified === true ? '官方事件與本機價格一致。' : '尚無核對通過的依據。')) + '</p><p>來源解析狀態：' + esc(event.status || '未提供') + '；' + esc(event.reason || '沒有額外狀態說明') + '</p><p>事件前價格 ' + fmt(event.before, 6) + '；參考價 ' + fmt(event.after, 6) + '；比較因子 ' + fmt(event.factor, 12) + '</p><p class="ke-evidence">來源網址：' + evidenceLink(event.sourceUrl) + '</p><p class="ke-evidence">回應雜湊：' + esc(event.sourceHash || '未提供') + '；擷取時間：' + esc(event.retrievedAt || '未提供') + '；解析版本：' + esc(event.version || '未提供') + '</p><pre class="ke-payload">' + esc(evidenceText(event.payload)) + '</pre></details>').join('') : '<p>尚無來源事件明細；請併看涵蓋狀態與不可判定原因，不能據此認定期間沒有公司行動。</p>') + '</details></div>';
  }
  function basisSection() {
    return '<div class="ke-basis"><div class="ke-nav" data-ke-interactive><label>價格比較基準<select id="ke-basis"><option value="raw">原始價格（保守排除）</option><option value="adjusted"' + (hasAdjusted() ? '' : ' disabled') + '>官方參考價調整比較</option></select></label></div><p id="ke-basis-status" class="ke-state' + (hasAdjusted() ? '' : ' ke-warn') + '" role="status">' + (hasAdjusted() ? '目前使用：' + esc(basisLabel(activeBasis())) + '。切換只改變研究比較，沿用本次已載入資料。' : '目前回應未提供官方參考價調整研究，已回退原始價格（保守排除）。') + ' 原六種事件與圖表 OHLC 維持原始價格。</p></div>';
  }
  function dailyResearchEvidence() {
    return '<h3>' + esc(basisLabel(activeBasis())) + '：研究期間完整每日證據</h3><p class="ke-muted">每日條件與首次事件分開列出；不可判定不等於條件未符合。圖表及成交價保持原始日線，所有高點區間排除當日；調整模式以每個觀察日為自己的比較基準日。</p><div class="ke-scroll"><table class="ke-research-table"><thead><tr><th>日期</th><th>規則判定</th><th>首次事件</th><th>數值依據與基準</th></tr></thead><tbody>' + data.candles.map(row => {
      const research = rowResearch(row) || {};
      return '<tr><td>' + esc(row.date) + '</td><td class="ke-wrap">' + researchRules().map(rule => esc(rule.label + '：' + researchCondition(research, rule.key) + '；' + ((research.reason || {})[rule.key] || ''))).join('<br>') + '</td><td class="ke-wrap">' + esc(researchSignals(row).map(label).join('、') || '無新增觀察事件') + '</td><td class="ke-wrap">' + esc(researchEvidence(research)) + rowAdjustmentEvidence(research) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
  }
  function allResearchExport() {
    const selected = priceBasis;
    try {
      return ['raw', ...(hasAdjusted() ? ['adjusted'] : [])].map(basis => {
        priceBasis = basis;
        return '<section class="ke-basis"><h2>價格比較基準：' + esc(basisLabel(basis)) + '</h2>' + adjustmentEvidence() + researchSection(true).replace(' id="ke-research"', '') + dailyResearchEvidence() + (executionData() ? '<section class="ke-execution">' + executionExport() + '</section>' : '<p>此價格基準尚未提供固定持有研究。</p>') + '</section>';
      }).join('');
    } finally { priceBasis = selected; }
  }
  const EXECUTION_COSTS = [['baseNet', '基準淨報酬'], ['stressNet', '壓力淨報酬'], ['gross', '未扣成本報酬']];
  const executionData = () => selectedResearch() && selectedResearch().execution;
  const executionRules = () => executionData() && Array.isArray(executionData().rules) ? executionData().rules : [];
  const executionAt = (rule, h) => (rule.horizons || {})[h] || {};
  const executionCostLabel = cost => (EXECUTION_COSTS.find(item => item[0] === cost) || [])[1] || cost;
  const ratio = value => number(value) ? fmt(value) + '%' : '資料不足';
  const reasonList = reasons => Array.isArray(reasons) && reasons.length ? '<ul>' + reasons.map(item => '<li>' + esc(item.reason || '原因未提供') + '（' + fmt(item.count, 0) + ' 筆）</li>').join('') + '</ul>' : '<p class="ke-muted">沒有列出排除原因。</p>';
  const executionRows = h => executionRules().flatMap(rule => (executionAt(rule, h).trades || []).map(trade => ({ ...trade, ruleLabel: rule.label }))).sort((a, b) => String(b.signalDate).localeCompare(String(a.signalDate)));
  function executionAssumptions() {
    const ex = executionData(), a = ex.assumptions || {};
    return '<div class="ke-state ke-warn"><p><strong>隔日開盤、固定持有的歷史研究；非實際成交紀錄，也不是文章策略完整重現。</strong></p><p>訊號比較基準：' + esc(basisLabel(activeBasis())) + '。進出價格一律採原始開盤與收盤，跨公司行動的持有期仍排除，未含股息。</p><p>進場：' + esc(a.entry || '未提供') + '。出場：' + esc(a.exit || '未提供') + '。</p><p>基準成本每邊 ' + ratio(a.baseCostPerSidePct) + '；壓力成本每邊 ' + ratio(a.stressCostPerSidePct) + '。' + esc(a.costNote || '成本假設未提供') + '</p></div><p class="ke-evidence">研究版本：' + esc(ex.version || '未提供') + '；固定持有 1／3／5／10 個市場交易日。1 日代表下一交易日開盤進場、同日收盤出場。未建立 VIDYA、停損或複利投資組合；不據此判定策略優勢。</p><ul class="ke-evidence">' + (a.notes || []).map(note => '<li>' + esc(note) + '</li>').join('') + '</ul>';
  }
  function executionCounts(h) {
    return '<h4>訊號與可用樣本</h4><p class="ke-muted">成熟、未成熟及排除分開列示。可判定日數為 0 時，零訊號代表資料不足，不能解讀為沒有觸發機會。</p><div class="ke-scroll" tabindex="0" aria-label="訊號與可用樣本，可水平捲動"><table><thead><tr><th>研究規則</th><th>可判定日數</th><th>首次訊號</th><th>成熟</th><th>未成熟</th><th>排除</th><th>非重疊</th><th>重疊排除</th></tr></thead><tbody>' + executionRules().map(rule => {
      const count = executionAt(rule, h).counts || {};
      return '<tr><td class="ke-wrap">' + esc(rule.label) + (rule.eligibleDays === 0 ? '<small>資料不足，無法判定訊號</small>' : '') + '</td>' + [rule.eligibleDays, count.signals, count.mature, count.immature, count.excluded, count.nonOverlapping, count.overlapExcluded].map(value => '<td>' + fmt(value, 0) + '</td>').join('') + '</tr>';
    }).join('') + '</tbody></table></div>';
  }
  function executionDistributions(h, cost) {
    return '<h4>' + esc(executionCostLabel(cost)) + '分布</h4><p class="ke-muted">全部成熟樣本與非重疊樣本分開比較。第 5 百分位與最低／最高僅描述現有樣本，不是尾端風險預測；小樣本不足以確認穩定性。</p><div class="ke-scroll" tabindex="0" aria-label="固定持有報酬分布，可水平捲動"><table><thead><tr><th>研究規則</th><th>樣本口徑</th><th>樣本數</th><th>平均</th><th>中位數</th><th>正報酬比例</th><th>第 5 百分位</th><th>中間 50%</th><th>最低／最高</th></tr></thead><tbody>' + executionRules().map(rule => ['raw', 'nonOverlapping'].map(kind => {
      const group = executionAt(rule, h)[kind] || {}, s = group[cost] || {};
      return '<tr><td class="ke-wrap">' + esc(rule.label) + '</td><td>' + (kind === 'raw' ? '全部成熟' : '非重疊') + '</td><td>' + fmt(s.n, 0) + (s.smallSample ? '<small>小樣本</small>' : '') + '</td>' + cell(s.mean) + cell(s.median) + '<td>' + ratio(s.positivePct) + '</td>' + cell(s.p05) + '<td>' + pct(s.q25) + '～' + pct(s.q75) + '</td><td>' + pct(s.min) + '／' + pct(s.max) + '</td></tr>';
    }).join('')).join('') + '</tbody></table></div>';
  }
  function executionRandom(h, cost) {
    return '<h4>同股票、同年份隨機進場對照・' + esc(executionCostLabel(cost)) + '</h4><p class="ke-muted">依成熟訊號的各年筆數，從同股票、同年份合格候選抽取相同筆數；固定種子重抽 1,000 組。下表為每組平均報酬的分布，候選可能重疊；「不低於訊號的比例」不是 p 值，也不代表策略成功機率。</p><div class="ke-scroll" tabindex="0" aria-label="分層隨機對照，可水平捲動"><table><thead><tr><th>研究規則／狀態</th><th>每組樣本數</th><th>抽樣組數</th><th>訊號平均</th><th>隨機平均的中位數</th><th>隨機平均的 2.5%～97.5% 分位</th><th>不低於訊號的比例</th></tr></thead><tbody>' + executionRules().map(rule => {
      const r = executionAt(rule, h).random || {}, m = (r.metrics || {})[cost] || {};
      return '<tr><td class="ke-wrap">' + esc(rule.label) + '<small>' + esc(r.status || '資料不足，無法比較') + '</small>' + (r.n === 0 ? '<small>無成熟樣本，無法比較</small>' : '') + '</td><td>' + fmt(r.n, 0) + '</td><td>' + fmt(r.draws, 0) + '</td>' + cell(m.signalMean) + cell(m.median) + '<td>' + pct(m.p025) + '～' + pct(m.p975) + '</td><td>' + ratio(m.atLeastSignalPct) + '</td></tr>';
    }).join('') + '</tbody></table></div>';
  }
  function executionBenchmark(h, cost) {
    return '<h4>同日進出 0050 配對對照・' + esc(executionCostLabel(cost)) + '</h4><p class="ke-muted">只比較股票與 0050 都有完整、可核對進出資料的同一組交易；缺漏不補零。平均超額及超額中位數單位為百分點，未含股息。</p><div class="ke-scroll" tabindex="0" aria-label="0050 配對對照，可水平捲動"><table><thead><tr><th>研究規則</th><th>股票成熟數</th><th>配對數</th><th>缺漏／排除</th><th>配對股票平均</th><th>配對 0050 平均</th><th>平均超額</th><th>超額中位數</th></tr></thead><tbody>' + executionRules().map(rule => {
      const b = executionAt(rule, h).benchmark || {}, stock = (b.stock || {})[cost] || {}, benchmark = (b.benchmark || {})[cost] || {}, excess = (b.excess || {})[cost] || {};
      return '<tr><td class="ke-wrap">' + esc(rule.label) + (b.pairedCount === 0 ? '<small>沒有可配對樣本，無法比較</small>' : '') + '</td><td>' + fmt(b.eligibleStockCount, 0) + '</td><td>' + fmt(b.pairedCount, 0) + (excess.smallSample ? '<small>小樣本</small>' : '') + '</td><td>' + fmt(b.excludedCount, 0) + '</td>' + cell(stock.mean) + cell(benchmark.mean) + cell(excess.mean, '配對股票減去 0050，單位為百分點') + cell(excess.median, '逐筆配對差額中位數，單位為百分點') + '</tr>';
    }).join('') + '</tbody></table></div>';
  }
  function executionReasons(h) {
    return '<details><summary>完整不可判定、排除理由與隨機配對前提</summary>' + executionRules().map(rule => {
      const item = executionAt(rule, h), random = item.random || {}, benchmark = item.benchmark || {};
      return '<h4>' + esc(rule.label) + '</h4><p>訊號不可判定日期的原因：</p>' + reasonList(rule.ineligibleReasons) + '<p>固定持有交易排除原因：</p>' + reasonList(item.excludedReasons) + '<p>0050 配對缺漏／排除原因：</p>' + reasonList(benchmark.excludedReasons) + '<p class="ke-evidence">' + esc(benchmark.note || '0050 配對前提未提供') + '</p><p class="ke-evidence">隨機對照：' + esc(random.note || '前提未提供') + '；固定種子：' + esc(random.seed || '未建立') + '</p><ul>' + (random.yearStrata || []).map(stratum => '<li>' + esc(stratum.year) + ' 年：訊號 ' + fmt(stratum.signals, 0) + ' 筆；合格候選 ' + fmt(stratum.candidates, 0) + ' 日' + (stratum.candidates === 0 ? '，資料不足，無法比較' : '') + '</li>').join('') + '</ul>';
    }).join('') + '<p class="ke-muted">未成熟交易及個別缺漏原因保留於下方逐筆明細；同一天可能因不同規則列為不同筆研究觀察。</p></details>';
  }
  function executionTradeTable(rows) {
    const status = value => value === 'mature' ? '成熟' : value === 'immature' ? '未成熟' : value === 'excluded' ? '排除' : '不可判定';
    return '<table><thead><tr><th>訊號日／規則</th><th>進場日／開盤</th><th>出場日／收盤</th><th>狀態／理由</th><th>未扣成本</th><th>基準淨報酬</th><th>壓力淨報酬</th><th>非重疊納入</th><th>0050 配對狀態／理由</th><th>0050 開盤／收盤</th><th>0050 未扣成本</th><th>0050 基準</th><th>0050 壓力</th></tr></thead><tbody>' + (rows.length ? rows.map(row => {
      const b = row.benchmark || {};
      return '<tr><td class="ke-wrap">' + esc(row.signalDate || '日期未提供') + '<small>' + esc(row.ruleLabel) + '・' + fmt(row.horizon, 0) + ' 日</small></td><td>' + esc(row.entryDate || '尚未確定') + '<small>' + fmt(row.entryPrice) + '</small></td><td>' + esc(row.exitDate || '尚未成熟') + '<small>' + fmt(row.exitPrice) + '</small></td><td class="ke-wrap">' + status(row.status) + '<small>' + esc(row.reason || (row.status === 'mature' ? '符合固定持有資料條件' : '原因未提供')) + '</small></td>' + cell(row.gross) + cell(row.baseNet) + cell(row.stressNet) + '<td>' + (row.status === 'mature' ? row.nonOverlapping === true ? '納入' : row.nonOverlapping === false ? '重疊排除' : '未提供' : '不適用') + '</td><td class="ke-wrap">' + status(b.status) + '<small>' + esc(b.reason || (b.status === 'mature' ? '進出日期與股票一致' : '配對資料未提供')) + '</small><small>' + esc((b.entryDate || '進場日期未提供') + '～' + (b.exitDate || '出場日期未提供')) + '</small></td><td>' + fmt(b.entryPrice) + '／' + fmt(b.exitPrice) + '</td>' + cell(b.gross) + cell(b.baseNet) + cell(b.stressNet) + '</tr>';
    }).join('') : '<tr><td colspan="13">本期沒有首次訊號交易明細；請同時查看可判定日數與完整資料缺漏原因，不能據此認定沒有進場機會。</td></tr>') + '</tbody></table>';
  }
  function executionSection() {
    if (!executionData()) return '';
    return '<section id="ke-execution" class="ke-execution"><h3>隔日開盤固定持有研究</h3>' + executionAssumptions() + '<div class="ke-nav" data-ke-interactive><label>固定持有期<select id="ke-execution-horizon">' + [1, 3, 5, 10].map(h => '<option value="' + h + '"' + (h === 5 ? ' selected' : '') + '>' + h + ' 個交易日' + (h === 1 ? '（進場當日收盤）' : '') + '</option>').join('') + '</select></label><label>報酬成本口徑<select id="ke-execution-cost">' + EXECUTION_COSTS.map(([key, name]) => '<option value="' + key + '">' + name + '</option>').join('') + '</select></label></div><p id="ke-execution-scope" class="ke-muted" aria-live="polite"></p><div id="ke-execution-results"></div><details><summary>逐筆固定持有明細（包含未成熟、排除及 0050 缺漏）</summary><div class="ke-nav" data-ke-interactive><button id="ke-execution-prev">上一頁交易</button><span id="ke-execution-page" aria-live="polite"></span><button id="ke-execution-next">下一頁交易</button></div><div id="ke-execution-trades" class="ke-scroll" tabindex="0" aria-label="逐筆固定持有研究，可水平捲動"></div><p class="ke-muted">下載 HTML 報告保留全部持有期、三種成本口徑與所有逐筆明細，不受目前分頁限制。</p></details></section>';
  }
  function renderExecutionTrades() {
    const rows = executionRows($('ke-execution-horizon').value), pages = Math.max(1, Math.ceil(rows.length / EVENT_PAGE_SIZE));
    executionPage = Math.max(0, Math.min(pages - 1, executionPage));
    $('ke-execution-trades').innerHTML = executionTradeTable(rows.slice(executionPage * EVENT_PAGE_SIZE, (executionPage + 1) * EVENT_PAGE_SIZE));
    $('ke-execution-page').textContent = '第 ' + (executionPage + 1) + '／' + pages + ' 頁，共 ' + rows.length + ' 筆（由新到舊）';
    $('ke-execution-prev').disabled = executionPage === 0; $('ke-execution-next').disabled = executionPage === pages - 1;
  }
  function renderExecution() {
    if (!executionData()) return;
    const h = $('ke-execution-horizon').value, cost = $('ke-execution-cost').value;
    $('ke-execution-scope').textContent = '目前顯示：固定持有 ' + h + ' 個交易日・' + executionCostLabel(cost) + '；研究截至 ' + data.asOf + '。';
    $('ke-execution-results').innerHTML = executionCounts(h) + executionDistributions(h, cost) + executionRandom(h, cost) + executionBenchmark(h, cost) + executionReasons(h);
    renderExecutionTrades();
  }
  function executionExport() {
    return '<h3>隔日開盤固定持有研究：完整期數與成本口徑</h3>' + executionAssumptions() + [1, 3, 5, 10].map(h => '<section><h3>固定持有 ' + h + ' 個交易日</h3>' + executionCounts(h) + EXECUTION_COSTS.map(([cost]) => executionDistributions(h, cost) + executionRandom(h, cost) + executionBenchmark(h, cost)).join('') + executionReasons(h) + '<h4>本期全部逐筆明細</h4><div class="ke-scroll">' + executionTradeTable(executionRows(h)) + '</div></section>').join('');
  }
  function researchSection(exportAll = false) {
    if (!researchRules().length) return '';
    const research = selectedResearch(), latest = research.latest || {}, signals = latest.signals || [];
    const shadow = research.shadow, writer = shadow && shadow.writer;
    return '<section id="ke-research"><h3>突破位置與修復風險觀察</h3><p class="ke-muted">研究標籤與影子紀錄，不加入買進分數、不自動下單。正報酬不等於進場優勢；本頁工程觀察不代表已重現文章策略。</p>' +
      '<div class="ke-state' + (!latest.date || researchRules().some(rule => !(latest.eligible || {})[rule.key]) ? ' ke-warn' : '') + '">資料基準：' + esc(latest.date || '無可用交易日') + '；最近已完成交易日：' + esc(data.freshness.expectedSession || '待核對') + '。以本次截至日期以前的已完成日線分析；休市沿用最近已完成交易日，歷史查詢保留當時日期前提。</div>' +
      '<div class="ke-research-grid">' + researchRules().map(rule => '<article class="ke-research-card"><h4>' + esc(rule.label) + '</h4><p><strong>當日條件：' + researchCondition(latest, rule.key) + '</strong></p><p>' + (signals.includes(rule.key) ? '本日新增觀察事件' : '本日未新增觀察事件') + '；首次事件判定：' + ((latest.eligible || {})[rule.key] ? '可判定' : '不可判定') + '</p><p class="ke-muted">' + esc((latest.reason || {})[rule.key] || '請查看規則與判定依據。') + '</p></article>').join('') + '</div>' +
      '<p class="ke-evidence">' + esc(researchEvidence(latest)) + '</p>' +
      '<details><summary>研究規則、來源與判定前提</summary><ul>' + researchRules().map(rule => '<li><strong>' + esc(rule.label) + '</strong>：' + esc(rule.formula) + '</li>').join('') + '</ul><p>首次事件只在已能判定的前一交易日未符合、當日符合時成立；連續符合不重複記錄，無法核對前日時不補造事件。</p><p>本階段「修復風險」為工程版：20 日突破、前 100 日最大回撤至少 20%、距前 252 日高點至少低 15%；不是文章 15 日箱型策略的重現。VIDYA 尚未納入。</p><p class="ke-evidence">規則版本：' + esc(research.version || '未提供') + '；資料來源：' + esc(latest.source || '依官方日線品質紀錄') + '；輸入摘要：' + esc(latest.inputDigest || '未提供') + '</p><ul>' + (research.notes || []).map(note => '<li>' + esc(note) + '</li>').join('') + '</ul></details>' +
      '<p class="ke-muted">研究來源（2026 年 9 月 20 日）：<a href="https://blog.fantasymaya.org/posts/right-side-breakout-regime-note/" target="_blank" rel="noopener noreferrer">右側突破的出場回測</a>、<a href="https://blog.fantasymaya.org/posts/entry-signal-cross-validation/" target="_blank" rel="noopener noreferrer">進場策略與隨機比較</a>。本頁為工程觀察規則，不代表已重現文章策略或績效。</p>' +
      '<p class="ke-evidence">影子紀錄：' + (shadow ? esc(shadow.status || '已提供') + '；最近已記錄交易日 ' + esc(shadow.asOf || '尚無紀錄') + '；首次觀測 ' + esc(shadow.observedAt || '尚無紀錄') + '；目前版本觀察日數 ' + fmt(shadow.count, 0) + '（不是訊號數或績效樣本）。' + esc(shadow.note || '') : '尚未提供帳本狀態；歷史事件不視為當時已觀測的前瞻紀錄。') + '</p>' +
      (writer ? '<p class="ke-evidence">最近帳本寫入工作：' + esc(writer.status || '狀態未提供') + '；檢查標的 ' + fmt(writer.checked, 0) + '；新增觀察 ' + fmt(writer.added, 0) + '；失敗 ' + fmt(Array.isArray(writer.failures) ? writer.failures.length : writer.failures, 0) + '；執行時間 ' + esc(writer.observedAt || '未提供') + '。' + esc(writer.reason || '') + '</p>' : '') +
      (shadow && shadow.revised ? '<div class="ke-state ke-warn">目前資料與該日首次觀測不同；影子帳本保留首次證據，未覆寫或回填歷史。</div>' : '') +
      (shadow && shadow.evidence ? '<details><summary>首次觀測證據</summary><p class="ke-evidence">' + esc((shadow.evidence.date || shadow.asOf || '未提供日期') + '；' + researchEvidence(shadow.evidence)) + '</p><ul>' + researchRules().map(rule => '<li>' + esc(rule.label + '：當日條件' + researchCondition(shadow.evidence, rule.key) + '；' + ((shadow.evidence.signals || []).includes(rule.key) ? '新增觀察事件' : '未新增觀察事件') + '。' + ((shadow.evidence.reason || {})[rule.key] || '')) + '</li>').join('') + '</ul><p class="ke-evidence">首次輸入摘要：' + esc(shadow.evidence.inputDigest || '未提供') + '</p>' + rowAdjustmentEvidence(shadow.evidence) + '</details>' : '') +
      '<h3>研究事件後續表現</h3><p class="ke-muted">' + (exportAll ? '以下列出全部四種後續期數。' : '期數跟隨下方「後續交易日」選單。') + '事件日原始收盤至後續原始收盤的描述統計，非隔日開盤交易回測；基準為同期合格日期，非配對隨機進場或 0050。</p>' + (exportAll ? [1, 3, 5, 10].map(h => '<h4>後續 ' + h + ' 個交易日</h4><div class="ke-scroll">' + statsTable(research.stats || [], h) + '</div>').join('') : '<div id="ke-research-stats" class="ke-scroll" tabindex="0" aria-label="研究事件後續表現，可水平捲動"></div>') +
      '<details><summary>研究不可判定日期與原因</summary><ul>' + data.candles.filter(row => rowResearch(row) && researchRules().some(rule => !(rowResearch(row).eligible || {})[rule.key])).map(row => '<li>' + esc(row.date + '：' + researchRules().filter(rule => !(rowResearch(row).eligible || {})[rule.key]).map(rule => rule.label + '／' + ((rowResearch(row).reason || {})[rule.key] || '不可判定')).join('；')) + '</li>').join('') + '</ul></details></section>';
  }
  function render(preserveControls = false) {
    const previous = preserveControls ? { horizon: $('ke-horizon').value, executionHorizon: $('ke-execution-horizon') && $('ke-execution-horizon').value, cost: $('ke-execution-cost') && $('ke-execution-cost').value, day: selectedDay } : null;
    const f = data.freshness;
    $('ke-status').className = 'ke-state' + (f.fresh ? '' : ' ke-warn');
    $('ke-status').textContent = f.status + '｜應有 ' + (f.expectedSession || '待核對') + '；資料最新 ' + (f.latestSession || '無資料') + '。本次研究截至 ' + data.asOf + '。';
    $('ke-result').innerHTML = '<p class="ke-scope"><strong>' + esc(data.range.label) + '：' + esc(data.historyStart || '無資料') + '～' + esc(data.historyEnd || '無資料') + '</strong><br><span class="ke-muted">資料庫現存日線 ' + esc(data.availableStart || '無資料') + '～' + esc(data.availableEnd || '無資料') + '；完整歷史依現有資料範圍提供，尚未核對的日期不納入事件統計。</span></p>' + basisSection() + '<div class="ke-kpis"><div><span class="ke-muted">研究標的</span><strong>' + esc(data.sym + ' ' + data.name) + '</strong></div><div><span class="ke-muted">期間事件天數（含研究）</span><strong>' + eventRows().length + '</strong></div><div><span class="ke-muted">原六種規則可判定日數</span><strong>' + data.eligibleDays + '</strong></div><div><span class="ke-muted">時間軸日數</span><strong>' + data.timelineDays + '</strong></div></div>' + adjustmentEvidence() + researchSection() + executionSection() +
      '<section><h3>歷史 K 線與成交量（原始價格）</h3><p class="ke-muted">點選 K 線或黃色點可查看當日依據。紅漲綠跌；缺值以 × 標示。圖表價格永遠使用原始 OHLC，黃色點依所選研究比較基準更新；原六種事件維持原判定。圖表分段瀏覽，統計維持整個所選期間。</p><div class="ke-nav" data-ke-interactive><label>每段日數<select id="ke-size"><option value="30">30 日</option><option value="60">60 日</option><option value="120">120 日</option></select></label><button id="ke-first">最早</button><button id="ke-prev">上一段</button><button id="ke-next">下一段</button><button id="ke-last">最新</button><label>跳至日期<input id="ke-jump" type="date"></label><button id="ke-jump-go">前往日期</button></div><label class="ke-timeline" data-ke-interactive>歷史時間軸<input id="ke-position" type="range" min="0" step="1" value="0"></label><p id="ke-visible" class="ke-muted" aria-live="polite"></p><div id="ke-chart" class="ke-scroll"></div><div id="ke-detail" class="ke-detail" aria-live="polite"></div></section>' +
      '<section><h3>特殊事件與後續表現</h3><div class="ke-nav" data-ke-interactive><button id="ke-event-prev">上一頁事件</button><span id="ke-event-page" aria-live="polite"></span><button id="ke-event-next">下一頁事件</button></div><div id="ke-events" class="ke-scroll"></div><p class="ke-muted">包含原六種規則與研究首次觀察事件。資料不足的原因可點選該日查看；缺值與未成熟報酬皆不補零。下載報告包含所選期間全部事件與研究證據。</p></section>' +
      '<section><div class="ke-inline"><h3>歷史同型態統計</h3><label>後續交易日<select id="ke-horizon"><option value="1">1 日</option><option value="3">3 日</option><option value="5" selected>5 日</option><option value="10">10 日</option></select></label></div><p class="ke-muted">研究區間 ' + esc(data.historyStart || '尚未建立') + '～' + esc(data.historyEnd || '尚未建立') + '。各期只使用成熟樣本；平均差單位為百分點。</p><div id="ke-stats" class="ke-scroll"></div></section>' +
      '<details><summary>資料品質與不可判定日期</summary><p>官方來源：TWSE／TPEx；成交量統一為股。歷史中尚未官方核對 ' + data.unverifiedRows + ' 筆。</p><p>' + (data.companyActionCoverage ? '公司行動已核對：' + esc(data.companyActionCoverage.start + '～' + data.companyActionCoverage.end + '；' + data.companyActionCoverage.source) : '公司行動尚未完成核對。目前已提供台積電三年研究回補；其他標的需建立完整核對區間後才會產生統計。') + '</p><ul>' + data.candles.filter(r => !r.eligible).map(r => '<li>' + esc(r.date + '：' + r.reason) + '</li>').join('') + '</ul></details>' +
      '<details><summary>六種規則與統計口徑</summary><ul>' + data.rules.map(r => '<li>' + esc(r.label + '：' + r.formula) + '</li>').join('') + '</ul><ul>' + data.notes.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul></details>';
    if (!preserveControls) viewStart = Math.max(0, data.candles.length - viewSize);
    eventPage = 0;
    $('ke-basis').value = activeBasis();
    $('ke-basis').onchange = () => { priceBasis = $('ke-basis').value; render(true); $('ke-basis').focus(); };
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
    if (previous) $('ke-horizon').value = previous.horizon;
    $('ke-horizon').onchange = renderStats; renderStats(); renderChart(); renderEvents();
    if (executionData()) {
      executionPage = 0;
      $('ke-execution-horizon').onchange = () => { executionPage = 0; renderExecution(); };
      $('ke-execution-cost').onchange = renderExecution;
      $('ke-execution-prev').onclick = () => { executionPage--; renderExecutionTrades(); };
      $('ke-execution-next').onclick = () => { executionPage++; renderExecutionTrades(); };
      if (previous && previous.executionHorizon) $('ke-execution-horizon').value = previous.executionHorizon;
      if (previous && previous.cost) $('ke-execution-cost').value = previous.cost;
      renderExecution();
    }
    $('ke-result').onclick = event => { const el = event.target.closest('[data-ke-day]'); if (el) selectDay(el.dataset.keDay); };
    $('ke-result').onkeydown = event => { const el = event.target.closest('g[data-ke-day]'); if (el && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); selectDay(el.dataset.keDay); } };
    if (previous ? previous.day : data.candles.length) selectDay(previous ? previous.day : data.candles[data.candles.length - 1].date);
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
      copy.querySelector('#ke-research').innerHTML = allResearchExport();
      if (copy.querySelector('#ke-execution')) copy.querySelector('#ke-execution').innerHTML = '';
    }
    const charts = [];
    for (let i = 0; i < data.candles.length; i += 120) {
      const rows = data.candles.slice(i, i + 120);
      charts.push('<p>' + esc(rows[0].date + '～' + rows[rows.length - 1].date) + '</p>' + chart(rows));
    }
    copy.querySelector('#ke-chart').innerHTML = charts.join('') || chart([]);
    copy.querySelector('#ke-visible').textContent = '以下分段列出所選期間全部 ' + data.candles.length + ' 日，價格保持原始日線；圖上研究標記採 ' + basisLabel(activeBasis()) + '。' + (hasAdjusted() ? '兩種基準的完整研究依據分章列出。' : '目前回應僅提供原始價格研究，未提供調整比較模式。');
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

/* 官方日線事件研究：圖表、品質及統計使用同一份資料。 */
(function () {
  'use strict';
  let dialog, controller, priorFocus, data, generation = 0;
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
    let svg = '<svg viewBox="0 0 1000 440" aria-label="最近三十個市場交易日 K 線與成交量"><title>紅色為收盤高於開盤，綠色為收盤低於開盤；黃色點為特殊事件</title>';
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
      if (i % 5 === 0 || i === rows.length - 1) svg += '<text x="' + cx + '" y="427" text-anchor="middle">' + esc(r.date.slice(5)) + '</text>';
    });
    return svg + '</svg>';
  }
  function selectDay(day) {
    const r = data.candles.find(item => item.date === day); if (!r) return;
    $('ke-detail').innerHTML = '<strong>' + esc(r.date) + '｜' + esc(r.signals.map(label).join('、') || r.reason) + '</strong><div>' + esc(r.reason) + '</div><div class="ke-muted">開 ' + fmt(r.open) + '・高 ' + fmt(r.high) + '・低 ' + fmt(r.low) + '・收 ' + fmt(r.close) + '・成交 ' + fmt(r.volume, 0) + ' 股</div>' +
      (r.metrics ? '<div>實體 ' + pct(r.metrics.bodyPct, 4) + '・量比 ' + fmt(r.metrics.volumeRatio, 3) + ' 倍・前 20 日高／低 ' + fmt(r.metrics.priorHigh) + '／' + fmt(r.metrics.priorLow) + '</div>' : '') +
      '<div class="ke-muted">' + [1, 3, 5, 10].map(h => h + ' 日後：' + (number(r.returns[h].value) ? pct(r.returns[h].value) : esc(r.returns[h].reason))).join('；') + '</div>';
  }
  function renderStats() {
    const h = $('ke-horizon').value;
    $('ke-stats').innerHTML = '<table><thead><tr><th>型態</th><th>成熟樣本</th><th>平均</th><th>中位數</th><th>上漲比例</th><th>中間 50% 報酬</th><th>基準平均</th><th>平均差</th><th>非重疊平均</th></tr></thead><tbody>' + data.stats.map(row => {
      const s = row.horizons[h];
      return '<tr><td>' + esc(row.label) + '<small>事件總數 ' + row.cases + '</small></td><td>' + s.raw.n + (s.raw.smallSample ? '<small>小樣本</small>' : '') + '</td>' + cell(s.raw.mean) + cell(s.raw.median) + '<td>' + (number(s.raw.positivePct) ? fmt(s.raw.positivePct) + '%' : '資料不足') + '</td><td>' + pct(s.raw.q25) + '～' + pct(s.raw.q75) + '</td><td>' + pct(s.baseline.mean) + '<small>n=' + s.baseline.n + '</small></td>' + cell(s.difference, '事件平均減去同期間基準平均，單位為百分點') + '<td>' + pct(s.nonOverlapping.mean) + '<small>n=' + s.nonOverlapping.n + '</small></td></tr>';
    }).join('') + '</tbody></table>';
  }
  function render() {
    const f = data.freshness;
    $('ke-status').className = 'ke-state' + (f.fresh ? '' : ' ke-warn');
    $('ke-status').textContent = f.status + '｜應有 ' + (f.expectedSession || '待核對') + '；資料最新 ' + (f.latestSession || '無資料') + '。本次研究截至 ' + data.asOf + '。';
    $('ke-result').innerHTML = '<div class="ke-kpis"><div><span class="ke-muted">研究標的</span><strong>' + esc(data.sym + ' ' + data.name) + '</strong></div><div><span class="ke-muted">近 30 日事件天數</span><strong>' + data.events.length + '</strong></div><div><span class="ke-muted">近三年可判定交易日</span><strong>' + data.eligibleDays + '</strong></div></div>' +
      '<section><h3>最近 30 日 K 線與成交量</h3><p class="ke-muted">點選 K 線或黃色點可查看當日依據。紅漲綠跌；缺值以 × 標示。</p><div class="ke-scroll">' + chart(data.candles) + '</div><div id="ke-detail" class="ke-detail" aria-live="polite"></div></section>' +
      '<section><h3>特殊事件與後續表現</h3><div class="ke-scroll"><table><thead><tr><th>日期</th><th>事件</th><th>收盤</th><th>1 日後</th><th>3 日後</th><th>5 日後</th><th>10 日後</th></tr></thead><tbody>' + (data.events.length ? data.events.map(r => '<tr><td><button data-ke-day="' + esc(r.date) + '">' + esc(r.date) + '</button></td><td class="ke-wrap">' + esc(r.signals.map(label).join('、')) + '</td><td>' + fmt(r.close) + '</td>' + [1, 3, 5, 10].map(h => cell(r.returns[h].value, r.returns[h].reason)).join('') + '</tr>').join('') : '<tr><td colspan="7">此區間沒有可判定的特殊事件。請查看資料品質。</td></tr>') + '</tbody></table></div><p class="ke-muted">資料不足的原因可點選該日查看；缺值與未成熟報酬皆不補零。</p></section>' +
      '<section><div class="ke-inline"><h3>歷史同型態統計</h3><label>後續交易日<select id="ke-horizon"><option value="1">1 日</option><option value="3">3 日</option><option value="5" selected>5 日</option><option value="10">10 日</option></select></label></div><p class="ke-muted">研究區間 ' + esc(data.historyStart || '尚未建立') + '～' + esc(data.historyEnd || '尚未建立') + '。各期只使用成熟樣本；平均差單位為百分點。</p><div id="ke-stats" class="ke-scroll"></div></section>' +
      '<details><summary>資料品質與不可判定日期</summary><p>官方來源：TWSE／TPEx；成交量統一為股。歷史中尚未官方核對 ' + data.unverifiedRows + ' 筆。</p><p>' + (data.companyActionCoverage ? '公司行動已核對：' + esc(data.companyActionCoverage.start + '～' + data.companyActionCoverage.end + '；' + data.companyActionCoverage.source) : '公司行動尚未完成核對。目前已提供台積電三年研究回補；其他標的需建立完整核對區間後才會產生統計。') + '</p><ul>' + data.candles.filter(r => !r.eligible).map(r => '<li>' + esc(r.date + '：' + r.reason) + '</li>').join('') + '</ul></details>' +
      '<details><summary>六種規則與統計口徑</summary><ul>' + data.rules.map(r => '<li>' + esc(r.label + '：' + r.formula) + '</li>').join('') + '</ul><ul>' + data.notes.map(n => '<li>' + esc(n) + '</li>').join('') + '</ul></details>';
    $('ke-horizon').onchange = renderStats; renderStats();
    $('ke-result').onclick = event => { const el = event.target.closest('[data-ke-day]'); if (el) selectDay(el.dataset.keDay); };
    $('ke-result').onkeydown = event => { const el = event.target.closest('g[data-ke-day]'); if (el && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); selectDay(el.dataset.keDay); } };
    if (data.events.length) selectDay(data.events[0].date);
    $('ke-export').disabled = false;
  }
  async function load() {
    const sym = $('ke-sym').value.trim().toUpperCase();
    if (!/^[0-9A-Z]{4,7}$/.test(sym)) { $('ke-status').textContent = '請輸入有效台股代號。'; return; }
    const serial = ++generation;
    if (controller) controller.abort(); const request = controller = new AbortController();
    const params = new URLSearchParams({ sym }); if ($('ke-date').value) params.set('asOf', $('ke-date').value);
    $('ke-load').disabled = true; $('ke-export').disabled = true; $('ke-result').innerHTML = ''; $('ke-status').textContent = '正在讀取已核對日線與事件統計…';
    const timer = setTimeout(() => request.abort(), 20000);
    try {
      const response = await fetch('/kline-events?' + params, { signal: request.signal });
      if (!response.ok) throw new Error('事件資料尚未完整建立，請檢查日線更新狀態或截至日期。');
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
    copy.querySelectorAll('details').forEach(el => { el.open = true; });
    copy.querySelectorAll('select').forEach(el => { el.value = $(el.id).value; el.replaceWith(document.createTextNode(el.options[el.selectedIndex].text)); });
    copy.querySelectorAll('button').forEach(el => el.replaceWith(document.createTextNode(el.textContent)));
    const html = '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(data.sym) + ' K 線事件研究</title><style>body{margin:20px;background:#0b1220}' + CSS + '#ke-dialog{max-height:none;width:100%;max-width:1180px;margin:auto;overflow:visible}</style><main id="ke-dialog"><div class="ke-content"><h2>' + esc(data.sym) + ' K 線事件研究</h2><p>' + esc($('ke-status').textContent) + '</p>' + copy.innerHTML + '</div></main></html>';
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = data.sym + '_K線事件研究_' + data.asOf + '.html'; a.hidden = true;
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
    dialog.innerHTML = '<div class="ke-head"><div><h2 id="ke-title">K 線事件研究</h2><div class="ke-muted">找出值得觀察的日期，查看歷史後續表現</div></div><button id="ke-close">關閉</button></div><div class="ke-content"><div class="ke-fields"><label>台股代號<input id="ke-sym" value="' + esc(/^[0-9A-Z]{4,7}$/.test(current) ? current : '2330') + '" maxlength="7"></label><label>截至日期（留空為最新）<input id="ke-date" type="date"></label><button id="ke-load">載入研究</button><button id="ke-export" disabled>下載 HTML 報告</button></div><div id="ke-status" class="ke-state" role="status"></div><div id="ke-result"></div></div>';
    $('ke-close').onclick = close; dialog.oncancel = event => { event.preventDefault(); close(); };
    $('ke-load').onclick = load; $('ke-export').onclick = download;
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

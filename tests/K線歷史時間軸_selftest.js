/* 以實際事件處理函式驗證期間查詢、分段瀏覽、事件分頁與日期定位。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/K線事件研究.js'), 'utf8');
const ready = () => new Promise(resolve => setImmediate(resolve));

function harness(payload) {
  const elements = new Map(), calls = [], downloads = [];
  function element(id = '') {
    const el = { id, value: '', dataset: {}, classList: { toggle() {} },
      setAttribute() {}, appendChild() {}, focus() {}, click() {}, remove() {}, reportValidity: () => true,
      querySelectorAll: () => [], showModal() { this.open = true; }, close() { this.open = false; } };
    // 只替換 DOM 容器；圖表、事件及 HTML 組裝仍執行正式匯出函式。
    el.cloneNode = () => {
      const nodes = new Map(['ke-events', 'ke-chart', 'ke-visible', 'ke-research', 'ke-execution'].map(key => [key, element()]));
      const appended = [];
      return { querySelector: selector => nodes.get(selector.slice(1)), querySelectorAll: () => [],
        appendChild(node) { appended.push(node); },
        get innerHTML() { return [...nodes.values(), ...appended].map(node => node.innerHTML + (node.textContent || '')).join(''); } };
    };
    Object.defineProperty(el, 'innerHTML', { get() { return this.html || ''; }, set(html) {
      this.html = html;
      for (const match of html.matchAll(/<(\w+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
        const node = element(match[3]);
        node.value = (match[2].match(/\bvalue="([^"]*)"/) || [])[1] || '';
        if (match[1] === 'select') {
          const body = html.slice(match.index).split('</select>')[0];
          const options = [...body.matchAll(/<option value="([^"]+)"([^>]*)>/g)];
          node.value = (options.find(o => o[2].includes('selected')) || options[0])[1];
        }
      }
    } });
    if (id) elements.set(id, el);
    return el;
  }
  element('pro-tools');
  const context = { console, URLSearchParams, AbortController, Blob, clearTimeout,
    setTimeout: (fn, delay) => setTimeout(fn, delay === 30000 ? 0 : delay),
    URL: class extends URL { static createObjectURL(blob) { downloads.push(blob); return 'blob:驗收'; } static revokeObjectURL() {} },
    document: { getElementById: id => elements.get(id), createElement: () => element(),
      head: element(), body: element(), activeElement: null },
    fetch: async url => { calls.push(url); return { ok: true, json: async () => payload }; },
    addEventListener() {} };
  context.window = context;
  vm.runInNewContext(source, context);
  return { context, calls, downloads, get: id => elements.get(id) };
}
const candles = Array.from({ length: 230 }, (_, i) => ({
  date: new Date(Date.UTC(2016, 0, i + 1)).toISOString().slice(0, 10),
  open: 100, high: 101, low: 99, close: 100, volume: 1000, eligible: true,
  reason: '符合事件條件', signals: ['doji'], returns: Object.fromEntries([1, 3, 5, 10].map(h => [h, { value: 0, reason: null }]))
}));
const stats = { n: 100, mean: 0, median: 0, q25: 0, q75: 0, positivePct: 0 };
const payload = { sym: '2330', name: '台積電', asOf: candles.at(-1).date,
  freshness: { status: '測試資料', fresh: false }, range: { label: '完整歷史' },
  historyStart: candles[0].date, historyEnd: candles.at(-1).date,
  availableStart: candles[0].date, availableEnd: candles.at(-1).date,
  eligibleDays: 230, timelineDays: 230, unverifiedRows: 0, candles, events: [...candles].reverse(),
  rules: [{ key: 'doji', label: '十字線', formula: '測試規則' }], notes: [],
  stats: [{ key: 'doji', label: '十字線', cases: 230,
    horizons: Object.fromEntries([1, 3, 5, 10].map(h => [h, { raw: stats, baseline: stats, nonOverlapping: stats, difference: 0 }])) }] };

(async () => {
  const view = harness(payload), $ = view.get;
  view.context.KlineEventsUI.open('2330'); await ready();
  assert.match(view.calls[0], /range=3y/);
  assert.match($('ke-visible').textContent, /第 201～230 日/);
  assert.equal(($('ke-chart').innerHTML.match(/<g data-ke-day=/g) || []).length, 30);
  $('ke-first').onclick(); assert.match($('ke-visible').textContent, /第 1～30 日/);
  $('ke-next').onclick(); assert.match($('ke-visible').textContent, /第 31～60 日/);
  $('ke-position').value = '150'; $('ke-position').oninput();
  assert.match($('ke-visible').textContent, /第 151～180 日/);
  $('ke-size').value = '120'; $('ke-size').onchange();
  assert.equal(($('ke-chart').innerHTML.match(/<g data-ke-day=/g) || []).length, 120);
  assert.doesNotMatch($('ke-chart').innerHTML, /width="-/);
  assert.match($('ke-chart').innerHTML, /2016-/);
  $('ke-last').onclick(); assert.match($('ke-visible').textContent, /第 111～230 日/);
  const before = $('ke-stats').innerHTML;
  $('ke-jump').value = candles[40].date; $('ke-jump-go').onclick();
  assert.match($('ke-detail').innerHTML, new RegExp(candles[40].date));
  assert.equal($('ke-stats').innerHTML, before);
  assert.equal(($('ke-events').innerHTML.match(/<button data-ke-day=/g) || []).length, 50);
  for (let i = 0; i < 4; i++) $('ke-event-next').onclick();
  assert.match($('ke-event-page').textContent, /第 5／5 頁/);
  assert.equal(($('ke-events').innerHTML.match(/<button data-ke-day=/g) || []).length, 30);
  $('ke-export').onclick();
  const exported = await view.downloads[0].text();
  assert.equal((exported.match(/<g data-ke-day=/g) || []).length, 230);
  assert.equal((exported.match(/<button data-ke-day=/g) || []).length, 230);
  assert.equal((exported.match(/<svg /g) || []).length, 2);
  assert.match(exported, /所選期間全部 230 日/);
  assert.doesNotMatch(exported, /<script/);
  $('ke-result').onclick({ target: { closest: () => ({ dataset: { keDay: candles[0].date } }) } });
  assert.match($('ke-visible').textContent, /第 1～120 日/);
  assert.match($('ke-detail').innerHTML, new RegExp(candles[0].date));
  $('ke-range').value = 'all'; await $('ke-load').onclick();
  assert.match(view.calls.at(-1), /range=all/);
  $('ke-range').value = 'custom'; $('ke-range').onchange();
  assert.equal($('ke-start-field').hidden, false);
  const count = view.calls.length;
  await $('ke-load').onclick(); assert.equal(view.calls.length, count);
  $('ke-start').value = '2020-02-01'; $('ke-date').value = '2020-01-01';
  await $('ke-load').onclick(); assert.equal(view.calls.length, count);
  $('ke-start').value = '2016-01-01'; await $('ke-load').onclick();
  assert.match(view.calls.at(-1), /range=custom&asOf=2020-01-01&start=2016-01-01/);
  view.context.KlineEventsUI.close();
  const researchPayload = structuredClone(payload);
  const key = 'breakout_252';
  const observation = { eligible: { [key]: true }, conditions: { [key]: true },
    reason: { [key]: '條件首次成立，僅供研究觀察' }, signals: [key],
    metrics: { priorHigh252: 100, distance252HighPct: 2 },
    date: candles.at(-1).date, source: 'TWSE', inputDigest: '首次證據' };
  researchPayload.candles.at(-1).signals = [];
  researchPayload.candles.at(-1).research = observation;
  researchPayload.research = { version: '研究測試版', latest: observation,
    rules: [{ key, label: '一年高點突破觀察', formula: '收盤 > 前 252 日最高價' }], notes: ['<img src=x onerror=alert(1)>'],
    stats: [{ ...structuredClone(payload.stats[0]), key, label: '一年高點突破觀察', eligibleDays: 30, cases: 1 }],
    shadow: { status: '資料已修訂，保留原觀察', count: 3, asOf: observation.date, observedAt: '2026-09-22T18:30:00+08:00', revised: true,
      evidence: { ...observation, signals: [], conditions: { [key]: null }, reason: { [key]: '前一交易日不可判定' } } } };
  const researchView = harness(researchPayload), rget = researchView.get;
  researchView.context.KlineEventsUI.open('2330'); await ready();
  assert.equal(rget('ke-basis').value, 'raw');
  assert.match(rget('ke-result').innerHTML, /已回退原始價格（保守排除）/);
  assert.match(rget('ke-result').innerHTML, /不是訊號數或績效樣本/);
  assert.match(rget('ke-result').innerHTML, /資料已修訂，保留原觀察/);
  assert.match(rget('ke-result').innerHTML, /前一交易日不可判定/);
  assert.match(rget('ke-result').innerHTML, /&lt;img src=x/);
  assert.doesNotMatch(rget('ke-result').innerHTML, /<img src=x/);
  assert.match(rget('ke-events').innerHTML, /一年高點突破觀察/);
  assert.match(rget('ke-detail').innerHTML, /本日新增觀察事件/);
  assert.match(rget('ke-research-stats').innerHTML, /可判定日數 30/);
  rget('ke-horizon').value = '10'; rget('ke-horizon').onchange();
  assert.match(rget('ke-research-stats').innerHTML, /一年高點突破觀察/);
  rget('ke-export').onclick();
  const researchExport = await researchView.downloads[0].text();
  assert.match(researchExport, /一年高點突破觀察/);
  assert.match(researchExport, /條件首次成立，僅供研究觀察/);
  assert.match(researchExport, /首次事件/);
  researchView.context.KlineEventsUI.close();

  // 採用後端 execution 契約；同時覆蓋正向、未成熟、排除及零可判定日。
  const distribution = (n, mean) => ({ n, mean, median: mean, positivePct: n ? 60 : null,
    p05: mean == null ? null : mean - 1.5,
    q25: mean == null ? null : mean - 1, q75: mean == null ? null : mean + 1,
    min: mean == null ? null : mean - 2, max: mean == null ? null : mean + 2, smallSample: n < 30 });
  const group = (n, mean) => ({ n, gross: distribution(n, mean), baseNet: distribution(n, mean == null ? null : mean - 1), stressNet: distribution(n, mean == null ? null : mean - 2) });
  const executionPayload = structuredClone(researchPayload);
  executionPayload.research.execution = { version: 'breakout-execution-v1', horizons: [1, 3, 5, 10],
    assumptions: { entry: '訊號後下一個市場交易日開盤', exit: '訊號後第 h 個市場交易日收盤',
      baseCostPerSidePct: .25, stressCostPerSidePct: .5, costNote: '成本為情境假設，未含股息', notes: ['<img src=x onerror=alert(2)>'] },
    rules: [{ key, label: '一年高點突破觀察', signalCount: 53, eligibleDays: 100, ineligibleReasons: [],
      horizons: Object.fromEntries([1, 3, 5, 10].map(h => {
        const mature = h === 10 ? 0 : 51;
        return [h, { counts: { signals: 53, mature, immature: 53 - mature - 1, excluded: 1, nonOverlapping: mature ? 20 : 0, overlapExcluded: mature ? 31 : 0 },
          excludedReasons: [{ reason: '公司行動尚未核對 <script>錯誤</script>', count: 1 }], raw: group(mature, mature ? h : null), nonOverlapping: group(mature ? 20 : 0, mature ? h - .5 : null),
          random: { status: mature ? '完成' : '無成熟訊號', draws: mature ? 1000 : 0, n: mature, seed: '固定種子<&>', note: '同股票、同年份、同筆數抽樣，非 p 值',
            yearStrata: [{ year: '2016', signals: mature, candidates: mature ? 100 : 0 }],
            metrics: Object.fromEntries(['gross', 'baseNet', 'stressNet'].map((cost, i) => [cost, { signalMean: mature ? h - i : null, p025: mature ? -2 - i : null,
              median: mature ? 0 - i : null, p975: mature ? 2 - i : null, atLeastSignalPct: mature ? 0 : null }])) },
          benchmark: { symbol: '0050', label: '元大台灣 50', eligibleStockCount: mature, pairedCount: 0, excludedCount: mature,
            excludedReasons: mature ? [{ reason: '0050 缺少官方進場日線<&>', count: mature }] : [], stock: group(0, null), benchmark: group(0, null), excess: group(0, null), note: '相同可配對交易，差額為百分點' },
          trades: Array.from({ length: 53 }, (_, i) => ({ signalDate: candles[i].date, entryDate: candles[i + 1].date,
            exitDate: h === 10 ? null : candles[i + h].date, horizon: h, status: i === 52 ? 'excluded' : i < mature ? 'mature' : 'immature',
            reason: i === 52 ? '公司行動 <script>不可執行</script>' : i < mature ? null : '後續交易日尚未成熟',
            entryPrice: 100, exitPrice: i < mature ? 100 + h : null, gross: i < mature ? h : null, baseNet: i < mature ? h - 1 : null, stressNet: i < mature ? h - 2 : null,
            nonOverlapping: i < 20 && i < mature, benchmark: { status: 'excluded', reason: '0050 缺少官方進場日線<&>', entryDate: candles[i + 1].date,
              exitDate: null, entryPrice: null, exitPrice: null, gross: null, baseNet: null, stressNet: null } })) }];
      })) }, { key: 'repair_risk', label: '修復風險觀察', signalCount: 0, eligibleDays: 0,
      ineligibleReasons: [{ reason: '前 252 日存在公司行動，資料不足不可判定', count: 100 }],
      horizons: Object.fromEntries([1, 3, 5, 10].map(h => [h, { counts: { signals: 0, mature: 0, immature: 0, excluded: 0, nonOverlapping: 0, overlapExcluded: 0 },
        excludedReasons: [], raw: group(0, null), nonOverlapping: group(0, null), random: { status: '無成熟訊號', n: 0, draws: 0, metrics: {}, yearStrata: [] },
        benchmark: { pairedCount: 0, eligibleStockCount: 0, excludedCount: 0, excludedReasons: [], stock: group(0, null), benchmark: group(0, null), excess: group(0, null) }, trades: [] }])) }] };
  const executionView = harness(executionPayload), eget = executionView.get;
  executionView.context.KlineEventsUI.open('2330'); await ready();
  assert.match(eget('ke-result').innerHTML, /每邊 0.25%/);
  assert.match(eget('ke-result').innerHTML, /每邊 0.5%/);
  assert.match(eget('ke-result').innerHTML, /非實際成交紀錄/);
  assert.match(eget('ke-execution-scope').textContent, /5 個交易日・基準淨報酬/);
  assert.match(eget('ke-execution-results').innerHTML, /\+4%/);
  assert.match(eget('ke-execution-results').innerHTML, /不是 p 值/);
  assert.match(eget('ke-execution-results').innerHTML, /第 5 百分位/);
  assert.match(eget('ke-execution-results').innerHTML, /沒有可配對樣本，無法比較/);
  assert.match(eget('ke-execution-results').innerHTML, /資料不足，無法判定訊號/);
  assert.match(eget('ke-execution-results').innerHTML, /前 252 日存在公司行動/);
  assert.match(eget('ke-execution-results').innerHTML, /固定種子&lt;&amp;&gt;/);
  assert.match(eget('ke-execution-results').innerHTML, /0050 缺少官方進場日線&lt;&amp;&gt;/);
  assert.doesNotMatch(eget('ke-result').innerHTML + eget('ke-execution-results').innerHTML + eget('ke-execution-trades').innerHTML, /<script>|<img src=x/);
  assert.match(eget('ke-execution-trades').innerHTML, /後續交易日尚未成熟/);
  assert.match(eget('ke-execution-page').textContent, /第 1／2 頁，共 53 筆/);
  assert.equal((eget('ke-execution-trades').innerHTML.match(/<tr>/g) || []).length, 51);
  eget('ke-execution-next').onclick();
  assert.match(eget('ke-execution-page').textContent, /第 2／2 頁/);
  assert.equal((eget('ke-execution-trades').innerHTML.match(/<tr>/g) || []).length, 4);
  const preserved = eget('ke-research-stats').innerHTML;
  eget('ke-execution-cost').value = 'stressNet'; eget('ke-execution-cost').onchange();
  assert.match(eget('ke-execution-results').innerHTML, /壓力淨報酬分布/);
  assert.match(eget('ke-execution-results').innerHTML, /\+3%/);
  assert.equal(eget('ke-research-stats').innerHTML, preserved);
  eget('ke-execution-horizon').value = '10'; eget('ke-execution-horizon').onchange();
  assert.match(eget('ke-execution-scope').textContent, /10 個交易日・壓力淨報酬/);
  assert.match(eget('ke-execution-page').textContent, /第 1／2 頁/);
  assert.match(eget('ke-execution-results').innerHTML, /無成熟訊號/);
  assert.match(eget('ke-execution-results').innerHTML, /資料不足～資料不足/);
  assert.doesNotMatch(eget('ke-execution-results').innerHTML, />0%<|\+0%|NaN|undefined/);
  eget('ke-export').onclick();
  const executionExport = await executionView.downloads[0].text();
  for (const h of [1, 3, 5, 10]) assert.match(executionExport, new RegExp('固定持有 ' + h + ' 個交易日'));
  for (const name of ['基準淨報酬', '壓力淨報酬', '未扣成本報酬']) assert.match(executionExport, new RegExp(name + '分布'));
  assert.match(executionExport, /breakout-execution-v1/);
  assert.match(executionExport, /成本為情境假設，未含股息/);
  assert.match(executionExport, /&lt;img src=x/);
  assert.match(executionExport, /後續交易日尚未成熟/);
  assert.match(executionExport, /公司行動 &lt;script&gt;不可執行/);
  assert.match(executionExport, /固定種子&lt;&amp;&gt;/);
  assert.equal((executionExport.match(/0050 缺少官方進場日線&lt;&amp;&gt;/g) || []).length, 53 * 4 + 3);
  assert.doesNotMatch(executionExport, /<script>|<img src=x/);
  executionView.context.KlineEventsUI.close();
  const adjustedPayload = structuredClone(executionPayload);
  const factor = { date: '2016-08-01', kind: '除息', before: 100, after: 95, factor: .95, status: 'supported', reason: '已核對官方參考價',
    verified: true, verificationReason: null,
    sourceUrl: 'https://www.twse.com.tw/example?symbol=2330&year=2016', sourceHash: '原始回應<&>', retrievedAt: '2026-09-22T12:00:00+08:00', version: '參考價解析第一版', payload: { originalRow: ['<script>來源不可執行</script>', 100, 95] } };
  const adjustedRow = { ...structuredClone(observation), anchorDate: candles.at(-1).date, priceBasis: 'twse-reference-comparison',
    metrics: { priorHigh252: 95, distance252HighPct: 5, rawPriorHigh252: 100 }, comparisonEvidence: { anchorDate: candles.at(-1).date, events: [factor], windowStart: '2016-01-01' } };
  adjustedPayload.candles.at(-1).research.signals = [];
  adjustedPayload.candles.at(-1).research.conditions[key] = false;
  adjustedPayload.candles.at(-1).adjustedResearch = adjustedRow;
  adjustedPayload.research.adjusted = { ...structuredClone(adjustedPayload.research), version: 'breakout-observation-adjusted-v1', priceBasis: 'twse-reference-comparison',
    latest: adjustedRow, rules: [{ key, label: '調整高點突破觀察', formula: '比較收盤大於調整後 252 日高點' }],
    adjustmentEvidence: { coverage: { start: '2016-01-01', end: '2016-12-31', version: '涵蓋第一版', sources: ['TWSE', '<img src=x>'] },
      events: [factor, { ...factor, date: '2016-08-02', status: 'unsupported', reason: '同日複合事件未放行', verified: false, verificationReason: '本機前收盤不一致', sourceUrl: 'javascript:alert("不可執行")' }], notes: ['只調整比較，不計含息報酬'] } };
  adjustedPayload.research.adjusted.stats[0].label = '調整高點突破觀察';
  adjustedPayload.research.adjusted.execution.rules[0].label = '調整高點突破觀察';
  const adjustedView = harness(adjustedPayload), bget = adjustedView.get;
  adjustedView.context.KlineEventsUI.open('2330'); await ready();
  assert.equal(bget('ke-basis').value, 'adjusted');
  assert.match(bget('ke-result').innerHTML, /價格永遠使用原始 OHLC/);
  assert.match(bget('ke-result').innerHTML, /跨公司行動的持有期仍排除/);
  assert.match(bget('ke-result').innerHTML, /歷史結果採目前已核對版本/);
  assert.match(bget('ke-result').innerHTML, /href="https:\/\/www.twse.com.tw\/example\?symbol=2330&amp;year=2016"/);
  assert.doesNotMatch(bget('ke-result').innerHTML, /href="javascript:|<script>|<img src=x/);
  assert.match(bget('ke-result').innerHTML, /同日複合事件未放行/);
  assert.match(bget('ke-result').innerHTML, /本機價格核對：已核對通過/);
  assert.match(bget('ke-result').innerHTML, /本機價格核對：核對未通過/);
  assert.match(bget('ke-result').innerHTML, /本機前收盤不一致/);
  assert.match(bget('ke-detail').innerHTML, /價格比較基準日/);
  assert.match(bget('ke-detail').innerHTML, /對照原始高點/);
  assert.match(bget('ke-detail').innerHTML, /前 252 日原始高點/);
  assert.match(bget('ke-detail').innerHTML, /本日比較窗口的完整調整證據/);
  assert.match(bget('ke-events').innerHTML, /調整高點突破觀察/);
  assert.match(bget('ke-chart').innerHTML, /調整高點突破觀察/);
  assert.match(bget('ke-research-stats').innerHTML, /調整高點突破觀察/);
  assert.match(bget('ke-execution-results').innerHTML, /調整高點突破觀察/);
  const originalStats = bget('ke-stats').innerHTML;
  const rawPriceShapes = bget('ke-chart').innerHTML.match(/<(?:rect|line)\s[^>]+>/g);
  bget('ke-execution-horizon').value = '3'; bget('ke-execution-horizon').onchange();
  bget('ke-execution-cost').value = 'stressNet'; bget('ke-execution-cost').onchange();
  const fetchCount = adjustedView.calls.length;
  bget('ke-basis').value = 'raw'; bget('ke-basis').onchange();
  assert.equal(adjustedView.calls.length, fetchCount, '切換比較基準不得重抓資料');
  assert.equal(bget('ke-execution-horizon').value, '3');
  assert.equal(bget('ke-execution-cost').value, 'stressNet');
  assert.equal(bget('ke-stats').innerHTML, originalStats, '原六種事件統計保持不變');
  assert.deepEqual(bget('ke-chart').innerHTML.match(/<(?:rect|line)\s[^>]+>/g), rawPriceShapes, '比較基準切換不得改變原始 OHLC 圖形');
  assert.doesNotMatch(bget('ke-chart').innerHTML, /調整高點突破觀察/);
  assert.doesNotMatch(bget('ke-events').innerHTML, /調整高點突破觀察/);
  assert.match(bget('ke-research-stats').innerHTML, /一年高點突破觀察/);
  assert.match(bget('ke-execution-results').innerHTML, /一年高點突破觀察/);
  assert.match(bget('ke-detail').innerHTML, /原始價格（保守排除）/);
  bget('ke-export').onclick();
  const bothExport = await adjustedView.downloads[0].text();
  assert.match(bothExport, /價格比較基準：原始價格（保守排除）/);
  assert.match(bothExport, /價格比較基準：官方參考價調整比較/);
  assert.match(bothExport, /breakout-observation-adjusted-v1/);
  assert.match(bothExport, /原始回應&lt;&amp;&gt;/);
  assert.match(bothExport, /&lt;script&gt;來源不可執行/);
  assert.match(bothExport, /參考價解析第一版/);
  assert.match(bothExport, /涵蓋第一版/);
  assert.doesNotMatch(bothExport, /href="javascript:|<script>|<img src=x/);
  for (const h of [1, 3, 5, 10]) {
    assert.equal(bothExport.split('一年高點突破觀察・' + h + ' 日').length - 1, 53);
    assert.equal(bothExport.split('調整高點突破觀察・' + h + ' 日').length - 1, 53);
    assert.equal(bothExport.split('<h4>後續 ' + h + ' 個交易日</h4>').length - 1, 2);
  }
  assert.equal(bget('ke-basis').value, 'raw', '匯出兩模式後須保留目前選擇');
  bget('ke-basis').value = 'adjusted'; bget('ke-basis').onchange();
  assert.equal(bget('ke-execution-horizon').value, '3');
  assert.equal(bget('ke-execution-cost').value, 'stressNet');
  assert.match(bget('ke-events').innerHTML, /調整高點突破觀察/);
  adjustedView.context.KlineEventsUI.close();
  // 可傳入後端完整 report，讓實際輸出契約沿用相同 DOM／下載驗收流程。
  if (process.argv[2]) {
    const actual = JSON.parse(fs.readFileSync(path.resolve(process.argv[2]), 'utf8'));
    const actualView = harness(actual), aget = actualView.get;
    actualView.context.KlineEventsUI.open(actual.sym); await ready();
    assert.ok(aget('ke-execution-results'), '完整 report 應含第二階段研究');
    const bases = ['raw', ...(actual.research.adjusted ? ['adjusted'] : [])], expectedRows = new Map();
    for (const basis of bases) {
      aget('ke-basis').value = basis; aget('ke-basis').onchange();
      const research = basis === 'raw' ? actual.research : actual.research.adjusted;
      for (const h of [1, 3, 5, 10]) {
        aget('ke-execution-horizon').value = String(h); aget('ke-execution-horizon').onchange();
        for (const cost of ['gross', 'baseNet', 'stressNet']) {
          aget('ke-execution-cost').value = cost; aget('ke-execution-cost').onchange();
          assert.doesNotMatch(aget('ke-execution-results').innerHTML + aget('ke-execution-trades').innerHTML, /NaN|undefined/);
        }
        const total = research.execution.rules.reduce((n, rule) => n + rule.horizons[h].trades.length, 0);
        assert.match(aget('ke-execution-page').textContent, new RegExp('共 ' + total + ' 筆'));
        for (const rule of research.execution.rules) {
          const marker = rule.label + '・' + h + ' 日';
          expectedRows.set(marker, (expectedRows.get(marker) || 0) + rule.horizons[h].trades.length);
        }
      }
    }
    aget('ke-export').onclick();
    const actualExport = await actualView.downloads[0].text();
    for (const [marker, count] of expectedRows) assert.equal(actualExport.split(marker).length - 1, count, '匯出必須保留兩種模式每個期數的所有逐筆研究');
    assert.match(actualExport, /完整期數與成本口徑/);
    actualView.context.KlineEventsUI.close();
  }
  console.log('K 線歷史時間軸：原事件、價格比較基準、期數、成本、分頁、來源證據、缺漏原因、兩模式完整匯出及字元跳脫驗證通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

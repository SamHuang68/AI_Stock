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
      const nodes = new Map(['ke-events', 'ke-chart', 'ke-visible'].map(key => [key, element()]));
      return { querySelector: selector => nodes.get(selector.slice(1)), querySelectorAll: () => [],
        get innerHTML() { return [...nodes.values()].map(node => node.innerHTML + (node.textContent || '')).join(''); } };
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
    URL: { createObjectURL(blob) { downloads.push(blob); return 'blob:驗收'; }, revokeObjectURL() {} },
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
  const sideStats = { n: 1, gross: { mean: 2 }, baseNet: { mean: 1.49 }, stressNet: { mean: .98 } };
  const executionCell = { counts: { mature: 1, signals: 3, excluded: 0 }, raw: sideStats,
    trades: [{ signalDate: '2019-01-02', entryDate: '2019-01-03', exitDate: '2019-01-03', baseNet: 1.49, positionStatus: 'closed' },
      { signalDate: '2019-12-31', positionStatus: 'open' }, { signalDate: '2020-01-01', positionStatus: 'not_entered' }],
    benchmark: { excess: { baseNet: { mean: .2 } }, pairedCount: 1 },
    random: { metrics: { baseNet: { median: .1 } }, status: '完成' },
    fixedSplit: { trainEnd: '2023-12-31', testStart: '2024-01-01', train: { n: 1 }, test: { n: 0 } } };
  const rule = { key: 'breakout_252', label: '一年高點突破觀察', horizons: { '1': executionCell, '5': executionCell } };
  const research = { latest: { date: '2020-01-01', reason: { breakout_252: '條件首次成立' } }, rules: [rule], notes: ['不是點時或總報酬'],
    execution: { rules: [rule], assumptions: { entry: '次日開盤', exit: '指定日收盤', costNote: '每邊費用及滑價' } } };
  research.adjusted = { ...research, adjustmentEvidence: { events: [] } };
  let posted;
  view.context.fetch = async (url, options = {}) => {
    view.calls.push(url);
    if (options.method === 'POST') { posted = JSON.parse(options.body); return { ok: true, json: async () => ({ status: '已記錄本交易日', note: '首次不覆寫' }) }; }
    if (url.startsWith('/breakout-shadow')) return { ok: true, json: async () => ({ status: '已讀取', records: [{ date: '2020-01-01', version: '測試', observedAt: '2020-01-01T18:00:00+08:00', inputDigest: 'abc', revisionCount: 1 }] }) };
    return { ok: true, json: async () => ({ research, asOf: '2020-01-01', freshness: { fresh: true, expectedSession: '2020-01-01' }, historyStart: '2016-01-01', historyEnd: '2020-01-01', comparisonStatus: 'missing', comparisonReason: '尚無官方收據', limitations: [] }) };
  };
  // 查詢採最後成功載入的期間；編輯輸入欄位尚未載入時不可暗換研究範圍。
  view.context.ST_PRIVATE_WEB_PROFILE = { role: 'owner' };
  $('ke-sym').value = '0050'; $('ke-range').value = 'all';
  await $('ke-long-load').onclick();
  assert.match(view.calls.at(-1), /breakout-research\?sym=2330&range=custom&asOf=2020-01-01&start=2016-01-01/);
  assert.match($('ke-long-result').innerHTML, /1.49%/);
  assert.match($('ke-long-result').innerHTML, /不以測試結果調參/);
  assert.equal($('ke-long-save').disabled, false);
  $('ke-long-basis').value = 'official_reference'; $('ke-long-basis').onchange();
  assert.match($('ke-long-result').innerHTML, /尚無官方收據/);
  await $('ke-long-save').onclick();
  assert.deepEqual(posted, { sym: '2330', range: 'custom', asOf: '2020-01-01', start: '2016-01-01', priceBasis: 'official_reference' });
  assert.match($('ke-long-status').textContent, /首次不覆寫/);
  await $('ke-long-history').onclick();
  assert.equal(view.calls.at(-1), '/breakout-shadow?sym=2330');
  assert.match($('ke-long-shadow').innerHTML, /修訂 1 次/);
  view.context.KlineEventsUI.close();
  const reader = harness(payload), read = reader.get;
  reader.context.ST_PRIVATE_WEB_PROFILE = { profile: 'personal-market', role: 'reader' };
  reader.context.KlineEventsUI.open('2330'); await ready();
  assert.equal(read('ke-long-save').disabled, true);
  assert.equal(read('ke-long-history').disabled, true);
  assert.match(read('ke-long-access').textContent, /唯讀模式.*可載入突破研究/);
  reader.context.fetch = async url => {
    reader.calls.push(url);
    return { ok: true, json: async () => ({ research, asOf: '2020-01-01', freshness: { fresh: true, expectedSession: '2020-01-01' }, historyStart: '2016-01-01', historyEnd: '2020-01-01', limitations: [] }) };
  };
  await read('ke-long-load').onclick();
  assert.match(reader.calls.at(-1), /^\/breakout-research\?sym=2330/);
  assert.match(read('ke-long-result').innerHTML, /1.49%/);
  assert.equal(read('ke-long-save').disabled, true);
  assert.equal(read('ke-long-history').disabled, true);
  // 直接呼叫事件函式，證明不能只依 disabled 屬性阻止私人請求。
  const readerRequests = reader.calls.length;
  await read('ke-long-save').onclick();
  await read('ke-long-history').onclick();
  assert.equal(reader.calls.length, readerRequests);
  assert.equal(reader.calls.filter(url => url.startsWith('/breakout-shadow')).length, 0);
  reader.context.KlineEventsUI.close();
  console.log('K 線歷史時間軸與突破研究：期間、圖表、事件、官方比較、擁有者影子操作與唯讀帳號零私人請求驗證通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

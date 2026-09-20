'use strict';

// 執行完整正式 Pulse 模組；僅以受控 DOM、網路及時鐘模擬休市與亂序回應。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const tick = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const stamp = date => Date.parse(date + 'T05:30:00Z') / 1000;
const latestQuote = (extra = {}) => ({ ok: true, code: '2330', name: '測試股票', price: 110,
  prevClose: 100, date: '20260918', time: '13:30:00', asOf: '2026-09-18T05:30:00Z',
  stale: true, source: 'TWSE-MIS', ...extra });
const pack = (date = '20260918') => ({ pulse: { ok: true, updatedAt: '2026-09-20T01:00:00Z',
  overview: { institutional: { totalYi: 20 }, strip: { t00: {
    price: 25000, changePct: 1, date, asOf: date ? date.slice(0, 4) + '-' + date.slice(4, 6) + '-' + date.slice(6) + 'T05:30:00Z' : null
  } } } }, wlQuotes: {} });

function harness(nowIso = '2026-09-20T04:00:00Z') {
  const nodes = new Map(), requests = [], traces = [], timers = new Map(), intervals = new Map();
  let now = Date.parse(nowIso), timerId = 0, route = 'pulse';
  function element(id = '') {
    const node = { id, textContent: '', className: '', hidden: false, disabled: false, value: '',
      style: {}, dataset: {}, children: [], parentElement: null, handlers: {},
      querySelector: () => null, querySelectorAll: () => [],
      setAttribute(key, value) { this[key] = String(value); }, getAttribute(key) { return this[key] ?? null; },
      removeAttribute(key) { delete this[key]; }, addEventListener(type, handler) { this.handlers[type] = handler; },
      appendChild(child) { child.parentElement = this; this.children.push(child); if (child.id) nodes.set(child.id, child); },
      insertBefore(child) { this.appendChild(child); }, focus() {},
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false }
    };
    let html = '', owned = [];
    Object.defineProperty(node, 'innerHTML', { get: () => html, set(value) {
      html = String(value);
      for (const key of owned) nodes.delete(key);
      owned = [];
      for (const match of html.matchAll(/<([a-z][a-z0-9-]*)\b([^>]*\bid="([^"]+)"[^>]*)>/gi)) {
        const child = element(match[3]);
        child.className = (match[2].match(/\bclass="([^"]*)"/) || [])[1] || '';
        child.hidden = /\bhidden(?:\s|>|$)/.test(match[2]);
        child.value = (match[2].match(/\bvalue="([^"]*)"/) || [])[1] || '';
        child.textContent = html.slice(match.index + match[0].length).split('<')[0];
        child.parentElement = node;
        nodes.set(child.id, child); owned.push(child.id);
      }
    } });
    return node;
  }
  for (const id of ['view-pulse', 'mount-pulse', 'pl-root', 'pl-body', 'pulse-v5-css']) nodes.set(id, element(id));
  const saved = new Map();
  const c = { console, Math, Promise, AbortController, Intl,
    Date: class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } },
    location: { origin: 'http://test.invalid' }, SERVER: '',
    localStorage: { getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value) },
    document: { getElementById: id => nodes.get(id) || null, querySelector: () => null, querySelectorAll: () => [],
      createElement: () => element(), head: element(), body: element(), documentElement: element() },
    ShellV5: { route: () => route, go(next) { route = next; } },
    addEventListener() {}, dispatchEvent() {},
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, at: now + ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval(fn, ms) { const id = ++timerId; intervals.set(id, { fn, ms }); return id; },
    clearInterval(id) { intervals.delete(id); },
    fetch(url, options = {}) {
      const urlObject = new URL(url, 'http://test.invalid');
      const requestPath = urlObject.pathname + urlObject.search;
      if (urlObject.pathname === '/diagnostics/ui-route') {
        traces.push(JSON.parse(options.body)); return Promise.resolve(reply({ ok: true }));
      }
      if (!['/twquote', '/bars', '/yf/batch'].includes(urlObject.pathname)) return Promise.resolve(reply({ ok: true, rows: [] }));
      let resolve, reject;
      const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
      const request = { path: requestPath, options, resolve, reject, ignoreAbort: false };
      requests.push(request);
      const abort = () => { if (!request.ignoreAbort) { const error = new Error('測試取消'); error.name = 'AbortError'; reject(error); } };
      if (options.signal) {
        if (options.signal.aborted) abort();
        else options.signal.addEventListener('abort', abort, { once: true });
      }
      return promise;
    }
  };
  c.window = c; vm.createContext(c);
  let source = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
  const marker = '  window.PulseV5 = {';
  assert.equal(source.split(marker).length, 2);
  source = source.replace(marker, 'window.healthTest = { assessment: stockHealthAssessment, bind: bindStockHealth, render: render, ' +
    'quote: typeof stockHealthQuote === "function" ? stockHealthQuote : null, ' +
    'history: typeof stockHealthHistoryQuote === "function" ? stockHealthHistoryQuote : null, ' +
    'date: typeof stockHealthDate === "function" ? stockHealthDate : null };\n' + marker);
  vm.runInContext(source, c, { filename: 'src/ui/pulse_v5.js' });
  c.healthTest.render(pack());
  const h = { c, requests, traces, timers, nodes,
    async submit(code = '2330') { nodes.get('pl-stock-code').value = code; nodes.get('pl-stock-check').onsubmit({ preventDefault() {} }); await tick(); },
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const first = [...timers].filter(([, value]) => value.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!first) break;
        now = first[1].at; timers.delete(first[0]); first[1].fn(); await tick();
      }
      now = target; await tick();
    },
    leave() { route = 'chart'; c.PulseV5.deactivate(); },
    text() { return ['pl-stock-result-title', 'pl-stock-result-body', 'pl-stock-result-meta'].map(id => nodes.get(id).textContent).join('\n'); },
    visible() { return /(?:^|\s)on(?:\s|$)/.test(nodes.get('pl-stock-result').className); },
    rerender(value = pack()) { c.healthTest.render(value); }
  };
  return h;
}

function reply(payload, status = 200) { return { ok: status >= 200 && status < 300, status,
  json: async () => payload, text: async () => JSON.stringify(payload) }; }
async function complete(request, value, status = 200) {
  assert(request, '須存在對應網路請求'); request.resolve(reply(value, status)); await tick();
}
const dailyRows = (days = ['2026-09-17', '2026-09-18'], closes = [100, 110]) =>
  days.map((time, i) => ({ time, close: closes[i] }));
function yahooPayload(days = ['2026-09-17', '2026-09-18'], closes = [100, 110], indexDays = days) {
  const chart = (rows, values, name) => ({ chart: { result: [{ meta: { shortName: name, chartPreviousClose: 1 },
    timestamp: rows.map(stamp), indicators: { quote: [{ close: values }] } }] } });
  return { '2330.TW': chart(days, closes, '備援測試股票'), '^TWII': chart(indexDays, [1000, 1010], '加權指數') };
}
async function enterFallback(h) {
  await h.submit(); await complete(h.requests[0], { ok: false });
  assert.equal(h.requests.length, 3);
  assert.equal(h.requests[1].path, '/bars?sym=2330&market=TW');
  assert.equal(h.requests[2].path, '/yf/batch?syms=2330.TW%2C%5ETWII&range=1mo&interval=1d&nocache=1');
}

const cases = [];
const test = (name, run) => cases.push({ name, run });

test('休市仍以有日期的最新成交分析，揭露日期與歷史前提', async () => {
  const h = harness(); await h.submit(); await complete(h.requests[0], latestQuote());
  assert.match(h.text(), /2330.*\+10\.00%/);
  assert.match(h.text(), /2026-09-18/);
  assert.match(h.text(), /休市|歷史|最近.*交易|最近.*成交/);
  assert.doesNotMatch(h.text(), /暫時無法健診|目前找不到可用/);
  assert(h.visible()); assert.equal(h.nodes.get('pl-stock-open').hidden, false);
  assert.equal(h.requests.length, 1, '有可用成交時不必改查其他來源');
});

test('缺現價但 stale 有最後成交時，以歷史成交回顧', async () => {
  const h = harness(); await h.submit();
  await complete(h.requests[0], latestQuote({ price: null, quoteStatus: 'stale', lastKnownPrice: 110 }));
  assert.match(h.text(), /\+10\.00%/); assert.match(h.text(), /2026-09-18/);
  assert.match(h.text(), /歷史|最後.*成交|最近.*成交/);
  assert.doesNotMatch(h.text(), /暫時無法健診/);
});

test('同日大盤才能算相對表現，缺大盤或跨日不得宣稱接近大盤', async () => {
  const same = harness(); await same.submit(); await complete(same.requests[0], latestQuote());
  assert.match(same.text(), /同期加權指數 \+1\.00%.*\+9\.00 個百分點/);
  for (const market of [pack('20260917'), pack('')]) {
    const h = harness(); h.rerender(market); await h.submit(); await complete(h.requests[0], latestQuote());
    assert.match(h.text(), /\+10\.00%/);
    assert.doesNotMatch(h.text(), /接近大盤|相對大盤 [+-][0-9]/);
    assert.match(h.text(), /不判定相對強弱/);
  }
});

test('真實 render 重新建立 DOM 後仍保留健診結果與圖表按鈕', async () => {
  const h = harness(); await h.submit(); await complete(h.requests[0], latestQuote());
  const before = h.text(), oldNode = h.nodes.get('pl-stock-result');
  h.rerender(); await tick();
  assert.notEqual(h.nodes.get('pl-stock-result'), oldNode, 'fixture 必須重建節點，才能捕捉舊 DOM 寫入');
  assert.equal(h.text(), before); assert(h.visible()); assert.equal(h.nodes.get('pl-stock-open').hidden, false);
});

test('連續查詢由最新輸入取得結果，舊回應不可覆寫或啟動備援', async () => {
  const h = harness(); await h.submit('2330'); h.requests[0].ignoreAbort = true;
  await h.submit('2317'); assert.equal(h.requests[0].options.signal.aborted, true);
  await complete(h.requests[1], latestQuote({ code: '2317', name: '新查詢股票' }));
  const current = h.text();
  await complete(h.requests[0], latestQuote({ name: '過期回應' }));
  assert.equal(h.text(), current); assert.match(current, /2317/); assert.equal(h.requests.length, 2);
});

test('關閉或離頁會取消查詢，晚到回應不可重新開啟健診', async () => {
  for (const action of ['close', 'leave']) {
    const h = harness(); await h.submit(); const request = h.requests[0]; request.ignoreAbort = true;
    if (action === 'close') h.nodes.get('pl-stock-close').onclick(); else h.leave();
    assert.equal(request.options.signal.aborted, true, '關閉及離頁均須取消等待');
    const before = h.text(); await complete(request, latestQuote());
    assert.equal(h.text(), before); assert.equal(h.requests.length, 1);
    if (action === 'close') { assert.equal(h.visible(), false); h.rerender(); assert.equal(h.visible(), false); }
  }
});

test('無效價格、前收、未知日期與未來日期不得產生分析', async () => {
  const h = harness(), api = h.c.healthTest;
  for (const field of ['price', 'prevClose']) {
    for (const value of [null, '', 0, -10, NaN, Infinity, -Infinity, '非數字', true, false, [], [110], {}]) {
      assert.equal(api.quote(latestQuote({ [field]: value }), '2330'), null, field + ' 無效時必須拒絕');
      assert.equal(api.assessment(latestQuote({ [field]: value }), {}), null);
    }
  }
  for (const date of [null, '', '日期未知', '2026-02-30', '2026-09-21', '2026-09-18T05:30:00']) {
    assert.equal(api.quote(latestQuote({ date: null, asOf: date, timestampMs: null }), '2330'), null);
  }
  assert.equal(api.quote(latestQuote({ code: '2317' }), '2330'), null, '其他代號的行情不可套用');
  assert.equal(api.quote(latestQuote({ suspect: true }), '2330'), null, '來源可疑價格不可套用');
  assert.equal(api.date('2026-09-17T17:00:00Z'), '2026-09-18', 'UTC 須轉換臺北交易日');
  assert.equal(api.date(Date.parse('2026-09-18T05:30:00Z')), '2026-09-18');
  for (const value of [1e30, Infinity, NaN, Date.parse('2026-09-20T07:00:00Z')]) {
    assert.equal(api.date(value), null, '無效或同日未來時間不得變成有效日期');
  }
  assert.equal(api.quote(latestQuote({ asOf: '2026-09-20T07:00:00Z', tradeDate: '2026-09-20' }), '2330'), null);
  assert.equal(api.quote(latestQuote({ timestampMs: Date.parse('2026-09-20T07:00:00Z') }), '2330'), null);
  assert.equal(api.quote(latestQuote({ price: null, quoteStatus: 'missing', lastKnownPrice: 110 }), '2330'), null,
    '未標示 stale 的未知缺值不得自動改用最後成交');
});

test('日線只採兩個有效收盤價，保留實際跨日區間且不用區間前收', async () => {
  const api = harness().c.healthTest;
  const rows = [{ time: '2026-09-18', close: 120 }, { time: '2026-09-17', close: null },
    { time: '2026-09-14', close: 100 }, { time: '2026-09-19', close: -1 },
    { time: '2026-09-21', close: 900 }, { time: '未知', close: 300 }];
  const quote = api.history(rows, '2330', '測試歷史來源', '歷史股票');
  assert.equal(quote.price, 120); assert.equal(quote.prevClose, 100);
  assert.equal(quote.previousDate, '2026-09-14'); assert.equal(quote.tradeDate, '2026-09-18');
  const analysis = api.assessment(quote, { twQuote: latestQuote({ changePct: 1 }) });
  assert.match(analysis.title, /\+20\.00%/);
  assert.match(analysis.body, /2026-09-14 → 2026-09-18/);
  assert.match(analysis.body, /未調整除權息，不等同交易所當日漲跌幅/);
  assert.match(analysis.body, /不判定相對強弱/, '同日但前一基準日未知，不可用單日大盤比較區間');
  assert.equal(api.history([{ time: '2026-09-18', close: 120 }], '2330', '測試'), null);
  assert.equal(api.history([{ time: '2026-09-18', close: 120 }, { time: '2026-09-18', close: 121 }], '2330', '測試'), null);
  for (const multiplier of [1, 1000]) {
    const numeric = api.history(dailyRows().map(row => ({ time: stamp(row.time) * multiplier, close: row.close })), '2330', '測試');
    assert.equal(numeric.tradeDate, '2026-09-18'); assert.equal(numeric.previousDate, '2026-09-17');
    assert.equal(numeric.price, 110); assert.equal(numeric.prevClose, 100);
  }
});

test('兩個備援來源並行，選較新日線並明示同期指數差異', async () => {
  const h = harness(); await enterFallback(h);
  await complete(h.requests[1], { candles: dailyRows(['2026-09-15', '2026-09-16'], [100, 105]) });
  assert.match(h.text(), /健診中/, '須等待較新來源或其期限，避免先到舊資料搶先定案');
  await complete(h.requests[2], yahooPayload());
  assert.match(h.text(), /Yahoo 日線備援/); assert.match(h.text(), /2026-09-17 → 2026-09-18/);
  assert.match(h.text(), /\+10\.00%/); assert.doesNotMatch(h.text(), /10900\.00/);
  assert.match(h.text(), /同期加權指數 \+1\.00%.*\+9\.00 個百分點/);
});

test('本機較新或同日優先保留正式歷史，任一來源失敗仍可分析', async () => {
  for (const remote of [yahooPayload(['2026-09-15', '2026-09-16']), yahooPayload(), null]) {
    const h = harness(); await enterFallback(h);
    await complete(h.requests[1], { candles: dailyRows().map(row => ({ time: stamp(row.time), close: row.close })) });
    if (remote) await complete(h.requests[2], remote); else { h.requests[2].reject(new Error('測試來源離線')); await tick(); }
    assert.match(h.text(), /本機歷史日線/); assert.match(h.text(), /2026-09-17 → 2026-09-18/);
    assert.match(h.text(), /\+10\.00%/); assert.doesNotMatch(h.text(), /暫時無法健診/);
  }
});

test('備援指數須與個股起迄日期一致，缺值不可誤說接近大盤', async () => {
  const h = harness(); await enterFallback(h);
  await complete(h.requests[1], { candles: [] });
  await complete(h.requests[2], yahooPayload(['2026-09-17', '2026-09-18'], [100, 110], ['2026-09-16', '2026-09-18']));
  assert.match(h.text(), /\+10\.00%/); assert.match(h.text(), /不判定相對強弱/);
  assert.doesNotMatch(h.text(), /接近.*指數|同期加權指數/);
});

test('主查詢 HTTP、JSON 與網路錯誤均進歷史備援', async () => {
  for (const failure of ['http', 'json', 'network']) {
    const h = harness(); await h.submit();
    if (failure === 'http') await complete(h.requests[0], {}, 503);
    else if (failure === 'json') {
      h.requests[0].resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError('測試 JSON 無效'); } }); await tick();
    } else { h.requests[0].reject(new Error('測試網路失敗')); await tick(); }
    assert.equal(h.requests.length, 3, failure + ' 仍須查詢兩個歷史來源');
    await complete(h.requests[1], { candles: dailyRows() });
    await complete(h.requests[2], {}, 503);
    assert.match(h.text(), /\+10\.00%/); assert.match(h.text(), /歷史回顧/);
    assert.equal(h.timers.size, 0, '完成時必須移除等待計時器');
  }
});

test('主查詢 8 秒逾時後仍有獨立備援期限，晚到主回應不可覆寫', async () => {
  const h = harness(); await h.submit(); h.requests[0].ignoreAbort = true;
  await h.advance(7999); assert.equal(h.requests.length, 1);
  await h.advance(1); assert.equal(h.requests.length, 3);
  assert.equal(h.requests[0].options.signal.aborted, true);
  assert.equal(h.requests[1].options.signal.aborted, false, '備援須使用尚未取消的請求範圍');
  await h.advance(7000); await complete(h.requests[1], { candles: dailyRows() });
  await complete(h.requests[2], yahooPayload());
  const result = h.text(); assert.match(result, /歷史回顧/);
  await complete(h.requests[0], latestQuote({ price: 900, name: '晚到主回應' }));
  assert.equal(h.text(), result); assert.equal(h.timers.size, 0);
});

test('備援 8 秒有界等待，一源卡住可用另一源，全部卡住也結束', async () => {
  const one = harness(); await enterFallback(one); one.requests[2].ignoreAbort = true;
  await complete(one.requests[1], { candles: dailyRows() });
  await one.advance(8000); assert.match(one.text(), /\+10\.00%/);
  assert.equal(one.requests[2].options.signal.aborted, true); assert.equal(one.timers.size, 0);
  const both = harness(); await both.submit(); both.requests[0].ignoreAbort = true;
  await both.advance(8000); both.requests[1].ignoreAbort = true; both.requests[2].ignoreAbort = true;
  await both.advance(7999); assert.match(both.text(), /健診中/);
  await both.advance(1); assert.match(both.text(), /資料不足.*暫時無法健診/);
  assert.equal(both.nodes.get('pl-stock-open').hidden, true); assert.equal(both.timers.size, 0);
  assert(both.traces.some(row => row.event === 'stock_health_terminal_failure'));
});

test('備援途中重繪仍寫入目前節點，關閉能取消兩個來源並阻止晚到結果', async () => {
  const active = harness(); await enterFallback(active); const oldNode = active.nodes.get('pl-stock-result');
  active.rerender(); assert.notEqual(active.nodes.get('pl-stock-result'), oldNode);
  assert.match(active.text(), /健診中/);
  await complete(active.requests[1], { candles: dailyRows() }); await complete(active.requests[2], yahooPayload());
  assert.match(active.text(), /\+10\.00%/); assert(active.visible());
  const closed = harness(); await enterFallback(closed);
  closed.requests[1].ignoreAbort = true; closed.requests[2].ignoreAbort = true;
  closed.nodes.get('pl-stock-close').onclick();
  assert(closed.requests.slice(1).every(request => request.options.signal.aborted));
  await complete(closed.requests[1], { candles: dailyRows() }); await complete(closed.requests[2], yahooPayload());
  assert.equal(closed.visible(), false); assert.equal(closed.timers.size, 0);
});

test('錯誤代號不送查詢並取消前次等待，週末當日報價也不得宣稱盤中即時', async () => {
  const h = harness(); await h.submit(); h.requests[0].ignoreAbort = true;
  await h.submit('X'); assert.match(h.text(), /代號格式不正確/); assert.equal(h.requests.length, 1);
  await complete(h.requests[0], latestQuote()); assert.match(h.text(), /代號格式不正確/);
  const current = harness(); await current.submit();
  await complete(current.requests[0], latestQuote({ asOf: '2026-09-20T03:00:00Z', stale: false, priceRealtime: true }));
  assert.match(current.text(), /週末休市/); assert.match(current.text(), /非即時行情/);
  assert.match(current.text(), /歷史回顧/);
});

test('交易時段有效當日成交保留原有即時分析，不必退回歷史備援', async () => {
  const h = harness('2026-09-18T04:00:00Z'); await h.submit();
  await complete(h.requests[0], latestQuote({ asOf: '2026-09-18T03:59:59Z', time: '11:59:59', stale: false, priceRealtime: true }));
  assert.match(h.text(), /成交觀察/); assert.match(h.text(), /當日成交資料/);
  assert.doesNotMatch(h.text(), /歷史回顧|暫時無法健診/); assert.equal(h.requests.length, 1);
});

test('個股交易日、asOf 與 timestampMs 必須一致，日期矛盾時改查歷史', async () => {
  const h = harness(), api = h.c.healthTest;
  for (const quote of [
    latestQuote({ tradeDate: '2026-09-17' }),
    latestQuote({ timestampMs: Date.parse('2026-09-17T05:30:00Z') }),
    latestQuote({ tradeDate: '2026-09-18', asOf: '2026-09-19T05:30:00Z' })
  ]) {
    assert.equal(api.quote(quote, '2330'), null, '矛盾的日期不得選其中一個當有效來源');
    assert.equal(api.assessment(quote, {}), null);
  }
  await h.submit(); await complete(h.requests[0], latestQuote({ tradeDate: '2026-09-17' }));
  assert.equal(h.requests.length, 3, '主來源日期矛盾時仍須嘗試歷史資料');
  await complete(h.requests[1], { candles: dailyRows() }); await complete(h.requests[2], yahooPayload());
  assert.match(h.text(), /歷史回顧/); assert.match(h.text(), /2026-09-17 → 2026-09-18/);
});

test('未來、可疑、失敗或日期矛盾的指數不得用作相對強弱基準', async () => {
  const api = harness().c.healthTest;
  const quote = latestQuote({ asOf: '2026-09-20T03:00:00Z' });
  const valid = { tradeDate: '2026-09-20', asOf: '2026-09-20T03:00:00Z', changePct: 1 };
  const benchmarks = [
    { ...valid, asOf: '2026-09-20T07:00:00Z' },
    { ...valid, timestampMs: Date.parse('2026-09-20T07:00:00Z') },
    { ...valid, suspect: true }, { ...valid, ok: false },
    { ...valid, tradeDate: '2026-09-19' }
  ];
  for (const benchmark of benchmarks) {
    for (const embedded of [false, true]) {
      const analysis = api.assessment(embedded ? { ...quote, benchmark } : quote, { twQuote: benchmark });
      assert(analysis, '個股資料有效時仍須保留個股分析');
      assert.match(analysis.body, /不判定相對強弱/);
      assert.doesNotMatch(analysis.body, /接近.*指數|同期加權指數|相差 .*百分點/);
    }
  }
});

test('有限正數計算若溢位仍拒絕分析，相對差異溢位則停止指數比較', async () => {
  const h = harness(), api = h.c.healthTest;
  const overflow = latestQuote({ price: 1e308, prevClose: 1e-308 });
  assert(Number.isFinite(overflow.price) && Number.isFinite(overflow.prevClose));
  assert.equal(api.assessment(overflow, {}), null, '輸入均有限不代表計算結果有限');
  await h.submit(); await complete(h.requests[0], overflow);
  assert.match(h.text(), /資料不足.*暫時無法健診/); assert.doesNotMatch(h.text(), /Infinity|NaN/);
  const huge = api.assessment(latestQuote({ price: 1e306, prevClose: 1 }), {
    twQuote: { asOf: '2026-09-18T05:30:00Z', changePct: -1.7e308 }
  });
  assert(huge); assert.match(huge.body, /不判定相對強弱/);
  assert.doesNotMatch(huge.body, /Infinity|NaN|同期加權指數/);
});

test('盤中 Yahoo 當日日線只稱參考價，明示可能尚未收盤', async () => {
  const h = harness('2026-09-18T05:00:00Z'); await enterFallback(h);
  await complete(h.requests[1], { candles: [] });
  const payload = yahooPayload();
  for (const symbol of ['2330.TW', '^TWII']) {
    payload[symbol].chart.result[0].timestamp[1] = Date.parse('2026-09-18T01:00:00Z') / 1000;
  }
  await complete(h.requests[2], payload);
  assert.match(h.text(), /\+10\.00%/); assert.match(h.text(), /Yahoo 日線備援/);
  assert.match(h.text(), /當日日線可能尚未收盤/); assert.match(h.text(), /日線參考價/);
  assert.match(h.text(), /非即時行情/); assert.doesNotMatch(h.text(), /收盤價|成交觀察/);
});

test('舊健診顯示時保留尚未送出的代號，重繪後查詢實際輸入', async () => {
  const h = harness(); await h.submit('2330'); await complete(h.requests[0], latestQuote());
  const priorReport = h.text(), oldInput = h.nodes.get('pl-stock-code');
  oldInput.value = '6488'; oldInput.oninput();
  h.rerender(); await tick();
  const currentInput = h.nodes.get('pl-stock-code');
  assert.notEqual(currentInput, oldInput, '真實 render 必須重建輸入節點');
  assert.equal(currentInput.value, '6488', '背景重繪不可清除輸入或用舊報告代號覆寫');
  assert.equal(h.text(), priorReport, '輸入尚未送出時保留原健診結果');
  assert.equal(h.requests.length, 1, '輸入與背景重繪不得提前查詢');
  h.nodes.get('pl-stock-check').onsubmit({ preventDefault() {} }); await tick();
  assert.equal(h.requests[1].path, '/twquote?code=6488', '送出須使用畫面保留的實際代號');
  await complete(h.requests[1], latestQuote({ code: '6488', name: '新輸入股票' }));
  assert.match(h.text(), /6488 新輸入股票/); assert.equal(h.nodes.get('pl-stock-code').value, '6488');
});

(async () => {
  let failures = 0;
  for (const item of cases) {
    try { await item.run(); console.log('通過：' + item.name); }
    catch (error) { failures++; console.error('失敗：' + item.name + '\n' + error.stack); }
  }
  if (failures) { console.error('個股健診歷史分析：' + failures + ' 組失敗／' + cases.length + ' 組。'); process.exitCode = 1; }
  else console.log('個股健診歷史分析：' + cases.length + ' 組全部通過。');
})();

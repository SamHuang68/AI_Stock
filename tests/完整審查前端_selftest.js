'use strict';
// 僅記憶體替身：不開瀏覽器、不連線、不讀寫使用者儲存資料。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
// CI 的 Windows checkout 可為 CRLF；只正規化讀入字串，保留全部受測程式與斷言。
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');
const plain = value => JSON.parse(JSON.stringify(value));
function between(source, start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, '受測原始碼界線必須存在');
  return source.slice(a, b);
}
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function scope(seed = {}) {
  const store = new Map(), events = {}, timers = [];
  const s = { console: { log() {}, warn() {}, error() {} }, S: {},
    localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)) },
    document: { getElementById: () => null, addEventListener() {} },
    setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {},
    setInterval() {}, clearInterval() {}, requestAnimationFrame() {},
    alert() {}, confirm: () => true,
    fetch: () => { throw new Error('未安排的網路呼叫'); },
    addEventListener: (name, fn) => { (events[name] ||= []).push(fn); }, ...seed };
  s.window = s; vm.createContext(s);
  return { s, store, events, timers, run: code => vm.runInContext(code, s), load: file => vm.runInContext(read(file), s, { filename: file }) };
}
const html = read('stock_terminal.html');
async function positions() {
  const t = scope(); t.load('src/core/position_v2.js');
  const { s } = t;
  s.S.sym = 'B'; s.S.mkt = 'US'; s.__loadSeq = 2;
  s.S.data = { candles: [{ close: 111 }] };
  s.S.dataIdentity = { sym: 'A', mkt: 'US', loadSeq: 1 };
  s.S.positions = { A: { entry: 9 }, B: { entry: 8 } };
  const before = plain(s.S.positions);
  assert.equal(s.setPosition(10, 1, 20, 5, '', { sym: 'A', mkt: 'US' }), false);
  assert.deepEqual(plain(s.S.positions), before, '舊表單不可改寫新標的');
  assert.equal(s.currentPositionPrice(), null);
  assert.equal(s.setPosition(10, 1, 20, 5, '', { sym: 'B', mkt: 'US' }), true);
  assert.equal(s.S.positions.B.lastPrice, null, '不得保存舊標的現價');
  s.S.dataIdentity = { sym: 'B', mkt: 'US', loadSeq: 2 };
  assert.equal(s.currentPositionPrice(), 111);
  let click;
  s.document.getElementById = id => id === 'rpanel' ? { addEventListener: (_, fn) => { click = fn; } } : null;
  s.attachPosition();
  click({ preventDefault() {}, target: { closest: () => ({ dataset: { act: 'clear-pos', sym: 'A', mkt: 'US' } }) } });
  assert.ok(s.S.positions.B, '舊面板清除不得刪除新標的');
  click({ preventDefault() {}, target: { closest: () => ({ dataset: { act: 'clear-pos', sym: 'B', mkt: 'US' } }) } });
  assert.equal(s.S.positions.B, undefined);
  assert.equal(s.S.positions.A.entry, 9);
}
async function alerts() {
  for (const mode of ['讀取失敗', '缺少版本', '資料錯誤', '版本衝突', '保存失敗', '未確認', '成功']) {
    const calls = [], old = [{ id: 1, sym: 'OTHER', source: 'manual' }, { id: 2, sym: 'A', source: 'wizard' }];
    const t = scope({ fetch: async (url, opts = {}) => {
      calls.push({ url, opts });
      if (opts.method === 'POST') return { ok: !['版本衝突', '保存失敗'].includes(mode), status: mode === '版本衝突' ? 409 : 500, json: async () => ({ ok: mode !== '未確認' }) };
      return { ok: mode !== '讀取失敗', headers: { get: () => mode === '缺少版本' ? null : '"v1"' }, json: async () => mode === '資料錯誤' ? {} : plain(old) };
    } });
    t.run(read('src/screener/wizard_v3.js').replace(/\}\)\(\);\s*$/, 'window.__applyCore = applyCore; })();'));
    const action = t.s.__applyCore('A', 'US', {}, { alerts: [{ type: 'price', price: 10 }], conclusion: '案例' }, { alert: true });
    if (mode === '成功') assert.deepEqual(plain(await action), ['警報']);
    else await assert.rejects(action, /警報未完成/);
    if (['讀取失敗', '缺少版本', '資料錯誤'].includes(mode)) assert.equal(calls.length, 1, '讀取未確認不得送出覆寫');
    else {
      assert.equal(calls[1].opts.headers['If-Match'], '"v1"');
      const sent = JSON.parse(calls[1].opts.body);
      assert.deepEqual(sent[0], old[0]); assert.equal(sent.length, 2); assert.equal(sent[1].price, 10);
    }
  }
}
async function watches() {
  const sent = [], t = scope({ fetch: async (_, opts) => { sent.push(JSON.parse(opts.body)); return { ok: true }; } });
  const old = { '2330': { strategy: 'sma60_pullback', params: { n: 60 }, notes: '保留備註', addedAt: 123 } };
  t.store.set('stock_terminal_watches_v2', JSON.stringify(old));
  t.load('src/core/watch_v2.js');
  assert.equal(t.s.S.watches['2330'].signals[0].strategy, old['2330'].strategy);
  assert.equal(t.s.S.watches['2330'].notes, old['2330'].notes);
  assert.equal(t.s.S.watches['2330'].addedAt, 123);
  assert.equal(t.timers.length, 1, '舊格式首次啟動可建立同步計時器');
  t.timers[0]();
  assert.equal(sent[0]['2330'].signals[0].params.n, 60);
}
async function drawings() {
  for (const action of ['新增', '清空', '舊格式補載', '已清空重載']) {
    const pending = deferred(), t = scope({ S: { sym: 'A' }, fetch: (_, opts = {}) => opts.method === 'POST' ? Promise.resolve({ ok: true }) : pending.promise });
    if (action === '舊格式補載') t.store.set('draw_v3', '{"A":[]}');
    if (action === '已清空重載') { t.store.set('draw_v3', '{"A":[]}'); t.store.set('draw_v3_known', '["A"]'); }
    t.run(read('src/chart/drawtools_v3.js').replace(/\}\)\(\);\s*$/, 'window.__clearSym = clearSym; })();'));
    const loading = t.events.symLoaded[0]({ detail: { sym: 'A' } });
    if (action === '新增') t.s.drawToolsAdd('A', [{ type: 'hline', p: 10 }]);
    if (action === '清空') t.s.__clearSym();
    pending.resolve({ ok: true, json: async () => ({ objects: [{ type: 'hline', p: 99 }] }) });
    await loading;
    const saved = JSON.parse(t.store.get('draw_v3'));
    assert.deepEqual(saved.A, action === '新增' ? [{ type: 'hline', p: 10 }] : action === '舊格式補載' ? [{ type: 'hline', p: 99 }] : []);
  }
}
async function panels() {
  const requests = [], drawn = [], t = scope({ active: true, panels: [], fetchPanel: () => { const d = deferred(); requests.push(d); return d.promise; }, buildPanelChart: (_, p) => drawn.push(p.name) });
  t.run(between(read('src/chart/multichart_v3.js'), '  async function loadPanel(p)', '  // ---- UI ----'));
  const p = { sym: 'A', mkt: 'US', rg: '6mo', body: { isConnected: true }, nameEl: {} }; t.s.panels.push(p);
  const a = t.s.loadPanel(p); p.sym = 'B'; const b = t.s.loadPanel(p);
  requests[1].resolve({ name: 'B', candles: [{}] }); await b;
  requests[0].resolve({ name: 'A', candles: [{}] }); await a;
  assert.deepEqual(drawn, ['B']); assert.equal(p.nameEl.textContent, 'B');
  const c = t.s.loadPanel(p); p.rg = '1y'; const d = t.s.loadPanel(p);
  requests[3].resolve({ name: '新時框', candles: [{}] }); await d;
  requests[2].resolve({ name: '舊時框', candles: [{}] }); await c;
  assert.deepEqual(drawn, ['B', '新時框']);
  const e = t.s.loadPanel(p); t.s.panels = []; p.body.isConnected = false;
  requests[4].resolve({ name: '已拆除', candles: [{}] }); await e;
  assert.deepEqual(drawn, ['B', '新時框']);
}
async function indicatorCommit() {
  // 原封載入 loadSym 的 await／提交區段；未模擬完整主圖資料抓取流程。
  const requests = [], rendered = [], t = scope({ S: { sym: 'A', mkt: 'US', ind: null }, __loadSeq: 1,
    runWorker: () => { const d = deferred(); requests.push(d); return d.promise; }, renderInd: v => rendered.push(v.id) });
  const fragment = between(html, '    const indicators = await runWorker(parsed.candles);', '\n  }\n  try { renderRpanel();');
  t.run('async function commit(sym, mkt, _myLoad, parsed, last) {\n' + fragment + '\n}');
  const a = t.s.commit('A', 'US', 1, { candles: [] }, {});
  t.s.S.sym = 'B'; t.s.__loadSeq = 2;
  const b = t.s.commit('B', 'US', 2, { candles: [] }, {});
  requests[1].resolve({ id: 'B' }); await b; requests[0].resolve({ id: 'A' }); await a;
  assert.equal(t.s.S.ind.id, 'B'); assert.deepEqual(rendered, ['B']);
}
async function indicatorsAndDsl() {
  const t = scope();
  t.run(between(html, 'window.stEmaSeries = function', 'const _workerBlob') + '\nwindow.__workerSource = WORKER_SRC;');
  t.load('src/screener/backtest_v3.js'); t.load('src/screener/strategy_builder_v3.js');
  t.run(read('src/screener/strategy_script_v3.js').replace(/\}\)\(\);\s*$/, 'window.__interp = interp; })();'));
  assert.equal(t.s.StratLib.ema, t.s.stEmaSeries);
  assert.deepEqual(plain(t.s.stEmaSeries([null, 1, 2, 3, 4, null, 8], 3)), [null, null, null, 2, 3, null, null]);
  const closes = Array.from({ length: 40 }, (_, i) => i + 1);
  const candles = closes.map((close, i) => ({ time: i + 1, open: close, close, high: close + 1, low: close - 1, volume: 100 }));
  const m = t.s.StratLib.macd(closes);
  assert.equal(m.macd.findIndex(x => x !== null), 25); assert.equal(m.signal.findIndex(x => x !== null), 33);
  assert.equal(m.macd[25], 7); assert.equal(m.signal[33], 7); assert.equal(m.hist[33], 0);
  let workerResult;
  const worker = scope({ self: { postMessage: x => { workerResult = x; } } }); worker.run(t.s.__workerSource);
  for (const size of [26, 33, 34, 40]) {
    worker.s.self.onmessage({ data: { candles: candles.slice(0, size) } });
    assert.equal(workerResult.macd, m.macd[size - 1]); assert.equal(workerResult.macdSig, m.signal[size - 1]); assert.equal(workerResult.macdHist, m.hist[size - 1]);
  }
  const cols = t.s.Backtest.colsOf(candles);
  const valid = t.s.__interp('a = ema(close, 3)\nbuy = close > a\nplot a', cols);
  assert.equal(valid.env.a[2], 2); assert.equal(valid.env.buy[3], true); assert.equal(valid.plots.length, 1);
  for (const bad of ['buy = close => 3', 'buy = close > 3 garbage', 'plot close garbage', 'buy = 1..2', 'buy = ema(close)', 'buy = ema(close, 0)', 'buy = ema(close, 2.5)', 'buy = ema(close, close)', 'buy = abs(true)', 'buy = macd(1)']) {
    assert.throws(() => t.s.__interp('# 第一行\n' + bad, cols), /第 2 行/);
  }
}
async function markets() {
  const t = scope({ fetch: async () => ({ ok: false }) }); t.load('src/core/market_v3.js');
  const source = between(read('src/core/wl_live_v3.js'), '      const quoteSymbol =', '      const symMap =');
  t.run(source + '\nwindow.__quoteSymbol = quoteSymbol;');
  for (const [code, market, expected] of [['7203', 'JP', '7203.T'], ['7203.T', 'JP', '7203.T'], ['2330', 'TW', '2330.TW'], ['2330.TW', 'TW', '2330.TW'], ['6488.TWO', 'TW', '6488.TWO'], ['AAPL', 'US', 'AAPL'], ['__TXF__', 'TW', '__TXF__']]) {
    assert.equal(t.s.__quoteSymbol(code, market), expected);
  }
}
(async () => {
  for (const [name, test] of [['F05 倉位身分與資料保全', positions], ['F06 警報版本與失敗保全', alerts], ['F07 指標亂序提交', indicatorCommit], ['F10 舊 WATCH 首次遷移', watches], ['F13 畫線雲端延遲', drawings], ['F14 多圖亂序與拆除', panels], ['F15 市場代號正規化', markets], ['F16／F17 暖機與腳本錯誤', indicatorsAndDsl]]) {
    await test(); console.log('通過：' + name);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

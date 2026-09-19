'use strict';

// 完整執行正式 LIVE 模組，以受控回應驗證圖表與啟用週期的一致性。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'core', 'live_v2.js'), 'utf8');

function createHarness({ ready = true } = {}) {
  const elements = new Map();
  function element() {
    const classes = new Set();
    return {
      textContent: '', innerHTML: '', style: {},
      classList: {
        add: name => classes.add(name), remove: name => classes.delete(name),
        toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
      },
    };
  }
  for (const id of ['live-panel', 'btn-live', 'lp-px', 'lp-chg', 'lp-hl', 'lp-vol',
    'lp-bid', 'lp-ask', 'lp-bid-sz', 'lp-ask-sz', 'lp-state', 'lp-time', 'stattxt']) {
    elements.set(id, element());
  }
  elements.get('lp-px').textContent = '既有價格';
  elements.get('stattxt').textContent = '既有狀態';
  const listeners = new Map();
  const requests = [];
  const updates = [];
  const intervals = new Map();
  const timeouts = new Map();
  let timerId = 0;
  const state = {
    sym: '2330', mkt: 'TW',
    data: { candles: [{ time: 1789776000, open: 100, high: 101, low: 99, close: 100 }] },
    chartSeries: { update(candle) { updates.push({ sym: state.sym, ...candle }); } },
  };
  const sandbox = {
    S: state, __loadSeq: 1,
    document: {
      hidden: false,
      getElementById: id => elements.get(id) || null,
      createElement: () => element(),
      head: { appendChild() {} }, body: { appendChild() {} },
    },
    console: { log() {}, warn() {} },
    alert() { throw new Error('測試不應觸發提示'); },
    addEventListener(name, fn) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(fn);
    },
    setTimeout(fn) { const id = ++timerId; timeouts.set(id, fn); return id; },
    setInterval(fn) { const id = ++timerId; intervals.set(id, fn); return id; },
    clearInterval(id) { intervals.delete(id); },
    fetch(url) {
      return new Promise(resolve => requests.push({
        url, resolve(quote) { resolve({ ok: true, json: async () => quote }); },
      }));
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'src/core/live_v2.js' });
  // 時段節流另有自身用途；本測試固定盤中，專注非同步請求及圖表生命週期。
  vm.runInContext("sessionByTime = () => 'REGULAR'", sandbox);
  const emit = name => (listeners.get(name) || []).forEach(fn => fn({ detail: {
    sym: state.sym, mkt: state.mkt, loadSeq: sandbox.__loadSeq,
  } }));
  if (ready) emit('symLoaded');
  return {
    state, context: sandbox, requests, updates, elements, intervals, timeouts, emit,
    enable: () => sandbox.liveEnable(), disable: () => sandbox.liveDisable(),
    poll: () => sandbox.livePollOnce(),
    startLoad(sym = state.sym, mkt = state.mkt) {
      // stock_terminal.html 的 loadSym 契約：先遞增序號及更新標的，再通知載入中。
      sandbox.__loadSeq += 1;
      state.sym = sym;
      state.mkt = mkt;
      emit('symLoading');
    },
    async complete(index, quote) {
      assert.ok(requests[index], '預期請求必須已送出');
      requests[index].resolve(quote);
      await new Promise(resolve => setImmediate(resolve));
    },
  };
}

function quote(price, lastBarTime) {
  return { price, change: 1, changePct: 1, high: price + 1, low: price - 1,
    marketState: 'REGULAR', ...(lastBarTime == null ? {} : { lastBarTime }) };
}
function assertUntouched(h) {
  assert.equal(h.updates.length, 0, '過時報價不得更新 K 線');
  assert.equal(h.elements.get('lp-px').textContent, '既有價格', '過時報價不得更新 LIVE 面板');
  assert.equal(h.elements.get('stattxt').textContent, '既有狀態', '過時報價不得更新狀態列');
}

const cases = [
  ['圖表首次載入前不請求，載入完成後正常更新', async () => {
    const h = createHarness({ ready: false });
    h.enable();
    await h.poll();
    assert.equal(h.requests.length, 0);
    h.emit('symLoaded');
    const pending = h.poll();
    assert.match(h.requests[0].url, /\/quote\/2330\.TW$/);
    await h.complete(0, quote(105, 1000));
    await pending;
    assert.equal(h.updates.length, 1);
    assert.equal(h.updates[0].sym, '2330');
    assert.equal(h.updates[0].close, 105);
    assert.equal(h.elements.get('lp-px').textContent, '105.00');
    assert.equal(h.elements.get('stattxt').textContent, 'LIVE · 2330 105.00');
  }],
  ['切換標的後丟棄舊報價', async () => {
    const h = createHarness();
    h.enable();
    h.startLoad('2317');
    h.emit('symLoaded');
    await h.complete(0, quote(950, 1000));
    assertUntouched(h);
    const pending = h.poll();
    assert.match(h.requests[1].url, /\/quote\/2317\.TW$/);
    await h.complete(1, quote(110, 1001));
    await pending;
    assert.equal(h.updates[0].sym, '2317');
    assert.equal(h.updates[0].close, 110);
  }],
  ['同代號切換市場也不得接收舊市場回應', async () => {
    const h = createHarness();
    h.enable();
    h.state.mkt = 'US';
    await h.complete(0, quote(950));
    assertUntouched(h);
  }],
  ['僅載入序號改變亦可阻擋同標的舊回應', async () => {
    const h = createHarness();
    h.enable();
    h.context.__loadSeq += 1;
    await h.complete(0, quote(950));
    assertUntouched(h);
  }],
  ['僅遞增載入序號而未發出載入中事件時，仍須等完成通知才請求', async () => {
    const h = createHarness();
    // MarketChart.load 會更新序號及標的，但不發出 symLoading。
    h.context.__loadSeq += 1;
    h.state.sym = '2317';
    h.enable();
    h.poll();
    assert.equal(h.requests.length, 0, '尚未完成的新載入不可沿用上一張圖表的就緒狀態');
    assertUntouched(h);
    h.emit('symLoaded');
    const pending = h.poll();
    assert.equal(h.requests.length, 1, '完成通知應恢復正常輪詢');
    assert.match(h.requests[0].url, /\/quote\/2317\.TW$/);
    await h.complete(0, quote(110));
    await pending;
    assert.equal(h.updates.length, 1);
    assert.equal(h.updates[0].sym, '2317');
    assert.equal(h.updates[0].close, 110);
  }],
  ['標的載入中不請求，也不把回應寫入尚未替換的圖表', async () => {
    const h = createHarness();
    h.enable();
    h.startLoad('2317');
    await h.poll();
    assert.equal(h.requests.length, 1);
    await h.complete(0, quote(950));
    assertUntouched(h);
    h.emit('symLoaded');
    const pending = h.poll();
    await h.complete(1, quote(110));
    await pending;
    assert.equal(h.updates[0].close, 110);
  }],
  ['切換離開再返回相同標的仍阻擋原請求', async () => {
    const h = createHarness();
    h.enable();
    h.startLoad('2317');
    h.emit('symLoaded');
    h.startLoad('2330');
    h.emit('symLoaded');
    await h.complete(0, quote(950));
    assertUntouched(h);
  }],
  ['關閉後晚到回應不寫入，輪詢亦不再送出', async () => {
    const h = createHarness();
    h.enable();
    h.disable();
    await h.complete(0, quote(950));
    await h.poll();
    assertUntouched(h);
    assert.equal(h.requests.length, 1);
    assert.equal(h.intervals.size, 0);
  }],
  ['關閉再啟用不接收前代請求，當代回應仍可更新', async () => {
    const h = createHarness();
    h.enable();
    h.disable();
    h.enable();
    await h.complete(0, quote(950));
    assertUntouched(h);
    await h.complete(1, quote(110));
    assert.equal(h.updates.length, 1);
    assert.equal(h.updates[0].close, 110);
  }],
  ['同標的請求逆序完成且無來源時間時，舊請求不可覆寫', async () => {
    const h = createHarness();
    h.enable();
    const newer = h.poll();
    await h.complete(1, quote(110));
    await newer;
    await h.complete(0, quote(105));
    assert.equal(h.updates.length, 1);
    assert.equal(h.updates[0].close, 110);
    assert.equal(h.elements.get('lp-px').textContent, '110.00');
  }],
  ['請求按序完成但來源報價時間倒退時保留較新報價', async () => {
    const h = createHarness();
    h.enable();
    await h.complete(0, quote(110, 1001));
    const older = h.poll();
    await h.complete(1, quote(105, 1000));
    await older;
    assert.equal(h.updates.length, 1);
    const equalTime = h.poll();
    await h.complete(2, quote(111, 1001));
    await equalTime;
    assert.equal(h.updates.length, 2, '同分鐘內的新請求仍可更新價格');
    assert.equal(h.updates[1].close, 111);
  }],
  ['缺少來源時間的中間回應不清除已接受的時間基準', async () => {
    const h = createHarness();
    h.enable();
    await h.complete(0, { ...quote(110), timestampMs: 1001000 });
    const unknown = h.poll();
    await h.complete(1, quote(111));
    await unknown;
    const older = h.poll();
    await h.complete(2, { ...quote(105), timestampMs: 1000000 });
    await older;
    assert.equal(h.updates.length, 2);
    assert.equal(h.updates[1].close, 111);
  }],
  ['新標的使用自身來源時間，不繼承上一檔的時間基準', async () => {
    const h = createHarness();
    h.enable();
    await h.complete(0, quote(110, 2000));
    h.startLoad('2317');
    h.emit('symLoaded');
    const pending = h.poll();
    await h.complete(1, quote(105, 1000));
    await pending;
    assert.equal(h.updates.length, 2);
    assert.equal(h.updates[1].sym, '2317');
    assert.equal(h.updates[1].close, 105);
  }],
];

(async () => {
  for (const [name, run] of cases) {
    await run();
    console.log('通過：' + name);
  }
  console.log(`LIVE 報價一致性：${cases.length} 項行為驗證全部通過。`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

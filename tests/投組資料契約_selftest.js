'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const root = path.resolve(__dirname, '..');
const bookSource = fs.readFileSync(path.join(root, 'src/ui/book_v5.js'), 'utf8');

const contractSource = fs.readFileSync(path.join(root, 'src/core/投組資料契約_v5.js'), 'utf8');
let checks = 0;
function check(condition, message) {
  assert(condition, message);
  checks++;
  console.log('通過：' + message);
}
function harness(state, stored, role) {
  const listeners = {};
  const writes = [];
  const reads = [];
  const storage = Object.assign({}, stored);
  const context = vm.createContext({
    S: state,
    localStorage: {
      getItem(key) { reads.push(key); return storage[key] == null ? null : storage[key]; },
      setItem(key, value) { writes.push([key, value]); storage[key] = value; }
    },
    CustomEvent: function (type, opts) { this.type = type; this.detail = opts.detail; },
    addEventListener(type, fn) { (listeners[type] || (listeners[type] = [])).push(fn); },
    dispatchEvent(event) { (listeners[event.type] || []).forEach(fn => fn(event)); },
    ST_PRIVATE_WEB_PROFILE: role ? { profile: 'personal-market', role } : null
  });
  context.window = context;
  vm.runInContext(contractSource, context);
  return { context, api: context.PortfolioContext, writes, reads, storage };
}

const valid = () => ({ '2330': { shares: 100, lastPrice: 1000, entry: 500, mkt: 'TW', notes: '私人筆記' } });
const empty = harness({ positions: {}, wl: [{ t: '2330', m: 'TW' }] });
check(empty.api.getMode() === 'actual', '預設為實際持倉');
check(!empty.api.resolve().ready && empty.api.resolve().holdings.length === 0, '空持倉不退回自選等權');
check(empty.api.resolve('observation_pool').ready && empty.api.resolve('observation_pool').holdings[0].weight === 1,
  '觀察池只有明確選擇才採等權');

for (const value of [0, -1, NaN, Infinity, null, undefined, '', true, '錯誤']) {
  for (const field of ['shares', 'lastPrice']) {
    const positions = valid();
    positions['2330'][field] = value;
    const result = harness({ positions }).api.resolve();
    check(!result.ready && result.holdings.length === 0 && result.coverage.excluded === 1,
      field + ' 拒絕缺漏或無效數值：' + String(value));
  }
}
const positions = valid();
positions['0050'] = { shares: 10, entry: 50, mkt: 'TW' };
const partial = harness({ positions }).api.resolve();
check(!partial.ready && partial.holdings.length === 0 && partial.coverage.included === 1,
  '部分有效仍停止整組計算，成本不冒充現價');
check(partial.issues[0].action.length > 0, '缺漏附有改善方式');

const state = { positions: valid() };
const before = JSON.stringify(state);
const actual = harness(state);
const result = actual.api.resolve();
check(result.ready && result.holdings[0].weight === 100000 && result.currency === 'TWD', '實際市值只採有效股數與現價');
check(JSON.stringify(state) === before && actual.writes.length === 0, '解析不改持倉也不寫入儲存');
check(!JSON.stringify(result).includes('私人筆記') && !JSON.stringify(result).includes('entry'), '輸出不帶私人筆記或成本');

const mixed = valid();
mixed.NVDA = { shares: 2, lastPrice: 100, mkt: 'US' };
const mixedResult = harness({ positions: mixed }).api.resolve();
check(!mixedResult.ready && !mixedResult.coverage.comparable && mixedResult.holdings.length === 0,
  '無匯率時不可混合新臺幣與美元市值');
const unknown = harness({ positions: { ABC: { shares: 1, lastPrice: 2, mkt: 'UNKNOWN' } } }).api.resolve();
check(!unknown.ready, '未知市場與幣別停止計算');
check(!harness({ positions: { '2330': { shares: 1e-300, lastPrice: 1e-300, mkt: 'TW' } } }).api.resolve().ready,
  '市值數值下溢至零時拒收');
check(!harness({ positions: { '2330': { shares: 1e308, lastPrice: 1, mkt: 'TW' }, '0050': { shares: 1e308, lastPrice: 1, mkt: 'TW' } } }).api.resolve().ready,
  '個別有限但總市值溢位時停止計算');
check(!harness({ positions: { '2330': { shares: 1, lastPrice: 100, mkt: 'TW', currency: 'USD' } } }).api.resolve().ready,
  '市場與明示幣別衝突時停止計算');

const secretStorage = { stock_terminal_positions_v2: JSON.stringify(valid()), st_wl: '[{"t":"2330"}]' };
const reader = harness({ positions: valid() }, secretStorage, 'reader');
const readerResult = reader.api.resolve();
check(!readerResult.ready && readerResult.holdings.length === 0 && readerResult.coverage.total === 0,
  '唯讀角色不暴露私人持倉或數量');
check(!reader.reads.includes('stock_terminal_positions_v2') && !reader.reads.includes('st_wl'), '唯讀角色不讀取私人儲存內容');

const eventHarness = harness({ positions: valid(), wl: [{ t: '0050', m: 'TW' }] });
const events = [];
eventHarness.context.addEventListener('portfolioContext', event => events.push(event.detail));
eventHarness.api.setMode('observation_pool');
check(eventHarness.api.getMode() === 'observation_pool' && events.length === 1 && events[0].previousMode === 'actual', '模式更新通知所有消費端');
check(eventHarness.writes.length === 1 && eventHarness.writes[0][0] === 'st_portfolio_mode_v1' && eventHarness.writes[0][1] === 'observation_pool',
  '只儲存模式字串，不儲存持倉');
check(!JSON.stringify(events).includes('holdings'), '模式事件不攜帶私人持倉');
eventHarness.api.setMode('observation_pool');
check(events.length === 1, '相同模式不重複通知');
assert.throws(() => eventHarness.api.setMode('custom'), /模式/);
eventHarness.context.dispatchEvent({ type: 'storage', key: 'st_portfolio_mode_v1', newValue: 'actual' });
check(eventHarness.api.getMode() === 'actual' && events.length === 2 && events[1].reason === 'storage', '跨分頁模式同步但不重寫儲存');
const oldStorage = harness(undefined, secretStorage);
check(oldStorage.api.resolve().ready, '狀態尚未初始化時可讀取既有持倉鍵');
check(!harness({ positions: {} }, secretStorage).api.resolve().ready, '已初始化的空持倉不被舊儲存復活');
check(!harness({ wl: [] }, secretStorage).api.resolve('observation_pool').ready, '已清空自選不被舊儲存復活');

// 有界 DOM 替身只驗證狀態／請求順序，不取代真實瀏覽器排版驗收。
function bookHarness(state, role) {
  const env = harness(state, {}, role);
  const elements = {};
  function element(id) {
    const attrs = {};
    const classes = new Set();
    const node = {
      id, value: '', textContent: '', style: {}, buttons: [],
      classList: {
        add(value) { classes.add(value); },
        remove(value) { classes.delete(value); },
        contains(value) { return classes.has(value); },
        toggle(value, force) {
          const on = force === undefined ? !classes.has(value) : force;
          if (on) classes.add(value); else classes.delete(value);
          return on;
        }
      },
      setAttribute(key, value) { attrs[key] = value; },
      getAttribute(key) { return attrs[key] || null; },
      appendChild(child) { elements[child.id] = child; },
      querySelectorAll(selector) { return selector === '[data-src]' ? this.buttons : []; }
    };
    let html = '';
    Object.defineProperty(node, 'innerHTML', {
      get() { return html; },
      set(value) {
        html = value;
        if (id !== 'mount-book') return;
        for (const match of value.matchAll(/id="([^"]+)"/g)) elements[match[1]] = element(match[1]);
        node.buttons = [...value.matchAll(/data-src="([^"]+)"/g)].map(match => {
          const button = element('按鈕-' + match[1]);
          button.setAttribute('data-src', match[1]);
          return button;
        });
      }
    });
    return node;
  }
  elements['view-book'] = element('view-book');
  elements['mount-book'] = element('mount-book');
  env.context.document = {
    readyState: 'complete',
    head: { appendChild(node) { elements[node.id] = node; } },
    getElementById(id) { return elements[id] || null; },
    createElement() { return element(''); },
    addEventListener() {}
  };
  env.context.setTimeout = () => 0;
  env.context.AbortController = AbortController;
  const requests = [];
  env.context.fetch = (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
  vm.runInContext(bookSource, env.context);
  return Object.assign(env, { elements, requests, book: env.context.BookV5 });
}
function portfolioResponse(sym) {
  return { stocks: { [sym]: { weight: 100, beta: 1, vol: 20, name: sym } },
    portfolio: { var95: 1, vol: 20, days: 100 }, benchmark: '^TWII', skipped: [] };
}
async function settle(request, data) {
  request.resolve({ ok: true, json: () => Promise.resolve(data) });
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
}

(async function verifyBook() {
  const emptyBook = bookHarness({ positions: {}, wl: [{ t: '2330', m: 'TW' }] });
  emptyBook.book.activate();
  check(emptyBook.requests.length === 0 && emptyBook.book.last() === null, '投組頁空持倉不發送自選替代請求');
  check(emptyBook.elements['bk-body'].innerHTML.includes('尚未建立實際持倉'), '投組頁顯示空持倉與改善方式');
  const readerBook = bookHarness({ positions: valid(), wl: [{ t: '2330', m: 'TW' }] }, 'reader');
  readerBook.book.activate();
  check(readerBook.requests.length === 0 && !readerBook.elements['bk-edit'].value.includes('2330'), '唯讀角色投組頁不展示或送出私人部位');

  const liveState = { positions: valid(), wl: [{ t: '0050', m: 'TW' }] };
  const page = bookHarness(liveState);
  page.book.activate();
  check(page.requests.length === 1 && JSON.parse(page.requests[0].options.body).portfolioKind === 'actual', '投組頁依共用實際模式發送市值權重');
  page.api.setMode('observation_pool');
  check(page.requests.length === 2 && page.requests[0].options.signal.aborted, '切換共用模式中止前次瀏覽器請求並建立新代次');
  check(JSON.parse(page.requests[1].options.body).holdings[0].weight === 1, '等權觀察池請求保留明確模式');
  await settle(page.requests[1], portfolioResponse('0050'));
  const newHtml = page.elements['bk-body'].innerHTML;
  await settle(page.requests[0], portfolioResponse('2330'));
  check(page.elements['bk-body'].innerHTML === newHtml && !!page.book.last().stocks['0050'], '晚到舊模式回應不能覆蓋新結果');
  check(page.elements['bk-sub'].textContent.includes('非實際持倉'), '觀察池結果持續標示非實際持倉');

  page.api.setMode('actual');
  const waiting = page.requests[2];
  liveState.positions = {};
  await settle(waiting, portfolioResponse('2330'));
  check(page.book.last() === null && page.elements['bk-body'].innerHTML.includes('尚未建立實際持倉'), '請求期間清空持倉使回應失效');

  const partialState = { positions: valid() };
  partialState.positions['0050'] = { shares: 10, entry: 40, mkt: 'TW' };
  const partialBook = bookHarness(partialState);
  partialBook.book.activate();
  check(partialBook.requests.length === 0 && partialBook.elements['bk-mode-details'].textContent.includes('1／2'), '部分市值缺漏顯示覆蓋率且不送部分持倉');
  const nonTw = bookHarness({ positions: { NVDA: { shares: 2, lastPrice: 100, mkt: 'US' } } });
  nonTw.book.activate();
  check(nonTw.requests.length === 0 && nonTw.elements['bk-body'].innerHTML.includes('僅支援臺股'), '後端臺股限定時不誤送美股分析');

  const simulation = bookHarness({ positions: valid(), wl: [{ t: '0050', m: 'TW' }] });
  simulation.book.activate();
  simulation.elements['bk-edit'].value = '2330 0';
  simulation.elements['bk-edit'].oninput();
  simulation.elements['bk-run'].onclick();
  check(simulation.requests.length === 1 && simulation.book.last() === null && simulation.elements['bk-body'].innerHTML.includes('權重不是有效正數'), '手動模擬零權重不以一取代');
  simulation.elements['bk-edit'].value = '2330 40';
  simulation.elements['bk-edit'].oninput();
  simulation.elements['bk-run'].onclick();
  check(JSON.parse(simulation.requests[1].options.body).portfolioKind === 'simulation' && simulation.api.getMode() === 'actual', '手動模擬有獨立標籤且不冒充共用實際持倉');
  await settle(simulation.requests[1], portfolioResponse('2330'));
  check(simulation.elements['bk-sub'].textContent.includes('情境模擬'), '模擬結果持續保留模式標籤');
  simulation.api.setMode('observation_pool');
  check(JSON.parse(simulation.requests[2].options.body).portfolioKind === 'observation_pool', '共用模式事件使投組頁退出本頁模擬');

  const skipped = bookHarness({ positions: valid() });
  skipped.book.activate();
  const incomplete = portfolioResponse('2330');
  incomplete.skipped = ['2330'];
  await settle(skipped.requests[0], incomplete);
  check(skipped.book.last() !== null && skipped.elements['bk-body'].innerHTML.includes('資料不足') && skipped.elements['bk-body'].innerHTML.includes('2330'), '歷史缺漏保留已知標的與未知風險，不縮減分母或隱藏整份結果');

  const stopped = bookHarness({ positions: valid() });
  stopped.book.activate();
  stopped.book.deactivate();
  await settle(stopped.requests[0], portfolioResponse('2330'));
  check(stopped.book.last() === null, '離開投組頁後晚到回應不留下可用舊結果');

  const hydrate = bookHarness({ positions: valid(), wl: [{ t: '0050', m: 'TW' }] });
  let finishHydrate;
  hydrate.context.WaveDeckBridge = {
    streamStatus: () => ({ ok: false }),
    fetchState: () => new Promise(resolve => { finishHydrate = resolve; })
  };
  hydrate.book.activate();
  await settle(hydrate.requests[0], portfolioResponse('2330'));
  const oldHydrate = finishHydrate;
  hydrate.api.setMode('observation_pool');
  oldHydrate();
  await new Promise(resolve => setImmediate(resolve));
  check(hydrate.book.last() === null && hydrate.elements['bk-body'].innerHTML.includes('分析中'), '橋接狀態延後完成也不能呈現舊模式成果');

  const errors = bookHarness({ positions: valid(), wl: [{ t: '0050', m: 'TW' }] });
  errors.book.activate();
  errors.api.setMode('observation_pool');
  await settle(errors.requests[1], portfolioResponse('0050'));
  errors.requests[0].reject(new Error('舊請求失敗'));
  await new Promise(resolve => setImmediate(resolve));
  check(!!errors.book.last().stocks['0050'] && !errors.elements['bk-body'].innerHTML.includes('舊請求失敗'), '晚到舊錯誤不能蓋掉新成功結果');
  console.log('投組資料契約與頁面行為測試完成：' + checks + ' 項。');
}()).catch(error => {
  console.error('投組契約測試失敗：' + error.message);
  process.exitCode = 1;
});

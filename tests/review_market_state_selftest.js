'use strict';
// 假時鐘與離線刷新：不啟動瀏覽器、不呼叫網路。
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.resolve(__dirname, '..');
let now = Date.parse('2026-10-08T01:00:00Z');
class Clock extends Date {
  constructor(...args) { super(...(args.length ? args : [now])); }
  static now() { return now; }
}
let response = { ok: false };
const context = {
  Date: Clock, location: { origin: 'http://offline.test' },
  CustomEvent: function (name, detail) { this.detail = detail; },
  dispatchEvent() {}, AppKernel: { api: { getJson: () => Promise.resolve(response) } }
};
context.window = context;
vm.createContext(context);
for (const file of ['src/core/market_freshness_v5.js', 'src/core/market_data_v5.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context);
}
async function main() {
  const snapshot = { ok: true, quotes: { '^TWII': { market: { asOf: new Clock().toISOString() } } } };
  context.MarketData.publish(snapshot);
  assert.equal(context.MarketData.get().freshness.freshness, 'fresh');
  await context.MarketData.refresh();
  assert(context.MarketData.get().refreshError);
  now += 121000;
  assert.equal(context.MarketData.get().freshness.freshness, 'delayed');
  now += 900000;
  assert.equal(context.MarketData.get().freshness.freshness, 'stale');
  response = { ok: true, quotes: { '^TWII': { market: { asOf: new Clock().toISOString() } } } };
  await context.MarketData.refresh();
  assert.equal(context.MarketData.get().freshness.freshness, 'fresh');
  assert.equal(context.MarketData.get().refreshError, null);
  // 載入核心不得初始化 ICU；首次日期轉換才建 formatter，之後重用。
  let constructors = 0;
  const scope = { window: {}, Intl: { DateTimeFormat: function (...args) {
    constructors++;
    return new Intl.DateTimeFormat(...args);
  } } };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'src/screener/backtest_v3.js'), 'utf8'), scope, { timeout: 3000 });
  assert.equal(constructors, 0);
  assert.equal(scope.window.Backtest.dateKey(Date.parse('2026-10-08T01:00:00Z') / 1000, 'TW'), '2026-10-08');
  scope.window.Backtest.dateKey(Date.parse('2026-10-08T01:00:00Z') / 1000, 'TW');
  assert.equal(constructors, 1);
  assert.throws(() => scope.window.Backtest.dateKey(Date.parse('2026-10-08T01:00:00Z') / 1000, 'JP'), /日期契約/);
  const elements = Object.create(null);
  for (const id of ['ds-style', 'ds-modal', 'ds-box', 'ds-list', 'ds-all', 'ds-st', 'ds-density']) {
    elements[id] = { style: {}, textContent: '', value: 'month' };
  }
  const buttons = ['db', 'macro'].map(id => ({ getAttribute: () => id }));
  elements['ds-box'].querySelector = id => elements[id.slice(1)];
  elements['ds-box'].querySelectorAll = () => buttons;
  const calls = []; let opened = 0;
  const ui = { document: { getElementById: id => elements[id] || null },
    localStorage: { getItem: () => null, setItem() {} },
    DailyCacheUI: { open() { opened++; } },
    fetch: async (url, opts) => {
      if (url.endsWith('/datasources')) return { ok: true, json: async () => ({ sources: [
        { id: 'db', name: '日線', updatable: true }, { id: 'macro', name: '指數', updatable: true }
      ] }) };
      calls.push(JSON.parse(opts.body)); return { json: async () => ({ ok: true }) };
    } };
  ui.window = ui;
  vm.runInNewContext(fs.readFileSync(path.join(root, 'src/ui/datasources_v3.js'), 'utf8'), ui);
  await ui.datasourcesOpen();
  await elements['ds-all'].onclick();
  assert.equal(opened, 0);
  assert.deepEqual(calls.map(x => x.id), ['macro']);
  assert.match(elements['ds-st'].textContent, /日線未更新/);
  await buttons[0].onclick();
  assert.equal(opened, 1);
  assert.equal(elements['ds-modal'].style.display, 'none');
  const cacheElements = {};
  for (const id of ['dc-start', 'dc-cancel', 'dc-status', 'dc-range', 'dc-source', 'dc-warm', 'dc-close']) {
    cacheElements[id] = { disabled: false, textContent: '', value: id === 'dc-source' ? 'history' : '1y' };
  }
  const dialog = { open: false, style: {}, innerHTML: '', isConnected: true, appendChild() {},
    querySelectorAll: () => [{ dataset: { dcSymbol: '2330', dcMarket: 'TW' } }],
    showModal() { this.open = true; }, close() { this.open = false; } };
  let fetches = 0, cacheReject = true, cacheJobStatus = 'running';
  const cacheTimers = [];
  const cacheScope = { window: {}, S: { sym: '2330', mkt: 'TW' }, HTMLElement: class {},
    document: { body: { appendChild() {} }, activeElement: null,
      getElementById: id => cacheElements[id] || null, createElement: () => dialog },
    clearTimeout() {}, setTimeout(callback) { cacheTimers.push(callback); return cacheTimers.length; }, setInterval() { return 1; }, clearInterval() {},
    fetch: async (url) => {
      fetches++;
      if (url === '/daily-cache/refresh' && cacheReject) return { ok: false, status: 409, json: async () => ({ error: '已有日線更新進行中，請等待完成或取消' }) };
      return { ok: true, json: async () => ({ jobId: 'existing', status: cacheJobStatus }) };
    } };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'src/ui/daily_cache_v3.js'), 'utf8'), cacheScope);
  cacheScope.window.DailyCacheUI.open();
  await new Promise(resolve => setImmediate(resolve));
  await cacheElements['dc-start'].onclick();
  assert(fetches >= 3);
  assert.match(cacheElements['dc-status'].textContent, /更新中/);
  assert.match(cacheElements['dc-status'].textContent, /本次選擇未被接受.*已有日線更新進行中/);
  await cacheTimers.at(-1)();
  assert.match(cacheElements['dc-status'].textContent, /本次選擇未被接受/);
  assert.equal(cacheElements['dc-start'].disabled, true);
  assert.equal(cacheElements['dc-cancel'].disabled, false);
  cacheJobStatus = 'completed'; await cacheTimers.at(-1)();
  assert.equal(cacheElements['dc-start'].disabled, false);
  assert.match(cacheElements['dc-status'].textContent, /本次選擇未被接受/);
  cacheReject = false; await cacheElements['dc-start'].onclick();
  assert.doesNotMatch(cacheElements['dc-status'].textContent, /本次選擇未被接受/);
  const watchButton = { disabled: false, dataset: { on: '1' }, style: {} };
  let watchResponse = { ok: false, status: 403, json() { throw Error('Reader 不得讀取私人回應'); } };
  const watchScope = { document: { getElementById: () => watchButton }, window: {},
    fetch: async () => watchResponse };
  const pro = fs.readFileSync(path.join(root, 'src/core/pro_v2.js'), 'utf8');
  const from = pro.indexOf('function refreshWatchBgBtn()');
  const until = pro.indexOf('async function toggleWatchBg', from);
  assert(from >= 0 && until > from);
  vm.runInNewContext(pro.slice(from, until), watchScope);
  watchScope.refreshWatchBgBtn();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(watchButton.disabled, true);
  assert.equal(watchButton.dataset.on, '');
  assert.equal(watchButton.textContent, '僅擁有者可用');
  watchResponse = { ok: true, status: 200, json: async () => ({ enabled: true, rules_count: 2, last_run: '測試' }) };
  watchScope.refreshWatchBgBtn();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(watchButton.disabled, false);
  assert.equal(watchButton.dataset.on, '1');
  assert.match(watchButton.title, /規則 2 檔/);

  // 真正載入完整模組；只模擬瀏覽器平台，不注入產品缺少的函式或全域變數。
  function browserDocument() {
    const doc = { readyState: 'loading', addEventListener() {} };
    const voidTags = new Set(['input', 'br', 'hr', 'img', 'meta', 'link']);
    function matches(node, selector) {
      const tag = selector.match(/^[a-z]+/i);
      if (tag && node.tagName !== tag[0].toLowerCase()) return false;
      const id = selector.match(/#([\w-]+)/);
      if (id && node.id !== id[1]) return false;
      const classes = [...selector.matchAll(/\.([\w-]+)/g)];
      if (classes.some(match => !node.className.split(/\s+/).includes(match[1]))) return false;
      for (const match of selector.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)) {
        if (!(match[1] in node.attributes)) return false;
        if (match[2] !== undefined && node.attributes[match[1]] !== match[2]) return false;
      }
      return true;
    }
    function select(parent, selector) {
      const selectors = selector.split(',').map(value => value.trim());
      const result = [];
      function visit(node) {
        for (const child of node.children) {
          if (selectors.some(value => {
            const parts = value.split(/\s+/); let current = child;
            if (!matches(current, parts.pop())) return false;
            while (parts.length) {
              const previous = parts.pop(); current = current.parentNode;
              while (current && current !== parent && !matches(current, previous)) current = current.parentNode;
              if (!current || !matches(current, previous)) return false;
            }
            return true;
          })) result.push(child);
          visit(child);
        }
      }
      visit(parent); return result;
    }
    function element(tag) {
      let html = '';
      const node = { tagName: tag.toLowerCase(), id: '', className: '', attributes: {},
        children: [], parentNode: null, style: {}, dataset: {}, textContent: '', value: '',
        classList: { remove() {}, add() {} }, addEventListener() {},
        appendChild(child) { child.parentNode = this; this.children.push(child); return child; },
        getAttribute(name) { return name === 'id' ? this.id : this.attributes[name] ?? null; },
        querySelectorAll(selector) { return select(this, selector); },
        querySelector(selector) { return this.querySelectorAll(selector)[0] || null; } };
      Object.defineProperty(node, 'innerHTML', { get() { return html; }, set(value) {
        html = String(value); this.children = [];
        const stack = [this];
        for (const match of html.matchAll(/<\/?([a-z][a-z0-9]*)\b([^>]*)>/gi)) {
          const tagName = match[1].toLowerCase();
          if (match[0].startsWith('</')) {
            const index = stack.map(item => item.tagName).lastIndexOf(tagName);
            if (index > 0) stack.length = index;
            continue;
          }
          const child = element(tagName);
          for (const attr of match[2].matchAll(/([\w-]+)(?:="([^"]*)"|='([^']*)'|=([^\s>]+))?/g)) {
            const key = attr[1], text = attr[2] ?? attr[3] ?? attr[4] ?? '';
            child.attributes[key] = text;
            if (key === 'id') child.id = text;
            if (key === 'class') child.className = text;
            if (key === 'value') child.value = text;
            if (key === 'checked') child.checked = true;
            if (key.startsWith('data-')) child.dataset[key.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = text;
          }
          stack[stack.length - 1].appendChild(child);
          if (!voidTags.has(tagName) && !match[0].endsWith('/>')) stack.push(child);
        }
      } });
      return node;
    }
    doc.head = element('head'); doc.body = element('body');
    doc.createElement = element;
    doc.querySelectorAll = selector => [...doc.head.querySelectorAll(selector), ...doc.body.querySelectorAll(selector)];
    doc.getElementById = id => doc.querySelectorAll('#' + id)[0] || null;
    const panel = element('div'); panel.id = 'view-news'; doc.body.appendChild(panel);
    return doc;
  }
  const alertDoc = browserDocument();
  let role = 'reader', privateReads = 0, ruleList = [{ sym: '2330', market: 'TW', price: 100, note: '離線私人規則' }];
  let blockedOwnerConfig = null;
  const alertCalls = [], writeCalls = [], writeAlerts = [];
  let writeFailure = null, pendingRuleWrite = null;
  function reply(status, data) {
    return { ok: status === 200, status, async json() {
      if (status !== 200) { privateReads++; throw Error('錯誤回應不得解析私人內容'); }
      return JSON.parse(JSON.stringify(data));
    } };
  }
  const ownerConfig = { enabled: true, running: true, telegram: { enabled: true, chat_id: 'offline-private-chat' } };
  const alertBrowser = { document: alertDoc, SERVER: 'http://offline.test', Date: Clock,
    addEventListener() {}, setTimeout() { return 1; }, clearTimeout() {},
    setInterval() { return 1; }, clearInterval() {}, alert(message) { writeAlerts.push(String(message)); },
    fetch: async (url, options = {}) => {
      const endpoint = new URL(url).pathname; alertCalls.push(endpoint);
      if (options.method === 'POST') {
        writeCalls.push({ endpoint, body: JSON.parse(options.body) });
        if (writeFailure === 'pending') return new Promise(resolve => {
          pendingRuleWrite = () => { ruleList = JSON.parse(options.body); resolve(reply(200, { ok: true })); };
        });
        if (writeFailure === 'network') throw Error('離線寫入連線失敗');
        if (writeFailure) return reply(writeFailure);
        if (endpoint === '/alert/rules') ruleList = JSON.parse(options.body);
        return reply(200, endpoint === '/alert/test' ? { results: { offline: true } } : { ok: true });
      }
      if (endpoint === '/events') return reply(200, {});
      if (endpoint === '/flash') return reply(200, { items: [] });
      if (endpoint === '/alert/config' && role === 'pending-owner') {
        return new Promise(resolve => { blockedOwnerConfig = () => resolve(reply(200, ownerConfig)); });
      }
      if (role === 'reader' || (role === 'rules-forbidden' && endpoint === '/alert/rules')) return reply(403);
      if (role === 'http-error' || (role === 'rules-error' && endpoint === '/alert/rules')) return reply(503);
      if (role === 'network-error') throw Error('離線連線失敗');
      if (endpoint === '/alert/status') return reply(200, { running: true });
      if (endpoint === '/alert/config') return reply(200, ownerConfig);
      if (endpoint === '/alert/rules') return reply(200, ruleList);
      throw Error('未預期的端點：' + endpoint);
    } };
  alertBrowser.window = alertBrowser;
  vm.createContext(alertBrowser);
  for (const file of ['src/ui/news_v5.js', 'src/alert/alert_push_v3.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), alertBrowser, { filename: file, timeout: 3000 });
  }
  const settleAlert = () => new Promise(resolve => setImmediate(resolve));
  const alertBody = () => alertDoc.getElementById('ap-body');
  const alertStatus = () => alertDoc.getElementById('ap-status');
  function noPrivateForms() {
    assert.equal(alertBody().querySelector('input, select, table'), null);
    assert.doesNotMatch(alertBody().innerHTML, /offline-private-chat|離線私人規則/);
  }
  alertBrowser.NewsV5.refresh(); alertBrowser.alertPushOpen();
  await settleAlert();
  assert.match(alertDoc.getElementById('nw-body').innerHTML, /僅擁有者可見/);
  assert.equal(alertStatus().textContent, '僅擁有者可見'); noPrivateForms();
  assert.equal(privateReads, 0);
  role = 'owner';
  alertBrowser.NewsV5.refresh(); alertBrowser.alertPushOpen();
  await settleAlert();
  assert.match(alertDoc.getElementById('nw-body').innerHTML, /運行中/);
  assert(alertDoc.getElementById('ap-save'));
  assert.match(alertBody().innerHTML, /offline-private-chat|離線私人規則/);
  assert.match(alertBody().innerHTML, /daemon 執行中.*規則 1 條/);
  role = 'reader'; alertBrowser.alertPushOpen();
  noPrivateForms(); // 回應抵達前已清除前一次 Owner 的表單與規則。
  await settleAlert();
  assert.equal(alertStatus().textContent, '僅擁有者可見'); noPrivateForms();
  alertDoc.getElementById('ap-close2').onclick();
  assert.equal(alertDoc.getElementById('ap-modal').style.display, 'none');
  role = 'rules-forbidden'; alertBrowser.alertPushOpen(); await settleAlert();
  assert.equal(alertStatus().textContent, '僅擁有者可見'); noPrivateForms();
  for (role of ['http-error', 'rules-error', 'network-error']) {
    alertBrowser.NewsV5.refresh(); alertBrowser.alertPushOpen(); await settleAlert();
    assert.match(alertStatus().textContent, /讀取失敗，無法確認 daemon 狀態/);
    assert.doesNotMatch(alertBody().innerHTML, /daemon 未啟動/); noPrivateForms();
    if (role === 'http-error') assert.match(alertDoc.getElementById('nw-body').innerHTML, /讀取失敗（HTTP 503）/);
    if (role === 'network-error') assert.match(alertDoc.getElementById('nw-body').innerHTML, /讀取失敗，無法確認警報狀態/);
  }
  role = 'pending-owner'; alertBrowser.alertPushOpen(); await settleAlert();
  assert.equal(typeof blockedOwnerConfig, 'function');
  role = 'reader'; alertBrowser.alertPushOpen(); await settleAlert();
  blockedOwnerConfig(); await settleAlert();
  assert.equal(alertStatus().textContent, '僅擁有者可見'); noPrivateForms();
  role = 'owner'; ruleList = [];
  alertBrowser.NewsV5.refresh(); alertBrowser.alertPushOpen(); await settleAlert();
  assert.match(alertDoc.getElementById('nw-body').innerHTML, /運行中/);
  assert(alertDoc.getElementById('ap-save'));
  assert.match(alertBody().innerHTML, /daemon 執行中.*規則 0 條/);
  assert.doesNotMatch(alertBody().innerHTML, /離線私人規則/);
  assert.equal(privateReads, 0);
  assert(alertCalls.includes('/alert/status') && alertCalls.includes('/alert/config') && alertCalls.includes('/alert/rules'));
  // 透過完整模組的真實按鈕驗證 Owner 寫入；錯誤回應仍不可解析私人 body。
  const unhandledWrites = [];
  const captureUnhandledWrite = error => unhandledWrites.push(error);
  process.on('unhandledRejection', captureUnhandledWrite);
  const actions = [
    { selector: '#ap-save', endpoint: '/alert/config', label: '儲存設定', success: /已儲存/ },
    { selector: '#ap-test', endpoint: '/alert/test', label: '測試推播', success: /測試結果/ },
    { selector: '#ap-r-add', endpoint: '/alert/rules', label: '儲存規則', setup() {
      alertDoc.getElementById('ap-r-sym').value = '2317';
      alertDoc.getElementById('ap-r-price').value = '120';
    } },
    { selector: '#ap-c-add', endpoint: '/alert/rules', label: '儲存規則', setup() {
      alertDoc.getElementById('ap-c-sym').value = '2317';
      const row = alertBody().querySelector('.ap-cc');
      row.querySelector('.ap-cc-l').value = 'close'; row.querySelector('.ap-cc-op').value = 'gt';
      row.querySelector('.ap-cc-r').value = '120';
    } },
    { selector: '[data-del]', endpoint: '/alert/rules', label: '儲存規則' },
  ];
  let writeScenarios = 0, recoveryScenarios = 0;
  try {
    for (const action of actions) {
      for (const failure of [400, 503, 'network', null]) {
        role = 'owner'; writeFailure = null;
        ruleList = [{ sym: '2330', market: 'TW', price: 100, note: '離線私人規則' }];
        alertBrowser.alertPushOpen(); await settleAlert();
        const confirmedRules = JSON.parse(JSON.stringify(ruleList));
        if (action.setup) action.setup();
        const button = alertBody().querySelector(action.selector);
        assert(button, action.selector + ' 必須由完整模組建立');
        const previousCalls = writeCalls.length, previousAlerts = writeAlerts.length;
        writeFailure = failure;
        await assert.doesNotReject(Promise.resolve(button.onclick()), action.label + ' 不得洩漏 rejected promise');
        await settleAlert();
        assert.equal(writeCalls.length, previousCalls + 1);
        assert.equal(writeCalls.at(-1).endpoint, action.endpoint);
        assert.equal(privateReads, 0, '錯誤回應 body 不得被讀取');
        assert.equal(unhandledWrites.length, 0, '事件分派不得留下 unhandled rejection');
        if (failure) {
          assert.equal(writeAlerts.length, previousAlerts + 1);
          assert.match(writeAlerts.at(-1), new RegExp(action.label + '失敗'));
          assert.equal(alertStatus().textContent, writeAlerts.at(-1));
          assert.match(writeAlerts.at(-1), failure === 'network' ? /連線或回應異常/ : new RegExp('HTTP ' + failure));
          assert(alertDoc.getElementById('ap-save'), '失敗不得丟失可重試的表單');
          assert.deepEqual(ruleList, confirmedRules, 'HTTP fixture 不得與產品共用陣列');
          if (action.endpoint === '/alert/rules') {
            writeFailure = null;
            if (action.selector === '[data-del]') {
              alertDoc.getElementById('ap-r-sym').value = '2317';
              alertDoc.getElementById('ap-r-price').value = '120';
              alertDoc.getElementById('ap-r-add').onclick();
            } else alertBody().querySelector('[data-del]').onclick();
            await settleAlert();
            const subsequent = writeCalls.at(-1).body;
            if (action.selector === '[data-del]') {
              assert.deepEqual(subsequent.slice(0, 1), confirmedRules, '後續新增不得夾帶前次失敗刪除');
              assert.equal(subsequent.length, 2);
            } else assert.deepEqual(subsequent, [], '後續刪除不得夾帶前次失敗新增');
            recoveryScenarios++;
          }
        } else if (action.success) {
          assert.equal(writeAlerts.length, previousAlerts + 1);
          assert.match(writeAlerts.at(-1), action.success);
        } else {
          assert.equal(writeAlerts.length, previousAlerts);
          assert.match(alertBody().innerHTML, /daemon 執行中/);
          const expectedRules = action.selector === '[data-del]' ? 0 : 2;
          assert.equal(writeCalls.at(-1).body.length, expectedRules);
          assert.match(alertBody().innerHTML, new RegExp('規則 ' + expectedRules + ' 條'));
        }
        writeScenarios++;
      }
    }
  } finally { process.removeListener('unhandledRejection', captureUnhandledWrite); }
  assert.equal(writeScenarios, 20);
  assert.equal(recoveryScenarios, 9);
  ruleList = [{ sym: '2330', market: 'TW', price: 100 }];
  writeFailure = null; alertBrowser.alertPushOpen(); await settleAlert();
  alertDoc.getElementById('ap-r-sym').value = '2317';
  alertDoc.getElementById('ap-r-price').value = '120';
  writeFailure = 'pending';
  const pendingCalls = writeCalls.length;
  alertDoc.getElementById('ap-r-add').onclick(); await settleAlert();
  assert.equal(typeof pendingRuleWrite, 'function');
  alertBody().querySelector('[data-del]').onclick(); await settleAlert();
  assert.equal(writeCalls.length, pendingCalls + 1, '寫入中重複操作不得另送未確認的快照');
  assert.match(alertStatus().textContent, /規則儲存中/);
  writeFailure = null; pendingRuleWrite(); await settleAlert();
  assert.equal(ruleList.length, 2);
  assert.equal(privateReads, 0);
  console.log('警報失敗後 9 個後續寫入與重複操作、409 拒收跨輪詢保留及成功清除：通過');
  console.log('Owner 警報寫入 20 個情境：HTTP 400／503、網路失敗、成功、錯誤 body 零讀取與 rejected promise 收尾：通過');
  console.log('行情效期、日期初始化、選定日線更新、拒收後既有工作與 Reader／Owner 警報狀態：通過');
}
main().catch(error => { console.error(error); process.exitCode = 1; });

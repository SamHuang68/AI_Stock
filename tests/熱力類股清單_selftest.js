#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const sourcePath = path.join(root, 'src/ui/heat_v5.js');
const source = fs.readFileSync(sourcePath, 'utf8');
const marker = '  window.HeatV5 = {';
assert.equal(source.split(marker).length, 2, '須能唯一定位測試注入點');
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const ids = new Map();
  const requests = [];
  const loaded = [];
  const navigation = [];
  const diagnostics = [];
  const scheduled = new Map();
  let timerId = 0;
  const decode = value => String(value).replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

  // 此小型 DOM 只處理本介面的元素、屬性與事件；HTML、事件及請求邏輯皆執行正式原文。
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {};
      this.listeners = new Map(); this.open = false; this.value = ''; this._text = ''; this._html = '';
      this.classList = {
        contains: name => this.classes().includes(name),
        add: (...names) => { this.attrs.class = [...new Set([...this.classes(), ...names])].join(' '); },
        remove: (...names) => { this.attrs.class = this.classes().filter(name => !names.includes(name)).join(' '); },
        toggle: (name, enabled) => {
          if (enabled === undefined) enabled = !this.classList.contains(name);
          if (enabled) this.classList.add(name); else this.classList.remove(name);
          return enabled;
        }
      };
    }
    classes() { return String(this.attrs.class || '').split(/\s+/).filter(Boolean); }
    get id() { return this.attrs.id || ''; }
    set id(value) { this.setAttribute('id', value); }
    get className() { return this.attrs.class || ''; }
    set className(value) { this.attrs.class = value; }
    setAttribute(key, value) { this.attrs[key] = String(value); if (key === 'id') ids.set(String(value), this); }
    getAttribute(key) { return this.attrs[key] ?? null; }
    appendChild(child) { this.children.push(child); child.parent = this; return child; }
    descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
    matches(selector) {
      if (selector.startsWith('.')) return selector.slice(1).split('.').every(name => this.classList.contains(name));
      const attribute = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
      return Boolean(attribute && this.getAttribute(attribute[1]) !== null &&
        (attribute[2] === undefined || this.getAttribute(attribute[1]) === attribute[2]));
    }
    querySelectorAll(selector) { return this.descendants().filter(child => child.matches(selector)); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    addEventListener(name, handler) { this.listeners.set(name, handler); }
    showModal() { this.open = true; }
    close() { this.open = false; this.listeners.get('close')?.({ type: 'close' }); }
    click() { return this.onclick?.({ currentTarget: this }); }
    set textContent(value) { this._text = String(value); }
    get textContent() { return this._text; }
    get innerHTML() { return this._html; }
    set innerHTML(value) {
      for (const child of this.descendants()) if (child.id && ids.get(child.id) === child) ids.delete(child.id);
      this.children = []; this._html = String(value);
      const stack = [this];
      for (const match of this._html.matchAll(/<(\/?)([a-z][\w-]*)\b([^>]*)>/gi)) {
        const [, closing, tag, attributes] = match;
        if (closing) {
          while (stack.length > 1) if (stack.pop().tagName === tag.toUpperCase()) break;
          continue;
        }
        const child = new Element(tag);
        for (const attr of attributes.matchAll(/([\w:-]+)(?:="([^"]*)")?/g)) child.setAttribute(attr[1], decode(attr[2] || ''));
        const parent = stack.at(-1); parent.appendChild(child);
        if (tag === 'option' && parent.tagName === 'SELECT' && !parent.value) parent.value = child.getAttribute('value') || '';
        if (!['input', 'br', 'hr', 'img', 'meta', 'link'].includes(tag)) stack.push(child);
      }
    }
  }

  const head = new Element('head'), body = new Element('body');
  const panel = new Element(); panel.id = 'view-heat'; body.appendChild(panel);
  function payload(market, code = market === 'US' ? 'NVDA' : '2330') {
    return { ok: true, market, sector: market === 'US' ? '科技' : '半導體', scopeLabel: '可驗證的類股成員', date: '2026-09-10',
      rows: [{ code, name: market === 'US' ? '輝達' : '台積電', price: 100, changePct: 2.5, asOf: '2026-09-10' }] };
  }
  function sectors(market) {
    return { market, date: '2026-09-10', sectors: [{ name: market === 'US' ? '科技' : '半導體',
      symbol: market === 'US' ? 'XLK' : '2330', close: 100, changePct: 1.5 }] };
  }
  const sandbox = {
    console, Date, Intl, AbortController,
    window: { SERVER: '', addEventListener() {}, ShellV5: {
      route() { return 'heat'; }, go(route) { navigation.push(route); }, softBadge() {}
    } },
    document: { readyState: 'loading', head, body, addEventListener() {},
      getElementById(id) { return ids.get(id) || null; }, createElement(tag) { return new Element(tag); } },
    loadSym(code, market) { loaded.push({ code, market }); },
    setTimeout(fn) { const id = ++timerId; scheduled.set(id, fn); return id; },
    clearTimeout(id) { scheduled.delete(id); },
    setInterval() { return ++timerId; }, clearInterval() {},
    fetch(url, options = {}) {
      if (url === '/diagnostics/ui-route') {
        diagnostics.push(JSON.parse(options.body)); return Promise.resolve({ ok: true });
      }
      const parsed = new URL(url, 'http://測試.local');
      if (parsed.pathname === '/sectors/members') {
        let resolve, reject;
        const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
        // 刻意允許取消後仍回應，驗證序號防護，而非只依賴 AbortController。
        requests.push({ url: parsed, options,
          succeed(result, status = 200) { resolve({ ok: status === 200, status, json: () => Promise.resolve(result) }); },
          fail(message = '模擬連線中斷') { reject(new Error(message)); } });
        return promise;
      }
      const market = parsed.searchParams.get('mkt') || 'TW';
      const result = parsed.pathname === '/sectors' ? sectors(market) : { ok: true, mkt: market, buy: [], short: [] };
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(result) });
    }
  };
  vm.createContext(sandbox);
  const injection = '  window.__heatTest = { renderHeat, openMembers, closeMembers, selectMemberRows };\n';
  vm.runInContext(source.replace(marker, injection + marker), sandbox, { filename: sourcePath });
  const api = sandbox.window.__heatTest;
  api.renderHeat(sectors('TW'));
  return { api, publicApi: sandbox.window.HeatV5, requests, loaded, navigation, diagnostics, scheduled, payload,
    element(id) { return ids.get(id); },
    cell() { return ids.get('ht-body').querySelector('.ht-cell'); },
    memberCodes() { return ids.get('hm-list')?.querySelectorAll('[data-code]').map(row => row.getAttribute('data-code')) || []; },
    marketButton(market) { return ids.get('mount-heat').querySelectorAll('[data-mkt]').find(button => button.classList.contains('ht-btn') && button.getAttribute('data-mkt') === market); }
  };
}

const cases = [];
const test = (name, run) => cases.push({ name, run });

test('點類股開啟成員清單，點個股才切換圖表', async () => {
  const h = harness(); h.cell().click();
  assert.deepEqual(h.loaded, [], '點類股不載入代表股');
  assert.deepEqual(h.navigation, [], '點類股留在熱力頁');
  assert.equal(h.element('ht-members-dialog').open, true);
  assert.equal(h.requests[0].url.searchParams.get('sector'), '半導體');
  assert.equal(h.requests[0].url.searchParams.get('symbol'), null, '台股不把代表股當成員來源');
  h.requests[0].succeed(h.payload('TW')); await tick();
  assert.deepEqual(h.memberCodes(), ['2330']);
  h.element('hm-list').querySelector('[data-code]').click();
  assert.deepEqual(h.loaded, [{ code: '2330', market: 'TW' }]);
  assert.deepEqual(h.navigation, ['chart']);
  assert.equal(h.element('ht-members-dialog').open, false);
});

test('清單關閉後的晚到成功回應不會重新呈現', async () => {
  const h = harness(); h.cell().click();
  const request = h.requests[0]; h.element('hm-close').click();
  const before = h.element('hm-body').innerHTML;
  assert.equal(request.options.signal.aborted, true);
  request.succeed(h.payload('TW')); await tick();
  assert.equal(h.element('ht-members-dialog').open, false);
  assert.equal(h.element('hm-body').innerHTML, before);
  assert.deepEqual(h.memberCodes(), []);
});

test('切換市場按鈕取消舊清單且晚到台股資料不覆蓋美股', async () => {
  const h = harness(); h.cell().click(); const old = h.requests[0];
  h.marketButton('US').click(); await tick();
  assert.equal(old.options.signal.aborted, true);
  assert.equal(h.element('ht-members-dialog').open, false);
  h.cell().click();
  assert.equal(h.requests[1].url.searchParams.get('mkt'), 'US');
  assert.equal(h.requests[1].url.searchParams.get('symbol'), 'XLK');
  h.requests[1].succeed(h.payload('US')); await tick();
  old.succeed(h.payload('TW')); await tick();
  assert.deepEqual(h.memberCodes(), ['NVDA']);
  assert.equal(h.element('hm-title').textContent, '科技 · 個股清單');
});

test('路由參數切換市場也必須取消舊清單', async () => {
  const h = harness(); h.cell().click(); const old = h.requests[0];
  h.publicApi.activate({ mkt: 'US' }); await tick();
  const wasAborted = old.options.signal.aborted;
  old.succeed(h.payload('TW')); await tick();
  assert.deepEqual(h.memberCodes(), [], '新市場不得呈現晚到的舊市場成員');
  assert.equal(wasAborted, true, '深連結改市場必須中止舊市場清單請求');
  assert.equal(h.element('ht-members-dialog').open, false);
});

test('改選類股後晚到失敗回應不會覆蓋新清單', async () => {
  const h = harness(); h.cell().click(); const old = h.requests[0];
  const next = h.api.openMembers({ market: 'TW', sector: '航運' });
  h.requests[1].succeed({ ...h.payload('TW', '2603'), sector: '航運' }); await next;
  old.fail(); await tick();
  assert.deepEqual(h.memberCodes(), ['2603']);
  assert.equal(h.element('hm-title').textContent, '航運 · 個股清單');
  assert.equal(h.element('hm-retry'), undefined);
});

test('缺少漲跌排序置末，零與負值維持正確順序且不改動原陣列', () => {
  const h = harness();
  const rows = [
    { code: '2002', changePct: null }, { code: '2317', changePct: -1 }, { code: '2330', changePct: 2 },
    { code: '1101', changePct: 0 }, { code: '3008', changePct: '' }, { code: '4904', changePct: '未知' },
    { code: '6505', changePct: Infinity }, { code: '2603', changePct: undefined }
  ];
  const before = rows.slice();
  assert.deepEqual(plain(h.api.selectMemberRows(rows, '', 'change').map(row => row.code)),
    ['2330', '1101', '2317', '2002', '2603', '3008', '4904', '6505']);
  assert.deepEqual(rows, before);
  assert.deepEqual(plain(h.api.selectMemberRows(rows, '', 'code').map(row => row.code)),
    ['1101', '2002', '2317', '2330', '2603', '3008', '4904', '6505']);
});

test('清單搜尋與排序使用實際輸入事件，缺值顯示占位符', async () => {
  const h = harness(); h.cell().click();
  const result = h.payload('TW');
  result.rows.push({ code: '2303', name: '聯電', price: null, changePct: null },
    { code: '3443', name: '創意', price: 300, changePct: -1 });
  h.requests[0].succeed(result); await tick();
  assert.deepEqual(h.memberCodes(), ['2330', '3443', '2303']);
  assert.match(h.element('hm-list').innerHTML, /<span>—<\/span><strong class="">—<\/strong>/);
  h.element('hm-search').value = '聯電'; h.element('hm-search').oninput();
  assert.deepEqual(h.memberCodes(), ['2303']);
  assert.equal(h.element('hm-count').textContent, '顯示 1／3 檔');
  h.element('hm-search').value = ''; h.element('hm-sort').value = 'code'; h.element('hm-sort').onchange();
  assert.deepEqual(h.memberCodes(), ['2303', '2330', '3443']);
});

test('回應市場不符時顯示可重試錯誤，重試仍使用原選取', async () => {
  const h = harness(); h.cell().click();
  h.requests[0].succeed(h.payload('US')); await tick();
  assert.match(h.element('hm-body').innerHTML, /回應市場不符/);
  assert.deepEqual(h.memberCodes(), []);
  h.element('hm-retry').click();
  assert.equal(h.requests[1].url.searchParams.get('mkt'), 'TW');
  assert.equal(h.requests[1].url.searchParams.get('sector'), '半導體');
  h.requests[1].succeed(h.payload('TW')); await tick();
  assert.deepEqual(h.memberCodes(), ['2330']);
});

test('離開熱力頁取消清單，晚到回應不會更動已關閉介面', async () => {
  const h = harness(); h.cell().click(); const old = h.requests[0];
  h.publicApi.deactivate();
  assert.equal(old.options.signal.aborted, true);
  old.succeed(h.payload('TW')); await tick();
  assert.equal(h.element('ht-members-dialog').open, false);
  assert.deepEqual(h.memberCodes(), []);
  assert.ok(h.diagnostics.some(event => event.event === '類股個股讀取取消'));
});

test('讀取逾時後保留重試畫面，晚到成功回應不覆蓋錯誤', async () => {
  const h = harness(); h.cell().click(); const request = h.requests[0];
  assert.equal(h.scheduled.size, 1, '每次成員請求只有一個期限計時器');
  [...h.scheduled.values()][0](); await tick();
  assert.equal(request.options.signal.aborted, true);
  assert.match(h.element('hm-body').innerHTML, /讀取逾時/);
  const before = h.element('hm-body').innerHTML;
  request.succeed(h.payload('TW')); await tick();
  assert.equal(h.element('hm-body').innerHTML, before);
  assert.deepEqual(h.memberCodes(), []);
  assert.equal(h.scheduled.size, 0, '逾時後不殘留計時器');
});

test('部分行情尚未取得時仍列出完整成員並揭露取得數量', async () => {
  const h = harness(); h.cell().click();
  const result = h.payload('TW');
  result.quotedCount = 1;
  result.rows.push({ code: '2303', name: '聯電', price: null, changePct: null });
  h.requests[0].succeed(result); await tick();
  assert.deepEqual(h.memberCodes(), ['2330', '2303']);
  assert.match(h.element('hm-body').innerHTML, /已取得 1／2 檔漲跌，其餘行情尚未取得/);
  assert.equal(h.element('hm-count').textContent, '共 2 檔');
});

test('精確類股名稱優先，選電子不會同時選到電子零組件', () => {
  const h = harness();
  h.api.renderHeat({ sectors: [
    { name: '電子', close: 100, changePct: 2 },
    { name: '電子零組件', close: 100, changePct: 1 }
  ] });
  const cells = h.element('ht-body').querySelectorAll('.ht-cell');
  cells.find(cell => cell.getAttribute('data-name') === '電子').click();
  assert.deepEqual(cells.filter(cell => cell.classList.contains('hi')).map(cell => cell.getAttribute('data-name')), ['電子']);
  assert.equal(cells.find(cell => cell.getAttribute('data-name') === '電子零組件').classList.contains('dim'), true);
  assert.equal(h.requests[0].url.searchParams.get('sector'), '電子');
});

(async () => {
  let failed = 0;
  for (const item of cases) {
    try { await item.run(); console.log('通過：' + item.name); }
    catch (error) { failed++; console.error('失敗：' + item.name + '\n' + error.message); }
  }
  console.log('熱力類股清單：' + (cases.length - failed) + '／' + cases.length + ' 組通過。');
  if (failed) process.exitCode = 1;
})();

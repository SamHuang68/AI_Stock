'use strict';

// 完整執行正式市場廣度模組，以受控 Promise 驗證面板及請求的生命週期。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'ui', 'breadth_v5.js'), 'utf8');

function createHarness() {
  const elements = new Map();
  function element() {
    return { innerHTML: '', textContent: '', querySelector: () => null,
      querySelectorAll: () => [], appendChild() {} };
  }
  for (const id of ['view-breadth', 'mount-breadth', 'bd-root', 'bd-body', 'bd-sub', 'breadth-v5-css']) {
    elements.set(id, element());
  }
  const requests = [], badges = [], bridge = [];
  const timers = new Map();
  let timerId = 0;
  const sandbox = {
    document: {
      getElementById: id => elements.get(id) || null,
      createElement: () => element(), head: { appendChild() {} }, addEventListener() {},
    },
    ShellV5: {
      route: () => 'breadth',
      softBadge(mount, active, text) { badges.push({ mount, active, text }); },
    },
    WaveDeckBridge: {
      lastSync: () => null,
      syncFromMarket: data => bridge.push(data),
    },
    setInterval(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearInterval: id => timers.delete(id),
    fetch(url) {
      return new Promise((resolve, reject) => requests.push({
        url, reject, resolve(data) { resolve({ ok: true, json: async () => data }); },
      }));
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'src/ui/breadth_v5.js' });
  return {
    api: sandbox.BreadthV5, elements, requests, badges, bridge, timers,
    body: elements.get('bd-body'), sub: elements.get('bd-sub'),
    async complete(batch, label) {
      const offset = batch * 3;
      assert.equal(requests[offset].url.split('?')[0], '/breadth');
      requests[offset].resolve({ ok: true, date: label, source: '測試來源', score: 70,
        stocks: { up: 600, down: 300, unchanged: 100, net: 300, advRatio: 2 / 3 },
        summary: label });
      requests[offset + 1].resolve({ rows: [{ date: label, up: 600, down: 300, flat: 100, lsRatio: 2 }] });
      requests[offset + 2].resolve({ gainers: [{ code: label, name: label, changePct: 1 }] });
      await new Promise(resolve => setImmediate(resolve));
    },
    async fail(batch) {
      const offset = batch * 3;
      requests[offset].reject(new Error('測試連線失敗'));
      requests[offset + 1].resolve(null);
      requests[offset + 2].resolve(null);
      await new Promise(resolve => setImmediate(resolve));
    },
  };
}

function assertCurrent(h, label) {
  assert.equal(h.api.last().date, label, '最後資料必須屬於目前請求');
  assert.equal(h.api.last()._hist[0].date, label, '歷史必須與廣度同批');
  assert.equal(h.api.last()._movers.gainers[0].code, label, '強弱榜必須與廣度同批');
  assert.ok(h.sub.textContent.includes(label), '副標必須屬於目前請求');
  assert.ok(h.body.innerHTML.includes(label), '畫面必須屬於目前請求');
}

const cases = [
  ['正常載入呈現廣度、歷史及強弱榜，完成後結束更新標示', async () => {
    const h = createHarness();
    h.api.activate();
    assert.equal(h.requests.length, 3);
    assert.equal(h.timers.size, 1);
    await h.complete(0, '正常資料');
    assertCurrent(h, '正常資料');
    assert.equal(h.bridge.length, 1);
    assert.equal(h.badges.at(-1).active, false);
  }],
  ['同頁請求逆序完成時保留最新畫面與快取', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.refresh(true);
    await h.complete(1, '新資料');
    const rendered = h.body.innerHTML;
    await h.complete(0, '舊資料');
    assertCurrent(h, '新資料');
    assert.equal(h.body.innerHTML, rendered);
    assert.equal(h.bridge.length, 1, '舊回應不得推送 WaveDeck');
  }],
  ['舊成功回應不得結束尚未完成的新請求更新標示', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.refresh(false, { soft: true });
    const displayed = h.body.innerHTML;
    await h.complete(0, '舊資料');
    assert.equal(h.api.last(), null);
    assert.equal(h.body.innerHTML, displayed);
    assert.equal(h.badges.at(-1).active, true);
    assert.equal(h.bridge.length, 0);
    await h.complete(1, '新資料');
    assertCurrent(h, '新資料');
    assert.equal(h.badges.at(-1).active, false);
  }],
  ['舊失敗回應不得覆寫畫面或清除新請求更新標示', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.refresh(false, { soft: true });
    const displayed = h.body.innerHTML;
    await h.fail(0);
    assert.equal(h.api.last(), null);
    assert.equal(h.body.innerHTML, displayed);
    assert.equal(h.badges.at(-1).active, true);
    await h.complete(1, '新資料');
    assertCurrent(h, '新資料');
  }],
  ['離頁後的成功回應不得修改畫面、快取或推送', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.deactivate();
    const displayed = h.body.innerHTML;
    const badgeCount = h.badges.length;
    await h.complete(0, '離頁舊資料');
    assert.equal(h.api.last(), null);
    assert.equal(h.body.innerHTML, displayed);
    assert.equal(h.bridge.length, 0);
    assert.equal(h.badges.length, badgeCount);
    assert.equal(h.badges.at(-1).active, false);
    assert.equal(h.timers.size, 0);
  }],
  ['離頁後的失敗回應不得顯示錯誤或修改更新標示', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.deactivate();
    const displayed = h.body.innerHTML;
    const badgeCount = h.badges.length;
    await h.fail(0);
    assert.equal(h.api.last(), null);
    assert.equal(h.body.innerHTML, displayed);
    assert.equal(h.badges.length, badgeCount);
  }],
  ['離頁重入後的前代回應不得覆寫本代結果', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.deactivate();
    h.api.activate();
    await h.complete(1, '重入新資料');
    await h.complete(0, '前代舊資料');
    assertCurrent(h, '重入新資料');
    assert.equal(h.bridge.length, 1);
    assert.equal(h.timers.size, 1);
  }],
  ['目前請求失敗仍顯示錯誤，後續重試可正常更新', async () => {
    const h = createHarness();
    h.api.activate();
    await h.fail(0);
    assert.ok(h.body.innerHTML.includes('載入失敗：測試連線失敗'));
    assert.equal(h.badges.at(-1).active, false);
    h.api.refresh(true);
    await h.complete(1, '重試資料');
    assertCurrent(h, '重試資料');
  }],
];

(async () => {
  for (const [name, run] of cases) {
    await run();
    console.log('通過：' + name);
  }
  console.log(`市場廣度生命週期：${cases.length} 項行為驗證全部通過。`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

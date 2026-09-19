'use strict';

// 完整執行正式 Hub 模組，以受控 Promise 驗證因子頁回應的生命週期。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'ui', 'hub_v5.js'), 'utf8');

function createHarness() {
  const elements = new Map();
  function element() { return { innerHTML: '', textContent: '', querySelectorAll: () => [], appendChild() {} }; }
  for (const id of ['view-factors', 'mount-factors', 'hub-fac-body', 'hub-v5-css']) elements.set(id, element());
  const requests = [];
  const sandbox = {
    document: {
      getElementById: id => elements.get(id) || null, createElement: () => element(),
      head: { appendChild() {} },
    },
    fetch(url) {
      return new Promise((resolve, reject) => requests.push({
        url, reject, resolve(data) { resolve({ ok: true, json: async () => data }); },
      }));
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: 'src/ui/hub_v5.js' });
  return {
    api: sandbox.FactorsV5, requests, body: elements.get('hub-fac-body'),
    async complete(batch, label) {
      const offset = batch * 2;
      assert.equal(requests[offset].url, '/pulse');
      assert.equal(requests[offset + 1].url, '/pulse/history?kind=pulse&n=12');
      requests[offset].resolve({ statusText: label, totalScore: 65,
        positiveFactors: [{ name: label + '正面因素', score: 2, description: '正面說明' }],
        riskFactors: [{ name: label + '風險因素', score: -1, description: '風險說明' }],
        pendingFactors: [{ name: label + '未納入因素', description: '待資料' }],
        marketRows: [{ k: label + '體質支柱', v: '測試數值', score: 60 }] });
      requests[offset + 1].resolve({ rows: [{ date: label + '歷史', health: 65, risk: 35, total: 65, statusText: label }] });
      await new Promise(resolve => setImmediate(resolve));
    },
    async fail(batch) {
      requests[batch * 2].reject(new Error('測試連線失敗'));
      requests[batch * 2 + 1].reject(new Error('測試連線失敗'));
      await new Promise(resolve => setImmediate(resolve));
    },
  };
}

function assertContents(h, label) {
  for (const suffix of ['正面因素', '風險因素', '未納入因素', '體質支柱', '歷史']) {
    assert.ok(h.body.innerHTML.includes(label + suffix), '應保留完整內容：' + suffix);
  }
}

const cases = [
  ['正常完成時保留全部因子、支柱與歷史內容', async () => {
    const h = createHarness();
    h.api.activate();
    await h.complete(0, '正常資料');
    assertContents(h, '正常資料');
  }],
  ['同頁逆序回應不得覆寫較新的因子資料', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.activate();
    await h.complete(1, '新資料');
    const current = h.body.innerHTML;
    await h.complete(0, '舊資料');
    assertContents(h, '新資料');
    assert.equal(h.body.innerHTML, current);
  }],
  ['離開因子頁後晚到回應不得修改隱藏頁面', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.deactivate();
    const current = h.body.innerHTML;
    await h.complete(0, '離頁資料');
    assert.equal(h.body.innerHTML, current);
  }],
  ['離頁重入後保留新一代結果', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.deactivate();
    h.api.activate();
    await h.complete(1, '重入新資料');
    const current = h.body.innerHTML;
    await h.complete(0, '前代舊資料');
    assertContents(h, '重入新資料');
    assert.equal(h.body.innerHTML, current);
  }],
  ['舊請求失敗形成的空結果不得覆寫新資料', async () => {
    const h = createHarness();
    h.api.activate();
    h.api.deactivate();
    h.api.activate();
    await h.complete(1, '重入新資料');
    const current = h.body.innerHTML;
    await h.fail(0);
    assert.equal(h.body.innerHTML, current);
  }],
  ['目前請求失敗仍可呈現無資料，重新載入可恢復', async () => {
    const h = createHarness();
    h.api.activate();
    await h.fail(0);
    assert.ok(h.body.innerHTML.includes('支柱尚未就緒'));
    assert.ok(h.body.innerHTML.includes('尚無歷史'));
    h.api.activate();
    await h.complete(1, '重試資料');
    assertContents(h, '重試資料');
  }],
];

(async () => {
  for (const [name, run] of cases) {
    await run();
    console.log('通過：' + name);
  }
  console.log(`因子頁生命週期：${cases.length} 項行為驗證全部通過。`);
})().catch(error => { console.error(error); process.exitCode = 1; });

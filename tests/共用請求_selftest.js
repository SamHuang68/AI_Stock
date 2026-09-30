'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function main() {
  let calls = 0;
  let status = 200;
  const context = {
    window: {}, location: { origin: 'http://本機驗收' },
    AbortController, setTimeout, clearTimeout,
    fetch: async () => {
      calls++;
      await new Promise(resolve => setTimeout(resolve, 5));
      return new Response(JSON.stringify({ price: 22000 }), { status });
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/core/app_kernel_v5.js'), 'utf8'), context);
  const api = context.window.AppKernel.api;
  const results = await Promise.all([api.getJson('/txf'), api.getJson('/txf')]);
  assert.equal(calls, 1, '同步讀取只發出一次請求');
  assert.equal(results[0].price, 22000);
  assert.equal(results[1].price, 22000, '每個使用者可獨立讀取回應內容');
  const responses = await Promise.all([api.request('/txf'), api.request('/txf')]);
  assert.notEqual(responses[0], responses[1], '回應物件彼此獨立');
  assert.deepEqual(await responses[0].json(), await responses[1].json());
  assert.equal(calls, 2, '請求完成後可再次更新');
  status = 503;
  const failures = await Promise.allSettled([api.getJson('/txf'), api.getJson('/txf')]);
  assert.ok(failures.every(result => result.status === 'rejected' && result.reason.status === 503));
  assert.equal(calls, 3, '失敗的同步請求仍共用傳輸');
  status = 200;
  assert.equal((await api.getJson('/txf')).price, 22000, '失敗後可重試');
  assert.equal(calls, 4);
  console.log('共用請求驗收通過：獨立回應、單次傳輸、完成後更新及失敗重試。');
}

main().catch(error => { console.error(error); process.exitCode = 1; });

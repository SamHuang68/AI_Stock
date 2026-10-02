'use strict';
// 使用 Node vm 重現 decision_data_v5 的延遲 fetch 與快照世代檢查。
// 不依賴瀏覽器，僅驗證：相同 profile 共用 inflight、不同 profile 隔離、
// 逆序回應不覆蓋較新 revision、AbortSignal 取消後不發布、
// strict 模式帶回原錯誤、readonly 不會 POST /pulse/refresh、以及 pulse job 失敗傳遞。

var vm = require('vm');
var fs = require('fs');
var path = require('path');
var assert = require('assert');

var sourcePath = path.join(__dirname, '..', 'src', 'core', 'decision_data_v5.js');
var source = fs.readFileSync(sourcePath, 'utf8');

function makeResponse(payload, status) {
  status = status == null ? 200 : status;
  var body = payload == null ? '' : JSON.stringify(payload);
  return {
    ok: status >= 200 && status < 300,
    status: status,
    text: function () { return Promise.resolve(body); },
    json: function () { return Promise.resolve(payload); }
  };
}

function createSandbox(profile) {
  var pending = [];
  function fetchStub(url, init) {
    return new Promise(function (resolve, reject) {
      pending.push({ url: String(url), init: init || {}, resolve: resolve, reject: reject });
    });
  }
  var storage = Object.create(null);
  var sandbox = {
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    Promise: Promise,
    JSON: JSON,
    Date: Date,
    Math: Math,
    Object: Object,
    Array: Array,
    Error: Error,
    String: String,
    Number: Number,
    Boolean: Boolean,
    encodeURIComponent: encodeURIComponent,
    AbortController: AbortController,
    CustomEvent: function (type, init) { this.type = type; this.detail = (init || {}).detail; },
    fetch: fetchStub,
    localStorage: {
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(storage, k) ? storage[k] : null; },
      setItem: function (k, v) { storage[k] = String(v); },
      removeItem: function (k) { delete storage[k]; }
    },
    location: { origin: 'http://localhost' }
  };
  sandbox.window = {
    SERVER: 'http://localhost',
    dispatchEvent: function () { return true; }
  };
  if (profile) sandbox.window.ST_PRIVATE_WEB_PROFILE = profile;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  sandbox.__pending = pending;
  return sandbox;
}

function flush(times) {
  times = times || 20;
  var p = Promise.resolve();
  for (var i = 0; i < times; i++) p = p.then(function () {});
  return p;
}

function wait(ms) {
  return new Promise(function (r) { setTimeout(r, ms); });
}

async function testSameProfileSharesInflight() {
  var box = createSandbox();
  var dd = box.window.DecisionData;
  var p1 = dd.refresh({ riskProfile: 'A' });
  var p2 = dd.refresh({ riskProfile: 'A' });
  await flush();
  assert.strictEqual(box.__pending.length, 1, '相同 profile 應共用 inflight');
  assert.strictEqual(p1, p2, '返回的 Promise 應完全相同');
  box.__pending[0].resolve(makeResponse({ regime: { id: 'A' }, snapshotId: 'A', revision: 1 }));
  await Promise.all([p1, p2]);
}

async function testDifferentProfileIsolated() {
  var box = createSandbox();
  var dd = box.window.DecisionData;
  dd.refresh({ riskProfile: 'A' });
  dd.refresh({ riskProfile: 'B' });
  await flush();
  assert.strictEqual(box.__pending.length, 2, '不同 profile 的 POST 不應共用 inflight');
}

async function testReverseOrderDoesNotOverwrite() {
  var box = createSandbox();
  var dd = box.window.DecisionData;
  var p1 = dd.refresh({ riskProfile: 'A' });
  var p2 = dd.refresh({ riskProfile: 'B' });
  await flush();
  assert.strictEqual(box.__pending.length, 2);
  // 先回較新 revision=2
  box.__pending[1].resolve(makeResponse({ regime: { id: 'B' }, snapshotId: 'B', revision: 2 }));
  await flush();
  // 再回較舊 revision=1
  box.__pending[0].resolve(makeResponse({ regime: { id: 'A' }, snapshotId: 'A', revision: 1 }));
  await Promise.all([p1, p2]);
  await flush();
  var st = dd.get();
  assert.strictEqual(st.snapshotId, 'B', '較新 revision 不應被逆序回應覆蓋');
  assert.strictEqual(st.revision, 2);
  assert.strictEqual(st.summary && st.summary.snapshotId, 'B', 'summary 應與 context 同步配對');
}

async function testAbortSignalPreventsPublish() {
  var box = createSandbox();
  var dd = box.window.DecisionData;
  var controller = new AbortController();
  var p = dd.refresh({ riskProfile: 'X', signal: controller.signal });
  await flush();
  assert.strictEqual(box.__pending.length, 1);
  controller.abort();
  box.__pending[0].resolve(makeResponse({ regime: { id: 'X' }, snapshotId: 'X', revision: 9 }));
  await p;
  await flush();
  var st = dd.get();
  assert.strictEqual(st.context, null, '取消之後即使 fetch 回傳也不得發布');
  assert.strictEqual(st.snapshotId, null);
}

async function testParentRevisionAndPulseIdentityStayTogether() {
  var dd = createSandbox().window.DecisionData;
  dd.publish({regime: {id: 'personal'}, viewScope: 'personal', parentSnapshotId: 'market-8',
    parentRevision: 8, portfolioInputKey: 'simulation:2330'});
  dd.fromPulse({decisionSummary: {regime: {id: 'market'}, snapshotId: 'market-8', revision: 8}});
  assert.strictEqual(dd.get().context.regime.id, 'personal', '同版 Pulse 不清除個人檢視');
  dd.publish({regime: {id: 'old'}, viewScope: 'market', snapshotId: 'market-7', revision: 7});
  assert.strictEqual(dd.get().context.regime.id, 'personal', '跨 scope 仍不可回退市場水位');
  dd.fromPulse({decisionSummary: {regime: {id: 'new'}, snapshotId: 'market-9', revision: 9}});
  assert.strictEqual(dd.get().context, null, '新 Pulse 不得與舊完整 context 配對');
  assert.strictEqual(dd.get().snapshotId, 'market-9');
  assert.strictEqual(dd.get().portfolioInputKey, null, '新 Pulse 不得沿用舊個人輸入身份');
  assert.strictEqual(dd.get().parentSnapshotId, null);
  assert.strictEqual(dd.get().parentRevision, 0);
  dd.publish({regime: {id: 'late-personal'}, parentRevision: 8, portfolioInputKey: 'actual:2330'});
  assert.strictEqual(dd.get().summary.snapshotId, 'market-9', '晚到個人檢視不能覆蓋已觀測新 Pulse');
  dd.fromPulse({decisionSummary: {regime: {id: 'old-pulse'}, snapshotId: 'market-8', revision: 8}});
  assert.strictEqual(dd.get().summary.snapshotId, 'market-9');
}

async function testStrictAndAbortOwnedRequestsNeverShare() {
  var box = createSandbox(), dd = box.window.DecisionData;
  var controller = new AbortController();
  var p1 = dd.refresh({riskProfile: 'A'});
  var p2 = dd.refresh({riskProfile: 'A', strict: true});
  var p3 = dd.refresh({riskProfile: 'A', signal: controller.signal});
  await flush();
  assert.strictEqual(box.__pending.length, 3, 'strict 與取消所有權不得共用非 strict 要求');
  controller.abort();
  box.__pending.forEach(function (item) { item.resolve(makeResponse({regime: {id: 'A'}, revision: 1})); });
  await Promise.all([p1, p2, p3]);
}

async function testStrictPropagatesOriginalError() {
  var box = createSandbox();
  var dd = box.window.DecisionData;
  var p = dd.refresh({ strict: true, riskProfile: 'S' });
  await flush();
  assert.strictEqual(box.__pending.length, 1);
  box.__pending[0].resolve(makeResponse(null, 503));
  var caught = null;
  try { await p; } catch (e) { caught = e; }
  assert.ok(caught, 'strict 失敗必須丟出錯誤');
  assert.strictEqual(caught.status, 503, '必須保留原始 HTTP 狀態');
  assert.ok(/503/.test(caught.message), '錯誤訊息應包含原始狀態');
}

async function testReadonlyDoesNotPostPulse() {
  var box = createSandbox({ role: 'viewer' });
  var dd = box.window.DecisionData;
  assert.strictEqual(dd.canUpdateMarket(), false, 'viewer 不得更新市場');
  var p = dd.refreshPulse({ update: true });
  await flush();
  assert.strictEqual(box.__pending.length, 1, 'readonly 僅發出一次 GET');
  var call = box.__pending[0];
  assert.ok(/\/pulse$/.test(call.url), 'readonly 僅允許 GET /pulse');
  assert.ok(!call.init.method || call.init.method === 'GET', 'readonly 不得使用 POST');
  call.resolve(makeResponse({ ok: true }));
  var result = await p;
  assert.strictEqual(result.requestedUpdate, false, 'readonly 不會請求更新');
}

async function testPulseJobFailurePropagates() {
  var box = createSandbox({ role: 'owner' });
  var dd = box.window.DecisionData;
  var p = dd.refreshPulse({ update: true });
  await flush();
  assert.strictEqual(box.__pending.length, 1);
  assert.strictEqual(box.__pending[0].init.method, 'POST', 'owner 才會 POST /pulse/refresh');
  assert.ok(/\/pulse\/refresh$/.test(box.__pending[0].url));
  box.__pending[0].resolve(makeResponse({ job: { jobId: 'j-1', status: 'running' } }));
  // 等過 1 秒以通過 pause()
  await wait(1100);
  await flush();
  assert.strictEqual(box.__pending.length, 2, '應輪詢 /pulse/update-status');
  assert.ok(/\/pulse\/update-status\?jobId=j-1$/.test(box.__pending[1].url));
  box.__pending[1].resolve(makeResponse({ job: { jobId: 'j-1', status: 'failed', error: '來源失效' } }));
  await flush();
  assert.strictEqual(box.__pending.length, 3, '狀態完成後應讀取最新 /pulse');
  box.__pending[2].resolve(makeResponse({ ok: true }));
  var result = await p;
  assert.strictEqual(result.job.status, 'failed');
  assert.strictEqual(result.error, '來源失效', 'job 失敗需保留原錯誤訊息');
}

(async function run() {
  var cases = [
    ['同 profile 共用 inflight', testSameProfileSharesInflight],
    ['不同 profile 隔離 inflight', testDifferentProfileIsolated],
    ['逆序回應不覆蓋較新 revision', testReverseOrderDoesNotOverwrite],
    ['AbortSignal 取消後不發布', testAbortSignalPreventsPublish],
    ['跨範圍修訂水位與 Pulse 身份一致', testParentRevisionAndPulseIdentityStayTogether],
    ['strict 與取消要求保留各自生命週期', testStrictAndAbortOwnedRequestsNeverShare],
    ['strict 傳遞原始錯誤', testStrictPropagatesOriginalError],
    ['readonly 不 POST pulse', testReadonlyDoesNotPostPulse],
    ['pulse job 失敗傳遞', testPulseJobFailurePropagates]
  ];
  var failed = 0;
  for (var i = 0; i < cases.length; i++) {
    var name = cases[i][0];
    try {
      await cases[i][1]();
      console.log('✓ ' + name);
    } catch (error) {
      failed++;
      console.error('✗ ' + name);
      console.error(error && error.stack || error);
    }
  }
  if (failed) { console.error('共 ' + failed + ' 個案例失敗'); process.exit(1); }
  console.log('全部 ' + cases.length + ' 個案例通過');
})();

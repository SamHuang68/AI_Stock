/* 正式共用 store 的去重、保留資料、權限與離頁行為。 */
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(require('path').join(__dirname, '../src/core/更新工作_v5.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
async function run() {
  const calls = [], handlers = {};
  const document = { hidden: false, addEventListener: (name, fn) => { handlers[name] = fn; } };
  const context = { window: {}, document, location: { origin: 'http://offline.test' }, AbortController,
    Set, JSON, Date, Promise, setTimeout, clearTimeout,
    fetch: (url, options) => new Promise((resolve, reject) => {
      calls.push({ url, options, resolve, reject });
      options.signal.addEventListener('abort', () => { const error = new Error('已取消'); error.name = 'AbortError'; reject(error); }, { once: true });
    }) };
  vm.createContext(context); vm.runInContext(source, context);
  const store = context.window.UpdateJobs;
  const reply = (call, value, status = 200) => call.resolve({ ok: status < 400, status, json: async () => value });
  const good = { ok: true, jobs: [{ jobId: 'p-first', status: 'running' }], capabilities: { canSubmit: true, canRetry: true }, workers: {} };
  const off1 = store.subscribe(() => {}), off2 = store.subscribe(() => {});
  const first = store.refresh(), second = store.refresh();
  assert.strictEqual(first, second); assert.strictEqual(calls.length, 1);
  reply(calls[0], good); await first; await tick();
  assert.strictEqual(store.snapshot().jobs.length, 1); assert.strictEqual(store.diagnostics().timers, 1);
  const read = store.refresh(); reply(calls[1], { error: '合成來源失敗' }, 503); await read;
  assert.strictEqual(store.snapshot().jobs.length, 1); assert.match(store.snapshot().error, /合成/);
  const submit = store.submit('options'); await tick();
  await assert.rejects(store.submit('research'), /上一個/);
  assert.strictEqual(JSON.parse(calls[2].options.body).type, 'options');
  reply(calls[2], { ok: true, job: { jobId: 'r-next' } }, 202); await tick();
  reply(calls[3], good); await submit;
  assert.strictEqual(store.snapshot().writing, false);
  const hidden = store.refresh(); document.hidden = true; handlers.visibilitychange();
  assert.strictEqual(calls[4].options.signal.aborted, true);
  reply(calls[4], { ...good, jobs: [] }); await hidden;
  assert.strictEqual(store.snapshot().jobs.length, 1); assert.strictEqual(store.diagnostics().timers, 0);
  document.hidden = false; handlers.visibilitychange(); await tick();
  reply(calls[5], { ...good, capabilities: { canSubmit: false, canRetry: false } }); await tick();
  const count = calls.length; await assert.rejects(store.submit('pulse'), /僅能讀取/); assert.strictEqual(calls.length, count);
  off1(); assert.strictEqual(store.diagnostics().subscribers, 1);
  off2(); assert.strictEqual(store.diagnostics().subscribers, 0); assert.strictEqual(store.diagnostics().timers, 0);
  for (let i = 0; i < 100; i++) { const off = store.subscribe(() => {}); off(); }
  assert.strictEqual(store.diagnostics().subscribers, 0); assert.strictEqual(store.diagnostics().timers, 0);
  await tick();
  async function feed(jobs) {
    const pending = store.refresh();
    reply(calls[calls.length - 1], { ...good, jobs });
    await pending; await tick();
  }
  await feed([{ jobId: 'r-source', status: 'running' }]);
  let resolved = false;
  const progress = [];
  const follow = store.wait('r-source', { timeoutMs: 5000, onProgress: job => progress.push(job.jobId) }).then(job => { resolved = true; return job; });
  await feed([{ jobId: 'r-source', status: 'succeeded', result: { marketJobId: 'p-publish' } }, { jobId: 'p-publish', status: 'running' }]);
  assert.strictEqual(resolved, false);
  await feed([{ jobId: 'r-source', status: 'succeeded', result: { marketJobId: 'p-publish' } }, { jobId: 'p-publish', status: 'succeeded', result: { snapshotId: 'new' } }]);
  assert.strictEqual((await follow).jobId, 'p-publish'); assert(progress.includes('p-publish'));
  assert.strictEqual(store.diagnostics().subscribers, 0);
  await store.wait('p-publish'); assert.strictEqual(store.diagnostics().subscribers, 0);
  const cancel = new AbortController();
  const canceled = store.wait('r-pending', { signal: cancel.signal });
  cancel.abort(); await assert.rejects(canceled, error => error.name === 'AbortError');
  assert.strictEqual(store.diagnostics().subscribers, 0);
  await assert.rejects(store.wait('r-pending', { timeoutMs: 1 }), error => error.name === 'TimeoutError');
  assert.strictEqual(store.diagnostics().subscribers, 0); assert.strictEqual(store.diagnostics().timers, 0);
  await feed([{ jobId: 'r-failed', status: 'failed', error: '合成工作失敗' }]);
  await assert.rejects(store.wait('r-failed'), /合成工作失敗/);
  assert.strictEqual(store.diagnostics().subscribers, 0);
  console.log('更新工作共用狀態：去重、失敗保留、提交鎖、權限、隱藏及100次離頁檢查通過');
}
run().catch(error => { console.error(error); process.exitCode = 1; });

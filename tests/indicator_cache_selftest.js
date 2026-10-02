/* 用原始 worker 獨立運算，驗證快取不改公式、輸入與版本不混用。 */
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const html = fs.readFileSync(require('node:path').join(__dirname, '../stock_terminal.html'), 'utf8');
const definition = html.match(/const WORKER_SRC = `[\s\S]*?`;/)[0];
const sourceContext = {}; vm.runInNewContext(definition + '; globalThis.source=WORKER_SRC;', sourceContext);
const source = sourceContext.source;
const code = fs.readFileSync(require('node:path').join(__dirname, '../src/core/indicator_cache_v3.js'), 'utf8');
let calls = 0;
function compute(candles) {
  let result; const worker = {self:{postMessage:r=>{result=r;}}};
  vm.runInNewContext(source, worker); worker.self.onmessage({data:{candles}});
  return JSON.parse(JSON.stringify(result));
}
const storage = { getItem(k){return this[k] || null;},setItem(k,v){this[k]=v;},removeItem(k){delete this[k];} };
function harness(version=source) {
  const context = {window:{runWorker:async candles=>{calls++;return compute(candles);}},crypto:webcrypto,TextEncoder,localStorage:storage,WORKER_SRC:version};
  vm.runInNewContext(code, context);return context.window;
}
(async()=>{
  const candles=Array.from({length:90},(_,i)=>({time:1700000000+i*86400,open:100+i,high:102+i,low:99+i,close:101+i,volume:1000+i}));
  const expected=compute(candles), app=harness();
  const a=await app.runWorker(candles);assert.deepEqual(a,expected);a.rsi14=-999;
  assert.deepEqual(JSON.parse(JSON.stringify(await app.runWorker(candles))),expected);assert.equal(calls,1);
  const changed=structuredClone(candles);changed[10].close+=0.5;
  await app.runWorker(changed);assert.equal(calls,2);
  const next=harness(source+'\n// 公式版本更新');await next.runWorker(candles);assert.equal(calls,3);
  const restored=harness();assert.deepEqual(JSON.parse(JSON.stringify(await restored.runWorker(candles))),expected);assert.equal(calls,3);
  const fresh=structuredClone(candles);fresh[0].volume++;
  await Promise.all([app.runWorker(fresh),app.runWorker(fresh)]);assert.equal(calls,4);
  assert.equal(app.IndicatorCache.stats().cacheOnly,true);
  console.log('指標快取：原 worker 數值、內容／版本隔離、持久重用與同時呼叫合併通過');
})().catch(e=>{console.error(e);process.exitCode=1;});

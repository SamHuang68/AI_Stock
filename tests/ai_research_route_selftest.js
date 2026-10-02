'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../src/ai/ai_runtime_client.js'), 'utf8');
const expected = { mode: 'fast', host: 'fixture-host', provider: 'LM Studio', model: 'fixture-model',
  dataBoundary: 'local-only', destinationId: 'st-ai-direct-v1:fixture' };
function harness(response) {
  const calls = [];
  const ctx = { AbortController, TextDecoder, setTimeout, clearTimeout, setInterval, clearInterval,
    fetch: async (url, options) => { calls.push({ url, options }); return response; } };
  ctx.window = ctx;
  vm.runInNewContext(code, ctx);
  return { calls, client: ctx.STAI };
}
function reply(route = expected, receipt = 'actual-server-receipt', status = 200) {
  const headers = { 'Content-Type': 'text/event-stream', 'X-ST-AI-Request-ID': receipt,
    'X-ST-AI-Mode': route.mode, 'X-ST-AI-Host': route.host, 'X-ST-AI-Provider': route.provider,
    'X-ST-AI-Model': route.model, 'X-ST-AI-Data-Boundary': route.dataBoundary, 'X-ST-AI-Destination-ID': route.destinationId };
  return new Response('data: {"type":"delta","text":"研究正文"}\n\ndata: {"type":"done"}\n\n', { status, headers });
}
(async function () {
  const valid = harness(reply());
  const original = { ...expected };
  const task = valid.client.request({ prompt: '研究', context: '快照', expectedRoute: original, requestId: 'client-correlation' });
  original.model = 'changed-after-start';
  const result = await task.promise;
  assert.deepEqual(JSON.parse(valid.calls[0].options.body), { prompt: '研究', context: '快照', expectedRoute: expected });
  assert.equal(result.text, '研究正文');
  assert.equal(result.meta.serverRequestId, 'actual-server-receipt');
  assert.equal(result.meta.requestId, 'actual-server-receipt');
  assert.equal(result.meta.destinationId, expected.destinationId);
  for (const key of Object.keys(expected)) {
    const h = harness(reply({ ...expected, [key]: 'other-route' }));
    let output = '';
    await assert.rejects(h.client.request({ prompt: '研究', expectedRoute: expected, onText: text => { output = text; } }).promise, /實際路由.*不符/);
    assert.equal(output, '', '不符路由的正文不得出現在研究輸出');
  }
  const missingReceipt = harness(reply(expected, ''));
  await assert.rejects(missingReceipt.client.request({ prompt: '研究', expectedRoute: expected, requestId: 'client-only' }).promise,
    error => /伺服器收據不符/.test(error.message) && error.serverRequestId === '');
  const ordinary = harness(reply(expected, ''));
  const ordinaryResult = await ordinary.client.request({ prompt: '一般副駕', requestId: 'client-only' }).promise;
  assert.equal(ordinaryResult.meta.serverRequestId, '', '不能拿前端 trace id 假冒伺服器回傳收據');
  assert.equal(ordinaryResult.meta.requestId, 'client-only', '舊顯示用 correlation id 保留相容');
  assert.equal(Object.hasOwn(JSON.parse(ordinary.calls[0].options.body), 'expectedRoute'), false);
  for (const route of [null, {}, { ...expected, mode: 'deep' }, { ...expected, unexpected: 'field' }]) {
    const h = harness(reply());
    await assert.rejects(h.client.request({ prompt: '研究', expectedRoute: route }).promise, /契約不完整/);
    assert.equal(h.calls.length, 0, '無效 expectedRoute 在瀏覽器端即停止');
  }
  const denied = harness(new Response('{"error":"研究 AI 路由已改變"}', { status: 409, headers: { 'Content-Type': 'application/json' } }));
  await assert.rejects(denied.client.request({ prompt: '研究', expectedRoute: expected }).promise,
    error => error.status === 409 && error.serverRequestId === '' && /路由已改變/.test(error.detail));
  console.log('研究 AI 路由驗證通過：預期路由、實際收據、不符即停、一般副駕相容；沒有真實 AI 呼叫。');
})().catch(error => { console.error(error); process.exitCode = 1; });

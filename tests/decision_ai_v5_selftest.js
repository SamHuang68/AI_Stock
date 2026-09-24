'use strict';
// 正式 Decision UI 接既有研究任務；網路只以受控回應替代，不呼叫模型。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const { harness, contextPayload } = require('./投組決策同步_selftest.js');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/ui/decision_v5.js'), 'utf8');
const snap = (id, rows = 30) => ({ snapshotId: id, persistence: 'committed', digest: 'a'.repeat(64),
  revision: id === 'public-old' ? 1 : 2, asOf: new Date(id === 'public-old' ? 900000 : 999000).toISOString(), regime: { id: 'NEUTRAL' },
  evidence: Array.from({ length: rows }, (_, i) => ({ id: 'metric.' + i, evidenceId: id + ':' + i,
    digest: 'b'.repeat(64), value: i, metric: '公開指標', source: '公開來源', asOf: '2026-09-23T01:00:00Z' })) });
async function prepared(role = 'owner', customize = null) {
  const h = harness(role); h.mounts = []; h.stops = 0;
  h.c.ResearchTasks = { mount(node, read) { h.mounts.push({ node, read }); }, stop() { h.stops++; } };
  h.c.DecisionV5.refresh(true);
  const request = h.requests.find(x => x.path === '/decision/context');
  const context = contextPayload('current'); context.privateNote = '私人情境不可送';
  context.portfolioOverlay = { kind: 'simulation', holdings: [{ sym: '2330', weight: 987654 }] };
  context.riskProfile = { baseGrossExposure: 876543, privateNote: '私人風險不可送' };
  if (customize) customize(context);
  await h.complete(request, context);
  return h;
}
(async () => {
  assert(!source.includes("fetch(SRV + '/ai/local'"), 'Decision 不得保留模型直送旁路');
  assert(!source.includes('(lastContext.evidence || []).slice(0, 12)'), '公開證據不得截為前十二筆');
  const h = await prepared();
  h.nodes.get('dc-ai-btn').onclick();
  h.nodes.get('dc-ai-btn').onclick();
  assert.equal(h.requests.filter(x => x.path.startsWith('/research/workflow')).length, 1, '讀取中重按不重複');
  assert(h.nodes.get('dc-ai-btn').disabled);
  const request = h.pending('/research/workflow?current=dc-current', 'GET');
  assert.equal(request.options.body, undefined);
  const payload = { current: snap('dc-current'), previous: snap('public-old') };
  await h.complete(request, payload);
  assert.equal(h.mounts.length, 1);
  const input = h.mounts[0].read();
  assert.equal(input.data.current.evidence.length, 30);
  assert.equal(input.data.previous.evidence.length, 30);
  assert.equal(input.record, null); assert.equal(input.subject, null);
  assert(!JSON.stringify(input).includes('私人情境不可送'));
  h.c.crypto = webcrypto; h.c.TextEncoder = TextEncoder;
  vm.runInContext(fs.readFileSync(path.join(root, 'src/core/研究任務.js'), 'utf8'), h.c);
  const packet = await h.c.ResearchTaskCore.freeze(input, 'changes');
  assert(packet.evidence.some(row => row.evidenceId.includes('29')), '末筆公開證據進入正式S5完整包');
  assert(!JSON.stringify(packet).includes('987654'));
  assert.match(h.nodes.get('dc-research-status').textContent, /目的地、模型及費用/);
  assert(h.requests.every(x => !x.path.startsWith('/ai/')), '開啟只讀取快照，不探測路由或推理');
  console.log('通過：正式入口接S5、完整證據凍結、私人模擬隔離、未確認不呼叫模型');
  const route = await h.c.ResearchTaskCore.route({ available: true, host: '離線替身', provider: '測試提供者',
    model: '測試模型', dataBoundary: 'local-only', destination: 'http://127.0.0.1:1234/v1',
    destinationId: '離線目的地摘要', destinationVerified: true }, 'fast');
  const calls = [], events = [];
  const runner = new h.c.ResearchTaskCore.Runner(h.c.localStorage, { request(options) {
    calls.push(options);
    return { cancel() {}, promise: Promise.resolve({ text: JSON.stringify({ claims: [{ evidenceId: '未知引用', quote: '捏造引文',
      phase: 'current', interpretation: '研究推論', limitations: ['資料不足'], nextChecks: ['人工查證'] }],
      limitations: ['資料不足'], nextChecks: ['人工查證'] }),
      meta: { host: route.host, provider: route.provider, model: route.model, dataBoundary: route.dataBoundary,
        destinationId: route.destinationId, requestId: '受控請求', serverRequestId: '受控請求' } }) };
  } });
  await assert.rejects(runner.run(packet, route, null), /尚未確認/);
  assert.equal(calls.length, 0);
  const receipt = await runner.run(packet, route, { packageHash: packet.hash, routeHash: route.hash }, state => events.push(state.status));
  assert.equal(calls.length, 1); assert.equal(receipt.result.verified, false); assert.equal(receipt.result.claims.length, 0);
  assert(receipt.result.issues.some(item => item.includes('引用不存在'))); assert(events.includes('quarantined')); assert(!events.includes('verified'));
  assert(!JSON.stringify(calls[0].body).includes('987654')); assert(!JSON.stringify(calls[0].body).includes('876543'));
  assert(!/私人情境不可送|私人風險不可送/.test(JSON.stringify(calls[0].body)));
  assert(JSON.parse(calls[0].body.context).evidence.some(row => row.evidenceId.includes('29')));
  console.log('通過：決策來源的真S5 Runner 逐次同意、未知引用隔離且完整公開資料不混私人風險');
  h.seed('newer-market');
  assert.equal(h.mounts.length, 1, '市場重新繪製不重建既有凍結面板');
  h.nodes.get('dc-research-close').onclick();
  assert.equal(h.stops, 1); assert(h.nodes.get('dc-research-card').hidden);
  console.log('通過：市場更新保留獨立研究面板，關閉沿既有S5停止接收');

  const departed = await prepared();
  departed.nodes.get('dc-ai-btn').onclick();
  const late = departed.pending('/research/workflow?current=dc-current'); late.ignoreAbort = true;
  departed.leave(); await departed.complete(late, payload);
  assert.equal(departed.mounts.length, 0); assert(late.options.signal.aborted);
  console.log('通過：離頁後晚到公開快照不重新掛載模型任務');

  const failed = await prepared(); failed.nodes.get('dc-ai-btn').onclick();
  await failed.complete(failed.pending('/research/workflow?current=dc-current'), {}, 503);
  assert.match(failed.nodes.get('dc-research-status').textContent, /503/);
  assert.equal(failed.mounts.length, 0); assert(!failed.nodes.get('dc-ai-btn').disabled);
  failed.nodes.get('dc-ai-btn').onclick();
  await failed.advance(15000);
  assert.match(failed.nodes.get('dc-research-status').textContent, /逾時/);
  assert(!failed.nodes.get('dc-ai-btn').disabled);
  console.log('通過：讀取失敗及逾時明示、可重試且不自動推理');

  const wrong = await prepared(); wrong.nodes.get('dc-ai-btn').onclick();
  await wrong.complete(wrong.pending('/research/workflow?current=dc-current'), { current: snap('另一個已提交快照') });
  assert.equal(wrong.mounts.length, 0);
  assert.match(wrong.nodes.get('dc-research-status').textContent, /指定決策快照不符/);
  assert.equal(wrong.requests.filter(x => x.path.startsWith('/research/workflow')).length, 1, '不得暗中改讀別份快照');
  console.log('通過：指定快照回應歸屬不符時拒絕凍結與暗中替代');

  for (const localId of [null, '不可當公開版本的本機識別']) {
    const personal = await prepared('owner', context => {
      delete context.snapshotId;
      if (localId) context.snapshotId = localId;
      context.parentSnapshotId = '公開父快照'; context.persistence = 'ephemeral'; context.viewScope = 'personal';
    });
    personal.nodes.get('dc-ai-btn').onclick();
    const read = personal.pending('/research/workflow?current=' + encodeURIComponent('公開父快照'));
    await personal.complete(read, { current: snap('公開父快照'), previous: snap('public-old') });
    assert.equal(personal.mounts.length, 1);
    assert.equal(personal.mounts[0].read().data.current.snapshotId, '公開父快照');
    assert(!JSON.stringify(personal.mounts[0].read()).includes('987654'));
    assert(!JSON.stringify(personal.mounts[0].read()).includes('876543'));
    assert(personal.requests.filter(x => x.path.startsWith('/research/workflow')).every(x => x.path.includes('current=')), '不得默默改讀最新版本');
  }
  console.log('通過：真私人回應形狀只沿parentSnapshotId取得原公開基準，不送overlay或風險數值');

  const reader = await prepared('reader');
  assert(reader.nodes.get('dc-ai-btn').disabled);
  reader.nodes.get('dc-ai-btn').onclick();
  assert(reader.requests.every(x => !x.path.startsWith('/research/workflow') && !x.path.startsWith('/ai/')));
  console.log('通過：Reader 不啟動模型研究或讀取私人模擬');
  console.log('決策研究入口：8 組完整接線驗證通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

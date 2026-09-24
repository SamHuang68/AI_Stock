'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const root = path.resolve(__dirname, '..');
function harness(role = 'owner', broken = false, destinationMismatch = false, missingRequestId = false) {
  const nodes = new Map(), saved = new Map(), requests = [], downloads = [], copied = [];
  function element(id = '') {
    const item = { id, value: '', checked: false, disabled: false, hidden: false, textContent: '',
      querySelector: selector => nodes.get(selector.slice(1)) || null,
      appendChild() {}, click() {}, remove() {} };
    Object.defineProperty(item, 'innerHTML', { get() { return this.html || ''; }, set(value) {
      this.html = String(value);
      for (const match of this.html.matchAll(/<\w+\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
        const child = element(match[1]); child.disabled = /\bdisabled/.test(match[0]);
        if (child.id === 'rt-type') child.value = 'changes'; if (child.id === 'rt-mode') child.value = 'fast';
      }
    } });
    if (id) nodes.set(id, item); return item;
  }
  const route = { available: true, host: '本機測試', provider: '測試提供者', model: '測試模型', dataBoundary: 'local-only',
    destination: 'http://127.0.0.1:1234/v1/chat/completions', destinationId: 'offline-destination-id', destinationVerified: true };
  const current = { snapshotId: 'dc-now', revision: 2, asOf: new Date().toISOString(), persistence: 'committed', digest: 'a'.repeat(64),
    evidence: [{ evidenceId: 'dc-now:metric', id: 'metric', digest: 'b'.repeat(64), value: 10, source: '<script>敵意來源</script>' }] };
  const previous = JSON.parse(JSON.stringify(current)); previous.snapshotId = 'dc-before'; previous.revision = 1;
  previous.evidence[0].evidenceId = 'dc-before:metric';
  const context = { console, Date, Math, Promise, Map, Set, Uint8Array, TextEncoder, TextDecoder, AbortController, Blob,
    setTimeout, clearTimeout, setInterval, clearInterval, crypto: webcrypto, ST_PRIVATE_WEB_PROFILE: { role },
    navigator: { clipboard: { writeText: async text => copied.push(text) } },
    URL: { createObjectURL(blob) { downloads.push(blob); return 'blob:研究驗證'; }, revokeObjectURL() {} },
    localStorage: { get length() { return saved.size; }, key: i => [...saved.keys()][i], getItem: key => saved.has(key) ? saved.get(key) : null,
      setItem: (key, value) => saved.set(key, value) },
    document: { createElement: () => element() },
    async fetch(url, options = {}) {
      requests.push({ url, options });
      if (url === '/ai/local/status') return { ok: true, json: async () => ({ modes: { fast: route, deep: Object.assign({}, route, { dataBoundary: 'external' }) } }) };
      const body = JSON.parse(options.body), packet = JSON.parse(body.context), evidence = packet.evidence[0];
      const report = JSON.stringify({ claims: [{ evidenceId: evidence.evidenceId, phase: evidence.phase, quote: evidence.quote,
        interpretation: '研究推論：資料 10 尚不能確認方向', limitations: ['來源時點有限'], nextChecks: ['確認後續資料'] }],
        limitations: ['未做因果推論'], nextChecks: ['人工查證'] });
      const text = 'data: ' + JSON.stringify({ type: 'delta', text: report }) + '\n\n' +
        (broken ? '' : 'data: {"type":"done"}\n\n');
      const headers = { 'Content-Type': 'text/event-stream',
        'X-ST-AI-Host': route.host, 'X-ST-AI-Provider': route.provider, 'X-ST-AI-Model': route.model,
        'X-ST-AI-Data-Boundary': route.dataBoundary, 'X-ST-AI-Destination-ID': destinationMismatch ? 'changed-destination' : route.destinationId };
      if (!missingRequestId) headers['X-ST-AI-Request-ID'] = 'ui-request';
      return new Response(text, { headers });
    } };
  // Node 的 Headers 只接受 Latin-1；測試路由使用 ASCII，畫面標籤仍由正式繁中元件產生。
  route.host = 'test-host'; route.provider = 'test-provider'; route.model = 'test-model';
  context.window = context; vm.createContext(context);
  for (const file of ['src/ai/ai_runtime_client.js', 'src/core/研究任務.js', 'src/ui/研究任務面板.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, { filename: file });
  }
  const container = element('test-mount');
  context.ResearchTasks.mount(container, () => ({ data: { current, previous }, record: { note: '私人內容不得外送' } }));
  return { context, nodes, requests, saved, container, copied, downloads, route, get: id => nodes.get(id) };
}
(async () => {
  const h = harness(); assert.equal(h.requests.length, 0, '掛載不讀路由或呼叫模型');
  await h.get('rt-freeze').onclick(); assert.equal(h.requests.length, 0, '凍結完全離線');
  assert(h.get('rt-package').innerHTML.includes('&lt;script&gt;')); assert(!h.get('rt-package').innerHTML.includes('<script>'));
  await h.get('rt-copy').onclick(); assert.equal(JSON.parse(h.copied[0]).evidence.length, 2);
  assert(!h.copied[0].includes('私人內容不得外送'));
  assert.equal(h.get('rt-run').disabled, true);
  await h.get('rt-route-read').onclick(); assert.equal(h.requests.length, 1); assert(h.requests[0].url.endsWith('/ai/local/status'));
  assert(h.get('rt-route').innerHTML.includes('test-model')); assert(h.get('rt-route').innerHTML.includes('費用尚未確認'));
  assert(h.get('rt-route').innerHTML.includes('http://127.0.0.1:1234/v1/chat/completions'));
  await h.get('rt-run').onclick(); assert.equal(h.requests.length, 1, '未勾同意仍不可模型呼叫');
  h.get('rt-consent').checked = true; h.get('rt-consent').onchange(); await h.get('rt-run').onclick();
  assert.equal(h.requests.length, 2); assert.equal(h.requests[1].url, '/ai/local');
  const body = JSON.parse(h.requests[1].options.body); assert.equal(body.expectedRoute.model, 'test-model');
  assert.equal(body.expectedRoute.destinationId, 'offline-destination-id');
  assert(!body.context.includes('私人內容不得外送'));
  assert(h.get('rt-result').innerHTML.includes('引文核對通過')); assert(h.get('rt-result').innerHTML.includes('研究推論'));
  assert(h.get('rt-result').innerHTML.includes('ui-request')); assert(!h.get('rt-result').innerHTML.includes('<script>'));
  await h.get('rt-history-read').onclick(); assert(h.get('rt-history').innerHTML.includes('verified'));
  h.context.ResearchTasks.stop();
  console.log('通過：完整 UI 離線凍結、完整複製、路由揭露、逐次同意、STAI expectedRoute 與安全呈現');

  const broken = harness('owner', true); await broken.get('rt-freeze').onclick(); await broken.get('rt-route-read').onclick();
  broken.get('rt-consent').checked = true; await broken.get('rt-run').onclick();
  assert(broken.get('rt-status').textContent.includes('未收到完成確認'));
  assert(broken.get('rt-result').innerHTML.includes('本次不列入研究摘要'));
  assert(!broken.get('rt-result').innerHTML.includes('引文核對通過'));
  await broken.get('rt-history-read').onclick(); assert(broken.get('rt-history').innerHTML.includes('failed'));
  console.log('通過：正式 STAI 串流缺少完成事件時只保留隔離原文與失敗紀錄');

  const reader = harness('reader'); await reader.get('rt-freeze').onclick();
  assert.equal(reader.get('rt-route-read').disabled, true);
  await reader.get('rt-route-read').onclick(); reader.get('rt-consent').checked = true; await reader.get('rt-run').onclick();
  assert.equal(reader.requests.length, 0); assert(reader.container.innerHTML.includes('Reader'));
  console.log('通過：Reader 只能離線整理，直接觸發事件也不呼叫路由或模型');

  const unverified = harness(); unverified.route.destinationVerified = false;
  unverified.route.reason = '實際端點無法核對';
  await unverified.get('rt-freeze').onclick(); await unverified.get('rt-route-read').onclick();
  assert(unverified.get('rt-status').textContent.includes('實際端點無法核對'));
  unverified.get('rt-consent').checked = true; await unverified.get('rt-run').onclick();
  assert.equal(unverified.requests.length, 1, '未知目的地只有狀態讀取，不送模型');
  const changed = harness('owner', false, true);
  await changed.get('rt-freeze').onclick(); await changed.get('rt-route-read').onclick();
  changed.get('rt-consent').checked = true; await changed.get('rt-run').onclick();
  assert(changed.get('rt-result').innerHTML.includes('回應不可驗證'));
  assert(changed.get('rt-result').innerHTML.includes('destinationId'));
  assert(!changed.get('rt-result').innerHTML.includes('引文核對通過；'));
  console.log('通過：未知實際目的地不送模型，同名模型回應目的地改變時隔離');

  const missingId = harness('owner', false, false, true);
  await missingId.get('rt-freeze').onclick(); await missingId.get('rt-route-read').onclick();
  missingId.get('rt-consent').checked = true; await missingId.get('rt-run').onclick();
  const missingArchive = await new missingId.context.ResearchTaskCore.Store(missingId.context.localStorage).all();
  const quarantined = missingArchive.events.find(e => e.status === 'quarantined');
  assert(quarantined, '只有伺服器請求識別標頭缺失也必須隔離');
  assert(quarantined.value.meta.requestId.startsWith('ai-'), '既有瀏覽器追蹤識別回退保留');
  assert.equal(quarantined.value.meta.serverRequestId, '', '瀏覽器追蹤識別不能冒充伺服器識別');
  assert.equal(quarantined.value.meta.model, missingId.route.model);
  assert.equal(quarantined.value.meta.destinationId, missingId.route.destinationId);
  assert.equal(quarantined.value.result.issues.length, 1); assert(quarantined.value.result.issues[0].includes('伺服器請求識別'));
  assert(missingId.get('rt-result').innerHTML.includes('回應不可驗證'));
  console.log('通過：正式 STAI 缺伺服器請求識別標頭時，保留追蹤回退但隔離研究回應');
})().catch(error => { console.error(error); process.exitCode = 1; });

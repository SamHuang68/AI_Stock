'use strict';

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const decision = fs.readFileSync(path.join(root, 'src', 'ui', 'decision_v5.js'), 'utf8');
const gateway = fs.readFileSync(path.join(root, 'server', 'private_web_gateway.py'), 'utf8');

function ok(condition, message) {
  if (!condition) throw new Error('FAIL: ' + message);
  console.log('PASS:', message);
}

ok(/var AI_TIMEOUT_MS = 12 \* 60 \* 1000/.test(decision) &&
  /AbortController/.test(decision) && /aiController\.abort\(\)/.test(decision),
  'Decision AI has a bounded twelve-minute browser wait');
ok(/if \(aiBusy\) return;/.test(decision) && /aria-busy/.test(decision) &&
  /AI 解釋中…/.test(decision),
  'Decision AI prevents duplicate expensive requests and exposes busy state');
ok(/showEmpty\('AI 解釋尚無可用資料'/.test(decision) &&
  !/if \(!lastContext\) return;/.test(decision),
  'missing DecisionContext is visible instead of silently ignored');
ok((decision.match(/restoreAiDisplay\(\);/g) || []).length >= 2 &&
  /aiDisplayState = \{ visible: true/.test(decision),
  'AI state is rehydrated after periodic DecisionContext renders');
ok(/STAI.request/.test(decision) && /result.meta.requestId/.test(decision) &&
  /請求編號：/.test(decision) && /aiErrorMessage\(error, localRequestId\)/.test(decision),
  'AI requests keep a user-visible correlation identifier');
ok(/status === 401/.test(decision) && /status === 403/.test(decision) &&
  /status === 413/.test(decision) && /status === 429/.test(decision) &&
  /status === 502/.test(decision) && /status === 503/.test(decision),
  'HTTP and runtime failures are classified instead of all appearing disconnected');
ok(/模型完成推理但沒有輸出可見正文/.test(decision) &&
  /市場資料已在分析期間更新/.test(decision),
  'empty output and stale-context output fail explicitly');
ok(/AI 解釋（Owner）/.test(decision) && /gateway\/whoami/.test(decision) &&
  /button\.disabled = !!aiBusy \|\| aiAccessRole === 'reader'/.test(decision),
  'reader accounts see an owner-only disabled control without widening permissions');
ok(/role:__ST_PRIVATE_ROLE__/.test(gateway) && /def _private_profile_boot\(role: str\)/.test(gateway) &&
  /safe_role = "owner" if role == "owner" else "reader"/.test(gateway),
  'gateway injects only its authenticated owner or reader role');

const matcherSource = decision.match(/function aiRuntimeFailureDetail\(answer\) \{[\s\S]*?\n  \}/);
ok(!!matcherSource, 'runtime warning classifier is available for behavioral verification');
const runtimeFailureDetail = new Function(matcherSource[0] + '\nreturn aiRuntimeFailureDetail;')();
ok(runtimeFailureDetail('支持證據。\n⚠ 非投資建議') === '',
  'required non-investment disclaimer remains a successful AI answer');
ok(runtimeFailureDetail('⚠ LM Studio 服務未啟動') === 'LM Studio 服務未啟動',
  'leading runtime warning remains an explicit AI failure');

console.log('Decision AI selftest passed.');

(async () => {
  const assert = require('node:assert/strict');
  const { harness, tick } = require('./投組決策同步_selftest.js');
  const h = harness();
  h.c.DecisionV5.refresh(true);
  await h.complete(h.pending('/decision/context', 'POST'), {
    regime: { id: '固定市場', label: '固定市場' }, revision: 1,
    evidence: [{ id: '價格依據', value: 100 }], actionEnvelope: {}, dataQuality: {}
  });
  const before = JSON.stringify(h.c.DecisionData.get());
  let options;
  h.c.STAI = { request(value) { options = value; const error = new Error('SSE 未收到完成事件'); error.detail = '連線中斷，沒有完成收據'; return { promise: Promise.reject(error) }; } };
  h.nodes.get('dc-ai-btn').onclick(); await tick();
  assert.match(h.nodes.get('dc-ai-body').textContent, /連線中斷|完成收據/);
  assert.equal(JSON.stringify(h.c.DecisionData.get()), before);
  assert.match(options.prompt, /不得改寫 regime/);
  h.c.STAI.request = () => ({ promise: Promise.resolve({ text: '支持證據為價格依據。⚠ 非投資建議', meta: { requestId: '已完成測試' } }) });
  h.nodes.get('dc-ai-btn').onclick(); await tick();
  assert.match(h.nodes.get('dc-ai-body').textContent, /支持證據為價格依據/);
  assert.match(h.nodes.get('dc-ai-body').textContent, /已完成測試/);
  assert.equal(JSON.stringify(h.c.DecisionData.get()), before);
  console.log('通過：決策AI完成收據/截斷錯誤/證據prompt與市場Context不可變');

  for (const role of ['owner', 'reader', 'unknown']) {
    const pending = harness('unknown');
    pending.c.dispatchEvent(new pending.c.CustomEvent('decisionData', { detail: { state: { context: {
      regime: { id: '權限測試' }, actionEnvelope: {}, evidence: []
    } } } }));
    let calls = 0;
    pending.c.STAI = { request() { calls++; return { promise: Promise.resolve({ text: '權限確認完成', meta: {} }) }; } };
    const button = pending.nodes.get('dc-ai-btn');
    button.onclick(); button.onclick();
    assert.equal(button.disabled, true);
    assert.match(pending.nodes.get('dc-ai-body').textContent, /正在確認 Private Web 權限/);
    assert.equal(pending.requests.filter(request => request.path === '/gateway/whoami').length, 1);
    await pending.complete(pending.pending('/gateway/whoami'), { role }, role === 'unknown' ? 503 : 200);
    assert.equal(calls, role === 'owner' ? 1 : 0);
    assert.equal(button.disabled, role === 'reader');
    assert.match(pending.nodes.get('dc-ai-body').textContent, role === 'owner' ? /權限確認完成/ : role === 'reader' ? /僅 Owner/ : /無法確認/);
  }
  console.log('通過：首次權限確認立即回饋、防重複與 Owner／Reader／查核失敗分流');

  const missing = harness('unknown');
  missing.c.DecisionV5.activate();
  let missingCalls = 0;
  missing.c.STAI = { request() { missingCalls++; throw new Error('缺少決策資料不應呼叫模型'); } };
  missing.nodes.get('dc-ai-btn').onclick();
  await missing.complete(missing.pending('/gateway/whoami'), { role: 'owner' });
  assert.equal(missingCalls, 0);
  assert.equal(missing.nodes.get('dc-ai-btn').disabled, false);
  assert.match(missing.nodes.get('dc-ai-body').textContent, /尚無可用資料[\s\S]*更新市場資料/);
  assert.match(missing.nodes.get('dc-ai-status').textContent, /解釋未完成/);
  console.log('通過：首次權限確認後缺少決策資料時，明確顯示未完成而非假成功');
})().catch(error => { console.error(error); process.exitCode = 1; });

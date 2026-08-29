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
ok(/X-ST-Trace-ID/.test(decision) && /X-ST-AI-Request-ID/.test(decision) &&
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

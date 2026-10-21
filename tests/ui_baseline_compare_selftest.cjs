// UI 同條件對照工具的自我驗證：同一版本（HEAD）對自己，必須全部就緒、無頁面錯誤，
// 且沒有任何一組被判為「有差異」（版本內不穩定是頁面本身的競態，照實列出但不算工具失敗）。
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const run = spawnSync(process.execPath, [path.join(__dirname, 'ui_baseline_compare.cjs'), '--self', '--base', 'HEAD',
  '--routes', 'pulse,heat'], { cwd: root, encoding: 'utf8', timeout: 540000 });
process.stdout.write(run.stdout || '');
process.stderr.write(run.stderr || '');
assert.equal(run.status, 0, '自我對照失敗（見上方問題清單）');

const line = (run.stdout || '').split(/\r?\n/).find(l => l.startsWith('報告：'));
assert.ok(line, '找不到報告路徑');
const receipt = JSON.parse(fs.readFileSync(path.join(root, path.dirname(line.slice(3).trim()), 'receipt.json'), 'utf8'));
assert.equal(receipt.fixtureOnly, true);
assert.equal(receipt.base.sha, receipt.head.sha, '自我對照兩邊必須是同一版本');
assert.equal(receipt.pairs.length, 4, '應有 pulse、heat 各兩種視窗共 4 組');
for (const pair of receipt.pairs) {
  for (const entry of [pair.base, pair.head, pair.baseRepeat, pair.headRepeat]) {
    assert.equal(entry.ready, true, `${pair.route} ${pair.viewport} ${entry.version} 未就緒`);
    assert.deepEqual(entry.pageErrors, [], `${pair.route} ${pair.viewport} ${entry.version} 有頁面錯誤`);
  }
  assert.notEqual(pair.verdict, 'different', `${pair.route} ${pair.viewport} 同一版本被判為有差異`);
}
// 產業頁必須真的使用合成資料渲染（16 個示意類股），不是空白頁。
assert.ok(receipt.unfixtured.every(e => e !== 'GET /sectors'), '/sectors 應由合成資料回應');
console.log('ui_baseline_compare selftest OK：' + receipt.pairs.map(p => `${p.route} ${p.viewport}=${p.verdict}`).join('，'));

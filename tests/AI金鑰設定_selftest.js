// 使用實際設定函式驗證慢回覆與失敗不會清除既有工作區；全程使用模擬服務。
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(path.join(__dirname, '..', 'stock_terminal.html'), 'utf8');
const code = html.slice(html.indexOf('function showKeyModal()'), html.indexOf('async function clearKey()'));
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup() {
  const nodes = {}, posts = [];
  let resolveStatus, rejectStatus;
  const pending = new Promise((resolve, reject) => { resolveStatus = resolve; rejectStatus = reject; });
  const scope = {
    S: { aiKeySet: true }, SERVER: '',
    document: {
      getElementById(id) { return nodes[id] || null; },
      createElement() {
        const modal = { isConnected: false, querySelector(s) { return nodes[s.slice(1)]; },
          remove() { this.isConnected = false; delete nodes['key-modal']; },
          set innerHTML(value) {
            nodes['key-inp'] = { value: '', focus() {} };
            nodes['key-workspace'] = { value: '', disabled: true };
            nodes['key-save'] = { disabled: true };
            nodes['key-workspace-state'] = { textContent: '' };
          } };
        nodes['key-modal'] = modal;
        return modal;
      },
      body: { appendChild(node) { node.isConnected = true; } },
    },
    fetch(url, options) {
      if (url === '/ai-key/status') return pending;
      posts.push(JSON.parse(options.body));
      return Promise.resolve({ ok: true });
    },
    updateKeyBtn() {}, renderRpanel() {}, alert(message) { throw new Error(message); },
  };
  vm.createContext(scope);
  vm.runInContext(code, scope);
  scope.showKeyModal();
  return { scope, nodes, posts, resolveStatus, rejectStatus };
}

(async () => {
  const slow = setup();
  slow.nodes['key-inp'].value = 'sk-test-new';
  await slow.scope.saveKey();
  assert.equal(slow.posts.length, 0, '設定載入前不得儲存新金鑰');
  slow.resolveStatus({ ok: true, json: async () => ({ set: true, workspaceId: 'wrkspc_existing' }) });
  await tick();
  assert.equal(slow.nodes['key-save'].disabled, false);
  await slow.scope.saveKey();
  assert.deepEqual(slow.posts, [{ key: 'sk-test-new', workspaceId: 'wrkspc_existing' }]);

  const failed = setup();
  failed.nodes['key-inp'].value = 'sk-test-new';
  failed.rejectStatus(new Error('模擬服務無法連線'));
  await tick();
  await failed.scope.saveKey();
  assert.equal(failed.nodes['key-save'].disabled, true);
  assert.equal(failed.posts.length, 0, '設定讀取失敗不得省略工作區後儲存');
  assert.match(failed.nodes['key-workspace-state'].textContent, /重新開啟/);

  const workspaceOnly = setup();
  workspaceOnly.resolveStatus({ ok: true, json: async () => ({ set: true, workspaceId: '' }) });
  await tick();
  workspaceOnly.nodes['key-workspace'].value = 'wrkspc_selected';
  await workspaceOnly.scope.saveKey();
  assert.deepEqual(workspaceOnly.posts, [{ key: '', workspaceId: 'wrkspc_selected' }]);
  console.log('AI 金鑰設定驗收通過：載入中、讀取失敗、保留工作區與只更新工作區。');
})().catch(error => { console.error(error); process.exitCode = 1; });

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'stock_terminal.html'), 'utf8');
const start = source.indexOf('const RPANEL_PAGES =');
const end = source.indexOf('function renderRpanel()', start);
if (start < 0 || end < 0) throw new Error('mobile workspace pager source block missing');

function element() {
  const attrs = {};
  return {
    dataset: {}, innerHTML: '', textContent: '', disabled: false, scrollTop: 0,
    classList: { toggle() {} },
    setAttribute(k, v) { attrs[k] = String(v); },
    removeAttribute(k) { delete attrs[k]; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    addEventListener() {}
  };
}

const ids = {
  body: element(), left: element(), right: element(), rpanel: element(),
  'rpage-label': element(), 'rpage-dots': element(),
  'rpage-prev': element(), 'rpage-next': element()
};
let orientation = 'portrait';
let dispatchCount = 0;
const sandbox = {
  S: { tab: 'stats' },
  document: {
    getElementById(id) { return ids[id] || null; },
    querySelectorAll() { return []; }
  },
  window: {
    innerWidth: 375, innerHeight: 667,
    matchMedia(query) {
      return { matches: query.includes('orientation: portrait') ? orientation === 'portrait' : true };
    },
    dispatchEvent() { dispatchCount += 1; }
  },
  fetch() { return Promise.resolve({ ok: true }); },
  Event: function Event(name) { this.type = name; },
  setTimeout(fn) { fn(); return 1; },
  clearTimeout() {},
  getDispatchCount() { return dispatchCount; },
  setOrientation(value) { orientation = value; },
  console
};

const exercise = source.slice(start, end) + `
syncMobileWorkspacePage();
syncMobileWorkspacePage();
globalThis.__initialResizeCount = getDispatchCount();
shiftRtab(1);
globalThis.__portrait = {
  page: document.getElementById('body').getAttribute('data-mobile-workspace-page'),
  key: document.getElementById('body').getAttribute('data-mobile-workspace-key'),
  label: document.getElementById('rpage-label').textContent,
  dots: (document.getElementById('rpage-dots').innerHTML.match(/rpage-dot/g) || []).length
};
setOrientation('landscape');
syncMobileWorkspacePage();
globalThis.__landscape = {
  page: document.getElementById('body').getAttribute('data-mobile-workspace-page'),
  key: document.getElementById('body').getAttribute('data-mobile-workspace-key')
};`;

vm.createContext(sandbox);
vm.runInContext(exercise, sandbox);

function ok(value, message) {
  if (!value) throw new Error('FAIL: ' + message);
  console.log('OK  ', message);
}

ok(sandbox.__portrait.page === 'analysis', 'next changes the entire portrait workspace to analysis');
ok(sandbox.__initialResizeCount === 1, 'chart visibility emits one resize without a self-triggering loop');
ok(sandbox.__portrait.key === 'stats', 'first analysis page is technical statistics');
ok(sandbox.__portrait.label === '技術統計 · 2 / 7', 'bottom index includes line chart as page one');
ok(sandbox.__portrait.dots === 7, 'bottom index renders seven workspace pages');
ok(sandbox.__landscape.page == null && sandbox.__landscape.key == null,
  'landscape removes portrait paging state and restores the split workspace');
console.log('\nmobile_workspace_pager_selftest PASSED');

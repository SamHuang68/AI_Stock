'use strict';

// 執行實際換頁函式，確認共同捲動位置與圖表可見狀態；幾何仍由瀏覽器驗收。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/ui/shell_v5.js'), 'utf8');
const start = source.indexOf('  function applyRoute(id, opts) {');
const end = source.indexOf('  function go(id, opts) {', start);
assert.ok(start >= 0 && end > start, '找到實際路由切換函式');

function element(route) {
  const classes = new Set();
  return {
    dataset: { route }, scrollTop: 0, scrollLeft: 0,
    classList: {
      toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
      contains(name) { return classes.has(name); }
    },
    setAttribute() {}, removeAttribute() {}
  };
}

const routes = ['heat', 'news', 'chart'].map(id => ({ id }));
const panels = routes.map(route => element(route.id));
const ids = Object.fromEntries(['topbar', 'body', 'wlbar', 'rpanel-pager', 'shell-views', 'shell-main', 'mkt-bar']
  .map(id => [id, element()]));
const pageBody = element();
const rootElement = element();
const frames = [];
const surfaces = [ids['shell-main'], ids['shell-views'], pageBody, rootElement];
const emitted = [];
const deactivated = [];
const loaded = [];
const context = {
  state: { route: 'heat', prevRoute: 'heat' }, ROUTES: routes, STORAGE_KEY: '測試路由',
  resolveAlias(id, opts) { return { id, opts }; },
  findRoute(id) { return routes.find(route => route.id === id); },
  $(id) { return ids[id] || null; },
  document: { body: pageBody, documentElement: rootElement, querySelectorAll() { return panels; } },
  window: {
    location: { pathname: '/', search: '' }, history: { replaceState() {} }, dispatchEvent() {},
    requestAnimationFrame(callback) { frames.push(callback); return frames.length; }
  },
  localStorage: { setItem() {} },
  ringState: { open: false },
  deactivateRoute(id) { deactivated.push(id); },
  emitRoute(id, opts) { emitted.push({ id, opts }); },
  traceMobilePanelLayout() {},
  loadSym(sym, mkt) { loaded.push({ sym, mkt }); },
  setTimeout(fn) { fn(); }, Event: function (name) { this.type = name; }, console
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

function setScroll(top, left) {
  surfaces.forEach(surface => { surface.scrollTop = top; surface.scrollLeft = left; });
}
function assertScroll(top, left, label) {
  surfaces.forEach(surface => {
    assert.equal(surface.scrollTop, top, label + '：垂直位置');
    assert.equal(surface.scrollLeft, left, label + '：橫向位置');
  });
}
function flushFrames() {
  frames.splice(0).forEach(callback => callback());
}

setScroll(920, 12);
context.applyRoute('heat', { sector: '半導體' });
assertScroll(920, 12, '相同路由的類股選取保留內外容器閱讀位置');
assert.equal(frames.length, 0, '相同路由不排入下一幀歸零');
assert.equal(emitted.at(-1).opts.sector, '半導體', '保留同路由選取參數');
assert.deepEqual(deactivated, [], '相同路由不終止既有模組');

context.applyRoute('news');
assertScroll(0, 0, '切換功能頁清除主容器及外層頁面位移');
setScroll(26.333, 8);
flushFrames();
assertScroll(0, 0, '路由重排後下一幀清除焦點造成的外層位移');
assert.equal(frames.length, 0, '路由捲動補正只排一幀');
assert.equal(ids['shell-views'].classList.contains('show'), true, '功能頁使用共同捲動容器');
assert.equal(ids['rpanel-pager'].classList.contains('shell-hidden'), true, '功能頁隱藏圖表分頁底列');
assert.deepEqual(deactivated, ['heat'], '只終止離開的模組');

setScroll(450, 13);
context.applyRoute('chart', { sym: '2330', mkt: 'TW' });
assert.equal(ids['shell-views'].classList.contains('show'), false, '圖表仍使用原工作台');
assert.equal(ids['rpanel-pager'].classList.contains('shell-hidden'), false, '圖表保留分析分頁底列');
assert.deepEqual(loaded, [{ sym: '2330', mkt: 'TW' }], '切換個股仍傳送代號與市場');
assertScroll(0, 0, '切換到圖表時清除殘留位置');
flushFrames();
setScroll(165, 8);
context.applyRoute('heat');
assertScroll(0, 0, '圖表捲動後切到熱力不殘留裁頭位移');
flushFrames();

// 執行總覽的實際欄數診斷，避免短橫式已改兩欄卻仍被診斷成桌機五欄。
const pulseSource = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
const probeStart = pulseSource.indexOf('  function probeLayoutCols() {');
const probeEnd = pulseSource.indexOf('  function injectCSS() {', probeStart);
assert.ok(probeStart >= 0 && probeEnd > probeStart, '找到實際總覽欄數診斷函式');
for (const [width, height, columns] of [[393, 852, 2], [852, 330, 2], [767, 400, 2], [981, 330, 5], [1440, 900, 5]]) {
  const probe = { style: {} };
  const zones = [{ children: Array(5) }, { children: Array(5) }];
  const probeContext = {
    pulseMode: 'expert', MOBILE_LAYOUT_CONTRACT: '2col-scroll', LAYOUT_CONTRACT: '5col-2zone', LAYOUT_ANCHOR: '版面測試',
    $(id) { return id === 'pl-layout-probe' ? probe : null; },
    document: { querySelectorAll() { return zones; } },
    window: {
      matchMedia(query) {
        const limits = [...query.matchAll(/\((max|min)-(width|height):\s*(\d+)px\)/g)];
        const sizeMatches = limits.every(([, edge, axis, value]) => {
          const actual = axis === 'width' ? width : height;
          return edge === 'max' ? actual <= Number(value) : actual >= Number(value);
        });
        const orientation = query.match(/orientation:\s*(portrait|landscape)/)?.[1];
        return { matches: sizeMatches && (!orientation || (orientation === 'portrait' ? height >= width : width > height)) };
      },
      getComputedStyle() { return { gridTemplateColumns: Array(columns).fill('160px').join(' ') }; }
    },
    console: { log() {} }
  };
  vm.createContext(probeContext);
  vm.runInContext(pulseSource.slice(probeStart, probeEnd), probeContext);
  assert.equal(probeContext.probeLayoutCols(), true, width + '×' + height + ' 的實際欄數診斷應通過');
  assert.match(probe.textContent, columns === 2 ? /手機兩欄/ : /實測 5\+5/);
}

console.log('手機頁面捲動自測通過：路由位置、圖表工作台、個股切換及五種視窗的總覽欄數皆正常。');

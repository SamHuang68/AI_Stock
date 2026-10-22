'use strict';
/**
 * 統計面板的研究卡片（波峰觀察、波峰 100 日、投信 5 日、條件期望）與分頁的互動（審查 TQ-01）。
 *
 * 正式頁面的 S 是頂層 `let S`，不是 window.S。過去這四個模組用 `typeof window.S !== 'undefined'` 守衛，
 * 在正式頁面永遠不成立：換股時卡片被掛進共用的 #rpanel，即使當時在「體檢」分頁；切回「統計」分頁時
 * 面板被 renderRpanel 整塊重畫，卡片消失，直到下次換股。
 *
 * 此測試執行 src/ui 內四個模組的正式程式碼，只提供瀏覽器環境：先宣告頂層 `let S`（詞法綁定），並斷言
 * window.S 始終是 undefined；DOM 是最小實作，會在「面板重畫」時真的移除舊節點。
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const MODULES = [
  { file: 'src/ui/peak_observation_v5.js', sectId: 'st-pk-sect', flag: 'shadowPeakObservation' },
  { file: 'src/ui/peak_observation_100d_v5.js', sectId: 'st-pk100-sect', flag: 'shadowPeak100d' },
  { file: 'src/ui/touxin_5d_v5.js', sectId: 'st-tx-sect', flag: 'shadowTouxin5d' },
  { file: 'src/ui/conditional_expectation_v5.js', sectId: 'st-ce-sect', flag: 'shadowConditionalExpectation' },
];

function makeEnv(mod, { windowS = false } = {}) {
  const registry = new Map();            // id → element（只含已連到文件的節點）
  const listeners = {};
  const fetches = [];
  function element(tag) {
    const el = { tagName: tag, id: '', hidden: false, innerHTML: '', textContent: '', children: [], dataset: {}, parent: null, isConnected: false,
      appendChild(child) { child.parent = el; el.children.push(child); connect(child, el.isConnected); return child; },
      remove() { if (el.parent) el.parent.children = el.parent.children.filter(c => c !== el); disconnect(el); el.parent = null; } };
    return el;
  }
  function connect(el, on) { el.isConnected = on; if (on && el.id) registry.set(el.id, el); el.children.forEach(c => connect(c, on)); }
  function disconnect(el) { el.isConnected = false; if (el.id && registry.get(el.id) === el) registry.delete(el.id); el.children.forEach(disconnect); }
  const host = element('div'); host.id = 'rpanel'; connect(host, true);
  // 模擬 renderRpanel：整塊換掉面板內容，舊的子節點全部脫離文件
  const wipe = () => { host.children.slice().forEach(c => disconnect(c)); host.children = []; host.innerHTML = '<table>stats</table>'; };

  const context = {
    FeatureFlags: { isEnabled: name => name === mod.flag },
    SERVER: 'http://127.0.0.1:18432',
    addEventListener(name, fn) { (listeners[name] = listeners[name] || []).push(fn); },
    dispatchEvent(event) { (listeners[event.type] || []).forEach(fn => fn(event)); return true; },
    console: { log() {}, warn() {}, error() {} }, Date, Number, Math, isFinite, Promise, JSON, Object, Array, String, Boolean, Map, Set, Error, RegExp,
    encodeURIComponent, setTimeout: () => 0, clearTimeout() {},
    location: { origin: 'http://127.0.0.1:18432' },
    fetch(url) { fetches.push(String(url)); return Promise.resolve({ ok: false, json: () => Promise.resolve(null) }); },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
    document: {
      getElementById: id => registry.get(id) || null,
      createElement: element,
      addEventListener() {},
    },
  };
  // 瀏覽器裡 window 就是全域物件
  context.window = context;
  context.globalThis = context;
  const windowObj = context;
  vm.createContext(context);
  vm.runInContext("let S = { sym: '2330', mkt: 'TW', tab: 'stats' };", context, { filename: 'stock_terminal.html#S' });
  if (windowS) windowObj.S = vm.runInContext('S', context);
  vm.runInContext(fs.readFileSync(path.join(root, mod.file), 'utf8'), context, { filename: mod.file });
  const setState = patch => vm.runInContext('Object.assign(S, ' + JSON.stringify(patch) + ')', context);
  const emit = (type, detail) => windowObj.dispatchEvent(new context.CustomEvent(type, { detail }));
  const flush = () => new Promise(resolve => setImmediate(resolve));
  return { context, host, registry, fetches, wipe, setState, emit, flush, windowObj };
}

let failed = false;
function run(name, fn) {
  return Promise.resolve().then(fn).then(() => console.log('OK   ' + name), error => { failed = true; console.error('FAIL ' + name + '\n  ' + (error && error.stack || error)); });
}

(async () => {
  for (const mod of MODULES) {
    const tag = '[' + path.basename(mod.file) + '] ';

    await run(tag + '前提：正式環境沒有 window.S，詞法 S 存在', async () => {
      const env = makeEnv(mod);
      assert.strictEqual(env.windowObj.S, undefined);
      assert.strictEqual(vm.runInContext('typeof S', env.context), 'object');
    });

    await run(tag + '在統計分頁換股：卡片掛進面板', async () => {
      const env = makeEnv(mod);
      env.emit('symLoaded', { sym: '2330', mkt: 'TW' });
      await env.flush();
      const sect = env.registry.get(mod.sectId);
      assert(sect && sect.isConnected, '卡片沒有掛上');
      assert.strictEqual(sect.dataset.sym, '2330');
      assert.strictEqual(env.host.children.length, 1);
    });

    await run(tag + '在體檢分頁換股：卡片不得掛進共用面板', async () => {
      const env = makeEnv(mod);
      env.setState({ tab: 'health' });
      env.emit('symLoaded', { sym: '2317', mkt: 'TW' });
      await env.flush();
      assert.strictEqual(env.registry.get(mod.sectId), undefined, '體檢分頁出現了統計卡片');
      assert.strictEqual(env.host.children.length, 0);
      assert.strictEqual(env.fetches.length, 0, '不該為看不到的卡片發出請求');
    });

    await run(tag + '面板被重畫後重新掛上卡片', async () => {
      const env = makeEnv(mod);
      env.emit('symLoaded', { sym: '2330', mkt: 'TW' });
      await env.flush();
      assert(env.registry.get(mod.sectId));
      env.wipe();
      assert.strictEqual(env.registry.get(mod.sectId), undefined, '夾具：重畫後舊卡片應已脫離文件');
      env.emit('statsPanelRendered', { sym: '2330', mkt: 'TW' });
      await env.flush();
      const sect = env.registry.get(mod.sectId);
      assert(sect && sect.isConnected, '重畫後卡片沒有回來');
      assert.strictEqual(sect.dataset.sym, '2330');
    });

    await run(tag + '切離統計分頁再切回：卡片回來', async () => {
      const env = makeEnv(mod);
      env.emit('symLoaded', { sym: '2330', mkt: 'TW' });
      await env.flush();
      env.setState({ tab: 'health' }); env.wipe();             // 切到體檢：面板被換成體檢內容
      env.emit('symLoaded', { sym: '2317', mkt: 'TW' });
      await env.flush();
      assert.strictEqual(env.registry.get(mod.sectId), undefined);
      env.setState({ tab: 'stats', sym: '2317' }); env.wipe();  // 切回統計
      env.emit('statsPanelRendered', { sym: '2317', mkt: 'TW' });
      await env.flush();
      const sect = env.registry.get(mod.sectId);
      assert(sect && sect.dataset.sym === '2317', '切回統計分頁後應顯示目前這檔股票的卡片');
    });

    await run(tag + '已掛著同一檔股票的卡片時，重畫通知不重複載入', async () => {
      const env = makeEnv(mod);
      env.emit('symLoaded', { sym: '2330', mkt: 'TW' });
      await env.flush();
      const before = env.fetches.length;
      env.emit('statsPanelRendered', { sym: '2330', mkt: 'TW' });
      await env.flush();
      assert.strictEqual(env.fetches.length, before, '同一檔股票不應重複請求');
    });

    await run(tag + '非台股不顯示卡片；window.S 存在時行為相同', async () => {
      const us = makeEnv(mod);
      us.setState({ mkt: 'US', sym: 'AAPL' });
      us.emit('symLoaded', { sym: 'AAPL', mkt: 'US' });
      await us.flush();
      assert.strictEqual(us.registry.get(mod.sectId), undefined);
      const withWindowS = makeEnv(mod, { windowS: true });
      withWindowS.setState({ tab: 'health' });
      withWindowS.emit('symLoaded', { sym: '2317', mkt: 'TW' });
      await withWindowS.flush();
      assert.strictEqual(withWindowS.registry.get(mod.sectId), undefined);
    });
  }
  if (!failed) console.log('\nAll stats card tab checks passed.');
  else process.exitCode = 1;
})();

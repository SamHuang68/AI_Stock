'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/chart/hotkeys_v3.js'), 'utf8');
let openDialog = false, handler, navigations = [], symbols = [], prevented = 0;
const document = {
  querySelector: selector => selector === 'dialog[open]' && openDialog ? {} : null,
  querySelectorAll: () => [], getElementById: () => null,
  addEventListener: (name, fn) => { if (name === 'keydown') handler = fn; }
};
const context = { document, console: { log() {} },
  window: { ShellV5: { isRingOpen: () => false, route: () => 'research', go: route => navigations.push(route) } },
  S: { sym: '2330', wl: [{ t: '2330', m: 'TW' }, { t: '0050', m: 'TW' }] },
  loadSym: symbol => symbols.push(symbol), getComputedStyle: () => ({ display: 'none' }) };
vm.runInNewContext(source, context, { filename: 'hotkeys_v3.js' });
function key(value, extra = {}) {
  handler(Object.assign({ key: value, target: { tagName: 'BUTTON' }, preventDefault: () => prevented++ }, extra));
}
openDialog = true;
key('Escape'); key(' ', { code: 'Space' }); key('/'); key('?');
assert.deepEqual(navigations, [], '原生對話框開啟時 Escape 不得切換背景路由');
assert.deepEqual(symbols, [], '原生按鈕 Space 不得改變背景股票');
assert.equal(prevented, 0, '原生 dialog 的鍵盤預設行為必須保留');
openDialog = false;
key('Escape', { defaultPrevented: true });
assert.deepEqual(navigations, [], '已處理的按鍵不得重複導航');
key('Escape');
assert.deepEqual(navigations, ['chart'], '沒有浮層時保留舊 Escape 導航');
key(' ', { code: 'Space' });
assert.deepEqual(symbols, ['0050'], '沒有浮層時保留自選股快捷鍵');
key('Escape', { target: { tagName: 'INPUT' } });
assert.deepEqual(navigations, ['chart'], '輸入欄位不導航');
console.log('對話框快捷鍵：正式模組 6 組回歸通過');

/* 正式研究模組：工具列入口、可見性、Escape、關閉與頁面切換。 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const nodes = new Map(), listeners = new Map();
const context = { console, URLSearchParams, AbortController, setTimeout() { return 0; }, clearTimeout() {},
  fetch: () => new Promise(() => {}),
  addEventListener(type, fn) { listeners.set(type, fn); } };
function element(id = '') {
  const e = { id, isConnected: true, disabled: false, hidden: false, value: '', parentElement: null,
    setAttribute() {}, getClientRects() { return this.hidden || this.parentElement && this.parentElement.hidden ? [] : [{}]; },
    querySelector(selector) { return selector === '.tbg-btn' ? this.button : null; },
    closest(selector) { return selector === '.tbg-menu' ? this.menu : null; },
    appendChild(child) { nodes.set(child.id, child); child.parentElement = this; },
    showModal() { this.open = true; }, close() { this.open = false; },
    focus() { context.document.activeElement = this; } };
  Object.defineProperty(e, 'innerHTML', { get() { return this.html || ''; }, set(html) {
    this.html = html;
    for (const match of html.matchAll(/<\w+\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
      const child = element(match[1]);
      child.value = (match[0].match(/\bvalue="([^"]*)"/) || [])[1] || '';
      if (child.id === 'ke-range') child.value = '3y';
    }
  } });
  if (id) nodes.set(id, e); return e;
}
context.document = { activeElement: null, getElementById: id => nodes.get(id), createElement: () => element(),
  head: element(), body: element() };
context.window = context;
element('pro-tools');
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/ui/K線事件研究.js'), 'utf8'), context);
const trigger = nodes.get('btn-kline-events');
trigger.focus(); trigger.onclick({ currentTarget: trigger });
assert.equal(context.document.activeElement.id, 'ke-close');
context.KlineEventsUI.close(); assert.equal(context.document.activeElement, trigger);
const group = element('tbg-screen'), button = element('screen-trigger'); group.button = button;
const menu = element('tbg-menu-screen'); trigger.menu = menu; trigger.parentElement = menu;
trigger.focus(); trigger.onclick({ currentTarget: trigger }); menu.hidden = true;
let cancelled = false;
nodes.get('ke-dialog').oncancel({ preventDefault() { cancelled = true; } });
assert(cancelled); assert.equal(nodes.get('ke-dialog').open, false);
assert.equal(context.document.activeElement, button, '收合選單後 Escape 回可見分類按鈕');
menu.hidden = false; trigger.onclick({ currentTarget: trigger }); menu.hidden = true;
nodes.get('ke-close').onclick(); assert.equal(context.document.activeElement, button);
const external = element('visible-external'); context.KlineEventsUI.open('2330', external);
context.KlineEventsUI.close(); assert.equal(context.document.activeElement, external);
context.KlineEventsUI.open('2330', external); external.isConnected = false;
context.KlineEventsUI.close(); assert.equal(context.document.activeElement, button, '入口被移除時退到研究工具列分類');
menu.hidden = false; trigger.onclick({ currentTarget: trigger }); menu.hidden = true;
listeners.get('hashchange')(); assert.equal(nodes.get('ke-dialog').open, false);
assert.equal(context.document.activeElement, button);
console.log('通過：正式研究開窗、獨立入口、工具列關閉／Escape、入口移除與換頁焦點返回');

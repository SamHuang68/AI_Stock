#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const scriptPath = path.resolve(__dirname, '../src/ui/dragwin_v3.js');
const source = fs.readFileSync(scriptPath, 'utf8');
const STORAGE_KEY = 'stock_winpos_v3';

class Element {
  constructor(tag, { id = '', position = 'static', rect } = {}) {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.nodeType = 1;
    this.children = [];
    this.parentElement = null;
    this.style = {};
    this.position = position;
    this.textContent = '';
    this.rect = rect || { left: 120, top: 140, width: 400, height: 300 };
    this.offsetWidth = this.rect.width;
    this.offsetHeight = this.rect.height;
  }
  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }
  matches(selector) {
    return selector.split(',').some(tag => tag.trim().toUpperCase() === this.tagName);
  }
  closest(selector) {
    for (let element = this; element; element = element.parentElement) {
      if (element.matches(selector)) return element;
    }
    return null;
  }
  querySelectorAll(selector) {
    const results = [];
    for (const child of this.children) {
      if (child.matches(selector)) results.push(child);
      results.push(...child.querySelectorAll(selector));
    }
    return results;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  getBoundingClientRect() { return { ...this.rect }; }
}

function fixture(native) {
  const overlay = new Element(native ? 'dialog' : 'div', {
    position: 'fixed', rect: { left: 0, top: 0, width: 1000, height: 800 }
  });
  const box = overlay.appendChild(new Element('div', { id: native ? '估值內容' : '原有視窗' }));
  const heading = box.appendChild(new Element('h3'));
  heading.textContent = native ? '估值假設' : '原有功能';
  const target = heading.appendChild(new Element('span'));
  return { overlay, box, heading, target };
}

function harness(saved = {}) {
  const events = new Map();
  const storage = new Map([[STORAGE_KEY, JSON.stringify(saved)]]);
  let observer = null;
  let storageWrites = 0;
  const document = {
    body: new Element('body'), head: new Element('head'),
    addEventListener(name, listener) { events.set(name, listener); },
    createElement(tag) { return new Element(tag); }
  };
  const sandbox = {
    document,
    localStorage: {
      getItem(key) { return storage.get(key) ?? null; },
      setItem(key, value) { storageWrites++; storage.set(key, value); }
    },
    getComputedStyle(element) { return { position: element.style.position || element.position }; },
    MutationObserver: class {
      constructor(callback) { observer = callback; }
      observe(target, options) {
        assert.equal(target, document.body);
        assert.equal(options.childList, true);
        assert.equal(options.subtree, true);
      }
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: scriptPath });
  return {
    emit(name, target, options = {}) {
      const event = { target, button: 0, clientX: 140, clientY: 160,
        defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...options };
      assert.ok(events.has(name), '應註冊指定事件');
      events.get(name)(event);
      return event;
    },
    added(...nodes) { observer([{ addedNodes: nodes }]); },
    saved() { return JSON.parse(storage.get(STORAGE_KEY)); },
    writes() { return storageWrites; }
  };
}

let passed = 0;
function test(name, run) { run(); passed++; console.log('通過：' + name); }

test('原生對話框標題按下及移動不改動內容定位', () => {
  const h = harness(), native = fixture(true);
  const before = { ...native.box.style };
  const down = h.emit('mousedown', native.target);
  h.emit('mousemove', native.target, { clientX: 300, clientY: 500 });
  h.emit('mouseup', native.target);
  assert.deepEqual(native.box.style, before);
  assert.deepEqual(native.heading.style, {});
  assert.equal(down.defaultPrevented, false);
  assert.equal(h.writes(), 0);
});

test('原生對話框雙擊保留原有樣式及儲存紀錄', () => {
  const saved = { '估值內容': { x: 30, y: 50 } };
  const h = harness(saved), native = fixture(true);
  native.box.style = { position: 'relative', margin: '8px', top: '2px' };
  const before = { ...native.box.style };
  h.emit('dblclick', native.target);
  assert.deepEqual(native.box.style, before);
  assert.deepEqual(h.saved(), saved);
  assert.equal(h.writes(), 0);
});

test('原有覆蓋視窗仍可拖曳、儲存位置及雙擊重置', () => {
  const h = harness(), legacy = fixture(false);
  const down = h.emit('mousedown', legacy.target);
  assert.equal(down.defaultPrevented, true);
  assert.equal(legacy.box.style.position, 'absolute');
  assert.equal(legacy.heading.style.cursor, 'grabbing');
  h.emit('mousemove', legacy.target, { clientX: 200, clientY: 220 });
  assert.equal(legacy.box.style.left, '180px');
  assert.equal(legacy.box.style.top, '200px');
  h.emit('mouseup', legacy.target);
  assert.deepEqual(h.saved(), { '原有視窗': { x: 180, y: 200 } });
  assert.equal(legacy.heading.style.cursor, '');
  h.emit('dblclick', legacy.target);
  assert.equal(legacy.box.style.position, '');
  assert.equal(legacy.box.style.left, '');
  assert.equal(legacy.box.style.top, '');
  assert.deepEqual(h.saved(), {});
});

test('新增節點觀察只還原舊視窗，不將原生對話框套成絕對定位', () => {
  const saved = { '估值內容': { x: 1, y: -657 }, '原有視窗': { x: 80, y: 90 } };
  const h = harness(saved), native = fixture(true), legacy = fixture(false);
  h.added(native.overlay, legacy.overlay);
  assert.deepEqual(native.box.style, {});
  assert.equal(legacy.box.style.position, 'absolute');
  assert.equal(legacy.box.style.left, '80px');
  assert.equal(legacy.box.style.top, '90px');
  // 對話框內部後續新增的內容也會被觀察；其祖先仍需排除。
  h.added(native.box);
  assert.deepEqual(native.box.style, {});
  assert.deepEqual(h.saved(), saved);
  assert.equal(h.writes(), 0);
});

console.log('原生對話框拖曳驗證完成：' + passed + ' 項通過。');

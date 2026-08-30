#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/core/etf_v3.js'), 'utf8');
const tipSource = fs.readFileSync(path.join(root, 'src/core/etf_flow_tip_v3.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'stock_terminal.html'), 'utf8');

function ok(value, label) {
  if (!value) throw new Error('FAIL: ' + label);
  process.stdout.write('ok - ' + label + '\n');
}

function response(status, body, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: key => headers[key] || headers[String(key).toLowerCase()] || null },
    clone() { return response(status, body, headers); },
    async json() { return body; },
  };
}

const deltaQueue = [];
const emptyElement = () => ({
  id: '', style: {}, dataset: {}, classList: {add(){}, remove(){}, toggle(){}},
  setAttribute(){}, addEventListener(){}, appendChild(){}, querySelector(){return null;},
  querySelectorAll(){return [];}, closest(){return null;},
});
const document = {
  head: { appendChild(){} }, body: { appendChild(){} },
  getElementById(){ return null; }, createElement: emptyElement,
  addEventListener(){}, querySelectorAll(){ return []; },
};
const sandbox = {
  console, document, SERVER: 'http://st.test',
  S: { tab: 'stats', sym: '2330', mkt: 'TW', wl: [] },
  setTab(){}, renderWl(){}, renderRpanel(){},
  AbortController, Date, Math, JSON, Promise, Set, Map,
  setTimeout(fn, ms) { if (ms >= 12000) return 1; Promise.resolve().then(fn); return 2; },
  clearTimeout(){}, addEventListener(){}, matchMedia(){ return {matches:true}; },
  fetch: async url => {
    if (String(url).includes('/diagnostics/')) return response(200, {ok:true});
    if (String(url).includes('/etf-catalog')) {
      return response(200, {categories:[{key:'active',etfs:[{code:'00992A',name:'測試ETF',enabled:true}]}]});
    }
    if (String(url).includes('/etf-delta')) {
      const next = deltaQueue.shift();
      if (next instanceof Error) throw next;
      return next || response(500, {error:'fixture queue empty'});
    }
    return response(404, {});
  },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox, {filename:'etf_v3.js'});

function runTipEventRegression() {
  const byId = new Map();
  const docListeners = new Map();

  class Element {
    constructor(tag = 'div') {
      this.tagName = String(tag).toUpperCase();
      this.nodeType = 1;
      this.id = '';
      this.className = '';
      this.style = {};
      this.attributes = new Map();
      this.children = [];
      this.parentElement = null;
      this.offsetWidth = 360;
      this.offsetHeight = 120;
      this.listeners = new Map();
    }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
    appendChild(child) {
      child.parentElement = this;
      this.children.push(child);
      if (child.id) byId.set(child.id, child);
      return child;
    }
    addEventListener(type, fn) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(fn);
    }
    contains(node) {
      for (let current = node; current; current = current.parentElement) {
        if (current === this) return true;
      }
      return false;
    }
    closest(selector) {
      for (let current = this; current; current = current.parentElement) {
        if (selector === '.wlchip[data-mkt="TW"]'
            && current.className.split(/\s+/).includes('wlchip')
            && current.getAttribute('data-mkt') === 'TW') return current;
        if (selector === '[data-etf-flow-trigger]'
            && current.getAttribute('data-etf-flow-trigger') != null) return current;
        if (selector === '.eft-close'
            && current.className.split(/\s+/).includes('eft-close')) return current;
        if (selector === '.eft-item'
            && current.className.split(/\s+/).includes('eft-item')) return current;
      }
      return null;
    }
    querySelector(selector) {
      if (selector === '[data-etf-flow-trigger]') {
        return this.children.find(child => child.getAttribute('data-etf-flow-trigger') != null) || null;
      }
      return null;
    }
    getBoundingClientRect() { return {left:20, top:20, right:180, bottom:64, width:160, height:44}; }
  }

  const head = new Element('head');
  const body = new Element('body');
  const documentMock = {
    head, body,
    createElement: tag => new Element(tag),
    getElementById: id => byId.get(id) || null,
    addEventListener(type, fn) {
      if (!docListeners.has(type)) docListeners.set(type, []);
      docListeners.get(type).push(fn);
    },
  };
  const dispatch = (type, event) => {
    for (const listener of docListeners.get(type) || []) {
      listener(event);
      if (event.immediateStopped) break;
    }
  };
  const makeChip = sym => {
    const chip = new Element('div');
    chip.className = 'wlchip';
    chip.setAttribute('data-mkt', 'TW');
    chip.setAttribute('data-sym', sym);
    const badge = new Element('button');
    badge.setAttribute('data-etf-flow-trigger', '1');
    chip.appendChild(badge);
    body.appendChild(chip);
    return {chip, badge};
  };
  const windowListeners = new Map();
  const context = {
    console, document: documentMock,
    S: {wl:[]}, SERVER:'http://st.test', location:{origin:'http://st.test'},
    EtfFlow:{getStockFlow:sym => ({sym, available:false, freshness:'missing', freshnessDetail:{}})},
    innerWidth:1200, innerHeight:800,
    visualViewport:{offsetLeft:0, offsetTop:0, width:1200, height:800, addEventListener(){}},
    matchMedia: query => ({matches: query.includes('any-hover') || query.includes('any-pointer')}),
    addEventListener(type, fn) {
      if (!windowListeners.has(type)) windowListeners.set(type, []);
      windowListeners.get(type).push(fn);
    },
    setTimeout: fn => { fn(); return 1; }, clearTimeout(){},
    fetch: async () => ({ok:true}), Date, JSON, Math, Promise,
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(tipSource, context, {filename:'etf_flow_tip_v3.js'});

  const first = makeChip('2330');
  const second = makeChip('2303');
  context.EtfFlowTip.openForChip(first.chip, {interaction:'test'});
  const tip = documentMock.getElementById('etf-flow-tip');
  dispatch('pointerdown', {target:second.chip});
  const otherChipClosed = tip.style.display === 'none';

  context.EtfFlowTip.openForChip(first.chip, {interaction:'test'});
  let globalHotkeyCount = 0;
  documentMock.addEventListener('keydown', () => { globalHotkeyCount += 1; });
  const escapeEvent = {
    key:'Escape', defaultPrevented:false, immediateStopped:false,
    preventDefault(){ this.defaultPrevented = true; },
    stopImmediatePropagation(){ this.immediateStopped = true; },
    stopPropagation(){},
  };
  dispatch('keydown', escapeEvent);
  const escapeClosed = tip.style.display === 'none';
  const escapeConsumed = escapeEvent.defaultPrevented && escapeEvent.immediateStopped && globalHotkeyCount === 0;
  const keyEvent = key => ({
    key, defaultPrevented:false, immediateStopped:false,
    target:first.badge,
    preventDefault(){ this.defaultPrevented = true; },
    stopImmediatePropagation(){ this.immediateStopped = true; },
    stopPropagation(){},
  });
  context.EtfFlowTip.openForChip(first.chip, {interaction:'test'});
  const hotkeysBeforeKeyboard = globalHotkeyCount;
  const enterEvent = keyEvent('Enter');
  dispatch('keydown', enterEvent);
  const keyboardToggleClosed = tip.style.display === 'none';
  const spaceEvent = keyEvent(' ');
  dispatch('keydown', spaceEvent);
  const keyboardToggleOpened = tip.style.display === 'block';
  const keyboardConsumed = enterEvent.defaultPrevented && enterEvent.immediateStopped &&
    spaceEvent.defaultPrevented && spaceEvent.immediateStopped &&
    globalHotkeyCount === hotkeysBeforeKeyboard;
  return {
    otherChipClosed,
    escapeClosed,
    escapeConsumed,
    keyboardToggle: keyboardToggleClosed && keyboardToggleOpened,
    keyboardConsumed,
  };
}

async function main() {
  await Promise.resolve(); await Promise.resolve();
  ok(sandbox.EtfFlow.changeDirection({shares_delta:200, delta:-0.2}) === 1,
    'share increase overrides opposing weight decrease');
  ok(sandbox.EtfFlow.changeDirection({shares_delta:-200, delta:0.2}) === -1,
    'share decrease overrides opposing weight increase');
  ok(sandbox.EtfFlow.changeDirection({shares_delta:0, delta:0.2}) === 1,
    'weight is the fallback only when shares are unchanged');

  const first = {
    date:'2026-08-28', prev_date:'2026-08-27', meta:{history:{state:'ok'}},
    etfs:[{code:'00992A',name:'測試ETF',new:[],removed:[],changed:[{
      code:'2330',name:'台積電',shares_delta:200,delta:-0.2,
    }]}],
  };
  deltaQueue.push(response(200, first));
  await sandbox.etfV3FetchDelta();
  let flow = sandbox.EtfFlow.getStockFlow('2330');
  ok(flow.available && flow.incCount === 1 && flow.decCount === 0 && !flow.unchanged,
    'changed-only payload becomes a visible increase signal');
  ok(flow.chgSum === -0.2, 'position compatibility alias preserves weight delta');

  deltaQueue.push(response(503, {error:'upstream unavailable'}));
  deltaQueue.push(response(503, {error:'upstream unavailable'}));
  deltaQueue.push(response(503, {error:'upstream unavailable'}));
  await sandbox.etfV3FetchDelta();
  flow = sandbox.EtfFlow.getStockFlow('2330');
  ok(flow.available && flow.date === '2026-08-28', 'terminal 503 preserves last-good ETF data');
  ok(flow.freshness === 'stale' && !!flow.sourceError, 'failed refresh marks last-good data stale');

  const second = {...first, date:'2026-08-29', meta:{history:{state:'stale'}}, etfs:[]};
  deltaQueue.push(response(200, second));
  await sandbox.etfV3FetchDelta();
  flow = sandbox.EtfFlow.getStockFlow('2330');
  ok(flow.available && flow.unchanged && flow.freshness === 'stale',
    'fresh response distinguishes no-change from missing and keeps server freshness');

  const legacy = {...first, date:'2026-08-10', meta:undefined};
  deltaQueue.push(response(200, legacy));
  await sandbox.etfV3FetchDelta();
  flow = sandbox.EtfFlow.getStockFlow('2330');
  ok(flow.available && flow.freshness === 'stale'
      && flow.freshnessDetail.reason === 'history_contract_missing'
      && flow.freshnessDetail.legacyPayload === true,
    'legacy API payload without history health can never be labelled fresh');

  ok(/\.wlchip\[data-mkt="TW"\]/.test(tipSource) && !/\^\[\+-\]\\d\+\$/.test(tipSource),
    'tooltip targets the whole TW chip instead of only a tiny +/- badge');
  ok(/class="etf-flow-signs"/.test(html) && /data-etf-up=/.test(html) && /data-etf-down=/.test(html) &&
      /grid-template-rows:repeat\(2,8px\)/.test(tipSource) &&
      /\.etf-flow-sign\.up\{color:var\(--red\)\}/.test(tipSource) &&
      /\.etf-flow-sign\.down\{color:var\(--green\)\}/.test(tipSource),
    'compact ETF indicator stacks plus over minus and preserves Taiwan direction colors');
  ok(!/>ETF ↑/.test(html) && !/>ETF ↓/.test(html) &&
      /aria-label="\$\{w\.t\} ETF 動向：\$\{_text\}/.test(html),
    'variable ETF counts stay in accessible detail instead of widening the watchlist chip');
ok(/wl-menu-etf/.test(html) && /EtfFlowTip\.openForChip/.test(html),
  'mobile long-press menu exposes ETF movement');
ok(/class="eft-close"/.test(tipSource) && /pointerdown/.test(tipSource),
  'ETF tooltip has explicit and outside-tap close paths');
ok(/any-hover: hover/.test(tipSource) && /any-pointer: fine/.test(tipSource),
  'hybrid touch-and-mouse Windows devices retain whole-chip hover');
  ok(/history_contract_missing/.test(tipSource) && /不能視為最新資料/.test(tipSource),
    'legacy backend contract is explained instead of being presented as valid data');
  const interaction = runTipEventRegression();
  ok(interaction.otherChipClosed,
    'touching another TW chip closes the previous ETF tooltip');
  ok(interaction.escapeClosed && interaction.escapeConsumed,
    'Escape closes the visible tooltip without leaking into global hotkeys');
  ok(interaction.keyboardToggle,
    'Enter closes and Space opens the ETF tooltip with pointer-equivalent semantics');
  ok(interaction.keyboardConsumed,
    'ETF Enter/Space activation is consumed before global watchlist hotkeys');
  ok(/<\/html>\s*$/.test(html) && !/<\/html>[\s\S]+<script/i.test(html),
    'source HTML ends at closing html with no legacy owner afterward');
  process.stdout.write('ETF flow v3 selftest passed.\n');
}

main().catch(error => { console.error(error.stack || error); process.exit(1); });

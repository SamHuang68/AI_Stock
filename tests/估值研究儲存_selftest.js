#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const uiPath = path.join(root, 'src/ui/估值承接研究.js');
const uiSource = fs.readFileSync(uiPath, 'utf8');
const coreSource = fs.readFileSync(path.join(root, 'src/core/估值承接核心.js'), 'utf8');
const marker = 'window.ValuationResearchUI = { open, close };';
assert.equal(uiSource.split(marker).length, 2, '須能唯一定位測試注入點');
const KEY = 'st.valuation-research.v1';
const NOW = Date.parse('2026-09-10T12:00:00Z');
class ResearchDate extends Date {
  constructor(...args) { super(...(args.length ? args : [NOW])); }
  static now() { return NOW; }
}
const clone = value => JSON.parse(JSON.stringify(value));
const baseProfile = { category: 'general', epsLow: '10', epsHigh: '10', epsPeriod: '完整年度', reason: '持續獲利假設',
  peLow: '20', peHigh: '30', entryPrice: '', exitPrice: '', budget: '', tranches: [],
  buyFeePct: '0.1425', sellFeePct: '0.1425', sellTaxPct: '0.3', minFee: '20' };
const baseRow = { sym: '2330', close: 250, per: 25,
  research: { priceAsOf: '2026-09-09', valuationDate: '2026-09-09', priceFresh: true, scopeEligible: true } };

function harness(storage = new Map()) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { value: '', textContent: '', innerHTML: '', children: [],
      open: false, isConnected: true, focus() {}, setAttribute() {},
      showModal() { this.open = true; }, close() { this.open = false; } });
    return elements.get(id);
  };
  let writesFail = false;
  const sandbox = {
    Date: ResearchDate, Intl, console, window: {}, AbortController, setTimeout, clearTimeout,
    fetch: async () => ({ ok: true, json: async () => ({ row: clone(baseRow) }) }),
    document: { getElementById: element, activeElement: element('原焦點') },
    localStorage: {
      getItem: key => storage.has(key) ? storage.get(key) : null,
      setItem(key, value) { if (writesFail) throw new Error('模擬儲存空間不足'); storage.set(key, String(value)); },
      removeItem: key => storage.delete(key)
    },
    renderInputs(profile) {
      sandbox.renderedProfile = clone(profile);
      Object.keys(profile).filter(key => key !== 'tranches').forEach(key => { element('vr-' + key).value = String(profile[key] == null ? '' : profile[key]); });
      element('vr-tranches').children = (profile.tranches || []).map(row => ({
        querySelector: selector => ({ value: String((selector === '.vr-price' ? row.price : row.shares) ?? '') })
      }));
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(coreSource, sandbox, { filename: '估值承接核心.js' });
  sandbox.window.ValuationResearch = sandbox.ValuationResearch;
  // 只替代版面繪製與網路刷新；被測的輸入、草稿、版本與持久化函式保持原文。
  const injection = `
    window.__storageTest = { appendSnapshot, persist, changed, save, open, close, fmt, percent, observation,
      renderFacts: facts, renderVerdict: recalculate, refresh,
      setActive(value) { active = value; }, getActive() { return active; },
      prepareRendering() {
        style = function () {};
        renderForm = function (profile) { renderInputs(profile); };
        facts = function () {}; renderHistory = function () {}; refresh = function () {};
        recalculate = function () { return evaluate(); };
      }
    };
    ${marker}`;
  vm.runInContext(uiSource.replace(marker, injection), sandbox, { filename: uiPath });
  const api = sandbox.window.__storageTest;
  api.prepareRendering();
  return { api, element, sandbox, storage, failWrites(value) { writesFail = value; },
    setStore(value) { storage.set(KEY, JSON.stringify(value)); },
    store() { return JSON.parse(storage.get(KEY) || '{}'); },
    activate({ saved = { revision: '版本一', profile: clone(baseProfile), snapshots: [] }, row = clone(baseRow), settings = { peMax: 30, excludeIp: true }, symbol = '2330' } = {}) {
      api.setActive({ symbol, saved, row, settings, dirty: false }); return saved;
    },
    result() { const state = api.getActive(); return sandbox.ValuationResearch.evaluate(api.observation(), state.saved.profile || baseProfile, state.settings); }
  };
}
let count = 0;
function test(name, run) { run(); count++; console.log('通過：' + name); }

test('調整研究上限只記錄假設更新，不形成市場趨勢', () => {
  const h = harness(), saved = h.activate({ row: { ...clone(baseRow), per: 35 } });
  h.api.appendSnapshot(saved, h.result());
  assert.equal(saved.snapshots[0].scope, 'pe_above');
  h.api.getActive().settings.peMax = 40;
  h.api.appendSnapshot(saved, h.result());
  assert.equal(saved.snapshots[1].scope, 'in_scope');
  assert.deepEqual(clone(saved.snapshots[1].events), ['估值假設已更新']);
});
test('切換 IP 排除設定也建立新的比較基準', () => {
  const h = harness(), profile = { ...baseProfile, category: 'ip' };
  const saved = h.activate({ symbol: '3529', row: { ...clone(baseRow), sym: '3529' }, saved: { revision: '版本一', profile, snapshots: [] } });
  h.api.appendSnapshot(saved, h.result()); h.api.getActive().settings.excludeIp = false;
  h.api.appendSnapshot(saved, h.result());
  assert.deepEqual(clone(saved.snapshots[1].events), ['估值假設已更新']);
});
test('相同觀察去重，真正的新交易日價格變化仍可記錄', () => {
  const h = harness(), saved = h.activate();
  h.api.appendSnapshot(saved, h.result()); h.api.appendSnapshot(saved, h.result());
  assert.equal(saved.snapshots.length, 1);
  h.api.getActive().row.close = 190; h.api.getActive().row.research.priceAsOf = '2026-09-10';
  h.api.appendSnapshot(saved, h.result());
  assert.equal(saved.snapshots.length, 2);
  assert.ok(saved.snapshots[1].events.some(text => text.includes('已達承接價')));
});
test('舊分頁無法覆蓋另一分頁的新版本', () => {
  const storage = new Map(), oldTab = harness(storage), newTab = harness(storage);
  const old = { revision: '版本一', profile: clone(baseProfile), snapshots: [] };
  oldTab.activate({ saved: clone(old) }); newTab.activate({ saved: clone(old) });
  oldTab.setStore({ '2330': clone(old) });
  const latest = { ...clone(old), revision: '版本二', profile: { ...baseProfile, epsLow: '20', epsHigh: '20' } };
  assert.equal(newTab.api.persist(latest), true);
  const before = oldTab.storage.get(KEY);
  assert.equal(oldTab.api.persist({ ...old, snapshots: [{ price: 250 }] }), false);
  assert.equal(oldTab.storage.get(KEY), before);
  assert.match(oldTab.element('vr-save-state').textContent, /另一分頁/);
});
test('正常更新只替換目標股票，其他研究資料保留', () => {
  const h = harness(), saved = h.activate();
  h.setStore({ '2330': clone(saved), '2317': { revision: '另一股票', profile: { eps: '5' } } });
  assert.equal(h.api.persist({ ...saved, revision: '版本二' }), true);
  assert.deepEqual(h.store()['2317'], { revision: '另一股票', profile: { eps: '5' } });
});
test('準備快照不會先改寫已載入的歷史陣列', () => {
  const h = harness(), activeSaved = h.activate(), candidate = { ...activeSaved };
  h.api.appendSnapshot(candidate, h.result());
  assert.equal(candidate.snapshots.length, 1); assert.equal(activeSaved.snapshots.length, 0);
});
test('未完成批次可保存草稿，關閉再開恢復且不新增正式快照', () => {
  const h = harness(), saved = { revision: '版本一', profile: clone(baseProfile), snapshots: [] };
  h.setStore({ '2330': saved });
  h.api.open('2330', clone(baseRow));
  h.sandbox.renderInputs({ ...baseProfile, epsLow: '12', epsHigh: '12', reason: '尚在整理的估值理由', tranches: [{ price: '90', shares: '' }] });
  h.api.changed();
  assert.equal(h.store()['2330'].profile.epsLow, '10'); assert.equal(h.store()['2330'].snapshots.length, 0);
  h.api.close(); h.api.open('2330', clone(baseRow));
  assert.equal(h.sandbox.renderedProfile.epsLow, '12');
  assert.deepEqual(h.sandbox.renderedProfile.tranches, [{ price: '90', shares: '' }]);
  assert.equal(h.api.getActive().dirty, true);
  assert.match(h.element('vr-save-state').textContent, /已還原草稿/);
  assert.equal(h.store()['2330'].snapshots.length, 0);
});
test('較舊版本草稿不覆蓋另一分頁的新假設', () => {
  const h = harness();
  h.setStore({ '2330': { revision: '版本二', profile: { ...baseProfile, epsLow: '20', epsHigh: '20' }, snapshots: [] } });
  h.storage.set(KEY + '.draft.2330', JSON.stringify({ baseRevision: '版本一', profile: { ...baseProfile, epsLow: '12', epsHigh: '12' } }));
  h.api.open('2330', clone(baseRow));
  assert.equal(h.sandbox.renderedProfile.epsLow, '20'); assert.equal(h.api.getActive().dirty, false);
});
test('正式儲存成功才清除草稿，儲存失敗時保留草稿', () => {
  const h = harness();
  h.api.open('2330', clone(baseRow)); h.sandbox.renderInputs({ ...baseProfile, epsLow: '12', epsHigh: '12' }); h.api.changed();
  const draftKey = KEY + '.draft.2330', draftBefore = h.storage.get(draftKey);
  h.failWrites(true); h.api.save();
  assert.equal(h.storage.get(draftKey), draftBefore); assert.equal(h.api.getActive().dirty, true);
  h.failWrites(false); h.api.save();
  assert.equal(h.storage.has(draftKey), false); assert.equal(h.store()['2330'].profile.epsLow, '12');
  assert.equal(h.api.getActive().dirty, false);
});
test('未來、格式錯誤或不存在的行情日期不進歷史', () => {
  ['2026-09-11', '2026-02-30', '2026-13-01', '2026-00-01', '2026-09-00', '2026/09/09', '', null].forEach(priceAsOf => {
    const h = harness(), row = clone(baseRow); row.research.priceAsOf = priceAsOf;
    const saved = h.activate({ row }); h.api.appendSnapshot(saved, h.result());
    assert.equal(saved.snapshots.length, 0, '不應收錄行情日期：' + priceAsOf);
  });
});
test('未來、格式錯誤或不存在的估值日期不進歷史', () => {
  ['2026-09-11', '2026-02-30', '2026-13-01', '2026-00-01', '2026-09-00', '2026/09/09'].forEach(valuationDate => {
    const h = harness(), row = clone(baseRow); row.research.valuationDate = valuationDate;
    const saved = h.activate({ row }); h.api.appendSnapshot(saved, h.result());
    assert.equal(saved.snapshots.length, 0, '不應收錄估值日期：' + valuationDate);
  });
});
test('行情日或估值資料日倒退均保留原比較基準', () => {
  ['priceAsOf', 'valuationDate'].forEach(key => {
    const h = harness(), saved = h.activate(); h.api.appendSnapshot(saved, h.result());
    h.api.getActive().row.close = 190; h.api.getActive().row.research[key] = '2026-09-08';
    h.api.appendSnapshot(saved, h.result()); assert.equal(saved.snapshots.length, 1);
  });
});
test('缺值與非正價格不產生零元快照，畫面保留未提供', () => {
  [null, undefined, '', 0, -1, NaN, Infinity].forEach(close => {
    const h = harness(), saved = h.activate({ row: { ...clone(baseRow), close } });
    h.api.appendSnapshot(saved, h.result()); assert.equal(saved.snapshots.length, 0);
  });
  const h = harness();
  [null, undefined, '', NaN, Infinity].forEach(value => { assert.equal(h.api.fmt(value), '未提供'); assert.equal(h.api.percent(value), '未提供'); });
  assert.equal(h.api.fmt(0), '0'); assert.equal(h.api.percent(0), '0%');
  h.activate({ row: null }); assert.equal(h.result().scope, 'source_unknown'); assert.equal(h.result().hypothesisPe, null);
});
test('缺資料頁面保留原因、來源、零值與安全文字', () => {
  const h = harness();
  h.api.open('2330', { sym: '2330', close: null, per: null, revYoy: 0,
    research: { dataStatus: 'partial', missing: ['未保存官方來源', '<img onerror=攻擊>'] } });
  h.api.renderFacts(); h.api.renderVerdict();
  assert.match(h.element('vr-facts').innerHTML, /未保存官方來源/);
  assert.match(h.element('vr-facts').innerHTML, /0%/);
  assert.match(h.element('vr-facts').innerHTML, /&lt;img/);
  assert.doesNotMatch(h.element('vr-facts').innerHTML, /<img/);
  assert.match(h.element('vr-verdict').innerHTML, /官方來源或日期/);
  assert.match(h.element('vr-position').innerHTML, /未提供/);
});
test('過期或未通過來源門檻的資料不寫入市場觀察', () => {
  for (const missing of [{ priceFresh: false }, { scopeEligible: false }]) {
    const h = harness(), row = clone(baseRow); Object.assign(row.research, missing);
    const saved = h.activate({ row }); h.api.appendSnapshot(saved, h.result());
    assert.equal(saved.snapshots.length, 0);
  }
});
test('價格核對收據與成交量衝突分開呈現且來源文字不注入 HTML', () => {
  const h = harness();
  h.api.open('2330', { sym: '2330', close: 101, research: {
    priceAsOf: '2026-10-02', priceVerified: true, priceVerification: '官方收據逐欄核對',
    volumeConflict: true, volumeShares: null, rawPriceSource: null,
    sourceReceipts: [{ source: 'TWSE', parserVersion: 'twse-stock-day-v1',
      retrievedAt: '2026-10-03T01:25:00Z', writtenAt: '2026-10-03T09:00:00Z',
      url: 'https://www.twse.com.tw/<img>', sourceHash: 'abc', notes: ['含零股、盤後定價、鉅額交易', '<script>'] }]
  } });
  h.api.renderFacts();
  const html = h.element('vr-facts').innerHTML;
  assert.match(html, /官方收據逐欄核對/);
  assert.match(html, /官方量與原始量不一致，研究量留空待核對/);
  assert.match(html, /未記錄；不以核對來源代替/);
  assert.match(html, /2026-10-03T01:25:00Z/);
  assert.match(html, /2026-10-03T09:00:00Z/);
  assert.match(html, /含零股、盤後定價、鉅額交易/);
  assert.doesNotMatch(html, /<img>|<script>/);
});
test('讀者暫時計算不讀寫擁有者假設、草稿或歷史', () => {
  const h = harness();
  h.setStore({ '2330': { revision: '私人版本', profile: { ...baseProfile, reason: '私人理由' }, snapshots: [] } });
  h.storage.set(KEY + '.draft.2330', JSON.stringify({ profile: { ...baseProfile, reason: '私人草稿' }, baseRevision: '私人版本' }));
  const original = Array.from(h.storage.entries()), access = [];
  const storageApi = h.sandbox.localStorage;
  h.sandbox.localStorage = Object.fromEntries(Object.entries(storageApi).map(([key, fn]) => [key, (...args) => { access.push(key); return fn(...args); }]));
  h.sandbox.window.ST_PRIVATE_WEB_PROFILE = { role: 'reader' };
  h.api.open('2330', clone(baseRow));
  assert.equal(h.sandbox.renderedProfile.reason, '');
  assert.equal(h.element('vr-save').disabled, true);
  h.sandbox.renderInputs(baseProfile); h.api.changed(); h.api.save();
  assert.equal(h.api.persist({ profile: baseProfile }), false);
  const candidate = { snapshots: [] }; h.api.appendSnapshot(candidate, h.result());
  assert.equal(candidate.snapshots.length, 0); h.api.close();
  assert.deepEqual(access, []); assert.deepEqual(Array.from(h.storage.entries()), original);
  h.sandbox.window.ST_PRIVATE_WEB_PROFILE = { role: 'owner' }; h.api.open('2330', clone(baseRow));
  assert.equal(h.sandbox.renderedProfile.reason, '私人草稿');
});
test('開啟後權限降低清除畫面私人副本，但保留原儲存資料', () => {
  const h = harness();
  h.setStore({ '2330': { revision: '私人版本', profile: { ...baseProfile, reason: '私人理由' }, snapshots: [] } });
  h.api.open('2330', clone(baseRow));
  const before = Array.from(h.storage.entries()), access = [];
  const storageApi = h.sandbox.localStorage;
  h.sandbox.localStorage = Object.fromEntries(Object.entries(storageApi).map(([key, fn]) => [key, (...args) => { access.push(key); return fn(...args); }]));
  h.sandbox.window.ST_PRIVATE_WEB_PROFILE = { role: 'reader' }; h.api.changed(); h.api.save();
  assert.equal(h.sandbox.renderedProfile.reason, '');
  assert.deepEqual(clone(h.api.getActive().saved), {});
  assert.deepEqual(access, []); assert.deepEqual(Array.from(h.storage.entries()), before);
});
(async () => {
  const query = harness();
  for (const excludeIp of [true, false]) {
    query.api.open('2330', null, { peMax: 40, excludeIp });
    let requested;
    query.sandbox.fetch = async url => { requested = new URL(url, 'https://st-offline.test'); return { ok: true, json: async () => ({ row: clone(baseRow) }) }; };
    await query.api.refresh();
    assert.equal(requested.pathname, '/valuation-research/2330');
    assert.equal(requested.searchParams.get('peMax'), '40');
    assert.equal(requested.searchParams.get('excludeIp'), String(excludeIp));
  }
  count++; console.log('通過：估值刷新採用 HTTP 契約的 true／false，並保留研究上限');
  const reader = harness(), accesses = [];
  reader.sandbox.window.ST_PRIVATE_WEB_PROFILE = { role: 'reader' };
  reader.sandbox.localStorage = { getItem() { accesses.push('讀'); }, setItem() { accesses.push('寫'); }, removeItem() { accesses.push('刪'); } };
  reader.api.open('2330', clone(baseRow)); await reader.api.refresh(); reader.api.close();
  assert.deepEqual(accesses, []); count++;
  console.log('通過：讀者非同步行情刷新不存取私人儲存');
  const h = harness(); h.api.open('2330', null);
  h.sandbox.fetch = async () => ({ ok: true, json: async () => ({ row: { sym: '2330', close: null,
    research: { dataStatus: 'partial', missing: ['官方快取尚缺'] } } }) });
  await h.api.refresh();
  assert.match(h.element('vr-load-state').textContent, /資料不足/);
  assert.equal(h.api.getActive().row.close, null); count++;
  console.log('通過：刷新缺資料結果仍可呈現限制');
  h.sandbox.fetch = async () => { throw new Error('離線'); };
  await h.api.refresh();
  assert.match(h.element('vr-load-state').textContent, /取得資料失敗/); count++;
  console.log('通過：刷新失敗保留輸入與明確錯誤');
  const pending = [];
  h.sandbox.fetch = () => new Promise(resolve => pending.push(resolve));
  const older = h.api.refresh(); h.api.open('2317', null); const newer = h.api.refresh();
  pending[1]({ ok: true, json: async () => ({ row: { sym: '2317', close: 200, research: { dataStatus: 'partial' } } }) });
  await newer;
  pending[0]({ ok: true, json: async () => ({ row: clone(baseRow) }) }); await older;
  assert.equal(h.api.getActive().row.sym, '2317'); count++;
  console.log('通過：舊股票的延遲回應不覆蓋新研究視窗');
  console.log('估值研究儲存與頁面：' + count + ' 組測試全部通過。');
})().catch(error => { console.error(error); process.exitCode = 1; });

test('官方研究量與原始數值並列，差異不冒充來源或單位', () => {
  const h = harness();
  const volume = { status: 'selected', value: 15792206, rawValue: 15071494, numericDifference: 720712,
    source: 'TWSE', asOf: '2026-10-02', unit: '股', rawSource: null, rawUnit: null };
  h.api.open('2330', { sym: '2330', research: { volumeShares: 15792206, volumeConflict: true,
    officialResearchVolume: volume, volumeDifferences: [volume], volumeBasis: 'official-receipt' } });
  h.api.renderFacts();
  const html = h.element('vr-facts').innerHTML;
  for (const value of ['15,792,206', '15,071,494', '720,712', 'TWSE／2026-10-02',
    '研究採完整官方股數；原始量差異保留', '單位未記錄', '查看研究期間的成交量差異']) assert.ok(html.includes(value), value);
  assert.doesNotMatch(html, /留空待核對/);
});

'use strict';

// 使用完整正式 store 與 Pulse 模組，驗證身分、效期視圖及同步狀態的跨模組接線。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const clone = value => JSON.parse(JSON.stringify(value));
const tick = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

function harness() {
  const nodes = new Map(), requests = [];
  nodes.set('pl-head-meta', { innerHTML: '', title: '', hidden: true });
  nodes.set('pl-head-jobs', {});
  const state = {
    console, Date, Math, Promise,
    document: { getElementById: id => nodes.get(id) || null },
    location: { origin: 'http://test.invalid' },
    localStorage: { getItem() { return null; }, setItem() {} },
    addEventListener() {}, dispatchEvent() {}, setTimeout() { return 1; }, clearTimeout() {},
    CustomEvent: function (type, init) { this.type = type; this.detail = init.detail; },
    fetch(url) { return new Promise((resolve, reject) => requests.push({ url, resolve, reject })); }
  };
  state.window = state;
  vm.createContext(state);
  vm.runInContext(fs.readFileSync(path.join(root, 'src/core/decision_data_v5.js'), 'utf8'), state);
  const source = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
  const marker = '  window.PulseV5 = {';
  assert.equal(source.split(marker).length, 2);
  vm.runInContext(source.replace(marker, 'window.renderTestHead = renderHeadMeta;\n' + marker), state);
  return {
    state, requests,
    head(pulse) { state.renderTestHead({ pulse }); return nodes.get('pl-head-meta').innerHTML; },
    html() { return nodes.get('pl-head-meta').innerHTML; },
    async status(value, request = requests.at(-1)) {
      request.resolve({ ok: true, json: async () => value }); await tick();
      return nodes.get('pl-head-meta').innerHTML;
    }
  };
}

function context() {
  return {
    contractVersion: 1, snapshotId: 'dc-input-a', revision: 7, inputHash: 'input-a',
    rulesDigest: 'rules-a', publicationStatus: 'accepted', persistence: 'committed',
    viewScope: 'market', viewState: 'current', asOf: '2026-09-20T01:00:00Z',
    regime: { id: 'NEUTRAL', label: '中性', score: 50, confidence: 0.5, ruleId: 'neutral' },
    actionEnvelope: { posture: 'HOLD', allowed: ['HOLD'], restricted: [] },
    keyLevels: { levels: { r1: 26000, pivot: 25000, s1: 24000 } },
    confirmation: ['等待確認'], invalidation: ['失守支撐'],
    dataQuality: { completeness: 1, freshness: 1, scopeConsistency: true, staleFields: [] }
  };
}

function pulse(summary) {
  return {
    updatedAt: '2026-09-20T01:00:00Z', dataCompleteness: 100, decisionSummary: clone(summary),
    marketSnapshot: {
      contractVersion: 2, generatedAt: '2026-09-20T01:00:00Z', marketAsOf: '2026-09-20T00:59:00Z',
      quotes: { '^TWII': { price: 25000 } },
      freshness: { freshness: 'fresh', worstAsOf: '2026-09-20T00:59:00Z' }
    }
  };
}

function summary(h, value = context()) {
  return clone(h.state.DecisionData.publish(value).summary);
}

async function checkIdentityAndViews() {
  const h = harness(), full = context(), marketSummary = summary(h, full);
  for (const key of ['snapshotId', 'revision', 'inputHash', 'rulesDigest', 'publicationStatus', 'persistence', 'viewScope', 'viewState']) {
    assert.equal(marketSummary[key], full[key], '正式 store 不可遺失 ' + key);
  }
  let html = h.head(pulse(marketSummary));
  assert.match(html, /快照：<b>dc-input-a<\/b>/);
  assert.match(html, /修訂：<b>7<\/b>/);
  assert.match(html, /契約版本：<b>決策 1／行情 2/);
  assert.match(html, /儲存狀態：<b>已持久儲存/);
  assert.match(html, /畫面識別：<b>[0-9a-f]+/);
  assert.match(html, /摘要／全文快照與核對內容一致/);

  const changed = clone(marketSummary);
  changed.snapshotId = 'dc-input-b'; changed.inputHash = 'input-b'; changed.revision = 8;
  const later = pulse(changed); later.marketSnapshot.quotes['^TWII'].price = 26000;
  html = h.head(later);
  assert.match(html, /快照：<b>dc-input-b/);
  assert.match(html, /修訂：<b>8/);
  assert.match(html, /尚未核對（不同快照）/);
  assert.match(html, /效期：<b>有效/);

  const unrelated = context(); unrelated.snapshotId = 'dc-stale'; unrelated.dataQuality.freshness = 0.1;
  h.state.DecisionData.publish(unrelated);
  html = h.head(pulse(marketSummary));
  assert.match(html, /快照：<b>dc-input-a/);
  assert.match(html, /效期：<b>有效/, '其他來源的舊摘要不可改寫目前 Pulse 效期');
  assert.match(html, /尚未核對（不同快照）/);

  const sameIdDifferentRegime = clone(full); sameIdDifferentRegime.regime.id = 'DEFENSIVE';
  h.state.DecisionData.publish(sameIdDifferentRegime);
  assert.match(h.head(pulse(marketSummary)), /摘要／全文核對內容不同/);
  const sameIdDifferentAction = clone(full); sameIdDifferentAction.actionEnvelope.posture = 'DEFENSIVE';
  h.state.DecisionData.publish(sameIdDifferentAction);
  assert.match(h.head(pulse(marketSummary)), /摘要／全文核對內容不同/);
  const embedded = pulse(marketSummary); embedded.decision = clone(full);
  assert.match(h.head(embedded), /摘要／全文快照與核對內容一致/,
    '同一 Pulse 帶全文時優先核對它，不得使用其他來源的全文');
  const expired = clone(full); expired.viewState = 'source_expired';
  h.state.DecisionData.publish(expired);
  assert.match(h.head(pulse(marketSummary)), /效期視圖不同，尚未核對/);
  const differentRevision = clone(full); differentRevision.revision = 8;
  h.state.DecisionData.publish(differentRevision);
  assert.match(h.head(pulse(marketSummary)), /快照識別不一致/);
  const differentRules = clone(full); differentRules.rulesDigest = 'rules-b';
  h.state.DecisionData.publish(differentRules);
  assert.match(h.head(pulse(marketSummary)), /快照識別不一致/);
  const missingHash = clone(full); delete missingHash.inputHash;
  h.state.DecisionData.publish(missingHash);
  assert.match(h.head(pulse(marketSummary)), /輸入或規則識別未提供/);
  const unconfirmed = clone(full); unconfirmed.persistence = null;
  h.state.DecisionData.publish(unconfirmed);
  assert.match(h.head(pulse(marketSummary)), /持久儲存未確認/);

  const personal = clone(full);
  delete personal.snapshotId; delete personal.revision;
  Object.assign(personal, { parentSnapshotId: full.snapshotId, viewScope: 'personal',
    publicationStatus: 'derived', persistence: 'ephemeral' });
  const personalSummary = summary(h, personal);
  assert.equal(personalSummary.parentSnapshotId, full.snapshotId);
  assert.equal(personalSummary.snapshotId, null); assert.equal(personalSummary.revision, null);
  html = h.head(pulse(marketSummary));
  assert.match(html, /快照：<b>dc-input-a/);
  assert.match(html, /尚未核對（個人化衍生視圖）/);
  html = h.head(pulse(personalSummary));
  assert.match(html, /快照：<b>未提供/); assert.match(html, /修訂：<b>未提供/);
  assert.match(html, /儲存狀態：<b>未持久儲存（個人化衍生）/);
  assert.match(html, /衍生來源快照：<b>dc-input-a/);
  assert.match(html, /發布狀態：<b>個人化衍生/);
  assert.doesNotMatch(html, /已持久儲存/);

  const legacy = harness();
  html = legacy.head(pulse({ contractVersion: 9, regime: { id: 'NEUTRAL' }, dataQuality: { scopeConsistency: true } }));
  assert.match(html, /市場範圍：<b>一致/);
  assert.match(html, /僅有摘要，全文未提供/);
  assert.match(html, /快照：<b>未提供/); assert.match(html, /修訂：<b>未提供/);
  assert.match(html, /契約版本：<b>決策 9／行情 2/);
  assert.doesNotMatch(html, /摘要／全文.*一致/);
  console.log('通過：正規識別投影、跨來源隔離、個人化衍生、內容與效期視圖核對及舊契約降級');
}

async function checkHistorySync() {
  const h = harness(), data = pulse(summary(h));
  h.head(data);
  let html = await h.status({ ok: true, running: false, lastOk: '2026-09-19T09:00:00', lastError: null });
  assert.match(html, /歷史資料同步：<b>已完成；最後成功 2026-09-19T09:00:00/);
  assert.match(html, /查看歷史資料同步/);
  h.head(data);
  html = await h.status({ ok: true, running: false, lastOk: '2026-09-19T09:00:00', lastError: '最新同步失敗 <img src=x>' });
  assert.match(html, /歷史資料同步：<b>失敗：最新同步失敗/);
  assert.match(html, /最後成功 2026-09-19T09:00:00/);
  assert(html.includes('&lt;img src=x&gt;')); assert(!html.includes('<img src=x>'));
  assert.doesNotMatch(html, /歷史資料同步：<b>已完成/);
  h.head(data);
  html = await h.status(null);
  assert.match(html, /查詢失敗；最後成功 2026-09-19T09:00:00/);

  h.head(data); const old = h.requests.at(-1);
  h.head(data);
  await h.status({ ok: true, running: false, lastOk: '2026-09-20T09:00:00', lastError: '目前失敗' });
  html = await h.status({ ok: true, running: false, lastOk: '2026-09-19T09:00:00' }, old);
  assert.match(html, /失敗：目前失敗；最後成功 2026-09-20T09:00:00/);
  h.head(data);
  html = await h.status({ ok: true, running: true, lastOk: '2026-09-20T09:00:00' });
  assert.match(html, /歷史資料同步：<b>進行中；最後成功/);
  h.head(data);
  html = await h.status({ ok: true, running: false, lastResult: { ok: false, error: '結果失敗' }, lastOk: '2026-09-20T09:00:00' });
  assert.match(html, /失敗：結果失敗；最後成功/);
  console.log('通過：歷史同步失敗優先、保留最後成功、HTTP 缺值、錯誤轉義及舊回應拒收');
}

(async () => {
  await checkIdentityAndViews();
  await checkHistorySync();
  console.log('決策快照呈現行為測試全部通過。');
})().catch(error => { console.error(error); process.exitCode = 1; });

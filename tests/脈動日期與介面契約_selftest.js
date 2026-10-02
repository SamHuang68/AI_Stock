'use strict';
// 實際模組的來源日期、取消、純讀焦點、持久快照及 AI 完成契約。
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.resolve(__dirname, '..');
const nodes = new Map(), requests = [], timers = new Map();
let timerId = 0;
function node() {
  return { textContent: '', innerHTML: '', style: {}, hidden: false, className: '', value: '',
    classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll() { return []; },
    querySelector() { return null; }, setAttribute() {}, getAttribute() { return null; } };
}
const scope = {
  console, Date, Intl, Math, Promise, AbortController,
  document: { readyState: 'loading', getElementById: id => nodes.get(id) || null,
    querySelectorAll: () => [], querySelector: () => null, addEventListener() {},
    createElement: node, head: { appendChild(el) { nodes.set(el.id, el); } } },
  localStorage: { getItem: () => null }, location: { hash: '' }, addEventListener() {},
  setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
  clearTimeout(id) { timers.delete(id); }, setInterval() { return 1; }, clearInterval() {},
  fetch(url, options) { return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })); },
};
scope.window = scope;
const source = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
vm.runInNewContext(source.replace('  window.PulseV5 = {', `
  window.fixture = { bindStockHealth:bindStockHealth, loadBeginnerFocus:loadBeginnerFocus,
    renderHeadMeta:renderHeadMeta, renderStrip:renderStrip, runAiSummary:runAiSummary,
    setMacro:function(value){_lastMacro=value;}, aiBusy:function(){return aiSummaryInFlight;},
    setPack:function(value){lastPack=value;}, readRefresh:function(){return refresh(false);} };
  window.PulseV5 = {`), scope);
const P = scope.PulseV5, T = scope.fixture;
const flush = () => new Promise(resolve => setImmediate(resolve));
function reply(request, data) { request.resolve({ ok: true, status: 200, json: async () => data }); }
function quote(extra = {}) {
  return { ok:true, code:'2330', price:102, prevClose:100, tradeDate:'2026-09-25',
    asOf:'2026-09-25T13:30:00+08:00', source:'官方測試來源', priceRealtime:false, ...extra };
}
const model = { twQuote:{tradeDate:'2026-09-25',changePct:1} };
assert.equal(requests.length, 0, '初始化不啟動網路要求');
assert.equal(P.stockHealthAssessment(quote(), model).cls, 'strong');
assert.match(P.stockHealthAssessment(quote(), model).body, /1\.00 個百分點/);
assert.match(P.stockHealthAssessment(quote(), { twQuote:{tradeDate:'2026-09-24',changePct:-9} }).body, /缺少相同日期與期間/);
assert.equal(P.stockHealthAssessment(quote({price:false}), model), null);
assert.equal(P.stockHealthAssessment(quote({prevClose:0}), model), null);
assert.equal(P.stockHealthAssessment(quote({asOf:'2026-09-24T13:30:00+08:00'}), model), null);
assert.equal(P.stockHealthAssessment(quote({tradeDate:'2099-09-25',asOf:'2099-09-25T13:30:00+08:00'}), model), null);
assert.equal(P.stockHealthAssessment(quote({tradeDate:'2026-02-30',asOf:null}), model), null);
assert.match(P.stockHealthAssessment(quote(), model).title, /歷史回顧/);
const history = P.stockHealthHistoryQuote([{time:'2026-09-24',close:100},{time:'2026-09-25',close:101}], '00631L', '測試日線');
assert.equal(history.previousDate, '2026-09-24');
assert.equal(history.price,101);
assert.equal(P.stockHealthHistoryQuote([{time:'2026-09-24',close:100},{time:'2026-09-25',close:101},{time:'2026-09-25',close:102}], '2330', '測試日線'), null);
assert.match(P.stockHealthAssessment({...history,benchmark:{tradeDate:'2026-09-25',previousDate:'2026-09-23',changePct:0}}, {}).body, /缺少相同日期與期間/);
const summary = { snapshotId:'持久快照-1',revision:2,viewState:'saved',inputHash:'a',rulesDigest:'b',persistence:'committed' };
assert.match(P.decisionSnapshotComparison(summary, null), /全文未提供/);
assert.match(P.decisionSnapshotComparison(summary, {...summary,snapshotId:'其他快照'}), /不同快照/);
assert.match(P.decisionSnapshotComparison(summary, {...summary}), /核對內容一致/);
assert.match(P.decisionSnapshotComparison(summary, {...summary,revision:3}), /不一致/);
const chips = P.renderBeginnerSignalStrip({strip:{t00Trend:{ma5:100,n:4},limitUp:0,limitDown:0}},
  {riskScore:0,riskLabel:'低風險',riskFactors:[],positiveFactors:[],pillars:{marginRatio:0,medianPE:0},extras:{nhnl:{newHighs:0,newLows:0,sampleN:10}}});
assert.match(chips, /樣本未滿 5 日/); assert.match(chips, /漲 0 · 跌 0/);
assert.match(chips, /高 0 · 低 0/); assert.match(chips, /尚無焦點快取/);
assert.doesNotMatch(chips, /undefined|NaN|勝率/);
assert.match(T.renderStrip({strip:{}},{txf:{}}), /觀察期間未提供/);
assert.match(T.renderStrip({strip:{txfTrend:{observationPeriod:{start:'2026-09-01',end:'2026-09-25'}}}},{txf:{}}), /2026-09-01 → 2026-09-25/);

(async () => {
  nodes.set('pl-head-meta',node());
  T.renderHeadMeta({pulse:{updatedAt:'2026-09-29T12:00:00+08:00',decisionSummary:summary}});
  assert.match(nodes.get('pl-head-meta').innerHTML,/快照：<b>持久快照-1/);
  assert.match(nodes.get('pl-head-meta').innerHTML,/行情來源時間：<b>—/);
  reply(requests.at(-1), {ok:true,running:false}); await flush();
  vm.runInNewContext(fs.readFileSync(path.join(root,'src/core/market_freshness_v5.js'),'utf8'),scope);
  T.renderHeadMeta({pulse:{marketSnapshot:{quotes:{a:{asOf:'2026-09-25T01:00:00Z'},b:{asOf:'2026-09-25T02:00:00Z'}}},decisionSummary:summary}});
  assert.match(nodes.get('pl-head-meta').innerHTML,/行情最舊來源時間：<b>2026\/09\/25 09:00:00/);
  reply(requests.at(-1), {ok:true,running:false}); await flush();
  nodes.set('pl-beginner-focus-cache',node());
  const loading=T.loadBeginnerFocus();
  assert.equal(requests.at(-1).url,'/focus?mkt=TW&cacheOnly=1');
  reply(requests.at(-1),{ok:true,available:false,buy:[],short:[],scan:null}); await loading;
  assert.match(nodes.get('pl-beginner-focus-cache').innerHTML,/不會因開啟總覽啟動掃描/);
  const valid=T.loadBeginnerFocus();
  reply(requests.at(-1),{ok:true,available:true,buy:[{sym:'2330',signals:['均線突破'],rsi14:52}],short:[],scan:{completedAt:'2026-09-25T07:00:00Z'}}); await valid;
  assert.match(nodes.get('pl-beginner-focus-cache').innerHTML,/獨立焦點快取/);
  assert.match(nodes.get('pl-beginner-focus-cache').innerHTML,/15:00:00/);

  for (const id of ['pl-stock-check','pl-stock-code','pl-stock-result','pl-stock-result-title','pl-stock-result-body','pl-stock-result-meta','pl-stock-open','pl-stock-close']) nodes.set(id,node());
  T.bindStockHealth(); nodes.get('pl-stock-code').value='2330';
  const first=nodes.get('pl-stock-check').onsubmit({preventDefault(){}}); await flush();
  const pending=requests.findLast(r=>r.url.startsWith('/twquote?'));
  nodes.get('pl-stock-close').onclick();
  reply(pending,quote()); await first;
  assert.equal(nodes.get('pl-stock-result').className,'pl-stock-result','關閉後的舊回應不可重開健診');
  nodes.get('pl-stock-code').value='2330';
  const a=nodes.get('pl-stock-check').onsubmit({preventDefault(){}}); await flush();
  const old=requests.findLast(r=>r.url.startsWith('/twquote?'));
  nodes.get('pl-stock-code').value='0050';
  const b=nodes.get('pl-stock-check').onsubmit({preventDefault(){}}); await flush();
  reply(requests.findLast(r=>r.url.startsWith('/twquote?')),quote({code:'0050'})); await b;
  reply(old,quote()); await a;
  assert.match(nodes.get('pl-stock-result-title').textContent,/0050/,'新查詢不被舊回應覆寫');

  for (const id of ['pl-ai','pl-ai-body','pl-ai-st','pl-ai-meta']) nodes.set(id,node());
  scope.STAI={request(){return {promise:Promise.reject(new Error('串流缺少完成事件')),cancel(){}};}};
  const ai=T.runAiSummary('fast'); reply(requests.at(-1),{modes:{}}); await ai;
  assert.match(nodes.get('pl-ai-st').textContent,/未完成/);
  assert.doesNotMatch(nodes.get('pl-ai-meta').textContent,/完成於/);
  assert.equal(T.aiBusy(),false);
  scope.STAI={request(){return {promise:Promise.resolve({text:'已確認的完整摘要',meta:{requestId:'fixture',host:'測試主機'}}),cancel(){}};}};
  const complete=T.runAiSummary('fast'); reply(requests.at(-1),{modes:{}}); await complete;
  assert.equal(nodes.get('pl-ai-body').textContent,'已確認的完整摘要');
  assert.match(nodes.get('pl-ai-meta').textContent,/完成於/);
  let deepOptions, finishDeep;
  scope.STAI={request(options){deepOptions=options;
    options.onStatus({meta:{host:'測試主機',provider:'實際供應商',model:'回報模型',dataBoundary:'external-provider'}});
    return {promise:new Promise(resolve=>{finishDeep=resolve;}),cancel(){}};}};
  const deep=T.runAiSummary('deep'); reply(requests.at(-1),{modes:{}}); await flush();
  assert.equal(deepOptions.endpoint,'/ai/deep');
  assert.match(nodes.get('pl-ai-body').textContent,/約 12 分鐘/);
  assert.match(nodes.get('pl-ai-st').textContent,/實際供應商 · 回報模型 · 外部供應商資料邊界/);
  assert.doesNotMatch(nodes.get('pl-ai-meta').textContent,/完成於/);
  finishDeep({text:'深度分析完整正文',meta:{host:'測試主機',provider:'實際供應商',model:'回報模型',dataBoundary:'external-provider'}});
  await deep; assert.match(nodes.get('pl-ai-meta').textContent,/完成於/);

  for (const id of ['view-pulse','mount-pulse','pl-root','pl-body','pl-refresh','pl-update-status']) nodes.set(id,node());
  const saved={pulse:{ok:true,decisionSummary:{snapshotId:'已提交-舊快照'}}};
  T.setPack(saved); nodes.get('pl-body').innerHTML='使用者正在讀取的上次資料';
  let updateOptions;
  scope.DecisionData={canUpdateMarket:()=>true,refreshPulse(options){updateOptions=options;
    return Promise.resolve({pulse:null,job:{status:'failed',error:'來源未完成'}});}};
  await P.refresh();
  assert.equal(updateOptions.update,true); assert.equal(P.last(),saved);
  assert.equal(nodes.get('pl-body').innerHTML,'使用者正在讀取的上次資料');
  assert.match(nodes.get('pl-update-status').textContent,/保留上次已提交資料/);
  await T.readRefresh(); assert.equal(updateOptions.update,false,'自動讀取不要求建立新快照');
  let finish;
  scope.DecisionData.refreshPulse=options=>{updateOptions=options;return new Promise(resolve=>{finish=resolve;});};
  const pendingUpdate=P.refresh(); P.deactivate();
  assert.equal(updateOptions.signal.aborted,true);
  nodes.get('pl-update-status').textContent='新頁面的狀態';
  finish({pulse:null,job:{status:'failed',error:'晚到的失敗'}}); await pendingUpdate;
  assert.equal(nodes.get('pl-update-status').textContent,'新頁面的狀態','離頁後不可用舊工作回應改寫畫面');
  console.log('脈動日期、來源、取消、純讀焦點、持久快照與 AI 完成契約通過');
})().catch(error=>{console.error(error);process.exitCode=1;});

'use strict';
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), assert = require('node:assert/strict');
const { webcrypto } = require('node:crypto');
const root = path.resolve(__dirname, '..'), tick = () => new Promise(resolve => setImmediate(resolve));
const DOMAIN_NAMES = ['fundamentals', 'flows', 'supplyChainNews', 'peersThemes', 'etfResearch'];
function report(symbol) {
  const domains = Object.fromEntries(DOMAIN_NAMES.map(name => [name, { availability: 'unknown', asOf: null, source: [], evidence: [], reason: '尚無保存資料，公告日未知' }]));
  domains.fundamentals = { availability: 'partial', asOf: null, source: ['保存財報'], reason: '期別不是公告時間',
    evidence: [{ evidenceId: 'fundamental:' + symbol, digest: 'e'.repeat(64), domain: 'fundamentals', kind: 'income', symbol, asOf: null, source: '保存財報', value: { sales: 123, period: '2026Q2', marginNote: '<script>不可執行</script>' } }] };
  domains.peersThemes = { availability: 'available', asOf: '2026-09-22', source: ['同日官方日線'], reason: '同市場同日期比較，非報酬預測',
    evidence: [{ evidenceId: 'peers:' + symbol, digest: 'f'.repeat(64), domain: 'peersThemes', kind: 'same_industry', symbol, asOf: '2026-09-22', source: '同日官方日線', value: { currency: 'TWD', market: 'TW', peers: [{ symbol: '2303', changePct: 1.2 }] } }] };
  return { ok: true, version: 'research-subject-v1', symbol, market: 'TW', currency: 'TWD', asOf: null, readOnly: true, domains, evidence: [], digest: 'b'.repeat(64), notes: ['完整公開研究'] };
}
function daily(symbol) { return { ok: true, symbol, asOf: '2026-09-22', research: { version: 'breakout-v1', stats: [], latest: { signals: [] } } }; }
function harness() {
  const nodes = new Map(), data = new Map(), requests = [], navigation = [], listeners = new Map();
  let taskInput;
  function element(id = '') {
    const node = { id, value: '', textContent: '', disabled: false, style: {}, attrs: {}, tools: [],
      appendChild() {}, getAttribute(key) { return this.attrs[key] || null; }, querySelectorAll(selector) { return selector === '[data-rw-tool]' ? this.tools : []; } };
    Object.defineProperty(node, 'innerHTML', { get() { return this.html || ''; }, set(value) {
      this.html = String(value); this.tools = [];
      for (const match of this.html.matchAll(/<\w+\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
        const child = element(match[1]); const val = /\bvalue="([^"]*)"/.exec(match[0]); child.value = val ? val[1] : ''; child.disabled = /\bdisabled/.test(match[0]);
      }
      for (const match of this.html.matchAll(/<button\b[^>]*data-rw-tool="([^"]+)"[^>]*>/g)) {
        const button = element(); button.attrs['data-rw-tool'] = match[1]; button.disabled = /\bdisabled/.test(match[0]); this.tools.push(button);
      }
    } });
    if (id) nodes.set(id, node); return node;
  }
  element('mount-research');
  const storage = { get length() { return data.size; }, key: i => [...data.keys()][i], getItem: k => data.has(k) ? data.get(k) : null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) };
  const current = { snapshotId: 'dc-current', revision: 2, persistence: 'committed', asOf: new Date().toISOString(), digest: 'd'.repeat(64),
    evidence: [{ evidenceId: 'current:metric', digest: 'a'.repeat(64), id: 'metric', asOf: new Date().toISOString(), source: '正式快照', value: 1 }] };
  const context = { console, Date, Math, Promise, Set, Map, Uint8Array, TextEncoder, AbortController, crypto: webcrypto, setTimeout, clearTimeout,
    localStorage: storage, sessionStorage: storage, SC_CHAINS: { TW: [{ stage: '晶圓分類', stocks: [['2330', '台積電'], ['2303', '聯電']] }] },
    document: { getElementById: id => nodes.get(id) || null, createElement: () => element(), head: { appendChild() {} } },
    addEventListener(type, fn) { listeners.set(type, fn); },
    ResearchTasks: { mount(_node, input) { taskInput = input; }, stop() {} },
    ShellV5: { go(route, options) { navigation.push({ route, options }); } },
    ValuationResearchUI: { open(symbol) { navigation.push({ tool: 'valuation', symbol }); } },
    openEtfMgrModal() { navigation.push({ tool: 'etf' }); }, supplyChainOpen() { navigation.push({ tool: 'supply' }); },
    fetch(url, options) {
      const call = { url, options }; requests.push(call);
      if (url.startsWith('/research/workflow')) return Promise.resolve({ ok: true, json: async () => ({ ok: true, current, previous: null, changes: [], history: [], nextBefore: null }) });
      assert(url.startsWith('/research/subject?') || url.startsWith('/kline-events?'), '只能讀取指定既有公開資料入口');
      assert.equal(options.method, undefined, '公開資料入口只能 GET');
      return new Promise((resolve, reject) => { call.resolve = payload => resolve({ ok: true, json: async () => payload }); call.reject = reject; });
    } };
  context.window = context; vm.createContext(context);
  for (const file of ['src/core/研究工作流.js', 'src/core/研究任務.js', 'src/ui/研究工作台.js']) vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, { filename: file });
  return { context, nodes, storage, requests, navigation, current, get: id => nodes.get(id), input: () => taskInput(),
    async start() { context.ResearchDesk.activate(); for (let i = 0; i < 10; i++) await tick(); },
    read(symbol) { nodes.get('rw-symbol').value = symbol; return nodes.get('rw-subject-load').onclick(); },
    complete(symbol, from = 0, profile = report(symbol)) { for (const call of requests.slice(from)) {
      if (call.url === '/kline-events?sym=' + symbol + '&range=1y') call.resolve(daily(symbol));
      if (call.url === '/research/subject?symbol=' + symbol) call.resolve(profile);
    } } };
}
(async () => {
  const h = harness(); await h.start();
  assert.equal(h.requests.length, 1, '掛載只讀快照，不自動讀各領域資料');
  const loading = h.read('2330'); h.complete('2330'); await loading;
  const first = h.input().subject, html = h.get('rw-subject').innerHTML;
  for (const label of ['基本面與估值資料', '法人與籌碼', '公開新聞與事件', '同業與主題比較', 'ETF 研究', '供應鏈研究分類']) assert(html.includes(label));
  assert(html.includes('來源資料日 未知')); assert(html.includes('非供應關係證明')); assert(html.includes('123'));
  assert(html.includes('&lt;script&gt;')); assert(!html.includes('<script>')); assert.equal(h.navigation.length, 0);
  const tools = h.get('rw-subject').tools; for (const button of tools) { assert.equal(button.disabled, false); button.onclick(); }
  assert(h.navigation.some(x => x.tool === 'valuation' && x.symbol === '2330'));
  assert(h.navigation.some(x => x.route === 'institutional')); assert(h.navigation.some(x => x.tool === 'etf'));
  const packet = await h.context.ResearchTaskCore.freeze({ data: { current: h.current }, subject: first }, 'subject');
  assert.equal(packet.subjects.current.savedResearch.report.domains.fundamentals.evidence[0].value.sales, 123);
  assert(packet.evidence.some(row => row.evidenceId.endsWith(':savedResearch') && row.quote.includes('來源日期') === false && row.quote.includes('2026Q2')));
  first.savedResearch.report.domains.fundamentals.evidence[0].value.sales = 999;
  assert.equal(packet.subjects.current.savedResearch.report.domains.fundamentals.evidence[0].value.sales, 123, '模型公開包凍結不可回寫');
  const contaminated = JSON.parse(JSON.stringify(first));
  contaminated.savedResearch.private = '外層私人資料'; contaminated.savedResearch.notes = '外層私人筆記'; contaminated.savedResearch.holdings = { position: '外層私人持倉' };
  contaminated.savedResearch.report.private = '報告額外私人資料'; contaminated.savedResearch.report.domains.fundamentals.private = '領域額外私人資料';
  contaminated.savedResearch.report.domains.fundamentals.evidence[0].private = '證據額外私人資料';
  contaminated.savedResearch.report.domains.fundamentals.evidence[0].value.holdings = ['財報混入私人持倉'];
  contaminated.savedResearch.report.domains.etfResearch.evidence = [{ evidenceId: 'public-etf', digest: 'a'.repeat(64), domain: 'etfResearch', kind: 'saved_holdings', symbol: '2330', asOf: null, source: '公開基金快照',
    value: { name: '公開基金', sourceDate: null, holdings: [{ code: '2303', name: '聯電', shares: 100, weight: 0.1, market: 'TW', private: '基金列混入私人欄位' }] } }];
  const publicPacket = await h.context.ResearchTaskCore.freeze({ data: { current: h.current }, subject: contaminated }, 'subject');
  for (const privateText of ['外層私人資料', '外層私人筆記', '外層私人持倉', '報告額外私人資料', '領域額外私人資料', '證據額外私人資料', '財報混入私人持倉', '基金列混入私人欄位']) assert(!JSON.stringify(publicPacket).includes(privateText));
  assert.equal(publicPacket.subjects.current.originalSavedReport, undefined, '完整本機原報告不繞過公開白名單進入模型');
  assert.equal(publicPacket.subjects.current.savedResearch.report.domains.etfResearch.evidence[0].value.holdings[0].shares, 100, '真正 ETF 公開持股不得被隱私篩選刪除');
  assert.equal(publicPacket.subjects.current.savedResearch.report.domains.fundamentals.asOf, null);
  console.log('通過：領域真資料呈現、日期未知、既有功能入口及完整公開資料模型凍結');

  const oldHtml = h.get('rw-subject').innerHTML, oldSubject = h.input().subject;
  let start = h.requests.length; const failed = h.read('0050');
  h.requests.slice(start).find(c => c.url.startsWith('/research/subject')).reject(new Error('合成保存資料讀取失敗'));
  h.requests.slice(start).find(c => c.url.startsWith('/kline-events')).resolve(daily('0050')); await failed;
  assert.equal(h.input().subject, oldSubject); assert.equal(h.get('rw-subject').innerHTML, oldHtml); assert(h.get('rw-status').textContent.includes('完整保留'));
  start = h.requests.length; const earlier = h.read('2330'), laterStart = h.requests.length, later = h.read('0050');
  assert(h.requests[start].options.signal.aborted); h.complete('0050', laterStart); await later;
  h.complete('2330', start); await earlier; assert.equal(h.input().subject.symbol, '0050');
  start = h.requests.length; const away = h.read('2330'); h.context.ResearchDesk.deactivate(); h.complete('2330', start); await away;
  assert.equal(h.input().subject.symbol, '0050'); assert(h.requests[start].options.signal.aborted);
  h.context.ResearchDesk.activate();
  start = h.requests.length; const wrong = h.read('2330'); h.complete('2330', start, report('0050')); await wrong;
  assert.equal(h.input().subject.symbol, '0050'); assert(h.get('rw-status').textContent.includes('歸屬不符'));
  start = h.requests.length; const noDaily = h.read('2330');
  h.requests.slice(start).find(c => c.url.startsWith('/kline-events')).reject(new Error('日線資料庫暫不可讀取（503）'));
  h.requests.slice(start).find(c => c.url.startsWith('/research/subject')).resolve(report('2330')); await noDaily;
  assert.equal(h.input().subject.symbol, '2330'); assert.equal(h.input().subject.technicalAvailability, 'unknown');
  assert.equal(h.input().subject.savedResearch.report.domains.fundamentals.evidence[0].value.sales, 123);
  assert(h.get('rw-subject').innerHTML.includes('日線資料庫暫不可讀取（503）'));
  console.log('通過：失敗完整保留、逆序不覆寫、離頁停止及錯誤標的歸屬拒絕');

  start = h.requests.length; const etf = h.read('00981a.tw'); h.complete('00981A', start); await etf;
  assert.equal(h.input().subject.symbol, '00981A'); assert.equal(h.input().subject.technicalAvailability, 'unknown');
  assert.equal(h.requests.slice(start).length, 1, '尚未支援字尾的日線入口不能錯送代號');
  assert(h.get('rw-subject').innerHTML.includes('技術研究未知'));
  console.log('通過：ETF 英文字尾正規化與未支援日線明示未知');
})().catch(error => { console.error(error); process.exitCode = 1; });

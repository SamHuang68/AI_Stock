'use strict';

// 真實 Chromium 執行正式模組。所有頁面要求均由固定資料攔截；不啟動行情、模型或正式後端。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', '研究工作台驗收'));
const origin = 'https://st-offline.test';
const files = ['chart/hotkeys_v3.js', 'core/投組資料契約_v5.js', 'core/研究工作流.js', 'core/更新工作_v5.js',
  'ai/ai_runtime_client.js', 'core/研究任務.js', 'ui/研究任務面板.js', 'ui/研究工作台.js', 'ui/更新工作中心.js'];
const scripts = new Map(files.map(file => ['/src/' + file, fs.readFileSync(path.join(root, 'src', file), 'utf8')]));
const report = { browser: null, scopes: ['正式研究工作台、研究任務面板、投組契約及更新中心', '導航外殼使用固定測試容器，不替代全站或正式服務驗收'], checks: [], layouts: [], requests: [], pageErrors: [] };
report.sources = [...scripts].map(([file, source]) => ({ file, sha256Lf: crypto.createHash('sha256').update(source.replace(/\r\n/g, '\n')).digest('hex') }));
let revision = 2;
const snapshot = n => ({ snapshotId: 'dc-' + n, revision: n, persistence: 'committed', asOf: `2026-09-${20 + n}T01:00:00+08:00`,
  digest: String(n).repeat(64), publishedAt: `2026-09-${20 + n}T01:01:00+08:00`, regime: { id: n === 1 ? 'NEUTRAL' : 'CONFLICT' },
  dataQuality: { freshness: 1, warnings: ['固定離線資料，並非即時行情'] }, keyLevels: { support: 23000, resistance: 24123.45 },
  evidence: Array.from({ length: 6 }, (_, i) => ({ id: 'metric.' + i, evidenceId: 'dc-' + n + ':metric.' + i, digest: 'a'.repeat(64),
    metric: '完整市場證據與使用前提 ' + i, value: 123456789.123 + n, comparison: '保留全部來源日期、限制與較長分析內容，不應被遮蔽或裁切。',
    quality: 'observed', source: '固定測試來源', asOf: `2026-09-${20 + n}T00:00:00+08:00` })) });
function workflow(url) {
  const current = snapshot(Number((url.searchParams.get('current') || 'dc-' + revision).split('-')[1]));
  const previous = snapshot(Number((url.searchParams.get('previous') || 'dc-' + (current.revision - 1)).split('-')[1]));
  const older = url.searchParams.has('before');
  return { ok: true, version: 'research-workflow-v1', current, previous,
    history: (older ? [snapshot(1)] : [current, previous]).map(s => ({ snapshotId: s.snapshotId, revision: s.revision, asOf: s.asOf, digest: s.digest })),
    nextBefore: !older && previous.revision > 1 ? previous.revision : null,
    changes: [{ key: 'regime', title: '市場情境與完整變化說明', kind: 'state', before: previous.regime, after: current.regime,
      fromSnapshotId: previous.snapshotId, toSnapshotId: current.snapshotId }] };
}
function subject(symbol) {
  return { ok: true, symbol, asOf: '2026-09-22', source: '固定官方日線副本', quality: { status: 'complete', missing: [] },
    research: { version: 'breakout-observation-v1', stats: [{ rule: '突破研究', horizons: { 1: { mean: .03 } } }],
      latest: { date: '2026-09-22', eligible: true }, shadow: { count: 0 },
      adjusted: { version: 'breakout-observation-adjusted-v1', priceBasis: 'twse-reference-comparison', stats: [], latest: {}, shadow: { count: 0 } } } };
}
const domainLabels = ['基本面與估值資料', '法人與籌碼', '已保存公開新聞與事件', '同業與主題比較', 'ETF 研究', '供應鏈研究分類'];
function savedSubject(symbol) {
  const domains = Object.fromEntries(['fundamentals', 'flows', 'supplyChainNews', 'peersThemes', 'etfResearch'].map(name =>
    [name, { availability: 'unknown', asOf: null, source: [], evidence: [], reason: symbol + ' 尚無可核對的已保存資料；未知不代表零或沒有風險。' }]));
  function add(name, kind, asOf, value, availability = 'available') {
    const source = symbol + ' 固定公開來源 ' + name;
    const row = { symbol, domain: name, kind, asOf, source, value };
    row.digest = crypto.createHash('sha256').update(JSON.stringify(row)).digest('hex');
    row.evidenceId = 'subject:' + symbol + ':' + name + ':' + row.digest;
    domains[name] = { availability, asOf, source: [source], evidence: [row], reason: symbol + ' 完整來源前提保留；取得時間不等於公告時間，各領域日期不能合併成即時訊號。' };
  }
  if (symbol === '2330') {
    add('fundamentals', 'revenue', '2026-09-10', { period: '202608', periodLabel: '2026 年 8 月', monthRev: 335772000, yoyPct: 23.4, unit: '仟元', unitMultiplier: 1000, sourceDate: '2026-09-10' });
    add('flows', 'institutional', '2026-09-21', { foreign: 2000, trust: -300, dealer: 100, total: 1800, unit: '張', sourceDate: '2026-09-21' }, 'partial');
    add('supplyChainNews', 'company_news', '2026-09-20', { title: '2330 專屬公開事件與有限研究前提', time: '2026-09-20T08:00:00+08:00', code: symbol, source: '固定公告', url: 'https://example.invalid/public-event' });
    add('peersThemes', 'same_industry', '2026-09-18', { symbol: '2303', industry: '半導體', market: 'TW', currency: 'TWD', comparable: false, changePct: null, comparisonReason: '兩檔來源日期不同，不能宣稱同日強弱。', observations: [{ close: 49.5, asOf: '2026-09-18', source: '固定官方日線副本', priceBasis: 'raw', issues: ['比較日不一致'] }] }, 'partial');
    domains.etfResearch = { availability: 'not_applicable', asOf: '2026-09-10', source: ['2330 固定公司分類'], evidence: [], reason: '已保存公司分類可核對為一般公司，ETF 持股研究不適用。' };
  } else {
    add('flows', 'institutional', '2026-09-19', { foreign: -150, trust: 300, dealer: 20, total: 170, unit: '張', sourceDate: '2026-09-19' }, 'partial');
    add('etfResearch', 'catalog_classification', null, { code: symbol, name: symbol + ' 固定 ETF 名錄', market: 'TW', category: '國內股票型' }, 'partial');
    domains.etfResearch.classificationAsOf = '2026-09-18';
    domains.etfResearch.classificationNote = '名錄日期不是持股日期；未取得可核對的持股時點。';
  }
  const result = { ok: true, version: 'research-subject-v1', symbol, market: 'TW', currency: 'TWD', asOf: null, readOnly: true,
    domains, evidence: Object.values(domains).flatMap(value => value.evidence), notes: ['固定資料僅驗證研究流程，各領域日期分開保留。'] };
  result.digest = crypto.createHash('sha256').update(JSON.stringify(result)).digest('hex');
  return result;
}
const baseJob = { jobId: 'r-' + '1'.repeat(32), type: 'research', status: 'failed', stage: '來源暫不可用',
  queuedAt: '2026-09-22T00:00:00Z', startedAt: '2026-09-22T00:00:01Z', finishedAt: '2026-09-22T00:00:02Z',
  reason: 'manual', attempt: 1, canRetry: true, error: '較長錯誤說明：保留原始研究與使用前提，請待來源恢復後再重試。'.repeat(3) };
function html(role) {
  return `<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>離線研究工作台驗收</title>
  <style>*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:#071322;color:#e2e8f0}nav{display:flex;gap:8px;padding:8px;flex-wrap:wrap}nav button{font:14px sans-serif;padding:8px}#other{padding:20px}[hidden]{display:none!important}</style></head>
  <body><nav><button id="nav-research">研究工作台</button><button id="nav-other">其他頁面</button><button id="nav-updates">更新中心</button></nav><div id="mount-research"></div><div id="other" hidden>固定測試導航頁面</div>
  <script>window.ST_PRIVATE_WEB_PROFILE={role:${JSON.stringify(role)}};window.SERVER='';window.S={positions:{},watches:{'2330':{mkt:'TW'}}};window.SC_CHAINS={TW:[{stage:'2330 固定研究分類',stocks:[['2330','台積電'],['2303','聯電']]}]};window.ShellV5={route:function(){return 'research'},go:function(route,options){window.lastChart={route,options}}};</script>
  ${files.map(file => `<script src="/src/${file}"></script>`).join('')}
  <script>
  document.getElementById('nav-research').onclick=function(){document.getElementById('mount-research').hidden=false;document.getElementById('other').hidden=true;ResearchDesk.activate()};
  document.getElementById('nav-other').onclick=function(){ResearchDesk.deactivate();document.getElementById('mount-research').hidden=true;document.getElementById('other').hidden=false};
  document.getElementById('nav-updates').onclick=function(event){UpdateCenter.open(event.currentTarget)};
  ResearchDesk.activate();
  </script></body></html>`;
}
async function harness(browser, role = 'owner') {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, hasTouch: true, acceptDownloads: true });
  const jobs = [JSON.parse(JSON.stringify(baseJob))];
  const state = { failPortfolio: false, failDaily: false };
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    const entry = { role, method: request.method(), path: url.pathname, query: url.search, fixture: true }; report.requests.push(entry);
    if (url.origin !== origin) { entry.fixture = false; await route.abort(); return; }
    let payload;
    if (url.pathname === '/') { await route.fulfill({ contentType: 'text/html; charset=utf-8', body: html(role) }); return; }
    const script = scripts.get(decodeURIComponent(url.pathname));
    if (script) { await route.fulfill({ contentType: 'application/javascript; charset=utf-8', body: script }); return; }
    if (url.pathname === '/research/workflow' && request.method() === 'GET') payload = workflow(url);
    else if (url.pathname === '/research/validation' && request.method() === 'GET') payload = { ok: true, observations: [], nextBefore: null,
      validation: { observations: 0, strata: [], status: 'not_started', retrospectiveBackfill: false,
        notes: ['合成資料尚無前向觀測；不得以歷史結果補造尚未發生的研究證據。'] } };
    else if (url.pathname === '/research/portfolio' && request.method() === 'GET') {
      if (state.failPortfolio) { await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: '合成來源失敗，先前組合研究保留' }) }); return; }
      payload = { ok: true, status: 'unknown', rules: [], notes: ['合成缺資料前提：除權息權利、成本及資料覆蓋尚不足，不能把工程驗證視為策略獲利證明。'.repeat(2)] };
    }
    else if (url.pathname === '/research/subject' && request.method() === 'GET') payload = savedSubject(url.searchParams.get('symbol'));
    else if (url.pathname === '/kline-events' && request.method() === 'GET') {
      if (state.failDaily) { await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: '固定日線來源暫不可用，其他保存研究仍可閱讀' }) }); return; }
      payload = subject(url.searchParams.get('sym'));
    }
    else if (url.pathname === '/updates' && request.method() === 'GET') payload = { ok: true, jobs,
      capabilities: { canSubmit: role === 'owner', canRetry: role === 'owner', types: role === 'owner' ? ['pulse', 'options', 'research'] : [] },
      workers: { pulse: { running: true }, research: { running: true } }, note: '市場與研究使用既有工作者；所有內容為離線固定資料。' };
    else if ((url.pathname === '/updates' || url.pathname === '/updates/retry') && request.method() === 'POST') {
      if (role !== 'owner') { await route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ error: '唯讀禁止寫入' }) }); return; }
      const job = { ...baseJob, jobId: 'p-' + '2'.repeat(32), type: 'pulse', status: 'succeeded', stage: '正式快照已提交', canRetry: false, error: null, result: { snapshotId: 'dc-3', revision: 3 } };
      jobs.unshift(job); payload = { ok: true, job, coalesced: false };
    } else { entry.fixture = false; await route.abort(); return; }
    await route.fulfill({ status: request.method() === 'POST' ? 202 : 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });
  const page = await context.newPage();
  page.on('pageerror', error => report.pageErrors.push({ role, error: error.message }));
  await page.goto(origin, { waitUntil: 'load' });
  await page.waitForFunction(() => document.getElementById('rw-changes').textContent.includes('dc-2') || document.getElementById('rw-changes').textContent.includes('dc-3'));
  return { context, page, jobs, state };
}
async function frame(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function geometry(page, selector) {
  return page.locator(selector).evaluate(root => {
    const nodes = [...root.querySelectorAll('button,summary,h2,h3,h4,p,pre,dt,dd,.uc-job-head,.rw-change')].filter(node => node.getClientRects().length && node.clientWidth);
    const clipped = nodes.filter(node => node.scrollWidth > node.clientWidth + 2 ||
      (getComputedStyle(node).overflowY === 'hidden' && node.scrollHeight > node.clientHeight + 2)).map(node => ({ tag: node.tagName, text: node.textContent.slice(0, 80), width: node.clientWidth, scrollWidth: node.scrollWidth }));
    // 原生 select 的 scrollWidth 不反映選項文字截斷，另量測實際字型與箭頭空間。
    const canvas = document.createElement('canvas'), drawing = canvas.getContext('2d');
    const clippedSelection = [...root.querySelectorAll('#rw-current,#rw-previous,#rw-records')].filter(node => {
      if (!node.getClientRects().length || !node.selectedOptions.length) return false;
      const css = getComputedStyle(node); drawing.font = css.font;
      const width = node.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight) - 20;
      return drawing.measureText(node.selectedOptions[0].textContent).width > width + 2;
    }).map(node => ({ id: node.id, text: node.selectedOptions[0].textContent, width: node.clientWidth }));
    return { width: innerWidth, height: innerHeight, pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
      componentOverflow: root.scrollWidth > root.clientWidth + 2, clipped, clippedSelection };
  });
}
async function checkLayout(page, width, height, label) {
  await page.setViewportSize({ width, height });
  await page.locator('#rw-root details').evaluateAll(nodes => nodes.forEach(node => { node.open = true; }));
  await frame(page);
  const research = await geometry(page, '#rw-root');
  assert.equal(research.pageOverflow, false, label + ' 研究頁水平溢出');
  assert.equal(research.componentOverflow, false, label + ' 研究元件水平溢出');
  assert.deepEqual(research.clipped, [], label + ' 研究文字裁切 ' + JSON.stringify(research.clipped));
  assert.deepEqual(research.clippedSelection, [], label + ' 快照選項裁切 ' + JSON.stringify(research.clippedSelection));
  await page.locator('#nav-updates').click();
  await page.waitForFunction(() => document.querySelectorAll('#st-update-center .uc-job').length > 0);
  await frame(page);
  const updates = await geometry(page, '#st-update-center');
  assert.equal(updates.componentOverflow, false, label + ' 更新中心水平溢出');
  assert.deepEqual(updates.clipped, [], label + ' 更新中心文字裁切 ' + JSON.stringify(updates.clipped));
  await page.screenshot({ path: path.join(output, label + '-更新中心.png') });
  const priorNavigation = await page.evaluate(() => window.lastChart || null);
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'nav-updates', 'Escape 回復可見入口焦點');
  assert.deepEqual(await page.evaluate(() => window.lastChart || null), priorNavigation, '正式全域快捷鍵不可在對話框 Escape 時導回圖表');
  await page.screenshot({ path: path.join(output, label + '-研究工作台.png'), fullPage: true });
  await page.locator('#rw-root details').evaluateAll(nodes => nodes.forEach(node => { node.open = false; }));
  await page.evaluate(() => scrollTo(0, 0)); await frame(page);
  await page.screenshot({ path: path.join(output, label + '-一般畫面.png') });
  report.layouts.push({ label, research, updates });
}
async function listenerCounts(context, page) {
  const session = await context.newCDPSession(page), counts = {};
  try {
    for (const expression of ['window', 'document', 'document.getElementById("st-update-center")']) {
      const value = await session.send('Runtime.evaluate', { expression });
      const result = await session.send('DOMDebugger.getEventListeners', { objectId: value.result.objectId });
      counts[expression] = result.listeners.reduce((all, listener) => { all[listener.type] = (all[listener.type] || 0) + 1; return all; }, {});
      await session.send('Runtime.releaseObject', { objectId: value.result.objectId });
    }
  } finally { await session.detach(); }
  return counts;
}
async function records(page) { return page.evaluate(() => new ResearchWorkflow.Store(localStorage).list().records); }
async function save(page, title, review = false) {
  const count = (await records(page)).length;
  await page.locator('#rw-title').fill(title);
  await page.locator('#rw-note').fill('完整研究筆記：保留當時資料與限制，不能用事後資訊回寫假說。');
  await page.locator(review ? '#rw-save-review' : '#rw-save').click();
  await page.waitForFunction(n => new ResearchWorkflow.Store(localStorage).list().records.length === n, count + 1);
  await page.waitForFunction(() => document.getElementById('rw-record').textContent.includes('內容摘要核對通過'));
  return (await records(page))[0];
}
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const launch = { headless: true };
  if (process.env.ST_BROWSER_CHANNEL) launch.channel = process.env.ST_BROWSER_CHANNEL;
  if (process.env.ST_BROWSER_EXECUTABLE) launch.executablePath = process.env.ST_BROWSER_EXECUTABLE;
  const browser = await chromium.launch(launch);
  report.browser = { version: browser.version(), channel: process.env.ST_BROWSER_CHANNEL || 'bundled-chromium' };
  try {
    const owner = await harness(browser), page = owner.page;
    await page.locator('#rw-subject-load').click();
    await page.waitForFunction(() => document.getElementById('rw-subject').textContent.includes('2330 ·'));
    const initialDomains = page.locator('#rw-subject > .rw-grid > article');
    assert.deepEqual(await initialDomains.locator('h4').allTextContents(), domainLabels);
    for (const [index, date, source] of [[0, '2026-09-10', '2330 固定公開來源 fundamentals'], [1, '2026-09-21', '2330 固定公開來源 flows'], [2, '2026-09-20', '2330 固定公開來源 supplyChainNews'], [3, '2026-09-18', '2330 固定公開來源 peersThemes']]) {
      const text = await initialDomains.nth(index).textContent();
      assert(text.includes('來源資料日 ' + date) && text.includes('來源：' + source));
    }
    assert((await initialDomains.nth(4).textContent()).includes('已核對為不適用'));
    const classificationText = await initialDomains.nth(5).textContent();
    assert(classificationText.includes('來源資料日 未知') && classificationText.includes('非供應關係證明') && classificationText.includes('SC_CHAINS.TW'));
    report.checks.push('六個標的研究領域保留各自時點與來源，分類日期未知及 ETF 不適用均明示');
    const first = await save(page, '原始研究：完整保留當時假說與資料'.repeat(20).slice(0, 240));
    assert.deepEqual(first.subject.savedResearch.report, savedSubject('2330'));
    assert.equal(first.subject.savedResearch.supplyChainClassification.evidence[0].value.stage, '2330 固定研究分類');
    await page.locator('#nav-other').click(); await page.locator('#nav-research').click();
    assert((await page.locator('#rw-title').inputValue()).includes('原始研究'));
    await page.locator('#rw-records').selectOption(first.id);
    await page.waitForFunction(() => !document.getElementById('rw-save-review').disabled);
    revision = 3;
    await page.locator('#rw-refresh').click();
    await page.waitForFunction(() => document.getElementById('rw-changes').textContent.includes('dc-3'));
    const reviewed = await save(page, '原始研究的事後回顧', true);
    assert.equal(reviewed.reviewOf, first.id); assert.equal(reviewed.snapshot.snapshotId, first.snapshot.snapshotId);
    assert.equal(reviewed.outcome.snapshot.snapshotId, 'dc-3');
    assert.deepEqual(reviewed.subject.savedResearch, first.subject.savedResearch, '回顧保留當時全部領域證據');
    assert.equal((await records(page)).find(row => row.id === first.id).digest, first.digest);
    await page.locator('#rw-more').click();
    await page.waitForFunction(() => !!document.querySelector('#rw-current option[value="dc-1"]'));
    assert.equal(await page.locator('#rw-current').inputValue(), 'dc-3');
    report.checks.push('保存→切頁→回顧保留原紀錄，事後快照另存');

    assert.equal(report.requests.filter(row => ['/research/validation', '/research/portfolio'].includes(row.path)).length, 0, '研究擴充不能自動提交或載入');
    await page.locator('#rw-validation-load').click();
    await page.waitForFunction(() => document.getElementById('rw-validation').textContent.includes('已保存觀測 0 筆'));
    await page.locator('#rw-portfolio-load').click();
    await page.waitForFunction(() => document.getElementById('rw-portfolio-result').textContent.includes('合成缺資料前提'));
    const previousPortfolio = await page.locator('#rw-portfolio-result').textContent();
    owner.state.failPortfolio = true;
    await page.locator('#rw-portfolio-load').click();
    await page.waitForFunction(() => document.getElementById('rw-status').textContent.includes('合成來源失敗'));
    assert.equal(await page.locator('#rw-portfolio-result').textContent(), previousPortfolio);
    owner.state.failPortfolio = false;
    report.checks.push('預警無樣本、組合資料未知與 HTTP 503 失敗保留均由明確按鈕載入，完整前提可閱讀');

    const downloaded = page.waitForEvent('download'); await page.locator('#rw-export').click();
    const download = await downloaded, stream = await download.createReadStream(), chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    const backup = Buffer.concat(chunks), exported = JSON.parse(backup); assert.equal(exported.records.length, 2);
    assert.deepEqual(exported.records.find(row => row.id === first.id).subject.savedResearch, first.subject.savedResearch);
    const imported = await harness(browser);
    await imported.page.locator('#rw-import').setInputFiles({ name: '固定研究備份.json', mimeType: 'application/json', buffer: backup });
    await imported.page.waitForFunction(() => document.getElementById('rw-status').textContent.includes('已匯入 2 筆'));
    const importedRecords = await records(imported.page);
    assert.equal(importedRecords.length, 2);
    assert.deepEqual(importedRecords.find(row => row.id === first.id).subject.savedResearch, first.subject.savedResearch);
    await imported.context.close();
    report.checks.push('透過實際下載與檔案選擇器匯入兩筆研究，六領域來源、時點與完整證據均不遺失');

    const unavailable = await harness(browser);
    unavailable.state.failDaily = true;
    await unavailable.page.locator('#rw-subject-load').click();
    await unavailable.page.waitForFunction(() => document.getElementById('rw-subject').textContent.includes('2330 ·'));
    assert((await unavailable.page.locator('#rw-subject').textContent()).includes('技術研究未知：固定日線來源暫不可用'));
    assert.equal(await unavailable.page.locator('#rw-subject > .rw-grid > article').count(), 6);
    const noDaily = await save(unavailable.page, '日線失敗仍可保存其餘研究');
    assert.equal(noDaily.subject.technicalAvailability, 'unknown'); assert.equal(noDaily.subject.asOf, null);
    assert.deepEqual(noDaily.subject.savedResearch.report, savedSubject('2330'));
    await unavailable.page.locator('#rw-symbol').fill('00981A'); await unavailable.page.locator('#rw-subject-load').click();
    await unavailable.page.waitForFunction(() => document.getElementById('rw-subject').textContent.includes('00981A ·'));
    assert.equal(report.requests.filter(row => row.path === '/kline-events' && row.query.includes('00981A')).length, 0);
    assert((await unavailable.page.locator('#rw-subject').textContent()).includes('日線研究入口尚未支援此代號格式'));
    assert((await unavailable.page.locator('#rw-subject > .rw-grid > article').nth(4).textContent()).includes('00981A 固定公開來源 etfResearch'));
    await unavailable.context.close();
    report.checks.push('日線 HTTP 503 仍可閱讀及保存其他五領域與分類；字尾 ETF 代號不呼叫不支援的數字日線入口');

    await page.evaluate(() => {
      const original = crypto.subtle.digest.bind(crypto.subtle), freeze = ResearchWorkflow.freezeSubject;
      window.restoreDigest = () => { crypto.subtle.digest = original; ResearchWorkflow.freezeSubject = freeze; };
      window.hashWaiting = false;
      crypto.subtle.digest = async (algorithm, bytes) => {
        const value = JSON.parse(new TextDecoder().decode(bytes));
        if (!window.hashWaiting && value.daily && value.daily.symbol === '2330' && value.savedResearch) {
          window.hashWaiting = true;
          await new Promise(resolve => { window.releaseOldHash = resolve; });
        }
        return original(algorithm, bytes);
      };
      ResearchWorkflow.freezeSubject = async (...args) => {
        try { return await freeze(...args); }
        finally { if (args[0] === '2330') window.oldSubjectResolved = true; }
      };
    });
    await page.locator('#rw-symbol').fill('2330'); await page.locator('#rw-subject-load').click();
    await page.waitForFunction(() => window.hashWaiting);
    await page.locator('#rw-symbol').fill('0050'); await page.locator('#rw-subject-load').click();
    await page.waitForFunction(() => document.getElementById('rw-subject').textContent.includes('0050 ·'));
    await page.evaluate(() => releaseOldHash()); await page.waitForFunction(() => window.oldSubjectResolved);
    await frame(page); await page.evaluate(() => restoreDigest());
    const race = await save(page, '競態核對：應保存0050');
    assert.equal(race.subject.symbol, '0050'); assert.equal(race.symbol, '0050');
    assert.deepEqual(race.subject.savedResearch.report, savedSubject('0050'));
    assert.equal(race.subject.savedResearch.supplyChainClassification.availability, 'unknown');
    assert.equal(race.subject.savedResearch.supplyChainClassification.evidence.length, 0);
    assert.equal((await page.locator('#rw-subject').textContent()).includes('2330'), false, '換股後不可殘留前股資料與分類');
    const switched = page.locator('#rw-subject > .rw-grid > article');
    for (const index of [0, 2, 3, 5]) assert((await switched.nth(index).textContent()).includes('未知／尚無保存證據'));
    assert((await switched.nth(4).textContent()).includes('來源資料日 未知'));
    report.checks.push('A 的摘要晚於 B 返回，畫面與保存紀錄均保持 B');
    report.checks.push('2330 切換 0050 後六領域不殘留前股內容，未知基本面、事件、同業、分類及 ETF 持股日期保持未知');

    await page.evaluate(id => {
      const key = 'st.research.record.v1.' + id, row = JSON.parse(localStorage.getItem(key));
      row.snapshot.regime = { id: '事後改寫' }; localStorage.setItem(key, JSON.stringify(row));
      dispatchEvent(new StorageEvent('storage', { key }));
    }, reviewed.id);
    await page.locator('#rw-records').selectOption(reviewed.id);
    await page.waitForFunction(() => document.getElementById('rw-record').textContent.includes('內容摘要不符'));
    assert.equal(await page.locator('#rw-save-review').isDisabled(), true);
    await page.locator('#rt-type').selectOption('review'); await page.locator('#rt-freeze').click();
    await page.waitForFunction(() => /需要|摘要不符/.test(document.getElementById('rt-status').textContent));
    assert.equal(await page.locator('#rt-run').isDisabled(), true);
    const refused = await page.evaluate(async id => {
      const record = JSON.parse(localStorage.getItem('st.research.record.v1.' + id));
      try { await ResearchTaskCore.freeze({ record }, 'review'); return false; } catch (_) { return true; }
    }, reviewed.id);
    assert(refused, '損毀紀錄在 core 層也必須拒絕');
    report.checks.push('損毀研究不可回顧或交給 AI，UI 與核心雙重拒絕');

    await page.locator('#rw-records').selectOption(first.id);
    await page.waitForFunction(() => document.getElementById('rw-record').textContent.includes('內容摘要核對通過'));
    await page.locator('#rw-hypothesis').fill('旋轉後必須保留的完整草稿與研究模式');
    const selected = await page.locator('#rw-current').inputValue();
    for (const [width, height] of [[375,812], [390,844], [430,932], [844,390], [1280,720], [1920,1080]]) {
      await checkLayout(page, width, height, `${width}×${height}`);
    }
    await checkLayout(page, 640, 360, '1280×720的200%等效寬度');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.locator('#rw-current').inputValue(), selected);
    assert.equal(await page.locator('#rw-symbol').inputValue(), '0050');
    assert.equal(await page.locator('#rw-hypothesis').inputValue(), '旋轉後必須保留的完整草稿與研究模式');
    report.checks.push('六尺寸、200%等效寬度與直橫旋轉保留選股、快照與草稿');

    // 透過正式介面整理公開資料，只保存 prepared；沒有讀取路由或呼叫模型。
    await page.locator('#rt-type').selectOption('changes'); await page.locator('#rt-freeze').click();
    await page.waitForFunction(() => document.getElementById('rt-status').textContent.includes('已凍結完整公開資料'));
    for (const [width, height] of [[375,812], [390,844], [430,932], [844,390], [1280,720], [1920,1080], [640,360]]) {
      await page.setViewportSize({ width, height }); await page.locator('#nav-updates').click();
      await page.waitForFunction(() => document.querySelector('#st-update-center .uc-local-jobs').textContent.includes('此紀錄只保存離線整理'));
      const localJobs = await geometry(page, '#st-update-center');
      assert.equal(localJobs.componentOverflow, false); assert.deepEqual(localJobs.clipped, []);
      await page.screenshot({ path: path.join(output, `${width}×${height}-本機研究工作.png`) });
      await page.keyboard.press('Escape');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'nav-updates');
    }
    report.checks.push('真實凍結操作形成 prepared 本機工作，七尺寸完整顯示離線整理及未呼叫模型前提');

    await page.locator('#nav-updates').focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.getElementById('st-update-center').open);
    const keyboard = [];
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press('Tab');
      const focus = await page.evaluate(() => ({ inside: document.getElementById('st-update-center').contains(document.activeElement),
        tag: document.activeElement.tagName, id: document.activeElement.id, documentFocused: document.hasFocus() }));
      keyboard.push(focus);
      // 原生 Chromium 允許 Tab 進入瀏覽器工具列；仍不可落到背景頁面控制項。
      assert(focus.inside || (focus.tag === 'BODY' && !focus.documentFocused), '對話框鍵盤焦點不可落到背景：' + JSON.stringify(focus));
    }
    report.keyboard = keyboard;
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'nav-updates');
    report.checks.push('Enter 開啟、原生對話框焦點隔離、Escape 回復入口且正式全域快捷鍵不切頁');

    await page.locator('#nav-updates').click();
    await page.locator('#st-update-center [data-submit="pulse"]').click();
    await page.waitForFunction(() => document.querySelector('#st-update-center .uc-jobs').textContent.includes('正式快照已提交'));
    await page.keyboard.press('Escape');
    report.checks.push('Owner 實際提交固定工作並讀取 HTTP 202 後的正式完成狀態');

    const beforeListeners = await listenerCounts(owner.context, page);
    for (let i = 0; i < 100; i++) {
      await page.locator('#nav-updates').click(); await page.keyboard.press('Escape');
      await page.locator('#nav-other').click(); await page.locator('#nav-research').click();
    }
    await frame(page);
    const cleanup = await page.evaluate(() => ({ ...UpdateJobs.diagnostics(), desks: document.querySelectorAll('#rw-root').length,
      centers: document.querySelectorAll('#st-update-center').length, title: document.getElementById('rw-title').value }));
    assert.equal(cleanup.subscribers, 0); assert.equal(cleanup.timers, 0); assert.equal(cleanup.requests, 0);
    assert.equal(cleanup.desks, 1); assert.equal(cleanup.centers, 1);
    const afterListeners = await listenerCounts(owner.context, page);
    assert.deepEqual(afterListeners, beforeListeners, '100 次進出不可增加全域與對話框事件監聽器');
    report.listeners = { before: beforeListeners, after: afterListeners };
    report.checks.push({ '100次進出清理': cleanup });

    const reader = await harness(browser, 'reader');
    await reader.page.locator('#nav-updates').click();
    await reader.page.waitForFunction(() => document.querySelector('#st-update-center .uc-readonly').textContent.includes('唯讀'));
    assert.equal(await reader.page.locator('#st-update-center [data-submit]:enabled').count(), 0);
    assert.equal(await reader.page.locator('#st-update-center [data-retry]').count(), 0);
    await reader.page.keyboard.press('Escape');
    assert.equal(await reader.page.locator('#rt-run').isDisabled(), true);
    assert.equal(await reader.page.locator('#rt-route-read').isDisabled(), true);
    await reader.page.locator('#rw-refresh').click(); await frame(reader.page);
    assert.equal(report.requests.filter(r => r.role === 'reader' && r.method !== 'GET').length, 0);
    report.checks.push('Reader 只送出讀取要求，更新、重試、模型執行與模型路由控制停用');
    await reader.context.close(); await owner.context.close();
    assert.deepEqual(report.pageErrors, [], '不可有未捕捉的瀏覽器錯誤');
    assert.equal(report.requests.filter(r => !r.fixture).length, 0, '全部網路要求必須命中固定資料');
    assert.equal(report.requests.filter(r => r.path.startsWith('/ai/')).length, 0, '不呼叫任何模型入口');
    report.passed = true;
  } catch (error) {
    report.passed = false; report.failure = error.stack || error.message;
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    fs.writeFileSync(path.join(output, '失敗-' + stamp + '.json'), JSON.stringify(report, null, 2));
    throw error;
  } finally {
    fs.writeFileSync(path.join(output, '驗收摘要.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
  console.log(JSON.stringify({ passed: report.passed, browser: report.browser, checks: report.checks.length,
    layouts: report.layouts.length, output }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });

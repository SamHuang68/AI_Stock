'use strict';

// 正式外殼與研究／投組／決策模組；只以固定來源驗證互動，不連線正式服務或模型。
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', '外殼研究互動驗收'));
const origin = 'https://st-shell-offline.test';
const modules = ['core/投組資料契約_v5.js', 'core/decision_data_v5.js', 'core/研究工作流.js', 'core/更新工作_v5.js',
  'ai/ai_runtime_client.js', 'core/研究任務.js', 'ui/研究任務面板.js',
  'ui/book_v5.js', 'ui/decision_v5.js', 'ui/研究工作台.js', 'ui/更新工作中心.js', 'ui/shell_v5.js'];
const sources = new Map(modules.map(file => ['/src/' + file, fs.readFileSync(path.join(root, 'src', file), 'utf8')]));
const report = { checks: [], requests: [], pageErrors: [], timings: [], sources: [...sources].map(([file, value]) => ({
  file, sha256Lf: crypto.createHash('sha256').update(value.replace(/\r\n/g, '\n')).digest('hex') })) };
const sessions = { premarket: '盤前', intraday: '盤中', afterhours: '盤後', closed: '休市' };
function snapshot(revision, session) {
  return { ok: true, snapshotId: 'dc-' + revision, revision, persistence: 'committed', contractVersion: 1,
    asOf: '2026-09-22T01:00:00+08:00', digest: String(revision).repeat(64), regime: { id: 'NEUTRAL', label: '研究觀察' },
    marketState: { session, label: sessions[session] }, dataQuality: { warnings: ['固定研究資料，來源時間並非現在'] },
    confirmation: ['固定確認條件：需下一份已提交證據支持'], invalidation: ['固定反方：成交與方向尚有分歧'],
    evidence: [{ id: 'fixture.support', evidenceId: 'dc-' + revision + ':fixture.support', digest: 'a'.repeat(64),
      metric: '支持與反方證據', value: revision, quality: 'observed', asOf: '2026-09-22', source: '固定來源',
      comparison: '固定支持：已保存量價；固定反方：資料仍有分歧，不自動給交易結論。' }] };
}
function html() {
  return '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<style>*{box-sizing:border-box}html,body{height:100%;margin:0;background:#071322;color:#e2e8f0}#app{height:100%;display:flex;flex-direction:column}#body{height:100%;min-height:0}button,input,textarea,select{font:14px sans-serif}</style></head><body>' +
    '<div id="app"><div id="body">固定圖表容器</div></div>' +
    '<script>window.ST_PRIVATE_WEB_PROFILE={profile:"personal-market",role:"owner"};window.SERVER="";window.S={positions:{},wl:[{t:"2330",m:"TW"},{t:"0050",m:"TW"}]};window.PulseV5={activate(){document.getElementById("mount-pulse").textContent="固定市場入口"},deactivate(){}};window.loadSym=function(sym,mkt){window.lastSymbol={sym,mkt}};</script>' +
    modules.map(file => '<script src="/src/' + file + '"></script>').join('') + '</body></html>';
}
async function frame(page) { await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))); }
async function geometry(page, selector) {
  return page.locator(selector).evaluate(root => {
    const clipped = [...root.querySelectorAll('button,summary,p,h2,h3,h4,pre,label')].filter(node => node.getClientRects().length && node.clientWidth).filter(node => {
      const css = getComputedStyle(node);
      return node.scrollWidth > node.clientWidth + 2 && !['auto', 'scroll'].includes(css.overflowX) ||
        node.scrollHeight > node.clientHeight + 2 && ['hidden', 'clip'].includes(css.overflowY);
    }).map(node => ({ tag: node.tagName, text: node.textContent.slice(0, 100) }));
    const rect = root.getBoundingClientRect();
    return { width: rect.width, rect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom },
      withinViewport: rect.left >= -2 && rect.top >= -2 && rect.right <= innerWidth + 2 && rect.bottom <= innerHeight + 2,
      clipped, pageOverflow: document.documentElement.scrollWidth > innerWidth + 2 };
  });
}
async function touchDrag(context, page, selector) {
  const box = await page.locator(selector).boundingBox();
  assert(box && box.width > 100 && box.height > 200, '觸控捲動區域必須可見');
  const x = Math.min(box.x + box.width / 2, (await page.viewportSize()).width / 2);
  const y = Math.min(box.y + box.height - 150, (await page.viewportSize()).height - 150);
  const before = await page.locator(selector).evaluate(node => node.scrollTop);
  const cdp = await context.newCDPSession(page);
  try {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
    for (let step = 1; step <= 12; step++) {
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y - step * 20 }] });
      await page.waitForTimeout(20);
    }
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    await page.waitForFunction(({ selector, before }) => document.querySelector(selector).scrollTop > before + 40, { selector, before });
  } finally { await cdp.detach(); }
  return { before, after: await page.locator(selector).evaluate(node => node.scrollTop) };
}
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.ST_BROWSER_CHANNEL ? { channel: process.env.ST_BROWSER_CHANNEL } : {}) });
  report.browser = browser.version();
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
  let scenario = 'premarket', offline = false, changed = true, delayWorkflowMs = 0;
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    report.requests.push({ path: url.pathname, query: url.search, method: req.method() });
    if (url.origin !== origin) return route.abort('blockedbyclient');
    if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html() });
    if (sources.has(decodeURIComponent(url.pathname))) return route.fulfill({ contentType: 'text/javascript', body: sources.get(decodeURIComponent(url.pathname)) });
    if (url.pathname === '/assets/st50-icon.svg') return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg"/>' });
    if (offline && url.pathname === '/updates') return route.abort('internetdisconnected');
    if (url.pathname === '/research/workflow' && delayWorkflowMs) await new Promise(resolve => setTimeout(resolve, delayWorkflowMs));
    const current = snapshot(2, scenario), previous = snapshot(1, scenario);
    let value;
    if (url.pathname === '/research/workflow') value = { ok: true, current, previous, history: [current, previous], nextBefore: null,
      changes: changed ? [{ key: 'confirmation', title: '固定重要變化與確認條件', kind: 'state', before: previous.confirmation, after: current.confirmation,
        fromSnapshotId: previous.snapshotId, toSnapshotId: current.snapshotId }] : [] };
    else if (url.pathname === '/pulse') value = { ok: true, updatedAt: current.asOf, decisionSummary: current };
    else if (url.pathname === '/decision/context') {
      value = req.method() === 'POST' ? { ...current, persistence: 'ephemeral', parentSnapshotId: current.snapshotId } : current;
      if (req.method() === 'POST') delete value.snapshotId;
    }
    else if (url.pathname === '/decision/history') value = { ok: true, snapshots: [], items: [], history: [] };
    else if (url.pathname === '/updates') value = { ok: true, jobs: [{ jobId: 'r-fixture', type: 'research', status: 'succeeded', stage: '固定已完成工作', queuedAt: '2026-09-22T00:00:00Z' }],
      capabilities: { canSubmit: false, canRetry: false, types: [] }, workers: {} };
    else if (url.pathname === '/health') value = { ok: true };
    else if (url.pathname === '/gateway/whoami') value = { role: 'owner' };
    else if (url.pathname === '/research/overnight-intraday') value = { ok: true, markets: {}, available: false };
    else if (url.pathname === '/sync/status') value = { ok: true, running: false, counts: { index: 100 } };
    else if (url.pathname === '/diagnostics/ui-route') value = { ok: true };
    else if (url.pathname === '/portfolio') value = { stocks: {}, portfolio: { var95: null, vol: null, days: 0 }, benchmark: '^TWII', skipped: ['2330', '0050'] };
    else { report.unexpected = (report.unexpected || []).concat(url.pathname); return route.abort('blockedbyclient'); }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) });
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.pageErrors.push(error.message));
  try {
    await page.goto(origin); await page.waitForFunction(() => window.ShellV5 && document.documentElement.classList.contains('st5-booted'));
    await page.waitForTimeout(220); await page.evaluate(() => { ShellV5.closeRing(); ShellV5.go('research'); });
    await page.waitForFunction(() => document.getElementById('rw-changes').textContent.includes('dc-2'));
    for (const [session, label] of Object.entries(sessions)) {
      scenario = session;
      const start = performance.now();
      await page.locator('#rw-refresh').tap();
      await page.waitForFunction(label => document.getElementById('rw-evidence').textContent.includes(label), label);
      assert((await page.locator('#rw-changes').textContent()).includes('2026-09-22T01:00:00+08:00'));
      const asOfMs = performance.now() - start;
      await page.locator('#rw-evidence details').first().locator('summary').tap();
      assert((await page.locator('#rw-evidence details').first().innerText()).includes('固定反方'));
      const evidenceMs = performance.now() - start;
      assert(asOfMs < 10000 && evidenceMs < 60000, label + ' 固定互動流程超出有界目標');
      report.timings.push({ session, label, asOfMs: Math.round(asOfMs), evidenceMs: Math.round(evidenceMs), humanReading: false });
    }
    changed = false; await page.locator('#rw-refresh').tap();
    await page.waitForFunction(() => document.getElementById('rw-changes').textContent.includes('沒有可確認的新狀態變化'));
    assert((await page.locator('#rw-changes').textContent()).includes('比較 2026-09-22T01:00:00+08:00'));
    report.checks.push('四盤別固定資料以實際觸控完成時點、比較基準、支持及反方或無變化流程；計時不代表真人閱讀速度');

    await page.locator('#rw-root details').evaluateAll(nodes => nodes.forEach(node => { node.open = true; }));
    await page.locator('#shell-views').evaluate(node => { node.scrollTop = 0; }); await frame(page);
    report.touch = await touchDrag(context, page, '#shell-views');
    await page.waitForTimeout(250);
    const savedPosition = await page.locator('#shell-views').evaluate(node => node.scrollTop);
    delayWorkflowMs = 700;
    await page.evaluate(() => document.getElementById('rw-refresh').click());
    await page.waitForTimeout(30);
    await page.evaluate(() => ShellV5.go('chart', { sym: '2330', mkt: 'TW' })); await frame(page);
    assert.equal(await page.locator('#shell-views').evaluate(node => node.scrollTop), 0);
    await page.evaluate(() => ShellV5.go('research')); await frame(page);
    assert(Math.abs(await page.locator('#shell-views').evaluate(node => node.scrollTop) - savedPosition) < 2, '研究返回須保留外層閱讀位置');
    await page.waitForTimeout(800);
    assert(Math.abs(await page.locator('#shell-views').evaluate(node => node.scrollTop) - savedPosition) < 2, '被中止的慢回應返回後仍保留原研究DOM及閱讀位置');
    delayWorkflowMs = 0;
    await page.evaluate(() => { ShellV5.go('chart'); ShellV5.go('research'); ShellV5.go('book'); }); await frame(page);
    assert.equal(await page.evaluate(() => ShellV5.route()), 'book');
    assert.equal(await page.locator('#shell-views').evaluate(node => node.scrollTop), 0, '舊恢復不可改寫最後路由');
    report.checks.push('真正觸控拖曳移動閱讀位置；返回可回復，首次新頁及快速逆序路由不沿用錯誤位置');

    await page.evaluate(() => ShellV5.go('research', { focusSection: 'summary' })); await frame(page);
    assert.equal(await page.locator('#shell-views').evaluate(node => node.scrollTop), 0, '深連結不得套用舊閱讀位置');
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.evaluate(() => { document.documentElement.style.zoom = '2'; }); await frame(page);
    const zoom = await geometry(page, '#rw-root');
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).zoom), '2');
    assert.equal(zoom.pageOverflow, false); assert.deepEqual(zoom.clipped, []);
    await page.locator('#rw-updates').tap(); await page.waitForFunction(() => document.getElementById('st-update-center').open);
    const zoomUpdates = await geometry(page, '#st-update-center'); assert.deepEqual(zoomUpdates.clipped, []);
    assert.equal(zoomUpdates.withinViewport, true, '放大後更新中心標題、關閉及全部可捲動內容必須在視窗內');
    await page.screenshot({ path: path.join(output, '200%原生CSS放大-更新中心.png') });
    await page.keyboard.press('Escape');
    await page.screenshot({ path: path.join(output, '200%原生CSS放大-研究.png') });
    await page.evaluate(() => { document.documentElement.style.zoom = ''; });
    report.zoom = { method: 'Chromium 原生 CSS zoom:2（整體內容兩倍）；另有 640×360 的重排驗證，不冒稱 OS 字型設定', research: zoom, updates: zoomUpdates };
    report.checks.push('內容實際放大200%仍能閱讀完整研究、觸控開啟更新中心及鍵盤關閉');

    await page.setViewportSize({ width: 640, height: 360 });
    const magnification = await context.newCDPSession(page);
    await magnification.send('Emulation.setDeviceMetricsOverride', { width: 640, height: 360, deviceScaleFactor: 2, mobile: false });
    await frame(page);
    assert.deepEqual(await page.evaluate(() => ({ width: innerWidth, ratio: devicePixelRatio })), { width: 640, ratio: 2 });
    const equivalentResearch = await geometry(page, '#rw-root');
    assert.equal(equivalentResearch.pageOverflow, false); assert.deepEqual(equivalentResearch.clipped, []);
    await page.locator('#rw-updates').tap();
    await page.waitForFunction(() => document.getElementById('st-update-center').open);
    const equivalentUpdates = await geometry(page, '#st-update-center');
    assert.equal(equivalentUpdates.withinViewport, true); assert.deepEqual(equivalentUpdates.clipped, []);
    const magnifiedPng = Buffer.from((await magnification.send('Page.captureScreenshot', { format: 'png', fromSurface: true })).data, 'base64');
    fs.writeFileSync(path.join(output, '200%瀏覽器縮放等效-更新中心.png'), magnifiedPng);
    assert.equal(magnifiedPng.readUInt32BE(16), 1280); assert.equal(magnifiedPng.readUInt32BE(20), 720);
    await page.keyboard.press('Escape');
    fs.writeFileSync(path.join(output, '200%瀏覽器縮放等效-研究.png'), Buffer.from((await magnification.send('Page.captureScreenshot', { format: 'png', fromSurface: true })).data, 'base64'));
    report.magnificationEquivalent = { method: '640×360 CSS 視窗及 DPR2，輸出1280×720，文字與控制項實體像素兩倍；未操作瀏覽器GUI或OS字型設定', research: equivalentResearch, updates: equivalentUpdates };
    await magnification.send('Emulation.clearDeviceMetricsOverride'); await magnification.detach();
    await page.setViewportSize({ width: 390, height: 844 });
    report.checks.push('200%瀏覽器縮放等效下完整內容重排、觸控與關閉焦點可用，輸出為1280×720');

    await page.locator('#rw-updates').tap(); await page.waitForFunction(() => document.querySelector('#st-update-center .uc-jobs').textContent.includes('固定已完成工作'));
    offline = true; await page.evaluate(() => UpdateJobs.refresh());
    await page.waitForFunction(() => !!UpdateJobs.snapshot().error);
    assert((await page.locator('#st-update-center .uc-jobs').first().innerText()).includes('固定已完成工作'), '斷網保留最後已知工作');
    await page.evaluate(() => {
      window.originalDate = Date; window.sleeping = true;
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => window.sleeping });
      document.dispatchEvent(new Event('visibilitychange'));
      window.Date = class extends originalDate { constructor(...args) { super(...(args.length ? args : [originalDate.now() + 8 * 3600000])); } static now() { return originalDate.now() + 8 * 3600000; } };
    });
    assert.deepEqual(await page.evaluate(() => UpdateJobs.diagnostics()), { subscribers: 1, timers: 0, requests: 0 });
    offline = false;
    await page.evaluate(() => { window.sleeping = false; document.dispatchEvent(new Event('visibilitychange')); });
    await page.waitForFunction(() => !UpdateJobs.snapshot().error && UpdateJobs.snapshot().jobs.length === 1);
    assert.equal(report.requests.filter(row => row.method === 'POST' && row.path === '/updates').length, 0, '恢復不可重送來源更新');
    await page.keyboard.press('Escape'); await page.evaluate(() => { window.Date = originalDate; delete document.hidden; });
    assert.deepEqual(await page.evaluate(() => UpdateJobs.diagnostics()), { subscribers: 0, timers: 0, requests: 0 });
    report.checks.push('真實fetch斷網錯誤保留前次工作，模擬八小時時鐘間隔及重新可見可恢復純讀；未休眠主機');

    const privateBefore = await page.evaluate(() => JSON.stringify(S.positions));
    const simulationText = 'TW:2330 40\n0050 60';
    await page.evaluate(() => ShellV5.go('book')); await page.waitForFunction(() => !!document.getElementById('bk-edit'));
    await page.locator('[data-src="simulation"]').tap();
    await page.locator('#bk-edit').fill(simulationText);
    await page.waitForFunction(() => PortfolioContext.getMode() === 'simulation');
    assert.equal(await page.evaluate(() => PortfolioContext.getSimulation()), simulationText);
    await page.evaluate(() => ShellV5.go('decision'));
    await page.waitForFunction(() => document.getElementById('dc-use-simulation')?.getAttribute('aria-pressed') === 'true');
    assert((await page.locator('#dc-portfolio-status').innerText()).includes('模擬'));
    await page.locator('#dc-ai-btn').tap();
    await page.waitForFunction(() => !!document.querySelector('#dc-research-panel #rt-freeze'));
    assert.equal(report.requests.filter(row => row.path === '/research/workflow').at(-1).query, '?current=dc-2', '私人疊加必須精確引用父快照');
    await page.locator('#dc-research-panel #rt-freeze').tap();
    await page.waitForFunction(() => document.querySelector('#dc-research-panel #rt-status').textContent.includes('已凍結完整公開資料'));
    assert.equal(await page.locator('#dc-research-panel #rt-run').isDisabled(), true);
    await page.locator('#dc-research-close').tap();
    await page.evaluate(() => ShellV5.go('research')); await frame(page);
    assert.equal(await page.locator('#rw-portfolio-mode').inputValue(), 'simulation');
    assert((await page.locator('#rw-portfolio-source').innerText()).includes('模擬'));
    await page.locator('#rw-root #rt-freeze').tap();
    await page.waitForFunction(() => document.querySelector('#rw-root #rt-status').textContent.includes('已凍結完整公開資料'));
    await page.locator('#rw-portfolio-mode').selectOption('observation_pool');
    await page.evaluate(() => ShellV5.go('decision'));
    await page.waitForFunction(() => document.getElementById('dc-use-watch')?.getAttribute('aria-pressed') === 'true');
    await page.locator('#dc-use-positions').tap();
    await page.evaluate(() => ShellV5.go('book')); await frame(page);
    assert.equal(await page.evaluate(() => PortfolioContext.getMode()), 'actual');
    assert.equal(await page.evaluate(() => JSON.stringify(S.positions)), privateBefore);
    await page.locator('[data-src="simulation"]').tap();
    assert.equal(await page.locator('#bk-edit').inputValue(), simulationText);
    await page.reload(); await page.waitForFunction(() => window.ShellV5 && document.documentElement.classList.contains('st5-booted'));
    await page.waitForTimeout(220); await page.evaluate(() => { ShellV5.closeRing(); ShellV5.go('book'); }); await frame(page);
    assert.equal(await page.evaluate(() => PortfolioContext.getMode()), 'simulation');
    assert.equal(await page.locator('#bk-edit').inputValue(), simulationText);
    assert.equal(await page.evaluate(() => JSON.stringify(S.positions)), privateBefore);
    report.checks.push('實際→情境→決策→研究→觀察池→實際跨頁一致，模擬輸入可重載且不改真實持倉');
    report.checks.push('舊決策 AI 入口只凍結完整公開包；決策與研究來回後各自面板可操作且沒有模型要求');

    assert.deepEqual(report.pageErrors, []); assert.deepEqual(report.unexpected || [], []);
    assert.equal(report.requests.filter(row => row.path.startsWith('/ai/')).length, 0);
    report.passed = true;
  } catch (error) {
    report.passed = false; report.failure = error.stack;
    report.failureState = await page.evaluate(() => ({ mode: window.PortfolioContext && PortfolioContext.getMode(),
      buttons: [...document.querySelectorAll('.dc-source-btn')].map(node => ({ id: node.id, pressed: node.getAttribute('aria-pressed') })),
      status: document.getElementById('dc-portfolio-status')?.textContent, researchMode: document.getElementById('rw-portfolio-mode')?.value,
      decisionData: window.DecisionData && DecisionData.snapshot && DecisionData.snapshot() }));
    report.failureSurfaces = await page.evaluate(() => [...document.querySelectorAll('html,body,#app,#shell-main,#shell-views,.sv-panel.on,#rw-root')].map(node => ({ id: node.id || node.tagName,
      width: node.clientWidth, height: node.clientHeight, top: node.scrollTop, scrollHeight: node.scrollHeight, overflow: getComputedStyle(node).overflowY })));
    await page.screenshot({ path: path.join(output, '失敗.png') });
    throw error;
  }
  finally { fs.writeFileSync(path.join(output, '外殼研究互動.json'), JSON.stringify(report, null, 2)); await browser.close(); }
  console.log(JSON.stringify({ passed: report.passed, checks: report.checks.length, output }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });

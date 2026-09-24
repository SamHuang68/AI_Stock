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
async function updateTriggerState(page) {
  return page.evaluate(() => {
    const button = document.getElementById('rw-updates');
    const rect = button && button.getBoundingClientRect();
    const at = rect && document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    const dialog = document.getElementById('st-update-center');
    return {
      route: window.ShellV5 && ShellV5.route(),
      zoom: getComputedStyle(document.documentElement).zoom,
      viewport: { width: innerWidth, height: innerHeight, ratio: devicePixelRatio, visualScale: visualViewport && visualViewport.scale },
      button: rect && { x: rect.x, y: rect.y, width: rect.width, height: rect.height, disabled: button.disabled, hasClick: typeof button.onclick === 'function' },
      elementAtCenter: at && { tag: at.tagName, id: at.id, text: (at.textContent || '').slice(0, 60) },
      dialog: dialog && { open: dialog.open, modal: dialog.matches(':modal') },
      events: window.auditTouchEvents || []
    };
  });
}
async function openUpdates(page) {
  // 仍用 locator.tap，不補合成 click。前後證據只供失敗時對照，不改產品按鈕。
  await page.evaluate(() => { window.auditTouchEvents = []; });
  const evidence = { before: await updateTriggerState(page), playwrightBox: await page.locator('#rw-updates').boundingBox() };
  (report.openings || (report.openings = [])).push(evidence);
  try {
    await page.locator('#rw-updates').tap();
    const opened = page.locator('#st-update-center[open]');
    await opened.waitFor({ state: 'visible' });
    assert.equal(await opened.evaluate(node => node.matches(':modal')), true, '更新中心必須實際開啟為模態對話框');
    assert.equal(await page.evaluate(() => ShellV5.route()), 'research', '開啟更新中心不可切離研究頁');
  } finally { evidence.after = await updateTriggerState(page); }
}
async function closeUpdates(page) {
  await page.keyboard.press('Escape');
  await page.locator('#st-update-center').waitFor({ state: 'hidden' });
  assert.equal(await page.locator('#st-update-center').count(), 1, '關閉應保留既有對話框供再次開啟');
  assert.equal(await page.evaluate(() => ShellV5.route()), 'research', '關閉更新中心不可切離研究頁');
}
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
  // 落在按鈕或輸入框上的合成手勢只會觸發 touch，不會捲動外層。改點在非控制項的內容上。
  const point = await page.locator(selector).evaluate(node => {
    const rect = node.getBoundingClientRect();
    const blocksScroll = (el) => el && el.closest('button,a,input,textarea,select,summary,label,[role="button"]');
    for (let y = rect.top + 48; y < Math.min(rect.bottom, innerHeight) - 24; y += 20) {
      const x = Math.min(Math.max(rect.left + 24, rect.left + rect.width / 2), innerWidth - 8);
      const el = document.elementFromPoint(x, y);
      if (!el || !node.contains(el) || blocksScroll(el)) continue;
      return { x, y, tag: el.tagName, id: el.id || '' };
    }
    return null;
  });
  assert(point, '必須在捲動區內找到不會攔截捲動的觸控點');
  const { x, y } = point;
  const before = await page.locator(selector).evaluate(node => node.scrollTop);
  // 合成捲動手勢常常不送出 trusted touch。稽核可以記下，但完成條件只看目標區真的捲動並且停住。
  await page.evaluate(selector => {
    const node = document.querySelector(selector);
    const audit = {
      trustedStart: false, trustedEnd: false, scrollEnd: false, samples: [],
      releasedAt: null, gestureCompletedAt: null, settledTop: null, settledBy: null, before: node.scrollTop
    };
    window.auditDragCompletion = audit;
    const remember = (entry) => {
      audit.samples.push(entry);
      if (audit.samples.length > 80) audit.samples.shift();
    };
    const onTouch = (event) => {
      if (event.type === 'touchstart' && event.isTrusted) audit.trustedStart = true;
      if (event.type === 'touchend' && event.isTrusted) {
        audit.trustedEnd = true;
        audit.releasedAt = performance.now();
      }
      remember({ type: event.type, trusted: event.isTrusted, top: node.scrollTop, time: performance.now() });
    };
    const onScroll = () => remember({ type: 'scroll', top: node.scrollTop, time: performance.now() });
    const onScrollEnd = () => {
      const top = node.scrollTop;
      // 手勢開始前可能先出現 scrollTop 仍為 0 的 scrollend，那不是捲動完成。
      if (top > audit.before + 40) {
        audit.scrollEnd = true;
        audit.scrollEndTop = top;
      }
      remember({ type: 'scrollend', top, time: performance.now() });
    };
    node.addEventListener('touchstart', onTouch, true);
    node.addEventListener('touchend', onTouch, true);
    node.addEventListener('scroll', onScroll, { passive: true });
    node.addEventListener('scrollend', onScrollEnd);
    window.__auditDragCleanup = () => {
      node.removeEventListener('touchstart', onTouch, true);
      node.removeEventListener('touchend', onTouch, true);
      node.removeEventListener('scroll', onScroll);
      node.removeEventListener('scrollend', onScrollEnd);
    };
  }, selector);
  const cdp = await context.newCDPSession(page);
  try {
    // 協議裡 yDistance 正值是向上捲。負值才會增加 scrollTop。
    // 觸控來源在這版 Chromium 只送出 touchstart／touchend，scrollTop 不會變；滑鼠來源才會真正捲動。
    // trusted touch 只留在稽核，缺少時不視為失敗。
    await cdp.send('Input.synthesizeScrollGesture', {
      x, y, yDistance: -240, gestureSourceType: 'mouse', preventFling: true, speed: 800
    });
    await page.evaluate(selector => {
      const audit = window.auditDragCompletion;
      const node = document.querySelector(selector);
      audit.gestureCompletedAt = performance.now();
      audit.settledTop = node ? node.scrollTop : null;
    }, selector);
    await page.waitForFunction(({ selector, before }) => {
      const node = document.querySelector(selector);
      const audit = window.auditDragCompletion;
      if (!node || !audit) return false;
      const top = node.scrollTop;
      if (!(top > before + 40)) return false;
      if (audit.scrollEnd && top === audit.scrollEndTop) {
        audit.settledTop = top;
        audit.settledBy = 'scrollend';
        return true;
      }
      const now = performance.now();
      if (audit.stableTop !== top) {
        audit.stableTop = top;
        audit.stableSince = now;
        return false;
      }
      if (now - audit.stableSince < 150) return false;
      audit.settledTop = top;
      audit.settledBy = 'scrollTop-stable';
      return true;
    }, { selector, before });
  } finally {
    await page.evaluate(() => { if (window.__auditDragCleanup) window.__auditDragCleanup(); }).catch(() => {});
    await cdp.detach();
  }
  const after = await page.locator(selector).evaluate(node => node.scrollTop);
  const audit = await page.evaluate(() => window.auditDragCompletion);
  assert(after > before + 40, '觸控手勢必須真正捲動目標區域');
  return { before, after, audit };
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
  await context.addInitScript(() => {
    window.auditTouchEvents = [];
    const record = (event) => {
      const target = event.target;
      const id = target && target.id;
      const onUpdates = id === 'rw-updates' || !!(target && target.closest && target.closest('#rw-updates'));
      if (!onUpdates) return;
      if ((event.type === 'pointermove' || event.type === 'touchmove') && id !== 'rw-updates') return;
      const list = window.auditTouchEvents;
      if (list.length >= 100) return;
      list.push({ type: event.type, trusted: event.isTrusted, id: id || '', time: performance.now() });
    };
    for (const type of ['pointerdown', 'pointerup', 'pointermove', 'pointercancel', 'touchstart', 'touchend', 'touchmove', 'touchcancel', 'click']) {
      document.addEventListener(type, record, true);
    }
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.pageErrors.push(error.message));
  try {
    await page.goto(origin); await page.waitForFunction(() => window.ShellV5 && document.documentElement.classList.contains('st5-booted'));
    await page.waitForFunction(() => ShellV5.isRingOpen());
    await page.evaluate(() => { ShellV5.closeRing(); ShellV5.go('research'); });
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
    await openUpdates(page);
    const zoomUpdates = await geometry(page, '#st-update-center'); assert.deepEqual(zoomUpdates.clipped, []);
    assert.equal(zoomUpdates.withinViewport, true, '放大後更新中心標題、關閉及全部可捲動內容必須在視窗內');
    await page.screenshot({ path: path.join(output, '200%原生CSS放大-更新中心.png') });
    await closeUpdates(page);
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
    await openUpdates(page);
    const equivalentUpdates = await geometry(page, '#st-update-center');
    assert.equal(equivalentUpdates.withinViewport, true); assert.deepEqual(equivalentUpdates.clipped, []);
    const magnifiedPng = Buffer.from((await magnification.send('Page.captureScreenshot', { format: 'png', fromSurface: true })).data, 'base64');
    fs.writeFileSync(path.join(output, '200%瀏覽器縮放等效-更新中心.png'), magnifiedPng);
    assert.equal(magnifiedPng.readUInt32BE(16), 1280); assert.equal(magnifiedPng.readUInt32BE(20), 720);
    await closeUpdates(page);
    fs.writeFileSync(path.join(output, '200%瀏覽器縮放等效-研究.png'), Buffer.from((await magnification.send('Page.captureScreenshot', { format: 'png', fromSurface: true })).data, 'base64'));
    report.magnificationEquivalent = { method: '640×360 CSS 視窗及 DPR2，輸出1280×720，文字與控制項實體像素兩倍；未操作瀏覽器GUI或OS字型設定', research: equivalentResearch, updates: equivalentUpdates };
    await magnification.send('Emulation.clearDeviceMetricsOverride'); await magnification.detach();
    await page.setViewportSize({ width: 390, height: 844 });
    report.checks.push('200%瀏覽器縮放等效下完整內容重排、觸控與關閉焦點可用，輸出為1280×720');

    await openUpdates(page);
    await page.waitForFunction(() => document.querySelector('#st-update-center[open] .uc-jobs')?.textContent.includes('固定已完成工作'));
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
    await closeUpdates(page); await page.evaluate(() => { window.Date = originalDate; delete document.hidden; });
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
    await page.waitForFunction(() => ShellV5.isRingOpen());
    await page.evaluate(() => { ShellV5.closeRing(); ShellV5.go('book'); }); await frame(page);
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
      decisionData: window.DecisionData && DecisionData.snapshot && DecisionData.snapshot(),
      drag: window.auditDragCompletion }));
    report.failureSurfaces = await page.evaluate(() => [...document.querySelectorAll('html,body,#app,#shell-main,#shell-views,.sv-panel.on,#rw-root')].map(node => ({ id: node.id || node.tagName,
      width: node.clientWidth, height: node.clientHeight, top: node.scrollTop, scrollHeight: node.scrollHeight, overflow: getComputedStyle(node).overflowY })));
    console.error(JSON.stringify({ openings: report.openings || [], failureState: report.failureState, failureSurfaces: report.failureSurfaces, pageErrors: report.pageErrors }, null, 2));
    await page.screenshot({ path: path.join(output, '失敗.png') });
    throw error;
  }
  finally { fs.writeFileSync(path.join(output, '外殼研究互動.json'), JSON.stringify(report, null, 2)); await browser.close(); }
  console.log(JSON.stringify({ passed: report.passed, checks: report.checks.length, output }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });

/* 正式 WaveDeck HTML／JS 的失敗恢復與開頁回歸；所有請求由離線 fixture 回覆。 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(process.env.ST_PLAYWRIGHT || process.env.PLAYWRIGHT_PATH || 'playwright');
const root = path.resolve(__dirname, '..');

const initial = {
  fsm: 'Flat', mode: 'paper', symbol: 'TXF', style: 50, kill_switch: false,
  positions: { account: 0, strategy: 0, txt_target: 0, ai_suggested: 0 },
  strategy_execution: { mode: 'discretionary' }, no_overnight: { enabled: false },
  exec: { price: 45020, lots: 0 }, ai: { action: 'HOLD', process: {}, next_watch: [] },
  account: {}, costs: { provider: 'heuristic' }, lights: { system: 'run' },
  st_link: { status: 'up', fail_safe: false }, st_overlay: {}, transport: {}
};

async function fixture(browser, options = {}) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const controls = { state: structuredClone(initial), stateReads: 0, bridgeReads: 0,
    stateFailures: 0, stOnline: true, score: 80, calls: [], errors: [], ...options };
  page.on('pageerror', error => controls.errors.push(error.message));
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (value, status = 200) => route.fulfill({ status, contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type' }, body: JSON.stringify(value) });
    if (url.hostname === '127.0.0.1' && url.port === '18432') {
      if (url.pathname === '/bridge/wavedeck' && request.method() === 'GET') {
        controls.bridgeReads++;
        return json({ ok: controls.stOnline }, controls.stOnline ? 200 : 503);
      }
      if (decodeURIComponent(url.pathname) === '/fundamental/^TWII') {
        return controls.fundamentalFailure ? json({ ok: false }, 503) : json({ score: controls.score, label: '測試資料' });
      }
      if (url.pathname === '/breadth') return json({ stocks: { advRatio: 0.5, up: 50, down: 50 } });
      if (url.pathname === '/twindex') return json({ indices: { t00: { price: 45020, changePct: 1 } } });
      return json({ ok: true });
    }
    if (url.hostname !== 'wd-fixture.test') return route.abort();
    if (['/', '/js/deck.js', '/css/deck.css'].includes(url.pathname)) {
      const file = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      return route.fulfill({ status: 200, contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html',
        body: await fs.readFile(path.join(root, 'wavedeck/web', file), 'utf8') });
    }
    if (url.pathname === '/api/state') {
      controls.stateReads++;
      if (controls.stateReads <= controls.stateFailures) return json({ ok: false, error: '暫時無法讀取狀態' }, 503);
    }
    if (url.pathname === '/api/exec_md/latest') return json({ ok: true, file: '<測試>.md', markdown: '# 執行細節\n<script>window.injected=true</script>\n資料完整' });
    if (request.method() === 'POST') {
      const body = request.postDataJSON();
      controls.calls.push({ path: url.pathname, body });
      if (url.pathname === '/api/kill') controls.state.kill_switch = body.on;
      if (url.pathname === '/bridge/st') {
        controls.state.st_overlay.fail_safe = false;
        controls.state.st_link.fail_safe = false;
      }
      if (url.pathname === '/api/style') controls.state.style = controls.appliedStyle ?? body.style;
    }
    return json({ ok: true, state: controls.state });
  });
  await page.goto('http://wd-fixture.test/');
  return { context, page, controls };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    {
      const { context, page, controls } = await fixture(browser, { stateFailures: 1 });
      try {
        await page.waitForFunction(() => document.getElementById('wdSyncTxt').textContent === 'ERR');
        await page.locator('#btnKill').click();
        await page.waitForFunction(() => document.getElementById('toast').textContent.includes('暫停新單'));
        assert.equal(controls.calls.filter(call => call.path === '/api/kill').length, 1);
        await page.waitForFunction(() => document.getElementById('wdSyncTxt').textContent === 'OK', null, { timeout: 5000 });
        assert.ok(controls.stateReads >= 2, '首次 503 後必須自動再次讀取狀態');
        assert.deepEqual(controls.errors, []);
      } finally { await context.close(); }
    }
    {
      const { context, page, controls } = await fixture(browser);
      try {
        await page.waitForFunction(() => document.getElementById('stStyle').textContent.includes('65'));
        controls.stOnline = false;
        await page.locator('#btnPullSt').click();
        await page.waitForFunction(() => document.getElementById('toast').textContent.includes('未套用舊資料'));
        assert.ok(controls.bridgeReads >= 2);
        controls.stOnline = true;
        controls.fundamentalFailure = true;
        await page.locator('#btnPullSt').click();
        await page.waitForFunction(() => !document.getElementById('btnPullSt').disabled);
        assert.ok(controls.bridgeReads >= 3, 'bridge 成功但建議資料失敗仍不得重用舊值');
        assert.match(await page.locator('#toast').textContent(), /未套用舊資料/);
        assert.equal(controls.calls.filter(call => ['/bridge/st', '/api/style'].includes(call.path)).length, 0);
        assert.deepEqual(controls.errors, []);
      } finally { await context.close(); }
    }
    {
      const { context, page, controls } = await fixture(browser, { score: 20, appliedStyle: 55 });
      try {
        await page.waitForFunction(() => document.getElementById('stStyle').textContent.includes('35'));
        controls.score = 80;
        controls.state.st_link.fail_safe = true;
        controls.state.st_overlay.fail_safe = true;
        await page.waitForFunction(() => !document.getElementById('fsBadge').hidden, null, { timeout: 5000 });
        await page.locator('#btnPullSt').click();
        await page.waitForFunction(() => document.getElementById('toast').textContent === '已套用 ST 建議風格 → 55');
        const bridge = controls.calls.find(call => call.path === '/bridge/st');
        assert.equal(bridge.body.style, 65, '人工套用須使用重新取得的建議，保留人工解除 fail-safe 政策');
        assert.equal(controls.calls.find(call => call.path === '/api/style').body.style, 65);
        assert.equal(controls.state.st_link.fail_safe, false);
        assert.deepEqual(controls.errors, []);
      } finally { await context.close(); }
    }
    {
      const { context, page, controls } = await fixture(browser);
      try {
        const popupReady = context.waitForEvent('page');
        await page.locator('#btnExecMd').click();
        const popup = await popupReady;
        await popup.waitForLoadState('domcontentloaded');
        assert.match(popup.url(), /^blob:/);
        assert.equal(await popup.title(), '<測試>.md');
        assert.match(await popup.locator('pre').textContent(), /<script>window.injected=true<\/script>/);
        assert.equal(await popup.evaluate(() => window.opener), null);
        assert.equal(await popup.evaluate(() => window.injected), undefined);
        assert.doesNotMatch(await page.locator('#toast').textContent(), /彈窗被擋/);
        assert.deepEqual(controls.errors, []);
      } finally { await context.close(); }
    }
    console.log(JSON.stringify({ result: '通過', cases: ['首次503恢復與控制', '拒絕舊ST建議', '新建議與人工解除政策', '完整MD與opener隔離'] }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

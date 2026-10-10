/* 正式介面搭配隔離 API；不連線正式服務、不送交易。 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const playwrightModule = process.env.ST_PLAYWRIGHT || process.env.PLAYWRIGHT_PATH || 'playwright';
const root = path.resolve(__dirname, '..');
const evidence = process.env.WD_UI_EVIDENCE || process.env.E || path.join(root, 'scratch', 'WD策略介面');
const baseline = process.argv.includes('--baseline');
const baselineRef = 'f2db8085851c44e76f21d519b601ca820d4f733a';
const initialState = {
  fsm: 'InPosition', mode: 'paper', symbol: 'TXF', style: 50, kill_switch: false,
  positions: { account: 1, strategy: 1, txt_target: 1, ai_suggested: 1 },
  no_overnight: { enabled: true, force_flat_time: '13:40', block_new_before_close_min: 15 },
  strategy_execution: { mode: 'discretionary' },
  exec: { price: 45020, lots: 1, last_order_action: '模擬多單', last_ai_action: '維持續抱' },
  ai: { action: 'HOLD', action_label: '維持續抱', confidence: 0.72, bias_long: 0.6, bias_short: 0.4, summary: '價格仍在既定區間，等待完整訊號。', reasoning: '保持原有倉位與風險資訊。', next_watch: ['價格區間', '截止時間'], process: { gate: 'PASS' } },
  account: { yesterday_balance: 100000, equity: 101000, source: 'paper', position_sync: 'synced' },
  costs: { provider: 'heuristic', session_usd: 0, day_usd: 0, month_usd: 0 },
  lights: { system: 'run', broker_api: 'ok', position_sync: 'ok', kill_switch: 'off', webhook: 'ok', openai_or_local: 'ok', st_bridge: 'ok' },
  st_link: { status: 'ok' }, st_overlay: { spillover_prob: 0.6 },
  transport: { webhook: 'ready', last_webhook_status: '待命', last_tv_event: '離線驗證', tunnel: 'local' }
};

(async () => {
  await fs.mkdir(evidence, { recursive: true });
  const baselineAssets = new Map();
  if (baseline) {
    try {
      for (const file of ['index.html', 'js/deck.js', 'css/deck.css']) {
        baselineAssets.set(file, execFileSync('git', ['show', `${baselineRef}:wavedeck/web/${file}`], {
          cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
        }));
      }
    } catch (error) {
      const skipped = { result: '略過修改前截圖', baseline_ref: baselineRef, reason: '固定基準版本或必要檔案無法讀取；未改用目前版本。' };
      await fs.writeFile(path.join(evidence, 'WD修改前.json'), JSON.stringify(skipped, null, 2));
      console.log(JSON.stringify(skipped));
      return;
    }
  }
  const { chromium } = require(playwrightModule);
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport, locale: 'zh-TW' });
      let state = structuredClone(initialState);
      const calls = [];
      const errors = [];
      let rejectRegister = false;
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.hostname !== 'wd-fixture.test') return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
        const pathname = url.pathname;
        if (pathname === '/' || pathname === '/js/deck.js' || pathname === '/css/deck.css') {
          const file = pathname === '/' ? 'index.html' : pathname.slice(1);
          return route.fulfill({ status: 200, contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html', body: baseline ? baselineAssets.get(file) : await fs.readFile(path.join(root, 'wavedeck/web', file), 'utf8') });
        }
        const body = route.request().postDataJSON();
        if (route.request().method() === 'POST') calls.push({ path: pathname, body });
        if (pathname === '/api/strategy/register' && rejectRegister) {
          rejectRegister = false;
          return route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ ok: false, error: '版本雜湊不符，請重新匯出' }) });
        }
        if (pathname === '/api/style') state.style = body.style;
        if (pathname === '/api/no_overnight') state.no_overnight = body;
        if (pathname === '/api/strategy/activate') state.strategy_execution = body;
        if (pathname === '/api/strategy/mode') state.strategy_execution.mode = body.mode;
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, state, manifest: body && body.manifest, mode: state.mode }) });
      });
      await page.goto('http://wd-fixture.test/');
      await page.locator('#posKv').waitFor();
      await page.waitForFunction(() => document.getElementById('styleVal').textContent === '50');
      await page.screenshot({ path: path.join(evidence, `WD${baseline ? '修改前' : '修改後'}-${viewport.width}.png`), fullPage: true });
      const dimensions = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
      if (!baseline) assert.ok(dimensions.scroll <= dimensions.width, '頁面不可橫向溢位');
      for (const id of ['styleRange', 'btnDemo', 'providerSelect', 'btnModePaper', 'btnModeLive', 'btnSyncTxt', 'btnKill', 'btnPanic', 'btnKillOff', 'btnPullSt']) {
        assert.equal(await page.locator('#' + id).count(), 1, '保留既有控制：' + id);
      }
      assert.equal(await page.locator('[data-cmd]').count(), 4);
      if (!baseline) {
        const narrative = await page.locator('.narr-block').evaluateAll(elements => elements.map(element => {
          const box = element.getBoundingClientRect();
          return { top: box.top, bottom: box.bottom, height: box.height };
        }));
        assert.ok(narrative.every(box => box.height > 30), '既有敘事區不可被壓扁');
        assert.ok(narrative.slice(1).every((box, index) => box.top >= narrative[index].bottom), '既有敘事區不可重疊');
        for (const id of ['btnPullSt', 'btnDemo', 'btnModePaper', 'btnModeLive', 'btnSyncTxt', 'btnKill', 'btnPanic', 'btnKillOff']) {
          await page.locator('#' + id).scrollIntoViewIfNeeded();
          assert.ok(await page.locator('#' + id).evaluate(element => {
            const box = element.getBoundingClientRect();
            const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
            return !!hit && (hit === element || element.contains(hit));
          }), '既有控制實際可達：' + id);
        }
        await page.locator('[data-style="35"]').click();
        await page.waitForFunction(() => document.getElementById('styleVal').textContent === '35');
        const [demoResponse] = await Promise.all([
          page.waitForResponse(response => new URL(response.url()).pathname === '/api/demo_tick'
            && response.request().method() === 'POST'),
          page.locator('#btnDemo').click()
        ]);
        assert.equal(demoResponse.status(), 200, '模擬請求實際回應成功');
        assert.equal(calls.filter(c => c.path === '/api/demo_tick').length, 1);
        const summary = page.locator('#strategyDetails summary');
        await summary.focus();
        await summary.press('Enter');
        assert.equal(await page.locator('#strategyDetails').getAttribute('open'), '');
        await page.locator('#strategyFile').setInputFiles({ name: '錯誤策略.json', mimeType: 'application/json', buffer: Buffer.from('{') });
        await page.waitForFunction(() => document.getElementById('strategyMessage').textContent.includes('無法匯入'));
        assert.equal(await page.locator('#btnActivateStrategy').isDisabled(), true);
        const manifest = JSON.parse(await fs.readFile(path.join(root, 'tests/fixtures/固定策略版本.json'), 'utf8'));
        const malicious = structuredClone(manifest);
        malicious.context.symbol = '<img src=x onerror="window.策略注入=true">';
        await page.locator('#strategyFile').setInputFiles({ name: '字串驗證.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(malicious)) });
        await page.waitForFunction(() => document.getElementById('strategyPreview').textContent.includes('<img'));
        assert.equal(await page.locator('#strategyPreview img').count(), 0);
        assert.equal(await page.evaluate(() => !!window.策略注入), false);
        await page.locator('#strategyFile').setInputFiles(path.join(root, 'tests/fixtures/固定策略版本.json'));
        await page.waitForFunction(version => document.getElementById('strategyPreview').textContent.includes(version), manifest.version);
        assert.equal(calls.filter(c => c.path === '/api/strategy/activate').length, 0);
        rejectRegister = true;
        await page.locator('#btnRegisterStrategy').click();
        await page.waitForFunction(() => document.getElementById('strategyMessage').textContent.includes('雜湊不符'));
        assert.equal(await page.locator('#btnActivateStrategy').isDisabled(), true);
        await page.locator('#btnRegisterStrategy').click();
        await page.waitForFunction(() => !document.getElementById('btnActivateStrategy').disabled);
        assert.equal(state.strategy_execution.mode, 'discretionary');
        await page.locator('#btnActivateStrategy').click();
        await page.waitForFunction(() => document.getElementById('strategyMode').textContent.includes('固定規則'));
        assert.equal(state.strategy_execution.version, manifest.version);
        assert.equal(calls.filter(c => c.path === '/api/mode' || c.path === '/api/broker').length, 0);
        await page.locator('#btnDemo').click();
        assert.equal(calls.filter(c => c.path === '/api/demo_tick').length, 1);
        assert.match(await page.locator('#toast').textContent(), /完整策略訊號/);
        const template = JSON.parse(await page.locator('#strategyWebhook').inputValue());
        assert.equal(template.strategy_id, manifest.strategy_id);
        assert.equal(template.version, manifest.version);
        assert.equal(template.timeframe, manifest.execution.timeframe);
        assert.equal(template.action, 'HOLD');
        assert.equal(template.price, null);
        await page.locator('#btnCopyWebhook').click();
        assert.match(await page.locator('#strategyMessage').textContent(), /複製|選取/);
        assert.equal(calls.filter(c => c.path.includes('webhook')).length, 0);
        await page.locator('#noOvernight summary').click();
        await page.locator('#overnightTime').fill('14:00');
        await page.locator('#overnightMinutes').fill('20');
        await page.locator('#btnSaveOvernight').click();
        await page.waitForFunction(() => document.getElementById('overnightMessage').textContent.includes('已儲存'));
        assert.deepEqual(state.no_overnight, { enabled: true, force_flat_time: '14:00', block_new_before_close_min: 20 });
        state.execution = { status: 'sent', simulated: true, evidence_kind: 'txt_written', position_confirmed: false };
        state.overnight_enforcement = { status: 'pending', message: '等待倉位核對' };
        await page.waitForFunction(() => document.getElementById('executionReceipt').textContent.includes('已送出，尚未取得成交確認'));
        assert.match(await page.locator('#executionReceipt').textContent(), /紙上模擬/);
        assert.match(await page.locator('#overnightProgress').textContent(), /尚未完成/);
        state.execution.position_confirmed = true;
        await page.waitForFunction(() => document.getElementById('executionReceipt').textContent.includes('倉位已核對；未取得成交明細'));
        await page.screenshot({ path: path.join(evidence, `WD設定與回報-${viewport.width}.png`), fullPage: true });
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '展開設定不可橫向溢位');
        await page.locator('#btnDiscretionary').click();
        await page.waitForFunction(() => document.getElementById('strategyMode').textContent.includes('AI 自主判斷'));
        for (const command of ['start', 'stop', 'restart', 'refresh']) {
          // click 返回只表示點擊完成；先建立等待，核對同一指令的回應再判讀紀錄。
          const [controlResponse] = await Promise.all([
            page.waitForResponse(response => new URL(response.url()).pathname === '/api/control'
              && response.request().method() === 'POST'
              && response.request().postDataJSON().cmd === command),
            page.locator(`[data-cmd="${command}"]`).click()
          ]);
          assert.equal(controlResponse.status(), 200, '控制請求實際回應成功：' + command);
        }
        assert.deepEqual(calls.filter(c => c.path === '/api/control').map(c => c.body.cmd), ['start', 'stop', 'restart', 'refresh']);
      }
      assert.deepEqual(errors, []);
      results.push({ viewport, dimensions, errors });
      await page.close();
    }
  } finally { await browser.close(); }
  const report = { result: '通過', baseline, baseline_ref: baseline ? baselineRef : null, results };
  await fs.writeFile(path.join(evidence, baseline ? 'WD修改前.json' : 'WD驗證結果.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
})().catch(error => { console.error(error); process.exitCode = 1; });

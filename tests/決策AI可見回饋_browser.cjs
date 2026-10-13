'use strict';
// 使用正式決策介面與瀏覽器排版；市場及 AI 回覆固定，不啟動模型或連線正式服務。
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict'), crypto = require('node:crypto');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', '決策AI可見回饋'));
const source = fs.readFileSync(path.join(root, 'src/ui/decision_v5.js'), 'utf8');
const report = { fixtureOnly: true, sourceSha256: crypto.createHash('sha256').update(source).digest('hex'), checks: [], pageErrors: [] };
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      page.on('pageerror', error => report.pageErrors.push(error.message));
      await page.route('**/*', route => route.abort());
      await page.setContent('<style>html,body{margin:0;height:100%;--text:#d4deea;--thi:#edf5ff;--tlo:#8195ad;--border:#29405c;--bg2:#091321;--bg3:#102034;--gold:#facc15}#view-decision{height:100vh}</style><main id="view-decision" class="sv-panel on"></main>');
      await page.evaluate(() => {
        window.ShellV5 = { route: () => 'decision' };
        window.ST_PRIVATE_WEB_PROFILE = { role: 'owner' };
        window.fetch = async () => ({ ok: true, json: async () => ({ rows: [] }) });
        window.fixtureContext = { regime: { id: '等待確認', label: '固定市場情境' }, actionEnvelope: {},
          confirmation: ['價格與廣度同步確認'], invalidation: ['來源失效'], evidence: [] };
        window.fixtureRender = () => window.dispatchEvent(new CustomEvent('decisionData', { detail: { state: { context: window.fixtureContext } } }));
        window.fixtureCalls = 0;
        window.STAI = { request() { window.fixtureCalls++; return { promise: new Promise((resolve, reject) => {
          window.fixtureResolve = resolve; window.fixtureReject = reject;
        }) }; } };
      });
      await page.addScriptTag({ content: source });
      await page.evaluate(() => window.fixtureRender());
      const button = page.locator('#dc-ai-btn'), card = page.locator('#dc-ai-card');
      await button.focus();
      await page.keyboard.press('Enter');
      await page.waitForFunction(() => window.fixtureCalls === 1);
      const box = await card.boundingBox();
      const buttonBox = await button.boundingBox();
      report.checks.push({ viewport, loading: { card: box, button: buttonBox } });
      await page.screenshot({ path: path.join(output, viewport.width + '-載入.png') });
      assert(box.y >= 0 && box.y + box.height <= viewport.height, '點擊後等待訊息必須在目前畫面完整可見');
      assert(box.y - (buttonBox.y + buttonBox.height) < 100, 'AI 解釋應緊鄰操作列');
      assert.equal(await button.isDisabled(), true);
      assert.equal(await button.getAttribute('aria-expanded'), 'true');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'dc-ai-title');
      await page.evaluate(() => { window.fixtureCard = document.getElementById('dc-ai-card'); window.fixtureRender(); });
      assert.equal(await page.evaluate(() => window.fixtureCard === document.getElementById('dc-ai-card')), true, '市場重繪須保留解釋節點');
      await page.evaluate(() => { document.getElementById('view-decision').scrollTop = 500; });
      const anchor = page.locator('#dc-section-evidence');
      const anchorTop = (await anchor.boundingBox()).y;
      await page.evaluate(() => window.fixtureResolve({ text: '支持證據仍待確認。\n最強反方為來源不足，價格與廣度分歧時應等待；⚠ 非投資建議。', meta: { requestId: '可見回饋測試' } }));
      await page.waitForFunction(() => !document.getElementById('dc-ai-btn').disabled);
      assert.match(await card.innerText(), /解釋已完成[\s\S]*可見回饋測試/);
      // 結果高度改變時，瀏覽器會透過捲動錨定調整 scrollTop；比較實際閱讀內容的位置。
      assert(Math.abs((await anchor.boundingBox()).y - anchorTop) <= 1, '完成時不移動正在閱讀的內容');
      const scroll = await page.locator('#view-decision').evaluate(node => node.scrollTop);
      await page.evaluate(() => window.fixtureRender());
      assert.equal(await page.locator('#view-decision').evaluate(node => node.scrollTop), scroll, '背景重繪不搶捲動位置');
      await button.click();
      await page.waitForFunction(() => window.fixtureCalls === 2);
      await page.evaluate(() => window.fixtureReject(Object.assign(new Error('固定失敗'), { status: 503 })));
      await page.waitForFunction(() => !document.getElementById('dc-ai-btn').disabled);
      assert.match(await button.innerText(), /重試/);
      assert.match(await card.innerText(), /解釋未完成[\s\S]*尚未就緒/);
      await button.click();
      await page.waitForFunction(() => window.fixtureCalls === 3);
      await page.evaluate(() => window.fixtureResolve({ text: '重試完成。\n' + '來源與失效條件均保留，仍須自行確認。'.repeat(50), meta: {} }));
      await page.waitForFunction(() => !document.getElementById('dc-ai-btn').disabled);
      assert.match(await card.innerText(), /重試完成/);
      assert.equal(await card.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true, '長文不可水平溢位');
      await page.screenshot({ path: path.join(output, viewport.width + '-完成.png') });
      if (viewport.width === 1440) {
        await page.evaluate(() => { document.body.style.zoom = '2'; document.getElementById('view-decision').scrollTop = 0; });
        assert.equal(await card.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true, '兩倍縮放長文不可水平溢位');
      }
      report.checks.at(-1).passed = true;
      await page.close();
    }
    assert.deepEqual(report.pageErrors, []);
    console.log('通過：桌面及窄螢幕可見等待、鍵盤焦點、成功、錯誤重試、持續節點與捲動位置。');
  } finally {
    fs.writeFileSync(path.join(output, '結果.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

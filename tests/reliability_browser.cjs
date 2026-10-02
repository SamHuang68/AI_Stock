'use strict';

// 真實 Chromium 觸控與產品元件；固定收據僅供介面驗收，不是市場績效。
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'scratch', 'reliability-browser');
const origin = 'https://st-reliability-offline.test';
const modules = ['src/ui/stock_health_v5.js', 'src/ui/更新工作中心.js'];
const sources = Object.fromEntries(modules.map(file => [file, fs.readFileSync(path.join(root, file), 'utf8')]));
const report = { fixtureOnly: true, sourceHashes: Object.fromEntries(modules.map(file =>
  [file, crypto.createHash('sha256').update(sources[file]).digest('hex')])), checks: [], pageErrors: [], blocked: [] };

function html() {
  return '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<style>*{box-sizing:border-box}body{margin:8px;font:14px system-ui;background:#101827;color:#e2e8f0}button{font:inherit;padding:12px}#health{max-width:100%;overflow-wrap:anywhere}pre{overflow:auto}</style>' +
    '<title>離線可靠性驗收</title><h1>離線固定收據，非市場績效</h1><button id="updates">更新中心</button><div id="health"></div>' +
    '<script>window.SERVER="";window.UpdateJobs={subscribe(fn){fn(window.fixtureState);return function(){}},refresh(){return Promise.resolve()},submit(){throw Error("驗收不得提交更新")},retry(){throw Error("驗收不得重試更新")}};</script>' +
    modules.map(file => '<script src="/' + file + '"></script>').join('') + '</html>';
}

async function drag(page, session) {
  const dialog = page.locator('#st-update-center');
  await dialog.evaluate(node => {
    window.touchEvidence = { starts: 0, ends: 0, scrollEnds: 0, before: node.scrollTop };
    node.addEventListener('touchstart', e => { if (e.isTrusted) touchEvidence.starts++; }, { passive: true });
    node.addEventListener('touchend', e => { if (e.isTrusted) touchEvidence.ends++; }, { passive: true });
    node.addEventListener('scrollend', e => { if (e.isTrusted) touchEvidence.scrollEnds++; }, { passive: true });
  });
  const b = await dialog.boundingBox();
  const x = Math.round(b.x + b.width * .7), y = Math.round(b.y + b.height * .8);
  const point = { x, y, id: 0, force: 1 };
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] });
  for (let step = 1; step <= 10; step++) {
    point.y = y - step * Math.min(18, b.height / 25);
    await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point] });
    await page.waitForTimeout(32);
  }
  // 手指先停住再離開，避免 fling 讓下一次點按僅中止慣性滑動。
  await page.waitForTimeout(250);
  await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [point] });
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  report.gesture = await page.evaluate(() => ({ ...window.touchEvidence, scrollTop: document.getElementById('st-update-center').scrollTop }));
  await page.waitForFunction(() => {
    const node = document.getElementById('st-update-center'), e = window.touchEvidence;
    e.stable = Math.abs((e.lastTop ?? -100) - node.scrollTop) < .5 ? (e.stable || 0) + 1 : 0;
    e.lastTop = node.scrollTop;
    return e.starts > 0 && e.ends > 0 && e.scrollEnds > 0 && node.scrollTop > e.before + 20 && e.stable >= 8;
  }, null, { polling: 'raf', timeout: 10000 });
  return page.evaluate(() => window.touchEvidence);
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [width, height, throttle] of [[390, 844, 1], [844, 390, 1], [390, 844, 4]]) {
      const context = await browser.newContext({ viewport: { width, height }, hasTouch: true, isMobile: true });
      const page = await context.newPage();
      page.on('pageerror', e => report.pageErrors.push(e.message));
      await page.route('**/*', async route => {
        const url = new URL(route.request().url()), key = decodeURIComponent(url.pathname.slice(1));
        if (url.origin !== origin || (url.pathname !== '/' && !sources[key])) {
          report.blocked.push(route.request().url()); return route.abort();
        }
        return route.fulfill({ contentType: url.pathname === '/' ? 'text/html; charset=utf-8' : 'application/javascript; charset=utf-8',
          body: url.pathname === '/' ? html() : sources[key] });
      });
      await page.goto(origin);
      const session = await context.newCDPSession(page);
      await session.send('Emulation.setCPUThrottlingRate', { rate: throttle });
      await page.evaluate(() => {
        window.fixtureState = { capabilities: { canSubmit: false, canRetry: false, types: ['pulse', 'options'] },
          jobs: Array.from({length:20}, (_, i) => ({jobId:'fixture-'+i,type:'pulse',status:'failed',error:'固定缺日收據；非真實更新'})) };
        document.getElementById('updates').onclick = function () { UpdateCenter.open(this); };
        document.getElementById('health').innerHTML = StockHealthV5.maintenanceHtml({ observations: {
          enabled:true,events:534,outcomes:0,forward:{note:'次日收盤起算，需要事件後 6／21 個完整交易日',
          horizons:[{horizon:5,resolved:0,pending:534},{horizon:20,resolved:0,pending:534}]},
          lastRun:{outcomeProgress:{byHorizon:{'5':{missing_stock_sessions:2,awaiting_observed_sessions:532}},samples:[]}}
        }});
      });
      assert.match(await page.locator('#health').innerText(), /待核對／成熟 534/);
      assert.match(await page.locator('#health').innerText(), /個股觀察期缺日 2/);
      await page.locator('#updates').tap();
      await page.locator('#st-update-center[open]').waitFor({ state: 'visible' });
      assert.equal(await page.locator('[data-submit="pulse"]').isDisabled(), true);
      const touch = await drag(page, session);
      report.active = { width, height, throttle, touch };
      await page.evaluate(() => {
        window.closeEvents = [];
        for (const type of ['touchstart', 'touchend', 'click', 'scrollend']) document.addEventListener(type, e => {
          window.closeEvents.push({type, trusted:e.isTrusted, target:e.target.outerHTML?.slice(0,150)});
        }, true);
      });
      await page.screenshot({ path: path.join(output, 'before-close.png') });
      await page.locator('#st-update-center [data-close]').tap();
      report.active.closeEvents = await page.evaluate(() => window.closeEvents);
      await page.locator('#st-update-center').waitFor({ state: 'hidden' });
      assert.equal(await page.evaluate(() => document.activeElement.id), 'updates');
      await page.locator('#updates').tap();
      await page.locator('#st-update-center[open]').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#st-update-center').evaluate(node => node.matches(':modal')), true);
      const bounds = await page.locator('#st-update-center').boundingBox();
      assert(bounds.x >= -1 && bounds.y >= -1 && bounds.x + bounds.width <= width + 1 && bounds.y + bounds.height <= height + 1);
      await page.keyboard.press('Escape');
      await page.locator('#st-update-center').waitFor({ state: 'hidden' });
      await page.screenshot({ path: path.join(output, `${width}-${height}-${throttle}.png`), fullPage: true });
      report.checks.push({ width, height, throttle, touch, reopened: true, readerProtected: true, bounds });
      await context.close();
    }
    assert.deepEqual(report.pageErrors, []);
    assert.deepEqual(report.blocked, []);
    console.log('可靠性瀏覽器驗收通過：三組真觸控、實際捲動、停止後再次點按、焦點與唯讀權限。');
  } finally {
    fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

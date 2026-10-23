// 警報規則表單（完整建置頁面、離線 fixture）：新條件類型的門檻欄位、範圍檢查、只提醒一次，
// 以及既有價位規則與舊規則清單原樣保留。不連網：所有請求由本檔回應或攔下。
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const origin = 'https://st-alert-form.test';
const html = fs.readFileSync(path.join(root, 'stock_terminal_v2.html'), 'utf8');
const chartLib = path.join(__dirname, 'fixtures', 'lightweight-charts-4.2.0.js');

const legacy = [
  { id: 1, sym: '2330', market: 'TW', type: 'cross_up', price: 600, note: '舊規則', enabled: true },
  { id: 2, sym: '2317', market: 'TW', type: 'pct_up', threshold: 3, once: true, _last_once_done: true, note: '', enabled: true },
  { id: 3, sym: 'AAPL', market: 'US', type: 'volume_ratio', threshold: 2.5, note: '', enabled: true },
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce', serviceWorkers: 'block' });
  await context.addInitScript(() => localStorage.setItem('wizard_dismiss', JSON.stringify({ all: 1 })));
  const page = await context.newPage();
  const errors = [], posts = [], dialogs = [];
  let rules = JSON.parse(JSON.stringify(legacy));
  let config = { enabled: true, running: true, telegram: {}, email: {}, webhook: {} };
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', async d => { dialogs.push(d.message()); await d.dismiss(); });
  await context.route('**/*', r => {
    const req = r.request(), url = new URL(req.url());
    if (url.origin !== origin) {
      if (url.href.includes('lightweight-charts@4.2.0/')) return r.fulfill({ path: chartLib, contentType: 'application/javascript' });
      return r.abort('blockedbyclient');
    }
    const file = decodeURIComponent(url.pathname.slice(1));
    if (file === '') return r.fulfill({ contentType: 'text/html; charset=utf-8', body: html });
    const abs = path.join(root, file);
    if (req.method() === 'GET' && /\.(js|css|png|svg|woff2?)$/.test(file) && !file.includes('..') && fs.existsSync(abs)) return r.fulfill({ path: abs });
    if (url.pathname === '/alert/config') return r.fulfill({ json: config });
    if (url.pathname === '/alert/rules' && req.method() === 'GET') return r.fulfill({ json: rules });
    if (url.pathname === '/alert/rules' && req.method() === 'POST') {
      rules = JSON.parse(req.postData());
      posts.push(rules);
      return r.fulfill({ json: { ok: true, count: rules.length } });
    }
    return r.fulfill({ json: {} });
  });

  await page.goto(origin + '/#pulse', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('html.st5-booted', { state: 'attached' });
  await page.evaluate(() => window.alertPushOpen());
  await page.waitForSelector('#ap-rules tr');

  const cells = await page.$$eval('#ap-rules tr', rows => rows.map(tr => [...tr.querySelectorAll('td')].slice(0, 4).map(td => td.textContent.trim())));
  assert.deepEqual(cells, [
    ['2330', 'TW', '過壓力↑', '600'],
    ['2317', 'TW', '漲幅達↑（只提醒一次・已提醒）', '3%'],
    ['AAPL', 'US', '預估量比', '2.5 倍昨量'],
  ]);
  assert.equal(await page.$eval('#ap-rules', el => el.closest('table').querySelector('thead').textContent.includes('價位／門檻')), true);

  await page.selectOption('#ap-r-type', 'volume_ratio');
  assert.equal(await page.getAttribute('#ap-r-price', 'placeholder'), '倍數（1–20）');
  assert.match(await page.textContent('#ap-r-hint'), /線性換算，早盤偏高，開盤 15 分鐘內不判斷/);

  await page.fill('#ap-r-sym', '2454');
  await page.fill('#ap-r-price', '25');
  await page.click('#ap-r-add');
  assert.deepEqual(dialogs, ['請填代號與 1 到 20 的倍數']);
  assert.equal(posts.length, 0, '超出範圍不得送出');

  await page.fill('#ap-r-price', '2');
  await page.check('#ap-r-once');
  await page.click('#ap-r-add');
  await page.waitForFunction(() => document.querySelectorAll('#ap-rules tr').length === 4);
  const added = posts[0][3];
  assert.deepEqual(posts[0].slice(0, 3), legacy, '既有規則原樣保留');
  assert.equal(added.type, 'volume_ratio');
  assert.equal(added.threshold, 2);
  assert.equal(added.once, true);
  assert.equal('price' in added, false);

  await page.selectOption('#ap-r-type', 'cross_down');
  assert.equal(await page.getAttribute('#ap-r-price', 'placeholder'), '價位');
  await page.fill('#ap-r-sym', '2603');
  await page.fill('#ap-r-price', '180');
  await page.click('#ap-r-add');
  await page.waitForFunction(() => document.querySelectorAll('#ap-rules tr').length === 5);
  const priceRule = posts[1][4];
  assert.equal(priceRule.type, 'cross_down');
  assert.equal(priceRule.price, 180);
  assert.equal('threshold' in priceRule, false);
  assert.equal('once' in priceRule, false, '未勾選時不寫 once');

  // Inert markup must remain data in both value attributes and rule table text.
  // All routes above are fixtures; this does not send a test notification.
  const inert = '\"><span data-review-marker="inert">A & B</span>';
  config = {
    enabled: true, telegram: { chat_id: inert },
    email: { smtp_host: inert, user: inert, to: inert }, webhook: { url: inert },
  };
  rules = [
    { id: 90, sym: inert, market: inert, type: 'cross_up', price: inert, note: inert },
    { id: 91, sym: inert, type: 'composite', combine: inert,
      conditions: [{ left: inert, op: 'lt', right: inert }] },
  ];
  await page.evaluate(() => window.alertPushOpen());
  await page.waitForFunction(() => document.querySelector('#ap-tg-chat')?.value.includes('data-review-marker'));
  for (const id of ['ap-tg-chat', 'ap-em-host', 'ap-em-user', 'ap-em-to', 'ap-wh-url']) {
    assert.equal(await page.inputValue('#' + id), inert);
  }
  assert.equal(await page.locator('#ap-body [data-review-marker]').count(), 0);
  assert.equal(await page.locator('#ap-rules tr').count(), 1);
  assert.equal(await page.locator('#ap-rules td').first().textContent(), inert);
  assert.equal(posts.length, 2, 'rendering settings must not send alerts or rewrite rules');

  assert.deepEqual(errors, []);
  await browser.close();
  console.log('alert_rule_form_browser OK：新條件門檻、範圍檢查、只提醒一次、既有規則保留');
})().catch(error => { console.error(error); process.exitCode = 1; });

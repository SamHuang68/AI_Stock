'use strict';
// 正式選股模組以固定離線回應驗證，沒有呼叫市場來源。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', '選股候選驗收'));
const source = fs.readFileSync(path.join(root, 'src/ui/scan_v5.js'), 'utf8');
const origin = 'https://st-offline.test';
const report = { passed: false, sourceSha256Lf: crypto.createHash('sha256').update(source.replace(/\r\n/g, '\n')).digest('hex'), checks: [], pageErrors: [] };
const html = `<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>選股候選離線驗收</title><style>
:root{--bg:#071322;--bg2:#102236;--bg3:#1f344a;--text:#dbe7f5;--thi:#fff;--tlo:#acbcd0;--gold:#f5c355;--border:#476078;--red:#f98990;--green:#4ce0bc}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text)}#shell-views{height:100vh;display:flex}button,input,select{font-family:sans-serif}
</style></head><body><div id="shell-views"><div id="view-scan" class="sv-panel on"><div id="mount-scan" class="sv-mount"></div></div></div><script>window.SERVER='';window.ShellV5={route:()=> 'offline-fixture'};</script><script src="/scan.js"></script><script>ScanV5.activate()</script></body></html>`;
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({ headless:true, ...(process.env.ST_BROWSER_CHANNEL ? {channel:process.env.ST_BROWSER_CHANNEL} : {}) });
  try {
    report.browser = browser.version();
    for (const [width,height] of [[1280,720],[390,844],[844,390]]) {
      const context = await browser.newContext({viewport:{width,height},hasTouch:true,acceptDownloads:true});
      let sequence = 0;
      await context.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.origin !== origin) return route.abort();
        if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:html});
        if (url.pathname === '/scan.js') return route.fulfill({contentType:'text/javascript',body:source});
        if (url.pathname === '/screener') return route.fulfill({json:{sectors:['半導體']}});
        if (url.pathname === '/screen3' && route.request().method() === 'POST') {
          sequence++;
          return route.fulfill({json:{scanned:100,techPass:80,matched:90,results:[
            {sym:'2330',name:'台積電',close:1000,per:sequence===1?20:8,revYoy:20},
            {sym:'2454',name:'聯發科',close:900,per:10,revYoy:15},
            {sym:'00981A',name:'缺少估值的研究樣本',close:10,per:null,revYoy:null}
          ]}});
        }
        return route.abort();
      });
      const page = await context.newPage();
      page.on('pageerror', error => report.pageErrors.push(String(error)));
      await page.goto(origin);
      await page.locator('#sc-run').click();
      await page.waitForFunction(() => ScanV5.receipts().length === 1);
      await page.locator('#sc-sort-key').selectOption('per');
      await page.locator('#sc-run').click();
      await page.waitForFunction(() => ScanV5.receipts().length === 2);
      await page.locator('.sc-comparison > summary').click();
      const text = await page.locator('.sc-comparison').innerText();
      assert.match(text,/第 2 位 → 第 1 位/);
      assert.match(text,/取得時間不等於行情/);
      assert.match(text,/資料不足/);
      const [download] = await Promise.all([page.waitForEvent('download'),page.locator('#sc-comparison-export').click()]);
      const destination = path.join(output, `${width}x${height}-選股掃描完整收據.json`);
      await download.saveAs(destination);
      const saved = JSON.parse(fs.readFileSync(destination,'utf8'));
      assert.equal(saved.receipts.length,2);
      assert.equal(saved.receipts[0].response.results[0].per,20);
      assert.equal(saved.receipts[1].response.results[0].per,8);
      const layout = await page.evaluate(() => {
        const root = document.querySelector('#sc-root').getBoundingClientRect();
        const comparison = document.querySelector('.sc-comparison').getBoundingClientRect();
        const results = document.querySelector('#sc-results');
        return {pageOverflow:document.documentElement.scrollWidth > innerWidth + 1,root:{left:root.left,right:root.right},comparisonWidth:comparison.width,resultWidth:results.clientWidth,resultsScrollable:results.scrollHeight>results.clientHeight};
      });
      assert.equal(layout.pageOverflow,false);
      assert(layout.comparisonWidth <= layout.resultWidth + 1,'比較詳情不得撐破結果容器');
      await page.screenshot({path:path.join(output,`${width}x${height}-候選變化.png`),fullPage:true});
      report.checks.push({width,height,scans:sequence,receiptCount:saved.receipts.length,layout});
      await context.close();
    }
    assert.deepEqual(report.pageErrors,[]);
    report.passed = true;
  } finally { await browser.close(); fs.writeFileSync(path.join(output,'選股候選驗收.json'),JSON.stringify(report,null,2)); }
  console.log(JSON.stringify(report,null,2));
})().catch(error => {console.error(error);process.exitCode=1;});

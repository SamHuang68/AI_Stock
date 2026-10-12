'use strict';
// 正式頁面與樣式的局部排版驗收；行情為固定值，所有網路要求均攔截，不啟動正式服務。
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', '手機行情遮蔽'));
const origin = 'https://st-mobile-layout.test';
const html = fs.readFileSync(path.join(root, 'stock_terminal_v2.html'), 'utf8');
const assetPaths = [...new Set([...html.matchAll(/(?:src|href)="(src\/[^"?]+)(?:\?[^"\s]*)?"/g)].map(m => m[1]))];
const assets = Object.fromEntries(assetPaths.map(file => [file, fs.readFileSync(path.join(root, file), 'utf8')]));
const changed = ['src/ui/polish_v3.js', 'src/ui/chart_visual_v5.js', 'src/ui/mobile_v2.css'];
const report = { fixtureOnly: true, inputs: ['stock_terminal_v2.html', ...assetPaths], cases: [], pageErrors: [] };

async function measure(page) {
  return page.evaluate(() => {
    const rect = el => { const r = el.getBoundingClientRect(); return { x:r.x, y:r.y, width:r.width, height:r.height, right:r.right, bottom:r.bottom }; };
    const intersects = (a,b) => a.x < b.right && a.right > b.x && a.y < b.bottom && a.bottom > b.y;
    const bar = document.querySelector('#mkt-bar'), fab = document.querySelector('#st-ring-fab');
    const panel = document.querySelector('.mkt-panel.on');
    const clipped = [...panel.querySelectorAll('.mkt-cell')].flatMap(cell => {
      const c = rect(cell);
      return [...cell.querySelectorAll('.nm,.px,.delta,.ch')].flatMap(el => {
        const range = document.createRange(); range.selectNodeContents(el); const t = range.getBoundingClientRect();
        return t.left < c.x - .5 || t.right > c.right + .5 || t.top < c.y - .5 || t.bottom > c.bottom + .5
          ? [{ symbol:cell.dataset.mktSym, field:el.className, text:el.textContent }] : [];
      });
    });
    const controls = [...document.querySelectorAll('#topbar button,#chart-search input,#rpanel-pager button,#rpage-label,#rpanel-pager .rpage-prefix')]
      .filter(el => el.getBoundingClientRect().width && getComputedStyle(el).visibility !== 'hidden');
    const controlIssues = controls.flatMap(el => {
      const r = rect(el), range = document.createRange(); range.selectNodeContents(el); const t = range.getBoundingClientRect();
      const outside = r.x < -.5 || r.right > innerWidth + .5 || r.y < -.5 || r.bottom > innerHeight + .5;
      const textCut = el.tagName !== 'INPUT' && el.textContent.trim() && (t.left < r.x - .5 || t.right > r.right + .5);
      const covered = (fab && el !== fab && intersects(r, rect(fab))) || controls.some(other => other !== el && intersects(r,rect(other)));
      return outside || textCut || covered ? [{ id:el.id || el.className, outside, textCut, covered }] : [];
    });
    return { clipped, controlIssues, market:rect(bar), fab:rect(fab), fabOverlap:intersects(rect(bar),rect(fab)),
      scrollWidth:panel.scrollWidth, clientWidth:panel.clientWidth, scrollLeft:panel.scrollLeft,
      documentOverflow:document.documentElement.scrollWidth > innerWidth,
      counts:[...document.querySelectorAll('.mkt-panel')].map(p => p.querySelectorAll('.mkt-cell').length) };
  });
}

async function swipe(page, context) {
  const session = await context.newCDPSession(page), b = await page.locator('.mkt-panel.on').boundingBox();
  const start = Math.floor(b.x + b.width * .85), y = Math.floor(b.y + b.height / 2);
  await session.send('Input.dispatchTouchEvent', { type:'touchStart', touchPoints:[{x:start,y}] });
  for (let i=1;i<=8;i++) {
    await session.send('Input.dispatchTouchEvent', { type:'touchMove', touchPoints:[{x:start-i*b.width*.07,y}] });
  }
  await session.send('Input.dispatchTouchEvent', { type:'touchEnd', touchPoints:[] });
  await page.waitForFunction(() => document.querySelector('.mkt-panel.on').scrollLeft > 10, null, { timeout:2000 });
}

(async () => {
  fs.mkdirSync(output, { recursive:true });
  const browser = await chromium.launch({ headless:true });
  try {
    const versions = process.env.ST_MOBILE_BASELINE ? ['修改前','候選'] : ['候選'];
    for (const version of versions) {
      const sources = {...assets};
      if (version === '修改前') for (const file of changed) sources[file] = fs.readFileSync(path.join(process.env.ST_MOBILE_BASELINE,file),'utf8');
      const viewports = version === '修改前' ? [[375,812]] : [[320,740],[375,812],[390,844],[667,375],[844,390],[1440,900]];
      for (const [width,height] of viewports) {
        const mobile = width <= 900;
        const context = await browser.newContext({ viewport:{width,height}, hasTouch:mobile, isMobile:mobile, reducedMotion:'reduce' });
        // 沿用產品的「不再提示」設定，使首次精靈提示不攔截本次行情觸控案例。
        await context.addInitScript(() => localStorage.setItem('wizard_dismiss',JSON.stringify({all:1})));
        const page = await context.newPage();
        page.on('pageerror', error => report.pageErrors.push({version,width,error:error.message}));
        await context.route('**/*', route => {
          const url = new URL(route.request().url()), file = decodeURIComponent(url.pathname.slice(1));
          if (url.origin === origin && (file === '' || sources[file])) return route.fulfill({
            contentType:file === '' ? 'text/html; charset=utf-8' : file.endsWith('.css') ? 'text/css; charset=utf-8' : 'application/javascript; charset=utf-8', body:file === '' ? html : sources[file] });
          // 外部字型、圖表 CDN 與市場 API 不連外；這個案例僅驗正式 UI 排版。
          return route.fulfill({ contentType:'application/json', body:'{}' });
        });
        await page.goto(origin + '/#chart', { waitUntil:'domcontentloaded' });
        await page.waitForSelector('html.st5-booted', {state:'attached'});
        await page.waitForSelector('#st-ring.on');
        await page.evaluate(() => { window.ShellV5.go('chart'); window.ShellV5.closeRing(); });
        await page.waitForSelector('html.st5-booted #mkt-bar .mkt-cell');
        await page.waitForSelector('#st-ring-fab');
        await page.evaluate(() => {
          window.mobileLayoutLoads = [];
          window.loadSym = (sym,mkt) => window.mobileLayoutLoads.push({sym,mkt});
          document.querySelectorAll('.mkt-cell').forEach((cell,i) => {
            cell.classList.remove('loading');
            cell.querySelector('.px').textContent = i % 3 === 0 ? '99,999.99' : '4,567.89';
            cell.querySelector('.delta').textContent = '-1,234.56';
            cell.querySelector('.ch').textContent = '-12.34%';
          });
        });
        const entry = { version, width, height, tabs:[] }; report.cases.push(entry);
        for (const tab of ['tw','mkt']) {
          await page.locator(`[data-mkt-tab="${tab}"]`).click();
          await page.evaluate(() => document.querySelector('.mkt-panel.on').scrollLeft = 0);
          const result = await measure(page); entry.tabs.push({tab,...result});
          if (version === '候選' && mobile) {
            assert.deepEqual(result.counts,[7,12]);
            assert.deepEqual(result.clipped,[],`${width} ${tab} 行情文字裁切`);
            assert.equal(result.fabOverlap,false,`${width} 轉盤遮住行情`);
            assert.equal(result.documentOverflow,false,`${width} 整頁溢位`);
            assert.deepEqual(result.controlIssues,[],`${width} 相鄰控制入口遮蔽`);
          }
          if (width === 375 || (version === '候選' && tab === 'mkt')) await page.screenshot({path:path.join(output,`${version}-${width}x${height}-${tab}.png`)});
        }
        if (version === '候選' && mobile) {
          await swipe(page,context);
          entry.touchScroll = (await measure(page)).scrollLeft;
          const panel = page.locator('.mkt-panel.on');
          await panel.evaluate(el => el.scrollLeft = el.scrollWidth);
          for (const sym of ['SI=F','CL=F']) await page.locator(`.mkt-panel.on [data-mkt-sym="${sym}"]`).click();
          assert.deepEqual(await page.evaluate(() => window.mobileLayoutLoads.map(x=>x.sym)),['SI=F','CL=F']);
          entry.lastItemsClickable = true;
          if (width === 375) await page.screenshot({path:path.join(output,'候選-375x812-市場末端.png')});
          await page.locator('#st-ring-fab').click();
          await page.waitForSelector('#st-ring.on[aria-hidden="false"]',{timeout:2000});
          entry.ringOpened = true;
        }
        await context.close();
      }
    }
    if (process.env.ST_MOBILE_BASELINE) {
      assert.ok(report.cases[0].tabs.some(t=>t.clipped.length > 0),'修改前應重現行情裁切');
      assert.ok(report.cases[0].tabs.some(t=>t.fabOverlap),'修改前應重現轉盤遮蔽');
    }
    report.status = '通過';
  } catch (error) { report.status='失敗'; report.failure=error.stack; throw error; }
  finally { fs.writeFileSync(path.join(output,'報告.json'),JSON.stringify(report,null,2)); await browser.close(); }
  console.log(JSON.stringify({status:report.status,cases:report.cases.length,output}));
})();

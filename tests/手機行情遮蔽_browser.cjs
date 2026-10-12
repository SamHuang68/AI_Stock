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
// 使用正式頁面同版的真實圖表引擎；固定日線只隔離行情網路，不替代圖表渲染。
const chartLibrary = fs.readFileSync(path.join(__dirname,'fixtures/lightweight-charts-4.2.0.js'),'utf8');
const bars = Array.from({length:90},(_,i) => {
  const close = 2150 + i*3 + Math.sin(i/5)*100;
  return {time:Date.UTC(2026,5,1+i)/1000,open:close+(i%2 ? 12 : -12),high:close+24,low:close-24,close,volume:1000000+(i%9)*200000};
});
const quote = Object.fromEntries(['open','high','low','close','volume'].map(k=>[k,bars.map(b=>b[k])]));
const fixture = {chart:{result:[{timestamp:bars.map(b=>b.time),indicators:{quote:[quote]},meta:{symbol:'2330.TW',shortName:'台積電',currency:'TWD',regularMarketPrice:bars.at(-1).close,regularMarketPreviousClose:bars.at(-2).close,regularMarketTime:bars.at(-1).time}}],error:null}};
const changed = ['src/ui/polish_v3.js', 'src/ui/chart_visual_v5.js', 'src/ui/mobile_v2.css', 'src/ui/toolbar_v3.js'];
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
      const scroller = el.closest('#topbar');
      const scrollable = scroller && getComputedStyle(scroller).overflowX === 'auto';
      const outside = (!scrollable && (r.x < -.5 || r.right > innerWidth + .5)) || r.y < -.5 || r.bottom > innerHeight + .5;
      const textCut = el.tagName !== 'INPUT' && el.textContent.trim() && (t.left < r.x - .5 || t.right > r.right + .5);
      const covered = (fab && el !== fab && intersects(r, rect(fab))) || controls.some(other => other !== el && intersects(r,rect(other)));
      return outside || textCut || covered ? [{ id:el.id || el.className, outside, textCut, covered,rect:r,innerHeight }] : [];
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

async function measureChart(page) {
  return page.evaluate(() => {
    const box = id => {const r=document.querySelector(id).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom};};
    const candles = S.data.candles;
    const coordinates = candles.map(c=>({x:S.chart.timeScale().timeToCoordinate(c.time+S.tzOffset),high:S.chartSeries.priceToCoordinate(c.high),low:S.chartSeries.priceToCoordinate(c.low),volume:S.volSeries.priceToCoordinate(c.volume)}));
    const shot = S.chart.takeScreenshot(), pixels = shot.getContext('2d').getImageData(0,0,shot.width,shot.height).data;
    let coloredPixels=0;
    for(let i=0;i<pixels.length;i+=4) if ((pixels[i]>130 && pixels[i]>pixels[i+1]*1.35) || (pixels[i+1]>100 && pixels[i+1]>pixels[i]*1.35)) coloredPixels++;
    return {chart:box('#chart-wrap'),analysis:box('#right'),top:box('#topbar'),watchlist:box('#wlbar'),tools:box('#pro-tools'),market:box('#mkt-bar'),
      bars:candles.length,coordinates,coloredPixels,library:LightweightCharts.version(),info:box('#chart-info')};
  });
}

async function checkScrolledControls(page) {
  const checked = [];
  for(const selector of ['#topbar button','#pro-tools .tbg-btn','#vp-inline button']) {
    for(const el of await page.locator(selector).all()) {
      if(!await el.isVisible()) continue;
      await el.scrollIntoViewIfNeeded();
      const hit = await el.evaluate(node=>{const r=node.getBoundingClientRect(), top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {id:node.id||node.textContent.trim(),reachable:r.x>=0&&r.right<=innerWidth&&top&&(top===node||node.contains(top))};});
      assert.ok(hit.reachable,`橫向捲動後入口仍被遮蔽：${hit.id}`); checked.push(hit.id);
    }
  }
  const lastGroup=page.locator('#pro-tools .tbg-btn').last();
  await lastGroup.click();
  const menu = page.locator('.tbg-menu:visible');
  await menu.waitFor();
  assert.ok(await menu.evaluate(el=>{const r=el.getBoundingClientRect();return el.parentElement===document.body&&r.x>=0&&r.right<=innerWidth&&r.y>=0&&r.bottom<=innerHeight;}),'工具選單超出短橫向畫面');
  await lastGroup.click();
  await page.evaluate(()=>{document.querySelector('#topbar').scrollLeft=0;document.querySelector('#pro-tools').scrollLeft=0;});
  return checked;
}

(async () => {
  fs.mkdirSync(output, { recursive:true });
  const browser = await chromium.launch({ headless:true });
  try {
    const versions = process.env.ST_MOBILE_BASELINE ? ['修改前','候選'] : ['候選'];
    for (const version of versions) {
      const sources = {...assets};
      const pageHtml = version === '修改前' ? fs.readFileSync(path.join(process.env.ST_MOBILE_BASELINE,'stock_terminal_v2.html'),'utf8') : html;
      if (version === '修改前') for (const file of changed) sources[file] = fs.readFileSync(path.join(process.env.ST_MOBILE_BASELINE,file),'utf8');
      const viewports = version === '修改前' ? [[844,300],[844,390]] : [[320,740],[375,812],[390,844],[667,300],[844,300],[844,330],[844,390],[932,300],[1440,900]];
      for (const [width,height] of viewports) {
        const mobile = width <= 1100;
        const shortLandscape = mobile && width>height;
        const context = await browser.newContext({ viewport:{width,height}, hasTouch:mobile, isMobile:mobile, reducedMotion:'reduce' });
        // 沿用產品的「不再提示」設定，使首次精靈提示不攔截本次行情觸控案例。
        await context.addInitScript(() => localStorage.setItem('wizard_dismiss',JSON.stringify({all:1})));
        const page = await context.newPage();
        page.setDefaultTimeout(5000);
        page.on('pageerror', error => report.pageErrors.push({version,width,error:error.message}));
        await context.route('**/*', route => {
          const url = new URL(route.request().url()), file = decodeURIComponent(url.pathname.slice(1));
          if (url.origin === origin && (file === '' || sources[file])) return route.fulfill({
            contentType:file === '' ? 'text/html; charset=utf-8' : file.endsWith('.css') ? 'text/css; charset=utf-8' : 'application/javascript; charset=utf-8', body:file === '' ? pageHtml : sources[file] });
          if(url.href.includes('lightweight-charts@4.2.0/')) return route.fulfill({contentType:'application/javascript',body:chartLibrary});
          if(url.pathname.startsWith('/yf/') && !url.pathname.endsWith('/batch')) return route.fulfill({contentType:'application/json',body:JSON.stringify(fixture)});
          // 其他網路一律隔離；正式 loadSym／指標／圖表仍用上面的固定日線完成渲染。
          return route.fulfill({ contentType:'application/json', body:'{}' });
        });
        await page.goto(origin + '/#chart', { waitUntil:'domcontentloaded' });
        await page.waitForSelector('html.st5-booted', {state:'attached'});
        await page.waitForSelector('#st-ring.on');
        await page.evaluate(() => { window.ShellV5.go('chart'); window.ShellV5.closeRing(); });
        await page.waitForSelector('html.st5-booted #mkt-bar .mkt-cell');
        await page.waitForSelector('#st-ring-fab');
        await page.waitForFunction(()=>typeof S!=='undefined' && S.chartSeries && S.volSeries && S.data?.candles?.length===90);
        await page.waitForFunction(()=>document.querySelector('#vp-inline')?.classList.contains('on'));
        await page.waitForFunction(()=>document.querySelector('#chart-loading').style.display==='none');
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
        entry.chart = await measureChart(page);
        if(shortLandscape) await page.screenshot({path:path.join(output,`${version}-${width}x${height}-圖表.png`)});
        if(version==='候選' && shortLandscape) {
          assert.ok(entry.chart.chart.height>=110,`${width}x${height} K 線高度不足：${entry.chart.chart.height}`);
          assert.ok(entry.chart.analysis.width>=width*.3 && entry.chart.analysis.height>=180,'橫向分析區仍須同屏可見');
          assert.ok(entry.chart.chart.y>=entry.chart.tools.bottom-.5 && entry.chart.chart.bottom<=entry.chart.market.y+.5,'K 線被工具或行情覆蓋');
          assert.ok(entry.chart.market.bottom<=height+.5,'行情列超出真正可用高度');
          assert.ok(entry.chart.coloredPixels>200,'真實 K 線與成交量必須完成繪製');
          assert.ok(entry.chart.coordinates.filter(c=>c.x>0&&c.x<entry.chart.chart.width&&c.high>=0&&c.low<entry.chart.chart.height&&c.volume>=0&&c.volume<entry.chart.chart.height).length>=60,'可視 K 棒／量座標不足');
          entry.reachableControls=await checkScrolledControls(page);
          await page.locator('#right-collapse').click();
          await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
          entry.collapsedChart=await measureChart(page);
          await page.waitForFunction(()=>document.querySelector('#right').getBoundingClientRect().width<1 && document.querySelector('#chart-wrap').getBoundingClientRect().width>innerWidth*.9);
          await page.locator('#right-collapse').click();
          await page.waitForFunction(()=>document.querySelector('#right').getBoundingClientRect().width>innerWidth*.3);
          entry.analysisCollapsePreserved=true;
        }
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
          if(width===844 && height===300) {
            await page.evaluate(()=>window.ShellV5.closeRing());
            await page.setViewportSize({width:375,height:812});
            await page.waitForFunction(()=>Math.abs(document.querySelector('#app').getBoundingClientRect().height-812)<1);
            await page.setViewportSize({width,height});
            await page.waitForFunction(()=>Math.abs(document.querySelector('#app').getBoundingClientRect().height-300)<1 && document.querySelector('#chart-wrap').getBoundingClientRect().height>=110);
            entry.rotationPreserved=true;
          }
        }
        await context.close();
      }
    }
    if (process.env.ST_MOBILE_BASELINE) {
      assert.ok(report.cases[0].chart.chart.height<60,'修改前應重現短橫向 K 線被壓縮');
    }
    assert.deepEqual(report.pageErrors,[],'頁面執行錯誤');
    report.status = '通過';
  } catch (error) { report.status='失敗'; report.failure=error.stack; throw error; }
  finally { fs.writeFileSync(path.join(output,'報告.json'),JSON.stringify(report,null,2)); await browser.close(); }
  console.log(JSON.stringify({status:report.status,cases:report.cases.length,output}));
})();

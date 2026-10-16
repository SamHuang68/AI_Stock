'use strict';
// 載入完整建置頁面；僅在網路邊界提供固定行情，不建立 window.S 或替換產品函式。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const base = process.env.ST_HEADLINE_BASE || 'https://market-headline.test';
const live = !!process.env.ST_HEADLINE_BASE;
const runtime = process.env.ST_HEADLINE_RUNTIME === '1';
const out = process.env.ST_HEADLINE_OUTPUT || path.join(root, 'scratch', '行情標頭對齊');
const report = { mode: live ? (runtime ? '部署版實際頁面' : '候選頁面搭配受管API') : '完整頁面固定行情驗收', cases: [], errors: [] };
const observed = '2026-10-16T04:59:58+08:00';
function chart(sym, intraday) {
  const prices = sym === '^TWII' ? [48341.31, 48625.83, 46969.87] : sym === '^TWOII' ? [410, 415, 396.9] : [48792, 48100, 46979];
  const lastTime = Date.parse('2026-10-15T13:30:00+08:00') / 1000;
  const timestamp = intraday ? Array.from({length:20}, (_, i) => lastTime - (19-i)*60) : [lastTime-172800,lastTime-86400,lastTime];
  const close = intraday ? timestamp.map((_, i) => prices[2] - 19 + i) : prices;
  return { chart: { result: [{meta:{symbol:sym, longName:sym, currency:'TWD', exchangeTimezoneName:'Asia/Taipei',
    regularMarketPrice:prices[2],regularMarketTime:lastTime,previousClose:48341.3,chartPreviousClose:48341.3,
    regularMarketDayHigh: sym === '^TWII' ? 48382.75 : 50194, dataGranularity:intraday?'1m':'1d'}, timestamp,
    indicators:{quote:[{open:close.map(x=>x-2), high:close.map(x=>x+20), low:close.map(x=>x-20), close, volume:close.map(()=>100)}]}}],error:null} };
}
function snapshot() {
  return {ok:true, quotes:{
    '^TWII':{market:{price:null,referencePrice:46969.87,asOf:'2026-10-16T07:50:00+08:00',source:'twse-mis',session:'regular'}},
    '^TWOII':{market:{price:null,referencePrice:396.9,asOf:'2026-10-16T07:50:00+08:00',source:'twse-mis',session:'regular'}},
    '__TXF__':{high:47520,market:{price:47366,referencePrice:46931,asOf:observed,source:'taifex-mis',session:'night'}}
  }};
}
(async () => {
  fs.mkdirSync(out, {recursive:true});
  const browser = await chromium.launch({headless:true});
  const apiSnapshot = snapshot();
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900},locale:'zh-TW',serviceWorkers:'block'});
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push(error.message));
    await context.route('**/*', async route => {
      const req = route.request(), u = new URL(req.url()), rel = decodeURIComponent(u.pathname.slice(1));
      if (!['GET','HEAD','OPTIONS'].includes(req.method())) return route.abort('blockedbyclient');
      if (runtime) return route.continue();
      if (!live && u.hostname === 'unpkg.com' && u.pathname === '/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js') {
        return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(root,'tests/fixtures/lightweight-charts-4.2.0.js'))});
      }
      if (u.origin === base) {
        const file = path.resolve(root, !rel || ['index.html','stock_terminal_v2.html'].includes(rel) ? 'stock_terminal_v2.html' : rel);
        if (file.startsWith(root + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) {
          const type = file.endsWith('.html') ? 'text/html' : file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'application/javascript' : null;
          if (type) return route.fulfill({contentType:type+'; charset=utf-8',body:fs.readFileSync(file)});
        }
        if (!live) {
          let body = {ok:true};
          if (rel === 'market/snapshot') body = apiSnapshot;
          else if (rel === 'pulse') body = {ok:true,indices:{},marketSnapshot:snapshot()};
          else if (rel === 'yf/batch') body = Object.fromEntries((u.searchParams.get('syms')||'').split(',').map(s=>[s,chart(s,false)]));
          else if (rel.startsWith('yf/')) body = chart(rel.slice(3),u.searchParams.get('interval')==='1m');
          else if (rel.startsWith('quote/')) return route.fulfill({status:502,json:{ok:false}});
          else if (rel === 'twindex') body = {ok:false,indices:{}};
          else if (rel === 'margin_ratio') body = {ok:true,series:[],points:[]};
          return route.fulfill({json:body});
        }
      }
      if (!live) return route.abort('blockedbyclient');
      return route.continue();
    });
    if (live) report.healthBefore = await (await context.request.get(base+'/health/live')).json();
    await page.goto(base+'/', {waitUntil:'domcontentloaded',timeout:25000});
    await page.waitForSelector('#st-ring.on',{timeout:15000});
    await page.evaluate(() => { window.ShellV5.go('chart'); window.ShellV5.closeRing(); });
    report.coldState = await page.evaluate(() => ({windowS:typeof window.S, lexical:typeof S}));
    assert.equal(report.coldState.windowS,'undefined','正式冷啟動不得由測試注入 window.S');
    async function select(sym, range) {
      await page.locator(`[data-mkt-sym="${sym}"]`).first().click();
      await page.locator(`[data-rg="${range}"]`).first().click();
      await page.waitForFunction(({sym,range}) => S.sym===sym && S.range===range && S.ind &&
        S.dataIdentity?.sym===sym && S.dataIdentity?.loadSeq===window.__loadSeq,{sym,range},{timeout:30000});
      await page.evaluate(() => window.MarketData.refresh());
      await page.waitForFunction(() => !!S.data?.marketHeadline,null,{timeout:10000});
      await page.waitForTimeout(150); // 包含正式 renderChart 的 60ms 延後重繪。
      const state = await page.evaluate(() => {
        const cell=document.querySelector(`[data-mkt-sym="${S.sym}"]`), text=id=>document.getElementById(id)?.textContent;
        return {sym:S.sym,range:S.range,price:text('ci-price'),change:text('ci-chg'),high:text('ci-high'),stamp:text('ci-market-asof'),
          stripPrice:cell?.querySelector('.px')?.textContent,stripDelta:cell?.querySelector('.delta')?.textContent,
          stripPct:cell?.querySelector('.ch')?.textContent,headline:S.data.marketHeadline,
          quote:window.MarketData.get().quotes[S.sym],count:S.data.candles.length,
          windowS:typeof window.S,chartClose:S.data.candles.at(-1).close,statsPrice:text('rp-PRICE'),statsChange:text('rp-CHANGE'),
          statsRange:text('rp-RANGE'),rangeBase:S.data.rangeBase,rangeChange:text('ci-range-chg')};
      });
      const m=state.quote.market, delta=m.price-m.referencePrice, pct=delta/m.referencePrice*100;
      assert.equal(Number(state.price.replaceAll(',','')),Number(m.price.toFixed(2)));
      assert.equal(Number(state.stripPrice.replaceAll(',','')),Number(m.price.toFixed(2)));
      assert.equal(Number(state.stripDelta),Number(delta.toFixed(2)));
      assert(state.change.includes(delta.toFixed(2)) && state.change.includes(pct.toFixed(2)+'%'),JSON.stringify(state));
      assert.equal(state.headline.referencePrice,m.referencePrice);
      assert.equal(state.statsPrice,m.price.toFixed(2)+' TWD');
      assert(state.statsChange.includes(delta.toFixed(2)) && state.statsChange.includes(pct.toFixed(2)+'%'));
      if (range!=='1d' && state.rangeBase>0) {
        const rd=m.price-state.rangeBase, rp=rd/state.rangeBase*100;
        assert(state.statsRange.includes(rd.toFixed(2)) && state.statsRange.includes(rp.toFixed(2)+'%'));
      }
      if (range==='1d' && sym==='__TXF__') assert(!state.high.includes('50194'),'不得把日線區間最高當夜盤最高');
      report.cases.push(state);
      return state;
    }
    for (const sym of ['^TWII','^TWOII','__TXF__']) {
      for (const range of ['1d','6mo']) await select(sym,range);
    }
    if (!live) {
      apiSnapshot.quotes.__TXF__.market.price = 47400;
      apiSnapshot.quotes.__TXF__.market.asOf = '2026-10-16T05:00:00+08:00';
      await page.evaluate(() => window.MarketData.refresh());
      const second=await page.evaluate(()=>({price:document.getElementById('rp-PRICE').textContent,
        range:document.getElementById('rp-RANGE').textContent,base:S.data.rangeBase}));
      assert.equal(second.price,'47400.00 TWD');
      assert(second.range.includes((47400-second.base).toFixed(2)));
      report.secondQuote=second;
    }
    if (live) {
      await page.locator('[data-mkt-sym="__MARGIN_RATIO__"]').first().click();
      await page.waitForFunction(()=>typeof window.S==='object' && S.sym==='__MARGIN_RATIO__');
      const warm=await select('__TXF__','1d');
      assert.equal(warm.windowS,'object');
      report.warmState=warm;
    }
    await select('^TWII','1d');
    await page.screenshot({path:path.join(out,'大盤對齊.png'),fullPage:true});
    await select('__TXF__','1d');
    await page.screenshot({path:path.join(out,'台指期對齊.png'),fullPage:true});
    report.viewports=[];
    for (const viewport of [{width:390,height:844},{width:844,height:390},{width:667,height:375}]) {
      await page.setViewportSize(viewport);
      await page.waitForTimeout(100);
      const boxes=await page.evaluate(()=>['ci-price','ci-chg','ci-high','ci-market-asof'].map(id=>{
        const el=document.getElementById(id), r=el.getBoundingClientRect(), css=getComputedStyle(el);
        return {id,text:el.textContent,x:r.x,y:r.y,width:r.width,height:r.height,display:css.display,visibility:css.visibility};
      }));
      for (const box of boxes) {
        assert(box.width>0 && box.height>0 && box.display!=='none' && box.visibility!=='hidden',JSON.stringify(box));
        assert(box.x>=0 && box.y>=0 && box.x+box.width<=viewport.width+1 && box.y+box.height<=viewport.height+1,JSON.stringify({viewport,box}));
      }
      report.viewports.push({viewport,boxes});
      await page.screenshot({path:path.join(out,`${viewport.width}x${viewport.height}行情對齊.png`),fullPage:true});
    }
    if (!live) {
      assert.equal(report.cases[0].price,'46969.87');
      assert(report.cases[0].change.includes('-1655.96'));
      assert.equal(report.cases[4].price,'47366.00');
      assert.equal(report.cases[4].chartClose,46979,'夜盤不得覆寫歷史日 K');
    }
    if (live) {
      report.healthAfter = await (await context.request.get(base+'/health/live')).json();
      assert.equal(report.healthAfter.runtimeCommit,report.healthBefore.runtimeCommit);
    }
    report.result='指定主圖與行情列情境對齊';
  } catch (error) { report.failure=error.stack; process.exitCode=1; }
  finally {
    await browser.close(); fs.writeFileSync(path.join(out,'驗收結果.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({mode:report.mode,result:report.result,cases:report.cases.length,failure:report.failure,errors:report.errors}));
  }
})();

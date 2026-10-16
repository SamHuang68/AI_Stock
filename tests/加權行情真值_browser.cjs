'use strict';
// 完整正式頁面冷啟動；僅固定網路回覆。期望值來自獨立官方資料，不從產品狀態反算。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/加權行情20261016.json'), 'utf8'));
const expected = fixture.expected;
const runtime = process.env.ST_TRUTH_RUNTIME === '1';
const base = (process.env.ST_TRUTH_BASE || 'https://market-truth.test').replace(/\/$/, '');
const remote = !!process.env.ST_TRUTH_BASE;
const out = process.env.ST_TRUTH_OUTPUT || path.join(root, 'scratch', '加權行情真值');
const report = {模式:runtime ? '實際站自然載入' : '完整頁面網路邊界固定資料', 期望:expected, 案例:[], 頁面錯誤:[]};
function chart(sym, minute) {
  const timestamp = minute ? Array.from({length:30}, (_, i) => 1792126860 + i * 60) : fixture.yahoo.timestamp;
  const close = minute ? timestamp.map((_, i) => expected.price - (29 - i)) : fixture.yahoo.close;
  return {chart:{result:[{meta:{...fixture.yahoo.meta, symbol:sym, dataGranularity:minute ? '1m' : '1d'},
    timestamp, indicators:{quote:[{close, open:close, high:close.map(x => x == null ? null : x + 1),
      low:close.map(x => x == null ? null : x - 1), volume:close.map(x => x == null ? null : 100)}]}}],error:null}};
}
function latch() { let release; const promise = new Promise(resolve => { release = resolve; }); return {promise,release}; }
async function run(browser, order) {
  const context = await browser.newContext({viewport:{width:1440,height:900}, locale:'zh-TW',serviceWorkers:'block'});
  const page = await context.newPage();
  page.setDefaultTimeout(7000);
  const entry = {順序:order, 網路:[], 畫面:[]};
  report.案例.push(entry);
  const gate = latch();
  const batchFinished = latch();
  page.on('pageerror', error => report.頁面錯誤.push({案例:order,訊息:error.message}));
  page.on('requestfinished', request => {
    const u = new URL(request.url());
    if (u.pathname === '/yf/batch' && (u.searchParams.get('syms') || '').includes('^TWII')) batchFinished.release();
    if (/^\/(yf\/|market\/snapshot|pulse)/.test(u.pathname)) entry.網路.push({路徑:u.pathname + u.search,完成時間:Date.now()});
  });
  if (!runtime) await context.route('**/*', async route => {
    const req = route.request(), u = new URL(req.url()), rel = decodeURIComponent(u.pathname.slice(1));
    if (!['GET','HEAD','OPTIONS'].includes(req.method())) return route.abort('blockedbyclient');
    if (rel === 'market/snapshot' || rel === 'pulse') {
      if (order === 'Yahoo先到') await gate.promise;
      return route.fulfill({json:rel === 'pulse' ? {ok:true,indices:{},marketSnapshot:fixture.official} : fixture.official});
    }
    if (rel.startsWith('yf/')) {
      if (order === '官方先到') await gate.promise;
      const body = rel === 'yf/batch'
        ? Object.fromEntries((u.searchParams.get('syms') || '').split(',').map(sym => [sym,chart(sym,false)]))
        : chart(rel.slice(3),u.searchParams.get('interval') === '1m');
      return route.fulfill({json:body});
    }
    if (u.hostname === 'unpkg.com' && u.pathname === '/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js') {
      return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(__dirname,'fixtures/lightweight-charts-4.2.0.js'))});
    }
    if (u.origin === base && !remote) {
      const file = path.resolve(root, !rel || rel === 'index.html' ? 'stock_terminal_v2.html' : rel);
      const types = {'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon'};
      const type = types[path.extname(file)];
      if (file.startsWith(root + path.sep) && type && fs.existsSync(file) && fs.statSync(file).isFile()) {
        return route.fulfill({contentType:type,body:fs.readFileSync(file)});
      }
    }
    if (rel.startsWith('quote/')) return route.fulfill({status:502,json:{ok:false}});
    if (rel === 'twindex') return route.fulfill({json:{ok:false,indices:{}}});
    if (rel === 'margin_ratio') return route.fulfill({json:{ok:true,series:[],points:[]}});
    if (remote) return route.continue();
    if (u.origin === base) return route.fulfill({json:{ok:true}});
    return route.abort('blockedbyclient');
  });
  try {
    await page.goto(base + '/', {waitUntil:'domcontentloaded',timeout:15000});
    await page.locator('#st-ring.on').waitFor();
    // 使用產品既有轉盤與按鈕；兩層選單都按真實入口。
    await page.locator('#st-ring .sr-layer.active [data-id="price"]').click();
    await page.locator('#st-ring .sr-layer.active [data-route="chart"]').click();
    await page.locator('[data-mkt-sym="^TWII"]').first().click();
    if (!runtime) {
      await page.waitForFunction(order => {
        const q = window.MarketData?.get().quotes['^TWII'];
        return order === 'Yahoo先到' ? q?.chartFallback === true : q?.market?.source === 'twse-mis';
      }, order);
      entry.先到行情 = await page.evaluate(() => window.MarketData.get().quotes['^TWII']);
      const delayedBatch = order === '官方先到'
        ? page.waitForResponse(response => new URL(response.url()).pathname === '/yf/batch') : null;
      gate.release();
      if (delayedBatch) await (await delayedBatch).finished();
      let deadline;
      try {
        await Promise.race([batchFinished.promise,new Promise((_,reject) => {
          deadline = setTimeout(() => reject(new Error('未觀測到自然加權批次請求完成')),7000);
        })]);
      } finally { clearTimeout(deadline); }
      // requestfinished 之後讓既有 promise 與畫面繪製消化回覆；無主動行情刷新。
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    }
    await page.waitForFunction(() => {
      const q = window.MarketData?.get().quotes['^TWII'];
      return q?.market?.source === 'twse-mis' && !q.chartFallback;
    });
    const officialDate = await page.evaluate(() => {
      const at = window.MarketData.get().quotes['^TWII'].market.asOf;
      return new Date(Date.parse(at) + 28800000).toISOString().slice(0,10);
    });
    assert.equal(officialDate,expected.tradeDate,'行情交易日不符本案固定真值，不能跳過或宣告通過');
    for (const range of ['1d','6mo']) {
      await page.locator(`[data-rg="${range}"]`).first().click();
      await page.waitForFunction(range => typeof S !== 'undefined' && S.sym === '^TWII' && S.range === range &&
        S.dataIdentity?.sym === '^TWII' && S.dataIdentity?.loadSeq === window.__loadSeq && !!S.data?.marketHeadline,
      range);
      // 等正常繪製完成；不強刷行情，也不改寫全域狀態。
      await page.waitForFunction(({price,change,changePct}) => {
        const clean = text => (text || '').replaceAll(',','');
        const cell = document.querySelector('[data-mkt-sym="^TWII"]');
        const text = document.getElementById('ci-chg')?.textContent || '';
        return Number(clean(document.getElementById('ci-price')?.textContent)) === price &&
          Number(clean(cell?.querySelector('.px')?.textContent)) === price &&
          cell?.querySelector('.delta')?.textContent === '+' + change.toFixed(2) &&
          text.includes('+' + change.toFixed(2)) && text.includes('+' + changePct.toFixed(2) + '%');
      }, expected);
      const state = await page.evaluate(() => {
        const cell = document.querySelector('[data-mkt-sym="^TWII"]'), text = id => document.getElementById(id)?.textContent;
        return {range:S.range,price:text('ci-price'),change:text('ci-chg'),stripPrice:cell?.querySelector('.px')?.textContent,
          stripDelta:cell?.querySelector('.delta')?.textContent,stripPct:cell?.querySelector('.ch')?.textContent,
          statsPrice:text('rp-PRICE'),statsChange:text('rp-CHANGE'),quote:window.MarketData.get().quotes['^TWII'],
          headline:S.data.marketHeadline,windowS:typeof window.S};
      });
      entry.畫面.push(state);
      const market = state.quote.market;
      const tradeDate = new Date(Date.parse(market.asOf) + 28800000).toISOString().slice(0,10);
      assert.equal(tradeDate, expected.tradeDate, '實際行情交易日不符本案固定真值，不能跳過或宣告通過');
      assert.equal(market.price,expected.price,'官方現價');
      assert.equal(market.referencePrice,expected.referencePrice,'官方昨收');
      assert.equal(state.headline.referencePrice,expected.referencePrice,'主圖昨收');
      assert.equal(state.stripDelta,'+' + expected.change.toFixed(2),'行情列漲跌');
      assert.equal(state.stripPct,'▲' + expected.changePct.toFixed(2) + '%','行情列漲幅');
      assert.equal(state.statsPrice,expected.price.toFixed(2) + ' TWD','統計現價');
      assert.equal(state.statsChange,'+' + expected.change.toFixed(2) + ' (+' + expected.changePct.toFixed(2) + '%)','統計漲跌');
      assert.equal(state.windowS,'undefined','冷啟動不得由測試注入 window.S');
      await page.screenshot({path:path.join(out,`${order}-${range}.png`),fullPage:true});
    }
    assert.equal(report.頁面錯誤.length,0,'完整頁面不得有未處理 JavaScript 錯誤');
    entry.結果 = '通過';
  } catch (error) {
    entry.結果 = '失敗';
    await page.screenshot({path:path.join(out,`${order}-失敗.png`),fullPage:true}).catch(() => {});
    throw error;
  } finally { gate.release(); await context.close(); }
}
(async () => {
  fs.mkdirSync(out,{recursive:true});
  let browser;
  try {
    assert(!runtime || remote,'實際站模式必須設定 ST_TRUTH_BASE');
    browser = await chromium.launch({headless:true});
    for (const order of runtime ? ['實際站'] : ['Yahoo先到','官方先到']) await run(browser,order);
    report.結果 = '通過';
  } catch (error) { report.結果 = '失敗'; report.失敗 = error.stack; process.exitCode = 1; }
  finally {
    if (browser) await browser.close();
    fs.writeFileSync(path.join(out,'驗收結果.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  }
})();

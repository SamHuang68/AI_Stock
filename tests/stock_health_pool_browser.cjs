'use strict';
// 完整產品模組、固定資料與可控回覆順序；不連正式服務，不計算市場績效。
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict'), crypto = require('node:crypto');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', 'health-pool'));
const read = file => fs.readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n');
const source = read('src/ui/stock_health_v5.js'), infoSource = read('src/core/info_v2.js');
const report = { fixtureOnly:true, checks:[], pageErrors:[], unexpectedNetwork:[],
  sourceHashes:Object.fromEntries([['src/ui/stock_health_v5.js',source],['src/core/info_v2.js',infoSource]]
    .map(([file,text]) => [file,crypto.createHash('sha256').update(text).digest('hex')])) };

(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true});
  try {
    async function run(name, test) {
      const page = await browser.newPage({viewport:{width:1100,height:900}});
      page.on('pageerror', error => report.pageErrors.push({name,message:error.message}));
      await page.route('**/*', route => {
        if (route.request().url() === 'https://health-pool-fixture.test/') {
          return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>成績單離線驗收</title><h1>固定資料，非市場績效</h1><div id="rpanel"></div></html>'});
        }
        report.unexpectedNetwork.push(route.request().url()); return route.abort();
      });
      await page.goto('https://health-pool-fixture.test/');
      await page.evaluate(() => {
        localStorage.setItem('st_stock_health_mode_v1','advanced');
        window.S = {sym:'2330',mkt:'TW',tab:'health',wl:[]};
        window.reads = []; window.posts = []; window.mockCalls = [];
        window.AppKernel = {api:{
          getJson(url, options = {}) {
            mockCalls.push(url);
            if (url.startsWith('/stock-signals/pooled?')) {
              // 刻意不理會 signal，證明單靠取消請求並不足以保護畫面與快取。
              return new Promise((resolve,reject) => reads.push({url,options,resolve,reject}));
            }
            if (url === '/stock-signals/push-config') return Promise.resolve({mode:'off',symbols:0});
            if (url.startsWith('/stock-signals?')) {
              const p = new URLSearchParams(url.split('?')[1]);
              return Promise.resolve({ok:true,symbol:p.get('sym'),market:p.get('market'),asOf:'2026-10-02',
                health:{lights:[],summary:{sentence:'固定規則案例'}},events:[]});
            }
            throw Error('未預期的讀取：'+url);
          },
          postJson(url, body) {
            mockCalls.push('MOCK POST '+url);
            if (url === '/stock-signals/pooled/refresh') return new Promise((resolve,reject) => posts.push({url,body,resolve,reject}));
            if (url === '/stock-signals/watchlist') return Promise.resolve({});
            throw Error('未預期的寫入：'+url);
          }
        }};
        window.poolFixture = (market,marker) => ({available:true,market,symbols:market==='TW'?111:222,
          window:{from:'2020-01-01',to:'2026-10-02'},generatedAt:'2026-10-03',minSample:100,minSymbols:5,
          scoreboard:[],method:marker,caveats:['固定案例，不代表實際績效']});
      });
      await page.addScriptTag({content:source});
      const start = async (sym='2330',mkt='TW') => {
        await page.evaluate(({sym,mkt}) => {
          S.sym=sym;S.mkt=mkt;StockHealthV5.renderInto(document.getElementById('rpanel'),true);
        }, {sym,mkt});
        await page.waitForFunction(sym => document.querySelector('.sh5-title')?.textContent.includes(sym),sym);
      };
      const open = async expected => {
        await page.locator('#sh5-pool').evaluate(node => { node.open=true; });
        await page.waitForFunction(n => reads.length===n,expected);
      };
      const close = async () => {
        await page.locator('#sh5-pool').evaluate(node => {
          window.closeHandled=false;
          node.addEventListener('toggle',()=>{window.closeHandled=true;},{once:true});
          node.open=false;
        });
        await page.waitForFunction(()=>window.closeHandled);
      };
      const finish = (index,market,marker) => page.evaluate(async ({index,market,marker}) => {
        reads[index].resolve(poolFixture(market,marker));
        for (let i=0;i<8;i++) await Promise.resolve();
      },{index,market,marker});
      const finishPost = index => page.evaluate(async index => {
        posts[index].resolve({ok:true}); for(let i=0;i<8;i++) await Promise.resolve();
      },index);
      const body = () => page.locator('#sh5-pool-body').textContent();
      try {
        await test({page,start,open,close,finish,finishPost,body});
        report.checks.push({name,passed:true});
      } finally { await page.close(); }
    }

    await run('TW 晚到回覆不覆蓋 US，也不污染市場快取',async ({page,start,open,finish,body}) => {
      await start();await open(1);
      await start('AAPL','US');await open(2);
      await finish(1,'US','US目前收據');await finish(0,'TW','TW過期收據');
      assert.match(await body(),/US目前收據/);assert.doesNotMatch(await body(),/TW過期收據/);
      assert.match(await page.locator('.sh5-title').innerText(),/AAPL/);
      await page.screenshot({path:path.join(output,'latest-market.png')});
      await start('2303','TW');
      assert.doesNotMatch(await body(),/US目前收據|TW過期收據/);
    });
    await run('US 晚到回覆不覆蓋 TW',async ({start,open,finish,body}) => {
      await start('AAPL','US');await open(1);
      await start();await open(2);
      await finish(1,'TW','TW目前收據');await finish(0,'US','US過期收據');
      assert.match(await body(),/TW目前收據/);assert.doesNotMatch(await body(),/US過期收據/);
    });
    await run('有效快取依市場隔離，同市場換股仍可沿用',async ({start,open,finish,body}) => {
      await start();await open(1);await finish(0,'TW','TW有效快取');
      await start('AAPL','US');assert.doesNotMatch(await body(),/TW有效快取/);
      await open(2);await finish(1,'US','US有效快取');
      await start('2303','TW');assert.match(await body(),/TW有效快取/);assert.doesNotMatch(await body(),/US有效快取/);
      await start('MSFT','US');assert.match(await body(),/US有效快取/);assert.doesNotMatch(await body(),/TW有效快取/);
    });
    await run('關閉重開使原請求失效，來源忽略取消仍不覆寫',async ({page,start,open,close,finish,body}) => {
      await start();await open(1);await close();
      assert.equal(await page.evaluate(()=>reads[0].options.signal.aborted),true);
      await open(2);await finish(1,'TW','重新開啟收據');await finish(0,'TW','關閉前收據');
      assert.match(await body(),/重新開啟收據/);assert.doesNotMatch(await body(),/關閉前收據/);
      await start('2303','TW');assert.match(await body(),/重新開啟收據/);
    });
    await run('關閉時交付的資料不進快取',async ({start,open,close,finish,body}) => {
      await start();await open(1);await close();await finish(0,'TW','關閉後收據');
      await start('2303','TW');assert.doesNotMatch(await body(),/關閉後收據/);
    });
    await run('手動重算晚回覆不在另一市場接續讀取',async ({page,start,open,finish,finishPost,body}) => {
      await start();await open(1);await finish(0,'TW','重算前收據');
      await page.locator('#sh5-pool-refresh').click();
      await page.waitForFunction(()=>posts.length===1);
      assert.equal(await page.evaluate(()=>posts[0].body.market),'TW');
      await start('AAPL','US');await open(2);await finish(1,'US','US目前收據');
      await finishPost(0);
      assert.equal(await page.evaluate(()=>reads.length),2);
      assert.match(await body(),/US目前收據/);
    });
    await run('重算後已送出的 GET 不能覆蓋新卡片',async ({page,start,open,finish,finishPost,body}) => {
      await start();await open(1);await finish(0,'TW','重算前收據');
      await page.locator('#sh5-pool-refresh').click();await page.waitForFunction(()=>posts.length===1);
      await finishPost(0);await page.waitForFunction(()=>reads.length===2);
      await start('AAPL','US');await open(3);await finish(2,'US','US目前收據');
      await finish(1,'TW','舊重算收據');
      assert.match(await body(),/US目前收據/);assert.doesNotMatch(await body(),/舊重算收據/);
      await start();assert.match(await body(),/重算前收據/);assert.doesNotMatch(await body(),/舊重算收據/);
    });
    await run('手動重算期間關閉重開，舊 POST 不追加讀取',async ({page,start,open,close,finish,finishPost,body}) => {
      await start();await open(1);await finish(0,'TW','重算前收據');
      await page.locator('#sh5-pool-refresh').click();await page.waitForFunction(()=>posts.length===1);
      await close();await open(2);await finish(1,'TW','重新開啟收據');await finishPost(0);
      assert.equal(await page.evaluate(()=>reads.length),2);
      assert.match(await body(),/重新開啟收據/);
    });
    await run('同卡片手動重算成功仍會讀取及呈現新資料',async ({page,start,open,finish,finishPost,body}) => {
      await start();await open(1);await finish(0,'TW','更新前收據');
      await page.locator('#sh5-pool-refresh').click();await page.waitForFunction(()=>posts.length===1);
      await finishPost(0);await page.waitForFunction(()=>reads.length===2);
      await finish(1,'TW','更新後收據');
      assert.match(await body(),/更新後收據/);assert.equal(await page.locator('#sh5-pool-refresh').isEnabled(),true);
    });
    await run('目前讀取失敗可唯讀重試，舊失敗不污染新結果',async ({page,start,open,close,finish,body}) => {
      await start();await open(1);
      await page.evaluate(()=>reads[0].reject(Error('固定缺資料')));
      await page.locator('[data-pool-retry]').waitFor();
      assert.match(await body(),/成績單讀取失敗/);assert.doesNotMatch(await body(),/載入中/);
      await page.locator('[data-pool-retry]').click();await page.waitForFunction(()=>reads.length===2);
      await close();await open(3);await finish(2,'TW','最新重試收據');
      await page.evaluate(()=>reads[1].reject(Error('舊失敗')));
      assert.match(await body(),/最新重試收據/);assert.doesNotMatch(await body(),/舊失敗/);
      assert.equal(await page.evaluate(()=>posts.length),0);
    });
    await run('指標與劇本說明不捏造最高勝率或固定比例',async ({page}) => {
      await page.evaluate(()=>{
        window.STRATEGIES=[];window.PRESETS=[{key:'fixture',lbl:'固定劇本',signals:[],desc:'規則條件',when:'固定情境'}];
        window.IND_DEFS=[];window.clearInd=()=>{};
      });
      await page.addScriptTag({content:infoSource});
      const claims=await page.evaluate(()=>({kd:INFO_CONTENT['ind:K'].body,preset:INFO_CONTENT['preset:fixture'].body}));
      assert.doesNotMatch(claims.kd,/勝率最高/);
      assert.doesNotMatch(claims.preset,/70\s*[~～–-]\s*80\s*%|專業投資人常用組合篩選/);
      assert.match(claims.preset,/歷史統計與真實前瞻結果需分開核對/);
    });
    assert.deepEqual(report.pageErrors,[]);
    assert.deepEqual(report.unexpectedNetwork,[]);
    console.log('成績單離線瀏覽器驗收通過：'+report.checks.length+' 個案例，未連正式服務。');
  } finally {
    fs.writeFileSync(path.join(output,'summary.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});

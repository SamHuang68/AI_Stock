'use strict';
// 載入產品模組與真實 modal；資料、回覆順序皆固定，不連行情／正式服務。
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict'), crypto = require('node:crypto');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', 'pattern-modal'));
const read = name => fs.readFileSync(path.join(root, name), 'utf8').replace(/\r\n/g, '\n');
const modalSource = read('src/core/pro_v2.js'), patternSource = read('src/chart/pattern_v3.js');
const modalStart = modalSource.indexOf('function showProModal(');
const modalEnd = modalSource.indexOf('// ============================================================\n// UI INJECTION — buttons + replay bar', modalStart);
assert(modalStart >= 0 && modalEnd > modalStart, '找不到既有 modal 邊界');
const report = { fixtureOnly: true, browser: 'chromium', checks: [], pageErrors: [], networkRequests: [],
  sourceHashes: Object.fromEntries([['src/core/pro_v2.js',modalSource],['src/chart/pattern_v3.js',patternSource]]
    .map(([file, text]) => [file, crypto.createHash('sha256').update(text).digest('hex')])) };
const candles = count => Array.from({length:count}, (_, i) => {
  const close = 100 + i * 0.3 + Math.sin(i * Math.PI / 8) * 4;
  return {time:1735689600 + i * 86400, open:close - 0.3, high:close + 1, low:close - 1, close, volume:1000};
});
(async () => {
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true});
  try {
    async function run(name, test, viewport = {width:1100, height:1000}) {
      const page = await browser.newPage({viewport, hasTouch:viewport.width < 500});
      await page.route('**/*', route => { report.networkRequests.push(route.request().url()); return route.abort(); });
      page.on('pageerror', error => report.pageErrors.push({name, message:error.message}));
      await page.setContent('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>型態視窗離線驗收</title><style>:root{--bg2:#101827;--gold:#fbbf24;--gold-m:#8c711b;--text:#e2e8f0;--tlo:#b3bfd0;--tf:#9aa9bd;--border:#344154;--red:#f87171;--green:#4ade80;--orange:#fb923c}body{background:#101827;color:#e2e8f0;font:16px sans-serif}*{box-sizing:border-box}</style><h1>型態視窗離線驗收</h1><p>固定資料，不是正式行情</p><div id="rangebar"></div><div id="pro-tools"></div>');
      await page.evaluate(() => {
        window.S = {sym:'2330',mkt:'TW',candles:[],patternsEnabled:false};
        window.__loadSeq = 1; window.SERVER = 'https://pattern-fixture.invalid';
        window.parseYF = raw => raw; window.renderChart = () => {};
        window.requests = []; window.runs = []; window.ignoreAbort = true;
        window.fetch = (url, options = {}) => new Promise((resolve, reject) => {
          const item = {url, signal:options.signal, resolve, reject};
          window.requests.push(item);
          options.signal?.addEventListener('abort', () => {
            if (!window.ignoreAbort) reject(new DOMException('fixture cancelled', 'AbortError'));
          }, {once:true});
        });
      });
      await page.addScriptTag({content:modalSource.slice(modalStart, modalEnd)});
      await page.addScriptTag({content:patternSource});
      const start = (sym = '2330', mkt = 'TW', change = true) => page.evaluate(({sym,mkt,change}) => {
        S.sym=sym; S.mkt=mkt; if(change) window.__loadSeq++;
        window.runs.push(PatternV3.showPatternsModal());
      }, {sym,mkt,change});
      const finish = (index, count = 80, status = 200) => page.evaluate(async ({index,data,status}) => {
        requests[index].resolve({ok:status===200,status,json:async()=>({candles:data})});
        await runs[index];
      }, {index,data:candles(count),status});
      const text = () => page.locator('#pro-modal-bg').innerText();
      try {
        await test({page,start,finish,text});
        report.checks.push({name,passed:true});
      } finally { await page.close(); }
    }
    await run('較舊 2330 晚回覆不能覆蓋 2303', async ({page,start,finish,text}) => {
      await start(); await start('2303');
      assert.equal(await page.evaluate(() => requests[0].signal.aborted), true);
      await finish(1,80);
      assert.match(await text(), /2303/);
      await finish(0,65);  // 模擬來源無視 abort，確實交付舊回覆。
      assert.match(await text(), /2303/); assert.doesNotMatch(await text(), /2330/);
      assert.match(await text(), /80/);
      await page.screenshot({path:path.join(output,'latest-symbol.png')});
    });
    await run('按關閉後，晚到回覆不能重新開啟', async ({page,start,finish}) => {
      await start(); await page.locator('[data-pro="modal-close"]').click();
      assert.equal(await page.evaluate(() => requests[0].signal.aborted), true);
      await finish(0);
      assert.equal(await page.locator('#pro-modal-bg').count(),0);
    }, {width:390,height:844});
    await run('同標的關閉重開採用新請求，取消本文不污染快取', async ({page,start,finish,text}) => {
      await start(); await page.locator('[data-pro="modal-close"]').click();
      await start('2330','TW',false);
      await finish(1,80); await finish(0,65);
      assert.match(await text(), /80/);
      assert.equal(await page.evaluate(async () => (await PatternV3.loadPatternCandles('2330','TW')).length),80);
      assert.equal(await page.evaluate(() => requests.length),2);
    });
    await run('圖表 A→B→A 仍以載入序號拒收舊回覆', async ({page,start,finish}) => {
      await start();
      await page.evaluate(() => { S.sym='2303'; window.__loadSeq++; S.sym='2330'; window.__loadSeq++; });
      await finish(0);
      assert.equal(await page.locator('#pro-modal-bg').count(),0);
    });
    await run('相同代碼切換市場不接收原市場回覆', async ({page,start,finish}) => {
      await start();
      await page.evaluate(() => { S.mkt='US'; });
      await finish(0);
      assert.equal(await page.locator('#pro-modal-bg').count(),0);
    });
    await run('其他工具取代 modal 後不受舊型態回覆影響', async ({page,start,finish,text}) => {
      await start();
      await page.evaluate(() => showProModal('<p>其他工具內容</p>'));
      await finish(0);
      assert.match(await text(), /其他工具內容/);
      await page.locator('[data-pro="modal-close"]').click();
      assert.equal(await page.locator('#pro-modal-bg').count(),0);
    });
    await run('目前請求 HTTP 失敗顯示可操作錯誤，舊失敗不覆蓋新成功', async ({page,start,finish,text}) => {
      await start(); await finish(0,0,503);
      assert.match(await text(), /無法載入 2330/);
      assert.doesNotMatch(await text(), /抓取 2 年/);
      await start('2303'); await start('2317');
      await finish(2); await finish(1,0,503);
      assert.match(await text(), /2317/); assert.doesNotMatch(await text(), /無法載入/);
    });
    await run('標頭先到、取消後本文晚到，仍不能寫入快取', async ({page,start,finish}) => {
      await start();
      await page.evaluate(() => requests[0].resolve({ok:true,status:200,json:() => new Promise(resolve => {window.bodyResolve=resolve;})}));
      await page.waitForFunction(() => typeof window.bodyResolve==='function');
      await page.locator('[data-pro="modal-close"]').click();
      await page.evaluate(async data => { bodyResolve({candles:data}); await runs[0]; }, candles(65));
      assert.equal(await page.locator('#pro-modal-bg').count(),0);
      await start('2330','TW',false);
      assert.equal(await page.evaluate(() => requests.length),2);
      await finish(1);
    });
    await run('新圖載入事件取消請求；遵守 abort 的來源亦正常結束', async ({page,start}) => {
      await page.evaluate(() => { window.ignoreAbort=false; });
      await start();
      await page.evaluate(async () => {
        S.sym='2303'; window.__loadSeq++; window.dispatchEvent(new Event('symLoaded')); await runs[0];
      });
      assert.equal(await page.locator('#pro-modal-bg').count(),0);
      assert.equal(await page.evaluate(() => requests[0].signal.aborted),true);
    });
    await run('型態規則未包裝成勝率或星級，獨立歷史統計保留', async ({page,start,finish,text}) => {
      const values = await page.evaluate(() => {
        const p = (a,b) => [{price:a,time:1},{price:b,time:2}];
        return [PatternV3.detectTrendStructure([], {highs:p(110,120),lows:p(90,100)}),
                PatternV3.detectTrendStructure([], {highs:p(120,110),lows:p(100,90)})];
      });
      for (const value of values) {
        assert.match(value.reliability, /未驗證勝率/);
        assert.doesNotMatch(value.reliability, /最高勝率|⭐/);
      }
      assert.doesNotMatch(patternSource, /最高勝率|⭐/);
      await start(); await finish(0);
      await page.waitForFunction(() => !document.querySelector('#pat-hit-rates').textContent.includes('計算型態'));
      assert.match(await text(), /未經勝率排序，不代表獲利機率/);
      assert.match(await text(), /型態歷史命中率/);
      await page.evaluate(() => {
        document.querySelectorAll('details').forEach(el => {el.open=true;});
        document.querySelector('#pro-modal-bg > div').scrollTop=1e6;
      });
      await page.screenshot({path:path.join(output,'rule-disclaimer.png')});
    });
    await run('失去視窗歸屬後停止分批統計，不交付過期結果', async ({page}) => {
      const value = await page.evaluate(async data => {
        let active=true, done=false;
        PatternV3.hitRates(data,10,()=>{done=true;},()=>active);
        active=false;
        // 已排入的首個續批先執行，再讀取結果；不靠長時間睡眠。
        await new Promise(resolve => setTimeout(resolve,0));
        return done;
      }, candles(200));
      assert.equal(value,false);
    });
    assert.deepEqual(report.pageErrors,[]);
    assert.deepEqual(report.networkRequests,[]);
    console.log(JSON.stringify({passed:report.checks.length,pageErrors:0,networkRequests:0,output}));
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(report,null,2)+'\n');
  }
})().catch(error => { console.error(error); process.exitCode=1; });

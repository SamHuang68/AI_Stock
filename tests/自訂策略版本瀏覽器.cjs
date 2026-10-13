'use strict';
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', '自訂策略版本驗收'));
const files = ['backtest_v3.js', '策略版本.js', 'strategy_builder_v3.js'];
const baselineCommit = 'f2db8085851c44e76f21d519b601ca820d4f733a';
let baselineAvailable = false;
try {
  execFileSync('git', ['cat-file', '-e', baselineCommit + '^{commit}'], { cwd: root, stdio: 'ignore' });
  baselineAvailable = true;
} catch (error) {
  if (error.status !== 128 && error.status !== 1) throw error;
  console.log('固定舊版提交在此工作樹不可讀取；本次只驗證候選，未比較修改前畫面。');
}
const candles = Array.from({length:100}, (_,i) => {
  const close = 100 + i * .2 + Math.sin(i / 3) * 8;
  return {time: 1767225600 + i * 86400, open:close-.3, high:close+1, low:close-1, close, volume:1000};
});
(async () => {
  fs.mkdirSync(output,{recursive:true});
  const browser = await chromium.launch({headless:true});
  const checks = [], errors = [];
  try {
    for (const width of [1100, 390]) {
      for (const baseline of (baselineAvailable ? [true, false] : [false])) {
        const page = await browser.newPage({viewport:{width,height:900},acceptDownloads:true});
        page.on('pageerror', e => errors.push(e.message));
        await page.route('**/*', route => route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>策略固定資料驗收</title><body><button id="open">策略條件</button></body></html>'}));
        await page.goto('http://localhost:19479');
        await page.evaluate(data => { window.S={sym:'2330',mkt:'TW',data:{candles:data}}; window.currentRangeDef=()=>({interval:'1d'}); },candles);
        for (const f of files.filter(f => !baseline || f !== '策略版本.js')) {
          const content = baseline ? execFileSync('git',['show',baselineCommit+':src/screener/'+f],{cwd:root,encoding:'utf8'}) : fs.readFileSync(path.join(root,'src/screener',f),'utf8');
          await page.addScriptTag({content});
        }
        await page.evaluate(()=>document.getElementById('open').onclick=()=>stratBuilderOpen());
        await page.click('#open');
        await page.locator('#sb-run').click();
        assert.ok((await page.locator('#sb-contract').innerText()).includes('下一可成交開盤'));
        await page.screenshot({path:path.join(output,`${baseline?'修改前':'修改後'}-${width}.png`),fullPage:true});
        assert.equal(await page.evaluate(()=>document.getElementById('sb-box').scrollWidth <= document.getElementById('sb-box').clientWidth + 2),true,'對話框無水平溢出');
        if (!baseline) {
          await page.locator('summary').filter({hasText:'八種既有策略'}).click();
          await page.fill('#sb-train-end','2026-03-01'); await page.fill('#sb-test-end','2026-04-10');
          await page.click('#sb-holdout');
          assert.ok((await page.locator('#sb-msg').innerText()).includes('八種既有策略'));
          await page.locator('summary').filter({hasText:'目前自訂條件'}).click();
          await page.fill('#sb-custom-train-end','2026-03-01'); await page.fill('#sb-custom-test-end','2026-04-10');
          await page.click('#sb-custom-holdout');
          await page.waitForFunction(()=>window._sbLast?.report);
          assert.ok((await page.locator('#sb-msg').innerText()).includes('固定自訂策略'));
          const first = await page.evaluate(()=>window._sbLast.report.version);
          const report = await page.evaluate(()=>window._sbLast.report);
          assert.equal(report.manifest.version,report.version);
          assert.equal(report.split.test.curve[0].equity,1);
          await page.fill('#sb-maxbars','3'); await page.click('#sb-freeze');
          await page.waitForFunction(()=>StrategyVersion.list().length===2);
          const versions=await page.evaluate(()=>StrategyVersion.list());
          assert.equal(versions[0].version,first); assert.notEqual(versions[1].version,first);
          const downloadWait=page.waitForEvent('download'); await page.click('#sb-export-version');
          const download=await downloadWait; await download.saveAs(path.join(output,`匯出版本-${width}.json`));
          const downloaded=JSON.parse(fs.readFileSync(path.join(output,`匯出版本-${width}.json`),'utf8'));
          assert.equal(downloaded.version,versions[1].version);
          const reportWait=page.waitForEvent('download'); await page.click('#sb-export-report');
          const rd=await reportWait; await rd.saveAs(path.join(output,`樣本外報告-${width}.json`));
          assert.equal(JSON.parse(fs.readFileSync(path.join(output,`樣本外報告-${width}.json`),'utf8')).version,first);
          await page.screenshot({path:path.join(output,`樣本外結果-${width}.png`),fullPage:true});
          await page.keyboard.press('Escape');
          assert.equal(await page.locator('#sb-modal').isVisible(),false);
          assert.equal(await page.evaluate(()=>document.activeElement.id),'open');
          checks.push({width,passed:true,version:first});
        }
        await page.close();
      }
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'驗收結果.json'),JSON.stringify({fixtureOnly:true,baselineCommit,baselineCompared:baselineAvailable,
      baselineReason:baselineAvailable ? '已比較固定舊版' : '固定舊版提交不可讀取，未比較修改前畫面',checks,errors},null,2));
    console.log('自訂策略版本瀏覽器驗收通過：桌面、窄螢幕、舊入口、自訂樣本外、下載與焦點返回');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});

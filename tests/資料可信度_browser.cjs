'use strict';
// 真實瀏覽器執行產品模組；來源固定於離線 fixture，不是策略績效或正式資料驗證。
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const browsers=require(process.env.ST_PLAYWRIGHT || 'playwright');
const root=path.resolve(__dirname,'..');
const output=path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root,'scratch','資料可信度瀏覽器'));
const origin='https://st-data-evidence.test';
const files=['src/ui/hub_v5.js','src/ui/daily_cache_v3.js'];
const sources=new Map(files.map(file=>['/'+file,fs.readFileSync(path.join(root,file),'utf8')]));
const report={fixtureOnly:true,physicalDevice:false,nativeSafari:false,screenReader:false,checks:[],pageErrors:[],requests:[],sourceHashes:{}};
for(const [file,source] of sources)report.sourceHashes[file]=crypto.createHash('sha256').update(source).digest('hex');
const html='<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+
 '<title>資料可信度離線驗收</title><style>body{margin:8px;background:#101827;color:#e2e8f0;font:15px system-ui}*{box-sizing:border-box}button{font:inherit;padding:10px}#shell-views{height:78vh;min-width:0}#pro-tools{margin:8px}dialog button{font:inherit;padding:9px}</style>'+
 '<h1>固定收據，不是市場績效</h1><div id="pro-tools"></div><div id="shell-views"><div id="view-settings" class="sv-panel on"><div id="mount-settings"></div></div></div>'+
 '<script>window.SERVER="";window.S={sym:"2330",mkt:"TW",watches:{}};window.ShellV5={go(){},goDashboard(){}};</script>'+
 files.map(file=>'<script src="/'+file+'"></script>').join('')+'</html>';
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 for(const engine of (process.env.ST_BROWSER_ENGINES || 'chromium').split(',')){
  const browser=await browsers[engine].launch({headless:true});
  try{
   for(const [width,height] of [[1440,1000],[390,844],[844,390]]){
    const context=await browser.newContext({viewport:{width,height},hasTouch:true});
    const page=await context.newPage();let commit='a'.repeat(40);
    page.on('pageerror',error=>report.pageErrors.push({engine,width,message:error.message}));
    await page.route('**/*',route=>{
     const req=route.request(),url=new URL(req.url());report.requests.push({engine,width,path:url.pathname,method:req.method()});
     if(url.origin!==origin||req.method()!=='GET')return route.abort();
     if(url.pathname==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:html});
     if(sources.has(url.pathname))return route.fulfill({contentType:'application/javascript; charset=utf-8',body:sources.get(url.pathname)});
     const responses={
      '/health':{status:'ok',runtimeCommit:commit},'/features':{flags:{}},'/datasources':{sources:[]},
      '/sync/status':{running:false,counts:{breadth:0},datasets:[]},
      '/daily-cache/status':{status:'completed',range:'1y',symbols:[{symbol:'2330',market:'TW'}],completed:1,
       results:[{symbol:'2330',rows:12,quality:{observed:12,accepted:5,conflicts:7,missing:2,invalid:0,
        conflictDates:['2026-09-23'],missingDates:['2026-09-29'],note:'官方與原始成交量不同；保留雙份證據，沒有自動採用。'}}]}
     };
     if(!(url.pathname in responses))return route.abort();
     return route.fulfill({contentType:'application/json; charset=utf-8',body:JSON.stringify(responses[url.pathname])});
    });
    await page.goto(origin);
    await page.evaluate(()=>SettingsV5.activate());
    await page.waitForFunction(()=>document.querySelector('#hub-runtime-commit')?.textContent==='aaaaaaaaaaaa');
    commit='<img src=x onerror="window.invalidCommitExecuted=true">';
    await page.evaluate(()=>SettingsV5.activate());
    await page.waitForFunction(()=>document.querySelector('#hub-runtime-commit')?.textContent==='版本尚未提供');
    assert.equal(await page.evaluate(()=>!!window.invalidCommitExecuted),false);
    await page.locator('#btn-daily-cache').tap();
    await page.waitForFunction(()=>document.querySelector('#dc-status')?.textContent.includes('來源衝突 7'));
    const status=await page.locator('#dc-status').innerText();
    assert.match(status,/品質通過 5/);assert.match(status,/缺日 2/);assert.doesNotMatch(status,/新增 12/);
    await page.locator('#dc-evidence summary').tap();
    assert.match(await page.locator('#dc-evidence pre').innerText(),/2026-09-23/);
    assert.match(await page.locator('#dc-evidence pre').innerText(),/沒有自動採用/);
    const box=await page.locator('#dc-dialog').boundingBox();assert(box.x>=-1&&box.x+box.width<=width+1);
    const scroll=await page.locator('#dc-dialog').evaluate(n=>({scrollHeight:n.scrollHeight,clientHeight:n.clientHeight,scrollWidth:n.scrollWidth,clientWidth:n.clientWidth}));
    assert(scroll.scrollWidth<=scroll.clientWidth+1,'日線來源證據不可橫向裁切');
    await page.screenshot({path:path.join(output,engine+'-'+width+'x'+height+'.png')});
    await page.keyboard.press('Escape');
    await page.locator('#dc-dialog').waitFor({state:'hidden'});
    assert.equal(await page.evaluate(()=>document.activeElement.id),'btn-daily-cache');
    report.checks.push({engine,version:browser.version(),width,height,keyboardEscape:true,focusReturned:true,
      sourceAndQualitySeparated:true,unknownRevisionSafe:true,evidenceReadable:true,scroll});
    await context.close();
   }
  }finally{await browser.close();}
 }
 assert.deepEqual(report.pageErrors,[]);assert(report.requests.every(r=>r.method==='GET'));
 report.passed=true;
 console.log('資料可信度與版本：'+report.checks.length+' 組真實瀏覽器／尺寸驗收通過；離線 fixture 不代表策略績效。');
})().catch(error=>{report.error=error.stack;console.error(error);process.exitCode=1;}).finally(()=>{
 report.at=new Date().toISOString();fs.writeFileSync(path.join(output,'驗收.json'),JSON.stringify(report,null,2));
});

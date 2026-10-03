'use strict';
// 真實瀏覽器執行產品模組；來源固定於離線 fixture，不是策略績效或正式資料驗證。
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const browsers=require(process.env.ST_PLAYWRIGHT || 'playwright');
const root=path.resolve(__dirname,'..');
const output=path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root,'scratch','資料可信度瀏覽器'));
const origin='https://st-data-evidence.test';
const files=['src/ui/hub_v5.js','src/ui/daily_cache_v3.js','src/ui/toolbar_v3.js'];
const sources=new Map(files.map(file=>['/'+file,fs.readFileSync(path.join(root,file),'utf8')]));
const report={fixtureOnly:true,physicalDevice:false,nativeSafari:false,screenReader:false,checks:[],focusInterleavings:[],pageErrors:[],requests:[],sourceHashes:{}};
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
    const page=await context.newPage();let commit='a'.repeat(40),sourceMode='normal',pendingSource=null;
    await page.addInitScript(()=>{
     // 追蹤固定 API 本文讀取，確保舊回覆真的交付才斷言，不依賴固定毫秒等待。
     const nativeFetch=window.fetch.bind(window);window.fixturePendingJson=0;
     window.fetch=(...args)=>{
      window.fixturePendingJson++;
      return nativeFetch(...args).then(response=>{
       if(!response.ok){window.fixturePendingJson--;return response;}
       const nativeJson=response.json.bind(response);
       response.json=()=>nativeJson().finally(()=>{window.fixturePendingJson--;});
       return response;
      },error=>{window.fixturePendingJson--;throw error;});
     };
    });
    const sourceFixture={sources:[
     {name:'零筆快取',kind:'file',status:{count:0,updated:0}},
     {name:'缺少統計',kind:'file',status:{count:null,updated:null}},
     {name:'巨觀序列',kind:'file',provider:'來源<script>window.sourceInjected=true</script>',reliability:'official',
      status:{count:12,updated:1759276800,publishable:false,staleCount:3}},
     {name:'即時介面',kind:'live',status:{count:0,updated:0}},
     {name:'每日介面',kind:'daily',status:{count:0,updated:0}},
     {name:'舊版狀態',status:'等待核對',note:'<img src=x onerror="window.sourceInjected=true">'},
     {name:'來源錯誤',status:{ok:false,error:{message:'無法讀取<script>'}}},
     {name:'缺少狀態',reliability:'official'}
    ]};
    page.on('pageerror',error=>report.pageErrors.push({engine,width,message:error.message}));
    await page.route('**/*',route=>{
     const req=route.request(),url=new URL(req.url());report.requests.push({engine,width,path:url.pathname,method:req.method()});
     if(url.origin!==origin||req.method()!=='GET')return route.abort();
     if(url.pathname==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:html});
     if(sources.has(url.pathname))return route.fulfill({contentType:'application/javascript; charset=utf-8',body:sources.get(url.pathname)});
     const responses={
      '/health':{status:'ok',runtimeCommit:commit},'/features':{flags:{}},'/datasources':sourceFixture,
      '/sync/status':{running:false,counts:{breadth:0},datasets:[]},
      '/daily-cache/status':{status:'completed',range:'1y',symbols:[{symbol:'2330',market:'TW'}],completed:1,
       results:[{symbol:'2330',rows:12,quality:{observed:12,accepted:5,conflicts:7,missing:2,invalid:0,
        conflictDates:['2026-09-23'],missingDates:['2026-09-29'],note:'官方與原始成交量不同；保留雙份證據，沒有自動採用。'}}]}
     };
     if(url.pathname==='/datasources'){
      if(sourceMode==='hold'){sourceMode='normal';pendingSource=route;return;}
      if(sourceMode==='error')return route.fulfill({status:503,contentType:'application/json',body:'{}'});
      if(sourceMode==='empty')responses['/datasources']={sources:[]};
      if(sourceMode==='invalid')responses['/datasources']={sources:{count:12}};
     }
     if(!(url.pathname in responses))return route.abort();
     return route.fulfill({contentType:'application/json; charset=utf-8',body:JSON.stringify(responses[url.pathname])});
    });
    await page.goto(origin);
    await page.evaluate(()=>SettingsV5.activate());
    await page.waitForFunction(()=>document.querySelector('#hub-runtime-commit')?.textContent==='aaaaaaaaaaaa');
    const sourcePanel=page.locator('#hub-system-sources');
    const sourceRow=name=>sourcePanel.locator('tr').filter({has:page.locator('td').filter({hasText:name})});
    assert.match(await sourceRow('零筆快取').innerText(),/紀錄數 0/);
    assert.match(await sourceRow('缺少統計').innerText(),/紀錄數未提供/);
    assert.match(await sourceRow('巨觀序列').innerText(),/未通過發布檢查[\s\S]*過期序列 3/);
    assert.match(await sourceRow('巨觀序列').innerText(),/檔案修改時間：2025-10-01 00:00:00 UTC/);
    assert.match(await sourceRow('巨觀序列').innerText(),/來源類型：官方/);
    for(const name of ['即時介面','每日介面'])assert.match(await sourceRow(name).innerText(),/尚未提供快取統計/);
    assert.match(await sourceRow('舊版狀態').innerText(),/等待核對/);
    assert.match(await sourceRow('來源錯誤').innerText(),/來源回報失敗：無法讀取<script>/);
    assert.match(await sourceRow('缺少狀態').innerText(),/狀態未提供/);
    assert.doesNotMatch(await sourcePanel.innerText(),/\[object Object\]/);
    assert.match(await sourcePanel.innerText(),/檔案修改時間不是行情資料日/);
    assert.equal(await sourcePanel.locator('script,img').count(),0);
    assert.equal(await page.evaluate(()=>!!window.sourceInjected),false);
    for(const [mode,message] of [['error','資料源載入失敗'],['empty','尚無資料源資訊'],['invalid','資料源格式無法識別']]){
     sourceMode=mode;await page.evaluate(()=>SettingsV5.activate());
     await page.waitForFunction(text=>document.querySelector('#hub-system-sources')?.textContent.includes(text),message);
    }
    // 保留前一次 API 回覆，等新版設定已顯示再交付舊回覆。
    sourceMode='hold';await page.evaluate(()=>SettingsV5.activate());
    await new Promise((resolve,reject)=>{let tries=0;const poll=()=>pendingSource?resolve():++tries>200?reject(new Error('未收到待交付資料源請求')):setTimeout(poll,10);poll();});
    await page.evaluate(()=>SettingsV5.activate());
    await page.waitForFunction(()=>document.querySelector('#hub-system-sources')?.textContent.includes('零筆快取'));
    await pendingSource.fulfill({contentType:'application/json',body:JSON.stringify({sources:[{name:'過期設定回覆',status:'舊版'}]})});
    await page.waitForFunction(()=>window.fixturePendingJson===0);
    assert.doesNotMatch(await sourcePanel.innerText(),/過期設定回覆/);
    commit='<img src=x onerror="window.invalidCommitExecuted=true">';
    await page.evaluate(()=>SettingsV5.activate());
    await page.waitForFunction(()=>document.querySelector('#hub-runtime-commit')?.textContent==='版本尚未提供');
    assert.equal(await page.evaluate(()=>!!window.invalidCommitExecuted),false);
    await page.locator('#tbg-sys > .tbg-btn').tap();
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
    const category=page.locator('#tbg-sys > .tbg-btn');
    assert.equal(await category.evaluate(n=>n===document.activeElement),true,'正常關閉應回到分類入口');
    assert.equal(await category.isVisible(),true);

    // 固定真實存在的排程交錯：只暫留 toolbar 的 closeAll(0)，用原生 Escape
    // 在選單仍可見時關閉 dialog，再執行原 closeAll。其他計時器／來源讀取不變。
    await page.evaluate(()=>{
     const nativeTimeout=window.setTimeout, pending=[];
     window.fixtureMenuClose={pending,release(){window.setTimeout=nativeTimeout;pending.splice(0).forEach(task=>nativeTimeout(task.fn,0,...task.args));}};
     window.setTimeout=function(fn,delay,...args){
      if(delay===0&&typeof fn==='function'&&fn.name==='closeAll'){pending.push({fn,args});return 0;}
      return nativeTimeout(fn,delay,...args);
     };
    });
    await category.tap();
    await page.locator('#btn-daily-cache').tap();
    await page.waitForFunction(()=>window.fixtureMenuClose.pending.length===1);
    assert.equal(await page.locator('#dc-dialog').evaluate(n=>n.open),true);
    assert.equal(await page.locator('#tbg-menu-sys').isVisible(),true);
    await page.keyboard.press('Escape');
    await page.locator('#dc-dialog').waitFor({state:'hidden'});
    const focusBeforeMenuClose=await page.evaluate(()=>({id:document.activeElement.id,category:document.activeElement.closest('#tbg-sys')?.id||null}));
    await page.evaluate(()=>window.fixtureMenuClose.release());
    await page.waitForFunction(()=>!document.querySelector('#tbg-menu-sys').classList.contains('open'));
    const focusAfterMenuClose=await page.evaluate(()=>{
     const node=document.activeElement;
     return {id:node.id,category:node.closest('#tbg-sys')?.id||null,
       visible:!!node.getClientRects().length&&getComputedStyle(node).visibility!=='hidden'};
    });
    report.focusInterleavings.push({engine,width,height,focusBeforeMenuClose,focusAfterMenuClose});
    assert.equal(focusAfterMenuClose.category,'tbg-sys','快速 Escape 後選單延後收合，焦點必須仍在分類入口');
    assert.equal(focusAfterMenuClose.visible,true,'快速關閉後不可留下隱藏焦點');
    assert.equal(await category.evaluate(n=>n===document.activeElement),true);
    report.checks.push({engine,version:browser.version(),width,height,keyboardEscape:true,focusReturned:true,
      quickEscapeBeforeMenuClose:true,sourceAndQualitySeparated:true,unknownRevisionSafe:true,evidenceReadable:true,
      typedSourceStatus:true,missingDistinctFromZero:true,escapedSourceFields:true,staleSettingsDiscarded:true,scroll});
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

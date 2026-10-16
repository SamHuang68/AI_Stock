'use strict';
// 完整頁面與真實按鈕；替身僅位於網路邊界，所有 S 與圖表序列存取均為唯讀。
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const base = (process.env.ST_INTRADAY_BASE || 'https://intraday.test').replace(/\/$/, '');
const live = !!process.env.ST_INTRADAY_BASE;
const runtime = process.env.ST_INTRADAY_RUNTIME === '1';
if (runtime && !live) throw new Error('實際部署驗收必須指定 ST_INTRADAY_BASE');
const out = process.env.ST_INTRADAY_OUTPUT || path.join(root, 'scratch', '當日分時');
const report = {模式:live ? (runtime?'部署版真實資料':'候選頁面與真實資料'):'固定資料完整頁面',案例:[],錯誤:[],請求:[]};
const sec = s => Date.parse(s + '+08:00') / 1000;
const day = '2026-10-16';
const targets = ['__TXF__','^TWOII'];
function payload(sym, minute) {
  const future = sym === '__TXF__';
  const times = minute ? (future ? ['04:58','04:59','05:00','08:45','08:46','08:47','09:00','09:01'] : ['09:00','09:01','09:02','09:03','09:04']).map(t=>sec(`${day}T${t}:00`))
    : Array.from({length:30}, (_,i)=>sec(`${day}T13:30:00`)-(29-i)*86400);
  const price = future ? 47300 : 390;
  const candles = times.map((time,i)=>({time,open:price+i,high:price+i+2,low:price+i-1,close:price+i+1,volume:100,session:future&&i>=3?1:0}));
  const sessions = future ? [{start:sec('2026-10-15T15:00:00'),end:sec(`${day}T05:00:00`),timezone:'Asia/Taipei'},{start:sec(`${day}T08:45:00`),end:sec(`${day}T13:45:00`),timezone:'Asia/Taipei'}]
    : [{start:sec(`${day}T09:00:00`),end:sec(`${day}T13:30:00`),timezone:'Asia/Taipei'}];
  const source = 'https://tw.stock.yahoo.com/quote/'+(future?'WTX%26':'%5ETWOII');
  const minuteResult = {ok:true,name:'台指期近一分時',version:'txf-minute/1',limitations:['固定資料情境'],cached:false,symbol:sym,source,interval:'1m',exchangeTimezone:'Asia/Taipei',sourceTimestamp:times.at(-1),asOf:new Date(times.at(-1)*1000).toISOString(),sessions,candles,previousClose:price-10,freshness:{ageSeconds:0,stale:false},missing:{invalidPriceBars:0,unknownVolumeBars:0}};
  const meta = {symbol:sym,longName:sym,currency:'TWD',exchangeTimezoneName:'Asia/Taipei',regularMarketPrice:candles.at(-1).close,regularMarketTime:times.at(-1),previousClose:price-10,chartPreviousClose:price-10,dataGranularity:minute?'1m':'1d'};
  if (minute && targets.includes(sym)) Object.assign(meta,{_verifiedIntraday:true,_source:source,sourceTradingPeriods:[sessions],_intraday:minuteResult});
  return {chart:{result:[{meta,timestamp:times,indicators:{quote:[Object.fromEntries(['open','high','low','close','volume'].map(k=>[k,candles.map(c=>c[k])]))]}}],error:null}};
}
function snapshot() {
  return {ok:true,quotes:Object.fromEntries(['^TWII',...targets].map(sym=>[sym,{market:{price:sym==='__TXF__'?47308:395,referencePrice:sym==='__TXF__'?47290:380,asOf:`${day}T09:04:00+08:00`,source:sym==='__TXF__'?'taifex-mis':'twse-mis',session:'regular'}}]))};
}
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({headless:true});
  let page, failSym=null, slowSym=null, slowReceived, releaseSlow;
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900},locale:'zh-TW',timezoneId:'Asia/Taipei',serviceWorkers:'block'});
    page = await context.newPage();
    if(!live)await page.clock.install();
    page.setDefaultTimeout(10000);
    page.on('pageerror',e=>report.錯誤.push(e.message));
    await context.route('**/*',async route=>{
      const req=route.request(),u=new URL(req.url()),rel=decodeURIComponent(u.pathname.slice(1));
      if (!['GET','HEAD','OPTIONS'].includes(req.method())) return route.abort('blockedbyclient');
      if (rel.startsWith('yf/') || rel.startsWith('quote/')) report.請求.push({路徑:rel,區間:u.searchParams.get('range'),粒度:u.searchParams.get('interval')});
      if (runtime) return route.continue();
      if (!live && u.hostname==='unpkg.com' && u.pathname.endsWith('/lightweight-charts.standalone.production.js')) return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(root,'tests/fixtures/lightweight-charts-4.2.0.js'))});
      if(u.origin===base){
        const file=path.resolve(root,!rel||['index.html','stock_terminal_v2.html'].includes(rel)?'stock_terminal_v2.html':rel);
        if(file.startsWith(root+path.sep)&&fs.existsSync(file)&&fs.statSync(file).isFile()){
          const type=file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':null;
          if(type)return route.fulfill({contentType:type+'; charset=utf-8',body:fs.readFileSync(file)});
        }
        if(!live){
          let body={ok:true};
          if(rel==='market/snapshot')body=snapshot();
          else if(rel==='txf-intraday')body=payload('__TXF__',true).chart.result[0].meta._intraday;
          else if(rel==='pulse')body={ok:true,indices:{},marketSnapshot:snapshot()};
          else if(rel==='yf/batch')body=Object.fromEntries((u.searchParams.get('syms')||'').split(',').map(s=>[s,payload(s,false)]));
          else if(rel.startsWith('yf/')){
            const sym=rel.slice(3),minute=u.searchParams.get('interval')==='1m';
            if(sym===slowSym&&minute){slowReceived();await new Promise(resolve=>{releaseSlow=resolve;});}
            if(sym===failSym&&minute)return route.fulfill({status:503,json:{chart:{result:null,error:{description:'測試分鐘來源中斷'}}}});
            body=payload(sym,minute);
          }else if(rel.startsWith('quote/'))body={price:99999,prevClose:99000,open:99000,high:99999,low:99000,lastBarTime:sec(`${day}T09:04:00`)};
          else if(rel==='twindex')body={ok:false,indices:{}};
          else if(rel==='margin_ratio')body={ok:true,series:[],points:[]};
          return route.fulfill({json:body});
        }
      }
      return live?route.continue():route.abort('blockedbyclient');
    });
    if(live)report.部署身分開始=await(await context.request.get(base+'/health/live')).json();
    await page.goto(base+'/',{waitUntil:'domcontentloaded',timeout:25000});
    await page.locator('#st-ring.on').waitFor();
    await page.locator('#st-ring .sr-layer.active [data-id="price"]').click();
    await page.locator('#st-ring .sr-layer.active [data-route="chart"]').click();
    if(await page.locator('#st-ring.on').isVisible())await page.locator('#st-ring-bd').click({position:{x:5,y:5}});
    assert.equal(await page.evaluate(()=>typeof window.S),'undefined','冷啟動不得注入 window.S');
    async function ready(sym,range){
      await page.waitForFunction(({sym,range})=>S.sym===sym&&S.range===range&&S.ind&&S.dataIdentity?.sym===sym&&S.dataIdentity.loadSeq===window.__loadSeq,{sym,range},{timeout:20000});
      await page.waitForTimeout(120);
      return page.evaluate(()=>({標的:S.sym,區間:S.range,meta:S.data.meta,candles:S.data.candles,identity:S.dataIdentity,seq:window.__loadSeq,
        圖表:S.chartSeries?.data(),圓點:S.dotSeries?.data(),留白:S.wsSeries?.data(),時差:S.tzOffset||0,
        缺分鐘:S.data.candles.flatMap((c,i,rows)=>{
          if(!i||c.time-rows[i-1].time<=60)return [];
          const t=rows[i-1].time+60+(S.tzOffset||0),axis=S.chart.timeScale(),x=axis.timeToCoordinate(t);
          const logical=x==null?null:Math.round(axis.coordinateToLogical(x));
          return [{time:t,x,前:x==null?null:axis.timeToCoordinate(rows[i-1].time+(S.tzOffset||0)),後:axis.timeToCoordinate(c.time+(S.tzOffset||0)),
            K棒:logical==null?null:S.chartSeries.dataByIndex(logical),圓點:logical==null?null:S.dotSeries?.dataByIndex(logical)}];
        }),
        價格:document.getElementById('ci-price')?.textContent,標頭:S.data.marketHeadline,行情:window.MarketData?.get()?.quotes?.[S.sym]?.market,
        日線替代:S.data.intradayUnavailable}));
    }
    async function select(sym,range){
      await page.locator(`[data-mkt-sym="${sym}"]`).first().click();
      await page.locator(`[data-rg="${range}"]`).first().click();
      return ready(sym,range);
    }
    function check(state){
      report.最後圖表狀態 = state;
      assert(state.candles.length>1,'必須有多筆真實行情');
      assert.equal(state.identity.sym,state.標的);
      if(state.區間==='1d'){
        assert.equal(state.meta.dataGranularity,'1m');assert.equal(state.meta._verifiedIntraday,true);
        assert.equal(state.日線替代,false);
        assert(state.meta._intraday?.ok&&state.meta._intraday?.freshness,'保留來源與新鮮度');
        assert(state.candles.every(c=>Number.isInteger(c.time)&&c.time%60===0),'分鐘時間戳');
        assert(state.candles.some((c,i)=>i&&c.time-state.candles[i-1].time===60),'至少一對連續分鐘');
        const source=state.meta._intraday;
        assert(/^https:\/\//.test(state.meta._source),'保留可追溯來源 URL');
        const localDate=t=>new Date((t+28800)*1000).toISOString().slice(0,10);
        assert.equal(localDate(state.candles.at(-1).time),localDate(source.sourceTimestamp),'末筆日期對齊來源日期');
        assert(state.candles.at(-1).time<=source.sourceTimestamp,'不得製造超過來源時間的 K 棒');
        assert(source.sourceTimestamp-state.candles[0].time<36*3600,'當日盤別不得混入多日歷史');
        assert(state.candles.every(c=>source.sessions.some(s=>c.time>=s.start&&c.time<=s.end)),'僅顯示來源盤別');
        if(!live&&state.標的==='__TXF__'){
          for(const t of ['05:00','08:45'])assert(state.candles.some(c=>c.time===sec(`${day}T${t}:00`)),`保留 ${t} 夜盤或日盤邊界`);
          const gapStart=sec(`${day}T05:00:00`)+state.時差,gapEnd=sec(`${day}T08:45:00`)+state.時差;
          // 圖表庫 data() 只回傳有價格資料；用公開時間軸與 dataByIndex 驗證真實留白。
          const gap=state.缺分鐘.find(c=>c.time>gapStart&&c.time<gapEnd);
          assert(gap&&gap.x!=null&&gap.前<gap.x&&gap.x<gap.後,'休盤分鐘須占有時間軸位置');
          assert(!gap.K棒&&!gap.圓點,'休盤位置不可有價格或 K 棒');
        }
      }else assert.equal(state.meta.dataGranularity,'1d','半年保留日線');
      if(state.行情?.price!=null&&state.標頭){
        assert.equal(state.標頭.referencePrice,state.行情.referencePrice,'正式標頭使用同組基準');
        assert.equal(Number(state.價格.replaceAll(',','')),Number(state.行情.price.toFixed(2)),'正式價格一致');
      }
      report.案例.push({標的:state.標的,區間:state.區間,筆數:state.candles.length,首筆:state.candles[0].time,末筆:state.candles.at(-1).time,粒度:state.meta.dataGranularity,來源:state.meta._source,新鮮度:state.meta._intraday?.freshness});
    }
    for(const sym of targets)for(const range of ['1d','6mo']){const state=await select(sym,range);check(state);await page.screenshot({path:path.join(out,`${sym==='__TXF__'?'台指期':'櫃買'}_${range}.png`),fullPage:true});}
    const beforeDialog=await select('__TXF__','1d');
    await page.locator('#tbg-chart .tbg-btn').click();await page.locator('#btn-txf-minute').click();
    await page.locator('dialog[open] #ti-body svg polyline').first().waitFor();
    assert(await page.locator('dialog[open] #ti-body tbody tr').count()>1,'獨立分時工具仍有分鐘表格');
    await page.locator('#ti-close').click();
    assert.equal((await ready('__TXF__','1d')).candles.at(-1).time,beforeDialog.candles.at(-1).time,'獨立工具不可改寫主圖');
    report.案例.push({案例:'既有獨立台指期分時入口與分鐘表格'});
    await page.locator('#tbg-chart .tbg-btn').click();await page.locator('#btn-multichart').click();
    const panel=page.locator('#mc-grid .mc-panel').first();
    for(const sym of targets){
      await panel.locator('input').fill(sym);await panel.locator('input').press('Enter');
      await panel.locator('select').selectOption('1d');
      await page.waitForFunction(sym=>document.querySelector('#mc-grid .mc-panel .mc-nm')?.textContent.includes(sym==='__TXF__'?'台指期':sym==='^TWOII'?'櫃買':sym)||document.querySelector('#mc-grid .mc-panel .mc-nm')?.textContent===sym,sym);
      await panel.locator('canvas').first().waitFor();
      assert(report.請求.some(r=>r.路徑===`yf/${sym}`&&r.區間==='1d'&&r.粒度==='1m'));
      await page.screenshot({path:path.join(out,`${sym==='__TXF__'?'台指期':'櫃買'}多圖.png`),fullPage:true});
    }
    await page.locator('#mc-bar [data-act="close"]').click();
    report.案例.push({案例:'兩標的多圖一日分鐘入口'});
    if(!live){
      for(const sym of targets){
        await select(sym,'6mo');failSym=sym;const start=report.請求.length;
        await page.locator('[data-rg="1d"]').click();
        await page.locator('#chart-loading').waitFor({state:'visible'});
        await page.waitForFunction(()=>/分鐘|分時|無資料|失敗/.test(document.getElementById('chart-loading')?.textContent||''));
        const failed=await page.evaluate(()=>({identity:S.dataIdentity,visible:getComputedStyle(document.getElementById('chart-info')).display,訊息:document.getElementById('chart-loading').textContent}));
        assert.equal(failed.identity,null,'來源失敗不可沿用舊資料身分');assert.equal(failed.visible,'none');
        assert(!report.請求.slice(start).some(r=>r.路徑===`yf/${sym}`&&r.粒度==='1d'),'分鐘失敗不得退日線');
        assert(!report.請求.slice(start).some(r=>r.路徑===`quote/${sym}`),'分鐘失敗不得合成報價單點');
        failSym=null;
        await page.locator('#intraday-retry').click();
        check(await ready(sym,'1d'));report.案例.push({案例:'分鐘中斷與按鈕重試',標的:sym,訊息:failed.訊息});
      }
      await select('^TWOII','1d');slowSym='__TXF__';
      let slowTimer; const received=new Promise((resolve,reject)=>{slowTimer=setTimeout(()=>reject(new Error('未觀測到延遲分鐘請求')),10000);slowReceived=()=>{clearTimeout(slowTimer);resolve();};});
      await page.locator('[data-mkt-sym="__TXF__"]').first().click();await received;
      await page.locator('[data-mkt-sym="^TWOII"]').first().click();await ready('^TWOII','1d');
      slowSym=null;releaseSlow();await page.waitForTimeout(200);
      const race=await ready('^TWOII','1d');assert.equal(race.meta.symbol,'^TWOII');report.案例.push({案例:'延遲台指期回應不覆蓋櫃買',標的:race.標的});
    }else report.未執行情境=['實際來源不注入失敗或延遲；錯誤重試與切股競態由固定資料案例驗證'];
    await select('__TXF__','1d');report.手機=[];
    for(const viewport of [{width:390,height:844},{width:844,height:390},{width:667,height:375}]){
      await page.setViewportSize(viewport);await page.waitForTimeout(120);
      const boxes=await page.evaluate(()=>['ci-price','ci-chg','ci-market-asof','ci-intraday-asof'].map(id=>{const el=document.getElementById(id),r=el.getBoundingClientRect(),s=getComputedStyle(el);return {id,x:r.x,y:r.y,width:r.width,height:r.height,display:s.display,visibility:s.visibility};}));
      for(const b of boxes){assert(b.width>0&&b.height>0&&b.display!=='none'&&b.visibility!=='hidden');assert(b.x>=0&&b.y>=0&&b.x+b.width<=viewport.width+1&&b.y+b.height<=viewport.height+1,JSON.stringify({viewport,b}));}
      assert(await page.locator('[data-rg="1d"]').isVisible(),'手機可切換一天');
      report.手機.push({尺寸:viewport,位置:boxes});await page.screenshot({path:path.join(out,`${viewport.width}x${viewport.height}分時.png`),fullPage:true});
    }
    if(!live){
      // 使用瀏覽器測試時鐘推進已存在的 90 秒 timer，不替換產品函式。
      for(const sym of targets){
        await select(sym,'1d');const before=report.請求.filter(r=>r.路徑===`yf/${sym}`&&r.粒度==='1m').length;
        await page.clock.fastForward(91000);await ready(sym,'1d');
        assert(report.請求.filter(r=>r.路徑===`yf/${sym}`&&r.粒度==='1m').length>before,'分時自動重新取得');
      }
      report.案例.push({案例:'兩標的90秒分鐘刷新'});
    }
    if(live){report.部署身分結束=await(await context.request.get(base+'/health/live')).json();assert.equal(report.部署身分結束.runtimeCommit,report.部署身分開始.runtimeCommit);}
    assert.deepEqual(report.錯誤,[],'完整頁面不得產生未捕捉錯誤');report.結果='當日分時指定案例通過';
  }catch(error){report.失敗=error.stack;process.exitCode=1;if(page)await page.screenshot({path:path.join(out,'失敗畫面.png'),fullPage:true}).catch(e=>{report.截圖錯誤=e.message;});}
  finally{if(releaseSlow)releaseSlow();await browser.close();fs.writeFileSync(path.join(out,'驗收結果.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({模式:report.模式,結果:report.結果,案例數:report.案例.length,失敗:report.失敗,錯誤:report.錯誤}));}
})();

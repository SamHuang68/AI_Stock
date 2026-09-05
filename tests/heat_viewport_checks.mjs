/** 類股熱力圖可讀性閘門：固定 API 測試資料，量測真正的 ST 畫面，不以容器存在當作通過。 */
export async function checkHeatViewport({send, evaluate, sleep, screenshot, report, failures}) {
  async function swipeUp(x,y,distance) {
    await send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});
    for(let i=1;i<=10;i++) {
      await send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y-distance*i/10}]});
      await sleep(25);
    }
    await send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  }
  await evaluate(send, `(() => {
    window.__heatGateFetch = window.fetch;
    window.fetch = function(input, init) {
      const url = new URL(typeof input === 'string' ? input : input.url, location.href);
      const mkt = url.searchParams.get('mkt') || 'TW';
      if (url.pathname === '/sectors') return Promise.resolve(new Response(JSON.stringify({
        date:'20260904', sectors:Array.from({length:49},(_,i)=>({
          name:['電腦及週邊設備','電子類兩倍槓桿','電機機械','通信網路','其他電子'][i%5]+' '+(i+1),
          symbol:'XLK', close:1000+i, changePct:4.69-i*.15,
          marketSharePct:2.1, rs20VsBenchmarkPct:1.2
        })),sectorFlow:{label:'漲跌參與（無產業成交額）',participationPct:89}
      }),{headers:{'Content-Type':'application/json'}}));
      if (url.pathname === '/focus') return Promise.resolve(new Response(JSON.stringify({
        ok:true,mkt,scanned:1083,
        buy:Array.from({length:20},(_,i)=>({sym:String(2330+i),name:'測試電子股份有限公司',changePct:5-i*.1})),
        short:Array.from({length:20},(_,i)=>({sym:String(3000+i),name:'測試半導體股份有限公司',changePct:-5+i*.1}))
      }),{headers:{'Content-Type':'application/json'}}));
      return window.__heatGateFetch.call(this,input,init);
    }; return true;
  })()`);
  try {
    for (const vp of [
      {width:844,height:390,mobile:true}, {width:932,height:430,mobile:true},
      {width:740,height:320,mobile:true}, {width:1024,height:500,mobile:true},
      {width:390,height:844,mobile:true}, {width:1440,height:900,mobile:false}
    ]) {
      await send('Emulation.setDeviceMetricsOverride',{...vp,screenWidth:vp.width,screenHeight:vp.height,deviceScaleFactor:1});
      await send('Emulation.setTouchEmulationEnabled',{enabled:vp.mobile,maxTouchPoints:5});
      await evaluate(send, `window.ShellV5.go('heat'); window.HeatV5.refresh(true); window.dispatchEvent(new Event('resize')); true`);
      await sleep(900);
      const item = await evaluate(send, `(() => {
        const q=s=>document.querySelector(s), rect=e=>e.getBoundingClientRect();
        const wrap=q('.ht-grid-wrap'), dash=q('.ht-dash'), shell=q('#shell-views');
        shell.scrollTop=0; wrap.scrollTop=0;
        const cells=[...q('.ht-grid').children], lists=[...document.querySelectorAll('#ht-focus .ht-list')];
        if(cells.length!==49 || lists.length!==2) throw new Error('熱力圖測試資料未形成');
        const w=rect(wrap), d=rect(dash), k=[...document.querySelectorAll('.ht-kpi>.k')];
        const completeRows=new Set(cells.filter(e=>rect(e).top>=w.top-1 && rect(e).bottom<=w.bottom+1).map(e=>Math.round(rect(e).top))).size;
        const listHeights=lists.map(e=>e.clientHeight);
        const visibleFocusRows=lists.map(list=>[...list.children].filter(e=>rect(e).top>=rect(list).top-1&&rect(e).bottom<=rect(list).bottom+1).length);
        const last=cells.at(-1); wrap.scrollTop=wrap.scrollHeight; last.scrollIntoView({block:'nearest'});
        const lastRect=rect(last), shellRect=rect(shell);
        const lastReachable=lastRect.top>=Math.max(rect(wrap).top,shellRect.top)-1 && lastRect.bottom<=Math.min(rect(wrap).bottom,shellRect.bottom)+1;
        lists.forEach(list=>list.scrollTop=list.scrollHeight);
        const focusReachable=lists.every(list=>{const row=list.lastElementChild;row.scrollIntoView({block:'nearest'});return rect(row).bottom<=Math.min(rect(list).bottom,rect(shell).bottom)+1;});
        return {width:innerWidth,height:innerHeight,heatHeight:wrap.clientHeight,completeRows,listHeights,visibleFocusRows,
          kpiRows:new Set(k.map(e=>Math.round(rect(e).top))).size,dashTop:d.top,
          sideBySide:Math.abs(rect(q('.ht-main')).top-rect(q('.ht-focus-zone')).top)<2,
          lastReachable,focusReachable,horizontalOverflow:shell.scrollWidth-shell.clientWidth,
          tileFont:parseFloat(getComputedStyle(q('.ht-cell .nm')).fontSize)};
      })()`);
      const issues=[];
      if(vp.mobile && vp.width>vp.height) {
        await evaluate(send, `document.querySelector('#shell-views').scrollTop=0; true`);
        const outerPoint=await evaluate(send, `(() => {
          const r=document.querySelector('.ht-main').getBoundingClientRect();
          const x=r.right+2, y=innerHeight-45;
          const hit=document.elementFromPoint(x,y);
          return {x,y,target:hit&&(hit.id||hit.className)};
        })()`);
        item.touchTarget=outerPoint.target;
        await swipeUp(outerPoint.x,outerPoint.y,Math.min(160,outerPoint.y-15));
        await sleep(500);
        const afterTouch=await evaluate(send, `document.querySelector('#shell-views').scrollTop`);
        await sleep(500);
        const held=await evaluate(send, `document.querySelector('#shell-views').scrollTop`);
        item.outerTouchScroll=afterTouch; item.outerTouchHeld=held;
        if(afterTouch<20 || Math.abs(afterTouch-held)>2) issues.push('外層觸控未捲動或停止後回彈');
      }
      if(item.heatHeight<210 || item.completeRows<3) issues.push('熱力圖不足三個完整可讀列');
      if(item.listHeights.some(h=>h<96) || item.visibleFocusRows.some(n=>n<3)) issues.push('焦點清單不足三列可視高度');
      if(vp.width>vp.height && (item.kpiRows!==1 || !item.sideBySide)) issues.push('橫式摘要未收斂為單列或主區未並排');
      if(!item.lastReachable || !item.focusReachable) issues.push('最後一筆內容不可達');
      if(item.horizontalOverflow>2) issues.push('頁面水平溢出');
      if(item.tileFont<10) issues.push('主要字體過小');
      // 捲至內容起點後量測與螢幕的交集，避免「容器很高但仍在畫面外」假通過。
      await evaluate(send, `(() => {
        const shell=document.querySelector('#shell-views'), dash=document.querySelector('.ht-dash');
        shell.scrollTop+=dash.getBoundingClientRect().top-shell.getBoundingClientRect().top;
        document.querySelectorAll('.ht-grid-wrap,.ht-list').forEach(e=>e.scrollTop=0); return true;
      })()`);
      await sleep(400);
      const screen = await evaluate(send, `(() => {
        const shell=document.querySelector('#shell-views'), wrap=document.querySelector('.ht-grid-wrap');
        const sr=shell.getBoundingClientRect(), wr=wrap.getBoundingClientRect();
        const top=Math.max(sr.top,wr.top,0), bottom=Math.min(sr.bottom,wr.bottom,innerHeight);
        const rows=new Set([...wrap.querySelectorAll('.ht-cell')].filter(e=>{const r=e.getBoundingClientRect();return r.top>=top-1&&r.bottom<=bottom+1;}).map(e=>Math.round(e.getBoundingClientRect().top))).size;
        return {screenHeatRows:rows,screenHeatHeight:bottom-top,scrollTop:shell.scrollTop};
      })()`);
      if(screen.screenHeatRows<3) issues.push('螢幕內實際可讀熱力圖不足三列');
      await sleep(500);
      const retained=await evaluate(send, `document.querySelector('#shell-views').scrollTop`);
      if(Math.abs(retained-screen.scrollTop)>2) issues.push('捲動位置回彈');
      const label=vp.width+'x'+vp.height;
      report.push({viewport:label,route:'heat-readable',fixture:true,...item,...screen,issues});
      failures.push(...issues.map(s=>label+' 熱力圖：'+s));
      console.log((issues.length?'FAIL ':'OK   ')+label+' 類股可視區 '+JSON.stringify({...item,...screen}));
      await screenshot(send,label+'-類股內容區');
      if(vp.mobile && vp.width>vp.height) {
        const point=await evaluate(send, `(() => { const r=document.querySelector('.ht-grid-wrap').getBoundingClientRect(); return {x:r.left+r.width/2,y:Math.min(r.bottom,innerHeight)-35}; })()`);
        await swipeUp(point.x,point.y,Math.min(140,point.y-15));
        await sleep(600);
        const innerScroll=await evaluate(send, `document.querySelector('.ht-grid-wrap').scrollTop`);
        if(innerScroll<20) {issues.push('熱力圖內層觸控無法捲動'); failures.push(label+' 熱力圖內層觸控無法捲動');}
        report.at(-1).innerTouchScroll=innerScroll;
        const focusChecks=[];
        for(let index=0;index<2;index++) {
          await evaluate(send, `(() => {const e=document.querySelectorAll('#ht-focus .ht-list')[${index}];e.scrollTop=0;e.scrollIntoView({block:'nearest'});return true;})()`);
          await sleep(350);
          const focus=await evaluate(send, `(() => {
            const e=document.querySelectorAll('#ht-focus .ht-list')[${index}],r=e.getBoundingClientRect();
            const s=document.querySelector('#shell-views').getBoundingClientRect();
            const top=Math.max(0,r.top,s.top),bottom=Math.min(innerHeight,r.bottom,s.bottom);
            return {x:r.left+r.width/2,y:bottom-12,rows:[...e.children].filter(c=>{const b=c.getBoundingClientRect();return b.top>=top-1&&b.bottom<=bottom+1;}).length};
          })()`);
          await swipeUp(focus.x,focus.y,70);
          await sleep(600);
          const scroll=await evaluate(send, `document.querySelectorAll('#ht-focus .ht-list')[${index}].scrollTop`);
          focusChecks.push({rows:focus.rows,scroll});
          if(focus.rows<3||scroll<20) {issues.push('焦點實際可讀列數或觸控捲動不足');failures.push(label+' 焦點'+index+'可視／觸控失敗');}
        }
        report.at(-1).focusChecks=focusChecks;
      }
      await evaluate(send, `document.querySelectorAll('#shell-views,.ht-grid-wrap,.ht-list').forEach(e=>e.scrollTop=0); true`);
      await screenshot(send,label+'-類股熱力');
    }
    // 不重新啟用路由或重載資料，保留同一份 DOM 驗證直橫往返。
    for(const vp of [{width:390,height:844},{width:844,height:390},{width:390,height:844}]) {
      await send('Emulation.setDeviceMetricsOverride',{...vp,screenWidth:vp.width,screenHeight:vp.height,deviceScaleFactor:1,mobile:true});
      await send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:5});
      await sleep(800);
      const rotation=await evaluate(send, `(() => {
        const shell=document.querySelector('#shell-views'),last=document.querySelector('#ht-focus .ht-two>div:last-child .ht-row:last-child');
        last.scrollIntoView({block:'end'}); const r=last.getBoundingClientRect(), s=shell.getBoundingClientRect();
        return {scrollTop:shell.scrollTop,reachable:r.top>=s.top-1&&r.bottom<=Math.min(innerHeight,s.bottom)+1,cells:document.querySelectorAll('.ht-cell').length};
      })()`);
      await sleep(700);
      const held=await evaluate(send, `document.querySelector('#shell-views').scrollTop`);
      const issues=rotation.reachable&&rotation.cells===49&&Math.abs(held-rotation.scrollTop)<2?[]:['同頁直橫切換後末列不可達或捲動回彈'];
      report.push({route:'heat-rotation',viewport:vp.width+'x'+vp.height,...rotation,held,issues});
      failures.push(...issues);
      await screenshot(send,vp.width+'x'+vp.height+'-旋轉後末列');
    }
  } finally {
    await evaluate(send, `window.fetch=window.__heatGateFetch; delete window.__heatGateFetch; true`);
  }
  await send('Emulation.setDeviceMetricsOverride',{width:844,height:390,screenWidth:844,screenHeight:390,deviceScaleFactor:1,mobile:true});
  // 冷載入清掉模組內的焦點快取，不能只還原 fetch 就把混合畫面標成真實資料。
  await send('Page.reload',{ignoreCache:true});
  let liveReady=false;
  for(let attempt=0;attempt<120;attempt++) {
    await sleep(250);
    liveReady=await evaluate(send, `!!document.querySelector('.ht-cell') && !!document.querySelector('#ht-focus') &&
      !document.querySelector('#ht-focus').textContent.includes('掃描中') &&
      !document.querySelector('#ht-root').textContent.includes('測試電子股份有限公司') &&
      !document.querySelector('#ht-root').textContent.includes('測試半導體股份有限公司')`);
    if(liveReady) break;
  }
  if(!liveReady) throw new Error('實際來源未就緒，禁止用混合測試快取宣稱真實資料截圖');
  await evaluate(send, `document.querySelectorAll('#shell-views,.ht-grid-wrap,.ht-list').forEach(e=>e.scrollTop=0); true`);
  const live=await evaluate(send, `({cells:document.querySelectorAll('.ht-cell').length,caption:document.querySelector('#ht-sub').textContent,heatHeight:document.querySelector('.ht-grid-wrap').clientHeight})`);
  report.push({route:'heat-live',fixture:false,...live,issues:[]});
  await screenshot(send,'844x390-實際來源');
}

/* 台指期分鐘來源獨立檢視；不修改主日線、現價或回測資料。 */
(function () {
  'use strict';
  let dialog, controller;
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const local = t => new Date(t*1000).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false});
  function paths(rows) {
    const prices = rows.map(r=>r.close), lo = Math.min(...prices), hi = Math.max(...prices);
    const first = rows[0].time, span = Math.max(60,rows.at(-1).time-first), scale = Math.max(1,hi-lo);
    const groups=[]; let current=[], prior;
    for(const row of rows){
      if(prior && (row.session!==prior.session || row.time-prior.time!==60)){groups.push(current);current=[];}
      current.push((30+((row.time-first)/span)*740).toFixed(2)+','+(200-((row.close-lo)/scale)*170).toFixed(2)); prior=row;
    }
    if(current.length)groups.push(current);
    return {groups,lo,hi};
  }
  function render(data) {
    if(!data.ok){$('ti-body').textContent=data.message+'；'+(data.error||'');return;}
    const rows=data.candles, graph=paths(rows), last=rows.at(-1);
    $('ti-body').innerHTML='<p>'+esc(data.name)+' · '+rows.length+' 根 · '+esc(data.version)+'</p><p>來源時間：'+esc(local(data.sourceTimestamp))+'（臺北） · '+(data.freshness.stale?'資料較舊':'15 分鐘內來源資料')+' · '+(data.cached?'快取':'本次取得')+'</p>'+
      '<p>最後分鐘收盤 '+esc(last.close)+'｜來源前收 '+esc(data.previousClose??'未知')+'｜缺價格 '+esc(data.missing.invalidPriceBars)+'｜未知成交量 '+esc(data.missing.unknownVolumeBars)+'</p>'+
      '<svg role="img" aria-label="台指期來源分鐘收盤走勢，缺分鐘與不同盤別不連線" viewBox="0 0 800 235" style="display:block;width:100%;background:#0f172a;border-radius:10px"><text x="30" y="18" fill="#cbd5e1">'+esc(graph.hi)+'</text><text x="30" y="225" fill="#cbd5e1">'+esc(graph.lo)+'</text>'+graph.groups.map(p=>'<polyline points="'+p.join(' ')+'" fill="none" stroke="#38bdf8" stroke-width="2"/>').join('')+'</svg><p>'+esc(local(rows[0].time))+' → '+esc(local(last.time))+'</p>'+
      '<details><summary>來源盤別與最近 20 分鐘 OHLCV</summary>'+data.sessions.map((p,i)=>'<p>來源區段 '+(i+1)+'：'+esc(local(p.start))+' → '+esc(local(p.end))+'</p>').join('')+
      '<div style="overflow:auto"><table style="width:100%;font-variant-numeric:tabular-nums"><thead><tr><th>臺北時間</th><th>開</th><th>高</th><th>低</th><th>收</th><th>量</th></tr></thead><tbody>'+rows.slice(-20).map(r=>'<tr>'+[local(r.time),r.open,r.high,r.low,r.close,r.volume??'未知'].map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div></details>'+
      '<p>'+data.limitations.map(esc).join('；')+'。</p><a href="https://tw.stock.yahoo.com/quote/WTX%26" target="_blank" rel="noopener noreferrer">查看 Yahoo 原始來源</a>';
  }
  async function refresh(){
    controller?.abort(); const request=new AbortController(); controller=request;
    $('ti-body').textContent='核對來源標的、時間戳與盤別中…'; $('ti-refresh').disabled=true;
    try{const r=await fetch('/txf-intraday',{signal:request.signal}); const data=await r.json();if(controller===request&&dialog.open)render(data);}
    catch(e){if(e.name!=='AbortError'&&controller===request)$('ti-body').textContent='分鐘資料讀取失敗：'+e.message;}
    finally{if(controller===request)$('ti-refresh').disabled=false;}
  }
  function close(){controller?.abort();controller=null;dialog?.close();}
  function open(){
    if(!dialog){dialog=document.createElement('dialog');dialog.style.cssText='width:min(900px,92vw);max-height:88vh;overflow:auto;background:#111827;color:#e5e7eb;border:1px solid #475569;border-radius:16px;padding:20px';document.body.appendChild(dialog);}
    dialog.innerHTML='<h2>台指期近一分時</h2><p>獨立分鐘行情。開啟或按重新取得會讀取既有 Yahoo 來源，60 秒內沿用記憶體快取，不自動輪詢。</p><div style="display:flex;gap:12px"><button id="ti-refresh">重新取得</button><button id="ti-close">關閉</button></div><div id="ti-body" role="status"></div>';
    $('ti-refresh').onclick=refresh;$('ti-close').onclick=close;dialog.oncancel=close;dialog.showModal();refresh();
  }
  function mount(){const p=$('pro-tools');if(!p)return false;if(!$('btn-txf-minute')){const b=document.createElement('button');b.id='btn-txf-minute';b.className='btn';b.textContent='台指期分時';b.onclick=open;p.appendChild(b);}return true;}
  if(!mount()){let tries=0;const timer=setInterval(()=>{if(mount()||++tries>30)clearInterval(timer);},300);}
  window.TxfIntradayUI={open,close,paths};
})();

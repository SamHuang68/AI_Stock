'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/加權行情20261016.json'),'utf8').replace(/^\uFEFF/,''));
const storeCode = fs.readFileSync(path.join(root,'src/core/market_data_v5.js'),'utf8');
const polish = fs.readFileSync(path.join(root,'src/ui/polish_v3.js'),'utf8');
const start = polish.indexOf('async function refreshMktBar()');
const refreshCode = polish.slice(start,polish.indexOf('async function refreshMacroTrackCells()',start));
const clone = x=>JSON.parse(JSON.stringify(x));
function env(body=clone(fixture.yahoo)) {
  const events=[];
  const context={console,Date,Number,Math,isFinite,SERVER_P:'https://fixture.test',
    MKT_INDICES:[{sym:'^TWII'}],CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},
    renderCanonicalMarketQuote(){},refreshMarginRatioCell:async()=>{},refreshMacroTrackCells:async()=>{},
    fetch:async url=>({ok:true,json:async()=>String(url).includes('/yf/batch')?{'^TWII':{chart:{result:[{meta:body.meta,timestamp:body.timestamp,indicators:{quote:[{close:body.close}]}}]}}}:{ok:false}})};
  context.window={SERVER:context.SERVER_P,dispatchEvent:e=>events.push(clone(e.detail)),addEventListener(){}};
  vm.createContext(context);vm.runInContext(storeCode,context);context.MarketData=context.window.MarketData;
  vm.runInContext(refreshCode,context);
  return {store:context.MarketData,events,refresh:()=>context.refreshMktBar()};
}
function fallback(asOf='2026-10-16T13:33:25+08:00',symbol='^TWII') {
  return {quotes:{[symbol]:{chartFallback:true,market:{price:47111.26,referencePrice:48625.828125,asOf}}}};
}
function official(symbol='^TWII',asOf='2026-10-16T13:33:00+08:00') {
  return {quotes:{[symbol]:{market:{price:fixture.expected.price,referencePrice:fixture.expected.referencePrice,asOf,source:'twse-mis'}}}};
}
(async()=>{
  let count=0;
  for (const symbol of ['^TWII','^TWOII']) {
    for (const order of ['fallback-first','official-first']) {
      const e=env();
      if(order==='fallback-first'){e.store.publish(fallback(undefined,symbol),'chart-fallback');e.store.publish(official(symbol),'snapshot');}
      else{e.store.publish(official(symbol),'snapshot');e.store.publish(fallback(undefined,symbol),'chart-fallback');}
      assert.equal(e.store.get().quotes[symbol].market.referencePrice,fixture.expected.referencePrice,`${symbol} ${order}`);count++;
    }
  }
  // 跨日仍以交易日先後為準，不讓較舊官方值蓋過新交易日備援。
  {
    const e=env();e.store.publish(fallback(),'chart-fallback');e.store.publish(official('^TWII','2026-10-15T13:33:00+08:00'),'snapshot');
    assert.equal(e.store.get().quotes['^TWII'].market.referencePrice,48625.828125);count++;
  }
  // 同一來源仍拒絕較舊行情；台指期不適用指數備援校正例外。
  for(const symbol of ['^TWII','__TXF__']) {
    const e=env();const newer=official(symbol,'2026-10-16T13:34:00+08:00');newer.quotes[symbol].market.price=47200;
    e.store.publish(newer,'snapshot');e.store.publish(official(symbol),'snapshot');assert.equal(e.store.get().quotes[symbol].market.price,47200);count++;
  }
  // 實際原始形狀：當日日 K 為 null，最後有效收盤屬於前一交易日。
  {
    const e=env();await e.refresh();const m=e.store.get().quotes['^TWII'].market;
    assert.equal(m.referenceDate,fixture.expected.referenceDate);
    assert.equal(m.referencePrice,46969.87109375);
    assert.equal(Number(m.displayChange.toFixed(2)),fixture.expected.change);
    assert.equal(Number(m.displayChangePct.toFixed(2)),fixture.expected.changePct);count++;
  }
  // 當日日 K 已填值仍須選 10/15，不退回區間起點 chartPreviousClose。
  {
    const data=clone(fixture.yahoo);data.close[2]=fixture.expected.price;
    const e=env(data);await e.refresh();assert.equal(e.store.get().quotes['^TWII'].market.referencePrice,46969.87109375);count++;
  }
  // 現價缺值時，現價與前收、日期一併退回最後有效日 K，不產生混日 0%。
  {
    const data=clone(fixture.yahoo);data.meta.regularMarketPrice=null;
    const e=env(data);await e.refresh();const m=e.store.get().quotes['^TWII'].market;
    assert.equal(m.price,46969.87109375);assert.equal(m.referencePrice,48625.828125);
    assert.equal(m.referenceDate,'2026-10-14');assert.equal(m.asOf,new Date(1792026000*1000).toISOString());
    assert.equal(Number(m.displayChange.toFixed(2)),-1655.96);count++;
  }
  // metadata 只有前收數字時，不以數值相等虛構其日期。
  {
    const data=clone(fixture.yahoo);data.meta.regularMarketPreviousClose=46969.87109375;
    const e=env(data);await e.refresh();assert.equal(e.store.get().quotes['^TWII'].market.referenceDate,null);count++;
  }
  console.log(`加權獨立真值與來源順序：${count} 組局部情境通過`);
})().catch(e=>{console.error(e);process.exitCode=1;});

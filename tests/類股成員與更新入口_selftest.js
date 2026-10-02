'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root=path.resolve(__dirname,'..'), nodes=new Map(), requests=[], navigation=[];
function node() { return {innerHTML:'',style:{},classList:{add(){},remove(){},toggle(){}},
  querySelectorAll(selector){
    if(selector!=='[data-member-code]') return [];
    this.buttons=[...this.innerHTML.matchAll(/data-member-code="([^"]*)"/g)].map(m=>({getAttribute(){return m[1];}}));
    return this.buttons;
  }}; }
const scope={console,Date,Promise,AbortController,location:{},localStorage:{getItem(){return null;}},
  loadSym:(...args)=>navigation.push(['symbol',...args]),
  addEventListener(){},setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},
  ShellV5:{route:()=> 'heat',go:(...args)=>navigation.push(args)},
  document:{readyState:'loading',getElementById:id=>nodes.get(id)||null,createElement:node,addEventListener(){},head:{appendChild(el){nodes.set(el.id,el);}}},
  fetch(url,options){return new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));}};
scope.window=scope;
const heat=fs.readFileSync(path.join(root,'src/ui/heat_v5.js'),'utf8');
vm.runInNewContext(heat.replace('  window.HeatV5 = {',`window.fixture={renderMembers:renderMembers,loadMembers:loadMembers,loadFocus:loadFocus,
  injectCSS:injectCSS,state:state}; window.HeatV5 = {`),scope);
const T=scope.fixture;
nodes.set('ht-members',node()); nodes.set('ht-focus',node()); nodes.set('ht-focus-title',node());
const members={ok:true,market:'TW',sector:'半導體',date:'2026-09-25',source:'官方來源',
  scopeLabel:'上市普通股',classificationComplete:false,rows:[{code:'2330',name:'台積電',price:0,changePct:null,asOf:'2026-09-25'}]};
T.renderMembers(members,'半導體','TW');
assert.match(nodes.get('ht-members').innerHTML,/分類資料未完整/);
assert.match(nodes.get('ht-members').innerHTML,/>0<\/td>/);
assert.match(nodes.get('ht-members').innerHTML,/>—<\/td>/);
nodes.get('ht-members').buttons[0].onclick();
assert.equal(navigation.at(-1)[0],'chart'); assert.equal(navigation.at(-2)[1],'2330');
T.renderMembers({...members,ok:false,error:'來源失敗<script>'},'半導體','TW');
assert.doesNotMatch(nodes.get('ht-members').innerHTML,/<script>|data-member-code/);
assert.match(nodes.get('ht-members').innerHTML,/來源失敗&lt;script&gt;/);
T.renderMembers({ok:true,market:'US',scope:'UNAVAILABLE',unavailableReason:'未提供可信任成員來源',rows:[]},'科技','US');
assert.match(nodes.get('ht-members').innerHTML,/未提供可信任成員來源/);
assert.doesNotMatch(nodes.get('ht-members').innerHTML,/2330|data-member-code/);
T.injectCSS();
assert.match(nodes.get('heat-v5-css').textContent,/overflow-y:auto!important/);
assert.match(nodes.get('heat-v5-css').textContent,/grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function reply(request,data){request.resolve({ok:true,status:200,json:async()=>data});}

(async()=>{
  T.state.sector='半導體'; const first=T.loadMembers('半導體','TW'); const old=requests.at(-1);
  T.state.sector='金融'; const second=T.loadMembers('金融','TW');
  reply(requests.at(-1),{...members,sector:'金融',rows:[{code:'2881',name:'富邦金',price:100,changePct:0}]}); await second;
  reply(old,members); await first;
  assert.match(nodes.get('ht-members').innerHTML,/2881/); assert.doesNotMatch(nodes.get('ht-members').innerHTML,/2330/);
  const count=requests.length; await T.loadMembers('金融','TW'); assert.equal(requests.length,count,'短期重繪沿用同類股快取');
  T.loadFocus(false); assert.match(requests.at(-1).url,/cacheOnly=1/);
  reply(requests.at(-1),{ok:true,mkt:'TW',available:false,reason:'尚無有效的已完成掃描'}); await flush();
  assert.match(nodes.get('ht-focus').innerHTML,/才會明確要求掃描/);
  T.loadFocus(true); assert.match(requests.at(-1).url,/refresh=1/);
  reply(requests.at(-1),{ok:true,mkt:'TW',buy:[],short:[],scan:{completedAt:'2026-09-25T07:00:00Z'}}); await flush();
  assert.match(nodes.get('ht-focus').innerHTML,/2026-09-25T07:00:00Z/);

  // 執行殼層實際的按鈕建立區塊，再觸發使用者 click；不得直接啟動 /sync。
  const shell=fs.readFileSync(path.join(root,'src/ui/shell_v5.js'),'utf8');
  const start=shell.indexOf("    if (topbar && !$('shell-sync-btn')) {");
  const end=shell.indexOf("    if (topbar && !PRIVATE_WEB",start);
  assert(start>=0&&end>start);
  let button, opened=null, fallback='';
  const ctx={topbar:{appendChild(el){button=el;}},$:()=>null,
    document:{createElement(){return {addEventListener(event,callback){this[event]=callback;}};}},
    window:{UpdateCenter:{open(el){opened=el;}}},toast(text){fallback=text;}};
  vm.runInNewContext(shell.slice(start,end),ctx);
  button.click(); assert.equal(opened,button); assert.match(button.innerHTML,/更新中心/);
  ctx.window.UpdateCenter=null; button.click(); assert.match(fallback,/重新載入/);
  console.log('類股真實成員、缺值、延遲回應、純讀焦點與更新入口點擊通過');
})().catch(error=>{console.error(error);process.exitCode=1;});

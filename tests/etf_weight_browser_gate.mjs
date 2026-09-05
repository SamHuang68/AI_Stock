/** 用真實 Chrome 視窗模擬驗證 ETF 排名排序與手機捲動。 */
import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const profile=await fs.mkdtemp(path.join(os.tmpdir(),'st-etf-rank-'));
const chrome=process.env.CHROME_PATH || path.join(process.env.LOCALAPPDATA,'Google','Chrome','Application','chrome.exe');
const proc=spawn(chrome,['--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
let ws;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
try{
 let port;
 for(let attempt=0;attempt<100;attempt++){
  try{port=(await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;}catch{await pause(100);}
 }
 if(!port)throw new Error('Chrome 未開啟測試通道');
 const tabs=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
 ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
 let sequence=0;const pending=new Map();
 ws.addEventListener('message',event=>{const msg=JSON.parse(event.data);const pair=pending.get(msg.id);if(!pair)return;pending.delete(msg.id);msg.error?pair.reject(new Error(msg.error.message)):pair.resolve(msg.result);});
 const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.text);return r.result?.value;};
 const reports=[];
 for(const [width,height] of [[390,844],[430,932],[932,430],[1600,900]]){
  await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<1000});
  await send('Page.navigate',{url:pathToFileURL(path.join(root,'tests','fixtures','etf_weight_ranking.html')).href+`?width=${width}`});
  let result;
  for(let i=0;i<100;i++){
   result=await evaluate(`(()=>{const r=document.getElementById('result');return r?.dataset.status?{status:r.dataset.status,checks:JSON.parse(r.textContent),width:innerWidth,scrollWidth:document.documentElement.scrollWidth}:null})()`);
   if(result)break;await pause(100);
  }
  if(!result||result.status!=='passed'||result.width!==width)throw new Error(`視窗 ${width} 驗證失敗：${JSON.stringify(result)}`);
  // 驗證後隱藏測試紀錄，截圖只保留產品介面。
  await evaluate("document.getElementById('result').style.display='none'");
  const shot=await send('Page.captureScreenshot',{format:'png'});
  await fs.mkdir(path.join(root,'logs'),{recursive:true});
  await fs.writeFile(path.join(root,'logs',`ETF排名-${width}.png`),Buffer.from(shot.data,'base64'));
  reports.push({width,height,status:result.status,checks:result.checks.length});
 }
 console.log(JSON.stringify({status:'通過',viewports:reports}));
}finally{
 ws?.close();proc.kill();
}

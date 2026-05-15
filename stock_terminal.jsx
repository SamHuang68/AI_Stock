import { useState, useEffect, useRef, useCallback } from "react";

const OTC=new Set(["3105","3661","6488","6669","6770","8046","3045","3653","6415","5274","6550","3008","3533","6719","5347","2382","3034","4966","6104","3081"]);
const DEFAULT_WL=[{ticker:"2330",market:"TW"},{ticker:"0050",market:"TW"},{ticker:"NVDA",market:"US"},{ticker:"TSM",market:"US"}];
const IND_DEFS=[
  {k:"sma5",lbl:"SMA 5",sub:"5日均"},{k:"sma20",lbl:"SMA 20",sub:"20日均"},
  {k:"rsi14",lbl:"RSI 14",sub:"強弱指數"},{k:"macd",lbl:"MACD",sub:"DIF"},
  {k:"macdSig",lbl:"訊號線",sub:"DEA"},{k:"macdH",lbl:"MACD柱",sub:"DIF-DEA"},
  {k:"kdK",lbl:"KD K",sub:"隨機K"},{k:"kdD",lbl:"KD D",sub:"隨機D"},
  {k:"vol",lbl:"年化波動",sub:"Ann.Vol"},{k:"maxdd",lbl:"最大回撤",sub:"MaxDD"},
  {k:"volRatio",lbl:"量比",sub:"vs均量"},{k:"d2sma20",lbl:"距SMA20",sub:"偏離度"},
];
const PHASES=["搜尋公開市場資訊","解析最新財務報表","比對法人預估數據","評估技術面籌碼","整合產業生態","撰寫 Golem 分析報告"];
const GOLEM_PROMPT=`你是 Golem AI，專業股市分析 AI，風格精準直白、數據驅動。
輸出以下格式報告（中文，指標英文保留）：

📊 資料說明
[數據截止時間]

一、市場概況 (Market Overview)
[整體漲跌氛圍，量化呈現]

二、[標的] 主要分析
[成交價漲跌，對比自選股強弱，成交量評價]

三、技術指標重點 (Technical Context)
[RSI/MACD/KD 解讀，多空方向]

四、風險提醒
[2-3個具體風險]

五、可觀察的價位或事件
支撐：[價位]（原因）
壓力：[價位]（原因）
重要事件：[催化劑或風險]

[!IMPORTANT]
以上分析僅基於技術數據，不構成任何投資建議。`;

// ── 指標函式 ──────────────────────────────────────────────────────────

const sma=(d,n)=>{const f=d.filter(v=>v!=null);return f.length<n?null:f.slice(-n).reduce((a,b)=>a+b,0)/n;};

const emaArr=(d,n)=>{const k=2/(n+1),r=[d[0]];for(let i=1;i<d.length;i++)r.push(d[i]*k+r[i-1]*(1-k));return r;};

// FIX #2: 換成 Wilder's SMMA（標準 RSI 公式），原簡單平均誤差可達 ±17 pts
const rsiCalc=(d,n=14)=>{
  const f=d.filter(v=>v!=null);
  if(f.length<n+1)return 50;
  const gains=[], losses=[];
  for(let i=1;i<f.length;i++){
    const diff=f[i]-f[i-1];
    gains.push(diff>0?diff:0);
    losses.push(diff<0?-diff:0);
  }
  // 前 n 期用簡單平均初始化
  let ag=gains.slice(0,n).reduce((a,b)=>a+b,0)/n;
  let al=losses.slice(0,n).reduce((a,b)=>a+b,0)/n;
  // 後續用 Wilder 平滑（SMMA = (prev*(n-1)+curr)/n）
  for(let i=n;i<gains.length;i++){
    ag=(ag*(n-1)+gains[i])/n;
    al=(al*(n-1)+losses[i])/n;
  }
  return al===0?100:100-(100/(1+ag/al));
};

const macdCalc=(d)=>{const f=d.filter(v=>v!=null);if(f.length<35)return{macd:0,signal:0,histogram:0};const e12=emaArr(f,12),e26=emaArr(f,26),ml=e12.map((v,i)=>v-e26[i]).slice(25),sig=emaArr(ml,9),m=ml.at(-1)||0,s=sig.at(-1)||0;return{macd:m,signal:s,histogram:m-s};};

const stochKD=(H,L,C,n=9)=>{let k=50,d=50;const h=H.filter(v=>v!=null),l=L.filter(v=>v!=null),c=C.filter(v=>v!=null),len=Math.min(h.length,l.length,c.length);for(let i=n-1;i<len;i++){const hh=Math.max(...h.slice(i-n+1,i+1)),ll=Math.min(...l.slice(i-n+1,i+1)),rsv=hh===ll?50:(c[i]-ll)/(hh-ll)*100;k=k*2/3+rsv/3;d=d*2/3+k/3;}return{k,d};};

const annVol=(d)=>{const f=d.filter(v=>v!=null);if(f.length<20)return 0;const r=f.slice(-20).map((v,i,a)=>i?Math.log(v/a[i-1]):0).slice(1),m=r.reduce((a,b)=>a+b,0)/r.length;return Math.sqrt(r.map(x=>(x-m)**2).reduce((a,b)=>a+b,0)/r.length)*Math.sqrt(252);};

const maxDD=(d)=>{const f=d.filter(v=>v!=null);if(!f.length)return 0;let peak=f[0],mdd=0;for(const v of f){if(v>peak)peak=v;const dd=(peak-v)/peak;if(dd>mdd)mdd=dd;}return mdd;};

const fmtVol=(v,m)=>{if(!v)return"—";if(m==="TW")return`${(v/10000).toFixed(1)}萬`;if(v>1e9)return`${(v/1e9).toFixed(2)}B`;if(v>1e6)return`${(v/1e6).toFixed(2)}M`;return v.toLocaleString();};
const toYSym=(t,m)=>m==="US"?t:OTC.has(t)?t+".TWO":t+".TW";
const toTVSym=(t,m)=>{if(m==="US"){const N=new Set(["BRK.A","BRK.B","JPM","BAC","TSM","V","MA","WMT","XOM","UNH","LLY","AVGO"]);return N.has(t)?`NYSE:${t}`:`NASDAQ:${t}`;}return OTC.has(t)?`TPEX:${t}`:`TWSE:${t}`;};

// ── Yahoo Finance 取數 ────────────────────────────────────────────────
async function fetchYahoo(ticker,market){
  const sym=toYSym(ticker,market);
  const url=`https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=1d&range=3mo`;
  const proxies=[`https://corsproxy.io/?url=${encodeURIComponent(url)}`,`https://api.allorigins.win/get?url=${encodeURIComponent(url)}`];
  for(const p of proxies){try{const r=await fetch(p,{signal:AbortSignal.timeout(10000)});if(!r.ok)continue;const raw=await r.json();const j=raw.contents?JSON.parse(raw.contents):raw;if(j?.chart?.result?.[0])return j.chart.result[0];}catch{}}
  return null;
}

function processChart(chart,ticker,market){
  const meta=chart.meta,q=chart.indicators?.quote?.[0]||{};
  const closes=(q.close||[]).filter(v=>v!=null),highs=(q.high||[]).filter(v=>v!=null),lows=(q.low||[]).filter(v=>v!=null),vols=(q.volume||[]).filter(v=>v!=null);
  if(!closes.length)return null;
  const price=meta.regularMarketPrice||closes.at(-1)||0,prev=meta.chartPreviousClose||closes.at(-2)||price;
  const changeNum=prev?((price-prev)/prev*100):0,vol=vols.at(-1)||0;
  const avgVol=vols.slice(-20).reduce((a,b)=>a+b,0)/Math.max(vols.slice(-20).length,1);
  const s20=sma(closes,20)||price,mc=macdCalc(closes),kd=stochKD(highs,lows,closes);
  return{ticker,market,name:meta.longName||meta.shortName||ticker,
    price:price.toFixed(2),currency:market==="TW"?"TWD":"USD",
    change:(changeNum>=0?"+":"")+changeNum.toFixed(2)+"%",changeNum,
    volume:fmtVol(vol,market),prevClose:prev.toFixed(2),
    high52:(meta["52WeekHigh"]||0).toFixed(2),low52:(meta["52WeekLow"]||0).toFixed(2),
    ts:new Date().toLocaleTimeString("zh-TW",{hour:"2-digit",minute:"2-digit"}),
    indicators:{
      sma5:sma(closes,5)?.toFixed(2)||"—",sma20:s20?.toFixed(2)||"—",
      rsi14:rsiCalc(closes,14).toFixed(1),
      macd:mc.macd.toFixed(4),macdSig:mc.signal.toFixed(4),macdH:mc.histogram.toFixed(4),
      kdK:kd.k.toFixed(1),kdD:kd.d.toFixed(1),
      vol:(annVol(closes)*100).toFixed(1)+"%",maxdd:(maxDD(closes)*100).toFixed(1)+"%",
      volRatio:(avgVol>0?(vol/avgVol):1).toFixed(2)+"x",
      d2sma20:((price/s20-1)*100>=0?"+":"")+((price/s20-1)*100).toFixed(1)+"%"
    }};
}

// ══════════════════════════════════════════════════════════════════════
// Golem AI — 使用 Cowork 內建 askClaude（無需 API Key，無 CORS 問題）
// ══════════════════════════════════════════════════════════════════════
async function callGolem(system, userMsg) {
  const fullPrompt = `${system}\n\n${userMsg}`;
  const result = await window.cowork.askClaude(fullPrompt, []);
  if (!result) throw new Error("分析未返回結果，請稍後重試");
  return result;
}

// ── CSS ───────────────────────────────────────────────────────────────
const CSS=`
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#060A12;--bg2:#0B1220;--bg3:#111B2E;--bg4:#162240;--border:#1A2740;--bhi:#2A3D5C;
  --gold:#F5C518;--gs:rgba(245,197,24,.08);--gm:rgba(245,197,24,.18);
  --text:#C8D3E0;--thi:#F1F5FA;--tlo:#5A6A82;--tf:#2D3A52;
  --green:#4ADE80;--gnb:rgba(74,222,128,.08);--gbd:rgba(74,222,128,.3);
  --red:#F87171;--rnb:rgba(248,113,113,.08);--rbd:rgba(248,113,113,.3);
  --blue:#60A5FA;--bnb:rgba(96,165,250,.08);--bbd:rgba(96,165,250,.3);
  --cyan:#67E8F9;--orange:#FB923C;}
html,body{background:var(--bg);height:100%;font-family:'Noto Serif TC',serif;color:var(--text)}
::-webkit-scrollbar{width:4px;height:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--bhi);border-radius:2px}
.app{display:flex;flex-direction:column;height:100vh;min-height:0}
.top{flex-shrink:0;background:rgba(6,10,18,.97);border-bottom:1px solid var(--border);padding:0 12px;height:48px;display:flex;align-items:center;gap:8px}
.logo-m{width:26px;height:26px;background:var(--gs);border:1px solid var(--gm);border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0}
.logo-t{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--gold);letter-spacing:2px;font-weight:700;text-transform:uppercase;flex-shrink:0}
.logo-v{font-family:'JetBrains Mono',monospace;font-size:7px;color:var(--tlo);margin-top:1px}
.bd{display:flex;align-items:center;gap:5px;padding:0 8px;border-left:1px solid var(--border);font-family:'JetBrains Mono',monospace;font-size:10px;flex-shrink:0}
.bup{color:var(--green);font-weight:700}.bdn{color:var(--red);font-weight:700}.bavg{font-weight:700}.bsep{color:var(--tf)}
.sp{flex:1}
.pl{width:5px;height:5px;border-radius:50%;background:var(--green);box-shadow:0 0 5px var(--green);animation:pulse 2.5s ease infinite;flex-shrink:0}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.tb{padding:4px 9px;border-radius:5px;border:1px solid var(--border);background:transparent;color:var(--tlo);font-family:'JetBrains Mono',monospace;font-size:9px;cursor:pointer;font-weight:600;white-space:nowrap;flex-shrink:0;transition:all .15s}
.tb:hover{border-color:var(--gm);color:var(--gold);background:var(--gs)}
.tb.pr{background:var(--gold);color:#060A12;border-color:var(--gold)}.tb.pr:hover{background:#FBBF24}
.tb:disabled{opacity:.35;cursor:not-allowed}
.add-bar{flex-shrink:0;background:var(--bg2);border-bottom:1px solid var(--border);padding:7px 12px;display:flex;align-items:center;gap:6px}
.add-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--gold);flex-shrink:0}
.ai{flex:1;min-width:0;max-width:120px;background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:5px 8px;color:var(--thi);font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;letter-spacing:2px;text-transform:uppercase;outline:none}
.ai:focus{border-color:var(--gold);box-shadow:0 0 0 2px var(--gs)}
.am{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:5px 6px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:9px;outline:none;cursor:pointer;flex-shrink:0}
.as2{padding:5px 12px;background:var(--gold);color:#060A12;border:none;border-radius:5px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;cursor:pointer;flex-shrink:0}
.wl-strip{flex-shrink:0;background:var(--bg);border-bottom:1px solid var(--border);display:flex;overflow-x:auto;gap:2px;padding:4px 8px}
.wi{padding:5px 10px;border-radius:6px;cursor:pointer;border:1px solid var(--border);display:flex;align-items:center;gap:6px;white-space:nowrap;flex-shrink:0;transition:all .15s;background:var(--bg2)}
.wi:hover{border-color:var(--bhi);background:var(--bg3)}
.wi.act{border-color:var(--gold);background:var(--bg4)}
.wt{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:1px;color:var(--thi)}
.wi.act .wt{color:var(--gold)}
.wm{font-family:'JetBrains Mono',monospace;font-size:7px;padding:1px 3px;border-radius:2px}
.wm.tw{background:var(--gnb);color:var(--green)}.wm.us{background:var(--bnb);color:var(--blue)}
.wprice{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--thi)}
.wchg{font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700}
.wchg.up{color:var(--green)}.wchg.dn{color:var(--red)}.wchg.flat{color:var(--tlo)}
.wdel{background:transparent;border:none;color:var(--tf);cursor:pointer;font-size:11px;padding:0 2px;opacity:0;transition:color .15s}
.wi:hover .wdel{opacity:1}.wdel:hover{color:var(--red)}
.ms{display:inline-block;width:8px;height:8px;border:1.5px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.body{flex:1;display:flex;overflow:hidden;min-height:0}
.ct{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}
.ca{flex:1;min-height:0;border-bottom:1px solid var(--border);position:relative;background:var(--bg)}
.ch{position:absolute;top:0;left:0;right:0;height:32px;background:rgba(6,10,18,.92);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 10px;gap:7px;z-index:10}
.ck{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:var(--gold);letter-spacing:2px}
.cn{font-size:10px;color:var(--tlo)}
.cpx{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:var(--thi)}
.cc{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700}
.cc.up{color:var(--green)}.cc.dn{color:var(--red)}.cc.flat{color:var(--tlo)}
.tvf{width:100%;height:100%;border:none;padding-top:32px}
.hint{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--tf);gap:5px}
.ig{flex-shrink:0;overflow-x:auto}
.ig-g{display:flex;flex-wrap:wrap;gap:1px;background:var(--border);padding:1px}
.ic{background:var(--bg2);padding:6px 10px;min-width:80px;flex:1}
.il{font-family:'JetBrains Mono',monospace;font-size:7px;color:var(--tlo);letter-spacing:1px;text-transform:uppercase;margin-bottom:2px}
.iv{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:var(--thi)}
.iv.up{color:var(--green)}.iv.dn{color:var(--red)}.iv.warn{color:var(--orange)}.iv.info{color:var(--cyan)}
.is2{font-family:'JetBrains Mono',monospace;font-size:7px;color:var(--tf);margin-top:1px}
.rp{width:270px;flex-shrink:0;border-left:1px solid var(--border);display:flex;flex-direction:column;background:var(--bg2)}
.rt{display:flex;border-bottom:1px solid var(--border);flex-shrink:0;background:var(--bg)}
.rtb{flex:1;padding:7px 0;text-align:center;font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tlo);letter-spacing:1px;cursor:pointer;border-bottom:2px solid transparent;transition:all .15s}
.rtb:hover{color:var(--text)}.rtb.act{color:var(--gold);border-bottom-color:var(--gold)}
.rb{flex:1;overflow-y:auto;padding:12px}
.re{text-align:center;padding:30px 0;font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tf);line-height:1.8}
.st{font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700;color:var(--gold);letter-spacing:2px}
.sn{font-size:11px;color:var(--tlo);margin-top:2px;margin-bottom:9px}
.spr{display:flex;align-items:baseline;gap:7px;margin-bottom:3px}
.sp2{font-family:'JetBrains Mono',monospace;font-size:19px;font-weight:700;color:var(--thi)}
.scr{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--tlo)}
.sbg2{font-family:'JetBrains Mono',monospace;font-size:8px;padding:2px 6px;border-radius:3px;font-weight:700}
.sbg2.tw{background:var(--gnb);color:var(--green);border:1px solid var(--gbd)}
.sbg2.us{background:var(--bnb);color:var(--blue);border:1px solid var(--bbd)}
.sch{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700;margin-bottom:11px}
.sch.up{color:var(--green)}.sch.dn{color:var(--red)}.sch.flat{color:var(--tlo)}
.sr{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border)}
.sr:last-of-type{border-bottom:none}
.sk{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tlo)}
.sv{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--thi);font-weight:600}
.anb{width:100%;padding:9px;background:var(--gold);color:#060A12;border:none;border-radius:7px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;cursor:pointer;transition:all .15s;margin-top:10px}
.anb:hover:not(:disabled){background:#FBBF24}
.anb:disabled{opacity:.35;cursor:not-allowed}
.aspin{width:32px;height:32px;border:2px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 9px}
.aph{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--gold);letter-spacing:1px;text-align:center}
.adot{animation:blink 1.2s step-end infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
.abar{height:2px;background:var(--bg);border-radius:1px;overflow:hidden;margin-top:9px}
.abar-f{height:100%;background:linear-gradient(90deg,var(--gold),var(--cyan),var(--gold));background-size:200% 100%;animation:grad 2s linear infinite}
@keyframes grad{to{background-position:-200% 0}}
.abox{text-align:center;padding:16px 0}
.afr{padding:6px 9px;background:var(--bg);border:1px solid var(--border);border-radius:5px;margin-bottom:10px}
.aft{font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--cyan);margin-bottom:2px}
.afd{font-size:10px;color:var(--tlo);line-height:1.6}
.asct{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--gold);font-weight:700;margin:10px 0 5px;padding-bottom:3px;border-bottom:1px solid var(--border)}
.aln{font-size:11px;line-height:1.85;color:var(--text);margin:2px 0}
.ark{padding:4px 7px;background:var(--rnb);border:1px solid rgba(248,113,113,.2);border-radius:4px;margin:3px 0;font-size:11px;color:var(--text)}
.alv{display:flex;gap:6px;padding:3px 7px;background:var(--bg);border-radius:4px;margin:2px 0;font-size:11px;color:var(--text)}
.adc{padding:6px 8px;background:var(--gs);border:1px solid var(--gm);border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:8px;color:var(--tlo);margin-top:9px;line-height:1.7}
.aerr{padding:10px;background:var(--rnb);border:1px solid var(--rbd);border-radius:6px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--red);margin-bottom:9px}
@media(max-width:700px){.rp{display:none}}
`;

// ── 子元件 ────────────────────────────────────────────────────────────
function IndCard({def,data}){
  const raw=data?.indicators?.[def.k];let cls="";
  if(raw){
    if(def.k==="rsi14"){const n=parseFloat(raw);cls=n>=70?"warn":n<=30?"dn":"";}
    else if(def.k==="macd"||def.k==="macdH")cls=parseFloat(raw)>=0?"up":"dn";
    else if(def.k==="d2sma20")cls=raw.startsWith("+")?"up":raw.startsWith("-")?"dn":"";
    else if(def.k==="kdK"){const n=parseFloat(raw);cls=n>=80?"warn":n<=20?"info":"";}
  }
  return <div className="ic"><div className="il">{def.lbl}</div><div className={`iv ${cls}`}>{raw||"—"}</div><div className="is2">{def.sub}</div></div>;
}

function AnalysisView({text,onRerun}){
  if(!text)return <div className="re">點擊「🍌 Golem 分析」開始<br/><span style={{fontSize:8,color:"var(--tf)"}}>Claude AI · 免費 · 約 15-30 秒</span></div>;
  if(text.startsWith("ERR:"))return <><div className="aerr">⚠ {text.slice(4)}</div><button className="anb" onClick={onRerun}>🔄 重試</button></>;
  let inRisk=false,inLevel=false;
  return <div>
    <div className="afr"><div className="aft">📊 分析完成</div><div className="afd">{new Date().toLocaleString("zh-TW")}<br/>Claude AI · Web Search</div></div>
    {text.split("\n").map((line,i)=>{
      const isSec=/^(一|二|三|四|五|[📊])[、.]/.test(line);
      const isImp=line.includes("[!IMPORTANT]")||line.includes("不構成任何投資建議");
      if(line.includes("四、"))inRisk=true;
      if(line.includes("五、")){inRisk=false;inLevel=true;}
      if(isSec)return <div key={i} className="asct">{line}</div>;
      if(isImp)return <div key={i} className="adc">{line.replace("[!IMPORTANT]","⚠")}</div>;
      if(!line.trim())return <div key={i} style={{height:4}}/>;
      if(inRisk&&/^[-•]/.test(line))return <div key={i} className="ark">⚠ {line.replace(/^[-•]\s*/,"")}</div>;
      if(inLevel&&/^(支撐|壓力|重要)/.test(line)){
        const t=/支撐/.test(line)?"支撐":/壓力/.test(line)?"壓力":"事件";
        const c=/支撐/.test(line)?"var(--green)":/壓力/.test(line)?"var(--red)":"var(--blue)";
        const bg=/支撐/.test(line)?"var(--gnb)":/壓力/.test(line)?"var(--rnb)":"var(--bnb)";
        return <div key={i} className="alv">
          <span style={{fontFamily:"JetBrains Mono,monospace",fontSize:8,padding:"2px 5px",borderRadius:2,background:bg,color:c,flexShrink:0}}>{t}</span>
          {line.replace(/^(支撐|壓力|重要事件)[：:]\s*/,"")}
        </div>;
      }
      return <div key={i} className="aln">{line}</div>;
    })}
    <button className="anb" style={{marginTop:10}} onClick={onRerun}>🔄 重新分析</button>
  </div>;
}

// ── 主元件 ────────────────────────────────────────────────────────────
export default function App(){
  const [wl,setWl]=useState(DEFAULT_WL);
  const [data,setData]=useState({});
  const [loading,setLoading]=useState(new Set());
  const [sel,setSel]=useState(null);
  const [tab,setTab]=useState("stats");
  const [analyzing,setAnalyzing]=useState(false);
  const [aText,setAText]=useState("");
  const [aPhase,setAPhase]=useState("");
  const [addT,setAddT]=useState("");
  const [addM,setAddM]=useState("TW");
  const phaseTimer=useRef(null);

  const refresh=useCallback(async(ticker,market)=>{
    setLoading(p=>new Set(p).add(ticker));
    const chart=await fetchYahoo(ticker,market);
    setLoading(p=>{const n=new Set(p);n.delete(ticker);return n;});
    if(chart){
      const processed=processChart(chart,ticker,market);
      if(processed)setData(p=>({...p,[ticker]:processed}));
    }
  },[]);

  useEffect(()=>{
    wl.forEach(w=>refresh(w.ticker,w.market));
    // FIX #4: 元件卸載時清除計時器，防止記憶體洩漏
    return ()=>clearInterval(phaseTimer.current);
  },[]);

  const addStock=()=>{
    const t=addT.trim().toUpperCase();
    if(!t||wl.find(w=>w.ticker===t&&w.market===addM))return;
    const newItem={ticker:t,market:addM};
    setWl(p=>[...p,newItem]);
    setAddT("");
    setSel(newItem);
    setTab("stats");
    refresh(t,addM);
  };
  const removeStock=(t,m,e)=>{
    e.stopPropagation();
    setWl(p=>p.filter(w=>!(w.ticker===t&&w.market===m)));
    if(sel?.ticker===t)setSel(null);
    setData(p=>{const n={...p};delete n[t];return n;});
  };

  const dataArr=wl.map(w=>data[w.ticker]).filter(Boolean);
  const upCnt=dataArr.filter(d=>d.changeNum>0).length;
  const dnCnt=dataArr.filter(d=>d.changeNum<0).length;
  const avgChg=dataArr.length?dataArr.reduce((s,d)=>s+d.changeNum,0)/dataArr.length:0;
  const selData=sel?data[sel.ticker]:null;
  const tvSrc=sel?`https://www.tradingview.com/widgetembed/?frameElementId=tv&symbol=${encodeURIComponent(toTVSym(sel.ticker,sel.market))}&interval=D&hidesidetoolbar=1&hidetoptoolbar=0&toolbarbg=0B1220&studies=RSI%40tv-basicstudies%1FMACD%40tv-basicstudies%1FStoch%40tv-basicstudies&theme=dark&style=1&timezone=Asia%2FTaipei&withdateranges=1&locale=zh_TW&saveimage=0&showpopupbutton=0`:null;

  const runAnalysis=useCallback(async()=>{
    if(!sel)return;
    setAnalyzing(true);setAText("");setTab("analysis");
    let pi=0;setAPhase(PHASES[0]);
    clearInterval(phaseTimer.current);
    phaseTimer.current=setInterval(()=>{pi=(pi+1)%PHASES.length;setAPhase(PHASES[pi]);},3500);

    const d=selData;
    const allStr=wl.map(w=>{const x=data[w.ticker];return x?`${x.ticker}:${x.price}${x.currency} ${x.change}`:`${w.ticker}:無資料`;}).join(" | ");
    const indStr=d?Object.entries(d.indicators).map(([k,v])=>`${k}:${v}`).join(" "):"-";
    const msg=`分析標的：${sel.ticker}(${sel.market==="TW"?"台股":"美股"})\n${d?`名稱:${d.name} 價格:${d.price}${d.currency} 漲跌:${d.change}\n量:${d.volume} 52週:${d.low52}-${d.high52}\n指標:${indStr}`:""}\n自選股:${allStr}\n廣度：▲${upCnt}/▼${dnCnt}/均${avgChg>=0?"+":""}${avgChg.toFixed(2)}%`;

    try {
      const result = await callGolem(GOLEM_PROMPT, msg);
      clearInterval(phaseTimer.current);
      setAText(result);
    } catch(e) {
      clearInterval(phaseTimer.current);
      setAText("ERR:" + e.message);
    } finally {
      setAnalyzing(false);
    }
  },[sel,selData,wl,data,upCnt,dnCnt,avgChg]);

  return <>
    <style>{CSS}</style>
    <div className="app">
      <div className="top">
        <div className="logo-m">🍌</div>
        <div style={{flexShrink:0}}><div className="logo-t">個股研究終端機</div><div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:7,color:"var(--tlo)",marginTop:1}}>v5.1 · Golem Dashboard · 免費版</div></div>
        <div className="bd">
          <span className="bup">▲{upCnt}</span><span className="bsep">/</span>
          <span className="bdn">▼{dnCnt}</span><span className="bsep">/</span>
          <span className="bavg" style={{color:avgChg>=0?"var(--green)":"var(--red)"}}>{avgChg>=0?"+":""}{avgChg.toFixed(2)}%</span>
        </div>
        <div className="sp"/>
        <div className="pl"/>
        <button className="tb" onClick={()=>wl.forEach(w=>refresh(w.ticker,w.market))}>⟳ 更新</button>
        <button className="tb pr" onClick={runAnalysis} disabled={!sel||analyzing}>{analyzing?"⏳ 分析中":"🍌 分析"}</button>
      </div>

      <div className="add-bar">
        <span className="add-lbl">＋ 新增</span>
        <input className="ai" value={addT} onChange={e=>setAddT(e.target.value.toUpperCase())}
          onKeyDown={e=>e.key==="Enter"&&addStock()} placeholder="2330 / SNPS" maxLength={10}/>
        <select className="am" value={addM} onChange={e=>setAddM(e.target.value)}>
          <option value="TW">🇹🇼 台股</option><option value="US">🇺🇸 美股</option>
        </select>
        <button className="as2" onClick={addStock}>＋ 加入</button>
      </div>

      <div className="wl-strip">
        {wl.map(w=>{
          const d=data[w.ticker],isLoad=loading.has(w.ticker),isAct=sel?.ticker===w.ticker;
          const cc=!d?"":d.changeNum>0?"up":d.changeNum<0?"dn":"flat";
          return <div key={w.ticker+w.market} className={`wi ${isAct?"act":""}`}
            onClick={()=>{setSel({ticker:w.ticker,market:w.market});setTab("stats");}}>
            <span className={`wm ${w.market.toLowerCase()}`}>{w.market}</span>
            <span className="wt">{w.ticker}</span>
            <span className="wprice">{isLoad?<span className="ms"/>:(d?d.price:"—")}</span>
            <span className={`wchg ${cc}`}>{d?d.change:"—"}</span>
            <button className="wdel" onClick={e=>removeStock(w.ticker,w.market,e)}>×</button>
          </div>;
        })}
      </div>

      <div className="body">
        <div className="ct">
          <div className="ca">
            <div className="ch">
              <span className="ck">{sel?.ticker||"—"}</span>
              <span className="cn">{selData?.name||"點選股票"}</span>
              <span style={{marginLeft:"auto"}} className="cpx">{selData?`${selData.price} ${selData.currency}`:""}</span>
              <span className={`cc ${selData?selData.changeNum>0?"up":selData.changeNum<0?"dn":"flat":""}`}>{selData?.change||""}</span>
            </div>
            {tvSrc?<iframe className="tvf" key={sel.ticker} src={tvSrc} title="TV" allowTransparency frameBorder="0" scrolling="no" allowFullScreen/>
              :<div className="hint"><span>↑ 點選股票或加入新代號</span></div>}
          </div>
          <div className="ig"><div className="ig-g">{IND_DEFS.map(d=><IndCard key={d.k} def={d} data={selData}/>)}</div></div>
        </div>

        <div className="rp">
          <div className="rt">
            {["stats","analysis"].map(t=><div key={t} className={`rtb ${tab===t?"act":""}`} onClick={()=>setTab(t)}>{t==="stats"?"📋 快覽":"🍌 分析"}</div>)}
          </div>
          <div className="rb">
            {tab==="stats"&&(selData?<div>
              <div className="st">{selData.ticker}</div>
              <div className="sn">{selData.name}</div>
              <div className="spr"><span className="sp2">{selData.price}</span><span className="scr">{selData.currency}</span><span className={`sbg2 ${selData.market.toLowerCase()}`}>{selData.market==="TW"?"🇹🇼 台股":"🇺🇸 美股"}</span></div>
              <div className={`sch ${selData.changeNum>0?"up":selData.changeNum<0?"dn":"flat"}`}>{selData.change}</div>
              {[["前收盤",`${selData.prevClose} ${selData.currency}`],["52週高/低",`${selData.high52}/${selData.low52}`],["成交量",selData.volume],["更新",selData.ts]].map(([k,v])=>
                <div key={k} className="sr"><span className="sk">{k}</span><span className="sv">{v}</span></div>)}
              <button className="anb" onClick={runAnalysis} disabled={analyzing}>{analyzing?"⏳ 分析中（約15-30秒）...":"🍌 Golem 分析"}</button>
            </div>:<div className="re">← 點選股票查看詳情</div>)}
            {tab==="analysis"&&(analyzing
              ?<div className="abox">
                <div className="aspin"/>
                <div className="aph">{aPhase}<span className="adot">...</span></div>
                <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:8,color:"var(--tf)",marginTop:5}}>Claude AI + Web Search · 約 15-30 秒</div>
                <div className="abar"><div className="abar-f"/></div>
              </div>
              :<AnalysisView text={aText} onRerun={runAnalysis}/>
            )}
          </div>
        </div>
      </div>
    </div>
  </>;
}

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/enhance_v3.js'), 'utf8');
const end = source.lastIndexOf('})();');
assert.ok(end > 0, 'module closure anchor missing');
const neutral = {rsi14:50, macd:0, macdSig:0, K:50, D:50, sma20:100, sma60:100};
function setup() {
  const calls = [];
  const s = {console, S:{sym:'2330', mkt:'TW', tab:'stats', ind:neutral, data:{candles:[{close:100}]}},
    document:{readyState:'loading', getElementById(){return null}, querySelector(){return null}, createElement(){return {}}, head:{appendChild(){}}, addEventListener(){}},
    localStorage:{getItem(){return null}, setItem(){}}, setTimeout(){}, renderStats(){return '<div>original stats</div>'}, setTab(){},
    fetch:async url=>{calls.push(url);return {ok:true,json:async()=>({})}}, parseYF:()=>({candles:Array.from({length:60},()=>({close:100}))}), runWorker:async()=>neutral};
  s.window=s;vm.createContext(s);
  vm.runInContext(source.slice(0,end)+'window.testTech={techScore,techScoreResolved,computeCanonTech,dualCardHtml};'+source.slice(end),s);
  return {s,calls,t:s.testTech};
}
async function run() {
  const {s,t,calls}=setup();
  assert.equal(t.techScore(neutral,[{close:100}]),50);
  assert.equal(t.techScore({},[{close:100}]),null);
  const strong={rsi14:75,macd:1,macdSig:0,K:80,D:60,sma20:95,sma60:90};
  const score=t.techScore(strong,[{close:100}]);assert.equal(score,100);
  assert.equal(t.techScore({...neutral,rsi14:'50',macd:'0',macdSig:'0'},[{close:100}]),50);
  await t.computeCanonTech('2330','TW');assert.match(calls[0],/2330.TW\?range=1y&interval=1d$/);
  assert.equal(t.techScoreResolved(),50);s.S.data.candles=[{close:200}];s.S.ind=strong;assert.equal(t.techScoreResolved(),50,'display range must not change canonical score');
  s.S.sym='AAPL';s.S.mkt='US';await t.computeCanonTech('AAPL','US');assert.match(calls[1],/\/yf\/AAPL\?range=1y&interval=1d$/);assert.equal(t.techScoreResolved(),50);
  s.S.sym='00632R';s.S.mkt='TW';s.runWorker=async()=>strong;await t.computeCanonTech('00632R','TW');assert.match(calls[2],/0050.TW/);assert.equal(t.techScoreResolved(),100-score);
  const html=t.dualCardHtml(70);assert.match(html,/data-score-kind="technical"/);assert.match(html,/data-score-kind="fundamental"/);assert.doesNotMatch(html,/setTab\('health'\)|data-score-kind="health"/);
  const untouched=fs.readFileSync(path.join(__dirname,'../src/ui/stock_health_v5.js'),'utf8');assert.match(untouched,/StockHealthV5/);
  console.log('PASS historical score formula, numeric inputs, canonical TW/US, range independence, inverse mapping and separate score card');
}
run().catch(e=>{console.error(e);process.exitCode=1});

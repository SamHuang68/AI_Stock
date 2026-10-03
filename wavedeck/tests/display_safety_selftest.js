'use strict';
// Offline fake DOM contract checks; no server, browser, or network is launched.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: '', textContent: '', style: {},
    classList: {add() {}, remove() {}, toggle() {}}, value: ''
  });
  return elements.get(id);
}
let response;
const context = {
  window: {},
  document: {readyState:'loading', addEventListener() {},
    getElementById:element, querySelectorAll:() => []},
  fetch:async () => ({ok:true, json:async () => response}),
  setTimeout() {}, clearTimeout() {}
};
const source = fs.readFileSync(path.join(__dirname, '../web/js/deck.js'), 'utf8');
const marker = "  if (document.readyState === 'loading')";
assert.equal(source.split(marker).length, 2);
vm.runInNewContext(source.replace(marker,
  '  window.fixture = {render, money, fmtPct, refreshStCost};\n' + marker), context);
const {render, money, fmtPct, refreshStCost} = context.window.fixture;
const attack = '"><img src=x onerror=alert(1)><script>alert(1)</script>&';
let assertions = 0;
function check(fn) { fn(); assertions++; }
for (const value of [null, undefined, '', true, NaN, Infinity]) {
  check(() => assert.equal(money(value), '—'));
  check(() => assert.equal(fmtPct(value), '—'));
}
check(() => assert.equal(money(0), '0'));
check(() => assert.equal(fmtPct(0), '0%'));
const state = {
  fsm:'AwaitingFill', mode:'paper', style:50,
  positions:{ai_suggested:attack, txt_target:0, strategy:0, account:0},
  ai:{action_label:attack, confidence:null, bias_long:null, bias_short:0,
      summary:attack, next_watch:[attack], invalidation:{price:null}, process:{}},
  quote:{as_of:'2026-10-03T12:00:00+08:00', quality:'demo', demo:true},
  no_overnight:{enabled:true, force_flat_time:attack},
  lights:{system:attack, email_monitor:attack},
  account:{equity:null, yesterday_balance:null, equity_change:null,
      daily_dd_pct:null, broker_api:attack},
  execution:{status:'pending'},
  exec:{last_ai_action:attack, last_order_action:attack, price:null, lots:0},
  costs:{session_usd:null, day_usd:null, month_usd:null, provider:attack,
      local_calls:attack, cloud_calls:0,
      budget:{committed_usd:1.5, reserved_usd:1.5, limit_usd:5, pricing_configured:true}},
  transport:{webhook:attack,tunnel:attack,domain:attack,parse_errors:attack}
};
render(state);
for (const [id, el] of elements) {
  check(() => assert.ok(!/<(?:img|script)\b/i.test(el.innerHTML), id));
  check(() => assert.ok(!/title="[^"]*"\s+onerror=/i.test(el.innerHTML), id));
}
check(() => assert.match(element('aiTags').innerHTML, /&lt;img/));
check(() => assert.equal(element('aiConf').textContent, '—'));
check(() => assert.equal(element('fsm').textContent, '等待成交確認'));
check(() => assert.match(element('execKv').innerHTML, /pending/));
check(() => assert.match(element('acct').innerHTML, /—（未評估）/));
check(() => assert.match(element('noOvernight').innerHTML, /自動強制平倉尚未實作/));
check(() => assert.match(element('aiUpdated').textContent, /2026-10-03T12:00:00\+08:00.*核對時.*示範/));
check(() => assert.equal(element('stSpillPct').textContent, '—'));
check(() => assert.match(element('costKv').innerHTML, /已用及預留 USD 1.5/));
check(() => assert.match(element('costKv').innerHTML, /預留 USD/));
render({...state, ai:{next_watch:attack}, st_overlay:{spillover_prob:0},
  costs:{provider:'heuristic', session_usd:0, day_usd:null, month_usd:null}});
check(() => assert.equal(element('stSpillPct').textContent, '0%'));
check(() => assert.match(element('costKv').innerHTML, /未配置雲端費率，禁止付費呼叫/));
check(() => assert.ok(!element('costKv').innerHTML.includes('API 費用 $0')));
(async () => {
  response = {ok:true, costs:{combined_usd_est:attack, st_local_calls:attack}};
  await refreshStCost();
  check(() => assert.ok(!/<(?:img|script)\b/i.test(element('costKv').innerHTML)));
  check(() => assert.match(element('costKv').innerHTML, /ST\+WD 合計/));
  console.log(JSON.stringify({fixture:'display_safety', assertions, passed:true, environment:'offline fake DOM'}));
})().catch(error => { console.error(error); process.exitCode = 1; });

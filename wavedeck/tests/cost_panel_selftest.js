'use strict';
// 離線假 DOM：不啟動伺服器、瀏覽器或網路。載入真實的 deck.js，檢查費用面板在各種帳本狀態下的呈現。
// 「基準狀態整支 render 跑得完」本身就是一項檢查：在 render 內新增 var 而蓋掉外層同名函式（例如 money），
// 會讓面板之前的區塊丟例外，語法檢查與 Python 測試都抓不到，只有真的執行 render 才會發現。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    innerHTML: '', textContent: '', style: {}, value: '', checked: false, disabled: false,
    classList: {add() {}, remove() {}, toggle() {}}
  });
  return elements.get(id);
}
const context = {
  window: {},
  document: {readyState: 'loading', addEventListener() {}, getElementById: element, querySelectorAll: () => []},
  fetch: async () => ({ok: true, json: async () => ({})}),
  setTimeout() {}, clearTimeout() {}
};
const source = fs.readFileSync(path.join(__dirname, '../web/js/deck.js'), 'utf8');
const marker = "  if (document.readyState === 'loading')";
assert.equal(source.split(marker).length, 2, '找不到唯一的啟動標記；deck.js 的結構變了，請更新這支自測');
vm.runInNewContext(source.replace(marker, '  window.fixture = {render, money};\n' + marker), context);
const {render, money} = context.window.fixture;

let assertions = 0;
function check(fn) { fn(); assertions++; }
const costHtml = () => element('costKv').innerHTML;

function stateWith(costs) {
  return {
    fsm: 'InPosition', mode: 'paper', style: 50,
    positions: {ai_suggested: 0, txt_target: 0, strategy: 0, account: 0},
    ai: {action_label: '維持續抱', confidence: 0.6, bias_long: 0.6, bias_short: 0.4, summary: '測試', next_watch: [],
         invalidation: {price: null}, process: {}},
    no_overnight: {enabled: false}, lights: {system: 'ok'},
    account: {equity: 1000000, yesterday_balance: 1000000, equity_change: 0, daily_dd_pct: 0, broker_api: 'paper'},
    execution: {status: 'confirmed'}, exec: {price: 45000, lots: 0},
    costs, transport: {webhook: 'ready', tunnel: 'named', domain: '127.0.0.1:1', parse_errors: 0}
  };
}
const ledger = (over) => ({day: '2026-10-03', timezone: 'UTC+08:00', limit_usd: 5, spent_usd: 0.00014, reserved_usd: 0,
  committed_usd: 0.00014, available_usd: 4.99986, unknown_requests: 0, pending_requests: 0, blocked: false,
  limit_breached: false, pricing_configured: true, ...over});

// 1. 基準：沒有帳本、規則引擎。整支 render 要跑得完，且既有的面板內容不變（權益格式化用的是外層 money）。
check(() => assert.doesNotThrow(() => render(stateWith({provider: 'heuristic', session_usd: 0, day_usd: 0, month_usd: 0}))));
check(() => assert.match(costHtml(), /API 費用 \$0（非雲端）/));
check(() => assert.match(costHtml(), /本機／雲端次/));
check(() => assert.ok(!/帳本/.test(costHtml())));
check(() => assert.equal(money(1000000), '1,000,000'));
check(() => assert.match(element('acct').innerHTML, /1,000,000/));

// 2. 正常的付費請求：已用及預留與上限、預留與可用金額
render(stateWith({provider: 'openai', session_usd: 0.00014, day_usd: 0.00014, month_usd: 0.00014, local_calls: 0,
  cloud_calls: 1, budget: ledger()}));
check(() => assert.match(costHtml(), /帳本 2026-10-03：已用及預留 \$0\.00014 \/ 上限 \$5/));
check(() => assert.match(costHtml(), /預留 USD<\/div><div class="v">0</));
check(() => assert.match(costHtml(), /可用 USD<\/div><div class="v">4\.99986</));
check(() => assert.ok(!/已阻擋|未知費用/.test(costHtml())));

// 3. 付費請求失敗後退回規則引擎（provider 變 heuristic）：不能顯示「API 費用 $0」，要顯示帳本與未知費用
render(stateWith({provider: 'heuristic', session_usd: 0, day_usd: 0.0012, month_usd: 0, cloud_calls: 1,
  budget: ledger({spent_usd: 0, reserved_usd: 0.0012, committed_usd: 0.0012, available_usd: 4.9988, unknown_requests: 1})}));
check(() => assert.ok(!costHtml().includes('API 費用 $0')));
check(() => assert.match(costHtml(), /已用及預留 \$0\.0012/));
check(() => assert.match(costHtml(), /未知費用 1 筆（已保留預留）/));

// 4. 阻擋的各種原因，各有固定說明
render(stateWith({provider: 'heuristic', budget: ledger({blocked: true, pricing_configured: false, committed_usd: 0, spent_usd: 0, available_usd: 5, status: 'unconfigured'})}));
check(() => assert.match(costHtml(), /未配置雲端價目，付費呼叫已阻擋/));
render(stateWith({provider: 'heuristic', budget: ledger({blocked: true, committed_usd: 5, available_usd: 0})}));
check(() => assert.match(costHtml(), /已達每日上限，付費呼叫已阻擋/));
render(stateWith({provider: 'heuristic', budget: ledger({blocked: true, limit_breached: true})}));
check(() => assert.match(costHtml(), /超出已配置成本限制，付費呼叫已停止，需人工處理/));
render(stateWith({provider: 'heuristic', budget: ledger({blocked: true, status: 'unavailable', limit_usd: null, spent_usd: null,
  reserved_usd: null, committed_usd: null, available_usd: null, pricing_configured: false})}));
check(() => assert.match(costHtml(), /費用帳本無法驗證，付費呼叫已阻擋/));
check(() => assert.match(costHtml(), /已用及預留 未知 \/ 上限 未知/));   // 帳本讀不到是「未知」，不是 0
check(() => assert.ok(!/已用及預留 \$0/.test(costHtml())));

// 5. 舊的執行期狀態：供應者是 openai 但還沒有帳本紀錄
render(stateWith({provider: 'openai', day_usd: 0.5}));
check(() => assert.match(costHtml(), /今日 \$0\.5（尚無費用帳本紀錄）/));
check(() => assert.ok(!costHtml().includes('警戒')));

// 6. 帳本欄位來自狀態檔，不可信：日期與數字只輸出安全字元
const attack = '"><img src=x onerror=alert(1)><script>alert(1)</script>';
render(stateWith({provider: 'openai', budget: ledger({day: attack, limit_usd: attack, committed_usd: attack,
  reserved_usd: attack, available_usd: attack, unknown_requests: attack})}));
check(() => assert.ok(!/<(?:img|script)\b/i.test(costHtml())));
check(() => assert.match(costHtml(), /已用及預留 未知 \/ 上限 未知/));

console.log(JSON.stringify({fixture: 'cost_panel', assertions, passed: true, environment: 'offline fake DOM'}));

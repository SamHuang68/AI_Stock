// 個股體檢卡（stock_health_v5）：三種閱讀深度、統計閘門、跳脫與用詞紅線。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/ui/stock_health_v5.js'), 'utf8');
const store = {};
const sandbox = {
  window: {},
  document: { getElementById() { return null; }, createElement() { return {}; }, head: { appendChild() {} } },
  localStorage: { getItem(k) { return store[k] || null; }, setItem(k, v) { store[k] = String(v); } },
  location: { origin: 'http://127.0.0.1:18432' },
  console,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const H = sandbox.StockHealthV5;

const qualityMarkup = H.qualityHtml({ label: '資料需留意', referenceSession: '2026-09-24',
  items: [{ label: '籌碼', status: 'missing', impact: '只影響籌碼<script>' },
    { label: '統計', status: 'stale', asOf: '2026-09-10', lagSessions: 8, generatedAt: '2026-09-27' }], notes: [] }, 'pro');
if (!qualityMarkup.includes('缺資料') || !qualityMarkup.includes('待更新') || qualityMarkup.includes('<script>')) throw new Error('品質提示或跳脫錯誤');
const maintenanceMarkup = H.maintenanceHtml({ running: false, job: {status:'failed', steps:[{label:'重算',status:'failed'}]},
  observations: {enabled:true,events:0,outcomes:0}, inventory: {symbols:100,alignedSymbols:80} });
if (!maintenanceMarkup.includes('失敗') || !maintenanceMarkup.includes('80／100') || !maintenanceMarkup.includes('0 個事件')) throw new Error('維護失敗或真實空狀態錯誤');
const adjustmentMarkup = H.sensitivityHtml({status:'missing',coveredSymbols:0,totalSymbols:100,limitations:[]});
const closedMarkup = H.maintenanceHtml({job:{},observations:{enabled:true,lastRun:{asOf:'2026-09-28',reason:'官方公告休市：教師節'}},
  inventory:{calendar:{reason:'官方公告休市：教師節'},knownInactive:[{symbol:'5371',label:'股份轉換<script>',stopDate:'2026-08-24',
    localAsOf:'2026-09-03',sourceDateConflict:true,source:'https://www.tpex.org.tw/'}]}});
if (!closedMarkup.includes('教師節') || !closedMarkup.includes('未納入還原比較') || closedMarkup.includes('<script>')) throw new Error('休市與終止交易必須可見且安全跳脫');
const reconciledMarkup = H.sensitivityHtml({status:'missing',snapshotSymbols:100,reconciledSymbols:72,limitations:[]});
if (!reconciledMarkup.includes('72 檔經明示分割') || !reconciledMarkup.includes('原始行情與差異證據保留')) throw new Error('價格基準轉換必須揭露');
if (!adjustmentMarkup.includes('缺值不當成無除權息') || !adjustmentMarkup.includes('0／100')) throw new Error('缺還原資料必須明示');
const mismatchMarkup = H.sensitivityHtml({status:'missing',coveredSymbols:0,totalSymbols:1,snapshotSymbols:1,
  limitations:[],missingSymbols:['2330'],missingDetails:[{symbol:'2330',label:'原價不一致<script>',priceMismatches:[{date:'2024-03-29'}]}]});
if (!mismatchMarkup.includes('已取得來源快照 1 檔') || !mismatchMarkup.includes('2024-03-29') || mismatchMarkup.includes('<script>')) throw new Error('來源已取得但未接納的原因不可隱藏');

function ok(value, message) {
  if (!value) throw new Error('FAIL: ' + message);
  console.log('OK  ', message);
}

const light = (key, label, state, tag) => ({ key, label, state, tag, plain: label + '說明', values: {}, evidenceId: 'light.' + key });
const fixture = {
  ok: true, symbol: '2330', market: 'TW', asOf: '2026-09-25', engine: 'st-stock-signals/v1', bars: 900,
  session: { provisional: false }, dataSource: 'local-db', staleDays: 0, generatedAt: '2026-09-25T15:00:00+08:00',
  disclaimer: '不是買賣建議', evidence: { 'ind.close': {} },
  indicators: { close: 1000, chgPct: 1.2, sma5: 990, sma20: 980, sma60: 950, rsi14: 72.3, macd: 1, macdSignal: 0.5,
    macdHist: 0.5, bbUpper: 1010, bbLower: 950, atr14: 20, volVs20d: 1.1, vol5vs20: 0.9, high20: 1005, low20: 940 },
  health: {
    lights: [light('trend', '趨勢', 'bull', '上升'), light('momentum', '動能', 'caution', '過熱'),
      light('volume', '量能', 'neutral', '正常'), light('chip', '籌碼', 'bear', '法人賣'), light('risk', '風險', 'unknown', '資料不足')],
    summary: { sentence: '中期上升趨勢未變，但短線漲多過熱<script>', overall: 'mixed' },
    invalidation: { text: '收盤跌破季線 950.00（距今 -5.0%）代表中期上升趨勢轉弱' },
  },
  events: [
    { signalId: 'mom_rsi_fade', label: 'RSI 過熱回落', direction: 'bear', directionLabel: '偏空', date: '2026-09-25',
      barsAgo: 0, status: 'new', statusLabel: '今日新訊號', provisional: false, detail: 'RSI 由 74 跌回 70 以下',
      plain: '買氣過熱後開始降溫', invalidation: { text: '收盤再創近 10 日新高', level: 1012.5 }, evidenceId: 'event.mom_rsi_fade',
      stats: { minSample: 20, method: '只用當根以前資料', horizons: [
        { horizon: 5, n: 34, gate: 'ok', upRatio: 0.41, baseUpRatio: 0.52, medianRet: -0.004, medianAdverse: 0.03, edgePts: -11 },
        { horizon: 20, n: 33, gate: 'ok', upRatio: 0.48, baseUpRatio: 0.55, medianRet: 0.01, medianAdverse: 0.06, edgePts: -7 }] } },
    { signalId: 'vol_breakout_20d', label: '帶量突破 20 日高', direction: 'bull', directionLabel: '偏多', date: '2026-09-20',
      barsAgo: 3, status: 'invalidated', statusLabel: '已失效', provisional: false, detail: '突破',
      plain: '突破近一個月高點', invalidation: { text: '收盤跌回突破點之下', level: 990 }, evidenceId: 'event.vol_breakout_20d',
      stats: { minSample: 20, horizons: [{ horizon: 5, n: 7, gate: 'insufficient', upRatio: null }] } },
  ],
};

const beginner = H.cardHtml(fixture, 'beginner', { mode: 'off', channels: [], symbols: 3 });
ok(beginner.includes('中期上升趨勢未變') && !beginner.includes('<script>'), 'summary rendered and HTML-escaped');
ok(beginner.includes('什麼情況代表判斷錯了'), 'beginner card shows invalidation line');
ok(beginner.includes('RSI 過熱回落') && !beginner.includes('帶量突破 20 日高'), 'beginner hides invalidated events');
ok(beginner.includes('上漲 41%') && beginner.includes('本檔全期間 52%'), 'gated stats show ratio with base rate');
ok(!beginner.includes('報酬中位數'), 'beginner keeps stats to one line');
ok(!beginner.includes('SMA5 / 20 / 60'), 'beginner has no indicator table');

const advanced = H.cardHtml(fixture, 'advanced', null);
ok(advanced.includes('帶量突破 20 日高') && advanced.includes('不顯示比例'), 'advanced shows invalidated event and n<20 gate text');
ok(advanced.includes('報酬中位數'), 'advanced shows median and adverse move');

const pro = H.cardHtml(fixture, 'pro', null);
ok(pro.includes('SMA5 / 20 / 60') && pro.includes('方法：'), 'pro shows indicators and stats method');
ok(pro.includes('專業檢視：事件、分布與證據') && pro.includes('原始證據表') && !advanced.includes('原始證據表'), '專業模式具有進階模式沒有的證據檢視');
ok(pro.includes('aria-pressed="true"') && pro.includes('觸發前後數值'), '閱讀深度按鈕具有選取語意且表格可捲動');
fixture.events[0].stats.horizons[0].distribution = { p10: -.03, p50: -.004, p90: .06, worst: -.08 };
ok(H.cardHtml(fixture, 'pro').includes('第 10／50／90 百分位'), '專業模式呈現後端分布');
fixture.events[0].stats.horizons[0].gate = 'insufficient';
ok(!H.cardHtml(fixture, 'pro').includes('第 10／50／90 百分位'), '不足樣本即使有數值也不得顯示分布');
fixture.events[0].stats.horizons[0].gate = 'ok';

for (const html of [beginner, advanced, pro]) {
  ok(!/買進|賣出|保證獲利/.test(html), 'no buy/sell directives in rendered card');
}

const failed = H.cardHtml({ ok: false, symbol: '1234', message: '日線不足 70 根' }, 'beginner', null);
ok(failed.includes('日線不足 70 根'), 'fail-closed message surfaces');

const board = H.boardHtml({ items: [
  { ok: true, symbol: '2330', market: 'TW', close: 1000, chgPct: 1.2, lights: fixture.health.lights,
    summary: fixture.health.summary, events: [{ label: 'RSI 過熱回落', direction: 'bear', barsAgo: 0, provisional: true }] },
  { ok: false, symbol: '1234', market: 'TW', message: '尚無資料' }] });
ok(board.includes('data-code="2330"') && board.includes('RSI 過熱回落（暫定）'), 'board lists today events with provisional flag');
ok(board.includes('尚無資料'), 'board keeps failed rows visible');

const noiseEv = { stats: { minSample: 20, horizons: [{ horizon: 5, n: 60, gate: 'ok', upRatio: 0.55, baseUpRatio: 0.52,
  ci95Pts: 12.6, edgePts: 3, edgeVerdict: 'noise' }] } };
ok(/誤差範圍內/.test(H.statsLine(noiseEv, 'beginner')) && /±12.6/.test(H.statsLine(noiseEv, 'beginner')),
  'stats line tells beginners when the edge is within noise');
ok(/尚未計算/.test(H.scoreboardHtml({ available: false })), 'scoreboard explains missing pooled stats');
const sb = H.scoreboardHtml({ available: true, symbols: 1800, minSample: 100, minSymbols: 5, window: { from: '2021-01-04', to: '2026-09-25' },
  generatedAt: '2026-09-25T15:00:00+08:00', method: '逐檔同規則', caveats: ['存活者偏差'],
  scoreboard: [{ label: '帶量突破 20 日高', familyLabel: '量價', directionLabel: '偏多', horizons: [
    { horizon: 5, n: 4200, symbols: 900, gate: 'ok', upRatio: 0.58, baseUpRatio: 0.51, ci95Pts: 1.5, edgePts: 7, edgeVerdict: 'above',
      stability: { olderUpRatio: 0.6, recentUpRatio: 0.56 } },
    { horizon: 20, n: 4100, gate: 'insufficient' }] }] });
ok(sb.includes('高於基準') && sb.includes('60% → 56%') && sb.includes('存活者偏差'), 'scoreboard shows verdict, stability and caveats');

const described = { stats: { minSample: 20, horizons: [{ horizon: 5, n: 60, gate: 'ok', upRatio: 0.9,
  baseUpRatio: 0.5, ci95Pts: 8.2, edgePts: 40, edgeVerdict: 'descriptive' }] } };
ok(H.statsLine(described, 'beginner').includes('尚未驗證優勢'), '描述差距不冒稱統計優勢');
const researched = H.scoreboardHtml({ available: true, symbols: 20, scoreboard: [{
  label: '測試訊號', familyLabel: '量價', directionLabel: '偏多', horizons: [{ horizon: 5, n: 100, gate: 'ok',
    upRatio: .6, baseUpRatio: .5, edgePts: 10, edgeVerdict: 'descriptive' }],
  research: { horizons: [{ horizon: 5, all: { n: 100, quarters: 10, meanDeltaRet: .9, blockMeanDeltaRet: .01, deltaRetCI95: [-.01, .02] } }] }
}], research: { selection: { reason: '沒有候選 <script>' } } });
ok(researched.includes('100 次／10 季') && researched.includes('季度差距區間'), '研究顯示有效時間區塊及差距區間');
ok(researched.includes('季度等權差距 1.00%') && !researched.includes('90.00%'), '區間與平均使用相同季度權重');
ok(researched.includes('沒有候選 &lt;script&gt;') && researched.includes('未校正多重比較'), '空候選與探索限制保持可見並跳脫文字');

H.setMode('pro');
ok(H.getMode() === 'pro', 'mode persists');

const maint = H.maintenanceHtml({ schedule: { enabled: false }, observations: { enabled: true,
  lastRun: { priceInputs: 3, chipChannelsComplete: 4, chipChannelsExpected: 6, missingPriceSymbols: ['2317'], missingChipInputs: [] } } });
ok(maint.includes('持續授權盤後自動更新') && !maint.includes('id="sh5-schedule-enable" checked'), '每日外部更新預設未勾選');
ok(maint.includes('首次價量輸入 3') && maint.includes('4／6') && maint.includes('2317'), '價量與籌碼缺漏分開呈現');
ok(H.maintenanceHtml({ schedule: { enabled: true } }).includes('id="sh5-schedule-enable" checked'), '已授權的排程狀態可核對並停用');
const partialView = H.sensitivityHtml({ status: 'available', coveredSymbols: 1054, totalSymbols: 1083, signals: [],
  partial: { status: 'available', coveredSymbols: 26, totalSymbols: 26, windowCount: 38, coveredBars: 27000, signals: [] } });
ok(partialView.includes('完整覆蓋 1054／1083') && partialView.includes('部分歷史區段：38 段、27000 根日線（26／26'), '部分歷史與完整股票覆蓋分開呈現');

const reportView = H.evidenceReportHtml({ total: 21, nextBefore: 2, lastCheckedAt: '2026-09-29T20:40:00+08:00', latest: {
  execution: 'completed', sessionDate: '2026-09-29', metrics: { researchThrough: '2026-09-29' },
  constraints: [{ label: '研究優勢', state: 'unproven', summary: 'no_candidate <script>', next: '繼續觀察' }],
  checks: [{ label: '來源', state: 'waiting', detail: '<img src=x>' }],
  observations: { horizons: [{ horizon: 5, mature: 1, waiting: 4, due: 2 }] }
}, history: [{ sessionDate: '2026-09-29', checkedAt: '20:40', execution: 'completed', changes: [{ label: '事件數', before: 1, after: 3 }] }] });
ok(reportView.includes('尚未驗證優勢') && reportView.includes('no_candidate &lt;script&gt;'), '檢查完成不等於投資證據達標，來源文字跳脫');
ok(reportView.includes('待時間累積 4') && reportView.includes('仍待結算 2'), '未到期與到期未結算分開呈現');
ok(reportView.includes('data-before="2"') && reportView.includes('1 → 3') && reportView.includes('&lt;img src=x&gt;'), '完整歷史分頁、變化與跳脫文字可見');
ok(H.evidenceReportHtml({}).includes('尚無驗證報告'), '沒有報告不冒稱完成');
ok(H.evidenceReportHtml({ latest: { execution: 'failed' } }).includes('最近檢查失敗'), '程序失敗明確保留');
ok(H.evidenceReportHtml({ history: [{ execution: 'failed', checks: [{ detail: '舊報告特定失敗原因 <script>' }] }] })
  .includes('舊報告特定失敗原因 &lt;script&gt;'), '新報告完成後仍可回查舊失敗的完整原因');
console.log('\nstock_health_v5_selftest PASSED');

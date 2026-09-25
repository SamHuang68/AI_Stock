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

H.setMode('pro');
ok(H.getMode() === 'pro', 'mode persists');

console.log('\nstock_health_v5_selftest PASSED');

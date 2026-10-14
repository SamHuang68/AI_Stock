'use strict';
/**
 * 大盤(^TWII/^TWOII)日漲跌基準：頂部標頭必須與底部總體列（同一個 /twindex 官方昨收）一致。
 * 重現：主圖已是今天，Yahoo chartPreviousClose 卻是錯的昨收 → 標頭 -676.17 (-1.37%)，
 * 底部 +285 (+0.59%)。此測試執行 polish_v3.js 與 stock_terminal.html 內的正式程式碼，
 * 只提供瀏覽器環境（window、S、fetch、DOM 節點、圖表序列），不改寫被測邏輯。
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const polish = fs.readFileSync(path.join(root, 'src/ui/polish_v3.js'), 'utf8').replace(/\r\n/g, '\n');
const terminal = fs.readFileSync(path.join(root, 'stock_terminal.html'), 'utf8').replace(/\r\n/g, '\n');

function slice(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert(start >= 0, '找不到 ' + startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert(end > start, '找不到 ' + endMarker);
  return source.slice(start, end);
}

const headerCode = slice(terminal, '/** 漲跌字串：', 'async function fetchYF');
const marksCode = slice(polish, '// 昨收虛線 + 右軸讀數', '\nfunction renderChartLegend');
const patchCode = slice(polish, '(function patchTwIndexHeader()', '// ============================================================\n// 大盤融資維持率');

// 2026-10-14 09:30 台北 = 2026-10-14 01:30 UTC；前一交易日 2026-10-13。
const SEC_1014 = Date.UTC(2026, 9, 14, 1, 30) / 1000;
const SEC_1013 = Date.UTC(2026, 9, 13, 1, 30) / 1000;

function makeEnv({ sym = '^TWII', lastTime = SEC_1014, lastClose = 48625.83, hero = 48625.83,
                   yesterdayClose = 49302.0, twindex, tab = 'chart' }) {
  const nodes = {};
  const node = id => (nodes[id] = nodes[id] || { id, textContent: '', innerHTML: '', style: {}, classList: { add() {}, remove() {} } });
  ['ci-price', 'ci-chg', 'ci-range-chg'].forEach(node);
  const lines = [], removed = [], calls = { rpanel: 0 };
  const listeners = {};
  const S = {
    sym, mkt: 'TW', tab, range: '1d',
    data: { candles: [{ time: lastTime - 300, close: lastClose - 5 }, { time: lastTime, close: lastClose }],
            heroPrice: hero, yesterdayClose, rangeBase: null, rangeChgLbl: '' },
    chartSeries: {
      createPriceLine(options) { const line = { options }; lines.push(line); return line; },
      removePriceLine(line) { removed.push(line); },
    },
  };
  const context = {
    S, console: { log() {}, warn() {}, error() {} }, Date, Number, Math, isFinite, Map,
    SERVER_P: 'http://127.0.0.1:18432',
    LightweightCharts: { LineStyle: { Dashed: 2 } },
    document: { getElementById: id => (id === 'chart-wrap' ? null : node(id)) },
    renderRpanel() { calls.rpanel++; },
    fetch: async () => ({ ok: true, json: async () => twindex }),
  };
  context.window = {
    addEventListener(name, handler) { (listeners[name] = listeners[name] || []).push(handler); },
  };
  vm.createContext(context);
  vm.runInContext(headerCode, context);   // fmtChgAbsPct / calcChgFromBase / updateHeaderChg（正式程式碼）
  vm.runInContext(marksCode, context);    // applyPrevCloseMarks / renderCloseReadout（正式程式碼）
  vm.runInContext(patchCode, context);    // patchTwIndexHeader
  return {
    S, nodes, lines, removed, calls,
    async symLoaded() { for (const handler of listeners.symLoaded || []) await handler(); },
  };
}

const official = (extra) => ({ ok: true, indices: { t00: Object.assign({
  price: 48625.83, prevClose: 48340.83, tradeDate: '2026-10-14', source: 'twse-mis' }, extra) } });

(async () => {
  // 1) 重現畫面：Yahoo 昨收 49302.00 → 應改用官方昨收 48340.83，標頭 +285.00 (+0.59%)
  {
    const env = makeEnv({ twindex: official() });
    await env.symLoaded();
    assert.strictEqual(env.S.data.yesterdayClose, 48340.83);
    assert.strictEqual(env.nodes['ci-chg'].innerHTML.replace(/ <span.*$/, ''), '+285.00 (+0.59%)');
    assert.strictEqual(env.lines.length, 1, '昨收虛線須以官方昨收重畫');
    assert.strictEqual(env.lines[0].options.price, 48340.83);
    assert.strictEqual(env.nodes['ci-price'].textContent, '', '主圖已是今天時不覆寫現價');
    assert.strictEqual(env.calls.rpanel, 0, '非統計分頁不重繪右側面板');
  }

  // 2) 統計分頁開著時，CHANGE 列要跟著重繪
  {
    const env = makeEnv({ twindex: official(), tab: 'stats' });
    await env.symLoaded();
    assert.strictEqual(env.calls.rpanel, 1);
  }

  // 3) 昨收已與官方一致 → 不介入（不重畫、不動標頭）
  {
    const env = makeEnv({ twindex: official(), yesterdayClose: 48340.83 });
    await env.symLoaded();
    assert.strictEqual(env.lines.length, 0);
    assert.strictEqual(env.nodes['ci-chg'].innerHTML, '');
  }

  // 4) 浮點誤差不算不一致
  {
    const env = makeEnv({ twindex: official(), yesterdayClose: 48340.83000000001 });
    await env.symLoaded();
    assert.strictEqual(env.lines.length, 0);
  }

  // 5) 主圖最新一根仍是上一交易日（且收盤不等於官方昨收）→ 不換基準，避免標頭與主圖錯位
  {
    const env = makeEnv({ twindex: official(), lastTime: SEC_1013, lastClose: 48100, hero: 48100, yesterdayClose: 47900 });
    await env.symLoaded();
    assert.strictEqual(env.S.data.yesterdayClose, 47900);
    assert.strictEqual(env.lines.length, 0);
  }

  // 6) 伺服器沒有 tradeDate（舊回應）→ 非落後時不換基準
  {
    const env = makeEnv({ twindex: official({ tradeDate: undefined }) });
    await env.symLoaded();
    assert.strictEqual(env.S.data.yesterdayClose, 49302.0);
  }

  // 7) 早盤 Yahoo 落後一日（最後一根收盤≈官方昨收）→ 沿用原行為：現價與基準整組改官方
  {
    const env = makeEnv({ lastTime: SEC_1013, lastClose: 48340.83, hero: 48340.83, yesterdayClose: 48000,
                          twindex: official({ price: 48400.5 }) });
    await env.symLoaded();
    assert.strictEqual(env.nodes['ci-price'].textContent, '48400.50');
    assert.strictEqual(env.S.data.yesterdayClose, 48340.83);
    assert.strictEqual(env.nodes['ci-chg'].innerHTML.replace(/ <span.*$/, ''), '+59.67 (+0.12%)');
  }

  // 8) /twindex 無成交價（盤前／休市）或昨收缺 → 保留 Yahoo 值
  for (const bad of [official({ price: null }), official({ prevClose: null }), { ok: false }]) {
    const env = makeEnv({ twindex: bad });
    await env.symLoaded();
    assert.strictEqual(env.S.data.yesterdayClose, 49302.0);
    assert.strictEqual(env.lines.length, 0);
  }

  // 9) 非大盤指數 → 不介入
  {
    const env = makeEnv({ sym: '2330', twindex: official() });
    await env.symLoaded();
    assert.strictEqual(env.S.data.yesterdayClose, 49302.0);
  }

  // 10) 櫃買 ^TWOII 對應 o00
  {
    const env = makeEnv({ sym: '^TWOII', lastClose: 420.5, hero: 420.5, yesterdayClose: 430,
                          twindex: { ok: true, indices: { o00: { price: 420.5, prevClose: 415.5, tradeDate: '2026-10-14' } } } });
    await env.symLoaded();
    assert.strictEqual(env.S.data.yesterdayClose, 415.5);
  }

  // 11) 取不到 /twindex（斷線）→ 不拋錯、保留 Yahoo 值
  {
    const env = makeEnv({ twindex: null });
    await env.symLoaded();
    assert.strictEqual(env.S.data.yesterdayClose, 49302.0);
  }

  console.log('tw_index_day_change_selftest: ok');
})().catch(error => { console.error(error); process.exit(1); });

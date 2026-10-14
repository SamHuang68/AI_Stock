'use strict';
/**
 * 右軸「今／昨」收盤標籤：價位接近時不得互相蓋住。
 * 重現：2026-10-14 大盤今收 48625.83、官方昨收 48341.31 只差 0.59%，兩個標籤各貼自己的價位高度，
 * 實機量到垂直重疊 8～9px（桌機、844×390、390×844 皆然）。
 * 此測試執行 polish_v3.js 內的正式程式碼，只提供瀏覽器環境（DOM 節點、座標換算、圖表序列）。
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const polish = fs.readFileSync(path.join(root, 'src/ui/polish_v3.js'), 'utf8').replace(/\r\n/g, '\n');
const start = polish.indexOf('// 昨收虛線 + 右軸讀數');
const end = polish.indexOf('\nfunction renderChartLegend', start);
assert(start >= 0 && end > start, '找不到昨收虛線與右軸讀數的程式區段');
const marksCode = polish.slice(start, end);

// 實機量測：今收標籤高 17px、昨收標籤高 13px；48625.83 與 48341.31 相差 285 點約 9px。
const NOW_H = 17;
const PREV_H = 13;
const PX_PER_POINT = 9 / 284.52;

function makeEnv({ close = 48625.83, prevClose = 48341.31, wrapHeight = 600, topOfNow = 330 } = {}) {
  const appended = [];
  const lines = [];
  const wrap = {
    clientHeight: wrapHeight,
    appendChild(el) { appended.push(el); },
  };
  const byId = {};
  const context = {
    S: {
      sym: '^TWII', mkt: 'TW',
      chartSeries: {
        priceToCoordinate: price => topOfNow + (close - price) * PX_PER_POINT,
        createPriceLine(options) { const line = { options }; lines.push(line); return line; },
        removePriceLine() {},
      },
    },
    LightweightCharts: { LineStyle: { Dashed: 2 } },
    window: {},
    _isRedUpSym: () => true,
    document: {
      getElementById: id => (id === 'chart-wrap' ? wrap : byId[id] || null),
      createElement: () => ({
        id: '', textContent: '', style: { cssText: '', top: '' },
        get offsetHeight() { return this.textContent.startsWith('今') ? NOW_H : PREV_H; },
        remove() {},
      }),
    },
  };
  vm.createContext(context);
  vm.runInContext(marksCode, context);
  return {
    render(c, p) { context.renderCloseReadout(c, p); },
    mark(p, c) { context.applyPrevCloseMarks(p, c); },
    lines,
    tags() {
      const out = {};
      appended.forEach(el => {
        const m = /top:([-0-9.]+)px/.exec(el.style.cssText);
        const top = el.style.top !== '' ? parseFloat(el.style.top) : parseFloat(m[1]);
        out[el.id] = { text: el.textContent, y: top, h: el.id === 'ctag-now' ? NOW_H : PREV_H };
      });
      return out;
    },
  };
}

const gap = (a, b) => {
  const [upper, lower] = a.y <= b.y ? [a, b] : [b, a];
  return (lower.y - lower.h / 2) - (upper.y + upper.h / 2);
};

// 1) 重現畫面：今收在上、昨收在下且只差 9px → 讓開後不重疊，上方標籤不動、下方標籤下移。
{
  const env = makeEnv();
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, 330, '上方標籤維持自己的價位高度');
  assert(t['ctag-prev'].y > 330 + 9, '下方標籤須下移');
  assert(gap(t['ctag-now'], t['ctag-prev']) >= 0, '兩個標籤不得垂直重疊：' + JSON.stringify(t));
  assert.strictEqual(t['ctag-now'].text, '今48625.83');
  assert.strictEqual(t['ctag-prev'].text, '昨48341.31', '標籤文字仍是精確價位');
}

// 2) 昨收虛線不受影響：仍只有一條，價位是精確的昨收。
{
  const env = makeEnv();
  env.mark(48341.31, 48625.83);
  assert.strictEqual(env.lines.length, 1);
  assert.strictEqual(env.lines[0].options.price, 48341.31);
}

// 3) 今收低於昨收（畫面上今收在下）→ 今收標籤讓開，昨收標籤不動。
{
  const env = makeEnv({ close: 48000, prevClose: 48100, topOfNow: 400 });
  env.render(48000, 48100);
  const t = env.tags();
  assert.strictEqual(t['ctag-prev'].y, 400 + (48000 - 48100) * PX_PER_POINT, '上方（昨收）標籤不動');
  assert(gap(t['ctag-now'], t['ctag-prev']) >= 0, '兩個標籤不得垂直重疊：' + JSON.stringify(t));
}

// 4) 兩個價位本來就離得夠遠（舊的 Yahoo 昨收 49302）→ 完全不移動。
{
  const env = makeEnv({ prevClose: 49302 });
  env.render(48625.83, 49302);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, 330);
  assert.strictEqual(t['ctag-prev'].y, 330 + (48625.83 - 49302) * PX_PER_POINT);
}

// 5) 昨收標籤原本完全在圖內，被讓開後才超出圖高 → 整組上移，仍不重疊且在圖內。
{
  const env = makeEnv({ wrapHeight: 350 });   // 昨收原本下緣 339 + 6.5 = 345.5 ≤ 350；讓開後下緣 353.5 > 350
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert(gap(t['ctag-now'], t['ctag-prev']) >= 0, JSON.stringify(t));
  assert(t['ctag-prev'].y + t['ctag-prev'].h / 2 <= 350 + 1e-9, '下方標籤不得超出圖高');
  assert(t['ctag-now'].y < 330, '被讓開而超出圖高時，整組才上移');
}

// 6) 沒有昨收 → 只有今收標籤，不報錯、不移動。
{
  const env = makeEnv();
  env.render(48625.83, null);
  const t = env.tags();
  assert.deepStrictEqual(Object.keys(t), ['ctag-now']);
  assert.strictEqual(t['ctag-now'].y, 330);
}

// 7) 昨收跳空到畫面外（例如隔夜大幅跳空或漲跌停）：priceToCoordinate 仍回傳畫面外的座標。
//    畫面內的今收標籤不得被拖離自己的價位，畫面外的昨收標籤也不動。
{
  const env = makeEnv({ wrapHeight: 600, prevClose: 40000 });   // 昨收約在 y = 330 + 8625.83 * PX_PER_POINT ≈ 598 之下
  const farBelow = 330 + (48625.83 - 30000) * PX_PER_POINT;      // 保證在畫面外
  const env2 = makeEnv({ wrapHeight: 600, prevClose: 30000 });
  env2.render(48625.83, 30000);
  const t = env2.tags();
  assert(farBelow > 600, '測試前提：昨收在畫面外');
  assert.strictEqual(t['ctag-now'].y, 330, '畫面內的今收標籤不得被拖離自己的價位');
  assert.strictEqual(t['ctag-prev'].y, farBelow, '畫面外的昨收標籤維持原座標');
  env.render(48625.83, 40000);   // 畫面內且距離夠遠：同樣不移動
  assert.strictEqual(env.tags()['ctag-now'].y, 330);
}

// 8) 今收跳空到畫面上方之外、昨收在畫面內：昨收標籤不得被推到別處。
{
  const env = makeEnv({ wrapHeight: 600, topOfNow: -50 });       // 今收在畫面上方之外
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, -50);
  assert.strictEqual(t['ctag-prev'].y, -50 + (48625.83 - 48341.31) * PX_PER_POINT, '畫面外的標籤不參與避讓');
}

console.log('axis_tag_collision_selftest: ok');

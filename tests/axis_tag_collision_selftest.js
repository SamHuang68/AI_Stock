'use strict';
/**
 * 右軸「今／昨」收盤標籤：價位接近時不得互相蓋住，且不得因此改變其他資訊。
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
const FALLBACK_H = 14;   // 讀不到 offsetHeight 時程式採用的估計值
const PX_PER_POINT = 9 / 284.52;

// ys：直接指定兩個標籤的座標（{now, prev}，可為 NaN／null）；未指定時依價差線性換算。
// heightMode：'normal'（17／13）、'zero'（offsetHeight 為 0）、'missing'（offsetHeight 為 undefined）。
// paneHeight：提供時以 S.chart.paneSize() 回傳（價格窗格高度），否則程式退回 wrapHeight。
function makeEnv({ close = 48625.83, prevClose = 48341.31, wrapHeight = 600, topOfNow = 330,
                   ys = null, heightMode = 'normal', paneHeight = null } = {}) {
  const appended = [];
  const lines = [];
  const wrap = {
    clientHeight: wrapHeight,
    appendChild(el) { appended.push(el); },
  };
  const S = {
    sym: '^TWII', mkt: 'TW',
    chartSeries: {
      priceToCoordinate: price => {
        if (ys) return price === close ? ys.now : ys.prev;
        return topOfNow + (close - price) * PX_PER_POINT;
      },
      createPriceLine(options) { const line = { options }; lines.push(line); return line; },
      removePriceLine() {},
    },
  };
  if (paneHeight !== null) S.chart = { paneSize: () => ({ height: paneHeight, width: 388 }) };
  const context = {
    S,
    LightweightCharts: { LineStyle: { Dashed: 2 } },
    window: {},
    _isRedUpSym: () => true,
    document: {
      getElementById: id => (id === 'chart-wrap' ? wrap : null),
      createElement: () => ({
        id: '', textContent: '', style: { cssText: '', top: '' },
        get offsetHeight() {
          if (heightMode === 'zero') return 0;
          if (heightMode === 'missing') return undefined;
          return this.textContent.startsWith('今') ? NOW_H : PREV_H;
        },
        remove() {},
      }),
    },
  };
  vm.createContext(context);
  vm.runInContext(marksCode, context);
  const h = id => (heightMode === 'normal' ? (id === 'ctag-now' ? NOW_H : PREV_H) : FALLBACK_H);
  return {
    render(c, p) { context.renderCloseReadout(c, p); },
    mark(p, c) { context.applyPrevCloseMarks(p, c); },
    lines,
    tags() {
      const out = {};
      appended.forEach(el => {
        const m = /top:([^;]+);/.exec(el.style.cssText);
        const top = el.style.top !== '' ? parseFloat(el.style.top) : parseFloat(m[1]);
        out[el.id] = { text: el.textContent, y: top, h: h(el.id), rawTop: el.style.top !== '' ? el.style.top : m[1] };
      });
      return out;
    },
  };
}

const gap = (a, b) => {
  const [upper, lower] = a.y <= b.y ? [a, b] : [b, a];
  return (lower.y - lower.h / 2) - (upper.y + upper.h / 2);
};
const noNaN = t => Object.values(t).forEach(x => assert(Number.isFinite(x.y) && !/NaN/.test(x.rawTop), 'top 不得是 NaN：' + JSON.stringify(x)));

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

// 7) 昨收跳空到畫面外（隔夜大幅跳空、漲跌停）：priceToCoordinate 仍回傳畫面外的座標。
//    畫面內的今收標籤不得被拖離自己的價位，畫面外的昨收標籤也不動。
{
  const env = makeEnv({ wrapHeight: 600, ys: { now: 330, prev: 900 } });
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, 330, '畫面內的今收標籤不得被拖離自己的價位');
  assert.strictEqual(t['ctag-prev'].y, 900, '畫面外的昨收標籤維持原座標');
}

// 8) 昨收的價位壓在圖底邊（身體一半在圖內）：本來就貼邊，不得把今收標籤拉走。
{
  const env = makeEnv({ wrapHeight: 600, ys: { now: 330, prev: 602.9 } });
  env.render(48625.83, 48341.31);
  assert.strictEqual(env.tags()['ctag-now'].y, 330);
}

// 9) 今收在畫面上方之外、昨收在畫面內：昨收標籤不得被推到別處。
{
  const env = makeEnv({ wrapHeight: 600, ys: { now: -50, prev: -41 } });
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, -50);
  assert.strictEqual(t['ctag-prev'].y, -41, '兩個標籤都在畫面外：不參與避讓');
  env.render(48625.83, 48341.31);
}

// 10) 兩個價位完全相同（今收等於昨收）→ 仍須分開，且不得把今收標籤移離價位。
{
  const env = makeEnv({ ys: { now: 300, prev: 300 } });
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, 300);
  assert(gap(t['ctag-now'], t['ctag-prev']) >= 2 - 1e-9, '相同價位也要分開：' + JSON.stringify(t));
}

// 11) 讀不到標籤高度（offsetHeight 為 0 或 undefined）→ 以 14px 估計，不報錯、位置合理。
for (const heightMode of ['zero', 'missing']) {
  const env = makeEnv({ heightMode, ys: { now: 330, prev: 339 } });
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, 330, heightMode);
  assert.strictEqual(t['ctag-prev'].y, 330 + FALLBACK_H / 2 + FALLBACK_H / 2 + 2, heightMode + '：以 14px 估計');
  noNaN(t);
}

// 12) 圖高未知（clientHeight 為 0）→ 不做超出圖高的判斷，仍分開，不報錯。
{
  const env = makeEnv({ wrapHeight: 0 });
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, 330);
  assert(gap(t['ctag-now'], t['ctag-prev']) >= 0);
  noNaN(t);
}

// 13) priceToCoordinate 回傳 NaN／null／undefined → 不畫該標籤，另一個標籤不受影響，top 不得是 NaN。
for (const bad of [NaN, null, undefined]) {
  const env = makeEnv({ ys: { now: 330, prev: bad } });
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.deepStrictEqual(Object.keys(t), ['ctag-now'], String(bad));
  assert.strictEqual(t['ctag-now'].y, 330, String(bad));
  noNaN(t);
}

// 14) 避讓的下限用價格窗格高度（S.chart.paneSize），而不是含時間軸的容器高度。
//     容器 444、窗格 436：昨收原本下緣 440.5 已壓在窗格底邊之外，只抵銷被讓開而推出去的那一段。
{
  const ys = { now: 425, prev: 434 };
  const withPane = makeEnv({ wrapHeight: 444, paneHeight: 436, ys });
  withPane.render(48625.83, 48341.31);
  const wrapOnly = makeEnv({ wrapHeight: 444, ys });
  wrapOnly.render(48625.83, 48341.31);
  const a = withPane.tags(), b = wrapOnly.tags();
  assert(gap(a['ctag-now'], a['ctag-prev']) >= 0 && gap(b['ctag-now'], b['ctag-prev']) >= 0);
  assert(a['ctag-now'].y < b['ctag-now'].y, '以窗格高度 436 為限時上移得比用容器高度 444 更多：' + a['ctag-now'].y + ' vs ' + b['ctag-now'].y);
}

// 15) 圖極矮、兩個標籤都放不下 → 上移不得把最上面的標籤推出圖頂，也不得出現 NaN。
{
  const env = makeEnv({ wrapHeight: 20, ys: { now: 5, prev: 8 } });
  env.render(48625.83, 48341.31);
  const t = env.tags();
  assert.strictEqual(t['ctag-now'].y, 5, '上方標籤不得因上移而離開自己的價位');
  assert(gap(t['ctag-now'], t['ctag-prev']) >= 0);
  noNaN(t);
}

console.log('axis_tag_collision_selftest: ok');

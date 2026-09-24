/**
 * beginner_signals_selftest.js — 新手短訊號只用既有 payload，不重算 RSI／SMA。
 * Run: node tests/beginner_signals_selftest.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');

function sliceFn(name, nextName) {
  const start = src.indexOf('function ' + name + '(');
  const end = src.indexOf('function ' + nextName + '(');
  if (start < 0 || end < 0 || end <= start) {
    throw new Error('無法切出 ' + name + ' → ' + nextName);
  }
  return src.slice(start, end);
}

const code = [
  sliceFn('esc', 'goRoute'),
  sliceFn('pct', 'fmt'),
  sliceFn('fmt', 'chgPts'),
  sliceFn('radarNumber', 'radarClamp'),
  sliceFn('todaySignalChip', 'beginnerChip'),
  sliceFn('moverRows', 'renderMovers'),
  'module.exports = { renderBeginnerSignalStrip: renderBeginnerSignalStrip, moverRows: moverRows };'
].join('\n');

const sandbox = { module: { exports: {} }, Number: Number, String: String, isFinite: isFinite };
vm.createContext(sandbox);
vm.runInContext(code, sandbox, { filename: 'beginner-signals-extract.js' });
const api = sandbox.module.exports;

let failed = 0;
function ok(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); failed++; }
  else console.log('OK  ', msg);
}

const pack = {
  overview: {
    strip: {
      limitUp: 12,
      limitDown: 3,
      t00Trend: { ma5: 23456.78, vsMa5Pct: 1.25, momScore: 62.4, level: '偏強', trend: '溫和上行', n: 20 }
    }
  },
  pulse: {
    riskScore: 41.2,
    riskLabel: '風險偏低',
    riskFactors: [{ name: '借券賣出壓力' }],
    positiveFactors: [{ name: '廣度偏多' }],
    aiSpill: { ok: true, direction: 'pos', soxChangePct: 1.8, ixicChangePct: 0.6, vixLevel: 16.4, factorName: 'AI科技外溢偏多' },
    snapshot: {
      topSector: { name: '半導體', changePct: 2.4 },
      bottomSector: { name: '觀光餐旅', changePct: -1.1 }
    },
    extras: { nhnl: { newHighs: 8, newLows: 2, sampleN: 120 } },
    decisionSummary: {
      earlyWarnings: { signals: [{ label: '上行前兆證據', state: 'WATCH', strength: 48 }] },
      invalidation: ['廣度跌破四成']
    },
    movers: {
      limitUp: [
        { code: '2330', name: '台積電', changePct: 9.9 },
        { code: '2454', name: '聯發科', changePct: 10 },
        { code: '2308', name: '台達電', changePct: 9.95 }
      ],
      limitDown: [{ code: '2882', name: '國泰金', changePct: -9.5 }]
    },
    us10y: { value: 4.21, date: '2026-09-23' },
    pillars: { marginRatio: 168.42, medianPE: 18.4, riskZone: '中性' },
    focusHint: {
      ok: true,
      buy: { sym: '2330', name: '台積電', changePct: 1.2, rsi14: 62.1, signals: ['多頭排列', 'RSI轉強'] },
      short: { sym: '2317', name: '鴻海', changePct: -0.8, rsi14: 71.4, signals: ['空頭排列'] }
    }
  }
};

const html = api.renderBeginnerSignalStrip(pack.overview, pack.pulse);
ok(html.includes('今日短訊號') && html.includes('class="pl-today-chip"'), '今日短訊號列在新手面板內');
ok(html.includes('五日均') && html.includes('偏強') && html.includes('23,456.78') && html.includes('+1.25%'),
  '五日均顯示後端 ma5 與 vsMa5Pct');
ok(html.includes('風險偏低') && html.includes('41.2') && html.includes('借券賣出壓力'),
  '風險分與因子名稱沿用 pulse');
ok(html.includes('AI科技外溢偏多') && html.includes('費半 +1.80%') && html.includes('VIX 16.4'),
  '科技外溢沿用 aiSpill，不另算方向');
ok(html.includes('漲 12 · 跌 3') && html.includes('半導體') && html.includes('觀光餐旅'),
  '官方漲跌停與產業極值沿用既有欄位');
ok(html.includes('高 8 · 低 2') && html.includes('樣本 120'),
  '新高新低沿用 extras.nhnl');
ok(html.includes('留意') && html.includes('上行前兆證據') && html.includes('廣度跌破四成'),
  '預警與失效條件沿用 decisionSummary');
ok(html.includes('漲 3 · 跌 1') && html.includes('2330') && html.includes('2882'),
  '漲跌榜家數用完整 movers 清單，名稱只取前兩檔');
ok(html.includes('4.21%') && html.includes('168.42%') && html.includes('18.4 倍'),
  '美債、融資維持率與本益比中位沿用後端數值');
ok(html.includes('做多 2330') && html.includes('RSI 62.1') && html.includes('多頭排列') && html.includes('做空 2317'),
  '焦點 RSI 使用快取裡的後端值');
ok(!html.includes('function') && !/\/focus\?/.test(html), '畫面不內嵌公式、也不打新的焦點掃描');

const empty = api.renderBeginnerSignalStrip({ strip: { t00Trend: { n: 0 } } }, {
  aiSpill: { ok: false, reason: 'no_sox_ixic' },
  focusHint: { ok: false, reason: 'cache_miss' },
  movers: { gainers: [{ code: '2330', name: '台積電', changePct: 1.2, ex: 'TWSE' }] }
});
ok(empty.includes('等待均線') && !empty.includes('23,456'), '沒有 ma5 時不估算五日均');
ok(empty.includes('等待外溢') && empty.includes('尚未掃描') && !/RSI \d/.test(empty),
  '外溢或缺快取時不補方向、不顯示 RSI');
ok(empty.includes('尚無極端漲跌'), '未達近漲停門檻的漲幅不混進漲跌榜');

if (failed) {
  console.error('beginner_signals_selftest FAILED', failed);
  process.exit(1);
}
console.log('beginner_signals_selftest PASSED');

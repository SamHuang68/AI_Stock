/**
 * chart_visual_v5_selftest.js — 圖表視覺與市場色彩契約（無瀏覽器）
 * 用法：node tests/chart_visual_v5_selftest.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/ui/chart_visual_v5.js'), 'utf8');
const sandbox = {
  window: {
    Colors: {
      isRedUp(sym) {
        const s = String(sym || '').toUpperCase();
        return /^\d/.test(s) || /^\^TW/.test(s) || s === '__TXF__' || s === '^N225' || /^\d{4}\.T$/.test(s);
      }
    }
  },
  console: { info() {} }
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'chart_visual_v5.js' });

let failed = 0;
function ok(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); failed++; }
  else console.log('OK  ', msg);
}

const chartVisual = sandbox.window.ChartVisualV5;
const tw = chartVisual.themeFor('2330', 'TW');
const us = chartVisual.themeFor('NVDA', 'US');
const jp = chartVisual.themeFor('^N225', 'JP');

ok(chartVisual.version === '5.0.0', 'chart visual contract version');
ok(tw.redUp && tw.candleUp === '#ff6b7a' && tw.candleDown === '#42df91',
  'Taiwan chart uses red-up and green-down');
ok(!us.redUp && us.candleUp === '#42df91' && us.candleDown === '#ff6b7a',
  'US chart uses green-up and red-down');
ok(jp.redUp && jp.candleUp === '#ff6b7a' && jp.candleDown === '#42df91',
  'Japan chart uses red-up and green-down');
ok(tw.volumeUp.includes('255,107,122') && us.volumeUp.includes('66,223,145'),
  'volume direction follows the same market-aware palette');
ok(tw.ma20 === '#f6c84c' && tw.ma60 === '#67d8e8' && /rgba/.test(tw.band),
  'moving-average hierarchy and subdued band are stable');

if (failed) process.exit(1);
console.log('\nchart_visual_v5_selftest PASSED');

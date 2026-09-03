/**
 * wavedeck_onepage_selftest.js — WD 一頁高密度契約（無瀏覽器）
 * 用法：node tests/wavedeck_onepage_selftest.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const css = fs.readFileSync(path.join(root, 'wavedeck/web/css/deck.css'), 'utf8');
const html = fs.readFileSync(path.join(root, 'wavedeck/web/index.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'wavedeck/web/js/deck.js'), 'utf8');
const ver = fs.readFileSync(path.join(root, 'wavedeck/VERSION'), 'utf8').trim();

let failed = 0;
function ok(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); failed++; }
  else console.log('OK  ', msg);
}

ok(/^0\.1\.20/.test(ver), 'VERSION is 0.1.20');
ok(fs.existsSync(path.join(root, 'wavedeck/server/exec_md.py')), 'exec_md module exists');
ok(/btnExecMd/.test(html) && /aiMarketStatus/.test(html) && /執行 MD/.test(html),
  'console has Wave AI–style exec MD button + status/reasoning slots');
ok(/exec_md/.test(fs.readFileSync(path.join(root, 'wavedeck/server/engine.py'), 'utf8')) &&
  /enrich_and_maybe_write/.test(fs.readFileSync(path.join(root, 'wavedeck/server/exec_md.py'), 'utf8')),
  'engine hooks exec_md translation layer');
ok(/waveai-center/.test(html) && /narr-block c2/.test(html) && /narr-block c3/.test(html) &&
  /aiInvalidation/.test(html) && /layer3/.test(html) && /lyAiAction/.test(html) &&
  /bias-bars/.test(html) && /市場狀態/.test(html) && /判斷理由/.test(html),
  'center column is Wave AI C1–C5 narrative layout');
ok(/minmax\(260px, 1fr\) minmax\(420px, 2\.15fr\)/.test(css) ||
  /minmax\(420px, 2\.15fr\)/.test(css),
  'global grid is ~1:2:1 with wide center');
ok(/#111827/.test(css) && /#1f2937/.test(css) && /#374151/.test(css),
  'theme tokens align Wave AI dark panels');
ok(/height:\s*100dvh/.test(css) && /overflow:\s*hidden/.test(css) &&
  /\.app\s*\{[^}]*overflow:\s*hidden/.test(css),
  'deck app locked to one viewport (100dvh, overflow hidden)');
ok(/\.cols\s*\{[^}]*overflow:\s*hidden/.test(css) &&
  /\.col\s*\{[^}]*overflow:\s*hidden/.test(css),
  'deck columns do not page-scroll');
ok(/sys-box/.test(html) && /系統控制/.test(html) && /data-cmd="start"/.test(html) &&
  /sys-btns/.test(css),
  'system control lives in left column like Wave AI');
ok(!/SYSTEM CONTROL/.test(html) && /EMERGENCY/.test(html) && /DECISION/.test(html),
  'footer condensed to decision + emergency (no third system row)');
ok(/lights-box/.test(html) && /pos-grid/.test(html) && /pos-grid/.test(css),
  'dense grids for position / lights / transport');
ok(/Wave AI 參考 · 攻能驗證 · 非實盤/.test(js) && !/資料性質/.test(js),
  'account note compact; no wide 資料性質 row');
ok(/async function refreshSt\(\)[\s\S]*?jget\(ST \+ '\/bridge\/wavedeck'\)/.test(js),
  'ST 狀態燈使用已開放 CORS 的 WaveDeck bridge 探針');
ok(!/async function refreshSt\(\)[\s\S]*?jget\(ST \+ '\/health'\)/.test(js),
  'ST 狀態燈不使用遭跨來源阻擋的 health 端點');
ok(/一頁密度|100dvh|Wave AI/.test(css.split('\n')[0]) || /一頁高密度/.test(css),
  'CSS header documents one-page Wave AI density');

if (failed) {
  console.error('\n' + failed + ' failure(s)');
  process.exit(1);
}
console.log('\nAll wavedeck onepage checks passed.');

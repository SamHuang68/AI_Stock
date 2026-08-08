/**
 * shell_v5_selftest.js — ST 5.0 tip 殼層／品牌／熱鍵契約（無瀏覽器）
 * 用法：node tests/shell_v5_selftest.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const shell = fs.readFileSync(path.join(root, 'src/ui/shell_v5.js'), 'utf8');
const hotkeys = fs.readFileSync(path.join(root, 'src/chart/hotkeys_v3.js'), 'utf8');

let failed = 0;
function ok(cond, msg) {
  if (!cond) { console.error('FAIL:', msg); failed++; }
  else console.log('OK  ', msg);
}

ok(/VERSION = '5\.0'/.test(shell), 'VERSION is 5.0');
ok(/st50-icon\.svg/.test(shell), 'ST icon asset referenced');
ok(fs.existsSync(path.join(root, 'assets/st50-icon.svg')), 'assets/st50-icon.svg exists');
ok(/HOTKEY_ROUTES/.test(shell), 'HOTKEY_ROUTES defined');
ok(/aria-current/.test(shell), 'aria-current on nav');
ok(/deactivateRoute/.test(shell), 'deactivate on leave');
ok(/softBadge/.test(shell), 'softBadge helper');
ok(/data-st50-favicon/.test(shell), 'favicon wired');
ok(/shell-logo-ico/.test(shell), 'topbar logo icon');

['pulse', 'chart', 'breadth', 'heat', 'institutional', 'ai', 'scan', 'book', 'settings'].forEach(function (id) {
  ok(new RegExp("id: '" + id + "'").test(shell), 'route ' + id);
});

ok(/ShellV5\.go\('chart'\)/.test(hotkeys), 'Esc → chart in hotkeys');
ok(/Alt\+Shift\+1/.test(hotkeys), 'Alt+Shift help row');
ok(/ai: 'AiV5'/.test(shell), 'AiV5 in PANEL_MAP');

['breadth_v5.js', 'heat_v5.js', 'afterhours_v5.js', 'news_v5.js', 'pulse_v5.js', 'ai_v5.js'].forEach(function (f) {
  const t = fs.readFileSync(path.join(root, 'src/ui', f), 'utf8');
  ok(/deactivate/.test(t), f + ' has deactivate');
});

const bridge = fs.readFileSync(path.join(root, 'src/ui/bridge_v5.js'), 'utf8');
ok(/portfolioOpen/.test(bridge) && /marketFlowOpen/.test(bridge) && /openAIModal/.test(bridge),
  'bridge_v5 wraps portfolio/marketflow/AI');
const build = fs.readFileSync(path.join(root, 'build_v2.py'), 'utf8');
ok(build.indexOf('src/ui/ai_v5.js') >= 0 && build.indexOf('src/ui/bridge_v5.js') >= 0,
  'ai_v5 + bridge_v5 in build_v2');

const hub = fs.readFileSync(path.join(root, 'src/ui/hub_v5.js'), 'utf8');
ok(/hub-inst-hero/.test(hub), 'institutional hero strip');
ok(/data-who="trust"/.test(hub) && /data-who="dealer"/.test(hub), 'institutional who tabs');
ok(/fmtLots/.test(hub) && /單位：張/.test(hub), 'institutional ranks use 張');
ok(/magBars/.test(hub) && /refMeter/.test(hub), 'institutional magBars + turnover meter');
ok(/minmax\(0,1fr\) minmax\(0,2fr\)/.test(hub), 'institutional chart ~1/3 width');
ok(/lots-bar/.test(hub) && /class="streak"/.test(hub), 'institutional lots bar separated from streak');
ok(/vz-xlabs/.test(fs.readFileSync(path.join(root, 'src/ui/viz_v5.js'), 'utf8')), 'sparkLine X tick labels');
ok(/d\.buy \|\| d\.long/.test(hub) || /focus\.buy/.test(hub) || /d\.buy \|\|/.test(hub),
  'signals use /focus buy field');
ok(/hub-card\[data-code\]/.test(hub) || /data-code="' \+ sym/.test(hub),
  'international cards clickable');
ok(/黃金（避險）/.test(hub) && /銅（景氣循環）/.test(hub) && /g\.role/.test(hub),
  'international shows gold hedge + copper cycle roles');

const ai = fs.readFileSync(path.join(root, 'src/ui/ai_v5.js'), 'utf8');
ok(/ai5-strip/.test(ai) && /ai5-dash/.test(ai), 'ai professional strip+dash');
ok(/focus\.buy/.test(ai) || /buy \|\| focus\.long/.test(ai), 'ai maps focus.buy');
ok(!/ai5-card/.test(ai) || /ai5-tools/.test(ai), 'ai launcher not card-grid only');

const ah = fs.readFileSync(path.join(root, 'src/ui/afterhours_v5.js'), 'utf8');
ok(/自營/.test(ah) && /成交金額/.test(ah), 'afterhours strip has 成交／籌碼含自營');

const bd = fs.readFileSync(path.join(root, 'src/ui/breadth_v5.js'), 'utf8');
ok(/強弱榜/.test(bd), 'breadth movers replace note panel');
ok(/結構條不重複/.test(bd) || /結構只用 magBars/.test(bd), 'breadth avoids inst number+bar dup');
ok(/官方≠清單/.test(bd) || /官方漲停家數/.test(bd), 'breadth limit popup separates official vs approx list');

const pl = fs.readFileSync(path.join(root, 'src/ui/pulse_v5.js'), 'utf8');
ok(/上市漲跌停 · 官方/.test(pl), 'pulse strip labels official limit counts');
ok(/近漲停/.test(pl) && /≠頂列官方家數/.test(pl), 'pulse movers panel not branded as official limit');
ok(/movers\.limitUp/.test(pl), 'pulse prefers movers.limitUp for near-limit list');
ok(/function chgWithPct/.test(pl) && /chgWithPct\(t00/.test(pl) && /chgWithPct\(txf/.test(pl),
  'pulse strip shows change points + pct for TAIEX/OTC/TXF');
ok(/GC=F/.test(pl) && /HG=F/.test(pl) && /x\.role/.test(pl),
  'pulse global prefer includes gold and copper with role');

const nw = fs.readFileSync(path.join(root, 'src/ui/news_v5.js'), 'utf8');
ok(/nw-mkt-seg/.test(nw) && /flashMkt/.test(nw), 'news TW/US filter');

if (failed) {
  console.error('\n' + failed + ' failure(s)');
  process.exit(1);
}
console.log('\nshell_v5_selftest PASSED');

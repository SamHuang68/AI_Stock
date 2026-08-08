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

if (failed) {
  console.error('\n' + failed + ' failure(s)');
  process.exit(1);
}
console.log('\nshell_v5_selftest PASSED');

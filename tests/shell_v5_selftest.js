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

['pulse', 'chart', 'breadth', 'heat', 'institutional', 'scan', 'book', 'settings'].forEach(function (id) {
  ok(new RegExp("id: '" + id + "'").test(shell), 'route ' + id);
});

ok(/ShellV5\.go\('chart'\)/.test(hotkeys), 'Esc → chart in hotkeys');
ok(/Alt\+Shift\+1/.test(hotkeys), 'Alt+Shift help row');

['breadth_v5.js', 'heat_v5.js', 'afterhours_v5.js', 'news_v5.js', 'pulse_v5.js'].forEach(function (f) {
  const t = fs.readFileSync(path.join(root, 'src/ui', f), 'utf8');
  ok(/deactivate/.test(t), f + ' has deactivate');
});

if (failed) {
  console.error('\n' + failed + ' failure(s)');
  process.exit(1);
}
console.log('\nshell_v5_selftest PASSED');

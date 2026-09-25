// 所有打包進 stock_terminal_v2.html 的前端腳本都必須能被解析。
// 一支檔案語法錯誤會讓整個模組在瀏覽器靜默失效（例：合併衝突殘留的孤兒程式碼）。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const build = fs.readFileSync(path.join(root, 'build_v2.py'), 'utf8');
const scripts = new Set();
for (const m of build.matchAll(/'(src\/[^']+\.js)'/g)) {
  const line = build.slice(build.lastIndexOf('\n', m.index) + 1, m.index);
  if (!line.trim().startsWith('#')) scripts.add(m[1]);
}
if (scripts.size < 50) throw new Error('FAIL: expected build_v2.py script list, found ' + scripts.size);
let bad = 0;
for (const rel of [...scripts].sort()) {
  const file = path.join(root, rel);
  if (!fs.existsSync(file)) { console.log('MISSING', rel); bad++; continue; }
  try {
    new vm.Script(fs.readFileSync(file, 'utf8'), { filename: rel });
  } catch (e) {
    console.log('SYNTAX ', rel, '-', e.message);
    bad++;
  }
}
if (bad) throw new Error('FAIL: ' + bad + ' shipped script(s) do not parse');
console.log('OK   ', scripts.size, 'shipped scripts parse');
console.log('\njs_syntax_selftest PASSED');

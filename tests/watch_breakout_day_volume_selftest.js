'use strict';
// 審查 IND-01：前端 WATCH「突破 N 日新高」用當日量／前 20 日均量，與後端 watch_daemon 同口徑。
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/core/watch_v2.js'), 'utf8').replace(/\r\n/g, '\n');
const start = source.indexOf('function rsiWildersSeries');
const end = source.indexOf('// ── Preset combos', start);
if (start < 0 || end < 0) throw new Error('watch_v2 strategy block missing');
const sandbox = { num(v) { if (v == null) return null; const n = Number(v); return isFinite(n) ? n : null; }, console };
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end) + '\nglobalThis.__S = STRATEGIES;', sandbox);
const breakout = sandbox.__S.find(s => s.key === 'breakout_n_high');
function bars(lastVolume) {
  const out = Array.from({ length: 25 }, () => ({ close: 100, high: 101, low: 99, volume: 1000 }));
  out.push({ close: 105, high: 106, low: 100.5, volume: lastVolume });
  return out;
}
function ok(value, message) { if (!value) throw new Error('FAIL: ' + message); console.log('OK  ', message); }
// ind.volRatio 故意給 5 日／20 日口徑的 1.27，不可再決定結果
const tripled = breakout.check({ volRatio: 1.27 }, bars(3000), { days: 20, volMult: 1.5 });
ok(tripled.status === 'trigger' && /3\.0x/.test(tripled.detail), 'single-day 3x volume breakout triggers: ' + tripled.detail);
ok(breakout.check({ volRatio: 2 }, bars(1200), { days: 20, volMult: 1.5 }).status === 'partial', 'normal volume breakout is partial');
const gap = bars(3000); gap[10].volume = null;
ok(breakout.check({}, gap, { days: 20, volMult: 1.5 }).status === 'partial', 'missing prior volume does not trigger');
ok(breakout.paramFields.find(f => f.key === 'volMult').hint === '當日量為前 20 日均量幾倍', 'hint describes the actual formula');
console.log('watch breakout day volume selftest ok');

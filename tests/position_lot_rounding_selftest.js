'use strict';
// 張→股換算不得因浮點誤差少 1 股：執行 position_v2.js 內的正式 lotsToShares。
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'src/core/position_v2.js'), 'utf8').replace(/\r\n/g, '\n');
const start = source.indexOf('/** 張→股');
const end = source.indexOf('function submitPosition()', start);
assert(start >= 0 && end > start, '找不到 lotsToShares');
const context = {};
vm.createContext(context);
vm.runInContext(source.slice(start, end) + '\nthis.lotsToShares = lotsToShares;', context);
const { lotsToShares } = context;

let checked = 0;
for (let tenth = 1; tenth <= 9999; tenth++) {          // 0.1～999.9 張
  assert.strictEqual(lotsToShares((tenth / 10).toString()), String(tenth * 100), `${tenth / 10} 張`);
  checked++;
}
for (let hundredth = 1; hundredth <= 99999; hundredth++) { // 0.01～999.99 張
  assert.strictEqual(lotsToShares((hundredth / 100).toString()), String(hundredth * 10), `${hundredth / 100} 張`);
  checked++;
}
assert.strictEqual(lotsToShares('32.3'), '32300');
assert.strictEqual(lotsToShares('abc'), 'abc');         // 非數字原樣交給 setPosition 拒絕
// 敏感度：舊寫法在同一組輸入會少 1 股。
assert.notStrictEqual(String(parseInt(String(parseFloat('32.3') * 1000), 10)), '32300');
console.log(`張數換算：${checked} 筆全部正確`);

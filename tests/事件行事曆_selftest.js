// 驗證來源失敗、真正空資料、完整列數與官方欄位跳脫。
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const body = {innerHTML: '', querySelectorAll() {return [];}};
let payload = {};
const sandbox = {
  window: {}, document: {getElementById(id) {return id === 'cal-body' ? body : null;}},
  fetch: async () => ({json: async () => payload}),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/alert/calendar_v3.js'), 'utf8'), sandbox);
(async () => {
  payload = {exDividend: [], exDividendSource: {status: 'unavailable'}};
  await sandbox.window.calendarRefresh();
  assert(body.innerHTML.includes('尚不能判定是否有預告'));
  payload.exDividendSource.status = 'ok';
  await sandbox.window.calendarRefresh();
  assert(body.innerHTML.includes('官方上市除權息預告目前為空'));
  payload.exDividend = Array.from({length: 70}, (_, n) => ({code: String(1000 + n), date: '2026-10-01', name: '<測試>', type: '息'}));
  await sandbox.window.calendarRefresh();
  assert.equal((body.innerHTML.match(/data-code=/g) || []).length, 70);
  assert(body.innerHTML.includes('&lt;測試&gt;'));
  assert(body.innerHTML.includes('不含上櫃'));
  console.log('事件行事曆：來源狀態、完整列數及跳脫檢查通過');
})().catch(error => {console.error(error); process.exitCode = 1;});

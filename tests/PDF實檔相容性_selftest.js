'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { fileURLToPath } = require('url');
const { enableModules, loadImporter } = require('./PDF匯入測試工具.cjs');
enableModules(__filename);

async function main() {
  const plans = new Map();
  let tasks = 0, destroyed = 0;
  const importer = loadImporter(async url => {
    const lib = await import(url);
    return { version: lib.version, GlobalWorkerOptions: lib.GlobalWorkerOptions, PDFWorker: lib.PDFWorker, getDocument(options) {
      // Node 使用檔案系統資產；瀏覽器的同源 fetch 與真實 worker 另做瀏覽器驗收。
      const nodeOptions = { ...options };
      for (const key of ['cMapUrl', 'standardFontDataUrl', 'wasmUrl']) nodeOptions[key] = fileURLToPath(options[key]).replace(/\\/g, '/');
      const task = lib.getDocument(nodeOptions);
      tasks++;
      const destroy = task.destroy.bind(task);
      task.destroy = async () => { try { await destroy(); } finally { destroyed++; } };
      return task;
    } };
  }, { setPlan(code, market, plan) { plans.set(code, { market, ...JSON.parse(JSON.stringify(plan)) }); } });

  function file(name) {
    return { name, arrayBuffer: async () => {
      const bytes = fs.readFileSync(path.join(__dirname, 'fixtures/pdf_import', name));
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    } };
  }
  const chinese = await importer.extractText(file('中文多頁計畫.pdf'));
  assert.ok(chinese.includes('下週執行總表'));
  assert.ok(chinese.includes('台積電 2330 買區 900～920'));
  assert.ok(chinese.indexOf('PAGE 1 END') < chinese.indexOf('聯發科 2454'));
  assert.ok(chinese.includes('PAGE 2 END'));
  const result = await importer.parseFile(file('中文多頁計畫.pdf'));
  assert.strictEqual(result.imported, 2);
  assert.deepStrictEqual(plans.get('2330'), { market: 'TW', resistance: 950, buyZoneLow: 900,
    buyZoneHigh: 920, stopLoss: 880, weakBreak: 850, longCondition: '站穩 925 突破 950', role: '主倉', outlook: '' });
  assert.strictEqual(plans.get('2454').resistance, 1200);
  assert.strictEqual(plans.get('2454').stopLoss, 1080);
  assert.strictEqual(plans.get('2454').weakBreak, 1000);
  assert.strictEqual(plans.get('2454').role, '觀察倉');
  const before = JSON.stringify([...plans]);
  const english = await importer.extractText(file('一般多頁文字.pdf'));
  assert.ok(english.includes('First page: PDF import compatibility.'));
  assert.ok(english.indexOf('PAGE 1 END') < english.indexOf('Second page:'));
  assert.strictEqual((await importer.parseFile(file('一般多頁文字.pdf'))).imported, 0);
  assert.strictEqual((await importer.parseFile(file('空白文件.pdf'))).imported, 0);
  await assert.rejects(importer.parseFile(file('密碼保護.pdf')), /需要密碼/);
  await assert.rejects(importer.parseFile(file('損毀文件.pdf')), /損毀/);
  assert.strictEqual(JSON.stringify([...plans]), before, '無有效計畫或解析失敗時，不可改動已匯入計畫');
  assert.strictEqual(tasks, 7);
  assert.strictEqual(destroyed, tasks, '每份真實 PDF 的 loading task 均須結束');
  console.log('PDF 實檔：中文 CMap、兩頁計畫、多頁英文字、空白、密碼與損毀案例通過');
}
main().catch(error => { console.error(error); process.exitCode = 1; });

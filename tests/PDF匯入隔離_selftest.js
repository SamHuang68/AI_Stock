'use strict';
const assert = require('assert');
const { enableModules, loadImporter } = require('./PDF匯入測試工具.cjs');
enableModules(__filename);

async function main() {
  let imports = 0, documents = 0, destroyed = 0, cleaned = 0, options;
  const lib = {
    version: '6.3.289', GlobalWorkerOptions: {}, PDFWorker: class { destroy() {} },
    getDocument(input) {
      documents++; options = input;
      return { destroy: async () => { destroyed++; }, promise: Promise.resolve({
        numPages: 1,
        getPage: async () => ({ cleanup() { cleaned++; }, getTextContent: async () => ({ items: [
          { str: '2330', transform: [1, 0, 0, 1, 80, 600] },
          { str: '台積電', transform: [1, 0, 0, 1, 10, 600] },
          { type: 'beginMarkedContent' },
          { str: '買區 900～920 突破 950 破 880 減碼 破 850 出場', transform: [1, 0, 0, 1, 10, 580] },
        ] }) }),
      }) };
    },
  };
  const importer = loadImporter(async url => {
    imports++;
    assert.ok(url.endsWith('/assets/vendor/pdfjs/6.3.289/pdf.min.mjs'));
    return lib;
  }, { pdfjsLib: { getDocument() { throw new Error('不可沿用舊全域物件'); } } });
  const one = importer.loadPdfJs(), two = importer.loadPdfJs();
  assert.strictEqual(one, two, '並行載入應共用一次請求');
  await Promise.all([one, two]);
  assert.strictEqual(imports, 1);
  assert.ok(lib.GlobalWorkerOptions.workerSrc.endsWith('/6.3.289/pdf.worker.min.mjs'));
  const data = new ArrayBuffer(8);
  const text = await importer.extractText({ arrayBuffer: async () => data });
  assert.strictEqual(options.data, data);
  assert.ok(!('url' in options), '檔案內容不得轉成遠端 URL');
  assert.ok(!('isEvalSupported' in options), '不得以新版已移除的選項作為安全證據');
  assert.ok(text.startsWith('台積電 2330\n買區'));
  assert.strictEqual(options.cMapPacked, true);
  for (const [key, name] of [['cMapUrl', 'cmaps'], ['standardFontDataUrl', 'standard_fonts'], ['wasmUrl', 'wasm']]) {
    assert.ok(options[key].endsWith('/6.3.289/' + name + '/'));
  }
  assert.strictEqual(destroyed, 1);
  assert.strictEqual(cleaned, 1);

  let attempt = 0;
  const retry = loadImporter(async () => { if (++attempt === 1) throw new Error('模擬載入失敗'); return lib; });
  await assert.rejects(retry.loadPdfJs(), /解析元件載入失敗/);
  await retry.loadPdfJs();
  assert.strictEqual(attempt, 2);
  const mismatch = loadImporter(async () => ({ ...lib, version: '3.11.174' }));
  await assert.rejects(mismatch.loadPdfJs(), error => /版本不符/.test(error.cause.message));

  for (const [name, message] of [['PasswordException', '密碼'], ['InvalidPDFException', '損毀'], ['Error', '模擬解析失敗']]) {
    let released = 0, writes = 0;
    const failure = loadImporter(async () => ({ ...lib, getDocument() {
      return { promise: Promise.reject(Object.assign(new Error('模擬解析失敗'), { name })), destroy: async () => { released++; } };
    } }), { setPlan() { writes++; } });
    await assert.rejects(failure.parseFile({ name: '測試.pdf', arrayBuffer: async () => data }), new RegExp(message));
    assert.strictEqual(released, 1);
    assert.strictEqual(writes, 0, '解析失敗不得部分寫入計畫');
  }

  let failPageCleanup = 0, failTaskCleanup = 0;
  const pageFailure = loadImporter(async () => ({ ...lib, getDocument() {
    return { promise: Promise.resolve({ numPages: 1, getPage: async () => ({
      getTextContent: async () => { throw new Error('頁面解析失敗'); }, cleanup() { failPageCleanup++; },
    }) }), destroy: async () => { failTaskCleanup++; } };
  } }));
  await assert.rejects(pageFailure.extractText({ arrayBuffer: async () => data }), /頁面解析失敗/);
  assert.strictEqual(failPageCleanup, 1);
  assert.strictEqual(failTaskCleanup, 1);

  let trigger, timeoutDestroyed = 0, timerCleared = false;
  const timeout = loadImporter(async () => ({ ...lib, getDocument() {
    return { promise: new Promise(() => {}), destroy: async () => { timeoutDestroyed++; } };
  } }), {
    setTimeout(callback, delay) { if (delay === 120000) { trigger = callback; return 17; } assert.strictEqual(delay, 5000); return 18; },
    clearTimeout(id) { if (id === 17) timerCleared = true; },
  });
  const pending = timeout.extractText({ arrayBuffer: async () => data });
  while (!trigger) await new Promise(resolve => setImmediate(resolve));
  trigger();
  await assert.rejects(pending, /超過 120 秒/);
  assert.strictEqual(timeoutDestroyed, 1);
  assert.ok(timerCleared);
  for (const cleanupFails of [false, true]) {
    const timers = new Map();
    let workerDestroyed = false;
    const stuck = loadImporter(async () => ({ ...lib,
      PDFWorker: class { destroy() { workerDestroyed = true; } },
      getDocument() { return { promise: new Promise(() => {}), destroy() {
        return cleanupFails ? Promise.reject(new Error('清理錯誤')) : new Promise(() => {});
      } }; },
    }), { setTimeout(callback, delay) { timers.set(delay, callback); return delay; }, clearTimeout() {} });
    const result = stuck.extractText({ arrayBuffer: async () => data });
    const rejected = assert.rejects(result, /超過 120 秒/);
    while (!timers.has(120000)) await new Promise(resolve => setImmediate(resolve));
    timers.get(120000)();
    while (!timers.has(5000)) await new Promise(resolve => setImmediate(resolve));
    if (!cleanupFails) timers.get(5000)();
    await rejected;
    assert.ok(workerDestroyed, '清理卡住或拒絕時仍須終止實際 worker');
  }
  for (const label of ['買區：', '買區:', '可買區（元）', '支撐位', '可買區（元）：']) {
    const blocks = importer.extractBlocks('聯發科 2454 ' + label + ' 1100～1150 站穩 1160 突破 1200 破 1080 減碼 破 1000 出場');
    assert.strictEqual(blocks.length, 1);
    assert.strictEqual(blocks[0].code, '2454');
    assert.strictEqual(importer.parseStockBlock(blocks[0].text).buyZoneLow, 1100);
  }
  assert.strictEqual(documents, 1);
  console.log('PDF 匯入：固定版本、同源資產、載入重試、解析錯誤與逾時清理通過');
}
main().catch(error => { console.error(error); process.exitCode = 1; });

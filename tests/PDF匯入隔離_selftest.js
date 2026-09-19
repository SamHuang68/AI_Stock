'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

(async function () {
  let options;
  const environment = {
    console: { log() {}, warn() {} },
    pdfjsLib: {
      getDocument(input) {
        options = input;
        return { promise: Promise.resolve({
          numPages: 1,
          getPage: async () => ({ getTextContent: async () => ({ items: [
            { str: '2330', transform: [1, 0, 0, 1, 80, 600] },
            { str: '台積電', transform: [1, 0, 0, 1, 10, 600] }
          ] }) })
        }) };
      }
    }
  };
  vm.createContext(environment);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/ui/pdf_import_v3.js'), 'utf8'), environment);
  const data = new ArrayBuffer(8);
  const text = await environment.PlanPdfImport.extractText({ arrayBuffer: async () => data });
  assert.strictEqual(options.data, data);
  assert.strictEqual(options.isEvalSupported, false, 'PDF 文字匯入必須停用動態程式碼');
  assert.ok(text.startsWith('台積電 2330\n'), '原有文字排序與擷取仍須運作');
  console.log('PDF 匯入隔離：通過');
})().catch(error => { console.error(error); process.exitCode = 1; });

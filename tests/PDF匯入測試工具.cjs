'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { pathToFileURL } = require('url');

function enableModules(filename) {
  if (process.execArgv.includes('--experimental-vm-modules')) return;
  const result = require('child_process').spawnSync(process.execPath,
    ['--experimental-vm-modules', filename], { stdio: 'inherit' });
  process.exit(result.status === null ? 1 : result.status);
}

function loadImporter(importModule, extras = {}) {
  const source = path.resolve(__dirname, '../src/ui/pdf_import_v3.js');
  const environment = {
    console: { log() {}, warn() {} }, URL, ArrayBuffer, Uint8Array, setTimeout, clearTimeout,
    document: { currentScript: { src: pathToFileURL(source).href } }, ...extras,
  };
  vm.createContext(environment);
  vm.runInContext(fs.readFileSync(source, 'utf8'), environment, {
    filename: source,
    importModuleDynamically: async url => {
      const api = await importModule(url);
      const names = Object.keys(api);
      const module = new vm.SyntheticModule(names, function () {
        for (const name of names) this.setExport(name, api[name]);
      }, { context: environment });
      await module.link(() => {});
      await module.evaluate();
      return module;
    },
  });
  return environment.PlanPdfImport;
}

module.exports = { enableModules, loadImporter };

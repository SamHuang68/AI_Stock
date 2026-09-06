#!/usr/bin/env node
'use strict';

var fs = require('fs');
var path = require('path');
var vm = require('vm');

function ok(cond, msg) {
  if (!cond) throw new Error(msg);
}

var root = path.join(__dirname, '..');
var src = fs.readFileSync(path.join(root, 'src/core/feature_flags_v5.js'), 'utf8');
var storage = { _d: {}, removed: false };
var sandbox = {
  CustomEvent: function CustomEvent(type, init) {
    this.type = type;
    this.detail = init && init.detail;
  },
  window: {
    dispatchEvent: function () {},
    CustomEvent: function CustomEvent(type, init) {
      this.type = type;
      this.detail = init && init.detail;
    },
    SERVER: 'http://127.0.0.1:18432',
    localStorage: {
      getItem: function (k) { return storage._d[k] || null; },
      setItem: function (k, v) { storage._d[k] = String(v); },
      removeItem: function (k) {
        storage.removed = true;
        delete storage._d[k];
      }
    },
    fetch: function (url) {
      if (url.indexOf('/features') >= 0) {
        return Promise.resolve({
          ok: true,
          json: function () {
            return Promise.resolve({
              ok: true,
              flags: {
                shadowOvernightIntraday: false,
                shadowEarlyWarning: false,
                shadowConsensusAttention: false
              }
            });
          }
        });
      }
      return Promise.reject(new Error('unexpected fetch ' + url));
    },
    FeatureFlags: null
  },
  location: { origin: 'http://127.0.0.1:18432' },
  document: { readyState: 'complete' },
  console: console,
  Promise: Promise,
  setTimeout: setTimeout
};
sandbox.fetch = sandbox.window.fetch;
sandbox.location = sandbox.location;
sandbox.localStorage = sandbox.window.localStorage;
vm.createContext(sandbox);
vm.runInContext(src, sandbox);

var FF = sandbox.window.FeatureFlags;
ok(FF && FF.isEnabled, 'FeatureFlags API exists');
ok(storage.removed, 'boot clears stale localStorage override key');
ok(!FF.isEnabled('shadowEarlyWarning'), 'server /features is authoritative when flags off');

storage._d['st_feature_flags_v1'] = JSON.stringify({ shadowEarlyWarning: true });
FF.refresh().then(function () {
  ok(!FF.isEnabled('shadowEarlyWarning'),
    'localStorage alone cannot enable shadow panels when server flags are off');
  ok(/伺服器旗標關閉/.test(FF.enableHint('shadowEarlyWarning')),
    'enableHint documents server enable path');
  console.log('feature_flags_v5_selftest: ok');
}).catch(function (err) {
  console.error(err);
  process.exit(1);
});

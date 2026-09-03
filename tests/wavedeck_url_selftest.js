#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const bridge = fs.readFileSync(path.join(root, 'src/ui/wavedeck_bridge_v5.js'), 'utf8');
const shell = fs.readFileSync(path.join(root, 'src/ui/shell_v5.js'), 'utf8');

function ok(condition, message) {
  if (!condition) {
    console.error('失敗：' + message);
    process.exitCode = 1;
    return;
  }
  console.log('通過：' + message);
}

const helperMatch = bridge.match(/function isReservedPrivateWebUrl\(value\) \{[\s\S]*?\n  \}/);
ok(!!helperMatch, '找到 WaveDeck 保留埠判斷函式');

if (helperMatch) {
  const windowStub = { location: { href: 'http://127.0.0.1:18432/#pulse' } };
  const helper = new Function(
    'window', 'URL', helperMatch[0] + '; return isReservedPrivateWebUrl;'
  )(windowStub, URL);
  ok(helper('http://127.0.0.1:18434/'), '拒絕本機 Private Web 18434');
  ok(helper('http://localhost:18435/'), '拒絕本機 Private Web 18435');
  ok(!helper('http://127.0.0.1:18433/'), '允許 WaveDeck 預設 18433');
  ok(!helper('http://127.0.0.1:19000/'), '允許安全的自訂埠');
}

ok(
  /if \(isReservedPrivateWebUrl\(url\)\)[\s\S]*?已拒絕開啟/.test(bridge),
  '所有 WaveDeckBridge.open(url) 呼叫都套用保留埠防線'
);
ok(
  !/window\.open\(window\.WAVEDECK_URL/.test(shell) &&
    !/else \{\s*window\.open\(url, '_blank', 'noopener'\);/.test(shell),
  'Shell 後援不會繞過 WaveDeckBridge 的保留埠防線'
);

if (process.exitCode) process.exit(process.exitCode);
console.log('WaveDeck 網址安全自測完成。');

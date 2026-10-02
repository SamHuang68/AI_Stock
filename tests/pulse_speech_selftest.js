'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const srcPath = path.join(__dirname, '..', 'src', 'ui', 'pulse_v5.js');
const src = fs.readFileSync(srcPath, 'utf8');

function extractFn(name) {
  const marker = 'function ' + name;
  const idx = src.indexOf(marker);
  if (idx < 0) throw new Error('function not found: ' + name);
  let i = src.indexOf('{', idx);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    const c = src[j];
    if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return src.slice(idx, j + 1); }
  }
  throw new Error('unterminated function: ' + name);
}

const fnSrcs = ['splitSpeechText', 'pickChineseLocalVoice', 'stopAiSpeech', 'toggleAiSpeech']
  .map(extractFn).join('\n\n');

function makeSandbox(opts) {
  opts = opts || {};
  const dom = opts.dom || {};
  const voices = opts.voices || [];
  const sandbox = {
    aiSpeechActive: false,
    aiSpeechSession: 0,
    aiSpeechQueue: null,
    syncCount: 0,
    utterances: [],
    speakCalls: 0,
    cancelCalls: 0,
    $: function (id) { return dom[id] || null; },
    syncAiSummaryControls: function () { sandbox.syncCount++; },
    window: {
      speechSynthesis: {
        getVoices: function () {
          if (opts.getVoicesThrows) throw new Error('getVoices fail');
          return voices;
        },
        speak: function (u) {
          sandbox.speakCalls++;
          if (opts.speakThrows) throw new Error('speak fail');
          if (typeof opts.speak === 'function') opts.speak(u, sandbox);
        },
        cancel: function () {
          sandbox.cancelCalls++;
          if (opts.cancelThrows) throw new Error('cancel fail');
        }
      },
      SpeechSynthesisUtterance: function (text) {
        this.text = text;
        this.lang = '';
        this.voice = null;
        this.rate = 1;
        this.onend = null;
        this.onerror = null;
        sandbox.utterances.push(this);
      }
    }
  };
  if (opts.noSpeechSynthesis) delete sandbox.window.speechSynthesis;
  if (opts.noUtterance) delete sandbox.window.SpeechSynthesisUtterance;
  vm.createContext(sandbox);
  vm.runInContext(fnSrcs, sandbox);
  sandbox.API = {
    splitSpeechText: sandbox.splitSpeechText,
    pickChineseLocalVoice: sandbox.pickChineseLocalVoice,
    stopAiSpeech: sandbox.stopAiSpeech,
    toggleAiSpeech: sandbox.toggleAiSpeech
  };
  sandbox.state = function () {
    return {
      active: sandbox.aiSpeechActive,
      session: sandbox.aiSpeechSession,
      queueLen: sandbox.aiSpeechQueue ? sandbox.aiSpeechQueue.length : 0
    };
  };
  return sandbox;
}

let passed = 0;
let failed = 0;
async function test(name, fn) {
  try {
    await fn();
    passed++;
    console.log('OK   ' + name);
  } catch (e) {
    failed++;
    console.error('FAIL ' + name);
    console.error(e && e.stack ? e.stack : e);
  }
}

(async function main() {
  await test('splitSpeechText: 超長無標點中文每段<=120且完整', function () {
    const sb = makeSandbox();
    const text = '一'.repeat(300);
    const segs = sb.API.splitSpeechText(text);
    assert.ok(segs.length >= 2, 'segments=' + segs.length);
    segs.forEach(function (s) { assert.ok(Array.from(s).length <= 120); });
    assert.strictEqual(segs.join(''), text);
  });

  await test('splitSpeechText: emoji 不被破壞', function () {
    const sb = makeSandbox();
    const text = '\uD83D\uDE00'.repeat(150);
    const segs = sb.API.splitSpeechText(text);
    segs.forEach(function (s) { assert.ok(Array.from(s).length <= 120); });
    assert.strictEqual(segs.join(''), text);
    segs.forEach(function (s) {
      for (let i = 0; i < s.length; i++) {
        const code = s.charCodeAt(i);
        if (code >= 0xD800 && code <= 0xDBFF) {
          const nx = s.charCodeAt(i + 1);
          assert.ok(nx >= 0xDC00 && nx <= 0xDFFF, 'lone high surrogate');
          i++;
        } else {
          assert.ok(!(code >= 0xDC00 && code <= 0xDFFF), 'lone low surrogate');
        }
      }
    });
  });

  await test('splitSpeechText: 中文句子保留完整內容', function () {
    const sb = makeSandbox();
    const text = '你好。今天天氣真好！明天再見？';
    const segs = sb.API.splitSpeechText(text);
    assert.ok(segs.length >= 1);
    assert.strictEqual(segs.join(''), text);
  });

  await test('splitSpeechText: 空字串或空白回空陣列', function () {
    const sb = makeSandbox();
    assert.strictEqual(sb.API.splitSpeechText('').length, 0);
    assert.strictEqual(sb.API.splitSpeechText('   ').length, 0);
    assert.strictEqual(sb.API.splitSpeechText(null).length, 0);
  });

  await test('toggleAiSpeech: 不支援 API 時提示', function () {
    const meta = { textContent: '' };
    const body = { textContent: '你好世界' };
    const sb = makeSandbox({
      dom: { 'pl-ai-body': body, 'pl-ai-meta': meta },
      noSpeechSynthesis: true
    });
    sb.API.toggleAiSpeech();
    assert.strictEqual(meta.textContent, '此瀏覽器不支援語音朗讀');
    assert.strictEqual(sb.state().active, false);
    assert.strictEqual(sb.speakCalls, 0);
  });

  await test('toggleAiSpeech: 空本文提示未完成', function () {
    const meta = { textContent: '' };
    const sb = makeSandbox({
      dom: { 'pl-ai-body': { textContent: '' }, 'pl-ai-meta': meta },
      voices: [{ lang: 'zh-TW', localService: true }]
    });
    sb.API.toggleAiSpeech();
    assert.strictEqual(meta.textContent, '摘要完成後即可朗讀');
    assert.strictEqual(sb.state().active, false);
    assert.strictEqual(sb.speakCalls, 0);
  });

  await test('toggleAiSpeech: 思考中（未完成）提示', function () {
    const meta = { textContent: '' };
    const sb = makeSandbox({
      dom: { 'pl-ai-body': { textContent: '思考中…' }, 'pl-ai-meta': meta },
      voices: [{ lang: 'zh-TW', localService: true }]
    });
    sb.API.toggleAiSpeech();
    assert.strictEqual(meta.textContent, '摘要完成後即可朗讀');
    assert.strictEqual(sb.state().active, false);
    assert.strictEqual(sb.speakCalls, 0);
  });

  await test('toggleAiSpeech: 只有遠端 voice 時拒絕朗讀', function () {
    const meta = { textContent: '' };
    const sb = makeSandbox({
      dom: { 'pl-ai-body': { textContent: '你好世界，這是一段摘要。' }, 'pl-ai-meta': meta },
      voices: [
        { lang: 'zh-TW', localService: false, name: 'remoteTW' },
        { lang: 'en-US', localService: true, name: 'en' }
      ]
    });
    sb.API.toggleAiSpeech();
    assert.ok(/本機中文語音/.test(meta.textContent), 'meta=' + meta.textContent);
    assert.strictEqual(sb.state().active, false);
    assert.strictEqual(sb.speakCalls, 0);
  });

  await test('pickChineseLocalVoice: 優先回傳 zh-TW', function () {
    const sb = makeSandbox({
      voices: [
        { lang: 'zh-CN', localService: true, name: 'cn' },
        { lang: 'zh-TW', localService: true, name: 'tw' },
        { lang: 'en-US', localService: true, name: 'en' }
      ]
    });
    const v = sb.API.pickChineseLocalVoice();
    assert.strictEqual(v.name, 'tw');
  });

  await test('pickChineseLocalVoice: 無本機中文回 null', function () {
    const sb = makeSandbox({ voices: [{ lang: 'en-US', localService: true }] });
    assert.strictEqual(sb.API.pickChineseLocalVoice(), null);
    const sb2 = makeSandbox({ voices: [{ lang: 'zh-TW', localService: false }] });
    assert.strictEqual(sb2.API.pickChineseLocalVoice(), null);
  });

  await test('toggleAiSpeech: 逐段完整唸完整本文並綁定本機 voice', async function () {
    const meta = { textContent: '' };
    const text = '一二三。'.repeat(80);
    const voice = { lang: 'zh-TW', localService: true, name: 'tw' };
    const spoken = [];
    const sb = makeSandbox({
      dom: { 'pl-ai-body': { textContent: text }, 'pl-ai-meta': meta },
      voices: [voice],
      speak: function (u) {
        assert.strictEqual(u.voice, voice);
        spoken.push(u.text);
        setImmediate(function () { if (u.onend) u.onend(); });
      }
    });
    sb.API.toggleAiSpeech();
    assert.strictEqual(sb.state().active, true);
    await new Promise(function (resolve) {
      const tick = function () {
        if (sb.state().active) setImmediate(tick);
        else resolve();
      };
      setImmediate(tick);
    });
    assert.strictEqual(spoken.join(''), text, '完整本文必須被唸完');
    assert.ok(sb.speakCalls >= 2, 'speakCalls=' + sb.speakCalls);
  });

  await test('stopAiSpeech: 停止後舊 callback 不復活佇列', function () {
    const meta = { textContent: '' };
    const text = '一。二。三。四。五。';
    let saved = null;
    const sb = makeSandbox({
      dom: { 'pl-ai-body': { textContent: text }, 'pl-ai-meta': meta },
      voices: [{ lang: 'zh-TW', localService: true }],
      speak: function (u) { if (!saved) saved = u; }
    });
    sb.API.toggleAiSpeech();
    assert.ok(saved);
    const beforeSpeak = sb.speakCalls;
    sb.API.stopAiSpeech();
    assert.strictEqual(sb.state().active, false);
    assert.strictEqual(sb.state().queueLen, 0);
    if (saved.onend) saved.onend();
    if (saved.onerror) saved.onerror();
    assert.strictEqual(sb.state().active, false);
    assert.strictEqual(sb.speakCalls, beforeSpeak, '舊 callback 不可再觸發 speak');
  });

  await test('toggleAiSpeech: 重啟後舊 callback 不影響新 session', function () {
    const meta = { textContent: '' };
    const text = '一。二。三。四。';
    let saved = null;
    const sb = makeSandbox({
      dom: { 'pl-ai-body': { textContent: text }, 'pl-ai-meta': meta },
      voices: [{ lang: 'zh-TW', localService: true }],
      speak: function (u) { saved = u; }
    });
    sb.API.toggleAiSpeech();
    const oldUtter = saved;
    sb.API.stopAiSpeech();
    saved = null;
    sb.API.toggleAiSpeech();
    const newUtter = saved;
    assert.ok(oldUtter && newUtter && oldUtter !== newUtter);
    const speakBefore = sb.speakCalls;
    const activeBefore = sb.state().active;
    oldUtter.onend();
    oldUtter.onerror();
    assert.strictEqual(sb.speakCalls, speakBefore, '舊 onend 不應觸發新 speak');
    assert.strictEqual(sb.state().active, activeBefore, '舊 callback 不應更改新 session 狀態');
  });

  await test('toggleAiSpeech: speak 丟例外時清除狀態', function () {
    const meta = { textContent: '' };
    const sb = makeSandbox({
      dom: { 'pl-ai-body': { textContent: '你好世界' }, 'pl-ai-meta': meta },
      voices: [{ lang: 'zh-TW', localService: true }],
      speakThrows: true
    });
    sb.API.toggleAiSpeech();
    assert.strictEqual(sb.state().active, false);
  });

  await test('stopAiSpeech: cancel 丟例外不會中斷', function () {
    const sb = makeSandbox({
      voices: [{ lang: 'zh-TW', localService: true }],
      cancelThrows: true
    });
    assert.doesNotThrow(function () { sb.API.stopAiSpeech(); });
    assert.strictEqual(sb.state().active, false);
  });

  await test('toggleAiSpeech: onerror 清除狀態', function () {
    const meta = { textContent: '' };
    let saved = null;
    const sb = makeSandbox({
      dom: { 'pl-ai-body': { textContent: '你好世界，摘要如下。' }, 'pl-ai-meta': meta },
      voices: [{ lang: 'zh-TW', localService: true }],
      speak: function (u) { saved = u; }
    });
    sb.API.toggleAiSpeech();
    assert.strictEqual(sb.state().active, true);
    saved.onerror();
    assert.strictEqual(sb.state().active, false);
    assert.strictEqual(sb.state().queueLen, 0);
  });

  if (failed > 0) {
    console.error('FAILED ' + failed + ' / passed ' + passed);
    process.exit(1);
  } else {
    console.log('ALL PASSED total=' + passed);
  }
})().catch(function (e) {
  console.error(e);
  process.exit(1);
});

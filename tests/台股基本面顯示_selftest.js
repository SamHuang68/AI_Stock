#!/usr/bin/env node
// ============================================================
// tests/台股基本面顯示_selftest.js — PR102 基本面 UI/快取自我測試
// 以 Node vm 直接載入 src/fundamental/fundamental_v3.js，不碰外部服務。
// 涵蓋：fmtMoney（萬／億／零／缺值）、toYuan 單位乘法、台股一般業顯示、
//      台股缺值、金融業不適用、美股保持、HTML escape、較舊期備註、
//      快取 TTL（完整/部分/伺服器更短）、過期允許重試、inflight 併發、
//      A→B→A 過時回應不覆蓋。
// ============================================================
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const SRC_PATH = path.resolve(__dirname, '..', 'src', 'fundamental', 'fundamental_v3.js');
const RAW_SOURCE = fs.readFileSync(SRC_PATH, 'utf8');
const SOURCE = RAW_SOURCE.replace('window.fetchFund = fetchFund;', 'window.fetchFund = fetchFund;'+"    // 測試探針（僅對自我測試使用；不影響 UI）\n    window.__fundInternals = {\n      escapeHTML: escapeHTML,\n      fmtMoney: fmtMoney,\n      toYuan: toYuan,\n      render: render,\n      renderEmpty: renderEmpty,\n      isPartial: isPartial,\n      writeCache: writeCache,\n      readCache: readCache,\n      _getCache: function () { return _fCache; },\n      _getInflight: function () { return _fInflight; },\n      _clearCache: function () { for (const k in _fCache) delete _fCache[k]; },\n      _getLastReq: function () { return _fLastReq; },\n      CACHE_FULL_MS: CACHE_FULL_MS,\n      CACHE_PARTIAL_MS: CACHE_PARTIAL_MS\n    };");

function mkCtx(opts) {
  opts = opts || {};
  const panel = {
    innerHTML: '',
    insertAdjacentHTML(_pos, html) { this.innerHTML += html; },
  };
  const elements = {};
  const document = {
    getElementById(id) {
      if (id === 'rpanel') return panel;
      return elements[id] || null;
    },
    _set(id, el) { elements[id] = el; },
  };
  const origRenderStats = opts.renderStats || function () { return ''; };
  const win = {
    SERVER: 'http://test.local',
    S: opts.S || { sym: 'TEST', mkt: 'TW', tab: 'stats' },
    renderStats: origRenderStats,
    _fundPatched: false,
  };
  const sandbox = {
    window: win,
    document: document,
    fetch: opts.fetch || (async () => ({ ok: false, status: 500, json: async () => null })),
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    console: console,
    Date: Date,
    Number: Number,
    String: String,
    Math: Math,
    JSON: JSON,
    Promise: Promise,
    isFinite: isFinite,
    encodeURIComponent: encodeURIComponent,
    renderStats: origRenderStats,
    panel: panel,
    elements: elements,
  };
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox);
  return sandbox;
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

let pass = 0, fail = 0;
async function test(name, fn) {
  try {
    await fn();
    pass++;
    console.log('  ✔', name);
  } catch (err) {
    fail++;
    console.log('  ✘', name);
    console.log('   ', (err && err.stack) || err);
  }
}

(async function main() {
  console.log('臺股基本面顯示 selftest（PR102）');

  await test('真實頂層 let S 不掛 window 時仍顯示基本面', async () => {
    let calls = 0;
    const ctx = {console, setTimeout, clearTimeout, fetch: async () => {
      calls++; return {ok:true,json:async()=>({market:'TW',revenue:{monthRev:0,unitMultiplier:1000,yoyPct:0}})};
    }, document: {getElementById:()=>null}};
    ctx.window=ctx;
    vm.createContext(ctx);
    vm.runInContext("let S={sym:'2330',mkt:'TW',tab:'stats'}; function renderStats(){return 'base';}",ctx);
    assert.strictEqual(ctx.S, undefined);
    vm.runInContext(RAW_SOURCE,ctx);
    assert(vm.runInContext('renderStats()',ctx).includes('fund-sect'));
    await Promise.resolve(); await Promise.resolve();
    assert.strictEqual(calls,1);
  });

  // --- 1) fmtMoney / toYuan ---
  await test('fmtMoney：50,000 元 → "5 萬"', () => {
    const s = mkCtx();
    const { fmtMoney } = s.window.__fundInternals;
    assert.strictEqual(fmtMoney(50000), '5 萬');
  });
  await test('fmtMoney：1.5e8 元 → "1.5 億"', () => {
    const s = mkCtx();
    const { fmtMoney } = s.window.__fundInternals;
    assert.strictEqual(fmtMoney(1.5e8), '1.5 億');
  });
  await test('fmtMoney：零 → "0"（不要被判成缺值）', () => {
    const s = mkCtx();
    const { fmtMoney } = s.window.__fundInternals;
    assert.strictEqual(fmtMoney(0), '0');
  });
  await test('fmtMoney：null → "—"', () => {
    const s = mkCtx();
    const { fmtMoney } = s.window.__fundInternals;
    assert.strictEqual(fmtMoney(null), '—');
  });
  await test('toYuan：150,000 千元 × 1000 = 1.5 億元（僅乘一次）', () => {
    const s = mkCtx();
    const { toYuan, fmtMoney } = s.window.__fundInternals;
    const yuan = toYuan(150000, 1000);
    assert.strictEqual(yuan, 1.5e8);
    assert.strictEqual(fmtMoney(yuan), '1.5 億');
  });
  await test('toYuan：缺 multiplier 不會額外放大', () => {
    const s = mkCtx();
    const { toYuan } = s.window.__fundInternals;
    assert.strictEqual(toYuan(1234, undefined), 1234);
    assert.strictEqual(toYuan(1234, 1), 1234);
  });

  // --- 2) 台股一般業顯示 ---
  await test('台股一般業：月營收/三率/來源出表日/累計', () => {
    const s = mkCtx();
    const { render } = s.window.__fundInternals;
    const html = render({
      market: 'TW', score: 72,
      revenue: {
        period: '11508', periodLabel: '2026-08',
        monthRev: 150000, unit: '新臺幣千元', unitMultiplier: 1000,
        yoyPct: 5.2, momPct: -1.3, cumYoyPct: 8.1, cumRev: 1200000,
        sourceName: 'TWSE 月營收', sourceDate: '2026-09-10',
      },
      income: {
        period: '2026年第2季累計', industry: '半導體業', industryCode: '24',
        marginStatus: 'available', epsUnit: '新臺幣元', eps: 7.21,
        netIncome: 50000000, unitMultiplier: 1000,
        grossMargin: 45.3, opMargin: 30.1, netMargin: 25.5,
        sourceName: 'TWSE 綜合損益表', sourceDate: '2026-08-14',
      },
    });
    assert(html.includes('臺股月營收'), '需顯示臺股月營收');
    assert(html.includes('2026-08'));
    assert(html.includes('1.5 億'), '月營收換算應為 1.5 億（千元×1000）');
    assert(html.includes('+5.2%'));
    assert(html.includes('45.3%'));
    assert(html.includes('TWSE 月營收'));
    assert(html.includes('出表日 2026-09-10'));
    assert(html.includes('累計營收 YoY'));
    assert(!html.includes('盈餘成長'), '不應誤顯示 Yahoo 盈餘成長');
  });

  // --- 3) 台股月營收缺值 ---
  await test('台股月營收缺值：仍顯示臺股月營收欄位（不走 Yahoo）', () => {
    const s = mkCtx();
    const { render } = s.window.__fundInternals;
    const html = render({
      market: 'TW',
      revenue: {
        period: '11508', periodLabel: '2026-08',
        monthRev: null, unitMultiplier: 1000,
        yoyPct: null, momPct: null, cumYoyPct: null,
      },
    });
    assert(html.includes('臺股月營收'));
    assert(html.includes('—'));
    assert(!html.includes('盈餘成長'));
  });

  // --- 4) 零值 vs 缺值分明 ---
  await test('零值顯示 0.0%，缺值顯示 —', () => {
    const s = mkCtx();
    const { render } = s.window.__fundInternals;
    const html = render({
      market: 'TW',
      revenue: {
        period: '11508', periodLabel: '2026-08',
        monthRev: 0, unitMultiplier: 1000,
        yoyPct: 0, momPct: null, cumYoyPct: 0,
      },
    });
    assert(html.includes('+0.0%'), '0 應顯示 +0.0%');
    assert(/MoM 月增[^]*?—/.test(html), 'momPct 缺值應顯示 —');
    // 月營收 0 元 → '0'
    assert(/臺股月營收[^]*?0</.test(html) || html.includes('>0<'));
  });

  // --- 5) 金融業不適用 ---
  await test('金融業：三率不適用、顯示稅後與母公司淨利', () => {
    const s = mkCtx();
    const { render } = s.window.__fundInternals;
    const html = render({
      market: 'TW',
      income: {
        period: '2026年第2季累計', industry: '銀行業', industryCode: '28',
        marginStatus: 'not_applicable',
        marginNote: '金融業適用不同科目分類，一般三率公式不適用',
        epsUnit: '新臺幣元', eps: 1.85,
        netIncome: 20000000, parentNetIncome: 18000000, unitMultiplier: 1000,
        sourceName: 'TWSE 綜合損益表', sourceDate: '2026-08-14',
      },
      scoreNote: '金融業不適用一般業評分',
    });
    assert(html.includes('不適用'), '三率應標示不適用');
    assert(html.includes('稅後淨利'));
    assert(html.includes('母公司業主淨利'));
    assert(html.includes('EPS 1.85'));
    assert(html.includes('金融業不適用一般業評分'));
    assert(!/毛利率[^\n]*\d+\.\d+%/.test(html), '毛利率不應顯示百分比');
  });

  // --- 6) 美股保持 ---
  await test('美股：Yahoo 成長+三率仍正常', () => {
    const s = mkCtx({ S: { sym: 'AAPL', mkt: 'US', tab: 'stats' } });
    const { render } = s.window.__fundInternals;
    const html = render({
      market: 'US', score: 68,
      revenue: { period: 'TTM', label: 'Yahoo keystats', yoyPct: 7.5, cumYoyPct: 12.3 },
      income: { period: 'TTM', eps: 6.11, grossMargin: 44.0, opMargin: 29.5, netMargin: 24.2 },
      _source: 'keystats',
    });
    assert(html.includes('成長 TTM'));
    assert(html.includes('盈餘成長'));
    assert(html.includes('+7.5%'));
    assert(html.includes('+12.3%'));
    assert(html.includes('44.0%'));
    assert(!html.includes('臺股月營收'));
  });

  // --- 7) HTML escape ---
  await test('HTML escape：script/img 標籤被跳脫', () => {
    const s = mkCtx();
    const { render } = s.window.__fundInternals;
    const html = render({
      market: 'TW', score: 50,
      revenue: {
        period: '11508', periodLabel: '<b>2026-08</b>',
        monthRev: 150000, unitMultiplier: 1000,
        yoyPct: 1, momPct: 1, cumYoyPct: 1,
        sourceName: '<img src=x>', sourceDate: '<svg>',
      },
      scoreNote: '<script>alert(1)</script>',
    });
    assert(!html.includes('<script>'));
    assert(html.includes('&lt;script&gt;'));
    assert(!html.includes('<img src=x>'));
    assert(html.includes('&lt;img src=x&gt;'));
    assert(html.includes('&lt;b&gt;2026-08&lt;/b&gt;'));
  });

  // --- 8) 較舊期備註 ---
  await test('較舊期備註：expectedPeriod != period 時顯示', () => {
    const s = mkCtx();
    const { render } = s.window.__fundInternals;
    const html = render({
      market: 'TW',
      revenue: {
        period: '11507', periodLabel: '2026-07',
        monthRev: 100000, unitMultiplier: 1000,
        yoyPct: 0, momPct: 0, cumYoyPct: 0,
        expectedPeriod: '2026-08', priorPeriod: true,
      },
    });
    assert(html.includes('最近完整月份為 2026-08'));
    assert(html.includes('目前取得較舊期 2026-07'));
    assert(!html.includes('較舊期 true'));
    assert(!/PIT/i.test(html), '不聲稱 PIT');
  });

  // --- 9) 快取 TTL ---
  await test('快取 TTL：完整 300s、缺值 60s、伺服器 cacheTtlSeconds 更短才取代', () => {
    const s = mkCtx();
    const I = s.window.__fundInternals;
    const now = 10000000;
    I.writeCache('AAA|TW', { revenue: { monthRev: 1, yoyPct: 1 } }, now);
    assert.strictEqual(I._getCache()['AAA|TW'].expireAt - now, I.CACHE_FULL_MS);

    I.writeCache('BBB|TW', { revenue: null, income: null, _note: 'x' }, now);
    assert.strictEqual(I._getCache()['BBB|TW'].expireAt - now, I.CACHE_PARTIAL_MS);

    I.writeCache('CCC|TW', { revenue: { monthRev: 1, yoyPct: 1 } }, now, 15);
    assert.strictEqual(I._getCache()['CCC|TW'].expireAt - now, 15 * 1000);

    // server TTL 比上限更長時，仍以 300s 為上限（不被延長）
    I.writeCache('DDD|TW', { revenue: { monthRev: 1, yoyPct: 1 } }, now, 10000);
    assert.strictEqual(I._getCache()['DDD|TW'].expireAt - now, I.CACHE_FULL_MS);
  });

  await test('快取過期：readCache 回 null，允許重試', () => {
    const s = mkCtx();
    const I = s.window.__fundInternals;
    const now = 1000000;
    I.writeCache('K|TW', { revenue: { monthRev: 1, yoyPct: 1 } }, now, 2);
    assert(I.readCache('K|TW', now + 1000));
    assert.strictEqual(I.readCache('K|TW', now + 3000), null);
  });

  // --- 10) 併發 inflight ---
  await test('inflight：同 sym 併發 fetch 僅觸發一次', async () => {
    let n = 0;
    const s = mkCtx({
      fetch: async () => {
        n++;
        await wait(10);
        return { ok: true, json: async () => ({ revenue: { monthRev: 1, unitMultiplier: 1000 } }) };
      },
    });
    const p1 = s.window.fetchFund('2330', 'TW');
    const p2 = s.window.fetchFund('2330', 'TW');
    const [a, b] = await Promise.all([p1, p2]);
    assert.strictEqual(n, 1, 'fetch 應僅觸發一次');
    assert.strictEqual(a, b);
  });

  // --- 11) 失敗不污染快取（可重試） ---
  await test('fetch 失敗不污染快取：下次仍可重試', async () => {
    let n = 0;
    const s = mkCtx({
      fetch: async () => { n++; return { ok: false, status: 500, json: async () => null }; },
    });
    const a = await s.window.fetchFund('XXX', 'TW');
    assert.strictEqual(a, null);
    const b = await s.window.fetchFund('XXX', 'TW');
    assert.strictEqual(b, null);
    assert.strictEqual(n, 2, '失敗後應允許下一次重試');
  });

  // --- 12) A→B→A 過時回應不覆蓋 ---
  await test('A→B→A：過時 renderStats 回應不覆蓋當前 symbol', async () => {
    const resolvers = {};
    const s = mkCtx({
      fetch: async (url) => {
        const sym = decodeURIComponent(url.split('/fundamental/')[1].split('?')[0]);
        return new Promise(res => {
          resolvers[sym] = () => res({
            ok: true,
            json: async () => ({
              market: 'TW',
              revenue: {
                period: '11508', periodLabel: 'P-' + sym,
                monthRev: 123, unitMultiplier: 1000,
                yoyPct: 1, momPct: 1, cumYoyPct: 1,
              },
            }),
          });
        });
      },
    });
    // 代次 1：A
    s.window.S = { sym: 'A', mkt: 'TW', tab: 'stats' };
    s.window.renderStats();
    // 代次 2：B
    s.window.S = { sym: 'B', mkt: 'TW', tab: 'stats' };
    s.window.renderStats();
    // 代次 3：A（最新）
    s.window.S = { sym: 'A', mkt: 'TW', tab: 'stats' };
    s.window.renderStats();

    // 讓 B（代次 2）先回應 → 應被 _fLastReq.seq 檢查擋下
    if (resolvers['B']) resolvers['B']();
    await wait(5);
    // A（代次 1 與 代次 3 共用 inflight promise；只回一次）
    if (resolvers['A']) resolvers['A']();
    await wait(5);

    const last = s.window.__fundInternals._getLastReq();
    assert.strictEqual(last.sym, 'A', '_fLastReq 應停在 A');
    assert.strictEqual(last.seq, 3, '_fLastReq.seq 應為 3');
    assert(!s.panel.innerHTML.includes('P-B'), '不應將 B 的回應寫入 DOM');
    assert(s.panel.innerHTML.includes('P-A'), '最新 A 的成功回應必須確實呈現');
  });

  console.log(`\n結果：通過 ${pass}，失敗 ${fail}`);
  if (fail) process.exit(1);
})();

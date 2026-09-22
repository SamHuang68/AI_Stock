'use strict';

// 離線幾何驗證：執行正式樣式函式，所有網路要求一律阻擋。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
function css(file, end) {
  const source = fs.readFileSync(path.join(root, 'src/ui', file), 'utf8');
  const start = source.indexOf('  function injectCSS() {');
  const style = {};
  const context = { $: () => style };
  vm.createContext(context);
  vm.runInContext(source.slice(start, source.indexOf(end, start)) + '\ninjectCSS();', context);
  return style.textContent;
}
const visual = fs.readFileSync(path.join(root, 'src/ui/visual_system_v5.js'), 'utf8').match(/var CSS = `([\s\S]*?)`;/)[1];
const styles = css('shell_v5.js', '  function stubHTML(') + css('pulse_v5.js', '  function tw(') + visual;
const card = (_, i) => `<section class="pl-sec"><h4><span class="pl-sec-title-text">${i + 1} 市場趨勢與完整標題</span><a>查看詳細分析</a></h4>
  <div class="pl-inst4">${['外資買賣超', '投信買賣超', '成交金額', '最新收盤'].map(k => `<div class="c"><div class="k">${k}</div><span class="v">123456.78</span></div>`).join('')}</div>
  <div class="pl-inst-cmt">分析前提：採用最近交易日的歷史資料，完整說明不應被裁切或遮蔽。</div>
  <div class="pl-fill">${'<p>長內容可捲動閱讀，保留每一筆資訊。</p>'.repeat(12)}</div></section>`;
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  try {
    const context = await browser.newContext({ isMobile: true, hasTouch: true });
    await context.route('**/*', route => route.abort());
    const page = await context.newPage();
    const results = [];
    for (const [width, height, columns] of [[844,390,5], [667,375,5], [932,430,5], [393,852,2], [844,390,5]]) {
      await page.setViewportSize({ width, height });
      if (!results.length) await page.setContent(`<html class="st-vs5"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
        *{box-sizing:border-box}html,body{margin:0;height:100%}#app,#shell-main,#shell-views{height:100%;min-height:0}
        ${styles}</style></head><body><div id="app"><div id="shell-main"><div id="shell-views" class="show">
        <div id="view-pulse" class="sv-panel on"><div id="mount-pulse" class="sv-mount"><div id="pl-root">
        <div class="pl-head"><div class="pl-head-start">市場總覽</div><div class="pl-head-end">專業模式</div></div>
        <div id="pl-body" class="pl-mode-expert"><div class="pl-dash"><div class="pl-zone">${Array.from({length:5}, card).join('')}</div>
        <div class="pl-zone">${Array.from({length:5}, card).join('')}</div></div></div></div></div></div></div></div></div></body></html>`);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const result = await page.evaluate(() => {
        const zones = [...document.querySelectorAll('.pl-zone')];
        const cards = [...document.querySelectorAll('.pl-sec')];
        const text = [...document.querySelectorAll('.pl-sec h4,.c .v,.pl-inst-cmt')];
        return {
          columns: zones.map(z => getComputedStyle(z).gridTemplateColumns.split(' ').length),
          overflow: cards.some(c => c.scrollWidth > c.clientWidth + 1),
          clippedText: text.some(t => t.scrollWidth > t.clientWidth + 1 || t.scrollHeight > t.clientHeight + 1),
          pageOverflow: document.documentElement.scrollWidth > innerWidth,
          bottom: Math.max(...cards.map(c => c.getBoundingClientRect().bottom)),
          scrollable: cards.every(c => c.scrollHeight > c.clientHeight || c.querySelector('.pl-fill').scrollHeight > c.querySelector('.pl-fill').clientHeight)
        };
      });
      if (result.clippedText) console.log(width, height, await page.locator('.pl-sec h4,.c .v,.pl-inst-cmt').evaluateAll(nodes => nodes.filter(t => t.scrollWidth > t.clientWidth + 1 || t.scrollHeight > t.clientHeight + 1).map(t => ({ tag: t.outerHTML, width: t.clientWidth, height: t.clientHeight, scrollWidth: t.scrollWidth, scrollHeight: t.scrollHeight }))));
      assert.deepEqual(result.columns, [columns, columns], `${width}×${height} 欄數`);
      assert.equal(result.overflow, false, '卡片文字不可橫向溢出');
      assert.equal(result.clippedText, false, '標題、數字及分析前提不可裁切');
      assert.equal(result.pageOverflow, false, '頁面不可橫向溢出');
      assert.equal(result.scrollable, true, '長內容可捲動');
      if (columns === 5) assert.ok(result.bottom <= height + 1, '上下兩排應完整位於視窗內');
      results.push({ width, height, ...result });
    }
    console.log(JSON.stringify(results, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

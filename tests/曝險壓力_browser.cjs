'use strict';
// 固定資料只送入正式 decisionData 入口；不讀使用者儲存、不連外、不複製產品渲染函式。
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict'), crypto = require('node:crypto');
const { chromium } = require(process.env.ST_PLAYWRIGHT || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.ST_BROWSER_OUTPUT || path.join(root, 'scratch', '曝險壓力驗收'));
const source = fs.readFileSync(path.join(root, 'src/ui/decision_v5.js'), 'utf8');
const deliveredHtml = fs.readFileSync(path.join(root, 'stock_terminal_v2.html'), 'utf8');
assert.equal([...deliveredHtml.matchAll(/<script src="src\/ui\/decision_v5\.js\?v=[0-9a-f]+"><\/script>/g)].length, 1,
  '正式產物必須載入唯一曝險評估元件');
const report = { fixtureOnly: true, sourceSha256: crypto.createHash('sha256').update(source).digest('hex'), checks: [], pageErrors: [] };
const components = [
  { key: 'volatility', score: 0, tone: 'cool', quality: 'ready', detail: '短期與模型波動比較', periodLabel: '2026-09-15～2026-10-13；最近 20 交易日' },
  { key: 'margin', score: 100, tone: 'hot', quality: 'partial', qualityNote: '現有 38 筆；52 週資料品質門檻至少 200 筆且覆蓋 330 天，並非市場風險門檻', detail: '現有樣本百分位 100', periodLabel: '2026-08-13～2026-10-12；38 筆／目標 52 週' },
  { key: 'leverage', score: 70, tone: 'watch', quality: 'review_due', qualityNote: '月度模型複查期限已過', detail: '效率差僅供研究參考', periodLabel: '月度模型 2026-09-01；複查期限 2026-10-01' },
  { key: 'portfolio', score: null, tone: 'unknown', quality: 'unknown', qualityNote: '未納入實際投組', detail: '未提供投組', periodLabel: '投組資料期間未知' }
];
const incomplete = { assessmentVersion: 1, score: 85, tone: 'hot', compositeScore: null, compositeTone: 'unknown', compositeState: '資料不足', rawWeightedScore: 48.6,
  quality: 'incomplete', qualityReasons: ['融資樣本不足', '月度模型待複查'], calculatedAt: '2026-10-13T09:00:00+08:00', scopeLabel: '市場分項；未含實際持倉', cadence: '日資料與月度模型；非盤中即時',
  conservativeConstraint: { score: 85, floor: 85, active: true, formula: '融資擁擠100×85%=85', drivers: [{ key: 'margin', score: 100, quality: 'partial' }] }, components };
const complete = structuredClone(incomplete);
Object.assign(complete, { quality: 'ready', qualityReasons: [], compositeScore: 48.6, compositeTone: 'steady', compositeState: '中性', scopeLabel: '市場分項；未含實際持倉' });
complete.components.filter(item => item.key !== 'portfolio').forEach(item => { item.quality = 'ready'; item.qualityNote = ''; });
complete.conservativeConstraint.drivers[0].quality = 'ready';
Object.assign(complete.components[1], { periodLabel: '2025-10-13～2026-10-13；252 筆、覆蓋 365 天／目標 52 週', detail: '52 週百分位 100' });
Object.assign(complete.components[2], { periodLabel: '月度模型 2026-10-01；複查期限 2026-11-01' });

const legacy = { score: 85, tone: 'hot', components: components.map(({ quality, qualityNote, periodLabel, ...item }) => item) };
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 375, height: 812 }]) {
      for (const [name, temperature] of [['不足樣本', incomplete], ['完整資料', complete], ['舊版回應', legacy]]) {
        const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
        page.setDefaultTimeout(10000);
        page.on('pageerror', error => report.pageErrors.push(error.message));
        await page.route('**/*', route => route.abort());
        await page.setContent('<style>html,body{margin:0;height:100%;--text:#d4deea;--thi:#edf5ff;--tlo:#8195ad;--border:#29405c;--bg2:#091321;--bg3:#102034;--gold:#facc15}#view-decision{height:100vh}</style><main id="view-decision" class="sv-panel on"></main>');
        await page.evaluate(() => {
          window.ShellV5 = { route: () => 'decision' };
          window.ST_PRIVATE_WEB_PROFILE = { role: 'reader' };
          window.fetch = async () => ({ ok: true, json: async () => ({ rows: [] }) });
        });
        await page.addScriptTag({ content: source });
        await page.evaluate(temperature => window.dispatchEvent(new CustomEvent('decisionData', { detail: { state: { context: {
          asOf: '2026-10-13T09:00:00+08:00', regime: { id: '等待確認', label: '固定市場情境' }, actionEnvelope: {}, evidence: [], exposureLab: { model: '固定研究模型', temperature }
        } } } })), temperature);
        const panel = page.locator('.dc-temp');
        await panel.scrollIntoViewIfNeeded();
        assert.match(await panel.innerText(), /曝險壓力 · 綜合評估/);
        assert.match(await panel.locator('.dc-temp-constraint').innerText(), /保守約束 85\/100/);
        assert.equal(await panel.locator('.dc-temp-score').innerText(), name === '完整資料' ? '48.6/100' : '—/100');
        assert.match(await panel.innerText(), /快照：2026-10-13T09:00:00\+08:00/);
        assert.match(await panel.innerText(), /日資料與月度模型；非盤中即時/);
        if (name === '不足樣本') {
          assert.match(await panel.innerText(), /融資擁擠100×85%=85/);
          assert.match(await panel.innerText(), /樣本不足/);
          assert.match(await panel.innerText(), /模型待複查/);
          assert.match(await panel.innerText(), /未納入實際投組/);
          assert.doesNotMatch(await panel.innerText(), /48\.6/);
        }
        if (name === '舊版回應') assert.match(await panel.innerText(), /資料說明待更新/);
        const periods = await panel.locator('.dc-temp-period').allTextContents();
        assert.deepEqual(periods, temperature.components.map(item => item.periodLabel || '資料期間未知'));
        for (const period of await panel.locator('.dc-temp-period').all()) {
          await period.scrollIntoViewIfNeeded();
          assert(await period.isVisible(), '分項期間必須可見');
          assert(await period.evaluate(node => {
            const box = node.getBoundingClientRect();
            return box.left >= 0 && box.right <= innerWidth + 1 && box.top >= 0 && box.bottom <= innerHeight + 1;
          }), '捲動後期間必須完整位於可視範圍');
        }
        const overflow = await panel.evaluate(node => [node, ...node.querySelectorAll('*')].filter(item => item.clientWidth && item.scrollWidth > item.clientWidth + 1).map(item => item.className));
        assert.deepEqual(overflow, [], '曝險資訊不得水平溢位或截斷');
        await panel.screenshot({ path: path.join(output, viewport.width + '-' + name + '.png') });
        report.checks.push({ viewport, scenario: name, periods, passed: true });
        await page.close();
      }
    }
    assert.deepEqual(report.pageErrors, []);
    console.log('通過：三種曝險資料情境、手機及桌面、完整期間與資訊溢位。');
  } finally {
    fs.writeFileSync(path.join(output, '結果.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

// UI 同條件對照工具（規則 0009「既有能力保全」第 4 條）。
//
// 用法：
//   node tests/ui_baseline_compare.cjs                      # origin/main 對工作樹
//   node tests/ui_baseline_compare.cjs --base <rev> --head <rev|WORKTREE>
//   node tests/ui_baseline_compare.cjs --routes heat,pulse --viewports 1440x900,390x844
//   node tests/ui_baseline_compare.cjs --self               # 同一版本對自己，驗證工具本身
//
// 兩個版本各自從 Git 取出並執行 build_v2.py，在相同的合成資料、固定時鐘、相同視窗下截圖。
// 所有對外請求一律攔下（不連網）；本機 API 只回 tests/fixtures/ui_baseline 的合成資料，
// 沒有 fixture 的端點回 {} 並列入報告。輸出在 scratch/ui-baseline/<run>/：兩版截圖、並排報告、JSON 收據。
// 判讀：相同，或有差異（附差異像素數與範圍，由人判讀是否為可接受的設計改善）。
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const synthetic = require('./fixtures/ui_baseline/synthetic.cjs');

const ROOT = path.resolve(__dirname, '..');
const ORIGIN = 'https://st-ui-baseline.test';
const CHART_LIB = path.join(__dirname, 'fixtures', 'lightweight-charts-4.2.0.js');
const STATIC_EXT = /\.(js|css|png|svg|jpg|jpeg|webp|gif|ico|woff2?|ttf|json|map)$/i;
const READY = {
  pulse: "document.querySelector('#pl-root') && document.querySelector('#pl-root').children.length > 0",
  decision: "document.querySelector('#dc-root')",
  heat: "document.querySelector('#ht-root .ht-grid')",
  chart: "document.querySelector('#chart-loading') && document.querySelector('#chart-loading').style.display === 'none'",
};

function parseArgs(argv) {
  const args = { base: 'origin/main', head: 'WORKTREE', routes: ['pulse', 'decision', 'heat', 'chart'],
    viewports: ['1440x900', '390x844'], self: false, settleMs: 1500, readyTimeoutMs: 12000 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], next = () => argv[++i];
    if (a === '--base') args.base = next();
    else if (a === '--head') args.head = next();
    else if (a === '--routes') args.routes = next().split(',').filter(Boolean);
    else if (a === '--viewports') args.viewports = next().split(',').filter(Boolean);
    else if (a === '--self') args.self = true;
    else throw new Error('未知參數：' + a);
  }
  for (const r of args.routes) if (!READY[r]) throw new Error('不支援的路由：' + r + '（可用：' + Object.keys(READY).join(', ') + '）');
  if (args.self) args.head = args.base;
  return args;
}

const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');
const git = (...a) => execFileSync('git', a, { cwd: ROOT, encoding: 'utf8' }).trim();

function prepareVersion(rev, workDir) {
  const isWorktree = rev === 'WORKTREE';
  const sha = isWorktree ? git('rev-parse', 'HEAD') : git('rev-parse', '--verify', rev + '^{commit}');
  const dir = path.join(workDir, isWorktree ? 'src-worktree' : 'src-' + sha.slice(0, 12));
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  if (isWorktree) {
    // 已追蹤與未追蹤（不含 .gitignore 排除）的檔案，反映工作樹目前內容；不寫回工作樹。
    const files = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], { cwd: ROOT })
      .toString('utf8').split('\0').filter(Boolean);
    for (const rel of files) {
      const src = path.join(ROOT, rel);
      if (!fs.existsSync(src) || !fs.statSync(src).isFile()) continue; // 已刪除的檔案
      fs.mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true });
      fs.copyFileSync(src, path.join(dir, rel));
    }
  } else {
    // 相對路徑解壓：GNU tar 會把「C:\…」當成遠端主機，Windows bsdtar 與 GNU tar 都接受相對檔名。
    const tarName = '.ui-baseline-src.tar';
    execFileSync('git', ['archive', '--format=tar', '-o', path.join(dir, tarName), sha], { cwd: ROOT });
    execFileSync('tar', ['-xf', tarName], { cwd: dir });
    fs.rmSync(path.join(dir, tarName), { force: true });
  }
  execFileSync(process.env.PYTHON || 'python', ['build_v2.py'], { cwd: dir, stdio: 'pipe' });
  const html = fs.readFileSync(path.join(dir, 'stock_terminal_v2.html'), 'utf8');
  return { rev, sha, dir, html, htmlSha256: sha256(html) };
}

async function capture(browser, version, label, route, viewport, opts, report, outDir) {
  const [width, height] = viewport.split('x').map(Number);
  const mobile = width <= 900;
  const context = await browser.newContext({ viewport: { width, height }, isMobile: mobile, hasTouch: mobile,
    reducedMotion: 'reduce', serviceWorkers: 'block', locale: 'zh-TW', timezoneId: 'Asia/Taipei' });
  await context.addInitScript(() => {
    localStorage.setItem('wizard_dismiss', JSON.stringify({ all: 1 }));
    // 固定亂數：產品內少數 ID／退避抖動使用 Math.random，固定後兩版行為一致。
    let seed = 20260115;
    Math.random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  });
  const page = await context.newPage();
  await page.clock.setFixedTime(new Date(synthetic.FIXED_EPOCH_MS));
  const entry = { version: label, route, viewport, ready: false, pageErrors: [] };
  page.on('pageerror', e => entry.pageErrors.push(e.message));
  await context.route('**/*', r => {
    const req = r.request(), url = new URL(req.url());
    if (url.origin !== ORIGIN) {
      if (url.href.includes('lightweight-charts@4.2.0/')) return r.fulfill({ path: CHART_LIB, contentType: 'application/javascript' });
      report.blocked.add(url.origin + url.pathname);
      return r.abort('blockedbyclient');
    }
    const file = decodeURIComponent(url.pathname.slice(1));
    if (file === '') return r.fulfill({ contentType: 'text/html; charset=utf-8', body: version.html });
    const abs = path.join(version.dir, file);
    if (req.method() === 'GET' && STATIC_EXT.test(file) && !file.startsWith('data/') && !file.includes('..')
        && fs.existsSync(abs) && fs.statSync(abs).isFile()) return r.fulfill({ path: abs });
    const hit = synthetic.respond(req.method(), url);
    if (!hit) report.unfixtured.add(req.method() + ' ' + url.pathname);
    return r.fulfill({ contentType: 'application/json; charset=utf-8', body: JSON.stringify(hit ? hit.json : {}) });
  });
  try {
    await page.goto(ORIGIN + '/#pulse', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('html.st5-booted', { state: 'attached', timeout: opts.readyTimeoutMs });
    await page.evaluate(r => { window.ShellV5.go(r); if (window.ShellV5.closeRing) window.ShellV5.closeRing(); }, route);
    await page.waitForFunction(READY[route], null, { timeout: opts.readyTimeoutMs });
    entry.ready = true;
  } catch (error) {
    entry.readyError = String(error.message || error).split('\n')[0];
  }
  await page.waitForTimeout(opts.settleMs);
  // 截圖不比較動態：停用動畫與轉場（兩版相同處理）；開機後才彈出的分析轉盤再關一次並確認已關閉。
  await page.addStyleTag({ content: '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}' });
  await page.evaluate(() => { if (window.ShellV5 && window.ShellV5.closeRing) window.ShellV5.closeRing(); });
  try {
    await page.waitForFunction(() => !document.querySelector('#st-ring.on'), null, { timeout: 5000 });
  } catch (error) {
    entry.ringError = '分析轉盤未關閉';
  }
  // 等畫面穩定：DOM 與所有 canvas 連續 4 次（每 300ms）沒有變化才截圖，最多再等 15 秒。
  entry.stable = await page.evaluate(async () => {
    const signature = () => {
      let text = document.body ? document.body.innerHTML : '';
      for (const c of document.querySelectorAll('canvas')) { try { text += c.toDataURL().length + ':' + c.width + 'x' + c.height; } catch (e) { text += 'tainted'; } }
      let h = 0; for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0;
      return h + ':' + text.length;
    };
    let last = signature(), same = 0;
    for (let waited = 0; waited < 15000; waited += 300) {
      await new Promise(r => setTimeout(r, 300));
      const now = signature();
      same = now === last ? same + 1 : 0; last = now;
      if (same >= 4) return true;
    }
    return false;
  });
  const file = path.join(outDir, label, `${route}-${viewport}.png`);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const png = await page.screenshot({ path: file });
  entry.file = path.relative(outDir, file).replace(/\\/g, '/');
  entry.sha256 = sha256(png);
  await context.close();
  return entry;
}

// 在瀏覽器 canvas 內比對像素（不新增依賴）。任一色版差距 > 16 計為差異像素。
// 不設容忍門檻：固定渲染參數後同一版本的截圖逐位元組相同，任何差異都交給人判讀，
// 避免把少量文字改動誤當成雜訊（實測一行標題改字只有約 0.03% 像素）。
async function pixelDiff(browser, pairs, outDir) {
  const context = await browser.newContext();
  const page = await context.newPage();
  for (const p of pairs) {
    if (p.verdict === 'unstable') continue;
    if (p.identical) { p.diffPixels = 0; p.verdict = 'identical'; continue; }
    const read = f => 'data:image/png;base64,' + fs.readFileSync(path.join(outDir, f)).toString('base64');
    const result = await page.evaluate(async ([a, b]) => {
      const load = src => new Promise((ok, fail) => { const img = new Image(); img.onload = () => ok(img); img.onerror = fail; img.src = src; });
      const [ia, ib] = await Promise.all([load(a), load(b)]);
      if (ia.width !== ib.width || ia.height !== ib.height) return { sizeMismatch: true, total: ia.width * ia.height, diff: ia.width * ia.height };
      const pixels = img => { const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
        const g = c.getContext('2d'); g.drawImage(img, 0, 0); return g.getImageData(0, 0, c.width, c.height).data; };
      const da = pixels(ia), db = pixels(ib);
      let diff = 0, x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
      for (let i = 0; i < da.length; i += 4) {
        if (Math.abs(da[i] - db[i]) > 16 || Math.abs(da[i + 1] - db[i + 1]) > 16 || Math.abs(da[i + 2] - db[i + 2]) > 16) {
          diff++; const n = i / 4, x = n % ia.width, y = (n - x) / ia.width;
          x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
        }
      }
      return { total: ia.width * ia.height, diff, box: diff ? [x0, y0, x1, y1] : null };
    }, [read(p.base.file), read(p.head.file)]);
    p.diffPixels = result.diff;
    p.diffBox = result.box || null;
    p.verdict = !result.sizeMismatch && result.diff === 0 ? 'identical' : 'different';
  }
  await context.close();
}

const VERDICT_LABEL = { identical: '相同', different: '有差異，請人工比對', unstable: '版本內不穩定（同一版本兩次截圖不同），不判讀' };

function reportHtml(receipt) {
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const rows = receipt.pairs.map(p => `<section><h2>${esc(p.route)} · ${esc(p.viewport)} · ${esc(VERDICT_LABEL[p.verdict] || p.verdict)}${p.diffPixels ? '（差異像素 ' + p.diffPixels + (p.diffBox ? '，範圍 ' + esc(p.diffBox.join(',')) : '') + '）' : ''}</h2>
<div class="pair"><figure><figcaption>基準 ${esc(receipt.base.rev)}（${esc(receipt.base.sha.slice(0, 12))}）${p.base.ready ? '' : ' · 未就緒：' + esc(p.base.readyError || '')}</figcaption><img src="${esc(p.base.file)}"></figure>
<figure><figcaption>候選 ${esc(receipt.head.rev)}（${esc(receipt.head.sha.slice(0, 12))}）${p.head.ready ? '' : ' · 未就緒：' + esc(p.head.readyError || '')}</figcaption><img src="${esc(p.head.file)}"></figure></div></section>`).join('\n');
  return `<!doctype html><meta charset="utf-8"><title>UI 同條件對照</title>
<style>body{font:14px system-ui;background:#0f172a;color:#e2e8f0;margin:16px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}
img{max-width:100%;border:1px solid #334155}figure{margin:0}h2{font-size:15px;margin:24px 0 8px}code{color:#93c5fd}</style>
<h1>UI 同條件對照（示意資料，非真實行情）</h1>
<p>固定時鐘 <code>${esc(receipt.fixedClock)}</code>；合成資料 SHA256 <code>${esc(receipt.fixturesSha256.slice(0, 16))}</code>；
攔下的對外請求 ${receipt.blocked.length} 筆；沒有 fixture 的端點 ${receipt.unfixtured.length} 個（回空物件，兩版相同）。</p>
${rows}`;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const runId = new Date().toISOString().replace(/[:.]/g, '-');
  const outDir = path.join(ROOT, 'scratch', 'ui-baseline', runId);
  const workDir = path.join(ROOT, 'scratch', 'ui-baseline', 'sources');
  fs.mkdirSync(outDir, { recursive: true });
  fs.mkdirSync(workDir, { recursive: true });

  const base = prepareVersion(opts.base, workDir);
  const head = opts.self ? base : prepareVersion(opts.head, workDir);
  const report = { blocked: new Set(), unfixtured: new Set() };
  // 固定渲染路徑，減少反鋸齒與光柵化雜訊。
  const browser = await chromium.launch({ headless: true, args: ['--disable-gpu', '--font-render-hinting=none',
    '--disable-lcd-text', '--force-color-profile=srgb', '--disable-partial-raster', '--force-device-scale-factor=1'] });
  const pairs = [];
  try {
    for (const route of opts.routes) {
      for (const viewport of opts.viewports) {
        // 每個版本截兩次：同一版本兩次不同代表頁面本身有競態，該組標為「版本內不穩定」不判讀。
        const b = await capture(browser, base, 'base', route, viewport, opts, report, outDir);
        const h = await capture(browser, head, 'head', route, viewport, opts, report, outDir);
        const b2 = await capture(browser, base, 'base-repeat', route, viewport, opts, report, outDir);
        const h2 = await capture(browser, head, 'head-repeat', route, viewport, opts, report, outDir);
        const unstable = [b.sha256 !== b2.sha256 && 'base', h.sha256 !== h2.sha256 && 'head'].filter(Boolean);
        pairs.push({ route, viewport, base: b, head: h, baseRepeat: b2, headRepeat: h2, unstableWithin: unstable,
          identical: b.sha256 === h.sha256, verdict: unstable.length ? 'unstable' : undefined });
      }
    }
    await pixelDiff(browser, pairs, outDir);
  } finally {
    await browser.close();
  }

  const fixtureFile = path.join(__dirname, 'fixtures', 'ui_baseline', 'synthetic.cjs');
  const receipt = {
    tool: 'tests/ui_baseline_compare.cjs', createdAt: new Date().toISOString(), fixtureOnly: true,
    fixedClock: synthetic.FIXED_AS_OF, fixturesSha256: sha256(fs.readFileSync(fixtureFile)),
    chartLibrarySha256: sha256(fs.readFileSync(CHART_LIB)),
    base: { rev: base.rev, sha: base.sha, htmlSha256: base.htmlSha256 },
    head: { rev: head.rev, sha: head.sha, htmlSha256: head.htmlSha256 },
    pairs, blocked: [...report.blocked].sort(), unfixtured: [...report.unfixtured].sort(),
  };
  fs.writeFileSync(path.join(outDir, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
  fs.writeFileSync(path.join(outDir, 'report.html'), reportHtml(receipt));

  const problems = pairs.flatMap(p => [p.base, p.head, p.baseRepeat, p.headRepeat]
    .filter(e => !e.ready || !e.stable || e.ringError || e.pageErrors.length)
    .map(e => `${e.version} ${p.route} ${p.viewport}: ${e.ready ? '' : '未就緒 ' + (e.readyError || '')}${e.stable ? '' : ' 畫面未穩定'}${e.ringError ? ' ' + e.ringError : ''}${e.pageErrors.length ? ' 頁面錯誤 ' + e.pageErrors.join(' | ') : ''}`));
  if (opts.self) {
    for (const p of pairs) if (p.verdict === 'different') problems.push(`自我對照 ${p.route} ${p.viewport} 截圖不一致（差異像素 ${p.diffPixels}，工具不穩定）`);
  }
  console.log(`報告：${path.relative(ROOT, path.join(outDir, 'report.html'))}`);
  const count = v => pairs.filter(p => p.verdict === v).length;
  for (const p of pairs.filter(x => x.verdict === 'unstable')) console.log(`版本內不穩定：${p.route} ${p.viewport}（${p.unstableWithin.join('、')}）— 頁面本身有競態，請另行調查`);
  console.log(`對照 ${pairs.length} 組；相同 ${count('identical')}、有差異 ${count('different')}、版本內不穩定 ${count('unstable')}；攔下對外請求 ${receipt.blocked.length} 筆；無 fixture 端點 ${receipt.unfixtured.length} 個`);
  if (problems.length) {
    console.error('問題：\n' + problems.map(s => '  - ' + s).join('\n'));
    process.exitCode = 1;
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
